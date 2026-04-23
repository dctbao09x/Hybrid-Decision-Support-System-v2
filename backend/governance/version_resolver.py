# backend/governance/version_resolver.py
"""
Version Resolver — Prompt-14 (Schema Hash + Version Trace + Artifact Chain)
============================================================================

Resolves the four canonical version dimensions for every decision response
so that **no response** can have an unknown lineage.

Version axes
------------
model_version    : Active production model from ModelRegistry (falls back to
                   DecisionController._model_version literal).
rule_version     : Deterministic fingerprint of the loaded rule set —
                   SHA-256 of ``RuleService.list_rules()`` sorted JSON body.
taxonomy_version : Deterministic fingerprint of the taxonomy dataset counts —
                   SHA-256 of ``TaxonomyManager.self_check()`` sorted JSON.
schema_version   : Fixed semver string "response-v4.0".  Increment when the
                   JSON schema of DecisionResponse changes.

schema_hash
-----------
SHA-256 of the concatenation of the four version strings (sorted by axis name)
to give frontend a single hash it can compare without parsing each field.

INVARIANTS
----------
* This module NEVER raises — every resolution error is swallowed and a safe
  fallback value is substituted so that the pipeline can still return a
  traceable (if degraded) response.
* All hashes are lowercase hex SHA-256.
* Resolutions are *not* cached so each call reflects live state.

USAGE (in decision_controller.run_pipeline)::

    from backend.governance.version_resolver import resolve_versions
    versions = resolve_versions(model_version_hint="v1.0.0")
    # Then pass versions.model_version, .rule_version, … into DecisionMeta
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("governance.version_resolver")

# ─── Constants ────────────────────────────────────────────────────────────────

#: Stable schema version — increment whenever DecisionResponse JSON schema changes.
RESPONSE_SCHEMA_VERSION = "response-v4.0"

_UNKNOWN = "unknown"


# ─── Data container ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VersionBundle:
    """
    Immutable snapshot of all four version axes for one decision.

    Attributes
    ----------
    model_version    : active ML model version string.
    rule_version     : SHA-256 fingerprint of the loaded rule set.
    taxonomy_version : SHA-256 fingerprint of the taxonomy dataset.
    schema_version   : fixed JSON schema semver string.
    schema_hash      : SHA-256 of the four version strings combined.
    resolved_at      : ISO-8601 UTC timestamp of resolution.
    """
    model_version:    str
    rule_version:     str
    taxonomy_version: str
    schema_version:   str
    schema_hash:      str
    resolved_at:      str

    def to_dict(self) -> Dict[str, str]:
        """Return a plain dict for embedding in API responses."""
        return {
            "model_version":    self.model_version,
            "rule_version":     self.rule_version,
            "taxonomy_version": self.taxonomy_version,
            "schema_version":   self.schema_version,
            "schema_hash":      self.schema_hash,
            "resolved_at":      self.resolved_at,
        }


# ─── Hash helpers ─────────────────────────────────────────────────────────────

def _sha256(obj: Any) -> str:
    """Return lowercase SHA-256 hex of the JSON-serialised *obj*."""
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_schema_hash(
    model_version: str,
    rule_version: str,
    taxonomy_version: str,
    schema_version: str,
) -> str:
    """
    Compute the combined schema hash — single fingerprint that the frontend
    can store and compare across responses.

    The hash is deterministic: it depends *only* on the four version strings.
    Sorting by axis name ensures that the ordering of arguments does not
    influence the output.

    Returns
    -------
    str
        Lowercase hex SHA-256.
    """
    axes = {
        "model_version":    model_version,
        "rule_version":     rule_version,
        "taxonomy_version": taxonomy_version,
        "schema_version":   schema_version,
    }
    return _sha256(axes)


# ─── Individual resolvers (each is fault-isolated) ───────────────────────────

def _resolve_model_version(hint: Optional[str]) -> str:
    """
    Return the active production model version.

    Resolution order:
    1. ModelRegistry.get_active() — live registry
    2. *hint* argument (e.g. DecisionController._model_version)
    3. "unknown"
    """
    try:
        from backend.ml.model_registry import get_model_registry  # noqa: PLC0415
        registry = get_model_registry()
        active = registry.get_active()
        if active:
            return active.version
    except Exception as exc:
        logger.debug("model_version resolution via registry failed: %s", exc)

    if hint and hint != _UNKNOWN:
        return hint
    return _UNKNOWN


def _resolve_rule_version() -> str:
    """
    Return the SHA-256 fingerprint of the currently loaded rule set.

    Takes the full rule list from RuleService, sorts by rule name for
    determinism, and hashes the result.
    """
    try:
        from backend.rule_engine.rule_service import RuleService  # noqa: PLC0415
        rules_raw = RuleService.list_rules(page_size=200).get("rules", [])
        # Sort by name for determinism across restarts
        key_data = sorted(
            [{"name": r.get("name", ""), "category": r.get("category", ""),
              "priority": r.get("priority", 0)} for r in rules_raw],
            key=lambda x: (x["category"], x["name"]),
        )
        rv = _sha256(key_data)[:16]  # 16-char prefix — human-readable
        logger.debug("rule_version resolved: %s (%d rules)", rv, len(rules_raw))
        return rv
    except Exception as exc:
        logger.debug("rule_version resolution failed: %s", exc)
        return _UNKNOWN


def _resolve_taxonomy_version() -> str:
    """
    Return the SHA-256 fingerprint of the taxonomy dataset counts.

    Uses ``TaxonomyManager.self_check()`` which returns ``{dataset: count}``.
    """
    try:
        from backend.api.routers.taxonomy_router import get_taxonomy_manager  # noqa: PLC0415
        mgr = get_taxonomy_manager()
        if mgr is None:
            return _UNKNOWN
        counts = mgr.self_check()
        tv = _sha256(counts)[:16]
        logger.debug("taxonomy_version resolved: %s", tv)
        return tv
    except Exception as exc:
        logger.debug("taxonomy_version resolution failed: %s", exc)
        return _UNKNOWN


# ─── Public API ───────────────────────────────────────────────────────────────

def resolve_versions(
    model_version_hint: Optional[str] = None,
) -> VersionBundle:
    """
    Resolve all four version axes and compute the combined schema_hash.

    This function is the **single source of truth** for version metadata in
    every decision response.  It is fault-tolerant — if any axis resolution
    fails, the axis falls back to "unknown" and resolution continues.

    Parameters
    ----------
    model_version_hint:
        Fallback model version string (e.g. ``self._model_version`` from
        ``DecisionController``). Used if the ModelRegistry is unavailable.

    Returns
    -------
    VersionBundle
        Immutable bundle of all four versions + schema_hash.
    """
    mv = _resolve_model_version(model_version_hint)
    rv = _resolve_rule_version()
    tv = _resolve_taxonomy_version()
    sv = RESPONSE_SCHEMA_VERSION

    sh = compute_schema_hash(mv, rv, tv, sv)
    resolved_at = datetime.now(timezone.utc).isoformat()

    logger.info(
        "VersionBundle resolved: model=%s rule=%s taxonomy=%s schema=%s hash=%s",
        mv, rv, tv, sv, sh[:16] + "…",
    )

    return VersionBundle(
        model_version=mv,
        rule_version=rv,
        taxonomy_version=tv,
        schema_version=sv,
        schema_hash=sh,
        resolved_at=resolved_at,
    )

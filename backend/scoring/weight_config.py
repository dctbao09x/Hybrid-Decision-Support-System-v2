# backend/scoring/weight_config.py
"""
Canonical Sub-Score Weight Loader
==================================

Single source of truth for loading ``SubScoreWeights`` from the declarative
config file (``config/scoring.yaml``).

DESIGN CONTRACT
---------------
* Configuration is read from ``config/scoring.yaml`` → ``sub_score_weights``.
* All five components are **mandatory** — no component may be absent or None.
* ``sum(weights) == 1.0`` is enforced at load time (tolerance 1e-6).
* **No environment variables** affect weight values.  Any env-based override is
  rejected by design.
* Returns a plain ``Dict[str, float]`` to avoid a circular import with
  ``sub_scorer.py`` (which defines ``SubScoreWeights``).  Callers convert this
  dict to ``SubScoreWeights(**d)`` after import.

PROHIBITED
----------
* os.environ.get() for weight values
* Runtime mutation of loaded weights
* Partial weight blocks (all five components are required)

USAGE
-----
    from backend.scoring.weight_config import load_sub_score_weight_dict
    weights_dict = load_sub_score_weight_dict()
    # → {"skill": 0.30, "experience": 0.25, "education": 0.20,
    #    "goal_alignment": 0.15, "preference": 0.10}
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

# Canonical path — relative to workspace root.
# weight_config.py lives at backend/scoring/weight_config.py
# scoring.yaml lives at config/scoring.yaml  → three parents up from this file.
_WORKSPACE_ROOT: Path = Path(__file__).resolve().parents[2]  # backend/scoring → backend → workspace
_SCORING_YAML: Path = _WORKSPACE_ROOT / "config" / "scoring.yaml"

# The authoritative key inside scoring.yaml.
_BLOCK_KEY: str = "sub_score_weights"

# Canonical component names — must match SubScoreWeights.COMPONENTS exactly.
_COMPONENTS: tuple[str, ...] = (
    "skill",
    "experience",
    "education",
    "goal_alignment",
    "preference",
)

# Tolerance for sum(weights) == 1.0 (mirrors SubScoreWeights.validate).
_SUM_TOLERANCE: float = 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def load_sub_score_weight_dict(
    config_path: Path | None = None,
) -> Dict[str, float]:
    """
    Load the ``sub_score_weights`` block from ``config/scoring.yaml``.

    Parameters
    ----------
    config_path:
        Override the default path to ``scoring.yaml``.  Intended for tests
        that supply an isolated fixture file.  Production callers must NOT
        supply this argument.

    Returns
    -------
    Dict[str, float]
        ``{"skill": w, "experience": w, "education": w,
           "goal_alignment": w, "preference": w}`` with all values ≥ 0
        and sum == 1.0 (± 1e-6).

    Raises
    ------
    FileNotFoundError
        If ``scoring.yaml`` does not exist at the resolved path.
    KeyError
        If the ``sub_score_weights`` block is missing or a component is absent.
    ValueError
        If any weight is negative or ``sum(weights)`` deviates from 1.0 by
        more than ``_SUM_TOLERANCE``.
    ImportError
        If PyYAML is not installed.
    """
    try:
        import yaml  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "PyYAML is required for weight config loading.  "
            "Install it with: pip install pyyaml"
        ) from exc

    path = config_path or _SCORING_YAML

    if not path.exists():
        raise FileNotFoundError(
            f"scoring.yaml not found at '{path}'.  "
            f"The sub_score_weights block is required for Stage 9 scoring."
        )

    with open(path, "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)

    if not isinstance(config, dict) or _BLOCK_KEY not in config:
        raise KeyError(
            f"'{_BLOCK_KEY}' block is missing from '{path}'.  "
            f"Add it with all five components: {list(_COMPONENTS)}"
        )

    raw: dict = config[_BLOCK_KEY]

    # ── Completeness check ─────────────────────────────────────────────────
    missing = [c for c in _COMPONENTS if c not in raw]
    if missing:
        raise KeyError(
            f"sub_score_weights is missing components: {missing}.\n"
            f"All five components are mandatory: {list(_COMPONENTS)}"
        )

    # ── Build and validate ─────────────────────────────────────────────────
    weights: Dict[str, float] = {}
    for c in _COMPONENTS:
        val = raw[c]
        try:
            val = float(val)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"sub_score_weights.{c} = {val!r} is not a valid float."
            ) from exc

        if val < 0.0:
            raise ValueError(
                f"sub_score_weights.{c} = {val} is negative; "
                "all weights must be >= 0."
            )
        weights[c] = val

    _validate_sum(weights)

    logger.debug(
        "[weight_config] sub_score_weights loaded from %s: %s",
        path.name, {k: round(v, 6) for k, v in weights.items()},
    )
    return weights


def validate_weights_dict(weights: Dict[str, float]) -> None:
    """
    Validate a ``{component: weight}`` dict against the weight integrity rules.

    Rules
    -----
    1. All five canonical components are present.
    2. All values are non-negative floats.
    3. ``sum(values) == 1.0`` within ``_SUM_TOLERANCE``.

    Raises
    ------
    KeyError
        If a canonical component is absent.
    ValueError
        If any value is negative or the sum deviates from 1.0.
    """
    missing = [c for c in _COMPONENTS if c not in weights]
    if missing:
        raise KeyError(f"Weight dict missing components: {missing}")

    for c in _COMPONENTS:
        if weights[c] < 0.0:
            raise ValueError(
                f"weights[{c!r}] = {weights[c]} is negative."
            )

    _validate_sum(weights)


def _validate_sum(weights: Dict[str, float]) -> None:
    """Assert sum(weights) == 1.0 within ``_SUM_TOLERANCE``."""
    total = sum(weights[c] for c in _COMPONENTS)
    if abs(total - 1.0) > _SUM_TOLERANCE:
        detail = "  +  ".join(f"{c}={weights[c]:.8f}" for c in _COMPONENTS)
        raise ValueError(
            f"sub_score_weights must sum to 1.0, got {total:.10f}.\n"
            f"  {detail}\n"
            f"  tolerance = {_SUM_TOLERANCE:.0e}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# DETERMINISM PROOF HELPER
# ─────────────────────────────────────────────────────────────────────────────

def get_weight_resolution_source() -> str:
    """
    Return a human-readable description of where weights are resolved from.

    Used by the integrity test to prove deterministic weight resolution.

    Returns
    -------
    str
        One of:
          "config:scoring.yaml"  — weights loaded from the canonical file
          "hardcoded:defaults"   — fallback defaults (tests / dev only)
    """
    path = _SCORING_YAML
    if path.exists():
        try:
            import yaml  # type: ignore[import]
            with open(path, "r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh)
            if isinstance(cfg, dict) and _BLOCK_KEY in cfg:
                return f"config:{path.name}"
        except Exception:
            pass
    return "hardcoded:defaults"


__all__ = [
    "load_sub_score_weight_dict",
    "validate_weights_dict",
    "get_weight_resolution_source",
    "_COMPONENTS",
    "_SUM_TOLERANCE",
]

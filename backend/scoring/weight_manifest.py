# backend/scoring/weight_manifest.py
"""
Immutable Weight Manifest
=========================

DETERMINISTIC SCORING HARDENING — ENV REMOVAL + MANIFEST ENFORCEMENT

This module provides an immutable, self-verifying manifest for weight
configuration.  All weight-related configuration is read ONCE at
module load time from manifest.json.  No environment variables affect
scoring weights.

INVARIANTS:
- Weight version is read-only after module load
- Validation mode is always STRICT (production-only)
- manifest.locked MUST be True — any other value aborts startup
- checksum_manifest_file is verified at read time (canonical SHA256)
- Any attempt to override at runtime raises RuntimeError

MANIFEST SCHEMA (backend/scoring/weights/manifest.json):
    active_version          str   — weight artifact version ID
    weights_path            str   — relative path to weights.json
    sha256                  str   — SHA256 of the weights file itself
    internal_checksum       str   — SHA256 of the weights dict
    locked                  bool  — MUST be true; false aborts loading
    created_at              str   — ISO8601 creation timestamp
    checksum_manifest_file  str   — canonical SHA256 of manifest content
                                    (all fields except checksum_manifest_file)

PROHIBITED:
- os.environ.get() for weight configuration
- Runtime version switching
- Dynamic validation mode changes
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Final, Optional

logger = logging.getLogger("scoring.weight_manifest")

# Registry path - single source of truth
_REGISTRY_PATH: Final[Path] = Path(__file__).resolve().parent / "weights" / "registry.json"
_ACTIVE_WEIGHTS_PATH: Final[Path] = Path(__file__).resolve().parent.parent / "models" / "weights" / "active" / "weights.json"

# Manifest path — single file, filesystem read-only
_MANIFEST_PATH: Final[Path] = Path(__file__).resolve().parent / "weights" / "manifest.json"

# Fields that are hashed to produce checksum_manifest_file.
# MUST NOT include "checksum_manifest_file" itself (self-referential).
_CANONICAL_FIELDS: Final[tuple] = (
    "active_version",
    "weights_path",
    "sha256",
    "internal_checksum",
    "locked",
    "created_at",
    "_comment",
)


def _compute_canonical_hash(manifest_dict: Dict[str, Any]) -> str:
    """
    Compute the canonical SHA256 of a manifest dict.

    Algorithm:
        1. Build an ordered sub-dict of _CANONICAL_FIELDS only
        2. Serialise with json.dumps(sort_keys=False, indent=2) + newline
        3. Return sha256(bytes)

    The canonical representation is identical to what is written on disk
    when manifest.json is created: json.dumps(..., indent=2) + "\\n".
    """
    canonical: Dict[str, Any] = {k: manifest_dict[k] for k in _CANONICAL_FIELDS if k in manifest_dict}
    raw = (json.dumps(canonical, indent=2) + "\n").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

# Manifest lock for thread safety during initialization
_manifest_lock = Lock()
_manifest_initialized: bool = False


# Required fields — any missing field aborts startup.
# These are the JSON key names in manifest.json.
_REQUIRED_MANIFEST_FIELDS: Final[tuple] = (
    "active_version",
    "weights_path",
    "sha256",          # weights file hash (mapped to WeightManifest.checksum)
    "locked",
    "checksum_manifest_file",
)


@dataclass(frozen=True)
class WeightManifest:
    """
    Immutable, self-verifying weight manifest.

    All fields are read-only after creation (frozen=True).

    Fields
    ------
    active_version          — weight artifact version ID
    validation_mode         — always "STRICT"; no runtime override
    weights_path            — relative path to weights.json
    checksum                — SHA256 of the weights file (sha256 field)
    locked                  — MUST be True; False is a manifest violation
    checksum_manifest_file  — canonical SHA256 of all manifest fields
                              except checksum_manifest_file itself
    """
    active_version: str
    validation_mode: str          # Always "STRICT" in production
    weights_path: str
    checksum: str                 # SHA256 of weights file (manifest sha256)
    locked: bool                  # MUST be True
    checksum_manifest_file: str   # Canonical SHA256 of manifest content

    def __post_init__(self) -> None:
        """Enforce all manifest invariants immediately on construction."""
        if not self.active_version:
            raise RuntimeError("[MANIFEST] INVARIANT VIOLATION: active_version is required")
        if not self.weights_path:
            raise RuntimeError("[MANIFEST] INVARIANT VIOLATION: weights_path is required")
        if not self.checksum:
            raise RuntimeError("[MANIFEST] INVARIANT VIOLATION: checksum (weights file SHA256) is required")
        if not self.checksum_manifest_file:
            raise RuntimeError("[MANIFEST] INVARIANT VIOLATION: checksum_manifest_file is required")
        if self.locked is not True:
            raise RuntimeError(
                f"[MANIFEST] INVARIANT VIOLATION: manifest.locked is {self.locked!r}. "
                f"Manifest MUST be locked=true. Scoring ABORTED."
            )
        if self.validation_mode != "STRICT":
            logger.warning(
                f"[MANIFEST] validation_mode is {self.validation_mode!r}; "
                f"production requires STRICT"
            )


# Module-level singleton
_manifest: Optional[WeightManifest] = None


def _load_manifest_from_files() -> WeightManifest:
    """
    Load and strictly validate manifest.json.

    Steps
    -----
    1. Read manifest.json bytes and parse JSON.
    2. Verify all required fields are present — missing field → RuntimeError.
    3. Verify manifest.locked is True — False → RuntimeError.
    4. Verify checksum_manifest_file:
           expected = sha256(canonical fields serialised as stored)
           if mismatch → RuntimeError (file tampered or fields changed)
    5. Build and return frozen WeightManifest.

    This is called ONCE at module initialization and never again.
    """
    manifest_path = _MANIFEST_PATH
    if not manifest_path.exists():
        raise RuntimeError(
            f"[MANIFEST] manifest.json not found: {manifest_path}. "
            f"System cannot start without a valid weight manifest."
        )

    # ── Step 1: Parse ────────────────────────────────────────────────────────
    try:
        raw_text = manifest_path.read_text(encoding="utf-8")
        data: Dict[str, Any] = json.loads(raw_text)
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"[MANIFEST] Failed to read manifest.json: {exc}") from exc

    # ── Step 2: Required fields ───────────────────────────────────────────────
    missing = [f for f in _REQUIRED_MANIFEST_FIELDS if f not in data]
    if missing:
        raise RuntimeError(
            f"[MANIFEST] STARTUP ABORTED — missing required field(s): {missing}. "
            f"Manifest: {manifest_path}"
        )

    # ── Step 3: locked ───────────────────────────────────────────────────────
    if data["locked"] is not True:
        raise RuntimeError(
            f"[MANIFEST] STARTUP ABORTED — manifest.locked={data['locked']!r}. "
            f"Manifest MUST be locked=true. "
            f"Weight changes require a new training pipeline run and CI deployment."
        )

    # ── Step 4: checksum_manifest_file verification ───────────────────────────
    stored_cmf = data["checksum_manifest_file"]
    computed_cmf = _compute_canonical_hash(data)
    if computed_cmf != stored_cmf:
        raise RuntimeError(
            f"[MANIFEST] STARTUP ABORTED — manifest.json has been tampered. "
            f"checksum_manifest_file mismatch:\n"
            f"  stored  : {stored_cmf}\n"
            f"  computed: {computed_cmf}\n"
            f"Restore manifest.json from a trusted source."
        )

    # ── Step 5: Build frozen dataclass ───────────────────────────────────────
    # Map manifest.sha256 → WeightManifest.checksum (weights file hash)
    manifest = WeightManifest(
        active_version=data["active_version"],
        validation_mode="STRICT",          # always STRICT — no ENV override
        weights_path=data["weights_path"],
        checksum=data["sha256"],
        locked=data["locked"],
        checksum_manifest_file=data["checksum_manifest_file"],
    )

    logger.info(
        f"[MANIFEST] Loaded and verified: "
        f"version={manifest.active_version} "
        f"locked={manifest.locked} "
        f"cmf={manifest.checksum_manifest_file[:16]}..."
    )

    return manifest


def get_manifest() -> WeightManifest:
    """
    Get the immutable weight manifest.
    
    Thread-safe lazy initialization.
    After first call, returns the same frozen manifest.
    """
    global _manifest, _manifest_initialized
    
    if not _manifest_initialized:
        with _manifest_lock:
            # Double-check locking
            if not _manifest_initialized:
                _manifest = _load_manifest_from_files()
                _manifest_initialized = True
    
    return _manifest


def load_active_weight_version() -> str:
    """
    Load active weight version from immutable manifest.
    
    This replaces os.environ.get("SIMGR_WEIGHTS_VERSION").
    
    Returns:
        str: The active weight version string.
        
    Raises:
        RuntimeError: If manifest cannot be loaded.
    """
    return get_manifest().active_version


def load_validation_mode() -> str:
    """
    Load validation mode from immutable manifest.
    
    This replaces os.environ.get("SIMGR_WEIGHT_VALIDATION_MODE").
    Always returns "STRICT" in production - no ENV override.
    
    Returns:
        str: "STRICT" (production mode).
    """
    return get_manifest().validation_mode


def assert_version_immutable(requested_version: Optional[str]) -> None:
    """
    Assert that runtime is not trying to override the weight version.
    
    Args:
        requested_version: Version requested by caller.
        
    Raises:
        RuntimeError: If requested_version differs from manifest.
    """
    if requested_version is None:
        return
    
    manifest = get_manifest()
    
    # Allow version match
    if requested_version == manifest.active_version:
        return
    
    # Block version override attempt
    raise RuntimeError(
        f"[MANIFEST] INVARIANT VIOLATION: Runtime version override blocked. "
        f"requested={requested_version} manifest={manifest.active_version}. "
        f"Weight version is immutable - modify registry.json and restart."
    )


def assert_no_env_override() -> None:
    """
    Assert that no ENV variables are affecting weight loading.
    
    This is a runtime safety check. Call during startup.
    
    Raises:
        RuntimeError: If scoring-related ENV variables are detected.
    """
    import os
    
    # ENV variables that are BLOCKED from affecting scoring
    blocked_env_vars = [
        "SIMGR_WEIGHTS_VERSION",
        "SIMGR_WEIGHT_VALIDATION_MODE",
    ]
    
    violations = []
    for var in blocked_env_vars:
        value = os.environ.get(var)
        if value is not None:
            violations.append(f"{var}={value}")
    
    if violations:
        raise RuntimeError(
            f"[MANIFEST] INVARIANT VIOLATION: Blocked ENV variables detected: "
            f"{', '.join(violations)}. "
            f"These ENV variables are deprecated and will be ignored. "
            f"Remove them from environment and use registry.json for configuration."
        )


# Eager initialization check (optional - can be called at startup)
def initialize() -> None:
    """
    Eagerly initialize the manifest and run safety checks.
    
    Call this at application startup to fail fast on configuration errors.
    """
    # Load manifest
    manifest = get_manifest()
    
    # Check for blocked ENV variables (warn but don't fail for backward compat)
    import os
    for var in ["SIMGR_WEIGHTS_VERSION", "SIMGR_WEIGHT_VALIDATION_MODE"]:
        if os.environ.get(var):
            logger.warning(
                f"[MANIFEST] DEPRECATION: ENV variable {var} is set but will be ignored. "
                f"Use registry.json for configuration."
            )
    
    logger.info(
        f"[MANIFEST] Initialization complete: "
        f"version={manifest.active_version} mode={manifest.validation_mode}"
    )

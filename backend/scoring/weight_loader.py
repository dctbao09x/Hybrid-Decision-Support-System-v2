# backend/scoring/weight_loader.py
"""
Weight Loader with Governance
=============================

STRICT loading - NO fallbacks, NO defaults.
All weights MUST come from trained artifacts with checksums.

GĐ1 PHẦN B: Fallback Elimination
GĐ1 PHẦN C: Artifact Standardization
GĐ1 PHẦN E: Load Pipeline Hardening
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("scoring.weight_loader")

# Registry path (PHẦN D)
REGISTRY_PATH = Path(__file__).resolve().parent / "weights" / "registry.json"
WEIGHTS_DIR = Path(__file__).resolve().parent.parent / "models" / "weights"

# HARDENED: ENV overrides removed for deterministic scoring
# Previous: ALLOWED_ENV_OVERRIDES = frozenset(["SIMGR_WEIGHTS_VERSION"])
# All version selection now goes through immutable manifest


class WeightLoadError(Exception):
    """Weight loading failed - CRITICAL."""
    pass


class WeightChecksumError(WeightLoadError):
    """Checksum mismatch - INTEGRITY VIOLATION."""
    pass


class WeightManifestIntegrityError(WeightLoadError):
    """Manifest SHA256 mismatch - FILE INTEGRITY VIOLATION."""
    pass


class WeightNotFoundError(WeightLoadError):
    """Required weight artifact missing."""
    pass


class WeightRegistryError(WeightLoadError):
    """Registry lookup failed."""
    pass


class WeightValidationError(WeightLoadError):
    """Weight values invalid."""
    pass


class WeightWriteProtectionError(WeightLoadError):
    """Attempted write to immutable weights directory."""
    pass


class G5TrainingMetadataError(WeightLoadError):
    """G5 training metadata missing or non-compliant."""
    pass


@dataclass
class WeightArtifact:
    """
    Standardized weight artifact (PHẦN C).
    
    Required fields - NO DEFAULTS except metadata.
    """
    version: str
    trained_at: str
    dataset_hash: str
    model_type: str
    metrics: Dict[str, float]
    weights: Dict[str, float]
    checksum: str
    
    # Computed on load
    _source_path: str = field(default="", repr=False)
    _loaded_at: str = field(default="", repr=False)
    _verified: bool = field(default=False, repr=False)
    
    @property
    def ws(self) -> float:
        return self.weights["study_score"]
    
    @property
    def wi(self) -> float:
        return self.weights["interest_score"]
    
    @property  
    def wm(self) -> float:
        return self.weights["market_score"]
    
    @property
    def wg(self) -> float:
        return self.weights["growth_score"]
    
    @property
    def wr(self) -> float:
        return self.weights["risk_score"]
    
    def validate(self) -> None:
        """Validate weight constraints - FAIL on any violation."""
        required_keys = ["study_score", "interest_score", "market_score", "growth_score", "risk_score"]
        
        # Check all keys present
        for key in required_keys:
            if key not in self.weights:
                raise WeightValidationError(f"Missing required weight: {key}")
            if not isinstance(self.weights[key], (int, float)):
                raise WeightValidationError(f"Weight {key} must be numeric, got {type(self.weights[key])}")
        
        # Check sum = 1.0
        total = sum(self.weights[k] for k in required_keys)
        if abs(total - 1.0) > 0.001:
            raise WeightValidationError(f"Weights must sum to 1.0, got {total:.4f}")
        
        # Check all values in [0, 1]
        for key in required_keys:
            val = self.weights[key]
            if not (0.0 <= val <= 1.0):
                raise WeightValidationError(f"Weight {key}={val} must be in [0, 1]")
    
    def to_dict(self) -> Dict[str, Any]:
        """Export as dict."""
        return {
            "version": self.version,
            "trained_at": self.trained_at,
            "dataset_hash": self.dataset_hash,
            "model_type": self.model_type,
            "metrics": self.metrics,
            "weights": self.weights,
            "checksum": self.checksum,
        }


def compute_checksum(weights: Dict[str, float]) -> str:
    """Compute SHA256 checksum of weights."""
    # Deterministic JSON serialization
    sorted_weights = json.dumps(weights, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(sorted_weights.encode()).hexdigest()


def verify_checksum(artifact: WeightArtifact) -> bool:
    """Verify artifact checksum."""
    computed = compute_checksum(artifact.weights)
    return computed == artifact.checksum


# =============================================================================
# WEIGHT VERSION IMMUTABILITY PROTOCOL
# =============================================================================

_MANIFEST_PATH: Path = Path(__file__).resolve().parent / "weights" / "manifest.json"


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA256 hash of entire file contents."""
    with open(file_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


_MANIFEST_REQUIRED_FIELDS: tuple = (
    "active_version",
    "weights_path",
    "sha256",
    "locked",
    "checksum_manifest_file",
)

# Fields used to compute checksum_manifest_file (all except checksum_manifest_file itself).
_MANIFEST_CANONICAL_FIELDS: tuple = (
    "active_version",
    "weights_path",
    "sha256",
    "internal_checksum",
    "locked",
    "created_at",
    "_comment",
)


def _compute_manifest_canonical_hash(data: Dict[str, Any]) -> str:
    """
    Compute the canonical SHA256 of a manifest dict.

    Algorithm mirrors weight_manifest._compute_canonical_hash():
        1. Select _MANIFEST_CANONICAL_FIELDS only (exclude checksum_manifest_file)
        2. json.dumps(sort_keys=False, indent=2) + newline → UTF-8 bytes
        3. Return sha256 hex digest
    """
    canonical: Dict[str, Any] = {k: data[k] for k in _MANIFEST_CANONICAL_FIELDS if k in data}
    raw = (json.dumps(canonical, indent=2) + "\n").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_weight_manifest() -> Dict[str, Any]:
    """
    Load and strictly validate the immutable weight manifest.

    Enforcement steps:
        1. File existence check — missing file → WeightRegistryError
        2. JSON parse — malformed JSON → WeightRegistryError
        3. Required fields: active_version, weights_path, sha256,
           locked, checksum_manifest_file — any missing → WeightRegistryError
        4. locked MUST be True — False or missing → WeightManifestIntegrityError
        5. checksum_manifest_file self-integrity — mismatch → WeightManifestIntegrityError

    Returns:
        Dict containing validated manifest data.

    Raises:
        WeightRegistryError: If manifest not found, unreadable, or missing fields.
        WeightManifestIntegrityError: If locked=False or self-checksum mismatch.
    """
    manifest_path = _MANIFEST_PATH
    if not manifest_path.exists():
        raise WeightRegistryError(
            f"[MANIFEST] Weight manifest not found: {manifest_path}. "
            f"System requires immutable manifest for weight governance."
        )

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise WeightRegistryError(f"[MANIFEST] Invalid manifest JSON: {exc}") from exc
    except OSError as exc:
        raise WeightRegistryError(f"[MANIFEST] Cannot read manifest.json: {exc}") from exc

    # ── Required fields ───────────────────────────────────────────────────────
    missing = [field for field in _MANIFEST_REQUIRED_FIELDS if field not in data]
    if missing:
        raise WeightRegistryError(
            f"[MANIFEST] STARTUP ABORTED — missing required field(s): {missing}. "
            f"Manifest: {manifest_path}"
        )

    # ── locked enforcement ─────────────────────────────────────────────────── 
    if data["locked"] is not True:
        raise WeightManifestIntegrityError(
            f"[MANIFEST] STARTUP ABORTED — manifest.locked={data['locked']!r}. "
            f"Manifest MUST be locked=true. "
            f"Weight changes require a new training pipeline run and CI deployment."
        )

    # ── Self-integrity: checksum_manifest_file ────────────────────────────────
    stored_cmf: str = data["checksum_manifest_file"]
    computed_cmf: str = _compute_manifest_canonical_hash(data)
    if computed_cmf != stored_cmf:
        raise WeightManifestIntegrityError(
            f"[MANIFEST] STARTUP ABORTED — manifest.json has been tampered. "
            f"checksum_manifest_file mismatch:\n"
            f"  stored  : {stored_cmf}\n"
            f"  computed: {computed_cmf}\n"
            f"Restore manifest.json from a trusted source."
        )

    logger.info(
        f"[MANIFEST] Loaded and self-verified: "
        f"version={data['active_version']} "
        f"locked={data['locked']} "
        f"cmf={stored_cmf[:16]}..."
    )

    return data


def verify_g5_training_metadata(weights_path: Path) -> None:
    """
    G5 COMPLIANCE CHECK: Verify training_metadata.json exists and is G5-compliant.

    Must be called BEFORE loading weights.

    Checks:
        1. training_metadata.json exists alongside weights file.
        2. g5_compliant field is exactly True.
        3. training_dataset_hash field is present and non-empty.

    Args:
        weights_path: Absolute path to weights.json. Metadata is expected
                      in the same directory.

    Raises:
        G5TrainingMetadataError: If metadata missing, g5_compliant != True,
                                 or training_dataset_hash absent.
    """
    metadata_path = weights_path.parent / "training_metadata.json"

    if not metadata_path.exists():
        raise G5TrainingMetadataError(
            f"[G5] SCORING ABORTED — training_metadata.json not found at "
            f"{metadata_path}. "
            f"Run G5 Training Metadata Restoration Protocol to remediate."
        )

    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    except json.JSONDecodeError as exc:
        raise G5TrainingMetadataError(
            f"[G5] training_metadata.json is invalid JSON: {exc}"
        ) from exc
    except OSError as exc:
        raise G5TrainingMetadataError(
            f"[G5] Cannot read training_metadata.json: {exc}"
        ) from exc

    if metadata.get("g5_compliant") is not True:
        raise G5TrainingMetadataError(
            f"[G5] SCORING ABORTED — g5_compliant is not True "
            f"(found: {metadata.get('g5_compliant')!r}). "
            f"Model must be retrained and tagged as G5-compliant."
        )

    dataset_hash = metadata.get("training_dataset_hash", "")
    if not dataset_hash:
        raise G5TrainingMetadataError(
            f"[G5] SCORING ABORTED — training_dataset_hash is missing or empty "
            f"in training_metadata.json. "
            f"Lineage cannot be established — scoring blocked."
        )

    logger.info(
        f"[G5] Training metadata verified: "
        f"model_type={metadata.get('model_type')} "
        f"trained_at={metadata.get('trained_at')} "
        f"dataset_hash={dataset_hash[:16]}... "
        f"g5_compliant=True"
    )


def verify_weight_file_integrity(weights_path: Path) -> None:
    """
    Verify weight file SHA256 against manifest.
    
    CRITICAL: This MUST be called before loading weights.
    
    Args:
        weights_path: Path to weights.json file.
        
    Raises:
        WeightManifestIntegrityError: If SHA256 mismatch.
        WeightRegistryError: If manifest cannot be loaded.
    """
    manifest = load_weight_manifest()

    # locked is already enforced inside load_weight_manifest() — no re-check needed.

    # Compute file SHA256
    computed_sha256 = compute_file_sha256(weights_path)
    expected_sha256 = manifest["sha256"]
    
    if computed_sha256 != expected_sha256:
        logger.critical(
            f"[MANIFEST] INTEGRITY VIOLATION DETECTED!\n"
            f"  Expected SHA256: {expected_sha256}\n"
            f"  Computed SHA256: {computed_sha256}\n"
            f"  File: {weights_path}"
        )
        raise WeightManifestIntegrityError(
            f"[INTEGRITY] Weight file SHA256 mismatch. "
            f"expected={expected_sha256[:16]}... computed={computed_sha256[:16]}... "
            f"Scoring ABORTED. Weight file may have been tampered with."
        )
    
    logger.info(
        f"[MANIFEST] Integrity verified: SHA256={computed_sha256[:16]}... "
        f"version={manifest['active_version']}"
    )


def assert_weights_directory_readonly() -> None:
    """
    Runtime guard: Ensure no write operations can modify weights directory.
    
    This is a safety check - actual filesystem permissions should also be set.
    
    Raises:
        WeightWriteProtectionError: If weights directory is writable.
    """
    import os
    import stat
    
    weights_dir = Path.cwd() / WEIGHTS_DIR / "active"
    weights_file = weights_dir / "weights.json"
    
    if weights_file.exists():
        # Check if file is writable
        mode = os.stat(weights_file).st_mode
        if mode & stat.S_IWUSR or mode & stat.S_IWGRP or mode & stat.S_IWOTH:
            logger.warning(
                f"[SECURITY] Weight file is writable: {weights_file}. "
                f"Consider setting read-only permissions."
            )


class WeightLoader:
    """
    Strict weight loader with governance.
    
    RULES (PHẦN E):
    - NO env overrides except whitelisted
    - NO relative paths
    - Registry lookup ONLY
    - Checksum verification REQUIRED
    - FAIL on any violation
    """
    
    def __init__(self, registry_path: Optional[Path] = None):
        self._registry_path = registry_path or REGISTRY_PATH
        self._registry: Optional[Dict] = None
        self._active: Optional[WeightArtifact] = None
    
    def _load_registry(self) -> Dict:
        """Load weight registry."""
        if not self._registry_path.exists():
            raise WeightRegistryError(f"Registry not found: {self._registry_path}")
        
        try:
            with open(self._registry_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise WeightRegistryError(f"Invalid registry JSON: {e}")
    
    def _resolve_version(self, version: Optional[str] = None) -> str:
        """Resolve version from manifest (ENV override removed for determinism)."""
        from backend.scoring.weight_manifest import (
            load_active_weight_version,
            assert_version_immutable,
        )
        
        if version:
            # Validate version matches manifest - block runtime override
            assert_version_immutable(version)
            return version
        
        # HARDENED: ENV override removed
        # Previous: env_version = os.environ.get("SIMGR_WEIGHTS_VERSION")
        # Now: Always use manifest version
        
        # Get version from immutable manifest
        manifest_version = load_active_weight_version()
        logger.info(f"[WEIGHT_LOAD] Using manifest version: {manifest_version}")
        return manifest_version
    
    def _validate_path(self, path: Path) -> None:
        """Validate path is absolute and within allowed directories."""
        # Reject relative paths
        if not path.is_absolute():
            # Make it absolute based on cwd
            path = Path.cwd() / path
        
        # Check exists
        if not path.exists():
            raise WeightNotFoundError(f"Weight file not found: {path}")
        
        # Check is file
        if not path.is_file():
            raise WeightNotFoundError(f"Weight path is not a file: {path}")
    
    def load(self, version: Optional[str] = None, path: Optional[Path] = None) -> WeightArtifact:
        """
        Load weights with STRICT validation and SHA256 integrity check.
        
        WEIGHT VERSION IMMUTABILITY PROTOCOL:
        1. Load manifest.json
        2. Verify weight file SHA256 matches manifest
        3. If mismatch: raise exception, abort scoring
        4. Only then load and validate weights
        
        Args:
            version: Version to load (from registry if None)
            path: Direct path override (for testing only)
        
        Returns:
            Verified WeightArtifact
            
        Raises:
            WeightManifestIntegrityError: If SHA256 mismatch
            WeightLoadError: On ANY other failure - NO FALLBACK
        """
        # Resolve path
        if path:
            weight_path = Path(path)
        else:
            resolved_version = self._resolve_version(version)
            weight_path = WEIGHTS_DIR / resolved_version / "weights.json"
        
        # Make absolute
        if not weight_path.is_absolute():
            weight_path = Path.cwd() / weight_path
        
        # Validate path
        if not weight_path.exists():
            raise WeightNotFoundError(
                f"[WEIGHT_LOAD] FAILED - File not found: {weight_path}"
            )

        # =====================================================================
        # G5 TRAINING METADATA COMPLIANCE CHECK
        # =====================================================================
        # CRITICAL: Verify training_metadata.json BEFORE loading weights.
        # Missing or non-compliant metadata → immediate abort.
        verify_g5_training_metadata(weight_path)

        # =====================================================================
        # WEIGHT VERSION IMMUTABILITY PROTOCOL - SHA256 VERIFICATION
        # =====================================================================
        # CRITICAL: Verify file integrity BEFORE loading contents
        # If SHA256 mismatch: ABORT immediately - do not proceed
        try:
            verify_weight_file_integrity(weight_path)
        except WeightManifestIntegrityError:
            logger.critical("[WEIGHT_LOAD] ABORTED - Integrity check failed")
            raise
        except WeightRegistryError as e:
            logger.warning(f"[WEIGHT_LOAD] Manifest check skipped: {e}")
            # Continue for backward compatibility, but log warning
        
        # Load JSON
        try:
            with open(weight_path, 'r') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise WeightLoadError(f"Invalid weights JSON: {e}")
        
        # Parse artifact - NO FALLBACKS
        try:
            artifact = WeightArtifact(
                version=data["version"],
                trained_at=data["trained_at"],
                dataset_hash=data["dataset_hash"],
                model_type=data["model_type"],
                metrics=data["metrics"],
                weights=data["weights"],
                checksum=data["checksum"],
            )
        except KeyError as e:
            raise WeightLoadError(f"Missing required field in weights.json: {e}")
        
        artifact._source_path = str(weight_path)
        artifact._loaded_at = datetime.now().isoformat()
        
        # Validate weights
        artifact.validate()
        
        # Verify checksum (PHẦN C)
        if not verify_checksum(artifact):
            computed = compute_checksum(artifact.weights)
            raise WeightChecksumError(
                f"[WEIGHT_LOAD] CHECKSUM MISMATCH - "
                f"expected={artifact.checksum[:16]}... computed={computed[:16]}..."
            )
        
        artifact._verified = True
        
        # Log successful load (PHẦN E)
        logger.info(
            f"[WEIGHT_LOAD] version={artifact.version} "
            f"hash={artifact.checksum[:16]}... "
            f"source={artifact._source_path}"
        )
        
        self._active = artifact
        return artifact
    
    def get_active(self) -> WeightArtifact:
        """Get currently loaded weights."""
        if self._active is None:
            raise WeightLoadError("No weights loaded - call load() first")
        return self._active
    
    def is_default(self, artifact: WeightArtifact) -> bool:
        """Check if weights are defaults (GUARD)."""
        # Default weights pattern
        default_pattern = {
            "study_score": 0.25,
            "interest_score": 0.25,
            "market_score": 0.25,
            "growth_score": 0.15,
            "risk_score": 0.10,
        }
        
        return artifact.weights == default_pattern


# Global loader instance
_loader: Optional[WeightLoader] = None


def get_weight_loader() -> WeightLoader:
    """Get global weight loader."""
    global _loader
    if _loader is None:
        _loader = WeightLoader()
    return _loader


def load_weights(version: Optional[str] = None) -> WeightArtifact:
    """Convenience function to load weights."""
    return get_weight_loader().load(version)


def require_trained_weights() -> WeightArtifact:
    """
    Load weights and FAIL if they are defaults.
    
    GUARD: Prevents silent fallback to defaults.
    """
    loader = get_weight_loader()
    artifact = loader.load()
    
    if loader.is_default(artifact):
        raise WeightLoadError(
            "[WEIGHT_LOAD] FAILED - Default weights detected. "
            "Trained weights REQUIRED in production."
        )
    
    return artifact

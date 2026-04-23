# backend/scoring/weights_registry.py
"""
WEIGHTS REGISTRY - GĐ5 Training ↔ Runtime Linkage

This module is the GATEKEEPER for all weight artifacts.

Responsibilities:
- Load and validate weights at runtime
- Verify training lineage
- Block manual/unverified weights
- Maintain audit trail
- Promote weights between environments

ENFORCEMENT:
- Runtime WILL REJECT weights without valid metadata
- Runtime WILL REJECT weights with checksum mismatch
- Runtime WILL LOG all weight loading events

PRINCIPLES:
- No Untagged Model
- No Manual Promotion
- Immutable Artifact
- Verified Lineage
- Runtime-Enforced Governance
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum

from backend.scoring.scoring_formula import ScoringFormula
from backend.scoring.weight_metadata import (
    WeightMetadata,
    ArtifactStatus,
    compute_weights_checksum,
    validate_metadata,
    detect_manual_override,
    PIPELINE_VERSION,
)

logger = logging.getLogger(__name__)


# =====================================================
# CONSTANTS
# =====================================================

DEFAULT_WEIGHTS_DIR = str(
    Path(__file__).resolve().parent.parent.parent / "models" / "weights"
)
ACTIVE_WEIGHTS_SUBDIR = "active"
AUDIT_LOG_FILE = "weight_audit.log"
DEPLOYMENT_LOG_FILE = "deployment_log.json"

# ===========================================
# SCORING INTEGRITY CONSTANTS (GĐ Phase 1 + 5)
# ===========================================
# Phase 5: Accept both linear_regression and ridge_regression
ALLOWED_METHODS = ["linear_regression", "ridge_regression"]
REQUIRED_METHOD = "linear_regression"  # Default fallback for schema validation
REQUIRED_WEIGHT_KEYS = ["study", "interest", "market", "growth", "risk"]


# ===========================================
# PHASE 4: WEIGHT VERSION CONTRACT
# ===========================================

REQUIRED_WEIGHT_SCHEMA_FIELDS = [
    "version",
    "method", 
    "trained_at",
    "dataset_hash",
    "r2_score",
    "weights"
]

OPTIONAL_WEIGHT_SCHEMA_FIELDS = [
    "training_commit",
    "samples",
    "metrics",
    "checksum"
]


class WeightSchemaError(Exception):
    """Raised when weight file does not conform to version contract."""
    pass


def validate_weight_schema(weight_data: Dict[str, Any]) -> None:
    """Validate weight file conforms to Phase 4 version contract.
    
    Required fields:
    - version: str
    - method: str (must be 'linear_regression')
    - trained_at: str (UTC ISO timestamp)
    - dataset_hash: str (SHA256 hash)
    - r2_score: float
    - weights: dict with all SIMGR components
    
    Args:
        weight_data: Loaded weight file data
        
    Raises:
        WeightSchemaError: If schema validation fails
    """
    errors = []
    
    # Check required fields
    for field in REQUIRED_WEIGHT_SCHEMA_FIELDS:
        if field not in weight_data:
            errors.append(f"Missing required field: '{field}'")
    
    if errors:
        raise WeightSchemaError(
            f"Weight schema validation FAILED:\n" + 
            "\n".join(f"  - {e}" for e in errors)
        )
    
    # Validate method - Phase 5: accept both linear and ridge
    if weight_data.get("method") not in ALLOWED_METHODS:
        errors.append(
            f"Invalid method: '{weight_data.get('method')}', "
            f"allowed: {ALLOWED_METHODS}"
        )
    
    # Validate r2_score is numeric
    r2 = weight_data.get("r2_score")
    if not isinstance(r2, (int, float)):
        errors.append(f"r2_score must be numeric, got: {type(r2)}")
    
    # Validate weights dict
    weights = weight_data.get("weights", {})
    if not isinstance(weights, dict):
        errors.append(f"'weights' must be dict, got: {type(weights)}")
    else:
        # Check for all required weight keys (with or without _score suffix)
        for key in REQUIRED_WEIGHT_KEYS:
            key_with_suffix = f"{key}_score"
            if key not in weights and key_with_suffix not in weights:
                errors.append(f"Missing weight key: '{key}' or '{key_with_suffix}'")
    
    # Validate dataset_hash is non-empty string
    dataset_hash = weight_data.get("dataset_hash", "")
    if not isinstance(dataset_hash, str) or len(dataset_hash) < 8:
        errors.append(f"dataset_hash must be non-empty string (>=8 chars)")
    
    # Validate trained_at is non-empty string
    trained_at = weight_data.get("trained_at", "")
    if not isinstance(trained_at, str) or len(trained_at) < 10:
        errors.append(f"trained_at must be UTC ISO timestamp string")
    
    if errors:
        raise WeightSchemaError(
            f"Weight schema validation FAILED:\n" + 
            "\n".join(f"  - {e}" for e in errors)
        )
    
    logger.info(f"[SCHEMA] Weight schema validation PASSED for version: {weight_data.get('version')}")


class ScoringIntegrityError(Exception):
    """Raised when scoring integrity validation fails."""
    pass


class LoadMode(Enum):
    """Weight loading mode."""
    STRICT = "strict"  # Fail if any validation fails
    WARN = "warn"      # Log warning but continue
    BYPASS = "bypass"  # Skip validation (DANGEROUS - for testing only)


# =====================================================
# AUDIT LOGGING
# =====================================================

@dataclass
class WeightLoadEvent:
    """Record of a weight loading event."""
    timestamp: str
    version: str
    status: ArtifactStatus
    checksum: str
    mode: LoadMode
    errors: List[str] = field(default_factory=list)
    source: str = ""  # File path
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "version": self.version,
            "status": self.status.value,
            "checksum": self.checksum,
            "mode": self.mode.value,
            "errors": self.errors,
            "source": self.source,
        }


def log_audit_event(event: WeightLoadEvent, audit_path: Optional[str] = None) -> None:
    """Append event to audit log."""
    if not audit_path:
        audit_path = os.path.join(DEFAULT_WEIGHTS_DIR, AUDIT_LOG_FILE)
    
    try:
        os.makedirs(os.path.dirname(audit_path), exist_ok=True)
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict()) + "\n")
    except Exception as e:
        logger.error(f"[AUDIT] Failed to write audit log: {e}")


# =====================================================
# VALIDATION ERRORS
# =====================================================

class WeightValidationError(Exception):
    """Base exception for weight validation failures."""
    pass


class MissingMetadataError(WeightValidationError):
    """Raised when weight_metadata.json is missing."""
    pass


class ChecksumMismatchError(WeightValidationError):
    """Raised when checksum verification fails."""
    pass


class ManualWeightError(WeightValidationError):
    """Raised when manual weight override is detected."""


class ZeroWeightError(WeightValidationError):
    """Raised when any SIMGR component has zero weight.

    A zero weight means that component is completely disabled, violating
    the 5-component SIMGR production model requirement.
    """
    pass


# Minimum weight per component enforced at load time (matches training floor)
MIN_PRODUCTION_WEIGHT = 0.05
LOW_WEIGHT_THRESHOLD  = 0.08   # Warn but allow


class IncompleteArtifactError(WeightValidationError):
    """Raised when artifact is incomplete."""
    pass


class LineageVerificationError(WeightValidationError):
    """Raised when training lineage cannot be verified."""
    pass


# =====================================================
# WEIGHTS REGISTRY
# =====================================================

class WeightsRegistry:
    """
    Central registry for SIMGR weight artifacts.
    
    This class enforces:
    - All weights MUST have valid metadata
    - All weights MUST pass checksum verification
    - All weights MUST be traceable to a training run
    - All load events MUST be audited
    
    Usage:
        registry = WeightsRegistry()
        weights = registry.load_active_weights()
        # or
        weights = registry.load_version("v3")
    """
    
    def __init__(
        self,
        weights_dir: str = DEFAULT_WEIGHTS_DIR,
        mode: LoadMode = LoadMode.STRICT,
        enable_audit: bool = True,
    ):
        """
        Initialize registry.
        
        Args:
            weights_dir: Base directory for weight artifacts
            mode: Validation mode (STRICT recommended for production)
            enable_audit: Whether to log audit events
        """
        self.weights_dir = Path(weights_dir)
        self.mode = mode
        self.enable_audit = enable_audit
        self._active_weights: Optional[Dict[str, float]] = None
        self._active_metadata: Optional[WeightMetadata] = None
        self._load_history: List[WeightLoadEvent] = []
    
    # ===========================================
    # PUBLIC API
    # ===========================================
    
    def load_active_weights(self) -> Dict[str, float]:
        """
        Load active (production) weights.
        
        Returns:
            Dict mapping weight key to value
            
        Raises:
            WeightValidationError: If validation fails in STRICT mode
        """
        active_dir = self.weights_dir / ACTIVE_WEIGHTS_SUBDIR
        return self._load_from_directory(active_dir)
    
    def load_version(self, version: str) -> Dict[str, float]:
        """
        Load weights from specific version.
        
        Args:
            version: Version string (e.g., "v3")
            
        Returns:
            Dict mapping weight key to value
            
        Raises:
            WeightValidationError: If validation fails in STRICT mode
        """
        version_dir = self.weights_dir / version
        return self._load_from_directory(version_dir)
    
    def get_active_metadata(self) -> Optional[WeightMetadata]:
        """Get metadata for currently loaded active weights."""
        if not self._active_metadata:
            self.load_active_weights()
        return self._active_metadata
    
    def list_versions(self) -> List[str]:
        """List all available weight versions."""
        versions = []
        if not self.weights_dir.exists():
            return versions
        
        for item in self.weights_dir.iterdir():
            if item.is_dir() and item.name != ACTIVE_WEIGHTS_SUBDIR:
                weights_file = item / "weights.json"
                if weights_file.exists():
                    versions.append(item.name)
        
        return sorted(versions)
    
    def get_version_metadata(self, version: str) -> Optional[WeightMetadata]:
        """Get metadata for a specific version."""
        version_dir = self.weights_dir / version
        metadata_path = version_dir / "weight_metadata.json"
        
        if metadata_path.exists():
            return WeightMetadata.from_file(str(metadata_path))
        return None
    
    def promote_to_active(
        self,
        version: str,
        approved_by: str = "",
        reason: str = "",
    ) -> bool:
        """
        Promote a version to active.
        
        This creates a copy in the 'active' directory.
        
        Args:
            version: Version to promote
            approved_by: Who approved the promotion
            reason: Reason for promotion
            
        Returns:
            True if successful
            
        Raises:
            WeightValidationError: If version invalid
        """
        # Validate source version first
        source_weights = self.load_version(version)
        source_metadata = self.get_version_metadata(version)
        
        if not source_metadata:
            raise MissingMetadataError(
                f"Cannot promote {version}: missing metadata"
            )
        
        # Check for manual override
        if self.mode == LoadMode.STRICT and detect_manual_override(source_metadata):
            raise ManualWeightError(
                f"Cannot promote {version}: detected manual weights"
            )
        
        # Update metadata with promotion info
        source_metadata.approved_by = approved_by
        source_metadata.approved_at = datetime.utcnow().isoformat() + "Z"
        source_metadata.promotion_reason = reason
        
        # Copy to active
        source_dir = self.weights_dir / version
        active_dir = self.weights_dir / ACTIVE_WEIGHTS_SUBDIR
        
        # Backup current active if exists
        if active_dir.exists():
            backup_name = f"active_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            backup_dir = self.weights_dir / backup_name
            shutil.copytree(active_dir, backup_dir)
            logger.info(f"[PROMOTE] Backed up active to {backup_name}")
        
        # Copy files
        active_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_dir / "weights.json", active_dir / "weights.json")
        source_metadata.save(str(active_dir / "weight_metadata.json"))
        
        if (source_dir / "metrics.json").exists():
            shutil.copy2(source_dir / "metrics.json", active_dir / "metrics.json")
        
        logger.info(f"[PROMOTE] Promoted {version} to active by {approved_by}")
        
        # Audit
        self._audit_event(
            version=version,
            status=ArtifactStatus.VALID,
            checksum=source_metadata.checksum,
            source=str(source_dir),
            errors=[f"Promoted to active by {approved_by}: {reason}"],
        )
        
        return True
    
    def validate_artifact(self, version: str) -> Tuple[ArtifactStatus, List[str]]:
        """
        Validate a weight artifact without loading.
        
        Returns:
            Tuple of (status, list_of_issues)
        """
        version_dir = self.weights_dir / version
        issues = []
        
        # Check directory exists
        if not version_dir.exists():
            return ArtifactStatus.UNKNOWN, [f"Version directory not found: {version}"]
        
        # Check weights.json
        weights_path = version_dir / "weights.json"
        if not weights_path.exists():
            return ArtifactStatus.UNKNOWN, ["weights.json not found"]
        
        # Check metadata
        metadata_path = version_dir / "weight_metadata.json"
        if not metadata_path.exists():
            return ArtifactStatus.MISSING_METADATA, ["weight_metadata.json not found"]
        
        try:
            metadata = WeightMetadata.from_file(str(metadata_path))
        except Exception as e:
            return ArtifactStatus.MISSING_METADATA, [f"Failed to parse metadata: {e}"]
        
        # Validate metadata
        is_valid, errors = validate_metadata(metadata)
        if not is_valid:
            issues.extend(errors)
        
        # Verify checksum
        try:
            with open(weights_path, "r", encoding="utf-8") as f:
                weights_data = json.load(f)
            
            weights = weights_data.get("weights", {})
            actual_checksum = compute_weights_checksum(weights)
            
            if metadata.checksum and actual_checksum != metadata.checksum:
                return ArtifactStatus.INVALID_CHECKSUM, [
                    f"Checksum mismatch: expected {metadata.checksum}, got {actual_checksum}"
                ]
        except Exception as e:
            issues.append(f"Checksum verification failed: {e}")
        
        # Check for manual override
        if detect_manual_override(metadata):
            return ArtifactStatus.MANUAL_OVERRIDE, [
                "Detected manual weight override"
            ] + issues
        
        # Check features
        expected_features = set(
            ScoringFormula.WEIGHT_KEYS[comp]
            for comp in ScoringFormula.COMPONENTS
        )
        if set(metadata.features) != expected_features:
            return ArtifactStatus.INCOMPLETE_FEATURES, [
                f"Features mismatch: expected {expected_features}"
            ]
        
        if issues:
            return ArtifactStatus.UNKNOWN, issues
        
        return ArtifactStatus.VALID, []
    
    # ===========================================
    # INTERNAL METHODS
    # ===========================================
    
    def _load_from_directory(self, dir_path: Path) -> Dict[str, float]:
        """Load and validate weights from a directory."""
        weights_path = dir_path / "weights.json"
        metadata_path = dir_path / "weight_metadata.json"
        
        # Check weights file exists
        if not weights_path.exists():
            raise IncompleteArtifactError(f"weights.json not found in {dir_path}")
        
        # Load weights
        with open(weights_path, "r", encoding="utf-8") as f:
            weights_data = json.load(f)
        
        weights = weights_data.get("weights", {})
        stored_checksum = weights_data.get("checksum", "")
        version = weights_data.get("version", "unknown")
        
        # ===========================================
        # SCORING INTEGRITY VALIDATION (GĐ Phase 1)
        # ===========================================
        # Extract method from metrics or root level
        method = weights_data.get("method") or weights_data.get("metrics", {}).get("method")
        trained_at = weights_data.get("trained_at", "unknown")
        
        if self.mode != LoadMode.BYPASS:
            # HARD FAIL: Method must be ML-trained
            if method not in ALLOWED_METHODS:
                logger.critical(
                    f"SCORING INTEGRITY FAILURE: Invalid weights detected. "
                    f"Expected method in {ALLOWED_METHODS}, got '{method}'."
                )
                raise ScoringIntegrityError(
                    f"Scoring Integrity Violation: "
                    f"Expected method in {ALLOWED_METHODS}, "
                    f"got '{method}'. "
                    "System cannot run with default or unverified weights."
                )
            
            # HARD FAIL: Required weight keys must exist
            # Map weight_score keys to simple keys for validation
            weight_keys_present = set()
            for key in weights.keys():
                # Convert 'study_score' -> 'study', etc.
                simple_key = key.replace("_score", "")
                weight_keys_present.add(simple_key)
            
            missing_keys = set(REQUIRED_WEIGHT_KEYS) - weight_keys_present
            if missing_keys:
                logger.critical(
                    f"SCORING INTEGRITY FAILURE: Weights file missing required components: {missing_keys}"
                )
                raise ScoringIntegrityError(
                    f"Weights file missing required components: {missing_keys}. "
                    f"Required: {REQUIRED_WEIGHT_KEYS}"
                )

            # ─── GĐ v2.0: ZERO-WEIGHT GUARD ────────────────────────────────────
            # Reject deployment if any SIMGR component has weight = 0 or below
            # the production minimum.  A zero weight silently disables a
            # component, reducing a 5-component SIMGR model to 3 or 4 components.
            zero_components = []
            low_components  = []
            for raw_key, raw_val in weights.items():
                comp_name = raw_key.replace("_score", "")
                w_val = float(raw_val)
                if w_val == 0.0:
                    zero_components.append((comp_name, w_val))
                elif w_val < MIN_PRODUCTION_WEIGHT:
                    low_components.append((comp_name, w_val))

            if zero_components:
                logger.critical(
                    "[REGISTRY] 5-COMPONENT SIMGR VIOLATION: Components with "
                    "weight=0 detected: %s.  Deployment BLOCKED.",
                    zero_components,
                )
                raise ZeroWeightError(
                    f"Production deployment blocked: the following SIMGR components "
                    f"have weight=0, which disables them entirely: {zero_components}. "
                    f"All 5 components (S, I, M, G, R) must have weight > 0.  "
                    f"Re-run the training pipeline with the sign-corrected "
                    f"prepare_training_matrix (GĐ v2.0 fix)."
                )

            if low_components:
                for comp, w in low_components:
                    logger.warning(
                        "[REGISTRY] LOW WEIGHT WARNING: component '%s' weight=%.4f "
                        "is below recommended minimum (%.2f).  "
                        "Consider re-training with more diverse data.",
                        comp, w, LOW_WEIGHT_THRESHOLD,
                    )
            # ─── end zero-weight guard ──────────────────────────────────────────

            # SUCCESS: Log validated weights
            logger.info(
                f"[SCORING] Loaded weights "
                f"version={version} "
                f"method={method} "
                f"trained_at={trained_at}"
            )
        
        # Load or create metadata
        metadata: Optional[WeightMetadata] = None
        if metadata_path.exists():
            try:
                metadata = WeightMetadata.from_file(str(metadata_path))
            except Exception as e:
                logger.warning(f"[REGISTRY] Failed to load metadata: {e}")
        
        errors = []
        status = ArtifactStatus.VALID
        
        # Validation checks
        if self.mode != LoadMode.BYPASS:
            # Check metadata exists
            if not metadata:
                errors.append("Missing weight_metadata.json")
                status = ArtifactStatus.MISSING_METADATA
                
                if self.mode == LoadMode.STRICT:
                    self._audit_event(version, status, stored_checksum, str(dir_path), errors)
                    raise MissingMetadataError(
                        f"GĐ5 VIOLATION: No metadata for weights at {dir_path}. "
                        "Weights MUST be produced by training pipeline."
                    )
            else:
                # Validate metadata
                is_valid, validation_errors = validate_metadata(metadata)
                if not is_valid:
                    errors.extend(validation_errors)
                    status = ArtifactStatus.MISSING_METADATA
                    
                    if self.mode == LoadMode.STRICT:
                        self._audit_event(version, status, stored_checksum, str(dir_path), errors)
                        raise IncompleteArtifactError(
                            f"GĐ5 VIOLATION: Invalid metadata: {validation_errors}"
                        )
                
                # Verify checksum
                actual_checksum = compute_weights_checksum(weights)
                if metadata.checksum and actual_checksum != metadata.checksum:
                    errors.append(f"Checksum mismatch")
                    status = ArtifactStatus.INVALID_CHECKSUM
                    
                    if self.mode == LoadMode.STRICT:
                        self._audit_event(version, status, actual_checksum, str(dir_path), errors)
                        raise ChecksumMismatchError(
                            f"GĐ5 VIOLATION: Weights modified after training. "
                            f"Expected: {metadata.checksum}, Got: {actual_checksum}"
                        )
                
                # Check for manual override
                if detect_manual_override(metadata):
                    errors.append("Manual weight override detected")
                    status = ArtifactStatus.MANUAL_OVERRIDE
                    
                    if self.mode == LoadMode.STRICT:
                        self._audit_event(version, status, stored_checksum, str(dir_path), errors)
                        raise ManualWeightError(
                            "GĐ5 VIOLATION: Manual weights detected. "
                            "Weights MUST come from training pipeline."
                        )
        
        # Log warnings if in WARN mode
        if self.mode == LoadMode.WARN and errors:
            for error in errors:
                logger.warning(f"[REGISTRY] {error}")
        
        # Audit successful load
        self._audit_event(
            version=metadata.version if metadata else version,
            status=status,
            checksum=metadata.checksum if metadata else stored_checksum,
            source=str(dir_path),
            errors=errors,
        )
        
        # Cache active weights
        if dir_path.name == ACTIVE_WEIGHTS_SUBDIR:
            self._active_weights = weights
            self._active_metadata = metadata
        
        logger.info(
            f"[REGISTRY] Loaded weights v{metadata.version if metadata else version} "
            f"(status: {status.value})"
        )
        
        return weights
    
    def _audit_event(
        self,
        version: str,
        status: ArtifactStatus,
        checksum: str,
        source: str,
        errors: List[str],
    ) -> None:
        """Record audit event."""
        event = WeightLoadEvent(
            timestamp=datetime.utcnow().isoformat() + "Z",
            version=version,
            status=status,
            checksum=checksum,
            mode=self.mode,
            errors=errors,
            source=source,
        )
        
        self._load_history.append(event)
        
        if self.enable_audit:
            log_audit_event(event)


# =====================================================
# MODULE-LEVEL HELPERS
# =====================================================

# Global registry instance
_registry: Optional[WeightsRegistry] = None


def get_registry(
    mode: LoadMode = LoadMode.STRICT,
    weights_dir: str = DEFAULT_WEIGHTS_DIR,
) -> WeightsRegistry:
    """Get or create global registry instance."""
    global _registry
    if _registry is None:
        _registry = WeightsRegistry(weights_dir=weights_dir, mode=mode)
    return _registry


def load_verified_weights(
    version: Optional[str] = None,
    mode: LoadMode = LoadMode.STRICT,
) -> Dict[str, float]:
    """
    Load weights with full verification.
    
    This is the RECOMMENDED way to load weights at runtime.
    
    Args:
        version: Specific version or None for active
        mode: Validation mode
        
    Returns:
        Verified weight dict
    """
    registry = get_registry(mode=mode)
    
    if version:
        return registry.load_version(version)
    else:
        return registry.load_active_weights()


def get_weight_lineage(version: Optional[str] = None) -> Dict[str, Any]:
    """
    Get full lineage information for weights.
    
    Useful for debugging and audit.
    """
    registry = get_registry()
    
    if version:
        metadata = registry.get_version_metadata(version)
    else:
        metadata = registry.get_active_metadata()
    
    if not metadata:
        return {"error": "No metadata available"}
    
    return {
        "version": metadata.version,
        "trained_at": metadata.trained_at,
        "dataset": metadata.dataset,
        "dataset_hash": metadata.dataset_hash,
        "trainer_commit": metadata.trainer_commit,
        "pipeline_version": metadata.pipeline_version,
        "checksum": metadata.checksum,
        "metrics": metadata.metrics.to_dict() if hasattr(metadata.metrics, 'to_dict') else metadata.metrics,
        "approved_by": metadata.approved_by,
        "approved_at": metadata.approved_at,
    }


# =====================================================
# DEVELOPMENT-ONLY DEFAULT WEIGHTS (GĐ Phase 1)
# =====================================================

DEFAULTS_FILE = "defaults.json"

# HARDENED (2026-02-21): SIMGR_ENVIRONMENT ENV read permanently removed.
# Environment is always PRODUCTION — no runtime override is possible.
# Weight resolution is manifest-driven only (manifest.json, locked=true).
ENVIRONMENT: str = "production"


def load_default_weights_for_development() -> Dict[str, float]:
    """
    [PERMANENTLY BLOCKED — production-hardening-2026-02-21]

    Default weights via ENV-driven environment detection have been removed.
    Weight loading is manifest-driven only: manifest.json + sha256 verification.

    This function now always raises RuntimeError regardless of caller,
    because ENVIRONMENT is hardcoded to "production" and is no longer
    readable from os.environ.

    Raises:
        RuntimeError: Always — default weight loading is disabled.
    """
    # ENVIRONMENT is always "production" — this branch always triggers.
    if ENVIRONMENT != "development":
        logger.critical(
            "[SCORING] GOVERNANCE BLOCK: load_default_weights_for_development() "
            "called but default weight loading is permanently disabled. "
            "Use manifest-driven weight loading only."
        )
        raise RuntimeError(
            "Default weights are permanently disabled. "
            "ENVIRONMENT is hardcoded to 'production'; "
            "no ENV override is possible. "
            "Load weights via manifest.json only."
        )
    
    defaults_path = Path(DEFAULT_WEIGHTS_DIR) / DEFAULTS_FILE
    
    if not defaults_path.exists():
        raise FileNotFoundError(f"Defaults file not found: {defaults_path}")
    
    with open(defaults_path, "r", encoding="utf-8") as f:
        defaults_data = json.load(f)
    
    logger.warning(
        "[SCORING] Loaded DEFAULT weights for DEVELOPMENT mode. "
        "NOT FOR PRODUCTION USE."
    )
    
    return defaults_data.get("weights", {})


# =====================================================
# EXPORTS
# =====================================================

__all__ = [
    # Main class
    "WeightsRegistry",
    # Enums
    "LoadMode",
    # Errors
    "WeightValidationError",
    "MissingMetadataError",
    "ChecksumMismatchError",
    "ManualWeightError",
    "IncompleteArtifactError",
    "LineageVerificationError",
    "ScoringIntegrityError",
    # Constants (GĐ Phase 1)
    "REQUIRED_METHOD",
    "REQUIRED_WEIGHT_KEYS",
    "ENVIRONMENT",
    # Helpers
    "get_registry",
    "load_verified_weights",
    "get_weight_lineage",
    "load_default_weights_for_development",
    # Events
    "WeightLoadEvent",
]

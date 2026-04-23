# backend/scoring/weight_metadata.py
"""
WEIGHT METADATA STANDARD - GĐ5 Training ↔ Runtime Linkage

This module defines:
- Metadata schema for trained weights
- Checksum computation and verification
- Lineage tracking
- Artifact validation

PRINCIPLES:
- No Untagged Model
- No Manual Promotion
- Immutable Artifact
- Verified Lineage
- Runtime-Enforced Governance
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from enum import Enum

from backend.scoring.scoring_formula import ScoringFormula

logger = logging.getLogger(__name__)


# =====================================================
# CONSTANTS
# =====================================================

METADATA_VERSION = "1.0"
PIPELINE_VERSION = "train_v2.1"
REQUIRED_METADATA_FIELDS = [
    "version",
    "trained_at",
    "dataset",
    "features",
    "checksum",
    "pipeline_version",
]


class ArtifactStatus(Enum):
    """Status of a weight artifact."""
    VALID = "valid"
    INVALID_CHECKSUM = "invalid_checksum"
    MISSING_METADATA = "missing_metadata"
    INCOMPLETE_FEATURES = "incomplete_features"
    MANUAL_OVERRIDE = "manual_override"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


# =====================================================
# METADATA SCHEMA
# =====================================================

@dataclass
class TrainingMetrics:
    """Metrics from training run."""
    r2: float = 0.0
    mae: float = 0.0
    rmse: float = 0.0
    train_loss: float = 0.0
    val_loss: float = 0.0
    correlation: float = 0.0
    n_samples: int = 0
    n_folds: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrainingMetrics":
        return cls(
            r2=data.get("r2", 0.0),
            mae=data.get("mae", 0.0),
            rmse=data.get("rmse", 0.0),
            train_loss=data.get("train_loss", 0.0),
            val_loss=data.get("val_loss", 0.0),
            correlation=data.get("correlation", 0.0),
            n_samples=data.get("n_samples", 0),
            n_folds=data.get("n_folds", 0),
        )


@dataclass
class WeightMetadata:
    """
    MANDATORY metadata for trained weights.
    
    Every weight artifact MUST have this metadata.
    Runtime WILL REJECT weights without valid metadata.
    """
    
    # Core identification
    version: str
    trained_at: str  # ISO 8601 format
    
    # Data lineage
    dataset: str  # Path to training dataset
    dataset_hash: str = ""  # SHA256 of dataset
    
    # Feature specification (MUST match ScoringFormula.COMPONENTS)
    features: List[str] = field(default_factory=list)
    
    # Artifact integrity
    checksum: str = ""  # SHA256 of weights.json
    
    # Pipeline tracking
    trainer_commit: str = ""  # Git commit hash
    pipeline_version: str = PIPELINE_VERSION
    
    # Training metrics
    metrics: TrainingMetrics = field(default_factory=TrainingMetrics)
    
    # Governance
    approved_by: str = ""  # For manual approval tracking
    approved_at: str = ""
    promotion_reason: str = ""
    
    # Metadata version
    metadata_version: str = METADATA_VERSION
    
    def __post_init__(self):
        """Validate on creation."""
        if not self.features:
            # Default to ScoringFormula components
            self.features = [
                ScoringFormula.WEIGHT_KEYS[comp]
                for comp in ScoringFormula.COMPONENTS
            ]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "version": self.version,
            "trained_at": self.trained_at,
            "dataset": self.dataset,
            "dataset_hash": self.dataset_hash,
            "features": self.features,
            "checksum": self.checksum,
            "trainer_commit": self.trainer_commit,
            "pipeline_version": self.pipeline_version,
            "metrics": self.metrics.to_dict() if isinstance(self.metrics, TrainingMetrics) else self.metrics,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "promotion_reason": self.promotion_reason,
            "metadata_version": self.metadata_version,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WeightMetadata":
        """Create from dictionary."""
        metrics_data = data.get("metrics", {})
        if isinstance(metrics_data, dict):
            metrics = TrainingMetrics.from_dict(metrics_data)
        else:
            metrics = TrainingMetrics()
        
        return cls(
            version=data.get("version", ""),
            trained_at=data.get("trained_at", ""),
            dataset=data.get("dataset", ""),
            dataset_hash=data.get("dataset_hash", ""),
            features=data.get("features", []),
            checksum=data.get("checksum", ""),
            trainer_commit=data.get("trainer_commit", ""),
            pipeline_version=data.get("pipeline_version", ""),
            metrics=metrics,
            approved_by=data.get("approved_by", ""),
            approved_at=data.get("approved_at", ""),
            promotion_reason=data.get("promotion_reason", ""),
            metadata_version=data.get("metadata_version", METADATA_VERSION),
        )
    
    @classmethod
    def from_file(cls, path: str) -> "WeightMetadata":
        """Load metadata from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)
    
    def save(self, path: str) -> None:
        """Save metadata to JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info(f"[METADATA] Saved to {path}")


# =====================================================
# CHECKSUM UTILITIES
# =====================================================

def compute_file_checksum(file_path: str) -> str:
    """Compute SHA256 checksum of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return f"sha256:{sha256.hexdigest()}"


def compute_weights_checksum(weights: Dict[str, float]) -> str:
    """Compute SHA256 checksum of weights dict."""
    # Normalize: sort keys, round values
    normalized = {
        k: round(v, 8) for k, v in sorted(weights.items())
    }
    content = json.dumps(normalized, sort_keys=True)
    sha256 = hashlib.sha256(content.encode()).hexdigest()
    return f"sha256:{sha256}"


def verify_checksum(file_path: str, expected_checksum: str) -> bool:
    """Verify file checksum matches expected."""
    if not expected_checksum:
        return False
    
    actual = compute_file_checksum(file_path)
    return actual == expected_checksum


# =====================================================
# GIT UTILITIES
# =====================================================

def get_git_commit() -> str:
    """Get current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]
    except Exception:
        pass
    return "unknown"


def get_git_branch() -> str:
    """Get current git branch."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


# =====================================================
# VALIDATION FUNCTIONS
# =====================================================

def validate_metadata(metadata: WeightMetadata) -> tuple[bool, List[str]]:
    """
    Validate weight metadata completeness.
    
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    # Check required fields
    if not metadata.version:
        errors.append("Missing required field: version")
    
    if not metadata.trained_at:
        errors.append("Missing required field: trained_at")
    
    if not metadata.dataset:
        errors.append("Missing required field: dataset")
    
    if not metadata.checksum:
        errors.append("Missing required field: checksum")
    
    if not metadata.pipeline_version:
        errors.append("Missing required field: pipeline_version")
    
    # Validate features match ScoringFormula
    expected_features = [
        ScoringFormula.WEIGHT_KEYS[comp]
        for comp in ScoringFormula.COMPONENTS
    ]
    
    if set(metadata.features) != set(expected_features):
        errors.append(
            f"Features mismatch. Expected: {expected_features}, "
            f"Got: {metadata.features}"
        )
    
    # Validate timestamp format (ISO 8601)
    if metadata.trained_at:
        try:
            datetime.fromisoformat(metadata.trained_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"Invalid timestamp format: {metadata.trained_at}")
    
    return len(errors) == 0, errors


def detect_manual_override(metadata: WeightMetadata) -> bool:
    """
    Detect if weights were manually created/modified.
    
    Signs of manual override:
    - No trainer_commit
    - No dataset
    - Suspicious pipeline_version
    - No metrics
    """
    # No git commit = likely manual
    if not metadata.trainer_commit or metadata.trainer_commit == "unknown":
        logger.warning("[MANUAL_DETECT] No trainer_commit - possible manual weights")
        return True
    
    # No dataset = definitely manual
    if not metadata.dataset:
        logger.warning("[MANUAL_DETECT] No dataset - manual weights detected")
        return True
    
    # Check metrics
    if metadata.metrics.n_samples == 0:
        logger.warning("[MANUAL_DETECT] Zero training samples - possible manual weights")
        return True
    
    return False


# =====================================================
# ARTIFACT CREATION
# =====================================================

def create_weight_artifact(
    weights: Dict[str, float],
    version: str,
    dataset_path: str,
    metrics: Dict[str, Any],
    output_dir: str,
) -> tuple[str, str]:
    """
    Create complete weight artifact with metadata.
    
    Creates:
        - weights.json
        - weight_metadata.json
    
    Returns:
        Tuple of (weights_path, metadata_path)
    """
    from pathlib import Path
    
    # Create output directory
    version_dir = Path(output_dir) / version
    version_dir.mkdir(parents=True, exist_ok=True)
    
    # Compute checksums
    weights_checksum = compute_weights_checksum(weights)
    
    dataset_hash = ""
    if dataset_path and os.path.exists(dataset_path):
        dataset_hash = compute_file_checksum(dataset_path)
    
    # Build weights.json
    weights_data = {
        "version": version,
        "weights": weights,
        "checksum": weights_checksum,
    }
    
    weights_path = version_dir / "weights.json"
    with open(weights_path, "w", encoding="utf-8") as f:
        json.dump(weights_data, f, indent=2)
    
    # Build metadata
    metadata = WeightMetadata(
        version=version,
        trained_at=datetime.utcnow().isoformat() + "Z",
        dataset=dataset_path,
        dataset_hash=dataset_hash,
        features=[
            ScoringFormula.WEIGHT_KEYS[comp]
            for comp in ScoringFormula.COMPONENTS
        ],
        checksum=weights_checksum,
        trainer_commit=get_git_commit(),
        pipeline_version=PIPELINE_VERSION,
        metrics=TrainingMetrics.from_dict(metrics),
    )
    
    # Save metadata
    metadata_path = version_dir / "weight_metadata.json"
    metadata.save(str(metadata_path))
    
    logger.info(f"[ARTIFACT] Created weight artifact at {version_dir}")
    logger.info(f"[ARTIFACT] Checksum: {weights_checksum}")
    
    return str(weights_path), str(metadata_path)


# =====================================================
# EXPORTS
# =====================================================

__all__ = [
    # Schema
    "WeightMetadata",
    "TrainingMetrics",
    "ArtifactStatus",
    # Constants
    "METADATA_VERSION",
    "PIPELINE_VERSION",
    "REQUIRED_METADATA_FIELDS",
    # Functions
    "compute_file_checksum",
    "compute_weights_checksum",
    "verify_checksum",
    "validate_metadata",
    "detect_manual_override",
    "create_weight_artifact",
    "get_git_commit",
    "get_git_branch",
]

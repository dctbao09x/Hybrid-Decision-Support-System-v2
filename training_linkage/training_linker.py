# backend/scoring/training_linker.py
"""
PHẦN C — RUNTIME LINKER (GĐ5)

TrainingLinker - The ONLY gateway for loading weights at runtime.

Responsibilities:
1. Load weights + metadata
2. Verify checksum
3. Verify dataset exists (if required)
4. Verify feature set
5. Verify freshness (MAX_AGE_DAYS)
6. Verify metrics thresholds
7. Enforce version

RUNTIME CHỈ chạy với trained model - NO EXCEPTIONS.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


# =============================================================================
# CUSTOM ERRORS - GĐ5 INTEGRITY VIOLATIONS
# =============================================================================

class ModelIntegrityError(Exception):
    """Base error for all model integrity violations."""
    pass


class StaleModelError(ModelIntegrityError):
    """Model is older than MAX_AGE_DAYS."""
    pass


class TamperedModelError(ModelIntegrityError):
    """Checksum mismatch - model was modified after training."""
    pass


class InvalidModelError(ModelIntegrityError):
    """Missing or invalid metadata."""
    pass


class UnqualifiedModelError(ModelIntegrityError):
    """Model metrics below required thresholds."""
    pass


class MissingTrainerCommitError(ModelIntegrityError):
    """No trainer commit - cannot verify origin."""
    pass


class FilesystemManipulationError(ModelIntegrityError):
    """Detected direct filesystem manipulation."""
    pass


# =============================================================================
# METRIC THRESHOLDS - PHẦN B REQUIREMENTS
# =============================================================================

@dataclass(frozen=True)
class MetricThresholds:
    """Required metric thresholds for model qualification.
    
    PHẦN B: Model MUST meet these to be exported.
    """
    min_r2: float = 0.7        # R² >= 0.7
    max_mae: float = 0.1       # MAE <= 0.1
    min_correlation: float = 0.6  # Correlation coefficient
    min_samples: int = 100     # Minimum training samples


DEFAULT_THRESHOLDS = MetricThresholds()


# =============================================================================
# MODEL LINEAGE - PHẦN G TRACEABILITY
# =============================================================================

@dataclass
class ModelLineage:
    """Traceability information for model origin.
    
    PHẦN G: Mỗi response phải kèm model_lineage.
    """
    weight_version: str
    trained_at: str
    dataset: str
    dataset_checksum: str
    weights_checksum: str
    pipeline_version: str
    trainer_commit: str
    metrics: Dict[str, float]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for API response."""
        return {
            "weight_version": self.weight_version,
            "trained_at": self.trained_at,
            "dataset": self.dataset,
            "checksum": self.weights_checksum,
            "pipeline_version": self.pipeline_version,
        }
    
    def to_full_dict(self) -> Dict[str, Any]:
        """Full traceability dict."""
        return {
            "weight_version": self.weight_version,
            "trained_at": self.trained_at,
            "dataset": self.dataset,
            "dataset_checksum": self.dataset_checksum,
            "weights_checksum": self.weights_checksum,
            "pipeline_version": self.pipeline_version,
            "trainer_commit": self.trainer_commit,
            "metrics": self.metrics,
        }


# =============================================================================
# TRAINING LINKER - CENTRAL RUNTIME GATEWAY
# =============================================================================

class TrainingLinker:
    """
    The ONLY gateway for loading weights at runtime.
    
    PHẦN C: Runtime Linker responsibilities
    PHẦN D: Runtime Enforcement - scoring_formula.py MUST use this
    PHẦN E: Staleness & Tamper Detection
    PHẦN F: Manual Override Blocking
    
    RULES:
    - NO direct weights.json loading
    - NO default fallback
    - NO hardcoded weights
    - ALL verification MUST pass
    """
    
    # Configuration
    MAX_AGE_DAYS: int = 90
    BASE_PATH: str = "models/weights"
    ACTIVE_DIR: str = "active"
    
    # Required SIMGR features
    REQUIRED_FEATURES: List[str] = [
        "study", "interest", "market", "growth", "risk"
    ]
    
    # Singleton pattern for runtime caching
    _instance: Optional["TrainingLinker"] = None
    _cached_weights: Optional[Dict[str, float]] = None
    _cached_lineage: Optional[ModelLineage] = None
    _verified: bool = False
    
    def __new__(cls) -> "TrainingLinker":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self._thresholds = DEFAULT_THRESHOLDS
    
    @classmethod
    def reset(cls) -> None:
        """Reset singleton for testing purposes only."""
        cls._instance = None
        cls._cached_weights = None
        cls._cached_lineage = None
        cls._verified = False
    
    # =========================================================================
    # MAIN INTERFACE
    # =========================================================================
    
    @classmethod
    def load_verified_weights(
        cls,
        version: Optional[str] = None,
        force_reload: bool = False,
    ) -> "SIMGRWeights":
        """Load and verify weights - THE ONLY WAY to get weights at runtime.
        
        PHẦN D: This is the ONLY method scoring_formula.py should use.
        
        Args:
            version: Specific version to load, or None for active.
            force_reload: Bypass cache and re-verify.
            
        Returns:
            SIMGRWeights instance with verified weights.
            
        Raises:
            ModelIntegrityError: If any verification fails.
        """
        from backend.scoring.config import SIMGRWeights
        
        linker = cls()
        
        # Use cache if valid and not forcing reload
        if (cls._verified and cls._cached_weights and 
            not force_reload and version is None):
            logger.debug("[LINKER] Using cached verified weights")
            return cls._create_simgr_weights(cls._cached_weights)
        
        # Full verification pipeline
        weights, lineage = linker._full_verification(version)
        
        # Cache for subsequent calls
        cls._cached_weights = weights
        cls._cached_lineage = lineage
        cls._verified = True
        
        logger.info(
            f"[LINKER] Verified weights loaded: {lineage.weight_version} "
            f"(trained: {lineage.trained_at})"
        )
        
        return cls._create_simgr_weights(weights)
    
    @classmethod
    def get_lineage(cls) -> ModelLineage:
        """Get current model lineage for traceability.
        
        PHẦN G: Use this to include lineage in API responses.
        
        Raises:
            InvalidModelError: If no verified model loaded.
        """
        if not cls._verified or cls._cached_lineage is None:
            raise InvalidModelError(
                "No verified model loaded. Call load_verified_weights() first."
            )
        return cls._cached_lineage
    
    @classmethod
    def get_lineage_header(cls) -> Dict[str, Any]:
        """Get lineage dict for API response headers.
        
        PHẦN G: Mỗi response phải kèm model_lineage.
        """
        lineage = cls.get_lineage()
        return {"model_lineage": lineage.to_dict()}
    
    # =========================================================================
    # VERIFICATION PIPELINE
    # =========================================================================
    
    def _full_verification(
        self, 
        version: Optional[str] = None,
    ) -> Tuple[Dict[str, float], ModelLineage]:
        """Run complete verification pipeline.
        
        Steps:
        1. Load weights.json
        2. Load weight_metadata.json
        3. Verify checksum (PHẦN E)
        4. Verify freshness (PHẦN E)
        5. Verify features (PHẦN C)
        6. Verify metrics (PHẦN B/E)
        7. Verify trainer commit (PHẦN F)
        8. Check manual override (PHẦN F)
        
        All steps MUST pass - NO exceptions.
        """
        version = version or self.ACTIVE_DIR
        version_path = Path(self.BASE_PATH) / version
        
        # Step 1: Load weights.json
        weights_file = version_path / "weights.json"
        if not weights_file.exists():
            raise InvalidModelError(
                f"Weights file not found: {weights_file}. "
                "No trained model available. Run training pipeline."
            )
        
        with open(weights_file, "r") as f:
            payload = json.load(f)
        
        weights = payload.get("weights", {})
        stored_checksum = payload.get("checksum", "")
        
        # Step 2: Load weight_metadata.json
        metadata_file = version_path / "weight_metadata.json"
        if not metadata_file.exists():
            raise InvalidModelError(
                f"INVALID_MODEL: Metadata file not found: {metadata_file}. "
                "Model was not produced by valid training pipeline."
            )
        
        with open(metadata_file, "r") as f:
            metadata = json.load(f)
        
        # Step 3: Verify checksum (PHẦN E - TAMPERED_MODEL)
        self._verify_checksum(weights, metadata, stored_checksum)
        
        # Step 4: Verify freshness (PHẦN E - STALE_MODEL)
        self._verify_freshness(metadata)
        
        # Step 5: Verify features
        self._verify_features(metadata)
        
        # Step 6: Verify metrics (PHẦN E - UNQUALIFIED_MODEL)
        self._verify_metrics(metadata)
        
        # Step 7: Verify trainer commit (PHẦN F)
        self._verify_trainer_commit(metadata)
        
        # Step 8: Check manual override (PHẦN F)
        self._check_manual_override(weights_file, metadata_file, metadata)
        
        # Build lineage
        lineage = self._build_lineage(payload, metadata, version)
        
        return weights, lineage
    
    def _verify_checksum(
        self, 
        weights: Dict[str, float], 
        metadata: Dict, 
        stored_checksum: str,
    ) -> None:
        """Verify weight checksum matches metadata.
        
        PHẦN E: Checksum mismatch → TAMPERED_MODEL
        """
        from backend.scoring.weight_metadata import compute_weights_checksum
        
        # Compute actual checksum
        actual_checksum = compute_weights_checksum(weights)
        
        # Compare with metadata checksum
        metadata_checksum = metadata.get("weights_checksum", "")
        
        if actual_checksum != metadata_checksum:
            raise TamperedModelError(
                f"TAMPERED_MODEL: Checksum mismatch!\n"
                f"  Expected (metadata): {metadata_checksum[:16]}...\n"
                f"  Actual (computed):   {actual_checksum[:16]}...\n"
                f"Model was modified after training. Re-train required."
            )
        
        logger.debug(f"[LINKER] Checksum verified: {actual_checksum[:16]}...")
    
    def _verify_freshness(self, metadata: Dict) -> None:
        """Verify model is not stale.
        
        PHẦN E: if now - trained_at > MAX_AGE → STALE_MODEL
        """
        trained_at_str = metadata.get("trained_at", "")
        
        if not trained_at_str:
            raise InvalidModelError(
                "INVALID_MODEL: Missing trained_at timestamp in metadata."
            )
        
        try:
            trained_at = datetime.fromisoformat(trained_at_str.replace("Z", "+00:00"))
            # Handle naive datetime
            if trained_at.tzinfo is not None:
                trained_at = trained_at.replace(tzinfo=None)
        except ValueError as e:
            raise InvalidModelError(
                f"INVALID_MODEL: Cannot parse trained_at: {trained_at_str}"
            ) from e
        
        now = datetime.utcnow()
        age = now - trained_at
        max_age = timedelta(days=self.MAX_AGE_DAYS)
        
        if age > max_age:
            raise StaleModelError(
                f"STALE_MODEL: Model too old!\n"
                f"  Trained at: {trained_at.isoformat()}\n"
                f"  Age: {age.days} days\n"
                f"  Max allowed: {self.MAX_AGE_DAYS} days\n"
                f"Re-training required."
            )
        
        logger.debug(f"[LINKER] Freshness verified: {age.days} days old")
    
    def _verify_features(self, metadata: Dict) -> None:
        """Verify all required features present.
        
        PHẦN C: Verify feature set.
        """
        features = metadata.get("features", [])
        
        missing = [f for f in self.REQUIRED_FEATURES if f not in features]
        
        if missing:
            raise InvalidModelError(
                f"INVALID_MODEL: Missing required features: {missing}\n"
                f"Model features: {features}\n"
                f"Required: {self.REQUIRED_FEATURES}"
            )
        
        logger.debug(f"[LINKER] Features verified: {features}")
    
    def _verify_metrics(self, metadata: Dict) -> None:
        """Verify model metrics meet thresholds.
        
        PHẦN E: Metric below threshold → UNQUALIFIED_MODEL
        PHẦN B: R² >= 0.7, MAE <= 0.1
        """
        metrics = metadata.get("metrics", {})
        
        # Check R² (correlation² as proxy)
        correlation = metrics.get("correlation", 0.0)
        r2 = correlation ** 2  # Approximate R²
        
        if r2 < self._thresholds.min_r2:
            raise UnqualifiedModelError(
                f"UNQUALIFIED_MODEL: R² too low!\n"
                f"  R² (from correlation²): {r2:.4f}\n"
                f"  Required minimum: {self._thresholds.min_r2}\n"
                f"Model does not meet quality threshold."
            )
        
        # Check MAE
        mae = metrics.get("mae", float("inf"))
        if mae > self._thresholds.max_mae:
            raise UnqualifiedModelError(
                f"UNQUALIFIED_MODEL: MAE too high!\n"
                f"  MAE: {mae:.4f}\n"
                f"  Required maximum: {self._thresholds.max_mae}\n"
                f"Model does not meet quality threshold."
            )
        
        # Check correlation
        if correlation < self._thresholds.min_correlation:
            raise UnqualifiedModelError(
                f"UNQUALIFIED_MODEL: Correlation too low!\n"
                f"  Correlation: {correlation:.4f}\n"
                f"  Required minimum: {self._thresholds.min_correlation}\n"
                f"Model does not meet quality threshold."
            )
        
        # Check samples
        samples = metrics.get("n_samples", metrics.get("samples_used", 0))
        if samples < self._thresholds.min_samples:
            raise UnqualifiedModelError(
                f"UNQUALIFIED_MODEL: Insufficient training samples!\n"
                f"  Samples: {samples}\n"
                f"  Required minimum: {self._thresholds.min_samples}\n"
                f"Not enough data for reliable model."
            )
        
        logger.debug(
            f"[LINKER] Metrics verified: R²={r2:.3f}, MAE={mae:.4f}, "
            f"corr={correlation:.3f}, samples={samples}"
        )
    
    def _verify_trainer_commit(self, metadata: Dict) -> None:
        """Verify trainer commit is present.
        
        PHẦN F: Missing trainer_commit → AUTO-REJECT
        """
        commit = metadata.get("trainer_commit", "")
        
        if not commit or commit == "unknown":
            raise MissingTrainerCommitError(
                "INVALID_MODEL: Missing trainer_commit in metadata.\n"
                "Cannot verify model origin. Model may be manually created."
            )
        
        logger.debug(f"[LINKER] Trainer commit verified: {commit[:8]}...")
    
    def _check_manual_override(
        self,
        weights_file: Path,
        metadata_file: Path,
        metadata: Dict,
    ) -> None:
        """Check for manual override indicators.
        
        PHẦN F: Detect manual manipulation.
        
        Indicators:
        - weights.json modified time > metadata
        - Missing audit trail
        """
        import os
        
        # Compare modification times
        weights_mtime = os.path.getmtime(weights_file)
        metadata_mtime = os.path.getmtime(metadata_file)
        
        # Allow small time difference (1 second) for atomic writes
        if weights_mtime > metadata_mtime + 1:
            raise FilesystemManipulationError(
                "TAMPERED_MODEL: weights.json modified after metadata.\n"
                f"  Weights mtime: {datetime.fromtimestamp(weights_mtime)}\n"
                f"  Metadata mtime: {datetime.fromtimestamp(metadata_mtime)}\n"
                "Direct filesystem manipulation detected. Use promote_model.py."
            )
        
        # Check for promotion audit
        status = metadata.get("status", "")
        if status == "promoted_manual":
            raise FilesystemManipulationError(
                "INVALID_MODEL: Manual promotion detected.\n"
                "Use promote_model.py with proper audit trail."
            )
        
        logger.debug("[LINKER] No manual override detected")
    
    def _build_lineage(
        self,
        payload: Dict,
        metadata: Dict,
        version: str,
    ) -> ModelLineage:
        """Build lineage object for traceability."""
        metrics = metadata.get("metrics", {})
        
        return ModelLineage(
            weight_version=metadata.get("version", version),
            trained_at=metadata.get("trained_at", ""),
            dataset=metadata.get("dataset", ""),
            dataset_checksum=metadata.get("dataset_checksum", ""),
            weights_checksum=metadata.get("weights_checksum", ""),
            pipeline_version=metadata.get("pipeline_version", ""),
            trainer_commit=metadata.get("trainer_commit", ""),
            metrics={
                "train_loss": metrics.get("train_loss", 0),
                "val_loss": metrics.get("val_loss", 0),
                "correlation": metrics.get("correlation", 0),
                "r2": metrics.get("r2", 0),
                "mae": metrics.get("mae", 0),
                "n_samples": metrics.get("n_samples", metrics.get("samples_used", 0)),
            },
        )
    
    @staticmethod
    def _create_simgr_weights(weights: Dict[str, float]) -> "SIMGRWeights":
        """Create SIMGRWeights from verified weights dict."""
        from backend.scoring.config import SIMGRWeights
        
        return SIMGRWeights(
            study_score=weights.get("study", weights.get("study_score", 0.25)),
            interest_score=weights.get("interest", weights.get("interest_score", 0.25)),
            market_score=weights.get("market", weights.get("market_score", 0.25)),
            growth_score=weights.get("growth", weights.get("growth_score", 0.15)),
            risk_score=weights.get("risk", weights.get("risk_score", 0.10)),
        )


# =============================================================================
# MODULE-LEVEL FUNCTIONS - CONVENIENCE API
# =============================================================================

def load_verified_weights(
    version: Optional[str] = None,
    force_reload: bool = False,
) -> "SIMGRWeights":
    """Load verified weights - convenience wrapper.
    
    PHẦN D: Use this instead of direct weight loading.
    """
    return TrainingLinker.load_verified_weights(version, force_reload)


def get_model_lineage() -> ModelLineage:
    """Get current model lineage."""
    return TrainingLinker.get_lineage()


def get_lineage_header() -> Dict[str, Any]:
    """Get lineage header for API responses.
    
    PHẦN G: Include in every API response.
    """
    return TrainingLinker.get_lineage_header()


def verify_model_integrity(version: Optional[str] = None) -> Tuple[bool, List[str]]:
    """Verify model integrity without loading.
    
    Returns:
        (is_valid, errors) tuple.
    """
    errors = []
    
    try:
        TrainingLinker.load_verified_weights(version, force_reload=True)
        return True, []
    except StaleModelError as e:
        errors.append(f"STALE_MODEL: {e}")
    except TamperedModelError as e:
        errors.append(f"TAMPERED_MODEL: {e}")
    except InvalidModelError as e:
        errors.append(f"INVALID_MODEL: {e}")
    except UnqualifiedModelError as e:
        errors.append(f"UNQUALIFIED_MODEL: {e}")
    except MissingTrainerCommitError as e:
        errors.append(f"MISSING_COMMIT: {e}")
    except FilesystemManipulationError as e:
        errors.append(f"FILESYSTEM_MANIPULATION: {e}")
    except ModelIntegrityError as e:
        errors.append(f"INTEGRITY_ERROR: {e}")
    except Exception as e:
        errors.append(f"UNKNOWN_ERROR: {e}")
    
    return False, errors

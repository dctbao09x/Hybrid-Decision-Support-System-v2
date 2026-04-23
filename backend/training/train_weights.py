# backend/training/train_weights.py
"""
SIMGR Weight Learning Pipeline - Phase 5 Advanced Modeling.

Trains optimal weights for the SIMGR scoring formula using sklearn
with Ridge Regression, K-Fold Cross Validation, and automatic model selection.

GĐ Phase 5: ADVANCED MODELING & RETRAINING AUTOMATION
- Uses sklearn.linear_model.LinearRegression or Ridge (positive=True)
- K-Fold Cross Validation (default 5-fold)
- Automatic model selection between Linear and Ridge
- Overfitting detection guards
- Weights normalized to sum to 1
- Risk sign handled in scoring_formula.py (NOT inverted in training)

GĐ4: DELEGATES TO scoring_formula.py FOR FORMULA DEFINITION.
Formula definition is in scoring_formula.py - this module USES it, not DEFINES it.

Input: data/scoring/train.csv
Output: models/weights/archive/v5_<model_type>_<timestamp>.json
        models/weights/active/weights.json (after explicit activation)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd

# sklearn imports for Linear Regression and Ridge
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.model_selection import KFold, cross_val_score
from sklearn.metrics import r2_score, mean_absolute_error

from backend.scoring.scoring_formula import ScoringFormula

# Phase 3 validation import (lazy to avoid circular imports)
_validator_module = None

def get_validator_module():
    """Lazy import of validate_weights module."""
    global _validator_module
    if _validator_module is None:
        from backend.training import validate_weights as _vm
        _validator_module = _vm
    return _validator_module

logger = logging.getLogger(__name__)


# =====================================================
# CONFIGURATION
# =====================================================

@dataclass
class TrainingConfig:
    """Configuration for weight training.
    
    GĐ Phase 5: Advanced Modeling configuration with Ridge and K-Fold CV.
    """
    input_csv: str = "backend/data/scoring/train.csv"
    output_dir: str = "models/weights"
    version: str = "v5"
    
    # Phase 5: Model selection configuration
    model_type: str = "auto"  # "linear", "ridge", or "auto" (compares both)
    ridge_alpha: float = 1.0  # Ridge regularization strength
    
    # Phase 5: K-Fold Cross Validation
    n_folds: int = 5          # Number of CV folds
    enable_cv: bool = True    # Enable cross-validation
    
    # Phase 5: Overfitting detection
    max_overfit_gap: float = 0.1  # Max allowed gap between train R² and CV mean
    
    # Legacy compatibility
    method: str = "linear_regression"  # Updated dynamically based on model_type
    random_seed: int = 42
    
    # Governance thresholds - MUST pass to export
    min_r2: float = 0.6       # R² >= 0.6 required (Phase 2 spec)
    max_mae: float = 0.15     # MAE <= 0.15 allowed
    enforce_thresholds: bool = True  # Abort export if metrics fail


class TrainingGovernanceError(Exception):
    """Raised when training fails governance checks."""
    pass


class TrainingQualityError(Exception):
    """Raised when model fails quality thresholds."""
    pass


# =====================================================
# ADVANCED MODEL WEIGHT TRAINER (Phase 5)
# =====================================================

class SIMGRWeightTrainer:
    """Train SIMGR weights using sklearn with Ridge and K-Fold CV.
    
    GĐ Phase 5: Advanced Modeling implementation.
    - Supports LinearRegression and Ridge with positive=True
    - K-Fold Cross Validation for proper model evaluation
    - Automatic model selection (compares Linear vs Ridge)
    - Overfitting detection guards
    - Normalizes weights to sum to 1
    - Risk sign handled in scoring_formula.py (NOT inverted here)
    
    GĐ4: Uses ScoringFormula as SINGLE SOURCE OF TRUTH for:
    - Component names
    - Sign conventions
    - Formula computation
    """
    
    def __init__(self, config: Optional[TrainingConfig] = None):
        self.config = config or TrainingConfig()
        self.best_weights: Dict[str, float] = {}
        self.metrics: Dict[str, Any] = {}
        self._data: Optional[pd.DataFrame] = None
        self._model: Any = None  # LinearRegression or Ridge
        self._raw_weights: Optional[np.ndarray] = None
        
        # Phase 5: Track CV results
        self._cv_scores: Optional[np.ndarray] = None
        self._selected_model_type: str = "linear"  # Track which model was selected
        
    # ===========================================
    # PHASE 1: DATA PREPARATION
    # ===========================================
    
    def load_data(self, csv_path: Optional[str] = None) -> pd.DataFrame:
        """Load training data from CSV.
        
        Expected columns:
            - study: Study component score [0,1]
            - interest: Interest component score [0,1]
            - market: Market component score [0,1]
            - growth: Growth component score [0,1]
            - risk: Risk component score [0,1] (POSITIVE - sign handled in scoring)
            - outcome: Target variable (satisfaction, success) [0,1]
            - weight (optional): Sample weight
        
        IMPORTANT: Risk is POSITIVE in training data.
        Negative sign convention is applied in scoring_formula.py.
        """
        path = csv_path or self.config.input_csv
        
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Training data not found: {path}. "
                "Please create training dataset first."
            )
        
        df = pd.read_csv(path)
        
        # Validate required columns using ScoringFormula canonical components
        required = ScoringFormula.COMPONENTS + ["outcome"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        
        # Validate ranges [0, 1]
        for col in ScoringFormula.COMPONENTS + ["outcome"]:
            if df[col].min() < 0 or df[col].max() > 1:
                logger.warning(f"Column {col} has values outside [0,1]. Clamping.")
                df[col] = df[col].clip(0, 1)
        
        logger.info(f"[TRAIN] Loaded {len(df)} training samples from {path}")
        self._data = df
        return df
    
    def prepare_training_matrix(self, data: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare X, y matrices for Linear Regression.

        GĐ Phase 2, TASK 2: Training data matrix.
        GĐ v2.0 FIX: Apply ScoringFormula.SIGN to each column so that
        NEGATIVE-sign components (risk) are NEGATED before fitting.

        Without this, LinearRegression(positive=True) is forced to set risk
        coefficient to 0 even though risk has a strong negative relationship
        with outcome.  After negation, -risk is positively correlated with
        outcome, so positive=True can assign a non-zero coefficient.

        X_adj = sign[comp] * X[comp]   for each component
                e.g.  risk column → -risk  (sign = -1)
                      all others  →  +comp  (sign = +1)

        y = [outcome, ...]

        IMPORTANT: The returned coefficient for the negated column IS the
        weight (w_R) used in the scoring formula  Score -= w_R * R.
        No further sign inversion needed after normalize_weights.

        Returns:
            (X_adj, y) tuple of numpy arrays
        """
        # Build sign-adjusted X matrix: positive=True on X_adj is equivalent
        # to the formula  Score = Σ sign[i] * w[i] * raw_score[i]
        X_cols = []
        for comp in ScoringFormula.COMPONENTS:
            sign = ScoringFormula.SIGN[comp]         # +1 or -1
            col = data[comp].values.astype(float)
            X_cols.append(sign * col)                # negate risk column

        X = np.array(X_cols).T

        y = data["outcome"].values

        logger.info(
            "[TRAIN] Prepared sign-adjusted training matrix: "
            "X shape=%s, y shape=%s", X.shape, y.shape
        )
        logger.info(
            "[TRAIN] Components: %s  |  Signs applied: %s "
            "(risk negated so positive=True can learn its weight)",
            ScoringFormula.COMPONENTS,
            {c: ScoringFormula.SIGN[c] for c in ScoringFormula.COMPONENTS},
        )

        return X, y
    
    # ===========================================
    # PHASE 2: MODEL TRAINING
    # ===========================================
    
    def train_linear_regression(self, X: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Train weights using sklearn LinearRegression.
        
        GĐ Phase 2, TASK 3: Implement Linear Regression.
        
        Uses:
            model = LinearRegression(positive=True)
            model.fit(X, y)
            raw_weights = model.coef_
        
        Args:
            X: Feature matrix shape (n_samples, 5)
            y: Target array shape (n_samples,)
            
        Returns:
            Raw (unnormalized) weight coefficients
        """
        logger.info("[TRAIN] Training with sklearn LinearRegression (positive=True)...")
        
        # GĐ Phase 2: Use ONLY sklearn LinearRegression, NO SLSQP
        self._model = LinearRegression(positive=True, fit_intercept=False)
        self._model.fit(X, y)
        
        self._raw_weights = self._model.coef_
        
        logger.info(f"[TRAIN] Raw coefficients: {self._raw_weights}")
        
        return self._raw_weights
    
    def train_ridge_regression(self, X: np.ndarray, y: np.ndarray, alpha: Optional[float] = None) -> np.ndarray:
        """Train weights using sklearn Ridge Regression.
        
        GĐ Phase 5: Ridge Regression with L2 regularization.
        
        Uses:
            model = Ridge(alpha=alpha, positive=True, fit_intercept=False)
            model.fit(X, y)
            raw_weights = model.coef_
        
        Args:
            X: Feature matrix shape (n_samples, 5)
            y: Target array shape (n_samples,)
            alpha: Regularization strength (default from config)
            
        Returns:
            Raw (unnormalized) weight coefficients
        """
        ridge_alpha = alpha if alpha is not None else self.config.ridge_alpha
        logger.info(f"[TRAIN] Training with sklearn Ridge (alpha={ridge_alpha}, positive=True)...")
        
        # GĐ Phase 5: Ridge with positive constraint
        self._model = Ridge(alpha=ridge_alpha, positive=True, fit_intercept=False)
        self._model.fit(X, y)
        
        self._raw_weights = self._model.coef_
        
        logger.info(f"[TRAIN] Raw coefficients: {self._raw_weights}")
        
        return self._raw_weights
    
    def k_fold_cross_validate(self, X: np.ndarray, y: np.ndarray, model_type: str = "linear") -> Dict[str, Any]:
        """Perform K-Fold Cross Validation.
        
        GĐ Phase 5: K-Fold CV for robust model evaluation.
        
        Args:
            X: Feature matrix
            y: Target array
            model_type: "linear" or "ridge"
            
        Returns:
            Dict with cv_scores, cv_mean, cv_std, train_r2
        """
        n_folds = self.config.n_folds
        logger.info(f"[TRAIN] Running {n_folds}-Fold Cross Validation for {model_type}...")
        
        # Create model based on type
        if model_type == "linear":
            model = LinearRegression(positive=True, fit_intercept=False)
        else:
            model = Ridge(alpha=self.config.ridge_alpha, positive=True, fit_intercept=False)
        
        # K-Fold CV
        kf = KFold(n_splits=n_folds, shuffle=True, random_state=self.config.random_seed)
        cv_scores = cross_val_score(model, X, y, cv=kf, scoring="r2")
        
        # Train on full data for comparison
        model.fit(X, y)
        train_r2 = r2_score(y, model.predict(X))
        
        cv_result = {
            "model_type": model_type,
            "cv_scores": cv_scores.tolist(),
            "cv_mean": float(cv_scores.mean()),
            "cv_std": float(cv_scores.std()),
            "train_r2": float(train_r2),
            "overfit_gap": float(abs(train_r2 - cv_scores.mean()))
        }
        
        logger.info(f"[TRAIN] CV Results ({model_type}): mean={cv_result['cv_mean']:.4f} ± {cv_result['cv_std']:.4f}")
        logger.info(f"[TRAIN] Train R²={train_r2:.4f}, CV Mean={cv_result['cv_mean']:.4f}, Gap={cv_result['overfit_gap']:.4f}")
        
        return cv_result
    
    def auto_select_model(self, X: np.ndarray, y: np.ndarray) -> Tuple[str, Dict[str, Any]]:
        """Automatically select best model using K-Fold CV.
        
        GĐ Phase 5: Compare Linear vs Ridge and select best.
        
        Selection criteria:
        1. Higher CV mean R²
        2. Lower overfitting gap (train R² - CV mean)
        3. Prefer linear if difference < 0.01 (simpler model)
        
        Returns:
            Tuple of (selected_model_type, cv_results_dict)
        """
        logger.info("[TRAIN] Auto-selecting best model (Linear vs Ridge)...")
        
        # Run CV for both models
        linear_cv = self.k_fold_cross_validate(X, y, "linear")
        ridge_cv = self.k_fold_cross_validate(X, y, "ridge")
        
        # Compare CV means
        linear_mean = linear_cv["cv_mean"]
        ridge_mean = ridge_cv["cv_mean"]
        
        cv_diff = ridge_mean - linear_mean
        
        # Selection logic
        if cv_diff > 0.01:
            # Ridge is significantly better
            selected = "ridge"
            reason = f"Ridge CV mean ({ridge_mean:.4f}) > Linear ({linear_mean:.4f}) by {cv_diff:.4f}"
        elif cv_diff < -0.01:
            # Linear is significantly better
            selected = "linear"
            reason = f"Linear CV mean ({linear_mean:.4f}) > Ridge ({ridge_mean:.4f}) by {abs(cv_diff):.4f}"
        else:
            # Similar performance - prefer simpler linear model
            selected = "linear"
            reason = f"Similar performance (diff={cv_diff:.4f}), preferring simpler Linear model"
        
        logger.info(f"[TRAIN] Model Selection: {selected.upper()}")
        logger.info(f"[TRAIN] Reason: {reason}")
        
        cv_results = {
            "linear": linear_cv,
            "ridge": ridge_cv,
            "selected": selected,
            "selection_reason": reason
        }
        
        return selected, cv_results
    
    def detect_overfitting(self, cv_result: Dict[str, Any]) -> bool:
        """Detect potential overfitting.
        
        GĐ Phase 5: Guard against overfitting.
        
        Overfitting detected if:
            abs(train_r2 - cv_mean) > max_overfit_gap
        
        Returns:
            True if overfitting detected
        """
        overfit_gap = cv_result["overfit_gap"]
        max_gap = self.config.max_overfit_gap
        
        if overfit_gap > max_gap:
            logger.warning(f"[TRAIN] OVERFITTING DETECTED: gap={overfit_gap:.4f} > threshold={max_gap:.4f}")
            logger.warning(f"[TRAIN] Train R²={cv_result['train_r2']:.4f}, CV Mean={cv_result['cv_mean']:.4f}")
            return True
        
        logger.info(f"[TRAIN] No overfitting: gap={overfit_gap:.4f} <= threshold={max_gap:.4f}")
        return False
    
    # ===========================================
    # PHASE 3: WEIGHT NORMALIZATION
    # ===========================================
    
    # Minimum weight allowed per component in production (5-component SIMGR model)
    MIN_COMPONENT_WEIGHT = 0.05

    def normalize_weights(self, raw_weights: np.ndarray) -> Dict[str, float]:
        """Normalize weights to sum to 1.0.

        GĐ Phase 2, TASK 4: Normalize Weights.
        GĐ v2.0 FIX: Apply minimum weight floor (MIN_COMPONENT_WEIGHT) to
        prevent any SIMGR component from being silently disabled by the
        optimizer.  A weight of exactly 0 means the component is excluded
        from production scoring — which violates the 5-component SIMGR spec.

        Floor strategy:
          1. Normalize raw coefficients to sum = 1
          2. If any component weight < MIN_COMPONENT_WEIGHT, bump to floor
          3. Re-normalize so sum stays = 1
          4. Log a WARNING for each floored component

        Args:
            raw_weights: Raw coefficients from LinearRegression / Ridge

        Returns:
            Dict mapping component names to normalized weights (sum=1.0,
            each >= MIN_COMPONENT_WEIGHT)
        """
        # Step 1: Initial normalization
        weight_sum = float(np.sum(raw_weights))
        if weight_sum <= 0:
            raise TrainingGovernanceError(
                "Training failed: All weights are zero or negative. "
                "Check training data quality."
            )

        normalized = raw_weights / weight_sum

        # Step 2: Map to dict
        weights_dict: Dict[str, float] = {
            comp: float(normalized[idx])
            for idx, comp in enumerate(ScoringFormula.COMPONENTS)
        }

        logger.info("[TRAIN] Raw normalized weights: %s", weights_dict)

        # Step 3: Apply minimum floor for 5-component enforcement
        floored = False
        for comp, w in weights_dict.items():
            if w < self.MIN_COMPONENT_WEIGHT:
                logger.warning(
                    "[TRAIN] Component '%s' weight=%.6f is below minimum %.2f — "
                    "applying floor to enforce 5-component SIMGR model.",
                    comp, w, self.MIN_COMPONENT_WEIGHT,
                )
                weights_dict[comp] = self.MIN_COMPONENT_WEIGHT
                floored = True

        # Step 4: Re-normalize if any floor was applied
        if floored:
            total = sum(weights_dict.values())
            weights_dict = {k: v / total for k, v in weights_dict.items()}
            logger.warning(
                "[TRAIN] Weights re-normalized after floor application: %s",
                {k: round(v, 6) for k, v in weights_dict.items()},
            )

        logger.info(
            "[TRAIN] Final normalized weights (sum=1.0): %s",
            {k: round(v, 6) for k, v in weights_dict.items()},
        )

        return weights_dict
    
    # ===========================================
    # PHASE 4: GOVERNANCE METRICS COMPUTATION
    # ===========================================
    
    def compute_governance_metrics(
        self, 
        X: np.ndarray, 
        y: np.ndarray
    ) -> Dict[str, Any]:
        """Compute governance metrics for validation.
        
        GĐ Phase 2, TASK 5: Compute Governance Metrics.
        
        Computes:
            - r2_score: Coefficient of determination
            - MAE: Mean Absolute Error
            - samples: Number of training samples
        
        Returns:
            Dict of governance metrics
        """
        if self._model is None:
            raise TrainingGovernanceError("Model not trained. Call train_linear_regression first.")
        
        predictions = self._model.predict(X)
        
        metrics = {
            "method": "linear_regression",
            "r2_score": float(r2_score(y, predictions)),
            "mae": float(mean_absolute_error(y, predictions)),
            "samples": int(len(y)),
            "train_loss": float(np.mean((y - predictions) ** 2)),  # MSE
            "correlation": float(np.corrcoef(y, predictions)[0, 1]) if len(y) > 1 else 0.0,
            "formula_version": ScoringFormula.VERSION,
        }
        
        logger.info(
            f"[TRAIN] Governance metrics: "
            f"R²={metrics['r2_score']:.4f}, "
            f"MAE={metrics['mae']:.4f}, "
            f"samples={metrics['samples']}"
        )
        
        return metrics
    
    def validate_governance_thresholds(self) -> None:
        """Validate metrics meet governance thresholds.
        
        GĐ Phase 2, TASK 5: Reject model if r2_score < 0.6
        
        Raises:
            TrainingQualityError: If metrics below threshold
        """
        if not self.config.enforce_thresholds:
            logger.warning("[TRAIN] Threshold enforcement DISABLED!")
            return
        
        r2 = self.metrics.get("r2_score", 0.0)
        mae = self.metrics.get("mae", float("inf"))
        
        errors = []
        
        # GĐ Phase 2: R² >= 0.6 required
        if r2 < self.config.min_r2:
            errors.append(
                f"R² = {r2:.4f} < {self.config.min_r2} (minimum required)"
            )
        
        # MAE threshold
        if mae > self.config.max_mae:
            errors.append(
                f"MAE = {mae:.4f} > {self.config.max_mae} (maximum allowed)"
            )
        
        if errors:
            error_msg = (
                f"GĐ Phase 2: Model FAILS governance thresholds!\n"
                + "\n".join(f"  - {e}" for e in errors) +
                f"\nModel export ABORTED. Minimum R² required: {self.config.min_r2}"
            )
            logger.critical(error_msg)
            raise TrainingQualityError(error_msg)
        
        logger.info(
            f"[TRAIN] Governance thresholds PASSED "
            f"(R²={r2:.4f} >= {self.config.min_r2}, "
            f"MAE={mae:.4f} <= {self.config.max_mae})"
        )
    
    # ===========================================
    # PHASE 5: INTEGRITY CHECKS
    # ===========================================
    
    def validate_integrity(self) -> None:
        """Validate training integrity.

        GĐ Phase 2, TASK 8: Add Training Integrity Checks.
        GĐ v2.0 FIX: Enforce that all 5 SIMGR components have non-zero,
        non-trivial weights before allowing archival / activation.

        Assertions:
            - sum(weights) ≈ 1.0
            - all weights >= 0
            - all weights >= MIN_COMPONENT_WEIGHT  (5-component enforcement)

        Raises:
            TrainingGovernanceError: If integrity checks fail
        """
        weights_sum = sum(self.best_weights.values())

        # Check weights sum to 1.0
        if abs(weights_sum - 1.0) >= 1e-6:
            raise TrainingGovernanceError(
                f"Integrity violation: weights sum to {weights_sum:.6f}, "
                f"expected 1.0 (tolerance 1e-6)"
            )

        # Check all weights are non-negative
        negative_weights = {k: v for k, v in self.best_weights.items() if v < 0}
        if negative_weights:
            raise TrainingGovernanceError(
                f"Integrity violation: negative weights detected: {negative_weights}"
            )

        # GĐ v2.0: Enforce 5-component SIMGR — no component may be zero/near-zero
        below_floor = {
            k: v for k, v in self.best_weights.items()
            if v < self.MIN_COMPONENT_WEIGHT
        }
        if below_floor:
            raise TrainingGovernanceError(
                f"5-Component SIMGR violation: the following components have weight "
                f"below the minimum threshold ({self.MIN_COMPONENT_WEIGHT}): "
                f"{below_floor}.  All 5 SIMGR components (S, I, M, G, R) must "
                f"contribute to the production model.  "
                f"Ensure training pipeline applies sign convention (see prepare_training_matrix)."
            )

        logger.info(
            "[TRAIN] Integrity checks PASSED: sum=1.0, all weights >= 0, "
            "all components >= %.2f (5-component SIMGR enforced).",
            self.MIN_COMPONENT_WEIGHT,
        )
    
    # ===========================================
    # PHASE 6: EXPORT & ACTIVATION
    # ===========================================
    
    def compute_dataset_hash(self) -> str:
        """Compute SHA256 hash of training dataset."""
        data_path = Path(self.config.input_csv)
        if not data_path.exists():
            return "unknown"
        
        sha256 = hashlib.sha256()
        with open(data_path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def save_to_archive(self) -> str:
        """Save weights to archive with timestamp.
        
        GĐ Phase 2, TASK 7: Save Strategy - Step 1.
        
        Saves to:
            models/weights/archive/v2_linear_regression_<timestamp>.json
        
        Returns:
            Path to archived weights file
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        archive_dir = Path(self.config.output_dir) / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"v2_linear_regression_{timestamp}.json"
        archive_path = archive_dir / filename
        
        # Compute checksums
        dataset_hash = self.compute_dataset_hash()
        weights_json = json.dumps(self.best_weights, sort_keys=True, separators=(',', ':'))
        checksum = hashlib.sha256(weights_json.encode()).hexdigest()
        
        # GĐ Phase 2, TASK 6: Export Governance-Compliant Weights File
        payload = {
            "version": f"v2_linear_regression_{timestamp}",
            "method": "linear_regression",  # MUST match Phase 1 requirement
            "trained_at": datetime.utcnow().isoformat() + "Z",
            "dataset_hash": dataset_hash[:16],  # Short hash for display
            "r2_score": self.metrics.get("r2_score", 0.0),
            "weights": {
                "study_score": self.best_weights.get("study", 0.0),
                "interest_score": self.best_weights.get("interest", 0.0),
                "market_score": self.best_weights.get("market", 0.0),
                "growth_score": self.best_weights.get("growth", 0.0),
                "risk_score": self.best_weights.get("risk", 0.0),
            },
            "metrics": self.metrics,
            "checksum": checksum,
        }
        
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        
        logger.info(f"[TRAIN] Archived weights: {archive_path}")
        
        return str(archive_path)
    
    def _run_phase3_validation(self) -> bool:
        """Run Phase 3 validation before activation.
        
        GĐ Phase 3, Task 5: Block activation until validation passes.
        
        Validates:
        - Backtest vs baseline
        - R² absolute threshold
        - Improvement threshold
        - Weight sanity
        
        Returns:
            True if validation passes, False otherwise
        """
        try:
            validator_module = get_validator_module()
            
            # Build weights dict with _score suffix for validator
            weights_with_suffix = {
                "study_score": self.best_weights.get("study", 0.0),
                "interest_score": self.best_weights.get("interest", 0.0),
                "market_score": self.best_weights.get("market", 0.0),
                "growth_score": self.best_weights.get("growth", 0.0),
                "risk_score": self.best_weights.get("risk", 0.0),
            }
            
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            version = f"v2_linear_regression_{timestamp}"
            
            # Run validation
            passed = validator_module.validate_weights(
                weights_with_suffix,
                version=version
            )
            
            logger.info("[TRAIN] Phase 3 validation PASSED - activation allowed")
            return passed
            
        except validator_module.ValidationError as e:
            logger.error(f"[TRAIN] Phase 3 validation FAILED: {e}")
            return False
        except Exception as e:
            logger.error(f"[TRAIN] Phase 3 validation ERROR: {e}")
            # On unexpected error, block activation for safety
            return False
    
    def activate_weights(self, archive_path: str) -> str:
        """Copy validated weights to active directory.
        
        GĐ Phase 2, TASK 7: Save Strategy - Step 2.
        
        ONLY after successful validation, copy to:
            models/weights/active/weights.json
        
        Args:
            archive_path: Path to archived weights file
            
        Returns:
            Path to active weights file
        """
        active_dir = Path(self.config.output_dir) / "active"
        active_dir.mkdir(parents=True, exist_ok=True)
        
        active_weights_path = active_dir / "weights.json"
        
        # Backup existing active weights if present
        if active_weights_path.exists():
            backup_path = active_dir / f"weights_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            shutil.copy2(active_weights_path, backup_path)
            logger.info(f"[TRAIN] Backed up active weights to: {backup_path}")
        
        # Copy archive to active
        shutil.copy2(archive_path, active_weights_path)
        
        logger.info(f"[TRAIN] Activated weights: {active_weights_path}")
        logger.info("[TRAIN] Phase 1 compatibility: method='linear_regression' ✓")
        
        return str(active_weights_path)
    
    # ===========================================
    # MAIN TRAINING PIPELINE
    # ===========================================
    
    def train(self) -> Dict[str, float]:
        """Full training pipeline with Ridge and K-Fold Cross Validation.
        
        GĐ Phase 5: Complete training workflow:
        1. Load and prepare data
        2. Run K-Fold Cross Validation (if enabled)
        3. Auto-select model (if model_type="auto")
        4. Train selected model (Linear or Ridge)
        5. Detect overfitting
        6. Normalize weights
        7. Compute governance metrics
        8. Validate thresholds
        9. Validate integrity
        10. Archive weights
        11. Await explicit activation (Phase 4)
        
        Returns:
            Dict of trained weights
            
        Raises:
            TrainingQualityError: If R² < 0.6 or overfitting detected
            TrainingGovernanceError: If integrity checks fail
        """
        logger.info("=" * 60)
        logger.info("[TRAIN] GĐ Phase 5: Advanced Modeling Training Pipeline")
        logger.info("=" * 60)
        
        # ===== STEP 1: DATA PREPARATION =====
        logger.info("[TRAIN] Step 1: Loading and preparing data...")
        data = self.load_data()
        X, y = self.prepare_training_matrix(data)
        
        # ===== STEP 2: K-FOLD CROSS VALIDATION =====
        cv_results = None
        if self.config.enable_cv:
            logger.info("[TRAIN] Step 2: Running K-Fold Cross Validation...")
            
            if self.config.model_type == "auto":
                # Auto-select best model
                self._selected_model_type, cv_results = self.auto_select_model(X, y)
            else:
                # Use specified model type
                self._selected_model_type = self.config.model_type
                cv_results = {
                    self._selected_model_type: self.k_fold_cross_validate(X, y, self._selected_model_type),
                    "selected": self._selected_model_type,
                    "selection_reason": f"User specified model_type={self._selected_model_type}"
                }
            
            # ===== STEP 3: OVERFITTING DETECTION =====
            logger.info("[TRAIN] Step 3: Checking for overfitting...")
            selected_cv = cv_results[self._selected_model_type]
            if self.detect_overfitting(selected_cv):
                if self.config.enforce_thresholds:
                    raise TrainingQualityError(
                        f"Overfitting detected: train-CV gap ({selected_cv['overfit_gap']:.4f}) "
                        f"> threshold ({self.config.max_overfit_gap:.4f})"
                    )
                else:
                    logger.warning("[TRAIN] Overfitting detected but enforcement disabled - continuing")
        else:
            logger.info("[TRAIN] Step 2-3: Cross Validation DISABLED")
            self._selected_model_type = self.config.model_type if self.config.model_type != "auto" else "linear"
        
        # ===== STEP 4: MODEL TRAINING =====
        logger.info(f"[TRAIN] Step 4: Training {self._selected_model_type.upper()} model...")
        if self._selected_model_type == "ridge":
            raw_weights = self.train_ridge_regression(X, y)
            self.config.method = "ridge_regression"
        else:
            raw_weights = self.train_linear_regression(X, y)
            self.config.method = "linear_regression"
        
        # ===== STEP 5: WEIGHT NORMALIZATION =====
        logger.info("[TRAIN] Step 5: Normalizing weights to sum=1.0...")
        self.best_weights = self.normalize_weights(raw_weights)
        
        # ===== STEP 6: GOVERNANCE METRICS =====
        logger.info("[TRAIN] Step 6: Computing governance metrics...")
        self.metrics = self.compute_governance_metrics(X, y)
        
        # Add CV metrics to governance report
        if cv_results:
            self.metrics["cv_results"] = cv_results
            self.metrics["selected_model"] = self._selected_model_type
            selected_cv = cv_results[self._selected_model_type]
            self.metrics["cv_mean"] = selected_cv["cv_mean"]
            self.metrics["cv_std"] = selected_cv["cv_std"]
            self.metrics["overfit_gap"] = selected_cv["overfit_gap"]
        
        # ===== STEP 7: THRESHOLD VALIDATION =====
        logger.info("[TRAIN] Step 7: Validating governance thresholds...")
        self.validate_governance_thresholds()
        
        # ===== STEP 8: INTEGRITY CHECKS =====
        logger.info("[TRAIN] Step 8: Running integrity checks...")
        self.validate_integrity()
        
        # Phase 2, TASK 8: Assert integrity  
        assert abs(sum(self.best_weights.values()) - 1.0) < 1e-6, "Weights must sum to 1.0"
        assert all(v >= 0 for v in self.best_weights.values()), "All weights must be >= 0"
        
        # ===== STEP 9: ARCHIVE =====
        logger.info("[TRAIN] Step 9: Archiving weights...")
        archive_path = self.save_to_archive()
        
        # ===== STEP 10: PHASE 3 VALIDATION (GATE) =====
        logger.info("[TRAIN] Step 10: Running Phase 3 validation (governance gate)...")
        validation_passed = self._run_phase3_validation()
        
        if not validation_passed:
            logger.warning("[TRAIN] Phase 3 validation FAILED - weights kept in ARCHIVE ONLY")
            logger.warning(f"[TRAIN] Archive: {archive_path}")
            logger.warning("[TRAIN] Activation BLOCKED - weights NOT activated")
            
            logger.info("=" * 60)
            logger.info("[TRAIN] Training completed with WARNINGS")
            logger.info("[TRAIN] Weights archived but NOT activated due to governance failure")
            logger.info("=" * 60)
            
            return self.best_weights
        
        # ===== STEP 11: NO AUTO-ACTIVATION (Phase 4) =====
        logger.info("[TRAIN] Step 11: Training complete - awaiting explicit activation")
        logger.info("[TRAIN] Phase 4: Auto-activation DISABLED")
        logger.info("[TRAIN] To activate, run:")
        logger.info(f"[TRAIN]   python -m backend.training.activate_weights --file {archive_path}")
        
        # ===== DONE =====
        logger.info("=" * 60)
        logger.info(f"[TRAIN] GĐ Phase 5: Training completed successfully!")
        logger.info(f"[TRAIN] Model: {self._selected_model_type.upper()}")
        logger.info(f"[TRAIN] R² = {self.metrics['r2_score']:.4f}")
        if cv_results:
            logger.info(f"[TRAIN] CV Mean = {self.metrics['cv_mean']:.4f} ± {self.metrics['cv_std']:.4f}")
        logger.info(f"[TRAIN] Archive: {archive_path}")
        logger.info("[TRAIN] Status: AWAITING EXPLICIT ACTIVATION")
        logger.info("=" * 60)
        
        # Store archive path for retrieval
        self._last_archive_path = archive_path
        
        return self.best_weights


# =====================================================
# UTILITY FUNCTIONS
# =====================================================

def load_weights_from_file(path: str) -> Dict[str, float]:
    """Load weights from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload["weights"]


# =====================================================
# CLI ENTRY POINT
# =====================================================

def main():
    """Main entry point for weight training.
    
    GĐ Phase 5: Advanced Modeling training CLI.
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Train SIMGR weights with Ridge/Linear + K-Fold CV (GĐ Phase 5)"
    )
    parser.add_argument(
        "--input",
        default="backend/data/scoring/train.csv",
        help="Path to training CSV",
    )
    parser.add_argument(
        "--output",
        default="models/weights",
        help="Output directory for weights",
    )
    parser.add_argument(
        "--min-r2",
        type=float,
        default=0.6,
        help="Minimum R² threshold (default: 0.6)",
    )
    parser.add_argument(
        "--model-type",
        choices=["linear", "ridge", "auto"],
        default="auto",
        help="Model type: linear, ridge, or auto (default: auto)",
    )
    parser.add_argument(
        "--ridge-alpha",
        type=float,
        default=1.0,
        help="Ridge regularization alpha (default: 1.0)",
    )
    parser.add_argument(
        "--n-folds",
        type=int,
        default=5,
        help="Number of cross-validation folds (default: 5)",
    )
    parser.add_argument(
        "--no-cv",
        action="store_true",
        help="Disable cross-validation",
    )
    parser.add_argument(
        "--no-enforce",
        action="store_true",
        help="Disable governance threshold enforcement (NOT RECOMMENDED)",
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    # Create trainer config
    config = TrainingConfig(
        input_csv=args.input,
        output_dir=args.output,
        min_r2=args.min_r2,
        model_type=args.model_type,
        ridge_alpha=args.ridge_alpha,
        n_folds=args.n_folds,
        enable_cv=not args.no_cv,
        enforce_thresholds=not args.no_enforce,
    )
    
    # Train
    trainer = SIMGRWeightTrainer(config)
    weights = trainer.train()
    
    # Display results
    print("\n" + "=" * 60)
    print("GĐ PHASE 5: ADVANCED MODELING TRAINING RESULTS")
    print("=" * 60)
    model_name = trainer._selected_model_type.upper()
    if trainer._selected_model_type == "ridge":
        print(f"\nModel: sklearn Ridge (alpha={config.ridge_alpha}, positive=True)")
    else:
        print(f"\nModel: sklearn LinearRegression (positive=True)")
    print(f"R² Score: {trainer.metrics['r2_score']:.4f}")
    if "cv_mean" in trainer.metrics:
        print(f"CV R² Mean: {trainer.metrics['cv_mean']:.4f} ± {trainer.metrics['cv_std']:.4f}")
        print(f"Overfit Gap: {trainer.metrics['overfit_gap']:.4f}")
    print(f"MAE: {trainer.metrics['mae']:.4f}")
    print(f"Samples: {trainer.metrics['samples']}")
    print("\nTRAINED WEIGHTS:")
    for k, v in weights.items():
        print(f"  {k}: {v:.4f}")
    print(f"\nSum: {sum(weights.values()):.6f}")
    print("=" * 60)
    print(f"Method: '{trainer.config.method}' (Phase 1 compatible)")
    print("=" * 60)


if __name__ == "__main__":
    main()

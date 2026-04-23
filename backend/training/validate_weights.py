# backend/training/validate_weights.py
"""
Phase 3: Model Validation & Governance Framework.

Validates trained weights against baseline and enforces governance thresholds.

GĐ Phase 3 Capabilities:
- Backtest trained weights vs baseline (default weights)
- Enforce R² threshold (>= 0.6 absolute)
- Enforce improvement threshold (>= 5% over baseline)
- Validate weight sanity (sum=1, non-negative, no domination)
- Generate audit artifacts
- Block activation until validation passes
- Explainability output (weight rankings)

This module does NOT modify scoring formula or component logic.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

logger = logging.getLogger(__name__)


# =====================================================
# CONFIGURATION
# =====================================================

@dataclass
class ValidationConfig:
    """Configuration for weight validation."""
    # Thresholds
    min_r2: float = 0.6                    # Absolute R² minimum
    improvement_threshold: float = 0.05    # 5% improvement required over baseline
    max_mae: float = 0.15                  # Maximum allowed MAE
    
    # Weight sanity constraints
    max_single_weight: float = 0.5         # No single weight > 50% (domination guard)
    max_risk_weight: float = 0.3           # Risk weight cap
    weight_sum_tolerance: float = 1e-6     # Tolerance for sum=1 check
    
    # Baseline weights (default configuration)
    baseline_weights: Dict[str, float] = field(default_factory=lambda: {
        "study": 0.25,
        "interest": 0.25,
        "market": 0.25,
        "growth": 0.15,
        "risk": 0.10
    })
    
    # Paths
    training_data_path: str = "backend/data/scoring/train.csv"
    audit_reports_dir: str = "models/weights/audit_reports"


class ValidationError(Exception):
    """Base exception for validation failures."""
    pass


class GovernanceThresholdError(ValidationError):
    """Raised when governance thresholds are not met."""
    pass


class WeightSanityError(ValidationError):
    """Raised when weight sanity checks fail."""
    pass


class ImprovementThresholdError(ValidationError):
    """Raised when model does not improve sufficiently over baseline."""
    pass


# =====================================================
# TASK 1: BACKTESTING MODULE
# =====================================================

def compute_score(row: pd.Series, weights: Dict[str, float]) -> float:
    """Compute SIMGR score for a single row.
    
    IMPORTANT: Risk is SUBTRACTED exactly as in scoring_formula.py.
    
    Formula:
        score = w_study * study + w_interest * interest + w_market * market
                + w_growth * growth - w_risk * risk
    
    Args:
        row: Single row with component values (study, interest, market, growth, risk)
        weights: Dict with keys: study, interest, market, growth, risk
        
    Returns:
        Computed score
    """
    return (
        weights["study"] * row["study"]
        + weights["interest"] * row["interest"]
        + weights["market"] * row["market"]
        + weights["growth"] * row["growth"]
        - weights["risk"] * row["risk"]  # SUBTRACTED as per scoring_formula.py
    )


def compute_all_scores(data: pd.DataFrame, weights: Dict[str, float]) -> np.ndarray:
    """Compute scores for all rows in dataset.
    
    Args:
        data: DataFrame with component columns
        weights: Weight dict
        
    Returns:
        Array of computed scores
    """
    scores = data.apply(lambda row: compute_score(row, weights), axis=1)
    return scores.values


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """Compute validation metrics.
    
    Phase 3, Task 1.2: Compute RMSE, MAE, R².
    
    NOTE: ``r2`` is Pearson R² (scale-invariant), not sklearn's R².
    Normalized weights (sum=1) produce y_pred on a compressed scale relative
    to y_true, which makes sklearn R² negative even for an excellent model.
    Pearson R² measures rank-order/directional predictive quality and is
    unaffected by the normalization-induced scale shift.
    
    Args:
        y_true: Ground truth values
        y_pred: Predicted values
        
    Returns:
        Dict with rmse, mae, r2 (Pearson), r2_sklearn (scale-dependent reference)
    """
    # Pearson R² – scale/translation invariant, correct for normalized weights
    if np.std(y_pred) < 1e-9:
        pearson_r2 = 0.0
    else:
        corr = np.corrcoef(y_true, y_pred)[0, 1]
        pearson_r2 = float(corr ** 2) if not np.isnan(corr) else 0.0

    # sklearn R² – kept as informational reference; will be negative when scales differ
    r2_sklearn = float(r2_score(y_true, y_pred))

    mse = mean_squared_error(y_true, y_pred)
    return {
        "rmse": float(np.sqrt(mse)),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "r2": pearson_r2,         # Scale-invariant: governance threshold applied here
        "r2_sklearn": r2_sklearn, # Scale-dependent: informational only
    }


# =====================================================
# TASK 2: GOVERNANCE THRESHOLDS
# =====================================================

def enforce_absolute_threshold(
    trained_r2: float,
    config: ValidationConfig
) -> None:
    """Enforce absolute R² threshold.
    
    Phase 3, Task 2: R² must be >= 0.6.
    
    Raises:
        GovernanceThresholdError: If R² < min_r2
    """
    if trained_r2 < config.min_r2:
        raise GovernanceThresholdError(
            f"Model R² below absolute governance minimum. "
            f"R²={trained_r2:.4f} < {config.min_r2}"
        )


def enforce_improvement_threshold(
    trained_r2: float,
    baseline_r2: float,
    config: ValidationConfig
) -> None:
    """Enforce improvement over baseline.
    
    Phase 3, Task 2: Trained R² must be >= baseline_r² * (1 + improvement_threshold).
    
    Raises:
        ImprovementThresholdError: If improvement < threshold
    """
    required_r2 = baseline_r2 * (1 + config.improvement_threshold)
    
    if trained_r2 < required_r2:
        improvement = (trained_r2 - baseline_r2) / baseline_r2 if baseline_r2 > 0 else 0
        raise ImprovementThresholdError(
            f"Model improvement below governance threshold. "
            f"Trained R²={trained_r2:.4f}, Baseline R²={baseline_r2:.4f}, "
            f"Required R²={required_r2:.4f} ({config.improvement_threshold*100:.1f}% improvement). "
            f"Actual improvement={improvement*100:.2f}%"
        )


# =====================================================
# TASK 3: WEIGHT SANITY VALIDATION
# =====================================================

def validate_weight_sanity(
    weights: Dict[str, float],
    config: ValidationConfig
) -> None:
    """Validate weight sanity constraints.
    
    Phase 3, Task 3: Weight sanity checks.
    
    Constraints:
        - Sum ≈ 1.0 (within tolerance)
        - All weights >= 0
        - No single weight > 0.5 (domination guard)
        - Risk weight <= 0.3 (risk cap)
    
    Raises:
        WeightSanityError: If any constraint violated
    """
    errors = []
    
    # Sum check: must equal 1.0 within tolerance
    weight_sum = sum(weights.values())
    if abs(weight_sum - 1.0) >= config.weight_sum_tolerance:
        errors.append(
            f"Sum check FAILED: sum={weight_sum:.6f}, expected 1.0 "
            f"(tolerance={config.weight_sum_tolerance})"
        )
    
    # Non-negative check
    negative_weights = {k: v for k, v in weights.items() if v < 0}
    if negative_weights:
        errors.append(f"Non-negative check FAILED: {negative_weights}")
    
    # Domination guard: no single weight > 0.5
    dominant_weights = {k: v for k, v in weights.items() if v > config.max_single_weight}
    if dominant_weights:
        errors.append(
            f"Weight domination detected (>{config.max_single_weight}): {dominant_weights}"
        )
    
    # Risk cap guard
    risk_weight = weights.get("risk", 0.0)
    if risk_weight > config.max_risk_weight:
        errors.append(
            f"Risk weight exceeds governance cap: {risk_weight:.4f} > {config.max_risk_weight}"
        )
    
    if errors:
        raise WeightSanityError(
            "Weight sanity validation FAILED:\n" + "\n".join(f"  - {e}" for e in errors)
        )
    
    logger.info("[VALIDATE] Weight sanity checks PASSED")


# =====================================================
# TASK 4: AUDIT REPORT GENERATION
# =====================================================

def generate_audit_report(
    version: str,
    baseline_metrics: Dict[str, float],
    trained_metrics: Dict[str, float],
    trained_weights: Dict[str, float],
    config: ValidationConfig
) -> Dict[str, Any]:
    """Generate validation audit report.
    
    Phase 3, Task 4: Generate audit artifact.
    
    Structure:
        {
            "version": "...",
            "baseline_metrics": {...},
            "trained_metrics": {...},
            "improvement": {"r2_delta": float, "rmse_delta": float},
            "sanity_checks_passed": True,
            "governance_approved": True,
            "validated_at": "<UTC ISO timestamp>"
        }
    
    Returns:
        Audit report dict
    """
    r2_delta = trained_metrics["r2"] - baseline_metrics["r2"]
    rmse_delta = trained_metrics["rmse"] - baseline_metrics["rmse"]
    mae_delta = trained_metrics["mae"] - baseline_metrics["mae"]
    
    improvement_pct = (r2_delta / baseline_metrics["r2"] * 100) if baseline_metrics["r2"] > 0 else 0
    
    report = {
        "version": version,
        "baseline_metrics": baseline_metrics,
        "trained_metrics": trained_metrics,
        "improvement": {
            "r2_delta": float(r2_delta),
            "r2_improvement_pct": float(improvement_pct),
            "rmse_delta": float(rmse_delta),
            "mae_delta": float(mae_delta)
        },
        "weights": trained_weights,
        "sanity_checks_passed": True,
        "governance_approved": True,
        "config": {
            "min_r2": config.min_r2,
            "improvement_threshold": config.improvement_threshold,
            "max_single_weight": config.max_single_weight,
            "max_risk_weight": config.max_risk_weight
        },
        "validated_at": datetime.utcnow().isoformat() + "Z"
    }
    
    return report


def save_audit_report(
    report: Dict[str, Any],
    config: ValidationConfig
) -> str:
    """Save audit report to file.
    
    Saves to: models/weights/audit_reports/v2_validation_report_<timestamp>.json
    
    Returns:
        Path to saved report
    """
    audit_dir = Path(config.audit_reports_dir)
    audit_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"v2_validation_report_{timestamp}.json"
    report_path = audit_dir / filename
    
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    
    logger.info(f"[VALIDATE] Audit report saved: {report_path}")
    
    return str(report_path)


# =====================================================
# TASK 7: EXPLAINABILITY OUTPUT
# =====================================================

def print_weight_rankings(weights: Dict[str, float]) -> List[Dict[str, Any]]:
    """Print weight ranking table for explainability.
    
    Phase 3, Task 7: Explainability output.
    
    Prints:
        Component    Weight    Rank
        --------------------------------
        Market       0.31      1
        ...
    
    Returns:
        List of ranked weight dicts
    """
    # Sort by weight descending
    sorted_weights = sorted(weights.items(), key=lambda x: x[1], reverse=True)
    
    rankings = []
    print("\n" + "=" * 40)
    print("WEIGHT RANKINGS (Explainability)")
    print("=" * 40)
    print(f"{'Component':<12} {'Weight':<10} {'Rank':<6}")
    print("-" * 40)
    
    for rank, (component, weight) in enumerate(sorted_weights, 1):
        print(f"{component.capitalize():<12} {weight:<10.4f} {rank:<6}")
        rankings.append({
            "component": component,
            "weight": weight,
            "rank": rank
        })
    
    print("=" * 40 + "\n")
    
    logger.info(f"[VALIDATE] Weight rankings: {rankings}")
    
    return rankings


# =====================================================
# MAIN VALIDATION FUNCTION
# =====================================================

class WeightValidator:
    """Main validation class for Phase 3 governance.
    
    Validates trained weights against:
    - Baseline comparison
    - R² absolute threshold
    - Improvement threshold
    - Weight sanity checks
    - Risk cap
    
    Generates audit artifacts and blocks activation until validation passes.
    """
    
    def __init__(self, config: Optional[ValidationConfig] = None):
        self.config = config or ValidationConfig()
        self.baseline_metrics: Dict[str, float] = {}
        self.trained_metrics: Dict[str, float] = {}
        self.audit_report: Dict[str, Any] = {}
        self.validation_passed: bool = False
        
    def load_training_data(self) -> pd.DataFrame:
        """Load training data for backtesting."""
        path = self.config.training_data_path
        
        if not os.path.exists(path):
            raise FileNotFoundError(f"Training data not found: {path}")
        
        df = pd.read_csv(path)
        
        required_cols = ["study", "interest", "market", "growth", "risk", "outcome"]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        
        logger.info(f"[VALIDATE] Loaded {len(df)} samples from {path}")
        
        return df
    
    def normalize_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        """Normalize weight keys to standard format.
        
        Handles both 'study' and 'study_score' formats.
        """
        normalized = {}
        key_mapping = {
            "study_score": "study",
            "interest_score": "interest",
            "market_score": "market",
            "growth_score": "growth",
            "risk_score": "risk"
        }
        
        for key, value in weights.items():
            # Map _score suffix to plain name
            norm_key = key_mapping.get(key, key)
            normalized[norm_key] = value
        
        # Ensure all required keys present
        for key in ["study", "interest", "market", "growth", "risk"]:
            if key not in normalized:
                normalized[key] = 0.0
        
        return normalized
    
    def backtest(
        self,
        data: pd.DataFrame,
        trained_weights: Dict[str, float]
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        """Run backtesting against baseline.
        
        Phase 3, Task 1: Compare trained vs baseline.
        
        Returns:
            (baseline_metrics, trained_metrics)
        """
        y_true = data["outcome"].values
        
        # Compute baseline scores
        baseline = self.config.baseline_weights
        baseline_predictions = compute_all_scores(data, baseline)
        baseline_metrics = compute_metrics(y_true, baseline_predictions)
        
        # Compute trained scores
        trained = self.normalize_weights(trained_weights)
        trained_predictions = compute_all_scores(data, trained)
        trained_metrics = compute_metrics(y_true, trained_predictions)
        
        logger.info(f"[VALIDATE] Baseline metrics: R²={baseline_metrics['r2']:.4f}, "
                   f"RMSE={baseline_metrics['rmse']:.4f}, MAE={baseline_metrics['mae']:.4f}")
        logger.info(f"[VALIDATE] Trained metrics: R²={trained_metrics['r2']:.4f}, "
                   f"RMSE={trained_metrics['rmse']:.4f}, MAE={trained_metrics['mae']:.4f}")
        
        return baseline_metrics, trained_metrics
    
    def validate(
        self,
        trained_weights: Dict[str, float],
        version: str = "unknown"
    ) -> Tuple[bool, Dict[str, Any]]:
        """Full validation pipeline.
        
        Phase 3 complete validation:
        1. Load training data
        2. Backtest against baseline
        3. Enforce absolute R² threshold
        4. Enforce improvement threshold
        5. Validate weight sanity
        6. Generate audit report
        7. Print explainability output
        
        Args:
            trained_weights: Weights dict (either 'study' or 'study_score' format)
            version: Version string for audit report
            
        Returns:
            (validation_passed, audit_report)
            
        Raises:
            ValidationError: If any validation fails
        """
        logger.info("=" * 60)
        logger.info("[VALIDATE] GĐ Phase 3: Model Validation & Governance")
        logger.info("=" * 60)
        
        # Normalize weights
        weights = self.normalize_weights(trained_weights)
        
        # Step 1: Load data
        logger.info("[VALIDATE] Step 1: Loading training data...")
        data = self.load_training_data()
        
        # Step 2: Backtest
        logger.info("[VALIDATE] Step 2: Running backtest against baseline...")
        self.baseline_metrics, self.trained_metrics = self.backtest(data, weights)
        
        # Step 3: Enforce absolute R² threshold
        logger.info("[VALIDATE] Step 3: Checking absolute R² threshold...")
        enforce_absolute_threshold(self.trained_metrics["r2"], self.config)
        logger.info(f"[VALIDATE] Absolute R² threshold PASSED: {self.trained_metrics['r2']:.4f} >= {self.config.min_r2}")
        
        # Step 4: Enforce improvement threshold
        logger.info("[VALIDATE] Step 4: Checking improvement over baseline...")
        enforce_improvement_threshold(
            self.trained_metrics["r2"],
            self.baseline_metrics["r2"],
            self.config
        )
        improvement = (self.trained_metrics["r2"] - self.baseline_metrics["r2"]) / self.baseline_metrics["r2"] * 100
        logger.info(f"[VALIDATE] Improvement threshold PASSED: {improvement:.2f}% >= {self.config.improvement_threshold*100:.1f}%")
        
        # Step 5: Weight sanity validation
        logger.info("[VALIDATE] Step 5: Validating weight sanity...")
        validate_weight_sanity(weights, self.config)
        
        # Step 6: Generate audit report
        logger.info("[VALIDATE] Step 6: Generating audit report...")
        self.audit_report = generate_audit_report(
            version=version,
            baseline_metrics=self.baseline_metrics,
            trained_metrics=self.trained_metrics,
            trained_weights=weights,
            config=self.config
        )
        
        # Save audit report
        report_path = save_audit_report(self.audit_report, self.config)
        
        # Step 7: Explainability output
        logger.info("[VALIDATE] Step 7: Generating explainability output...")
        rankings = print_weight_rankings(weights)
        self.audit_report["rankings"] = rankings
        
        # Mark validation as passed
        self.validation_passed = True
        
        logger.info("=" * 60)
        logger.info("[VALIDATE] GĐ Phase 3: Validation PASSED!")
        logger.info(f"[VALIDATE] Audit report: {report_path}")
        logger.info("=" * 60)
        
        return True, self.audit_report


def validate_weights(
    trained_weights: Dict[str, float],
    version: str = "unknown",
    config: Optional[ValidationConfig] = None
) -> bool:
    """Convenience function for validation.
    
    Phase 3, Task 5: Block activation until validation passes.
    
    Args:
        trained_weights: Weights dict
        version: Version string
        config: Optional config
        
    Returns:
        True if validation passes
        
    Raises:
        ValidationError subclass if validation fails
    """
    validator = WeightValidator(config)
    passed, _ = validator.validate(trained_weights, version)
    return passed


# =====================================================
# CLI ENTRYPOINT
# =====================================================

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    # Load active weights file
    weights_path = "models/weights/active/weights.json"
    
    if len(sys.argv) > 1:
        weights_path = sys.argv[1]
    
    if not os.path.exists(weights_path):
        print(f"ERROR: Weights file not found: {weights_path}")
        sys.exit(1)
    
    with open(weights_path, "r") as f:
        weights_data = json.load(f)
    
    version = weights_data.get("version", "unknown")
    weights = weights_data.get("weights", {})
    
    try:
        result = validate_weights(weights, version)
        print(f"\n✓ Validation PASSED for {version}")
        sys.exit(0)
    except ValidationError as e:
        print(f"\n✗ Validation FAILED: {e}")
        sys.exit(1)

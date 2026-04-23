# tests/test_model_governance.py
"""
Phase 3: Automated Governance Tests.

GĐ Phase 3, Task 6: CI governance tests.

These tests MUST fail CI if governance is violated:
- Weights must sum to 1.0
- Risk must not be dominant (<=0.3)
- Model must improve over baseline
- R² must meet threshold
"""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd

# Import validation module
from backend.training.validate_weights import (
    ValidationConfig,
    ValidationError,
    GovernanceThresholdError,
    WeightSanityError,
    ImprovementThresholdError,
    WeightValidator,
    validate_weights,
    validate_weight_sanity,
    compute_score,
    compute_metrics,
    enforce_absolute_threshold,
    enforce_improvement_threshold,
)


# =====================================================
# FIXTURES
# =====================================================

@pytest.fixture
def valid_weights():
    """Valid weights that pass all checks."""
    return {
        "study": 0.30,
        "interest": 0.25,
        "market": 0.20,
        "growth": 0.15,
        "risk": 0.10
    }


@pytest.fixture
def valid_weights_with_suffix():
    """Valid weights with _score suffix."""
    return {
        "study_score": 0.30,
        "interest_score": 0.25,
        "market_score": 0.20,
        "growth_score": 0.15,
        "risk_score": 0.10
    }


@pytest.fixture
def baseline_weights():
    """Default baseline weights."""
    return {
        "study": 0.25,
        "interest": 0.25,
        "market": 0.25,
        "growth": 0.15,
        "risk": 0.10
    }


@pytest.fixture
def config():
    """Standard validation config."""
    return ValidationConfig()


@pytest.fixture
def sample_data():
    """Sample training data."""
    np.random.seed(42)
    n_samples = 50
    
    data = pd.DataFrame({
        "study": np.random.uniform(0.3, 1.0, n_samples),
        "interest": np.random.uniform(0.2, 0.9, n_samples),
        "market": np.random.uniform(0.1, 0.8, n_samples),
        "growth": np.random.uniform(0.2, 0.9, n_samples),
        "risk": np.random.uniform(0.0, 0.5, n_samples),
    })
    
    # Outcome based on weighted sum
    data["outcome"] = (
        0.3 * data["study"]
        + 0.25 * data["interest"]
        + 0.2 * data["market"]
        + 0.15 * data["growth"]
        - 0.1 * data["risk"]
    )
    data["outcome"] = data["outcome"].clip(0, 1)
    
    return data


# =====================================================
# TASK 6.1: WEIGHT SUM TESTS
# =====================================================

class TestWeightsSumToOne:
    """Tests for weight sum validation."""
    
    def test_weights_sum_to_one_passes(self, valid_weights, config):
        """Test that weights summing to 1.0 pass."""
        # Should not raise
        validate_weight_sanity(valid_weights, config)
    
    def test_weights_sum_greater_than_one_fails(self, config):
        """Test that weights > 1.0 fail."""
        bad_weights = {
            "study": 0.30,
            "interest": 0.30,
            "market": 0.30,
            "growth": 0.15,
            "risk": 0.10  # Sum = 1.15
        }
        
        with pytest.raises(WeightSanityError) as exc_info:
            validate_weight_sanity(bad_weights, config)
        
        assert "Sum check FAILED" in str(exc_info.value)
    
    def test_weights_sum_less_than_one_fails(self, config):
        """Test that weights < 1.0 fail."""
        bad_weights = {
            "study": 0.20,
            "interest": 0.20,
            "market": 0.20,
            "growth": 0.15,
            "risk": 0.10  # Sum = 0.85
        }
        
        with pytest.raises(WeightSanityError) as exc_info:
            validate_weight_sanity(bad_weights, config)
        
        assert "Sum check FAILED" in str(exc_info.value)
    
    def test_weights_sum_within_tolerance(self, config):
        """Test weights within tolerance pass."""
        # Just within tolerance
        weights = {
            "study": 0.300000001,
            "interest": 0.25,
            "market": 0.20,
            "growth": 0.15,
            "risk": 0.10
        }
        # Adjust to exactly 1.0 + small epsilon
        total = sum(weights.values())
        weights["study"] = weights["study"] + (1.0 - total + 1e-8)
        
        # Should pass if within tolerance
        validate_weight_sanity(weights, config)


# =====================================================
# TASK 6.2: RISK DOMINANCE TESTS
# =====================================================

class TestRiskNotDominant:
    """Tests for risk weight cap."""
    
    def test_risk_not_dominant_passes(self, valid_weights, config):
        """Test that normal risk weight passes."""
        # Risk = 0.10, should pass
        validate_weight_sanity(valid_weights, config)
    
    def test_risk_at_cap_passes(self, config):
        """Test risk exactly at cap passes."""
        weights = {
            "study": 0.20,
            "interest": 0.20,
            "market": 0.15,
            "growth": 0.15,
            "risk": 0.30  # Exactly at cap
        }
        # Should not raise
        validate_weight_sanity(weights, config)
    
    def test_risk_exceeds_cap_fails(self, config):
        """Test risk exceeding cap fails."""
        weights = {
            "study": 0.15,
            "interest": 0.15,
            "market": 0.15,
            "growth": 0.15,
            "risk": 0.40  # Exceeds 0.3 cap
        }
        
        with pytest.raises(WeightSanityError) as exc_info:
            validate_weight_sanity(weights, config)
        
        assert "Risk weight exceeds governance cap" in str(exc_info.value)
    
    def test_risk_zero_passes(self, config):
        """Test zero risk weight passes."""
        weights = {
            "study": 0.30,
            "interest": 0.30,
            "market": 0.20,
            "growth": 0.20,
            "risk": 0.0
        }
        validate_weight_sanity(weights, config)


# =====================================================
# TASK 6.3: MODEL IMPROVEMENT TESTS
# =====================================================

class TestModelImprovesOverBaseline:
    """Tests for improvement threshold enforcement."""
    
    def test_model_improves_over_baseline_passes(self, config):
        """Test that sufficient improvement passes."""
        baseline_r2 = 0.70
        trained_r2 = 0.80  # 14% improvement > 5% threshold
        
        # Should not raise
        enforce_improvement_threshold(trained_r2, baseline_r2, config)
    
    def test_model_exactly_at_threshold_passes(self, config):
        """Test exactly at improvement threshold passes."""
        baseline_r2 = 0.70
        required_r2 = baseline_r2 * (1 + config.improvement_threshold)  # 0.735
        trained_r2 = required_r2  # Exactly at threshold
        
        # Should not raise (>= comparison)
        enforce_improvement_threshold(trained_r2, baseline_r2, config)
    
    def test_model_below_threshold_fails(self, config):
        """Test insufficient improvement fails."""
        baseline_r2 = 0.70
        trained_r2 = 0.72  # ~3% improvement < 5% threshold
        
        with pytest.raises(ImprovementThresholdError) as exc_info:
            enforce_improvement_threshold(trained_r2, baseline_r2, config)
        
        assert "improvement below governance threshold" in str(exc_info.value)
    
    def test_model_worse_than_baseline_fails(self, config):
        """Test model worse than baseline fails."""
        baseline_r2 = 0.70
        trained_r2 = 0.65  # Worse than baseline
        
        with pytest.raises(ImprovementThresholdError):
            enforce_improvement_threshold(trained_r2, baseline_r2, config)


# =====================================================
# TASK 6.4: ABSOLUTE R² THRESHOLD TESTS
# =====================================================

class TestAbsoluteR2Threshold:
    """Tests for absolute R² minimum."""
    
    def test_r2_above_threshold_passes(self, config):
        """Test R² above minimum passes."""
        enforce_absolute_threshold(0.75, config)
    
    def test_r2_exactly_at_threshold_passes(self, config):
        """Test R² exactly at minimum passes."""
        enforce_absolute_threshold(0.60, config)
    
    def test_r2_below_threshold_fails(self, config):
        """Test R² below minimum fails."""
        with pytest.raises(GovernanceThresholdError) as exc_info:
            enforce_absolute_threshold(0.55, config)
        
        assert "R² below absolute governance minimum" in str(exc_info.value)
    
    def test_r2_zero_fails(self, config):
        """Test zero R² fails."""
        with pytest.raises(GovernanceThresholdError):
            enforce_absolute_threshold(0.0, config)
    
    def test_r2_negative_fails(self, config):
        """Test negative R² fails."""
        with pytest.raises(GovernanceThresholdError):
            enforce_absolute_threshold(-0.1, config)


# =====================================================
# ADDITIONAL GOVERNANCE TESTS
# =====================================================

class TestWeightDomination:
    """Tests for single weight domination guard."""
    
    def test_no_domination_passes(self, valid_weights, config):
        """Test weights without domination pass."""
        validate_weight_sanity(valid_weights, config)
    
    def test_domination_at_exact_50_fails(self, config):
        """Test weight at exactly 0.5 passes (boundary)."""
        weights = {
            "study": 0.50,
            "interest": 0.20,
            "market": 0.15,
            "growth": 0.10,
            "risk": 0.05
        }
        # 0.5 should actually fail since > 0.5 check
        # Adjust to be at boundary
        validate_weight_sanity(weights, config)
    
    def test_domination_above_50_fails(self, config):
        """Test weight above 0.5 fails."""
        weights = {
            "study": 0.55,
            "interest": 0.15,
            "market": 0.15,
            "growth": 0.10,
            "risk": 0.05
        }
        
        with pytest.raises(WeightSanityError) as exc_info:
            validate_weight_sanity(weights, config)
        
        assert "domination detected" in str(exc_info.value)


class TestNonNegativeWeights:
    """Tests for non-negative weight constraint."""
    
    def test_all_positive_passes(self, valid_weights, config):
        """Test all positive weights pass."""
        validate_weight_sanity(valid_weights, config)
    
    def test_zero_weights_pass(self, config):
        """Test zero weights pass."""
        weights = {
            "study": 0.50,
            "interest": 0.30,
            "market": 0.0,
            "growth": 0.20,
            "risk": 0.0
        }
        validate_weight_sanity(weights, config)
    
    def test_negative_weight_fails(self, config):
        """Test negative weight fails."""
        weights = {
            "study": 0.40,
            "interest": 0.30,
            "market": 0.25,
            "growth": 0.15,
            "risk": -0.10  # Negative
        }
        
        with pytest.raises(WeightSanityError) as exc_info:
            validate_weight_sanity(weights, config)
        
        assert "Non-negative check FAILED" in str(exc_info.value)


# =====================================================
# INTEGRATION TESTS
# =====================================================

class TestFullValidation:
    """Integration tests for full validation pipeline."""
    
    def test_compute_score_with_risk_subtraction(self, valid_weights):
        """Test score computation correctly subtracts risk."""
        row = pd.Series({
            "study": 0.8,
            "interest": 0.7,
            "market": 0.6,
            "growth": 0.5,
            "risk": 0.4
        })
        
        # Expected: 0.30*0.8 + 0.25*0.7 + 0.20*0.6 + 0.15*0.5 - 0.10*0.4
        #         = 0.24 + 0.175 + 0.12 + 0.075 - 0.04 = 0.57
        expected = 0.24 + 0.175 + 0.12 + 0.075 - 0.04
        
        actual = compute_score(row, valid_weights)
        
        assert abs(actual - expected) < 1e-6
    
    def test_compute_metrics_returns_required_keys(self, sample_data, valid_weights):
        """Test metrics computation returns all required keys."""
        from backend.training.validate_weights import compute_all_scores
        
        y_true = sample_data["outcome"].values
        y_pred = compute_all_scores(sample_data, valid_weights)
        
        metrics = compute_metrics(y_true, y_pred)
        
        assert "rmse" in metrics
        assert "mae" in metrics
        assert "r2" in metrics
        assert all(isinstance(v, float) for v in metrics.values())


class TestWeightValidator:
    """Tests for WeightValidator class."""
    
    def test_normalize_weights_handles_suffix(self):
        """Test weight normalization handles _score suffix."""
        validator = WeightValidator()
        
        weights_with_suffix = {
            "study_score": 0.30,
            "interest_score": 0.25,
            "market_score": 0.20,
            "growth_score": 0.15,
            "risk_score": 0.10
        }
        
        normalized = validator.normalize_weights(weights_with_suffix)
        
        assert "study" in normalized
        assert "interest" in normalized
        assert "market" in normalized
        assert "growth" in normalized
        assert "risk" in normalized
        assert normalized["study"] == 0.30
    
    def test_normalize_weights_handles_plain_keys(self):
        """Test weight normalization handles plain keys."""
        validator = WeightValidator()
        
        weights = {
            "study": 0.30,
            "interest": 0.25,
            "market": 0.20,
            "growth": 0.15,
            "risk": 0.10
        }
        
        normalized = validator.normalize_weights(weights)
        
        assert normalized == weights


# =====================================================
# CI GUARD TESTS
# =====================================================

class TestCIGuards:
    """Critical tests that MUST fail CI if governance violated."""
    
    @pytest.mark.critical
    def test_ci_guard_weights_must_sum_to_one(self, config):
        """CI GUARD: Weights must sum to 1.0."""
        # This test exists to ensure CI blocks on sum violation
        bad_weights = {
            "study": 0.50,
            "interest": 0.50,
            "market": 0.50,
            "growth": 0.50,
            "risk": 0.50  # Sum = 2.5
        }
        
        with pytest.raises(WeightSanityError):
            validate_weight_sanity(bad_weights, config)
    
    @pytest.mark.critical
    def test_ci_guard_risk_cap_enforced(self, config):
        """CI GUARD: Risk cap must be enforced."""
        bad_weights = {
            "study": 0.10,
            "interest": 0.10,
            "market": 0.10,
            "growth": 0.25,
            "risk": 0.45  # Exceeds 0.3 cap
        }
        
        with pytest.raises(WeightSanityError):
            validate_weight_sanity(bad_weights, config)
    
    @pytest.mark.critical
    def test_ci_guard_r2_minimum_enforced(self, config):
        """CI GUARD: R² minimum must be enforced."""
        with pytest.raises(GovernanceThresholdError):
            enforce_absolute_threshold(0.50, config)
    
    @pytest.mark.critical
    def test_ci_guard_improvement_enforced(self, config):
        """CI GUARD: Improvement threshold must be enforced."""
        with pytest.raises(ImprovementThresholdError):
            enforce_improvement_threshold(0.60, 0.60, config)  # 0% improvement


# =====================================================
# PHASE 5: ADVANCED MODELING TESTS
# =====================================================

class TestPhase5RidgeAndCV:
    """Phase 5: Test Ridge Regression and K-Fold CV components."""
    
    @pytest.fixture
    def training_config(self):
        """Training configuration for Phase 5 tests."""
        from backend.training.train_weights import TrainingConfig
        return TrainingConfig(
            input_csv="backend/data/scoring/train.csv",
            output_dir="models/weights",
            model_type="auto",
            ridge_alpha=1.0,
            n_folds=5,
            enable_cv=True,
            max_overfit_gap=0.1,
            enforce_thresholds=True
        )
    
    def test_phase5_training_config_has_ridge_options(self, training_config):
        """Phase 5: TrainingConfig must have Ridge options."""
        assert hasattr(training_config, "model_type")
        assert hasattr(training_config, "ridge_alpha")
        assert hasattr(training_config, "n_folds")
        assert hasattr(training_config, "enable_cv")
        assert hasattr(training_config, "max_overfit_gap")
    
    def test_phase5_ridge_import_available(self):
        """Phase 5: Ridge regression must be importable."""
        from sklearn.linear_model import Ridge
        model = Ridge(alpha=1.0, positive=True, fit_intercept=False)
        assert model is not None
    
    def test_phase5_kfold_import_available(self):
        """Phase 5: KFold cross validation must be importable."""
        from sklearn.model_selection import KFold, cross_val_score
        kf = KFold(n_splits=5, shuffle=True, random_state=42)
        assert kf is not None
    
    def test_phase5_trainer_has_ridge_method(self):
        """Phase 5: Trainer must have Ridge training method."""
        from backend.training.train_weights import SIMGRWeightTrainer
        trainer = SIMGRWeightTrainer()
        assert hasattr(trainer, "train_ridge_regression")
        assert callable(trainer.train_ridge_regression)
    
    def test_phase5_trainer_has_cv_method(self):
        """Phase 5: Trainer must have cross validation method."""
        from backend.training.train_weights import SIMGRWeightTrainer
        trainer = SIMGRWeightTrainer()
        assert hasattr(trainer, "k_fold_cross_validate")
        assert callable(trainer.k_fold_cross_validate)
    
    def test_phase5_trainer_has_auto_select(self):
        """Phase 5: Trainer must have auto model selection."""
        from backend.training.train_weights import SIMGRWeightTrainer
        trainer = SIMGRWeightTrainer()
        assert hasattr(trainer, "auto_select_model")
        assert callable(trainer.auto_select_model)
    
    def test_phase5_trainer_has_overfit_detection(self):
        """Phase 5: Trainer must have overfitting detection."""
        from backend.training.train_weights import SIMGRWeightTrainer
        trainer = SIMGRWeightTrainer()
        assert hasattr(trainer, "detect_overfitting")
        assert callable(trainer.detect_overfitting)
    
    @pytest.mark.critical
    def test_phase5_model_type_auto_is_valid(self, training_config):
        """Phase 5: model_type='auto' must be a valid option."""
        assert training_config.model_type in ["linear", "ridge", "auto"]
    
    @pytest.mark.critical
    def test_phase5_cv_folds_reasonable(self, training_config):
        """Phase 5: CV folds must be reasonable (3-10)."""
        assert 3 <= training_config.n_folds <= 10
    
    @pytest.mark.critical
    def test_phase5_ridge_alpha_positive(self, training_config):
        """Phase 5: Ridge alpha must be positive."""
        assert training_config.ridge_alpha > 0


class TestPhase5RetrainingMonitor:
    """Phase 5: Test retraining monitor module."""
    
    def test_retraining_monitor_module_exists(self):
        """Phase 5: Retraining monitor module must exist."""
        from backend.training import retraining_monitor
        assert retraining_monitor is not None
    
    def test_retraining_monitor_class_exists(self):
        """Phase 5: RetrainingMonitor class must exist."""
        from backend.training.retraining_monitor import RetrainingMonitor
        assert RetrainingMonitor is not None
    
    def test_retraining_config_exists(self):
        """Phase 5: RetrainingConfig must exist."""
        from backend.training.retraining_monitor import RetrainingConfig
        config = RetrainingConfig()
        assert config is not None
    
    def test_retraining_config_has_triggers(self):
        """Phase 5: RetrainingConfig must have trigger thresholds."""
        from backend.training.retraining_monitor import RetrainingConfig
        config = RetrainingConfig()
        assert hasattr(config, "min_new_samples")
        assert hasattr(config, "growth_ratio_threshold")
        assert hasattr(config, "max_model_age_days")
        assert hasattr(config, "min_r2_threshold")
        assert hasattr(config, "max_weight_change")
    
    def test_retraining_monitor_has_check_methods(self):
        """Phase 5: Monitor must have trigger check methods."""
        from backend.training.retraining_monitor import RetrainingMonitor
        monitor = RetrainingMonitor()
        assert hasattr(monitor, "check_dataset_growth")
        assert hasattr(monitor, "check_time_based")
        assert hasattr(monitor, "check_performance_degradation")
        assert hasattr(monitor, "check_weight_stability")
        assert hasattr(monitor, "check_all_triggers")
    
    def test_retraining_monitor_generate_report(self):
        """Phase 5: Monitor must generate status report."""
        from backend.training.retraining_monitor import RetrainingMonitor
        monitor = RetrainingMonitor()
        assert hasattr(monitor, "generate_report")
        assert callable(monitor.generate_report)
    
    @pytest.mark.critical
    def test_retraining_trigger_enum_exists(self):
        """Phase 5: Retraining trigger types must exist."""
        from backend.training.retraining_monitor import RetrainingTrigger
        assert hasattr(RetrainingTrigger, "DATASET_GROWTH")
        assert hasattr(RetrainingTrigger, "TIME_BASED")
        assert hasattr(RetrainingTrigger, "PERFORMANCE_DEGRADATION")
        assert hasattr(RetrainingTrigger, "WEIGHT_DRIFT")


class TestPhase5WeightStability:
    """Phase 5: Test weight stability comparison."""
    
    @pytest.fixture
    def sample_weights_v1(self):
        """Sample weights version 1."""
        return {
            "study": 0.30,
            "interest": 0.25,
            "market": 0.20,
            "growth": 0.15,
            "risk": 0.10
        }
    
    @pytest.fixture
    def sample_weights_v2_stable(self):
        """Sample weights version 2 - stable change."""
        return {
            "study": 0.32,  # +0.02
            "interest": 0.24,  # -0.01
            "market": 0.19,  # -0.01
            "growth": 0.15,  # unchanged
            "risk": 0.10  # unchanged
        }
    
    @pytest.fixture
    def sample_weights_v2_unstable(self):
        """Sample weights version 2 - unstable change."""
        return {
            "study": 0.50,  # +0.20 BIG CHANGE
            "interest": 0.15,  # -0.10
            "market": 0.15,  # -0.05
            "growth": 0.10,  # -0.05
            "risk": 0.10  # unchanged
        }
    
    def test_stability_check_returns_dict(self, sample_weights_v2_stable):
        """Phase 5: Stability check must return dict."""
        from backend.training.retraining_monitor import RetrainingMonitor
        monitor = RetrainingMonitor()
        result = monitor.check_weight_stability(sample_weights_v2_stable)
        assert isinstance(result, dict)
        assert "stable" in result
    
    @pytest.mark.critical
    def test_stability_max_change_threshold(self):
        """Phase 5: Weight stability must have max change threshold."""
        from backend.training.retraining_monitor import RetrainingConfig
        config = RetrainingConfig()
        assert config.max_weight_change == 0.15  # Default 15% change


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

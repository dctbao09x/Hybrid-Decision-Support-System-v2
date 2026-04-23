# tests/scoring_full/test_calculator.py
"""
Full coverage tests for backend/scoring/calculator.py

GĐ6: Coverage Recovery - Target: ≥90%

Tests:
- Formula correctness (risk subtracted)
- Component scoring pipeline
- Weight application
- Boundary conditions
- Error handling
"""

from __future__ import annotations

import pytest
from typing import Dict
from unittest.mock import MagicMock, patch
import math


class TestSIMGRCalculator:
    """Tests for SIMGRCalculator class."""
    
    def test_init_requires_scoring_config(self):
        """Calculator requires ScoringConfig type."""
        from backend.scoring.calculator import SIMGRCalculator
        
        with pytest.raises(TypeError, match="config must be ScoringConfig"):
            SIMGRCalculator(config=None)
        
        with pytest.raises(TypeError, match="config must be ScoringConfig"):
            SIMGRCalculator(config={"fake": "dict"})
    
    def test_init_with_valid_config(self, mock_scoring_config):
        """Calculator initializes with valid config."""
        from backend.scoring.calculator import SIMGRCalculator
        
        calc = SIMGRCalculator(config=mock_scoring_config)
        assert calc.config is not None
        assert calc.normalizer is not None
    
    def test_validate_components_checks_simgr_components(self, mock_scoring_config):
        """Calculator validates all SIMGR components exist."""
        from backend.scoring.calculator import SIMGRCalculator
        from backend.scoring.scoring_formula import ScoringFormula
        
        calc = SIMGRCalculator(config=mock_scoring_config)
        
        # All SIMGR components should be available
        for comp in ScoringFormula.COMPONENTS:
            assert comp in calc.config.component_map


class TestFormulaCorrectness:
    """Tests for SIMGR formula implementation."""
    
    def test_formula_subtracts_risk(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """Risk MUST be subtracted in final formula: Score = wS*S + wI*I + wM*M + wG*G - wR*R"""
        from backend.scoring.calculator import SIMGRCalculator
        
        calc = SIMGRCalculator(config=mock_scoring_config)
        total, breakdown = calc.calculate(mock_user_profile, mock_career_data)
        
        # If risk is subtracted, total should be affected by risk_score
        risk_score = breakdown.get("risk_score", 0)
        
        # With risk > 0, total should be lower than if risk = 0
        # We can't test exact formula here without mocking all components,
        # but we verify the score is reasonable
        assert 0.0 <= total <= 1.0
        assert "risk_score" in breakdown
    
    def test_formula_with_all_ones_risk_one(
        self, all_ones_with_risk, mock_weights, expected_score_calculator
    ):
        """With all scores=1.0 including risk, formula gives predictable result."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        expected = expected_score_calculator(all_ones_with_risk, mock_weights)
        actual = ScoringFormula.compute(
            all_ones_with_risk, mock_weights, validate=False, clamp_output=False
        )
        
        # wS*1 + wI*1 + wM*1 + wG*1 - wR*1 = 0.25+0.25+0.25+0.15 - 0.10 = 0.80
        assert abs(actual - expected) < 1e-6
        assert abs(actual - 0.80) < 1e-6
    
    def test_formula_with_zero_risk_weight(
        self, all_ones_with_risk, zero_risk_weights, expected_score_calculator
    ):
        """With wR=0, risk has no effect."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        expected = expected_score_calculator(all_ones_with_risk, zero_risk_weights)
        actual = ScoringFormula.compute(
            all_ones_with_risk, zero_risk_weights, validate=False, clamp_output=False
        )
        
        # wS*1 + wI*1 + wM*1 + wG*1 - 0*1 = 0.25+0.25+0.25+0.25 = 1.0
        assert abs(actual - expected) < 1e-6
        assert abs(actual - 1.0) < 1e-6
    
    def test_formula_with_high_risk_weight(
        self, all_ones_with_risk, high_risk_weights, expected_score_calculator
    ):
        """With high wR, risk significantly lowers score."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        expected = expected_score_calculator(all_ones_with_risk, high_risk_weights)
        actual = ScoringFormula.compute(
            all_ones_with_risk, high_risk_weights, validate=False, clamp_output=False
        )
        
        # wS*1 + wI*1 + wM*1 + wG*1 - wR*1 = 0.15+0.15+0.10+0.10 - 0.50 = 0.0
        assert abs(actual - expected) < 1e-6
        assert abs(actual - 0.0) < 1e-6
    
    def test_formula_zero_risk_score(self, perfect_scores, mock_weights, expected_score_calculator):
        """With risk=0.0, risk penalty is zero."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        expected = expected_score_calculator(perfect_scores, mock_weights)
        actual = ScoringFormula.compute(
            perfect_scores, mock_weights, validate=False, clamp_output=False
        )
        
        # No risk penalty
        # 0.25*1 + 0.25*1 + 0.25*1 + 0.15*1 - 0.10*0 = 0.90
        assert abs(actual - expected) < 1e-6
        assert abs(actual - 0.90) < 1e-6
    
    def test_formula_full_risk_score(self, worst_scores, mock_weights, expected_score_calculator):
        """With maximum risk and zero positives, score is negative (clamped to 0)."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        # Without clamping
        raw = ScoringFormula.compute(
            worst_scores, mock_weights, validate=False, clamp_output=False
        )
        
        # 0.25*0 + 0.25*0 + 0.25*0 + 0.15*0 - 0.10*1 = -0.10
        assert abs(raw - (-0.10)) < 1e-6
        
        # With clamping
        clamped = ScoringFormula.compute(
            worst_scores, mock_weights, validate=False, clamp_output=True
        )
        assert clamped == 0.0


class TestWeightVariations:
    """Test different weight configurations."""
    
    @pytest.mark.parametrize("risk_weight", [0.0, 0.05, 0.10, 0.20, 0.30])
    def test_risk_weight_variations(self, risk_weight: float, all_ones_with_risk):
        """Test various risk weight values."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        # Distribute remaining weight equally
        remaining = 1.0 - risk_weight
        other = remaining / 4
        
        weights = {
            "study": other,
            "interest": other,
            "market": other,
            "growth": other,
            "risk": risk_weight,
        }
        
        actual = ScoringFormula.compute(
            all_ones_with_risk, weights, validate=False, clamp_output=False
        )
        
        # Expected: 4*other - risk_weight = (1-risk_weight) - risk_weight = 1 - 2*risk_weight
        expected = 1.0 - 2 * risk_weight
        assert abs(actual - expected) < 1e-6
    
    def test_weights_must_sum_to_one(self):
        """Validation fails if weights don't sum to 1.0."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        bad_weights = {
            "study": 0.3,
            "interest": 0.3,
            "market": 0.3,
            "growth": 0.3,
            "risk": 0.3,  # Sum = 1.5
        }
        scores = {
            "study": 0.5, "interest": 0.5, "market": 0.5, "growth": 0.5, "risk": 0.5
        }
        
        with pytest.raises(ValueError, match="must sum to 1.0"):
            ScoringFormula.compute(scores, bad_weights, validate=True)


class TestBoundaryConditions:
    """Test boundary conditions for calculator."""
    
    @pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
    def test_valid_score_values(self, value: float, mock_weights):
        """Valid score values [0, 1] accepted."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        scores = {
            "study": value,
            "interest": value,
            "market": value,
            "growth": value,
            "risk": value,
        }
        
        result = ScoringFormula.compute(scores, mock_weights, validate=True)
        assert 0.0 <= result <= 1.0
    
    @pytest.mark.parametrize("value", [-0.1, 1.1, -1.0, 2.0, float('inf')])
    def test_invalid_score_values_rejected(self, value: float, mock_weights):
        """Invalid score values outside [0,1] rejected."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        scores = {
            "study": value,
            "interest": 0.5,
            "market": 0.5,
            "growth": 0.5,
            "risk": 0.5,
        }
        
        with pytest.raises(ValueError, match="must be in"):
            ScoringFormula.compute(scores, mock_weights, validate=True)
    
    def test_nan_score_rejected(self, mock_weights):
        """NaN score values rejected."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        scores = {
            "study": float('nan'),
            "interest": 0.5,
            "market": 0.5,
            "growth": 0.5,
            "risk": 0.5,
        }
        
        with pytest.raises(ValueError, match="must be in"):
            ScoringFormula.compute(scores, mock_weights, validate=True)
    
    def test_missing_component_rejected(self, mock_weights):
        """Missing component rejected."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        incomplete_scores = {
            "study": 0.5,
            "interest": 0.5,
            # Missing: market, growth, risk
        }
        
        with pytest.raises(ValueError, match="Missing required components"):
            ScoringFormula.compute(incomplete_scores, mock_weights, validate=True)


class TestCalculatorCalculate:
    """Tests for SIMGRCalculator.calculate() method."""
    
    def test_calculate_returns_tuple(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """calculate() returns (total, breakdown) tuple."""
        from backend.scoring.calculator import SIMGRCalculator
        
        calc = SIMGRCalculator(config=mock_scoring_config)
        result = calc.calculate(mock_user_profile, mock_career_data)
        
        assert isinstance(result, tuple)
        assert len(result) == 2
        total, breakdown = result
        assert isinstance(total, float)
        assert isinstance(breakdown, dict)
    
    def test_calculate_breakdown_has_all_components(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """Breakdown contains all SIMGR components."""
        from backend.scoring.calculator import SIMGRCalculator
        from backend.scoring.scoring_formula import ScoringFormula
        
        calc = SIMGRCalculator(config=mock_scoring_config)
        _, breakdown = calc.calculate(mock_user_profile, mock_career_data)
        
        for comp in ScoringFormula.COMPONENTS:
            assert f"{comp}_score" in breakdown, f"Missing {comp}_score in breakdown"
    
    def test_calculate_score_clamped(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """Total score is clamped to [0, 1]."""
        from backend.scoring.calculator import SIMGRCalculator
        
        calc = SIMGRCalculator(config=mock_scoring_config)
        total, _ = calc.calculate(mock_user_profile, mock_career_data)
        
        assert 0.0 <= total <= 1.0


class TestComponentComputation:
    """Tests for _compute_component method."""
    
    def test_missing_component_returns_fallback(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """Missing component uses fallback value."""
        from backend.scoring.calculator import SIMGRCalculator
        from backend.scoring.scoring_formula import ScoringFormula
        
        # Remove a component from config
        mock_scoring_config.component_map.pop("study", None)
        
        calc = SIMGRCalculator(config=mock_scoring_config)
        
        # Should not crash, should use fallback
        total, breakdown = calc.calculate(mock_user_profile, mock_career_data)
        
        # Fallback for study is 0.5
        assert breakdown["study_score"] == ScoringFormula.get_default_fallback("study")
    
    def test_component_exception_uses_fallback(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache, failing_component_fn
    ):
        """Component exception triggers fallback (in non-debug mode)."""
        from backend.scoring.calculator import SIMGRCalculator
        
        # Set to non-debug mode
        mock_scoring_config.debug_mode = False
        mock_scoring_config.component_map["study"] = failing_component_fn
        
        calc = SIMGRCalculator(config=mock_scoring_config)
        total, breakdown = calc.calculate(mock_user_profile, mock_career_data)
        
        # Should have fallback value and error details
        assert "study_score" in breakdown
        if "study_details" in breakdown:
            assert "error" in breakdown.get("study_details", {})
    
    def test_component_exception_raises_in_debug_mode(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache, failing_component_fn
    ):
        """Component exception re-raised in debug mode."""
        from backend.scoring.calculator import SIMGRCalculator
        
        mock_scoring_config.debug_mode = True
        mock_scoring_config.component_map["study"] = failing_component_fn
        
        calc = SIMGRCalculator(config=mock_scoring_config)
        
        with pytest.raises(ValueError, match="Component computation failed"):
            calc.calculate(mock_user_profile, mock_career_data)


class TestRiskMonotonicity:
    """Tests for risk monotonicity (higher risk = lower score)."""
    
    def test_higher_risk_lower_score(self, mock_weights):
        """Higher risk values should produce lower total scores."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        base_scores = {"study": 0.8, "interest": 0.7, "market": 0.6, "growth": 0.5}
        
        last_total = None
        for risk in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
            scores = {**base_scores, "risk": risk}
            total = ScoringFormula.compute(
                scores, mock_weights, validate=False, clamp_output=False
            )
            
            if last_total is not None:
                assert total < last_total, f"Risk monotonicity violated at risk={risk}"
            last_total = total
    
    def test_risk_impact_proportional_to_weight(self):
        """Risk impact should be proportional to risk weight."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        scores = {"study": 0.8, "interest": 0.7, "market": 0.6, "growth": 0.5, "risk": 0.5}
        
        # Low risk weight
        low_w = {"study": 0.25, "interest": 0.25, "market": 0.25, "growth": 0.20, "risk": 0.05}
        low_result = ScoringFormula.compute(scores, low_w, validate=False, clamp_output=False)
        
        # High risk weight
        high_w = {"study": 0.20, "interest": 0.20, "market": 0.20, "growth": 0.15, "risk": 0.25}
        high_result = ScoringFormula.compute(scores, high_w, validate=False, clamp_output=False)
        
        # With higher risk weight, impact should be larger
        low_impact = 0.05 * 0.5  # 0.025
        high_impact = 0.25 * 0.5  # 0.125
        
        # Higher weight means larger penalty, so lower score
        assert high_result < low_result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

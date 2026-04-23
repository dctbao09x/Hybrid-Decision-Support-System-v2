# tests/risk/test_penalty.py
"""
Tests for Risk Penalty Engine - SIMGR Stage 3 Compliance

CRITICAL TESTS:
- Penalty reduces score (NO INVERSION)
- High risk = high penalty
- Config-driven computation
"""

import pytest
from typing import Dict


class TestRiskPenaltyEngine:
    """Tests for RiskPenaltyEngine."""
    
    def test_engine_instantiation(self):
        """Engine should instantiate without errors."""
        from backend.risk.penalty import RiskPenaltyEngine
        engine = RiskPenaltyEngine()
        assert engine is not None
    
    def test_compute_returns_float(self):
        """Compute should return a float."""
        from backend.risk.penalty import RiskPenaltyEngine
        engine = RiskPenaltyEngine()
        
        result = engine.compute(
            market=0.5,
            skill=0.3,
            competition=0.4,
            dropout=0.2,
            unemployment=0.1,
            cost=0.35,
        )
        
        assert isinstance(result, float)
    
    def test_compute_in_range(self):
        """Result must be in [0, 1]."""
        from backend.risk.penalty import RiskPenaltyEngine
        engine = RiskPenaltyEngine()
        
        result = engine.compute(
            market=0.5,
            skill=0.3,
            competition=0.4,
            dropout=0.2,
            unemployment=0.1,
            cost=0.35,
        )
        
        assert 0.0 <= result <= 1.0
    
    def test_high_risk_high_penalty(self):
        """High inputs should produce high penalty (NO INVERSION)."""
        from backend.risk.penalty import RiskPenaltyEngine
        engine = RiskPenaltyEngine()
        
        # All low risk
        low_result = engine.compute(
            market=0.1,
            skill=0.1,
            competition=0.1,
            dropout=0.1,
            unemployment=0.1,
            cost=0.1,
        )
        
        # All high risk
        high_result = engine.compute(
            market=0.9,
            skill=0.9,
            competition=0.9,
            dropout=0.9,
            unemployment=0.9,
            cost=0.9,
        )
        
        # High risk must produce higher penalty (NO INVERSION)
        assert high_result > low_result, (
            f"High risk ({high_result}) must be greater than low risk ({low_result}). "
            "NO INVERSION allowed."
        )
    
    def test_penalty_reduces_score(self):
        """CRITICAL: Penalty should REDUCE final score, not increase it."""
        from backend.risk.penalty import RiskPenaltyEngine
        engine = RiskPenaltyEngine()
        
        # Simulate SIMGR calculation
        base_score = 0.7  # S + I + M + G contributions
        
        # Low risk case
        low_risk = engine.compute(
            market=0.1, skill=0.1, competition=0.1,
            dropout=0.1, unemployment=0.1, cost=0.1,
        )
        
        # High risk case
        high_risk = engine.compute(
            market=0.9, skill=0.9, competition=0.9,
            dropout=0.9, unemployment=0.9, cost=0.9,
        )
        
        # Apply SIMGR formula: Score = base - wR*R
        # Using wR = 0.2 as typical weight
        w_risk = 0.2
        score_low_risk = base_score - w_risk * low_risk
        score_high_risk = base_score - w_risk * high_risk
        
        # High risk should reduce score more
        assert score_high_risk < score_low_risk, (
            f"High risk should reduce score more. "
            f"Score with low risk: {score_low_risk}, "
            f"Score with high risk: {score_high_risk}"
        )
    
    def test_no_inversion_formula(self):
        """CRITICAL: Verify NO INVERSION in penalty calculation."""
        from backend.risk.penalty import RiskPenaltyEngine
        engine = RiskPenaltyEngine()
        
        # Zero risk should give near-zero penalty
        zero_risk = engine.compute(
            market=0.0, skill=0.0, competition=0.0,
            dropout=0.0, unemployment=0.0, cost=0.0,
            apply_threshold=False,
            apply_scaling=False,
        )
        
        # Full risk should give near-one penalty
        full_risk = engine.compute(
            market=1.0, skill=1.0, competition=1.0,
            dropout=1.0, unemployment=1.0, cost=1.0,
            apply_threshold=False,
            apply_scaling=False,
        )
        
        # Check NO INVERSION: 0 input → low output, 1 input → high output
        assert zero_risk < 0.2, f"Zero risk gave {zero_risk}, expected < 0.2 (check for inversion)"
        assert full_risk > 0.8, f"Full risk gave {full_risk}, expected > 0.8 (check for inversion)"
    
    def test_weighted_sum_formula(self):
        """Verify weighted sum formula."""
        from backend.risk.penalty import RiskPenaltyEngine
        engine = RiskPenaltyEngine()
        weights = engine.get_weights()
        
        # Input values
        market = 0.5
        skill = 0.4
        competition = 0.3
        dropout = 0.2
        unemployment = 0.15
        cost = 0.25
        
        # Expected result (weighted sum)
        expected = (
            weights['market_saturation'] * market +
            weights['skill_obsolescence'] * skill +
            weights['competition'] * competition +
            weights['dropout'] * dropout +
            weights['unemployment'] * unemployment +
            weights['cost'] * cost
        )
        
        # Actual (without threshold/scaling)
        actual = engine.compute(
            market=market,
            skill=skill,
            competition=competition,
            dropout=dropout,
            unemployment=unemployment,
            cost=cost,
            apply_threshold=False,
            apply_scaling=False,
        )
        
        # Should be close (allowing for clamping)
        assert abs(actual - expected) < 0.1, f"Expected ~{expected}, got {actual}"


class TestRiskBreakdown:
    """Tests for risk breakdown."""
    
    def test_breakdown_includes_all_components(self):
        """Breakdown should include all components."""
        from backend.risk.penalty import RiskPenaltyEngine
        engine = RiskPenaltyEngine()
        
        breakdown = engine.compute_with_breakdown(
            market=0.5,
            skill=0.3,
            competition=0.4,
            dropout=0.2,
            unemployment=0.1,
            cost=0.35,
        )
        
        assert hasattr(breakdown, 'market_saturation')
        assert hasattr(breakdown, 'skill_obsolescence')
        assert hasattr(breakdown, 'competition')
        assert hasattr(breakdown, 'dropout')
        assert hasattr(breakdown, 'unemployment')
        assert hasattr(breakdown, 'cost')
        assert hasattr(breakdown, 'total')
    
    def test_breakdown_to_dict(self):
        """Breakdown should convert to dict."""
        from backend.risk.penalty import RiskPenaltyEngine
        engine = RiskPenaltyEngine()
        
        breakdown = engine.compute_with_breakdown(
            market=0.5,
            skill=0.3,
            competition=0.4,
            dropout=0.2,
            unemployment=0.1,
            cost=0.35,
        )
        
        result = breakdown.to_dict()
        assert isinstance(result, dict)
        assert 'total' in result


class TestConvenienceFunction:
    """Tests for compute_risk convenience function."""
    
    def test_compute_risk_function(self):
        """compute_risk should work as convenience function."""
        from backend.risk import compute_risk
        
        result = compute_risk(
            market=0.5,
            skill=0.3,
            competition=0.4,
            dropout=0.2,
            unemployment=0.1,
            cost=0.35,
        )
        
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0
    
    def test_compute_risk_defaults(self):
        """compute_risk should have defaults."""
        from backend.risk import compute_risk
        
        result = compute_risk()  # All defaults
        
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0


class TestConfigReload:
    """Tests for config hot reload."""
    
    def test_engine_reload(self):
        """Engine should support reload."""
        from backend.risk.penalty import RiskPenaltyEngine
        engine = RiskPenaltyEngine()
        
        # Get initial weights
        initial_weights = engine.get_weights()
        
        # Reload
        engine.reload_config()
        
        # Should still have valid weights
        reloaded_weights = engine.get_weights()
        assert reloaded_weights is not None
        assert len(reloaded_weights) == 6


class TestEdgeCases:
    """Edge case tests."""
    
    def test_negative_inputs_clamped(self):
        """Negative inputs should be clamped to 0."""
        from backend.risk.penalty import RiskPenaltyEngine
        engine = RiskPenaltyEngine()
        
        result = engine.compute(
            market=-0.5,
            skill=-0.3,
            competition=-0.4,
            dropout=-0.2,
            unemployment=-0.1,
            cost=-0.35,
        )
        
        assert result >= 0.0
    
    def test_over_one_inputs_clamped(self):
        """Inputs > 1 should be clamped."""
        from backend.risk.penalty import RiskPenaltyEngine
        engine = RiskPenaltyEngine()
        
        result = engine.compute(
            market=1.5,
            skill=1.3,
            competition=1.4,
            dropout=1.2,
            unemployment=1.1,
            cost=1.35,
        )
        
        assert result <= 1.0

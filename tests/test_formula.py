# tests/test_formula.py
"""
SIMGR Scoring Formula Correctness Tests.

DOC FORMULA: Score = wS*S + wI*I + wM*M + wG*G - wR*R

These tests verify:
1. Risk is SUBTRACTED (not added)
2. Formula matches specification
3. High risk reduces score
4. Weights apply correctly
"""

import pytest
from unittest.mock import MagicMock, patch
from backend.scoring.scoring import SIMGRScorer
from backend.scoring.calculator import SIMGRCalculator
from backend.scoring.config import (
    ScoringConfig,
    SIMGRWeights,
    ComponentWeights,
    DEFAULT_CONFIG,
)
from backend.scoring.models import UserProfile, CareerData
from backend.scoring.normalizer import DataNormalizer


class TestScoringFormulaCorrectness:
    """Test suite for SIMGR formula compliance."""

    def test_risk_subtraction_direct_mode(self):
        """
        Verify risk is SUBTRACTED in direct scoring mode.
        
        DOC: Score = wS*S + wI*I + wM*M + wG*G - wR*R
        
        If risk increases, score should DECREASE.
        """
        scorer = SIMGRScorer()
        
        # Low risk scenario
        low_risk_result = scorer.score({
            "study": 0.8,
            "interest": 0.7,
            "market": 0.6,
            "growth": 0.5,
            "risk": 0.1,  # LOW risk
        })
        
        # High risk scenario (same other scores)
        high_risk_result = scorer.score({
            "study": 0.8,
            "interest": 0.7,
            "market": 0.6,
            "growth": 0.5,
            "risk": 0.9,  # HIGH risk
        })
        
        # High risk should result in LOWER score
        assert high_risk_result["total_score"] < low_risk_result["total_score"], \
            "Higher risk must reduce total score (risk should be subtracted)"
        
        # Score difference should be proportional to risk difference
        risk_diff = 0.9 - 0.1  # 0.8
        expected_score_diff = risk_diff * DEFAULT_CONFIG.simgr_weights.risk_score
        actual_diff = low_risk_result["total_score"] - high_risk_result["total_score"]
        
        assert abs(actual_diff - expected_score_diff) < 0.01, \
            f"Score difference should be ~{expected_score_diff}, got {actual_diff}"

    def test_zero_risk_maximizes_score(self):
        """Zero risk should not reduce score at all."""
        scorer = SIMGRScorer()
        
        # All perfect scores, zero risk
        result = scorer.score({
            "study": 1.0,
            "interest": 1.0,
            "market": 1.0,
            "growth": 1.0,
            "risk": 0.0,  # Zero risk
        })
        
        # Expected: 0.25*1 + 0.25*1 + 0.25*1 + 0.15*1 - 0.10*0 = 0.90
        expected = (
            1.0 * DEFAULT_CONFIG.simgr_weights.study_score +
            1.0 * DEFAULT_CONFIG.simgr_weights.interest_score +
            1.0 * DEFAULT_CONFIG.simgr_weights.market_score +
            1.0 * DEFAULT_CONFIG.simgr_weights.growth_score -
            0.0 * DEFAULT_CONFIG.simgr_weights.risk_score
        )
        
        assert abs(result["total_score"] - expected) < 0.01, \
            f"Expected {expected}, got {result['total_score']}"

    def test_max_risk_reduces_score(self):
        """Maximum risk should reduce score by full weight."""
        scorer = SIMGRScorer()
        
        # All perfect scores, max risk
        result = scorer.score({
            "study": 1.0,
            "interest": 1.0,
            "market": 1.0,
            "growth": 1.0,
            "risk": 1.0,  # Maximum risk
        })
        
        # Expected: 0.25*1 + 0.25*1 + 0.25*1 + 0.15*1 - 0.10*1 = 0.80
        expected = (
            1.0 * DEFAULT_CONFIG.simgr_weights.study_score +
            1.0 * DEFAULT_CONFIG.simgr_weights.interest_score +
            1.0 * DEFAULT_CONFIG.simgr_weights.market_score +
            1.0 * DEFAULT_CONFIG.simgr_weights.growth_score -
            1.0 * DEFAULT_CONFIG.simgr_weights.risk_score
        )
        
        assert abs(result["total_score"] - expected) < 0.01, \
            f"Expected {expected}, got {result['total_score']}"

    def test_formula_components_additive_except_risk(self):
        """S, I, M, G should be additive; R should be subtractive."""
        scorer = SIMGRScorer()
        
        # Baseline: all zeros
        base = scorer.score({
            "study": 0.0,
            "interest": 0.0,
            "market": 0.0,
            "growth": 0.0,
            "risk": 0.0,
        })
        
        # Adding study should INCREASE score
        with_study = scorer.score({
            "study": 1.0,
            "interest": 0.0,
            "market": 0.0,
            "growth": 0.0,
            "risk": 0.0,
        })
        assert with_study["total_score"] > base["total_score"], \
            "Adding study should increase score"
        
        # Adding risk should DECREASE score (from baseline with all 0.5)
        low_risk = scorer.score({
            "study": 0.5,
            "interest": 0.5,
            "market": 0.5,
            "growth": 0.5,
            "risk": 0.0,
        })
        high_risk = scorer.score({
            "study": 0.5,
            "interest": 0.5,
            "market": 0.5,
            "growth": 0.5,
            "risk": 1.0,
        })
        assert high_risk["total_score"] < low_risk["total_score"], \
            "Adding risk should decrease score"

    def test_weights_sum_constraint(self):
        """Verify default weights sum to 1.0."""
        weights = DEFAULT_CONFIG.simgr_weights
        total = (
            weights.study_score +
            weights.interest_score +
            weights.market_score +
            weights.growth_score +
            weights.risk_score
        )
        assert abs(total - 1.0) < 0.001, f"Weights must sum to 1.0, got {total}"


class TestCalculatorFormulaCorrectness:
    """Test SIMGRCalculator formula implementation."""

    def test_calculator_subtracts_risk(self):
        """Verify calculator uses subtraction for risk."""
        from backend.scoring.components import risk as risk_component
        
        config = DEFAULT_CONFIG
        calculator = SIMGRCalculator(config)
        
        # Create test profile and career
        user = UserProfile(
            skills=["python", "java"],
            interests=["AI", "data"],
            education_level="Master",
            ability_score=0.8,
            confidence_score=0.8,
        )
        
        # Career with LOW risk factors
        low_risk_career = CareerData(
            name="Low Risk Job",
            required_skills=["python"],
            preferred_skills=["java"],
            domain="tech",
            domain_interests=["AI"],
            ai_relevance=0.9,  # High AI relevance = low competition risk
            growth_rate=0.9,   # High growth = low obsolescence risk
            competition=0.1,   # Low competition = low saturation risk
        )
        
        # Career with HIGH risk factors
        high_risk_career = CareerData(
            name="High Risk Job",
            required_skills=["python"],
            preferred_skills=["java"],
            domain="tech",
            domain_interests=["AI"],
            ai_relevance=0.1,  # Low AI relevance = high competition risk
            growth_rate=0.1,   # Low growth = high obsolescence risk
            competition=0.9,   # High competition = high saturation risk
        )
        
        low_score, _ = calculator.calculate(user, low_risk_career)
        high_score, _ = calculator.calculate(user, high_risk_career)
        
        # Higher risk career should have LOWER total score
        assert high_score < low_score, \
            f"High risk career ({high_score}) should score lower than low risk ({low_score})"


class TestRiskComponentOutput:
    """Test that risk component returns RAW risk (not inverted)."""

    def test_risk_component_returns_raw_risk(self):
        """Risk component should return raw risk value (high = bad)."""
        from backend.scoring.components.risk import score as risk_score
        from backend.scoring.models import ScoreResult
        
        user = UserProfile(skills=[], interests=[])
        config = DEFAULT_CONFIG
        
        # High risk scenario
        high_risk_career = CareerData(
            name="High Risk",
            required_skills=[],
            preferred_skills=[],
            domain="",
            domain_interests=[],
            ai_relevance=0.0,  # Low = high risk
            growth_rate=0.0,   # Low = high risk
            competition=1.0,   # High = high risk
        )
        
        result = risk_score(high_risk_career, user, config)
        
        # Should return HIGH value for high risk
        assert result.value > 0.5, \
            f"High risk career should return risk > 0.5, got {result.value}"
        
        # Low risk scenario
        low_risk_career = CareerData(
            name="Low Risk",
            required_skills=[],
            preferred_skills=[],
            domain="",
            domain_interests=[],
            ai_relevance=1.0,  # High = low risk
            growth_rate=1.0,   # High = low risk
            competition=0.0,   # Low = low risk
        )
        
        result_low = risk_score(low_risk_career, user, config)
        
        # Should return LOW value for low risk
        assert result_low.value < 0.5, \
            f"Low risk career should return risk < 0.5, got {result_low.value}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

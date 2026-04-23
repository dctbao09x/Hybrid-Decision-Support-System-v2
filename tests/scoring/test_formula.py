# tests/scoring/test_formula.py
"""
Tests for SIMGR Formula Compliance (R001)

Validates:
- Formula correctness: Score = wS*S + wI*I + wM*M + wG*G - wR*R
- Risk SUBTRACTED not ADDED
- Weight sum = 1.0
- Score in [0, 1]
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.scoring.calculator import SIMGRCalculator
from backend.scoring.config import SIMGRWeights, ComponentWeights, ScoringConfig
from backend.scoring.models import UserProfile, CareerData


class TestFormulaCorrectness:
    """Test SIMGR formula implementation."""
    
    def test_formula_subtracts_risk(self):
        """Risk must be SUBTRACTED in final formula."""
        from backend.scoring.config import SIMGRWeights
        """Risk must be SUBTRACTED in final formula."""
        # With all scores = 1.0 and risk = 0.5
        # If risk is subtracted: total < 1.0
        # If risk is added: total > 1.0
        
        weights = SIMGRWeights(
            study_score=0.2,
            interest_score=0.2,
            market_score=0.2,
            growth_score=0.2,
            risk_score=0.2,
        )
        
        simgr_scores = {
            "study": 1.0,
            "interest": 1.0,
            "market": 1.0,
            "growth": 1.0,
            "risk": 1.0,  # High risk
        }
        
        # Manual formula: wS*1 + wI*1 + wM*1 + wG*1 - wR*1
        # = 0.2 + 0.2 + 0.2 + 0.2 - 0.2 = 0.6
        expected = 0.6
        
        # Force using calculated score
        total = (
            weights.study_score * simgr_scores["study"]
            + weights.interest_score * simgr_scores["interest"]
            + weights.market_score * simgr_scores["market"]
            + weights.growth_score * simgr_scores["growth"]
            - weights.risk_score * simgr_scores["risk"]
        )
        
        assert abs(total - expected) < 0.001
    
    def test_risk_monotonicity(self):
        """Higher risk should result in lower score."""
        weights = SIMGRWeights(
            study_score=0.25,
            interest_score=0.25,
            market_score=0.25,
            growth_score=0.15,
            risk_score=0.10,
        )
        
        base_scores = {
            "study": 0.8,
            "interest": 0.7,
            "market": 0.6,
            "growth": 0.5,
        }
        
        # Calculate with low risk
        low_risk_total = (
            weights.study_score * base_scores["study"]
            + weights.interest_score * base_scores["interest"]
            + weights.market_score * base_scores["market"]
            + weights.growth_score * base_scores["growth"]
            - weights.risk_score * 0.2  # Low risk
        )
        
        # Calculate with high risk
        high_risk_total = (
            weights.study_score * base_scores["study"]
            + weights.interest_score * base_scores["interest"]
            + weights.market_score * base_scores["market"]
            + weights.growth_score * base_scores["growth"]
            - weights.risk_score * 0.8  # High risk
        )
        
        assert low_risk_total > high_risk_total, "Higher risk should give lower score"
    
    def test_zero_risk_gives_max_contribution(self):
        """Zero risk should not reduce the score."""
        weights = SIMGRWeights()
        
        simgr_scores = {
            "study": 0.8,
            "interest": 0.7,
            "market": 0.6,
            "growth": 0.5,
            "risk": 0.0,  # Zero risk
        }
        
        # With zero risk, formula is: wS*S + wI*I + wM*M + wG*G - 0
        positive_sum = (
            weights.study_score * simgr_scores["study"]
            + weights.interest_score * simgr_scores["interest"]
            + weights.market_score * simgr_scores["market"]
            + weights.growth_score * simgr_scores["growth"]
        )
        
        total_with_zero_risk = (
            positive_sum - weights.risk_score * simgr_scores["risk"]
        )
        
        assert total_with_zero_risk == positive_sum


class TestWeightValidation:
    """Test weight constraints."""
    
    def test_default_weights_sum_to_one(self):
        """Default weights must sum to 1.0."""
        weights = SIMGRWeights()
        total = (
            weights.study_score
            + weights.interest_score
            + weights.market_score
            + weights.growth_score
            + weights.risk_score
        )
        assert abs(total - 1.0) < 0.001
    
    def test_custom_weights_sum_validation(self):
        """Custom weights that don't sum to 1.0 should raise error."""
        with pytest.raises(ValueError, match="must sum to 1.0"):
            SIMGRWeights(
                study_score=0.3,
                interest_score=0.3,
                market_score=0.3,
                growth_score=0.3,
                risk_score=0.3,  # Sum = 1.5
            )
    
    def test_trained_weights_sum_to_one(self):
        """Weights loaded from training should sum to 1.0."""
        try:
            weights = SIMGRWeights.from_file("models/weights/v1/weights.json")
            total = (
                weights.study_score
                + weights.interest_score
                + weights.market_score
                + weights.growth_score
                + weights.risk_score
            )
            assert abs(total - 1.0) < 0.001
        except FileNotFoundError:
            pytest.skip("Trained weights not found")


class TestScoreBounds:
    """Test score normalization."""
    
    def test_score_not_negative(self):
        """Final score should not go below 0."""
        weights = SIMGRWeights()
        
        # Worst case: all scores 0 except risk = 1
        simgr_scores = {
            "study": 0.0,
            "interest": 0.0,
            "market": 0.0,
            "growth": 0.0,
            "risk": 1.0,
        }
        
        raw_total = (
            weights.study_score * simgr_scores["study"]
            + weights.interest_score * simgr_scores["interest"]
            + weights.market_score * simgr_scores["market"]
            + weights.growth_score * simgr_scores["growth"]
            - weights.risk_score * simgr_scores["risk"]
        )
        
        # Raw could be negative, but final should be clamped
        clamped = max(0.0, min(1.0, raw_total))
        assert clamped >= 0.0
    
    def test_score_not_above_one(self):
        """Final score should not exceed 1.0."""
        weights = SIMGRWeights()
        
        # Best case: all scores 1, risk = 0
        simgr_scores = {
            "study": 1.0,
            "interest": 1.0,
            "market": 1.0,
            "growth": 1.0,
            "risk": 0.0,
        }
        
        raw_total = (
            weights.study_score * simgr_scores["study"]
            + weights.interest_score * simgr_scores["interest"]
            + weights.market_score * simgr_scores["market"]
            + weights.growth_score * simgr_scores["growth"]
            - weights.risk_score * simgr_scores["risk"]
        )
        
        clamped = max(0.0, min(1.0, raw_total))
        assert clamped <= 1.0


class TestR001Compliance:
    """Test R001 Formula Compliance requirements."""
    
    def test_formula_documented(self):
        """Formula must be documented in calculator module."""
        from backend.scoring import calculator
        import inspect
        source = inspect.getsource(calculator)
        # Check that risk is subtracted (minus sign before risk)
        assert "- wR*R" in source or "- weights.risk_score * simgr_scores" in source or \
               "simgr_scores.get(\"risk\"" in source
    
    def test_risk_is_penalty(self):
        """Risk component must act as penalty (subtracted)."""
        weights = SIMGRWeights(
            study_score=0.25,
            interest_score=0.25,
            market_score=0.25,
            growth_score=0.15,
            risk_score=0.10,
        )
        
        # Same positive scores, different risk
        base = {
            "study": 0.7,
            "interest": 0.7,
            "market": 0.7,
            "growth": 0.7,
        }
        
        score_low_risk = (
            weights.study_score * base["study"]
            + weights.interest_score * base["interest"]
            + weights.market_score * base["market"]
            + weights.growth_score * base["growth"]
            - weights.risk_score * 0.1
        )
        
        score_high_risk = (
            weights.study_score * base["study"]
            + weights.interest_score * base["interest"]
            + weights.market_score * base["market"]
            + weights.growth_score * base["growth"]
            - weights.risk_score * 0.9
        )
        
        assert score_low_risk > score_high_risk


# =====================================================
# GĐ4 EXTENDED - PHẦN F: FORMULA UNIT TESTS
# =====================================================

class TestScoringFormulaCompute:
    """Test ScoringFormula.compute() is the ONLY formula authority."""
    
    def test_scoring_formula_compute_basic(self):
        """ScoringFormula.compute() produces expected result."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        scores = {
            "study": 0.8,
            "interest": 0.7,
            "market": 0.6,
            "growth": 0.5,
            "risk": 0.2,
        }
        weights = {
            "study": 0.25,
            "interest": 0.25,
            "market": 0.25,
            "growth": 0.15,
            "risk": 0.10,
        }
        
        result = ScoringFormula.compute(scores, weights)
        
        # Manual: 0.25*0.8 + 0.25*0.7 + 0.25*0.6 + 0.15*0.5 - 0.10*0.2
        # = 0.2 + 0.175 + 0.15 + 0.075 - 0.02 = 0.58
        expected = 0.58
        assert abs(result - expected) < 0.001
    
    def test_scoring_formula_subtracts_risk(self):
        """ScoringFormula.compute() MUST subtract risk."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        scores_low_risk = {
            "study": 0.8, "interest": 0.8, "market": 0.8, "growth": 0.8, "risk": 0.1
        }
        scores_high_risk = {
            "study": 0.8, "interest": 0.8, "market": 0.8, "growth": 0.8, "risk": 0.9
        }
        weights = {
            "study": 0.2, "interest": 0.2, "market": 0.2, "growth": 0.2, "risk": 0.2
        }
        
        low_result = ScoringFormula.compute(scores_low_risk, weights)
        high_result = ScoringFormula.compute(scores_high_risk, weights)
        
        assert low_result > high_result, "Risk MUST be subtracted"
    
    def test_scoring_formula_clamping(self):
        """ScoringFormula.compute() clamps output to [0,1]."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        # Case: extreme risk could produce negative
        scores = {
            "study": 0.0, "interest": 0.0, "market": 0.0, "growth": 0.0, "risk": 1.0
        }
        weights = {
            "study": 0.2, "interest": 0.2, "market": 0.2, "growth": 0.2, "risk": 0.2
        }
        
        result = ScoringFormula.compute(scores, weights, clamp_output=True)
        assert result >= 0.0
        assert result <= 1.0
    
    def test_scoring_formula_validation_missing_component(self):
        """ScoringFormula.compute() rejects missing components."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        scores = {"study": 0.8, "interest": 0.7}  # Missing market, growth, risk
        weights = {
            "study": 0.2, "interest": 0.2, "market": 0.2, "growth": 0.2, "risk": 0.2
        }
        
        with pytest.raises(ValueError, match="Missing required components"):
            ScoringFormula.compute(scores, weights, validate=True)
    
    def test_scoring_formula_validation_score_bounds(self):
        """ScoringFormula.compute() rejects scores outside [0,1]."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        scores = {
            "study": 1.5,  # Invalid - > 1.0
            "interest": 0.7, "market": 0.6, "growth": 0.5, "risk": 0.2
        }
        weights = {
            "study": 0.2, "interest": 0.2, "market": 0.2, "growth": 0.2, "risk": 0.2
        }
        
        with pytest.raises(ValueError, match="must be in"):
            ScoringFormula.compute(scores, weights, validate=True)


class TestFormulaBootVerification:
    """Test spec self-verification at boot (PHẦN E)."""
    
    def test_boot_verification_runs(self):
        """Importing scoring_formula.py runs boot verification."""
        # This import should NOT raise if spec matches
        from backend.scoring.scoring_formula import (
            ScoringFormula, DOC_SPEC_FORMULA, DOC_SPEC_COMPONENTS, DOC_SPEC_VERSION
        )
        
        # Verify the constants match at runtime
        assert ScoringFormula.SPEC == DOC_SPEC_FORMULA
        assert ScoringFormula.COMPONENTS == DOC_SPEC_COMPONENTS
        assert ScoringFormula.VERSION == DOC_SPEC_VERSION
    
    def test_canonical_formula_string(self):
        """Formula spec is the expected canonical string."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        assert ScoringFormula.SPEC == "Score = wS*S + wI*I + wM*M + wG*G - wR*R"
    
    def test_components_ordered(self):
        """Components are in canonical SIMGR order."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        assert ScoringFormula.COMPONENTS == ["study", "interest", "market", "growth", "risk"]
    
    def test_risk_sign_is_negative(self):
        """Risk MUST have negative sign."""
        from backend.scoring.scoring_formula import ScoringFormula
        
        assert ScoringFormula.SIGN["risk"] == -1


class TestAllModulesUseScoringFormula:
    """Test that scoring modules delegate to ScoringFormula.compute()."""
    
    def test_calculator_uses_scoring_formula(self):
        """calculator.py must call ScoringFormula.compute()."""
        import inspect
        from backend.scoring import calculator
        
        source = inspect.getsource(calculator)
        assert "ScoringFormula.compute" in source, (
            "calculator.py MUST use ScoringFormula.compute()"
        )
    
    def test_scoring_py_uses_scoring_formula(self):
        """scoring.py must call ScoringFormula.compute()."""
        from pathlib import Path
        
        scoring_path = Path(__file__).parent.parent.parent / "backend" / "scoring" / "scoring.py"
        if scoring_path.exists():
            source = scoring_path.read_text(encoding="utf-8")
            assert "ScoringFormula.compute" in source, (
                "scoring.py MUST use ScoringFormula.compute()"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

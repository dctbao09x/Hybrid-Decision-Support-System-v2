# tests/scoring/test_formula_consistency.py
"""
GĐ4 Extended - PHẦN G: Inference Consistency Check

This module performs exhaustive grid testing to verify:
- ScoringFormula.compute() produces consistent results
- Results match the expected formula: Score = wS*S + wI*I + wM*M + wG*G - wR*R
- Tolerance ≤ 1e-6 between expected and actual

Grid: S, I, M, G, R ∈ [0, 1] with step=0.1 (11^5 = 161,051 combinations)
For efficiency, we test a representative subset + edge cases.
"""

import pytest
import itertools
from typing import Dict, Tuple, List

# Configure precision
TOLERANCE = 1e-6
GRID_STEP = 0.1
GRID_VALUES = [round(x * GRID_STEP, 1) for x in range(11)]  # 0.0 to 1.0


def _get_scoring_formula():
    """
    Get ScoringFormula class directly without triggering full scoring package.
    
    This avoids import chain: scoring/__init__.py -> scoring.py -> engine.py
    which creates a global RankingEngine at import time.
    """
    import importlib.util
    from pathlib import Path
    
    # Find the module path
    module_path = Path(__file__).parent.parent.parent / "backend" / "scoring" / "scoring_formula.py"
    
    # Use importlib to load directly
    spec = importlib.util.spec_from_file_location("scoring_formula_direct", str(module_path))
    module = importlib.util.module_from_spec(spec)
    
    # Add to sys.modules to avoid dataclass issues
    import sys
    sys.modules["scoring_formula_direct"] = module
    
    spec.loader.exec_module(module)
    return module.ScoringFormula


# Cache the class
_ScoringFormula = None


def get_scoring_formula():
    """Get cached ScoringFormula class."""
    global _ScoringFormula
    if _ScoringFormula is None:
        try:
            # Try direct module import first (faster)
            from backend.scoring.scoring_formula import ScoringFormula
            _ScoringFormula = ScoringFormula
        except (ImportError, TypeError):
            # Fallback to isolated import
            _ScoringFormula = _get_scoring_formula()
    return _ScoringFormula


def expected_formula(
    scores: Dict[str, float],
    weights: Dict[str, float]
) -> float:
    """
    Reference implementation of SIMGR formula.
    
    Formula: Score = wS*S + wI*I + wM*M + wG*G - wR*R
    
    This is the GROUND TRUTH for testing.
    """
    return (
        weights["study"] * scores["study"]
        + weights["interest"] * scores["interest"]
        + weights["market"] * scores["market"]
        + weights["growth"] * scores["growth"]
        - weights["risk"] * scores["risk"]  # RISK SUBTRACTED
    )


class TestInferenceConsistency:
    """
    Exhaustive consistency tests for ScoringFormula.compute().
    
    Verifies that ScoringFormula.compute() matches expected_formula()
    within TOLERANCE for all tested combinations.
    """
    
    @pytest.fixture
    def equal_weights(self) -> Dict[str, float]:
        """Equal weights for all components."""
        return {
            "study": 0.2,
            "interest": 0.2,
            "market": 0.2,
            "growth": 0.2,
            "risk": 0.2,
        }
    
    @pytest.fixture
    def trained_weights(self) -> Dict[str, float]:
        """Weights that simulate trained distribution."""
        return {
            "study": 0.25,
            "interest": 0.25,
            "market": 0.25,
            "growth": 0.15,
            "risk": 0.10,
        }
    
    def test_grid_corners_equal_weights(self, equal_weights):
        """Test all corner cases (0 or 1 for each component)."""
        ScoringFormula = get_scoring_formula()
        
        corners = [0.0, 1.0]
        errors: List[Tuple[Dict, float, float]] = []
        
        for s, i, m, g, r in itertools.product(corners, repeat=5):
            scores = {
                "study": s, "interest": i, "market": m, "growth": g, "risk": r
            }
            
            expected = expected_formula(scores, equal_weights)
            actual = ScoringFormula.compute(
                scores, equal_weights, validate=False, clamp_output=False
            )
            
            if abs(expected - actual) > TOLERANCE:
                errors.append((scores, expected, actual))
        
        assert not errors, f"Consistency failures at corners:\n{errors[:5]}"
    
    def test_grid_corners_trained_weights(self, trained_weights):
        """Test corners with realistic weights."""
        ScoringFormula = get_scoring_formula()
        
        corners = [0.0, 1.0]
        errors: List[Tuple[Dict, float, float]] = []
        
        for s, i, m, g, r in itertools.product(corners, repeat=5):
            scores = {
                "study": s, "interest": i, "market": m, "growth": g, "risk": r
            }
            
            expected = expected_formula(scores, trained_weights)
            actual = ScoringFormula.compute(
                scores, trained_weights, validate=False, clamp_output=False
            )
            
            if abs(expected - actual) > TOLERANCE:
                errors.append((scores, expected, actual))
        
        assert not errors, f"Consistency failures at corners:\n{errors[:5]}"
    
    def test_grid_midpoints(self, equal_weights):
        """Test midpoint grid (step=0.5) - fast comprehensive check."""
        ScoringFormula = get_scoring_formula()
        
        midpoints = [0.0, 0.5, 1.0]
        errors: List[Tuple[Dict, float, float]] = []
        
        for s, i, m, g, r in itertools.product(midpoints, repeat=5):
            scores = {
                "study": s, "interest": i, "market": m, "growth": g, "risk": r
            }
            
            expected = expected_formula(scores, equal_weights)
            actual = ScoringFormula.compute(
                scores, equal_weights, validate=False, clamp_output=False
            )
            
            if abs(expected - actual) > TOLERANCE:
                errors.append((scores, expected, actual))
        
        assert not errors, f"Consistency failures at midpoints:\n{errors[:5]}"
    
    @pytest.mark.slow
    def test_full_grid_equal_weights(self, equal_weights):
        """
        Full grid test with step=0.1 (161,051 combinations).
        
        This is exhaustive but slow - mark as slow test.
        """
        ScoringFormula = get_scoring_formula()
        
        errors: List[Tuple[Dict, float, float]] = []
        
        for s, i, m, g, r in itertools.product(GRID_VALUES, repeat=5):
            scores = {
                "study": s, "interest": i, "market": m, "growth": g, "risk": r
            }
            
            expected = expected_formula(scores, equal_weights)
            actual = ScoringFormula.compute(
                scores, equal_weights, validate=False, clamp_output=False
            )
            
            if abs(expected - actual) > TOLERANCE:
                errors.append((scores, expected, actual))
                if len(errors) >= 10:  # Fail fast after 10 errors
                    break
        
        assert not errors, (
            f"Consistency failures ({len(errors)} total):\n"
            f"{errors[:5]}"
        )
    
    def test_specific_known_values(self, trained_weights):
        """Test specific known-value cases."""
        ScoringFormula = get_scoring_formula()
        
        test_cases = [
            # (scores, expected_result)
            (
                {"study": 0.8, "interest": 0.7, "market": 0.6, "growth": 0.5, "risk": 0.2},
                0.25*0.8 + 0.25*0.7 + 0.25*0.6 + 0.15*0.5 - 0.10*0.2
            ),
            (
                {"study": 1.0, "interest": 1.0, "market": 1.0, "growth": 1.0, "risk": 0.0},
                0.25 + 0.25 + 0.25 + 0.15  # = 0.9 (max positive)
            ),
            (
                {"study": 0.0, "interest": 0.0, "market": 0.0, "growth": 0.0, "risk": 1.0},
                -0.10  # (max risk, clamped to 0 with clamp_output=True)
            ),
            (
                {"study": 0.5, "interest": 0.5, "market": 0.5, "growth": 0.5, "risk": 0.5},
                0.25*0.5 + 0.25*0.5 + 0.25*0.5 + 0.15*0.5 - 0.10*0.5
            ),
        ]
        
        for scores, expected in test_cases:
            actual = ScoringFormula.compute(
                scores, trained_weights, validate=False, clamp_output=False
            )
            assert abs(actual - expected) <= TOLERANCE, (
                f"Mismatch for {scores}:\n"
                f"  Expected: {expected}\n"
                f"  Actual  : {actual}"
            )
    
    def test_risk_sign_consistency(self, equal_weights):
        """Verify risk is consistently subtracted across grid."""
        ScoringFormula = get_scoring_formula()
        
        # For any fixed positive scores, increasing risk MUST decrease total
        base_positives = {
            "study": 0.7, "interest": 0.7, "market": 0.7, "growth": 0.7
        }
        
        last_total = None
        for risk_val in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
            scores = {**base_positives, "risk": risk_val}
            total = ScoringFormula.compute(
                scores, equal_weights, validate=False, clamp_output=False
            )
            
            if last_total is not None:
                assert total < last_total, (
                    f"Risk monotonicity violated: "
                    f"risk={risk_val} gave {total} >= {last_total}"
                )
            last_total = total
    
    def test_clamping_consistency(self, trained_weights):
        """Test that clamping works correctly at boundaries."""
        ScoringFormula = get_scoring_formula()
        
        # Case: negative raw result (high risk, zero positives)
        neg_scores = {
            "study": 0.0, "interest": 0.0, "market": 0.0, 
            "growth": 0.0, "risk": 1.0
        }
        raw = ScoringFormula.compute(
            neg_scores, trained_weights, clamp_output=False
        )
        clamped = ScoringFormula.compute(
            neg_scores, trained_weights, clamp_output=True
        )
        
        assert raw < 0.0, "Raw should be negative"
        assert clamped == 0.0, "Clamped should be 0"
        
        # Case: positive raw result within bounds
        pos_scores = {
            "study": 0.8, "interest": 0.7, "market": 0.6,
            "growth": 0.5, "risk": 0.2
        }
        raw = ScoringFormula.compute(
            pos_scores, trained_weights, clamp_output=False
        )
        clamped = ScoringFormula.compute(
            pos_scores, trained_weights, clamp_output=True
        )
        
        assert 0.0 <= raw <= 1.0, "Raw should be in bounds"
        assert raw == clamped, "No clamping needed for in-bound values"


class TestFormulaStability:
    """Test formula produces stable results on repeated calls."""
    
    def test_repeated_calls_identical(self):
        """Multiple calls with same inputs produce identical results."""
        ScoringFormula = get_scoring_formula()
        
        scores = {
            "study": 0.73, "interest": 0.82, "market": 0.45,
            "growth": 0.61, "risk": 0.29
        }
        weights = {
            "study": 0.22, "interest": 0.28, "market": 0.20,
            "growth": 0.18, "risk": 0.12
        }
        
        results = [
            ScoringFormula.compute(scores, weights)
            for _ in range(100)
        ]
        
        assert all(r == results[0] for r in results), (
            "Formula should be deterministic"
        )
    
    def test_float_precision_consistency(self):
        """Test precision is maintained for edge floating-point cases."""
        ScoringFormula = get_scoring_formula()
        
        # Use values that might cause floating-point issues
        scores = {
            "study": 0.1, "interest": 0.1, "market": 0.1,
            "growth": 0.1, "risk": 0.1
        }
        weights = {
            "study": 0.2, "interest": 0.2, "market": 0.2,
            "growth": 0.2, "risk": 0.2
        }
        
        # Expected: 0.2*0.1 + 0.2*0.1 + 0.2*0.1 + 0.2*0.1 - 0.2*0.1 = 0.06
        expected = 0.06
        actual = ScoringFormula.compute(
            scores, weights, validate=False, clamp_output=False
        )
        
        assert abs(actual - expected) <= TOLERANCE


if __name__ == "__main__":
    # Run fast tests by default, add -m slow for full grid
    pytest.main([__file__, "-v", "-m", "not slow"])

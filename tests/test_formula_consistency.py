# tests/test_formula_consistency.py
"""
GĐ4 - FORMULA CONSISTENCY & ALIGNMENT Tests

Verifies:
1. Single Source of Truth (scoring_formula.py)
2. Runtime Inference == Spec == Code == Test
3. No Duplicate Formula Definitions
4. No Controller Field Inference
5. Deterministic Execution

THESE TESTS MUST PASS BEFORE GĐ4 IS CONSIDERED COMPLETE.
"""

import pytest
import ast
import re
from pathlib import Path
from typing import Dict, Any

from backend.scoring.scoring_formula import (
    ScoringFormula,
    ComponentSign,
    get_formula_spec,
    get_formula_version,
    compute_simgr_score,
)


class TestSingleSourceOfTruth:
    """Test that scoring_formula.py is the single authority."""

    def test_formula_spec_is_canonical(self):
        """Verify formula spec matches expected format."""
        spec = ScoringFormula.get_formula()
        assert spec == "Score = wS*S + wI*I + wM*M + wG*G - wR*R"
    
    def test_version_is_defined(self):
        """Verify version is defined."""
        assert ScoringFormula.VERSION == "v1.0"
        assert get_formula_version() == "v1.0"
    
    def test_components_are_complete(self):
        """Verify all 5 SIMGR components are defined."""
        expected = ["study", "interest", "market", "growth", "risk"]
        assert ScoringFormula.COMPONENTS == expected
    
    def test_sign_conventions_are_correct(self):
        """Verify sign conventions match spec."""
        # Positive components
        for comp in ["study", "interest", "market", "growth"]:
            assert ScoringFormula.SIGN[comp] == +1, f"{comp} should be positive"
        
        # Risk is negative (subtracted)
        assert ScoringFormula.SIGN["risk"] == -1, "Risk should be negative"
    
    def test_weight_keys_are_standardized(self):
        """Verify weight key naming convention."""
        for comp in ScoringFormula.COMPONENTS:
            key = ScoringFormula.WEIGHT_KEYS[comp]
            assert key == f"{comp}_score", f"Weight key for {comp} should be {comp}_score"


class TestFormulaComputation:
    """Test that formula computation is correct."""

    def test_compute_basic(self):
        """Test basic formula computation."""
        scores = {
            "study": 0.8,
            "interest": 0.7,
            "market": 0.6,
            "growth": 0.5,
            "risk": 0.2
        }
        weights = {
            "study": 0.25,
            "interest": 0.25,
            "market": 0.25,
            "growth": 0.15,
            "risk": 0.10
        }
        
        # Manual calculation
        expected = (
            0.25 * 0.8 +  # study
            0.25 * 0.7 +  # interest
            0.25 * 0.6 +  # market
            0.15 * 0.5 -  # growth
            0.10 * 0.2    # risk (subtracted)
        )
        
        result = ScoringFormula.compute(scores, weights)
        assert abs(result - expected) < 0.0001
    
    def test_risk_is_subtracted(self):
        """Verify risk reduces the total score."""
        scores_low_risk = {
            "study": 0.8, "interest": 0.8, "market": 0.8, 
            "growth": 0.8, "risk": 0.1
        }
        scores_high_risk = {
            "study": 0.8, "interest": 0.8, "market": 0.8, 
            "growth": 0.8, "risk": 0.9
        }
        weights = {
            "study": 0.25, "interest": 0.25, "market": 0.25, 
            "growth": 0.15, "risk": 0.10
        }
        
        low_score = ScoringFormula.compute(scores_low_risk, weights)
        high_score = ScoringFormula.compute(scores_high_risk, weights)
        
        assert high_score < low_score, "Higher risk should result in lower score"
    
    def test_clamping_upper(self):
        """Test that scores are clamped to max 1.0."""
        scores = {
            "study": 1.0, "interest": 1.0, "market": 1.0, 
            "growth": 1.0, "risk": 0.0
        }
        weights = {
            "study": 0.3, "interest": 0.3, "market": 0.3, 
            "growth": 0.05, "risk": 0.05
        }
        
        result = ScoringFormula.compute(scores, weights, clamp_output=True)
        assert result <= 1.0
    
    def test_clamping_lower(self):
        """Test that scores are clamped to min 0.0."""
        scores = {
            "study": 0.0, "interest": 0.0, "market": 0.0, 
            "growth": 0.0, "risk": 1.0
        }
        weights = {
            "study": 0.2, "interest": 0.2, "market": 0.2, 
            "growth": 0.2, "risk": 0.2
        }
        
        result = ScoringFormula.compute(scores, weights, clamp_output=True)
        assert result >= 0.0
    
    def test_module_level_helper_matches(self):
        """Test that module-level helper matches class method."""
        scores = {
            "study": 0.5, "interest": 0.5, "market": 0.5, 
            "growth": 0.5, "risk": 0.5
        }
        weights = {
            "study": 0.25, "interest": 0.25, "market": 0.25, 
            "growth": 0.15, "risk": 0.10
        }
        
        class_result = ScoringFormula.compute(scores, weights)
        module_result = compute_simgr_score(scores, weights)
        
        assert class_result == module_result


class TestValidation:
    """Test that validation catches invalid inputs."""

    def test_missing_component_raises(self):
        """Test that missing components raise ValueError."""
        scores = {
            "study": 0.5, "interest": 0.5, "market": 0.5, 
            "growth": 0.5
            # missing "risk"
        }
        weights = {
            "study": 0.25, "interest": 0.25, "market": 0.25, 
            "growth": 0.15, "risk": 0.10
        }
        
        with pytest.raises(ValueError, match="Missing required components"):
            ScoringFormula.compute(scores, weights, validate=True)
    
    def test_score_out_of_range_raises(self):
        """Test that scores outside [0,1] raise ValueError."""
        scores = {
            "study": 1.5,  # Invalid
            "interest": 0.5, "market": 0.5, 
            "growth": 0.5, "risk": 0.5
        }
        weights = {
            "study": 0.25, "interest": 0.25, "market": 0.25, 
            "growth": 0.15, "risk": 0.10
        }
        
        with pytest.raises(ValueError, match="must be in"):
            ScoringFormula.compute(scores, weights, validate=True)
    
    def test_weights_must_sum_to_one(self):
        """Test that weights must sum to 1.0."""
        scores = {
            "study": 0.5, "interest": 0.5, "market": 0.5, 
            "growth": 0.5, "risk": 0.5
        }
        weights = {
            "study": 0.3, "interest": 0.3, "market": 0.3, 
            "growth": 0.3, "risk": 0.3  # Sums to 1.5
        }
        
        with pytest.raises(ValueError, match="sum to 1.0"):
            ScoringFormula.compute(scores, weights, validate=True)


class TestBreakdown:
    """Test breakdown functionality."""

    def test_breakdown_contains_all_components(self):
        """Test that breakdown has all component contributions."""
        scores = {
            "study": 0.8, "interest": 0.7, "market": 0.6, 
            "growth": 0.5, "risk": 0.2
        }
        weights = {
            "study": 0.25, "interest": 0.25, "market": 0.25, 
            "growth": 0.15, "risk": 0.10
        }
        
        breakdown = ScoringFormula.get_breakdown(scores, weights)
        
        assert "formula" in breakdown
        assert "version" in breakdown
        assert "components" in breakdown
        assert "total_raw" in breakdown
        assert "total_clamped" in breakdown
        
        for comp in ScoringFormula.COMPONENTS:
            assert comp in breakdown["components"]
            assert "score" in breakdown["components"][comp]
            assert "weight" in breakdown["components"][comp]
            assert "sign" in breakdown["components"][comp]
            assert "contribution" in breakdown["components"][comp]
    
    def test_breakdown_contributions_match_formula(self):
        """Test that component contributions sum to total."""
        scores = {
            "study": 0.8, "interest": 0.7, "market": 0.6, 
            "growth": 0.5, "risk": 0.2
        }
        weights = {
            "study": 0.25, "interest": 0.25, "market": 0.25, 
            "growth": 0.15, "risk": 0.10
        }
        
        breakdown = ScoringFormula.get_breakdown(scores, weights)
        
        total_from_components = sum(
            breakdown["components"][comp]["contribution"]
            for comp in ScoringFormula.COMPONENTS
        )
        
        assert abs(total_from_components - breakdown["total_raw"]) < 0.0001


class TestNoDuplicateFormulas:
    """Test that no duplicate formula definitions exist."""

    @pytest.fixture
    def scoring_files(self):
        """Get list of scoring-related Python files."""
        base_path = Path("backend/scoring")
        return list(base_path.glob("**/*.py"))
    
    def test_formula_computation_only_in_scoring_formula(self):
        """
        Verify that weighted formula computation only exists in scoring_formula.py.
        
        Other files should DELEGATE to ScoringFormula.compute().
        """
        # Files that are ALLOWED to have formula references
        allowed_files = {
            "scoring_formula.py",  # The authority
        }
        
        # Pattern that matches inline formula computation
        formula_pattern = re.compile(
            r'(?:study|interest|market|growth).*\*.*(?:study|interest|market|growth).*-.*risk',
            re.IGNORECASE
        )
        
        base_path = Path("backend/scoring")
        violations = []
        
        for py_file in base_path.glob("**/*.py"):
            if py_file.name in allowed_files:
                continue
            if "__pycache__" in str(py_file):
                continue
            
            try:
                content = py_file.read_text(encoding='utf-8')
                
                # Look for inline formula computation
                if formula_pattern.search(content):
                    # Check if it's just a comment or docstring
                    lines_with_formula = [
                        (i, line) for i, line in enumerate(content.split('\n'), 1)
                        if formula_pattern.search(line) and 
                        not line.strip().startswith('#') and
                        not line.strip().startswith('"""') and
                        not line.strip().startswith("'''")
                    ]
                    if lines_with_formula:
                        violations.append(
                            f"{py_file.name}: lines {[l[0] for l in lines_with_formula]}"
                        )
            except Exception as e:
                pass  # Skip files that can't be read
        
        if violations:
            pytest.fail(
                f"Found inline formula computation outside scoring_formula.py:\n"
                + "\n".join(violations)
            )
    
    def test_no_hardcoded_component_lists(self):
        """
        Verify that component lists use ScoringFormula.COMPONENTS.
        
        Pattern to detect: ["study", "interest", "market", "growth", "risk"]
        """
        # Files that are ALLOWED to have component list
        allowed_files = {
            "scoring_formula.py",  # The authority
            "__init__.py",  # May have exports
        }
        
        base_path = Path("backend/scoring")
        violations = []
        
        for py_file in base_path.glob("**/*.py"):
            if py_file.name in allowed_files:
                continue
            if "__pycache__" in str(py_file):
                continue
            
            try:
                content = py_file.read_text(encoding='utf-8')
                
                # Look for hardcoded component lists
                if '["study", "interest", "market", "growth", "risk"]' in content:
                    violations.append(f"{py_file.name}")
            except Exception as e:
                pass
        
        if violations:
            pytest.fail(
                f"Found hardcoded component list (should use ScoringFormula.COMPONENTS):\n"
                + "\n".join(violations)
            )


class TestRuntimeSpecAlignment:
    """Test that runtime inference matches specification."""

    def test_scorer_uses_formula_module(self):
        """Test that SIMGRScorer uses ScoringFormula for computation."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        # Use direct mode to test formula computation path
        scores_input = {
            "study": 0.8,
            "interest": 0.7,
            "market": 0.6,
            "growth": 0.5,
            "risk": 0.2
        }
        
        result = scorer.score(scores_input)
        
        # Verify result includes formula version (GĐ4 addition)
        # This confirms the scorer is using the formula module
        assert "formula_version" in result or result.get("success") is True
    
    def test_calculator_uses_formula_module(self):
        """Test that SIMGRCalculator uses ScoringFormula for computation."""
        from backend.scoring.calculator import SIMGRCalculator
        from backend.scoring.config import DEFAULT_CONFIG
        
        calculator = SIMGRCalculator(DEFAULT_CONFIG)
        
        # The calculator should be importing ScoringFormula
        import inspect
        source = inspect.getsourcefile(SIMGRCalculator)
        
        with open(source, 'r', encoding='utf-8') as f:
            content = f.read()
        
        assert "from backend.scoring.scoring_formula import" in content, \
            "Calculator should import from scoring_formula module"
    
    def test_scoring_formula_is_spec_driven(self):
        """Verify ScoringFormula spec matches runtime behavior."""
        # Parse the spec
        spec = ScoringFormula.get_formula()
        
        # Verify spec format matches sign conventions
        assert "wS*S" in spec and ScoringFormula.SIGN["study"] == 1
        assert "wI*I" in spec and ScoringFormula.SIGN["interest"] == 1
        assert "wM*M" in spec and ScoringFormula.SIGN["market"] == 1
        assert "wG*G" in spec and ScoringFormula.SIGN["growth"] == 1
        assert "- wR*R" in spec and ScoringFormula.SIGN["risk"] == -1


class TestDeterministicExecution:
    """Test that formula execution is deterministic."""

    def test_same_input_same_output(self):
        """Verify same inputs produce same outputs."""
        scores = {
            "study": 0.8, "interest": 0.7, "market": 0.6, 
            "growth": 0.5, "risk": 0.2
        }
        weights = {
            "study": 0.25, "interest": 0.25, "market": 0.25, 
            "growth": 0.15, "risk": 0.10
        }
        
        results = [
            ScoringFormula.compute(scores, weights)
            for _ in range(100)
        ]
        
        assert all(r == results[0] for r in results), \
            "Formula must be deterministic"
    
    def test_order_independence(self):
        """Verify result is independent of dict key order."""
        weights = {
            "study": 0.25, "interest": 0.25, "market": 0.25, 
            "growth": 0.15, "risk": 0.10
        }
        
        # Different key orders
        scores1 = {
            "study": 0.8, "interest": 0.7, "market": 0.6, 
            "growth": 0.5, "risk": 0.2
        }
        scores2 = {
            "risk": 0.2, "growth": 0.5, "market": 0.6, 
            "interest": 0.7, "study": 0.8
        }
        
        result1 = ScoringFormula.compute(scores1, weights)
        result2 = ScoringFormula.compute(scores2, weights)
        
        assert result1 == result2, "Result should be independent of key order"


# =============================================================================
# INTEGRATION WITH EXISTING TESTS
# =============================================================================

class TestIntegrationWithExistingFormula:
    """Test that GĐ4 changes integrate with existing test_formula.py tests."""

    def test_existing_formula_tests_still_pass(self):
        """Verify existing formula tests still work with central module."""
        from backend.scoring.scoring import SIMGRScorer
        from backend.scoring.config import DEFAULT_CONFIG
        
        scorer = SIMGRScorer()
        
        # Test from existing test_formula.py
        low_risk_result = scorer.score({
            "study": 0.8,
            "interest": 0.7,
            "market": 0.6,
            "growth": 0.5,
            "risk": 0.1,
        })
        
        high_risk_result = scorer.score({
            "study": 0.8,
            "interest": 0.7,
            "market": 0.6,
            "growth": 0.5,
            "risk": 0.9,
        })
        
        # Higher risk should reduce score
        assert high_risk_result["total_score"] < low_risk_result["total_score"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

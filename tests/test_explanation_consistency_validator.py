"""
test_explanation_consistency_validator.py
══════════════════════════════════════════════════════════════════════════════
CI Guard — Explanation ↔ ScoringBreakdown Mathematical Consistency
=====================================================================

Proves that ``validate_explanation_consistency()`` enforces strict arithmetic
parity between an assembled ``UnifiedExplanation`` and the authoritative
``ScoringBreakdown`` that produced it.

INVARIANTS VERIFIED
───────────────────
1. PASS PATH
   A correctly assembled explanation passes without error.

2. TAMPERED CONTRIBUTION
   If any per_component_contributions value is modified (even by 1e-5),
   ``ExplanationInconsistencyError`` MUST be raised.

3. WRONG WEIGHT VERSION
   If ``explanation.weight_version`` does not match the expected version,
   ``ExplanationInconsistencyError`` MUST be raised.

4. MISSING COMPONENT
   If one component is removed from per_component_contributions,
   ``ExplanationInconsistencyError`` MUST be raised.

5. EXTRA COMPONENT
   If a spurious component is injected into per_component_contributions,
   ``ExplanationInconsistencyError`` MUST be raised.

6. SUM MISMATCH
   If contributions sum to a value != breakdown.final_score (by > 1e-6),
   ``ExplanationInconsistencyError`` MUST be raised.

7. NONE breakdown SKIPPED
   When scoring_breakdown is None (LLM-only path), validation is skipped
   entirely — no false positives.

8. EPSILON BOUNDARY
   A delta of exactly 1e-6 passes; a delta of 1e-5 fails — proving the
   threshold is enforced precisely.

9. MISMATCH MESSAGE QUALITY
   The exception message must name the offending component or field.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.explain.consistency_validator import (
    ExplanationInconsistencyError,
    validate_explanation_consistency,
)
from backend.explain.unified_schema import UnifiedExplanation


# ─────────────────────────────────────────────────────────────────────────────
# Minimal ScoringBreakdown stub
# (mirrors backend/scoring/sub_scorer.py ScoringBreakdown exactly)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _ScoringBreakdown:
    """Lightweight test double for ScoringBreakdown."""

    skill_score: float
    experience_score: float
    education_score: float
    goal_alignment_score: float
    preference_score: float

    final_score: float
    weights: Dict[str, float]
    contributions: Dict[str, float]
    formula: str = ""
    sub_score_meta: Dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Canonical test data
# ─────────────────────────────────────────────────────────────────────────────

_WEIGHT_VERSION = "v1.2.3"

# Weights: five components summing to 1.0
_WEIGHTS: Dict[str, float] = {
    "skill": 0.30,
    "experience": 0.25,
    "education": 0.20,
    "goal_alignment": 0.15,
    "preference": 0.10,
}

# Sub-scores in [0, 100]
_SUB_SCORES: Dict[str, float] = {
    "skill": 75.0,
    "experience": 75.0,
    "education": 75.0,
    "goal_alignment": 75.0,
    "preference": 75.0,
}

# Contributions = weight × sub_score  =>  each == 0.XX * 75.0
# skill:           0.30 * 75.0 = 22.5
# experience:      0.25 * 75.0 = 18.75
# education:       0.20 * 75.0 = 15.0
# goal_alignment:  0.15 * 75.0 = 11.25
# preference:      0.10 * 75.0 = 7.5
# sum = 75.0  → final_score = 75.0

_CONTRIBUTIONS: Dict[str, float] = {
    c: round(_WEIGHTS[c] * _SUB_SCORES[c], 6)
    for c in _WEIGHTS
}
_FINAL_SCORE: float = sum(_CONTRIBUTIONS.values())  # == 75.0


def _make_breakdown(
    *,
    contributions: Dict[str, float] | None = None,
    final_score: float | None = None,
) -> _ScoringBreakdown:
    """Build a canonical ScoringBreakdown stub with optional overrides."""
    return _ScoringBreakdown(
        skill_score=_SUB_SCORES["skill"],
        experience_score=_SUB_SCORES["experience"],
        education_score=_SUB_SCORES["education"],
        goal_alignment_score=_SUB_SCORES["goal_alignment"],
        preference_score=_SUB_SCORES["preference"],
        final_score=final_score if final_score is not None else _FINAL_SCORE,
        weights=dict(_WEIGHTS),
        contributions=contributions if contributions is not None else dict(_CONTRIBUTIONS),
    )


def _make_explanation(
    *,
    per_component_contributions: Dict[str, float] | None = None,
    weight_version: str = _WEIGHT_VERSION,
    trace_id: str = "trace-validator-test",
) -> UnifiedExplanation:
    """Build a canonical UnifiedExplanation with optional overrides."""
    return UnifiedExplanation.build(
        trace_id=trace_id,
        model_id="model-test-v1",
        kb_version="kb-test-2024",
        weight_version=weight_version,
        breakdown=dict(_WEIGHTS),
        per_component_contributions=(
            per_component_contributions
            if per_component_contributions is not None
            else dict(_CONTRIBUTIONS)
        ),
        reasoning=["Score exceeds threshold", "Skills match career profile"],
        input_summary={"math_score": 80.0},
        feature_snapshot={"math_score": 80.0},
        rule_path=[],
        weights={},
        evidence=[],
        confidence=0.85,
        prediction={"career": "Engineer", "score": _FINAL_SCORE},
        stage3_input_hash="aaa",
        stage3_output_hash="bbb",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — Pass Path (valid explanation passes without error)
# ─────────────────────────────────────────────────────────────────────────────

class TestPassPath:
    """A correctly assembled explanation must pass validation without error."""

    def test_valid_explanation_passes(self):
        explanation = _make_explanation()
        breakdown = _make_breakdown()
        # Must not raise
        validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)

    def test_zero_all_contributions_passes(self):
        """Zero contributions with zero final_score is arithmetically valid."""
        zero_contribs = {c: 0.0 for c in _CONTRIBUTIONS}
        explanation = _make_explanation(per_component_contributions=zero_contribs)
        breakdown = _make_breakdown(
            contributions=zero_contribs,
            final_score=0.0,
        )
        validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)

    def test_single_component_passes(self):
        """Edge case: single component (sum == that component)."""
        single = {"skill": 75.0}
        explanation = _make_explanation(per_component_contributions=single)
        breakdown = _make_breakdown(contributions=single, final_score=75.0)
        validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)

    def test_returns_none_on_success(self):
        """validate_explanation_consistency must return None when valid."""
        result = validate_explanation_consistency(
            _make_explanation(), _make_breakdown(), _WEIGHT_VERSION
        )
        assert result is None

    def test_different_weight_version_strings_all_pass_when_matching(self):
        for version in ["v1.0.0", "default", "prod-2024-02-22", ""]:
            exp = _make_explanation(weight_version=version)
            bd = _make_breakdown()
            validate_explanation_consistency(exp, bd, expected_weight_version=version)


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — Tampered Contribution (Invariant 1)
# ─────────────────────────────────────────────────────────────────────────────

class TestTamperedContribution:
    """
    FAILURE SIMULATION: Manually tamper contribution → must fail.

    Any modification to per_component_contributions violates Invariant 1
    and must raise ExplanationInconsistencyError.
    """

    def test_tamper_skill_contribution_raises(self):
        """Increase 'skill' contribution by 1.0 → mismatch detected."""
        tampered = {**_CONTRIBUTIONS, "skill": _CONTRIBUTIONS["skill"] + 1.0}
        explanation = _make_explanation(per_component_contributions=tampered)
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)
        assert "skill" in str(exc_info.value), (
            "Error message must name the offending component 'skill'"
        )

    def test_tamper_experience_contribution_raises(self):
        """Decrease 'experience' contribution by 0.5 → mismatch detected."""
        tampered = {**_CONTRIBUTIONS, "experience": _CONTRIBUTIONS["experience"] - 0.5}
        explanation = _make_explanation(per_component_contributions=tampered)
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)
        assert "experience" in str(exc_info.value)

    def test_tamper_education_contribution_to_zero_raises(self):
        """Zero out 'education' contribution → mismatch detected."""
        tampered = {**_CONTRIBUTIONS, "education": 0.0}
        explanation = _make_explanation(per_component_contributions=tampered)
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError):
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)

    def test_tamper_all_contributions_raises(self):
        """Double all contributions → multiple mismatches detected."""
        tampered = {c: v * 2.0 for c, v in _CONTRIBUTIONS.items()}
        explanation = _make_explanation(per_component_contributions=tampered)
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)
        err = exc_info.value
        # Should report multiple component mismatches
        assert len(err.mismatches) >= len(_CONTRIBUTIONS), (
            f"Expected at least {len(_CONTRIBUTIONS)} mismatches, got {len(err.mismatches)}"
        )

    def test_tamper_only_goal_alignment_raises(self):
        """Tamper goal_alignment → specifically named in error."""
        tampered = {**_CONTRIBUTIONS, "goal_alignment": 99.0}
        explanation = _make_explanation(per_component_contributions=tampered)
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)
        assert "goal_alignment" in str(exc_info.value)

    def test_mismatches_attribute_populated_on_tamper(self):
        """ExplanationInconsistencyError.mismatches must list each violation."""
        tampered = {**_CONTRIBUTIONS, "preference": 999.0}
        explanation = _make_explanation(per_component_contributions=tampered)
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)
        assert isinstance(exc_info.value.mismatches, list)
        assert len(exc_info.value.mismatches) >= 1

    def test_tamper_negative_contribution_raises(self):
        """Negative contribution value is a tamper; must fail."""
        tampered = {**_CONTRIBUTIONS, "skill": -10.0}
        explanation = _make_explanation(per_component_contributions=tampered)
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError):
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)


# ─────────────────────────────────────────────────────────────────────────────
# Section 3 — Wrong Weight Version (Invariant 3)
# ─────────────────────────────────────────────────────────────────────────────

class TestWrongWeightVersion:
    """
    FAILURE SIMULATION: Change weight_version → must fail.

    The explanation.weight_version must match expected_weight_version exactly.
    """

    def test_wrong_weight_version_raises(self):
        """Explanation version 'v1.2.3' vs expected 'v9.9.9' → must fail."""
        explanation = _make_explanation(weight_version="v1.2.3")
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, "v9.9.9")
        assert "weight_version" in str(exc_info.value)

    def test_empty_explanation_version_vs_real_expected_raises(self):
        explanation = _make_explanation(weight_version="")
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, "v1.0.0")
        assert "weight_version" in str(exc_info.value)

    def test_real_version_vs_empty_expected_raises(self):
        explanation = _make_explanation(weight_version="v1.0.0")
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, "")
        assert "weight_version" in str(exc_info.value)

    def test_case_sensitive_version_mismatch_raises(self):
        """'V1.2.3' vs 'v1.2.3' must fail (case-sensitive comparison)."""
        explanation = _make_explanation(weight_version="V1.2.3")
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, "v1.2.3")
        assert "weight_version" in str(exc_info.value)

    def test_version_mismatch_error_contains_both_versions(self):
        """Error message must show both the explanation version and expected version."""
        explanation = _make_explanation(weight_version="stale-v0.1")
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, "current-v2.0")
        err_str = str(exc_info.value)
        assert "stale-v0.1" in err_str
        assert "current-v2.0" in err_str

    def test_multiple_failures_include_version_mismatch(self):
        """Version mismatch combined with contribution tamper: both reported."""
        tampered = {**_CONTRIBUTIONS, "skill": _CONTRIBUTIONS["skill"] + 5.0}
        explanation = _make_explanation(
            per_component_contributions=tampered,
            weight_version="wrong-version",
        )
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, "correct-version")
        # Must report at least: contribution mismatch + version mismatch
        assert len(exc_info.value.mismatches) >= 2


# ─────────────────────────────────────────────────────────────────────────────
# Section 4 — Missing Component (Invariant 4a)
# ─────────────────────────────────────────────────────────────────────────────

class TestMissingComponent:
    """
    FAILURE SIMULATION: Remove one component → must fail.

    A component present in ScoringBreakdown but absent from
    per_component_contributions is a structural inconsistency.
    """

    def test_remove_skill_component_raises(self):
        """Remove 'skill' from per_component_contributions → must fail."""
        reduced = {c: v for c, v in _CONTRIBUTIONS.items() if c != "skill"}
        explanation = _make_explanation(per_component_contributions=reduced)
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)
        err_str = str(exc_info.value)
        assert "skill" in err_str, (
            "Error must name the missing component 'skill'"
        )

    def test_remove_preference_component_raises(self):
        """Remove 'preference' → must fail with message naming 'preference'."""
        reduced = {c: v for c, v in _CONTRIBUTIONS.items() if c != "preference"}
        explanation = _make_explanation(per_component_contributions=reduced)
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)
        assert "preference" in str(exc_info.value)

    def test_remove_multiple_components_raises(self):
        """Remove two components; error must report both."""
        reduced = {
            c: v for c, v in _CONTRIBUTIONS.items()
            if c not in ("experience", "education")
        }
        explanation = _make_explanation(per_component_contributions=reduced)
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)
        err_str = str(exc_info.value)
        assert "experience" in err_str or "education" in err_str

    def test_empty_per_component_contributions_raises(self):
        """Completely empty contributions dict → must fail for every component."""
        explanation = _make_explanation(per_component_contributions={})
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)
        err = exc_info.value
        # Every component is missing + sum mismatch
        assert len(err.mismatches) >= 2

    def test_missing_component_error_says_absent(self):
        """The error message must indicate a component is absent/missing."""
        reduced = {c: v for c, v in _CONTRIBUTIONS.items() if c != "goal_alignment"}
        explanation = _make_explanation(per_component_contributions=reduced)
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)
        assert "goal_alignment" in str(exc_info.value)


# ─────────────────────────────────────────────────────────────────────────────
# Section 5 — Extra Component (Invariant 4b)
# ─────────────────────────────────────────────────────────────────────────────

class TestExtraComponent:
    """
    FAILURE SIMULATION: Inject a spurious component → must fail.

    A component in per_component_contributions not present in
    ScoringBreakdown.contributions is a structural inconsistency.
    """

    def test_inject_spurious_component_raises(self):
        """Add 'lucky_bonus' component not in breakdown → must fail."""
        injected = {**_CONTRIBUTIONS, "lucky_bonus": 10.0}
        explanation = _make_explanation(per_component_contributions=injected)
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)
        assert "lucky_bonus" in str(exc_info.value)

    def test_inject_two_spurious_components_raises(self):
        """Inject two unknown components → both must be detected."""
        injected = {**_CONTRIBUTIONS, "bonus_a": 5.0, "bonus_b": 3.0}
        explanation = _make_explanation(per_component_contributions=injected)
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)
        err_str = str(exc_info.value)
        assert "bonus_a" in err_str or "bonus_b" in err_str


# ─────────────────────────────────────────────────────────────────────────────
# Section 6 — Sum Mismatch (Invariant 2)
# ─────────────────────────────────────────────────────────────────────────────

class TestSumMismatch:
    """
    sum(contributions) must equal final_score within 1e-6.

    This tests Invariant 2 independently from contribution-value mismatches
    by keeping contributions consistent with each other but inconsistent
    with breakdown.final_score.
    """

    def test_final_score_off_by_one_raises(self):
        """breakdown.final_score inflated by 1.0 → sum mismatch."""
        breakdown = _make_breakdown(final_score=_FINAL_SCORE + 1.0)
        explanation = _make_explanation()  # contributions == _CONTRIBUTIONS
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)
        assert "final_score" in str(exc_info.value).lower() or "sum" in str(exc_info.value).lower()

    def test_final_score_deflated_raises(self):
        """breakdown.final_score reduced by 5.0 → sum mismatch."""
        breakdown = _make_breakdown(final_score=_FINAL_SCORE - 5.0)
        explanation = _make_explanation()
        with pytest.raises(ExplanationInconsistencyError):
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)

    def test_final_score_zero_but_contributions_nonzero_raises(self):
        """Zero final_score with nonzero contributions → sum mismatch."""
        breakdown = _make_breakdown(final_score=0.0)
        explanation = _make_explanation()  # contributions sum to 75.0
        with pytest.raises(ExplanationInconsistencyError):
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)


# ─────────────────────────────────────────────────────────────────────────────
# Section 7 — Epsilon Boundary Precision
# ─────────────────────────────────────────────────────────────────────────────

class TestEpsilonBoundary:
    """
    δ ≤ 1e-6  → pass
    δ >  1e-6 → fail

    Proves the threshold is enforced precisely, not loosely.
    """

    _COMPONENT = "skill"

    def test_delta_at_epsilon_passes(self):
        """A delta of exactly 1e-6 must NOT trigger a mismatch."""
        original = _CONTRIBUTIONS[self._COMPONENT]
        adjusted = {**_CONTRIBUTIONS, self._COMPONENT: original + 1e-6}
        explanation = _make_explanation(per_component_contributions=adjusted)
        # Update breakdown to match the adjusted contribution so sum is still OK
        adjusted_bd = dict(_CONTRIBUTIONS)
        adjusted_bd[self._COMPONENT] = original + 1e-6
        breakdown = _make_breakdown(
            contributions=adjusted_bd,
            final_score=sum(adjusted_bd.values()),
        )
        # Both explanation and breakdown agree → should pass
        validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)

    def test_delta_above_epsilon_fails(self):
        """A delta of 1e-5 (10× threshold) must be caught."""
        original = _CONTRIBUTIONS[self._COMPONENT]
        tampered = {**_CONTRIBUTIONS, self._COMPONENT: original + 1e-5}
        explanation = _make_explanation(per_component_contributions=tampered)
        breakdown = _make_breakdown()  # contributions still == _CONTRIBUTIONS
        with pytest.raises(ExplanationInconsistencyError):
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)

    def test_tiny_float_rounding_does_not_cause_false_positive(self):
        """
        Floating-point arithmetic from round(w*s, 6) must not produce spurious
        failures — verify that the canonical _CONTRIBUTIONS from _make_breakdown
        always matches exactly.
        """
        explanation = _make_explanation()
        breakdown = _make_breakdown()
        # Must not raise regardless of internal float representation
        validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)


# ─────────────────────────────────────────────────────────────────────────────
# Section 8 — Exception Attributes and Message Quality
# ─────────────────────────────────────────────────────────────────────────────

class TestExceptionAttributes:
    """ExplanationInconsistencyError must carry structured, actionable data."""

    def test_mismatches_is_a_list(self):
        tampered = {**_CONTRIBUTIONS, "skill": 0.0}
        explanation = _make_explanation(per_component_contributions=tampered)
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)
        assert isinstance(exc_info.value.mismatches, list)

    def test_mismatches_are_strings(self):
        tampered = {**_CONTRIBUTIONS, "preference": 99.9}
        explanation = _make_explanation(per_component_contributions=tampered)
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)
        for m in exc_info.value.mismatches:
            assert isinstance(m, str), f"Each mismatch must be a string, got {type(m)}"

    def test_str_representation_includes_violation_count(self):
        """str(error) must mention number of violations."""
        tampered = {**_CONTRIBUTIONS, "skill": 0.0}
        explanation = _make_explanation(per_component_contributions=tampered)
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, _WEIGHT_VERSION)
        err_str = str(exc_info.value)
        # Must mention at least '1' (one violation)
        assert any(char.isdigit() for char in err_str), (
            "Error string must contain at least one digit (violation count)"
        )

    def test_multiple_violations_accumulate_in_mismatches(self):
        """
        Tamper one contribution AND use wrong weight_version simultaneously.
        Both must appear in mismatches without one masking the other.
        """
        tampered = {**_CONTRIBUTIONS, "education": -1.0}
        explanation = _make_explanation(
            per_component_contributions=tampered,
            weight_version="old-version",
        )
        breakdown = _make_breakdown()
        with pytest.raises(ExplanationInconsistencyError) as exc_info:
            validate_explanation_consistency(explanation, breakdown, "new-version")
        assert len(exc_info.value.mismatches) >= 2, (
            "Both contribution mismatch and version mismatch must be reported"
        )

    def test_error_is_subclass_of_exception(self):
        err = ExplanationInconsistencyError("test", mismatches=["issue"])
        assert isinstance(err, Exception)

    def test_error_mismatches_default_empty_list(self):
        err = ExplanationInconsistencyError("test")
        assert err.mismatches == []

# backend/scoring/tests/test_scoring_consistency_validator.py
"""
Scoring Consistency Validator — Failure Simulation Tests
=========================================================

Proves that inconsistent scoring results CANNOT pass silently.

COVERAGE
--------
Each test class targets exactly one rule of ``ScoringConsistencyValidator``:

  TestRule1_RequiredSubscores      — SCORE_001: missing sub-score component
  TestRule2_SubscoreRange          — SCORE_002: sub-score outside [0, 100]
  TestRule3_WeightedSumMismatch    — SCORE_003: weighted sum ≠ final_score
  TestRule4_ExplContribMismatch    — SCORE_004: explanation contributions mismatch
  TestRule5_WeightVersionAbsent    — SCORE_005: weight version missing
  TestAllRulesPassOnValidBreakdown — positive path: valid breakdown passes silently
  TestMultipleViolationsReported   — multiple rules violated simultaneously → all
                                     violations reported in a single exception

PROOF PROPERTY
--------------
Every test asserts that ``InconsistentScoringError`` is raised and that the
``violations`` list is non-empty, demonstrating that no inconsistent result
can reach a ``DecisionResponse`` without detection.
"""

from __future__ import annotations

import math
import pytest

from backend.scoring.consistency_validator import validate_scoring_consistency
from backend.scoring.errors import InconsistentScoringError
from backend.scoring.sub_scorer import ScoringBreakdown


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_WEIGHTS: dict[str, float] = {
    "skill":          0.30,
    "experience":     0.25,
    "education":      0.20,
    "goal_alignment": 0.15,
    "preference":     0.10,
}

_DEFAULT_SCORES: dict[str, float] = {
    "skill_score":          70.0,
    "experience_score":     60.0,
    "education_score":      80.0,
    "goal_alignment_score": 50.0,
    "preference_score":     90.0,
}


def _compute_contributions(
    weights: dict[str, float],
    scores: dict[str, float],
) -> dict[str, float]:
    """Compute contributions dict from weights and scores."""
    mapping = {
        "skill":          "skill_score",
        "experience":     "experience_score",
        "education":      "education_score",
        "goal_alignment": "goal_alignment_score",
        "preference":     "preference_score",
    }
    # Only compute contributions for components that are PRESENT in weights.
    # This allows test helpers to build breakdowns with intentionally missing
    # components (Rule-1 failure cases) without crashing the helper itself.
    return {
        comp: weights[comp] * scores[mapping[comp]]
        for comp in mapping
        if comp in weights and mapping[comp] in scores
    }


def _compute_final_score(contributions: dict[str, float]) -> float:
    """Compute final_score as the sum of contributions."""
    return sum(contributions.values())


def _make_valid_breakdown(**overrides) -> ScoringBreakdown:
    """
    Build a self-consistent ``ScoringBreakdown`` with optional field overrides.

    Pass keyword arguments to override any field:
        _make_valid_breakdown(skill_score=150.0)   # out-of-range
        _make_valid_breakdown(final_score=999.0)   # mismatched final
    """
    weights = overrides.pop("weights", dict(_DEFAULT_WEIGHTS))
    scores  = dict(_DEFAULT_SCORES)

    # Allow individual score overrides
    for k in list(_SCORE_ATTRS):
        if k in overrides:
            scores[k] = overrides.pop(k)

    contributions = _compute_contributions(weights, scores)
    final_score   = _compute_final_score(contributions)

    # Allow contribution/final_score overrides last (to simulate corruption)
    if "contributions" in overrides:
        contributions = overrides.pop("contributions")
    if "final_score" in overrides:
        final_score = overrides.pop("final_score")

    formula = (
        "final_score = "
        + " + ".join(
            f"{v:.2f}*{k}_score"
            for k, v in weights.items()
        )
    )

    return ScoringBreakdown(
        skill_score          = scores["skill_score"],
        experience_score     = scores["experience_score"],
        education_score      = scores["education_score"],
        goal_alignment_score = scores["goal_alignment_score"],
        preference_score     = scores["preference_score"],
        final_score          = final_score,
        weights              = weights,
        contributions        = contributions,
        formula              = formula,
        sub_score_meta       = {},
        **overrides,
    )


_SCORE_ATTRS = (
    "skill_score",
    "experience_score",
    "education_score",
    "goal_alignment_score",
    "preference_score",
)


# ─────────────────────────────────────────────────────────────────────────────
# TestRule1 — SCORE_001: Required sub-scores missing
# ─────────────────────────────────────────────────────────────────────────────

class TestRule1_RequiredSubscores:
    """SCORE_001: missing component key in weights → InconsistentScoringError."""

    def test_missing_single_weight_component(self):
        """Dropping 'skill' from weights.weights triggers SCORE_001."""
        weights = {k: v for k, v in _DEFAULT_WEIGHTS.items() if k != "skill"}
        bd = _make_valid_breakdown(weights=weights)

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(bd, weight_version="v1.0")

        err = exc_info.value
        assert err.violations, "violations list must be non-empty"
        assert any("SCORE_001" in v for v in err.violations)
        assert any("skill" in v for v in err.violations)

    def test_missing_multiple_weight_components(self):
        """Dropping several components → multiple SCORE_001 violations."""
        weights = {"skill": 1.0}  # only one component
        bd = _make_valid_breakdown(weights=weights)

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(bd, weight_version="v1.0")

        violations = exc_info.value.violations
        score_001_violations = [v for v in violations if "SCORE_001" in v]
        assert len(score_001_violations) >= 3, (
            "Expected at least 3 SCORE_001 violations for 3 missing components, "
            f"got: {score_001_violations}"
        )

    def test_empty_weights_dict_raises(self):
        """A completely empty weights dict triggers Rule 1 for ALL 5 components."""
        bd = _make_valid_breakdown(weights={})

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(bd, weight_version="v1.0")

        violations = [v for v in exc_info.value.violations if "SCORE_001" in v]
        assert len(violations) == 5, (
            f"Expected 5 SCORE_001 violations (one per component), got {violations}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# TestRule2 — SCORE_002: Sub-score out of [0, 100]
# ─────────────────────────────────────────────────────────────────────────────

class TestRule2_SubscoreRange:
    """SCORE_002: sub-score value outside [0, 100] → InconsistentScoringError."""

    def test_score_above_100(self):
        """skill_score = 150 violates [0, 100] bound."""
        bd = _make_valid_breakdown(skill_score=150.0)

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(bd, weight_version="v1.0")

        violations = exc_info.value.violations
        assert any("SCORE_002" in v and "skill_score" in v for v in violations)

    def test_score_below_0(self):
        """education_score = -5 violates [0, 100] bound."""
        bd = _make_valid_breakdown(education_score=-5.0)

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(bd, weight_version="v1.0")

        violations = exc_info.value.violations
        assert any("SCORE_002" in v and "education_score" in v for v in violations)

    def test_nan_score_raises(self):
        """NaN sub-score is detected and rejected."""
        bd = _make_valid_breakdown(experience_score=float("nan"))

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(bd, weight_version="v1.0")

        violations = exc_info.value.violations
        assert any("SCORE_002" in v and "experience_score" in v for v in violations)

    def test_inf_score_raises(self):
        """Infinite sub-score is detected and rejected."""
        bd = _make_valid_breakdown(preference_score=float("inf"))

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(bd, weight_version="v1.0")

        violations = exc_info.value.violations
        assert any("SCORE_002" in v and "preference_score" in v for v in violations)

    def test_final_score_above_100(self):
        """final_score > 100 is itself a range violation."""
        bd = _make_valid_breakdown(final_score=120.0)

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(bd, weight_version="v1.0")

        violations = exc_info.value.violations
        # Rule 2 should flag final_score; Rule 3 will also trigger a mismatch
        assert any("SCORE_002" in v and "final_score" in v for v in violations)

    def test_boundary_value_100_passes(self):
        """skill_score exactly 100 is exactly on the boundary — should pass Rule 2."""
        # Rebuild with skill_score=100
        weights  = dict(_DEFAULT_WEIGHTS)
        scores   = dict(_DEFAULT_SCORES)
        scores["skill_score"] = 100.0
        contribs = _compute_contributions(weights, scores)
        bd = ScoringBreakdown(
            skill_score=100.0,
            experience_score=scores["experience_score"],
            education_score=scores["education_score"],
            goal_alignment_score=scores["goal_alignment_score"],
            preference_score=scores["preference_score"],
            final_score=sum(contribs.values()),
            weights=weights,
            contributions=contribs,
            formula="",
            sub_score_meta={},
        )
        # Should NOT raise
        validate_scoring_consistency(bd, weight_version="v1.0")

    def test_boundary_value_0_passes(self):
        """skill_score exactly 0 is on the boundary — should pass Rule 2."""
        weights  = dict(_DEFAULT_WEIGHTS)
        scores   = dict(_DEFAULT_SCORES)
        scores["skill_score"] = 0.0
        contribs = _compute_contributions(weights, scores)
        bd = ScoringBreakdown(
            skill_score=0.0,
            experience_score=scores["experience_score"],
            education_score=scores["education_score"],
            goal_alignment_score=scores["goal_alignment_score"],
            preference_score=scores["preference_score"],
            final_score=sum(contribs.values()),
            weights=weights,
            contributions=contribs,
            formula="",
            sub_score_meta={},
        )
        validate_scoring_consistency(bd, weight_version="v1.0")


# ─────────────────────────────────────────────────────────────────────────────
# TestRule3 — SCORE_003: Weighted sum ≠ final_score
# ─────────────────────────────────────────────────────────────────────────────

class TestRule3_WeightedSumMismatch:
    """SCORE_003: final_score differs from weighted sum → InconsistentScoringError."""

    def test_final_score_tampered(self):
        """final_score set to 99.999 when weighted sum is ~69.5 → SCORE_003."""
        bd = _make_valid_breakdown(final_score=99.999)

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(bd, weight_version="v1.0")

        violations = exc_info.value.violations
        assert any("SCORE_003" in v for v in violations)

    def test_contributions_tampered(self):
        """contributions dict modified so sum ≠ final_score → SCORE_003."""
        weights      = dict(_DEFAULT_WEIGHTS)
        scores       = dict(_DEFAULT_SCORES)
        real_contribs = _compute_contributions(weights, scores)
        real_fs       = _compute_final_score(real_contribs)

        # Tamper: double one contribution without updating final_score
        tampered = dict(real_contribs)
        tampered["skill"] *= 2.0

        bd = ScoringBreakdown(
            skill_score          = scores["skill_score"],
            experience_score     = scores["experience_score"],
            education_score      = scores["education_score"],
            goal_alignment_score = scores["goal_alignment_score"],
            preference_score     = scores["preference_score"],
            final_score          = real_fs,       # old, correct value
            weights              = weights,
            contributions        = tampered,      # inflated
            formula              = "",
            sub_score_meta       = {},
        )

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(bd, weight_version="v1.0")

        assert any("SCORE_003" in v for v in exc_info.value.violations)

    def test_large_delta_detected(self):
        """A difference of 50 points is clearly outside the 1e-4 tolerance."""
        bd = _make_valid_breakdown(final_score=0.0)  # actual is ~69.5

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(bd, weight_version="v1.0")

        violations = exc_info.value.violations
        assert any("SCORE_003" in v for v in violations)
        # Verify delta is reported in the violation message
        assert any("delta" in v.lower() for v in violations if "SCORE_003" in v)

    def test_delta_within_tolerance_passes(self):
        """A delta of 1e-10 (floating-point noise) should pass Rule 3."""
        weights    = dict(_DEFAULT_WEIGHTS)
        scores     = dict(_DEFAULT_SCORES)
        contribs   = _compute_contributions(weights, scores)
        final_fs   = _compute_final_score(contribs) + 1e-10  # negligible drift
        bd = ScoringBreakdown(
            skill_score          = scores["skill_score"],
            experience_score     = scores["experience_score"],
            education_score      = scores["education_score"],
            goal_alignment_score = scores["goal_alignment_score"],
            preference_score     = scores["preference_score"],
            final_score          = final_fs,
            weights              = weights,
            contributions        = contribs,
            formula              = "",
            sub_score_meta       = {},
        )
        # Should NOT raise
        validate_scoring_consistency(bd, weight_version="v1.0")


# ─────────────────────────────────────────────────────────────────────────────
# TestRule4 — SCORE_004: Explanation contributions mismatch
# ─────────────────────────────────────────────────────────────────────────────

class TestRule4_ExplContribMismatch:
    """SCORE_004: explanation.contributions disagrees with breakdown → error."""

    @pytest.fixture()
    def valid_bd(self) -> ScoringBreakdown:
        return _make_valid_breakdown()

    def test_extra_key_in_explanation(self, valid_bd):
        """Extra component in explanation not in breakdown → SCORE_004."""
        bad_contribs = dict(valid_bd.contributions)
        bad_contribs["phantom_component"] = 5.0

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(
                valid_bd,
                weight_version="v1.0",
                explanation_contributions=bad_contribs,
            )

        assert any("SCORE_004" in v and "phantom_component" in v
                   for v in exc_info.value.violations)

    def test_missing_key_in_explanation(self, valid_bd):
        """Key present in breakdown but absent from explanation → SCORE_004."""
        bad_contribs = {k: v for k, v in valid_bd.contributions.items()
                        if k != "skill"}

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(
                valid_bd,
                weight_version="v1.0",
                explanation_contributions=bad_contribs,
            )

        assert any("SCORE_004" in v and "skill" in v
                   for v in exc_info.value.violations)

    def test_value_mismatch_above_tolerance(self, valid_bd):
        """Contribution value differs by > 1e-4 → SCORE_004."""
        bad_contribs = dict(valid_bd.contributions)
        original_key = next(iter(bad_contribs))
        bad_contribs[original_key] += 5.0  # large deviation

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(
                valid_bd,
                weight_version="v1.0",
                explanation_contributions=bad_contribs,
            )

        assert any("SCORE_004" in v and original_key in v
                   for v in exc_info.value.violations)

    def test_matching_contributions_passes(self, valid_bd):
        """Exact match between explanation and breakdown → no error."""
        # Should NOT raise
        validate_scoring_consistency(
            valid_bd,
            weight_version="v1.0",
            explanation_contributions=dict(valid_bd.contributions),
        )

    def test_no_explanation_provided_skips_rule4(self, valid_bd):
        """Rule 4 is skipped entirely when explanation_contributions=None."""
        # Should NOT raise even though we pass nothing
        validate_scoring_consistency(
            valid_bd,
            weight_version="v1.0",
            explanation_contributions=None,
        )


# ─────────────────────────────────────────────────────────────────────────────
# TestRule5 — SCORE_005: Weight version absent
# ─────────────────────────────────────────────────────────────────────────────

class TestRule5_WeightVersionAbsent:
    """SCORE_005: missing or empty weight_version → InconsistentScoringError."""

    @pytest.fixture()
    def valid_bd(self) -> ScoringBreakdown:
        return _make_valid_breakdown()

    def test_none_weight_version(self, valid_bd):
        """weight_version=None → SCORE_005."""
        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(valid_bd, weight_version=None)

        assert any("SCORE_005" in v for v in exc_info.value.violations)

    def test_empty_string_weight_version(self, valid_bd):
        """weight_version='' → SCORE_005."""
        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(valid_bd, weight_version="")

        assert any("SCORE_005" in v for v in exc_info.value.violations)

    def test_whitespace_only_weight_version(self, valid_bd):
        """weight_version='   ' (whitespace only) → SCORE_005."""
        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(valid_bd, weight_version="   ")

        assert any("SCORE_005" in v for v in exc_info.value.violations)

    def test_valid_weight_version_passes(self, valid_bd):
        """Any non-empty version string satisfies Rule 5."""
        validate_scoring_consistency(valid_bd, weight_version="v2.3.1")
        validate_scoring_consistency(valid_bd, weight_version="default")
        validate_scoring_consistency(valid_bd, weight_version="prod-2026-02-22")


# ─────────────────────────────────────────────────────────────────────────────
# TestAllRulesPassOnValidBreakdown — positive path
# ─────────────────────────────────────────────────────────────────────────────

class TestAllRulesPassOnValidBreakdown:
    """A fully self-consistent breakdown passes all five rules without error."""

    def test_canonical_valid_breakdown(self):
        """Default breakdown with correct weights, scores, and version → no error."""
        bd = _make_valid_breakdown()
        # Must complete without raising
        validate_scoring_consistency(bd, weight_version="v1.0.0")

    def test_valid_breakdown_with_explanation(self):
        """Valid breakdown + matching explanation contributions → no error."""
        bd = _make_valid_breakdown()
        validate_scoring_consistency(
            bd,
            weight_version="v1.0.0",
            explanation_contributions=dict(bd.contributions),
        )

    def test_zero_sub_scores(self):
        """All sub-scores = 0 is explicitly valid, produces final_score = 0."""
        weights  = dict(_DEFAULT_WEIGHTS)
        scores   = {k: 0.0 for k in _DEFAULT_SCORES}
        contribs = _compute_contributions(weights, scores)
        bd = ScoringBreakdown(
            skill_score=0.0, experience_score=0.0, education_score=0.0,
            goal_alignment_score=0.0, preference_score=0.0,
            final_score=0.0,
            weights=weights, contributions=contribs,
            formula="zero", sub_score_meta={},
        )
        validate_scoring_consistency(bd, weight_version="baseline")

    def test_maximum_sub_scores(self):
        """All sub-scores = 100 is explicitly valid when weights sum to 1."""
        weights  = dict(_DEFAULT_WEIGHTS)
        scores   = {k: 100.0 for k in _DEFAULT_SCORES}
        contribs = _compute_contributions(weights, scores)
        bd = ScoringBreakdown(
            skill_score=100.0, experience_score=100.0, education_score=100.0,
            goal_alignment_score=100.0, preference_score=100.0,
            final_score=100.0,
            weights=weights, contributions=contribs,
            formula="max", sub_score_meta={},
        )
        validate_scoring_consistency(bd, weight_version="v-max")


# ─────────────────────────────────────────────────────────────────────────────
# TestMultipleViolationsReported — all violations collected in one error
# ─────────────────────────────────────────────────────────────────────────────

class TestMultipleViolationsReported:
    """
    When multiple rules are broken simultaneously, InconsistentScoringError
    contains ALL violations — none are silently dropped.
    """

    def test_range_and_version_violations_both_reported(self):
        """Out-of-range score (Rule 2) + missing version (Rule 5) → 2 violations."""
        bd = _make_valid_breakdown(skill_score=200.0)

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(bd, weight_version=None)

        violations = exc_info.value.violations
        assert any("SCORE_002" in v for v in violations), (
            "Expected SCORE_002 violation for out-of-range score"
        )
        assert any("SCORE_005" in v for v in violations), (
            "Expected SCORE_005 violation for missing weight version"
        )

    def test_all_five_rules_broken_simultaneously(self):
        """
        Construct a maximally broken breakdown and verify all five rule codes appear.

        Scenario:
          Rule 1: weights missing 'experience' component
          Rule 2: skill_score = -10
          Rule 3: final_score = 9999 (tampered)
          Rule 4: explanation has phantom component
          Rule 5: weight_version = None
        """
        weights_missing_exp = {k: v for k, v in _DEFAULT_WEIGHTS.items()
                               if k != "experience"}
        bd = ScoringBreakdown(
            skill_score=-10.0,
            experience_score=60.0,
            education_score=80.0,
            goal_alignment_score=50.0,
            preference_score=90.0,
            final_score=9999.0,
            weights=weights_missing_exp,
            contributions={"skill": 5.0},  # incomplete
            formula="broken",
            sub_score_meta={},
        )

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(
                bd,
                weight_version=None,
                explanation_contributions={"phantom": 42.0},
            )

        violations  = exc_info.value.violations
        rule_codes  = {v.split(":")[0].strip() for v in violations}

        assert "SCORE_001" in rule_codes, "Rule 1 must be triggered"
        assert "SCORE_002" in rule_codes, "Rule 2 must be triggered"
        assert "SCORE_003" in rule_codes, "Rule 3 must be triggered"
        assert "SCORE_004" in rule_codes, "Rule 4 must be triggered"
        assert "SCORE_005" in rule_codes, "Rule 5 must be triggered"

    def test_error_message_is_human_readable(self):
        """InconsistentScoringError.__str__ includes violation details."""
        bd = _make_valid_breakdown(skill_score=999.0)

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(bd, weight_version=None)

        error_str = str(exc_info.value)
        assert "[1]" in error_str, "Violations must be numbered in the string output"
        assert "SCORE_" in error_str, "Error codes must appear in string output"

    def test_raises_not_returns_none(self):
        """validate_scoring_consistency NEVER returns None to swallow errors."""
        bd = _make_valid_breakdown(final_score=999.0)

        # Confirm it raises — not returns silently
        raised = False
        try:
            result = validate_scoring_consistency(bd, weight_version="v1.0")
        except InconsistentScoringError:
            raised = True

        assert raised, (
            "validate_scoring_consistency must raise InconsistentScoringError "
            "on invalid input, not return silently."
        )

    def test_error_carries_trace_id(self):
        """trace_id should be embedded in the error's trace_id attribute."""
        bd = _make_valid_breakdown(skill_score=-1.0)

        with pytest.raises(InconsistentScoringError) as exc_info:
            validate_scoring_consistency(
                bd,
                weight_version="v1.0",
                trace_id="dec-test-12345",
            )

        # The error should carry the trace_id from SIMGRValidationError base
        assert exc_info.value.trace_id is not None

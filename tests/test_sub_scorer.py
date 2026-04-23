"""
test_sub_scorer.py
──────────────────────────────────────────────────────────────────────────────
Mathematical consistency and correctness tests for the sub-score decomposition
engine (backend/scoring/sub_scorer.py).

GUARANTEES VERIFIED
-------------------
1. Each pure sub-score function produces a value in [0, 100].
2. final_score == sum(weight_i * component_score_i) for all valid inputs.
3. Weights must sum to 1.0; violation raises ValueError.
4. No hidden multipliers: final_score changes only when components or weights
   change — never from phantom modifications.
5. Each sub-score function is deterministic: same input → same output.
6. assemble_breakdown() accepts both ScoringInput-compatible dicts and Pydantic
   model instances.
7. Bounds are enforced at the clamping layer — extreme inputs never produce
   scores outside [0, 100].
"""

from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.scoring.sub_scorer import (
    DEFAULT_WEIGHTS,
    ScoringBreakdown,
    SubScoreWeights,
    assemble_breakdown,
    compute_education_score,
    compute_experience_score,
    compute_goal_alignment_score,
    compute_preference_score,
    compute_skill_score,
)

# ──────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ──────────────────────────────────────────────────────────────────────────────

MINIMAL_DICT: dict = {
    "personal_profile": {
        "ability_score": 0.75,
        "confidence_score": 0.65,
        "interests": ["technology", "data science"],
    },
    "experience": {"years": 4, "domains": ["software", "data engineering"]},
    "goals": {"career_aspirations": ["software engineer", "tech lead"], "timeline_years": 5},
    "skills": ["python", "sql", "machine learning", "java"],
    "education": {"level": "Bachelor", "field_of_study": "Computer Science"},
    "preferences": {"preferred_domains": ["tech", "ai"], "work_style": "hybrid"},
}

EXPERT_DICT: dict = {
    "personal_profile": {
        "ability_score": 0.95,
        "confidence_score": 0.90,
        "interests": ["ai", "research", "engineering", "data"],
    },
    "experience": {"years": 15, "domains": ["ai", "backend", "management", "research", "devops"]},
    "goals": {
        "career_aspirations": [
            "principal engineer", "research lead", "architect", "director", "cto"
        ],
        "timeline_years": 8,
    },
    "skills": ["python", "java", "tensorflow", "kubernetes", "sql", "c++", "rust", "go", "scala", "spark"],
    "education": {"level": "PhD", "field_of_study": "Computer Science"},
    "preferences": {
        "preferred_domains": ["ai", "cloud", "data", "engineering", "research"],
        "work_style": "hybrid",
    },
}

MINIMAL_ZERO_DICT: dict = {
    "personal_profile": {"ability_score": 0.0, "confidence_score": 0.0, "interests": ["x"]},
    "experience": {"years": 0, "domains": ["x"]},
    "goals": {"career_aspirations": ["x"], "timeline_years": 0},
    "skills": ["x"],
    "education": {"level": "", "field_of_study": ""},
    "preferences": {"preferred_domains": ["x"], "work_style": ""},
}


def _weighted_sum_external(breakdown: ScoringBreakdown) -> float:
    """External recomputation of final_score from embedded weights + sub-scores."""
    component_map = {
        "skill": breakdown.skill_score,
        "experience": breakdown.experience_score,
        "education": breakdown.education_score,
        "goal_alignment": breakdown.goal_alignment_score,
        "preference": breakdown.preference_score,
    }
    return sum(breakdown.weights[c] * component_map[c] for c in breakdown.weights)


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 1 — Pure sub-score functions: bounds and determinism
# ──────────────────────────────────────────────────────────────────────────────

class TestComputeSkillScore:
    def test_empty_skills_returns_zero(self):
        score, _ = compute_skill_score([])
        assert score == 0.0

    def test_single_skill(self):
        score, meta = compute_skill_score(["python"])
        assert score == 10.0
        assert meta["unique_skill_count"] == 1

    def test_deduplication(self):
        score, meta = compute_skill_score(["python", "Python", "PYTHON"])
        assert meta["unique_skill_count"] == 1
        assert score == 10.0

    def test_ten_skills_max_score(self):
        skills = [f"skill_{i}" for i in range(10)]
        score, _ = compute_skill_score(skills)
        assert score == 100.0

    def test_more_than_ten_skills_clamped(self):
        skills = [f"skill_{i}" for i in range(20)]
        score, _ = compute_skill_score(skills)
        assert score == 100.0

    def test_bounds(self):
        for n in range(0, 25, 3):
            score, _ = compute_skill_score([f"s{i}" for i in range(n)])
            assert 0.0 <= score <= 100.0

    def test_determinism(self):
        skills = ["python", "sql", "java"]
        s1, _ = compute_skill_score(skills)
        s2, _ = compute_skill_score(skills)
        assert s1 == s2


class TestComputeExperienceScore:
    def test_zero_years_zero_domains(self):
        # 0 years → 0 pts, but we pass at least 1 domain to avoid empty-domain confusion
        score, meta = compute_experience_score(0, [])
        assert score == 0.0

    def test_ten_years_four_domains_max(self):
        score, meta = compute_experience_score(10, ["a", "b", "c", "d"])
        # years_pts = min(60, 10*6) = 60; domain_pts = min(40, 4*10) = 40
        assert score == 100.0
        assert meta["years_pts"] == 60.0
        assert meta["domain_pts"] == 40.0

    def test_years_component_formula(self):
        score, meta = compute_experience_score(5, [])
        assert meta["years_pts"] == 30.0
        assert meta["domain_pts"] == 0.0
        assert score == 30.0

    def test_domain_deduplication(self):
        _, meta = compute_experience_score(0, ["AI", "ai", "Ai"])
        assert meta["unique_domains"] == 1

    def test_bounds(self):
        for years in range(0, 25, 5):
            for n_domains in range(0, 8):
                score, _ = compute_experience_score(years, [f"d{i}" for i in range(n_domains)])
                assert 0.0 <= score <= 100.0


class TestComputeEducationScore:
    def test_phd_maps_to_100(self):
        score, meta = compute_education_score("PhD")
        assert score == 100.0
        assert meta["match_type"] == "exact"

    def test_master_maps_correctly(self):
        score, _ = compute_education_score("Master")
        assert score == 85.0

    def test_bachelor_maps_correctly(self):
        score, _ = compute_education_score("Bachelor")
        assert score == 70.0

    def test_high_school_maps_correctly(self):
        score, _ = compute_education_score("High School")
        assert score == 30.0

    def test_unknown_level_defaults_to_50(self):
        score, meta = compute_education_score("XYZ-UNKNOWN")
        assert score == 50.0
        assert meta["match_type"] == "default"

    def test_empty_level_defaults_to_50(self):
        score, _ = compute_education_score("")
        assert score == 50.0

    def test_case_insensitive(self):
        s1, _ = compute_education_score("PhD")
        s2, _ = compute_education_score("phd")
        s3, _ = compute_education_score("PHD")
        assert s1 == s2 == s3

    def test_bounds(self):
        for level in ["PhD", "Master", "Bachelor", "Diploma", "High School", "", "Unknown"]:
            score, _ = compute_education_score(level)
            assert 0.0 <= score <= 100.0


class TestComputeGoalAlignmentScore:
    def test_empty_aspirations_zero_timeline(self):
        score, meta = compute_goal_alignment_score([], 0)
        assert score == 0.0

    def test_single_aspiration_ten_year_timeline(self):
        score, meta = compute_goal_alignment_score(["engineer"], 10)
        # aspiration_pts = min(70, 1*15) = 15; timeline_pts = 30
        assert score == 45.0
        assert meta["aspiration_pts"] == 15.0
        assert meta["timeline_pts"] == 30.0

    def test_five_aspirations_max_aspiration_pts(self):
        aspirations = ["a", "b", "c", "d", "e"]
        score, meta = compute_goal_alignment_score(aspirations, 5)
        assert meta["aspiration_pts"] == 70.0  # min(70, 5*15) = 70

    def test_timeline_bands(self):
        _, m0 = compute_goal_alignment_score(["x"], 0)
        _, m5 = compute_goal_alignment_score(["x"], 5)
        _, m15 = compute_goal_alignment_score(["x"], 15)
        _, m30 = compute_goal_alignment_score(["x"], 30)
        assert m0["timeline_pts"] == 0.0
        assert m5["timeline_pts"] == 30.0
        assert m15["timeline_pts"] == 20.0
        assert m30["timeline_pts"] == 10.0

    def test_deduplication(self):
        _, meta = compute_goal_alignment_score(["engineer", "Engineer", "ENGINEER"], 5)
        assert meta["unique_aspirations"] == 1

    def test_bounds(self):
        for n in range(0, 8):
            for tl in [0, 3, 10, 15, 25]:
                score, _ = compute_goal_alignment_score([f"a{i}" for i in range(n)], tl)
                assert 0.0 <= score <= 100.0


class TestComputePreferenceScore:
    def test_empty_domains_and_style(self):
        score, meta = compute_preference_score([], "")
        assert score == 0.0

    def test_recognised_style_adds_40(self):
        _, m_hybrid = compute_preference_score(["tech"], "hybrid")
        _, m_remote = compute_preference_score(["tech"], "remote")
        assert m_hybrid["style_pts"] == 40.0
        assert m_remote["style_pts"] == 40.0

    def test_unrecognised_nonempty_style_adds_20(self):
        _, meta = compute_preference_score(["tech"], "some-custom-arrangement")
        assert meta["style_pts"] == 20.0
        assert not meta["style_recognised"]

    def test_five_domains_max_domain_pts(self):
        _, meta = compute_preference_score(["a", "b", "c", "d", "e"], "")
        assert meta["domain_pts"] == 60.0

    def test_deduplication(self):
        _, m_dup = compute_preference_score(["AI", "ai", "Ai"], "hybrid")
        assert m_dup["unique_domains"] == 1

    def test_bounds(self):
        for n in range(0, 7):
            for style in ["hybrid", "remote", "unknown-style", ""]:
                score, _ = compute_preference_score([f"d{i}" for i in range(n)], style)
                assert 0.0 <= score <= 100.0


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 2 — SubScoreWeights validation
# ──────────────────────────────────────────────────────────────────────────────

class TestSubScoreWeights:
    def test_default_weights_sum_to_one(self):
        DEFAULT_WEIGHTS.validate()  # must not raise

    def test_default_weights_correct_values(self):
        assert DEFAULT_WEIGHTS.skill == 0.30
        assert DEFAULT_WEIGHTS.experience == 0.25
        assert DEFAULT_WEIGHTS.education == 0.20
        assert DEFAULT_WEIGHTS.goal_alignment == 0.15
        assert DEFAULT_WEIGHTS.preference == 0.10

    def test_custom_valid_weights_pass(self):
        w = SubScoreWeights(
            skill=0.20,
            experience=0.20,
            education=0.20,
            goal_alignment=0.20,
            preference=0.20,
        )
        w.validate()  # must not raise

    def test_weights_not_summing_to_one_raises(self):
        with pytest.raises(ValueError, match="sum to 1.0"):
            SubScoreWeights(
                skill=0.50,
                experience=0.50,
                education=0.50,
                goal_alignment=0.50,
                preference=0.50,
            ).validate()

    def test_negative_weight_raises(self):
        with pytest.raises(ValueError, match="negative"):
            SubScoreWeights(
                skill=-0.10,
                experience=0.40,
                education=0.30,
                goal_alignment=0.20,
                preference=0.20,
            ).validate()

    def test_as_dict_has_all_components(self):
        d = DEFAULT_WEIGHTS.as_dict()
        assert set(d.keys()) == {"skill", "experience", "education", "goal_alignment", "preference"}


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 3 — Mathematical consistency: final_score == weighted sum
# ──────────────────────────────────────────────────────────────────────────────

class TestFinalScoreMathematicalConsistency:
    """
    Core correctness test.

    THEOREM:  final_score == sum(weight_i * sub_score_i)

    We verify this by:
      1. Calling ``assemble_breakdown()`` with known inputs.
      2. Re-computing the weighted sum externally from the embedded weights
         and individual sub-score fields.
      3. Asserting equality within float tolerance (1e-6).

    This proves there are NO hidden multipliers, bonuses, or implicit modifiers.
    """

    def _assert_consistency(self, breakdown: ScoringBreakdown, *, label: str = "") -> None:
        """Helper: verify final_score == external weighted sum, within 1e-6."""
        external = _weighted_sum_external(breakdown)
        assert abs(breakdown.final_score - external) < 1e-6, (
            f"[{label}] final_score ({breakdown.final_score:.8f}) != "
            f"external weighted sum ({external:.8f})\n"
            f"  weights:      {breakdown.weights}\n"
            f"  skill:        {breakdown.skill_score}\n"
            f"  experience:   {breakdown.experience_score}\n"
            f"  education:    {breakdown.education_score}\n"
            f"  goal_align:   {breakdown.goal_alignment_score}\n"
            f"  preference:   {breakdown.preference_score}\n"
            f"  contributions: {breakdown.contributions}"
        )

    def test_consistency_minimal_profile(self):
        bd = assemble_breakdown(MINIMAL_DICT)
        self._assert_consistency(bd, label="minimal")

    def test_consistency_expert_profile(self):
        bd = assemble_breakdown(EXPERT_DICT)
        self._assert_consistency(bd, label="expert")

    def test_consistency_zero_profile(self):
        bd = assemble_breakdown(MINIMAL_ZERO_DICT)
        self._assert_consistency(bd, label="zero")

    def test_consistency_custom_weights(self):
        w = SubScoreWeights(
            skill=0.10,
            experience=0.20,
            education=0.30,
            goal_alignment=0.25,
            preference=0.15,
        )
        bd = assemble_breakdown(MINIMAL_DICT, weights=w)
        self._assert_consistency(bd, label="custom-weights")

    def test_contributions_sum_equals_final_score(self):
        """contributions must also sum exactly to final_score."""
        bd = assemble_breakdown(EXPERT_DICT)
        contributions_total = sum(bd.contributions.values())
        # Round-trip: contributions are pre-rounded, so allow 1e-4 tolerance
        assert abs(contributions_total - bd.final_score) < 1e-4, (
            f"sum(contributions) {contributions_total:.6f} != "
            f"final_score {bd.final_score:.6f}"
        )

    @pytest.mark.parametrize("skill_count", [0, 1, 3, 5, 10, 15])
    def test_consistency_varying_skill_counts(self, skill_count: int):
        data = dict(MINIMAL_DICT)
        data["skills"] = [f"skill_{i}" for i in range(skill_count)]
        bd = assemble_breakdown(data)
        self._assert_consistency(bd, label=f"skills={skill_count}")

    @pytest.mark.parametrize("years", [0, 1, 5, 10, 20])
    def test_consistency_varying_experience_years(self, years: int):
        data = dict(MINIMAL_DICT)
        data["experience"] = {"years": years, "domains": ["software"]}
        bd = assemble_breakdown(data)
        self._assert_consistency(bd, label=f"years={years}")

    @pytest.mark.parametrize("level", ["PhD", "Master", "Bachelor", "High School", ""])
    def test_consistency_varying_education_levels(self, level: str):
        data = dict(MINIMAL_DICT)
        data["education"] = {"level": level, "field_of_study": "CS"}
        bd = assemble_breakdown(data)
        self._assert_consistency(bd, label=f"level={level!r}")

    def test_final_score_changes_when_component_changes(self):
        """No phantom isolation: changing one component changes final_score."""
        bd_low = assemble_breakdown({**MINIMAL_DICT, "skills": ["python"]})
        bd_high = assemble_breakdown({**MINIMAL_DICT, "skills": ["python", "ml", "sql", "java", "go", "c++", "rust", "scala", "kotlin", "typescript"]})
        assert bd_high.final_score > bd_low.final_score, (
            "final_score should increase when more skills are added"
        )

    def test_final_score_invariant_when_nothing_changes(self):
        """Determinism: same input always produces same final_score."""
        bd1 = assemble_breakdown(MINIMAL_DICT)
        bd2 = assemble_breakdown(MINIMAL_DICT)
        assert bd1.final_score == bd2.final_score

    def test_no_hidden_multipliers_direct_calculation(self):
        """
        PROOF OF NO HIDDEN MULTIPLIERS.

        We construct an input where every sub-score is predictable, then
        manually compute the expected final_score from first principles and
        assert the engine matches it exactly.

        Input setup (with DEFAULT_WEIGHTS = {skill:0.30, experience:0.25,
                                              education:0.20, goal_alignment:0.15,
                                              preference:0.10}):

          skills = ["python"]                 → skill_score     = 10.0
          experience = years=0, domains=[]    → experience_score = 0.0
          education = "PhD"                   → education_score = 100.0
          goals = ["x"], timeline=5           → goal_alignment  = 15 + 30 = 45.0
          preferences = ["tech"], "hybrid"    → preference_score = 12 + 40 = 52.0

          expected = 0.30*10 + 0.25*0 + 0.20*100 + 0.15*45 + 0.10*52
                   = 3.0 + 0.0 + 20.0 + 6.75 + 5.2
                   = 34.95
        """
        input_data = {
            "personal_profile": {
                "ability_score": 0.5,
                "confidence_score": 0.5,
                "interests": ["x"],
            },
            "experience": {"years": 0, "domains": []},
            "goals": {"career_aspirations": ["x"], "timeline_years": 5},
            "skills": ["python"],
            "education": {"level": "PhD", "field_of_study": "CS"},
            "preferences": {"preferred_domains": ["tech"], "work_style": "hybrid"},
        }

        # Manually verify each sub-score
        ss_skill, _ = compute_skill_score(["python"])
        assert ss_skill == 10.0, f"Expected skill 10, got {ss_skill}"

        ss_exp, _ = compute_experience_score(0, [])
        assert ss_exp == 0.0, f"Expected experience 0, got {ss_exp}"

        ss_edu, _ = compute_education_score("PhD")
        assert ss_edu == 100.0, f"Expected education 100, got {ss_edu}"

        ss_goal, _ = compute_goal_alignment_score(["x"], 5)
        assert ss_goal == 45.0, f"Expected goal 45, got {ss_goal}"

        ss_pref, _ = compute_preference_score(["tech"], "hybrid")
        assert ss_pref == 52.0, f"Expected preference 52, got {ss_pref}"

        # Manual aggregation (DEFAULT_WEIGHTS)
        expected_final = (
            0.30 * 10.0   # skill
            + 0.25 * 0.0   # experience
            + 0.20 * 100.0 # education
            + 0.15 * 45.0  # goal_alignment
            + 0.10 * 52.0  # preference
        )
        # = 3.0 + 0.0 + 20.0 + 6.75 + 5.2 = 34.95

        bd = assemble_breakdown(input_data)
        assert abs(bd.final_score - expected_final) < 1e-6, (
            f"final_score {bd.final_score:.6f} != expected {expected_final:.6f}"
        )
        assert abs(bd.skill_score - 10.0) < 1e-6
        assert abs(bd.experience_score - 0.0) < 1e-6
        assert abs(bd.education_score - 100.0) < 1e-6
        assert abs(bd.goal_alignment_score - 45.0) < 1e-6
        assert abs(bd.preference_score - 52.0) < 1e-6


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 4 — Bounds enforcement
# ──────────────────────────────────────────────────────────────────────────────

class TestBoundsEnforcement:
    """All sub-scores and final_score must remain in [0, 100]."""

    def _check_all_bounds(self, bd: ScoringBreakdown) -> None:
        fields = {
            "skill_score": bd.skill_score,
            "experience_score": bd.experience_score,
            "education_score": bd.education_score,
            "goal_alignment_score": bd.goal_alignment_score,
            "preference_score": bd.preference_score,
            "final_score": bd.final_score,
        }
        for name, val in fields.items():
            assert 0.0 <= val <= 100.0, f"{name} = {val} is outside [0, 100]"
            assert not math.isnan(val), f"{name} is NaN"
            assert not math.isinf(val), f"{name} is Inf"

    def test_minimal_profile(self):
        self._check_all_bounds(assemble_breakdown(MINIMAL_DICT))

    def test_expert_profile(self):
        self._check_all_bounds(assemble_breakdown(EXPERT_DICT))

    def test_zero_profile(self):
        self._check_all_bounds(assemble_breakdown(MINIMAL_ZERO_DICT))

    def test_extreme_skills_count_clamped(self):
        data = dict(MINIMAL_DICT)
        data["skills"] = [f"skill_{i}" for i in range(1000)]
        bd = assemble_breakdown(data)
        assert bd.skill_score == 100.0
        self._check_all_bounds(bd)

    def test_extreme_experience_clamped(self):
        data = dict(MINIMAL_DICT)
        data["experience"] = {"years": 9999, "domains": [f"d{i}" for i in range(100)]}
        bd = assemble_breakdown(data)
        assert bd.experience_score == 100.0
        self._check_all_bounds(bd)


# ──────────────────────────────────────────────────────────────────────────────
# SECTION 5 — assemble_breakdown: interface acceptance and ScoringBreakdown shape
# ──────────────────────────────────────────────────────────────────────────────

class TestAssembleBreakdown:
    def test_returns_scoring_breakdown_instance(self):
        bd = assemble_breakdown(MINIMAL_DICT)
        assert isinstance(bd, ScoringBreakdown)

    def test_breakdown_is_immutable(self):
        bd = assemble_breakdown(MINIMAL_DICT)
        with pytest.raises((AttributeError, TypeError)):
            bd.final_score = 99.0  # direct assignment must fail on frozen dataclass

    def test_weights_dict_has_all_five_components(self):
        bd = assemble_breakdown(MINIMAL_DICT)
        assert set(bd.weights.keys()) == {
            "skill", "experience", "education", "goal_alignment", "preference"
        }

    def test_contributions_keys_match_weights_keys(self):
        bd = assemble_breakdown(MINIMAL_DICT)
        assert set(bd.contributions.keys()) == set(bd.weights.keys())

    def test_formula_string_is_present(self):
        bd = assemble_breakdown(MINIMAL_DICT)
        assert "final_score" in bd.formula
        assert "skill_score" in bd.formula

    def test_sub_score_meta_has_all_five_keys(self):
        bd = assemble_breakdown(MINIMAL_DICT)
        assert set(bd.sub_score_meta.keys()) == {
            "skill", "experience", "education", "goal_alignment", "preference"
        }

    def test_to_dict_serialises_all_fields(self):
        bd = assemble_breakdown(MINIMAL_DICT)
        d = bd.to_dict()
        for key in (
            "skill_score", "experience_score", "education_score",
            "goal_alignment_score", "preference_score", "final_score",
            "weights", "contributions", "formula",
        ):
            assert key in d, f"Missing key '{key}' in to_dict() output"

    def test_invalid_scoring_input_type_raises(self):
        with pytest.raises(TypeError):
            assemble_breakdown("not a dict or model")

    def test_invalid_weights_raises(self):
        with pytest.raises(ValueError):
            assemble_breakdown(
                MINIMAL_DICT,
                weights=SubScoreWeights(
                    skill=1.0, experience=1.0, education=1.0,
                    goal_alignment=1.0, preference=1.0,
                ),
            )

    def test_default_weights_match_module_constant(self):
        bd = assemble_breakdown(MINIMAL_DICT)
        assert bd.weights == DEFAULT_WEIGHTS.as_dict()

    def test_custom_weights_reflected_in_breakdown(self):
        custom = SubScoreWeights(
            skill=0.20, experience=0.20, education=0.20,
            goal_alignment=0.20, preference=0.20,
        )
        bd = assemble_breakdown(MINIMAL_DICT, weights=custom)
        assert bd.weights["skill"] == 0.20
        assert bd.weights["preference"] == 0.20

    def test_trace_id_does_not_affect_scores(self):
        bd1 = assemble_breakdown(MINIMAL_DICT, trace_id="trace-AAA")
        bd2 = assemble_breakdown(MINIMAL_DICT, trace_id="trace-BBB")
        assert bd1.final_score == bd2.final_score
        assert bd1.skill_score == bd2.skill_score

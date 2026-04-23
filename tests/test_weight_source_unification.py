"""
test_weight_source_unification.py
──────────────────────────────────────────────────────────────────────────────
CI GUARD — Weight Source Unification
=====================================

Proves that RuleJustificationEngine explanation weights are derived from
audited sources only — never from inline hardcoded literals.

GUARANTEES VERIFIED
───────────────────
1. sum(r.weight for r in evaluate(...)) == 1.0 in ALL scenarios:
      - all-4-primary-rules fire, no breakdown
      - subset of rules fires, no breakdown
      - fallback rule fires, no breakdown
      - rules fire WITH a ScoringBreakdown attached

2. When scored_breakdown is PROVIDED:
      - each RuleFire.weight traces to scoring_breakdown.contributions
        via _RULE_TO_SUB_SCORE (not to a literal)
      - changing the breakdown changes the weights proportionally

3. When scoring_breakdown is NOT provided:
      - weights come from _RULE_BASE_IMPORTANCE, normalized to sum=1.0
      - a single fired rule gets weight=1.0 (not 0.34)
      - two rules get proportionally re-distributed weights (not their raw table values)

4. _RULE_BASE_IMPORTANCE table integrity:
      - four primary rules sum to exactly 1.0
      - every rule in _RULE_TO_SUB_SCORE exists in _RULE_BASE_IMPORTANCE
      - all values are positive

5. Legacy literal values {0.34, 0.27, 0.18, 0.21} do NOT appear as weights
   unless the exact full-4-rule combination fires without a breakdown (which
   is the only case where they are mathematically correct).
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.explain.formatter import (
    RuleJustificationEngine,
    _RULE_BASE_IMPORTANCE,
    _RULE_TO_SUB_SCORE,
)
from backend.scoring.sub_scorer import assemble_breakdown, SubScoreWeights

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS — shared test fixtures
# ─────────────────────────────────────────────────────────────────────────────

# Features that trigger all four primary rules
_ALL_RULES_FEATURES = {
    "math_score":   80.0,
    "logic_score":  80.0,
    "physics_score": 65.0,
    "interest_it":  70.0,
}
_ALL_RULES_CONFIDENCE = 0.85  # ≥ 0.75 → model_confidence_guard fires

# Features that trigger zero primary rules → fallback fires
_NO_RULES_FEATURES = {
    "math_score":    30.0,
    "logic_score":   30.0,
    "physics_score": 30.0,
    "interest_it":   30.0,
}

# Minimal ScoringInput dict (used to build ScoringBreakdown)
_BASE_SCORING_INPUT = {
    "personal_profile": {
        "ability_score": 0.7,
        "confidence_score": 0.6,
        "interests": ["technology"],
    },
    "experience": {"years": 5, "domains": ["software"]},
    "goals": {"career_aspirations": ["software engineer"], "timeline_years": 5},
    "skills": ["python", "java", "sql"],
    "education": {"level": "Bachelor", "field_of_study": "Computer Science"},
    "preferences": {"preferred_domains": ["tech", "ai"], "work_style": "hybrid"},
}

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — Sum-to-1.0 invariant: all scenarios
# ─────────────────────────────────────────────────────────────────────────────

class TestWeightsSumToOneInvariant:
    """sum(r.weight) == 1.0 must hold in every possible invocation."""

    def _check(self, features, confidence, breakdown=None, *, label=""):
        engine = RuleJustificationEngine()
        rules = engine.evaluate(
            features, "Test Career", confidence,
            scoring_breakdown=breakdown,
        )
        total = sum(r.weight for r in rules)
        assert abs(total - 1.0) < 1e-9, (
            f"[{label}] sum(weights)={total:.12f} != 1.0  "
            f"rules={[r.rule_id for r in rules]}"
        )
        return rules

    def test_all_four_rules_no_breakdown(self):
        self._check(_ALL_RULES_FEATURES, _ALL_RULES_CONFIDENCE, label="all-4-no-bd")

    def test_no_rules_no_breakdown(self):
        self._check(_NO_RULES_FEATURES, 0.4, label="fallback-no-bd")

    def test_only_logic_math_fires_no_breakdown(self):
        features = {"math_score": 80.0, "logic_score": 80.0,
                    "physics_score": 30.0, "interest_it": 30.0}
        self._check(features, 0.5, label="single-rule-no-bd")

    def test_two_rules_fire_no_breakdown(self):
        features = {"math_score": 80.0, "logic_score": 80.0,
                    "physics_score": 30.0, "interest_it": 70.0}
        self._check(features, 0.5, label="two-rules-no-bd")

    def test_three_rules_fire_no_breakdown(self):
        features = {"math_score": 80.0, "logic_score": 80.0,
                    "physics_score": 65.0, "interest_it": 70.0}
        self._check(features, 0.5, label="three-rules-no-bd")

    def test_all_four_rules_with_breakdown(self):
        bd = assemble_breakdown(_BASE_SCORING_INPUT)
        self._check(_ALL_RULES_FEATURES, _ALL_RULES_CONFIDENCE,
                    breakdown=bd, label="all-4-with-bd")

    def test_two_rules_with_breakdown(self):
        bd = assemble_breakdown(_BASE_SCORING_INPUT)
        features = {"math_score": 80.0, "logic_score": 80.0,
                    "physics_score": 30.0, "interest_it": 70.0}
        self._check(features, 0.5, breakdown=bd, label="two-rules-with-bd")

    def test_single_rule_with_breakdown(self):
        bd = assemble_breakdown(_BASE_SCORING_INPUT)
        features = {"math_score": 80.0, "logic_score": 80.0,
                    "physics_score": 30.0, "interest_it": 30.0}
        self._check(features, 0.5, breakdown=bd, label="single-rule-with-bd")

    def test_fallback_with_breakdown(self):
        bd = assemble_breakdown(_BASE_SCORING_INPUT)
        self._check(_NO_RULES_FEATURES, 0.4, breakdown=bd, label="fallback-with-bd")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — ScoringBreakdown anchor: weights trace to contributions
# ─────────────────────────────────────────────────────────────────────────────

class TestWeightsTraceToBreakdownContributions:
    """
    When scoring_breakdown is provided, each RuleFire.weight must be
    proportional to scoring_breakdown.contributions via _RULE_TO_SUB_SCORE.
    """

    def test_weight_proportional_to_mapped_contribution(self):
        """
        For each fired rule with a sub-score mapping:
            rule.weight == contributions[sub_score_key] / sum(mapped contributions)
        """
        bd = assemble_breakdown(_BASE_SCORING_INPUT)
        engine = RuleJustificationEngine()
        rules = engine.evaluate(
            _ALL_RULES_FEATURES, "Career", _ALL_RULES_CONFIDENCE,
            scoring_breakdown=bd,
        )
        fired_ids = [r.rule_id for r in rules]

        # Recompute expected weights from contributions
        raw: dict[str, float] = {}
        for rule_id in fired_ids:
            sub_key = _RULE_TO_SUB_SCORE.get(rule_id)
            if sub_key and sub_key in bd.contributions:
                raw[rule_id] = max(0.0, float(bd.contributions[sub_key]))
            else:
                raw[rule_id] = _RULE_BASE_IMPORTANCE.get(rule_id, 0.10)
        total = sum(raw.values())
        expected = {r: v / total for r, v in raw.items()}

        for rule in rules:
            assert abs(rule.weight - expected[rule.rule_id]) < 1e-9, (
                f"{rule.rule_id}: expected {expected[rule.rule_id]:.10f}, "
                f"got {rule.weight:.10f}"
            )

    def test_changing_breakdown_changes_weights(self):
        """
        If the scoring breakdown changes, the rule weights must change
        proportionally — proving they trace to the breakdown, not literals.
        """
        bd_low_skill = assemble_breakdown(_BASE_SCORING_INPUT)

        high_skill_input = dict(_BASE_SCORING_INPUT)
        high_skill_input["skills"] = [f"skill_{i}" for i in range(10)]
        bd_high_skill = assemble_breakdown(high_skill_input)

        # Pre-condition: skill contribution must differ
        assert bd_low_skill.contributions["skill"] != bd_high_skill.contributions["skill"], \
            "Pre-condition: skill contributions must differ between inputs"

        engine = RuleJustificationEngine()
        rules_low = engine.evaluate(
            _ALL_RULES_FEATURES, "Career", _ALL_RULES_CONFIDENCE,
            scoring_breakdown=bd_low_skill,
        )
        rules_high = engine.evaluate(
            _ALL_RULES_FEATURES, "Career", _ALL_RULES_CONFIDENCE,
            scoring_breakdown=bd_high_skill,
        )

        weight_map_low = {r.rule_id: r.weight for r in rules_low}
        weight_map_high = {r.rule_id: r.weight for r in rules_high}

        # rule_logic_math_strength maps to "skill" — its weight must change
        w_low = weight_map_low["rule_logic_math_strength"]
        w_high = weight_map_high["rule_logic_math_strength"]
        assert abs(w_low - w_high) > 1e-6, (
            f"rule_logic_math_strength weight must change when skill contribution changes. "
            f"skill_contrib_low={bd_low_skill.contributions['skill']:.4f}  "
            f"skill_contrib_high={bd_high_skill.contributions['skill']:.4f}  "
            f"w_low={w_low:.6f}  w_high={w_high:.6f}"
        )

    def test_different_weights_produce_different_rule_weights(self):
        """
        Custom SubScoreWeights → different contributions → different rule weights.
        Proves weight tracing works end-to-end.
        """
        w_default = SubScoreWeights()
        w_skill_heavy = SubScoreWeights(
            skill=0.60, experience=0.15, education=0.10,
            goal_alignment=0.10, preference=0.05,
        )

        bd_default = assemble_breakdown(_BASE_SCORING_INPUT, weights=w_default)
        bd_skill_heavy = assemble_breakdown(_BASE_SCORING_INPUT, weights=w_skill_heavy)

        engine = RuleJustificationEngine()
        rules_default = engine.evaluate(
            _ALL_RULES_FEATURES, "Career", _ALL_RULES_CONFIDENCE,
            scoring_breakdown=bd_default,
        )
        rules_skill_heavy = engine.evaluate(
            _ALL_RULES_FEATURES, "Career", _ALL_RULES_CONFIDENCE,
            scoring_breakdown=bd_skill_heavy,
        )

        wm_default = {r.rule_id: r.weight for r in rules_default}
        wm_heavy = {r.rule_id: r.weight for r in rules_skill_heavy}

        # skill-heavy → rule_logic_math_strength weight must increase
        assert wm_heavy["rule_logic_math_strength"] > wm_default["rule_logic_math_strength"], (
            "Skill-heavy weights must increase rule_logic_math_strength weight"
        )
        # preference-down → rule_it_interest_alignment weight must decrease
        assert wm_heavy["rule_it_interest_alignment"] < wm_default["rule_it_interest_alignment"], (
            "Reduced preference weight must decrease rule_it_interest_alignment weight"
        )


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — No-breakdown normalization: not the old literals
# ─────────────────────────────────────────────────────────────────────────────

class TestNoBreakdownNormalizationCorrectness:
    """Without a breakdown, weights are normalized base importance - not raw literals."""

    def test_single_rule_gets_weight_one(self):
        """Single fired rule must have weight=1.0, not the old 0.34."""
        engine = RuleJustificationEngine()
        features = {"math_score": 80.0, "logic_score": 80.0,
                    "physics_score": 30.0, "interest_it": 30.0}
        rules = engine.evaluate(features, "Career", 0.5)

        assert len(rules) == 1
        assert rules[0].rule_id == "rule_logic_math_strength"
        assert abs(rules[0].weight - 1.0) < 1e-9, (
            f"Single rule must be weight=1.0, not the old 0.34. "
            f"Got: {rules[0].weight}"
        )

    def test_two_rules_not_raw_literals(self):
        """Two-rule combination produces proportional weights, not raw table values."""
        engine = RuleJustificationEngine()
        # logic_math (0.34) + it_interest (0.27) fire
        features = {"math_score": 80.0, "logic_score": 80.0,
                    "physics_score": 30.0, "interest_it": 70.0}
        rules = engine.evaluate(features, "Career", 0.5)

        weight_map = {r.rule_id: r.weight for r in rules}
        # Normalized: 0.34/(0.34+0.27)=0.5574..., 0.27/(0.34+0.27)=0.4426...
        expected_logic = 0.34 / (0.34 + 0.27)
        expected_it = 0.27 / (0.34 + 0.27)
        assert abs(weight_map["rule_logic_math_strength"] - expected_logic) < 1e-9
        assert abs(weight_map["rule_it_interest_alignment"] - expected_it) < 1e-9
        # Confirm these are NOT the old raw literals
        assert abs(weight_map["rule_logic_math_strength"] - 0.34) > 1e-6
        assert abs(weight_map["rule_it_interest_alignment"] - 0.27) > 1e-6

    def test_fallback_rule_gets_weight_one(self):
        """Fallback (fires alone) must get weight=1.0."""
        engine = RuleJustificationEngine()
        rules = engine.evaluate(_NO_RULES_FEATURES, "Career", 0.4)
        assert len(rules) == 1
        assert rules[0].rule_id == "rule_fallback_min_evidence"
        assert abs(rules[0].weight - 1.0) < 1e-9

    def test_all_four_primary_rules_equal_table_values(self):
        """
        When all four primary rules fire with no breakdown, weights must equal
        the _RULE_BASE_IMPORTANCE values exactly (they already sum to 1.0).
        """
        engine = RuleJustificationEngine()
        rules = engine.evaluate(_ALL_RULES_FEATURES, "Career", _ALL_RULES_CONFIDENCE)
        weight_map = {r.rule_id: r.weight for r in rules}

        primary_rules = [
            "rule_logic_math_strength",
            "rule_it_interest_alignment",
            "rule_quantitative_support",
            "rule_model_confidence_guard",
        ]
        for rule_id in primary_rules:
            expected = _RULE_BASE_IMPORTANCE[rule_id]
            assert abs(weight_map[rule_id] - expected) < 1e-9, (
                f"{rule_id}: expected {expected}, got {weight_map[rule_id]}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — _RULE_BASE_IMPORTANCE table integrity
# ─────────────────────────────────────────────────────────────────────────────

class TestBaseImportanceTableIntegrity:
    """The module constants must satisfy structural invariants."""

    def test_four_primary_rules_sum_to_exactly_one(self):
        """The four primary rules must sum to 1.0."""
        primary = [
            "rule_logic_math_strength",
            "rule_it_interest_alignment",
            "rule_quantitative_support",
            "rule_model_confidence_guard",
        ]
        total = sum(_RULE_BASE_IMPORTANCE[r] for r in primary)
        assert abs(total - 1.0) < 1e-9, (
            f"Primary rules sum={total:.12f}, expected 1.0 exactly"
        )

    def test_all_importance_values_positive(self):
        for rule_id, importance in _RULE_BASE_IMPORTANCE.items():
            assert importance > 0.0, (
                f"_RULE_BASE_IMPORTANCE[{rule_id!r}] = {importance} is not positive"
            )

    def test_rule_to_sub_score_keys_in_base_importance(self):
        """Every key in _RULE_TO_SUB_SCORE must also exist in _RULE_BASE_IMPORTANCE."""
        for rule_id in _RULE_TO_SUB_SCORE:
            assert rule_id in _RULE_BASE_IMPORTANCE, (
                f"{rule_id!r} in _RULE_TO_SUB_SCORE but missing from _RULE_BASE_IMPORTANCE"
            )

    def test_rule_to_sub_score_values_are_valid(self):
        """Mapped sub-score keys must be valid ScoringBreakdown component names."""
        valid_components = {"skill", "experience", "education", "goal_alignment", "preference", None}
        for rule_id, component in _RULE_TO_SUB_SCORE.items():
            assert component in valid_components, (
                f"_RULE_TO_SUB_SCORE[{rule_id!r}] = {component!r} is not a valid component"
            )


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — Determinism: scoring_breakdown path is deterministic
# ─────────────────────────────────────────────────────────────────────────────

class TestDeterminism:
    """Same inputs → identical rule weights regardless of invocation count."""

    def test_no_breakdown_deterministic(self):
        engine = RuleJustificationEngine()
        rules_a = engine.evaluate(_ALL_RULES_FEATURES, "Career", _ALL_RULES_CONFIDENCE)
        rules_b = engine.evaluate(_ALL_RULES_FEATURES, "Career", _ALL_RULES_CONFIDENCE)
        assert [r.to_dict() for r in rules_a] == [r.to_dict() for r in rules_b]

    def test_with_breakdown_deterministic(self):
        bd = assemble_breakdown(_BASE_SCORING_INPUT)
        engine = RuleJustificationEngine()
        rules_a = engine.evaluate(
            _ALL_RULES_FEATURES, "Career", _ALL_RULES_CONFIDENCE,
            scoring_breakdown=bd,
        )
        rules_b = engine.evaluate(
            _ALL_RULES_FEATURES, "Career", _ALL_RULES_CONFIDENCE,
            scoring_breakdown=bd,
        )
        assert [r.to_dict() for r in rules_a] == [r.to_dict() for r in rules_b]

    def test_breakdown_and_no_breakdown_differ(self):
        """
        Using a breakdown must produce different weights than no breakdown
        (for typical inputs), which confirms breakdown is actually being used.
        """
        bd = assemble_breakdown(_BASE_SCORING_INPUT)
        engine = RuleJustificationEngine()
        rules_with = engine.evaluate(
            _ALL_RULES_FEATURES, "Career", _ALL_RULES_CONFIDENCE,
            scoring_breakdown=bd,
        )
        rules_without = engine.evaluate(
            _ALL_RULES_FEATURES, "Career", _ALL_RULES_CONFIDENCE,
        )
        weights_with = {r.rule_id: r.weight for r in rules_with}
        weights_without = {r.rule_id: r.weight for r in rules_without}

        # At least one weight should differ (they're derived from different sources)
        any_differ = any(
            abs(weights_with[rid] - weights_without[rid]) > 1e-6
            for rid in weights_with
        )
        assert any_differ, (
            "breakdown-derived and base-importance-derived weights are identical — "
            "the breakdown may not be affecting weight computation"
        )

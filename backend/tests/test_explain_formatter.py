"""
Tests for backend/explain/formatter.py
Covers RuleJustificationEngine, EvidenceCollector, ConfidenceEstimator,
build_trace_edges, and format_summary_text functions.
"""
import math
import pytest
from backend.explain.formatter import (
    _norm,
    RuleJustificationEngine,
    EvidenceCollector,
    ConfidenceEstimator,
    build_trace_edges,
    format_summary_text,
)
from backend.explain.models import RuleFire


class TestNormFunction:
    """Tests for _norm helper function."""

    def test_norm_middle_value(self):
        """Test normalization of a middle value."""
        result = _norm(50.0, 0.0, 100.0)
        assert result == 0.5

    def test_norm_min_value(self):
        """Test normalization at minimum."""
        result = _norm(0.0, 0.0, 100.0)
        assert result == 0.0

    def test_norm_max_value(self):
        """Test normalization at maximum."""
        result = _norm(100.0, 0.0, 100.0)
        assert result == 1.0

    def test_norm_below_min(self):
        """Test normalization below minimum returns 0."""
        result = _norm(-10.0, 0.0, 100.0)
        assert result == 0.0

    def test_norm_above_max(self):
        """Test normalization above maximum returns 1."""
        result = _norm(150.0, 0.0, 100.0)
        assert result == 1.0

    def test_norm_equal_min_max(self):
        """Test when min equals max returns 0."""
        result = _norm(50.0, 50.0, 50.0)
        assert result == 0.0

    def test_norm_max_less_than_min(self):
        """Test when max is less than min returns 0."""
        result = _norm(50.0, 100.0, 0.0)
        assert result == 0.0


class TestRuleJustificationEngine:
    """Tests for RuleJustificationEngine."""

    @pytest.fixture
    def engine(self):
        return RuleJustificationEngine()

    def test_logic_math_strength_rule(self, engine):
        """Test rule fires when logic and math scores are high."""
        features = {
            "math_score": 75.0,
            "logic_score": 80.0,
            "physics_score": 50.0,
            "interest_it": 50.0,
        }
        rules = engine.evaluate(features, "Software Engineer", 0.6)
        
        rule_ids = [r.rule_id for r in rules]
        assert "rule_logic_math_strength" in rule_ids

    def test_it_interest_alignment_rule(self, engine):
        """Test rule fires when IT interest is high."""
        features = {
            "math_score": 50.0,
            "logic_score": 50.0,
            "physics_score": 50.0,
            "interest_it": 70.0,
        }
        rules = engine.evaluate(features, "IT Specialist", 0.6)
        
        rule_ids = [r.rule_id for r in rules]
        assert "rule_it_interest_alignment" in rule_ids

    def test_quantitative_support_rule(self, engine):
        """Test rule fires when physics score is high."""
        features = {
            "math_score": 50.0,
            "logic_score": 50.0,
            "physics_score": 65.0,
            "interest_it": 50.0,
        }
        rules = engine.evaluate(features, "Engineer", 0.6)
        
        rule_ids = [r.rule_id for r in rules]
        assert "rule_quantitative_support" in rule_ids

    def test_model_confidence_guard_rule(self, engine):
        """Test rule fires when confidence is high."""
        features = {
            "math_score": 50.0,
            "logic_score": 50.0,
            "physics_score": 50.0,
            "interest_it": 50.0,
        }
        rules = engine.evaluate(features, "Analyst", 0.85)
        
        rule_ids = [r.rule_id for r in rules]
        assert "rule_model_confidence_guard" in rule_ids

    def test_fallback_rule_when_no_rules_fire(self, engine):
        """Test fallback rule when no other rules fire."""
        features = {
            "math_score": 40.0,
            "logic_score": 40.0,
            "physics_score": 40.0,
            "interest_it": 40.0,
        }
        rules = engine.evaluate(features, "General", 0.4)
        
        assert len(rules) == 1
        assert rules[0].rule_id == "rule_fallback_min_evidence"

    def test_multiple_rules_fire(self, engine):
        """Test multiple rules can fire together and weights sum to 1.0.

        When all four primary rules fire without a scoring_breakdown, weights
        equal the _RULE_BASE_IMPORTANCE values (0.34+0.27+0.18+0.21=1.0 exactly).
        """
        from backend.explain.formatter import _RULE_BASE_IMPORTANCE
        features = {
            "math_score": 80.0,
            "logic_score": 80.0,
            "physics_score": 70.0,
            "interest_it": 75.0,
        }
        rules = engine.evaluate(features, "Software Engineer", 0.85)

        rule_ids = [r.rule_id for r in rules]
        assert "rule_logic_math_strength" in rule_ids
        assert "rule_it_interest_alignment" in rule_ids
        assert "rule_quantitative_support" in rule_ids
        assert "rule_model_confidence_guard" in rule_ids

        # Weights must sum to exactly 1.0
        total = sum(r.weight for r in rules)
        assert abs(total - 1.0) < 1e-9, f"Weights must sum to 1.0, got {total}"

        # When all four fire, weights equal base importance table values
        weight_map = {r.rule_id: r.weight for r in rules}
        for rule_id, expected in _RULE_BASE_IMPORTANCE.items():
            if rule_id in weight_map:
                assert abs(weight_map[rule_id] - expected) < 1e-9, (
                    f"{rule_id}: expected {expected}, got {weight_map[rule_id]}"
                )

    def test_rule_fire_has_correct_attributes(self, engine):
        """Test that RuleFire objects have correct attributes.

        With these inputs only rule_logic_math_strength fires (physics=50 < 60,
        interest_it=50 < 65, confidence=0.6 < 0.75).  When a single rule fires,
        _weights_from_base_importance normalises its base importance (0.34) to
        sum=1.0, so the weight becomes exactly 1.0 — not the old literal 0.34.
        """
        features = {
            "math_score": 80.0,
            "logic_score": 80.0,
            "physics_score": 50.0,
            "interest_it": 50.0,
        }
        rules = engine.evaluate(features, "Engineer", 0.6)

        rule = next(r for r in rules if r.rule_id == "rule_logic_math_strength")
        assert rule.condition == "logic_score >= 70 AND math_score >= 70"
        # Single rule fires → normalized weight == 1.0 (not hardcoded 0.34)
        assert abs(rule.weight - 1.0) < 1e-9, (
            f"Expected weight=1.0 (single rule, normalized), got {rule.weight}"
        )
        assert rule.matched_features["math_score"] == 80.0
        assert rule.matched_features["logic_score"] == 80.0

    def test_missing_features_default_to_zero(self, engine):
        """Test that missing features default to zero."""
        features = {}
        rules = engine.evaluate(features, "Unknown", 0.5)
        
        # Should get fallback rule since all scores are 0
        assert len(rules) == 1
        assert rules[0].rule_id == "rule_fallback_min_evidence"


class TestEvidenceCollector:
    """Tests for EvidenceCollector."""

    @pytest.fixture
    def collector(self):
        return EvidenceCollector()

    def test_collect_feature_evidence(self, collector):
        """Test collecting evidence from features."""
        features = {
            "math_score": 75.0,
            "physics_score": 60.0,
            "interest_it": 80.0,
            "logic_score": 70.0,
        }
        evidence = collector.collect(features)
        
        assert len(evidence) == 4
        sources = set(e.source for e in evidence)
        assert sources == {"feature_snapshot"}

    def test_collect_career_evidence(self, collector):
        """Test collecting evidence from top careers."""
        features = {"math_score": 75.0}
        top_careers = [
            {"career": "Engineer", "probability": 0.8},
            {"career": "Scientist", "probability": 0.15},
        ]
        evidence = collector.collect(features, top_careers)
        
        career_evidence = [e for e in evidence if e.source == "model_distribution"]
        assert len(career_evidence) == 2
        assert career_evidence[0].key == "rank_1"
        assert career_evidence[1].key == "rank_2"

    def test_collect_with_no_careers(self, collector):
        """Test collecting evidence with no careers."""
        features = {"math_score": 75.0}
        evidence = collector.collect(features, None)
        
        assert len(evidence) == 1
        assert evidence[0].source == "feature_snapshot"

    def test_collect_empty_features(self, collector):
        """Test collecting evidence with empty features."""
        features = {}
        evidence = collector.collect(features)
        
        assert len(evidence) == 0

    def test_evidence_weight_calculation(self, collector):
        """Test that evidence weights are normalized correctly."""
        features = {"math_score": 50.0}  # 50% normalized
        evidence = collector.collect(features)
        
        assert len(evidence) == 1
        assert evidence[0].weight == 0.5  # Normalized from 0-100

    def test_collect_partial_features(self, collector):
        """Test collecting with only some supported features."""
        features = {
            "math_score": 80.0,
            "unknown_feature": 90.0,  # Should be ignored
        }
        evidence = collector.collect(features)
        
        assert len(evidence) == 1
        assert evidence[0].key == "math_score"


class TestConfidenceEstimator:
    """Tests for ConfidenceEstimator."""

    @pytest.fixture
    def estimator(self):
        return ConfidenceEstimator()

    def test_estimate_basic(self, estimator):
        """Test basic confidence estimation."""
        result = estimator.estimate(
            probabilities=[0.8, 0.15, 0.05],
            fired_rules=3,
            total_rules=5,
            features={"math_score": 80.0, "logic_score": 75.0},
            feedback_agreement=0.9,
        )
        
        assert 0.0 <= result <= 1.0

    def test_estimate_no_probabilities(self, estimator):
        """Test estimation with no probabilities."""
        result = estimator.estimate(
            probabilities=None,
            fired_rules=2,
            total_rules=5,
            features={"math_score": 80.0},
            feedback_agreement=0.5,
        )
        
        assert 0.0 <= result <= 1.0

    def test_estimate_empty_probabilities(self, estimator):
        """Test estimation with empty probabilities list."""
        result = estimator.estimate(
            probabilities=[],
            fired_rules=2,
            total_rules=5,
            features={"math_score": 80.0},
            feedback_agreement=0.5,
        )
        
        assert 0.0 <= result <= 1.0

    def test_estimate_single_probability(self, estimator):
        """Test estimation with single probability."""
        result = estimator.estimate(
            probabilities=[1.0],
            fired_rules=3,
            total_rules=3,
            features={"math_score": 80.0},
            feedback_agreement=1.0,
        )
        
        assert 0.0 <= result <= 1.0

    def test_estimate_max_confidence(self, estimator):
        """Test high-confidence scenario."""
        result = estimator.estimate(
            probabilities=[0.99, 0.01],  # Low entropy
            fired_rules=5,
            total_rules=5,  # Full rule coverage
            features={"a": 1.0, "b": 1.0, "c": 1.0},  # High data density
            feedback_agreement=1.0,  # Perfect agreement
        )
        
        # Should be high confidence
        assert result > 0.7

    def test_estimate_low_confidence(self, estimator):
        """Test low-confidence scenario."""
        result = estimator.estimate(
            probabilities=[0.25, 0.25, 0.25, 0.25],  # High entropy
            fired_rules=0,
            total_rules=10,  # No rule coverage
            features={},  # No data
            feedback_agreement=0.0,  # No agreement
        )
        
        # Should be low confidence
        assert result < 0.5

    def test_estimate_clamps_feedback(self, estimator):
        """Test that feedback is clamped to [0, 1]."""
        result1 = estimator.estimate(
            probabilities=[0.5, 0.5],
            fired_rules=1,
            total_rules=2,
            features={"a": 1.0},
            feedback_agreement=-0.5,  # Below 0
        )
        result2 = estimator.estimate(
            probabilities=[0.5, 0.5],
            fired_rules=1,
            total_rules=2,
            features={"a": 1.0},
            feedback_agreement=1.5,  # Above 1
        )
        
        assert 0.0 <= result1 <= 1.0
        assert 0.0 <= result2 <= 1.0

    def test_estimate_zero_total_rules(self, estimator):
        """Test with zero total rules."""
        result = estimator.estimate(
            probabilities=[0.5, 0.5],
            fired_rules=0,
            total_rules=0,
            features={"a": 1.0},
            feedback_agreement=0.5,
        )
        
        assert 0.0 <= result <= 1.0


class TestBuildTraceEdges:
    """Tests for build_trace_edges function."""

    def test_build_basic_edges(self):
        """Test building basic trace edges."""
        fired_rules = [
            RuleFire(
                rule_id="rule_test",
                condition="test",
                matched_features={"math_score": 80.0},
                weight=0.5,
            ),
        ]
        edges = build_trace_edges(
            trace_id="trace-001",
            user_id="user-123",
            features={"math_score": 80.0},
            fired_rules=fired_rules,
            score=0.85,
            decision="Engineer",
        )
        
        assert len(edges) > 0
        edge_types = set(e.edge_type for e in edges)
        assert "submitted_input" in edge_types
        assert "extract_feature" in edge_types
        assert "trigger_rule" in edge_types
        assert "contribute_score" in edge_types
        assert "finalize_decision" in edge_types
        assert "await_feedback" in edge_types

    def test_build_edges_multiple_features(self):
        """Test building edges with multiple features."""
        fired_rules = []
        features = {
            "math_score": 80.0,
            "physics_score": 70.0,
            "logic_score": 75.0,
        }
        edges = build_trace_edges(
            trace_id="trace-002",
            user_id="user-456",
            features=features,
            fired_rules=fired_rules,
            score=0.75,
            decision="Scientist",
        )
        
        extract_edges = [e for e in edges if e.edge_type == "extract_feature"]
        assert len(extract_edges) == 3

    def test_build_edges_multiple_rules(self):
        """Test building edges with multiple rules."""
        fired_rules = [
            RuleFire(
                rule_id="rule_1",
                condition="test1",
                matched_features={"math_score": 80.0},
                weight=0.3,
            ),
            RuleFire(
                rule_id="rule_2",
                condition="test2",
                matched_features={"logic_score": 75.0},
                weight=0.4,
            ),
        ]
        edges = build_trace_edges(
            trace_id="trace-003",
            user_id="user-789",
            features={"math_score": 80.0, "logic_score": 75.0},
            fired_rules=fired_rules,
            score=0.9,
            decision="Engineer",
        )
        
        contribute_edges = [e for e in edges if e.edge_type == "contribute_score"]
        assert len(contribute_edges) == 2

    def test_build_edges_no_rules(self):
        """Test building edges with no rules fired."""
        edges = build_trace_edges(
            trace_id="trace-004",
            user_id="user-000",
            features={"math_score": 50.0},
            fired_rules=[],
            score=0.5,
            decision="General",
        )
        
        # Should still have input, feature, finalize, and feedback edges
        assert len(edges) >= 4

    def test_edge_metadata(self):
        """Test that edge metadata is correct."""
        fired_rules = [
            RuleFire(
                rule_id="rule_test",
                condition="test",
                matched_features={"math_score": 80.0},
                weight=0.5,
            ),
        ]
        edges = build_trace_edges(
            trace_id="trace-005",
            user_id="user-meta",
            features={"math_score": 80.0},
            fired_rules=fired_rules,
            score=0.85,
            decision="Engineer",
        )
        
        finalize_edge = next(e for e in edges if e.edge_type == "finalize_decision")
        assert finalize_edge.metadata.get("score") == 0.85
        assert finalize_edge.metadata.get("decision") == "Engineer"


class TestFormatSummaryText:
    """Tests for format_summary_text function."""

    def test_format_with_rules(self):
        """Test formatting with fired rules."""
        fired_rules = [
            RuleFire(rule_id="rule_1", condition="c1", matched_features={}, weight=0.3),
            RuleFire(rule_id="rule_2", condition="c2", matched_features={}, weight=0.4),
        ]
        result = format_summary_text("Engineer", 0.85, fired_rules)
        
        assert "Decision=Engineer" in result
        assert "confidence=0.85" in result
        assert "rule_1" in result
        assert "rule_2" in result

    def test_format_no_rules(self):
        """Test formatting with no rules."""
        result = format_summary_text("General", 0.5, [])
        
        assert "Decision=General" in result
        assert "confidence=0.50" in result
        assert "no rules fired" in result

    def test_format_max_three_rules(self):
        """Test that only top 3 rules are shown."""
        fired_rules = [
            RuleFire(rule_id=f"rule_{i}", condition=f"c{i}", matched_features={}, weight=0.2)
            for i in range(5)
        ]
        result = format_summary_text("Expert", 0.9, fired_rules)
        
        assert "rule_0" in result
        assert "rule_1" in result
        assert "rule_2" in result
        # rule_3 and rule_4 should not be in summary
        assert "rule_3" not in result
        assert "rule_4" not in result

    def test_format_single_rule(self):
        """Test formatting with single rule."""
        fired_rules = [
            RuleFire(rule_id="only_rule", condition="c", matched_features={}, weight=0.5),
        ]
        result = format_summary_text("Specialist", 0.75, fired_rules)
        
        assert "only_rule" in result
        assert "rule_path=only_rule" in result

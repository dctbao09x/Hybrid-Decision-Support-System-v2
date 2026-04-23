# backend/tests/test_scoring_schema.py
"""
Tests for scoring schema, input snapshot validation, structured output,
and the score_with_snapshot production entry point.

Coverage targets:
  - ScoringInputSnapshot hash computation & verification
  - ScoringOutputSchema structure
  - ScoreCard auto-tagging
  - ReproducibilityProof integrity
  - score_with_snapshot() end-to-end
  - Deterministic reproducibility (same input → same output hash)
"""

import pytest
import json
import hashlib
from copy import deepcopy

from backend.schemas.scoring import (
    UserProfileInput,
    CareerInput,
    ScoringConfigInput,
    ScoringInputSnapshot,
    ComponentScore,
    ScoreCard,
    ReproducibilityProof,
    ScoringOutputSchema,
    build_scoring_output,
)
from backend.scoring.config import ScoringConfig
from backend.scoring.models import (
    UserProfile,
    CareerData,
    ScoredCareer,
    ScoreBreakdown,
)
from backend.scoring.engine import score_with_snapshot, rank_careers


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def sample_user_dict():
    return {
        "skills": ["python", "sql", "machine learning"],
        "interests": ["AI", "data science"],
        "education_level": "Master",
        "ability_score": 0.8,
        "confidence_score": 0.7,
    }


@pytest.fixture
def sample_careers_list():
    return [
        {
            "name": "Data Scientist",
            "required_skills": ["python", "statistics"],
            "preferred_skills": ["machine learning", "sql"],
            "domain": "data science",
            "domain_interests": ["AI"],
            "ai_relevance": 0.9,
            "growth_rate": 0.85,
            "competition": 0.6,
        },
        {
            "name": "Software Engineer",
            "required_skills": ["python"],
            "preferred_skills": ["system design"],
            "domain": "software",
            "domain_interests": [],
            "ai_relevance": 0.7,
            "growth_rate": 0.7,
            "competition": 0.8,
        },
        {
            "name": "Product Manager",
            "required_skills": [],
            "preferred_skills": ["leadership"],
            "domain": "management",
            "domain_interests": [],
            "ai_relevance": 0.3,
            "growth_rate": 0.5,
            "competition": 0.5,
        },
    ]


@pytest.fixture
def sample_scored_careers():
    """Pre-built ScoredCareer list for testing build_scoring_output."""
    return [
        ScoredCareer(
            career_name="Data Scientist",
            total_score=0.82,
            breakdown=ScoreBreakdown(
                study_score=0.85,
                interest_score=0.80,
                market_score=0.88,
                growth_score=0.75,
                risk_score=0.70,
            ),
            rank=1,
        ),
        ScoredCareer(
            career_name="Software Engineer",
            total_score=0.65,
            breakdown=ScoreBreakdown(
                study_score=0.70,
                interest_score=0.50,
                market_score=0.72,
                growth_score=0.60,
                risk_score=0.55,
            ),
            rank=2,
        ),
    ]


# ══════════════════════════════════════════════════════════
#  Input Schema Validation Tests
# ══════════════════════════════════════════════════════════

class TestInputSchemas:
    """Test input schema validation."""

    def test_user_profile_input_defaults(self):
        u = UserProfileInput()
        assert u.skills == []
        assert u.interests == []
        assert u.education_level == "Bachelor"
        assert u.ability_score == 0.5
        assert u.confidence_score == 0.5

    def test_user_profile_input_valid(self, sample_user_dict):
        u = UserProfileInput(**sample_user_dict)
        assert len(u.skills) == 3
        assert u.education_level == "Master"
        assert u.ability_score == 0.8

    def test_user_profile_input_invalid_range(self):
        with pytest.raises(Exception):
            UserProfileInput(ability_score=1.5)

    def test_career_input_valid(self, sample_careers_list):
        c = CareerInput(**sample_careers_list[0])
        assert c.name == "Data Scientist"
        assert len(c.required_skills) == 2
        assert c.ai_relevance == 0.9

    def test_career_input_clamps_range(self):
        with pytest.raises(Exception):
            CareerInput(name="Bad", ai_relevance=2.0)

    def test_scoring_config_input_defaults(self):
        cfg = ScoringConfigInput()
        assert cfg.strategy == "weighted"
        assert cfg.weights is None
        assert cfg.min_score_threshold == 0.0
        assert cfg.debug_mode is False

    def test_scoring_config_input_invalid_strategy(self):
        with pytest.raises(ValueError):
            ScoringConfigInput(strategy="random_forest")


# ══════════════════════════════════════════════════════════
#  Input Snapshot Tests
# ══════════════════════════════════════════════════════════

class TestInputSnapshot:
    """Test ScoringInputSnapshot hashing and verification."""

    def test_snapshot_auto_computes_hash(self, sample_user_dict, sample_careers_list):
        snapshot = ScoringInputSnapshot(
            user_profile=UserProfileInput(**sample_user_dict),
            careers=[CareerInput(**c) for c in sample_careers_list],
        )
        assert snapshot.input_hash != ""
        assert len(snapshot.input_hash) == 64  # SHA-256 hex length

    def test_snapshot_verify_returns_true(self, sample_user_dict, sample_careers_list):
        snapshot = ScoringInputSnapshot(
            user_profile=UserProfileInput(**sample_user_dict),
            careers=[CareerInput(**c) for c in sample_careers_list],
        )
        assert snapshot.verify() is True

    def test_snapshot_hash_deterministic(self, sample_user_dict, sample_careers_list):
        """Same inputs → same hash (regardless of timestamp)."""
        s1 = ScoringInputSnapshot(
            user_profile=UserProfileInput(**sample_user_dict),
            careers=[CareerInput(**c) for c in sample_careers_list],
            timestamp="2025-01-01T00:00:00+00:00",
        )
        s2 = ScoringInputSnapshot(
            user_profile=UserProfileInput(**sample_user_dict),
            careers=[CareerInput(**c) for c in sample_careers_list],
            timestamp="2025-06-15T12:00:00+00:00",
        )
        assert s1.input_hash == s2.input_hash

    def test_snapshot_hash_changes_on_different_input(
        self, sample_user_dict, sample_careers_list
    ):
        s1 = ScoringInputSnapshot(
            user_profile=UserProfileInput(**sample_user_dict),
            careers=[CareerInput(**c) for c in sample_careers_list],
        )
        modified_user = {**sample_user_dict, "ability_score": 0.3}
        s2 = ScoringInputSnapshot(
            user_profile=UserProfileInput(**modified_user),
            careers=[CareerInput(**c) for c in sample_careers_list],
        )
        assert s1.input_hash != s2.input_hash

    def test_snapshot_hash_changes_on_different_careers(
        self, sample_user_dict, sample_careers_list
    ):
        s1 = ScoringInputSnapshot(
            user_profile=UserProfileInput(**sample_user_dict),
            careers=[CareerInput(**c) for c in sample_careers_list],
        )
        shorter = sample_careers_list[:1]
        s2 = ScoringInputSnapshot(
            user_profile=UserProfileInput(**sample_user_dict),
            careers=[CareerInput(**c) for c in shorter],
        )
        assert s1.input_hash != s2.input_hash

    def test_snapshot_hash_changes_on_different_config(
        self, sample_user_dict, sample_careers_list
    ):
        s1 = ScoringInputSnapshot(
            user_profile=UserProfileInput(**sample_user_dict),
            careers=[CareerInput(**c) for c in sample_careers_list],
            config=ScoringConfigInput(strategy="weighted"),
        )
        s2 = ScoringInputSnapshot(
            user_profile=UserProfileInput(**sample_user_dict),
            careers=[CareerInput(**c) for c in sample_careers_list],
            config=ScoringConfigInput(strategy="personalized"),
        )
        assert s1.input_hash != s2.input_hash


# ══════════════════════════════════════════════════════════
#  ScoreCard & Tagging Tests
# ══════════════════════════════════════════════════════════

class TestScoreCard:
    """Test ScoreCard auto-tagging."""

    def _make_card(self, total, study=0.5, interest=0.5, market=0.5,
                   growth=0.5, risk=0.5, rank=1):
        return ScoreCard(
            career_name="Test Career",
            total_score=total,
            rank=rank,
            components=[
                ComponentScore(name="study", score=study, weight=0.25,
                               contribution=round(study * 0.25, 6)),
                ComponentScore(name="interest", score=interest, weight=0.25,
                               contribution=round(interest * 0.25, 6)),
                ComponentScore(name="market", score=market, weight=0.25,
                               contribution=round(market * 0.25, 6)),
                ComponentScore(name="growth", score=growth, weight=0.15,
                               contribution=round(growth * 0.15, 6)),
                ComponentScore(name="risk", score=risk, weight=0.10,
                               contribution=round(risk * 0.10, 6)),
            ],
        )

    def test_strong_match_tag(self):
        card = self._make_card(0.85, study=0.9, interest=0.9, market=0.9)
        assert "strong_match" in card.tags

    def test_weak_match_tag(self):
        card = self._make_card(0.20, study=0.2, interest=0.2, market=0.2,
                               growth=0.2, risk=0.2)
        assert "weak_match" in card.tags

    def test_top_component_tag(self):
        card = self._make_card(0.5, study=0.90)
        assert "top_study" in card.tags

    def test_weak_component_tag(self):
        card = self._make_card(0.5, market=0.15)
        assert "weak_market" in card.tags

    def test_no_tags_for_mediocre_scores(self):
        card = self._make_card(0.50, study=0.5, interest=0.5, market=0.5,
                               growth=0.5, risk=0.5)
        assert card.tags == []

    def test_five_components_required(self):
        card = self._make_card(0.5)
        assert len(card.components) == 5


# ══════════════════════════════════════════════════════════
#  build_scoring_output Tests
# ══════════════════════════════════════════════════════════

class TestBuildScoringOutput:
    """Test the builder function."""

    def test_builds_valid_output(self, sample_scored_careers):
        config = ScoringConfig()
        output = build_scoring_output(
            scored_careers=sample_scored_careers,
            config_used=config,
            strategy_name="weighted",
        )
        assert isinstance(output, ScoringOutputSchema)
        assert output.total_evaluated == 2
        assert output.total_returned == 2
        assert output.strategy == "weighted"
        assert len(output.score_cards) == 2

    def test_score_cards_ordered(self, sample_scored_careers):
        config = ScoringConfig()
        output = build_scoring_output(
            scored_careers=sample_scored_careers,
            config_used=config,
            strategy_name="weighted",
        )
        assert output.score_cards[0].rank == 1
        assert output.score_cards[1].rank == 2
        assert output.score_cards[0].total_score >= output.score_cards[1].total_score

    def test_weights_used_matches_config(self, sample_scored_careers):
        config = ScoringConfig.create_custom(study=0.4, interest=0.2,
                                              market=0.2, growth=0.1, risk=0.1)
        output = build_scoring_output(
            scored_careers=sample_scored_careers,
            config_used=config,
            strategy_name="weighted",
        )
        assert output.weights_used["study_score"] == 0.4
        assert output.weights_used["interest_score"] == 0.2

    def test_reproducibility_proof_present(self, sample_scored_careers):
        config = ScoringConfig()
        output = build_scoring_output(
            scored_careers=sample_scored_careers,
            config_used=config,
            strategy_name="weighted",
        )
        proof = output.reproducibility
        assert isinstance(proof, ReproducibilityProof)
        assert proof.output_hash != ""
        assert proof.config_hash != ""
        assert proof.deterministic is True
        assert proof.strategy == "weighted"

    def test_with_input_snapshot(self, sample_scored_careers):
        config = ScoringConfig()
        snapshot = ScoringInputSnapshot(
            user_profile=UserProfileInput(skills=["python"]),
            careers=[CareerInput(name="Test")],
        )
        output = build_scoring_output(
            scored_careers=sample_scored_careers,
            config_used=config,
            strategy_name="weighted",
            input_snapshot=snapshot,
        )
        assert output.reproducibility.input_hash == snapshot.input_hash

    def test_output_hash_deterministic(self, sample_scored_careers):
        config = ScoringConfig()
        o1 = build_scoring_output(
            scored_careers=sample_scored_careers,
            config_used=config,
            strategy_name="weighted",
        )
        o2 = build_scoring_output(
            scored_careers=sample_scored_careers,
            config_used=config,
            strategy_name="weighted",
        )
        assert o1.reproducibility.output_hash == o2.reproducibility.output_hash

    def test_duration_ms_passed(self, sample_scored_careers):
        config = ScoringConfig()
        output = build_scoring_output(
            scored_careers=sample_scored_careers,
            config_used=config,
            strategy_name="weighted",
            duration_ms=42.5,
        )
        assert output.duration_ms == 42.5


# ══════════════════════════════════════════════════════════
#  score_with_snapshot() End-to-End Tests
# ══════════════════════════════════════════════════════════

class TestScoreWithSnapshot:
    """Test the production entry point."""

    def test_basic_scoring(self, sample_user_dict, sample_careers_list):
        output = score_with_snapshot(sample_user_dict, sample_careers_list)
        assert isinstance(output, ScoringOutputSchema)
        assert output.total_evaluated == len(sample_careers_list)
        assert output.strategy == "weighted"
        assert len(output.score_cards) > 0
        assert output.duration_ms is not None
        assert output.duration_ms > 0

    def test_all_scores_in_range(self, sample_user_dict, sample_careers_list):
        output = score_with_snapshot(sample_user_dict, sample_careers_list)
        for sc in output.score_cards:
            assert 0.0 <= sc.total_score <= 1.0
            for comp in sc.components:
                assert 0.0 <= comp.score <= 1.0
                assert 0.0 <= comp.weight <= 1.0

    def test_ranks_sequential(self, sample_user_dict, sample_careers_list):
        output = score_with_snapshot(sample_user_dict, sample_careers_list)
        ranks = [sc.rank for sc in output.score_cards]
        assert ranks == list(range(1, len(ranks) + 1))

    def test_scores_descending(self, sample_user_dict, sample_careers_list):
        output = score_with_snapshot(sample_user_dict, sample_careers_list)
        scores = [sc.total_score for sc in output.score_cards]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]

    def test_reproducibility_proof_valid(
        self, sample_user_dict, sample_careers_list
    ):
        output = score_with_snapshot(sample_user_dict, sample_careers_list)
        proof = output.reproducibility
        assert proof.input_hash != ""
        assert proof.output_hash != ""
        assert proof.config_hash != ""
        assert proof.deterministic is True
        assert len(proof.weights_used) == 5

    def test_personalized_strategy(self, sample_user_dict, sample_careers_list):
        output = score_with_snapshot(
            sample_user_dict,
            sample_careers_list,
            strategy="personalized",
        )
        assert output.strategy == "personalized"
        assert len(output.score_cards) > 0

    def test_custom_weights(self, sample_user_dict, sample_careers_list):
        output = score_with_snapshot(
            sample_user_dict,
            sample_careers_list,
            config_override={
                "weights": {
                    "study": 0.4,
                    "interest": 0.2,
                    "market": 0.2,
                    "growth": 0.1,
                    "risk": 0.1,
                },
            },
        )
        assert isinstance(output, ScoringOutputSchema)
        assert len(output.score_cards) > 0

    def test_min_threshold_filters(self, sample_user_dict, sample_careers_list):
        # First get all scores to find a good threshold
        full = score_with_snapshot(sample_user_dict, sample_careers_list)
        all_scores = [sc.total_score for sc in full.score_cards]

        if len(all_scores) > 1:
            # Use threshold between min and max score
            threshold = (min(all_scores) + max(all_scores)) / 2
            filtered = score_with_snapshot(
                sample_user_dict,
                sample_careers_list,
                config_override={"min_score_threshold": threshold},
            )
            assert filtered.total_returned <= full.total_returned

    def test_empty_careers_returns_empty(self, sample_user_dict):
        output = score_with_snapshot(sample_user_dict, [])
        assert output.total_evaluated == 0
        assert output.total_returned == 0
        assert output.score_cards == []

    def test_empty_user_skills(self, sample_careers_list):
        user = {"skills": [], "interests": []}
        output = score_with_snapshot(user, sample_careers_list)
        assert isinstance(output, ScoringOutputSchema)
        assert len(output.score_cards) == len(sample_careers_list)

    def test_five_components_per_card(self, sample_user_dict, sample_careers_list):
        output = score_with_snapshot(sample_user_dict, sample_careers_list)
        for sc in output.score_cards:
            assert len(sc.components) == 5
            names = {c.name for c in sc.components}
            assert names == {"study", "interest", "market", "growth", "risk"}


# ══════════════════════════════════════════════════════════
#  Reproducibility / Determinism Tests
# ══════════════════════════════════════════════════════════

class TestReproducibility:
    """Test that scoring is fully deterministic."""

    def test_identical_output_hash(self, sample_user_dict, sample_careers_list):
        """Two runs with identical input → same output hash."""
        o1 = score_with_snapshot(sample_user_dict, sample_careers_list)
        o2 = score_with_snapshot(sample_user_dict, sample_careers_list)
        assert o1.reproducibility.output_hash == o2.reproducibility.output_hash

    def test_identical_input_hash(self, sample_user_dict, sample_careers_list):
        """Two runs with identical input → same input hash."""
        o1 = score_with_snapshot(sample_user_dict, sample_careers_list)
        o2 = score_with_snapshot(sample_user_dict, sample_careers_list)
        assert o1.reproducibility.input_hash == o2.reproducibility.input_hash

    def test_identical_scores(self, sample_user_dict, sample_careers_list):
        """Two runs produce exactly the same scores."""
        o1 = score_with_snapshot(sample_user_dict, sample_careers_list)
        o2 = score_with_snapshot(sample_user_dict, sample_careers_list)
        for s1, s2 in zip(o1.score_cards, o2.score_cards):
            assert s1.total_score == s2.total_score
            assert s1.career_name == s2.career_name
            assert s1.rank == s2.rank

    def test_identical_component_scores(
        self, sample_user_dict, sample_careers_list
    ):
        """Two runs produce exactly the same component breakdown."""
        o1 = score_with_snapshot(sample_user_dict, sample_careers_list)
        o2 = score_with_snapshot(sample_user_dict, sample_careers_list)
        for s1, s2 in zip(o1.score_cards, o2.score_cards):
            for c1, c2 in zip(s1.components, s2.components):
                assert c1.name == c2.name
                assert c1.score == c2.score
                assert c1.weight == c2.weight
                assert c1.contribution == c2.contribution

    def test_different_input_different_hash(
        self, sample_user_dict, sample_careers_list
    ):
        """Different input → different hashes."""
        o1 = score_with_snapshot(sample_user_dict, sample_careers_list)
        modified = {**sample_user_dict, "ability_score": 0.1}
        o2 = score_with_snapshot(modified, sample_careers_list)
        assert o1.reproducibility.input_hash != o2.reproducibility.input_hash

    def test_config_hash_stable(self, sample_user_dict, sample_careers_list):
        """Same config → same config hash."""
        o1 = score_with_snapshot(sample_user_dict, sample_careers_list)
        o2 = score_with_snapshot(sample_user_dict, sample_careers_list)
        assert o1.reproducibility.config_hash == o2.reproducibility.config_hash

    def test_personalized_reproducible(
        self, sample_user_dict, sample_careers_list
    ):
        """Personalized strategy is also deterministic."""
        o1 = score_with_snapshot(
            sample_user_dict, sample_careers_list, strategy="personalized"
        )
        o2 = score_with_snapshot(
            sample_user_dict, sample_careers_list, strategy="personalized"
        )
        assert o1.reproducibility.output_hash == o2.reproducibility.output_hash
        for s1, s2 in zip(o1.score_cards, o2.score_cards):
            assert s1.total_score == s2.total_score


# ══════════════════════════════════════════════════════════
#  Edge Case Tests
# ══════════════════════════════════════════════════════════

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_single_career(self, sample_user_dict, sample_careers_list):
        output = score_with_snapshot(sample_user_dict, sample_careers_list[:1])
        assert len(output.score_cards) == 1
        assert output.score_cards[0].rank == 1

    def test_user_with_max_scores(self, sample_careers_list):
        user = {
            "skills": ["python", "sql", "statistics", "machine learning"],
            "interests": ["AI", "data science"],
            "education_level": "PhD",
            "ability_score": 1.0,
            "confidence_score": 1.0,
        }
        output = score_with_snapshot(user, sample_careers_list)
        assert all(0.0 <= sc.total_score <= 1.0 for sc in output.score_cards)

    def test_user_with_min_scores(self, sample_careers_list):
        user = {
            "skills": [],
            "interests": [],
            "education_level": "HighSchool",
            "ability_score": 0.0,
            "confidence_score": 0.0,
        }
        output = score_with_snapshot(user, sample_careers_list)
        assert all(0.0 <= sc.total_score <= 1.0 for sc in output.score_cards)

    def test_career_with_all_zeros(self, sample_user_dict):
        careers = [
            {
                "name": "Unknown",
                "required_skills": [],
                "preferred_skills": [],
                "domain": "unknown",
                "domain_interests": [],
                "ai_relevance": 0.0,
                "growth_rate": 0.0,
                "competition": 0.0,
            }
        ]
        output = score_with_snapshot(sample_user_dict, careers)
        assert len(output.score_cards) == 1
        assert 0.0 <= output.score_cards[0].total_score <= 1.0

    def test_career_with_all_ones(self, sample_user_dict):
        careers = [
            {
                "name": "Perfect",
                "required_skills": ["python", "sql"],
                "preferred_skills": ["machine learning"],
                "domain": "data science",
                "domain_interests": ["AI"],
                "ai_relevance": 1.0,
                "growth_rate": 1.0,
                "competition": 1.0,
            }
        ]
        output = score_with_snapshot(sample_user_dict, careers)
        assert len(output.score_cards) == 1
        assert 0.0 <= output.score_cards[0].total_score <= 1.0

    def test_serializable_output(self, sample_user_dict, sample_careers_list):
        """Output can be serialized to JSON."""
        output = score_with_snapshot(sample_user_dict, sample_careers_list)
        json_str = output.model_dump_json()
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert "score_cards" in parsed
        assert "reproducibility" in parsed

    def test_output_hash_method(self, sample_user_dict, sample_careers_list):
        """ScoringOutputSchema.output_hash() works."""
        output = score_with_snapshot(sample_user_dict, sample_careers_list)
        h = output.output_hash()
        assert len(h) == 64
        # Should match the proof's output hash
        assert h == output.reproducibility.output_hash


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

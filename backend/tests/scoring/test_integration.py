"""
Integration tests for scoring pipeline.

Tests end-to-end scoring with baseline validation.
"""

import pytest
import json
import os
from backend.scoring import rank_careers, score_jobs
from backend.scoring.models import UserProfile, CareerData
from backend.scoring.baseline_capture import create_baseline_user, create_baseline_careers


class TestBaselineValidation:
    """Test that refactored scoring matches baseline within ±2%."""

    @pytest.fixture
    def baseline_data(self):
        """Load baseline data."""
        baseline_file = "backend/tests/scoring/baseline.json"
        if not os.path.exists(baseline_file):
            pytest.skip("Baseline file not found. Run baseline_capture.py first.")

        with open(baseline_file, "r") as f:
            return json.load(f)

    def test_rank_careers_baseline_compatibility(self, baseline_data):
        """Test rank_careers output matches baseline."""
        user_data = baseline_data["user_profile"]
        career_data_list = baseline_data["careers"]
        expected_results = baseline_data["results"]

        # Reconstruct objects
        user = UserProfile(**user_data)
        careers = [CareerData(**c) for c in career_data_list]

        # Run scoring
        results = rank_careers(user, careers)

        # Validate each result
        for expected, actual in zip(expected_results, results):
            assert expected["career_name"] == actual.career_name
            assert expected["rank"] == actual.rank

            # Check total score within ±2%
            expected_score = expected["total_score"]
            actual_score = actual.total_score
            deviation = abs(actual_score - expected_score)
            assert deviation <= 0.02, f"Score deviation too large for {actual.career_name}: {deviation}"

            # Check breakdown scores within ±2%
            for key in ["study_score", "interest_score", "market_score", "growth_score", "risk_score"]:
                expected_val = expected["breakdown"][key]
                actual_val = getattr(actual.breakdown, key)
                deviation = abs(actual_val - expected_val)
                assert deviation <= 0.02, f"{key} deviation too large for {actual.career_name}: {deviation}"

    def test_score_jobs_new_interface(self):
        """Test new score_jobs interface."""
        user = create_baseline_user()
        careers = create_baseline_careers()

        results = score_jobs(careers, user)

        assert len(results) == len(careers)
        for result in results:
            assert hasattr(result, "contributions")
            assert "study" in result.contributions
            assert "weight" in result.contributions["study"]
            assert "contribution" in result.contributions["study"]

    def test_score_jobs_contributions_calculation(self):
        """Test contributions are calculated correctly."""
        user = UserProfile(skills=["python"])
        careers = [CareerData(name="Engineer", required_skills=["python"])]

        results = score_jobs(careers, user)

        result = results[0]
        for component in ["study", "interest", "market", "growth", "risk"]:
            weight = result.contributions[component]["weight"]
            contribution = result.contributions[component]["contribution"]
            score = getattr(result.breakdown, f"{component}_score")

            # Contribution should be weight * score
            expected_contribution = weight * score
            assert abs(contribution - expected_contribution) < 0.0001


class TestEndToEndPipeline:
    """Test complete scoring pipeline."""

    def test_full_pipeline_execution(self):
        """Test full pipeline from user profile to scored results."""
        user = UserProfile(
            skills=["python", "machine learning", "sql"],
            interests=["AI", "data science"],
            education_level="Master",
            ability_score=0.8,
            confidence_score=0.7
        )

        careers = [
            CareerData(
                name="Data Scientist",
                required_skills=["python", "statistics"],
                preferred_skills=["machine learning", "sql"],
                domain="data science",
                domain_interests=["AI"],
                ai_relevance=0.9,
                growth_rate=0.85,
                competition=0.6,
            ),
            CareerData(
                name="Software Engineer",
                required_skills=["python"],
                preferred_skills=["system design"],
                domain="software",
                ai_relevance=0.7,
                growth_rate=0.7,
                competition=0.8,
            ),
        ]

        # Test rank_careers (legacy)
        ranked_results = rank_careers(user, careers)
        assert len(ranked_results) == 2
        assert ranked_results[0].total_score >= ranked_results[1].total_score

        # Test score_jobs (new)
        scored_results = score_jobs(careers, user)
        assert len(scored_results) == 2

        # Results should be in same order
        for legacy, new in zip(ranked_results, scored_results):
            assert legacy.career_name == new.career_name
            assert legacy.total_score == new.total_score

    def test_pipeline_determinism(self):
        """Test pipeline produces identical results."""
        user = create_baseline_user()
        careers = create_baseline_careers()

        # Run multiple times
        results1 = rank_careers(user, careers)
        results2 = rank_careers(user, careers)

        assert len(results1) == len(results2)
        for r1, r2 in zip(results1, results2):
            assert r1.total_score == r2.total_score
            assert r1.career_name == r2.career_name
            assert r1.rank == r2.rank

    def test_pipeline_error_handling(self):
        """Test pipeline handles errors gracefully."""
        user = UserProfile()
        careers = []  # Empty list

        results = rank_careers(user, careers)
        assert results == []

        # Invalid user
        results = rank_careers(None, careers)
        assert results == []


class TestNormalizerIntegration:
    """Test normalizer integration with scoring."""

    def test_analyze_output_to_user_profile(self):
        """Test converting analyze output to UserProfile."""
        from backend.scoring.normalizer import Prompt3Normalizer

        analyze_output = {
            "age": 25,
            "education_level": "Bachelor",
            "interest_tags": ["AI", "machine learning"],
            "skill_tags": ["python", "sql"],
            "goal_cleaned": "Become AI Engineer",
            "intent": "career_change",
            "chat_summary": "Interested in AI",
            "confidence_score": 0.8
        }

        user_profile = Prompt3Normalizer.normalize_user_profile_from_analyze(analyze_output)

        assert isinstance(user_profile, UserProfile)
        assert [s.lower() for s in user_profile.skills] == ["python", "sql"]
        assert [s.lower() for s in user_profile.interests] == ["ai", "machine learning"]
        assert user_profile.education_level == "Bachelor"
        assert user_profile.ability_score == 0.8
        assert user_profile.confidence_score == 0.8

    def test_invalid_analyze_output_raises_error(self):
        """Test invalid analyze output raises ValueError."""
        from backend.scoring.normalizer import Prompt3Normalizer

        invalid_output = {
            "age": "invalid",  # Should be int
            "education_level": "Bachelor",
            "interest_tags": ["AI"],
            "skill_tags": ["python"],
            "goal_cleaned": "Goal",
            "intent": "intent",
            "chat_summary": "summary",
            "confidence_score": 0.8
        }

        with pytest.raises(ValueError):
            Prompt3Normalizer.normalize_user_profile_from_analyze(invalid_output)

    def test_malformed_analyze_output_empty_fields(self):
        """Test handling empty or missing fields in analyze output."""
        from backend.scoring.normalizer import Prompt3Normalizer

        # Test with empty interest_tags
        malformed_output = {
            "age": 25,
            "education_level": "Bachelor",
            "interest_tags": [],  # Empty
            "skill_tags": ["python"],
            "goal_cleaned": "Become developer",
            "intent": "career_change",
            "chat_summary": "Wants to code",
            "confidence_score": 0.7
        }

        user = Prompt3Normalizer.normalize_user_profile_from_analyze(malformed_output)
        assert user.interests == []
        assert [s.lower() for s in user.skills] == ["python"]

    def test_malformed_analyze_output_missing_chat_history(self):
        """Test analyze output with missing chat summary."""
        from backend.scoring.normalizer import Prompt3Normalizer

        # Missing chat_summary
        incomplete_output = {
            "age": 30,
            "education_level": "Master",
            "interest_tags": ["AI"],
            "skill_tags": ["python", "ml"],
            "goal_cleaned": "AI Engineer",
            "intent": "advancement",
            # Missing chat_summary
            "confidence_score": 0.9
        }

        with pytest.raises(ValueError, match="Missing required fields"):
            Prompt3Normalizer.normalize_user_profile_from_analyze(incomplete_output)

    def test_boundary_confidence_score(self):
        """Test boundary values for confidence_score."""
        from backend.scoring.normalizer import Prompt3Normalizer

        # Test minimum boundary
        min_conf_output = {
            "age": 22,
            "education_level": "Bachelor",
            "interest_tags": ["tech"],
            "skill_tags": ["coding"],
            "goal_cleaned": "Developer",
            "intent": "entry",
            "chat_summary": "New to coding",
            "confidence_score": 0.0
        }

        user_min = Prompt3Normalizer.normalize_user_profile_from_analyze(min_conf_output)
        assert user_min.confidence_score == 0.0
        assert user_min.ability_score == 0.0

        # Test maximum boundary
        max_conf_output = min_conf_output.copy()
        max_conf_output["confidence_score"] = 1.0

        user_max = Prompt3Normalizer.normalize_user_profile_from_analyze(max_conf_output)
        assert user_max.confidence_score == 1.0
        assert user_max.ability_score == 1.0

        # Test out of bounds (should raise error)
        invalid_conf_output = min_conf_output.copy()
        invalid_conf_output["confidence_score"] = 1.5

        with pytest.raises(ValueError, match="confidence_score must be float in"):
            Prompt3Normalizer.normalize_user_profile_from_analyze(invalid_conf_output)

    def test_config_reload_in_pipeline(self):
        """Test config reload functionality in scoring pipeline."""
        from backend.scoring import SIMGRScorer

        scorer = SIMGRScorer()

        input_data = {
            "user": {
                "skills": ["python"],
                "interests": ["AI"]
            },
            "careers": [
                {
                    "name": "Data Scientist",
                    "required_skills": ["python"],
                    "ai_relevance": 0.8
                }
            ],
            "config": {
                "study_score": 0.5,  # Increased from default 0.25
                "interest_score": 0.3,
                "market_score": 0.1,
                "growth_score": 0.05,
                "risk_score": 0.05
            }
        }

        result = scorer.score(input_data)

        assert result["success"] is True
        assert result["config_used"]["study_score"] == 0.5
        assert result["config_used"]["interest_score"] == 0.3

    def test_pipeline_with_empty_user_profile(self):
        """Test pipeline with minimal user profile."""
        user = UserProfile()  # Empty profile

        careers = [
            CareerData(name="General Job", required_skills=[])
        ]

        results = rank_careers(user, careers)

        assert len(results) == 1
        assert results[0].total_score >= 0.0  # Should still produce a score

    def test_pipeline_with_extreme_career_values(self):
        """Test pipeline with extreme career attribute values."""
        user = UserProfile(skills=["python"])

        careers = [
            CareerData(
                name="High AI Job",
                required_skills=["python"],
                ai_relevance=1.0,
                growth_rate=1.0,
                competition=0.0  # Low competition = good
            ),
            CareerData(
                name="Low AI Job",
                required_skills=["cobol"],  # No match
                ai_relevance=0.0,
                growth_rate=0.0,
                competition=1.0  # High competition = bad
            )
        ]

        results = rank_careers(user, careers)

        assert len(results) == 2
        # High AI job should score higher
        assert results[0].total_score > results[1].total_score

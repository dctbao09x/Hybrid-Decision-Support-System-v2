"""
Unit tests for backend/scoring/normalizer.py

Tests DataNormalizer utilities and Prompt3Normalizer integration.
"""

import pytest
import math
from backend.scoring.normalizer import DataNormalizer, Prompt3Normalizer
from backend.scoring.models import UserProfile


class TestDataNormalizer:
    """Test DataNormalizer static methods."""

    def test_clamp_valid_values(self):
        """Test clamping with valid inputs."""
        assert DataNormalizer.clamp(0.5) == 0.5
        assert DataNormalizer.clamp(1.5) == 1.0
        assert DataNormalizer.clamp(-0.5) == 0.0
        assert DataNormalizer.clamp(0.5, 0.2, 0.8) == 0.5
        assert DataNormalizer.clamp(0.1, 0.2, 0.8) == 0.2
        assert DataNormalizer.clamp(0.9, 0.2, 0.8) == 0.8

    def test_clamp_edge_cases(self):
        """Test clamping with edge cases."""
        assert DataNormalizer.clamp(None) == 0.0
        assert DataNormalizer.clamp("invalid") == 0.0
        assert DataNormalizer.clamp(float('inf')) == 1.0
        assert DataNormalizer.clamp(float('-inf')) == 0.0
        assert DataNormalizer.clamp(float('nan')) == 0.0

    def test_normalize_to_range(self):
        """Test range normalization."""
        assert DataNormalizer.normalize_to_range(5, 0, 10) == 0.5
        assert DataNormalizer.normalize_to_range(0, 0, 10) == 0.0
        assert DataNormalizer.normalize_to_range(10, 0, 10) == 1.0
        assert DataNormalizer.normalize_to_range(5, 0, 10, 100, 200) == 150.0

    def test_normalize_to_range_degenerate(self):
        """Test degenerate range (min == max)."""
        assert DataNormalizer.normalize_to_range(5, 5, 5) == 0.5

    def test_normalize_to_range_invalid(self):
        """Test invalid inputs."""
        assert DataNormalizer.normalize_to_range(None, 0, 10) == 0.0
        assert DataNormalizer.normalize_to_range(5, None, 10) == 0.0

    def test_normalize_list(self):
        """Test list normalization."""
        values = [0, 5, 10]
        result = DataNormalizer.normalize_list(values)
        assert result == [0.0, 0.5, 1.0]

    def test_normalize_list_degenerate(self):
        """Test degenerate list (all equal)."""
        values = [5, 5, 5]
        result = DataNormalizer.normalize_list(values)
        assert result == [0.5, 0.5, 0.5]

    def test_normalize_list_empty_invalid(self):
        """Test empty or invalid lists."""
        assert DataNormalizer.normalize_list([]) == []
        assert DataNormalizer.normalize_list(None) == []
        assert DataNormalizer.normalize_list([None, "invalid"]) == []

    def test_jaccard_similarity(self):
        """Test Jaccard similarity."""
        set1 = {"a", "b", "c"}
        set2 = {"b", "c", "d"}
        assert DataNormalizer.jaccard_similarity(set1, set2) == 0.5

        # Identical sets
        assert DataNormalizer.jaccard_similarity(set1, set1) == 1.0

        # Empty sets
        assert DataNormalizer.jaccard_similarity(set(), set()) == 0.0
        assert DataNormalizer.jaccard_similarity(set1, set()) == 0.0

    def test_cosine_similarity(self):
        """Test cosine similarity."""
        vec1 = [1, 0]
        vec2 = [0, 1]
        assert DataNormalizer.cosine_similarity(vec1, vec2) == 0.0

        vec1 = [1, 1]
        vec2 = [1, 1]
        assert abs(DataNormalizer.cosine_similarity(vec1, vec2) - 1.0) < 1e-6

        # Zero vectors
        assert DataNormalizer.cosine_similarity([0, 0], [1, 1]) == 0.0

        # Mismatched lengths
        with pytest.raises(ValueError):
            DataNormalizer.cosine_similarity([1, 2], [1])

    def test_cosine_similarity_invalid(self):
        """Test cosine similarity with invalid inputs."""
        assert DataNormalizer.cosine_similarity(None, [1, 2]) == 0.0
        assert DataNormalizer.cosine_similarity([1, 2], None) == 0.0
        assert DataNormalizer.cosine_similarity([], []) == 0.0

    def test_weighted_average(self):
        """Test weighted average."""
        values = [1, 2, 3]
        weights = [1, 1, 1]
        assert DataNormalizer.weighted_average(values, weights) == 2.0

        values = [1, 2]
        weights = [3, 1]
        assert DataNormalizer.weighted_average(values, weights) == 1.25

    def test_weighted_average_edge_cases(self):
        """Test weighted average edge cases."""
        assert DataNormalizer.weighted_average(None, [1, 2]) == 0.0
        assert DataNormalizer.weighted_average([1, 2], None) == 0.0
        assert DataNormalizer.weighted_average([], []) == 0.0
        assert DataNormalizer.weighted_average([1, 2], [0, 0]) == 0.0


class TestPrompt3Normalizer:
    """Test Prompt3Normalizer integration."""

    def test_normalize_user_profile_from_analyze_valid(self):
        """Test valid analyze output conversion."""
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

        user = Prompt3Normalizer.normalize_user_profile_from_analyze(analyze_output)

        assert isinstance(user, UserProfile)
        assert [s.lower() for s in user.skills] == ["python", "sql"]
        assert [s.lower() for s in user.interests] == ["ai", "machine learning"]
        assert user.education_level == "Bachelor"
        assert user.ability_score == 0.8
        assert user.confidence_score == 0.8

    def test_normalize_user_profile_from_analyze_missing_fields(self):
        """Test missing required fields."""
        incomplete_output = {
            "age": 25,
            "education_level": "Bachelor",
            # Missing interest_tags, skill_tags, etc.
        }

        with pytest.raises(ValueError, match="Missing required fields"):
            Prompt3Normalizer.normalize_user_profile_from_analyze(incomplete_output)

    def test_normalize_user_profile_from_analyze_invalid_age(self):
        """Test invalid age."""
        invalid_output = {
            "age": "invalid",
            "education_level": "Bachelor",
            "interest_tags": ["AI"],
            "skill_tags": ["python"],
            "goal_cleaned": "Goal",
            "intent": "intent",
            "chat_summary": "summary",
            "confidence_score": 0.8
        }

        with pytest.raises(ValueError, match="Invalid age"):
            Prompt3Normalizer.normalize_user_profile_from_analyze(invalid_output)

    def test_normalize_user_profile_from_analyze_invalid_tags(self):
        """Test invalid tag types."""
        invalid_output = {
            "age": 25,
            "education_level": "Bachelor",
            "interest_tags": "not a list",
            "skill_tags": ["python"],
            "goal_cleaned": "Goal",
            "intent": "intent",
            "chat_summary": "summary",
            "confidence_score": 0.8
        }

        with pytest.raises(ValueError, match="interest_tags must be list"):
            Prompt3Normalizer.normalize_user_profile_from_analyze(invalid_output)

    def test_normalize_user_profile_from_analyze_invalid_confidence(self):
        """Test invalid confidence score."""
        invalid_output = {
            "age": 25,
            "education_level": "Bachelor",
            "interest_tags": ["AI"],
            "skill_tags": ["python"],
            "goal_cleaned": "Goal",
            "intent": "intent",
            "chat_summary": "summary",
            "confidence_score": 1.5  # Invalid
        }

        with pytest.raises(ValueError, match="confidence_score must be float in"):
            Prompt3Normalizer.normalize_user_profile_from_analyze(invalid_output)

    def test_validate_analyze_output_valid(self):
        """Test validation of valid output."""
        valid_output = {
            "age": 25,
            "education_level": "Bachelor",
            "interest_tags": ["AI"],
            "skill_tags": ["python"],
            "goal_cleaned": "Goal",
            "intent": "intent",
            "chat_summary": "summary",
            "confidence_score": 0.8
        }

        assert Prompt3Normalizer.validate_analyze_output(valid_output) is True

    def test_validate_analyze_output_invalid(self):
        """Test validation of invalid output."""
        invalid_output = {"age": "invalid"}

        with pytest.raises(ValueError):
            Prompt3Normalizer.validate_analyze_output(invalid_output)

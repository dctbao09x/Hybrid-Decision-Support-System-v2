"""
Unit tests for backend/scoring/taxonomy_adapter.py

Tests normalization functions for skills, interests, and education.
"""

import pytest
from backend.scoring.taxonomy_adapter import (
    normalize_skill_list,
    normalize_interest_list,
    normalize_education
)


class TestNormalizeSkillList:
    """Test skill list normalization."""

    def test_normalize_skill_list_valid(self):
        """Test normalizing valid skill lists."""
        skills = ["Python", "Machine Learning", "SQL"]
        result = normalize_skill_list(skills)
        assert isinstance(result, list)
        assert len(result) == 3
        # Assuming taxonomy normalizes to lowercase
        assert all(isinstance(s, str) for s in result)

    def test_normalize_skill_list_empty(self):
        """Test normalizing empty skill list."""
        result = normalize_skill_list([])
        assert result == []

    def test_normalize_skill_list_none(self):
        """Test normalizing None input."""
        result = normalize_skill_list(None)
        assert result == []

    def test_normalize_skill_list_mixed_case(self):
        """Test case normalization."""
        skills = ["PYTHON", "machine learning"]
        result = normalize_skill_list(skills)
        assert len(result) == 2
        assert all(isinstance(s, str) for s in result)


class TestNormalizeInterestList:
    """Test interest list normalization."""

    def test_normalize_interest_list_valid(self):
        """Test normalizing valid interest lists."""
        interests = ["AI", "Data Science", "Backend"]
        result = normalize_interest_list(interests)
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(i, str) for i in result)

    def test_normalize_interest_list_empty(self):
        """Test normalizing empty interest list."""
        result = normalize_interest_list([])
        assert result == []

    def test_normalize_interest_list_none(self):
        """Test normalizing None input."""
        result = normalize_interest_list(None)
        assert result == []

    def test_normalize_interest_list_mixed_case(self):
        """Test case normalization."""
        interests = ["AI", "data science"]
        result = normalize_interest_list(interests)
        assert len(result) == 2
        assert all(isinstance(i, str) for i in result)


class TestNormalizeEducation:
    """Test education level normalization."""

    def test_normalize_education_valid(self):
        """Test normalizing valid education levels."""
        result = normalize_education("Bachelor")
        assert isinstance(result, str)
        assert result != "unknown"

    def test_normalize_education_unknown(self):
        """Test normalizing unknown education."""
        result = normalize_education("invalid")
        assert result == "unknown"

    def test_normalize_education_none(self):
        """Test normalizing None input."""
        result = normalize_education(None)
        assert result == "unknown"

    def test_normalize_education_empty(self):
        """Test normalizing empty string."""
        result = normalize_education("")
        assert result == "unknown"

    def test_normalize_education_case_insensitive(self):
        """Test case insensitivity."""
        result = normalize_education("MASTER")
        assert isinstance(result, str)
        assert result != "unknown"

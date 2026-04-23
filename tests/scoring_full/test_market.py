# tests/scoring_full/test_market.py
"""
Full coverage tests for backend/scoring/components/market.py

GĐ6: Coverage Recovery - Target: ≥85%

Tests:
- Market score computation via public score() API
- Various career inputs
- Boundary conditions
- Cache behavior
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


class TestMarketScore:
    """Tests for market score() function."""
    
    def test_market_returns_score_result(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """score() returns ScoreResult."""
        from backend.scoring.components.market import score
        from backend.scoring.models import ScoreResult
        
        result = score(mock_career_data, mock_user_profile, mock_scoring_config)
        
        assert isinstance(result, ScoreResult)
        assert hasattr(result, 'value')
        assert hasattr(result, 'meta')
    
    def test_market_value_in_bounds(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """Market value is in [0, 1]."""
        from backend.scoring.components.market import score
        
        result = score(mock_career_data, mock_user_profile, mock_scoring_config)
        
        assert 0.0 <= result.value <= 1.0
    
    def test_market_meta_contains_formula(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """Meta contains formula documentation."""
        from backend.scoring.components.market import score
        
        result = score(mock_career_data, mock_user_profile, mock_scoring_config)
        
        assert "formula" in result.meta
        assert "M =" in result.meta["formula"]
    
    def test_market_meta_contains_components(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """Meta contains all market components."""
        from backend.scoring.components.market import score
        
        result = score(mock_career_data, mock_user_profile, mock_scoring_config)
        
        assert "ai_relevance" in result.meta
        assert "growth_rate" in result.meta
        assert "salary_score" in result.meta
        assert "competition" in result.meta


class TestMarketAIRelevance:
    """Tests for AI relevance factor via score()."""
    
    def test_high_ai_relevance_increases_score(
        self, mock_scoring_config, mock_user_profile
    ):
        """High AI relevance increases market score."""
        from backend.scoring.components.market import score
        from backend.scoring.models import CareerData
        
        high_ai = CareerData(
            name="AI Engineer",
            required_skills=["python"],
            domain="technology",
            ai_relevance=0.95,
            growth_rate=0.5,
            competition=0.5,
        )
        
        low_ai = CareerData(
            name="Manual Labor",
            required_skills=["skill"],
            domain="other",
            ai_relevance=0.1,
            growth_rate=0.5,
            competition=0.5,
        )
        
        high_result = score(high_ai, mock_user_profile, mock_scoring_config)
        low_result = score(low_ai, mock_user_profile, mock_scoring_config)
        
        assert high_result.value > low_result.value
    
    def test_ai_relevance_clamped_in_output(
        self, mock_scoring_config, mock_user_profile
    ):
        """AI relevance in meta is clamped to [0, 1]."""
        from backend.scoring.components.market import score
        from backend.scoring.models import CareerData
        
        career = CareerData(
            name="Data Scientist",
            required_skills=["python"],
            domain="technology",
            ai_relevance=0.9,
            growth_rate=0.85,
            competition=0.6,
        )
        
        result = score(career, mock_user_profile, mock_scoring_config)
        
        assert 0.0 <= result.meta["ai_relevance"] <= 1.0


class TestMarketGrowth:
    """Tests for growth factor via score()."""
    
    def test_high_growth_increases_score(
        self, mock_scoring_config, mock_user_profile
    ):
        """High growth rate increases market score."""
        from backend.scoring.components.market import score
        from backend.scoring.models import CareerData
        
        high_growth = CareerData(
            name="Growing Field",
            required_skills=["skill"],
            domain="technology",
            ai_relevance=0.5,
            growth_rate=0.95,
            competition=0.5,
        )
        
        low_growth = CareerData(
            name="Declining Field",
            required_skills=["skill"],
            domain="other",
            ai_relevance=0.5,
            growth_rate=0.1,
            competition=0.5,
        )
        
        high_result = score(high_growth, mock_user_profile, mock_scoring_config)
        low_result = score(low_growth, mock_user_profile, mock_scoring_config)
        
        assert high_result.value > low_result.value
    
    def test_growth_rate_in_meta(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """Growth rate appears in meta."""
        from backend.scoring.components.market import score
        
        result = score(mock_career_data, mock_user_profile, mock_scoring_config)
        
        assert "growth_rate" in result.meta
        assert isinstance(result.meta["growth_rate"], float)


class TestMarketSalary:
    """Tests for salary factor via score()."""
    
    def test_known_career_has_salary(
        self, mock_scoring_config, mock_user_profile
    ):
        """Known careers have salary score from dataset."""
        from backend.scoring.components.market import score, SALARY_DATASET
        from backend.scoring.models import CareerData
        
        career = CareerData(
            name="Software Engineer",
            required_skills=["python"],
            domain="technology",
            ai_relevance=0.8,
            growth_rate=0.7,
            competition=0.5,
        )
        
        result = score(career, mock_user_profile, mock_scoring_config)
        
        assert "salary_score" in result.meta
        assert result.meta["salary_score"] > 0
    
    def test_unknown_career_uses_default_salary(
        self, mock_scoring_config, mock_user_profile
    ):
        """Unknown careers use default salary score."""
        from backend.scoring.components.market import score, SALARY_DATASET
        from backend.scoring.models import CareerData
        
        career = CareerData(
            name="Extremely Obscure Career XYZ123",
            required_skills=["skill"],
            domain="other",
            ai_relevance=0.5,
            growth_rate=0.5,
            competition=0.5,
        )
        
        result = score(career, mock_user_profile, mock_scoring_config)
        
        assert result.meta["salary_score"] == SALARY_DATASET["default"]
    
    def test_salary_dataset_has_defaults(self):
        """Salary dataset has default entry."""
        from backend.scoring.components.market import SALARY_DATASET
        
        assert "default" in SALARY_DATASET
        assert 0.0 <= SALARY_DATASET["default"] <= 1.0


class TestMarketCompetition:
    """Tests for competition factor via score()."""
    
    def test_low_competition_increases_score(
        self, mock_scoring_config, mock_user_profile
    ):
        """Low competition increases market score (inverse relationship)."""
        from backend.scoring.components.market import score
        from backend.scoring.models import CareerData
        
        low_comp = CareerData(
            name="Niche Role",
            required_skills=["skill"],
            domain="technology",
            ai_relevance=0.5,
            growth_rate=0.5,
            competition=0.1,
        )
        
        high_comp = CareerData(
            name="Saturated Role",
            required_skills=["skill"],
            domain="other",
            ai_relevance=0.5,
            growth_rate=0.5,
            competition=0.9,
        )
        
        low_result = score(low_comp, mock_user_profile, mock_scoring_config)
        high_result = score(high_comp, mock_user_profile, mock_scoring_config)
        
        assert low_result.value > high_result.value
    
    def test_inverse_competition_in_meta(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """Inverse competition appears in meta."""
        from backend.scoring.components.market import score
        
        result = score(mock_career_data, mock_user_profile, mock_scoring_config)
        
        assert "inverse_competition" in result.meta
        assert result.meta["inverse_competition"] == 1.0 - result.meta["competition"]


class TestMarketWeights:
    """Tests for market component weights."""
    
    def test_weights_sum_to_one(self):
        """Market factor weights sum to 1.0."""
        from backend.scoring.components.market import (
            WEIGHT_AI_RELEVANCE,
            WEIGHT_GROWTH_RATE,
            WEIGHT_SALARY,
            WEIGHT_INVERSE_COMP,
        )
        
        total = WEIGHT_AI_RELEVANCE + WEIGHT_GROWTH_RATE + WEIGHT_SALARY + WEIGHT_INVERSE_COMP
        assert abs(total - 1.0) < 1e-6
    
    def test_weights_positive(self):
        """All weights are positive."""
        from backend.scoring.components.market import (
            WEIGHT_AI_RELEVANCE,
            WEIGHT_GROWTH_RATE,
            WEIGHT_SALARY,
            WEIGHT_INVERSE_COMP,
        )
        
        assert WEIGHT_AI_RELEVANCE > 0
        assert WEIGHT_GROWTH_RATE > 0
        assert WEIGHT_SALARY > 0
        assert WEIGHT_INVERSE_COMP > 0
    
    def test_weights_in_meta(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """Weights appear in meta."""
        from backend.scoring.components.market import score
        
        result = score(mock_career_data, mock_user_profile, mock_scoring_config)
        
        assert "weights_used" in result.meta
        assert "ai_relevance" in result.meta["weights_used"]


class TestBoundaryConditions:
    """Boundary tests for market component."""
    
    def test_zero_all_factors(self, mock_scoring_config, mock_user_profile):
        """Zero/worst values give low score."""
        from backend.scoring.components.market import score
        from backend.scoring.models import CareerData
        
        career = CareerData(
            name="Worst Case Job",
            required_skills=["skill"],
            domain="other",
            growth_rate=0.0,
            ai_relevance=0.0,
            competition=1.0,
        )
        
        result = score(career, mock_user_profile, mock_scoring_config)
        
        assert result.value < 0.4
    
    def test_max_all_factors(self, mock_scoring_config, mock_user_profile):
        """Max values give high score."""
        from backend.scoring.components.market import score
        from backend.scoring.models import CareerData
        
        career = CareerData(
            name="Data Scientist",
            required_skills=["python"],
            domain="technology",
            growth_rate=1.0,
            ai_relevance=1.0,
            competition=0.0,
        )
        
        result = score(career, mock_user_profile, mock_scoring_config)
        
        assert result.value > 0.8
    
    def test_boundary_values_valid(
        self, mock_scoring_config, mock_user_profile
    ):
        """Boundary values (0, 1) are valid."""
        from backend.scoring.components.market import score
        from backend.scoring.models import CareerData
        
        for boundary in [0.0, 0.5, 1.0]:
            career = CareerData(
                name="Test Career",
                required_skills=["skill"],
                domain="technology",
                ai_relevance=boundary,
                growth_rate=boundary,
                competition=boundary,
            )
            
            result = score(career, mock_user_profile, mock_scoring_config)
            
            assert 0.0 <= result.value <= 1.0


class TestMarketCache:
    """Tests for market cache interactions."""
    
    def test_cache_miss_uses_career_input(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """Cache miss falls back to career input fields."""
        from backend.scoring.components.market import score
        
        with patch('backend.scoring.components.market._cache_loader') as mock_cache:
            mock_cache.lookup_by_title.return_value = None
            
            result = score(mock_career_data, mock_user_profile, mock_scoring_config)
            
            assert result.meta["source"] == "career_input"
            assert 0.0 <= result.value <= 1.0
    
    def test_cache_hit_uses_cached_values(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """Cache hit uses cached values."""
        from backend.scoring.components.market import score
        
        with patch('backend.scoring.components.market._cache_loader') as mock_cache:
            mock_cache.lookup_by_title.return_value = {
                "ai_relevance": 0.95,
                "growth_rate": 0.9,
                "competition": 0.2,
            }
            
            result = score(mock_career_data, mock_user_profile, mock_scoring_config)
            
            assert result.meta["source"] == "cache"
            assert result.meta["ai_relevance"] == 0.95


class TestSalaryLookup:
    """Tests for salary dataset lookups."""
    
    def test_exact_match_lookup(self):
        """Exact career name matches in salary dataset."""
        from backend.scoring.components.market import _get_salary_score, SALARY_DATASET
        
        result = _get_salary_score("software engineer")
        
        assert result == SALARY_DATASET["software engineer"]
    
    def test_case_insensitive_lookup(self):
        """Lookup is case insensitive."""
        from backend.scoring.components.market import _get_salary_score, SALARY_DATASET
        
        result = _get_salary_score("SOFTWARE ENGINEER")
        
        assert result == SALARY_DATASET["software engineer"]
    
    def test_partial_match_lookup(self):
        """Partial matches work."""
        from backend.scoring.components.market import _get_salary_score
        
        result = _get_salary_score("senior data scientist")
        
        assert result > 0.5
    
    def test_empty_name_returns_default(self):
        """Empty career name returns default."""
        from backend.scoring.components.market import _get_salary_score, SALARY_DATASET
        
        result = _get_salary_score("")
        
        assert result == SALARY_DATASET["default"]
    
    def test_unknown_name_returns_default(self):
        """Unknown career returns default."""
        from backend.scoring.components.market import _get_salary_score, SALARY_DATASET
        
        result = _get_salary_score("completely_unknown_xzy123")
        
        assert result == SALARY_DATASET["default"]


class TestMarketSource:
    """Tests for market data source tracking."""
    
    def test_source_field_present(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """Source field present in meta."""
        from backend.scoring.components.market import score
        
        result = score(mock_career_data, mock_user_profile, mock_scoring_config)
        
        assert "source" in result.meta
        assert result.meta["source"] in ["cache", "career_input"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

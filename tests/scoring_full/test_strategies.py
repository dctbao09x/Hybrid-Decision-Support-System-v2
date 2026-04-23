# tests/scoring_full/test_strategies.py
"""
Full coverage tests for backend/scoring/strategies.py

GĐ6: Coverage Recovery - Target: ≥85%

Tests:
- ScoringStrategy base class
- WeightedScoringStrategy
- PersonalizedScoringStrategy
- StrategyFactory
- Pre/post hooks
- Threshold filtering
"""

from __future__ import annotations

import pytest
from typing import List
from unittest.mock import MagicMock, patch
from copy import deepcopy


class TestScoringStrategyBase:
    """Tests for ScoringStrategy base class."""
    
    def test_init_requires_scoring_config(self, mock_scoring_config):
        """Init requires ScoringConfig type."""
        from backend.scoring.strategies import WeightedScoringStrategy
        
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        assert strategy.config is not None
    
    def test_init_rejects_invalid_config(self):
        """Init rejects non-ScoringConfig."""
        from backend.scoring.strategies import WeightedScoringStrategy
        
        with pytest.raises(TypeError):
            WeightedScoringStrategy({"not": "a config"})
    
    def test_init_deepcopies_config(self, mock_scoring_config):
        """Config is deepcopied to prevent mutation."""
        from backend.scoring.strategies import WeightedScoringStrategy
        
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        # Modifying original should not affect strategy's copy
        original_weight = mock_scoring_config.simgr_weights.study_score
        mock_scoring_config.simgr_weights.study_score = 0.99
        
        assert strategy.config.simgr_weights.study_score == original_weight
    
    def test_creates_calculator(self, mock_scoring_config):
        """Calculator created on init."""
        from backend.scoring.strategies import WeightedScoringStrategy
        from backend.scoring.calculator import SIMGRCalculator
        
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        assert hasattr(strategy, '_calculator')
        assert isinstance(strategy._calculator, SIMGRCalculator)


class TestPrePostRankHooks:
    """Tests for pre_rank and post_rank hooks."""
    
    def test_pre_rank_accepts_args(self, mock_scoring_config, mock_user_profile, mock_career_data):
        """pre_rank accepts user and careers."""
        from backend.scoring.strategies import WeightedScoringStrategy
        
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        # Should not raise
        strategy.pre_rank(mock_user_profile, [mock_career_data])
    
    def test_post_rank_accepts_results(self, mock_scoring_config):
        """post_rank accepts results list."""
        from backend.scoring.strategies import WeightedScoringStrategy
        
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        # Should not raise
        strategy.post_rank([])


class TestScoreOne:
    """Tests for score_one method."""
    
    def test_score_one_returns_scored_career(self, mock_scoring_config, mock_user_profile, mock_career_data):
        """score_one returns ScoredCareer."""
        from backend.scoring.strategies import WeightedScoringStrategy
        from backend.scoring.models import ScoredCareer
        
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        result = strategy.score_one(mock_user_profile, mock_career_data)
        
        assert isinstance(result, ScoredCareer)
    
    def test_score_one_has_breakdown(self, mock_scoring_config, mock_user_profile, mock_career_data):
        """score_one includes score breakdown."""
        from backend.scoring.strategies import WeightedScoringStrategy
        
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        result = strategy.score_one(mock_user_profile, mock_career_data)
        
        assert result.breakdown is not None
        assert hasattr(result.breakdown, 'study_score')
        assert hasattr(result.breakdown, 'interest_score')
    
    def test_score_one_filters_below_threshold(self, mock_scoring_config, mock_user_profile):
        """Career below threshold filtered out."""
        from backend.scoring.strategies import WeightedScoringStrategy
        from backend.scoring.models import CareerData
        
        mock_scoring_config.min_score_threshold = 0.99  # Very high threshold
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        # Career that will score low
        low_career = CareerData(
            name="Low Score",
            required_skills=["nonexistent_skill"],
            domain="other",
            ai_relevance=0.0,
            growth_rate=0.0,
            competition=1.0,
        )
        
        result = strategy.score_one(mock_user_profile, low_career)
        
        # Should be filtered
        assert result is None
    
    def test_score_one_returns_none_on_error(self, mock_scoring_config, mock_user_profile):
        """score_one returns None on error (non-debug mode)."""
        from backend.scoring.strategies import WeightedScoringStrategy
        
        mock_scoring_config.debug_mode = False
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        # Mock calculator to raise
        with patch.object(strategy._calculator, 'calculate', side_effect=Exception("Test error")):
            result = strategy.score_one(mock_user_profile, MagicMock())
        
        assert result is None
    
    def test_score_one_raises_in_debug_mode(self, mock_scoring_config, mock_user_profile):
        """score_one raises in debug mode."""
        from backend.scoring.strategies import WeightedScoringStrategy
        
        mock_scoring_config.debug_mode = True
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        # Mock calculator to raise
        with patch.object(strategy._calculator, 'calculate', side_effect=Exception("Test error")):
            with pytest.raises(Exception):
                strategy.score_one(mock_user_profile, MagicMock())


class TestRank:
    """Tests for rank method."""
    
    def test_rank_returns_sorted_list(self, mock_scoring_config, mock_user_profile):
        """rank returns sorted list."""
        from backend.scoring.strategies import WeightedScoringStrategy
        from backend.scoring.models import CareerData
        
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        careers = [
            CareerData(name="Career A", required_skills=["python"], domain="tech"),
            CareerData(name="Career B", required_skills=["java"], domain="tech"),
        ]
        
        results = strategy.rank(mock_user_profile, careers)
        
        assert isinstance(results, list)
        # Should be sorted by score descending
        if len(results) >= 2:
            assert results[0].total_score >= results[1].total_score
    
    def test_rank_assigns_positions(self, mock_scoring_config, mock_user_profile):
        """rank assigns rank positions."""
        from backend.scoring.strategies import WeightedScoringStrategy
        from backend.scoring.models import CareerData
        
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        careers = [
            CareerData(name="Career A", required_skills=["python"], domain="tech"),
            CareerData(name="Career B", required_skills=["java"], domain="tech"),
        ]
        
        results = strategy.rank(mock_user_profile, careers)
        
        if len(results) >= 1:
            assert results[0].rank == 1
        if len(results) >= 2:
            assert results[1].rank == 2
    
    def test_rank_empty_list_returns_empty(self, mock_scoring_config, mock_user_profile):
        """Empty career list returns empty result."""
        from backend.scoring.strategies import WeightedScoringStrategy
        
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        results = strategy.rank(mock_user_profile, [])
        
        assert results == []
    
    def test_rank_calls_pre_rank(self, mock_scoring_config, mock_user_profile, mock_career_data):
        """rank calls pre_rank hook."""
        from backend.scoring.strategies import WeightedScoringStrategy
        
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        with patch.object(strategy, 'pre_rank') as mock_pre:
            strategy.rank(mock_user_profile, [mock_career_data])
            mock_pre.assert_called_once()
    
    def test_rank_calls_post_rank(self, mock_scoring_config, mock_user_profile, mock_career_data):
        """rank calls post_rank hook."""
        from backend.scoring.strategies import WeightedScoringStrategy
        
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        with patch.object(strategy, 'post_rank') as mock_post:
            strategy.rank(mock_user_profile, [mock_career_data])
            mock_post.assert_called_once()


class TestWeightedScoringStrategy:
    """Tests for WeightedScoringStrategy."""
    
    def test_weighted_inherits_base(self, mock_scoring_config):
        """WeightedScoringStrategy inherits ScoringStrategy."""
        from backend.scoring.strategies import WeightedScoringStrategy, ScoringStrategy
        
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        assert isinstance(strategy, ScoringStrategy)
    
    def test_weighted_uses_fixed_weights(self, mock_scoring_config, mock_user_profile, mock_career_data):
        """Weighted strategy uses fixed config weights."""
        from backend.scoring.strategies import WeightedScoringStrategy
        
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        # Weights should match config
        assert strategy.config.simgr_weights.study_score == mock_scoring_config.simgr_weights.study_score


class TestPersonalizedScoringStrategy:
    """Tests for PersonalizedScoringStrategy."""
    
    def test_personalized_inherits_base(self, mock_scoring_config):
        """PersonalizedScoringStrategy inherits ScoringStrategy."""
        from backend.scoring.strategies import PersonalizedScoringStrategy, ScoringStrategy
        
        strategy = PersonalizedScoringStrategy(mock_scoring_config)
        
        assert isinstance(strategy, ScoringStrategy)
    
    def test_personalized_builds_config_on_pre_rank(self, mock_scoring_config, mock_user_profile, mock_career_data):
        """pre_rank builds personalized config."""
        from backend.scoring.strategies import PersonalizedScoringStrategy
        
        strategy = PersonalizedScoringStrategy(mock_scoring_config)
        
        assert strategy.personalized_config is None
        
        strategy.pre_rank(mock_user_profile, [mock_career_data])
        
        assert strategy.personalized_config is not None
    
    def test_personalized_high_confidence_boosts_interest(self, mock_scoring_config):
        """High confidence boosts interest weight."""
        from backend.scoring.strategies import PersonalizedScoringStrategy
        from backend.scoring.models import UserProfile
        
        base_interest = mock_scoring_config.simgr_weights.interest_score
        
        strategy = PersonalizedScoringStrategy(mock_scoring_config)
        
        high_conf_user = UserProfile(
            skills=["python"],
            interests=["tech"],
            education_level="Bachelor",
            ability_score=0.5,
            confidence_score=0.9,  # High confidence
        )
        
        personalized = strategy._build_personalized_config(high_conf_user)
        
        # Interest should be boosted
        assert personalized.simgr_weights.interest_score >= base_interest
    
    def test_personalized_low_confidence_boosts_study(self, mock_scoring_config):
        """Low confidence boosts study weight."""
        from backend.scoring.strategies import PersonalizedScoringStrategy
        from backend.scoring.models import UserProfile
        
        base_study = mock_scoring_config.simgr_weights.study_score
        
        strategy = PersonalizedScoringStrategy(mock_scoring_config)
        
        low_conf_user = UserProfile(
            skills=["python"],
            interests=["tech"],
            education_level="Bachelor",
            ability_score=0.5,
            confidence_score=0.2,  # Low confidence
        )
        
        personalized = strategy._build_personalized_config(low_conf_user)
        
        # Study should be boosted
        assert personalized.simgr_weights.study_score >= base_study
    
    def test_personalized_low_ability_boosts_market(self, mock_scoring_config):
        """Low ability boosts market weight (stability)."""
        from backend.scoring.strategies import PersonalizedScoringStrategy
        from backend.scoring.models import UserProfile
        
        base_market = mock_scoring_config.simgr_weights.market_score
        
        strategy = PersonalizedScoringStrategy(mock_scoring_config)
        
        low_ability_user = UserProfile(
            skills=["python"],
            interests=["tech"],
            education_level="Bachelor",
            ability_score=0.2,  # Low ability
            confidence_score=0.5,
        )
        
        personalized = strategy._build_personalized_config(low_ability_user)
        
        # Market should be boosted
        assert personalized.simgr_weights.market_score >= base_market
    
    def test_personalized_high_ability_boosts_growth(self, mock_scoring_config):
        """High ability boosts growth weight."""
        from backend.scoring.strategies import PersonalizedScoringStrategy
        from backend.scoring.models import UserProfile
        
        base_growth = mock_scoring_config.simgr_weights.growth_score
        
        strategy = PersonalizedScoringStrategy(mock_scoring_config)
        
        high_ability_user = UserProfile(
            skills=["python"],
            interests=["tech"],
            education_level="Bachelor",
            ability_score=0.9,  # High ability
            confidence_score=0.5,
        )
        
        personalized = strategy._build_personalized_config(high_ability_user)
        
        # Growth should be boosted
        assert personalized.simgr_weights.growth_score >= base_growth
    
    def test_personalized_never_mutates_base(self, mock_scoring_config):
        """Personalization never mutates base config."""
        from backend.scoring.strategies import PersonalizedScoringStrategy
        from backend.scoring.models import UserProfile
        from copy import deepcopy
        
        original_config = deepcopy(mock_scoring_config)
        
        strategy = PersonalizedScoringStrategy(mock_scoring_config)
        
        user = UserProfile(
            skills=["python"],
            interests=["tech"],
            education_level="Bachelor",
            ability_score=0.9,
            confidence_score=0.9,
        )
        
        strategy._build_personalized_config(user)
        
        # Base config should be unchanged
        assert strategy.config.simgr_weights.study_score == original_config.simgr_weights.study_score


class TestStrategyFactory:
    """Tests for StrategyFactory."""
    
    def test_factory_creates_weighted(self, mock_scoring_config):
        """Factory creates WeightedScoringStrategy."""
        from backend.scoring.strategies import StrategyFactory, WeightedScoringStrategy
        
        strategy = StrategyFactory.create("weighted", mock_scoring_config)
        
        assert isinstance(strategy, WeightedScoringStrategy)
    
    def test_factory_creates_personalized(self, mock_scoring_config):
        """Factory creates PersonalizedScoringStrategy."""
        from backend.scoring.strategies import StrategyFactory, PersonalizedScoringStrategy
        
        strategy = StrategyFactory.create("personalized", mock_scoring_config)
        
        assert isinstance(strategy, PersonalizedScoringStrategy)
    
    def test_factory_case_insensitive(self, mock_scoring_config):
        """Factory name is case-insensitive."""
        from backend.scoring.strategies import StrategyFactory, WeightedScoringStrategy
        
        strategy = StrategyFactory.create("WEIGHTED", mock_scoring_config)
        
        assert isinstance(strategy, WeightedScoringStrategy)
    
    def test_factory_unknown_raises(self, mock_scoring_config):
        """Unknown strategy name raises ValueError."""
        from backend.scoring.strategies import StrategyFactory
        
        with pytest.raises(ValueError) as exc_info:
            StrategyFactory.create("unknown_strategy", mock_scoring_config)
        
        assert "Unknown strategy" in str(exc_info.value)
    
    def test_factory_list_strategies(self):
        """list_strategies returns all registered."""
        from backend.scoring.strategies import StrategyFactory
        
        strategies = StrategyFactory.list_strategies()
        
        assert "weighted" in strategies
        assert "personalized" in strategies
    
    def test_factory_register_custom(self, mock_scoring_config):
        """register adds custom strategy."""
        from backend.scoring.strategies import StrategyFactory, ScoringStrategy
        
        class CustomStrategy(ScoringStrategy):
            pass
        
        StrategyFactory.register("custom_test", CustomStrategy)
        
        assert "custom_test" in StrategyFactory.list_strategies()
        
        # Clean up
        del StrategyFactory._registry["custom_test"]
    
    def test_factory_register_requires_inheritance(self):
        """register requires ScoringStrategy inheritance."""
        from backend.scoring.strategies import StrategyFactory
        
        class NotAStrategy:
            pass
        
        with pytest.raises(TypeError):
            StrategyFactory.register("invalid", NotAStrategy)


class TestScoreOneMissingBreakdown:
    """Tests for missing breakdown handling."""
    
    def test_missing_breakdown_key_raises(self, mock_scoring_config, mock_user_profile, mock_career_data):
        """Missing breakdown key raises ValueError."""
        from backend.scoring.strategies import WeightedScoringStrategy
        
        mock_scoring_config.debug_mode = True
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        # Mock calculator to return incomplete breakdown
        incomplete_breakdown = {
            "study_score": 0.5,
            # Missing other keys
        }
        
        with patch.object(strategy._calculator, 'calculate', return_value=(0.5, incomplete_breakdown)):
            with pytest.raises(ValueError) as exc_info:
                strategy.score_one(mock_user_profile, mock_career_data)
            
            assert "Incomplete breakdown" in str(exc_info.value)


class TestThresholdFiltering:
    """Tests for score threshold filtering."""
    
    def test_threshold_zero_accepts_all(self, mock_scoring_config, mock_user_profile, mock_career_data):
        """Zero threshold accepts all careers."""
        from backend.scoring.strategies import WeightedScoringStrategy
        
        mock_scoring_config.min_score_threshold = 0.0
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        result = strategy.score_one(mock_user_profile, mock_career_data)
        
        assert result is not None
    
    def test_threshold_one_filters_all(self, mock_scoring_config, mock_user_profile, mock_career_data):
        """Threshold of 1.0 filters all (impossible to achieve)."""
        from backend.scoring.strategies import WeightedScoringStrategy
        
        mock_scoring_config.min_score_threshold = 1.0001  # Impossible
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        result = strategy.score_one(mock_user_profile, mock_career_data)
        
        assert result is None


class TestScoredCareerRounding:
    """Tests for score rounding behavior."""
    
    def test_total_score_rounded_to_4_decimals(self, mock_scoring_config, mock_user_profile, mock_career_data):
        """Total score rounded to 4 decimal places."""
        from backend.scoring.strategies import WeightedScoringStrategy
        
        strategy = WeightedScoringStrategy(mock_scoring_config)
        
        result = strategy.score_one(mock_user_profile, mock_career_data)
        
        # Check rounding
        score_str = str(result.total_score)
        if '.' in score_str:
            decimals = len(score_str.split('.')[1])
            assert decimals <= 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

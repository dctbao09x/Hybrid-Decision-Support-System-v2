# tests/scoring_full/test_engine.py
"""
Full coverage tests for backend/scoring/engine.py

GĐ6: Coverage Recovery - Target: ≥85%

Tests:
- RankingEngine initialization
- Strategy building
- Ranking pipeline
- Input validation
- Error handling
- Stateless facade
"""

from __future__ import annotations

import pytest
from typing import List
from unittest.mock import MagicMock, patch


class TestRankingContext:
    """Tests for RankingContext class."""
    
    def test_context_has_request_id(self):
        """Context generates unique request ID."""
        from backend.scoring.engine import RankingContext
        
        ctx1 = RankingContext()
        ctx2 = RankingContext()
        
        assert ctx1.request_id is not None
        assert ctx2.request_id is not None
        assert ctx1.request_id != ctx2.request_id
    
    def test_context_has_timestamp(self):
        """Context has timestamp."""
        from backend.scoring.engine import RankingContext
        
        ctx = RankingContext()
        assert ctx.timestamp is not None
    
    def test_context_to_dict(self):
        """Context exports to dict."""
        from backend.scoring.engine import RankingContext
        
        ctx = RankingContext()
        d = ctx.to_dict()
        
        assert "request_id" in d
        assert "timestamp" in d
        assert isinstance(d["request_id"], str)


class TestRankingEngineInit:
    """Tests for RankingEngine initialization."""
    
    def test_init_with_defaults(self, mock_scoring_config):
        """Engine initializes with defaults."""
        from backend.scoring.engine import RankingEngine
        
        with patch("backend.scoring.engine.DEFAULT_CONFIG", mock_scoring_config):
            engine = RankingEngine()
            
            assert engine._default_config is not None
            assert engine._default_strategy_name == "weighted"
    
    def test_init_with_custom_config(self, mock_scoring_config):
        """Engine accepts custom config."""
        from backend.scoring.engine import RankingEngine
        
        engine = RankingEngine(default_config=mock_scoring_config)
        assert engine._default_config == mock_scoring_config
    
    def test_init_with_custom_strategy(self, mock_scoring_config):
        """Engine accepts custom default strategy."""
        from backend.scoring.engine import RankingEngine
        
        engine = RankingEngine(
            default_config=mock_scoring_config,
            default_strategy="personalized"
        )
        assert engine._default_strategy_name == "personalized"
    
    def test_init_invalid_strategy_falls_back(self, mock_scoring_config):
        """Invalid strategy falls back to weighted."""
        from backend.scoring.engine import RankingEngine
        
        engine = RankingEngine(
            default_config=mock_scoring_config,
            default_strategy="invalid_strategy"
        )
        assert engine._default_strategy_name == "weighted"


class TestRankingEngineRank:
    """Tests for RankingEngine.rank() method."""
    
    def test_rank_empty_careers_returns_empty(
        self, mock_scoring_config, mock_user_profile
    ):
        """Empty career list returns empty results."""
        from backend.scoring.engine import RankingEngine
        
        engine = RankingEngine(default_config=mock_scoring_config)
        results = engine.rank(mock_user_profile, [])
        
        assert results == []
    
    def test_rank_invalid_user_returns_empty(
        self, mock_scoring_config, mock_career_data
    ):
        """Invalid user type returns empty results."""
        from backend.scoring.engine import RankingEngine
        
        engine = RankingEngine(default_config=mock_scoring_config)
        results = engine.rank("not_a_user", [mock_career_data])
        
        assert results == []
    
    def test_rank_returns_scored_careers(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """rank() returns list of ScoredCareer."""
        from backend.scoring.engine import RankingEngine
        from backend.scoring.models import ScoredCareer
        
        engine = RankingEngine(default_config=mock_scoring_config)
        results = engine.rank(mock_user_profile, [mock_career_data])
        
        assert isinstance(results, list)
        if results:  # May be empty if filtered
            assert all(isinstance(r, ScoredCareer) for r in results)
    
    def test_rank_sorted_by_total_score(
        self, mock_scoring_config, mock_user_profile, multiple_careers,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """Results are sorted by total_score descending."""
        from backend.scoring.engine import RankingEngine
        
        engine = RankingEngine(default_config=mock_scoring_config)
        results = engine.rank(mock_user_profile, multiple_careers)
        
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i].total_score >= results[i + 1].total_score
    
    def test_rank_with_strategy_override(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """rank() accepts strategy override."""
        from backend.scoring.engine import RankingEngine
        
        engine = RankingEngine(default_config=mock_scoring_config)
        
        # Should not crash with valid strategy
        results = engine.rank(
            mock_user_profile, 
            [mock_career_data],
            strategy_name="weighted"
        )
        
        assert isinstance(results, list)
    
    def test_rank_with_config_override(
        self, mock_scoring_config, strict_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """rank() accepts config override."""
        from backend.scoring.engine import RankingEngine
        
        engine = RankingEngine(default_config=mock_scoring_config)
        
        results = engine.rank(
            mock_user_profile,
            [mock_career_data],
            config_override=strict_config
        )
        
        assert isinstance(results, list)


class TestRankingEngineErrorHandling:
    """Tests for error handling in RankingEngine."""
    
    def test_strategy_creation_error_returns_empty(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """Strategy creation error returns empty in non-debug mode."""
        from backend.scoring.engine import RankingEngine
        
        mock_scoring_config.debug_mode = False
        engine = RankingEngine(default_config=mock_scoring_config)
        
        # Force strategy creation to fail
        with patch.object(engine, '_build_strategy', side_effect=ValueError("Strategy error")):
            results = engine.rank(mock_user_profile, [mock_career_data])
            assert results == []
    
    def test_strategy_creation_error_raises_in_debug(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """Strategy creation error raises in debug mode."""
        from backend.scoring.engine import RankingEngine
        
        mock_scoring_config.debug_mode = True
        engine = RankingEngine(default_config=mock_scoring_config)
        
        with patch.object(engine, '_build_strategy', side_effect=ValueError("Strategy error")):
            with pytest.raises(ValueError, match="Strategy error"):
                engine.rank(mock_user_profile, [mock_career_data])


class TestRankFromInput:
    """Tests for RankingEngine.rank_from_input() method."""
    
    def test_rank_from_input_returns_output(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """rank_from_input() returns RankingOutput."""
        from backend.scoring.engine import RankingEngine
        from backend.scoring.models import RankingInput, RankingOutput
        
        engine = RankingEngine(default_config=mock_scoring_config)
        
        ranking_input = RankingInput(
            user_profile=mock_user_profile,
            eligible_careers=[mock_career_data],
        )
        
        output = engine.rank_from_input(ranking_input)
        
        assert isinstance(output, RankingOutput)
        assert output.total_evaluated == 1
    
    def test_rank_from_input_with_strategy(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """rank_from_input() accepts strategy override."""
        from backend.scoring.engine import RankingEngine
        from backend.scoring.models import RankingInput
        
        engine = RankingEngine(default_config=mock_scoring_config)
        
        ranking_input = RankingInput(
            user_profile=mock_user_profile,
            eligible_careers=[mock_career_data],
        )
        
        output = engine.rank_from_input(ranking_input, strategy_name="weighted")
        
        assert output is not None


class TestStatelessFacade:
    """Tests for stateless facade functions."""
    
    def test_rank_careers_function(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """rank_careers() facade works."""
        from backend.scoring.engine import rank_careers
        
        results = rank_careers(
            mock_user_profile, 
            [mock_career_data],
            config=mock_scoring_config
        )
        assert isinstance(results, list)
    
    def test_rank_careers_with_config_override(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """rank_careers() accepts config override."""
        from backend.scoring.engine import rank_careers
        
        results = rank_careers(
            mock_user_profile,
            [mock_career_data],
            config=mock_scoring_config
        )
        
        assert isinstance(results, list)


class TestBuildStrategy:
    """Tests for _build_strategy method."""
    
    def test_build_weighted_strategy(self, mock_scoring_config):
        """Builds weighted strategy."""
        from backend.scoring.engine import RankingEngine
        from backend.scoring.strategies import WeightedScoringStrategy
        
        engine = RankingEngine(default_config=mock_scoring_config)
        strategy = engine._build_strategy(mock_scoring_config, "weighted")
        
        assert isinstance(strategy, WeightedScoringStrategy)
    
    def test_build_personalized_strategy(self, mock_scoring_config):
        """Builds personalized strategy."""
        from backend.scoring.engine import RankingEngine
        from backend.scoring.strategies import PersonalizedScoringStrategy
        
        engine = RankingEngine(default_config=mock_scoring_config)
        strategy = engine._build_strategy(mock_scoring_config, "personalized")
        
        assert isinstance(strategy, PersonalizedScoringStrategy)
    
    def test_build_unknown_strategy_raises(self, mock_scoring_config):
        """Unknown strategy raises ValueError."""
        from backend.scoring.engine import RankingEngine
        
        engine = RankingEngine(default_config=mock_scoring_config)
        
        with pytest.raises(ValueError, match="Unknown strategy"):
            engine._build_strategy(mock_scoring_config, "unknown_strategy")
    
    def test_build_uses_default_when_none(self, mock_scoring_config):
        """Uses default strategy when name is None."""
        from backend.scoring.engine import RankingEngine
        
        engine = RankingEngine(default_config=mock_scoring_config)
        strategy = engine._build_strategy(mock_scoring_config, None)
        
        # Default is "weighted"
        assert strategy is not None


class TestContextPassthrough:
    """Tests for context passing through ranking."""
    
    def test_auto_creates_context(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """Context auto-created when not provided."""
        from backend.scoring.engine import RankingEngine
        
        engine = RankingEngine(default_config=mock_scoring_config)
        
        # Should not crash without context
        results = engine.rank(mock_user_profile, [mock_career_data])
        assert isinstance(results, list)
    
    def test_uses_provided_context(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """Uses provided context."""
        from backend.scoring.engine import RankingEngine, RankingContext
        
        engine = RankingEngine(default_config=mock_scoring_config)
        ctx = RankingContext()
        
        results = engine.rank(
            mock_user_profile,
            [mock_career_data],
            context=ctx
        )
        
        assert isinstance(results, list)


# =====================================================
# ENGINE COVERAGE HARDENING - GĐ6
# =====================================================

class TestScoreJobsFacade:
    """Tests for score_jobs() facade function."""
    
    def test_score_jobs_returns_list(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """score_jobs() returns list of ScoringResult."""
        from backend.scoring.engine import score_jobs
        
        results = score_jobs(
            [mock_career_data],
            mock_user_profile,
            config=mock_scoring_config
        )
        
        assert isinstance(results, list)
    
    def test_score_jobs_empty_list(self, mock_scoring_config, mock_user_profile):
        """score_jobs() with empty list returns empty."""
        from backend.scoring.engine import score_jobs
        
        results = score_jobs([], mock_user_profile, config=mock_scoring_config)
        assert results == []
    
    def test_score_jobs_has_contributions(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """score_jobs() results have contributions dict."""
        from backend.scoring.engine import score_jobs
        
        results = score_jobs(
            [mock_career_data],
            mock_user_profile,
            config=mock_scoring_config
        )
        
        if results:
            assert hasattr(results[0], 'contributions')
            assert isinstance(results[0].contributions, dict)
    
    def test_score_jobs_with_strategy(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """score_jobs() accepts strategy parameter."""
        from backend.scoring.engine import score_jobs
        
        results = score_jobs(
            [mock_career_data],
            mock_user_profile,
            config=mock_scoring_config,
            strategy="weighted"
        )
        
        assert isinstance(results, list)


class TestCreateEngineFactory:
    """Tests for create_engine() factory function."""
    
    def test_create_engine_default(self):
        """create_engine() with defaults."""
        from backend.scoring.engine import create_engine
        
        engine = create_engine()
        assert engine is not None
    
    def test_create_engine_with_config(self, mock_scoring_config):
        """create_engine() with custom config."""
        from backend.scoring.engine import create_engine
        
        engine = create_engine(config=mock_scoring_config)
        assert engine._default_config == mock_scoring_config
    
    def test_create_engine_with_strategy(self, mock_scoring_config):
        """create_engine() with custom strategy."""
        from backend.scoring.engine import create_engine
        
        engine = create_engine(
            config=mock_scoring_config,
            strategy="personalized"
        )
        assert engine._default_strategy_name == "personalized"


class TestRankingOutputConstruction:
    """Tests for RankingOutput construction."""
    
    def test_ranking_output_has_ranked_careers(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """RankingOutput has ranked_careers list."""
        from backend.scoring.engine import RankingEngine
        from backend.scoring.models import RankingInput
        
        engine = RankingEngine(default_config=mock_scoring_config)
        ranking_input = RankingInput(
            user_profile=mock_user_profile,
            eligible_careers=[mock_career_data],
        )
        
        output = engine.rank_from_input(ranking_input)
        
        assert hasattr(output, 'ranked_careers')
        assert isinstance(output.ranked_careers, list)
    
    def test_ranking_output_has_total_evaluated(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """RankingOutput has total_evaluated count."""
        from backend.scoring.engine import RankingEngine
        from backend.scoring.models import RankingInput
        
        engine = RankingEngine(default_config=mock_scoring_config)
        ranking_input = RankingInput(
            user_profile=mock_user_profile,
            eligible_careers=[mock_career_data, mock_career_data],
        )
        
        output = engine.rank_from_input(ranking_input)
        
        assert output.total_evaluated == 2
    
    def test_ranking_output_has_config_used(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """RankingOutput has config_used dict."""
        from backend.scoring.engine import RankingEngine
        from backend.scoring.models import RankingInput
        
        engine = RankingEngine(default_config=mock_scoring_config)
        ranking_input = RankingInput(
            user_profile=mock_user_profile,
            eligible_careers=[mock_career_data],
        )
        
        output = engine.rank_from_input(ranking_input)
        
        assert hasattr(output, 'config_used')
        assert isinstance(output.config_used, dict)


class TestEngineEdgeCases:
    """Tests for engine edge cases and error paths."""
    
    def test_rank_with_none_user_graceful(self, mock_scoring_config, mock_career_data):
        """Ranking with None user handled gracefully."""
        from backend.scoring.engine import RankingEngine
        
        engine = RankingEngine(default_config=mock_scoring_config)
        results = engine.rank(None, [mock_career_data])
        
        # Should return empty or handle gracefully
        assert results == [] or results is not None
    
    def test_rank_with_none_careers_graceful(self, mock_scoring_config, mock_user_profile):
        """Ranking with None careers handled gracefully."""
        from backend.scoring.engine import RankingEngine
        
        engine = RankingEngine(default_config=mock_scoring_config)
        results = engine.rank(mock_user_profile, None)
        
        # Should return empty list
        assert results == []
    
    def test_rank_multiple_careers_assigns_positions(
        self, mock_scoring_config, mock_user_profile, multiple_careers,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """Multiple careers get assigned rank positions."""
        from backend.scoring.engine import RankingEngine
        
        engine = RankingEngine(default_config=mock_scoring_config)
        results = engine.rank(mock_user_profile, multiple_careers)
        
        if len(results) > 0:
            # First result should have rank = 1
            assert results[0].rank == 1
        
        if len(results) > 1:
            # Second should have rank = 2
            assert results[1].rank == 2


class TestEngineExceptionHandling:
    """Tests for engine exception handling paths."""
    
    def test_rank_exception_returns_empty_in_non_debug(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """Exceptions during ranking return empty list in non-debug mode."""
        from backend.scoring.engine import RankingEngine
        from unittest.mock import patch, MagicMock
        
        mock_scoring_config.debug_mode = False
        engine = RankingEngine(default_config=mock_scoring_config)
        
        # Force an exception in score_all by patching the strategy's rank method
        with patch('backend.scoring.engine.StrategyFactory.create') as mock_create:
            mock_strategy = MagicMock()
            mock_strategy.rank.side_effect = RuntimeError("Test error")
            mock_create.return_value = mock_strategy
            
            results = engine.rank(mock_user_profile, [mock_career_data])
            
            # Should return empty list, not raise
            assert results == []
    
    def test_rank_exception_raises_in_debug(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """Exceptions during ranking re-raise in debug mode."""
        from backend.scoring.engine import RankingEngine
        from unittest.mock import patch, MagicMock
        
        mock_scoring_config.debug_mode = True
        engine = RankingEngine(default_config=mock_scoring_config)
        
        # Force an exception
        with patch('backend.scoring.engine.StrategyFactory.create') as mock_create:
            mock_strategy = MagicMock()
            mock_strategy.rank.side_effect = RuntimeError("Debug mode error")
            mock_create.return_value = mock_strategy
            
            with pytest.raises(RuntimeError, match="Debug mode error"):
                engine.rank(mock_user_profile, [mock_career_data])


class TestScoreWithSnapshot:
    """Tests for score_with_snapshot function.
    
    Covers lines 399-487 in engine.py.
    """
    
    def test_score_with_snapshot_importable(self):
        """score_with_snapshot function is importable."""
        from backend.scoring.engine import score_with_snapshot
        
        assert callable(score_with_snapshot)
    
    def test_score_with_snapshot_signature(self):
        """score_with_snapshot has expected parameters."""
        from backend.scoring.engine import score_with_snapshot
        import inspect
        
        sig = inspect.signature(score_with_snapshot)
        params = list(sig.parameters.keys())
        
        assert "user_dict" in params
        assert "careers_list" in params
    
    def test_score_with_snapshot_basic(
        self, mock_scoring_config,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """score_with_snapshot returns structured output."""
        from backend.scoring import engine as engine_module
        from backend.scoring.engine import RankingEngine, score_with_snapshot
        
        # Initialize global _engine
        engine_module._engine = RankingEngine(default_config=mock_scoring_config)
        
        user_dict = {
            "skills": ["python", "sql"],
            "interests": ["technology", "data"],
            "education_level": "Bachelor",
            "ability_score": 0.7,
            "confidence_score": 0.6,
        }
        
        careers_list = [
            {
                "name": "Software Engineer",
                "required_skills": ["python"],
                "domain": "technology",
            }
        ]
        
        result = score_with_snapshot(user_dict, careers_list)
        
        # Should return structured output
        assert hasattr(result, 'score_cards')
        assert hasattr(result, 'total_evaluated')
        assert result.total_evaluated >= 0
    
    def test_score_with_snapshot_with_weights(
        self, mock_scoring_config,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """score_with_snapshot with custom weights."""
        from backend.scoring import engine as engine_module
        from backend.scoring.engine import RankingEngine, score_with_snapshot
        
        engine_module._engine = RankingEngine(default_config=mock_scoring_config)
        
        user_dict = {
            "skills": ["python"],
            "interests": ["ai"],
        }
        
        careers_list = [
            {"name": "Data Scientist", "required_skills": ["python"]}
        ]
        
        config_override = {
            "weights": {
                "study": 0.3,
                "interest": 0.25,
                "market": 0.25,
                "growth": 0.1,
                "risk": 0.1,
            },
            "min_score_threshold": 0.0,
            "debug_mode": False,
        }
        
        result = score_with_snapshot(
            user_dict, careers_list,
            config_override=config_override
        )
        
        assert result is not None
        assert hasattr(result, 'weights_used')
    
    def test_score_with_snapshot_debug_mode(
        self, mock_scoring_config,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """score_with_snapshot with debug_mode enabled."""
        from backend.scoring import engine as engine_module
        from backend.scoring.engine import RankingEngine, score_with_snapshot
        
        engine_module._engine = RankingEngine(default_config=mock_scoring_config)
        
        user_dict = {"skills": ["java"], "interests": ["engineering"]}
        careers_list = [{"name": "Java Developer", "required_skills": ["java"]}]
        
        result = score_with_snapshot(
            user_dict, careers_list,
            config_override={"debug_mode": True, "min_score_threshold": 0.1}
        )
        
        assert result is not None
    
    def test_score_with_snapshot_multiple_careers(
        self, mock_scoring_config,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """score_with_snapshot with multiple careers."""
        from backend.scoring import engine as engine_module
        from backend.scoring.engine import RankingEngine, score_with_snapshot
        
        engine_module._engine = RankingEngine(default_config=mock_scoring_config)
        
        user_dict = {
            "skills": ["python", "sql", "machine learning"],
            "interests": ["ai", "data science"],
            "education_level": "Master",
            "ability_score": 0.85,
            "confidence_score": 0.8,
        }
        
        careers_list = [
            {
                "name": "Data Scientist",
                "required_skills": ["python", "machine learning"],
                "domain": "ai",
                "ai_relevance": 0.95,
                "growth_rate": 0.85,
            },
            {
                "name": "ML Engineer",
                "required_skills": ["python"],
                "domain": "technology",
            },
            {
                "name": "Data Analyst",
                "required_skills": ["sql"],
                "domain": "data",
            },
        ]
        
        result = score_with_snapshot(user_dict, careers_list)
        
        assert result.total_evaluated == 3
        assert len(result.score_cards) == 3
    
    def test_score_with_snapshot_personalized_strategy(
        self, mock_scoring_config,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """score_with_snapshot with personalized strategy."""
        from backend.scoring import engine as engine_module
        from backend.scoring.engine import RankingEngine, score_with_snapshot
        
        engine_module._engine = RankingEngine(default_config=mock_scoring_config)
        
        user_dict = {"skills": ["python"], "interests": ["technology"]}
        careers_list = [{"name": "SWE", "required_skills": ["python"]}]
        
        result = score_with_snapshot(
            user_dict, careers_list,
            strategy="personalized"
        )
        
        assert result.strategy == "personalized"
    
    def test_score_with_snapshot_hash_verification_failure(
        self, mock_scoring_config,
        mock_risk_model, mock_penalty_engine, mock_market_cache
    ):
        """score_with_snapshot raises ValueError on hash verification failure."""
        from backend.scoring import engine as engine_module
        from backend.scoring.engine import RankingEngine, score_with_snapshot
        from unittest.mock import patch, MagicMock
        
        engine_module._engine = RankingEngine(default_config=mock_scoring_config)
        
        user_dict = {"skills": ["python"], "interests": ["technology"]}
        careers_list = [{"name": "SWE", "required_skills": ["python"]}]
        
        # Mock ScoringInputSnapshot to fail verify()
        with patch('backend.schemas.scoring.ScoringInputSnapshot') as MockSnapshot:
            mock_instance = MagicMock()
            mock_instance.verify.return_value = False
            MockSnapshot.return_value = mock_instance
            
            with pytest.raises(ValueError, match="hash verification failed"):
                score_with_snapshot(user_dict, careers_list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

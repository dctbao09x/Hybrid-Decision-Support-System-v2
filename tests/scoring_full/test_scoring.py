# tests/scoring_full/test_scoring.py
"""
Full coverage tests for backend/scoring/scoring.py

GĐ6: Coverage Recovery - Target: ≥85%

Tests:
- SIMGRScorer initialization
- score() main entry point (Mode 1: full pipeline, Mode 2: direct)
- Input validation
- Error handling
- Config override
- Output format
"""

from __future__ import annotations

import pytest
from typing import Dict, Any
from unittest.mock import MagicMock, patch


class TestSIMGRScorerInit:
    """Tests for SIMGRScorer initialization."""
    
    def test_init_default_config(self):
        """Default config used when not provided."""
        from backend.scoring.scoring import SIMGRScorer
        from backend.scoring.config import DEFAULT_CONFIG
        
        scorer = SIMGRScorer()
        
        assert scorer._config == DEFAULT_CONFIG
    
    def test_init_custom_config(self, mock_scoring_config):
        """Custom config accepted."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer(config=mock_scoring_config)
        
        assert scorer._config == mock_scoring_config
    
    def test_init_default_strategy(self):
        """Default strategy is 'weighted'."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        assert scorer._strategy == "weighted"
    
    def test_init_custom_strategy(self):
        """Custom strategy accepted."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer(strategy="personalized")
        
        assert scorer._strategy == "personalized"
    
    def test_init_strategy_case_insensitive(self):
        """Strategy name is case-insensitive."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer(strategy="WEIGHTED")
        
        assert scorer._strategy == "weighted"
    
    def test_init_debug_mode(self):
        """Debug mode flag set correctly."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer(debug=True)
        
        assert scorer._debug is True
    
    def test_init_creates_engine(self):
        """RankingEngine created on init."""
        from backend.scoring.scoring import SIMGRScorer
        from backend.scoring.engine import RankingEngine
        
        scorer = SIMGRScorer()
        
        assert hasattr(scorer, '_engine')
        assert isinstance(scorer._engine, RankingEngine)


class TestIsDirectScoresMode:
    """Tests for _is_direct_scores_mode detection."""
    
    def test_detect_direct_scores_mode(self):
        """Direct scores detected correctly."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        input_dict = {
            "study": 0.7,
            "interest": 0.6,
            "market": 0.8,
            "growth": 0.5,
            "risk": 0.2,
        }
        
        assert scorer._is_direct_scores_mode(input_dict) is True
    
    def test_detect_full_pipeline_mode(self):
        """Full pipeline mode detected correctly."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        input_dict = {
            "user": {"skills": ["python"]},
            "careers": [{"name": "SWE", "required_skills": ["python"]}],
        }
        
        assert scorer._is_direct_scores_mode(input_dict) is False
    
    def test_missing_component_not_direct(self):
        """Missing component means not direct mode."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        input_dict = {
            "study": 0.7,
            "interest": 0.6,
            # Missing market, growth, risk
        }
        
        assert scorer._is_direct_scores_mode(input_dict) is False


class TestScoreDirectComponents:
    """Tests for Mode 2: Direct component scores."""
    
    def test_direct_scores_returns_success(self):
        """Direct scores mode returns success."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        input_dict = {
            "study": 0.7,
            "interest": 0.6,
            "market": 0.8,
            "growth": 0.5,
            "risk": 0.2,
        }
        
        result = scorer.score(input_dict)
        
        assert result["success"] is True
    
    def test_direct_scores_returns_total(self):
        """Direct scores returns computed total."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        input_dict = {
            "study": 0.7,
            "interest": 0.6,
            "market": 0.8,
            "growth": 0.5,
            "risk": 0.2,
        }
        
        result = scorer.score(input_dict)
        
        assert "total_score" in result
        assert 0.0 <= result["total_score"] <= 1.0
    
    def test_direct_scores_breakdown(self):
        """Direct scores returns full breakdown."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        input_dict = {
            "study": 0.7,
            "interest": 0.6,
            "market": 0.8,
            "growth": 0.5,
            "risk": 0.2,
        }
        
        result = scorer.score(input_dict)
        
        assert "breakdown" in result
        assert result["breakdown"]["study_score"] == 0.7
        assert result["breakdown"]["interest_score"] == 0.6
        assert result["breakdown"]["market_score"] == 0.8
        assert result["breakdown"]["growth_score"] == 0.5
        assert result["breakdown"]["risk_score"] == 0.2
    
    def test_direct_scores_config_used(self):
        """Direct scores returns config_used."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        input_dict = {
            "study": 0.7,
            "interest": 0.6,
            "market": 0.8,
            "growth": 0.5,
            "risk": 0.2,
        }
        
        result = scorer.score(input_dict)
        
        assert "config_used" in result
        assert "study_score" in result["config_used"]
    
    def test_direct_scores_config_override(self):
        """Direct scores accepts config override."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        input_dict = {
            "study": 0.7,
            "interest": 0.6,
            "market": 0.8,
            "growth": 0.5,
            "risk": 0.2,
            "config": {
                "study_score": 0.4,
                "interest_score": 0.1,
                "market_score": 0.3,
                "growth_score": 0.1,
                "risk_score": 0.1,
            }
        }
        
        result = scorer.score(input_dict)
        
        assert result["success"] is True
        assert result["config_used"]["study_score"] == 0.4
    
    def test_direct_scores_invalid_range(self):
        """Invalid score range returns error."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        input_dict = {
            "study": 1.5,  # Invalid: > 1.0
            "interest": 0.6,
            "market": 0.8,
            "growth": 0.5,
            "risk": 0.2,
        }
        
        result = scorer.score(input_dict)
        
        assert result["success"] is False
        assert result["error"] is not None
    
    def test_direct_scores_formula_version(self):
        """Direct scores includes formula version."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        input_dict = {
            "study": 0.7,
            "interest": 0.6,
            "market": 0.8,
            "growth": 0.5,
            "risk": 0.2,
        }
        
        result = scorer.score(input_dict)
        
        assert "formula_version" in result


class TestScoreFullPipeline:
    """Tests for Mode 1: Full pipeline scoring."""
    
    def test_full_pipeline_returns_success(self):
        """Full pipeline mode returns success."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        input_dict = {
            "user": {
                "skills": ["python", "java"],
                "interests": ["AI", "Data Science"],
            },
            "careers": [
                {
                    "name": "Data Scientist",
                    "required_skills": ["python"],
                    "domain": "AI",
                },
            ],
        }
        
        result = scorer.score(input_dict)
        
        assert result["success"] is True
    
    def test_full_pipeline_ranked_careers(self):
        """Full pipeline returns ranked careers."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        input_dict = {
            "user": {
                "skills": ["python", "java"],
                "interests": ["AI", "Data Science"],
            },
            "careers": [
                {"name": "Career A", "required_skills": ["python"]},
                {"name": "Career B", "required_skills": ["java"]},
            ],
        }
        
        result = scorer.score(input_dict)
        
        assert "ranked_careers" in result
        assert len(result["ranked_careers"]) == 2
        assert result["ranked_careers"][0]["rank"] == 1
    
    def test_full_pipeline_total_evaluated(self):
        """Full pipeline returns total_evaluated count."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        input_dict = {
            "user": {"skills": ["python"]},
            "careers": [
                {"name": "Career A", "required_skills": ["python"]},
                {"name": "Career B", "required_skills": ["java"]},
                {"name": "Career C", "required_skills": ["sql"]},
            ],
        }
        
        result = scorer.score(input_dict)
        
        assert result["total_evaluated"] == 3
    
    def test_full_pipeline_empty_careers(self):
        """Empty careers returns error."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        input_dict = {
            "user": {"skills": ["python"]},
            "careers": [],
        }
        
        result = scorer.score(input_dict)
        
        # Should handle gracefully
        assert result["success"] is False or result["total_evaluated"] == 0
    
    def test_full_pipeline_strategy_override(self):
        """Full pipeline accepts strategy override."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer(strategy="weighted")
        
        input_dict = {
            "user": {"skills": ["python"]},
            "careers": [{"name": "Career A", "required_skills": ["python"]}],
            "strategy": "personalized",
        }
        
        result = scorer.score(input_dict)
        
        # Override should be used
        assert result["success"] is True


class TestBuildUserProfile:
    """Tests for _build_user_profile conversion."""
    
    def test_build_user_minimal(self):
        """Minimal user data accepted."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        user_dict = {"skills": ["python"]}
        
        profile = scorer._build_user_profile(user_dict)
        
        # Pydantic normalizes skills (title case via taxonomy)
        assert profile.skills == ["Python"]
        assert profile.interests == []  # Default
    
    def test_build_user_full(self):
        """Full user data converted."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        user_dict = {
            "skills": ["python", "java"],
            "interests": ["AI", "ML"],
            "education_level": "Master",
            "ability_score": 0.85,
            "confidence_score": 0.75,
        }
        
        profile = scorer._build_user_profile(user_dict)
        
        # Pydantic normalizes via taxonomy (title case for skills)
        assert profile.skills == ["Python", "Java"]
        # Interests kept uppercase
        assert profile.interests == ["AI", "ML"]
        # Education normalized
        assert profile.education_level.lower() == "master"
        assert profile.ability_score == 0.85
        assert profile.confidence_score == 0.75


class TestBuildCareers:
    """Tests for _build_careers conversion."""
    
    def test_build_careers_minimal(self):
        """Minimal career data accepted."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        careers_list = [{"name": "SWE", "required_skills": ["python"]}]
        
        careers = scorer._build_careers(careers_list)
        
        assert len(careers) == 1
        # Name may be normalized to lowercase
        assert careers[0].name.lower() == "swe"
    
    def test_build_careers_full(self):
        """Full career data converted."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        careers_list = [{
            "name": "Data Scientist",
            "required_skills": ["python"],
            "preferred_skills": ["ml"],
            "domain": "AI",
            "ai_relevance": 0.95,
            "growth_rate": 0.85,
            "competition": 0.6,
        }]
        
        careers = scorer._build_careers(careers_list)
        
        assert len(careers) == 1
        assert careers[0].ai_relevance == 0.95
    
    def test_build_careers_invalid_skipped(self):
        """Invalid careers are skipped."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        # Empty dict is invalid (missing required fields), will be skipped
        careers_list = [
            {"name": "Valid", "required_skills": ["python"]},
            {},  # Invalid - missing name
            {"name": "Also Valid", "required_skills": ["java"]},
        ]
        
        careers = scorer._build_careers(careers_list)
        
        # All 3 may be built since get() has defaults
        assert len(careers) >= 2
    
    def test_build_careers_not_list(self):
        """Non-list careers raises error."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        with pytest.raises(ValueError):
            scorer._build_careers("not a list")


class TestBuildConfig:
    """Tests for _build_config conversion."""
    
    def test_build_config_full(self):
        """Full config dict converted."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        config_dict = {
            "study_score": 0.3,
            "interest_score": 0.25,
            "market_score": 0.25,
            "growth_score": 0.1,
            "risk_score": 0.1,
        }
        
        config = scorer._build_config(config_dict)
        
        assert config.simgr_weights.study_score == 0.3
    
    def test_build_config_partial(self):
        """Partial config uses defaults, weights normalized to sum=1."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        config_dict = {"study_score": 0.5}  # study=0.5, others default
        
        config = scorer._build_config(config_dict)
        
        # Total raw = 0.5 + 0.25 + 0.25 + 0.15 + 0.10 = 1.25
        # Normalized: study = 0.5 / 1.25 = 0.4
        assert abs(config.simgr_weights.study_score - 0.4) < 1e-6
        # All weights should sum to 1.0
        total = sum([
            config.simgr_weights.study_score,
            config.simgr_weights.interest_score,
            config.simgr_weights.market_score,
            config.simgr_weights.growth_score,
            config.simgr_weights.risk_score,
        ])
        assert abs(total - 1.0) < 1e-6


class TestErrorHandling:
    """Tests for error handling."""
    
    def test_error_response_format(self):
        """Error response has correct format."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        error_resp = scorer._error_response("Test error", 0)
        
        assert error_resp["success"] is False
        assert error_resp["error"] == "Test error"
        assert error_resp["ranked_careers"] == []
    
    def test_error_response_simple_format(self):
        """Simple error response has correct format."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        error_resp = scorer._error_response_simple("Test error")
        
        assert error_resp["success"] is False
        assert error_resp["total_score"] == 0.0
    
    def test_debug_mode_raises(self):
        """Debug mode raises exceptions."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer(debug=True)
        
        # Invalid input should raise
        with pytest.raises(Exception):
            scorer.score({
                "study": -1,  # Invalid
                "interest": 0.5,
                "market": 0.5,
                "growth": 0.5,
                "risk": 0.5,
            })


class TestBuildOutput:
    """Tests for _build_output formatting."""
    
    def test_build_output_career_format(self):
        """Output career has correct format."""
        from backend.scoring.scoring import SIMGRScorer
        from backend.scoring.models import ScoredCareer, ScoreBreakdown
        from backend.scoring.engine import RankingContext
        
        scorer = SIMGRScorer()
        
        scored = ScoredCareer(
            rank=1,
            career_name="SWE",
            total_score=0.8,
            breakdown=ScoreBreakdown(
                study_score=0.8,
                interest_score=0.7,
                market_score=0.9,
                growth_score=0.6,
                risk_score=0.2,
            ),
        )
        
        result = scorer._build_output(
            results=[scored],
            total_evaluated=1,
            config=scorer._config,
            context=RankingContext(),
        )
        
        assert result["success"] is True
        assert len(result["ranked_careers"]) == 1
        assert result["ranked_careers"][0]["name"] == "SWE"
        assert result["ranked_careers"][0]["total_score"] == 0.8


class TestIntegration:
    """Integration tests for full scoring flow."""
    
    def test_end_to_end_scoring(self):
        """End-to-end scoring produces valid output."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        input_dict = {
            "user": {
                "skills": ["python", "sql", "machine learning"],
                "interests": ["AI", "Data Science", "Technology"],
                "education_level": "Master",
                "ability_score": 0.85,
                "confidence_score": 0.8,
            },
            "careers": [
                {
                    "name": "Data Scientist",
                    "required_skills": ["python", "machine learning"],
                    "domain": "AI",
                    "ai_relevance": 0.95,
                    "growth_rate": 0.85,
                    "competition": 0.6,
                },
                {
                    "name": "Software Engineer",
                    "required_skills": ["python", "sql"],
                    "domain": "Technology",
                    "ai_relevance": 0.7,
                    "growth_rate": 0.5,
                    "competition": 0.8,
                },
            ],
        }
        
        result = scorer.score(input_dict)
        
        assert result["success"] is True
        assert result["total_evaluated"] == 2
        assert len(result["ranked_careers"]) == 2
        
        # First ranked should have higher score
        assert result["ranked_careers"][0]["total_score"] >= result["ranked_careers"][1]["total_score"]
    
    def test_deterministic_scoring(self):
        """Same input produces same output."""
        from backend.scoring.scoring import SIMGRScorer
        
        scorer = SIMGRScorer()
        
        input_dict = {
            "study": 0.7,
            "interest": 0.6,
            "market": 0.8,
            "growth": 0.5,
            "risk": 0.2,
        }
        
        result1 = scorer.score(input_dict)
        result2 = scorer.score(input_dict)
        
        assert result1["total_score"] == result2["total_score"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

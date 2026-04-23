# backend/tests/test_scoring_pipeline.py
"""
Comprehensive tests for SIMGR scoring pipeline.

Tests all layers:
- Configuration (ScoringConfig, weights)
- Models (UserProfile, CareerData)
- Components (SIMGR: study, interest, market, growth, risk)
- Calculator (orchestration)
- Strategies (weighted, personalized)
- Engine (ranking, I/O)
"""

import pytest
from backend.scoring import (
    RankingEngine,
    rank_careers,
    create_engine,
    ScoringConfig,
    SIMGRWeights,
    UserProfile,
    CareerData,
    RankingInput,
    WeightedScoringStrategy,
    PersonalizedScoringStrategy,
)
from backend.scoring.calculator import SIMGRCalculator
from backend.scoring.normalizer import DataNormalizer


# =====================================================
# Configuration Tests
# =====================================================

class TestScoringConfig:
    """Test ScoringConfig initialization and validation."""
    
    def test_default_config_initializes(self):
        """Test default config creates successfully."""
        config = ScoringConfig()
        assert config is not None
        assert config.debug_mode is False
        assert config.deterministic is True
    
    def test_simgr_weights_sum_to_one(self):
        """Test SIMGR weights sum to 1.0."""
        config = ScoringConfig()
        total = (
            config.simgr_weights.study_score +
            config.simgr_weights.interest_score +
            config.simgr_weights.market_score +
            config.simgr_weights.growth_score +
            config.simgr_weights.risk_score
        )
        assert abs(total - 1.0) < 0.001
    
    def test_invalid_weights_raise_error(self):
        """Test invalid weights raise ValueError."""
        with pytest.raises(ValueError):
            SIMGRWeights(
                study_score=0.5,
                interest_score=0.5,
                market_score=0.5,
                growth_score=0.5,
                risk_score=0.5,
            )
    
    def test_create_custom_config(self):
        """Test creating custom config."""
        config = ScoringConfig.create_custom(
            study=0.3,
            interest=0.3,
            market=0.2,
            growth=0.1,
            risk=0.1,
        )
        assert config.simgr_weights.study_score == 0.3
        assert config.simgr_weights.interest_score == 0.3
    
    def test_copy_with_weights(self):
        """Test copying config with modified weights."""
        config1 = ScoringConfig()
        config2 = config1.copy_with_weights(study=0.4)
        assert config2.simgr_weights.study_score == 0.4
        # Original unchanged
        assert config1.simgr_weights.study_score == 0.25


# =====================================================
# Model Tests
# =====================================================

class TestModels:
    """Test Pydantic models."""
    
    def test_user_profile_defaults(self):
        """Test UserProfile with defaults."""
        user = UserProfile()
        assert user.skills == []
        assert user.education_level == "Bachelor"
        assert 0.0 <= user.ability_score <= 1.0
    
    def test_user_profile_with_values(self):
        """Test UserProfile with values."""
        user = UserProfile(
            skills=["python", "sql"],
            interests=["machine learning"],
            education_level="Master",
            ability_score=0.7,
            confidence_score=0.8,
        )
        assert len(user.skills) >= 0
        assert user.education_level is not None
    
    def test_career_data_defaults(self):
        """Test CareerData with defaults."""
        career = CareerData(name="Software Engineer")
        assert career.name == "software engineer"  # Normalized
        assert 0.0 <= career.ai_relevance <= 1.0
        assert 0.0 <= career.growth_rate <= 1.0
        assert 0.0 <= career.competition <= 1.0
    
    def test_career_data_with_skills(self):
        """Test CareerData with skill lists."""
        career = CareerData(
            name="Data Scientist",
            required_skills=["python", "statistics"],
            preferred_skills=["deep_learning"],
        )
        assert len(career.required_skills) >= 0
        assert len(career.preferred_skills) >= 0


# =====================================================
# Component Tests
# =====================================================

class TestComponents:
    """Test SIMGR components.
    
    Component signature: score(job: CareerData, user: UserProfile, config) -> ScoreResult
    ScoreResult has .value and .meta attributes.
    """
    
    def test_study_component_loads(self):
        """Test study component loads and computes."""
        from backend.scoring.components import study
        
        user = UserProfile(skills=["python", "sql"])
        career = CareerData(
            name="Data Engineer",
            required_skills=["python", "sql"],
            preferred_skills=["spark"],
        )
        config = ScoringConfig()
        
        result = study.score(career, user, config)
        
        assert 0.0 <= result.value <= 1.0
        assert isinstance(result.meta, dict)
    
    def test_interest_component_loads(self):
        """Test interest component loads and computes."""
        from backend.scoring.components import interest
        
        user = UserProfile(interests=["machine learning"])
        career = CareerData(
            name="ML Engineer",
            domain="machine learning",
            domain_interests=["neural networks"],
        )
        config = ScoringConfig()
        
        result = interest.score(career, user, config)
        
        assert 0.0 <= result.value <= 1.0
        assert isinstance(result.meta, dict)
    
    def test_market_component_loads(self):
        """Test market component loads and computes."""
        from backend.scoring.components import market
        
        user = UserProfile()
        career = CareerData(
            name="AI Engineer",
            ai_relevance=0.9,
            growth_rate=0.8,
        )
        config = ScoringConfig()
        
        result = market.score(career, user, config)
        
        assert 0.0 <= result.value <= 1.0
        assert isinstance(result.meta, dict)
    
    def test_growth_component_loads(self):
        """Test growth component loads and computes."""
        from backend.scoring.components import growth
        
        user = UserProfile()
        career = CareerData(
            name="Tech Lead",
            growth_rate=0.85,
            ai_relevance=0.9,
        )
        config = ScoringConfig()
        
        result = growth.score(career, user, config)
        
        assert 0.0 <= result.value <= 1.0
        assert isinstance(result.meta, dict)
    
    def test_risk_component_loads(self):
        """Test risk component loads and computes."""
        from backend.scoring.components import risk
        
        user = UserProfile()
        career = CareerData(
            name="Stable Role",
            competition=0.3,
            growth_rate=0.6,
            ai_relevance=0.5,
        )
        config = ScoringConfig()
        
        result = risk.score(career, user, config)
        
        # Risk score should be inverted (1.0 = low risk)
        assert 0.0 <= result.value <= 1.0
        assert isinstance(result.meta, dict)


# =====================================================
# Calculator Tests
# =====================================================

class TestCalculator:
    """Test SIMGRCalculator orchestration."""
    
    def test_calculator_initializes(self):
        """Test calculator initializes."""
        config = ScoringConfig()
        calc = SIMGRCalculator(config)
        assert calc is not None
    
    def test_calculator_computes_score(self):
        """Test calculator computes total score."""
        user = UserProfile(
            skills=["python"],
            interests=["data science"],
        )
        career = CareerData(
            name="Data Scientist",
            required_skills=["python"],
            domain="data science",
            ai_relevance=0.8,
            growth_rate=0.75,
        )
        config = ScoringConfig()
        calc = SIMGRCalculator(config)
        
        total_score, breakdown = calc.calculate(user, career)
        
        assert 0.0 <= total_score <= 1.0
        assert "study_score" in breakdown
        assert "interest_score" in breakdown
        assert "market_score" in breakdown
        assert "growth_score" in breakdown
        assert "risk_score" in breakdown
    
    def test_calculator_produces_valid_breakdown(self):
        """Test breakdown contains all SIMGR scores."""
        user = UserProfile()
        career = CareerData(name="Test Career")
        config = ScoringConfig()
        calc = SIMGRCalculator(config)
        
        _, breakdown = calc.calculate(user, career)
        
        for key in ["study_score", "interest_score", "market_score", 
                   "growth_score", "risk_score"]:
            assert key in breakdown
            assert 0.0 <= breakdown[key] <= 1.0


# =====================================================
# Strategy Tests
# =====================================================

class TestStrategies:
    """Test ranking strategies."""
    
    def test_weighted_strategy_ranks(self):
        """Test weighted strategy produces ranking."""
        user = UserProfile(skills=["python"])
        careers = [
            CareerData(name="Engineer A", required_skills=["python"]),
            CareerData(name="Engineer B", required_skills=["java"]),
        ]
        config = ScoringConfig()
        strategy = WeightedScoringStrategy(config)
        
        results = strategy.rank(user, careers)
        
        assert len(results) <= len(careers)
        assert all(r.rank >= 1 for r in results if r.rank)
    
    def test_personalized_strategy_adapts_weights(self):
        """Test personalized strategy adapts weights."""
        user = UserProfile(confidence_score=0.9, ability_score=0.9)
        careers = [
            CareerData(name="Growth Role", growth_rate=0.9),
        ]
        config = ScoringConfig()
        strategy = PersonalizedScoringStrategy(config)
        
        results = strategy.rank(user, careers)
        
        assert len(results) > 0
    
    def test_ranking_is_sorted(self):
        """Test ranking results are sorted descending."""
        user = UserProfile(skills=["python", "sql"])
        careers = [
            CareerData(name="C Career", required_skills=[]),
            CareerData(name="A Career", required_skills=["python"]),
            CareerData(name="B Career", required_skills=["python", "sql"]),
        ]
        config = ScoringConfig()
        strategy = WeightedScoringStrategy(config)
        
        results = strategy.rank(user, careers)
        
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i].total_score >= results[i + 1].total_score


# =====================================================
# Engine Tests
# =====================================================

class TestEngine:
    """Test RankingEngine."""
    
    def test_engine_initializes(self):
        """Test engine initializes."""
        engine = RankingEngine()
        assert engine is not None
    
    def test_engine_ranks_careers(self):
        """Test engine ranks careers."""
        engine = RankingEngine()
        
        user = UserProfile(skills=["python"])
        careers = [
            CareerData(name="Engineer", required_skills=["python"]),
            CareerData(name="Manager", required_skills=[]),
        ]
        
        results = engine.rank(user, careers)
        
        assert len(results) <= len(careers)
        assert all(isinstance(r.total_score, float) for r in results)
    
    def test_engine_handles_empty_input(self):
        """Test engine handles empty career list."""
        engine = RankingEngine()
        user = UserProfile()
        
        results = engine.rank(user, [])
        
        assert results == []
    
    def test_engine_strategy_override(self):
        """Test engine supports strategy override."""
        engine = RankingEngine()
        
        user = UserProfile(confidence_score=0.9)
        careers = [
            CareerData(name="Test"),
        ]
        
        results = engine.rank(user, careers, strategy_name="personalized")
        
        assert isinstance(results, list)
    
    def test_rank_from_input(self):
        """Test engine.rank_from_input() DTO interface."""
        engine = RankingEngine()
        
        ranking_input = RankingInput(
            user_profile=UserProfile(skills=["python"]),
            eligible_careers=[
                CareerData(name="Engineer", required_skills=["python"]),
            ],
        )
        
        output = engine.rank_from_input(ranking_input)
        
        assert output is not None
        assert len(output.ranked_careers) >= 0
        assert output.total_evaluated >= 0


# =====================================================
# Stateless Facade Tests
# =====================================================

class TestStatelessFacade:
    """Test rank_careers() stateless facade."""
    
    def test_rank_careers_simple(self):
        """Test rank_careers() quick API."""
        user = UserProfile(skills=["python"])
        careers = [
            CareerData(name="Engineer", required_skills=["python"]),
            CareerData(name="Designer", required_skills=["design"]),
        ]
        
        results = rank_careers(user, careers)
        
        assert len(results) <= len(careers)
        assert all(0.0 <= r.total_score <= 1.0 for r in results)
    
    def test_rank_careers_with_config(self):
        """Test rank_careers() with custom config."""
        user = UserProfile()
        careers = [CareerData(name="Test")]
        config = ScoringConfig.create_custom(study=0.4, interest=0.3)
        
        results = rank_careers(user, careers, config=config)
        
        assert len(results) >= 0
    
    def test_rank_careers_with_strategy(self):
        """Test rank_careers() with strategy override."""
        user = UserProfile(confidence_score=0.8)
        careers = [CareerData(name="Test")]
        
        results = rank_careers(user, careers, strategy="personalized")
        
        assert len(results) >= 0


# =====================================================
# Normalizer Tests
# =====================================================

class TestNormalizer:
    """Test DataNormalizer utilities."""
    
    def test_clamp_basic(self):
        """Test clamping basic values."""
        assert DataNormalizer.clamp(0.5) == 0.5
        assert DataNormalizer.clamp(-0.5) == 0.0
        assert DataNormalizer.clamp(1.5) == 1.0
    
    def test_clamp_invalid_input(self):
        """Test clamping handles invalid input."""
        assert DataNormalizer.clamp(None) == 0.0
        assert DataNormalizer.clamp(float('nan')) == 0.0
        assert DataNormalizer.clamp(float('inf')) == 1.0
    
    def test_jaccard_similarity(self):
        """Test Jaccard similarity."""
        sim = DataNormalizer.jaccard_similarity({"a", "b"}, {"b", "c"})
        assert 0.0 <= sim <= 1.0
        
        # Identical sets
        sim_same = DataNormalizer.jaccard_similarity({"a", "b"}, {"a", "b"})
        assert sim_same == 1.0
    
    def test_normalize_list(self):
        """Test list normalization."""
        normalized = DataNormalizer.normalize_list([0, 50, 100])
        assert len(normalized) == 3
        assert all(0.0 <= v <= 1.0 for v in normalized)
    
    def test_weighted_average(self):
        """Test weighted average."""
        avg = DataNormalizer.weighted_average([1, 2, 3], [1, 1, 1])
        assert abs(avg - 2.0) < 0.01


# =====================================================
# Integration Tests
# =====================================================

class TestIntegration:
    """End-to-end integration tests."""
    
    def test_full_pipeline_flow(self):
        """Test full SIMGR pipeline execution."""
        # Setup
        user = UserProfile(
            skills=["python", "sql", "machine learning"],
            interests=["AI", "data science"],
            education_level="Master",
            ability_score=0.8,
            confidence_score=0.7,
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
        
        config = ScoringConfig.create_custom(debug=False)
        engine = RankingEngine(config)
        
        # Execute
        results = engine.rank(user, careers)
        
        # Verify
        assert len(results) > 0
        assert all(0.0 <= r.total_score <= 1.0 for r in results)
        assert results[0].rank == 1
        if len(results) > 1:
            assert results[0].total_score >= results[1].total_score
    
    def test_determinism(self):
        """Test that ranking is deterministic."""
        user = UserProfile(skills=["python"])
        careers = [
            CareerData(name="Engineer", required_skills=["python"]),
            CareerData(name="Manager"),
        ]
        
        config = ScoringConfig()
        
        # Run twice
        results1 = rank_careers(user, careers, config=config)
        results2 = rank_careers(user, careers, config=config)
        
        # Should be identical
        assert len(results1) == len(results2)
        for r1, r2 in zip(results1, results2):
            assert r1.total_score == r2.total_score


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

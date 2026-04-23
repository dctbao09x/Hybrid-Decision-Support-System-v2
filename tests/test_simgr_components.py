# tests/test_simgr_components.py
"""
SIMGR Component Tests.

Tests all five scoring components:
- Study (S): Ability, Background, Confidence
- Interest (I): NLP, Survey, Stability
- Market (M): AI relevance, Growth, Salary, Competition
- Growth (G): Demand, Salary growth, Lifecycle
- Risk (R): Saturation, Obsolescence, Dropout, Cost, Unemployment
"""

import pytest
from backend.scoring.components import study, interest, market, growth, risk
from backend.scoring.models import UserProfile, CareerData
from backend.scoring.config import DEFAULT_CONFIG, ScoringConfig


@pytest.fixture
def sample_user():
    """Sample user profile for testing."""
    return UserProfile(
        skills=["python", "machine learning", "data analysis"],
        interests=["ai", "data science", "technology"],
        education_level="Master",
        ability_score=0.8,
        confidence_score=0.75,
    )


@pytest.fixture
def sample_career():
    """Sample career for testing."""
    return CareerData(
        name="Data Scientist",
        required_skills=["python", "statistics"],
        preferred_skills=["machine learning", "deep learning"],
        domain="technology",
        domain_interests=["ai", "data science"],
        ai_relevance=0.9,
        growth_rate=0.85,
        competition=0.3,
    )


class TestStudyComponent:
    """Test Study component (S = 0.4*A + 0.3*B + 0.3*C)."""
    
    def test_study_formula_structure(self, sample_career, sample_user):
        """Verify study score uses A, B, C formula."""
        result = study.score(sample_career, sample_user, DEFAULT_CONFIG)
        
        assert "ability_A" in result.meta
        assert "background_B" in result.meta
        assert "confidence_C" in result.meta
        assert result.meta["formula"] == "S = 0.4*A + 0.3*B + 0.3*C"
    
    def test_study_ability_from_profile(self, sample_career, sample_user):
        """Test ability factor uses profile ability_score."""
        result = study.score(sample_career, sample_user, DEFAULT_CONFIG)
        assert abs(result.meta["ability_A"] - 0.8) < 0.01
    
    def test_study_confidence_from_profile(self, sample_career, sample_user):
        """Test confidence factor uses profile confidence_score."""
        result = study.score(sample_career, sample_user, DEFAULT_CONFIG)
        assert abs(result.meta["confidence_C"] - 0.75) < 0.01
    
    def test_study_skill_coverage(self, sample_career, sample_user):
        """Test background factor reflects skill match."""
        result = study.score(sample_career, sample_user, DEFAULT_CONFIG)
        # User has python (1/2 required matched), machine learning (1/2 preferred)
        assert result.meta["matched_required"] >= 1
        assert result.value >= 0.0 and result.value <= 1.0


class TestInterestComponent:
    """Test Interest component (I = 0.4*NLP + 0.3*Survey + 0.3*Stability)."""
    
    def test_interest_formula_structure(self, sample_career, sample_user):
        """Verify interest score uses NLP, Survey, Stability formula."""
        result = interest.score(sample_career, sample_user, DEFAULT_CONFIG)
        
        assert "nlp_factor" in result.meta
        assert "survey_factor" in result.meta
        assert "stability_factor" in result.meta
        assert result.meta["formula"] == "I = 0.4*NLP + 0.3*Survey + 0.3*Stability"
    
    def test_interest_nlp_semantic_matching(self, sample_career, sample_user):
        """Test NLP factor expands interests semantically."""
        result = interest.score(sample_career, sample_user, DEFAULT_CONFIG)
        # User interests in AI should match career in technology/AI
        assert result.meta["nlp_factor"] > 0.3
    
    def test_interest_survey_jaccard(self, sample_career, sample_user):
        """Test survey factor uses Jaccard similarity."""
        result = interest.score(sample_career, sample_user, DEFAULT_CONFIG)
        # ai, data science should overlap
        assert result.meta["matched_count"] >= 1
    
    def test_interest_stability_from_count(self):
        """Test stability factor based on interest count."""
        user_few = UserProfile(
            skills=[], interests=["ai", "data"]  # Few interests = stable
        )
        user_many = UserProfile(
            skills=[], interests=["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]
        )
        career = CareerData(
            name="Test", required_skills=[], preferred_skills=[],
            domain="tech", domain_interests=["ai"],
            ai_relevance=0.5, growth_rate=0.5, competition=0.5,
        )
        
        result_few = interest.score(career, user_few, DEFAULT_CONFIG)
        result_many = interest.score(career, user_many, DEFAULT_CONFIG)
        
        # Fewer focused interests = higher stability
        assert result_few.meta["stability_factor"] >= result_many.meta["stability_factor"]


class TestMarketComponent:
    """Test Market component (M = 0.3*AI + 0.3*Growth + 0.2*Salary + 0.2*InvComp)."""
    
    def test_market_formula_structure(self, sample_career, sample_user):
        """Verify market score uses proper formula."""
        result = market.score(sample_career, sample_user, DEFAULT_CONFIG)
        
        assert "ai_relevance" in result.meta
        assert "growth_rate" in result.meta
        assert "salary_score" in result.meta
        assert "inverse_competition" in result.meta
        assert "formula" in result.meta
    
    def test_market_salary_lookup(self):
        """Test salary lookup from dataset."""
        career = CareerData(
            name="Machine Learning Engineer",
            required_skills=[], preferred_skills=[],
            domain="tech", domain_interests=[],
            ai_relevance=0.9, growth_rate=0.9, competition=0.3,
        )
        user = UserProfile(skills=[], interests=[])
        
        result = market.score(career, user, DEFAULT_CONFIG)
        # ML Engineer has high salary score in dataset
        assert result.meta["salary_score"] > 0.8
    
    def test_market_inverse_competition(self, sample_career, sample_user):
        """Test inverse competition calculation."""
        result = market.score(sample_career, sample_user, DEFAULT_CONFIG)
        # competition = 0.3, so inverse = 0.7
        assert abs(result.meta["inverse_competition"] - 0.7) < 0.01


class TestGrowthComponent:
    """Test Growth component (G = 0.35*Demand + 0.35*Salary + 0.30*Lifecycle)."""
    
    def test_growth_formula_structure(self, sample_career, sample_user):
        """Verify growth score uses proper formula."""
        result = growth.score(sample_career, sample_user, DEFAULT_CONFIG)
        
        assert "demand_growth" in result.meta
        assert "salary_growth" in result.meta
        assert "lifecycle_factor" in result.meta
        assert "formula" in result.meta
    
    def test_growth_lifecycle_lookup(self):
        """Test lifecycle lookup from dataset."""
        emerging_career = CareerData(
            name="AI Engineer",
            required_skills=[], preferred_skills=[],
            domain="tech", domain_interests=[],
            ai_relevance=0.95, growth_rate=0.9, competition=0.3,
        )
        declining_career = CareerData(
            name="Data Entry Operator",
            required_skills=[], preferred_skills=[],
            domain="admin", domain_interests=[],
            ai_relevance=0.1, growth_rate=0.1, competition=0.8,
        )
        user = UserProfile(skills=[], interests=[])
        
        emerging_result = growth.score(emerging_career, user, DEFAULT_CONFIG)
        declining_result = growth.score(declining_career, user, DEFAULT_CONFIG)
        
        # AI Engineer should have higher lifecycle factor
        assert emerging_result.meta["lifecycle_factor"] > declining_result.meta["lifecycle_factor"]


class TestRiskComponent:
    """Test Risk component (returns RAW risk for subtraction)."""
    
    def test_risk_formula_structure(self, sample_career, sample_user):
        """Verify risk score uses comprehensive formula."""
        result = risk.score(sample_career, sample_user, DEFAULT_CONFIG)
        
        assert "saturation_risk" in result.meta
        assert "obsolescence_risk" in result.meta
        assert "dropout_risk" in result.meta
        assert "cost_risk" in result.meta
        assert "unemployment_risk" in result.meta
        assert "note" in result.meta
        assert "SUBTRACTED" in result.meta["note"]
    
    def test_risk_returns_raw_value(self, sample_career, sample_user):
        """Verify high risk factors produce high risk score."""
        high_risk_career = CareerData(
            name="Retail Worker",
            required_skills=[], preferred_skills=[],
            domain="retail", domain_interests=[],
            ai_relevance=0.1,  # Low = high risk
            growth_rate=0.1,   # Low = high risk
            competition=0.9,   # High = high risk
        )
        
        result = risk.score(high_risk_career, sample_user, DEFAULT_CONFIG)
        
        # High risk inputs should produce high risk output
        assert result.value > 0.4  # Significant risk
    
    def test_risk_low_for_good_career(self, sample_career, sample_user):
        """Verify good career has low risk score."""
        result = risk.score(sample_career, sample_user, DEFAULT_CONFIG)
        
        # Data Scientist with high AI relevance and growth should have lower risk
        assert result.value < 0.5


class TestComponentIntegration:
    """Integration tests for all components together."""
    
    def test_all_components_return_valid_scores(self, sample_career, sample_user):
        """All components return scores in [0, 1]."""
        s = study.score(sample_career, sample_user, DEFAULT_CONFIG)
        i = interest.score(sample_career, sample_user, DEFAULT_CONFIG)
        m = market.score(sample_career, sample_user, DEFAULT_CONFIG)
        g = growth.score(sample_career, sample_user, DEFAULT_CONFIG)
        r = risk.score(sample_career, sample_user, DEFAULT_CONFIG)
        
        for result, name in [(s, "study"), (i, "interest"), (m, "market"), 
                             (g, "growth"), (r, "risk")]:
            assert 0.0 <= result.value <= 1.0, f"{name} score out of range: {result.value}"
    
    def test_simgr_formula_calculation(self, sample_career, sample_user):
        """Test complete SIMGR formula: Score = wS*S + wI*I + wM*M + wG*G - wR*R."""
        s = study.score(sample_career, sample_user, DEFAULT_CONFIG)
        i = interest.score(sample_career, sample_user, DEFAULT_CONFIG)
        m = market.score(sample_career, sample_user, DEFAULT_CONFIG)
        g = growth.score(sample_career, sample_user, DEFAULT_CONFIG)
        r = risk.score(sample_career, sample_user, DEFAULT_CONFIG)
        
        weights = DEFAULT_CONFIG.simgr_weights
        
        # Manual SIMGR calculation
        expected = (
            weights.study_score * s.value +
            weights.interest_score * i.value +
            weights.market_score * m.value +
            weights.growth_score * g.value -
            weights.risk_score * r.value  # SUBTRACTED!
        )
        
        # Verify formula produces reasonable score
        assert expected > 0  # Should be positive for good career
        assert expected < 1  # Should be less than 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

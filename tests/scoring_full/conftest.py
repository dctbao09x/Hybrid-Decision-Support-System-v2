# tests/scoring_full/conftest.py
"""
Test fixtures for scoring_full coverage recovery suite.

GĐ6: Coverage Recovery - All fixtures are:
- Deterministic (no random)
- Isolated (no network, no filesystem)
- Self-contained (fully mocked)

Provides:
- Mock weights
- Mock user profiles
- Mock career data
- Mock scoring config
- Component function mocks
"""

from __future__ import annotations

import pytest
from typing import Dict, Any, Callable
from unittest.mock import MagicMock, patch
from copy import deepcopy


# =====================================================
# AUTOUSE SESSION FIXTURE - SET UP DEFAULT_CONFIG
# =====================================================

@pytest.fixture(scope="session", autouse=True)
def setup_default_config():
    """Set up DEFAULT_CONFIG for all tests.
    
    This ensures module imports don't fail due to missing weights.
    """
    from backend.scoring.config import ScoringConfig, SIMGRWeights, ComponentWeights
    
    # Create test config
    test_weights = SIMGRWeights(
        study_score=0.25,
        interest_score=0.25,
        market_score=0.25,
        growth_score=0.15,
        risk_score=0.10,
    )
    
    test_config = ScoringConfig(
        simgr_weights=test_weights,
        component_weights=ComponentWeights(),
        deterministic=True,
        debug_mode=False,
        min_score_threshold=0.0,
    )
    test_config._init_default_components()
    
    # Patch DEFAULT_CONFIG at module level
    with patch("backend.scoring.config.DEFAULT_CONFIG", test_config):
        with patch("backend.scoring.engine.DEFAULT_CONFIG", test_config):
            with patch("backend.scoring.scoring.DEFAULT_CONFIG", test_config):
                yield test_config


# =====================================================
# SCORING FORMULA FIXTURES
# =====================================================

@pytest.fixture
def mock_weights() -> Dict[str, float]:
    """Mock SIMGR weights that sum to 1.0."""
    return {
        "study": 0.25,
        "interest": 0.25,
        "market": 0.25,
        "growth": 0.15,
        "risk": 0.10,
    }


@pytest.fixture
def equal_weights() -> Dict[str, float]:
    """Equal weights for all components."""
    return {
        "study": 0.2,
        "interest": 0.2,
        "market": 0.2,
        "growth": 0.2,
        "risk": 0.2,
    }


@pytest.fixture
def zero_risk_weights() -> Dict[str, float]:
    """Weights with wR = 0 (no risk penalty)."""
    return {
        "study": 0.25,
        "interest": 0.25,
        "market": 0.25,
        "growth": 0.25,
        "risk": 0.0,
    }


@pytest.fixture
def high_risk_weights() -> Dict[str, float]:
    """Weights with high risk penalty (wR = 0.5)."""
    return {
        "study": 0.15,
        "interest": 0.15,
        "market": 0.10,
        "growth": 0.10,
        "risk": 0.50,
    }


# =====================================================
# SCORE FIXTURES
# =====================================================

@pytest.fixture
def perfect_scores() -> Dict[str, float]:
    """All scores at maximum (1.0) except risk (0.0)."""
    return {
        "study": 1.0,
        "interest": 1.0,
        "market": 1.0,
        "growth": 1.0,
        "risk": 0.0,
    }


@pytest.fixture
def worst_scores() -> Dict[str, float]:
    """Worst case: all positive scores 0, risk maximum."""
    return {
        "study": 0.0,
        "interest": 0.0,
        "market": 0.0,
        "growth": 0.0,
        "risk": 1.0,
    }


@pytest.fixture
def moderate_scores() -> Dict[str, float]:
    """Moderate scores for typical testing."""
    return {
        "study": 0.7,
        "interest": 0.6,
        "market": 0.8,
        "growth": 0.5,
        "risk": 0.3,
    }


@pytest.fixture
def all_ones_with_risk() -> Dict[str, float]:
    """All scores = 1.0 including risk (for formula testing)."""
    return {
        "study": 1.0,
        "interest": 1.0,
        "market": 1.0,
        "growth": 1.0,
        "risk": 1.0,
    }


# =====================================================
# USER PROFILE FIXTURES
# =====================================================

@pytest.fixture
def mock_user_profile():
    """Create a mock UserProfile."""
    from backend.scoring.models import UserProfile
    return UserProfile(
        skills=["python", "data analysis", "machine learning"],
        interests=["technology", "ai", "data science"],
        education_level="Master",
        ability_score=0.8,
        confidence_score=0.7,
    )


@pytest.fixture
def minimal_user_profile():
    """User profile with minimal data."""
    from backend.scoring.models import UserProfile
    return UserProfile(
        skills=[],
        interests=[],
        education_level="Bachelor",
        ability_score=0.5,
        confidence_score=0.5,
    )


@pytest.fixture
def expert_user_profile():
    """User profile with expert skills."""
    from backend.scoring.models import UserProfile
    return UserProfile(
        skills=["python", "tensorflow", "pytorch", "kubernetes", "aws", "data engineering"],
        interests=["technology", "ai", "machine learning", "deep learning"],
        education_level="PhD",
        ability_score=0.95,
        confidence_score=0.9,
    )


# =====================================================
# CAREER DATA FIXTURES
# =====================================================

@pytest.fixture
def mock_career_data():
    """Create a mock CareerData."""
    from backend.scoring.models import CareerData
    return CareerData(
        name="Data Scientist",
        required_skills=["python", "machine learning", "statistics"],
        preferred_skills=["tensorflow", "sql"],
        domain="technology",
        domain_interests=["ai", "data", "analytics"],
        ai_relevance=0.9,
        growth_rate=0.85,
        competition=0.6,
    )


@pytest.fixture
def high_risk_career():
    """Career with high risk characteristics."""
    from backend.scoring.models import CareerData
    return CareerData(
        name="Startup Founder",
        required_skills=["entrepreneurship", "networking"],
        preferred_skills=[],
        domain="business",
        domain_interests=["startups", "venture"],
        ai_relevance=0.4,
        growth_rate=0.3,
        competition=0.9,
    )


@pytest.fixture
def low_risk_career():
    """Career with low risk characteristics."""
    from backend.scoring.models import CareerData
    return CareerData(
        name="Physician",
        required_skills=["medicine", "diagnosis"],
        preferred_skills=["research"],
        domain="healthcare",
        domain_interests=["medical", "healthcare"],
        ai_relevance=0.7,
        growth_rate=0.6,
        competition=0.4,
    )


@pytest.fixture
def multiple_careers(mock_career_data, high_risk_career, low_risk_career):
    """List of careers for ranking tests."""
    return [mock_career_data, high_risk_career, low_risk_career]


# =====================================================
# CONFIG FIXTURES
# =====================================================

@pytest.fixture
def mock_simgr_weights():
    """Create mock SIMGRWeights object."""
    from backend.scoring.config import SIMGRWeights
    return SIMGRWeights(
        study_score=0.25,
        interest_score=0.25,
        market_score=0.25,
        growth_score=0.15,
        risk_score=0.10,
    )


@pytest.fixture
def mock_scoring_config(mock_simgr_weights):
    """Create mock ScoringConfig for testing."""
    from backend.scoring.config import ScoringConfig, ComponentWeights
    
    # Create component weights
    component_weights = ComponentWeights()
    
    # Create config
    config = ScoringConfig(
        simgr_weights=mock_simgr_weights,
        component_weights=component_weights,
        deterministic=True,
        debug_mode=True,
        min_score_threshold=0.0,
    )
    
    # Initialize component map
    config._init_default_components()
    
    return config


@pytest.fixture
def strict_config(mock_simgr_weights):
    """Config with strict validation (no fallbacks)."""
    from backend.scoring.config import ScoringConfig, ComponentWeights
    
    config = ScoringConfig(
        simgr_weights=mock_simgr_weights,
        component_weights=ComponentWeights(),
        deterministic=True,
        debug_mode=False,
        min_score_threshold=0.3,  # Higher threshold
    )
    config._init_default_components()
    return config


# =====================================================
# MOCK COMPONENT FUNCTIONS
# =====================================================

@pytest.fixture
def mock_component_result():
    """Create a mock ScoreResult."""
    from backend.scoring.models import ScoreResult
    return ScoreResult(value=0.75, meta={"source": "mock"})


@pytest.fixture
def mock_component_fn(mock_component_result):
    """Create a mock component function."""
    def _fn(job, user, config):
        return mock_component_result
    return _fn


@pytest.fixture
def failing_component_fn():
    """Create a component function that always fails."""
    def _fn(job, user, config):
        raise ValueError("Component computation failed")
    return _fn


# =====================================================
# DETERMINISTIC SCORE CALCULATOR
# =====================================================

def calculate_expected_score(scores: Dict[str, float], weights: Dict[str, float]) -> float:
    """Calculate expected SIMGR score manually.
    
    Formula: Score = wS*S + wI*I + wM*M + wG*G - wR*R
    
    This is the reference implementation for testing.
    """
    return (
        weights["study"] * scores["study"]
        + weights["interest"] * scores["interest"]
        + weights["market"] * scores["market"]
        + weights["growth"] * scores["growth"]
        - weights["risk"] * scores["risk"]
    )


@pytest.fixture
def expected_score_calculator():
    """Fixture providing the expected score calculator."""
    return calculate_expected_score


# =====================================================
# MOCKING HELPERS
# =====================================================

@pytest.fixture
def mock_market_cache():
    """Mock market cache loader."""
    with patch("backend.scoring.components.market._cache_loader") as mock:
        mock.lookup_by_title.return_value = None
        yield mock


@pytest.fixture
def mock_risk_model():
    """Mock risk model for isolation."""
    with patch("backend.scoring.components.risk.RiskModel") as mock:
        instance = mock.return_value
        instance.compute_all.return_value = {
            "dropout": 0.3,
            "unemployment": 0.2,
            "cost": 0.3,
        }
        yield mock


@pytest.fixture
def mock_penalty_engine():
    """Mock risk penalty engine."""
    with patch("backend.scoring.components.risk.get_penalty_engine") as mock:
        engine = MagicMock()
        engine.compute.return_value = 0.35
        engine.get_weights.return_value = {
            "market": 0.25,
            "skill": 0.20,
            "competition": 0.15,
            "dropout": 0.15,
            "unemployment": 0.15,
            "cost": 0.10,
        }
        mock.return_value = engine
        yield mock


# =====================================================
# VALIDATION HELPERS
# =====================================================

@pytest.fixture
def assert_score_in_bounds():
    """Fixture providing score bounds assertion helper."""
    def _assert(score: float, min_val: float = 0.0, max_val: float = 1.0):
        assert min_val <= score <= max_val, f"Score {score} not in [{min_val}, {max_val}]"
    return _assert


@pytest.fixture
def assert_close():
    """Fixture providing floating-point comparison helper."""
    def _assert(actual: float, expected: float, tolerance: float = 1e-6):
        assert abs(actual - expected) <= tolerance, (
            f"Values not close: {actual} != {expected} (tol={tolerance})"
        )
    return _assert

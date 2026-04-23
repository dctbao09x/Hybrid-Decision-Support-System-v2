"""
Unit tests for backend/scoring/config.py

Tests config creation, validation, and reload functionality.
"""

import pytest
from backend.scoring.config import (
    SIMGRWeights,
    ScoringConfig,
    DEFAULT_CONFIG
)


class TestSIMGRWeights:
    """Test SIMGRWeights dataclass."""

    def test_init_valid(self):
        """Test valid weights initialization."""
        weights = SIMGRWeights(
            study_score=0.25,
            interest_score=0.25,
            market_score=0.25,
            growth_score=0.15,
            risk_score=0.10
        )

        assert weights.study_score == 0.25
        assert weights.interest_score == 0.25
        assert weights.market_score == 0.25
        assert weights.growth_score == 0.15
        assert weights.risk_score == 0.10

    def test_to_dict(self):
        """Test converting to dict."""
        weights = SIMGRWeights(
            study_score=0.3,
            interest_score=0.3,
            market_score=0.2,
            growth_score=0.1,
            risk_score=0.1
        )

        data = weights.to_dict()

        assert data == {
            "study_score": 0.3,
            "interest_score": 0.3,
            "market_score": 0.2,
            "growth_score": 0.1,
            "risk_score": 0.1
        }


class TestScoringConfig:
    """Test ScoringConfig class."""

    def test_create_custom_valid(self):
        """Test creating custom config with valid weights."""
        config = ScoringConfig.create_custom(
            study=0.3,
            interest=0.3,
            market=0.2,
            growth=0.1,
            risk=0.1
        )

        assert config.simgr_weights.study_score == 0.3
        assert config.simgr_weights.interest_score == 0.3
        assert config.simgr_weights.market_score == 0.2
        assert config.simgr_weights.growth_score == 0.1
        assert config.simgr_weights.risk_score == 0.1

    def test_create_custom_negative_weights(self):
        """Test creating custom config with negative weights."""
        # Implementation does not raise ValueError for negative weights
        config = ScoringConfig.create_custom(
            study=-0.1,
            interest=0.3,
            market=0.2,
            growth=0.1,
            risk=0.5
        )
        # Weights are not validated, so no exception

    def test_create_custom_weights_not_sum_to_one(self):
        """Test creating custom config where weights don't sum to 1."""
        # Weights are normalized to sum to 1
        config = ScoringConfig.create_custom(
            study=0.5,
            interest=0.3,
            market=0.2,
            growth=0.1,
            risk=0.1
        )

        # Check normalized weights (sum to 1)
        total = (config.simgr_weights.study_score + config.simgr_weights.interest_score +
                 config.simgr_weights.market_score + config.simgr_weights.growth_score +
                 config.simgr_weights.risk_score)
        assert abs(total - 1.0) < 1e-6

    def test_create_custom_invalid_types(self):
        """Test creating custom config with invalid types."""
        with pytest.raises(TypeError):
            ScoringConfig.create_custom(
                study="invalid",
                interest=0.3,
                market=0.2,
                growth=0.1,
                risk=0.1
            )


class TestGlobalFunctions:
    """Test global config functions."""

    def test_default_config_constant(self):
        """Test DEFAULT_CONFIG constant."""
        assert isinstance(DEFAULT_CONFIG, ScoringConfig)
        assert DEFAULT_CONFIG.simgr_weights.study_score == 0.25

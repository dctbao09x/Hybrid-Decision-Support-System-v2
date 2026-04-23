# tests/scoring_full/test_risk.py
"""
Full coverage tests for backend/scoring/components/risk.py

GĐ6: Coverage Recovery - Target: ≥85%

Tests:
- Risk score computation
- Sub-component calculations
- Boundary conditions
- Dataset lookups
- Legacy fallback
"""

from __future__ import annotations

import pytest
from typing import Dict
from unittest.mock import MagicMock, patch
import math


class TestRiskScore:
    """Tests for risk score() function."""
    
    def test_risk_returns_score_result(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine
    ):
        """score() returns ScoreResult."""
        from backend.scoring.components.risk import score
        from backend.scoring.models import ScoreResult
        
        result = score(mock_career_data, mock_user_profile, mock_scoring_config)
        
        assert isinstance(result, ScoreResult)
        assert hasattr(result, 'value')
        assert hasattr(result, 'meta')
    
    def test_risk_value_in_bounds(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine
    ):
        """Risk value is in [0, 1]."""
        from backend.scoring.components.risk import score
        
        result = score(mock_career_data, mock_user_profile, mock_scoring_config)
        
        assert 0.0 <= result.value <= 1.0
    
    def test_risk_meta_contains_formula(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine
    ):
        """Meta contains formula documentation."""
        from backend.scoring.components.risk import score
        
        result = score(mock_career_data, mock_user_profile, mock_scoring_config)
        
        assert "formula" in result.meta
        assert "R =" in result.meta["formula"]
    
    def test_risk_meta_contains_components(
        self, mock_scoring_config, mock_user_profile, mock_career_data,
        mock_risk_model, mock_penalty_engine
    ):
        """Meta contains all risk components."""
        from backend.scoring.components.risk import score
        
        result = score(mock_career_data, mock_user_profile, mock_scoring_config)
        
        # Should have component breakdowns
        expected_keys = ["saturation_risk", "obsolescence_risk", "total_risk"]
        for key in expected_keys:
            assert key in result.meta, f"Missing {key} in meta"


class TestRiskSubComponents:
    """Tests for risk sub-component calculations."""
    
    def test_compute_saturation_risk(self, mock_career_data):
        """Saturation risk from competition."""
        from backend.scoring.components.risk import _compute_saturation_risk
        
        result = _compute_saturation_risk(mock_career_data)
        
        # Should equal competition
        assert result == mock_career_data.competition
        assert 0.0 <= result <= 1.0
    
    def test_compute_saturation_risk_high_competition(self, high_risk_career):
        """High competition = high saturation risk."""
        from backend.scoring.components.risk import _compute_saturation_risk
        
        result = _compute_saturation_risk(high_risk_career)
        
        assert result == high_risk_career.competition
        assert result > 0.5  # High risk career has competition=0.9
    
    def test_compute_obsolescence_risk(self, mock_career_data):
        """Obsolescence risk from growth and AI factors."""
        from backend.scoring.components.risk import _compute_obsolescence_risk
        
        result = _compute_obsolescence_risk(mock_career_data)
        
        # (1 - growth) + (1 - ai_relevance) / 2
        expected = ((1 - mock_career_data.growth_rate) + (1 - mock_career_data.ai_relevance)) / 2
        assert abs(result - expected) < 1e-6
    
    def test_compute_obsolescence_high_growth_low_risk(self, mock_career_data):
        """High growth and AI relevance = low obsolescence."""
        from backend.scoring.components.risk import _compute_obsolescence_risk
        from backend.scoring.models import CareerData
        
        # High growth, high AI relevance
        career = CareerData(
            name="AI Engineer",
            required_skills=[],
            domain="tech",
            growth_rate=0.9,  # High growth
            ai_relevance=0.95,  # Very AI relevant
            competition=0.5,
        )
        
        result = _compute_obsolescence_risk(career)
        
        # Should be low
        assert result < 0.1
    
    def test_compute_dropout_risk(self, mock_user_profile, mock_career_data):
        """Dropout risk from career characteristics."""
        from backend.scoring.components.risk import _compute_dropout_risk
        
        result = _compute_dropout_risk(mock_career_data, mock_user_profile)
        
        assert 0.0 <= result <= 1.0
    
    def test_compute_dropout_risk_startup(self, mock_user_profile, high_risk_career):
        """Startup founder has high dropout risk."""
        from backend.scoring.components.risk import _compute_dropout_risk
        
        result = _compute_dropout_risk(high_risk_career, mock_user_profile)
        
        # Startup founder should have high dropout risk
        assert result > 0.5
    
    def test_compute_cost_risk(self, mock_career_data):
        """Entry cost risk from career."""
        from backend.scoring.components.risk import _compute_cost_risk
        
        result = _compute_cost_risk(mock_career_data)
        
        assert 0.0 <= result <= 1.0
    
    def test_compute_cost_risk_physician(self, low_risk_career):
        """Physician has high entry cost."""
        from backend.scoring.components.risk import _compute_cost_risk
        
        result = _compute_cost_risk(low_risk_career)
        
        # Physician requires expensive education
        assert result > 0.8
    
    def test_compute_unemployment_risk(self, mock_career_data):
        """Unemployment risk from sector data."""
        from backend.scoring.components.risk import _compute_unemployment_risk
        
        result = _compute_unemployment_risk(mock_career_data)
        
        assert 0.0 <= result <= 1.0


class TestLookupValue:
    """Tests for _lookup_value helper."""
    
    def test_lookup_exact_match(self):
        """Exact match in dataset."""
        from backend.scoring.components.risk import _lookup_value, DROPOUT_RISK_DATASET
        
        result = _lookup_value(DROPOUT_RISK_DATASET, "physician")
        assert result == DROPOUT_RISK_DATASET["physician"]
    
    def test_lookup_partial_match(self):
        """Partial match in dataset."""
        from backend.scoring.components.risk import _lookup_value, DROPOUT_RISK_DATASET
        
        # "software engineer" key contains in search string
        result = _lookup_value(DROPOUT_RISK_DATASET, "software engineer senior")
        assert result == DROPOUT_RISK_DATASET["software engineer"]
    
    def test_lookup_default(self):
        """Unknown career returns default."""
        from backend.scoring.components.risk import _lookup_value, DROPOUT_RISK_DATASET
        
        result = _lookup_value(DROPOUT_RISK_DATASET, "unknown_career_xyz")
        assert result == DROPOUT_RISK_DATASET["default"]
    
    def test_lookup_empty_name(self):
        """Empty name returns default."""
        from backend.scoring.components.risk import _lookup_value, DROPOUT_RISK_DATASET
        
        result = _lookup_value(DROPOUT_RISK_DATASET, "")
        assert result == DROPOUT_RISK_DATASET["default"]
    
    def test_lookup_case_insensitive(self):
        """Lookup is case-insensitive."""
        from backend.scoring.components.risk import _lookup_value, DROPOUT_RISK_DATASET
        
        result = _lookup_value(DROPOUT_RISK_DATASET, "PHYSICIAN")
        assert result == DROPOUT_RISK_DATASET["physician"]


class TestBoundaryConditions:
    """Boundary tests for risk component."""
    
    @pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
    def test_competition_valid_values(self, value: float, mock_scoring_config, mock_user_profile):
        """Valid competition values accepted."""
        from backend.scoring.components.risk import score
        from backend.scoring.models import CareerData
        
        career = CareerData(
            name="Test Career",
            required_skills=[],
            domain="test",
            competition=value,
            growth_rate=0.5,
            ai_relevance=0.5,
        )
        
        with patch("backend.scoring.components.risk.RiskModel") as mock_rm:
            mock_rm.return_value.compute_all.return_value = {
                "dropout": 0.3, "unemployment": 0.2, "cost": 0.3
            }
            with patch("backend.scoring.components.risk.get_penalty_engine") as mock_pe:
                mock_pe.return_value.compute.return_value = 0.35
                mock_pe.return_value.get_weights.return_value = {}
                
                result = score(career, mock_user_profile, mock_scoring_config)
                assert 0.0 <= result.value <= 1.0
    
    @pytest.mark.parametrize("competition,growth,ai_relevance", [
        (0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0),
        (0.5, 0.5, 0.5),
    ])
    def test_combined_boundary_values(
        self, competition, growth, ai_relevance,
        mock_scoring_config, mock_user_profile,
        mock_risk_model, mock_penalty_engine
    ):
        """Combined boundary values handled."""
        from backend.scoring.components.risk import score
        from backend.scoring.models import CareerData
        
        career = CareerData(
            name="Test Career",
            required_skills=[],
            domain="test",
            competition=competition,
            growth_rate=growth,
            ai_relevance=ai_relevance,
        )
        
        result = score(career, mock_user_profile, mock_scoring_config)
        assert 0.0 <= result.value <= 1.0


class TestLegacyFallback:
    """Tests for legacy fallback computation."""
    
    def test_legacy_score_returns_result(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """Legacy score function works."""
        from backend.scoring.components.risk import _legacy_score
        from backend.scoring.models import ScoreResult
        
        result = _legacy_score(mock_career_data, mock_user_profile, mock_scoring_config)
        
        assert isinstance(result, ScoreResult)
        assert 0.0 <= result.value <= 1.0
    
    def test_legacy_uses_deprecated_weights(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """Legacy uses hardcoded weights."""
        from backend.scoring.components.risk import (
            _legacy_score,
            WEIGHT_SATURATION,
            WEIGHT_OBSOLESCENCE,
            WEIGHT_COMPETITION,
            WEIGHT_DROPOUT,
            WEIGHT_UNEMPLOYMENT,
            WEIGHT_COST,
        )
        
        result = _legacy_score(mock_career_data, mock_user_profile, mock_scoring_config)
        
        # Meta should have weights used
        assert result.meta.get("module") == "legacy (deprecated)"
        assert "weights_used" in result.meta
    
    def test_fallback_triggered_on_exception(
        self, mock_scoring_config, mock_user_profile, mock_career_data
    ):
        """Fallback triggered when new module fails."""
        from backend.scoring.components.risk import score
        
        with patch("backend.scoring.components.risk.RiskModel") as mock_rm:
            mock_rm.side_effect = Exception("Module failed")
            
            # Should not raise, should use legacy
            result = score(mock_career_data, mock_user_profile, mock_scoring_config)
            
            assert result.meta.get("module") == "legacy (deprecated)"


class TestRiskMonotonicity:
    """Tests for risk score monotonicity."""
    
    def test_higher_competition_higher_risk(self, mock_scoring_config, mock_user_profile):
        """Higher competition should correlate with higher risk."""
        from backend.scoring.components.risk import _legacy_score
        from backend.scoring.models import CareerData
        
        results = []
        for comp in [0.1, 0.3, 0.5, 0.7, 0.9]:
            career = CareerData(
                name="Test Career",
                required_skills=[],
                domain="test",
                competition=comp,
                growth_rate=0.5,
                ai_relevance=0.5,
            )
            result = _legacy_score(career, mock_user_profile, mock_scoring_config)
            results.append(result.value)
        
        # Risk should generally increase with competition
        # (not strictly monotonic due to other factors)
        assert results[-1] > results[0], "High competition should have higher risk"
    
    def test_higher_growth_lower_risk(self, mock_scoring_config, mock_user_profile):
        """Higher growth should correlate with lower obsolescence risk."""
        from backend.scoring.components.risk import _compute_obsolescence_risk
        from backend.scoring.models import CareerData
        
        results = []
        for growth in [0.1, 0.3, 0.5, 0.7, 0.9]:
            career = CareerData(
                name="Test Career",
                required_skills=[],
                domain="test",
                competition=0.5,
                growth_rate=growth,
                ai_relevance=0.5,
            )
            result = _compute_obsolescence_risk(career)
            results.append(result)
        
        # Obsolescence risk should decrease with higher growth
        assert results[-1] < results[0]


class TestRiskDatasets:
    """Tests for risk datasets."""
    
    def test_dropout_dataset_has_default(self):
        """Dropout dataset has default value."""
        from backend.scoring.components.risk import DROPOUT_RISK_DATASET
        
        assert "default" in DROPOUT_RISK_DATASET
        assert 0.0 <= DROPOUT_RISK_DATASET["default"] <= 1.0
    
    def test_cost_dataset_has_default(self):
        """Cost dataset has default value."""
        from backend.scoring.components.risk import COST_RISK_DATASET
        
        assert "default" in COST_RISK_DATASET
        assert 0.0 <= COST_RISK_DATASET["default"] <= 1.0
    
    def test_unemployment_dataset_has_default(self):
        """Unemployment dataset has default value."""
        from backend.scoring.components.risk import UNEMPLOYMENT_RISK_DATASET
        
        assert "default" in UNEMPLOYMENT_RISK_DATASET
        assert 0.0 <= UNEMPLOYMENT_RISK_DATASET["default"] <= 1.0
    
    def test_all_dataset_values_in_bounds(self):
        """All dataset values are in [0, 1]."""
        from backend.scoring.components.risk import (
            DROPOUT_RISK_DATASET,
            COST_RISK_DATASET,
            UNEMPLOYMENT_RISK_DATASET,
        )
        
        for dataset in [DROPOUT_RISK_DATASET, COST_RISK_DATASET, UNEMPLOYMENT_RISK_DATASET]:
            for key, value in dataset.items():
                assert 0.0 <= value <= 1.0, f"{key}: {value} not in [0,1]"


class TestRiskWeights:
    """Tests for risk component weights."""
    
    def test_weights_sum_to_one(self):
        """Risk sub-component weights sum to 1.0."""
        from backend.scoring.components.risk import (
            WEIGHT_SATURATION,
            WEIGHT_OBSOLESCENCE,
            WEIGHT_COMPETITION,
            WEIGHT_DROPOUT,
            WEIGHT_UNEMPLOYMENT,
            WEIGHT_COST,
        )
        
        total = (
            WEIGHT_SATURATION +
            WEIGHT_OBSOLESCENCE +
            WEIGHT_COMPETITION +
            WEIGHT_DROPOUT +
            WEIGHT_UNEMPLOYMENT +
            WEIGHT_COST
        )
        
        assert abs(total - 1.0) < 1e-6


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

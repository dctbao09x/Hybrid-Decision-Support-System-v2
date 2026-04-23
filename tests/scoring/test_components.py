# tests/scoring/test_components.py
"""
Tests for SIMGR Component Factors (R004)

Validates:
- Study: A (Ability), B (Background), C (Confidence)
- Interest: NLP, Survey, Stability
- Market: AI, Growth, Salary, InvComp
- Growth: Lifecycle, Demand, SalaryGrowth
- Risk: 6 factors
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestStudyComponent:
    """Test Study component (S = 0.4*A + 0.3*B + 0.3*C)."""
    
    def test_study_module_exists(self):
        """Study component module must exist."""
        from backend.scoring.components import study
        assert study is not None
    
    def test_ability_factor_function_exists(self):
        """Ability factor function must exist."""
        from backend.scoring.components.study import _compute_ability_factor
        assert callable(_compute_ability_factor)
    
    def test_background_factor_function_exists(self):
        """Background factor function must exist."""
        from backend.scoring.components.study import _compute_background_factor
        assert callable(_compute_background_factor)
    
    def test_confidence_factor_function_exists(self):
        """Confidence factor function must exist."""
        from backend.scoring.components.study import _compute_confidence_factor
        assert callable(_compute_confidence_factor)
    
    def test_study_weights_defined(self):
        """Study weights must be defined."""
        from backend.scoring.components.study import (
            WEIGHT_ABILITY,
            WEIGHT_BACKGROUND,
            WEIGHT_CONFIDENCE,
        )
        
        assert WEIGHT_ABILITY == 0.4
        assert WEIGHT_BACKGROUND == 0.3
        assert WEIGHT_CONFIDENCE == 0.3
    
    def test_study_weights_sum_to_one(self):
        """Study weights must sum to 1.0."""
        from backend.scoring.components.study import (
            WEIGHT_ABILITY,
            WEIGHT_BACKGROUND,
            WEIGHT_CONFIDENCE,
        )
        
        total = WEIGHT_ABILITY + WEIGHT_BACKGROUND + WEIGHT_CONFIDENCE
        assert abs(total - 1.0) < 0.001


class TestInterestComponent:
    """Test Interest component (I = 0.4*NLP + 0.3*Survey + 0.3*Stability)."""
    
    def test_interest_module_exists(self):
        """Interest component module must exist."""
        from backend.scoring.components import interest
        assert interest is not None
    
    def test_nlp_factor_function_exists(self):
        """NLP factor function must exist."""
        from backend.scoring.components.interest import _compute_nlp_factor
        assert callable(_compute_nlp_factor)
    
    def test_survey_factor_function_exists(self):
        """Survey factor function must exist."""
        from backend.scoring.components.interest import _compute_survey_factor
        assert callable(_compute_survey_factor)
    
    def test_stability_factor_function_exists(self):
        """Stability factor function must exist."""
        from backend.scoring.components.interest import _compute_stability_factor
        assert callable(_compute_stability_factor)
    
    def test_interest_weights_defined(self):
        """Interest weights must be defined."""
        from backend.scoring.components.interest import (
            WEIGHT_NLP,
            WEIGHT_SURVEY,
            WEIGHT_STABILITY,
        )
        
        assert WEIGHT_NLP == 0.4
        assert WEIGHT_SURVEY == 0.3
        assert WEIGHT_STABILITY == 0.3
    
    def test_interest_weights_sum_to_one(self):
        """Interest weights must sum to 1.0."""
        from backend.scoring.components.interest import (
            WEIGHT_NLP,
            WEIGHT_SURVEY,
            WEIGHT_STABILITY,
        )
        
        total = WEIGHT_NLP + WEIGHT_SURVEY + WEIGHT_STABILITY
        assert abs(total - 1.0) < 0.001


class TestMarketComponent:
    """Test Market component (M = 0.3*AI + 0.3*Growth + 0.2*Salary + 0.2*InvComp)."""
    
    def test_market_module_exists(self):
        """Market component module must exist."""
        from backend.scoring.components import market
        assert market is not None
    
    def test_market_weights_defined(self):
        """Market weights must be defined."""
        from backend.scoring.components.market import (
            WEIGHT_AI_RELEVANCE,
            WEIGHT_GROWTH_RATE,
            WEIGHT_SALARY,
            WEIGHT_INVERSE_COMP,
        )
        
        assert WEIGHT_AI_RELEVANCE == 0.3
        assert WEIGHT_GROWTH_RATE == 0.3
        assert WEIGHT_SALARY == 0.2
        assert WEIGHT_INVERSE_COMP == 0.2
    
    def test_market_weights_sum_to_one(self):
        """Market weights must sum to 1.0."""
        from backend.scoring.components.market import (
            WEIGHT_AI_RELEVANCE,
            WEIGHT_GROWTH_RATE,
            WEIGHT_SALARY,
            WEIGHT_INVERSE_COMP,
        )
        
        total = WEIGHT_AI_RELEVANCE + WEIGHT_GROWTH_RATE + WEIGHT_SALARY + WEIGHT_INVERSE_COMP
        assert abs(total - 1.0) < 0.001
    
    def test_salary_dataset_exists(self):
        """Salary dataset must exist with careers."""
        from backend.scoring.components.market import SALARY_DATASET
        
        assert len(SALARY_DATASET) > 10
        assert "software engineer" in SALARY_DATASET


class TestGrowthComponent:
    """Test Growth component (G = 0.4*Lifecycle + 0.3*Demand + 0.3*Salary)."""
    
    def test_growth_module_exists(self):
        """Growth component module must exist."""
        from backend.scoring.components import growth
        assert growth is not None
    
    def test_lifecycle_dataset_exists(self):
        """Lifecycle dataset must exist."""
        from backend.scoring.components.growth import LIFECYCLE_DATASET
        
        assert len(LIFECYCLE_DATASET) > 10
    
    def test_demand_forecast_exists(self):
        """Demand forecast dataset must exist."""
        from backend.scoring.components.growth import DEMAND_FORECAST
        
        assert len(DEMAND_FORECAST) > 10
    
    def test_growth_weights_defined(self):
        """Growth weights must be defined."""
        from backend.scoring.components.growth import (
            WEIGHT_DEMAND_GROWTH,
            WEIGHT_SALARY_GROWTH,
            WEIGHT_LIFECYCLE,
        )
        
        assert WEIGHT_DEMAND_GROWTH == 0.35
        assert WEIGHT_SALARY_GROWTH == 0.35
        assert WEIGHT_LIFECYCLE == 0.30
    
    def test_growth_weights_sum_to_one(self):
        """Growth weights must sum to 1.0."""
        from backend.scoring.components.growth import (
            WEIGHT_DEMAND_GROWTH,
            WEIGHT_SALARY_GROWTH,
            WEIGHT_LIFECYCLE,
        )
        
        total = WEIGHT_DEMAND_GROWTH + WEIGHT_SALARY_GROWTH + WEIGHT_LIFECYCLE
        assert abs(total - 1.0) < 0.001


class TestRiskComponent:
    """Test Risk component (6 factors)."""
    
    def test_risk_module_exists(self):
        """Risk component module must exist."""
        from backend.scoring.components import risk
        assert risk is not None
    
    def test_risk_weights_defined(self):
        """Risk weights must be defined."""
        from backend.scoring.components.risk import (
            WEIGHT_SATURATION,
            WEIGHT_OBSOLESCENCE,
            WEIGHT_COMPETITION,
            WEIGHT_DROPOUT,
            WEIGHT_UNEMPLOYMENT,
            WEIGHT_COST,
        )
        
        assert WEIGHT_SATURATION == 0.25
        assert WEIGHT_OBSOLESCENCE == 0.20
        assert WEIGHT_COMPETITION == 0.15
        assert WEIGHT_DROPOUT == 0.15
        assert WEIGHT_UNEMPLOYMENT == 0.15
        assert WEIGHT_COST == 0.10
    
    def test_risk_weights_sum_to_one(self):
        """Risk weights must sum to 1.0."""
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
        assert abs(total - 1.0) < 0.001
    
    def test_dropout_dataset_exists(self):
        """Dropout risk dataset must exist."""
        from backend.scoring.components.risk import DROPOUT_RISK_DATASET
        
        assert len(DROPOUT_RISK_DATASET) > 10
    
    def test_unemployment_dataset_exists(self):
        """Unemployment risk dataset must exist."""
        from backend.scoring.components.risk import UNEMPLOYMENT_RISK_DATASET
        
        assert len(UNEMPLOYMENT_RISK_DATASET) > 10


class TestRiskModel:
    """Test backend.risk module."""
    
    def test_risk_model_exists(self):
        """RiskModel must exist."""
        from backend.risk.model import RiskModel
        assert RiskModel is not None
    
    def test_dropout_predictor_exists(self):
        """DropoutPredictor must exist."""
        from backend.risk.model import DropoutPredictor
        assert DropoutPredictor is not None
    
    def test_unemployment_predictor_exists(self):
        """UnemploymentPredictor must exist."""
        from backend.risk.model import UnemploymentPredictor
        assert UnemploymentPredictor is not None
    
    def test_cost_model_exists(self):
        """CostModel must exist."""
        from backend.risk.model import CostModel
        assert CostModel is not None


class TestR004Compliance:
    """Test R004 Missing Factor Components compliance."""
    
    def test_all_study_factors_implemented(self):
        """All Study factors (A, B, C) must be implemented."""
        from backend.scoring.components.study import (
            _compute_ability_factor,
            _compute_background_factor,
            _compute_confidence_factor,
        )
        
        assert callable(_compute_ability_factor)
        assert callable(_compute_background_factor)
        assert callable(_compute_confidence_factor)
    
    def test_all_interest_factors_implemented(self):
        """All Interest factors (NLP, Survey, Stability) must be implemented."""
        from backend.scoring.components.interest import (
            _compute_nlp_factor,
            _compute_survey_factor,
            _compute_stability_factor,
        )
        
        assert callable(_compute_nlp_factor)
        assert callable(_compute_survey_factor)
        assert callable(_compute_stability_factor)
    
    def test_all_risk_factors_implemented(self):
        """All Risk factors must be implemented."""
        from backend.scoring.components.risk import (
            _compute_saturation_risk,
            _compute_obsolescence_risk,
            _compute_dropout_risk,
            _compute_cost_risk,
            _compute_unemployment_risk,
        )
        
        assert callable(_compute_saturation_risk)
        assert callable(_compute_obsolescence_risk)
        assert callable(_compute_dropout_risk)
        assert callable(_compute_cost_risk)
        assert callable(_compute_unemployment_risk)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

# tests/risk/test_models.py
"""
Tests for Risk Models - SIMGR Stage 3 Compliance

Tests for:
- DropoutPredictor
- UnemploymentPredictor
- CostModel
- RiskModel (aggregate)
"""

import pytest


class TestDropoutPredictor:
    """Tests for DropoutPredictor."""
    
    def test_instantiation(self):
        """DropoutPredictor should instantiate."""
        from backend.risk.model import DropoutPredictor
        predictor = DropoutPredictor()
        assert predictor is not None
    
    def test_predict_returns_float(self):
        """Predict should return a float."""
        from backend.risk.model import DropoutPredictor, UserRiskProfile
        
        predictor = DropoutPredictor()
        user = UserRiskProfile(
            user_id="test",
            education_level="bachelor",
            completion_history=[0.8, 0.9, 0.85],
            engagement_score=0.7,
        )
        
        result = predictor.predict(user)
        assert isinstance(result, float)
    
    def test_predict_in_range(self):
        """Prediction must be in [0, 1]."""
        from backend.risk.model import DropoutPredictor, UserRiskProfile
        
        predictor = DropoutPredictor()
        user = UserRiskProfile(
            user_id="test",
            education_level="bachelor",
            completion_history=[0.5],
            engagement_score=0.5,
        )
        
        result = predictor.predict(user)
        assert 0.0 <= result <= 1.0
    
    def test_low_engagement_high_dropout(self):
        """Low engagement should increase dropout risk."""
        from backend.risk.model import DropoutPredictor, UserRiskProfile
        
        predictor = DropoutPredictor()
        
        high_engage = UserRiskProfile(
            user_id="high",
            education_level="bachelor",
            completion_history=[0.9],
            engagement_score=0.95,
        )
        
        low_engage = UserRiskProfile(
            user_id="low",
            education_level="bachelor",
            completion_history=[0.9],
            engagement_score=0.1,
        )
        
        high_result = predictor.predict(high_engage)
        low_result = predictor.predict(low_engage)
        
        assert low_result > high_result, (
            f"Low engagement ({low_result}) should have higher dropout risk "
            f"than high engagement ({high_result})"
        )
    
    def test_poor_history_high_dropout(self):
        """Poor completion history should increase dropout risk."""
        from backend.risk.model import DropoutPredictor, UserRiskProfile
        
        predictor = DropoutPredictor()
        
        good_history = UserRiskProfile(
            user_id="good",
            education_level="bachelor",
            completion_history=[0.95, 0.92, 0.98],
            engagement_score=0.7,
        )
        
        poor_history = UserRiskProfile(
            user_id="poor",
            education_level="bachelor",
            completion_history=[0.2, 0.3, 0.1],
            engagement_score=0.7,
        )
        
        good_result = predictor.predict(good_history)
        poor_result = predictor.predict(poor_history)
        
        assert poor_result > good_result, (
            f"Poor history ({poor_result}) should have higher dropout risk "
            f"than good history ({good_result})"
        )


class TestUnemploymentPredictor:
    """Tests for UnemploymentPredictor."""
    
    def test_instantiation(self):
        """UnemploymentPredictor should instantiate."""
        from backend.risk.model import UnemploymentPredictor
        predictor = UnemploymentPredictor()
        assert predictor is not None
    
    def test_predict_returns_float(self):
        """Predict should return a float."""
        from backend.risk.model import UnemploymentPredictor, JobRiskProfile
        
        predictor = UnemploymentPredictor()
        job = JobRiskProfile(
            career_name="Software Engineer",
            sector="technology",
            region="west",
        )
        
        result = predictor.predict(job)
        assert isinstance(result, float)
    
    def test_predict_in_range(self):
        """Prediction must be in [0, 1]."""
        from backend.risk.model import UnemploymentPredictor, JobRiskProfile
        
        predictor = UnemploymentPredictor()
        job = JobRiskProfile(
            career_name="Data Scientist",
            sector="technology",
            region="national",
        )
        
        result = predictor.predict(job)
        assert 0.0 <= result <= 1.0
    
    def test_high_unemployment_sector(self):
        """High unemployment sectors should have higher risk."""
        from backend.risk.model import UnemploymentPredictor, JobRiskProfile
        
        predictor = UnemploymentPredictor()
        
        tech_job = JobRiskProfile(
            career_name="Software Engineer",
            sector="technology",
            region="national",
        )
        
        retail_job = JobRiskProfile(
            career_name="Retail Associate",
            sector="retail",
            region="national",
        )
        
        tech_result = predictor.predict(tech_job)
        retail_result = predictor.predict(retail_job)
        
        # Both should be valid predictions
        assert 0.0 <= tech_result <= 1.0
        assert 0.0 <= retail_result <= 1.0


class TestCostModel:
    """Tests for CostModel."""
    
    def test_instantiation(self):
        """CostModel should instantiate."""
        from backend.risk.model import CostModel
        model = CostModel()
        assert model is not None
    
    def test_compute_returns_float(self):
        """Compute should return a float."""
        from backend.risk.model import CostModel, JobRiskProfile
        
        model = CostModel()
        job = JobRiskProfile(
            career_name="Software Engineer",
            sector="technology",
            region="national",
            education_cost=50000.0,
            training_months=24,
            avg_salary=100000.0,
        )
        
        result = model.compute(job)
        assert isinstance(result, float)
    
    def test_compute_in_range(self):
        """Cost risk must be in [0, 1]."""
        from backend.risk.model import CostModel, JobRiskProfile
        
        model = CostModel()
        job = JobRiskProfile(
            career_name="Doctor",
            sector="healthcare",
            region="national",
            education_cost=200000.0,
            training_months=96,
            avg_salary=250000.0,
        )
        
        result = model.compute(job)
        assert 0.0 <= result <= 1.0
    
    def test_high_cost_high_risk(self):
        """High education cost should increase cost risk."""
        from backend.risk.model import CostModel, JobRiskProfile
        
        model = CostModel()
        
        low_cost_job = JobRiskProfile(
            career_name="Web Developer",
            sector="technology",
            region="national",
            education_cost=5000.0,
            training_months=6,
            avg_salary=60000.0,
        )
        
        high_cost_job = JobRiskProfile(
            career_name="Doctor",
            sector="healthcare",
            region="national",
            education_cost=300000.0,
            training_months=120,
            avg_salary=200000.0,
        )
        
        low_result = model.compute(low_cost_job)
        high_result = model.compute(high_cost_job)
        
        assert high_result > low_result, (
            f"High cost ({high_result}) should have higher risk "
            f"than low cost ({low_result})"
        )


class TestRiskModel:
    """Tests for aggregate RiskModel."""
    
    def test_instantiation(self):
        """RiskModel should instantiate."""
        from backend.risk.model import RiskModel
        model = RiskModel()
        assert model is not None
    
    def test_compute_all_returns_dict(self):
        """compute_all should return dict."""
        from backend.risk.model import RiskModel, UserRiskProfile, JobRiskProfile
        
        model = RiskModel()
        user = UserRiskProfile(
            user_id="test",
            education_level="bachelor",
            completion_history=[0.8],
            engagement_score=0.7,
        )
        job = JobRiskProfile(
            career_name="Software Engineer",
            sector="technology",
            region="national",
            education_cost=30000.0,
            training_months=24,
            avg_salary=100000.0,
        )
        
        result = model.compute_all(user, job)
        assert isinstance(result, dict)
    
    def test_compute_all_has_required_keys(self):
        """compute_all should have all required keys."""
        from backend.risk.model import RiskModel, UserRiskProfile, JobRiskProfile
        
        model = RiskModel()
        user = UserRiskProfile(
            user_id="test",
            education_level="bachelor",
            completion_history=[0.8],
            engagement_score=0.7,
        )
        job = JobRiskProfile(
            career_name="Software Engineer",
            sector="technology",
            region="national",
            education_cost=30000.0,
            training_months=24,
            avg_salary=100000.0,
        )
        
        result = model.compute_all(user, job)
        
        assert 'dropout' in result
        assert 'unemployment' in result
        assert 'cost' in result
    
    def test_all_results_in_range(self):
        """All results should be in [0, 1]."""
        from backend.risk.model import RiskModel, UserRiskProfile, JobRiskProfile
        
        model = RiskModel()
        user = UserRiskProfile(
            user_id="test",
            education_level="bachelor",
            completion_history=[0.8],
            engagement_score=0.7,
        )
        job = JobRiskProfile(
            career_name="Software Engineer",
            sector="technology",
            region="national",
            education_cost=30000.0,
            training_months=24,
            avg_salary=100000.0,
        )
        
        result = model.compute_all(user, job)
        
        for key, value in result.items():
            assert 0.0 <= value <= 1.0, f"{key}={value} out of range"


class TestNoInversionInModels:
    """Critical: Ensure no inversion in model outputs."""
    
    def test_dropout_no_inversion(self):
        """DropoutPredictor must not invert results."""
        from backend.risk.model import DropoutPredictor, UserRiskProfile
        
        predictor = DropoutPredictor()
        
        # High-risk user (low engagement, poor history)
        risky_user = UserRiskProfile(
            user_id="risky",
            education_level="high_school",
            completion_history=[0.1, 0.2],
            engagement_score=0.1,
        )
        
        # Low-risk user (high engagement, good history)
        safe_user = UserRiskProfile(
            user_id="safe",
            education_level="masters",
            completion_history=[0.95, 0.98],
            engagement_score=0.95,
        )
        
        risky_result = predictor.predict(risky_user)
        safe_result = predictor.predict(safe_user)
        
        # Risky should have HIGHER number (NO INVERSION)
        assert risky_result > safe_result, (
            f"Risky user ({risky_result}) should have higher dropout risk "
            f"than safe user ({safe_result}). Check for inversion."
        )
    
    def test_cost_no_inversion(self):
        """CostModel must not invert results."""
        from backend.risk.model import CostModel, JobRiskProfile
        
        model = CostModel()
        
        # High cost job
        expensive = JobRiskProfile(
            career_name="Doctor",
            sector="healthcare",
            region="national",
            education_cost=400000.0,
            training_months=144,
            avg_salary=200000.0,
        )
        
        # Low cost job
        cheap = JobRiskProfile(
            career_name="Freelancer",
            sector="technology",
            region="national",
            education_cost=1000.0,
            training_months=3,
            avg_salary=50000.0,
        )
        
        expensive_result = model.compute(expensive)
        cheap_result = model.compute(cheap)
        
        # Expensive should have HIGHER cost risk (NO INVERSION)
        assert expensive_result > cheap_result, (
            f"Expensive career ({expensive_result}) should have higher cost risk "
            f"than cheap career ({cheap_result}). Check for inversion."
        )

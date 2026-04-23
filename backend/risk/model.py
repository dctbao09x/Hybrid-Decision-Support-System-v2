# backend/risk/model.py
"""
Risk Models - SIMGR Stage 3 Compliant

Implements prediction models for:
- Dropout risk
- Unemployment risk
- Cost risk

NO MOCKING - Uses real data and calculations.
NO INVERSION - Returns raw risk values.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .registry import get_registry, ModelConfig
from .data_loader import (
    get_unemployment_loader,
    get_cost_loader,
    get_sector_loader,
)

logger = logging.getLogger(__name__)


@dataclass
class UserRiskProfile:
    """User profile data relevant to risk assessment."""
    user_id: str = "unknown"
    education_level: str = "bachelor"
    completion_history: List[float] = field(default_factory=lambda: [0.8])
    engagement_score: float = 0.7
    financial_stability: float = 0.6
    time_commitment: float = 0.7
    region: str = "national"
    current_salary: float = 60000.0


@dataclass
class JobRiskProfile:
    """Job/career profile data relevant to risk assessment."""
    career_name: str = ""
    sector: str = "technology"
    region: str = "national"
    education_cost: float = 30000.0
    training_months: int = 24
    avg_salary: float = 60000.0
    ai_relevance: float = 0.5
    growth_rate: float = 0.5
    competition: float = 0.5
    required_education: str = "bachelor"


class DropoutPredictor:
    """Predicts dropout/career abandonment risk.
    
    Uses weighted combination of:
    - Education factors (completion history)
    - Engagement factors (commitment score)
    
    NO MOCKING - Uses real calculations.
    NO INVERSION - Returns raw risk (high = bad).
    """
    
    def __init__(self, config: Optional[ModelConfig] = None):
        self.config = config or get_registry().get_model_config()
    
    def predict(self, user: UserRiskProfile) -> float:
        """Predict dropout risk for user.
        
        Args:
            user: User risk profile
            
        Returns:
            Dropout risk score [0, 1] where 1 = high risk.
        """
        # Education factor: completion history
        education_risk = self._compute_education_risk(user)
        
        # History factor: from completion history variance
        history_risk = self._compute_history_risk(user)
        
        # Engagement factor: commitment score
        engagement_risk = self._compute_engagement_risk(user)
        
        # Weighted combination (from config)
        dropout_risk = (
            self.config.dropout_education_weight * education_risk +
            self.config.dropout_history_weight * history_risk +
            self.config.dropout_engagement_weight * engagement_risk
        )
        
        # Clamp to [0, 1]
        return max(0.0, min(1.0, dropout_risk))
    
    def _compute_education_risk(self, user: UserRiskProfile) -> float:
        """Compute education-based dropout risk."""
        # Higher education level = lower dropout risk
        level_risk = {
            "high_school": 0.7,
            "associate": 0.5,
            "bachelor": 0.3,
            "masters": 0.2,
            "master": 0.2,
            "phd": 0.1,
            "doctorate": 0.1,
        }
        return level_risk.get(user.education_level.lower(), 0.4)
    
    def _compute_history_risk(self, user: UserRiskProfile) -> float:
        """Compute history-based dropout risk from completion history."""
        if not user.completion_history:
            return 0.5  # Unknown = medium risk
        
        # Average completion rate (low = high dropout risk)
        avg_completion = sum(user.completion_history) / len(user.completion_history)
        return 1.0 - avg_completion  # Invert: low completion = high risk
    
    def _compute_engagement_risk(self, user: UserRiskProfile) -> float:
        """Compute engagement-based dropout risk."""
        # Low engagement = high dropout risk
        return 1.0 - user.engagement_score
        
        # Low time commitment = high risk
        time_factor = 1.0 - user.time_commitment
        
        # Weighted average
        return (
            engagement_factor * 0.4 +
            financial_factor * 0.35 +
            time_factor * 0.25
        )


class UnemploymentPredictor:
    """Predicts unemployment risk for a career path.
    
    Uses weighted combination of:
    - Sector unemployment rates (from dataset)
    - Regional variations
    - Trend analysis
    
    NO MOCKING - Uses real dataset.
    NO INVERSION - Returns raw risk (high = bad).
    """
    
    def __init__(self, config: Optional[ModelConfig] = None):
        self.config = config or get_registry().get_model_config()
        self._unemployment_loader = get_unemployment_loader()
    
    def predict(self, job: JobRiskProfile) -> float:
        """Predict unemployment risk for career path.
        
        Args:
            job: Job risk profile (for sector/region)
            
        Returns:
            Unemployment risk score [0, 1] where 1 = high risk.
        """
        # Ensure dataset is loaded
        self._unemployment_loader.load_dataset()
        
        # Get sector-based risk
        sector_risk = self._compute_sector_risk(job)
        
        # Get regional adjustment
        region_risk = self._compute_region_risk(job)
        
        # Get trend-based adjustment
        trend_risk = self._compute_trend_risk(job)
        
        # Weighted combination (from config)
        unemployment_risk = (
            self.config.unemployment_sector_weight * sector_risk +
            self.config.unemployment_region_weight * region_risk +
            self.config.unemployment_trend_weight * trend_risk
        )
        
        # Clamp to [0, 1]
        return max(0.0, min(1.0, unemployment_risk))
    
    def _compute_sector_risk(self, job: JobRiskProfile) -> float:
        """Compute sector-based unemployment risk."""
        # Get unemployment rate from dataset
        rate = self._unemployment_loader.get_rate(
            sector=job.sector,
            year=2026,
        )
        
        # Normalize: 0% = 0 risk, 15%+ = 1.0 risk
        return min(1.0, rate / 0.15)
    
    def _compute_region_risk(self, job: JobRiskProfile) -> float:
        """Compute region-based unemployment adjustment."""
        rate = self._unemployment_loader.get_rate(
            region=job.region,
            sector=job.sector,
            year=2026,
        )
        
        # Normalize
        return min(1.0, rate / 0.15)
    
    def _compute_trend_risk(self, job: JobRiskProfile) -> float:
        """Compute trend-based unemployment risk."""
        trend = self._unemployment_loader.get_trend(
            region=job.region,
            sector=job.sector,
            year=2026,
        )
        
        trend_risk = {
            "declining": 0.2,  # Good - unemployment declining
            "stable": 0.4,     # Neutral
            "rising": 0.8,     # Bad - unemployment rising
        }
        
        return trend_risk.get(trend, 0.4)


class CostModel:
    """Computes career transition cost risk.
    
    Combines:
    - Education cost (tuition, materials)
    - Time cost (opportunity cost of training)
    - Opportunity cost (foregone income)
    
    All costs normalized to [0, 1] risk scale.
    NO MOCKING - Uses real dataset.
    NO INVERSION - Returns raw risk (high = bad).
    """
    
    def __init__(self, config: Optional[ModelConfig] = None):
        self.config = config or get_registry().get_model_config()
        self._cost_loader = get_cost_loader()
        self._thresholds = get_registry().get_thresholds()
    
    def compute(self, job: JobRiskProfile) -> float:
        """Compute total cost risk for career transition.
        
        Args:
            job: Job risk profile
            
        Returns:
            Cost risk score [0, 1] where 1 = high cost barrier.
        """
        # Ensure dataset is loaded
        self._cost_loader.load_dataset()
        
        # Compute individual cost factors
        education_risk = self._education_cost_risk(job)
        time_risk = self._time_cost_risk(job)
        opportunity_risk = self._opportunity_cost_risk(job)
        
        # Weighted combination (from config)
        total_risk = (
            self.config.cost_education_weight * education_risk +
            self.config.cost_time_weight * time_risk +
            self.config.cost_opportunity_weight * opportunity_risk
        )
        
        # Clamp to [0, 1]
        return max(0.0, min(1.0, total_risk))
    
    def _education_cost_risk(self, job: JobRiskProfile) -> float:
        """Compute education cost risk.
        
        Returns:
            Risk [0, 1] based on education cost vs threshold.
        """
        cost = job.education_cost
        
        # Normalize against thresholds
        if cost >= self._thresholds.cost_high:
            return 1.0
        elif cost >= self._thresholds.cost_medium:
            # Linear interpolation between medium and high
            return 0.5 + 0.5 * (cost - self._thresholds.cost_medium) / (
                self._thresholds.cost_high - self._thresholds.cost_medium
            )
        else:
            # Linear interpolation from 0 to medium
            return 0.5 * cost / self._thresholds.cost_medium
    
    def _time_cost_risk(self, job: JobRiskProfile) -> float:
        """Compute time cost risk based on training duration."""
        # Normalize: 0 months = 0 risk, 120+ months = 1.0 risk
        return min(1.0, job.training_months / 120.0)
    
    def _opportunity_cost_risk(self, job: JobRiskProfile) -> float:
        """Compute opportunity cost risk."""
        # Higher salary = lower opportunity cost (already earning well)
        # Lower salary = higher opportunity cost
        # Normalize against $100k baseline
        if job.avg_salary >= 100000:
            return 0.2  # Low opportunity cost
        elif job.avg_salary >= 60000:
            return 0.4
        else:
            return min(1.0, 0.6 + (60000 - job.avg_salary) / 100000)


class RiskModel:
    """Combined risk model for career assessment.
    
    Aggregates all risk predictors:
    - Dropout prediction
    - Unemployment prediction
    - Cost modeling
    
    Also computes market saturation, skill obsolescence, and competition
    risks from job profile data.
    """
    
    def __init__(self):
        self.dropout_predictor = DropoutPredictor()
        self.unemployment_predictor = UnemploymentPredictor()
        self.cost_model = CostModel()
        self._sector_loader = get_sector_loader()
    
    def compute_all(
        self,
        user: UserRiskProfile,
        job: JobRiskProfile,
    ) -> Dict[str, float]:
        """Compute all risk factors.
        
        Args:
            user: User risk profile
            job: Job risk profile
            
        Returns:
            Dictionary with all risk components.
        """
        return {
            "dropout": self.dropout_predictor.predict(user),
            "unemployment": self.unemployment_predictor.predict(job),
            "cost": self.cost_model.compute(job),
            "market_saturation": self.compute_market_saturation(job),
            "skill_obsolescence": self.compute_skill_obsolescence(job),
            "competition": self.compute_competition(job),
        }
    
    def compute_market_saturation(self, job: JobRiskProfile) -> float:
        """Compute market saturation risk.
        
        Uses competition level from job profile.
        """
        # Direct from job profile
        if job.competition is not None:
            return max(0.0, min(1.0, job.competition))
        
        # Fall back to sector data
        self._sector_loader.load_dataset()
        return self._sector_loader.get_saturation(job.sector)
    
    def compute_skill_obsolescence(self, job: JobRiskProfile) -> float:
        """Compute skill obsolescence risk.
        
        Based on AI relevance and growth rate.
        Low AI relevance + low growth = high obsolescence risk.
        """
        # Inverse of AI relevance (low AI relevance = high automation risk)
        ai_risk = 1.0 - job.ai_relevance
        
        # Inverse of growth (low growth = stagnant skills)
        growth_risk = 1.0 - job.growth_rate
        
        # Weighted average
        return (ai_risk * 0.6 + growth_risk * 0.4)
    
    def compute_competition(self, job: JobRiskProfile) -> float:
        """Compute competition risk.
        
        Direct from job profile competition level.
        """
        return max(0.0, min(1.0, job.competition))


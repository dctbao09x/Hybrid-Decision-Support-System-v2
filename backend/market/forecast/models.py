# backend/market/forecast/models.py
"""
Data models for Demand Forecasting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ForecastHorizon(Enum):
    """Forecast time horizons."""
    SHORT = "3_months"   # 3 months
    MEDIUM = "6_months"  # 6 months
    LONG = "12_months"   # 12 months


class ForecastScenario(Enum):
    """Forecast scenarios."""
    BASELINE = "baseline"       # Continue current trends
    OPTIMISTIC = "optimistic"   # Accelerated growth
    PESSIMISTIC = "pessimistic" # Decelerated/negative growth
    DISRUPTION = "disruption"   # Major market disruption


@dataclass
class ConfidenceBand:
    """
    Confidence band for forecast.
    
    Attributes:
        p50: 50th percentile (median)
        p80: 80th percentile (likely upper bound)
        p95: 95th percentile (high confidence upper bound)
        p20: 20th percentile (likely lower bound)
        p5: 5th percentile (high confidence lower bound)
    """
    p5: float
    p20: float
    p50: float  # Median
    p80: float
    p95: float
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "p5": self.p5,
            "p20": self.p20,
            "p50": self.p50,
            "p80": self.p80,
            "p95": self.p95,
        }
    
    @classmethod
    def from_samples(cls, samples: List[float]) -> "ConfidenceBand":
        """Create confidence band from Monte Carlo samples."""
        if not samples:
            return cls(0, 0, 0, 0, 0)
        
        sorted_samples = sorted(samples)
        n = len(sorted_samples)
        
        def percentile(p: float) -> float:
            idx = int(p * n / 100)
            return sorted_samples[min(idx, n - 1)]
        
        return cls(
            p5=percentile(5),
            p20=percentile(20),
            p50=percentile(50),
            p80=percentile(80),
            p95=percentile(95),
        )


@dataclass
class DemandForecast:
    """
    Demand forecast for a single skill.
    
    Attributes:
        skill_id: Reference to skill
        skill_name: Canonical skill name
        horizon: Forecast horizon
        forecast_date: When forecast was made
        target_date: Date of forecast prediction
        scenario: Forecast scenario
        predicted_demand: Point forecast (expected demand index)
        confidence: Confidence band
        current_demand: Current demand level for reference
        growth_rate: Predicted growth rate
        volatility: Expected volatility
        model_used: Which model(s) produced this forecast
        features: Key features driving forecast
    """
    skill_id: str
    skill_name: str
    horizon: ForecastHorizon
    forecast_date: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    target_date: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    scenario: ForecastScenario = ForecastScenario.BASELINE
    predicted_demand: float = 0.0
    confidence: ConfidenceBand = field(default_factory=lambda: ConfidenceBand(0, 0, 0, 0, 0))
    current_demand: float = 0.0
    growth_rate: float = 0.0
    volatility: float = 0.0
    model_used: str = "ensemble"
    features: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "horizon": self.horizon.value,
            "forecast_date": self.forecast_date.isoformat(),
            "target_date": self.target_date.isoformat(),
            "scenario": self.scenario.value,
            "predicted_demand": self.predicted_demand,
            "confidence": self.confidence.to_dict(),
            "current_demand": self.current_demand,
            "growth_rate": self.growth_rate,
            "volatility": self.volatility,
            "model_used": self.model_used,
            "features": self.features,
        }


@dataclass
class SkillDemandProjection:
    """
    Multi-horizon demand projection for a skill.
    
    Contains forecasts for all horizons and scenarios.
    """
    skill_id: str
    skill_name: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    short_term: Optional[DemandForecast] = None   # 3 months
    medium_term: Optional[DemandForecast] = None  # 6 months
    long_term: Optional[DemandForecast] = None    # 12 months
    scenarios: Dict[str, DemandForecast] = field(default_factory=dict)
    recommendation: str = ""
    risk_assessment: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "created_at": self.created_at.isoformat(),
            "short_term": self.short_term.to_dict() if self.short_term else None,
            "medium_term": self.medium_term.to_dict() if self.medium_term else None,
            "long_term": self.long_term.to_dict() if self.long_term else None,
            "scenarios": {k: v.to_dict() for k, v in self.scenarios.items()},
            "recommendation": self.recommendation,
            "risk_assessment": self.risk_assessment,
        }


@dataclass
class MarketForecastSnapshot:
    """
    Complete market forecast snapshot.
    """
    snapshot_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    horizon: ForecastHorizon = ForecastHorizon.MEDIUM
    total_skills_forecast: int = 0
    top_growing_skills: List[DemandForecast] = field(default_factory=list)
    top_declining_skills: List[DemandForecast] = field(default_factory=list)
    stable_skills: List[DemandForecast] = field(default_factory=list)
    high_volatility_skills: List[DemandForecast] = field(default_factory=list)
    industry_outlook: Dict[str, float] = field(default_factory=dict)
    overall_market_growth: float = 0.0
    confidence_score: float = 0.0
    summary: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp.isoformat(),
            "horizon": self.horizon.value,
            "total_skills_forecast": self.total_skills_forecast,
            "top_growing_skills": [f.to_dict() for f in self.top_growing_skills],
            "top_declining_skills": [f.to_dict() for f in self.top_declining_skills],
            "stable_skills": [f.to_dict() for f in self.stable_skills],
            "high_volatility_skills": [f.to_dict() for f in self.high_volatility_skills],
            "industry_outlook": self.industry_outlook,
            "overall_market_growth": self.overall_market_growth,
            "confidence_score": self.confidence_score,
            "summary": self.summary,
        }


@dataclass
class ForecastAccuracy:
    """
    Track forecast accuracy over time.
    """
    forecast_id: str
    skill_id: str
    forecast_date: datetime
    target_date: datetime
    predicted_value: float
    actual_value: Optional[float] = None
    error: Optional[float] = None
    error_percentage: Optional[float] = None
    model_used: str = ""
    
    def calculate_error(self, actual: float) -> None:
        """Calculate error once actual value is known."""
        self.actual_value = actual
        self.error = actual - self.predicted_value
        if self.predicted_value != 0:
            self.error_percentage = abs(self.error) / abs(self.predicted_value) * 100


@dataclass
class ModelPerformance:
    """
    Track model performance metrics.
    """
    model_name: str
    horizon: ForecastHorizon
    mae: float = 0.0   # Mean Absolute Error
    mape: float = 0.0  # Mean Absolute Percentage Error
    rmse: float = 0.0  # Root Mean Square Error
    r2: float = 0.0    # R-squared
    directional_accuracy: float = 0.0  # % of correct direction predictions
    sample_size: int = 0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

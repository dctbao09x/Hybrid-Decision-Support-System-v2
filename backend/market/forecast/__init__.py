# backend/market/forecast/__init__.py
"""
Demand Forecasting Engine
=========================

Predictive models for skill demand:
- 3/6/12 month forecasts
- Confidence bands (P50, P80, P95)
- Multiple model ensemble
- Scenario analysis
"""

from .models import (
    DemandForecast,
    ForecastHorizon,
    ForecastScenario,
    ConfidenceBand,
    SkillDemandProjection,
    MarketForecastSnapshot,
)
from .engine import (
    ForecastEngine,
    TimeSeriesModel,
    EnsembleForecaster,
    get_forecast_engine,
)

__all__ = [
    "DemandForecast",
    "ForecastHorizon",
    "ForecastScenario",
    "ConfidenceBand",
    "SkillDemandProjection",
    "MarketForecastSnapshot",
    "ForecastEngine",
    "TimeSeriesModel",
    "EnsembleForecaster",
    "get_forecast_engine",
]

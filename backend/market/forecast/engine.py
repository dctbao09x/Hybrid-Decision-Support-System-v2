# backend/market/forecast/engine.py
"""
Demand Forecasting Engine
=========================

Predictive models for skill demand:
- Exponential smoothing
- ARIMA-like components
- Regression with features
- Ensemble combination
- Monte Carlo confidence bands
"""

from __future__ import annotations

import json
import logging
import math
import random
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from .models import (
    ConfidenceBand,
    DemandForecast,
    ForecastAccuracy,
    ForecastHorizon,
    ForecastScenario,
    MarketForecastSnapshot,
    ModelPerformance,
    SkillDemandProjection,
)

logger = logging.getLogger("market.forecast.engine")


# ═══════════════════════════════════════════════════════════════════════
# Time Series Models
# ═══════════════════════════════════════════════════════════════════════


class TimeSeriesModel(ABC):
    """Base class for time series forecast models."""
    
    name: str = "base"
    
    @abstractmethod
    def fit(self, time_series: List[Tuple[datetime, float]]) -> None:
        """Fit model to historical data."""
        pass
    
    @abstractmethod
    def predict(self, steps: int) -> List[float]:
        """Predict future values."""
        pass
    
    @abstractmethod
    def predict_with_uncertainty(
        self, 
        steps: int, 
        n_samples: int = 1000,
    ) -> List[List[float]]:
        """Generate Monte Carlo samples for uncertainty."""
        pass


class ExponentialSmoothingModel(TimeSeriesModel):
    """
    Triple exponential smoothing (Holt-Winters).
    
    Handles trend and seasonality.
    """
    
    name = "exponential_smoothing"
    
    def __init__(
        self,
        alpha: float = 0.3,  # Level smoothing
        beta: float = 0.1,   # Trend smoothing
        gamma: float = 0.1,  # Seasonal smoothing
        seasonal_period: int = 7,  # Weekly seasonality
    ):
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.seasonal_period = seasonal_period
        
        self._level: float = 0
        self._trend: float = 0
        self._seasonal: List[float] = []
        self._residual_std: float = 1.0
        self._fitted = False
    
    def fit(self, time_series: List[Tuple[datetime, float]]) -> None:
        """Fit model using exponential smoothing."""
        if len(time_series) < self.seasonal_period + 2:
            # Not enough data for full model
            values = [v for _, v in sorted(time_series, key=lambda x: x[0])]
            self._level = sum(values) / len(values) if values else 0
            self._trend = 0
            self._seasonal = [1.0] * self.seasonal_period
            self._fitted = True
            return
        
        values = [v for _, v in sorted(time_series, key=lambda x: x[0])]
        n = len(values)
        
        # Initialize level
        self._level = sum(values[:self.seasonal_period]) / self.seasonal_period
        
        # Initialize trend
        sum1 = sum(values[:self.seasonal_period])
        sum2 = sum(values[self.seasonal_period:2*self.seasonal_period]) if n >= 2*self.seasonal_period else sum1
        self._trend = (sum2 - sum1) / (self.seasonal_period ** 2)
        
        # Initialize seasonal
        self._seasonal = [
            values[i] / self._level if self._level > 0 else 1.0
            for i in range(self.seasonal_period)
        ]
        
        # Fit with smoothing
        residuals = []
        for i, y in enumerate(values):
            s_idx = i % self.seasonal_period
            
            # Forecast
            forecast = (self._level + self._trend) * self._seasonal[s_idx]
            residuals.append(y - forecast)
            
            # Update level
            new_level = self.alpha * (y / self._seasonal[s_idx]) + (1 - self.alpha) * (self._level + self._trend)
            
            # Update trend
            self._trend = self.beta * (new_level - self._level) + (1 - self.beta) * self._trend
            
            # Update seasonal
            self._seasonal[s_idx] = self.gamma * (y / new_level) + (1 - self.gamma) * self._seasonal[s_idx]
            
            self._level = new_level
        
        self._residual_std = np.std(residuals) if residuals else 1.0
        self._fitted = True
    
    def predict(self, steps: int) -> List[float]:
        """Predict future values."""
        if not self._fitted:
            return [0.0] * steps
        
        predictions = []
        level = self._level
        trend = self._trend
        
        for i in range(steps):
            s_idx = i % self.seasonal_period
            pred = (level + (i + 1) * trend) * self._seasonal[s_idx]
            predictions.append(max(0, pred))  # Demand can't be negative
        
        return predictions
    
    def predict_with_uncertainty(
        self,
        steps: int,
        n_samples: int = 1000,
    ) -> List[List[float]]:
        """Generate Monte Carlo samples."""
        base_predictions = self.predict(steps)
        samples = []
        
        for _ in range(n_samples):
            sample = []
            cumulative_error = 0
            
            for i, pred in enumerate(base_predictions):
                # Error grows with forecast horizon
                horizon_factor = math.sqrt(i + 1)
                noise = random.gauss(0, self._residual_std * horizon_factor)
                cumulative_error += noise * 0.1  # Some error persists
                
                value = pred + noise + cumulative_error
                sample.append(max(0, value))
            
            samples.append(sample)
        
        return samples


class LinearTrendModel(TimeSeriesModel):
    """Simple linear trend model."""
    
    name = "linear_trend"
    
    def __init__(self):
        self._slope: float = 0
        self._intercept: float = 0
        self._residual_std: float = 1.0
        self._last_value: float = 0
        self._fitted = False
    
    def fit(self, time_series: List[Tuple[datetime, float]]) -> None:
        """Fit linear regression."""
        if len(time_series) < 2:
            self._fitted = True
            return
        
        sorted_ts = sorted(time_series, key=lambda x: x[0])
        base_time = sorted_ts[0][0]
        
        x = [(ts[0] - base_time).days for ts in sorted_ts]
        y = [ts[1] for ts in sorted_ts]
        
        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_xx = sum(xi * xi for xi in x)
        
        denom = n * sum_xx - sum_x * sum_x
        if denom == 0:
            self._slope = 0
            self._intercept = sum_y / n if n > 0 else 0
        else:
            self._slope = (n * sum_xy - sum_x * sum_y) / denom
            self._intercept = (sum_y - self._slope * sum_x) / n
        
        # Calculate residual std
        predictions = [self._intercept + self._slope * xi for xi in x]
        residuals = [yi - pi for yi, pi in zip(y, predictions)]
        self._residual_std = np.std(residuals) if residuals else 1.0
        
        self._last_value = x[-1]
        self._fitted = True
    
    def predict(self, steps: int) -> List[float]:
        """Predict future values."""
        if not self._fitted:
            return [0.0] * steps
        
        predictions = []
        for i in range(steps):
            day = self._last_value + (i + 1) * 30 / steps  # Assuming monthly steps
            pred = self._intercept + self._slope * day
            predictions.append(max(0, pred))
        
        return predictions
    
    def predict_with_uncertainty(
        self,
        steps: int,
        n_samples: int = 1000,
    ) -> List[List[float]]:
        """Generate Monte Carlo samples."""
        base = self.predict(steps)
        samples = []
        
        for _ in range(n_samples):
            sample = [
                max(0, pred + random.gauss(0, self._residual_std * math.sqrt(i + 1)))
                for i, pred in enumerate(base)
            ]
            samples.append(sample)
        
        return samples


class SeasonalNaiveModel(TimeSeriesModel):
    """Seasonal naive model - uses same season from previous period."""
    
    name = "seasonal_naive"
    
    def __init__(self, seasonal_period: int = 30):
        self.seasonal_period = seasonal_period
        self._seasonal_values: List[float] = []
        self._residual_std: float = 1.0
        self._fitted = False
    
    def fit(self, time_series: List[Tuple[datetime, float]]) -> None:
        """Extract seasonal pattern."""
        if len(time_series) < self.seasonal_period:
            self._seasonal_values = [
                ts[1] for ts in sorted(time_series, key=lambda x: x[0])
            ]
            self._fitted = True
            return
        
        sorted_ts = sorted(time_series, key=lambda x: x[0])
        
        # Average values by day-of-period
        seasonal_sums = [0.0] * self.seasonal_period
        seasonal_counts = [0] * self.seasonal_period
        
        for i, (_, val) in enumerate(sorted_ts):
            idx = i % self.seasonal_period
            seasonal_sums[idx] += val
            seasonal_counts[idx] += 1
        
        self._seasonal_values = [
            seasonal_sums[i] / seasonal_counts[i] if seasonal_counts[i] > 0 else 0
            for i in range(self.seasonal_period)
        ]
        
        # Calculate residual
        residuals = []
        for i, (_, val) in enumerate(sorted_ts):
            idx = i % self.seasonal_period
            residuals.append(val - self._seasonal_values[idx])
        
        self._residual_std = np.std(residuals) if residuals else 1.0
        self._fitted = True
    
    def predict(self, steps: int) -> List[float]:
        """Predict using seasonal pattern."""
        if not self._seasonal_values:
            return [0.0] * steps
        
        predictions = []
        for i in range(steps):
            idx = i % len(self._seasonal_values)
            predictions.append(max(0, self._seasonal_values[idx]))
        
        return predictions
    
    def predict_with_uncertainty(
        self,
        steps: int,
        n_samples: int = 1000,
    ) -> List[List[float]]:
        """Generate Monte Carlo samples."""
        base = self.predict(steps)
        samples = []
        
        for _ in range(n_samples):
            sample = [
                max(0, pred + random.gauss(0, self._residual_std))
                for pred in base
            ]
            samples.append(sample)
        
        return samples


# ═══════════════════════════════════════════════════════════════════════
# Ensemble Forecaster
# ═══════════════════════════════════════════════════════════════════════


class EnsembleForecaster:
    """
    Ensemble of multiple forecasting models.
    
    Combines predictions using weighted average based on
    historical performance.
    """
    
    def __init__(self):
        self._models: List[TimeSeriesModel] = [
            ExponentialSmoothingModel(),
            LinearTrendModel(),
            SeasonalNaiveModel(),
        ]
        
        # Model weights (initially equal)
        self._weights = {model.name: 1.0 / len(self._models) for model in self._models}
        
        # Performance tracking
        self._performance: Dict[str, ModelPerformance] = {}
    
    def fit(self, time_series: List[Tuple[datetime, float]]) -> None:
        """Fit all models."""
        for model in self._models:
            try:
                model.fit(time_series)
            except Exception as e:
                logger.error(f"Model {model.name} fit failed: {e}")
    
    def predict(self, steps: int) -> List[float]:
        """Weighted ensemble prediction."""
        predictions_per_model = []
        total_weight = 0
        
        for model in self._models:
            try:
                preds = model.predict(steps)
                weight = self._weights.get(model.name, 0)
                predictions_per_model.append((preds, weight))
                total_weight += weight
            except Exception as e:
                logger.error(f"Model {model.name} predict failed: {e}")
        
        if not predictions_per_model or total_weight == 0:
            return [0.0] * steps
        
        # Weighted average
        ensemble = [0.0] * steps
        for preds, weight in predictions_per_model:
            for i, p in enumerate(preds):
                ensemble[i] += p * weight / total_weight
        
        return ensemble
    
    def predict_with_confidence(
        self,
        steps: int,
        n_samples: int = 1000,
    ) -> Tuple[List[float], List[ConfidenceBand]]:
        """
        Generate predictions with confidence bands.
        
        Returns:
            Tuple of (point predictions, list of confidence bands per step)
        """
        # Collect samples from all models
        all_samples: List[List[float]] = []
        
        for model in self._models:
            try:
                samples = model.predict_with_uncertainty(steps, n_samples // len(self._models))
                weight = self._weights.get(model.name, 1.0)
                
                # Weight samples
                for sample in samples:
                    weighted = [v * weight for v in sample]
                    all_samples.append(weighted)
            except Exception as e:
                logger.error(f"Model {model.name} uncertainty failed: {e}")
        
        if not all_samples:
            point = self.predict(steps)
            bands = [ConfidenceBand(p, p, p, p, p) for p in point]
            return point, bands
        
        # Compute confidence bands per step
        point_predictions = []
        confidence_bands = []
        
        for step in range(steps):
            step_values = [sample[step] for sample in all_samples if len(sample) > step]
            
            if step_values:
                band = ConfidenceBand.from_samples(step_values)
                confidence_bands.append(band)
                point_predictions.append(band.p50)
            else:
                point_predictions.append(0)
                confidence_bands.append(ConfidenceBand(0, 0, 0, 0, 0))
        
        return point_predictions, confidence_bands
    
    def update_weights(self, performance: Dict[str, float]) -> None:
        """Update model weights based on performance (lower error = higher weight)."""
        total_inv_error = 0
        inv_errors = {}
        
        for model_name, error in performance.items():
            if error > 0:
                inv_error = 1.0 / error
            else:
                inv_error = 10.0  # Perfect performance
            inv_errors[model_name] = inv_error
            total_inv_error += inv_error
        
        if total_inv_error > 0:
            self._weights = {
                name: inv_e / total_inv_error
                for name, inv_e in inv_errors.items()
            }


# ═══════════════════════════════════════════════════════════════════════
# Forecast Engine
# ═══════════════════════════════════════════════════════════════════════


class ForecastEngine:
    """
    Main forecast engine.
    
    Features:
    - Multi-horizon forecasting
    - Scenario analysis
    - Confidence bands
    - Model performance tracking
    - Forecast storage and retrieval
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self._root = Path(__file__).resolve().parents[3]
        self._db_path = db_path or self._root / "storage/market/forecasts.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._lock = RLock()
        self._forecaster = EnsembleForecaster()
        
        # Horizon to days mapping
        self._horizon_days = {
            ForecastHorizon.SHORT: 90,
            ForecastHorizon.MEDIUM: 180,
            ForecastHorizon.LONG: 365,
        }
        
        # Scenario factors
        self._scenario_factors = {
            ForecastScenario.BASELINE: 1.0,
            ForecastScenario.OPTIMISTIC: 1.3,
            ForecastScenario.PESSIMISTIC: 0.7,
            ForecastScenario.DISRUPTION: 0.4,
        }
        
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS forecasts (
                    forecast_id TEXT PRIMARY KEY,
                    skill_id TEXT NOT NULL,
                    horizon TEXT NOT NULL,
                    scenario TEXT NOT NULL,
                    forecast_date TEXT NOT NULL,
                    target_date TEXT NOT NULL,
                    predicted_demand REAL,
                    confidence_p5 REAL,
                    confidence_p20 REAL,
                    confidence_p50 REAL,
                    confidence_p80 REAL,
                    confidence_p95 REAL,
                    current_demand REAL,
                    growth_rate REAL,
                    model_used TEXT,
                    features TEXT
                );
                
                CREATE TABLE IF NOT EXISTS forecast_accuracy (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    forecast_id TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    forecast_date TEXT NOT NULL,
                    target_date TEXT NOT NULL,
                    predicted_value REAL,
                    actual_value REAL,
                    error REAL,
                    error_pct REAL,
                    model_used TEXT,
                    UNIQUE(forecast_id)
                );
                
                CREATE TABLE IF NOT EXISTS model_performance (
                    model_name TEXT NOT NULL,
                    horizon TEXT NOT NULL,
                    mae REAL,
                    mape REAL,
                    rmse REAL,
                    r2 REAL,
                    directional_accuracy REAL,
                    sample_size INTEGER,
                    updated_at TEXT,
                    PRIMARY KEY (model_name, horizon)
                );
                
                CREATE INDEX IF NOT EXISTS idx_forecasts_skill ON forecasts(skill_id);
                CREATE INDEX IF NOT EXISTS idx_accuracy_skill ON forecast_accuracy(skill_id);
            """)
    
    def forecast_skill(
        self,
        skill_id: str,
        historical_data: List[Tuple[datetime, float]],
        horizon: ForecastHorizon = ForecastHorizon.MEDIUM,
        scenario: ForecastScenario = ForecastScenario.BASELINE,
    ) -> DemandForecast:
        """
        Generate demand forecast for a single skill.
        
        Args:
            skill_id: Skill identifier
            historical_data: Historical demand data [(timestamp, value)]
            horizon: Forecast horizon
            scenario: Forecast scenario
        
        Returns:
            DemandForecast with predictions and confidence bands
        """
        # Fit models
        self._forecaster.fit(historical_data)
        
        # Determine number of steps based on horizon
        days = self._horizon_days[horizon]
        steps = days // 7  # Weekly steps
        
        # Get predictions with confidence
        point_preds, bands = self._forecaster.predict_with_confidence(steps)
        
        # Apply scenario factor
        factor = self._scenario_factors[scenario]
        if factor != 1.0:
            point_preds = [p * factor for p in point_preds]
            bands = [
                ConfidenceBand(
                    b.p5 * factor,
                    b.p20 * factor,
                    b.p50 * factor,
                    b.p80 * factor,
                    b.p95 * factor,
                )
                for b in bands
            ]
        
        # Final values (end of horizon)
        final_pred = point_preds[-1] if point_preds else 0
        final_band = bands[-1] if bands else ConfidenceBand(0, 0, 0, 0, 0)
        
        # Current demand (last historical value)
        current = historical_data[-1][1] if historical_data else 0
        
        # Growth rate
        growth_rate = (final_pred - current) / current if current > 0 else 0
        
        # Calculate volatility
        if len(point_preds) > 1:
            changes = [
                (point_preds[i] - point_preds[i-1]) / point_preds[i-1] 
                if point_preds[i-1] > 0 else 0
                for i in range(1, len(point_preds))
            ]
            volatility = np.std(changes) if changes else 0
        else:
            volatility = 0
        
        forecast = DemandForecast(
            skill_id=skill_id,
            skill_name=skill_id,  # Would be resolved from taxonomy
            horizon=horizon,
            forecast_date=datetime.now(timezone.utc),
            target_date=datetime.now(timezone.utc) + timedelta(days=days),
            scenario=scenario,
            predicted_demand=final_pred,
            confidence=final_band,
            current_demand=current,
            growth_rate=growth_rate,
            volatility=volatility,
            model_used="ensemble",
        )
        
        # Save forecast
        self._save_forecast(forecast)
        
        return forecast
    
    def forecast_skill_all_horizons(
        self,
        skill_id: str,
        historical_data: List[Tuple[datetime, float]],
    ) -> SkillDemandProjection:
        """Generate forecasts for all horizons."""
        projection = SkillDemandProjection(
            skill_id=skill_id,
            skill_name=skill_id,
        )
        
        projection.short_term = self.forecast_skill(
            skill_id, historical_data, ForecastHorizon.SHORT
        )
        projection.medium_term = self.forecast_skill(
            skill_id, historical_data, ForecastHorizon.MEDIUM
        )
        projection.long_term = self.forecast_skill(
            skill_id, historical_data, ForecastHorizon.LONG
        )
        
        # Generate scenarios for medium term
        for scenario in ForecastScenario:
            projection.scenarios[scenario.value] = self.forecast_skill(
                skill_id, historical_data, ForecastHorizon.MEDIUM, scenario
            )
        
        # Generate recommendation
        projection.recommendation = self._generate_recommendation(projection)
        projection.risk_assessment = self._assess_risk(projection)
        
        return projection
    
    def _generate_recommendation(self, proj: SkillDemandProjection) -> str:
        """Generate investment recommendation based on forecasts."""
        if not proj.medium_term:
            return "Insufficient data for recommendation"
        
        growth = proj.medium_term.growth_rate
        volatility = proj.medium_term.volatility
        confidence_width = (
            proj.medium_term.confidence.p95 - proj.medium_term.confidence.p5
        ) / proj.medium_term.confidence.p50 if proj.medium_term.confidence.p50 > 0 else 1
        
        if growth > 0.3 and volatility < 0.2:
            return "Strong investment signal - high growth, low volatility"
        elif growth > 0.1 and volatility < 0.3:
            return "Moderate investment signal - steady growth"
        elif growth > 0 and confidence_width < 0.5:
            return "Consider modest investment - stable with some growth"
        elif growth < -0.1:
            return "Caution advised - declining demand expected"
        else:
            return "Neutral - monitor for changes"
    
    def _assess_risk(self, proj: SkillDemandProjection) -> str:
        """Assess forecast risk level."""
        if not proj.medium_term:
            return "Unknown risk - insufficient data"
        
        volatility = proj.medium_term.volatility
        
        # Compare pessimistic vs optimistic scenarios
        if proj.scenarios:
            pess = proj.scenarios.get("pessimistic")
            opt = proj.scenarios.get("optimistic")
            if pess and opt:
                scenario_spread = abs(opt.predicted_demand - pess.predicted_demand)
                relative_spread = scenario_spread / proj.medium_term.predicted_demand if proj.medium_term.predicted_demand > 0 else 1
                
                if relative_spread > 0.6:
                    return "High risk - large scenario spread indicates significant uncertainty"
                elif relative_spread > 0.3:
                    return "Medium risk - moderate uncertainty across scenarios"
        
        if volatility > 0.3:
            return "Medium-high risk - elevated volatility"
        elif volatility > 0.15:
            return "Medium risk - some volatility"
        else:
            return "Low risk - stable forecast"
    
    def _save_forecast(self, forecast: DemandForecast) -> None:
        """Save forecast to database."""
        forecast_id = f"fc_{forecast.skill_id}_{forecast.horizon.value}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO forecasts
                (forecast_id, skill_id, horizon, scenario, forecast_date, target_date,
                 predicted_demand, confidence_p5, confidence_p20, confidence_p50,
                 confidence_p80, confidence_p95, current_demand, growth_rate,
                 model_used, features)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                forecast_id,
                forecast.skill_id,
                forecast.horizon.value,
                forecast.scenario.value,
                forecast.forecast_date.isoformat(),
                forecast.target_date.isoformat(),
                forecast.predicted_demand,
                forecast.confidence.p5,
                forecast.confidence.p20,
                forecast.confidence.p50,
                forecast.confidence.p80,
                forecast.confidence.p95,
                forecast.current_demand,
                forecast.growth_rate,
                forecast.model_used,
                json.dumps(forecast.features),
            ))
    
    def create_market_snapshot(
        self,
        skill_forecasts: List[Tuple[str, List[Tuple[datetime, float]]]],
        horizon: ForecastHorizon = ForecastHorizon.MEDIUM,
    ) -> MarketForecastSnapshot:
        """Create complete market forecast snapshot."""
        snapshot_id = f"msnap_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        
        all_forecasts = []
        for skill_id, data in skill_forecasts:
            forecast = self.forecast_skill(skill_id, data, horizon)
            all_forecasts.append(forecast)
        
        # Sort by growth
        sorted_by_growth = sorted(all_forecasts, key=lambda f: f.growth_rate, reverse=True)
        
        top_growing = [f for f in sorted_by_growth[:10] if f.growth_rate > 0]
        top_declining = [f for f in sorted_by_growth[-10:] if f.growth_rate < 0][::-1]
        stable = [f for f in sorted_by_growth if -0.05 <= f.growth_rate <= 0.05]
        high_vol = sorted([f for f in all_forecasts if f.volatility > 0.2], key=lambda f: -f.volatility)[:10]
        
        # Overall market growth
        if all_forecasts:
            total_current = sum(f.current_demand for f in all_forecasts)
            total_predicted = sum(f.predicted_demand for f in all_forecasts)
            overall_growth = (total_predicted - total_current) / total_current if total_current > 0 else 0
        else:
            overall_growth = 0
        
        # Calculate average confidence
        if all_forecasts:
            avg_confidence = 1.0 - np.mean([f.volatility for f in all_forecasts])
        else:
            avg_confidence = 0
        
        # Summary
        summary_parts = []
        if top_growing:
            summary_parts.append(f"Top growers: {', '.join(f.skill_name for f in top_growing[:3])}")
        if top_declining:
            summary_parts.append(f"Declining: {', '.join(f.skill_name for f in top_declining[:3])}")
        summary_parts.append(f"Overall market growth: {overall_growth:.1%}")
        
        snapshot = MarketForecastSnapshot(
            snapshot_id=snapshot_id,
            horizon=horizon,
            total_skills_forecast=len(all_forecasts),
            top_growing_skills=top_growing,
            top_declining_skills=top_declining,
            stable_skills=stable[:10],
            high_volatility_skills=high_vol,
            overall_market_growth=overall_growth,
            confidence_score=avg_confidence,
            summary="; ".join(summary_parts),
        )
        
        return snapshot
    
    def record_actual(
        self,
        skill_id: str,
        target_date: datetime,
        actual_value: float,
    ) -> None:
        """Record actual value for forecast validation."""
        with sqlite3.connect(str(self._db_path)) as conn:
            # Find matching forecasts
            rows = conn.execute("""
                SELECT forecast_id, predicted_demand
                FROM forecasts
                WHERE skill_id = ? AND DATE(target_date) = DATE(?)
            """, (skill_id, target_date.isoformat())).fetchall()
            
            for forecast_id, predicted in rows:
                error = actual_value - predicted
                error_pct = abs(error) / predicted * 100 if predicted > 0 else 0
                
                conn.execute("""
                    INSERT OR REPLACE INTO forecast_accuracy
                    (forecast_id, skill_id, forecast_date, target_date,
                     predicted_value, actual_value, error, error_pct, model_used)
                    VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?, 'ensemble')
                """, (
                    forecast_id,
                    skill_id,
                    target_date.isoformat(),
                    predicted,
                    actual_value,
                    error,
                    error_pct,
                ))
    
    def get_model_performance(self) -> Dict[str, ModelPerformance]:
        """Get performance metrics for all models."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            
            result = {}
            for row in conn.execute("SELECT * FROM model_performance"):
                result[f"{row['model_name']}_{row['horizon']}"] = ModelPerformance(
                    model_name=row["model_name"],
                    horizon=ForecastHorizon(row["horizon"]),
                    mae=row["mae"] or 0,
                    mape=row["mape"] or 0,
                    rmse=row["rmse"] or 0,
                    r2=row["r2"] or 0,
                    directional_accuracy=row["directional_accuracy"] or 0,
                    sample_size=row["sample_size"] or 0,
                )
            
            return result


# ═══════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════

_engine: Optional[ForecastEngine] = None


def get_forecast_engine() -> ForecastEngine:
    """Get singleton ForecastEngine instance."""
    global _engine
    if _engine is None:
        _engine = ForecastEngine()
    return _engine

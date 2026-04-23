# backend/ops/cost/intelligence.py
"""
Cost Intelligence Engine
========================

Advanced cost analytics with:
- Trend prediction (3-6 months)
- Anomaly detection
- Budget forecasting
- Cost optimization recommendations
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from backend.ops.cost.models import (
    BudgetPeriod,
    BudgetStatus,
    CostCategory,
    CostForecast,
)
from backend.ops.cost.budget_manager import BudgetManager, get_budget_manager

logger = logging.getLogger("ops.cost.intelligence")


class TrendDirection(str, Enum):
    """Cost trend direction."""
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    VOLATILE = "volatile"


class AnomalyType(str, Enum):
    """Types of cost anomalies."""
    SPIKE = "spike"         # Sudden increase
    DROP = "drop"           # Sudden decrease
    DRIFT = "drift"         # Gradual unexpected change
    PATTERN = "pattern"     # Unusual pattern
    THRESHOLD = "threshold" # Threshold breach


@dataclass
class CostAnomaly:
    """Detected cost anomaly."""
    anomaly_id: str
    anomaly_type: AnomalyType
    budget_id: Optional[str]
    category: Optional[CostCategory]
    detected_at: str
    anomaly_score: float               # 0-1, higher = more anomalous
    expected_value: float
    actual_value: float
    deviation_percentage: float
    description: str
    severity: str = "medium"           # low, medium, high, critical
    resolved: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "anomaly_id": self.anomaly_id,
            "anomaly_type": self.anomaly_type.value,
            "budget_id": self.budget_id,
            "category": self.category.value if self.category else None,
            "detected_at": self.detected_at,
            "anomaly_score": round(self.anomaly_score, 4),
            "expected_value": round(self.expected_value, 2),
            "actual_value": round(self.actual_value, 2),
            "deviation_percentage": round(self.deviation_percentage, 2),
            "description": self.description,
            "severity": self.severity,
            "resolved": self.resolved,
        }


@dataclass
class CostTrend:
    """Cost trend analysis result."""
    budget_id: str
    direction: TrendDirection
    slope: float                       # Rate of change per day
    confidence: float
    forecast_30_days: float
    forecast_60_days: float
    forecast_90_days: float
    data_points: int
    analysis_period_days: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "budget_id": self.budget_id,
            "direction": self.direction.value,
            "slope": round(self.slope, 4),
            "confidence": round(self.confidence, 4),
            "forecast_30_days": round(self.forecast_30_days, 2),
            "forecast_60_days": round(self.forecast_60_days, 2),
            "forecast_90_days": round(self.forecast_90_days, 2),
            "data_points": self.data_points,
            "analysis_period_days": self.analysis_period_days,
        }


@dataclass
class CostRecommendation:
    """Cost optimization recommendation."""
    recommendation_id: str
    category: str
    title: str
    description: str
    estimated_savings: float
    effort: str                        # low, medium, high
    priority: str                      # low, medium, high, critical
    implementation_steps: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "estimated_savings": round(self.estimated_savings, 2),
            "effort": self.effort,
            "priority": self.priority,
            "implementation_steps": self.implementation_steps,
        }


class CostIntelligence:
    """
    Cost intelligence and forecasting engine.
    
    Features:
    - Exponential smoothing forecasts
    - Z-score anomaly detection
    - Trend analysis
    - Cost optimization recommendations
    """
    
    def __init__(self, budget_manager: Optional[BudgetManager] = None):
        self._manager = budget_manager or get_budget_manager()
        
        # Anomaly detection parameters
        self._zscore_threshold = 2.5   # Standard deviations for anomaly
        self._min_data_points = 7      # Minimum data points for analysis
        
        # Forecasting parameters
        self._alpha = 0.3              # Exponential smoothing parameter
        
        # Detected anomalies
        self._anomalies: List[CostAnomaly] = []
    
    # ═══════════════════════════════════════════════════════════════════
    # Forecasting
    # ═══════════════════════════════════════════════════════════════════
    
    def forecast_budget(
        self,
        budget_id: str,
        forecast_days: int = 30,
    ) -> Optional[CostForecast]:
        """
        Generate cost forecast for a budget.
        
        Uses exponential smoothing with trend detection.
        """
        budget = self._manager.get_budget(budget_id)
        if not budget:
            return None
        
        # Get historical data
        historical = self._get_daily_costs(budget_id, days=90)
        if len(historical) < self._min_data_points:
            logger.warning(f"Insufficient data for forecast: {len(historical)} points")
            return None
        
        # Apply exponential smoothing
        smoothed = self._exponential_smoothing(historical)
        
        # Calculate trend
        trend_slope = self._calculate_trend_slope(historical)
        
        # Generate forecast
        last_value = smoothed[-1] if smoothed else 0
        forecast_value = last_value + (trend_slope * forecast_days)
        
        # Calculate confidence interval (simplified)
        std_dev = self._calculate_std_dev(historical)
        confidence_margin = std_dev * 1.96 * math.sqrt(forecast_days / 30)
        
        # Detect trend direction
        if trend_slope > 0.01 * last_value:
            trend = "increasing"
        elif trend_slope < -0.01 * last_value:
            trend = "decreasing"
        else:
            trend = "stable"
        
        # Check for anomaly
        anomaly_score = self._calculate_anomaly_score(historical)
        
        forecast = CostForecast(
            forecast_id=f"fcst_{budget_id}_{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            budget_id=budget_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            forecast_date=(datetime.now(timezone.utc) + timedelta(days=forecast_days)).isoformat(),
            predicted_spend=max(0, forecast_value),
            confidence_lower=max(0, forecast_value - confidence_margin),
            confidence_upper=forecast_value + confidence_margin,
            method="exponential_smoothing",
            trend=trend,
            anomaly_detected=anomaly_score > 0.7,
            anomaly_score=anomaly_score,
            recommendations=self._generate_forecast_recommendations(budget, forecast_value, trend),
        )
        
        return forecast
    
    def forecast_all_budgets(self, forecast_days: int = 30) -> List[CostForecast]:
        """Generate forecasts for all active budgets."""
        forecasts = []
        for budget in self._manager.list_budgets(enabled_only=True):
            forecast = self.forecast_budget(budget.budget_id, forecast_days)
            if forecast:
                forecasts.append(forecast)
        return forecasts
    
    # ═══════════════════════════════════════════════════════════════════
    # Trend Analysis
    # ═══════════════════════════════════════════════════════════════════
    
    def analyze_trend(self, budget_id: str, days: int = 90) -> Optional[CostTrend]:
        """Analyze cost trend for a budget."""
        historical = self._get_daily_costs(budget_id, days=days)
        if len(historical) < self._min_data_points:
            return None
        
        slope = self._calculate_trend_slope(historical)
        std_dev = self._calculate_std_dev(historical)
        mean = sum(historical) / len(historical) if historical else 0
        
        # Determine direction
        if std_dev > 0.3 * mean:
            direction = TrendDirection.VOLATILE
        elif slope > 0.01 * mean:
            direction = TrendDirection.INCREASING
        elif slope < -0.01 * mean:
            direction = TrendDirection.DECREASING
        else:
            direction = TrendDirection.STABLE
        
        # Confidence based on R-squared
        r_squared = self._calculate_r_squared(historical)
        
        # Forecasts
        last_value = historical[-1] if historical else 0
        
        return CostTrend(
            budget_id=budget_id,
            direction=direction,
            slope=slope,
            confidence=r_squared,
            forecast_30_days=max(0, last_value + slope * 30),
            forecast_60_days=max(0, last_value + slope * 60),
            forecast_90_days=max(0, last_value + slope * 90),
            data_points=len(historical),
            analysis_period_days=days,
        )
    
    # ═══════════════════════════════════════════════════════════════════
    # Anomaly Detection
    # ═══════════════════════════════════════════════════════════════════
    
    def detect_anomalies(self, budget_id: Optional[str] = None) -> List[CostAnomaly]:
        """
        Detect cost anomalies using Z-score method.
        
        Args:
            budget_id: Specific budget to check, or None for all
        """
        anomalies: List[CostAnomaly] = []
        
        if budget_id:
            budgets = [self._manager.get_budget(budget_id)]
        else:
            budgets = self._manager.list_budgets(enabled_only=True)
        
        for budget in budgets:
            if not budget:
                continue
            
            historical = self._get_daily_costs(budget.budget_id, days=30)
            if len(historical) < self._min_data_points:
                continue
            
            # Calculate statistics
            mean = sum(historical) / len(historical)
            std_dev = self._calculate_std_dev(historical)
            
            if std_dev == 0:
                continue
            
            # Check today's value
            today_cost = historical[-1] if historical else 0
            zscore = abs(today_cost - mean) / std_dev
            
            if zscore > self._zscore_threshold:
                anomaly_type = AnomalyType.SPIKE if today_cost > mean else AnomalyType.DROP
                deviation = ((today_cost - mean) / mean) * 100 if mean > 0 else 0
                
                severity = "low"
                if zscore > 4:
                    severity = "critical"
                elif zscore > 3.5:
                    severity = "high"
                elif zscore > 3:
                    severity = "medium"
                
                anomaly = CostAnomaly(
                    anomaly_id=f"anom_{budget.budget_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                    anomaly_type=anomaly_type,
                    budget_id=budget.budget_id,
                    category=None,
                    detected_at=datetime.now(timezone.utc).isoformat(),
                    anomaly_score=min(1.0, zscore / 5),
                    expected_value=mean,
                    actual_value=today_cost,
                    deviation_percentage=deviation,
                    description=f"Cost {anomaly_type.value} detected: ${today_cost:.2f} vs expected ${mean:.2f} (Z={zscore:.2f})",
                    severity=severity,
                )
                
                anomalies.append(anomaly)
                self._anomalies.append(anomaly)
        
        return anomalies
    
    # ═══════════════════════════════════════════════════════════════════
    # Recommendations
    # ═══════════════════════════════════════════════════════════════════
    
    def generate_recommendations(self) -> List[CostRecommendation]:
        """Generate cost optimization recommendations."""
        recommendations: List[CostRecommendation] = []
        
        # Check budget utilizations
        for status in self._manager.get_all_budget_statuses():
            budget = self._manager.get_budget(status.budget_id)
            if not budget:
                continue
            
            utilization = status.utilization_percentage
            
            # High utilization recommendation
            if utilization > 0.8:
                recommendations.append(CostRecommendation(
                    recommendation_id=f"rec_util_{status.budget_id}",
                    category="Budget Management",
                    title=f"Review {budget.name} Budget",
                    description=f"Budget is at {utilization*100:.1f}% utilization. Consider increasing budget or optimizing usage.",
                    estimated_savings=0,
                    effort="low",
                    priority="high" if utilization > 0.9 else "medium",
                    implementation_steps=[
                        "Review recent cost drivers",
                        "Identify optimization opportunities",
                        "Consider budget adjustment",
                    ],
                ))
            
            # Analyze trends
            trend = self.analyze_trend(status.budget_id, days=30)
            if trend and trend.direction == TrendDirection.INCREASING:
                projected_excess = trend.forecast_30_days - budget.amount_usd
                if projected_excess > 0:
                    recommendations.append(CostRecommendation(
                        recommendation_id=f"rec_trend_{status.budget_id}",
                        category="Trend Alert",
                        title=f"Rising Cost Trend for {budget.name}",
                        description=f"Costs are trending up. Projected to exceed budget by ${projected_excess:.2f} in 30 days.",
                        estimated_savings=projected_excess,
                        effort="medium",
                        priority="high",
                        implementation_steps=[
                            "Investigate cost increase drivers",
                            "Implement usage optimization",
                            "Consider caching strategies",
                            "Review service configurations",
                        ],
                    ))
        
        # LLM optimization recommendation  
        llm_status = self._manager.get_budget_status("budget_llm_daily")
        if llm_status and llm_status.utilization_percentage > 0.5:
            recommendations.append(CostRecommendation(
                recommendation_id="rec_llm_opt",
                category="LLM Optimization",
                title="Optimize LLM Usage",
                description="Consider using smaller models for simpler tasks or implementing response caching.",
                estimated_savings=llm_status.spent_amount * 0.2,
                effort="medium",
                priority="medium",
                implementation_steps=[
                    "Implement semantic caching for repeated queries",
                    "Use smaller models for classification tasks",
                    "Batch similar requests where possible",
                    "Monitor and limit token usage per request",
                ],
            ))
        
        return recommendations
    
    def _generate_forecast_recommendations(
        self,
        budget,
        forecast_value: float,
        trend: str,
    ) -> List[str]:
        """Generate recommendations based on forecast."""
        recs: List[str] = []
        
        if forecast_value > budget.amount_usd:
            excess = forecast_value - budget.amount_usd
            recs.append(f"Projected to exceed budget by ${excess:.2f}")
            recs.append("Consider reducing usage or increasing budget")
        
        if trend == "increasing":
            recs.append("Costs are trending upward - investigate drivers")
        
        return recs
    
    # ═══════════════════════════════════════════════════════════════════
    # Helper Methods
    # ═══════════════════════════════════════════════════════════════════
    
    def _get_daily_costs(self, budget_id: str, days: int = 30) -> List[float]:
        """Get daily cost totals for a budget."""
        budget = self._manager.get_budget(budget_id)
        if not budget:
            return []
        
        daily_costs: List[float] = []
        end_date = datetime.now(timezone.utc)
        
        for i in range(days, 0, -1):
            day = end_date - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            
            total = self._manager.get_total_spent(
                day_start,
                day_end,
                budget.categories or None,
                service=budget.scope_id if budget.scope.value == "service" else None,
            )
            daily_costs.append(total)
        
        return daily_costs
    
    def _exponential_smoothing(self, data: List[float]) -> List[float]:
        """Apply exponential smoothing to time series."""
        if not data:
            return []
        
        smoothed = [data[0]]
        for i in range(1, len(data)):
            smoothed.append(self._alpha * data[i] + (1 - self._alpha) * smoothed[-1])
        
        return smoothed
    
    def _calculate_trend_slope(self, data: List[float]) -> float:
        """Calculate linear trend slope."""
        if len(data) < 2:
            return 0.0
        
        n = len(data)
        x_mean = (n - 1) / 2
        y_mean = sum(data) / n
        
        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(data))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            return 0.0
        
        return numerator / denominator
    
    def _calculate_std_dev(self, data: List[float]) -> float:
        """Calculate standard deviation."""
        if len(data) < 2:
            return 0.0
        
        mean = sum(data) / len(data)
        variance = sum((x - mean) ** 2 for x in data) / len(data)
        return math.sqrt(variance)
    
    def _calculate_r_squared(self, data: List[float]) -> float:
        """Calculate R-squared for linear fit."""
        if len(data) < 2:
            return 0.0
        
        n = len(data)
        y_mean = sum(data) / n
        
        # Total sum of squares
        ss_tot = sum((y - y_mean) ** 2 for y in data)
        if ss_tot == 0:
            return 1.0
        
        # Residual sum of squares (from linear fit)
        slope = self._calculate_trend_slope(data)
        intercept = y_mean - slope * ((n - 1) / 2)
        predicted = [intercept + slope * i for i in range(n)]
        ss_res = sum((y - p) ** 2 for y, p in zip(data, predicted))
        
        return 1 - (ss_res / ss_tot)
    
    def _calculate_anomaly_score(self, data: List[float]) -> float:
        """Calculate overall anomaly score for recent data."""
        if len(data) < 3:
            return 0.0
        
        # Check variability
        std_dev = self._calculate_std_dev(data)
        mean = sum(data) / len(data) if data else 1
        cv = std_dev / mean if mean > 0 else 0
        
        # High coefficient of variation indicates anomalous behavior
        return min(1.0, cv / 0.5)
    
    # ═══════════════════════════════════════════════════════════════════
    # Dashboard Data
    # ═══════════════════════════════════════════════════════════════════
    
    def get_intelligence_dashboard(self) -> Dict[str, Any]:
        """Get cost intelligence dashboard data."""
        forecasts = self.forecast_all_budgets(30)
        trends = []
        for budget in self._manager.list_budgets(enabled_only=True):
            trend = self.analyze_trend(budget.budget_id)
            if trend:
                trends.append(trend.to_dict())
        
        anomalies = self.detect_anomalies()
        recommendations = self.generate_recommendations()
        
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "forecasts": [f.to_dict() for f in forecasts],
            "trends": trends,
            "anomalies": [a.to_dict() for a in anomalies],
            "recommendations": [r.to_dict() for r in recommendations],
            "summary": {
                "total_forecasts": len(forecasts),
                "increasing_trends": sum(1 for t in trends if t["direction"] == "increasing"),
                "active_anomalies": len([a for a in anomalies if not a.resolved]),
                "critical_recommendations": len([r for r in recommendations if r.priority == "critical" or r.priority == "high"]),
            },
        }


# ═══════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════

_cost_intelligence: Optional[CostIntelligence] = None


def get_cost_intelligence() -> CostIntelligence:
    """Get singleton CostIntelligence instance."""
    global _cost_intelligence
    if _cost_intelligence is None:
        _cost_intelligence = CostIntelligence()
    return _cost_intelligence

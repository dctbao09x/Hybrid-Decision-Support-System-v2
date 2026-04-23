# backend/ops/cost/models.py
"""
Cost & Budget Models
====================

Enterprise-grade cost governance data structures:
- Budget definitions (monthly/quarterly/annual)
- Per-service, per-user, per-project budgets
- Hard/soft limits
- Cost records with granular tracking
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class BudgetPeriod(str, Enum):
    """Budget time periods."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class BudgetScope(str, Enum):
    """Budget scope types."""
    GLOBAL = "global"
    SERVICE = "service"
    USER = "user"
    PROJECT = "project"
    MODEL = "model"
    DEPARTMENT = "department"


class LimitType(str, Enum):
    """Limit enforcement types."""
    SOFT = "soft"      # Warning only
    HARD = "hard"      # Enforce stop


class CostCategory(str, Enum):
    """Cost categories for tracking."""
    COMPUTE = "compute"
    STORAGE = "storage"
    API_CALLS = "api_calls"
    LLM_USAGE = "llm_usage"
    INFERENCE = "inference"
    RETRAIN = "retrain"
    EMBEDDING = "embedding"
    BANDWIDTH = "bandwidth"
    EXTERNAL_API = "external_api"


class AlertLevel(str, Enum):
    """Cost alert severity levels."""
    INFO = "info"           # 50% threshold
    WARNING = "warning"     # 70% threshold
    CRITICAL = "critical"   # 85% threshold
    EMERGENCY = "emergency" # 95% threshold (hard stop)


class EnforcementAction(str, Enum):
    """Enforcement actions when limits exceeded."""
    NOTIFY = "notify"
    THROTTLE = "throttle"
    DEGRADE = "degrade"
    SHUTDOWN = "shutdown"
    ESCALATE = "escalate"


@dataclass
class BudgetThreshold:
    """Threshold configuration for a budget."""
    percentage: float          # 0.0 - 1.0
    alert_level: AlertLevel
    action: EnforcementAction
    notify_channels: List[str] = field(default_factory=list)
    auto_resolve: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "percentage": self.percentage,
            "alert_level": self.alert_level.value,
            "action": self.action.value,
            "notify_channels": self.notify_channels,
            "auto_resolve": self.auto_resolve,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BudgetThreshold":
        return cls(
            percentage=data["percentage"],
            alert_level=AlertLevel(data["alert_level"]),
            action=EnforcementAction(data["action"]),
            notify_channels=data.get("notify_channels", []),
            auto_resolve=data.get("auto_resolve", False),
        )


@dataclass
class BudgetDefinition:
    """
    Budget definition with limits and thresholds.
    
    Supports hierarchical budgets:
    - Global org budget
    - Per-service budget
    - Per-user/project budget
    """
    budget_id: str
    name: str
    description: str
    scope: BudgetScope
    scope_id: str                      # Service name, user_id, project_id, etc.
    period: BudgetPeriod
    amount_usd: float                  # Budget amount in USD
    limit_type: LimitType
    thresholds: List[BudgetThreshold] = field(default_factory=list)
    categories: List[CostCategory] = field(default_factory=list)  # Empty = all
    enabled: bool = True
    rollover: bool = False             # Carry unused budget to next period
    parent_budget_id: Optional[str] = None  # For hierarchical budgets
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.thresholds:
            self.thresholds = self._default_thresholds()
    
    def _default_thresholds(self) -> List[BudgetThreshold]:
        """Default threshold configuration."""
        return [
            BudgetThreshold(0.50, AlertLevel.INFO, EnforcementAction.NOTIFY, ["log"]),
            BudgetThreshold(0.70, AlertLevel.WARNING, EnforcementAction.NOTIFY, ["log", "email"]),
            BudgetThreshold(0.85, AlertLevel.CRITICAL, EnforcementAction.THROTTLE, ["log", "email", "slack"]),
            BudgetThreshold(0.95, AlertLevel.EMERGENCY, EnforcementAction.SHUTDOWN, ["log", "email", "slack", "pagerduty"]),
        ]
    
    @property
    def warning_threshold(self) -> float:
        """Get warning threshold (70%)."""
        for t in self.thresholds:
            if t.alert_level == AlertLevel.WARNING:
                return t.percentage
        return 0.70
    
    @property
    def critical_threshold(self) -> float:
        """Get critical threshold (85%)."""
        for t in self.thresholds:
            if t.alert_level == AlertLevel.CRITICAL:
                return t.percentage
        return 0.85
    
    @property
    def emergency_threshold(self) -> float:
        """Get emergency/hard stop threshold (95%)."""
        for t in self.thresholds:
            if t.alert_level == AlertLevel.EMERGENCY:
                return t.percentage
        return 0.95
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "budget_id": self.budget_id,
            "name": self.name,
            "description": self.description,
            "scope": self.scope.value,
            "scope_id": self.scope_id,
            "period": self.period.value,
            "amount_usd": self.amount_usd,
            "limit_type": self.limit_type.value,
            "thresholds": [t.to_dict() for t in self.thresholds],
            "categories": [c.value for c in self.categories],
            "enabled": self.enabled,
            "rollover": self.rollover,
            "parent_budget_id": self.parent_budget_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BudgetDefinition":
        return cls(
            budget_id=data["budget_id"],
            name=data["name"],
            description=data.get("description", ""),
            scope=BudgetScope(data["scope"]),
            scope_id=data["scope_id"],
            period=BudgetPeriod(data["period"]),
            amount_usd=data["amount_usd"],
            limit_type=LimitType(data.get("limit_type", "soft")),
            thresholds=[BudgetThreshold.from_dict(t) for t in data.get("thresholds", [])],
            categories=[CostCategory(c) for c in data.get("categories", [])],
            enabled=data.get("enabled", True),
            rollover=data.get("rollover", False),
            parent_budget_id=data.get("parent_budget_id"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class CostEntry:
    """
    Individual cost entry with granular tracking.
    
    Tracks costs for:
    - Compute (CPU/GPU time)
    - Storage
    - API calls
    - LLM usage (tokens)
    - Inference
    - Retraining
    """
    entry_id: str
    timestamp: str
    category: CostCategory
    amount_usd: float
    quantity: float = 1.0              # Units (tokens, calls, MB, hours)
    unit: str = "unit"                 # Unit type
    service: str = ""
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    model_id: Optional[str] = None
    trace_id: Optional[str] = None
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "category": self.category.value,
            "amount_usd": round(self.amount_usd, 6),
            "quantity": self.quantity,
            "unit": self.unit,
            "service": self.service,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "model_id": self.model_id,
            "trace_id": self.trace_id,
            "description": self.description,
            "metadata": self.metadata,
        }


@dataclass
class BudgetStatus:
    """Current status of a budget."""
    budget_id: str
    budget_name: str
    period: BudgetPeriod
    period_start: str
    period_end: str
    budget_amount: float
    spent_amount: float
    remaining_amount: float
    utilization_percentage: float
    current_alert_level: Optional[AlertLevel] = None
    is_exceeded: bool = False
    is_hard_limited: bool = False
    enforcement_active: bool = False
    active_action: Optional[EnforcementAction] = None
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    @property
    def is_warning(self) -> bool:
        return self.utilization_percentage >= 0.70
    
    @property
    def is_critical(self) -> bool:
        return self.utilization_percentage >= 0.85
    
    @property
    def is_emergency(self) -> bool:
        return self.utilization_percentage >= 0.95
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "budget_id": self.budget_id,
            "budget_name": self.budget_name,
            "period": self.period.value,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "budget_amount": round(self.budget_amount, 2),
            "spent_amount": round(self.spent_amount, 2),
            "remaining_amount": round(self.remaining_amount, 2),
            "utilization_percentage": round(self.utilization_percentage * 100, 2),
            "current_alert_level": self.current_alert_level.value if self.current_alert_level else None,
            "is_exceeded": self.is_exceeded,
            "is_hard_limited": self.is_hard_limited,
            "enforcement_active": self.enforcement_active,
            "active_action": self.active_action.value if self.active_action else None,
            "last_updated": self.last_updated,
        }


@dataclass
class CostForecast:
    """Cost forecast prediction."""
    forecast_id: str
    budget_id: str
    generated_at: str
    forecast_date: str
    predicted_spend: float
    confidence_lower: float
    confidence_upper: float
    confidence_level: float = 0.95
    method: str = "exponential_smoothing"
    trend: str = "stable"              # increasing, decreasing, stable
    anomaly_detected: bool = False
    anomaly_score: float = 0.0
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "forecast_id": self.forecast_id,
            "budget_id": self.budget_id,
            "generated_at": self.generated_at,
            "forecast_date": self.forecast_date,
            "predicted_spend": round(self.predicted_spend, 2),
            "confidence_lower": round(self.confidence_lower, 2),
            "confidence_upper": round(self.confidence_upper, 2),
            "confidence_level": self.confidence_level,
            "method": self.method,
            "trend": self.trend,
            "anomaly_detected": self.anomaly_detected,
            "anomaly_score": round(self.anomaly_score, 4),
            "recommendations": self.recommendations,
        }


# ═══════════════════════════════════════════════════════════════════════
# Default Budget Templates
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_BUDGETS = {
    "global_monthly": BudgetDefinition(
        budget_id="budget_global_monthly",
        name="Global Monthly Budget",
        description="Organization-wide monthly budget cap",
        scope=BudgetScope.GLOBAL,
        scope_id="org",
        period=BudgetPeriod.MONTHLY,
        amount_usd=10000.0,
        limit_type=LimitType.HARD,
    ),
    "llm_daily": BudgetDefinition(
        budget_id="budget_llm_daily",
        name="LLM Daily Budget",
        description="Daily cap for LLM API costs",
        scope=BudgetScope.SERVICE,
        scope_id="llm",
        period=BudgetPeriod.DAILY,
        amount_usd=500.0,
        limit_type=LimitType.SOFT,
        categories=[CostCategory.LLM_USAGE, CostCategory.EMBEDDING],
    ),
    "inference_daily": BudgetDefinition(
        budget_id="budget_inference_daily",
        name="Inference Daily Budget",
        description="Daily cap for inference costs",
        scope=BudgetScope.SERVICE,
        scope_id="inference",
        period=BudgetPeriod.DAILY,
        amount_usd=200.0,
        limit_type=LimitType.SOFT,
        categories=[CostCategory.INFERENCE, CostCategory.COMPUTE],
    ),
    "retrain_monthly": BudgetDefinition(
        budget_id="budget_retrain_monthly",
        name="Retrain Monthly Budget",
        description="Monthly cap for model retraining",
        scope=BudgetScope.SERVICE,
        scope_id="mlops",
        period=BudgetPeriod.MONTHLY,
        amount_usd=2000.0,
        limit_type=LimitType.HARD,
        categories=[CostCategory.RETRAIN, CostCategory.COMPUTE],
    ),
}

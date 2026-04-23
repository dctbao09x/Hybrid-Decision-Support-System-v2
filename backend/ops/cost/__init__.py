# backend/ops/cost/__init__.py
"""
Cost & Budget Governance Package
================================

Enterprise-grade cost governance for AI operations:
- Budget management (daily/monthly/quarterly/annual)
- Cost tracking (compute, storage, LLM, inference)
- Enforcement engine (throttle, degrade, shutdown)
- Cost intelligence (forecasting, anomaly detection)
"""

from backend.ops.cost.models import (
    AlertLevel,
    BudgetDefinition,
    BudgetPeriod,
    BudgetScope,
    BudgetStatus,
    BudgetThreshold,
    CostCategory,
    CostEntry,
    CostForecast,
    EnforcementAction,
    LimitType,
)
from backend.ops.cost.budget_manager import BudgetManager, get_budget_manager
from backend.ops.cost.enforcement import (
    CostEnforcementEngine,
    DegradeLevel,
    EnforcementState,
    ThrottleLevel,
    get_enforcement_engine,
)
from backend.ops.cost.intelligence import CostIntelligence, get_cost_intelligence

__all__ = [
    # Models
    "AlertLevel",
    "BudgetDefinition",
    "BudgetPeriod",
    "BudgetScope",
    "BudgetStatus",
    "BudgetThreshold",
    "CostCategory",
    "CostEntry",
    "CostForecast",
    "EnforcementAction",
    "LimitType",
    # Budget Manager
    "BudgetManager",
    "get_budget_manager",
    # Enforcement
    "CostEnforcementEngine",
    "DegradeLevel",
    "EnforcementState",
    "ThrottleLevel",
    "get_enforcement_engine",
    # Intelligence
    "CostIntelligence",
    "get_cost_intelligence",
]

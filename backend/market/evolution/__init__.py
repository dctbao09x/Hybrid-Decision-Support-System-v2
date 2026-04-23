# backend/market/evolution/__init__.py
"""
Autonomous Evolution Loop
=========================

Self-improving market intelligence system:
Collect → Analyze → Predict → Update → Validate → Deploy → Monitor → Learn
"""

from .models import (
    EvolutionState,
    EvolutionCycle,
    EvolutionStage,
    ValidationResult,
    DeploymentPlan,
    MonitoringReport,
    LearningInsight,
)
from .orchestrator import (
    EvolutionOrchestrator,
    CycleRunner,
    get_evolution_orchestrator,
)

__all__ = [
    "EvolutionState",
    "EvolutionCycle",
    "EvolutionStage",
    "ValidationResult",
    "DeploymentPlan",
    "MonitoringReport",
    "LearningInsight",
    "EvolutionOrchestrator",
    "CycleRunner",
    "get_evolution_orchestrator",
]

# backend/market/scoring/__init__.py
"""
Scoring Auto-Adaptation
=======================

Market-driven score adaptation:
- Market weight injection
- Drift penalties
- Demand bonuses
- Versioned configurations
- Rollback support
"""

from .models import (
    ScoringConfig,
    ScoringVersion,
    ScoreAdjustment,
    AdjustmentType,
    ScoringExplanation,
    AdaptationEvent,
)
from .adapter import (
    ScoringAdapter,
    ScoreExplainer,
    get_scoring_adapter,
)

__all__ = [
    "ScoringConfig",
    "ScoringVersion",
    "ScoreAdjustment",
    "AdjustmentType",
    "ScoringExplanation",
    "AdaptationEvent",
    "ScoringAdapter",
    "ScoreExplainer",
    "get_scoring_adapter",
]

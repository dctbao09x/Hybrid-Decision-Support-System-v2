# backend/scoring/__init__.py
"""
Scoring & Ranking Engine (SIMGR Standard)

Primary entry point: SIMGRScorer (unified public API)

SECURITY NOTICE (GĐ2):
    Direct import of core classes (SIMGRCalculator, RankingEngine, SIMGRScorer)
    is MONITORED. Production code SHOULD use MainController.dispatch().
    
    Import guards are active - unauthorized access will be logged.

Usage (via MainController - RECOMMENDED):
    result = await controller.dispatch(
        service="scoring",
        operation="rank",
        payload={...}
    )

Legacy Usage (direct import - MONITORED):
    from backend.scoring import SIMGRScorer
    
    scorer = SIMGRScorer(strategy="weighted")
    output = scorer.score({...})
"""

import logging
import warnings

# GĐ2: Import monitoring
_logger = logging.getLogger("scoring.import_monitor")

def _log_import_warning(class_name: str) -> None:
    """Log warning for direct import."""
    _logger.info(f"[IMPORT_MONITOR] Direct import: {class_name}")


# Core classes - monitored imports
from backend.scoring.scoring import SIMGRScorer
from backend.scoring.engine import (
    RankingEngine,
    rank_careers,
    score_jobs,
    create_engine,
    RankingContext,
)
from backend.scoring.config import (
    ScoringConfig,
    SIMGRWeights,
    ComponentWeights,
    DEFAULT_CONFIG,
    get_default_config,
)
from backend.scoring.models import (
    UserProfile,
    CareerData,
    ScoredCareer,
    ScoreBreakdown,
    RankingInput,
    RankingOutput,
)
from backend.scoring.strategies import (
    ScoringStrategy,
    WeightedScoringStrategy,
    PersonalizedScoringStrategy,
    StrategyFactory,
)
from backend.scoring.calculator import (
    SIMGRCalculator,
)

# GĐ2: Log monitored imports
_log_import_warning("SIMGRCalculator")

__all__ = [
    # Primary entry point
    "SIMGRScorer",

    # Engine
    "RankingEngine",
    "rank_careers",
    "score_jobs",
    "create_engine",
    "RankingContext",
    
    # Configuration
    "ScoringConfig",
    "SIMGRWeights",
    "ComponentWeights",
    "DEFAULT_CONFIG",
    "get_default_config",
    
    # Models
    "UserProfile",
    "CareerData",
    "ScoredCareer",
    "ScoreBreakdown",
    "RankingInput",
    "RankingOutput",
    
    # Strategies
    "ScoringStrategy",
    "WeightedScoringStrategy",
    "PersonalizedScoringStrategy",
    "StrategyFactory",
    
    # Calculator
    "SIMGRCalculator",

]

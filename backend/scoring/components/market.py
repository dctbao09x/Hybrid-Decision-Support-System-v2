# backend/scoring/components/market.py
"""
Market Score Component: Market attractiveness assessment.

SIMGR Market Formula: M = 0.3*AI + 0.3*Growth + 0.2*Salary + 0.2*InvComp
  - AI: AI relevance (automation resilience)
  - Growth: Market growth rate
  - Salary: Normalized salary attractiveness
  - InvComp: Inverse competition (1 - saturation)

This component measures how attractive the career market is.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from backend.scoring.models import UserProfile, CareerData, ScoreResult
from backend.scoring.config import ScoringConfig
from backend.scoring.normalizer import DataNormalizer
from backend.market.cache_loader import (
    DEFAULT_MAX_AGE_HOURS,
    DEFAULT_MIN_TRUST_SCORE,
    MarketCacheLoader,
)

logger = logging.getLogger(__name__)

_cache_loader = MarketCacheLoader()


# =====================================================
# Market Component Weights
# =====================================================
WEIGHT_AI_RELEVANCE = 0.3      # AI/automation resilience
WEIGHT_GROWTH_RATE = 0.3       # Market growth
WEIGHT_SALARY = 0.2            # Salary attractiveness
WEIGHT_INVERSE_COMP = 0.2      # Inverse competition


# =====================================================
# Deterministic Helpers
# =====================================================
def _competition_from_level(level: str, fallback: float, normalizer: DataNormalizer) -> float:
    level_norm = str(level or "").strip().upper()
    if level_norm == "HIGH":
        return 0.8
    if level_norm == "MEDIUM":
        return 0.5
    if level_norm == "LOW":
        return 0.25
    return normalizer.clamp(fallback)


def _salary_score_from_signal(signal: Dict[str, Any], normalizer: DataNormalizer) -> Optional[float]:
    salary_range = signal.get("salary_range") or {}
    salary_min = salary_range.get("min")
    salary_max = salary_range.get("max")

    try:
        min_value = float(salary_min) if salary_min is not None else None
    except Exception:
        min_value = None
    try:
        max_value = float(salary_max) if salary_max is not None else None
    except Exception:
        max_value = None

    if min_value is None and max_value is None:
        return None

    if min_value is not None and max_value is not None:
        midpoint = (min_value + max_value) / 2.0
    else:
        midpoint = min_value if min_value is not None else max_value
    if midpoint is None:
        return None

    salary_floor = float(os.getenv("MARKET_SALARY_BASE_MIN", "5000000"))
    salary_ceiling = float(os.getenv("MARKET_SALARY_BASE_MAX", "100000000"))
    if salary_ceiling <= salary_floor:
        salary_ceiling = salary_floor + 1.0

    normalized = (midpoint - salary_floor) / (salary_ceiling - salary_floor)
    return normalizer.clamp(float(normalized))


def _deterministic_salary_fallback(
    ai_relevance: float,
    growth_rate: float,
    competition: float,
    normalizer: DataNormalizer,
) -> float:
    # Deterministic proxy: higher growth/AI and lower competition implies stronger pay signal.
    return normalizer.clamp((ai_relevance + growth_rate + (1.0 - competition)) / 3.0)


def score(
    job: CareerData,
    user: UserProfile,
    config: ScoringConfig
) -> ScoreResult:
    """Compute market score: M = 0.3*AI + 0.3*Growth + 0.2*Salary + 0.2*InvComp.

    Args:
        job: Career profile with market data
        user: User profile (unused for market score)
        config: Scoring config with component weights

    Returns:
        ScoreResult with value [0,1] and meta dict
    """
    normalizer = DataNormalizer()
    min_trust_score = float(os.getenv("MARKET_SIGNAL_MIN_TRUST_SCORE", str(DEFAULT_MIN_TRUST_SCORE)))
    max_age_hours = int(os.getenv("MARKET_CACHE_MAX_AGE_HOURS", str(DEFAULT_MAX_AGE_HOURS)))

    market_signal = _cache_loader.get_market_signal(
        career_name=job.name,
        max_age_hours=max_age_hours,
        min_trust_score=min_trust_score,
    )

    # Never call realtime APIs in scoring; use cache if available, else deterministic profile rule.
    if market_signal:
        ai_relevance = normalizer.clamp(float(market_signal.get("ai_relevance", job.ai_relevance)))
        growth_rate = normalizer.clamp(float(market_signal.get("growth_rate", job.growth_rate)))
        competition = _competition_from_level(
            str(market_signal.get("competition_level", "")),
            fallback=job.competition,
            normalizer=normalizer,
        )
        salary_score = _salary_score_from_signal(market_signal, normalizer)
        if salary_score is None:
            salary_score = _deterministic_salary_fallback(
                ai_relevance=ai_relevance,
                growth_rate=growth_rate,
                competition=competition,
                normalizer=normalizer,
            )
        source = "market_cache"
        source_trust_score = float(market_signal.get("source_trust_score", 0.0))
        stale = bool(market_signal.get("stale", False))
        trust_ok = bool(market_signal.get("trust_ok", False))
        signal_count = int(market_signal.get("signal_count", 0))
    else:
        ai_relevance = normalizer.clamp(job.ai_relevance)
        growth_rate = normalizer.clamp(job.growth_rate)
        competition = normalizer.clamp(job.competition)
        salary_score = _deterministic_salary_fallback(
            ai_relevance=ai_relevance,
            growth_rate=growth_rate,
            competition=competition,
            normalizer=normalizer,
        )
        source = "career_profile_rule"
        source_trust_score = 0.0
        stale = False
        trust_ok = False
        signal_count = 0
        logger.debug(
            "Market cache miss for career=%s; using deterministic profile-based fallback",
            job.name,
        )

    # Inverse competition (high competition = low attractiveness)
    inverse_competition = 1.0 - competition

    # Apply SIMGR Market formula: M = 0.3*AI + 0.3*Growth + 0.2*Salary + 0.2*InvComp
    market_score = (
        WEIGHT_AI_RELEVANCE * ai_relevance +
        WEIGHT_GROWTH_RATE * growth_rate +
        WEIGHT_SALARY * salary_score +
        WEIGHT_INVERSE_COMP * inverse_competition
    )

    # Clamp result to [0, 1]
    market_score = normalizer.clamp(market_score)

    # Meta details
    meta = {
        "formula": "M = 0.3*AI + 0.3*Growth + 0.2*Salary + 0.2*InvComp",
        "source": source,
        "source_trust_score": round(source_trust_score, 4),
        "trust_ok": trust_ok,
        "stale": stale,
        "signal_count": signal_count,
        "ai_relevance": round(ai_relevance, 4),
        "growth_rate": round(growth_rate, 4),
        "salary_score": round(salary_score, 4),
        "competition": round(competition, 4),
        "inverse_competition": round(inverse_competition, 4),
        "weights_used": {
            "ai_relevance": WEIGHT_AI_RELEVANCE,
            "growth_rate": WEIGHT_GROWTH_RATE,
            "salary": WEIGHT_SALARY,
            "inverse_competition": WEIGHT_INVERSE_COMP,
        },
    }

    return ScoreResult(value=market_score, meta=meta)

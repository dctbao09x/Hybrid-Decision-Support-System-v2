# backend/scoring/engine.py
"""
Ranking Engine: Central orchestration of scoring pipeline.

Responsibilities:
- Accept RankingInput and produce RankingOutput
- Support strategy switching
- Inject configuration properly
- Expose rank_careers() stateless facade

GĐ7: Interface Consistency Gate
- All public outputs MUST return ScoreResultDTO
- No final_score, confidence_score, skill_score, legacy_score, normalized_score
- Type validation enforced at boundary via _validate_dto
"""

from __future__ import annotations

from typing import List, Optional
import uuid
import logging
from datetime import datetime

from backend.scoring.models import (
    UserProfile,
    CareerData,
    ScoredCareer,
    RankingInput,
    RankingOutput,
)
from backend.scoring.config import ScoringConfig, DEFAULT_CONFIG
from backend.scoring.strategies import (
    ScoringStrategy,
    StrategyFactory,
)
from backend.scoring.dto import ScoreResultDTO, _validate_dto, dto_from_scored_career

logger = logging.getLogger(__name__)


# =====================================================
# Execution Context
# =====================================================

class RankingContext:
    """Execution context for ranking request."""
    
    def __init__(self):
        """Initialize context."""
        self.request_id = str(uuid.uuid4())
        self.timestamp = datetime.now()
    
    def to_dict(self) -> dict:
        """Export as dict."""
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat(),
        }


# =====================================================
# Ranking Engine
# =====================================================

class RankingEngine:
    """Central decision engine for career ranking.
    
    Orchestrates the scoring pipeline:
    1. Accept user profile and careers
    2. Select/build strategy
    3. Delegate to strategy for ranking
    4. Return sorted, ranked results
    """
    
    def __init__(
        self,
        default_config: Optional[ScoringConfig] = None,
        default_strategy: str = "weighted",
    ):
        """Initialize engine.
        
        Args:
            default_config: Default scoring config (uses DEFAULT_CONFIG if None)
            default_strategy: Default strategy name ("weighted" or "personalized")
        """
        self._default_config = default_config or DEFAULT_CONFIG
        self._default_strategy_name = default_strategy.lower()
        
        # Validate strategy exists
        try:
            StrategyFactory.create(
                self._default_strategy_name,
                self._default_config
            )
        except ValueError as e:
            logger.warning(f"Invalid default strategy: {e}")
            self._default_strategy_name = "weighted"
    
    def _build_strategy(
        self,
        config: ScoringConfig,
        name: Optional[str] = None,
    ) -> ScoringStrategy:
        """Build strategy instance.
        
        Args:
            config: Scoring configuration
            name: Strategy name (uses default if None)
        
        Returns:
            ScoringStrategy instance
        """
        strategy_name = (name or self._default_strategy_name).lower()
        return StrategyFactory.create(strategy_name, config)
    
    def rank(
        self,
        user: UserProfile,
        careers: List[CareerData],
        config_override: Optional[ScoringConfig] = None,
        strategy_name: Optional[str] = None,
        context: Optional[RankingContext] = None,
    ) -> List[ScoredCareer]:
        """Rank careers for user.
        
        Args:
            user: User profile (required)
            careers: Careers to rank (required)
            config_override: Optional config override
            strategy_name: Optional strategy override
            context: Optional execution context (auto-created if None)
        
        Returns:
            List of ranked ScoredCareer results
        """
        ctx = context or RankingContext()
        config = config_override or self._default_config
        
        # Input validation
        if not careers:
            logger.warning(
                f"Ranking aborted (empty career list) | req={ctx.request_id}"
            )
            return []
        
        if not isinstance(user, UserProfile):
            logger.error(f"Invalid user type | req={ctx.request_id}")
            return []
        
        # Build strategy
        try:
            strategy = self._build_strategy(config, strategy_name)
        except ValueError as e:
            logger.error(
                f"Strategy creation failed: {e} | req={ctx.request_id}"
            )
            if config.debug_mode:
                raise
            return []
        
        # Execute ranking
        logger.info(
            f"Ranking start | req={ctx.request_id} "
            f"| user_skills={len(user.skills)} "
            f"| careers={len(careers)} "
            f"| strategy={strategy.__class__.__name__}"
        )
        
        try:
            results = strategy.rank(user, careers)
            
            logger.info(
                f"Ranking complete | req={ctx.request_id} "
                f"| returned={len(results)}"
            )
            
            return results
        
        except Exception as e:
            logger.exception(
                f"Ranking failed: {e} | req={ctx.request_id}"
            )
            
            if config.debug_mode:
                raise
            
            return []
    
    def rank_from_input(
        self,
        ranking_input: RankingInput,
        strategy_name: Optional[str] = None,
    ) -> RankingOutput:
        """Rank using RankingInput DTO.
        
        Args:
            ranking_input: Input containing user and careers
            strategy_name: Optional strategy override
        
        Returns:
            RankingOutput with results
        """
        context = RankingContext()
        
        # Use provided weights if present, else default
        config = self._default_config
        
        results = self.rank(
            user=ranking_input.user_profile,
            careers=ranking_input.eligible_careers,
            config_override=config,
            strategy_name=strategy_name,
            context=context,
        )
        
        return RankingOutput(
            ranked_careers=results,
            total_evaluated=len(ranking_input.eligible_careers),
            config_used=config.simgr_weights.to_dict(),
        )

    def rank_dto(
        self,
        user: UserProfile,
        careers: List[CareerData],
        config_override: Optional[ScoringConfig] = None,
        strategy_name: Optional[str] = None,
        context: Optional[RankingContext] = None,
    ) -> List[ScoreResultDTO]:
        """Rank careers and return DTO output (GĐ7 compliant).
        
        GĐ7 Interface Contract:
        - Output is List[ScoreResultDTO] only
        - No dict, namedtuple, or custom class
        - Type validation enforced via _validate_dto
        
        Args:
            user: User profile (required)
            careers: Careers to rank (required)
            config_override: Optional config override
            strategy_name: Optional strategy override
            context: Optional execution context (auto-created if None)
        
        Returns:
            List of ScoreResultDTO results (validated)
            
        Raises:
            TypeError: If any result fails DTO validation
        """
        # Get internal ScoredCareer results
        scored_careers = self.rank(
            user=user,
            careers=careers,
            config_override=config_override,
            strategy_name=strategy_name,
            context=context,
        )
        
        # Convert to DTO and validate
        dto_results: List[ScoreResultDTO] = []
        for i, scored in enumerate(scored_careers, start=1):
            dto = dto_from_scored_career(scored, rank=i)
            _validate_dto(dto)
            dto_results.append(dto)
        
        return dto_results


# =====================================================
# Stateless Facade
# =====================================================

# Global engine instance (lazy-loaded to prevent import-time errors)
_engine: Optional[RankingEngine] = None


def _get_engine() -> RankingEngine:
    """Get or create global engine (lazy initialization).
    
    Prevents import-time errors when DEFAULT_CONFIG is unavailable.
    Engine is created on first use.
    """
    global _engine
    if _engine is None:
        _engine = RankingEngine()
    return _engine


def rank_careers(
    user: UserProfile,
    careers: List[CareerData],
    *,
    config: Optional[ScoringConfig] = None,
    strategy: Optional[str] = None,
) -> List[ScoredCareer]:
    """Stateless facade for career ranking.
    
    Recommended usage for simple ranking operations.
    
    Args:
        user: User profile
        careers: Careers to rank
        config: Optional config override (keyword-only)
        strategy: Optional strategy override (keyword-only)
    
    Returns:
        List of ranked ScoredCareer results
    
    Example:
        ranked = rank_careers(user_profile, career_list)
    """
    return _get_engine().rank(
        user=user,
        careers=careers,
        config_override=config,
        strategy_name=strategy,
    )


def rank_careers_dto(
    user: UserProfile,
    careers: List[CareerData],
    *,
    config: Optional[ScoringConfig] = None,
    strategy: Optional[str] = None,
) -> List[ScoreResultDTO]:
    """Stateless facade for career ranking with DTO output (GĐ7 compliant).
    
    GĐ7 Interface Contract:
    - Output is List[ScoreResultDTO] only
    - All results validated via _validate_dto
    
    Args:
        user: User profile
        careers: Careers to rank
        config: Optional config override (keyword-only)
        strategy: Optional strategy override (keyword-only)
    
    Returns:
        List of ScoreResultDTO results
        
    Example:
        results = rank_careers_dto(user_profile, career_list)
        for dto in results:
            print(dto.total_score, dto.components, dto.rank)
    """
    return _get_engine().rank_dto(
        user=user,
        careers=careers,
        config_override=config,
        strategy_name=strategy,
    )


def score_jobs(
    clean_jobs: List[CareerData],
    user_profile: UserProfile,
    *,
    config: Optional[ScoringConfig] = None,
    strategy: Optional[str] = None,
) -> List[ScoringResult]:
    """Score jobs for user profile.

    Args:
        clean_jobs: List of cleaned job/career data
        user_profile: User profile for scoring
        config: Optional scoring config override
        strategy: Optional strategy override

    Returns:
        List of ScoringResult with contributions mapping
    """
    from backend.scoring.models import ScoringResult

    # Use global engine (lazy loaded)
    engine = _get_engine()
    results = engine.rank(
        user=user_profile,
        careers=clean_jobs,
        config_override=config,
        strategy_name=strategy,
    )

    # Convert to ScoringResult with contributions
    # Use the actual config (passed or default) for contribution weights
    active_config = config or engine._default_config
    scoring_results = []
    for result in results:
        weights = active_config.simgr_weights
        contributions = {
            "study": {
                "weight": weights.study_score,
                "contribution": round(
                    result.breakdown.study_score * weights.study_score, 6
                ),
            },
            "interest": {
                "weight": weights.interest_score,
                "contribution": round(
                    result.breakdown.interest_score * weights.interest_score, 6
                ),
            },
            "market": {
                "weight": weights.market_score,
                "contribution": round(
                    result.breakdown.market_score * weights.market_score, 6
                ),
            },
            "growth": {
                "weight": weights.growth_score,
                "contribution": round(
                    result.breakdown.growth_score * weights.growth_score, 6
                ),
            },
            "risk": {
                "weight": weights.risk_score,
                "contribution": round(
                    result.breakdown.risk_score * weights.risk_score, 6
                ),
            },
        }

        scoring_result = ScoringResult(
            career_name=result.career_name,
            total_score=result.total_score,
            breakdown=result.breakdown,
            contributions=contributions,
            rank=result.rank,
        )
        scoring_results.append(scoring_result)

    return scoring_results


def create_engine(
    config: Optional[ScoringConfig] = None,
    strategy: str = "weighted",
) -> RankingEngine:
    """Create new engine instance.

    Args:
        config: Optional default config
        strategy: Optional default strategy

    Returns:
        New RankingEngine instance
    """
    return RankingEngine(default_config=config, default_strategy=strategy)


def score_with_snapshot(
    user_dict: dict,
    careers_list: List[dict],
    *,
    config_override: Optional[dict] = None,
    strategy: str = "weighted",
) -> "ScoringOutputSchema":
    """
    Score careers with full input snapshot validation and structured output.

    This is the **recommended entry point** for production scoring.
    It validates inputs, computes a deterministic input hash, runs scoring,
    and returns a structured ScoringOutputSchema with reproducibility proof.

    Parameters
    ----------
    user_dict : dict
        Raw user profile dict (will be validated via Pydantic).
    careers_list : List[dict]
        Raw career dicts.
    config_override : dict, optional
        Keys: strategy, weights, min_score_threshold, debug_mode
    strategy : str
        Scoring strategy name.

    Returns
    -------
    ScoringOutputSchema
        Full structured output with score cards + reproducibility proof.

    Raises
    ------
    ValueError
        If input validation fails.
    """
    import time as _time

    from backend.schemas.scoring import (
        ScoringInputSnapshot,
        UserProfileInput,
        CareerInput,
        ScoringConfigInput,
        build_scoring_output,
    )

    t0 = _time.monotonic()

    # ── 1. Validate & build input snapshot ──
    user_input = UserProfileInput(**user_dict)
    career_inputs = [CareerInput(**c) for c in careers_list]

    cfg_input = ScoringConfigInput(
        strategy=strategy,
        **(config_override or {}),
    )

    snapshot = ScoringInputSnapshot(
        user_profile=user_input,
        careers=career_inputs,
        config=cfg_input,
    )

    # Verify hash was computed
    if not snapshot.verify():
        raise ValueError("Input snapshot hash verification failed")

    # ── 2. Convert to engine models ──
    user = UserProfile(
        skills=user_input.skills,
        interests=user_input.interests,
        education_level=user_input.education_level,
        ability_score=user_input.ability_score,
        confidence_score=user_input.confidence_score,
    )

    careers = [
        CareerData(
            name=c.name,
            required_skills=c.required_skills,
            preferred_skills=c.preferred_skills,
            domain=c.domain,
            domain_interests=c.domain_interests,
            ai_relevance=c.ai_relevance,
            growth_rate=c.growth_rate,
            competition=c.competition,
        )
        for c in career_inputs
    ]

    # ── 3. Build config ──
    engine_config = None
    actual_strategy = cfg_input.strategy

    if cfg_input.weights:
        engine_config = ScoringConfig.create_custom(
            study=cfg_input.weights.get("study"),
            interest=cfg_input.weights.get("interest"),
            market=cfg_input.weights.get("market"),
            growth=cfg_input.weights.get("growth"),
            risk=cfg_input.weights.get("risk"),
            debug=cfg_input.debug_mode,
            deterministic=True,
        )
        engine_config.min_score_threshold = cfg_input.min_score_threshold
    elif cfg_input.min_score_threshold > 0 or cfg_input.debug_mode:
        from copy import deepcopy

        engine_config = deepcopy(_engine._default_config)
        engine_config.min_score_threshold = cfg_input.min_score_threshold
        engine_config.debug_mode = cfg_input.debug_mode

    # ── 4. Score ──
    scored = _engine.rank(
        user=user,
        careers=careers,
        config_override=engine_config,
        strategy_name=actual_strategy,
    )

    duration_ms = (_time.monotonic() - t0) * 1000

    # ── 5. Build structured output ──
    used_config = engine_config or _engine._default_config
    return build_scoring_output(
        scored_careers=scored,
        config_used=used_config,
        strategy_name=actual_strategy,
        input_snapshot=snapshot,
        duration_ms=round(duration_ms, 2),
    )

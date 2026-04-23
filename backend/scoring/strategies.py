# backend/scoring/strategies.py
"""
Scoring strategies: Deterministic ranking algorithms.

Provides different ranking strategies with support for personalization.
All operations are stateless and don't mutate base configuration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional
import logging
from copy import deepcopy

from backend.scoring.models import (
    UserProfile,
    CareerData,
    ScoredCareer,
    ScoreBreakdown
)
from backend.scoring.config import ScoringConfig, SIMGRWeights
from backend.scoring.calculator import SIMGRCalculator

logger = logging.getLogger(__name__)


# =====================================================
# Base Strategy
# =====================================================

class ScoringStrategy(ABC):
    """Abstract base for scoring strategies.
    
    Properties:
    - Deterministic: No random behavior
    - Immutable: Never mutates input config
    - Stateless: All state passed as parameters
    """
    
    def __init__(self, config: ScoringConfig):
        """Initialize strategy.
        
        Args:
            config: Scoring configuration (not mutated)
        """
        if not isinstance(config, ScoringConfig):
            raise TypeError("config must be ScoringConfig")
        
        # Store config, never mutate it
        self.config = deepcopy(config)
        self._calculator = SIMGRCalculator(self.config)
    
    def pre_rank(
        self,
        user: UserProfile,
        careers: List[CareerData]
    ) -> None:
        """Hook before ranking (for setup).
        
        Args:
            user: User profile
            careers: Careers to rank
        """
        pass
    
    def post_rank(
        self,
        results: List[ScoredCareer]
    ) -> None:
        """Hook after ranking (for finalization).
        
        Args:
            results: Ranked results
        """
        pass
    
    def score_one(
        self,
        user: UserProfile,
        career: CareerData
    ) -> Optional[ScoredCareer]:
        """Score single career.
        
        Args:
            user: User profile
            career: Career profile
        
        Returns:
            ScoredCareer or None if filtered out
        """
        try:
            total, breakdown_dict = self._calculator.calculate(user, career)
            
            # Apply threshold filtering
            if total < self.config.min_score_threshold:
                logger.debug(
                    f"Career {career.name} filtered: score {total:.3f} "
                    f"< threshold {self.config.min_score_threshold}"
                )
                return None
            
            # GĐ1: NO FALLBACK - all breakdown scores must be present
            required_keys = ["study_score", "interest_score", "market_score", 
                           "growth_score", "risk_score"]
            missing_keys = [k for k in required_keys if k not in breakdown_dict]
            if missing_keys:
                raise ValueError(
                    f"[SCORING] Incomplete breakdown - missing: {missing_keys}. "
                    f"Calculator must return all SIMGR components."
                )
            
            # Build breakdown model - NO DEFAULTS
            breakdown = ScoreBreakdown(
                study_score=breakdown_dict["study_score"],
                interest_score=breakdown_dict["interest_score"],
                market_score=breakdown_dict["market_score"],
                growth_score=breakdown_dict["growth_score"],
                risk_score=breakdown_dict["risk_score"],
                study_details=breakdown_dict.get("study_details"),
                interest_details=breakdown_dict.get("interest_details"),
                market_details=breakdown_dict.get("market_details"),
                growth_details=breakdown_dict.get("growth_details"),
                risk_details=breakdown_dict.get("risk_details"),
            )
            
            return ScoredCareer(
                career_name=career.name,
                total_score=round(total, 4),
                breakdown=breakdown
            )
        
        except Exception as e:
            logger.exception(
                f"Scoring failed for {career.name}: {e}",
                exc_info=e
            )
            
            if self.config.debug_mode:
                raise
            
            return None
    
    def rank(
        self,
        user: UserProfile,
        careers: List[CareerData]
    ) -> List[ScoredCareer]:
        """Rank careers for user.
        
        Args:
            user: User profile
            careers: Careers to rank
        
        Returns:
            Sorted list of scored careers (highest score first)
        """
        if not careers:
            logger.warning("Ranking aborted: empty career list")
            return []
        
        # Pre-ranking hook
        self.pre_rank(user, careers)
        
        # Score each career
        scored: List[ScoredCareer] = []
        
        for career in careers:
            scored_career = self.score_one(user, career)
            if scored_career:
                scored.append(scored_career)
        
        # Sort by total_score descending
        scored.sort(key=lambda x: x.total_score, reverse=True)
        
        # Add ranking position
        for i, item in enumerate(scored, start=1):
            item.rank = i
        
        # Post-ranking hook
        self.post_rank(scored)
        
        logger.debug(
            f"Ranked {len(scored)} of {len(careers)} careers"
        )
        
        return scored


# =====================================================
# Weighted Strategy
# =====================================================

class WeightedScoringStrategy(ScoringStrategy):
    """Standard weighted SIMGR scoring.
    
    Uses fixed SIMGR weights from configuration.
    Most deterministic and reproducible strategy.
    """
    
    pass


# =====================================================
# Personalized Strategy
# =====================================================

class PersonalizedScoringStrategy(ScoringStrategy):
    """Adaptive weight strategy based on user profile.
    
    Personalizes SIMGR weights based on:
    - User confidence level
    - User ability level
    - User education level
    
    Never mutates base config; creates personalized copy.
    """
    
    def __init__(self, config: ScoringConfig):
        """Initialize personalized strategy."""
        super().__init__(config)
        self.personalized_config: Optional[ScoringConfig] = None
    
    def _build_personalized_config(
        self,
        user: UserProfile
    ) -> ScoringConfig:
        """Create personalized config based on user profile.
        
        Rules:
        - High confidence (>=0.8): Increase interest weight
        - Low confidence (<0.3): Increase study weight
        - Low ability (<=0.3): Increase market weight (stable careers)
        - High ability (>=0.8): Increase growth weight (growth careers)
        
        Args:
            user: User profile
        
        Returns:
            New personalized ScoringConfig (never mutates original)
        """
        # Start from deepcopy of base config
        cfg = deepcopy(self.config)
        
        # Extract base weights from actual config (not hardcoded)
        w = cfg.simgr_weights
        base_s = w.study_score
        base_i = w.interest_score
        base_m = w.market_score
        base_g = w.growth_score
        base_r = w.risk_score
        
        # Start with base allocation
        s = base_s
        i = base_i
        m = base_m
        g = base_g
        r = base_r
        
        # Apply personalization rules (redistribute, don't multiply)
        # High confidence: boost interest, reduce market
        if user.confidence_score >= 0.8:
            delta = 0.05
            i = min(base_i + delta, 0.35)
            m = max(base_m - delta, 0.15)
        
        # Low confidence: boost study, reduce growth
        elif user.confidence_score < 0.3:
            delta = 0.05
            s = min(base_s + delta, 0.35)
            g = max(base_g - delta, 0.05)
        
        # Low ability: boost market (stability), reduce growth
        if user.ability_score <= 0.3:
            delta = 0.05
            m = min(m + delta, 0.35)
            g = max(g - delta, 0.05)
        
        # High ability: boost growth, reduce market
        elif user.ability_score >= 0.8:
            delta = 0.05
            g = min(g + delta, 0.25)
            m = max(m - delta, 0.10)
        
        # Create SIMGRWeights (normalize will be called in __init__)
        cfg.simgr_weights = SIMGRWeights(
            study_score=s,
            interest_score=i,
            market_score=m,
            growth_score=g,
            risk_score=r,
        )
        
        # Create new calculator with personalized config
        cfg_copy = deepcopy(cfg)
        self._calculator = SIMGRCalculator(cfg_copy)
        
        return cfg
    
    def pre_rank(
        self,
        user: UserProfile,
        careers: List[CareerData]
    ) -> None:
        """Build personalized config before ranking.
        
        Args:
            user: User profile
            careers: Careers to rank
        """
        self.personalized_config = self._build_personalized_config(user)
        
        logger.debug(
            f"Personalized weights: "
            f"study={self.personalized_config.simgr_weights.study_score:.3f}, "
            f"interest={self.personalized_config.simgr_weights.interest_score:.3f}, "
            f"market={self.personalized_config.simgr_weights.market_score:.3f}, "
            f"growth={self.personalized_config.simgr_weights.growth_score:.3f}, "
            f"risk={self.personalized_config.simgr_weights.risk_score:.3f}"
        )


# =====================================================
# Strategy Factory
# =====================================================

class StrategyFactory:
    """Registry and factory for scoring strategies."""
    
    _registry = {
        "weighted": WeightedScoringStrategy,
        "personalized": PersonalizedScoringStrategy,
    }
    
    @classmethod
    def register(
        cls,
        name: str,
        strategy_class: type
    ) -> None:
        """Register custom strategy.
        
        Args:
            name: Strategy name
            strategy_class: Strategy class (must inherit ScoringStrategy)
        """
        if not issubclass(strategy_class, ScoringStrategy):
            raise TypeError(
                f"{strategy_class} must inherit ScoringStrategy"
            )
        cls._registry[name.lower()] = strategy_class
    
    @classmethod
    def create(
        cls,
        name: str,
        config: ScoringConfig
    ) -> ScoringStrategy:
        """Create strategy instance.
        
        Args:
            name: Strategy name (case-insensitive)
            config: Scoring configuration
        
        Returns:
            ScoringStrategy instance
        
        Raises:
            ValueError: If strategy not found
        """
        strategy_cls = cls._registry.get(name.lower())
        
        if not strategy_cls:
            available = ", ".join(cls._registry.keys())
            raise ValueError(
                f"Unknown strategy: {name}. Available: {available}"
            )
        
        return strategy_cls(config)
    
    @classmethod
    def list_strategies(cls) -> List[str]:
        """List all registered strategies.
        
        Returns:
            List of strategy names
        """
        return list(cls._registry.keys())

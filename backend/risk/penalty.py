# backend/risk/penalty.py
"""
Risk Penalty Engine - SIMGR Stage 3 Compliant

Central engine for computing total risk penalty.

CRITICAL RULES:
1. NO INVERSION - Risk is raw value (high = bad)
2. NO HARDCODING - All weights from config.yaml
3. Risk is SUBTRACTED in final SIMGR formula

Formula:
  R = w1*market + w2*obsolescence + w3*competition + w4*dropout + w5*unemployment + w6*cost

Where sum(weights) = 1.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .registry import get_registry, RiskWeights, PenaltyConfig, RiskThresholds

logger = logging.getLogger(__name__)


@dataclass
class RiskBreakdown:
    """Detailed breakdown of risk components."""
    market_saturation: float
    skill_obsolescence: float
    competition: float
    dropout: float
    unemployment: float
    cost: float
    total: float
    weighted_components: Dict[str, float]
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "market_saturation": self.market_saturation,
            "skill_obsolescence": self.skill_obsolescence,
            "competition": self.competition,
            "dropout": self.dropout,
            "unemployment": self.unemployment,
            "cost": self.cost,
            "total": self.total,
        }


class RiskPenaltyEngine:
    """Central engine for computing risk penalty.
    
    All weights and thresholds loaded from config.yaml.
    NO HARDCODING.
    NO INVERSION.
    
    Usage:
        engine = RiskPenaltyEngine()
        risk = engine.compute(
            market=0.5,
            skill=0.3,
            competition=0.4,
            dropout=0.2,
            unemployment=0.1,
            cost=0.35
        )
    """
    
    def __init__(self):
        self._registry = get_registry()
        self._weights: Optional[RiskWeights] = None
        self._penalty_config: Optional[PenaltyConfig] = None
        self._thresholds: Optional[RiskThresholds] = None
    
    def _ensure_config(self) -> None:
        """Ensure configuration is loaded."""
        if self._weights is None:
            self._weights = self._registry.get_weights()
        if self._penalty_config is None:
            self._penalty_config = self._registry.get_penalty_config()
        if self._thresholds is None:
            self._thresholds = self._registry.get_thresholds()
    
    def compute(
        self,
        market: float,
        skill: float,
        competition: float,
        dropout: float,
        unemployment: float,
        cost: float,
        apply_threshold: bool = True,
        apply_scaling: bool = True,
    ) -> float:
        """Compute total risk score.
        
        Args:
            market: Market saturation risk [0, 1]
            skill: Skill obsolescence risk [0, 1]
            competition: Competition risk [0, 1]
            dropout: Dropout risk [0, 1]
            unemployment: Unemployment risk [0, 1]
            cost: Cost barrier risk [0, 1]
            apply_threshold: Apply threshold adjustments
            apply_scaling: Apply scaling factor
            
        Returns:
            Total risk score [0, 1] where 1 = maximum risk.
            
        Note:
            This value should be SUBTRACTED in the final SIMGR formula:
            Score = wS*S + wI*I + wM*M + wG*G - wR*R
        """
        self._ensure_config()
        
        # Validate inputs
        market = self._clamp(market)
        skill = self._clamp(skill)
        competition = self._clamp(competition)
        dropout = self._clamp(dropout)
        unemployment = self._clamp(unemployment)
        cost = self._clamp(cost)
        
        # Apply threshold adjustments if enabled
        if apply_threshold:
            market = self._apply_threshold(market, self._thresholds.saturation_high)
            skill = self._apply_threshold(skill, self._thresholds.obsolescence_high)
            dropout = self._apply_threshold(dropout, self._thresholds.dropout_high)
            unemployment = self._apply_threshold(unemployment, self._thresholds.unemployment_high)
        
        # Weighted sum (all weights from config)
        total_risk = (
            self._weights.market_saturation * market +
            self._weights.skill_obsolescence * skill +
            self._weights.competition * competition +
            self._weights.dropout * dropout +
            self._weights.unemployment * unemployment +
            self._weights.cost * cost
        )
        
        # Apply scaling if enabled
        if apply_scaling:
            total_risk = self._apply_scaling(total_risk)
        
        # Apply penalty bounds
        total_risk = max(
            self._penalty_config.min_penalty,
            min(self._penalty_config.max_penalty, total_risk)
        )
        
        # CRITICAL: Return RAW risk (NO INVERSION)
        # High value = High risk = Bad
        return total_risk
    
    def compute_with_breakdown(
        self,
        market: float,
        skill: float,
        competition: float,
        dropout: float,
        unemployment: float,
        cost: float,
    ) -> RiskBreakdown:
        """Compute risk with detailed breakdown.
        
        Args:
            Same as compute()
            
        Returns:
            RiskBreakdown with all components and total.
        """
        self._ensure_config()
        
        # Clamp inputs
        market = self._clamp(market)
        skill = self._clamp(skill)
        competition = self._clamp(competition)
        dropout = self._clamp(dropout)
        unemployment = self._clamp(unemployment)
        cost = self._clamp(cost)
        
        # Weighted components
        weighted = {
            "market_saturation": self._weights.market_saturation * market,
            "skill_obsolescence": self._weights.skill_obsolescence * skill,
            "competition": self._weights.competition * competition,
            "dropout": self._weights.dropout * dropout,
            "unemployment": self._weights.unemployment * unemployment,
            "cost": self._weights.cost * cost,
        }
        
        total = self.compute(
            market=market,
            skill=skill,
            competition=competition,
            dropout=dropout,
            unemployment=unemployment,
            cost=cost,
        )
        
        return RiskBreakdown(
            market_saturation=market,
            skill_obsolescence=skill,
            competition=competition,
            dropout=dropout,
            unemployment=unemployment,
            cost=cost,
            total=total,
            weighted_components=weighted,
        )
    
    def _clamp(self, value: float) -> float:
        """Clamp value to [0, 1]."""
        return max(0.0, min(1.0, value))
    
    def _apply_threshold(self, value: float, threshold: float) -> float:
        """Apply threshold adjustment.
        
        Values above threshold get boosted.
        """
        if value > threshold:
            # Boost values above threshold
            excess = value - threshold
            boost = excess * self._penalty_config.scaling_factor
            return min(1.0, threshold + boost)
        return value
    
    def _apply_scaling(self, value: float) -> float:
        """Apply scaling factor to total risk."""
        base = self._penalty_config.base_rate
        scaled = base + (value - base) * self._penalty_config.scaling_factor
        return self._clamp(scaled)
    
    def get_weights(self) -> Dict[str, float]:
        """Get current weights for transparency."""
        self._ensure_config()
        return self._weights.to_dict()
    
    def reload_config(self) -> None:
        """Reload configuration (hot reload)."""
        self._registry.reload()
        self._weights = self._registry.get_weights()
        self._penalty_config = self._registry.get_penalty_config()
        self._thresholds = self._registry.get_thresholds()
        logger.info("Risk penalty engine config reloaded")


# Singleton instance
_engine: Optional[RiskPenaltyEngine] = None


def get_penalty_engine() -> RiskPenaltyEngine:
    """Get singleton penalty engine instance."""
    global _engine
    if _engine is None:
        _engine = RiskPenaltyEngine()
    return _engine


def compute_risk(
    market: float = 0.0,
    skill: float = 0.0,
    competition: float = 0.0,
    dropout: float = 0.0,
    unemployment: float = 0.0,
    cost: float = 0.0,
) -> float:
    """Convenience function to compute risk.
    
    Args:
        market: Market saturation risk
        skill: Skill obsolescence risk
        competition: Competition risk
        dropout: Dropout risk
        unemployment: Unemployment risk
        cost: Cost barrier risk
        
    Returns:
        Total risk score [0, 1]
    """
    engine = get_penalty_engine()
    return engine.compute(
        market=market,
        skill=skill,
        competition=competition,
        dropout=dropout,
        unemployment=unemployment,
        cost=cost,
    )

# backend/market/scoring/models.py
"""
Data models for Scoring Auto-Adaptation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class AdjustmentType(Enum):
    """Types of score adjustments."""
    MARKET_WEIGHT = "market_weight"       # Base skill value from market
    TREND_BONUS = "trend_bonus"           # Bonus for trending skills
    TREND_PENALTY = "trend_penalty"       # Penalty for declining skills
    DEMAND_MULTIPLIER = "demand_mult"     # Multiplier based on demand
    DRIFT_PENALTY = "drift_penalty"       # Penalty for skill drift
    SCARCITY_BONUS = "scarcity_bonus"     # Bonus for rare skills
    SALARY_CORRELATION = "salary_corr"    # Adjustment based on salary data
    RECENCY_DECAY = "recency_decay"       # Decay for outdated skills


@dataclass
class ScoreAdjustment:
    """
    Individual score adjustment.
    
    Attributes:
        adjustment_id: Unique identifier
        skill_id: Skill this applies to
        type: Type of adjustment
        value: Adjustment value (additive or multiplicative)
        is_multiplicative: If True, value is multiplier; else additive
        source: Source of adjustment (market, trend, manual)
        confidence: Confidence in this adjustment
        valid_from: When adjustment becomes active
        valid_until: When adjustment expires
        evidence: Supporting evidence
    """
    adjustment_id: str
    skill_id: str
    type: AdjustmentType
    value: float
    is_multiplicative: bool = False
    source: str = "auto"
    confidence: float = 1.0
    valid_from: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: Optional[datetime] = None
    evidence: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "adjustment_id": self.adjustment_id,
            "skill_id": self.skill_id,
            "type": self.type.value,
            "value": self.value,
            "is_multiplicative": self.is_multiplicative,
            "source": self.source,
            "confidence": self.confidence,
            "valid_from": self.valid_from.isoformat(),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "evidence": self.evidence,
        }


@dataclass
class ScoringConfig:
    """
    Complete scoring configuration.
    
    Attributes:
        config_id: Unique identifier
        name: Configuration name
        base_weights: Base skill weights
        adjustments: Active adjustments
        global_modifiers: Global score modifiers
        enabled_adjustment_types: Which adjustment types are active
        max_adjustment_cap: Maximum total adjustment allowed
        min_score: Minimum score floor
        max_score: Maximum score ceiling
    """
    config_id: str
    name: str = "default"
    base_weights: Dict[str, float] = field(default_factory=dict)
    adjustments: List[ScoreAdjustment] = field(default_factory=list)
    global_modifiers: Dict[str, float] = field(default_factory=dict)
    enabled_adjustment_types: List[AdjustmentType] = field(default_factory=lambda: list(AdjustmentType))
    max_adjustment_cap: float = 0.5  # Max 50% change from base
    min_score: float = 0.0
    max_score: float = 100.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "config_id": self.config_id,
            "name": self.name,
            "base_weights": self.base_weights,
            "adjustments": [a.to_dict() for a in self.adjustments],
            "global_modifiers": self.global_modifiers,
            "enabled_adjustment_types": [t.value for t in self.enabled_adjustment_types],
            "max_adjustment_cap": self.max_adjustment_cap,
            "min_score": self.min_score,
            "max_score": self.max_score,
        }


@dataclass
class ScoringVersion:
    """
    Versioned scoring configuration snapshot.
    
    Attributes:
        version_id: Unique version identifier
        version_number: Semantic version
        config: Scoring configuration
        created_at: When version was created
        created_by: Who created version
        is_active: Currently active version
        previous_version: Reference to previous version
        changes_summary: Summary of changes from previous
        rollback_safe: Whether rollback is safe
    """
    version_id: str
    version_number: str
    config: ScoringConfig
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = "system"
    is_active: bool = False
    previous_version: Optional[str] = None
    changes_summary: str = ""
    rollback_safe: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_id": self.version_id,
            "version_number": self.version_number,
            "config": self.config.to_dict(),
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "is_active": self.is_active,
            "previous_version": self.previous_version,
            "changes_summary": self.changes_summary,
            "rollback_safe": self.rollback_safe,
        }


@dataclass
class ScoringExplanation:
    """
    Explanation of score calculation.
    
    Attributes:
        skill_id: Skill being scored
        base_score: Original base score
        final_score: Final adjusted score
        adjustments_applied: List of adjustments applied
        adjustment_breakdown: Breakdown of each adjustment
        total_adjustment: Net adjustment amount
        explanation_text: Human-readable explanation
    """
    skill_id: str
    base_score: float
    final_score: float
    adjustments_applied: List[AdjustmentType] = field(default_factory=list)
    adjustment_breakdown: List[Dict[str, Any]] = field(default_factory=list)
    total_adjustment: float = 0.0
    explanation_text: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "base_score": self.base_score,
            "final_score": self.final_score,
            "adjustments_applied": [a.value for a in self.adjustments_applied],
            "adjustment_breakdown": self.adjustment_breakdown,
            "total_adjustment": self.total_adjustment,
            "explanation_text": self.explanation_text,
        }


@dataclass
class AdaptationEvent:
    """
    Record of scoring adaptation event.
    
    Attributes:
        event_id: Unique identifier
        timestamp: When event occurred
        event_type: Type of adaptation
        trigger: What triggered the adaptation
        skills_affected: Which skills were affected
        old_values: Previous values
        new_values: New values
        impact_assessment: Assessment of change impact
        approved_by: Who approved the change
        rollback_available: Can be rolled back
    """
    event_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str = ""
    trigger: str = ""
    skills_affected: List[str] = field(default_factory=list)
    old_values: Dict[str, Any] = field(default_factory=dict)
    new_values: Dict[str, Any] = field(default_factory=dict)
    impact_assessment: str = ""
    approved_by: Optional[str] = None
    rollback_available: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "trigger": self.trigger,
            "skills_affected": self.skills_affected,
            "old_values": self.old_values,
            "new_values": self.new_values,
            "impact_assessment": self.impact_assessment,
            "approved_by": self.approved_by,
            "rollback_available": self.rollback_available,
        }

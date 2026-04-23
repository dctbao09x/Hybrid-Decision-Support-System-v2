# backend/scoring/dto.py
"""
GĐ7 Canonical DTO — Interface Consistency Gate

Defines the SINGLE canonical data transfer object for scoring output.
ALL scoring engine outputs MUST return ScoreResultDTO.

Rules:
- Immutable (frozen=True)
- No optional score fields
- No aliases
- No fallback mapping

CONTRACT:
- Engine → Controller: ScoreResultDTO only
- No dict, namedtuple, or custom class
- Type validation enforced at boundary

FORBIDDEN FIELDS (legacy):
- final_score (use total_score)
- confidence_score (use components)
- skill_score (use components["study"])
- legacy_score
- normalized_score
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any


@dataclass(frozen=True)
class ScoreResultDTO:
    """Canonical scoring result DTO.
    
    Immutable data transfer object for scoring engine output.
    
    Attributes:
        career_id: Unique career identifier
        total_score: Weighted total score [0, 1]
        components: SIMGR component scores {study, interest, market, growth, risk}
        rank: Ranking position (1-indexed)
        meta: Additional metadata for explainability
        
    Invariants:
        - All fields are required (no Optional)
        - Frozen (immutable after creation)
        - total_score in [0, 1]
        - All component values in [0, 1]
        - rank >= 1
    """
    career_id: str
    total_score: float
    components: Dict[str, float]
    rank: int
    meta: Dict[str, Any]
    
    def __post_init__(self):
        """Validate DTO constraints after initialization."""
        # Validate total_score range
        if not (0.0 <= self.total_score <= 1.0):
            raise ValueError(f"total_score must be in [0, 1], got {self.total_score}")
        
        # Validate rank is positive
        if self.rank < 1:
            raise ValueError(f"rank must be >= 1, got {self.rank}")
        
        # Validate required components
        required_components = {"study", "interest", "market", "growth", "risk"}
        missing = required_components - set(self.components.keys())
        if missing:
            raise ValueError(f"Missing required components: {missing}")
        
        # Validate component values in [0, 1]
        for comp, value in self.components.items():
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"Component '{comp}' must be in [0, 1], got {value}")


def _validate_dto(obj: Any) -> None:
    """Runtime DTO type enforcement.
    
    MUST be called before returning to controller.
    
    Args:
        obj: Object to validate
        
    Raises:
        TypeError: If obj is not ScoreResultDTO
    """
    if not isinstance(obj, ScoreResultDTO):
        raise TypeError(
            f"Invalid scoring DTO: expected ScoreResultDTO, got {type(obj).__name__}. "
            "All scoring outputs must be ScoreResultDTO instances."
        )


def dto_from_scored_career(scored_career: Any, rank: int = 1) -> ScoreResultDTO:
    """Convert ScoredCareer to ScoreResultDTO.
    
    Bridge function for migration from legacy ScoredCareer to DTO.
    
    Args:
        scored_career: ScoredCareer instance from engine
        rank: Ranking position (1-indexed)
        
    Returns:
        ScoreResultDTO instance
        
    Raises:
        TypeError: If input is not valid
        ValueError: If required fields missing
    """
    # Extract career name/id
    career_id = getattr(scored_career, 'career_name', None)
    if career_id is None:
        raise ValueError("scored_career must have career_name attribute")
    
    # Extract total_score
    total_score = getattr(scored_career, 'total_score', None)
    if total_score is None:
        raise ValueError("scored_career must have total_score attribute")
    
    # Extract breakdown components
    breakdown = getattr(scored_career, 'breakdown', None)
    if breakdown is None:
        raise ValueError("scored_career must have breakdown attribute")
    
    components = {
        "study": getattr(breakdown, 'study_score', 0.0),
        "interest": getattr(breakdown, 'interest_score', 0.0),
        "market": getattr(breakdown, 'market_score', 0.0),
        "growth": getattr(breakdown, 'growth_score', 0.0),
        "risk": getattr(breakdown, 'risk_score', 0.0),
    }
    
    # Build meta
    meta = {
        "source": "ScoredCareer",
        "study_details": getattr(breakdown, 'study_details', None),
        "interest_details": getattr(breakdown, 'interest_details', None),
        "market_details": getattr(breakdown, 'market_details', None),
        "growth_details": getattr(breakdown, 'growth_details', None),
        "risk_details": getattr(breakdown, 'risk_details', None),
    }
    
    return ScoreResultDTO(
        career_id=career_id,
        total_score=total_score,
        components=components,
        rank=rank,
        meta=meta,
    )


__all__ = [
    "ScoreResultDTO",
    "_validate_dto",
    "dto_from_scored_career",
]

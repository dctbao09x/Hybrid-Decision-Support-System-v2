# backend/scoring/components/study.py
"""
Study Score Component: Academic performance and skill fit.

SIMGR Formula: S = 0.4*A + 0.3*B + 0.3*C
  - A: Ability (academic ability score)
  - B: Background (skill match with career requirements)
  - C: Confidence (self-assessed confidence level)

This component measures how well the user's academic/learning profile
matches career requirements.
"""

from __future__ import annotations

from typing import Optional, Set
from backend.scoring.models import UserProfile, CareerData, ScoreResult
from backend.scoring.config import ScoringConfig
from backend.scoring.normalizer import DataNormalizer


# =====================================================
# Study Component Weights (A, B, C)
# =====================================================
WEIGHT_ABILITY = 0.4       # A: Ability score
WEIGHT_BACKGROUND = 0.3    # B: Skill background match
WEIGHT_CONFIDENCE = 0.3    # C: Confidence score


def _normalize_set(values: Optional[list[str]]) -> Set[str]:
    """Normalize string list to lowercase set."""
    if not values:
        return set()
    return {str(v).strip().lower() for v in values if v}


def _compute_ability_factor(user: UserProfile) -> float:
    """Compute A (Ability) factor.
    
    Uses user's academic ability score, or infers from education level.
    
    Returns:
        Float in [0, 1] representing ability.
    """
    # Direct ability score if available
    if hasattr(user, 'ability_score') and user.ability_score is not None:
        return max(0.0, min(1.0, user.ability_score))
    
    # Infer from education level
    education_ability = {
        "phd": 0.95,
        "doctorate": 0.95,
        "master": 0.85,
        "master's": 0.85,
        "bachelor": 0.70,
        "bachelor's": 0.70,
        "associate": 0.55,
        "diploma": 0.50,
        "high school": 0.40,
        "secondary": 0.40,
    }
    
    if hasattr(user, 'education_level') and user.education_level:
        level = str(user.education_level).lower().strip()
        return education_ability.get(level, 0.5)
    
    return 0.5  # Default neutral


def _compute_background_factor(
    user: UserProfile,
    job: CareerData,
    config: ScoringConfig,
) -> tuple[float, dict]:
    """Compute B (Background) factor: skill match.
    
    Measures how well user's skills match career requirements.
    
    Returns:
        Tuple of (score, meta dict).
    """
    weights = config.component_weights

    # Normalize skill sets
    user_skills = _normalize_set(user.skills)
    required_skills = _normalize_set(job.required_skills)
    preferred_skills = _normalize_set(job.preferred_skills)

    # Required skill coverage
    if required_skills:
        required_coverage = len(user_skills & required_skills) / len(required_skills)
    else:
        required_coverage = 1.0  # No requirements = satisfied

    # Preferred skill coverage
    if preferred_skills:
        preferred_coverage = len(user_skills & preferred_skills) / len(preferred_skills)
    else:
        preferred_coverage = 0.5  # No preferences = neutral

    # Weighted combination
    background_score = (
        required_coverage * weights.required_skill_match +
        preferred_coverage * weights.preferred_skill_match
    )
    
    meta = {
        "required_coverage": round(required_coverage, 4),
        "preferred_coverage": round(preferred_coverage, 4),
        "matched_required": len(user_skills & required_skills),
        "total_required": len(required_skills),
        "matched_preferred": len(user_skills & preferred_skills),
        "total_preferred": len(preferred_skills),
    }
    
    return background_score, meta


def _compute_confidence_factor(user: UserProfile) -> float:
    """Compute C (Confidence) factor.
    
    Uses user's self-assessed confidence score.
    
    Returns:
        Float in [0, 1] representing confidence.
    """
    # Direct confidence score if available
    if hasattr(user, 'confidence_score') and user.confidence_score is not None:
        return max(0.0, min(1.0, user.confidence_score))
    
    # Default to moderate confidence
    return 0.6


def score(
    job: CareerData,
    user: UserProfile,
    config: ScoringConfig
) -> ScoreResult:
    """Compute study score: S = 0.4*A + 0.3*B + 0.3*C.

    Args:
        job: Career profile
        user: User profile
        config: Scoring config with component weights

    Returns:
        ScoreResult with value [0,1] and meta dict
    """
    normalizer = DataNormalizer()

    # Compute A (Ability)
    ability = _compute_ability_factor(user)
    
    # Compute B (Background)
    background, background_meta = _compute_background_factor(user, job, config)
    
    # Compute C (Confidence)
    confidence = _compute_confidence_factor(user)
    
    # Apply SIMGR Study formula: S = 0.4*A + 0.3*B + 0.3*C
    study_score = (
        WEIGHT_ABILITY * ability +
        WEIGHT_BACKGROUND * background +
        WEIGHT_CONFIDENCE * confidence
    )

    # Clamp to [0, 1]
    study_score = normalizer.clamp(study_score)

    # Meta details
    meta = {
        "ability_A": round(ability, 4),
        "background_B": round(background, 4),
        "confidence_C": round(confidence, 4),
        "formula": "S = 0.4*A + 0.3*B + 0.3*C",
        "weights_used": {
            "ability": WEIGHT_ABILITY,
            "background": WEIGHT_BACKGROUND,
            "confidence": WEIGHT_CONFIDENCE,
        },
        **background_meta,
    }

    if config.debug_mode:
        meta["user_skills"] = sorted(_normalize_set(user.skills))
        meta["required_skills"] = sorted(_normalize_set(job.required_skills))
        meta["preferred_skills"] = sorted(_normalize_set(job.preferred_skills))

    return ScoreResult(value=study_score, meta=meta)

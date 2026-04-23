# backend/scoring/components/risk.py
"""
Risk Score Component: Career risk assessment.

DEPRECATED: This module delegates to backend.risk for SIMGR Stage 3 compliance.

SIMGR Risk Formula: R = 0.25*Saturation + 0.20*Obsolescence + 0.15*Competition + 0.15*Dropout + 0.15*Unemployment + 0.10*Cost
  - Saturation: Market saturation risk
  - Obsolescence: Skill obsolescence risk (AI displacement)
  - Competition: Job market competition
  - Dropout: Likelihood of career abandonment
  - Unemployment: Sector unemployment risk
  - Cost: Entry cost/barrier risk

Returns RAW risk score where 1.0 = high risk, 0.0 = low risk.
This value is SUBTRACTED in the final SIMGR formula.

Migration Note:
  New code should use backend.risk module directly.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from backend.scoring.models import UserProfile, CareerData, ScoreResult
from backend.scoring.config import ScoringConfig
from backend.scoring.normalizer import DataNormalizer

# Import new risk module
from backend.risk import (
    RiskModel,
    RiskPenaltyEngine,
    get_penalty_engine,
)
from backend.risk.model import UserRiskProfile, JobRiskProfile

logger = logging.getLogger(__name__)

# =====================================================
# Risk Component Weights (DEPRECATED - use config)
# These are kept for backward compatibility only.
# New weights are loaded from backend/risk/config.yaml
# =====================================================
WEIGHT_SATURATION = 0.25      # Market saturation
WEIGHT_OBSOLESCENCE = 0.20   # Skill obsolescence
WEIGHT_COMPETITION = 0.15    # Competition
WEIGHT_DROPOUT = 0.15        # Dropout likelihood
WEIGHT_UNEMPLOYMENT = 0.15   # Sector unemployment
WEIGHT_COST = 0.10           # Entry cost barrier


# =====================================================
# Dropout Risk Dataset
# Likelihood of career abandonment (0 = low dropout, 1 = high)
# =====================================================
DROPOUT_RISK_DATASET: Dict[str, float] = {
    # Low dropout risk (stable, established paths)
    "physician": 0.10,
    "nurse": 0.20,
    "pharmacist": 0.15,
    "software engineer": 0.25,
    "data scientist": 0.28,
    "financial analyst": 0.22,
    
    # Moderate dropout risk
    "product manager": 0.35,
    "ux designer": 0.40,
    "marketing manager": 0.38,
    "project manager": 0.32,
    "business analyst": 0.35,
    
    # Higher dropout risk (high burnout, unstable)
    "startup founder": 0.65,
    "freelance developer": 0.55,
    "game developer": 0.50,
    "digital marketer": 0.48,
    "content creator": 0.60,
    "social media manager": 0.55,
    
    "default": 0.35,
}


# =====================================================
# Entry Cost Risk Dataset
# Barrier to entry (0 = easy, 1 = high barrier)
# =====================================================
COST_RISK_DATASET: Dict[str, float] = {
    # High entry cost
    "physician": 0.90,
    "lawyer": 0.85,
    "dentist": 0.88,
    "pharmacist": 0.80,
    "pilot": 0.85,
    
    # Moderate entry cost
    "data scientist": 0.55,
    "software engineer": 0.45,
    "accountant": 0.50,
    "financial analyst": 0.48,
    
    # Low entry cost
    "web developer": 0.30,
    "digital marketer": 0.25,
    "content writer": 0.20,
    "graphic designer": 0.35,
    "social media manager": 0.22,
    
    "default": 0.40,
}


# =====================================================
# Sector Unemployment Risk Dataset
# Based on BLS sector unemployment rates
# =====================================================
UNEMPLOYMENT_RISK_DATASET: Dict[str, float] = {
    # Low unemployment sectors
    "software engineer": 0.15,
    "data scientist": 0.12,
    "cybersecurity analyst": 0.10,
    "nurse": 0.12,
    "physician": 0.08,
    "devops engineer": 0.15,
    
    # Moderate unemployment
    "financial analyst": 0.25,
    "marketing manager": 0.30,
    "project manager": 0.28,
    "business analyst": 0.25,
    
    # Higher unemployment risk
    "graphic designer": 0.45,
    "journalist": 0.48,
    "retail manager": 0.50,
    "event planner": 0.55,
    
    "default": 0.30,
}


def _lookup_value(dataset: Dict[str, float], career_name: str) -> float:
    """Lookup value from dataset with fuzzy matching."""
    if not career_name:
        return dataset["default"]
    
    name_lower = career_name.lower().strip()
    
    # Exact match
    if name_lower in dataset:
        return dataset[name_lower]
    
    # Partial match
    for key, value in dataset.items():
        if key != "default" and (key in name_lower or name_lower in key):
            return value
    
    return dataset["default"]


def _compute_saturation_risk(job: CareerData) -> float:
    """Compute market saturation risk.
    
    High competition = high saturation risk.
    """
    return max(0.0, min(1.0, job.competition))


def _compute_obsolescence_risk(job: CareerData) -> float:
    """Compute skill obsolescence risk.
    
    Low growth rate and low AI relevance = high obsolescence risk.
    """
    # Inverse of growth rate (low growth = high obsolescence)
    growth_factor = 1.0 - job.growth_rate
    
    # Inverse of AI relevance (low AI relevance = vulnerable to automation)
    ai_factor = 1.0 - job.ai_relevance
    
    # Blend both factors
    return max(0.0, min(1.0, (growth_factor + ai_factor) / 2.0))


def _compute_dropout_risk(job: CareerData, user: UserProfile) -> float:
    """Compute career dropout likelihood.
    
    Based on career characteristics and user profile.
    """
    base_risk = _lookup_value(DROPOUT_RISK_DATASET, job.name)
    
    # Adjust based on user confidence if available
    if hasattr(user, 'confidence_score') and user.confidence_score is not None:
        # Higher confidence = lower dropout risk
        confidence_adjustment = (1.0 - user.confidence_score) * 0.2
        base_risk = min(1.0, base_risk + confidence_adjustment)
    
    return base_risk


def _compute_cost_risk(job: CareerData) -> float:
    """Compute entry cost/barrier risk.
    
    High entry barriers = high risk for accessibility.
    """
    return _lookup_value(COST_RISK_DATASET, job.name)


def _compute_unemployment_risk(job: CareerData) -> float:
    """Compute sector unemployment risk.
    
    Based on historical unemployment data for sector.
    """
    base_risk = _lookup_value(UNEMPLOYMENT_RISK_DATASET, job.name)
    
    # Adjust by competition (high competition = higher unemployment risk)
    if hasattr(job, 'competition'):
        competition_adjustment = job.competition * 0.15
        base_risk = min(1.0, base_risk + competition_adjustment)
    
    return base_risk


def score(
    job: CareerData,
    user: UserProfile,
    config: ScoringConfig
) -> ScoreResult:
    """Compute risk score using new Risk Module (SIMGR Stage 3).

    Args:
        job: Career profile
        user: User profile
        config: Scoring config with component weights

    Returns:
        ScoreResult with RAW risk value [0,1] where 1.0 = HIGH risk
        
    Note:
        This value is SUBTRACTED in the final SIMGR formula:
        Score = wS*S + wI*I + wM*M + wG*G - wR*R
        
    Migration:
        This function now delegates to backend.risk module.
    """
    normalizer = DataNormalizer()
    
    try:
        # Create profile objects for new risk module
        user_profile = UserRiskProfile(
            user_id=getattr(user, 'id', 'unknown'),
            education_level=getattr(user, 'education_level', 'bachelor'),
            completion_history=getattr(user, 'completion_history', [0.8]),
            engagement_score=getattr(user, 'engagement_score', 0.7),
        )
        
        job_profile = JobRiskProfile(
            career_name=job.name,
            sector=getattr(job, 'sector', 'technology'),
            region=getattr(job, 'region', 'national'),
            education_cost=getattr(job, 'education_cost', 30000.0),
            training_months=getattr(job, 'training_months', 24),
            avg_salary=getattr(job, 'salary', 60000.0),
        )
        
        # Use new RiskModel
        risk_model = RiskModel()
        risk_result = risk_model.compute_all(
            user=user_profile,
            job=job_profile,
        )
        
        # Extract component values
        dropout_risk = risk_result.get('dropout', 0.3)
        unemployment_risk = risk_result.get('unemployment', 0.2)
        cost_risk = risk_result.get('cost', 0.3)
        
        # Compute saturation from job competition
        saturation_risk = _compute_saturation_risk(job)
        
        # Compute obsolescence from job data
        obsolescence_risk = _compute_obsolescence_risk(job)
        
        # Competition risk
        competition_risk = max(0.0, min(1.0, job.competition))
        
        # Use new penalty engine
        engine = get_penalty_engine()
        total_risk = engine.compute(
            market=saturation_risk,
            skill=obsolescence_risk,
            competition=competition_risk,
            dropout=dropout_risk,
            unemployment=unemployment_risk,
            cost=cost_risk,
        )
        
        # Meta details
        meta = {
            "formula": "R = 0.25*Sat + 0.20*Obs + 0.15*Comp + 0.15*Drop + 0.15*Unemp + 0.10*Cost",
            "saturation_risk": round(saturation_risk, 4),
            "obsolescence_risk": round(obsolescence_risk, 4),
            "competition_risk": round(competition_risk, 4),
            "dropout_risk": round(dropout_risk, 4),
            "unemployment_risk": round(unemployment_risk, 4),
            "cost_risk": round(cost_risk, 4),
            "total_risk": round(total_risk, 4),
            "weights_used": engine.get_weights(),
            "raw_competition": round(job.competition, 4),
            "raw_growth_rate": round(job.growth_rate, 4),
            "raw_ai_relevance": round(job.ai_relevance, 4),
            "module": "backend.risk (SIMGR Stage 3)",
            "note": "RAW risk value (high=bad) - SUBTRACTED in final formula",
        }
        
        return ScoreResult(value=normalizer.clamp(total_risk), meta=meta)
        
    except Exception as e:
        # GĐ7: No backward compatibility - fail fast
        logger.error(f"Risk module failed: {e}")
        raise


# GĐ7: Legacy _legacy_score function REMOVED
# No backward compatibility layer per Interface Consistency Gate requirements

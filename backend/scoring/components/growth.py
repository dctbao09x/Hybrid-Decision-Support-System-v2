# backend/scoring/components/growth.py
"""
Growth Score Component: Career growth potential.

SIMGR Growth Formula: G = 0.35*Demand + 0.35*Salary + 0.30*Lifecycle
  - Demand: Job demand growth (from crawler/forecast)
  - Salary: Salary growth trajectory
  - Lifecycle: Career lifecycle stage factor

This component measures future growth potential of the career.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from backend.scoring.models import UserProfile, CareerData, ScoreResult
from backend.scoring.config import ScoringConfig
from backend.scoring.normalizer import DataNormalizer

logger = logging.getLogger(__name__)


# =====================================================
# Growth Component Weights
# =====================================================
WEIGHT_DEMAND_GROWTH = 0.35    # Job demand trajectory
WEIGHT_SALARY_GROWTH = 0.35   # Salary growth potential
WEIGHT_LIFECYCLE = 0.30       # Career lifecycle stage


# =====================================================
# Career Lifecycle Dataset
# Stage: 0.0 = declining, 0.5 = mature, 1.0 = emerging/growing
# =====================================================
LIFECYCLE_DATASET: Dict[str, float] = {
    # Emerging/high growth careers
    "Machine Learning Engineer": 0.95,
    "AI Engineer": 0.95,
    "data scientist": 0.90,
    "cloud architect": 0.88,
    "devops engineer": 0.85,
    "cybersecurity analyst": 0.85,
    "blockchain developer": 0.80,
    "mlops engineer": 0.92,
    "prompt engineer": 0.95,
    "data engineer": 0.88,
    
    # Growing careers
    "software engineer": 0.80,
    "product manager": 0.78,
    "full stack developer": 0.75,
    "ux designer": 0.72,
    "backend developer": 0.75,
    "frontend developer": 0.70,
    
    # Mature/stable careers
    "business analyst": 0.55,
    "project manager": 0.50,
    "financial analyst": 0.52,
    "marketing manager": 0.50,
    "database administrator": 0.45,
    
    # Declining/transforming careers
    "system administrator": 0.35,
    "technical writer": 0.40,
    "qa tester": 0.38,
    "manual tester": 0.25,
    "data entry operator": 0.15,

    # ── Agriculture / Aquaculture / Food ──────────────────────────────────────
    "agricultural engineer": 0.72,
    "livestock engineer": 0.62,
    "aquaculture engineer": 0.68,
    "agricultural quality inspector": 0.60,
    "food technology engineer": 0.70,

    # ── Construction / Architecture / Infrastructure ──────────────────────────
    "civil construction engineer": 0.62,
    "bridge and road engineer": 0.60,
    "structural architect": 0.65,
    "construction site supervisor": 0.55,
    "construction project manager": 0.60,

    # ── Manufacturing / Industrial Processing ────────────────────────────────
    "manufacturing engineer": 0.58,
    "quality assurance engineer": 0.55,
    "lean six sigma specialist": 0.60,
    "materials engineer": 0.58,
    "production line technician": 0.45,

    # ── Banking / Insurance / Investment ─────────────────────────────────────
    "bank credit specialist": 0.62,
    "investment analyst": 0.70,
    "risk management specialist": 0.72,
    "insurance consultant": 0.58,
    "securities trader": 0.68,

    # ── Tourism / Hospitality / Services ─────────────────────────────────────
    "hotel manager": 0.58,
    "tour operator": 0.55,
    "tour guide": 0.52,
    "restaurant manager": 0.55,
    "event coordinator": 0.62,

    # ── Public Administration / Civil Service / International Relations ───────
    "government official": 0.50,
    "policy planning specialist": 0.55,
    "foreign affairs specialist": 0.58,
    "customs officer": 0.48,
    "public project manager": 0.55,

    # ── Science / Research / Biotechnology ───────────────────────────────────
    "biology researcher": 0.75,
    "applied chemistry researcher": 0.72,
    "biotechnology engineer": 0.85,
    "laboratory testing specialist": 0.65,
    "applied physics researcher": 0.72,

    # ── Arts / Culture / Sports ───────────────────────────────────────────────
    "show director": 0.52,
    "screenwriter": 0.55,
    "sports coach": 0.58,
    "artist manager": 0.52,
    "cultural heritage conservator": 0.48,

    "default": 0.50,  # Neutral
}


# =====================================================
# Demand Forecast Data (5-year growth projections)
# Source modeling: BLS projections, LinkedIn trends
# =====================================================
DEMAND_FORECAST: Dict[str, float] = {
    # High demand growth
    "Machine Learning Engineer": 0.95,
    "AI Engineer": 0.95,
    "data scientist": 0.88,
    "cybersecurity analyst": 0.90,
    "cloud architect": 0.85,
    "devops engineer": 0.82,
    "data engineer": 0.85,
    
    # Moderate demand growth
    "software engineer": 0.75,
    "product manager": 0.70,
    "ux designer": 0.68,
    "full stack developer": 0.72,
    
    # Stable/low demand growth
    "business analyst": 0.55,
    "project manager": 0.52,
    "financial analyst": 0.50,

    # ── Agriculture / Aquaculture / Food ──────────────────────────────────────
    "agricultural engineer": 0.70,
    "livestock engineer": 0.60,
    "aquaculture engineer": 0.65,
    "agricultural quality inspector": 0.62,
    "food technology engineer": 0.68,

    # ── Construction / Architecture / Infrastructure ──────────────────────────
    "civil construction engineer": 0.65,
    "bridge and road engineer": 0.63,
    "structural architect": 0.65,
    "construction site supervisor": 0.60,
    "construction project manager": 0.62,

    # ── Manufacturing / Industrial Processing ────────────────────────────────
    "manufacturing engineer": 0.60,
    "quality assurance engineer": 0.62,
    "lean six sigma specialist": 0.65,
    "materials engineer": 0.58,
    "production line technician": 0.50,

    # ── Banking / Insurance / Investment ─────────────────────────────────────
    "bank credit specialist": 0.65,
    "investment analyst": 0.72,
    "risk management specialist": 0.75,
    "insurance consultant": 0.60,
    "securities trader": 0.68,

    # ── Tourism / Hospitality / Services ─────────────────────────────────────
    "hotel manager": 0.62,
    "tour operator": 0.60,
    "tour guide": 0.58,
    "restaurant manager": 0.60,
    "event coordinator": 0.65,

    # ── Public Administration / Civil Service / International Relations ───────
    "government official": 0.45,
    "policy planning specialist": 0.50,
    "foreign affairs specialist": 0.52,
    "customs officer": 0.48,
    "public project manager": 0.52,

    # ── Science / Research / Biotechnology ───────────────────────────────────
    "biology researcher": 0.72,
    "applied chemistry researcher": 0.68,
    "biotechnology engineer": 0.82,
    "laboratory testing specialist": 0.68,
    "applied physics researcher": 0.70,

    # ── Arts / Culture / Sports ───────────────────────────────────────────────
    "show director": 0.50,
    "screenwriter": 0.52,
    "sports coach": 0.60,
    "artist manager": 0.50,
    "cultural heritage conservator": 0.45,

    "default": 0.50,
}


# =====================================================
# Salary Growth Projections
# =====================================================
SALARY_GROWTH_DATA: Dict[str, float] = {
    # High salary growth potential
    "Machine Learning Engineer": 0.90,
    "AI Engineer": 0.92,
    "cloud architect": 0.88,
    "data scientist": 0.85,
    "cybersecurity analyst": 0.82,
    
    # Moderate salary growth
    "software engineer": 0.75,
    "devops engineer": 0.78,
    "product manager": 0.72,
    "data engineer": 0.80,
    
    # Lower salary growth
    "business analyst": 0.55,
    "project manager": 0.52,
    "qa engineer": 0.48,

    # ── Agriculture / Aquaculture / Food ──────────────────────────────────────
    "agricultural engineer": 0.58,
    "livestock engineer": 0.52,
    "aquaculture engineer": 0.55,
    "agricultural quality inspector": 0.50,
    "food technology engineer": 0.60,

    # ── Construction / Architecture / Infrastructure ──────────────────────────
    "civil construction engineer": 0.60,
    "bridge and road engineer": 0.62,
    "structural architect": 0.65,
    "construction site supervisor": 0.55,
    "construction project manager": 0.65,

    # ── Manufacturing / Industrial Processing ────────────────────────────────
    "manufacturing engineer": 0.58,
    "quality assurance engineer": 0.55,
    "lean six sigma specialist": 0.62,
    "materials engineer": 0.57,
    "production line technician": 0.45,

    # ── Banking / Insurance / Investment ─────────────────────────────────────
    "bank credit specialist": 0.68,
    "investment analyst": 0.75,
    "risk management specialist": 0.72,
    "insurance consultant": 0.60,
    "securities trader": 0.72,

    # ── Tourism / Hospitality / Services ─────────────────────────────────────
    "hotel manager": 0.58,
    "tour operator": 0.52,
    "tour guide": 0.48,
    "restaurant manager": 0.55,
    "event coordinator": 0.60,

    # ── Public Administration / Civil Service / International Relations ───────
    "government official": 0.50,
    "policy planning specialist": 0.55,
    "foreign affairs specialist": 0.58,
    "customs officer": 0.50,
    "public project manager": 0.55,

    # ── Science / Research / Biotechnology ───────────────────────────────────
    "biology researcher": 0.65,
    "applied chemistry researcher": 0.62,
    "biotechnology engineer": 0.75,
    "laboratory testing specialist": 0.60,
    "applied physics researcher": 0.65,

    # ── Arts / Culture / Sports ───────────────────────────────────────────────
    "show director": 0.55,
    "screenwriter": 0.53,
    "sports coach": 0.55,
    "artist manager": 0.55,
    "cultural heritage conservator": 0.45,

    "default": 0.55,
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


def _compute_demand_growth(job: CareerData) -> float:
    """Compute demand growth factor from forecast data.
    
    Uses crawler/forecast data when available, falls back to dataset.
    """
    # Use job's growth_rate if available and valid
    if hasattr(job, 'growth_rate') and job.growth_rate > 0:
        # Blend with forecast data
        forecast = _lookup_value(DEMAND_FORECAST, job.name)
        return (job.growth_rate + forecast) / 2.0
    
    return _lookup_value(DEMAND_FORECAST, job.name)


def _compute_salary_growth(job: CareerData) -> float:
    """Compute salary growth factor.
    
    Uses AI relevance as proxy for salary growth potential.
    """
    base_growth = _lookup_value(SALARY_GROWTH_DATA, job.name)
    
    # Adjust by AI relevance (higher AI relevance = higher salary growth)
    if hasattr(job, 'ai_relevance') and job.ai_relevance > 0:
        ai_factor = job.ai_relevance * 0.3  # 30% weight from AI relevance
        return min(1.0, base_growth * 0.7 + ai_factor)
    
    return base_growth


def _compute_lifecycle_factor(job: CareerData) -> float:
    """Compute career lifecycle stage factor.
    
    Returns factor indicating where career is in lifecycle.
    Higher = emerging/growing, Lower = mature/declining.
    """
    return _lookup_value(LIFECYCLE_DATASET, job.name)


def score(
    job: CareerData,
    user: UserProfile,
    config: ScoringConfig
) -> ScoreResult:
    """Compute growth score: G = 0.35*Demand + 0.35*Salary + 0.30*Lifecycle.

    Args:
        job: Career profile
        user: User profile (unused for this version)
        config: Scoring config with component weights

    Returns:
        ScoreResult with value [0,1] and meta dict
    """
    normalizer = DataNormalizer()

    # Compute growth factors
    demand_growth = _compute_demand_growth(job)
    salary_growth = _compute_salary_growth(job)
    lifecycle_factor = _compute_lifecycle_factor(job)

    # Apply SIMGR Growth formula: G = 0.35*Demand + 0.35*Salary + 0.30*Lifecycle
    growth_score = (
        WEIGHT_DEMAND_GROWTH * demand_growth +
        WEIGHT_SALARY_GROWTH * salary_growth +
        WEIGHT_LIFECYCLE * lifecycle_factor
    )

    # Clamp to [0, 1]
    growth_score = normalizer.clamp(growth_score)

    # Meta details
    meta = {
        "formula": "G = 0.35*Demand + 0.35*Salary + 0.30*Lifecycle",
        "demand_growth": round(demand_growth, 4),
        "salary_growth": round(salary_growth, 4),
        "lifecycle_factor": round(lifecycle_factor, 4),
        "weights_used": {
            "demand": WEIGHT_DEMAND_GROWTH,
            "salary": WEIGHT_SALARY_GROWTH,
            "lifecycle": WEIGHT_LIFECYCLE,
        },
        "raw_growth_rate": round(job.growth_rate, 4) if hasattr(job, 'growth_rate') else 0.0,
        "raw_ai_relevance": round(job.ai_relevance, 4) if hasattr(job, 'ai_relevance') else 0.0,
    }

    return ScoreResult(value=growth_score, meta=meta)

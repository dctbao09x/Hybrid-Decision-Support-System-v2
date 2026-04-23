# backend/scoring/components/interest.py
"""
Interest Score Component: Interest-career alignment.

SIMGR Interest Formula: I = 0.4*NLP + 0.3*Survey + 0.3*Stability
  - NLP: NLP-based semantic interest matching
  - Survey: Self-reported interest alignment (Jaccard similarity)
  - Stability: Interest stability/consistency factor

This component measures how well user interests align with career requirements.
"""

from __future__ import annotations

from typing import Optional, Set, List
from backend.scoring.models import UserProfile, CareerData, ScoreResult
from backend.scoring.config import ScoringConfig
from backend.scoring.normalizer import DataNormalizer


# =====================================================
# Interest Component Weights
# =====================================================
WEIGHT_NLP = 0.4          # NLP-based semantic matching
WEIGHT_SURVEY = 0.3       # Self-reported interest alignment
WEIGHT_STABILITY = 0.3    # Interest stability factor


# =====================================================
# Semantic similarity keywords for NLP matching
# =====================================================
DOMAIN_KEYWORDS = {
    "technology": ["tech", "software", "programming", "coding", "development", "it", "computer", "digital"],
    "ai": ["artificial intelligence", "machine learning", "ml", "deep learning", "neural", "data science"],
    "data": ["analytics", "data", "statistics", "analysis", "visualization", "business intelligence"],
    "finance": ["banking", "investment", "trading", "fintech", "financial", "accounting", "economics"],
    "healthcare": ["medical", "health", "clinical", "pharma", "biotech", "wellness", "hospital"],
    "design": ["ux", "ui", "creative", "graphic", "product design", "visual", "art"],
    "marketing": ["advertising", "brand", "seo", "content", "social media", "digital marketing"],
    "engineering": ["mechanical", "electrical", "civil", "chemical", "engineering", "systems"],
    "management": ["leadership", "project management", "team lead", "operations", "strategy"],
    "research": ["research", "science", "academic", "r&d", "innovation", "experimental"],
}


def _normalize_set(values: Optional[list[str]]) -> Set[str]:
    """Normalize string list to lowercase set."""
    if not values:
        return set()
    return {str(v).strip().lower() for v in values if v}


def _compute_nlp_factor(
    user_interests: Set[str],
    career_interests: Set[str],
    career_domain: Optional[str],
) -> float:
    """Compute NLP-based semantic interest score.
    
    Expands interests using domain keyword mappings for semantic matching.
    
    Returns:
        Float in [0, 1] representing semantic interest alignment.
    """
    if not user_interests:
        return 0.0
    
    # Expand user interests with semantic keywords
    expanded_user = set(user_interests)
    for interest in user_interests:
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if interest in keywords or interest == domain:
                expanded_user.update(keywords)
                expanded_user.add(domain)
    
    # Expand career interests with semantic keywords
    expanded_career = set(career_interests)
    if career_domain:
        domain_lower = career_domain.lower()
        expanded_career.add(domain_lower)
        if domain_lower in DOMAIN_KEYWORDS:
            expanded_career.update(DOMAIN_KEYWORDS[domain_lower])
    
    for interest in career_interests:
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if interest in keywords or interest == domain:
                expanded_career.update(keywords)
                expanded_career.add(domain)
    
    if not expanded_career:
        return 0.5  # Neutral if no career interests
    
    # Semantic overlap score
    overlap = len(expanded_user & expanded_career)
    total = len(expanded_career)
    
    return min(1.0, overlap / total) if total > 0 else 0.5


def _compute_survey_factor(
    user_interests: Set[str],
    career_interests: Set[str],
) -> float:
    """Compute survey-based interest score via Jaccard similarity.
    
    Direct comparison of self-reported interests.
    
    Returns:
        Float in [0, 1] representing interest alignment.
    """
    if not user_interests or not career_interests:
        return 0.0
    
    intersection = len(user_interests & career_interests)
    union = len(user_interests | career_interests)
    
    return intersection / union if union > 0 else 0.0


def _compute_stability_factor(user: UserProfile) -> float:
    """Compute interest stability factor.
    
    Measures how consistent/stable user's interests are.
    Higher stability = more reliable interest signal.
    
    Returns:
        Float in [0, 1] representing stability.
    """
    # Use interest_stability if available on profile
    if hasattr(user, 'interest_stability') and user.interest_stability is not None:
        return max(0.0, min(1.0, user.interest_stability))
    
    # Infer from number of interests (moderate count = more stable)
    if hasattr(user, 'interests') and user.interests:
        count = len(user.interests)
        if count == 0:
            return 0.3  # No interests = low stability signal
        elif count <= 3:
            return 0.7  # Few focused interests = stable
        elif count <= 7:
            return 0.9  # Moderate interests = very stable
        else:
            return 0.6  # Many interests = somewhat scattered
    
    return 0.6  # Default moderate stability


def score(
    job: CareerData,
    user: UserProfile,
    config: ScoringConfig
) -> ScoreResult:
    """Compute interest score: I = 0.4*NLP + 0.3*Survey + 0.3*Stability.

    Args:
        job: Career profile
        user: User profile
        config: Scoring config

    Returns:
        ScoreResult with value [0,1] and meta dict
    """
    normalizer = DataNormalizer()

    # Normalize interest sets
    user_interests = _normalize_set(user.interests)
    career_interests = _normalize_set(job.domain_interests)

    # Add domain as implicit interest if present
    if job.domain:
        career_interests.add(job.domain.strip().lower())

    # Compute factors
    nlp_score = _compute_nlp_factor(user_interests, career_interests, job.domain)
    survey_score = _compute_survey_factor(user_interests, career_interests)
    stability_score = _compute_stability_factor(user)
    
    # Apply SIMGR Interest formula: I = 0.4*NLP + 0.3*Survey + 0.3*Stability
    interest_score = (
        WEIGHT_NLP * nlp_score +
        WEIGHT_SURVEY * survey_score +
        WEIGHT_STABILITY * stability_score
    )

    # Clamp to [0, 1]
    interest_score = normalizer.clamp(interest_score)

    # Meta details
    matched_interests = sorted(user_interests & career_interests)

    meta = {
        "formula": "I = 0.4*NLP + 0.3*Survey + 0.3*Stability",
        "nlp_factor": round(nlp_score, 4),
        "survey_factor": round(survey_score, 4),
        "stability_factor": round(stability_score, 4),
        "weights_used": {
            "nlp": WEIGHT_NLP,
            "survey": WEIGHT_SURVEY,
            "stability": WEIGHT_STABILITY,
        },
        "matched_interests": matched_interests,
        "matched_count": len(matched_interests),
        "user_count": len(user_interests),
        "career_count": len(career_interests),
    }

    if config.debug_mode:
        meta["user_interests"] = sorted(user_interests)
        meta["career_interests"] = sorted(career_interests)

    return ScoreResult(value=interest_score, meta=meta)

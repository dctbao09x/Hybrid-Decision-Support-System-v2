"""
Capture baseline scores for regression testing.

Runs scoring pipeline with fixed inputs and saves outputs as fixtures.
"""

import json
import os
from typing import List, Dict, Any
from backend.scoring import rank_careers
from backend.scoring.models import UserProfile, CareerData


def create_baseline_user() -> UserProfile:
    """Create baseline user profile."""
    return UserProfile(
        skills=["python", "sql", "machine learning"],
        interests=["AI", "data science"],
        education_level="Master",
        ability_score=0.8,
        confidence_score=0.7,
    )


def create_baseline_careers() -> List[CareerData]:
    """Create baseline career list."""
    return [
        CareerData(
            name="Data Scientist",
            required_skills=["python", "statistics"],
            preferred_skills=["machine learning", "sql"],
            domain="data science",
            domain_interests=["AI"],
            ai_relevance=0.9,
            growth_rate=0.85,
            competition=0.6,
        ),
        CareerData(
            name="Software Engineer",
            required_skills=["python"],
            preferred_skills=["system design"],
            domain="software",
            ai_relevance=0.7,
            growth_rate=0.7,
            competition=0.8,
        ),
        CareerData(
            name="Product Manager",
            required_skills=["communication", "strategy"],
            preferred_skills=["analytics"],
            domain="business",
            ai_relevance=0.5,
            growth_rate=0.6,
            competition=0.7,
        ),
    ]


def capture_baseline() -> Dict[str, Any]:
    """Capture baseline scoring results."""
    user = create_baseline_user()
    careers = create_baseline_careers()

    results = rank_careers(user, careers)

    # Convert to serializable format
    baseline = {
        "user_profile": user.model_dump(),
        "careers": [c.model_dump() for c in careers],
        "results": [
            {
                "career_name": r.career_name,
                "total_score": round(r.total_score, 6),
                "breakdown": {
                    "study_score": round(r.breakdown.study_score, 6),
                    "interest_score": round(r.breakdown.interest_score, 6),
                    "market_score": round(r.breakdown.market_score, 6),
                    "growth_score": round(r.breakdown.growth_score, 6),
                    "risk_score": round(r.breakdown.risk_score, 6),
                },
                "rank": r.rank,
            }
            for r in results
        ],
    }

    return baseline


def save_baseline(filepath: str = "backend/tests/scoring/baseline.json") -> None:
    """Save baseline to file."""
    baseline = capture_baseline()

    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    with open(filepath, "w") as f:
        json.dump(baseline, f, indent=2)

    print(f"Baseline saved to {filepath}")


if __name__ == "__main__":
    save_baseline()

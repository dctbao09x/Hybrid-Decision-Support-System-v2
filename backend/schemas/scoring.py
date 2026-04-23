# backend/schemas/scoring.py
"""
Scoring API schemas — structured input/output contracts.

Provides:
  - ScoringInputSnapshot  : hashed, validated input for reproducibility
  - ScoringOutputSchema   : structured scoring response
  - ScoreCard             : single-career result with full breakdown
  - ReproducibilityProof  : evidence for deterministic replay

All schemas are Pydantic v2 BaseModel with strict validation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ══════════════════════════════════════════════════════════════
#  Input Schemas
# ══════════════════════════════════════════════════════════════

class UserProfileInput(BaseModel):
    """User profile as received from API."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    skills: List[str] = Field(
        default_factory=list,
        description="User's technical and soft skills",
    )
    interests: List[str] = Field(
        default_factory=list,
        description="User's career interests",
    )
    education_level: str = Field(
        default="Bachelor",
        description="Highest education level",
    )
    ability_score: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Self-assessed ability [0,1]",
    )
    confidence_score: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Self-assessed confidence [0,1]",
    )


class CareerInput(BaseModel):
    """Career profile as received from API."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(description="Career title")
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    domain: str = Field(default="general")
    domain_interests: List[str] = Field(default_factory=list)
    ai_relevance: float = Field(default=0.5, ge=0.0, le=1.0)
    growth_rate: float = Field(default=0.5, ge=0.0, le=1.0)
    competition: float = Field(default=0.5, ge=0.0, le=1.0)


class ScoringConfigInput(BaseModel):
    """Optional scoring config override."""

    model_config = ConfigDict(extra="forbid")

    strategy: str = Field(
        default="weighted",
        description="Scoring strategy: 'weighted' | 'personalized'",
    )
    weights: Optional[Dict[str, float]] = Field(
        default=None,
        description="Custom SIMGR weights {study, interest, market, growth, risk}",
    )
    min_score_threshold: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Minimum score to include in results",
    )
    debug_mode: bool = Field(
        default=False,
        description="Include component details in output",
    )

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        allowed = {"weighted", "personalized"}
        if v.lower() not in allowed:
            raise ValueError(
                f"strategy must be one of {allowed}, got '{v}'"
            )
        return v.lower()


# ══════════════════════════════════════════════════════════════
#  Input Snapshot — hashed for reproducibility
# ══════════════════════════════════════════════════════════════

class ScoringInputSnapshot(BaseModel):
    """
    Frozen, hashed snapshot of all scoring inputs.

    Used to verify that a re-run uses *identical* inputs.
    Hash algorithm: SHA-256 of deterministic JSON serialization.
    """

    model_config = ConfigDict(extra="forbid")

    user_profile: UserProfileInput
    careers: List[CareerInput]
    config: ScoringConfigInput = Field(default_factory=ScoringConfigInput)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    input_hash: str = Field(
        default="",
        description="SHA-256 of deterministic JSON(user+careers+config)",
    )

    @model_validator(mode="after")
    def compute_hash(self) -> "ScoringInputSnapshot":
        """Auto-compute content hash if not already set."""
        if not self.input_hash:
            self.input_hash = self._compute_hash()
        return self

    def _compute_hash(self) -> str:
        """Deterministic SHA-256 of inputs (excludes timestamp & hash)."""
        payload = {
            "user_profile": self.user_profile.model_dump(),
            "careers": [c.model_dump() for c in self.careers],
            "config": self.config.model_dump(),
        }
        canonical = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, default=str
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def verify(self) -> bool:
        """Re-compute hash and check it matches stored hash."""
        return self._compute_hash() == self.input_hash


# ══════════════════════════════════════════════════════════════
#  Output Schemas
# ══════════════════════════════════════════════════════════════

class ComponentScore(BaseModel):
    """Single SIMGR component result."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Component name (study|interest|market|growth|risk)")
    score: float = Field(ge=0.0, le=1.0, description="Component score")
    weight: float = Field(ge=0.0, le=1.0, description="Weight applied")
    contribution: float = Field(
        ge=0.0, le=1.0,
        description="Weighted contribution = score * weight",
    )
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Debug details (only in debug_mode)",
    )


class ScoreCard(BaseModel):
    """Structured result for a single scored career."""

    model_config = ConfigDict(extra="forbid")

    career_name: str = Field(description="Career title")
    total_score: float = Field(
        ge=0.0, le=1.0, description="Overall weighted SIMGR score"
    )
    rank: int = Field(ge=1, description="Ranking position (1-indexed)")
    components: List[ComponentScore] = Field(
        description="SIMGR component breakdown (5 items)"
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Auto-generated tags (e.g. 'top_study', 'high_growth')",
    )

    @model_validator(mode="after")
    def generate_tags(self) -> "ScoreCard":
        """Auto-tag based on component scores."""
        if self.tags:
            return self
        tags: List[str] = []
        for c in self.components:
            if c.score >= 0.85:
                tags.append(f"top_{c.name}")
            elif c.score <= 0.25:
                tags.append(f"weak_{c.name}")
        if self.total_score >= 0.80:
            tags.append("strong_match")
        elif self.total_score <= 0.30:
            tags.append("weak_match")
        self.tags = sorted(tags)
        return self


class ReproducibilityProof(BaseModel):
    """Evidence that a scoring run is reproducible."""

    model_config = ConfigDict(extra="forbid")

    input_hash: str = Field(description="SHA-256 of inputs")
    output_hash: str = Field(description="SHA-256 of outputs")
    config_hash: str = Field(description="SHA-256 of config used")
    weights_used: Dict[str, float] = Field(
        description="Actual SIMGR weights applied"
    )
    strategy: str = Field(description="Strategy name")
    deterministic: bool = Field(
        default=True, description="True if no stochastic operations"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


class ScoringOutputSchema(BaseModel):
    """Complete structured scoring response."""

    model_config = ConfigDict(extra="forbid")

    # Results
    score_cards: List[ScoreCard] = Field(
        description="Ranked career scorecards"
    )
    total_evaluated: int = Field(
        ge=0, description="Total careers evaluated"
    )
    total_returned: int = Field(
        ge=0, description="Careers returned (after threshold filter)"
    )

    # Config used
    weights_used: Dict[str, float] = Field(
        description="SIMGR weights actually applied"
    )
    strategy: str = Field(description="Strategy name")
    min_threshold: float = Field(
        ge=0.0, le=1.0, description="Score threshold applied"
    )

    # Reproducibility
    reproducibility: ReproducibilityProof = Field(
        description="Deterministic proof"
    )

    # Metadata
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    duration_ms: Optional[float] = Field(
        default=None, description="Scoring duration in milliseconds"
    )

    def output_hash(self) -> str:
        """Compute SHA-256 of scored results (for verification)."""
        payload = [
            {
                "career_name": sc.career_name,
                "total_score": sc.total_score,
                "rank": sc.rank,
                "components": [
                    {"name": c.name, "score": c.score, "weight": c.weight}
                    for c in sc.components
                ],
            }
            for sc in self.score_cards
        ]
        canonical = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, default=str
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════════
#  Builder — converts engine output → structured schema
# ══════════════════════════════════════════════════════════════

def build_scoring_output(
    scored_careers: list,
    config_used: "ScoringConfig",  # type: ignore[name-defined]
    strategy_name: str,
    input_snapshot: Optional[ScoringInputSnapshot] = None,
    duration_ms: Optional[float] = None,
) -> ScoringOutputSchema:
    """
    Convert raw engine output to structured ScoringOutputSchema.

    Parameters
    ----------
    scored_careers : List[ScoredCareer]
        Results from RankingEngine.rank()
    config_used : ScoringConfig
        The ScoringConfig that was actually applied
    strategy_name : str
        Strategy name ("weighted" or "personalized")
    input_snapshot : ScoringInputSnapshot, optional
        Hashed input for reproducibility proof
    duration_ms : float, optional
        Scoring duration in milliseconds

    Returns
    -------
    ScoringOutputSchema
    """
    weights = config_used.simgr_weights
    weights_dict = weights.to_dict()

    # Build score cards
    score_cards: List[ScoreCard] = []
    for sc in scored_careers:
        bd = sc.breakdown
        components = [
            ComponentScore(
                name="study",
                score=round(bd.study_score, 4),
                weight=weights.study_score,
                contribution=round(bd.study_score * weights.study_score, 6),
            ),
            ComponentScore(
                name="interest",
                score=round(bd.interest_score, 4),
                weight=weights.interest_score,
                contribution=round(bd.interest_score * weights.interest_score, 6),
            ),
            ComponentScore(
                name="market",
                score=round(bd.market_score, 4),
                weight=weights.market_score,
                contribution=round(bd.market_score * weights.market_score, 6),
            ),
            ComponentScore(
                name="growth",
                score=round(bd.growth_score, 4),
                weight=weights.growth_score,
                contribution=round(bd.growth_score * weights.growth_score, 6),
            ),
            ComponentScore(
                name="risk",
                score=round(bd.risk_score, 4),
                weight=weights.risk_score,
                contribution=round(bd.risk_score * weights.risk_score, 6),
            ),
        ]
        score_cards.append(
            ScoreCard(
                career_name=sc.career_name,
                total_score=round(sc.total_score, 4),
                rank=sc.rank or (len(score_cards) + 1),
                components=components,
            )
        )

    # Config hash
    cfg_canonical = json.dumps(weights_dict, sort_keys=True, default=str)
    config_hash = hashlib.sha256(cfg_canonical.encode("utf-8")).hexdigest()

    # Output hash
    out_payload = [
        {
            "career_name": sc.career_name,
            "total_score": sc.total_score,
            "rank": sc.rank,
            "components": [
                {"name": c.name, "score": c.score, "weight": c.weight}
                for c in sc.components
            ],
        }
        for sc in score_cards
    ]
    output_hash = hashlib.sha256(
        json.dumps(out_payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    proof = ReproducibilityProof(
        input_hash=input_snapshot.input_hash if input_snapshot else "",
        output_hash=output_hash,
        config_hash=config_hash,
        weights_used=weights_dict,
        strategy=strategy_name,
        deterministic=config_used.deterministic,
    )

    return ScoringOutputSchema(
        score_cards=score_cards,
        total_evaluated=len(scored_careers),
        total_returned=len(score_cards),
        weights_used=weights_dict,
        strategy=strategy_name,
        min_threshold=config_used.min_score_threshold,
        reproducibility=proof,
        duration_ms=duration_ms,
    )

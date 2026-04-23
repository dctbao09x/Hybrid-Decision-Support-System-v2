# backend/scoring/models.py
"""
Data models for scoring engine (Pydantic v2 compatible, SIMGR standard).
"""

from __future__ import annotations

from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict

from backend.scoring.taxonomy_adapter import (
    normalize_skill_list,
    normalize_interest_list,
    normalize_education
)


# ==============================================
# Base Configuration
# ==============================================

class BaseSchema(BaseModel):
    """Base schema with strict validation."""

    # SECURITY: strict mode enabled to prevent implicit coercion.
    # Required for deterministic contract enforcement.
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_default=True,
        validate_assignment=True,
        str_strip_whitespace=True
    )


# ==============================================
# Normalization Utilities
# ==============================================

def normalize_str_list(value: Optional[List[str]]) -> List[str]:
    """Normalize input to clean lowercase string list."""
    if value is None:
        return []

    if isinstance(value, (set, tuple)):
        value = list(value)

    if isinstance(value, list):
        return [
            str(item).lower().strip()
            for item in value
            if str(item).strip()
        ]

    return []


def normalize_str(value: Optional[str]) -> str:
    """Normalize single string to lowercase."""
    if value is None:
        return ""

    return str(value).strip().lower()


# ==============================================
# User Profile
# ==============================================

class UserProfile(BaseSchema):
    """User profile for scoring.
    
    Attributes:
        skills: List of user skills
        interests: List of user interests
        education_level: Highest education level
        ability_score: Self-assessed ability [0, 1]
        confidence_score: Self-assessed confidence [0, 1]
    """

    skills: List[str] = Field(
        default_factory=list,
        description="User's technical and soft skills"
    )
    interests: List[str] = Field(
        default_factory=list,
        description="User's career interests"
    )
    education_level: str = Field(
        default="Bachelor",
        description="Highest education level"
    )
    ability_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Self-assessed ability score"
    )
    confidence_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Self-assessed confidence score"
    )

    # Validators — single canonical pass via taxonomy
    @field_validator("skills", "interests", mode="before")
    @classmethod
    def normalize_lists(cls, v: Optional[List[str]], info) -> List[str]:
        """Normalize skill/interest lists via taxonomy (single pass)."""
        if info.field_name == "skills":
            return normalize_skill_list(v)
        return normalize_interest_list(v)

    @field_validator("education_level", mode="before")
    @classmethod
    def normalize_edu(cls, v: Optional[str]) -> str:
        """Normalize education level via taxonomy."""
        return normalize_education(v)


# ==============================================
# Strict Scoring Input Components
# (All components are mandatory — no defaults, no Optional)
# ==============================================

class PersonalProfileComponent(BaseSchema):
    """Mandatory personal profile component for scoring input.

    Both ability_score and confidence_score are required.
    interests must contain at least one entry.

    No defaults. No Optional fields. No auto-fill.
    """
    ability_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Self-assessed ability score [0, 1]. REQUIRED.",
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Self-assessed confidence score [0, 1]. REQUIRED.",
    )
    interests: List[str] = Field(
        ...,
        min_length=1,
        description="Career interests — at least 1 required.",
    )


class ExperienceComponent(BaseSchema):
    """Mandatory experience component for scoring input.

    No defaults. Caller must supply years and domains.
    """
    years: int = Field(
        ...,
        ge=0,
        description="Years of relevant experience. REQUIRED.",
    )
    domains: List[str] = Field(
        ...,
        description="Experience domains/fields. REQUIRED.",
    )


class GoalsComponent(BaseSchema):
    """Mandatory goals component for scoring input.

    At least one career aspiration is required.
    """
    career_aspirations: List[str] = Field(
        ...,
        min_length=1,
        description="Career aspirations — at least 1 required.",
    )
    timeline_years: int = Field(
        ...,
        ge=0,
        description="Goal timeline in years. REQUIRED.",
    )


class EducationComponent(BaseSchema):
    """Mandatory education component for scoring input.

    Both level and field_of_study must be explicitly supplied.
    """
    level: str = Field(
        ...,
        description="Highest education level. REQUIRED.",
    )
    field_of_study: str = Field(
        ...,
        description="Field / major of study. REQUIRED.",
    )

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, v: Optional[str]) -> str:
        """Normalize education level via taxonomy."""
        return normalize_education(v)


class PreferencesComponent(BaseSchema):
    """Mandatory preferences component for scoring input.

    At least one preferred domain and explicit work style are required.
    """
    preferred_domains: List[str] = Field(
        ...,
        min_length=1,
        description="Preferred career domains — at least 1 required.",
    )
    work_style: str = Field(
        ...,
        description="Preferred work style (e.g. 'remote', 'in-office'). REQUIRED.",
    )


class ScoringInput(BaseSchema):
    """Strict scoring input schema.

    ALL SIX components are mandatory.
    No defaults. No Optional fields. No silent fallbacks.

    Scoring execution MUST NOT proceed unless this schema passes
    validation. The validate_scoring_components() guard enforces
    this at runtime before every scoring call.

    Mandatory components
    --------------------
    personal_profile : PersonalProfileComponent
    experience       : ExperienceComponent
    goals            : GoalsComponent
    skills           : List[str]  (min 1)
    education        : EducationComponent
    preferences      : PreferencesComponent

    Invariants
    ----------
    - extra fields are FORBIDDEN (BaseSchema.extra = \"forbid\")
    - strict mode prevents implicit type coercion
    - validate_default = True catches wrong defaults at import time
    """

    personal_profile: PersonalProfileComponent = Field(
        ...,
        description="Personal profile. REQUIRED.",
    )
    experience: ExperienceComponent = Field(
        ...,
        description="Work / life experience. REQUIRED.",
    )
    goals: GoalsComponent = Field(
        ...,
        description="Career goals. REQUIRED.",
    )
    skills: List[str] = Field(
        ...,
        min_length=1,
        description="User skills — at least 1 required.",
    )
    education: EducationComponent = Field(
        ...,
        description="Education details. REQUIRED.",
    )
    preferences: PreferencesComponent = Field(
        ...,
        description="User preferences. REQUIRED.",
    )

    @field_validator("skills", mode="before")
    @classmethod
    def normalize_skills(cls, v: Optional[List[str]]) -> List[str]:
        """Normalize skills via taxonomy."""
        return normalize_skill_list(v)


# ==============================================
# Career Data
# ==============================================

class CareerData(BaseSchema):
    """Career profile for scoring.
    
    Attributes:
        name: Career title
        required_skills: Must-have skills
        preferred_skills: Nice-to-have skills
        domain: Career domain/category
        domain_interests: Interests relevant to domain
        ai_relevance: AI/tech relevance [0, 1]
        growth_rate: Expected growth rate [0, 1]
        competition: Market competition level [0, 1]
    """

    name: str = Field(
        description="Career title"
    )
    required_skills: List[str] = Field(
        default_factory=list,
        description="Required skills for career"
    )
    preferred_skills: List[str] = Field(
        default_factory=list,
        description="Preferred/nice-to-have skills"
    )
    domain: str = Field(
        default="general",
        description="Career domain"
    )
    domain_interests: List[str] = Field(
        default_factory=list,
        description="Interests aligned with domain"
    )
    ai_relevance: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="AI/tech relevance score"
    )
    growth_rate: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Industry growth rate"
    )
    competition: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Market competition level"
    )

    # Validators
    @field_validator("required_skills", "preferred_skills", mode="before")
    @classmethod
    def normalize_skill_lists(cls, v: Optional[List[str]]) -> List[str]:
        """Normalize skill lists via taxonomy."""
        return normalize_skill_list(v)

    @field_validator("domain_interests", mode="before")
    @classmethod
    def normalize_interest_lists(cls, v: Optional[List[str]]) -> List[str]:
        """Normalize interest lists via taxonomy."""
        return normalize_interest_list(v)

    @field_validator("name", "domain", mode="before")
    @classmethod
    def normalize_strings(cls, v: Optional[str]) -> str:
        """Normalize text fields."""
        return normalize_str(v)


# ==============================================
# Score Breakdown (SIMGR Standard)
# ==============================================

class ScoreBreakdown(BaseSchema):
    """SIMGR score breakdown.
    
    Attributes:
        study_score: Skill match & study fit [0, 1]
        interest_score: Interest alignment [0, 1]
        market_score: Market attractiveness [0, 1]
        growth_score: Growth potential [0, 1]
        risk_score: Risk assessment (inverted) [0, 1]
    """

    study_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Skill match & education fit"
    )
    interest_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Interest alignment"
    )
    market_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Market attractiveness"
    )
    growth_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Growth potential"
    )
    risk_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Risk (inverted, 1.0 = low risk)"
    )

    # Optional detailed breakdowns
    study_details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Detailed study component breakdown"
    )
    interest_details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Detailed interest component breakdown"
    )
    market_details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Detailed market component breakdown"
    )
    growth_details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Detailed growth component breakdown"
    )
    risk_details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Detailed risk component breakdown"
    )


# ==============================================
# Score Result (Component Level)
# ==============================================

class ScoreResult(BaseSchema):
    """Result from a single component scoring.

    Attributes:
        value: Score value in [0, 1]
        meta: Metadata dictionary for explainability
    """

    value: float = Field(
        ge=0.0,
        le=1.0,
        description="Score value"
    )
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata for explainability"
    )


# Rebuild for Pydantic v2 forward references
ScoreResult.model_rebuild()


# ==============================================
# Scoring Result (Job Level)
# ==============================================

class ScoringResult(BaseSchema):
    """Result from scoring a single job/career.

    Attributes:
        career_name: Name of career
        total_score: Overall weighted score [0, 1]
        breakdown: SIMGR component breakdown
        contributions: Component to weight to contribution mapping
        rank: Ranking position (1-indexed)
    """

    career_name: str = Field(
        description="Career title"
    )
    total_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall weighted score"
    )
    breakdown: ScoreBreakdown = Field(
        description="SIMGR breakdown"
    )
    contributions: Dict[str, Dict[str, float]] = Field(
        default_factory=dict,
        description="Component -> {weight: contribution} mapping"
    )
    rank: Optional[int] = Field(
        default=None,
        ge=1,
        description="Ranking position (1-indexed)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "career_name": "AI Engineer",
                "total_score": 0.82,
                "breakdown": {
                    "study_score": 0.85,
                    "interest_score": 0.80,
                    "market_score": 0.88,
                    "growth_score": 0.75,
                    "risk_score": 0.81
                },
                "contributions": {
                    "study": {"weight": 0.25, "contribution": 0.2125},
                    "interest": {"weight": 0.25, "contribution": 0.20},
                    "market": {"weight": 0.25, "contribution": 0.22},
                    "growth": {"weight": 0.15, "contribution": 0.1125},
                    "risk": {"weight": 0.10, "contribution": 0.081}
                },
                "rank": 1
            }
        }
    )


# ==============================================
# Scored Career Result (Legacy)
# ==============================================

class ScoredCareer(BaseSchema):
    """Career with computed score and ranking.

    Attributes:
        career_name: Name of career
        total_score: Overall weighted score [0, 1]
        breakdown: SIMGR component breakdown
        rank: Ranking position (1-indexed)
    """

    career_name: str = Field(
        description="Career title"
    )
    total_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall weighted score"
    )
    breakdown: ScoreBreakdown = Field(
        description="SIMGR breakdown"
    )
    rank: Optional[int] = Field(
        default=None,
        ge=1,
        description="Ranking position (1-indexed)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "career_name": "AI Engineer",
                "total_score": 0.82,
                "breakdown": {
                    "study_score": 0.85,
                    "interest_score": 0.80,
                    "market_score": 0.88,
                    "growth_score": 0.75,
                    "risk_score": 0.81
                },
                "rank": 1
            }
        }
    )


# ==============================================
# Ranking I/O Models
# ==============================================

class RankingInput(BaseSchema):
    """Input for ranking engine.
    
    Attributes:
        user_profile: User profile for matching
        eligible_careers: List of careers to rank
    """

    user_profile: UserProfile = Field(
        description="User profile"
    )
    eligible_careers: List[CareerData] = Field(
        description="Careers to rank"
    )


class RankingOutput(BaseSchema):
    """Output from ranking engine.
    
    Attributes:
        ranked_careers: Sorted list of scored careers
        total_evaluated: Total careers evaluated
        config_used: SIMGR weights used for ranking
    """

    ranked_careers: List[ScoredCareer] = Field(
        description="Ranked career results"
    )
    total_evaluated: int = Field(
        ge=0,
        description="Total careers evaluated"
    )
    config_used: Dict[str, float] = Field(
        description="SIMGR weights used"
    )

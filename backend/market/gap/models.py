# backend/market/gap/models.py
"""
Data models for Career Gap Analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class SkillLevel(Enum):
    """Skill proficiency levels."""
    NONE = 0
    BEGINNER = 1
    INTERMEDIATE = 2
    ADVANCED = 3
    EXPERT = 4


class GapSeverity(Enum):
    """Gap severity classification."""
    CRITICAL = "critical"    # Must-have skill missing
    HIGH = "high"            # Important skill weak
    MEDIUM = "medium"        # Nice-to-have skill missing
    LOW = "low"              # Optional improvement


class ResourceType(Enum):
    """Learning resource types."""
    COURSE = "course"
    TUTORIAL = "tutorial"
    BOOK = "book"
    CERTIFICATION = "certification"
    PROJECT = "project"
    MENTORSHIP = "mentorship"
    BOOTCAMP = "bootcamp"


@dataclass
class UserProfile:
    """
    User's current skill profile.
    
    Attributes:
        user_id: Unique identifier
        name: User name
        current_role: Current job title
        experience_years: Years of experience
        skills: Skill proficiency mapping {skill_id: level}
        education: Education history
        certifications: Held certifications
        interests: Career interests/goals
        constraints: Learning constraints (time, budget)
    """
    user_id: str
    name: str = ""
    current_role: str = ""
    experience_years: float = 0.0
    skills: Dict[str, SkillLevel] = field(default_factory=dict)
    education: List[str] = field(default_factory=list)
    certifications: List[str] = field(default_factory=list)
    interests: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "current_role": self.current_role,
            "experience_years": self.experience_years,
            "skills": {k: v.value for k, v in self.skills.items()},
            "education": self.education,
            "certifications": self.certifications,
            "interests": self.interests,
            "constraints": self.constraints,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfile":
        return cls(
            user_id=data.get("user_id", ""),
            name=data.get("name", ""),
            current_role=data.get("current_role", ""),
            experience_years=data.get("experience_years", 0),
            skills={k: SkillLevel(v) for k, v in data.get("skills", {}).items()},
            education=data.get("education", []),
            certifications=data.get("certifications", []),
            interests=data.get("interests", []),
            constraints=data.get("constraints", {}),
        )


@dataclass
class CareerTarget:
    """
    Target career/role for gap analysis.
    
    Attributes:
        career_id: Career identifier
        title: Job title
        required_skills: Required skills with min levels
        preferred_skills: Preferred skills with target levels
        min_experience: Minimum experience years
        typical_salary_range: Expected salary range
        growth_outlook: Market growth forecast
        demand_score: Current market demand (0-100)
    """
    career_id: str
    title: str
    required_skills: Dict[str, SkillLevel] = field(default_factory=dict)
    preferred_skills: Dict[str, SkillLevel] = field(default_factory=dict)
    min_experience: float = 0.0
    typical_salary_range: Tuple[float, float] = (0, 0)
    growth_outlook: str = "stable"
    demand_score: float = 50.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "career_id": self.career_id,
            "title": self.title,
            "required_skills": {k: v.value for k, v in self.required_skills.items()},
            "preferred_skills": {k: v.value for k, v in self.preferred_skills.items()},
            "min_experience": self.min_experience,
            "typical_salary_range": list(self.typical_salary_range),
            "growth_outlook": self.growth_outlook,
            "demand_score": self.demand_score,
        }


@dataclass
class SkillGap:
    """
    Identified skill gap.
    
    Attributes:
        skill_id: Skill identifier
        skill_name: Skill name
        current_level: User's current level
        required_level: Target level needed
        gap_size: Numeric gap (levels to improve)
        severity: Gap severity
        market_value: Skill's market value/demand
        time_to_close: Estimated months to close gap
        priority_score: Priority for learning (higher = more urgent)
    """
    skill_id: str
    skill_name: str
    current_level: SkillLevel = SkillLevel.NONE
    required_level: SkillLevel = SkillLevel.INTERMEDIATE
    gap_size: int = 0
    severity: GapSeverity = GapSeverity.MEDIUM
    market_value: float = 0.0
    time_to_close: float = 0.0  # Months
    priority_score: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "current_level": self.current_level.value,
            "required_level": self.required_level.value,
            "gap_size": self.gap_size,
            "severity": self.severity.value,
            "market_value": self.market_value,
            "time_to_close": self.time_to_close,
            "priority_score": self.priority_score,
        }


@dataclass
class LearningResource:
    """
    Learning resource recommendation.
    
    Attributes:
        resource_id: Resource identifier
        title: Resource title
        type: Resource type (course, book, etc.)
        provider: Provider (Coursera, Udemy, etc.)
        url: Resource URL
        duration_hours: Estimated duration
        cost: Cost in USD
        skill_coverage: Skills covered {skill_id: level_improvement}
        rating: User rating (0-5)
        difficulty: Difficulty level
        prerequisites: Required prerequisites
    """
    resource_id: str
    title: str
    type: ResourceType = ResourceType.COURSE
    provider: str = ""
    url: str = ""
    duration_hours: float = 0.0
    cost: float = 0.0
    skill_coverage: Dict[str, int] = field(default_factory=dict)  # skill_id -> levels gained
    rating: float = 0.0
    difficulty: SkillLevel = SkillLevel.BEGINNER
    prerequisites: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "title": self.title,
            "type": self.type.value,
            "provider": self.provider,
            "url": self.url,
            "duration_hours": self.duration_hours,
            "cost": self.cost,
            "skill_coverage": self.skill_coverage,
            "rating": self.rating,
            "difficulty": self.difficulty.value,
            "prerequisites": self.prerequisites,
        }


@dataclass
class LearningPath:
    """
    Optimized learning path.
    
    Attributes:
        path_id: Path identifier
        name: Path name
        target_career: Target career
        total_duration: Total duration (months)
        total_cost: Total cost
        milestones: Learning milestones
        resources: Ordered list of resources
        skill_progression: Expected skill progression
        completion_confidence: Probability of successful completion
    """
    path_id: str
    name: str
    target_career: str = ""
    total_duration: float = 0.0  # Months
    total_cost: float = 0.0
    milestones: List[Dict[str, Any]] = field(default_factory=list)
    resources: List[LearningResource] = field(default_factory=list)
    skill_progression: List[Dict[str, Any]] = field(default_factory=list)
    completion_confidence: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "path_id": self.path_id,
            "name": self.name,
            "target_career": self.target_career,
            "total_duration": self.total_duration,
            "total_cost": self.total_cost,
            "milestones": self.milestones,
            "resources": [r.to_dict() for r in self.resources],
            "skill_progression": self.skill_progression,
            "completion_confidence": self.completion_confidence,
        }


@dataclass
class GapAnalysisResult:
    """
    Complete gap analysis result.
    
    Attributes:
        analysis_id: Unique identifier
        user_id: User analyzed
        target: Target career
        timestamp: When analysis was performed
        overall_readiness: Overall readiness score (0-100)
        skill_gaps: Identified skill gaps
        strengths: User's strengths relative to target
        recommended_paths: Recommended learning paths
        time_to_readiness: Estimated months to full readiness
        alternative_targets: Alternative careers to consider
        summary: Human-readable summary
    """
    analysis_id: str
    user_id: str
    target: CareerTarget
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    overall_readiness: float = 0.0
    skill_gaps: List[SkillGap] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    recommended_paths: List[LearningPath] = field(default_factory=list)
    time_to_readiness: float = 0.0
    alternative_targets: List[str] = field(default_factory=list)
    summary: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "user_id": self.user_id,
            "target": self.target.to_dict(),
            "timestamp": self.timestamp.isoformat(),
            "overall_readiness": self.overall_readiness,
            "skill_gaps": [g.to_dict() for g in self.skill_gaps],
            "strengths": self.strengths,
            "recommended_paths": [p.to_dict() for p in self.recommended_paths],
            "time_to_readiness": self.time_to_readiness,
            "alternative_targets": self.alternative_targets,
            "summary": self.summary,
        }


@dataclass
class CareerTrajectory:
    """
    Long-term career trajectory projection.
    
    Attributes:
        trajectory_id: Unique identifier
        user_id: User
        current_role: Starting point
        milestones: Career milestones [(role, years_to_reach)]
        final_target: Ultimate career goal
        total_years: Years to reach final target
        key_skills_needed: Critical skills for trajectory
        salary_progression: Expected salary at each milestone
        risk_factors: Potential risks/blockers
    """
    trajectory_id: str
    user_id: str
    current_role: str = ""
    milestones: List[Tuple[str, float]] = field(default_factory=list)
    final_target: str = ""
    total_years: float = 0.0
    key_skills_needed: List[str] = field(default_factory=list)
    salary_progression: List[Tuple[str, float]] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "trajectory_id": self.trajectory_id,
            "user_id": self.user_id,
            "current_role": self.current_role,
            "milestones": [{"role": r, "years": y} for r, y in self.milestones],
            "final_target": self.final_target,
            "total_years": self.total_years,
            "key_skills_needed": self.key_skills_needed,
            "salary_progression": [{"role": r, "salary": s} for r, s in self.salary_progression],
            "risk_factors": self.risk_factors,
        }

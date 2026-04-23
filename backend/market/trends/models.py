# backend/market/trends/models.py
"""
Data models for Skill Trend & Drift Detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class TrendDirection(Enum):
    """Direction of skill trend."""
    RAPIDLY_GROWING = "rapidly_growing"      # > +20% MoM
    GROWING = "growing"                       # +5% to +20% MoM
    STABLE = "stable"                         # -5% to +5% MoM
    DECLINING = "declining"                   # -5% to -20% MoM
    RAPIDLY_DECLINING = "rapidly_declining"  # < -20% MoM


class TrendSignal(Enum):
    """Type of trend signal."""
    FREQUENCY_SPIKE = "frequency_spike"
    FREQUENCY_DROP = "frequency_drop"
    SALARY_SURGE = "salary_surge"
    SALARY_DROP = "salary_drop"
    NEW_CORRELATION = "new_correlation"
    LOST_CORRELATION = "lost_correlation"
    INDUSTRY_DIVERGENCE = "industry_divergence"
    GEOGRAPHIC_SHIFT = "geographic_shift"
    EXPERIENCE_SHIFT = "experience_shift"


@dataclass
class SkillTrend:
    """
    Trend analysis for a single skill.
    
    Attributes:
        skill_id: Reference to skill
        skill_name: Canonical skill name
        period_start: Start of analysis period
        period_end: End of analysis period
        direction: Overall trend direction
        frequency_velocity: Rate of frequency change (% per month)
        salary_velocity: Rate of salary change (% per month)
        job_count_velocity: Rate of job count change
        frequency_time_series: Historical frequency data [(timestamp, value)]
        salary_time_series: Historical salary data
        confidence: Confidence in trend assessment (0-1)
        signals: Detected trend signals
        supporting_data: Additional data points
    """
    skill_id: str
    skill_name: str
    period_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    period_end: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    direction: TrendDirection = TrendDirection.STABLE
    frequency_velocity: float = 0.0  # % change per month
    salary_velocity: float = 0.0
    job_count_velocity: float = 0.0
    frequency_time_series: List[Tuple[datetime, float]] = field(default_factory=list)
    salary_time_series: List[Tuple[datetime, float]] = field(default_factory=list)
    confidence: float = 1.0
    signals: List[TrendSignal] = field(default_factory=list)
    supporting_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "direction": self.direction.value,
            "frequency_velocity": self.frequency_velocity,
            "salary_velocity": self.salary_velocity,
            "job_count_velocity": self.job_count_velocity,
            "frequency_time_series": [
                (ts.isoformat(), val) for ts, val in self.frequency_time_series
            ],
            "salary_time_series": [
                (ts.isoformat(), val) for ts, val in self.salary_time_series
            ],
            "confidence": self.confidence,
            "signals": [s.value for s in self.signals],
            "supporting_data": self.supporting_data,
        }


@dataclass
class SkillDrift:
    """
    Detected drift in skill requirements/characteristics.
    
    Attributes:
        skill_id: Reference to skill
        drift_type: Type of drift detected
        old_value: Previous state/value
        new_value: New state/value
        magnitude: Drift magnitude (0-1)
        detected_at: When drift was detected
        evidence: Supporting evidence
        affected_careers: Careers affected by this drift
        recommended_action: Suggested response
    """
    skill_id: str
    drift_type: str
    old_value: Any
    new_value: Any
    magnitude: float
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    evidence: List[str] = field(default_factory=list)
    affected_careers: List[str] = field(default_factory=list)
    recommended_action: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "drift_type": self.drift_type,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "magnitude": self.magnitude,
            "detected_at": self.detected_at.isoformat(),
            "evidence": self.evidence,
            "affected_careers": self.affected_careers,
            "recommended_action": self.recommended_action,
        }


@dataclass
class CoSkillPair:
    """
    Co-occurrence relationship between two skills.
    
    Attributes:
        skill_a: First skill ID
        skill_b: Second skill ID
        co_occurrence_rate: How often skills appear together (0-1)
        lift: Lift ratio (co-occurrence vs expected)
        trend: Is this relationship growing or declining
        strength_velocity: Rate of relationship strength change
        first_observed: When relationship was first detected
        context: Common context (industries, roles, etc.)
    """
    skill_a: str
    skill_b: str
    co_occurrence_rate: float
    lift: float = 1.0
    trend: TrendDirection = TrendDirection.STABLE
    strength_velocity: float = 0.0
    first_observed: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_a": self.skill_a,
            "skill_b": self.skill_b,
            "co_occurrence_rate": self.co_occurrence_rate,
            "lift": self.lift,
            "trend": self.trend.value,
            "strength_velocity": self.strength_velocity,
            "first_observed": self.first_observed.isoformat(),
            "context": self.context,
        }


@dataclass
class ChangePoint:
    """
    Detected change point in time series.
    
    Attributes:
        skill_id: Reference to skill
        metric: Which metric changed (frequency, salary, etc.)
        timestamp: When change occurred
        value_before: Average value before change
        value_after: Average value after change
        change_magnitude: Size of change
        confidence: Confidence in detection
        possible_causes: Hypothesized causes
    """
    skill_id: str
    metric: str
    timestamp: datetime
    value_before: float
    value_after: float
    change_magnitude: float
    confidence: float = 1.0
    possible_causes: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "metric": self.metric,
            "timestamp": self.timestamp.isoformat(),
            "value_before": self.value_before,
            "value_after": self.value_after,
            "change_magnitude": self.change_magnitude,
            "confidence": self.confidence,
            "possible_causes": self.possible_causes,
        }


@dataclass
class TrendSnapshot:
    """
    Complete market trend snapshot.
    
    Attributes:
        snapshot_id: Unique identifier
        timestamp: When snapshot was taken
        period_days: Days of historical data analyzed
        total_skills_analyzed: Number of skills in analysis
        rapidly_growing: Skills with rapidly growing trends
        growing: Skills with growing trends
        stable: Skills with stable trends
        declining: Skills with declining trends
        rapidly_declining: Skills with rapidly declining trends
        emerging_correlations: Newly detected skill correlations
        breaking_correlations: Correlations that are weakening
        change_points: Detected change points
        summary: Human-readable summary
    """
    snapshot_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    period_days: int = 90
    total_skills_analyzed: int = 0
    rapidly_growing: List[SkillTrend] = field(default_factory=list)
    growing: List[SkillTrend] = field(default_factory=list)
    stable: List[SkillTrend] = field(default_factory=list)
    declining: List[SkillTrend] = field(default_factory=list)
    rapidly_declining: List[SkillTrend] = field(default_factory=list)
    emerging_correlations: List[CoSkillPair] = field(default_factory=list)
    breaking_correlations: List[CoSkillPair] = field(default_factory=list)
    change_points: List[ChangePoint] = field(default_factory=list)
    summary: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp.isoformat(),
            "period_days": self.period_days,
            "total_skills_analyzed": self.total_skills_analyzed,
            "rapidly_growing": [t.to_dict() for t in self.rapidly_growing],
            "growing": [t.to_dict() for t in self.growing],
            "stable": [t.to_dict() for t in self.stable],
            "declining": [t.to_dict() for t in self.declining],
            "rapidly_declining": [t.to_dict() for t in self.rapidly_declining],
            "emerging_correlations": [p.to_dict() for p in self.emerging_correlations],
            "breaking_correlations": [p.to_dict() for p in self.breaking_correlations],
            "change_points": [cp.to_dict() for cp in self.change_points],
            "summary": self.summary,
        }


@dataclass
class IndustryTrend:
    """
    Industry-specific skill trend.
    """
    industry: str
    top_skills: List[str]
    growing_skills: List[str]
    declining_skills: List[str]
    avg_salary_change: float
    job_volume_change: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class GeographicTrend:
    """
    Geographic skill trend.
    """
    region: str
    top_skills: List[str]
    unique_skills: List[str]  # Skills more prevalent here than elsewhere
    salary_premium: float     # vs national average
    demand_index: float       # Relative demand
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

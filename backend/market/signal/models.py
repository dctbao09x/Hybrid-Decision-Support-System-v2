# backend/market/signal/models.py
"""
Market Signal Data Models
=========================

Schema definitions for market data collection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class DataSource(str, Enum):
    """Supported data sources."""
    VIETNAMWORKS = "vietnamworks"
    TOPCV = "topcv"
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    GLASSDOOR = "glassdoor"
    COMPANY_CAREER = "company_career"
    GOVERNMENT = "government"
    CUSTOM = "custom"


class JobStatus(str, Enum):
    """Job posting status."""
    ACTIVE = "active"
    EXPIRED = "expired"
    FILLED = "filled"
    UNKNOWN = "unknown"


class ExperienceLevel(str, Enum):
    """Experience level categories."""
    INTERN = "intern"
    ENTRY = "entry"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    MANAGER = "manager"
    DIRECTOR = "director"
    EXECUTIVE = "executive"


@dataclass
class SalaryRange:
    """Salary information."""
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    currency: str = "VND"
    period: str = "monthly"  # monthly, yearly, hourly
    negotiable: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "min": self.min_value,
            "max": self.max_value,
            "currency": self.currency,
            "period": self.period,
            "negotiable": self.negotiable,
        }
    
    @property
    def midpoint(self) -> Optional[float]:
        if self.min_value and self.max_value:
            return (self.min_value + self.max_value) / 2
        return self.min_value or self.max_value


@dataclass
class Location:
    """Job location."""
    city: str
    district: Optional[str] = None
    country: str = "Vietnam"
    remote: bool = False
    hybrid: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "city": self.city,
            "district": self.district,
            "country": self.country,
            "remote": self.remote,
            "hybrid": self.hybrid,
        }


@dataclass
class Company:
    """Company information."""
    name: str
    industry: Optional[str] = None
    size: Optional[str] = None  # startup, small, medium, large, enterprise
    website: Optional[str] = None
    logo_url: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "industry": self.industry,
            "size": self.size,
            "website": self.website,
            "logo_url": self.logo_url,
        }


@dataclass
class JobPosting:
    """
    Normalized job posting record.
    
    Core schema for all market data.
    """
    # Identity
    source: DataSource
    source_job_id: str
    internal_id: str = ""
    
    # Core info
    title: str = ""
    company: Optional[Company] = None
    location: Optional[Location] = None
    
    # Compensation
    salary: Optional[SalaryRange] = None
    benefits: List[str] = field(default_factory=list)
    
    # Requirements
    skills: List[str] = field(default_factory=list)
    experience_level: Optional[ExperienceLevel] = None
    experience_years: Optional[float] = None
    education: Optional[str] = None
    
    # Classification
    career_category: Optional[str] = None
    industry: Optional[str] = None
    job_type: str = "full-time"  # full-time, part-time, contract, freelance
    
    # Description
    description: str = ""
    requirements_text: str = ""
    
    # Metadata
    status: JobStatus = JobStatus.ACTIVE
    posted_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    crawled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # URL
    source_url: str = ""
    
    # Raw data for debugging
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.internal_id:
            self.internal_id = f"{self.source.value}_{self.source_job_id}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "internal_id": self.internal_id,
            "source": self.source.value,
            "source_job_id": self.source_job_id,
            "title": self.title,
            "company": self.company.to_dict() if self.company else None,
            "location": self.location.to_dict() if self.location else None,
            "salary": self.salary.to_dict() if self.salary else None,
            "benefits": self.benefits,
            "skills": self.skills,
            "experience_level": self.experience_level.value if self.experience_level else None,
            "experience_years": self.experience_years,
            "education": self.education,
            "career_category": self.career_category,
            "industry": self.industry,
            "job_type": self.job_type,
            "description": self.description,
            "requirements_text": self.requirements_text,
            "status": self.status.value,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "crawled_at": self.crawled_at.isoformat(),
            "source_url": self.source_url,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobPosting":
        """Create from dictionary."""
        company = None
        if data.get("company"):
            company = Company(**data["company"])
        
        location = None
        if data.get("location"):
            location = Location(**data["location"])
        
        salary = None
        if data.get("salary"):
            salary = SalaryRange(
                min_value=data["salary"].get("min"),
                max_value=data["salary"].get("max"),
                currency=data["salary"].get("currency", "VND"),
                period=data["salary"].get("period", "monthly"),
                negotiable=data["salary"].get("negotiable", False),
            )
        
        return cls(
            source=DataSource(data["source"]),
            source_job_id=data["source_job_id"],
            internal_id=data.get("internal_id", ""),
            title=data.get("title", ""),
            company=company,
            location=location,
            salary=salary,
            benefits=data.get("benefits", []),
            skills=data.get("skills", []),
            experience_level=ExperienceLevel(data["experience_level"]) if data.get("experience_level") else None,
            experience_years=data.get("experience_years"),
            education=data.get("education"),
            career_category=data.get("career_category"),
            industry=data.get("industry"),
            job_type=data.get("job_type", "full-time"),
            description=data.get("description", ""),
            requirements_text=data.get("requirements_text", ""),
            status=JobStatus(data.get("status", "active")),
            source_url=data.get("source_url", ""),
        )


@dataclass
class CrawlJob:
    """Crawl job definition."""
    job_id: str
    source: DataSource
    query: Dict[str, Any]  # Search parameters
    priority: int = 5
    max_pages: int = 10
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "pending"  # pending, running, completed, failed
    results_count: int = 0
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "source": self.source.value,
            "query": self.query,
            "priority": self.priority,
            "max_pages": self.max_pages,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "results_count": self.results_count,
            "error_message": self.error_message,
        }


@dataclass
class MarketSnapshot:
    """Point-in-time market snapshot."""
    snapshot_id: str
    timestamp: datetime
    total_jobs: int
    active_jobs: int
    sources: Dict[str, int]  # source -> count
    top_skills: List[Dict[str, Any]]  # skill, count, salary_avg
    top_careers: List[Dict[str, Any]]  # career, count, growth
    regional_distribution: Dict[str, int]  # city -> count
    salary_stats: Dict[str, Any]  # min, max, avg, median by level
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp.isoformat(),
            "total_jobs": self.total_jobs,
            "active_jobs": self.active_jobs,
            "sources": self.sources,
            "top_skills": self.top_skills,
            "top_careers": self.top_careers,
            "regional_distribution": self.regional_distribution,
            "salary_stats": self.salary_stats,
        }


@dataclass
class ChangeEvent:
    """Detected change in market data."""
    event_id: str
    event_type: str  # new_job, job_updated, job_expired, skill_emerged, salary_changed
    timestamp: datetime
    source: DataSource
    entity_id: str
    entity_type: str  # job, skill, career
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    change_magnitude: float = 0.0  # 0-1 significance
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source.value,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "change_magnitude": self.change_magnitude,
        }

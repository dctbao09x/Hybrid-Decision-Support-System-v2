# backend/market/taxonomy/models.py
"""
Taxonomy Auto-Update Models
===========================

Data models for self-evolving skill/career ontology.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class SkillStatus(str, Enum):
    """Skill lifecycle status."""
    EMERGING = "emerging"       # New, being validated
    ACTIVE = "active"          # Confirmed, in use
    STABLE = "stable"          # Well-established
    DECLINING = "declining"    # Decreasing demand
    OBSOLETE = "obsolete"      # No longer relevant
    MERGED = "merged"          # Merged into another skill


class ChangeType(str, Enum):
    """Types of taxonomy changes."""
    SKILL_ADDED = "skill_added"
    SKILL_MERGED = "skill_merged"
    SKILL_SPLIT = "skill_split"
    SKILL_DEPRECATED = "skill_deprecated"
    SYNONYM_ADDED = "synonym_added"
    RELATION_ADDED = "relation_added"
    RELATION_REMOVED = "relation_removed"
    CAREER_UPDATED = "career_updated"


class RelationType(str, Enum):
    """Types of skill relationships."""
    REQUIRES = "requires"       # A requires B
    RELATED = "related"         # A is related to B
    SUPERSEDES = "supersedes"   # A replaces B
    VARIANT = "variant"         # A is variant of B (e.g., React vs ReactJS)
    PARENT = "parent"           # A is parent category of B


@dataclass
class SkillNode:
    """
    A skill in the taxonomy graph.
    """
    skill_id: str
    canonical_name: str
    
    # Aliases and synonyms
    aliases: Set[str] = field(default_factory=set)
    
    # Classification
    category: str = ""          # e.g., "programming", "soft_skill", "tool"
    domain: str = ""            # e.g., "data_science", "web_dev"
    
    # Lifecycle
    status: SkillStatus = SkillStatus.EMERGING
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Market metrics
    frequency: int = 0          # Total occurrences
    job_count: int = 0          # Number of jobs requiring
    avg_salary: Optional[float] = None
    growth_rate: float = 0.0    # YoY growth
    
    # Embedding for similarity
    embedding: Optional[List[float]] = None
    
    # Relations (skill_id -> relation_type)
    relations: Dict[str, RelationType] = field(default_factory=dict)
    
    # Metadata
    source_count: Dict[str, int] = field(default_factory=dict)  # source -> count
    confidence: float = 1.0
    human_verified: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "canonical_name": self.canonical_name,
            "aliases": list(self.aliases),
            "category": self.category,
            "domain": self.domain,
            "status": self.status.value,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "frequency": self.frequency,
            "job_count": self.job_count,
            "avg_salary": self.avg_salary,
            "growth_rate": self.growth_rate,
            "relations": {k: v.value for k, v in self.relations.items()},
            "confidence": self.confidence,
            "human_verified": self.human_verified,
        }


@dataclass
class CareerNode:
    """
    A career/job category in the taxonomy.
    """
    career_id: str
    canonical_name: str
    
    # Aliases
    aliases: Set[str] = field(default_factory=set)
    
    # Classification
    industry: str = ""
    level: str = ""  # entry, mid, senior, executive
    
    # Required skills (skill_id -> importance 0-1)
    required_skills: Dict[str, float] = field(default_factory=dict)
    optional_skills: Dict[str, float] = field(default_factory=dict)
    
    # Market metrics
    job_count: int = 0
    avg_salary_range: Optional[tuple] = None
    growth_rate: float = 0.0
    
    # Related careers
    related_careers: List[str] = field(default_factory=list)
    progression_from: List[str] = field(default_factory=list)
    progression_to: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "career_id": self.career_id,
            "canonical_name": self.canonical_name,
            "aliases": list(self.aliases),
            "industry": self.industry,
            "level": self.level,
            "required_skills": self.required_skills,
            "optional_skills": self.optional_skills,
            "job_count": self.job_count,
            "avg_salary_range": self.avg_salary_range,
            "growth_rate": self.growth_rate,
            "related_careers": self.related_careers,
            "progression_from": self.progression_from,
            "progression_to": self.progression_to,
        }


@dataclass
class TaxonomyVersion:
    """
    A versioned snapshot of the taxonomy.
    """
    version_id: str
    version_number: str  # Semantic versioning
    created_at: datetime
    
    # Stats
    skill_count: int = 0
    career_count: int = 0
    relation_count: int = 0
    
    # Changes from previous version
    changes: List[Dict[str, Any]] = field(default_factory=list)
    
    # Metadata
    auto_generated: bool = True
    human_approved: bool = False
    approved_by: Optional[str] = None
    notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_id": self.version_id,
            "version_number": self.version_number,
            "created_at": self.created_at.isoformat(),
            "skill_count": self.skill_count,
            "career_count": self.career_count,
            "relation_count": self.relation_count,
            "changes": self.changes,
            "auto_generated": self.auto_generated,
            "human_approved": self.human_approved,
            "approved_by": self.approved_by,
            "notes": self.notes,
        }


@dataclass
class TaxonomyChange:
    """
    A proposed or applied taxonomy change.
    """
    change_id: str
    change_type: ChangeType
    timestamp: datetime
    
    # Target entity
    entity_type: str  # skill, career
    entity_id: str
    
    # Change details
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    
    # Confidence and approval
    confidence: float = 1.0
    evidence: List[str] = field(default_factory=list)
    
    # Status
    status: str = "proposed"  # proposed, approved, applied, rejected
    proposed_by: str = "auto"  # auto, human
    reviewed_by: Optional[str] = None
    review_notes: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "change_id": self.change_id,
            "change_type": self.change_type.value,
            "timestamp": self.timestamp.isoformat(),
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "status": self.status,
            "proposed_by": self.proposed_by,
            "reviewed_by": self.reviewed_by,
            "review_notes": self.review_notes,
        }


@dataclass
class MergeCandidate:
    """
    Candidate skills to be merged.
    """
    skill_a: str
    skill_b: str
    similarity: float
    evidence: List[str]
    recommended_canonical: str
    confidence: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_a": self.skill_a,
            "skill_b": self.skill_b,
            "similarity": self.similarity,
            "evidence": self.evidence,
            "recommended_canonical": self.recommended_canonical,
            "confidence": self.confidence,
        }


@dataclass
class SkillCluster:
    """
    Cluster of related skills.
    """
    cluster_id: str
    name: str
    skills: List[str]
    centroid: Optional[List[float]] = None
    coherence: float = 0.0  # How tight the cluster is
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "name": self.name,
            "skills": self.skills,
            "coherence": self.coherence,
        }

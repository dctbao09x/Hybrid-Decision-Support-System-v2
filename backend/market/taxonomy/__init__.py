# backend/market/taxonomy/__init__.py
"""
Taxonomy Auto-Update Engine
===========================

Self-evolving skill/career ontology.

Components:
- SkillNode: Skill representation with embeddings and relations
- CareerNode: Career representation with skill requirements
- TaxonomyEngine: Main engine for taxonomy evolution
"""

from .models import (
    CareerNode,
    ChangeType,
    MergeCandidate,
    RelationType,
    SkillCluster,
    SkillNode,
    SkillStatus,
    TaxonomyChange,
    TaxonomyVersion,
)
from .engine import (
    SkillNormalizer,
    SkillEmbedder,
    TaxonomyEngine,
    get_taxonomy_engine,
)

__all__ = [
    # Models
    "SkillNode",
    "CareerNode",
    "TaxonomyVersion",
    "TaxonomyChange",
    "MergeCandidate",
    "SkillCluster",
    "SkillStatus",
    "ChangeType",
    "RelationType",
    # Engine
    "SkillNormalizer",
    "SkillEmbedder",
    "TaxonomyEngine",
    "get_taxonomy_engine",
]

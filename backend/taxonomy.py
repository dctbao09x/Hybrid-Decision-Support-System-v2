"""
Legacy Taxonomy Module (Backward Compatibility Layer)

This module re-exports taxonomy data as legacy constants while directing
all new usage to the taxonomy facade.
"""

import warnings

from taxonomy.facade import taxonomy
from taxonomy.constants import (
    DATASET_SKILLS,
    DATASET_INTERESTS,
    DATASET_EDUCATION,
    DATASET_INTENTS,
)
from taxonomy.normalizer import MOJIBAKE_MAP


warnings.warn(
    "backend.taxonomy is deprecated. "
    "Use taxonomy.facade.TaxonomyFacade or taxonomy.taxonomy instead.",
    DeprecationWarning,
    stacklevel=2
)


# =========================
# Legacy Constants
# =========================

# Keep name for backward compatibility
VIETNAMESE_MAP = MOJIBAKE_MAP

INTEREST_TAXONOMY = taxonomy.legacy_taxonomy_map(DATASET_INTERESTS)
SKILL_TAXONOMY = taxonomy.legacy_taxonomy_map(DATASET_SKILLS)
EDUCATION_MAPPING = taxonomy.legacy_taxonomy_map(DATASET_EDUCATION)
INTENT_KEYWORDS = taxonomy.legacy_intent_keywords()

__all__ = [
    "VIETNAMESE_MAP",
    "INTEREST_TAXONOMY",
    "SKILL_TAXONOMY",
    "EDUCATION_MAPPING",
    "INTENT_KEYWORDS",
]

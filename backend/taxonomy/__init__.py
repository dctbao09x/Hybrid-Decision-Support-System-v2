"""
Taxonomy package public API.
Centralized normalization, matching, and resolution for the platform.
"""

from .facade import TaxonomyFacade, taxonomy
from .constants import (
    DATASET_SKILLS,
    DATASET_INTERESTS,
    DATASET_EDUCATION,
    DATASET_INTENTS,
)

__all__ = [
    "TaxonomyFacade",
    "taxonomy",
    "DATASET_SKILLS",
    "DATASET_INTERESTS",
    "DATASET_EDUCATION",
    "DATASET_INTENTS",
]

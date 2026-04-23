"""
Schema models for taxonomy datasets.
"""

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class TaxonomyEntry:
    """
    Canonical taxonomy entry.

    Required fields:
    - id: stable identifier
    - canonical_label: display label
    - aliases: per-language alias lists
    - priority: higher wins in ties
    - deprecated: if true, excluded from matching
    """

    id: str
    canonical_label: str
    aliases: Dict[str, List[str]]
    priority: int
    deprecated: bool = False


@dataclass(frozen=True)
class Dataset:
    """Dataset wrapper for entries and metadata."""

    name: str
    entries: List[TaxonomyEntry]

"""
Taxonomy facade: single entry point for normalization & matching.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .constants import (
    DATASET_SKILLS,
    DATASET_INTERESTS,
    DATASET_EDUCATION,
    DATASET_INTENTS,
    DEFAULT_INTENT_ID,
    UNKNOWN_EDUCATION_ID,
    ENV_COMPAT_MODE,
)
from .manager import TaxonomyManager


class TaxonomyFacade:
    """Public API for taxonomy access."""

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        compat_mode: Optional[bool] = None
    ):
        data_dir = base_dir or (Path(__file__).parent / "data")
        self.manager = TaxonomyManager(data_dir)
        self.compat_mode = (
            bool(int(os.getenv(ENV_COMPAT_MODE, "0")))
            if compat_mode is None else bool(compat_mode)
        )

    # -------------------------
    # Normalization helpers
    # -------------------------

    def normalize_text(self, text: str) -> str:
        return self.manager.normalizer.normalize(text)

    def clean_text(self, text: str) -> str:
        return self.manager.normalizer.clean_text(text)

    # -------------------------
    # Resolution APIs
    # -------------------------

    def resolve_skills(
        self,
        text: str,
        *,
        return_ids: bool = False
    ) -> List[str]:
        entries = self.manager.resolve_all(DATASET_SKILLS, text)
        return [e.id if return_ids else e.canonical_label for e in entries]

    def resolve_interests(
        self,
        interests: Iterable[str],
        *,
        return_ids: bool = False
    ) -> List[str]:
        entries = self.manager.resolve_many(DATASET_INTERESTS, interests)
        return [e.id if return_ids else e.canonical_label for e in entries]

    def resolve_education(
        self,
        text: str,
        *,
        return_id: bool = True
    ) -> str:
        entry = self.manager.resolve_education(text)
        if not entry:
            return UNKNOWN_EDUCATION_ID
        if return_id:
            return entry.id
        if self.compat_mode and entry.id == UNKNOWN_EDUCATION_ID:
            return "unknown"
        return entry.canonical_label

    def detect_intent(self, text: str, *, return_id: bool = True) -> str:
        entry = self.manager.detect_intent(text)
        if not entry:
            return DEFAULT_INTENT_ID
        if return_id:
            return entry.id
        return entry.canonical_label

    def resolve_skill_list(
        self,
        skills: Iterable[str],
        *,
        return_ids: bool = False,
        include_unmatched: bool = True
    ) -> List[str]:
        resolved: List[str] = []
        for raw in skills or []:
            text = str(raw).strip()
            if not text:
                continue
            matches = self.manager.resolve_all(DATASET_SKILLS, text)
            if matches:
                resolved.extend(
                    [e.id if return_ids else e.canonical_label for e in matches]
                )
            elif include_unmatched:
                resolved.append(text)

        # De-dup deterministically
        seen = set()
        ordered: List[str] = []
        for item in resolved:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(item)
        return ordered

    def resolve_interest_list(
        self,
        interests: Iterable[str],
        *,
        return_ids: bool = False,
        include_unmatched: bool = True
    ) -> List[str]:
        resolved: List[str] = []
        for raw in interests or []:
            text = str(raw).strip()
            if not text:
                continue
            matches = self.manager.resolve_all(DATASET_INTERESTS, text)
            if matches:
                resolved.extend(
                    [e.id if return_ids else e.canonical_label for e in matches]
                )
            elif include_unmatched:
                resolved.append(text)

        seen = set()
        ordered: List[str] = []
        for item in resolved:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(item)
        return ordered

    # -------------------------
    # Legacy compatibility
    # -------------------------

    def legacy_taxonomy_map(self, dataset: str) -> Dict[str, str]:
        """
        Return alias->canonical_label map (legacy compatibility).
        """
        ds = self.manager.get_dataset(dataset)
        mapping: Dict[str, str] = {}
        for entry in ds.entries:
            if entry.deprecated:
                continue
            mapping[entry.canonical_label] = entry.canonical_label
            for values in entry.aliases.values():
                for alias in values:
                    mapping[alias] = entry.canonical_label
        return mapping

    def legacy_intent_keywords(self) -> Dict[str, List[str]]:
        """
        Legacy intent keyword map: intent_id -> aliases.
        """
        mapping: Dict[str, List[str]] = {}
        for entry in self.manager.intents.entries:
            aliases: List[str] = []
            aliases.append(entry.canonical_label)
            for values in entry.aliases.values():
                aliases.extend(values)
            mapping[entry.id] = [a for a in aliases if a]
        return mapping

    # -------------------------
    # Validation & Reports
    # -------------------------

    def self_check(self) -> Dict[str, int]:
        return self.manager.self_check()

    def coverage_report(self) -> Dict[str, Dict[str, int]]:
        return self.manager.coverage_report()


taxonomy = TaxonomyFacade()

"""
Taxonomy manager: loads datasets, indexes aliases, and resolves matches.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .constants import (
    DATASET_SKILLS,
    DATASET_INTERESTS,
    DATASET_EDUCATION,
    DATASET_INTENTS,
    DEFAULT_INTENT_ID,
    UNKNOWN_EDUCATION_ID,
)
from .schema import Dataset, TaxonomyEntry
from .loader import load_all_datasets, TaxonomyLoadError
from .normalizer import TextNormalizer
from .matcher import TaxonomyMatcher


@dataclass(frozen=True)
class TaxonomyMatch:
    entry: TaxonomyEntry
    match_type: str
    alias: str


class TaxonomyManager:
    """Central taxonomy resolver."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.normalizer = TextNormalizer()
        self.matcher = TaxonomyMatcher(self.normalizer)

        self.skills: Dataset
        self.interests: Dataset
        self.education: Dataset
        self.intents: Dataset

        self._by_dataset: Dict[str, Dataset] = {}
        self._index: Dict[str, Dict[str, List[TaxonomyEntry]]] = {}

        self._load()

    # ----------------------------
    # Load + Index
    # ----------------------------

    def _load(self) -> None:
        self.skills, self.interests, self.education, self.intents = load_all_datasets(
            self.base_dir
        )
        self._by_dataset = {
            DATASET_SKILLS: self.skills,
            DATASET_INTERESTS: self.interests,
            DATASET_EDUCATION: self.education,
            DATASET_INTENTS: self.intents,
        }
        self._build_indexes()

    def _build_indexes(self) -> None:
        self._index = {}
        for name, dataset in self._by_dataset.items():
            alias_map: Dict[str, List[TaxonomyEntry]] = {}
            for entry in dataset.entries:
                aliases = [entry.canonical_label]
                for values in entry.aliases.values():
                    aliases.extend(values)
                for alias in aliases:
                    norm = self.normalizer.normalize(alias)
                    if not norm:
                        continue
                    alias_map.setdefault(norm, []).append(entry)
            self._index[name] = alias_map

    # ----------------------------
    # Validation / Self-Check
    # ----------------------------

    def self_check(self) -> Dict[str, int]:
        """Startup self-check: ensure datasets loaded and indexed."""
        counts = {}
        for name, dataset in self._by_dataset.items():
            counts[name] = len(dataset.entries)
        return counts

    def coverage_report(self) -> Dict[str, Dict[str, int]]:
        """Coverage report for aliases and deprecated entries."""
        report: Dict[str, Dict[str, int]] = {}
        for name, dataset in self._by_dataset.items():
            alias_count = 0
            deprecated = 0
            for entry in dataset.entries:
                if entry.deprecated:
                    deprecated += 1
                for values in entry.aliases.values():
                    alias_count += len(values)
            report[name] = {
                "entries": len(dataset.entries),
                "aliases": alias_count,
                "deprecated": deprecated,
            }
        return report

    # ----------------------------
    # Accessors
    # ----------------------------

    def get_dataset(self, name: str) -> Dataset:
        if name not in self._by_dataset:
            raise KeyError(f"Unknown dataset: {name}")
        return self._by_dataset[name]

    def get_entry(self, dataset: str, entry_id: str) -> Optional[TaxonomyEntry]:
        ds = self.get_dataset(dataset)
        for entry in ds.entries:
            if entry.id == entry_id:
                return entry
        return None

    # ----------------------------
    # Matching
    # ----------------------------

    def resolve_best(self, dataset: str, text: str) -> Optional[TaxonomyEntry]:
        ds = self.get_dataset(dataset)
        matches = self.matcher.match_all(text, ds.entries)
        best = self.matcher.select_best(matches)
        return best.entry if best else None

    def resolve_all(self, dataset: str, text: str) -> List[TaxonomyEntry]:
        ds = self.get_dataset(dataset)
        matches = self.matcher.match_all(text, ds.entries)
        return self.matcher.select_unique_entries(matches)

    def resolve_many(self, dataset: str, texts: Iterable[str]) -> List[TaxonomyEntry]:
        results: List[TaxonomyEntry] = []
        for text in texts:
            results.extend(self.resolve_all(dataset, text))
        # de-dup deterministically
        seen = set()
        ordered: List[TaxonomyEntry] = []
        for entry in results:
            if entry.id in seen:
                continue
            seen.add(entry.id)
            ordered.append(entry)
        return ordered

    # ----------------------------
    # Intent Detection
    # ----------------------------

    def detect_intent(self, text: str) -> TaxonomyEntry:
        if not text:
            return self.get_entry(DATASET_INTENTS, DEFAULT_INTENT_ID)

        cleaned = self.normalizer.clean_text(text)
        normalized = self.normalizer.normalize(text)

        best_entry = None
        best_score = -1
        best_priority = -1

        for entry in self.intents.entries:
            if entry.deprecated:
                continue

            score = 0
            aliases = [entry.canonical_label]
            for values in entry.aliases.values():
                aliases.extend(values)

            for alias in aliases:
                if not alias:
                    continue
                alias_clean = self.normalizer.clean_text(alias)
                alias_norm = self.normalizer.normalize(alias)
                if alias_clean:
                    score += cleaned.count(alias_clean)
                if alias_norm:
                    score += normalized.count(alias_norm)

            if score > best_score or (
                score == best_score and entry.priority > best_priority
            ):
                best_score = score
                best_priority = entry.priority
                best_entry = entry

        if best_entry and best_score > 0:
            return best_entry

        return self.get_entry(DATASET_INTENTS, DEFAULT_INTENT_ID)

    # ----------------------------
    # Education Rank
    # ----------------------------

    def get_education_rank(self, education_id: str) -> int:
        entry = self.get_entry(DATASET_EDUCATION, education_id)
        if not entry:
            return 0
        return entry.priority

    def resolve_education(self, text: str) -> Optional[TaxonomyEntry]:
        if not text:
            return self.get_entry(DATASET_EDUCATION, UNKNOWN_EDUCATION_ID)
        return self.resolve_best(DATASET_EDUCATION, text) or self.get_entry(
            DATASET_EDUCATION, UNKNOWN_EDUCATION_ID
        )

    # ----------------------------
    # Reload
    # ----------------------------

    def reload(self) -> None:
        try:
            self._load()
        except TaxonomyLoadError:
            # Fail loudly; caller should handle.
            raise

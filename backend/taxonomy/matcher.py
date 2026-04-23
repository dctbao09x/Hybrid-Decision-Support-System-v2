"""
Deterministic matcher for taxonomy entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Tuple

from .schema import TaxonomyEntry
from .constants import (
    MATCH_WEIGHT_EXACT,
    MATCH_WEIGHT_ALIAS,
    MATCH_WEIGHT_SUBSTRING,
)
from .normalizer import TextNormalizer


class MatchType(str, Enum):
    EXACT = "exact"
    ALIAS = "alias"
    SUBSTRING = "substring"

    def weight(self) -> int:
        if self == MatchType.EXACT:
            return MATCH_WEIGHT_EXACT
        if self == MatchType.ALIAS:
            return MATCH_WEIGHT_ALIAS
        return MATCH_WEIGHT_SUBSTRING


@dataclass(frozen=True)
class MatchResult:
    entry: TaxonomyEntry
    match_type: MatchType
    alias: str

    def score(self) -> int:
        return self.match_type.weight()


class TaxonomyMatcher:
    """Matcher with exact + alias + substring logic."""

    def __init__(self, normalizer: TextNormalizer):
        self.normalizer = normalizer

    def _all_aliases(self, entry: TaxonomyEntry) -> List[str]:
        aliases = [entry.canonical_label]
        for values in entry.aliases.values():
            aliases.extend(values)
        return [a for a in aliases if a]

    def match_all(
        self,
        text: str,
        entries: Iterable[TaxonomyEntry]
    ) -> List[MatchResult]:
        if not text:
            return []

        cleaned = self.normalizer.clean_text(text)
        normalized = self.normalizer.normalize(text)

        results: List[MatchResult] = []
        for entry in entries:
            if entry.deprecated:
                continue
            for alias in self._all_aliases(entry):
                alias_clean = self.normalizer.clean_text(alias)
                alias_norm = self.normalizer.normalize(alias)

                if not alias_norm:
                    continue

                if normalized == alias_norm or cleaned == alias_clean:
                    results.append(
                        MatchResult(entry, MatchType.EXACT, alias)
                    )
                    continue

                if alias_clean and alias_clean in cleaned:
                    results.append(
                        MatchResult(entry, MatchType.ALIAS, alias)
                    )
                    continue

                if alias_norm and alias_norm in normalized:
                    results.append(
                        MatchResult(entry, MatchType.SUBSTRING, alias)
                    )

        return results

    def select_best(self, matches: List[MatchResult]) -> MatchResult | None:
        if not matches:
            return None

        def sort_key(m: MatchResult) -> Tuple[int, int, int, str]:
            alias_len = len(m.alias or "")
            return (
                m.score(),
                m.entry.priority,
                alias_len,
                m.entry.id
            )

        matches.sort(key=sort_key, reverse=True)
        return matches[0]

    def select_unique_entries(
        self,
        matches: List[MatchResult]
    ) -> List[TaxonomyEntry]:
        seen = set()
        ordered: List[TaxonomyEntry] = []

        def sort_key(m: MatchResult) -> Tuple[int, int, int, str]:
            alias_len = len(m.alias or "")
            return (
                m.score(),
                m.entry.priority,
                alias_len,
                m.entry.id
            )

        for match in sorted(matches, key=sort_key, reverse=True):
            if match.entry.id in seen:
                continue
            seen.add(match.entry.id)
            ordered.append(match.entry)

        return ordered

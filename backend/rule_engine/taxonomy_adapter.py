"""
Rule engine taxonomy adapter (deterministic normalization).
"""

from typing import Iterable, List

from backend.taxonomy.facade import taxonomy


def normalize_skill_list(values: Iterable[str]) -> List[str]:
    return taxonomy.resolve_skill_list(values or [], return_ids=False)


def normalize_interest_list(values: Iterable[str]) -> List[str]:
    return taxonomy.resolve_interest_list(values or [], return_ids=False)


def normalize_education(value: str) -> str:
    if not value:
        return "unknown"
    label = taxonomy.resolve_education(value, return_id=False)
    if str(label).lower() == "unknown":
        return "unknown"
    return label


def education_rank(value: str) -> int:
    entry_id = taxonomy.resolve_education(value, return_id=True)
    return taxonomy.manager.get_education_rank(entry_id)

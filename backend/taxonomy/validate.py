"""
Validation utilities for taxonomy datasets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from .facade import taxonomy
from .constants import (
    DATASET_SKILLS,
    DATASET_INTERESTS,
    DATASET_EDUCATION,
    DATASET_INTENTS,
)


def startup_check() -> Dict[str, int]:
    """
    Basic startup self-check: confirm datasets are loaded.
    """
    return taxonomy.self_check()


def coverage_report() -> Dict[str, Dict[str, int]]:
    """
    Coverage report: counts of entries + aliases + deprecated.
    """
    return taxonomy.coverage_report()


def validate_legacy_mapping() -> Dict[str, List[str]]:
    """
    Validate that legacy mappings resolve to the same canonical label.
    Returns dict of dataset -> list of mismatches.
    """

    data_path = Path(__file__).parent / "data" / "legacy_mapping.json"
    raw = json.loads(data_path.read_text(encoding="utf-8"))

    mismatches: Dict[str, List[str]] = {
        DATASET_SKILLS: [],
        DATASET_INTERESTS: [],
        DATASET_EDUCATION: [],
        DATASET_INTENTS: [],
    }

    for dataset, mapping in raw.items():
        if dataset == DATASET_SKILLS:
            resolver = lambda s: taxonomy.resolve_skills(s, return_ids=False)
        elif dataset == DATASET_INTERESTS:
            resolver = lambda s: taxonomy.resolve_interests([s], return_ids=False)
        elif dataset == DATASET_EDUCATION:
            resolver = lambda s: [taxonomy.resolve_education(s, return_id=False)]
        elif dataset == DATASET_INTENTS:
            resolver = lambda s: [s] if taxonomy.manager.get_entry(DATASET_INTENTS, s) else []
        else:
            continue

        for legacy_value, expected in mapping.items():
            resolved = resolver(legacy_value)
            if not resolved:
                mismatches[dataset].append(legacy_value)
                continue
            if expected not in resolved:
                mismatches[dataset].append(legacy_value)

    return mismatches

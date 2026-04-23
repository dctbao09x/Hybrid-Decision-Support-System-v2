"""
Dataset loader with schema validation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from .schema import TaxonomyEntry, Dataset
from .constants import SUPPORTED_LANGS


class TaxonomyLoadError(ValueError):
    """Raised when taxonomy datasets are invalid."""


def _validate_entry(raw: Dict, idx: int, dataset: str) -> TaxonomyEntry:
    missing = [k for k in ("id", "canonical_label", "aliases", "priority", "deprecated") if k not in raw]
    if missing:
        raise TaxonomyLoadError(
            f"{dataset}[{idx}] missing fields: {', '.join(missing)}"
        )

    entry_id = str(raw["id"]).strip()
    if not entry_id:
        raise TaxonomyLoadError(f"{dataset}[{idx}] empty id")

    canonical_label = str(raw["canonical_label"]).strip()
    if not canonical_label:
        raise TaxonomyLoadError(f"{dataset}[{idx}] empty canonical_label")

    aliases = raw["aliases"]
    if not isinstance(aliases, dict):
        raise TaxonomyLoadError(f"{dataset}[{idx}] aliases must be object")

    normalized_aliases: Dict[str, List[str]] = {}
    for lang in SUPPORTED_LANGS:
        values = aliases.get(lang, [])
        if values is None:
            values = []
        if not isinstance(values, list):
            raise TaxonomyLoadError(
                f"{dataset}[{idx}] aliases.{lang} must be list"
            )
        normalized_aliases[lang] = [str(v).strip() for v in values if str(v).strip()]

    try:
        priority = int(raw["priority"])
    except Exception as exc:
        raise TaxonomyLoadError(
            f"{dataset}[{idx}] invalid priority"
        ) from exc

    deprecated = bool(raw["deprecated"])

    return TaxonomyEntry(
        id=entry_id,
        canonical_label=canonical_label,
        aliases=normalized_aliases,
        priority=priority,
        deprecated=deprecated
    )


def load_dataset(path: Path, dataset_name: str) -> Dataset:
    if not path.exists():
        raise TaxonomyLoadError(f"Missing dataset: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise TaxonomyLoadError(f"{dataset_name} must be a list")

    entries: List[TaxonomyEntry] = []
    ids = set()

    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise TaxonomyLoadError(
                f"{dataset_name}[{idx}] must be object"
            )
        entry = _validate_entry(item, idx, dataset_name)
        if entry.id in ids:
            raise TaxonomyLoadError(
                f"{dataset_name} duplicate id: {entry.id}"
            )
        ids.add(entry.id)
        entries.append(entry)

    return Dataset(name=dataset_name, entries=entries)


def load_all_datasets(base_dir: Path) -> Tuple[Dataset, Dataset, Dataset, Dataset]:
    skills = load_dataset(base_dir / "skills.json", "skills")
    interests = load_dataset(base_dir / "interests.json", "interests")
    education = load_dataset(base_dir / "education.json", "education")
    intents = load_dataset(base_dir / "intents.json", "intents")
    return skills, interests, education, intents

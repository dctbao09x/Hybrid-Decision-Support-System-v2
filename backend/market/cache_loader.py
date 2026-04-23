"""Market cache loader used by scoring.

This module guarantees scoring reads market data from cache only.
No realtime API calls are performed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


SOURCE_TRUST_WEIGHTS: Dict[str, float] = {
    "vietnamworks": 0.90,
    "topcv": 0.88,
    "linkedin": 0.86,
    "indeed": 0.84,
    "glassdoor": 0.84,
    "adzuna": 0.80,
    "rapidapi": 0.78,
    "custom_crawler": 0.72,
    "custom": 0.70,
}

DEFAULT_MAX_AGE_HOURS = int(os.getenv("MARKET_CACHE_MAX_AGE_HOURS", "72"))
DEFAULT_MIN_TRUST_SCORE = float(os.getenv("MARKET_SIGNAL_MIN_TRUST_SCORE", "0.45"))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class CacheMeta:
    updated_at: Optional[datetime]
    entries_count: int
    fresh: bool
    max_age_hours: int


@dataclass(frozen=True)
class MarketSignalAssessment:
    career_name: str
    demand_level: str
    salary_range: Dict[str, Any]
    growth_rate: float
    competition_level: str
    ai_relevance: float
    source_trust_score: float
    stale: bool
    age_hours: Optional[float]
    signal_count: int
    sources: List[str]
    missing_required_fields: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "career_name": self.career_name,
            "demand_level": self.demand_level,
            "salary_range": self.salary_range,
            "growth_rate": self.growth_rate,
            "competition_level": self.competition_level,
            "ai_relevance": self.ai_relevance,
            "source_trust_score": self.source_trust_score,
            "stale": self.stale,
            "age_hours": self.age_hours,
            "signal_count": self.signal_count,
            "sources": self.sources,
            "missing_required_fields": self.missing_required_fields,
        }


class MarketCacheLoader:
    """Reads and indexes market cache for deterministic scoring usage."""

    def __init__(self, cache_path: Optional[Path] = None):
        root = Path(__file__).resolve().parents[2]
        self.cache_path = cache_path or (root / "data" / "market_cache.json")
        self._lock = RLock()
        self._cache_doc: Dict[str, Any] = {"version": "1.0", "updated_at": None, "entries": []}
        self._index_by_title: Dict[str, Dict[str, Any]] = {}
        self._all_by_title: Dict[str, List[Dict[str, Any]]] = {}
        self._last_loaded_mtime: Optional[float] = None

    def load(self) -> Dict[str, Any]:
        with self._lock:
            if not self.cache_path.exists():
                logger.warning("Market cache file not found: %s", self.cache_path)
                self._cache_doc = {"version": "1.0", "updated_at": None, "entries": []}
                self._index_by_title = {}
                self._all_by_title = {}
                self._last_loaded_mtime = None
                return self._cache_doc

            mtime = self.cache_path.stat().st_mtime
            if self._last_loaded_mtime is not None and mtime == self._last_loaded_mtime:
                return self._cache_doc

            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            entries = raw.get("entries") or []
            if not isinstance(entries, list):
                entries = []

            self._cache_doc = {
                "version": str(raw.get("version", "1.0")),
                "updated_at": raw.get("updated_at"),
                "entries": entries,
            }
            self._index_by_title = self._build_index(entries)
            self._all_by_title = self._build_all_index(entries)
            self._last_loaded_mtime = mtime

            logger.info(
                "Market cache loaded | path=%s | entries=%s",
                self.cache_path,
                len(entries),
            )
            return self._cache_doc

    def meta(self, max_age_hours: int = 24) -> CacheMeta:
        doc = self.load()
        updated_at_raw = doc.get("updated_at")
        parsed: Optional[datetime] = None
        fresh = False
        if isinstance(updated_at_raw, str):
            try:
                parsed = _parse_iso(updated_at_raw)
                fresh = parsed >= (_utc_now() - timedelta(hours=max_age_hours))
            except ValueError:
                parsed = None
                fresh = False

        return CacheMeta(
            updated_at=parsed,
            entries_count=len(doc.get("entries") or []),
            fresh=fresh,
            max_age_hours=max_age_hours,
        )

    def lookup_by_title(self, career_name: str) -> Optional[Dict[str, Any]]:
        self.load()
        key = (career_name or "").strip().lower()
        if not key:
            return None
        return self._index_by_title.get(key)

    def lookup_all_by_title(self, career_name: str) -> List[Dict[str, Any]]:
        self.load()
        key = (career_name or "").strip().lower()
        if not key:
            return []
        matches = list(self._all_by_title.get(key, []))
        if matches:
            return matches

        # Deterministic partial-match fallback: no synthetic values, only cached records.
        partial: List[Dict[str, Any]] = []
        for title_key, records in self._all_by_title.items():
            if key in title_key or title_key in key:
                partial.extend(records)
        return partial

    def assess_signal(
        self,
        career_name: str,
        max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    ) -> Optional[MarketSignalAssessment]:
        """Build a deterministic market signal from cached records.

        Returns None when there is no matching cached signal.
        """
        cache_meta = self.meta(max_age_hours=max_age_hours)
        records = self.lookup_all_by_title(career_name)
        if not records:
            return None

        sources: List[str] = []
        salary_mins: List[float] = []
        salary_maxs: List[float] = []
        ai_values: List[float] = []

        with_company = 0
        with_location = 0
        with_skills = 0

        for record in records:
            source = str(record.get("_source") or "custom").strip().lower()
            if source:
                sources.append(source)

            salary_min = _safe_float(record.get("salary_min"))
            salary_max = _safe_float(record.get("salary_max"))
            if salary_min is not None:
                salary_mins.append(salary_min)
            if salary_max is not None:
                salary_maxs.append(salary_max)

            ai_relevance = _safe_float(record.get("ai_relevance"))
            if ai_relevance is not None:
                ai_values.append(_clamp(ai_relevance))

            if record.get("company"):
                with_company += 1
            if record.get("location"):
                with_location += 1
            skills = record.get("skills")
            if isinstance(skills, list) and len(skills) > 0:
                with_skills += 1

        signal_count = len(records)
        source_count = len(set(sources))

        # Demand from observed volume in cache (deterministic, data-derived).
        if signal_count >= 20:
            demand_level = "HIGH"
        elif signal_count >= 6:
            demand_level = "MEDIUM"
        else:
            demand_level = "LOW"

        # Growth proxy from volume (0..1), avoids hardcoded career-specific constants.
        growth_rate = round(_clamp(signal_count / 30.0), 4)

        # Competition proxy from volume.
        if signal_count >= 20:
            competition_level = "HIGH"
            competition_score = 0.8
        elif signal_count >= 6:
            competition_level = "MEDIUM"
            competition_score = 0.5
        else:
            competition_level = "LOW"
            competition_score = 0.25

        ai_relevance = round(
            sum(ai_values) / len(ai_values) if ai_values else _clamp(0.35 + 0.65 * growth_rate),
            4,
        )

        salary_min_value = min(salary_mins) if salary_mins else None
        salary_max_value = max(salary_maxs) if salary_maxs else None

        source_trust = 0.0
        if source_count > 0:
            source_trust = sum(
                SOURCE_TRUST_WEIGHTS.get(src, SOURCE_TRUST_WEIGHTS["custom"])
                for src in set(sources)
            ) / source_count

        completeness = 0.0
        denominator = max(signal_count, 1)
        completeness += (with_company / denominator) * 0.35
        completeness += (with_location / denominator) * 0.25
        completeness += (with_skills / denominator) * 0.25
        completeness += (1.0 if salary_min_value is not None or salary_max_value is not None else 0.0) * 0.15

        age_hours: Optional[float] = None
        if cache_meta.updated_at is not None:
            age_hours = max((_utc_now() - cache_meta.updated_at).total_seconds() / 3600.0, 0.0)

        freshness_factor = 1.0
        stale = not cache_meta.fresh
        if age_hours is not None and max_age_hours > 0:
            freshness_factor = _clamp(1.0 - (age_hours / max_age_hours))

        trust_score = _clamp(
            (0.55 * source_trust)
            + (0.30 * completeness)
            + (0.15 * freshness_factor)
            - (0.10 if stale else 0.0)
        )

        missing_required_fields: List[str] = []
        if salary_min_value is None and salary_max_value is None:
            missing_required_fields.append("salary_range")
        if signal_count <= 0:
            missing_required_fields.append("market_signal_count")
        if source_count <= 0:
            missing_required_fields.append("source")

        salary_range = {
            "min": salary_min_value,
            "max": salary_max_value,
            "currency": "VND",
            "period": "monthly",
        }

        return MarketSignalAssessment(
            career_name=career_name,
            demand_level=demand_level,
            salary_range=salary_range,
            growth_rate=growth_rate,
            competition_level=competition_level,
            ai_relevance=ai_relevance,
            source_trust_score=round(trust_score, 4),
            stale=stale,
            age_hours=round(age_hours, 2) if age_hours is not None else None,
            signal_count=signal_count,
            sources=sorted(set(sources)),
            missing_required_fields=missing_required_fields,
        )

    def get_market_signal(
        self,
        career_name: str,
        max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
        min_trust_score: float = DEFAULT_MIN_TRUST_SCORE,
    ) -> Optional[Dict[str, Any]]:
        assessment = self.assess_signal(career_name, max_age_hours=max_age_hours)
        if assessment is None:
            return None
        payload = assessment.to_dict()
        payload["trust_ok"] = payload["source_trust_score"] >= float(min_trust_score)
        return payload

    @staticmethod
    def _build_index(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        index: Dict[str, Dict[str, Any]] = {}
        for entry in entries:
            source = str(entry.get("source") or "custom")
            payload = entry.get("payload") or {}
            jobs = payload.get("jobs") or []
            if not isinstance(jobs, list):
                continue
            for job in jobs:
                title = str(job.get("title") or "").strip().lower()
                if title and title not in index:
                    indexed_job = dict(job)
                    indexed_job["_source"] = source
                    indexed_job["_entry_timestamp"] = entry.get("timestamp")
                    index[title] = indexed_job
        return index

    @staticmethod
    def _build_all_index(entries: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        index: Dict[str, List[Dict[str, Any]]] = {}
        for entry in entries:
            source = str(entry.get("source") or "custom")
            payload = entry.get("payload") or {}
            jobs = payload.get("jobs") or []
            if not isinstance(jobs, list):
                continue
            for job in jobs:
                title = str(job.get("title") or "").strip().lower()
                if not title:
                    continue
                indexed_job = dict(job)
                indexed_job["_source"] = source
                indexed_job["_entry_timestamp"] = entry.get("timestamp")
                index.setdefault(title, []).append(indexed_job)
        return index

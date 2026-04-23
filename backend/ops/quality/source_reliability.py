# backend/ops/quality/source_reliability.py
"""
Source Reliability Scoring.

Tracks and scores data sources (TopCV, VietnamWorks, etc.) based on:
- Success rate (crawl completion)
- Data quality (validation pass rate)
- Freshness (how up-to-date)
- Volume consistency
- Response time
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.quality.reliability")


class SourceMetrics:
    """Metrics for a single data source."""

    def __init__(self, source_name: str):
        self.source_name = source_name
        self.crawl_attempts = 0
        self.crawl_successes = 0
        self.crawl_failures = 0
        self.total_records = 0
        self.valid_records = 0
        self.invalid_records = 0
        self.avg_response_time_ms: float = 0.0
        self.last_crawl_at: Optional[str] = None
        self.last_success_at: Optional[str] = None
        self.volume_history: List[int] = []
        self._response_times: List[float] = []

    def record_crawl(
        self,
        success: bool,
        records: int = 0,
        valid: int = 0,
        invalid: int = 0,
        response_time_ms: float = 0.0,
    ) -> None:
        self.crawl_attempts += 1
        self.last_crawl_at = datetime.now().isoformat()

        if success:
            self.crawl_successes += 1
            self.last_success_at = datetime.now().isoformat()
        else:
            self.crawl_failures += 1

        self.total_records += records
        self.valid_records += valid
        self.invalid_records += invalid
        self.volume_history.append(records)
        if len(self.volume_history) > 100:
            self.volume_history = self.volume_history[-100:]

        if response_time_ms > 0:
            self._response_times.append(response_time_ms)
            if len(self._response_times) > 100:
                self._response_times = self._response_times[-100:]
            self.avg_response_time_ms = (
                sum(self._response_times) / len(self._response_times)
            )

    @property
    def success_rate(self) -> float:
        return self.crawl_successes / self.crawl_attempts if self.crawl_attempts > 0 else 0.0

    @property
    def quality_rate(self) -> float:
        total = self.valid_records + self.invalid_records
        return self.valid_records / total if total > 0 else 0.0

    @property
    def volume_consistency(self) -> float:
        """How consistent is the volume across crawls (0-1)."""
        if len(self.volume_history) < 2:
            return 1.0
        avg = sum(self.volume_history) / len(self.volume_history)
        if avg == 0:
            return 0.0
        variance = sum((v - avg) ** 2 for v in self.volume_history) / len(self.volume_history)
        cv = (variance ** 0.5) / avg  # Coefficient of variation
        return max(0.0, 1.0 - cv)  # Lower CV = more consistent

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source_name,
            "crawl_attempts": self.crawl_attempts,
            "success_rate": round(self.success_rate, 4),
            "quality_rate": round(self.quality_rate, 4),
            "volume_consistency": round(self.volume_consistency, 4),
            "avg_response_time_ms": round(self.avg_response_time_ms, 2),
            "total_records": self.total_records,
            "last_crawl_at": self.last_crawl_at,
            "last_success_at": self.last_success_at,
        }


class SourceReliabilityScorer:
    """
    Scores data source reliability on a 0-1 scale.

    Composite score =
      0.3 * success_rate +
      0.3 * quality_rate +
      0.2 * freshness_score +
      0.2 * volume_consistency
    """

    WEIGHTS = {
        "success_rate": 0.3,
        "quality_rate": 0.3,
        "freshness": 0.2,
        "volume_consistency": 0.2,
    }

    def __init__(
        self,
        freshness_threshold_hours: float = 24.0,
        storage_path: Optional[Path] = None,
    ):
        self.freshness_threshold_hours = freshness_threshold_hours
        self.storage_path = storage_path or Path("backend/data/source_reliability.json")
        self._sources: Dict[str, SourceMetrics] = {}

    def get_or_create_source(self, name: str) -> SourceMetrics:
        if name not in self._sources:
            self._sources[name] = SourceMetrics(name)
        return self._sources[name]

    def record_crawl(
        self,
        source_name: str,
        success: bool,
        records: int = 0,
        valid: int = 0,
        invalid: int = 0,
        response_time_ms: float = 0.0,
    ) -> None:
        metrics = self.get_or_create_source(source_name)
        metrics.record_crawl(
            success=success,
            records=records,
            valid=valid,
            invalid=invalid,
            response_time_ms=response_time_ms,
        )

    def score_source(self, source_name: str) -> Dict[str, Any]:
        """Calculate composite reliability score for a source."""
        metrics = self._sources.get(source_name)
        if not metrics:
            return {"source": source_name, "score": 0.0, "status": "unknown"}

        # Freshness score
        freshness = 0.0
        if metrics.last_success_at:
            try:
                last = datetime.fromisoformat(metrics.last_success_at)
                hours_ago = (datetime.now() - last).total_seconds() / 3600
                freshness = max(0.0, 1.0 - hours_ago / self.freshness_threshold_hours)
            except ValueError:
                freshness = 0.0

        composite = (
            self.WEIGHTS["success_rate"] * metrics.success_rate
            + self.WEIGHTS["quality_rate"] * metrics.quality_rate
            + self.WEIGHTS["freshness"] * freshness
            + self.WEIGHTS["volume_consistency"] * metrics.volume_consistency
        )

        status = "healthy" if composite >= 0.8 else ("degraded" if composite >= 0.5 else "unreliable")

        return {
            "source": source_name,
            "score": round(composite, 4),
            "status": status,
            "components": {
                "success_rate": round(metrics.success_rate, 4),
                "quality_rate": round(metrics.quality_rate, 4),
                "freshness": round(freshness, 4),
                "volume_consistency": round(metrics.volume_consistency, 4),
            },
            "details": metrics.to_dict(),
        }

    def score_all(self) -> Dict[str, Any]:
        """Score all tracked sources."""
        scores = {name: self.score_source(name) for name in self._sources}
        avg_score = (
            sum(s["score"] for s in scores.values()) / len(scores) if scores else 0
        )
        return {
            "sources": scores,
            "average_score": round(avg_score, 4),
            "source_count": len(scores),
        }

    def save(self) -> None:
        """Persist source reliability data."""
        data = {
            name: m.to_dict() for name, m in self._sources.items()
        }
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(data, indent=2))

    def load(self) -> None:
        """Load persisted source reliability data."""
        if not self.storage_path.exists():
            return
        try:
            data = json.loads(self.storage_path.read_text())
            for name, info in data.items():
                m = self.get_or_create_source(name)
                m.crawl_attempts = info.get("crawl_attempts", 0)
                m.crawl_successes = int(info.get("success_rate", 0) * m.crawl_attempts)
                m.crawl_failures = m.crawl_attempts - m.crawl_successes
                m.total_records = info.get("total_records", 0)
                m.last_crawl_at = info.get("last_crawl_at")
                m.last_success_at = info.get("last_success_at")
        except Exception as e:
            logger.error(f"Failed to load reliability data: {e}")

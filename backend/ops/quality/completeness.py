# backend/ops/quality/completeness.py
"""
Data Completeness Checker.

Checks:
- Required field presence
- Optional field fill rates
- Per-source completeness trends
- Minimum viable record thresholds
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.quality.completeness")


class CompletenessReport:
    """Report on data completeness."""

    def __init__(self, batch_name: str = ""):
        self.batch_name = batch_name
        self.total_records = 0
        self.field_stats: Dict[str, Dict[str, int]] = {}
        self.overall_completeness = 0.0
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_name": self.batch_name,
            "total_records": self.total_records,
            "overall_completeness": round(self.overall_completeness, 4),
            "field_stats": self.field_stats,
            "timestamp": self.timestamp,
        }


class CompletenessChecker:
    """
    Checks data completeness for pipeline records.

    Computes fill rates for each field and identifies
    records falling below minimum completeness thresholds.
    """

    # Critical fields that MUST be present
    CRITICAL_FIELDS = ["job_id", "job_title", "company", "url"]

    # Important fields that SHOULD be present
    IMPORTANT_FIELDS = [
        "salary", "location", "skills", "experience",
        "job_type", "posted_date", "description",
    ]

    def __init__(
        self,
        min_completeness: float = 0.7,
        min_critical_completeness: float = 1.0,
    ):
        self.min_completeness = min_completeness
        self.min_critical_completeness = min_critical_completeness
        self._history: List[CompletenessReport] = []

    def check_batch(
        self,
        records: List[Dict[str, Any]],
        batch_name: str = "",
    ) -> CompletenessReport:
        """
        Check completeness for a batch of records.

        Returns:
            CompletenessReport with per-field fill rates
        """
        report = CompletenessReport(batch_name=batch_name)
        report.total_records = len(records)

        if not records:
            return report

        # Count non-null values per field
        all_fields = set()
        for r in records:
            all_fields.update(r.keys())

        field_counts: Dict[str, int] = defaultdict(int)
        for r in records:
            for f in all_fields:
                val = r.get(f)
                if val is not None and val != "" and val != []:
                    field_counts[f] += 1

        # Compute fill rates
        total = len(records)
        total_fills = 0
        total_possible = 0

        for f in sorted(all_fields):
            filled = field_counts.get(f, 0)
            fill_rate = filled / total

            is_critical = f in self.CRITICAL_FIELDS or f in [
                "title",  # alias for job_title
            ]
            is_important = f in self.IMPORTANT_FIELDS

            category = "critical" if is_critical else ("important" if is_important else "optional")

            report.field_stats[f] = {
                "filled": filled,
                "total": total,
                "fill_rate": round(fill_rate, 4),
                "category": category,
            }

            if is_critical or is_important:
                total_fills += filled
                total_possible += total

        report.overall_completeness = total_fills / total_possible if total_possible > 0 else 0.0

        self._history.append(report)
        if len(self._history) > 100:
            self._history = self._history[-100:]

        return report

    def get_incomplete_records(
        self,
        records: List[Dict[str, Any]],
        threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Get records below the completeness threshold."""
        thresh = threshold or self.min_completeness
        incomplete = []

        all_fields = self.CRITICAL_FIELDS + self.IMPORTANT_FIELDS
        for r in records:
            filled = sum(
                1 for f in all_fields
                if r.get(f) is not None and r.get(f) != "" and r.get(f) != []
            )
            completeness = filled / len(all_fields) if all_fields else 0
            if completeness < thresh:
                incomplete.append({
                    "record": r,
                    "completeness": round(completeness, 4),
                    "missing": [
                        f for f in all_fields
                        if r.get(f) is None or r.get(f) == "" or r.get(f) == []
                    ],
                })

        return incomplete

    def check_critical_fields(
        self,
        records: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Check that all critical fields are present in all records."""
        failures = []
        for i, r in enumerate(records):
            missing = [
                f for f in self.CRITICAL_FIELDS
                if r.get(f) is None or r.get(f) == ""
            ]
            # Also check aliases
            if "title" in missing and r.get("job_title"):
                missing.remove("title")

            if missing:
                failures.append({
                    "index": i,
                    "id": r.get("job_id", f"idx_{i}"),
                    "missing": missing,
                })

        return {
            "total_checked": len(records),
            "failures": len(failures),
            "pass_rate": round(1 - len(failures) / len(records), 4) if records else 0,
            "details": failures[:50],
        }

    def get_trend(self) -> List[Dict[str, Any]]:
        """Get completeness trend over recent batches."""
        return [
            {
                "batch": h.batch_name,
                "completeness": round(h.overall_completeness, 4),
                "records": h.total_records,
                "timestamp": h.timestamp,
            }
            for h in self._history[-20:]
        ]

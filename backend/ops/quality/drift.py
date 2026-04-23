# backend/ops/quality/drift.py
"""
Data Drift Monitor.

Detects distribution shifts between pipeline runs:
- Feature drift (salary, skills, locations)
- Volume drift (record count changes)
- Schema drift (new/removed fields)
- Concept drift (score distribution changes)
"""

from __future__ import annotations

import json
import logging
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.quality.drift")


class DriftReport:
    """Report of detected data drift."""

    def __init__(self, reference_batch: str, current_batch: str):
        self.reference_batch = reference_batch
        self.current_batch = current_batch
        self.timestamp = datetime.now().isoformat()
        self.feature_drifts: Dict[str, Dict[str, Any]] = {}
        self.volume_drift: Dict[str, Any] = {}
        self.schema_drift: Dict[str, Any] = {}
        self.overall_drift_score: float = 0.0
        self.alert: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reference": self.reference_batch,
            "current": self.current_batch,
            "timestamp": self.timestamp,
            "overall_drift_score": round(self.overall_drift_score, 4),
            "alert": self.alert,
            "feature_drifts": self.feature_drifts,
            "volume_drift": self.volume_drift,
            "schema_drift": self.schema_drift,
        }


class DriftMonitor:
    """
    Monitors data drift between pipeline runs.

    Uses statistical tests:
    - Population Stability Index (PSI) for numeric drift
    - Chi-squared approximation for categorical drift
    - Volume change detection
    - Schema comparison
    """

    def __init__(
        self,
        drift_threshold: float = 0.2,  # PSI > 0.2 = significant drift
        volume_change_threshold: float = 0.3,  # 30% volume change
        storage_dir: Optional[Path] = None,
    ):
        self.drift_threshold = drift_threshold
        self.volume_change_threshold = volume_change_threshold
        self.storage_dir = storage_dir or Path("backend/data/drift")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._baselines: Dict[str, Dict[str, Any]] = {}

    def set_baseline(
        self,
        batch_name: str,
        records: List[Dict[str, Any]],
    ) -> None:
        """Set a baseline batch for drift comparison."""
        profile = self._profile_batch(records)
        self._baselines[batch_name] = profile

        # Persist baseline
        baseline_path = self.storage_dir / f"baseline_{batch_name}.json"
        baseline_path.write_text(json.dumps(profile, indent=2, default=str))
        logger.info(f"Baseline set: {batch_name} ({len(records)} records)")

    def detect_drift(
        self,
        current_records: List[Dict[str, Any]],
        reference_name: Optional[str] = None,
        current_name: str = "current",
    ) -> DriftReport:
        """
        Detect drift between current data and a reference baseline.

        Args:
            current_records: Current batch of records
            reference_name: Name of baseline batch (uses last set if None)
            current_name: Label for current batch
        """
        ref_name = reference_name or (list(self._baselines.keys())[-1] if self._baselines else "none")
        report = DriftReport(reference_batch=ref_name, current_batch=current_name)

        ref_profile = self._baselines.get(ref_name)
        if not ref_profile:
            # Try loading from disk
            baseline_path = self.storage_dir / f"baseline_{ref_name}.json"
            if baseline_path.exists():
                ref_profile = json.loads(baseline_path.read_text())
                self._baselines[ref_name] = ref_profile

        if not ref_profile:
            report.schema_drift = {"error": f"No baseline '{ref_name}' found"}
            return report

        cur_profile = self._profile_batch(current_records)

        # ── Volume Drift ──
        ref_count = ref_profile.get("count", 0)
        cur_count = cur_profile.get("count", 0)
        if ref_count > 0:
            volume_change = abs(cur_count - ref_count) / ref_count
            report.volume_drift = {
                "reference_count": ref_count,
                "current_count": cur_count,
                "change_ratio": round(volume_change, 4),
                "alert": volume_change > self.volume_change_threshold,
            }

        # ── Schema Drift ──
        ref_fields = set(ref_profile.get("fields", []))
        cur_fields = set(cur_profile.get("fields", []))
        added = cur_fields - ref_fields
        removed = ref_fields - cur_fields
        report.schema_drift = {
            "added_fields": list(added),
            "removed_fields": list(removed),
            "fields_changed": len(added) + len(removed) > 0,
        }

        # ── Feature Drift (numeric fields) ──
        drift_scores = []
        for field_name, ref_stats in ref_profile.get("numeric_fields", {}).items():
            cur_stats = cur_profile.get("numeric_fields", {}).get(field_name)
            if not cur_stats:
                continue

            psi = self._compute_psi(
                ref_stats.get("histogram", []),
                cur_stats.get("histogram", []),
            )
            drift_scores.append(psi)
            report.feature_drifts[field_name] = {
                "type": "numeric",
                "psi": round(psi, 4),
                "drifted": psi > self.drift_threshold,
                "ref_mean": ref_stats.get("mean"),
                "cur_mean": cur_stats.get("mean"),
            }

        # ── Feature Drift (categorical fields) ──
        for field_name, ref_dist in ref_profile.get("categorical_fields", {}).items():
            cur_dist = cur_profile.get("categorical_fields", {}).get(field_name)
            if not cur_dist:
                continue

            psi = self._compute_categorical_psi(ref_dist, cur_dist)
            drift_scores.append(psi)
            report.feature_drifts[field_name] = {
                "type": "categorical",
                "psi": round(psi, 4),
                "drifted": psi > self.drift_threshold,
            }

        # ── Overall Drift Score ──
        report.overall_drift_score = (
            sum(drift_scores) / len(drift_scores) if drift_scores else 0.0
        )
        report.alert = report.overall_drift_score > self.drift_threshold

        # Persist report
        report_path = self.storage_dir / f"drift_{current_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_path.write_text(json.dumps(report.to_dict(), indent=2))

        if report.alert:
            logger.warning(f"DRIFT ALERT: score={report.overall_drift_score:.4f}")
        else:
            logger.info(f"Drift check passed: score={report.overall_drift_score:.4f}")

        return report

    # ── Private Helpers ─────────────────────────────────────

    def _profile_batch(self, records: List[Dict]) -> Dict[str, Any]:
        """Create a statistical profile of a batch."""
        if not records:
            return {"count": 0, "fields": [], "numeric_fields": {}, "categorical_fields": {}}

        fields = set()
        for r in records:
            fields.update(r.keys())

        numeric_fields: Dict[str, Dict] = {}
        categorical_fields: Dict[str, Dict] = {}

        numeric_candidates = [
            "salary_min", "salary_max", "salary", "experience",
            "total_score", "study", "interest", "market", "growth", "risk",
        ]
        categorical_candidates = [
            "location", "province_code", "job_type", "source",
            "company", "domain",
        ]

        for f in fields:
            values = [r.get(f) for r in records if r.get(f) is not None]
            if not values:
                continue

            if f in numeric_candidates or all(isinstance(v, (int, float)) for v in values[:20]):
                numeric_vals = []
                for v in values:
                    try:
                        numeric_vals.append(float(v))
                    except (ValueError, TypeError):
                        continue

                if len(numeric_vals) >= 5:
                    sorted_v = sorted(numeric_vals)
                    numeric_fields[f] = {
                        "mean": round(sum(numeric_vals) / len(numeric_vals), 4),
                        "median": round(sorted_v[len(sorted_v)//2], 4),
                        "min": round(min(numeric_vals), 4),
                        "max": round(max(numeric_vals), 4),
                        "count": len(numeric_vals),
                        "histogram": self._make_histogram(numeric_vals, bins=10),
                    }

            elif f in categorical_candidates:
                counts = Counter(str(v) for v in values)
                total = len(values)
                categorical_fields[f] = {
                    k: round(v / total, 4) for k, v in counts.most_common(50)
                }

        return {
            "count": len(records),
            "fields": sorted(fields),
            "numeric_fields": numeric_fields,
            "categorical_fields": categorical_fields,
        }

    def _make_histogram(self, values: List[float], bins: int = 10) -> List[float]:
        """Create a normalized histogram."""
        if not values:
            return []
        mn, mx = min(values), max(values)
        if mn == mx:
            return [1.0] + [0.0] * (bins - 1)

        bin_width = (mx - mn) / bins
        hist = [0] * bins
        for v in values:
            idx = min(int((v - mn) / bin_width), bins - 1)
            hist[idx] += 1

        total = sum(hist)
        return [h / total for h in hist] if total > 0 else hist

    def _compute_psi(
        self, ref_hist: List[float], cur_hist: List[float]
    ) -> float:
        """Compute Population Stability Index."""
        if not ref_hist or not cur_hist or len(ref_hist) != len(cur_hist):
            return 0.0

        eps = 1e-6
        psi = 0.0
        for p, q in zip(ref_hist, cur_hist):
            p = max(p, eps)
            q = max(q, eps)
            psi += (p - q) * math.log(p / q)
        return psi

    def _compute_categorical_psi(
        self, ref_dist: Dict[str, float], cur_dist: Dict[str, float]
    ) -> float:
        """Compute PSI for categorical distributions."""
        all_keys = set(ref_dist) | set(cur_dist)
        eps = 1e-6
        psi = 0.0
        for k in all_keys:
            p = max(ref_dist.get(k, 0), eps)
            q = max(cur_dist.get(k, 0), eps)
            psi += (p - q) * math.log(p / q)
        return psi

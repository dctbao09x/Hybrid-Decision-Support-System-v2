# backend/ops/quality/outlier.py
"""
Outlier Detection for pipeline data.

Detects:
- Salary outliers (IQR-based)
- Score distribution anomalies
- Unusual field values
- Cross-field inconsistencies
"""

from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ops.quality.outlier")


class OutlierDetector:
    """
    Detects outliers in crawled and scored job data.

    Methods:
    - IQR (Interquartile Range) for numeric fields
    - Z-score for normally distributed data
    - Frequency-based for categorical fields
    - Cross-field consistency checks
    """

    def __init__(
        self,
        iqr_multiplier: float = 1.5,
        z_threshold: float = 3.0,
        rare_category_threshold: float = 0.01,
    ):
        self.iqr_multiplier = iqr_multiplier
        self.z_threshold = z_threshold
        self.rare_category_threshold = rare_category_threshold

    def detect_numeric_outliers(
        self,
        records: List[Dict[str, Any]],
        field: str,
        method: str = "iqr",
    ) -> Dict[str, Any]:
        """
        Detect outliers in a numeric field.

        Args:
            records: Data records
            field: Field name to analyze
            method: "iqr" or "zscore"
        """
        values = []
        for r in records:
            val = r.get(field)
            if val is not None:
                try:
                    values.append(float(val))
                except (ValueError, TypeError):
                    continue

        if len(values) < 5:
            return {"field": field, "status": "insufficient_data", "outliers": []}

        if method == "iqr":
            outlier_indices, bounds = self._iqr_method(values)
        else:
            outlier_indices, bounds = self._zscore_method(values)

        outlier_records = []
        value_idx = 0
        for i, r in enumerate(records):
            val = r.get(field)
            if val is not None:
                try:
                    float(val)
                    if value_idx in outlier_indices:
                        outlier_records.append({
                            "index": i,
                            "id": r.get("job_id", f"idx_{i}"),
                            "value": val,
                            "field": field,
                        })
                    value_idx += 1
                except (ValueError, TypeError):
                    continue

        return {
            "field": field,
            "method": method,
            "total_values": len(values),
            "outlier_count": len(outlier_records),
            "outlier_rate": round(len(outlier_records) / len(values), 4) if values else 0,
            "bounds": bounds,
            "statistics": {
                "mean": round(sum(values) / len(values), 2),
                "median": round(sorted(values)[len(values) // 2], 2),
                "min": round(min(values), 2),
                "max": round(max(values), 2),
            },
            "outliers": outlier_records[:20],
        }

    def detect_categorical_outliers(
        self,
        records: List[Dict[str, Any]],
        field: str,
    ) -> Dict[str, Any]:
        """Detect rare categories in a categorical field."""
        values = [r.get(field) for r in records if r.get(field) is not None]
        if not values:
            return {"field": field, "status": "no_data"}

        counts = Counter(values)
        total = len(values)
        rare = {
            k: {"count": v, "rate": round(v / total, 4)}
            for k, v in counts.items()
            if v / total < self.rare_category_threshold
        }

        return {
            "field": field,
            "unique_values": len(counts),
            "total_values": total,
            "rare_categories": rare,
            "rare_count": len(rare),
            "top_5": dict(counts.most_common(5)),
        }

    def detect_score_anomalies(
        self,
        scores: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Detect anomalies in scoring output."""
        anomalies = []

        for i, s in enumerate(scores):
            total = s.get("total_score", 0)
            breakdown = s.get("breakdown", {})

            # Check score bounds
            if not 0 <= total <= 1:
                anomalies.append({
                    "index": i,
                    "type": "out_of_bounds",
                    "detail": f"total_score={total} not in [0,1]",
                })

            # Check component scores
            for comp, val in breakdown.items():
                if isinstance(val, (int, float)) and not 0 <= val <= 1:
                    anomalies.append({
                        "index": i,
                        "type": "component_out_of_bounds",
                        "detail": f"{comp}={val} not in [0,1]",
                    })

            # Check if all components are identical (suspicious)
            comp_values = [v for v in breakdown.values() if isinstance(v, (int, float))]
            if comp_values and len(set(round(v, 4) for v in comp_values)) == 1:
                anomalies.append({
                    "index": i,
                    "type": "uniform_components",
                    "detail": f"All components = {comp_values[0]}",
                })

        return {
            "total_scored": len(scores),
            "anomaly_count": len(anomalies),
            "anomaly_rate": round(len(anomalies) / len(scores), 4) if scores else 0,
            "anomalies": anomalies[:30],
        }

    def _iqr_method(self, values: List[float]) -> Tuple[set, Dict]:
        sorted_v = sorted(values)
        n = len(sorted_v)
        q1 = sorted_v[n // 4]
        q3 = sorted_v[3 * n // 4]
        iqr = q3 - q1
        lower = q1 - self.iqr_multiplier * iqr
        upper = q3 + self.iqr_multiplier * iqr

        outliers = {i for i, v in enumerate(values) if v < lower or v > upper}
        return outliers, {"q1": q1, "q3": q3, "iqr": iqr, "lower": lower, "upper": upper}

    def _zscore_method(self, values: List[float]) -> Tuple[set, Dict]:
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std = math.sqrt(variance) if variance > 0 else 1.0

        outliers = {
            i for i, v in enumerate(values)
            if abs((v - mean) / std) > self.z_threshold
        }
        return outliers, {"mean": mean, "std": std, "threshold": self.z_threshold}

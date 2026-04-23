# backend/ops/monitoring/anomaly.py
"""
Anomaly Detection for pipeline metrics.

Detects:
- Statistical anomalies in pipeline metrics
- Sudden volume changes
- Unusual execution patterns
- Score distribution shifts
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ops.monitoring.anomaly")


class AnomalyDetector:
    """
    Detects anomalies in pipeline time-series metrics.

    Uses simple statistical methods:
    - Moving average deviation
    - Z-score based detection
    - Percentage change detection
    """

    def __init__(
        self,
        z_threshold: float = 3.0,
        pct_change_threshold: float = 0.5,  # 50% change
        min_samples: int = 10,
    ):
        self.z_threshold = z_threshold
        self.pct_change_threshold = pct_change_threshold
        self.min_samples = min_samples
        self._series: Dict[str, List[Tuple[str, float]]] = defaultdict(list)

    def record(self, metric_name: str, value: float) -> Optional[Dict[str, Any]]:
        """
        Record a metric value and check for anomaly.

        Returns anomaly details if detected, None otherwise.
        """
        timestamp = datetime.now().isoformat()
        self._series[metric_name].append((timestamp, value))

        # Keep last 500 points
        if len(self._series[metric_name]) > 500:
            self._series[metric_name] = self._series[metric_name][-500:]

        return self._check_anomaly(metric_name, value)

    def _check_anomaly(
        self, metric_name: str, current_value: float
    ) -> Optional[Dict[str, Any]]:
        """Check if current value is anomalous."""
        values = [v for _, v in self._series[metric_name]]

        if len(values) < self.min_samples:
            return None

        # Use all but the last value for baseline
        baseline = values[:-1]
        mean = sum(baseline) / len(baseline)
        variance = sum((v - mean) ** 2 for v in baseline) / len(baseline)
        std = math.sqrt(variance) if variance > 0 else 0.001

        z_score = (current_value - mean) / std if std > 0 else 0.0

        # Percentage change from recent average
        recent_avg = sum(baseline[-5:]) / min(5, len(baseline))
        pct_change = abs(current_value - recent_avg) / recent_avg if recent_avg != 0 else 0.0

        is_anomaly = abs(z_score) > self.z_threshold or pct_change > self.pct_change_threshold

        if is_anomaly:
            anomaly = {
                "metric": metric_name,
                "value": current_value,
                "mean": round(mean, 4),
                "std": round(std, 4),
                "z_score": round(z_score, 4),
                "pct_change": round(pct_change, 4),
                "type": "z_score" if abs(z_score) > self.z_threshold else "pct_change",
                "direction": "high" if current_value > mean else "low",
                "timestamp": datetime.now().isoformat(),
            }
            logger.warning(f"ANOMALY: {metric_name}={current_value} (z={z_score:.2f}, Δ%={pct_change:.2%})")
            return anomaly

        return None

    def get_stats(self, metric_name: str) -> Dict[str, Any]:
        """Get statistics for a metric."""
        if metric_name not in self._series:
            return {"error": f"No data for '{metric_name}'"}

        values = [v for _, v in self._series[metric_name]]
        if not values:
            return {"error": "No values"}

        return {
            "metric": metric_name,
            "sample_count": len(values),
            "mean": round(sum(values) / len(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "latest": values[-1],
            "std": round(
                math.sqrt(
                    sum((v - sum(values) / len(values)) ** 2 for v in values) / len(values)
                ),
                4,
            ) if len(values) > 1 else 0,
        }

    def get_all_stats(self) -> Dict[str, Any]:
        """Get statistics for all tracked metrics."""
        return {name: self.get_stats(name) for name in self._series}

    def detect_batch_anomalies(
        self,
        metrics: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        """Record and check multiple metrics at once."""
        anomalies = []
        for name, value in metrics.items():
            result = self.record(name, value)
            if result:
                anomalies.append(result)
        return anomalies

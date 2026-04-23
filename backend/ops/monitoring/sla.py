# backend/ops/monitoring/sla.py
"""
SLA (Service Level Agreement) Monitoring.

Tracks and enforces:
- Pipeline execution time SLAs
- Data freshness SLAs
- Availability SLAs
- Quality SLAs
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.monitoring.sla")


class SLADefinition:
    """Definition of a single SLA metric."""

    def __init__(
        self,
        name: str,
        metric: str,
        threshold: float,
        window_hours: float = 24.0,
        severity: str = "warning",
    ):
        self.name = name
        self.metric = metric      # e.g., "pipeline_duration_seconds"
        self.threshold = threshold  # Max acceptable value
        self.window_hours = window_hours
        self.severity = severity   # "info", "warning", "critical"


class SLAViolation:
    """Record of an SLA being violated."""

    def __init__(
        self,
        sla: SLADefinition,
        actual_value: float,
        timestamp: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        self.sla_name = sla.name
        self.metric = sla.metric
        self.threshold = sla.threshold
        self.actual_value = actual_value
        self.severity = sla.severity
        self.timestamp = timestamp or datetime.now().isoformat()
        self.context = context or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sla_name": self.sla_name,
            "metric": self.metric,
            "threshold": self.threshold,
            "actual_value": self.actual_value,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "context": self.context,
        }


class SLAMonitor:
    """
    Monitors SLA compliance for the pipeline.

    Default SLAs:
    - Pipeline must complete within 2 hours
    - Data must be refreshed within 24 hours
    - Validation pass rate ≥ 95%
    - Scoring availability ≥ 99%
    - Crawl success rate ≥ 90%
    """

    DEFAULT_SLAS = [
        SLADefinition("pipeline_duration", "pipeline_duration_seconds", 7200, severity="warning"),
        SLADefinition("data_freshness", "data_age_hours", 24.0, severity="critical"),
        SLADefinition("validation_rate", "validation_pass_rate", 0.95, severity="warning"),
        SLADefinition("crawl_success", "crawl_success_rate", 0.90, severity="warning"),
        SLADefinition("stage_timeout", "stage_duration_seconds", 3600, severity="warning"),
    ]

    def __init__(self, custom_slas: Optional[List[SLADefinition]] = None):
        self._slas: Dict[str, SLADefinition] = {}
        self._violations: List[SLAViolation] = []
        self._metrics: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for sla in custom_slas or self.DEFAULT_SLAS:
            self.add_sla(sla)

    def add_sla(self, sla: SLADefinition) -> None:
        self._slas[sla.name] = sla

    def record_metric(
        self, metric: str, value: float, context: Optional[Dict[str, Any]] = None
    ) -> Optional[SLAViolation]:
        """
        Record a metric value and check for SLA violations.

        Returns violation if SLA breached, None otherwise.
        """
        entry = {
            "value": value,
            "timestamp": datetime.now().isoformat(),
            "context": context or {},
        }
        self._metrics[metric].append(entry)

        # Keep last 1000 entries per metric
        if len(self._metrics[metric]) > 1000:
            self._metrics[metric] = self._metrics[metric][-1000:]

        # Check SLAs
        for sla in self._slas.values():
            if sla.metric != metric:
                continue

            # For rates (0-1), violation means below threshold
            # For durations/ages, violation means above threshold
            is_rate = "rate" in metric
            violated = (value < sla.threshold) if is_rate else (value > sla.threshold)

            if violated:
                violation = SLAViolation(sla, value, context=context)
                self._violations.append(violation)
                logger.warning(
                    f"SLA VIOLATION: {sla.name} - "
                    f"actual={value:.4f}, threshold={sla.threshold:.4f}"
                )
                return violation

        return None

    def check_sla(self, sla_name: str) -> Dict[str, Any]:
        """Check current status of a specific SLA."""
        sla = self._slas.get(sla_name)
        if not sla:
            return {"error": f"SLA '{sla_name}' not found"}

        metric_data = self._metrics.get(sla.metric, [])
        recent = [
            m for m in metric_data
            if self._is_within_window(m["timestamp"], sla.window_hours)
        ]

        if not recent:
            return {
                "sla_name": sla_name,
                "status": "no_data",
                "threshold": sla.threshold,
            }

        values = [m["value"] for m in recent]
        avg = sum(values) / len(values)
        is_rate = "rate" in sla.metric
        compliant = (avg >= sla.threshold) if is_rate else (avg <= sla.threshold)

        violations_in_window = [
            v for v in self._violations
            if v.sla_name == sla_name and self._is_within_window(v.timestamp, sla.window_hours)
        ]

        return {
            "sla_name": sla_name,
            "status": "compliant" if compliant else "violated",
            "threshold": sla.threshold,
            "current_avg": round(avg, 4),
            "sample_count": len(recent),
            "violations_in_window": len(violations_in_window),
            "window_hours": sla.window_hours,
        }

    def get_dashboard(self) -> Dict[str, Any]:
        """Get SLA compliance dashboard."""
        dashboard = {}
        for name in self._slas:
            dashboard[name] = self.check_sla(name)

        total = len(dashboard)
        compliant = sum(1 for d in dashboard.values() if d.get("status") == "compliant")

        return {
            "overall_compliance": round(compliant / total, 4) if total else 0,
            "slas": dashboard,
            "total_violations": len(self._violations),
            "timestamp": datetime.now().isoformat(),
        }

    def get_violations(
        self, hours: float = 24.0, severity: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get recent violations."""
        recent = [
            v for v in self._violations
            if self._is_within_window(v.timestamp, hours)
            and (severity is None or v.severity == severity)
        ]
        return [v.to_dict() for v in recent]

    def _is_within_window(self, timestamp: str, hours: float) -> bool:
        try:
            ts = datetime.fromisoformat(timestamp)
            return (datetime.now() - ts).total_seconds() < hours * 3600
        except (ValueError, TypeError):
            return False

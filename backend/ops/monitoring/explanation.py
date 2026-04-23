# backend/ops/monitoring/explanation.py
"""
Explanation Monitoring.

Tracks quality and consistency of scoring explanations:
- Explanation completeness (all 5 SIMGR components present)
- Explanation latency
- Drift in explanation patterns
- User-facing explanation quality metrics
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.monitoring.explanation")


class ExplanationMetrics:
    """Metrics for a single explanation generation."""

    def __init__(
        self,
        career_name: str,
        has_all_components: bool,
        component_count: int,
        total_score: float,
        latency_ms: float = 0.0,
        readable_length: int = 0,
        trace_dict: Optional[Dict[str, Any]] = None,
    ):
        self.career_name = career_name
        self.has_all_components = has_all_components
        self.component_count = component_count
        self.total_score = total_score
        self.latency_ms = latency_ms
        self.readable_length = readable_length
        self.trace_dict = trace_dict or {}
        self.timestamp = datetime.now().isoformat()


class ExplanationMonitor:
    """
    Monitors quality of scoring explanations.

    Tracks:
    - Completeness: all 5 SIMGR components traced
    - Consistency: same input → same explanation structure
    - Latency: time to generate each explanation
    - Coverage: % of scored careers with explanations
    """

    REQUIRED_COMPONENTS = {"study", "interest", "market", "growth", "risk"}

    def __init__(self, max_history: int = 2000):
        self._history: List[ExplanationMetrics] = []
        self._max_history = max_history

        # Aggregates
        self._total_generated = 0
        self._total_complete = 0
        self._total_scored = 0  # careers that were scored
        self._component_freq: Dict[str, int] = defaultdict(int)
        self._latencies: List[float] = []

    def record_scored_career(self, career_name: str) -> None:
        """Record that a career was scored (for coverage tracking)."""
        self._total_scored += 1

    def record_explanation(
        self,
        career_name: str,
        trace_dict: Dict[str, Any],
        latency_ms: float = 0.0,
    ) -> ExplanationMetrics:
        """
        Record a generated explanation and compute quality metrics.

        Args:
            career_name: Name of career being explained
            trace_dict: Output from ScoringTrace.to_dict()
            latency_ms: Time taken to generate explanation
        """
        # Extract components from trace
        components = trace_dict.get("components", [])
        component_names = {c.get("component_name", "") for c in components}
        has_all = self.REQUIRED_COMPONENTS.issubset(component_names)

        readable = trace_dict.get("readable", "")
        if not readable:
            # Try to build from to_readable if available
            readable = trace_dict.get("explanation_text", "")

        metrics = ExplanationMetrics(
            career_name=career_name,
            has_all_components=has_all,
            component_count=len(components),
            total_score=trace_dict.get("total_score", 0.0),
            latency_ms=latency_ms,
            readable_length=len(readable),
            trace_dict=trace_dict,
        )

        self._total_generated += 1
        if has_all:
            self._total_complete += 1

        for name in component_names:
            self._component_freq[name] += 1

        self._latencies.append(latency_ms)
        if len(self._latencies) > self._max_history:
            self._latencies = self._latencies[-self._max_history:]

        self._history.append(metrics)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        if not has_all:
            missing = self.REQUIRED_COMPONENTS - component_names
            logger.warning(
                f"Incomplete explanation for '{career_name}': "
                f"missing components {missing}"
            )

        return metrics

    def get_dashboard(self) -> Dict[str, Any]:
        """Get explanation monitoring dashboard."""
        completeness_rate = (
            self._total_complete / self._total_generated
            if self._total_generated > 0 else 0.0
        )
        coverage_rate = (
            self._total_generated / self._total_scored
            if self._total_scored > 0 else 0.0
        )

        latency_stats = {}
        if self._latencies:
            latency_stats = {
                "mean_ms": round(statistics.mean(self._latencies), 2),
                "median_ms": round(statistics.median(self._latencies), 2),
                "p95_ms": round(
                    sorted(self._latencies)[int(len(self._latencies) * 0.95)], 2
                ) if len(self._latencies) >= 20 else None,
                "max_ms": round(max(self._latencies), 2),
            }

        return {
            "total_scored": self._total_scored,
            "total_explanations": self._total_generated,
            "completeness_rate": round(completeness_rate, 4),
            "coverage_rate": round(min(coverage_rate, 1.0), 4),
            "component_frequency": dict(self._component_freq),
            "latency": latency_stats,
            "timestamp": datetime.now().isoformat(),
        }

    def check_quality(self) -> Dict[str, Any]:
        """
        Run quality checks and return issues.

        Checks:
        - Completeness rate ≥ 95%
        - Coverage rate ≥ 90%
        - Mean latency ≤ 500ms
        - All 5 components appear in recent explanations
        """
        dashboard = self.get_dashboard()
        issues = []

        if dashboard["completeness_rate"] < 0.95:
            issues.append({
                "check": "completeness",
                "severity": "warning",
                "value": dashboard["completeness_rate"],
                "threshold": 0.95,
                "message": "Explanation completeness below 95%",
            })

        if dashboard["coverage_rate"] < 0.90:
            issues.append({
                "check": "coverage",
                "severity": "warning",
                "value": dashboard["coverage_rate"],
                "threshold": 0.90,
                "message": "Explanation coverage below 90%",
            })

        latency_mean = dashboard.get("latency", {}).get("mean_ms", 0)
        if latency_mean > 500:
            issues.append({
                "check": "latency",
                "severity": "warning",
                "value": latency_mean,
                "threshold": 500,
                "message": "Mean explanation latency exceeds 500ms",
            })

        # Check component coverage in recent explanations
        recent = self._history[-100:] if self._history else []
        if recent:
            recent_components = set()
            for m in recent:
                for c in m.trace_dict.get("components", []):
                    recent_components.add(c.get("component_name", ""))
            missing = self.REQUIRED_COMPONENTS - recent_components
            if missing:
                issues.append({
                    "check": "component_coverage",
                    "severity": "critical",
                    "missing": list(missing),
                    "message": f"Components {missing} never appear in recent explanations",
                })

        return {
            "healthy": len(issues) == 0,
            "issues": issues,
            "dashboard": dashboard,
        }

    def detect_drift(self, window: int = 50) -> Dict[str, Any]:
        """
        Detect drift in explanation patterns.

        Compares recent window vs older data to find:
        - Score distribution shift
        - Component count changes
        - Latency degradation
        """
        if len(self._history) < window * 2:
            return {"status": "insufficient_data", "needed": window * 2}

        older = self._history[-(window * 2):-window]
        recent = self._history[-window:]

        def avg(items: List[ExplanationMetrics], attr: str) -> float:
            vals = [getattr(m, attr) for m in items]
            return statistics.mean(vals) if vals else 0.0

        drift_signals = {}

        # Score drift
        old_score = avg(older, "total_score")
        new_score = avg(recent, "total_score")
        if old_score > 0:
            score_change = abs(new_score - old_score) / old_score
            drift_signals["score_drift"] = {
                "old_mean": round(old_score, 4),
                "new_mean": round(new_score, 4),
                "change_pct": round(score_change * 100, 2),
                "drifted": score_change > 0.15,
            }

        # Completeness drift
        old_complete = sum(1 for m in older if m.has_all_components) / len(older)
        new_complete = sum(1 for m in recent if m.has_all_components) / len(recent)
        drift_signals["completeness_drift"] = {
            "old_rate": round(old_complete, 4),
            "new_rate": round(new_complete, 4),
            "drifted": new_complete < old_complete - 0.05,
        }

        # Latency drift
        old_lat = avg(older, "latency_ms")
        new_lat = avg(recent, "latency_ms")
        if old_lat > 0:
            lat_change = (new_lat - old_lat) / old_lat
            drift_signals["latency_drift"] = {
                "old_mean_ms": round(old_lat, 2),
                "new_mean_ms": round(new_lat, 2),
                "change_pct": round(lat_change * 100, 2),
                "drifted": lat_change > 0.30,
            }

        any_drift = any(
            v.get("drifted", False) for v in drift_signals.values()
        )

        return {
            "status": "drift_detected" if any_drift else "stable",
            "signals": drift_signals,
            "window_size": window,
        }

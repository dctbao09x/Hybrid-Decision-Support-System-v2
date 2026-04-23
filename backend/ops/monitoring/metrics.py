# backend/ops/monitoring/metrics.py
"""
Metrics Collector & Exporter — Prometheus-compatible.

Collects:
  • Process metrics  : CPU%, RSS, open FDs, threads
  • Runtime counters : requests, errors, latency histogram
  • Pipeline metrics : error_rate, drift score, scoring latency
  • Browser metrics  : leak count, browser RSS

Exposes:
  • /metrics  (text/plain; Prometheus scrape format)
  • JSON dict (for /health/full embedding)

No external dependency — pure stdlib + psutil (optional).
All metrics are in-memory; reset on restart.
Collection is O(1)-amortised via periodic snapshots.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("ops.monitoring.metrics")

try:
    import psutil

    _PSUTIL = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    _PSUTIL = False


# ══════════════════════════════════════════════════════════
#  Data structures
# ══════════════════════════════════════════════════════════

@dataclass(frozen=True)
class MetricSample:
    """Single point-in-time metric value."""
    name: str
    value: float
    labels: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class _Histogram:
    """Simple fixed-bucket latency histogram."""

    BUCKETS: Tuple[float, ...] = (
        0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0,
        2.5, 5.0, 10.0, 30.0, 60.0, float("inf"),
    )

    def __init__(self, name: str):
        self.name = name
        self._counts: Dict[float, int] = {b: 0 for b in self.BUCKETS}
        self._sum: float = 0.0
        self._count: int = 0
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        with self._lock:
            self._sum += value
            self._count += 1
            for bucket in self.BUCKETS:
                if value <= bucket:
                    self._counts[bucket] += 1

    def to_prom(self) -> str:
        lines: List[str] = []
        for bucket, count in self._counts.items():
            le = "+Inf" if math.isinf(bucket) else str(bucket)
            lines.append(f'{self.name}_bucket{{le="{le}"}} {count}')
        lines.append(f"{self.name}_sum {self._sum:.6f}")
        lines.append(f"{self.name}_count {self._count}")
        return "\n".join(lines)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "count": self._count,
                "sum": round(self._sum, 6),
                "avg": round(self._sum / self._count, 6) if self._count else 0,
                "buckets": {
                    ("+Inf" if math.isinf(k) else str(k)): v
                    for k, v in self._counts.items()
                },
            }


# ══════════════════════════════════════════════════════════
#  MetricsCollector
# ══════════════════════════════════════════════════════════

class MetricsCollector:
    """
    Central metrics store — thread-safe, lightweight.

    Usage::

        mc = MetricsCollector()
        mc.inc("http_requests_total", labels={"method": "GET", "path": "/health"})
        mc.set_gauge("process_cpu_percent", 23.4)
        mc.observe_latency("http_request_duration_seconds", 0.042)
        print(mc.export_prometheus())
    """

    def __init__(self, history_size: int = 720):
        # Counters  (monotonically increasing)
        self._counters: Dict[str, float] = defaultdict(float)
        # Gauges    (current value, can go up/down)
        self._gauges: Dict[str, float] = {}
        # Histograms
        self._histograms: Dict[str, _Histogram] = {}
        # Time-series snapshots for sparkline / dashboard
        self._series: Dict[str, Deque[Tuple[float, float]]] = defaultdict(
            lambda: deque(maxlen=history_size)
        )
        self._lock = threading.Lock()
        self._start_ts = time.time()

        # Pre-register standard histograms
        self._histograms["http_request_duration_seconds"] = _Histogram(
            "http_request_duration_seconds"
        )
        self._histograms["scoring_duration_seconds"] = _Histogram(
            "scoring_duration_seconds"
        )
        self._histograms["pipeline_stage_duration_seconds"] = _Histogram(
            "pipeline_stage_duration_seconds"
        )

    # ── Counter ─────────────────────────────────────────

    def inc(
        self,
        name: str,
        value: float = 1.0,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        key = self._label_key(name, labels)
        with self._lock:
            self._counters[key] += value

    # ── Gauge ───────────────────────────────────────────

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value
            self._series[name].append((time.time(), value))

    def get_gauge(self, name: str) -> float:
        return self._gauges.get(name, 0.0)

    # ── Histogram ───────────────────────────────────────

    def observe_latency(self, name: str, value_seconds: float) -> None:
        h = self._histograms.get(name)
        if not h:
            h = _Histogram(name)
            self._histograms[name] = h
        h.observe(value_seconds)

    # ── Process metrics (psutil) ────────────────────────

    def collect_process_metrics(self) -> Dict[str, float]:
        """Snapshot current-process CPU / RAM / FDs."""
        metrics: Dict[str, float] = {}
        if not _PSUTIL:
            return metrics
        try:
            proc = psutil.Process(os.getpid())
            mem = proc.memory_info()
            metrics["process_rss_bytes"] = float(mem.rss)
            metrics["process_rss_mb"] = round(mem.rss / (1024 ** 2), 2)
            metrics["process_cpu_percent"] = proc.cpu_percent(interval=0.0)
            metrics["process_threads"] = float(proc.num_threads())
            try:
                metrics["process_open_fds"] = float(len(proc.open_files()))
            except (psutil.AccessDenied, OSError):
                metrics["process_open_fds"] = 0.0
        except Exception as exc:
            logger.debug("process metrics error: %s", exc)
        return metrics

    def collect_system_metrics(self) -> Dict[str, float]:
        """Snapshot system-level CPU / RAM."""
        metrics: Dict[str, float] = {}
        if not _PSUTIL:
            return metrics
        try:
            cpu = psutil.cpu_percent(interval=0.0)
            mem = psutil.virtual_memory()
            metrics["system_cpu_percent"] = cpu
            metrics["system_memory_percent"] = mem.percent
            metrics["system_memory_available_mb"] = round(
                mem.available / (1024 ** 2), 2
            )
            metrics["system_memory_total_mb"] = round(
                mem.total / (1024 ** 2), 2
            )
        except Exception as exc:
            logger.debug("system metrics error: %s", exc)
        return metrics

    def refresh_infra_gauges(self) -> None:
        """Collect process + system metrics and store as gauges."""
        for k, v in self.collect_process_metrics().items():
            self.set_gauge(k, v)
        for k, v in self.collect_system_metrics().items():
            self.set_gauge(k, v)
        self.set_gauge("process_uptime_seconds", time.time() - self._start_ts)

    # ── Error rate ──────────────────────────────────────

    def record_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration: float,
    ) -> None:
        """Record an HTTP request (called from middleware)."""
        self.inc("http_requests_total", labels={"method": method, "path": path})
        self.inc(
            f"http_responses_total",
            labels={"status": str(status_code)},
        )
        if status_code >= 500:
            self.inc("http_errors_total", labels={"method": method, "path": path})
        self.observe_latency("http_request_duration_seconds", duration)

    def error_rate(self, window_seconds: float = 300) -> float:
        """Compute error rate over recent requests (from counters)."""
        total = sum(
            v for k, v in self._counters.items()
            if k.startswith("http_requests_total")
        )
        errors = sum(
            v for k, v in self._counters.items()
            if k.startswith("http_errors_total")
        )
        if total == 0:
            return 0.0
        return round(errors / total, 6)

    # ── Drift gauge ─────────────────────────────────────

    def record_drift(self, score: float, drifted: bool) -> None:
        self.set_gauge("data_drift_score", score)
        self.set_gauge("data_drift_detected", 1.0 if drifted else 0.0)

    # ── Browser leak gauge ──────────────────────────────

    def record_browser_leak(self, leak_report: Dict[str, Any]) -> None:
        self.set_gauge(
            "browser_memory_leak",
            1.0 if leak_report.get("memory_leak") else 0.0,
        )
        self.set_gauge(
            "browser_leak_severity",
            {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}.get(
                leak_report.get("severity", "none"), 0
            ),
        )

    # ── Export: Prometheus format ────────────────────────

    def export_prometheus(self) -> str:
        """Render all metrics in Prometheus text exposition format."""
        self.refresh_infra_gauges()
        lines: List[str] = []

        # Gauges
        with self._lock:
            for name, value in sorted(self._gauges.items()):
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{name} {value}")

        # Counters
        with self._lock:
            seen_types: set = set()
            for key, value in sorted(self._counters.items()):
                base = key.split("{")[0] if "{" in key else key
                if base not in seen_types:
                    lines.append(f"# TYPE {base} counter")
                    seen_types.add(base)
                lines.append(f"{key} {value}")

        # Histograms
        for name, hist in self._histograms.items():
            lines.append(f"# TYPE {name} histogram")
            lines.append(hist.to_prom())

        lines.append("")
        return "\n".join(lines)

    # ── Export: JSON (for /health/full) ─────────────────

    def export_json(self) -> Dict[str, Any]:
        """Return all metrics as a JSON-friendly dict."""
        self.refresh_infra_gauges()
        with self._lock:
            return {
                "gauges": dict(self._gauges),
                "counters": dict(self._counters),
                "histograms": {
                    n: h.snapshot() for n, h in self._histograms.items()
                },
                "error_rate": self.error_rate(),
                "uptime_seconds": round(time.time() - self._start_ts, 1),
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }

    # ── Series for dashboards ───────────────────────────

    def get_series(
        self,
        name: str,
        last_n: int = 60,
    ) -> List[Dict[str, Any]]:
        """Return recent time-series for a gauge."""
        data = list(self._series.get(name, []))[-last_n:]
        return [{"ts": ts, "value": v} for ts, v in data]

    # ── Internal ────────────────────────────────────────

    @staticmethod
    def _label_key(name: str, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return name
        pairs = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{pairs}}}"

# backend/ops/resource/leak_detector.py
"""
Memory and CPU Leak Detection.

Analyzes resource trends to detect:
- Memory leaks (monotonically increasing RSS)
- CPU leaks (sustained high CPU)
- Handle/FD leaks
- Connection leaks
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.resource.leak")

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore[assignment]


@dataclass
class LeakReport:
    """Report of detected leaks."""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    memory_leak: bool = False
    cpu_leak: bool = False
    handle_leak: bool = False
    connection_leak: bool = False
    details: Dict[str, Any] = field(default_factory=dict)
    severity: str = "none"  # none, low, medium, high, critical
    recommendation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "memory_leak": self.memory_leak,
            "cpu_leak": self.cpu_leak,
            "handle_leak": self.handle_leak,
            "connection_leak": self.connection_leak,
            "severity": self.severity,
            "recommendation": self.recommendation,
            "details": self.details,
        }


@dataclass
class ResourceSample:
    """Single resource measurement."""
    timestamp: float
    rss_mb: float
    cpu_percent: float
    open_files: int = 0
    connections: int = 0
    threads: int = 0


class LeakDetector:
    """
    Detects resource leaks by analyzing trends over time.

    Algorithm:
    1. Collect periodic samples
    2. Compute moving averages and slopes
    3. Flag leaks when slope exceeds threshold consistently
    """

    def __init__(
        self,
        sample_interval: float = 30.0,
        window_size: int = 60,  # 30 min at 30s intervals
        rss_slope_threshold_mb_per_min: float = 2.0,
        cpu_sustained_threshold: float = 80.0,
        handle_growth_threshold: int = 50,
    ):
        self.sample_interval = sample_interval
        self.window_size = window_size
        self.rss_slope_threshold = rss_slope_threshold_mb_per_min
        self.cpu_sustained_threshold = cpu_sustained_threshold
        self.handle_growth_threshold = handle_growth_threshold
        self._samples: List[ResourceSample] = []
        self._pid: Optional[int] = None

    def set_pid(self, pid: int) -> None:
        """Set PID to monitor."""
        self._pid = pid

    def collect_sample(self, pid: Optional[int] = None) -> Optional[ResourceSample]:
        """Collect a single resource sample."""
        if not psutil:
            return None

        target_pid = pid or self._pid
        if not target_pid:
            return None

        try:
            proc = psutil.Process(target_pid)
            mem = proc.memory_info()
            sample = ResourceSample(
                timestamp=time.time(),
                rss_mb=mem.rss / (1024 * 1024),
                cpu_percent=proc.cpu_percent(interval=0.1),
                open_files=len(proc.open_files()),
                connections=len(proc.connections()),
                threads=proc.num_threads(),
            )
            self._samples.append(sample)
            if len(self._samples) > self.window_size:
                self._samples = self._samples[-self.window_size:]
            return sample
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def analyze(self) -> LeakReport:
        """Analyze collected samples for leaks."""
        report = LeakReport()

        if len(self._samples) < 10:
            report.recommendation = "Insufficient samples for analysis (need ≥ 10)"
            return report

        # ── Memory Leak Detection ──
        rss_values = [s.rss_mb for s in self._samples]
        time_values = [s.timestamp for s in self._samples]
        duration_min = (time_values[-1] - time_values[0]) / 60.0

        if duration_min > 0:
            rss_slope = (rss_values[-1] - rss_values[0]) / duration_min
            report.details["rss_slope_mb_per_min"] = round(rss_slope, 3)
            report.details["rss_start_mb"] = round(rss_values[0], 2)
            report.details["rss_end_mb"] = round(rss_values[-1], 2)
            report.details["duration_minutes"] = round(duration_min, 1)

            # Check if RSS is monotonically increasing
            increasing_count = sum(
                1 for i in range(1, len(rss_values)) if rss_values[i] > rss_values[i-1]
            )
            monotonic_ratio = increasing_count / (len(rss_values) - 1)
            report.details["rss_monotonic_ratio"] = round(monotonic_ratio, 3)

            if rss_slope > self.rss_slope_threshold and monotonic_ratio > 0.7:
                report.memory_leak = True

        # ── CPU Leak Detection ──
        cpu_values = [s.cpu_percent for s in self._samples]
        sustained_high = sum(1 for c in cpu_values if c > self.cpu_sustained_threshold)
        sustained_ratio = sustained_high / len(cpu_values)
        report.details["cpu_sustained_high_ratio"] = round(sustained_ratio, 3)

        if sustained_ratio > 0.8:
            report.cpu_leak = True

        # ── Handle Leak ──
        handle_values = [s.open_files for s in self._samples]
        if handle_values:
            handle_growth = handle_values[-1] - handle_values[0]
            report.details["handle_growth"] = handle_growth
            if handle_growth > self.handle_growth_threshold:
                report.handle_leak = True

        # ── Connection Leak ──
        conn_values = [s.connections for s in self._samples]
        if conn_values:
            conn_growth = conn_values[-1] - conn_values[0]
            report.details["connection_growth"] = conn_growth
            if conn_growth > self.handle_growth_threshold:
                report.connection_leak = True

        # ── Severity ──
        leak_count = sum([
            report.memory_leak,
            report.cpu_leak,
            report.handle_leak,
            report.connection_leak,
        ])
        if leak_count == 0:
            report.severity = "none"
            report.recommendation = "No leaks detected"
        elif leak_count == 1:
            report.severity = "medium"
            report.recommendation = "Single leak detected — investigate and restart"
        elif leak_count <= 3:
            report.severity = "high"
            report.recommendation = "Multiple leaks — restart required, investigate root cause"
        else:
            report.severity = "critical"
            report.recommendation = "Critical: all resources leaking — immediate restart needed"

        return report

    def reset(self) -> None:
        """Clear collected samples."""
        self._samples.clear()

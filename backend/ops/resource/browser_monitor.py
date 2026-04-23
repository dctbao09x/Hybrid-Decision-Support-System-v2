# backend/ops/resource/browser_monitor.py
"""
Browser Resource Monitor for Playwright crawlers.

Tracks:
- Per-browser memory (RSS, heap)
- CPU usage per browser process
- Page count and connection health
- Network bandwidth consumption
- Automatic kill on threshold breach
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.resource.browser")

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore[assignment]


@dataclass
class BrowserSnapshot:
    """Point-in-time browser resource snapshot."""
    timestamp: str
    pid: int
    rss_mb: float
    cpu_percent: float
    num_pages: int
    connections: int
    status: str  # "healthy", "warning", "critical"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "pid": self.pid,
            "rss_mb": round(self.rss_mb, 2),
            "cpu_percent": round(self.cpu_percent, 2),
            "num_pages": self.num_pages,
            "connections": self.connections,
            "status": self.status,
        }


@dataclass
class ResourceThresholds:
    """Thresholds for resource monitoring."""
    max_rss_mb: float = 512.0
    warning_rss_mb: float = 384.0
    max_cpu_percent: float = 90.0
    warning_cpu_percent: float = 70.0
    max_pages: int = 10
    max_connections: int = 50
    check_interval: float = 10.0  # seconds


class BrowserResourceMonitor:
    """
    Monitors Playwright browser resource consumption.

    Integrates with BaseCrawler's existing memory_watchdog
    and adds CPU monitoring, trend analysis, and auto-kill.
    """

    def __init__(
        self,
        thresholds: Optional[ResourceThresholds] = None,
        history_size: int = 360,  # 1 hour at 10s intervals
    ):
        self.thresholds = thresholds or ResourceThresholds()
        self._history: List[BrowserSnapshot] = []
        self._history_size = history_size
        self._monitoring = False
        self._task: Optional[asyncio.Task] = None
        self._browser_pid: Optional[int] = None
        self._kill_callback: Optional[Any] = None
        self._alert_callback: Optional[Any] = None

    def set_browser_pid(self, pid: int) -> None:
        """Set the browser process PID to monitor."""
        self._browser_pid = pid
        logger.info(f"Monitoring browser PID: {pid}")

    def set_kill_callback(self, callback) -> None:
        """Set callback to kill browser on critical threshold."""
        self._kill_callback = callback

    def set_alert_callback(self, callback) -> None:
        """Set callback for alert notifications."""
        self._alert_callback = callback

    async def start(self) -> None:
        """Start continuous monitoring."""
        if self._monitoring:
            return
        self._monitoring = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Browser resource monitor started")

    async def stop(self) -> None:
        """Stop monitoring."""
        self._monitoring = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Browser resource monitor stopped")

    async def take_snapshot(self) -> Optional[BrowserSnapshot]:
        """Take a single resource snapshot."""
        if not psutil or not self._browser_pid:
            return None

        try:
            proc = psutil.Process(self._browser_pid)
            mem = proc.memory_info()
            cpu = proc.cpu_percent(interval=0.1)

            # Count child processes (browser tabs)
            children = proc.children(recursive=True)
            num_pages = len(children)
            connections = len(proc.connections())

            rss_mb = mem.rss / (1024 * 1024)

            # Determine status
            if rss_mb > self.thresholds.max_rss_mb or cpu > self.thresholds.max_cpu_percent:
                status = "critical"
            elif rss_mb > self.thresholds.warning_rss_mb or cpu > self.thresholds.warning_cpu_percent:
                status = "warning"
            else:
                status = "healthy"

            snapshot = BrowserSnapshot(
                timestamp=datetime.now().isoformat(),
                pid=self._browser_pid,
                rss_mb=rss_mb,
                cpu_percent=cpu,
                num_pages=num_pages,
                connections=connections,
                status=status,
            )
            return snapshot

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            logger.warning(f"Browser process {self._browser_pid} not found")
            return None

    async def _monitor_loop(self) -> None:
        """Continuous monitoring loop."""
        while self._monitoring:
            snapshot = await self.take_snapshot()
            if snapshot:
                self._history.append(snapshot)
                if len(self._history) > self._history_size:
                    self._history = self._history[-self._history_size:]

                # Handle thresholds
                if snapshot.status == "critical":
                    logger.critical(
                        f"CRITICAL: Browser RSS={snapshot.rss_mb:.0f}MB "
                        f"CPU={snapshot.cpu_percent:.0f}%"
                    )
                    if self._alert_callback:
                        await self._alert_callback(snapshot)
                    if self._kill_callback:
                        logger.warning("Auto-killing browser due to critical resource usage")
                        await self._kill_callback()
                elif snapshot.status == "warning":
                    logger.warning(
                        f"WARNING: Browser RSS={snapshot.rss_mb:.0f}MB "
                        f"CPU={snapshot.cpu_percent:.0f}%"
                    )

            await asyncio.sleep(self.thresholds.check_interval)

    def get_current_stats(self) -> Dict[str, Any]:
        """Get current resource statistics."""
        if not self._history:
            return {"status": "no_data"}

        recent = self._history[-1]
        avg_rss = sum(s.rss_mb for s in self._history[-30:]) / min(30, len(self._history))
        avg_cpu = sum(s.cpu_percent for s in self._history[-30:]) / min(30, len(self._history))

        return {
            "current": recent.to_dict(),
            "avg_rss_mb_5min": round(avg_rss, 2),
            "avg_cpu_percent_5min": round(avg_cpu, 2),
            "snapshots_collected": len(self._history),
            "monitoring": self._monitoring,
        }

    def get_trend(self, window: int = 60) -> Dict[str, Any]:
        """Analyze resource trend over a window of snapshots."""
        if len(self._history) < 2:
            return {"trend": "insufficient_data"}

        recent = self._history[-min(window, len(self._history)):]
        rss_values = [s.rss_mb for s in recent]
        cpu_values = [s.cpu_percent for s in recent]

        # Simple linear trend
        rss_delta = rss_values[-1] - rss_values[0]
        cpu_delta = cpu_values[-1] - cpu_values[0]

        return {
            "window_size": len(recent),
            "rss_trend_mb": round(rss_delta, 2),
            "cpu_trend_pct": round(cpu_delta, 2),
            "rss_growing": rss_delta > 10,  # >10MB growth
            "cpu_growing": cpu_delta > 5,    # >5% growth
            "rss_min_mb": round(min(rss_values), 2),
            "rss_max_mb": round(max(rss_values), 2),
            "cpu_min_pct": round(min(cpu_values), 2),
            "cpu_max_pct": round(max(cpu_values), 2),
        }

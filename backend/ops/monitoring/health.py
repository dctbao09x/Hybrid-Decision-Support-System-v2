# backend/ops/monitoring/health.py
"""
Health Check Service for pipeline components.

Provides:
- /health/live  — lightweight liveness probe (no deps, <10 ms)
- /health/full  — deep component check + process metrics + drift + leaks
- Component-level health checks with timeouts
- Integration with MetricsCollector for runtime gauges
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger("ops.monitoring.health")


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ComponentHealth:
    """Health check result for a single component."""

    def __init__(
        self,
        name: str,
        status: HealthStatus = HealthStatus.UNKNOWN,
        response_time_ms: float = 0.0,
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.status = status
        self.response_time_ms = response_time_ms
        self.message = message
        self.details = details or {}
        self.checked_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "response_time_ms": round(self.response_time_ms, 2),
            "message": self.message,
            "details": self.details,
            "checked_at": self.checked_at,
        }


class HealthCheckService:
    """
    Central health check service.

    Probes:
      live  — in-process heartbeat, always fast
      full  — runs all registered checks + infra metrics

    Checks:
    - Crawler availability
    - Data pipeline file access
    - Scoring engine readiness
    - Disk space
    - Memory usage
    """

    def __init__(self):
        self._checks: Dict[str, Callable] = {}
        self._last_results: Dict[str, ComponentHealth] = {}
        self._start_time = datetime.now(timezone.utc)
        self._metrics = None  # Injected by OpsHub after init

    # ── Metric injection ────────────────────────────────

    def set_metrics(self, metrics) -> None:
        """Inject MetricsCollector (avoids circular import)."""
        self._metrics = metrics

    # ── Registration ────────────────────────────────────

    def register_check(
        self,
        name: str,
        check_fn: Callable[..., Coroutine],
    ) -> None:
        """Register a health check function."""
        self._checks[name] = check_fn
        logger.info("Health check registered: %s", name)

    # ── Probes ──────────────────────────────────────────

    async def live(self) -> Dict[str, Any]:
        """
        Liveness probe — extremely fast, no dependency calls.

        Returns HTTP 200 if the process is alive and the event loop
        is responsive.  Suitable for k8s livenessProbe / ELB health.
        """
        uptime = (
            datetime.now(timezone.utc) - self._start_time
        ).total_seconds()
        return {
            "status": "alive",
            "service": "hdss-backend",
            "pid": os.getpid(),
            "uptime_seconds": round(uptime, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def check_all(self) -> Dict[str, Any]:
        """
        Full health probe — runs every registered check,
        collects process/system metrics, computes overall status.

        Suitable for readinessProbe or monitoring dashboards.
        Typical latency: 200–500 ms.
        """
        results: Dict[str, ComponentHealth] = {}
        check_timeout = 10.0  # per-check timeout

        for name, check_fn in self._checks.items():
            start = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    check_fn(), timeout=check_timeout
                )
                elapsed = (time.monotonic() - start) * 1000

                if isinstance(result, dict):
                    status = HealthStatus(result.get("status", "healthy"))
                    message = result.get("message", "OK")
                    details = result.get("details", {})
                else:
                    status = (
                        HealthStatus.HEALTHY
                        if result
                        else HealthStatus.UNHEALTHY
                    )
                    message = "OK" if result else "Check failed"
                    details = {}

                results[name] = ComponentHealth(
                    name=name,
                    status=status,
                    response_time_ms=elapsed,
                    message=message,
                    details=details,
                )
            except asyncio.TimeoutError:
                results[name] = ComponentHealth(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    response_time_ms=check_timeout * 1000,
                    message="Health check timed out",
                )
            except Exception as e:
                elapsed = (time.monotonic() - start) * 1000
                results[name] = ComponentHealth(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    response_time_ms=elapsed,
                    message=f"Error: {str(e)[:200]}",
                )

        self._last_results = results

        # ── Overall status ──
        statuses = [r.status for r in results.values()]
        if not statuses or all(
            s == HealthStatus.HEALTHY for s in statuses
        ):
            overall = HealthStatus.HEALTHY
        elif any(s == HealthStatus.UNHEALTHY for s in statuses):
            overall = HealthStatus.UNHEALTHY
        else:
            overall = HealthStatus.DEGRADED

        uptime = (
            datetime.now(timezone.utc) - self._start_time
        ).total_seconds()

        payload: Dict[str, Any] = {
            "status": overall.value,
            "uptime_seconds": round(uptime, 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {
                name: r.to_dict() for name, r in results.items()
            },
        }

        # ── Embed metrics snapshot ──
        if self._metrics:
            payload["metrics"] = self._metrics.export_json()

        # ── Record gauge for alerting ──
        if self._metrics:
            status_val = {
                HealthStatus.HEALTHY: 1.0,
                HealthStatus.DEGRADED: 0.5,
                HealthStatus.UNHEALTHY: 0.0,
            }.get(overall, 0.0)
            self._metrics.set_gauge("health_status", status_val)

        return payload

    async def check_component(self, name: str) -> ComponentHealth:
        """Run a single component health check."""
        check_fn = self._checks.get(name)
        if not check_fn:
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNKNOWN,
                message="Not registered",
            )

        start = time.monotonic()
        try:
            result = await check_fn()
            elapsed = (time.monotonic() - start) * 1000
            return ComponentHealth(
                name=name,
                status=HealthStatus.HEALTHY,
                response_time_ms=elapsed,
                message="OK",
                details=result if isinstance(result, dict) else {},
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNHEALTHY,
                response_time_ms=elapsed,
                message=str(e),
            )

    def get_last_results(self) -> Dict[str, Any]:
        """Return cached results from the last full check."""
        return {
            name: r.to_dict() for name, r in self._last_results.items()
        }

    # ── Built-in Health Checks ──────────────────────────────

    @staticmethod
    async def check_disk_space(
        path: str = ".", min_free_gb: float = 1.0
    ) -> Dict[str, Any]:
        """Check available disk space."""
        import shutil
        total, used, free = shutil.disk_usage(path)
        free_gb = free / (1024**3)
        return {
            "status": "healthy" if free_gb >= min_free_gb else "unhealthy",
            "message": f"Free: {free_gb:.1f} GB",
            "details": {
                "total_gb": round(total / (1024**3), 2),
                "used_gb": round(used / (1024**3), 2),
                "free_gb": round(free_gb, 2),
            },
        }

    @staticmethod
    async def check_memory() -> Dict[str, Any]:
        """Check system memory usage."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            if mem.percent >= 95:
                status = "unhealthy"
            elif mem.percent >= 90:
                status = "degraded"
            else:
                status = "healthy"
            return {
                "status": status,
                "message": f"Memory: {mem.percent}% used",
                "details": {
                    "total_gb": round(mem.total / (1024**3), 2),
                    "available_gb": round(mem.available / (1024**3), 2),
                    "percent": mem.percent,
                },
            }
        except ImportError:
            return {"status": "unknown", "message": "psutil not available"}

    @staticmethod
    async def check_data_dir() -> Dict[str, Any]:
        """Check data directory accessibility."""
        from pathlib import Path
        data_dir = Path("backend/data")
        market_dir = data_dir / "market"

        writable = False
        if data_dir.exists():
            probe = data_dir / ".health_check"
            try:
                probe.touch()
                probe.unlink(missing_ok=True)
                writable = True
            except OSError:
                pass

        return {
            "status": "healthy" if data_dir.exists() and writable else "unhealthy",
            "details": {
                "data_dir_exists": data_dir.exists(),
                "market_dir_exists": market_dir.exists(),
                "writable": writable,
            },
        }

    @staticmethod
    async def check_scoring_engine() -> Dict[str, Any]:
        """Verify scoring engine can process using pre-warmed instance."""
        try:
            # Use pre-warmed scorer from WarmupManager
            from backend.ops.warmup import get_warmup_manager
            warmup = get_warmup_manager()
            scorer = warmup.scoring.get_scorer()
            
            # Quick validation with direct component scores (faster)
            test_input = {
                "study": 0.7,
                "interest": 0.6,
                "market": 0.5,
                "growth": 0.4,
                "risk": 0.3,
            }
            result = scorer.score(test_input)
            
            if result and result.get("success"):
                return {
                    "status": "healthy",
                    "message": "Scoring engine operational (pre-warmed)",
                    "details": {
                        "model_loaded": warmup.scoring._status.model_loaded if warmup.scoring._status else False,
                        "cache_warm": warmup.scoring._status.cache_warm if warmup.scoring._status else False,
                    },
                }
            else:
                return {
                    "status": "degraded",
                    "message": "Scoring engine returned invalid result",
                }
        except Exception as e:
            return {
                "status": "degraded",
                "message": f"Scoring engine error: {str(e)[:200]}",
            }

# backend/ops/resilience/readiness.py
"""
Readiness Probe System
======================

Implements Kubernetes-style readiness probes for backend services.

Features:
- Fast liveness probe (is process alive?)
- Deep readiness probe (can handle traffic?)
- Startup probe (is initialization complete?)
- Graceful degradation signaling

Endpoints:
- /health/live   → Liveness (200 if alive)
- /health/ready  → Readiness (200 if can serve, 503 if not)
- /health/startup → Startup complete (200 if warmed up)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger("ops.resilience.readiness")


class ProbeStatus(str, Enum):
    """Probe result status."""
    PASS = "pass"       # Healthy
    WARN = "warn"       # Degraded but functional
    FAIL = "fail"       # Unhealthy
    UNKNOWN = "unknown" # Not checked yet


@dataclass
class ProbeResult:
    """Result of a single probe check."""
    name: str
    status: ProbeStatus
    latency_ms: float
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "latency_ms": round(self.latency_ms, 2),
            "message": self.message,
            "details": self.details,
            "checked_at": self.checked_at,
        }


@dataclass
class ReadinessState:
    """Overall readiness state."""
    is_ready: bool = False
    is_live: bool = True
    startup_complete: bool = False
    startup_time_ms: float = 0.0
    last_check_at: Optional[str] = None
    degraded_components: List[str] = field(default_factory=list)
    failed_components: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_ready": self.is_ready,
            "is_live": self.is_live,
            "startup_complete": self.startup_complete,
            "startup_time_ms": round(self.startup_time_ms, 2),
            "last_check_at": self.last_check_at,
            "degraded_components": self.degraded_components,
            "failed_components": self.failed_components,
            "overall_status": (
                "ready" if self.is_ready
                else "degraded" if not self.failed_components
                else "not_ready"
            ),
        }


class ReadinessProbe:
    """
    Readiness probe system.
    
    Manages startup, liveness, and readiness checks for the backend.
    """
    
    _instance: Optional["ReadinessProbe"] = None
    
    def __init__(self):
        self._checks: Dict[str, Callable] = {}
        self._critical_checks: set = set()  # Checks that must pass for readiness
        self._state = ReadinessState()
        self._startup_t0 = time.monotonic()
        self._check_timeout_ms = 5000.0
        self._last_results: Dict[str, ProbeResult] = {}
    
    @classmethod
    def get_instance(cls) -> "ReadinessProbe":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None
    
    def register_check(
        self,
        name: str,
        check_fn: Callable[..., Coroutine],
        critical: bool = False,
    ) -> None:
        """
        Register a readiness check.
        
        Args:
            name: Check name for identification
            check_fn: Async function returning dict with status/message
            critical: If True, failure blocks readiness
        """
        self._checks[name] = check_fn
        if critical:
            self._critical_checks.add(name)
        logger.info(
            f"Readiness check registered: {name} (critical={critical})"
        )
    
    async def _run_check(self, name: str, check_fn: Callable) -> ProbeResult:
        """Run a single check with timeout."""
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                check_fn(),
                timeout=self._check_timeout_ms / 1000.0,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            
            # Parse result
            if isinstance(result, dict):
                status_str = result.get("status", "pass")
                if status_str in ("healthy", "ready", "pass", "ok"):
                    status = ProbeStatus.PASS
                elif status_str in ("degraded", "warn", "warning"):
                    status = ProbeStatus.WARN
                else:
                    status = ProbeStatus.FAIL
                message = result.get("message", "")
                details = result.get("details", {})
            elif result is True:
                status = ProbeStatus.PASS
                message = "OK"
                details = {}
            else:
                status = ProbeStatus.FAIL
                message = str(result) if result else "Check failed"
                details = {}
            
            return ProbeResult(
                name=name,
                status=status,
                latency_ms=elapsed_ms,
                message=message,
                details=details,
            )
            
        except asyncio.TimeoutError:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProbeResult(
                name=name,
                status=ProbeStatus.FAIL,
                latency_ms=elapsed_ms,
                message=f"Check timed out after {self._check_timeout_ms}ms",
            )
        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProbeResult(
                name=name,
                status=ProbeStatus.FAIL,
                latency_ms=elapsed_ms,
                message=f"Check error: {str(e)[:200]}",
            )
    
    async def check_liveness(self) -> Dict[str, Any]:
        """
        Liveness probe - is the process alive and responsive?
        
        Always fast (<10ms). No external dependencies.
        Returns 200 if event loop is responsive.
        """
        uptime_seconds = time.monotonic() - self._startup_t0
        
        return {
            "status": "alive",
            "pid": os.getpid(),
            "uptime_seconds": round(uptime_seconds, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    async def check_readiness(self) -> Dict[str, Any]:
        """
        Readiness probe - can the service handle traffic?
        
        Runs all registered checks. Returns 200 only if:
        - All critical checks pass
        - Startup is complete
        
        Returns 503 if not ready to serve traffic.
        """
        results: Dict[str, ProbeResult] = {}
        degraded = []
        failed = []
        
        # Run all checks in parallel
        check_tasks = {
            name: self._run_check(name, fn)
            for name, fn in self._checks.items()
        }
        
        if check_tasks:
            done_results = await asyncio.gather(*check_tasks.values())
            for name, result in zip(check_tasks.keys(), done_results):
                results[name] = result
                self._last_results[name] = result
                
                if result.status == ProbeStatus.FAIL:
                    failed.append(name)
                elif result.status == ProbeStatus.WARN:
                    degraded.append(name)
        
        # Determine overall readiness
        critical_ok = all(
            results.get(name, ProbeResult(name, ProbeStatus.UNKNOWN, 0))
            .status != ProbeStatus.FAIL
            for name in self._critical_checks
        )
        
        is_ready = (
            self._state.startup_complete
            and critical_ok
            and len(failed) == 0
        )
        
        # Update state
        self._state.is_ready = is_ready
        self._state.degraded_components = degraded
        self._state.failed_components = failed
        self._state.last_check_at = datetime.now(timezone.utc).isoformat()
        
        return {
            "status": "ready" if is_ready else "not_ready",
            "ready": is_ready,
            "startup_complete": self._state.startup_complete,
            "checks": {name: r.to_dict() for name, r in results.items()},
            "summary": {
                "total": len(results),
                "passed": len([r for r in results.values() if r.status == ProbeStatus.PASS]),
                "degraded": len(degraded),
                "failed": len(failed),
            },
            "degraded_components": degraded,
            "failed_components": failed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    async def check_startup(self) -> Dict[str, Any]:
        """
        Startup probe - has initialization completed?
        
        Returns 200 when all warmup tasks are done.
        Used by load balancers to know when to start sending traffic.
        """
        return {
            "status": "complete" if self._state.startup_complete else "initializing",
            "startup_complete": self._state.startup_complete,
            "startup_time_ms": self._state.startup_time_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    def mark_startup_complete(self, startup_time_ms: float = 0) -> None:
        """Mark startup as complete."""
        if startup_time_ms == 0:
            startup_time_ms = (time.monotonic() - self._startup_t0) * 1000
        
        self._state.startup_complete = True
        self._state.startup_time_ms = startup_time_ms
        self._state.is_ready = True  # Tentatively ready, will verify on first check
        
        logger.info(
            f"Startup complete in {startup_time_ms:.1f}ms, "
            f"registered checks: {list(self._checks.keys())}"
        )
    
    def get_state(self) -> ReadinessState:
        """Get current readiness state."""
        return self._state


# ══════════════════════════════════════════════════════════════════════════════
# Singleton accessor
# ══════════════════════════════════════════════════════════════════════════════

def get_readiness_probe() -> ReadinessProbe:
    """Get the global readiness probe instance."""
    return ReadinessProbe.get_instance()

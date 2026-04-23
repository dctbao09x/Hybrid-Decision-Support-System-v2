# backend/ops/orchestration/supervisor.py
"""
Auto-restart supervisor for pipeline components.

Features:
- Wraps any async callable with automatic restart on crash
- Configurable restart policy (max retries, backoff, cooldown)
- Health probe integration
- Graceful shutdown coordination
- Event hooks for monitoring integration
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger("ops.orchestration.supervisor")


class SupervisedState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    RESTARTING = "restarting"
    FAILED = "failed"
    SHUTDOWN = "shutdown"


@dataclass
class RestartPolicy:
    """Configuration for restart behaviour."""
    max_restarts: int = 5
    restart_window_seconds: float = 300.0       # reset counter after this
    base_backoff_seconds: float = 2.0
    max_backoff_seconds: float = 60.0
    backoff_factor: float = 2.0
    cooldown_after_max: float = 120.0           # wait before allowing manual restart


@dataclass
class SupervisorEvent:
    """Logged event in supervisor lifecycle."""
    timestamp: str
    event: str
    detail: str = ""


@dataclass
class SupervisedProcess:
    """Runtime tracking for one supervised component."""
    name: str
    state: SupervisedState = SupervisedState.STOPPED
    restart_count: int = 0
    last_start: Optional[float] = None
    last_crash: Optional[float] = None
    last_error: str = ""
    total_uptime_seconds: float = 0.0
    events: List[SupervisorEvent] = field(default_factory=list)
    _task: Optional[asyncio.Task] = field(default=None, repr=False)


class PipelineSupervisor:
    """
    Supervises async components with auto-restart.

    Usage:
        supervisor = PipelineSupervisor()

        # Register components
        supervisor.register("crawler_topcv", crawler.run, policy=RestartPolicy(max_restarts=3))
        supervisor.register("crawler_vnw", vnw_crawler.run)

        # Start all
        await supervisor.start_all()

        # Stop gracefully
        await supervisor.shutdown()
    """

    def __init__(self):
        self._processes: Dict[str, SupervisedProcess] = {}
        self._policies: Dict[str, RestartPolicy] = {}
        self._functions: Dict[str, Callable[..., Coroutine]] = {}
        self._shutdown_event = asyncio.Event()

        # Event hooks (monitoring integration)
        self._on_start: Optional[Callable] = None
        self._on_crash: Optional[Callable] = None
        self._on_restart: Optional[Callable] = None
        self._on_max_restart: Optional[Callable] = None

    # ── Registration ──────────────────────────────────

    def register(
        self,
        name: str,
        func: Callable[..., Coroutine],
        policy: Optional[RestartPolicy] = None,
    ) -> None:
        """Register a component for supervision."""
        self._functions[name] = func
        self._policies[name] = policy or RestartPolicy()
        self._processes[name] = SupervisedProcess(name=name)
        logger.info(f"Registered supervised process: {name}")

    # ── Lifecycle ─────────────────────────────────────

    async def start_all(self) -> None:
        """Start all registered components."""
        self._shutdown_event.clear()
        for name in self._functions:
            await self.start(name)

    async def start(self, name: str) -> None:
        """Start a single component."""
        if name not in self._functions:
            raise KeyError(f"Unknown process: {name}")

        proc = self._processes[name]
        if proc.state == SupervisedState.RUNNING:
            logger.warning(f"{name} is already running")
            return

        proc.state = SupervisedState.STARTING
        proc._task = asyncio.create_task(self._supervise_loop(name))
        self._record_event(name, "started")
        logger.info(f"Supervisor started: {name}")

    async def stop(self, name: str) -> None:
        """Stop a single component gracefully."""
        proc = self._processes.get(name)
        if not proc or not proc._task:
            return

        proc.state = SupervisedState.SHUTDOWN
        proc._task.cancel()
        try:
            await asyncio.wait_for(proc._task, timeout=10.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        proc._task = None
        proc.state = SupervisedState.STOPPED
        self._record_event(name, "stopped")

    async def shutdown(self) -> None:
        """Stop all components gracefully."""
        self._shutdown_event.set()
        for name in list(self._functions):
            await self.stop(name)
        logger.info("All supervised processes stopped")

    async def restart(self, name: str) -> None:
        """Manual restart of a component (resets restart counter)."""
        proc = self._processes.get(name)
        if proc:
            proc.restart_count = 0
        await self.stop(name)
        await self.start(name)
        self._record_event(name, "manual_restart")

    # ── Supervision Loop ──────────────────────────────

    async def _supervise_loop(self, name: str) -> None:
        """Core supervision loop with auto-restart."""
        proc = self._processes[name]
        policy = self._policies[name]
        func = self._functions[name]

        window_start = time.monotonic()

        while not self._shutdown_event.is_set():
            proc.state = SupervisedState.RUNNING
            proc.last_start = time.monotonic()

            if self._on_start:
                try:
                    await self._on_start(name)
                except Exception:
                    pass

            try:
                await func()
                # Clean exit
                self._record_event(name, "clean_exit")
                break

            except asyncio.CancelledError:
                self._record_event(name, "cancelled")
                break

            except Exception as e:
                crash_time = time.monotonic()
                uptime = crash_time - (proc.last_start or crash_time)
                proc.total_uptime_seconds += uptime
                proc.last_crash = crash_time
                proc.last_error = str(e)[:500]

                logger.error(f"Process {name} crashed: {e}")
                self._record_event(name, "crashed", str(e)[:200])

                if self._on_crash:
                    try:
                        await self._on_crash(name, e)
                    except Exception:
                        pass

                # Reset counter if outside window
                if crash_time - window_start > policy.restart_window_seconds:
                    proc.restart_count = 0
                    window_start = crash_time

                proc.restart_count += 1

                if proc.restart_count > policy.max_restarts:
                    proc.state = SupervisedState.FAILED
                    logger.critical(
                        f"Process {name} exceeded max restarts "
                        f"({policy.max_restarts}). Entering cooldown."
                    )
                    self._record_event(name, "max_restarts_exceeded")

                    if self._on_max_restart:
                        try:
                            await self._on_max_restart(name)
                        except Exception:
                            pass

                    # Cooldown before allowing manual restart
                    await asyncio.sleep(policy.cooldown_after_max)
                    break

                # Exponential backoff
                delay = min(
                    policy.base_backoff_seconds * (policy.backoff_factor ** (proc.restart_count - 1)),
                    policy.max_backoff_seconds,
                )
                proc.state = SupervisedState.RESTARTING
                logger.info(f"Restarting {name} in {delay:.1f}s (attempt {proc.restart_count}/{policy.max_restarts})")
                self._record_event(name, "restarting", f"delay={delay:.1f}s")

                if self._on_restart:
                    try:
                        await self._on_restart(name, proc.restart_count)
                    except Exception:
                        pass

                await asyncio.sleep(delay)

        if proc.last_start:
            proc.total_uptime_seconds += time.monotonic() - proc.last_start

    # ── Monitoring ────────────────────────────────────

    def set_hooks(
        self,
        on_start: Optional[Callable] = None,
        on_crash: Optional[Callable] = None,
        on_restart: Optional[Callable] = None,
        on_max_restart: Optional[Callable] = None,
    ) -> None:
        """Set event hooks for monitoring integration."""
        self._on_start = on_start
        self._on_crash = on_crash
        self._on_restart = on_restart
        self._on_max_restart = on_max_restart

    def get_status(self) -> Dict[str, Any]:
        """Get status of all supervised processes."""
        return {
            name: {
                "state": proc.state.value,
                "restart_count": proc.restart_count,
                "last_error": proc.last_error,
                "total_uptime_s": round(proc.total_uptime_seconds, 1),
                "events": len(proc.events),
            }
            for name, proc in self._processes.items()
        }

    def get_process_detail(self, name: str) -> Dict[str, Any]:
        """Get detailed info for one process."""
        proc = self._processes.get(name)
        if not proc:
            return {"error": f"Unknown process: {name}"}
        return {
            "name": proc.name,
            "state": proc.state.value,
            "restart_count": proc.restart_count,
            "last_error": proc.last_error,
            "total_uptime_s": round(proc.total_uptime_seconds, 1),
            "recent_events": [
                {"timestamp": e.timestamp, "event": e.event, "detail": e.detail}
                for e in proc.events[-20:]
            ],
        }

    def _record_event(self, name: str, event: str, detail: str = "") -> None:
        proc = self._processes.get(name)
        if proc:
            proc.events.append(SupervisorEvent(
                timestamp=datetime.now().isoformat(),
                event=event,
                detail=detail,
            ))
            if len(proc.events) > 200:
                proc.events = proc.events[-200:]

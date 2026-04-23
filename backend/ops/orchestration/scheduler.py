# backend/ops/orchestration/scheduler.py
"""
Pipeline Scheduler with cron-like scheduling, auto-retry, and failure isolation.

Manages the full pipeline lifecycle:
  crawl → validate → score → explain

Supports:
  - Cron-based scheduling
  - Manual trigger
  - Dependency-aware stage execution
  - Failure isolation (stage failure doesn't kill pipeline)
  - Auto-retry with exponential backoff
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger("ops.scheduler")


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class PipelineStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class StageResult:
    """Result of a single pipeline stage."""
    stage_name: str
    status: StageStatus = StageStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    records_in: int = 0
    records_out: int = 0
    error: Optional[str] = None
    retries: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineRun:
    """Represents a single pipeline execution."""
    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    status: PipelineStatus = PipelineStatus.IDLE
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    stages: Dict[str, StageResult] = field(default_factory=dict)
    trigger: str = "manual"  # "manual" | "scheduled" | "api"
    config_snapshot: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": round(self.duration_seconds, 2),
            "trigger": self.trigger,
            "stages": {
                name: {
                    "status": s.status.value,
                    "duration_seconds": round(s.duration_seconds, 2),
                    "records_in": s.records_in,
                    "records_out": s.records_out,
                    "error": s.error,
                    "retries": s.retries,
                }
                for name, s in self.stages.items()
            },
        }


@dataclass
class StageDefinition:
    """Definition of a pipeline stage."""
    name: str
    handler: Callable[..., Coroutine]
    depends_on: List[str] = field(default_factory=list)
    critical: bool = True  # If True, pipeline stops on failure
    max_retries: int = 3
    retry_delay_base: float = 5.0  # seconds, exponential backoff
    timeout: float = 3600.0  # 1 hour default


class PipelineScheduler:
    """
    Orchestrates the crawl → validate → score → explain pipeline.

    Features:
    - Stage-based execution with dependency resolution
    - Failure isolation for non-critical stages
    - Auto-retry with exponential backoff
    - Scheduling with cron-like intervals
    - Run history tracking
    """

    PIPELINE_STAGES = ["crawl", "validate", "score", "explain"]

    def __init__(self, max_history: int = 100):
        self._stages: Dict[str, StageDefinition] = {}
        self._run_history: List[PipelineRun] = []
        self._max_history = max_history
        self._current_run: Optional[PipelineRun] = None
        self._schedule_task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._lock = asyncio.Lock()

    # ── Stage Registration ──────────────────────────────────

    def register_stage(
        self,
        name: str,
        handler: Callable[..., Coroutine],
        depends_on: Optional[List[str]] = None,
        critical: bool = True,
        max_retries: int = 3,
        retry_delay_base: float = 5.0,
        timeout: float = 3600.0,
    ) -> None:
        """Register a pipeline stage."""
        self._stages[name] = StageDefinition(
            name=name,
            handler=handler,
            depends_on=depends_on or [],
            critical=critical,
            max_retries=max_retries,
            retry_delay_base=retry_delay_base,
            timeout=timeout,
        )
        logger.info(f"Registered stage: {name} (critical={critical}, retries={max_retries})")

    # ── Execution ───────────────────────────────────────────

    async def run_pipeline(
        self,
        trigger: str = "manual",
        config_override: Optional[Dict[str, Any]] = None,
        stages: Optional[List[str]] = None,
        checkpoint_mgr=None,
    ) -> PipelineRun:
        """
        Execute the full pipeline or a subset of stages.

        Args:
            trigger: What triggered this run
            config_override: Override default config
            stages: Specific stages to run (None = all)
            checkpoint_mgr: Optional CheckpointManager for state persistence
        """
        async with self._lock:
            run = PipelineRun(
                trigger=trigger,
                config_snapshot=config_override or {},
            )
            self._current_run = run

        run.started_at = datetime.now()
        run.status = PipelineStatus.RUNNING
        logger.info(f"Pipeline run {run.run_id} started (trigger={trigger})")

        stages_to_run = stages or self.PIPELINE_STAGES
        pipeline_ok = True
        previous_output = None

        for stage_name in stages_to_run:
            stage_def = self._stages.get(stage_name)
            if not stage_def:
                logger.warning(f"Stage '{stage_name}' not registered, skipping")
                run.stages[stage_name] = StageResult(
                    stage_name=stage_name, status=StageStatus.SKIPPED
                )
                continue

            # Check dependencies
            deps_met = all(
                run.stages.get(dep, StageResult(stage_name=dep, status=StageStatus.SKIPPED)).status
                == StageStatus.SUCCESS
                for dep in stage_def.depends_on
            )
            if not deps_met:
                logger.warning(f"Stage '{stage_name}' dependencies not met, skipping")
                run.stages[stage_name] = StageResult(
                    stage_name=stage_name, status=StageStatus.SKIPPED
                )
                if stage_def.critical:
                    pipeline_ok = False
                    break
                continue

            # Execute stage with retry
            result = await self._execute_stage(stage_def, previous_output, checkpoint_mgr)
            run.stages[stage_name] = result

            if result.status == StageStatus.SUCCESS:
                previous_output = result.metadata.get("output")
                if checkpoint_mgr:
                    await checkpoint_mgr.save(run.run_id, stage_name, result)
            elif stage_def.critical:
                pipeline_ok = False
                logger.error(f"Critical stage '{stage_name}' failed, stopping pipeline")
                break
            else:
                logger.warning(f"Non-critical stage '{stage_name}' failed, continuing")

        run.completed_at = datetime.now()
        if pipeline_ok:
            has_failures = any(
                s.status == StageStatus.FAILED for s in run.stages.values()
            )
            run.status = (
                PipelineStatus.PARTIAL_FAILURE if has_failures else PipelineStatus.COMPLETED
            )
        else:
            run.status = PipelineStatus.FAILED

        self._run_history.append(run)
        if len(self._run_history) > self._max_history:
            self._run_history = self._run_history[-self._max_history:]

        self._current_run = None
        logger.info(
            f"Pipeline run {run.run_id} finished: {run.status.value} "
            f"({run.duration_seconds:.1f}s)"
        )
        return run

    async def _execute_stage(
        self,
        stage_def: StageDefinition,
        input_data: Any,
        checkpoint_mgr=None,
    ) -> StageResult:
        """Execute a single stage with retry logic."""
        result = StageResult(stage_name=stage_def.name)
        result.started_at = datetime.now()

        for attempt in range(stage_def.max_retries + 1):
            try:
                result.status = StageStatus.RUNNING if attempt == 0 else StageStatus.RETRYING
                result.retries = attempt

                output = await asyncio.wait_for(
                    stage_def.handler(input_data),
                    timeout=stage_def.timeout,
                )

                result.status = StageStatus.SUCCESS
                result.completed_at = datetime.now()
                result.duration_seconds = (
                    result.completed_at - result.started_at
                ).total_seconds()

                if isinstance(output, dict):
                    result.records_in = output.get("records_in", 0)
                    result.records_out = output.get("records_out", 0)
                    result.metadata["output"] = output

                return result

            except asyncio.TimeoutError:
                result.error = f"Timeout after {stage_def.timeout}s (attempt {attempt+1})"
                logger.warning(result.error)
            except Exception as e:
                result.error = f"{type(e).__name__}: {str(e)[:500]}"
                logger.exception(f"Stage '{stage_def.name}' attempt {attempt+1} failed")

            if attempt < stage_def.max_retries:
                delay = stage_def.retry_delay_base * (2 ** attempt)
                logger.info(f"Retrying '{stage_def.name}' in {delay:.1f}s...")
                await asyncio.sleep(delay)

        result.status = StageStatus.FAILED
        result.completed_at = datetime.now()
        result.duration_seconds = (
            result.completed_at - result.started_at
        ).total_seconds()
        return result

    # ── Scheduling ──────────────────────────────────────────

    async def start_schedule(
        self,
        interval_seconds: int = 21600,  # 6 hours
        checkpoint_mgr=None,
    ) -> None:
        """Start scheduled pipeline runs."""
        self._shutdown.clear()
        logger.info(f"Scheduler started (interval={interval_seconds}s)")

        while not self._shutdown.is_set():
            try:
                await self.run_pipeline(
                    trigger="scheduled",
                    checkpoint_mgr=checkpoint_mgr,
                )
            except Exception:
                logger.exception("Scheduled run failed")

            try:
                await asyncio.wait_for(
                    self._shutdown.wait(), timeout=interval_seconds
                )
            except asyncio.TimeoutError:
                pass  # Normal: interval elapsed, next run

        logger.info("Scheduler stopped")

    def stop_schedule(self) -> None:
        """Stop the scheduler."""
        self._shutdown.set()
        if self._schedule_task and not self._schedule_task.done():
            self._schedule_task.cancel()

    # ── Status ──────────────────────────────────────────────

    @property
    def current_run(self) -> Optional[PipelineRun]:
        return self._current_run

    @property
    def run_history(self) -> List[PipelineRun]:
        return list(self._run_history)

    def get_last_run(self) -> Optional[PipelineRun]:
        return self._run_history[-1] if self._run_history else None

    def get_stats(self) -> Dict[str, Any]:
        """Get scheduler statistics."""
        if not self._run_history:
            return {"total_runs": 0}

        successes = sum(
            1 for r in self._run_history if r.status == PipelineStatus.COMPLETED
        )
        failures = sum(
            1 for r in self._run_history if r.status == PipelineStatus.FAILED
        )
        durations = [r.duration_seconds for r in self._run_history if r.duration_seconds > 0]

        return {
            "total_runs": len(self._run_history),
            "success_rate": round(successes / len(self._run_history), 4) if self._run_history else 0,
            "failures": failures,
            "avg_duration_seconds": round(sum(durations) / len(durations), 2) if durations else 0,
            "last_run": self._run_history[-1].to_dict() if self._run_history else None,
        }

"""
Recovery Manager — Central orchestrator for failure recovery.
=============================================================
Integrates FailureCatalog + StageRetryExecutor + StageRollbackManager +
RecoveryCheckpointManager into a single cohesive self-healing system.

Key guarantees:
  1. Stage fail ≠ kill whole run
     Non-critical stages are skipped; critical stages get retry + rollback.
  2. Recovery < 15 min
     Total recovery budget (retry delays + rollback) is capped at 15 min.
  3. Safe rerun
     Idempotency guard: same input → skip; changed input → rerun.
  4. Partial rollback
     Only affected stages are rolled back, not the entire pipeline.

Usage from MainController:
    recovery = RecoveryManager(catalog, retry_exec, rollback_mgr, checkpoint_mgr)
    result = await recovery.execute_stage(run_id, "crawl", stage_func, ...)
    # result.action tells you what happened: "completed" | "recovered" | "skipped" | "failed"
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional

from backend.ops.recovery.failure_catalog import (
    ClassifiedFailure,
    FailureCatalog,
    FailureCategory,
    RecoveryStrategy,
)
from backend.ops.recovery.stage_checkpoint import RecoveryCheckpointManager
from backend.ops.recovery.stage_retry import RetryResult, StageRetryExecutor
from backend.ops.recovery.stage_rollback import StageRollbackManager

logger = logging.getLogger("ops.recovery.manager")

# Maximum total recovery time per stage (seconds)
MAX_STAGE_RECOVERY_SECONDS = 300  # 5 min per stage
# Maximum total recovery time per run (seconds)
MAX_RUN_RECOVERY_SECONDS = 900    # 15 min total


# ── Stage criticality ──────────────────────────────────────────────────

STAGE_CRITICALITY: Dict[str, bool] = {
    "crawl": True,       # critical — no data without it
    "validate": True,    # critical — bad data is worse than no data
    "score": True,       # critical — scoring is the core value
    "explain": False,    # non-critical — recommendations work without explanations
}


# ── Recovery Result ────────────────────────────────────────────────────

@dataclass
class StageRecoveryResult:
    """Outcome of a recovery-managed stage execution."""
    stage: str
    run_id: str
    action: str          # completed | recovered | skipped | failed | aborted
    result: Any = None   # stage output data (if successful)
    attempts: int = 1
    retry_result: Optional[RetryResult] = None
    rollback_result: Optional[Dict[str, Any]] = None
    classified: Optional[ClassifiedFailure] = None
    duration: float = 0.0
    skip_reason: str = ""

    @property
    def success(self) -> bool:
        return self.action in ("completed", "recovered", "skipped")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "run_id": self.run_id,
            "action": self.action,
            "success": self.success,
            "attempts": self.attempts,
            "duration": round(self.duration, 2),
            "skip_reason": self.skip_reason,
            "retry": self.retry_result.to_dict() if self.retry_result else None,
            "rollback": self.rollback_result,
            "failure": self.classified.to_dict() if self.classified else None,
        }


@dataclass
class RunRecoveryResult:
    """Outcome of a full pipeline run with recovery."""
    run_id: str
    status: str = "running"  # completed | partial | failed
    stages: Dict[str, StageRecoveryResult] = field(default_factory=dict)
    total_duration: float = 0.0
    recovery_events: int = 0

    @property
    def completed_stages(self) -> List[str]:
        return [s for s, r in self.stages.items() if r.success]

    @property
    def failed_stages(self) -> List[str]:
        return [s for s, r in self.stages.items() if not r.success]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "total_duration": round(self.total_duration, 2),
            "recovery_events": self.recovery_events,
            "completed": self.completed_stages,
            "failed": self.failed_stages,
            "stages": {k: v.to_dict() for k, v in self.stages.items()},
        }


# ═══════════════════════════════════════════════════════════════════════
#  RecoveryManager
# ═══════════════════════════════════════════════════════════════════════

class RecoveryManager:
    """
    Central recovery orchestrator.

    execute_stage() wraps a stage function with:
      1. Safe-rerun check (idempotency)
      2. Retry with failure-aware backoff
      3. Rollback on failure (if strategy says so)
      4. Post-rollback retry (for ROLLBACK_AND_RETRY strategy)
      5. Skip non-critical stages on unrecoverable failure
      6. Time-budget enforcement (<15 min total)

    execute_pipeline() runs the full pipeline with per-stage recovery.
    """

    def __init__(
        self,
        catalog: Optional[FailureCatalog] = None,
        retry_executor: Optional[StageRetryExecutor] = None,
        rollback_manager: Optional[StageRollbackManager] = None,
        checkpoint_manager: Optional[RecoveryCheckpointManager] = None,
    ) -> None:
        self.catalog = catalog or FailureCatalog()
        self.retry = retry_executor or StageRetryExecutor(catalog=self.catalog)
        self.rollback = rollback_manager or StageRollbackManager()
        self.checkpoint = checkpoint_manager or RecoveryCheckpointManager()

        self._run_start_times: Dict[str, float] = {}
        self._recovery_log: List[Dict[str, Any]] = []

    # ── Single-stage execution with recovery ───────────────────────

    async def execute_stage(
        self,
        run_id: str,
        stage: str,
        func: Callable[..., Coroutine],
        *args: Any,
        critical: Optional[bool] = None,
        input_data: Any = None,
        **kwargs: Any,
    ) -> StageRecoveryResult:
        """
        Execute a single pipeline stage with full recovery support.

        Flow:
          1. Check time budget
          2. Safe-rerun guard (skip if input unchanged & already done)
          3. Begin checkpoint
          4. Execute with retry
          5. If failed & retryable → already retried in step 4
          6. If failed & strategy=ROLLBACK_AND_RETRY → rollback + one more try
          7. If failed & strategy=SKIP_STAGE & non-critical → skip
          8. If failed & strategy=ABORT/ESCALATE → propagate
        """
        stage_t0 = time.time()
        is_critical = critical if critical is not None else STAGE_CRITICALITY.get(stage, True)

        # ── 1. Time budget check ──
        if not self._check_time_budget(run_id):
            logger.error(
                f"[{run_id}] Recovery time budget exhausted — aborting stage '{stage}'"
            )
            return StageRecoveryResult(
                stage=stage,
                run_id=run_id,
                action="aborted",
                skip_reason="Recovery time budget exhausted (>15min)",
                duration=0.0,
            )

        # ── 2. Safe-rerun guard ──
        if not self.checkpoint.is_safe_rerun(run_id, stage, input_data):
            logger.info(
                f"[{run_id}] Stage '{stage}' already completed with same input — skipping"
            )
            return StageRecoveryResult(
                stage=stage,
                run_id=run_id,
                action="skipped",
                skip_reason="Idempotent: input unchanged, already completed",
                duration=0.0,
            )

        # ── 3. Begin checkpoint ──
        attempt = self.checkpoint.get_stage_attempt(run_id, stage) + 1
        self.checkpoint.begin_stage(
            run_id, stage, input_data=input_data, attempt=attempt
        )

        # ── 4. Execute with retry ──
        retry_result = await self.retry.execute(
            stage, func, *args, run_id=run_id, **kwargs,
        )

        if retry_result.success:
            # Stage completed successfully (possibly after retries)
            self.checkpoint.complete_stage(
                run_id, stage, output_data=retry_result.result
            )
            action = "recovered" if retry_result.attempts > 1 else "completed"
            if retry_result.attempts > 1:
                self._log_recovery(run_id, stage, "retry_success", retry_result.attempts)

            return StageRecoveryResult(
                stage=stage,
                run_id=run_id,
                action=action,
                result=retry_result.result,
                attempts=retry_result.attempts,
                retry_result=retry_result,
                duration=time.time() - stage_t0,
            )

        # ── Retry failed — classify and decide strategy ──
        classified = retry_result.classified
        if not classified:
            # Classify the last error if retry didn't
            classified = self.catalog.classify(
                retry_result.last_error or Exception("Unknown error"),
                stage=stage,
                run_id=run_id,
            )

        strategy = classified.recovery_strategy
        logger.warning(
            f"[{run_id}] Stage '{stage}' failed after {retry_result.attempts} attempts. "
            f"Category={classified.category.value}, Strategy={strategy.value}"
        )

        # ── 5. ROLLBACK_AND_RETRY ──
        if strategy == RecoveryStrategy.ROLLBACK_AND_RETRY:
            recovery = await self._rollback_and_retry(
                run_id, stage, func, args, kwargs,
                classified, retry_result, stage_t0,
            )
            if recovery:
                return recovery

        # ── 6. SKIP_STAGE (non-critical only) ──
        if strategy == RecoveryStrategy.SKIP_STAGE or (
            not is_critical and strategy != RecoveryStrategy.ABORT
        ):
            self.checkpoint.skip_stage(
                run_id, stage,
                reason=f"Non-critical stage skipped: {classified.category.value}",
            )
            self._log_recovery(run_id, stage, "skipped", retry_result.attempts)

            # Record to catalog history
            self.catalog.record_failure(
                run_id, stage, classified,
                recovered=True,
                recovery_duration=time.time() - stage_t0,
            )

            return StageRecoveryResult(
                stage=stage,
                run_id=run_id,
                action="skipped",
                attempts=retry_result.attempts,
                retry_result=retry_result,
                classified=classified,
                skip_reason=(
                    f"Non-critical stage skipped after {retry_result.attempts} "
                    f"attempts ({classified.category.value})"
                ),
                duration=time.time() - stage_t0,
            )

        # ── 7. ABORT / ESCALATE / unrecoverable ──
        self.checkpoint.fail_stage(
            run_id, stage, classified.error,
            metadata={"category": classified.category.value},
        )
        self.catalog.record_failure(
            run_id, stage, classified,
            recovered=False,
            recovery_duration=time.time() - stage_t0,
        )
        self._log_recovery(run_id, stage, "failed", retry_result.attempts)

        return StageRecoveryResult(
            stage=stage,
            run_id=run_id,
            action="failed",
            attempts=retry_result.attempts,
            retry_result=retry_result,
            classified=classified,
            duration=time.time() - stage_t0,
        )

    # ── Rollback-and-retry sub-flow ────────────────────────────────

    async def _rollback_and_retry(
        self,
        run_id: str,
        stage: str,
        func: Callable,
        args: tuple,
        kwargs: dict,
        classified: ClassifiedFailure,
        first_retry: RetryResult,
        stage_t0: float,
    ) -> Optional[StageRecoveryResult]:
        """
        Execute rollback → then one more retry attempt.
        Returns StageRecoveryResult if recovery succeeded, else None.
        """
        logger.info(
            f"[{run_id}] Attempting rollback-and-retry for stage '{stage}'"
        )

        # Build and execute rollback plan
        plan = self.rollback.create_plan(run_id, stage, classified)
        rollback_result = await self.rollback.execute_plan(plan)

        if not rollback_result.get("success", False):
            logger.error(
                f"[{run_id}] Rollback for '{stage}' failed — "
                f"cannot retry"
            )
            return None  # caller will handle abort/skip

        # ── One more retry after rollback ──
        logger.info(
            f"[{run_id}] Rollback succeeded — retrying stage '{stage}'"
        )

        try:
            result = await func(*args, **kwargs)

            # Success after rollback+retry
            self.checkpoint.complete_stage(
                run_id, stage, output_data=result
            )
            self.catalog.record_failure(
                run_id, stage, classified,
                recovered=True,
                recovery_duration=time.time() - stage_t0,
            )
            self._log_recovery(
                run_id, stage, "rollback_retry_success",
                first_retry.attempts + 1,
            )

            return StageRecoveryResult(
                stage=stage,
                run_id=run_id,
                action="recovered",
                result=result,
                attempts=first_retry.attempts + 1,
                retry_result=first_retry,
                rollback_result=rollback_result,
                classified=classified,
                duration=time.time() - stage_t0,
            )

        except Exception as e:
            logger.error(
                f"[{run_id}] Post-rollback retry for '{stage}' also failed: {e}"
            )
            return None

    # ── Full pipeline execution ────────────────────────────────────

    async def execute_pipeline(
        self,
        run_id: str,
        stage_funcs: Dict[str, Callable[..., Coroutine]],
        stage_args: Optional[Dict[str, tuple]] = None,
        stage_kwargs: Optional[Dict[str, dict]] = None,
        stage_order: Optional[List[str]] = None,
        resume_from: Optional[str] = None,
    ) -> RunRecoveryResult:
        """
        Execute a full pipeline with per-stage recovery.

        stage_funcs: {"crawl": _stage_crawl, "validate": _stage_validate, ...}
        Stage fail on non-critical stage → skip, continue.
        Stage fail on critical stage → stop pipeline, return partial.
        """
        order = stage_order or ["crawl", "validate", "score", "explain"]
        stage_args = stage_args or {}
        stage_kwargs = stage_kwargs or {}

        self._run_start_times[run_id] = time.time()

        run_result = RunRecoveryResult(run_id=run_id)

        # Resume from checkpoint if requested
        if resume_from:
            resume_point = self.checkpoint.get_resume_point(run_id)
            if resume_point and resume_point in order:
                idx = order.index(resume_point)
                order = order[idx:]
                logger.info(
                    f"[{run_id}] Resuming pipeline from stage '{resume_point}'"
                )

        pipeline_data: Dict[str, Any] = {}  # pass data between stages

        for stage in order:
            func = stage_funcs.get(stage)
            if not func:
                logger.warning(f"[{run_id}] No function for stage '{stage}' — skipping")
                continue

            # Prepare args — pass previous stage output as input
            args = stage_args.get(stage, ())
            kwargs = dict(stage_kwargs.get(stage, {}))

            stage_result = await self.execute_stage(
                run_id, stage, func, *args,
                input_data=pipeline_data.get(stage),
                **kwargs,
            )

            run_result.stages[stage] = stage_result

            if stage_result.action in ("recovered", "skipped"):
                run_result.recovery_events += 1

            if stage_result.success:
                # Pass output to next stage
                pipeline_data[stage] = stage_result.result
            else:
                # Critical stage failed — stop pipeline
                logger.error(
                    f"[{run_id}] Critical stage '{stage}' failed — "
                    f"pipeline stopped"
                )
                run_result.status = "partial" if run_result.completed_stages else "failed"
                break

        if not run_result.failed_stages:
            run_result.status = "completed"
        elif run_result.completed_stages and run_result.status == "running":
            run_result.status = "partial"

        run_result.total_duration = time.time() - self._run_start_times.get(run_id, time.time())

        # Finalize checkpoint
        self.checkpoint.finalize_run(run_id, status=run_result.status)

        return run_result

    # ── Time budget ────────────────────────────────────────────────

    def _check_time_budget(self, run_id: str) -> bool:
        """Check if we're still within the 15-minute recovery budget."""
        start = self._run_start_times.get(run_id)
        if not start:
            self._run_start_times[run_id] = time.time()
            return True
        elapsed = time.time() - start
        return elapsed < MAX_RUN_RECOVERY_SECONDS

    # ── Recovery log ───────────────────────────────────────────────

    def _log_recovery(
        self, run_id: str, stage: str, action: str, attempts: int
    ) -> None:
        self._recovery_log.append({
            "run_id": run_id,
            "stage": stage,
            "action": action,
            "attempts": attempts,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if len(self._recovery_log) > 300:
            self._recovery_log = self._recovery_log[-300:]

    def get_recovery_log(
        self, run_id: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        results = self._recovery_log
        if run_id:
            results = [r for r in results if r["run_id"] == run_id]
        return results[-limit:]

    # ── Stats / Dashboard ──────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        return {
            "catalog": self.catalog.get_stats(),
            "retry": self.retry.get_retry_stats(),
            "rollback": self.rollback.get_stats(),
            "recovery_log_size": len(self._recovery_log),
        }

    def get_failure_report(self) -> Dict[str, Any]:
        """Comprehensive failure report: catalog entries + history + stats."""
        return {
            "catalog_entries": len(self.catalog.list_entries()),
            "failure_categories": [c.value for c in FailureCategory],
            "recovery_strategies": [s.value for s in RecoveryStrategy],
            "history": self.catalog.get_history(limit=20),
            "stats": self.get_stats(),
            "stage_criticality": dict(STAGE_CRITICALITY),
        }

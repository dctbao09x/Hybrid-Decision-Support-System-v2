"""
Stage Rollback — Failure-aware partial rollback with validation.
================================================================
Enhances the base RollbackManager with:

  • Failure-type-aware rollback strategies
  • Partial rollback (only affected stages, not entire run)
  • Post-rollback validation (health check after rollback)
  • Rollback scripts: named, composable, auditable
  • Safe data preservation (never delete last-known-good data)
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from backend.ops.recovery.failure_catalog import (
    ClassifiedFailure,
    FailureCategory,
    RecoveryStrategy,
)

logger = logging.getLogger("ops.recovery.rollback")


# ── Rollback Action ────────────────────────────────────────────────────

@dataclass
class RollbackStep:
    """A single atomic rollback action."""
    name: str
    action_type: str   # revert_data | clear_checkpoint | restore_config | cleanup_resource | custom
    target: str        # stage name or file path
    description: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    executed: bool = False
    success: bool = False
    error: Optional[str] = None
    duration: float = 0.0
    timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "action_type": self.action_type,
            "target": self.target,
            "description": self.description,
            "executed": self.executed,
            "success": self.success,
            "error": self.error,
            "duration": self.duration,
            "timestamp": self.timestamp,
        }


# ── Rollback Plan ──────────────────────────────────────────────────────

@dataclass
class RollbackPlan:
    """Ordered set of rollback steps for a failure scenario."""
    run_id: str
    failed_stage: str
    reason: str
    failure_category: str
    recovery_strategy: str
    steps: List[RollbackStep] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    executed: bool = False
    success: bool = False
    total_duration: float = 0.0

    def add_step(self, step: RollbackStep) -> None:
        self.steps.append(step)

    @property
    def steps_succeeded(self) -> int:
        return sum(1 for s in self.steps if s.success)

    @property
    def steps_failed(self) -> int:
        return sum(1 for s in self.steps if s.executed and not s.success)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "failed_stage": self.failed_stage,
            "reason": self.reason,
            "failure_category": self.failure_category,
            "recovery_strategy": self.recovery_strategy,
            "created_at": self.created_at,
            "executed": self.executed,
            "success": self.success,
            "total_duration": round(self.total_duration, 2),
            "steps_total": len(self.steps),
            "steps_succeeded": self.steps_succeeded,
            "steps_failed": self.steps_failed,
            "steps": [s.to_dict() for s in self.steps],
        }


# ═══════════════════════════════════════════════════════════════════════
#  StageRollbackManager
# ═══════════════════════════════════════════════════════════════════════

ALL_STAGES = ["crawl", "validate", "score", "explain"]


class StageRollbackManager:
    """
    Failure-aware rollback manager.

    Rollback strategies by failure category:
      TRANSIENT  → no rollback needed, just retry
      DATA       → rollback affected stage outputs, preserve inputs
      CONFIG     → restore last-known-good config, abort
      RESOURCE   → cleanup leaked resources, rollback affected stage
      EXTERNAL   → rollback crawl data for the failed source, skip or retry
      INTERNAL   → full rollback to last checkpoint, abort
    """

    def __init__(
        self,
        checkpoint_dir: Optional[Path] = None,
        data_dir: Optional[Path] = None,
        log_dir: Optional[Path] = None,
    ) -> None:
        self.checkpoint_dir = checkpoint_dir or Path("backend/data/checkpoints")
        self.data_dir = data_dir or Path("backend/data/market")
        self.log_dir = log_dir or Path("backend/data/rollback_log")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._custom_handlers: Dict[str, Callable] = {}
        self._history: List[Dict[str, Any]] = []

    # ── Plan creation ──────────────────────────────────────────────

    def create_plan(
        self,
        run_id: str,
        failed_stage: str,
        classified: ClassifiedFailure,
    ) -> RollbackPlan:
        """
        Create a failure-aware rollback plan.

        The plan depends on the failure category:
          • TRANSIENT  → empty plan (retry only, no rollback)
          • DATA       → rollback failed stage + downstream outputs
          • RESOURCE   → cleanup resources + rollback failed stage
          • EXTERNAL   → rollback failed stage output only
          • CONFIG     → restore config + abort
          • INTERNAL   → full rollback of all stages from failed onwards
        """
        plan = RollbackPlan(
            run_id=run_id,
            failed_stage=failed_stage,
            reason=f"{classified.category.value}: {str(classified.error)[:200]}",
            failure_category=classified.category.value,
            recovery_strategy=classified.recovery_strategy.value,
        )

        category = classified.category
        strategy = classified.recovery_strategy

        # ── TRANSIENT — no rollback needed ──
        if category == FailureCategory.TRANSIENT:
            logger.info(
                f"[{run_id}] Transient failure in '{failed_stage}' — "
                f"no rollback needed"
            )
            return plan

        # ── RESOURCE — cleanup first ──
        if category == FailureCategory.RESOURCE:
            plan.add_step(RollbackStep(
                name="cleanup_browsers",
                action_type="cleanup_resource",
                target=failed_stage,
                description="Kill orphan browser processes and clear temp files",
                metadata={"resource_type": "browser"},
            ))
            plan.add_step(RollbackStep(
                name="gc_collect",
                action_type="cleanup_resource",
                target=failed_stage,
                description="Force garbage collection to free memory",
                metadata={"resource_type": "memory"},
            ))

        # ── Build rollback steps based on strategy ──
        if strategy in (RecoveryStrategy.ROLLBACK_AND_RETRY, RecoveryStrategy.ABORT):
            self._add_stage_rollback_steps(plan, run_id, failed_stage)

        if strategy == RecoveryStrategy.SKIP_STAGE:
            plan.add_step(RollbackStep(
                name=f"clear_{failed_stage}_output",
                action_type="revert_data",
                target=failed_stage,
                description=f"Clear output data from skipped stage '{failed_stage}'",
                metadata={"run_id": run_id, "stage": failed_stage},
            ))

        # ── CONFIG — restore last config ──
        if category == FailureCategory.CONFIG:
            plan.add_step(RollbackStep(
                name="restore_config",
                action_type="restore_config",
                target="config",
                description="Restore last-known-good configuration",
                metadata={"run_id": run_id},
            ))

        return plan

    def _add_stage_rollback_steps(
        self, plan: RollbackPlan, run_id: str, failed_stage: str
    ) -> None:
        """Add steps to rollback the failed stage and all downstream."""
        try:
            idx = ALL_STAGES.index(failed_stage)
        except ValueError:
            return

        # Rollback from failed stage onwards (downstream)
        for stage in ALL_STAGES[idx:]:
            plan.add_step(RollbackStep(
                name=f"revert_{stage}_data",
                action_type="revert_data",
                target=stage,
                description=f"Remove output data from '{stage}' stage",
                metadata={"run_id": run_id, "stage": stage},
            ))
            plan.add_step(RollbackStep(
                name=f"clear_{stage}_checkpoint",
                action_type="clear_checkpoint",
                target=stage,
                description=f"Clear checkpoint for '{stage}' stage",
                metadata={
                    "checkpoint_path": str(
                        self.checkpoint_dir / run_id / f"{stage}.json"
                    ),
                },
            ))

    # ── Plan execution ─────────────────────────────────────────────

    async def execute_plan(
        self,
        plan: RollbackPlan,
        validate_after: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute a rollback plan step-by-step.

        Returns a summary of what succeeded/failed.
        """
        t0 = time.time()
        results: Dict[str, Any] = {
            "run_id": plan.run_id,
            "success": True,
            "steps_executed": 0,
            "steps_succeeded": 0,
            "steps_failed": 0,
            "errors": [],
        }

        for step in plan.steps:
            step_t0 = time.time()
            try:
                await self._execute_step(step)
                step.executed = True
                step.success = True
                step.timestamp = datetime.now(timezone.utc).isoformat()
                step.duration = round(time.time() - step_t0, 3)
                results["steps_succeeded"] += 1

                logger.debug(
                    f"[{plan.run_id}] Rollback step '{step.name}' OK "
                    f"({step.duration:.2f}s)"
                )

            except Exception as e:
                step.executed = True
                step.success = False
                step.error = str(e)
                step.timestamp = datetime.now(timezone.utc).isoformat()
                step.duration = round(time.time() - step_t0, 3)
                results["steps_failed"] += 1
                results["errors"].append(f"{step.name}: {e}")
                results["success"] = False

                logger.error(
                    f"[{plan.run_id}] Rollback step '{step.name}' FAILED: {e}"
                )

            results["steps_executed"] += 1

        plan.executed = True
        plan.success = results["success"]
        plan.total_duration = round(time.time() - t0, 2)

        # ── Post-rollback validation ──
        if validate_after:
            validation = await self._validate_rollback(plan)
            results["validation"] = validation
            if not validation.get("healthy", True):
                results["success"] = False
                logger.warning(
                    f"[{plan.run_id}] Post-rollback validation FAILED"
                )

        # ── Persist rollback log ──
        self._save_log(plan)
        results["duration"] = plan.total_duration

        # History
        self._history.append(plan.to_dict())
        if len(self._history) > 100:
            self._history = self._history[-100:]

        return results

    # ── Step executors ─────────────────────────────────────────────

    async def _execute_step(self, step: RollbackStep) -> None:
        """Route a step to its handler."""
        if step.action_type == "revert_data":
            await self._revert_data(step)
        elif step.action_type == "clear_checkpoint":
            await self._clear_checkpoint(step)
        elif step.action_type == "restore_config":
            await self._restore_config(step)
        elif step.action_type == "cleanup_resource":
            await self._cleanup_resource(step)
        elif step.action_type == "custom":
            handler = self._custom_handlers.get(step.name)
            if handler:
                await handler(step)
            else:
                logger.warning(f"No handler for custom step '{step.name}'")
        else:
            logger.warning(f"Unknown action type: {step.action_type}")

    async def _revert_data(self, step: RollbackStep) -> None:
        """Remove stage output data."""
        run_id = step.metadata.get("run_id", "")
        stage = step.metadata.get("stage", "")

        # Remove artifact directory
        artifact_dir = self.checkpoint_dir / run_id / f"{stage}_data"
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir, ignore_errors=True)
            logger.debug(f"Removed artifact dir: {artifact_dir}")

    async def _clear_checkpoint(self, step: RollbackStep) -> None:
        """Clear a stage checkpoint file."""
        cp_path = Path(step.metadata.get("checkpoint_path", ""))
        if cp_path.exists():
            cp_path.unlink()
            logger.debug(f"Cleared checkpoint: {cp_path}")

    async def _restore_config(self, step: RollbackStep) -> None:
        """Restore config from backup."""
        # Try to find latest config backup
        backup_dir = Path("backend/data/backups/config")
        if backup_dir.exists():
            backups = sorted(backup_dir.glob("*.yaml"), reverse=True)
            if backups:
                target = Path("config/data_pipeline.yaml")
                shutil.copy2(backups[0], target)
                logger.info(f"Restored config from {backups[0]}")
                return
        logger.debug("No config backup found — skipping restore")

    async def _cleanup_resource(self, step: RollbackStep) -> None:
        """Cleanup leaked resources."""
        resource_type = step.metadata.get("resource_type", "")

        if resource_type == "memory":
            import gc
            gc.collect()
            logger.debug("Forced garbage collection")

        elif resource_type == "browser":
            # Kill orphan chromium processes (best-effort)
            try:
                import subprocess
                subprocess.run(
                    ["taskkill", "/F", "/IM", "chromium.exe"],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass  # Non-Windows or no orphans

    # ── Post-rollback validation ───────────────────────────────────

    async def _validate_rollback(self, plan: RollbackPlan) -> Dict[str, Any]:
        """
        Verify system health after rollback.
        Checks: data directory exists, checkpoint consistency, disk space.
        """
        checks: Dict[str, bool] = {}

        # 1. Data directory accessible
        checks["data_dir_exists"] = self.data_dir.exists()

        # 2. Rolled-back checkpoints are actually gone
        for step in plan.steps:
            if step.action_type == "clear_checkpoint":
                cp_path = Path(step.metadata.get("checkpoint_path", ""))
                checks[f"checkpoint_cleared_{step.target}"] = not cp_path.exists()

        # 3. Disk space > 100MB free
        try:
            import shutil as sh
            usage = sh.disk_usage(str(self.data_dir))
            free_mb = usage.free / (1024 * 1024)
            checks["disk_space_ok"] = free_mb > 100
        except Exception:
            checks["disk_space_ok"] = True  # can't check, assume ok

        healthy = all(checks.values())
        return {"healthy": healthy, "checks": checks}

    # ── Custom step registration ───────────────────────────────────

    def register_handler(
        self, name: str, handler: Callable
    ) -> None:
        """Register a custom rollback step handler."""
        self._custom_handlers[name] = handler

    # ── History & logging ──────────────────────────────────────────

    def _save_log(self, plan: RollbackPlan) -> None:
        """Persist rollback plan to log directory."""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            log_path = self.log_dir / f"rollback_{plan.run_id}_{ts}.json"
            log_path.write_text(json.dumps(plan.to_dict(), indent=2, default=str))
        except Exception as e:
            logger.warning(f"Failed to save rollback log: {e}")

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        if not self._history:
            return {
                "total_rollbacks": 0,
                "success_rate": 1.0,
                "by_category": {},
            }

        by_cat: Dict[str, int] = {}
        successes = 0
        for r in self._history:
            cat = r.get("failure_category", "unknown")
            by_cat[cat] = by_cat.get(cat, 0) + 1
            if r.get("success"):
                successes += 1

        total = len(self._history)
        return {
            "total_rollbacks": total,
            "success_rate": round(successes / total, 4) if total else 1.0,
            "by_category": by_cat,
        }

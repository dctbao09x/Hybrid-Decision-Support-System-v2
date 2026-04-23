# backend/ops/orchestration/rollback.py
"""
Rollback Manager for partial and full pipeline rollback.

Supports:
- Rolling back to a specific checkpoint
- Reverting dataset versions
- Stage-level partial rollback
- Automatic rollback on critical failures
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.rollback")


class RollbackAction:
    """Represents a single rollback action."""

    def __init__(
        self,
        action_type: str,
        target: str,
        description: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.action_type = action_type  # "revert_data", "restore_config", "clear_cache"
        self.target = target
        self.description = description
        self.metadata = metadata or {}
        self.executed = False
        self.timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type,
            "target": self.target,
            "description": self.description,
            "executed": self.executed,
            "timestamp": self.timestamp,
        }


class RollbackPlan:
    """Plan for rolling back pipeline state."""

    def __init__(self, run_id: str, reason: str):
        self.run_id = run_id
        self.reason = reason
        self.actions: List[RollbackAction] = []
        self.created_at = datetime.now().isoformat()

    def add_action(self, action: RollbackAction) -> None:
        self.actions.append(action)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "reason": self.reason,
            "created_at": self.created_at,
            "actions": [a.to_dict() for a in self.actions],
        }


class RollbackManager:
    """
    Manages rollback operations for pipeline runs.

    Integration points:
    - CheckpointManager: for state recovery
    - VersionManager: for dataset version reversal
    - ConfigVersioning: for config state recovery
    """

    def __init__(
        self,
        checkpoint_dir: Optional[Path] = None,
        data_dir: Optional[Path] = None,
        rollback_log_dir: Optional[Path] = None,
    ):
        self.checkpoint_dir = checkpoint_dir or Path("backend/data/checkpoints")
        self.data_dir = data_dir or Path("backend/data/market")
        self.rollback_log_dir = rollback_log_dir or Path("backend/data/rollback_log")
        self.rollback_log_dir.mkdir(parents=True, exist_ok=True)

    async def create_rollback_plan(
        self,
        run_id: str,
        target_stage: str,
        reason: str = "manual",
    ) -> RollbackPlan:
        """
        Create a rollback plan to revert to a specific stage's checkpoint.

        Args:
            run_id: The pipeline run to rollback
            target_stage: Roll back to this stage's state
            reason: Why rollback is needed
        """
        plan = RollbackPlan(run_id=run_id, reason=reason)
        stages = ["crawl", "validate", "score", "explain"]

        try:
            target_idx = stages.index(target_stage)
        except ValueError:
            raise ValueError(f"Invalid stage: {target_stage}")

        # Build actions for each stage after the target
        for stage in stages[target_idx + 1:]:
            # Revert output data
            plan.add_action(
                RollbackAction(
                    action_type="revert_data",
                    target=stage,
                    description=f"Remove output data from '{stage}' stage",
                    metadata={"stage": stage, "run_id": run_id},
                )
            )

            # Clear stage checkpoint
            plan.add_action(
                RollbackAction(
                    action_type="clear_checkpoint",
                    target=stage,
                    description=f"Clear checkpoint for '{stage}' stage",
                    metadata={"checkpoint_path": str(self.checkpoint_dir / run_id / f"{stage}.json")},
                )
            )

        logger.info(f"Rollback plan created: {run_id} → {target_stage} ({len(plan.actions)} actions)")
        return plan

    async def execute_rollback(self, plan: RollbackPlan) -> Dict[str, Any]:
        """
        Execute a rollback plan.

        Returns:
            Summary of executed actions with success/failure counts
        """
        results = {"success": 0, "failed": 0, "errors": []}
        logger.warning(f"Executing rollback for run {plan.run_id}: {plan.reason}")

        for action in plan.actions:
            try:
                if action.action_type == "revert_data":
                    await self._revert_data(action)
                elif action.action_type == "clear_checkpoint":
                    await self._clear_checkpoint(action)
                elif action.action_type == "restore_config":
                    await self._restore_config(action)

                action.executed = True
                action.timestamp = datetime.now().isoformat()
                results["success"] += 1

            except Exception as e:
                action.executed = False
                results["failed"] += 1
                results["errors"].append(f"{action.target}: {str(e)}")
                logger.exception(f"Rollback action failed: {action.target}")

        # Save rollback log
        log_path = self.rollback_log_dir / f"rollback_{plan.run_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        log_path.write_text(json.dumps(plan.to_dict(), indent=2))

        logger.info(f"Rollback complete: {results['success']} ok, {results['failed']} failed")
        return results

    async def auto_rollback_on_failure(
        self,
        run_id: str,
        failed_stage: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Automatic rollback when a critical stage fails.
        Rolls back to the last successful stage.
        """
        stages = ["crawl", "validate", "score", "explain"]
        try:
            idx = stages.index(failed_stage)
        except ValueError:
            return None

        if idx == 0:
            logger.warning("First stage failed, nothing to rollback")
            return None

        target = stages[idx - 1]
        plan = await self.create_rollback_plan(
            run_id=run_id,
            target_stage=target,
            reason=f"Auto-rollback: '{failed_stage}' failed",
        )
        return await self.execute_rollback(plan)

    # ── Internal Actions ────────────────────────────────────

    async def _revert_data(self, action: RollbackAction) -> None:
        """Remove output data produced by a stage."""
        stage = action.metadata.get("stage", "")
        run_id = action.metadata.get("run_id", "")

        # Remove stage-specific output artifacts
        artifact_dir = self.checkpoint_dir / run_id / f"{stage}_data"
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir, ignore_errors=True)
            logger.info(f"Reverted data: {artifact_dir}")

    async def _clear_checkpoint(self, action: RollbackAction) -> None:
        """Remove a checkpoint file."""
        cp_path = Path(action.metadata.get("checkpoint_path", ""))
        if cp_path.exists():
            cp_path.unlink()
            logger.info(f"Cleared checkpoint: {cp_path}")

    async def _restore_config(self, action: RollbackAction) -> None:
        """Restore a config from a snapshot."""
        source = Path(action.metadata.get("source", ""))
        target = Path(action.metadata.get("target", ""))
        if source.exists():
            shutil.copy2(source, target)
            logger.info(f"Restored config: {source} → {target}")

    # ── History ─────────────────────────────────────────────

    async def list_rollbacks(self) -> List[Dict[str, Any]]:
        """List all rollback logs."""
        logs = []
        if not self.rollback_log_dir.exists():
            return logs

        for f in sorted(self.rollback_log_dir.glob("rollback_*.json"), reverse=True):
            try:
                logs.append(json.loads(f.read_text()))
            except Exception:
                continue
        return logs

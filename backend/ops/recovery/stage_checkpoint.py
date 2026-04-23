"""
Stage Checkpoint — Enhanced checkpoint with stage-level data preservation.
=========================================================================
Extends the base CheckpointManager with:

  • Partial stage data saving (incremental within a stage)
  • Stage input/output snapshots for rollback
  • Safe-rerun detection (idempotency guard)
  • Checkpoint-based recovery point computation
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.recovery.checkpoint")


@dataclass
class StageCheckpoint:
    """Snapshot of a stage's execution state."""
    run_id: str
    stage: str
    status: str              # pending | running | completed | failed | skipped
    started_at: float = 0.0
    finished_at: float = 0.0
    input_hash: str = ""     # SHA-256 of serialized input
    output_hash: str = ""    # SHA-256 of serialized output
    records_in: int = 0
    records_out: int = 0
    attempt: int = 1         # which retry attempt this is
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        if self.finished_at and self.started_at:
            return round(self.finished_at - self.started_at, 3)
        return 0.0

    @property
    def is_complete(self) -> bool:
        return self.status == "completed"

    @property
    def is_failed(self) -> bool:
        return self.status == "failed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "stage": self.stage,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": self.duration,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "records_in": self.records_in,
            "records_out": self.records_out,
            "attempt": self.attempt,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class RunCheckpoint:
    """Full checkpoint state for a pipeline run."""
    run_id: str
    stages: Dict[str, StageCheckpoint] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = ""
    status: str = "running"  # running | completed | failed | partial

    def set_stage(self, cp: StageCheckpoint) -> None:
        self.stages[cp.stage] = cp
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def get_stage(self, stage: str) -> Optional[StageCheckpoint]:
        return self.stages.get(stage)

    @property
    def completed_stages(self) -> List[str]:
        return [s for s, cp in self.stages.items() if cp.is_complete]

    @property
    def failed_stages(self) -> List[str]:
        return [s for s, cp in self.stages.items() if cp.is_failed]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_stages": self.completed_stages,
            "failed_stages": self.failed_stages,
            "stages": {k: v.to_dict() for k, v in self.stages.items()},
        }


# ═══════════════════════════════════════════════════════════════════════
#  RecoveryCheckpointManager
# ═══════════════════════════════════════════════════════════════════════

class RecoveryCheckpointManager:
    """
    Manages run-level and stage-level checkpoints for recovery.

    Adds to the base CheckpointManager:
      • Input/output hashing for idempotency detection
      • Stage-level status tracking (pending→running→completed/failed)
      • Safe-rerun detection: skip stages whose input hasn't changed
      • Recovery point computation: given a run, figure out where to resume
    """

    ALL_STAGES = ["crawl", "validate", "score", "explain"]

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = base_dir or Path("backend/data/recovery_checkpoints")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._runs: Dict[str, RunCheckpoint] = {}

    # ── Stage lifecycle ────────────────────────────────────────────

    def begin_stage(
        self,
        run_id: str,
        stage: str,
        input_data: Any = None,
        attempt: int = 1,
    ) -> StageCheckpoint:
        """Mark a stage as running. Returns the StageCheckpoint."""
        run_cp = self._ensure_run(run_id)

        cp = StageCheckpoint(
            run_id=run_id,
            stage=stage,
            status="running",
            started_at=time.time(),
            input_hash=self._hash_data(input_data) if input_data else "",
            attempt=attempt,
        )
        if input_data:
            cp.records_in = self._count_records(input_data)

        run_cp.set_stage(cp)
        self._persist_run(run_id)
        return cp

    def complete_stage(
        self,
        run_id: str,
        stage: str,
        output_data: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StageCheckpoint:
        """Mark a stage as completed. Saves output hash."""
        run_cp = self._ensure_run(run_id)
        cp = run_cp.get_stage(stage)

        if cp is None:
            cp = StageCheckpoint(run_id=run_id, stage=stage, status="completed")

        cp.status = "completed"
        cp.finished_at = time.time()
        if output_data:
            cp.output_hash = self._hash_data(output_data)
            cp.records_out = self._count_records(output_data)
        if metadata:
            cp.metadata.update(metadata)

        run_cp.set_stage(cp)
        self._persist_run(run_id)
        return cp

    def fail_stage(
        self,
        run_id: str,
        stage: str,
        error: Exception,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StageCheckpoint:
        """Mark a stage as failed."""
        run_cp = self._ensure_run(run_id)
        cp = run_cp.get_stage(stage)

        if cp is None:
            cp = StageCheckpoint(run_id=run_id, stage=stage, status="failed")

        cp.status = "failed"
        cp.finished_at = time.time()
        cp.error = f"{type(error).__name__}: {str(error)[:500]}"
        if metadata:
            cp.metadata.update(metadata)

        run_cp.set_stage(cp)
        self._persist_run(run_id)
        return cp

    def skip_stage(self, run_id: str, stage: str, reason: str = "") -> StageCheckpoint:
        """Mark a stage as skipped (non-critical or recovery skip)."""
        run_cp = self._ensure_run(run_id)
        cp = StageCheckpoint(
            run_id=run_id,
            stage=stage,
            status="skipped",
            finished_at=time.time(),
            metadata={"skip_reason": reason},
        )
        run_cp.set_stage(cp)
        self._persist_run(run_id)
        return cp

    # ── Recovery queries ───────────────────────────────────────────

    def get_resume_point(self, run_id: str) -> Optional[str]:
        """Return the stage name to resume from (first non-completed)."""
        run_cp = self._runs.get(run_id)
        if not run_cp:
            run_cp = self._load_run(run_id)
        if not run_cp:
            return self.ALL_STAGES[0]

        for stage in self.ALL_STAGES:
            cp = run_cp.get_stage(stage)
            if cp is None or not cp.is_complete:
                return stage
        return None  # all completed

    def is_safe_rerun(
        self, run_id: str, stage: str, input_data: Any = None
    ) -> bool:
        """
        Check if re-running a stage is safe (idempotent).
        Safe if: stage already completed with same input hash.
        """
        run_cp = self._runs.get(run_id) or self._load_run(run_id)
        if not run_cp:
            return True  # no previous run, safe to run

        cp = run_cp.get_stage(stage)
        if cp is None:
            return True  # never ran, safe

        if not cp.is_complete:
            return True  # didn't finish, safe to retry

        if input_data is None:
            return True  # can't compare, allow rerun

        new_hash = self._hash_data(input_data)
        if new_hash == cp.input_hash:
            logger.info(
                f"[{run_id}] Stage '{stage}' safe-rerun: input unchanged, "
                f"skipping (idempotent)"
            )
            return False  # same input → skip, already done

        return True  # input changed, needs rerun

    def get_run_status(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Full status of a run's checkpoints."""
        run_cp = self._runs.get(run_id) or self._load_run(run_id)
        if not run_cp:
            return None
        return run_cp.to_dict()

    def get_stage_attempt(self, run_id: str, stage: str) -> int:
        """How many times has this stage been attempted?"""
        run_cp = self._runs.get(run_id) or self._load_run(run_id)
        if not run_cp:
            return 0
        cp = run_cp.get_stage(stage)
        return cp.attempt if cp else 0

    # ── Run finalization ───────────────────────────────────────────

    def finalize_run(self, run_id: str, status: str = "completed") -> None:
        """Mark the run as complete/failed/partial."""
        run_cp = self._ensure_run(run_id)
        run_cp.status = status
        run_cp.updated_at = datetime.now(timezone.utc).isoformat()
        self._persist_run(run_id)

    # ── Persistence ────────────────────────────────────────────────

    def _ensure_run(self, run_id: str) -> RunCheckpoint:
        if run_id not in self._runs:
            loaded = self._load_run(run_id)
            if loaded:
                self._runs[run_id] = loaded
            else:
                self._runs[run_id] = RunCheckpoint(run_id=run_id)
        return self._runs[run_id]

    def _persist_run(self, run_id: str) -> None:
        run_cp = self._runs.get(run_id)
        if not run_cp:
            return
        run_dir = self.base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "recovery_state.json"
        path.write_text(json.dumps(run_cp.to_dict(), indent=2, default=str))

    def _load_run(self, run_id: str) -> Optional[RunCheckpoint]:
        path = self.base_dir / run_id / "recovery_state.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            run_cp = RunCheckpoint(
                run_id=data["run_id"],
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
                status=data.get("status", "unknown"),
            )
            for stage_name, stage_data in data.get("stages", {}).items():
                cp = StageCheckpoint(
                    run_id=run_id,
                    stage=stage_name,
                    status=stage_data.get("status", "unknown"),
                    started_at=stage_data.get("started_at", 0),
                    finished_at=stage_data.get("finished_at", 0),
                    input_hash=stage_data.get("input_hash", ""),
                    output_hash=stage_data.get("output_hash", ""),
                    records_in=stage_data.get("records_in", 0),
                    records_out=stage_data.get("records_out", 0),
                    attempt=stage_data.get("attempt", 1),
                    error=stage_data.get("error"),
                    metadata=stage_data.get("metadata", {}),
                )
                run_cp.set_stage(cp)
            return run_cp
        except Exception as e:
            logger.warning(f"Failed to load checkpoint for {run_id}: {e}")
            return None

    # ── Hashing helpers ────────────────────────────────────────────

    @staticmethod
    def _hash_data(data: Any) -> str:
        """Deterministic SHA-256 hash of serializable data."""
        try:
            if isinstance(data, (dict, list)):
                raw = json.dumps(data, sort_keys=True, default=str)
            else:
                raw = str(data)
            return hashlib.sha256(raw.encode()).hexdigest()[:16]
        except Exception:
            return ""

    @staticmethod
    def _count_records(data: Any) -> int:
        """Count records in data (list length or dict key count)."""
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            return data.get("total_records", len(data))
        return 0

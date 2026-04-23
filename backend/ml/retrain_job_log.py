# backend/ml/retrain_job_log.py
"""
Retrain Job Log
================

Persistent tracker for retraining jobs.  Every retrain request is
assigned a ``job_id`` and written to ``retrain_jobs.jsonl``.

This module is the single enforcement point for:
  • Preventing concurrent retrain runs (only one RUNNING job at a time)
  • Providing a full audit trail of what triggered each retrain and
    what metrics resulted

Pass criteria: the ``POST /api/v1/ml/retrain`` endpoint calls
``RetrainJobLog.start_job()`` before doing any work; if a job is
already running it raises ``ConflictError`` — ML never runs
uncontrolled in the background.

Schema (one JSON line per job event):
  job_id       – UUID4
  timestamp    – ISO-8601 UTC of this log write
  status       – "pending" | "running" | "completed" | "failed"
  triggered_by – e.g. "manual" | "drift" | "schedule"
  started_at   – ISO-8601 UTC
  completed_at – ISO-8601 UTC or null
  error        – error message if failed
  metrics      – {"accuracy": ..., "precision": ..., "recall": ..., "f1": ...} or null
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ml.retrain_job_log")

_DEFAULT_LOG_PATH = Path("backend/data/logs/retrain_jobs.jsonl")


# ═══════════════════════════════════════════════════════════════════════════════
# Exceptions
# ═══════════════════════════════════════════════════════════════════════════════

class RetrainConflictError(RuntimeError):
    """Raised when a retrain job is already running."""


# ═══════════════════════════════════════════════════════════════════════════════
# Domain object
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RetrainJob:
    job_id:       str
    status:       str                    = "pending"    # pending|running|completed|failed
    triggered_by: str                    = "manual"
    started_at:   str                    = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: Optional[str]          = None
    error:        Optional[str]          = None
    metrics:      Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id":       self.job_id,
            "timestamp":    datetime.now(timezone.utc).isoformat(),
            "status":       self.status,
            "triggered_by": self.triggered_by,
            "started_at":   self.started_at,
            "completed_at": self.completed_at,
            "error":        self.error,
            "metrics":      self.metrics,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RetrainJob":
        return cls(
            job_id       = d.get("job_id", str(uuid.uuid4())),
            status       = d.get("status", "pending"),
            triggered_by = d.get("triggered_by", "manual"),
            started_at   = d.get("started_at", ""),
            completed_at = d.get("completed_at"),
            error        = d.get("error"),
            metrics      = d.get("metrics"),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# RetrainJobLog
# ═══════════════════════════════════════════════════════════════════════════════

class RetrainJobLog:
    """
    Append-only JSONL log of retrain jobs.

    Concurrency control
    -------------------
    ``start_job()`` checks whether any job with status ``running`` is
    currently in the log.  If one is found it raises ``RetrainConflictError``
    instead of starting another job.  This is the enforcement gate that
    prevents ML from running uncontrolled in the background.
    """

    def __init__(self, log_path: Optional[Path] = None):
        self._log_path = Path(log_path) if log_path else _DEFAULT_LOG_PATH
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    # ── writes ───────────────────────────────────────────────────────

    def start_job(self, triggered_by: str = "manual") -> RetrainJob:
        """
        Create a new retrain job in RUNNING state.

        Raises
        ------
        RetrainConflictError
            If another job is already in RUNNING state.
        """
        active = self.get_active_job()
        if active is not None:
            raise RetrainConflictError(
                f"Retrain job {active.job_id!r} is already running "
                f"(started {active.started_at}). Wait for it to finish or "
                "mark it as failed before starting a new run."
            )
        job = RetrainJob(
            job_id       = str(uuid.uuid4()),
            status       = "running",
            triggered_by = triggered_by,
        )
        self._append(job.to_dict())
        logger.info("[RETRAIN] started job %s triggered_by=%s", job.job_id, triggered_by)
        return job

    def complete_job(
        self,
        job_id: str,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> Optional[RetrainJob]:
        """Mark job as completed.  Appends updated record."""
        job = self._get_job(job_id)
        if job is None:
            return None
        job.status       = "completed"
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.metrics      = metrics
        self._append(job.to_dict())
        logger.info("[RETRAIN] completed job %s metrics=%s", job_id, metrics)
        return job

    def fail_job(self, job_id: str, error: str) -> Optional[RetrainJob]:
        """Mark job as failed.  Appends updated record."""
        job = self._get_job(job_id)
        if job is None:
            return None
        job.status       = "failed"
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.error        = error
        self._append(job.to_dict())
        logger.warning("[RETRAIN] failed job %s: %s", job_id, error)
        return job

    # ── reads ────────────────────────────────────────────────────────

    def get_active_job(self) -> Optional[RetrainJob]:
        """Return the currently-running job, or None."""
        # Replay: for each job_id keep last status
        latest: Dict[str, Dict[str, Any]] = {}
        for row in self._iter_rows():
            jid = row.get("job_id", "")
            if jid:
                latest[jid] = row
        for row in latest.values():
            if row.get("status") == "running":
                return RetrainJob.from_dict(row)
        return None

    def list_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the *latest* record per job, sorted newest-first."""
        latest: Dict[str, Dict[str, Any]] = {}
        for row in self._iter_rows():
            jid = row.get("job_id", "")
            if jid:
                latest[jid] = row
        rows = sorted(latest.values(), key=lambda r: r.get("started_at", ""), reverse=True)
        return rows[:limit]

    def count(self) -> int:
        """Count unique job IDs."""
        seen: set = set()
        for row in self._iter_rows():
            jid = row.get("job_id", "")
            if jid:
                seen.add(jid)
        return len(seen)

    # ── private helpers ──────────────────────────────────────────────

    def _append(self, record: Dict[str, Any]) -> None:
        with self._log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _iter_rows(self):
        if not self._log_path.exists():
            return
        for line in self._log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue

    def _get_job(self, job_id: str) -> Optional[RetrainJob]:
        latest_row: Optional[Dict] = None
        for row in self._iter_rows():
            if row.get("job_id") == job_id:
                latest_row = row
        return RetrainJob.from_dict(latest_row) if latest_row else None


# ═══════════════════════════════════════════════════════════════════════════════
# Module singleton
# ═══════════════════════════════════════════════════════════════════════════════

_log: Optional[RetrainJobLog] = None


def get_retrain_job_log(log_path: Optional[Path] = None) -> RetrainJobLog:
    """Return the process-level singleton RetrainJobLog."""
    global _log
    if _log is None:
        _log = RetrainJobLog(log_path)
    return _log

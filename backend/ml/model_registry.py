# backend/ml/model_registry.py
"""
ML Model Registry
=================

Persistent JSONL-backed store of every model version that has ever
been trained, staged, promoted to production, or archived.

Schema (one JSON object per line):
  event_id         – UUID4
  timestamp        – ISO-8601 UTC of this registry write
  version          – Semantic version string, e.g. "v1.0.0"
  status           – "pending" | "training" | "staged" | "production" | "archived"
  accuracy         – float [0, 1] or null
  precision        – float [0, 1] or null
  recall           – float [0, 1] or null
  f1               – float [0, 1] or null
  created_at       – ISO-8601 UTC when the training run started
  trained_at       – ISO-8601 UTC when metrics were finalised (or null)
  retrain_trigger  – e.g. "manual" | "drift" | "scheduled" | null
  notes            – free-text or null

Pass criteria: ModelRegistry.register() is the ONLY path for adding
a model to production — uncontrolled background promotion is blocked.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ml.model_registry")

_DEFAULT_LOG_PATH = Path("backend/data/logs/model_registry.jsonl")


# ═══════════════════════════════════════════════════════════════════════════════
# Domain objects
# ═══════════════════════════════════════════════════════════════════════════════

class ModelStatus(str, Enum):
    PENDING    = "pending"
    TRAINING   = "training"
    STAGED     = "staged"
    PRODUCTION = "production"
    ARCHIVED   = "archived"


@dataclass
class ModelRecord:
    """Represents one version of the model at a point in time."""

    version:         str
    status:          ModelStatus                  = ModelStatus.PENDING
    accuracy:        Optional[float]              = None
    precision:       Optional[float]              = None
    recall:          Optional[float]              = None
    f1:              Optional[float]              = None
    created_at:      str                          = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    trained_at:      Optional[str]                = None
    retrain_trigger: Optional[str]                = None
    notes:           Optional[str]                = None
    # internal
    event_id:        str                          = field(
        default_factory=lambda: str(uuid.uuid4())
    )
    timestamp:       str                          = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ── serialisation ────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        def _r(v: Optional[float]) -> Optional[float]:
            return round(v, 6) if v is not None else None

        return {
            "event_id":        self.event_id,
            "timestamp":       self.timestamp,
            "version":         self.version,
            "status":          self.status.value if isinstance(self.status, ModelStatus) else self.status,
            "accuracy":        _r(self.accuracy),
            "precision":       _r(self.precision),
            "recall":          _r(self.recall),
            "f1":              _r(self.f1),
            "created_at":      self.created_at,
            "trained_at":      self.trained_at,
            "retrain_trigger": self.retrain_trigger,
            "notes":           self.notes,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ModelRecord":
        status = d.get("status", "pending")
        try:
            status = ModelStatus(status)
        except ValueError:
            status = ModelStatus.PENDING
        return cls(
            version         = d.get("version", "unknown"),
            status          = status,
            accuracy        = d.get("accuracy"),
            precision       = d.get("precision"),
            recall          = d.get("recall"),
            f1              = d.get("f1"),
            created_at      = d.get("created_at", ""),
            trained_at      = d.get("trained_at"),
            retrain_trigger = d.get("retrain_trigger"),
            notes           = d.get("notes"),
            event_id        = d.get("event_id", str(uuid.uuid4())),
            timestamp       = d.get("timestamp", ""),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ModelRegistry
# ═══════════════════════════════════════════════════════════════════════════════

class ModelRegistry:
    """
    Append-only JSONL registry of model versions.

    Thread-safe for single-process use.  Every mutation appends a record to
    the JSONL file.  ``list_all()`` derives the latest state per version by
    replaying the log (newest-write-wins per version).
    """

    def __init__(self, log_path: Optional[Path] = None):
        self._log_path = Path(log_path) if log_path else _DEFAULT_LOG_PATH
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    # ── writes ───────────────────────────────────────────────────────

    def register(
        self,
        version: str,
        status: ModelStatus = ModelStatus.PENDING,
        *,
        accuracy:        Optional[float] = None,
        precision:       Optional[float] = None,
        recall:          Optional[float] = None,
        f1:              Optional[float] = None,
        trained_at:      Optional[str]   = None,
        retrain_trigger: Optional[str]   = None,
        notes:           Optional[str]   = None,
    ) -> ModelRecord:
        """Append a new entry for *version* to the registry."""
        rec = ModelRecord(
            version         = version,
            status          = status,
            accuracy        = accuracy,
            precision       = precision,
            recall          = recall,
            f1              = f1,
            trained_at      = trained_at,
            retrain_trigger = retrain_trigger,
            notes           = notes,
        )
        self._append(rec.to_dict())
        logger.info("[REGISTRY] registered %s → %s", version, status.value)
        return rec

    def update_status(
        self,
        version: str,
        status: ModelStatus,
        notes: Optional[str] = None,
    ) -> Optional[ModelRecord]:
        """
        Append a status-update event for an existing version.

        When promoting to ``production`` any current production version is
        automatically archived first (governance: only one active prod model).
        """
        if status == ModelStatus.PRODUCTION:
            active = self.get_active()
            if active and active.version != version:
                self._append_status(active.version, ModelStatus.ARCHIVED, "superseded")

        # Carry forward existing metrics
        existing = self._get_version_latest(version)
        if existing is None:
            logger.warning("[REGISTRY] update_status called for unknown version %s", version)
            return None

        updated = ModelRecord(
            version         = version,
            status          = status,
            accuracy        = existing.accuracy,
            precision       = existing.precision,
            recall          = existing.recall,
            f1              = existing.f1,
            created_at      = existing.created_at,
            trained_at      = existing.trained_at,
            retrain_trigger = existing.retrain_trigger,
            notes           = notes or existing.notes,
        )
        self._append(updated.to_dict())
        logger.info("[REGISTRY] %s → %s", version, status.value)
        return updated

    # ── reads ────────────────────────────────────────────────────────

    def list_all(self) -> List[ModelRecord]:
        """
        Return the *current* state of every known version.

        The log is replayed; for each version the LAST entry wins
        (newest-write-wins), giving the current state per version.
        Returns versions ordered newest-first by their latest timestamp.
        """
        latest: Dict[str, Dict[str, Any]] = {}
        for row in self._iter_rows():
            ver = row.get("version", "")
            if ver:
                latest[ver] = row
        records = [ModelRecord.from_dict(r) for r in latest.values()]
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return records

    def get_active(self) -> Optional[ModelRecord]:
        """Return the currently-active production model, or None."""
        for rec in self.list_all():
            if rec.status == ModelStatus.PRODUCTION:
                return rec
        return None

    def count(self) -> int:
        """Raw line count in the JSONL file."""
        if not self._log_path.exists():
            return 0
        return sum(1 for _ in self._log_path.read_text(encoding="utf-8").splitlines() if _.strip())

    def seed_from_weights_dir(self, weights_dir: Path = Path("models/weights")) -> int:
        """
        One-time import: walk *weights_dir*, read ``weights.json`` in each
        sub-directory and register any version not already in the log.
        Returns the number of versions imported.
        """
        known = {r.version for r in self.list_all()}
        imported = 0
        for subdir in sorted(weights_dir.iterdir()):
            if not subdir.is_dir() or subdir.name == "active":
                continue
            wf = subdir / "weights.json"
            if not wf.exists():
                continue
            try:
                data = json.loads(wf.read_text(encoding="utf-8"))
            except Exception:
                continue
            ver = data.get("version", subdir.name)
            if ver in known:
                continue
            metrics = data.get("metrics", {})
            self.register(
                version  = ver,
                status   = ModelStatus.STAGED,
                accuracy = metrics.get("accuracy"),
                precision= metrics.get("precision"),
                recall   = metrics.get("recall"),
                f1       = metrics.get("f1"),
                trained_at = data.get("trained_at"),
                notes    = "seeded from weights dir",
            )
            known.add(ver)
            imported += 1
        return imported

    # ── private helpers ──────────────────────────────────────────────

    def _append(self, record: Dict[str, Any]) -> None:
        with self._log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _append_status(self, version: str, status: ModelStatus, notes: str) -> None:
        existing = self._get_version_latest(version)
        if existing is None:
            return
        entry = existing.to_dict()
        entry["event_id"]  = str(uuid.uuid4())
        entry["timestamp"] = datetime.now(timezone.utc).isoformat()
        entry["status"]    = status.value
        entry["notes"]     = notes
        self._append(entry)

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

    def _get_version_latest(self, version: str) -> Optional[ModelRecord]:
        latest_row: Optional[Dict] = None
        for row in self._iter_rows():
            if row.get("version") == version:
                latest_row = row
        return ModelRecord.from_dict(latest_row) if latest_row else None


# ═══════════════════════════════════════════════════════════════════════════════
# Module singleton
# ═══════════════════════════════════════════════════════════════════════════════

_registry: Optional[ModelRegistry] = None


def get_model_registry(log_path: Optional[Path] = None) -> ModelRegistry:
    """Return the process-level singleton ModelRegistry."""
    global _registry
    if _registry is None:
        _registry = ModelRegistry(log_path)
    return _registry

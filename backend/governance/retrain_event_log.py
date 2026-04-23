# backend/governance/retrain_event_log.py
"""
Retrain Event Logger — Persistent Append-Only
==============================================

Writes every retraining lifecycle event to:
  backend/data/logs/retrain_event_log.jsonl

Each record is:
  • Appended to a JSONL file (never overwrites)
  • Hash-linked via the shared hash-chain logger

Record schema (JSON):
  {
    "event_id":               str,        -- UUID4
    "timestamp":              str,        -- ISO8601 UTC
    "trigger_source":         str,        -- "dataset_growth" | "time_based" |
                                          --  "performance_degradation" |
                                          --  "weight_drift" | "manual" | "drift_alert"
    "drift_reference":        str|null,   -- event_id of causal drift event
    "dataset_snapshot_hash":  str|null,   -- SHA256 of training dataset at retrain time
    "config_hash":            str|null,   -- SHA256 of RetrainingConfig dict
    "previous_model_version": str|null,
    "new_model_version":      str|null,
    "validation_metrics":     dict,       -- r2, accuracy, rmse, etc.
    "rollback_flag":          bool,       -- True if retrain was rolled back
    "chain_record_hash":      str         -- record_hash from hash_chain_logger
  }

Usage::

    from backend.governance.retrain_event_log import RetrainEventLogger

    logger = RetrainEventLogger()
    logger.append(
        trigger_source="drift_alert",
        drift_reference="some-drift-event-id",
        previous_model_version="v1.2",
        new_model_version="v1.3",
        validation_metrics={"r2": 0.81, "accuracy": 0.87},
    )
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.api.hash_chain_logger import append_record as _chain_append

_log = logging.getLogger("governance.retrain_event_log")

# ── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_LOG_PATH = Path("backend/data/logs/retrain_event_log.jsonl")

# Trigger source labels (mirrors RetrainingTrigger constants)
TRIGGER_DATASET_GROWTH          = "dataset_growth"
TRIGGER_TIME_BASED              = "time_based"
TRIGGER_PERFORMANCE_DEGRADATION = "performance_degradation"
TRIGGER_WEIGHT_DRIFT            = "weight_drift"
TRIGGER_MANUAL                  = "manual"
TRIGGER_DRIFT_ALERT             = "drift_alert"


# ── Schema helper ────────────────────────────────────────────────────────────

def _make_event(
    trigger_source: str,
    previous_model_version: Optional[str],
    new_model_version: Optional[str],
    validation_metrics: Dict[str, Any],
    rollback_flag: bool,
    drift_reference: Optional[str],
    dataset_snapshot_hash: Optional[str],
    config_hash: Optional[str],
    chain_record_hash: str,
) -> Dict[str, Any]:
    return {
        "event_id":               str(uuid.uuid4()),
        "timestamp":              datetime.now(timezone.utc).isoformat(),
        "trigger_source":         trigger_source,
        "drift_reference":        drift_reference,
        "dataset_snapshot_hash":  dataset_snapshot_hash,
        "config_hash":            config_hash,
        "previous_model_version": previous_model_version,
        "new_model_version":      new_model_version,
        "validation_metrics":     validation_metrics or {},
        "rollback_flag":          rollback_flag,
        "chain_record_hash":      chain_record_hash,
    }


# ── Logger class ─────────────────────────────────────────────────────────────

class RetrainEventLogger:
    """Append-only retrain event logger with hash-chain integrity.

    Args:
        log_path: Absolute or project-relative path to the JSONL file.
        chain_log_path: Path for the hash-chain audit log file.
    """

    def __init__(
        self,
        log_path: Optional[Path] = None,
        chain_log_path: Optional[str] = None,
    ) -> None:
        self._log_path: Path = Path(log_path or _DEFAULT_LOG_PATH)
        self._chain_log_path: Optional[str] = chain_log_path
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Public API ───────────────────────────────────────────────────────────

    def append(
        self,
        trigger_source: str,
        previous_model_version: Optional[str] = None,
        new_model_version: Optional[str] = None,
        validation_metrics: Optional[Dict[str, Any]] = None,
        rollback_flag: bool = False,
        drift_reference: Optional[str] = None,
        dataset_snapshot_hash: Optional[str] = None,
        config_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Append one retrain lifecycle event.

        Args:
            trigger_source:          Why retraining was triggered.
            previous_model_version:  Version before this retrain.
            new_model_version:       Version produced by this retrain.
            validation_metrics:      Dict of metric_name → value.
            rollback_flag:           True if the new model was rolled back.
            drift_reference:         event_id of the drift event that caused this.
            dataset_snapshot_hash:   SHA256 of the training dataset snapshot.
            config_hash:             SHA256 of the serialised RetrainingConfig.

        Returns:
            The written event dict (includes ``chain_record_hash``).
        """
        # Build content hash for chain-linking
        content_hash = self._content_hash(
            trigger_source,
            previous_model_version,
            new_model_version,
            dataset_snapshot_hash,
            config_hash,
        )

        # Append to hash chain
        try:
            chain_kwargs: Dict[str, Any] = {}
            if self._chain_log_path:
                chain_kwargs["log_path"] = self._chain_log_path
            chain_rec = _chain_append(artifact_hash=content_hash, **chain_kwargs)
            chain_record_hash = chain_rec["record_hash"]
        except Exception as exc:
            _log.warning("Retrain event chain-link failed (non-fatal): %s", exc)
            chain_record_hash = ""

        # Build event record
        event = _make_event(
            trigger_source=trigger_source,
            previous_model_version=previous_model_version,
            new_model_version=new_model_version,
            validation_metrics=validation_metrics or {},
            rollback_flag=rollback_flag,
            drift_reference=drift_reference,
            dataset_snapshot_hash=dataset_snapshot_hash,
            config_hash=config_hash,
            chain_record_hash=chain_record_hash,
        )

        # Append-only write
        try:
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, separators=(",", ":")) + "\n")
            _log.info(
                "RetrainEvent appended: trigger=%s prev=%s new=%s rollback=%s",
                trigger_source,
                previous_model_version,
                new_model_version,
                rollback_flag,
            )
        except OSError as exc:
            _log.error("Failed to append retrain event: %s", exc)
            raise

        return event

    def read_all(self, limit: int = 500, offset: int = 0) -> List[Dict[str, Any]]:
        """Read retrain events from the log (newest-first).

        Args:
            limit:  Max records to return.
            offset: Skip this many records from the top (after sorting).

        Returns:
            List of event dicts.
        """
        if not self._log_path.exists():
            return []

        events: List[Dict[str, Any]] = []
        try:
            with open(self._log_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except OSError as exc:
            _log.error("Failed to read retrain event log: %s", exc)
            return []

        events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return events[offset : offset + limit]

    def count(self) -> int:
        """Return total number of records in the log."""
        if not self._log_path.exists():
            return 0
        try:
            with open(self._log_path, "r", encoding="utf-8") as fh:
                return sum(1 for line in fh if line.strip())
        except OSError:
            return 0

    # ── Private ──────────────────────────────────────────────────────────────

    @staticmethod
    def _content_hash(
        trigger_source: str,
        prev_version: Optional[str],
        new_version: Optional[str],
        dataset_hash: Optional[str],
        config_hash: Optional[str],
    ) -> str:
        """Produce a 64-char hex SHA256 for chain-linking."""
        raw = "|".join([
            trigger_source,
            prev_version or "",
            new_version or "",
            dataset_hash or "",
            config_hash or "",
            datetime.now(timezone.utc).isoformat(),
        ])
        return hashlib.sha256(raw.encode()).hexdigest()


# ── Helpers for config hash ──────────────────────────────────────────────────

def hash_retrain_config(config_dict: Dict[str, Any]) -> str:
    """Produce a stable SHA256 of a RetrainingConfig dict.

    Args:
        config_dict: Plain dict representation of the config.

    Returns:
        First 16 hex chars (short hash for display) of SHA256.
    """
    raw = json.dumps(config_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Module-level singleton ───────────────────────────────────────────────────

_instance: Optional[RetrainEventLogger] = None


def get_retrain_event_logger() -> RetrainEventLogger:
    """Return the module-level singleton RetrainEventLogger."""
    global _instance
    if _instance is None:
        _instance = RetrainEventLogger()
    return _instance


def log_retrain_event(
    trigger_source: str,
    previous_model_version: Optional[str] = None,
    new_model_version: Optional[str] = None,
    validation_metrics: Optional[Dict[str, Any]] = None,
    rollback_flag: bool = False,
    drift_reference: Optional[str] = None,
    dataset_snapshot_hash: Optional[str] = None,
    config_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """Module-level convenience wrapper around the singleton logger."""
    return get_retrain_event_logger().append(
        trigger_source=trigger_source,
        previous_model_version=previous_model_version,
        new_model_version=new_model_version,
        validation_metrics=validation_metrics,
        rollback_flag=rollback_flag,
        drift_reference=drift_reference,
        dataset_snapshot_hash=dataset_snapshot_hash,
        config_hash=config_hash,
    )

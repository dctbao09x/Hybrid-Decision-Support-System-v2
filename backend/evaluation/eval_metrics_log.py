# backend/evaluation/eval_metrics_log.py
"""
Evaluation Metrics Logger — Persistent Append-Only
===================================================

Writes evaluation metric snapshots to:
  backend/data/logs/evaluation_metrics.jsonl

Each record represents a point-in-time snapshot of the rolling
evaluation metrics, hash-linked for tamper detection.

Record schema (JSON):
  {
    "event_id":          str,           -- UUID4
    "timestamp":         str,           -- ISO8601 UTC
    "model_version":     str,
    "sample_size":       int,           -- total predictions in window
    "labelled_size":     int,           -- predictions with ground truth
    "rolling_accuracy":  float|null,
    "rolling_f1":        float|null,
    "rolling_precision": float|null,
    "rolling_recall":    float|null,
    "calibration_error": float|null,    -- Brier Score (canonical calibration field)
    "ece":               float|null,    -- Expected Calibration Error
    "model_performance_confidence": float|null,
    "explanation_confidence_mean":  float|null,
    "active_alert_count": int,
    "alerts":            List[Dict],
    "chain_record_hash": str
  }

Usage::

    from backend.evaluation.eval_metrics_log import EvalMetricsLogger, log_eval_snapshot

    # Manual:
    logger = EvalMetricsLogger()
    logger.append(snapshot)

    # Convenience:
    log_eval_snapshot(snapshot)
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.api.hash_chain_logger import append_record as _chain_append
from backend.evaluation.rolling_evaluator import EvalSnapshot

_log = logging.getLogger("evaluation.eval_metrics_log")

# ── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_LOG_PATH = Path("backend/data/logs/evaluation_metrics.jsonl")


# ── Schema helper ────────────────────────────────────────────────────────────

def _snapshot_to_record(
    snapshot: EvalSnapshot,
    chain_record_hash: str = "",
) -> Dict[str, Any]:
    """Convert an :class:`EvalSnapshot` to the canonical JSONL schema."""
    return {
        "event_id":          str(uuid.uuid4()),
        "timestamp":         snapshot.timestamp,
        "model_version":     snapshot.model_version,
        "sample_size":       snapshot.sample_size,
        "labelled_size":     snapshot.labelled_size,
        "rolling_accuracy":  _r(snapshot.rolling_accuracy),
        "rolling_f1":        _r(snapshot.rolling_f1),
        "rolling_precision": _r(snapshot.rolling_precision),
        "rolling_recall":    _r(snapshot.rolling_recall),
        # canonical name per spec: "calibration_error" = Brier Score
        "calibration_error": _r(snapshot.brier_score),
        "ece":               _r(snapshot.ece),
        "model_performance_confidence": _r(snapshot.model_performance_confidence),
        "explanation_confidence_mean":  _r(snapshot.explanation_confidence_mean),
        "active_alert_count": len(snapshot.active_alerts),
        "alerts":            [a.to_dict() for a in snapshot.active_alerts],
        "chain_record_hash": chain_record_hash,
    }


def _r(v: Optional[float], digits: int = 6) -> Optional[float]:
    return round(v, digits) if v is not None else None


# ── Logger class ─────────────────────────────────────────────────────────────

class EvalMetricsLogger:
    """Append-only evaluation metrics logger with hash-chain integrity.

    Args:
        log_path:       Absolute or relative path to the JSONL file.
        chain_log_path: Path for the hash-chain log (shared by default).
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

    def append(self, snapshot: EvalSnapshot) -> Dict[str, Any]:
        """Persist one evaluation snapshot.

        Args:
            snapshot: :class:`EvalSnapshot` from :class:`RollingEvaluator`.

        Returns:
            The written record dict (includes ``chain_record_hash``).
        """
        # Build the record without chain hash first (for content-hash computation)
        record = _snapshot_to_record(snapshot, chain_record_hash="")

        # Compute 64-char SHA256 content hash for chain linking
        payload_str  = json.dumps(record, sort_keys=True, ensure_ascii=False)
        content_hash = hashlib.sha256(payload_str.encode()).hexdigest()

        try:
            chain_kwargs: Dict[str, Any] = {}
            if self._chain_log_path:
                chain_kwargs["log_path"] = self._chain_log_path
            chain_rec = _chain_append(content_hash, **chain_kwargs)
            record["chain_record_hash"] = chain_rec.get("record_hash", content_hash)
        except Exception as exc:
            _log.warning("hash-chain append failed (non-fatal): %s", exc)
            record["chain_record_hash"] = content_hash

        line = json.dumps(record, ensure_ascii=False)
        with open(self._log_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

        _log.debug(
            "eval_snapshot logged: model=%s f1=%s brier=%s samples=%d",
            record["model_version"],
            record["rolling_f1"],
            record["calibration_error"],
            record["sample_size"],
        )
        return record

    def read_recent(
        self,
        limit: int = 100,
        offset: int = 0,
        model_version: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return recent evaluation metric records (newest first).

        Args:
            limit:         Max records to return.
            offset:        Skip from the newest records.
            model_version: Filter by model version if provided.

        Returns:
            List of record dicts.
        """
        if not self._log_path.exists():
            return []
        all_records: List[Dict[str, Any]] = []
        try:
            with open(self._log_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if model_version and rec.get("model_version") != model_version:
                        continue
                    all_records.append(rec)
        except OSError as exc:
            _log.warning("read_recent failed: %s", exc)
            return []

        total = len(all_records)
        start = max(0, total - offset - limit)
        end   = max(0, total - offset)
        return list(reversed(all_records[start:end]))

    def latest(self, model_version: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return the single most recent record."""
        records = self.read_recent(limit=1, model_version=model_version)
        return records[0] if records else None

    def count(self) -> int:
        """Return total number of records in the log."""
        if not self._log_path.exists():
            return 0
        try:
            with open(self._log_path, "r", encoding="utf-8") as fh:
                return sum(1 for line in fh if line.strip())
        except OSError:
            return 0


# ── Module-level singleton ────────────────────────────────────────────────────

_singleton: Optional[EvalMetricsLogger] = None


def get_eval_metrics_logger() -> EvalMetricsLogger:
    """Return the process-wide :class:`EvalMetricsLogger` singleton."""
    global _singleton
    if _singleton is None:
        _singleton = EvalMetricsLogger()
    return _singleton


def log_eval_snapshot(snapshot: EvalSnapshot) -> Dict[str, Any]:
    """Convenience wrapper — persist a snapshot from the singleton logger.

    Non-fatal: exceptions are caught and logged so that evaluation logging
    never breaks the decision pipeline.
    """
    try:
        return get_eval_metrics_logger().append(snapshot)
    except Exception as exc:
        _log.error("log_eval_snapshot failed (non-fatal): %s", exc)
        return {}

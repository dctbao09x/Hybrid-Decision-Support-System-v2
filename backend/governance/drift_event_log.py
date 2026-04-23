# backend/governance/drift_event_log.py
"""
Drift Event Logger — Persistent Append-Only
============================================

Writes every drift detection event to:
  backend/data/logs/drift_event_log.jsonl

Each record is:
  • Appended to a JSONL file (never overwrites)
  • Hash-linked via the shared hash-chain logger so the log is
    tamper-detectable across restarts

Record schema (JSON):
  {
    "event_id":             str,   -- UUID4
    "timestamp":            str,   -- ISO8601 UTC
    "decision_trace_id":    str|null,
    "drift_type":           str,   -- feature_drift | prediction_drift | label_drift
    "divergence_metric":    str,   -- "jsd" | "psi" | "kl"
    "divergence_value":     float,
    "threshold":            float,
    "feature_name":         str|null,
    "model_version":        str,
    "triggered":            bool,
    "chain_record_hash":    str    -- record_hash from hash_chain_logger
  }

Usage::

    from backend.governance.drift_event_log import DriftEventLogger

    logger = DriftEventLogger()
    logger.append(
        drift_type="feature_drift",
        divergence_value=0.18,
        threshold=0.12,
        decision_trace_id="t-abc123",
        feature_name="study_score",
        model_version="v1.2",
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

_log = logging.getLogger("governance.drift_event_log")

# ── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_LOG_PATH = Path("backend/data/logs/drift_event_log.jsonl")

# Supported divergence metrics
METRIC_JSD = "jsd"
METRIC_PSI = "psi"
METRIC_KL  = "kl"


# ── Schema helper ────────────────────────────────────────────────────────────

def _make_event(
    drift_type: str,
    divergence_value: float,
    threshold: float,
    divergence_metric: str = METRIC_JSD,
    decision_trace_id: Optional[str] = None,
    feature_name: Optional[str] = None,
    model_version: str = "unknown",
    chain_record_hash: str = "",
) -> Dict[str, Any]:
    return {
        "event_id":          str(uuid.uuid4()),
        "timestamp":         datetime.now(timezone.utc).isoformat(),
        "decision_trace_id": decision_trace_id,
        "drift_type":        drift_type,
        "divergence_metric": divergence_metric,
        "divergence_value":  round(float(divergence_value), 8),
        "threshold":         round(float(threshold), 8),
        "feature_name":      feature_name,
        "model_version":     model_version,
        "triggered":         float(divergence_value) > float(threshold),
        "chain_record_hash": chain_record_hash,
    }


# ── Logger class ─────────────────────────────────────────────────────────────

class DriftEventLogger:
    """Append-only drift event logger with hash-chain integrity.

    Args:
        log_path: Absolute or project-relative path to the JSONL file.
        chain_log_path: Path for the hash-chain audit log file.  Defaults to the
                        shared ``audit_chain.log`` file written by the pipeline.
    """

    def __init__(
        self,
        log_path: Optional[Path] = None,
        chain_log_path: Optional[str] = None,
    ) -> None:
        self._log_path: Path = Path(log_path or _DEFAULT_LOG_PATH)
        self._chain_log_path: Optional[str] = chain_log_path  # None → SDK default
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Public API ───────────────────────────────────────────────────────────

    def append(
        self,
        drift_type: str,
        divergence_value: float,
        threshold: float,
        divergence_metric: str = METRIC_JSD,
        decision_trace_id: Optional[str] = None,
        feature_name: Optional[str] = None,
        model_version: str = "unknown",
    ) -> Dict[str, Any]:
        """Append one drift event to the persistent log.

        Args:
            drift_type:          "feature_drift" | "prediction_drift" | "label_drift"
            divergence_value:    Computed divergence (JSD, PSI, or KL).
            threshold:           Threshold used for this check.
            divergence_metric:   Which metric was used (default "jsd").
            decision_trace_id:   Pipeline trace ID, if this came from an inference.
            feature_name:        Feature dimension name (None for prediction/label drift).
            model_version:       Active model version string.

        Returns:
            The written event dict (includes ``chain_record_hash``).
        """
        # Build content hash for chain-linking (64-char SHA256)
        content_hash = self._content_hash(
            drift_type, divergence_value, threshold, decision_trace_id, feature_name
        )

        # Append to hash chain and capture chain record hash
        try:
            chain_kwargs: Dict[str, Any] = {}
            if self._chain_log_path:
                chain_kwargs["log_path"] = self._chain_log_path
            chain_rec = _chain_append(artifact_hash=content_hash, **chain_kwargs)
            chain_record_hash = chain_rec["record_hash"]
        except Exception as exc:
            _log.warning("Drift event chain-link failed (non-fatal): %s", exc)
            chain_record_hash = ""

        # Build event record
        event = _make_event(
            drift_type=drift_type,
            divergence_value=divergence_value,
            threshold=threshold,
            divergence_metric=divergence_metric,
            decision_trace_id=decision_trace_id,
            feature_name=feature_name,
            model_version=model_version,
            chain_record_hash=chain_record_hash,
        )

        # Append-only write
        try:
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, separators=(",", ":")) + "\n")
            _log.debug(
                "DriftEvent appended: trace=%s type=%s val=%.4f thr=%.4f triggered=%s",
                decision_trace_id,
                drift_type,
                divergence_value,
                threshold,
                event["triggered"],
            )
        except OSError as exc:
            _log.error("Failed to append drift event: %s", exc)
            raise

        return event

    def read_all(self, limit: int = 1000, offset: int = 0) -> List[Dict[str, Any]]:
        """Read events from the log file (newest-first).

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
            _log.error("Failed to read drift event log: %s", exc)
            return []

        # newest first
        events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return events[offset : offset + limit]

    def count(self) -> int:
        """Return the total number of records in the log."""
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
        drift_type: str,
        divergence_value: float,
        threshold: float,
        trace_id: Optional[str],
        feature_name: Optional[str],
    ) -> str:
        """Produce a 64-char hex SHA256 representing the event content."""
        raw = "|".join([
            drift_type,
            f"{divergence_value:.8f}",
            f"{threshold:.8f}",
            trace_id or "",
            feature_name or "",
            datetime.now(timezone.utc).isoformat(),
        ])
        return hashlib.sha256(raw.encode()).hexdigest()


# ── Module-level singleton ───────────────────────────────────────────────────

_instance: Optional[DriftEventLogger] = None


def get_drift_event_logger() -> DriftEventLogger:
    """Return the module-level singleton DriftEventLogger."""
    global _instance
    if _instance is None:
        _instance = DriftEventLogger()
    return _instance


def log_drift_event(
    drift_type: str,
    divergence_value: float,
    threshold: float,
    divergence_metric: str = METRIC_JSD,
    decision_trace_id: Optional[str] = None,
    feature_name: Optional[str] = None,
    model_version: str = "unknown",
) -> Dict[str, Any]:
    """Module-level convenience wrapper around the singleton logger."""
    return get_drift_event_logger().append(
        drift_type=drift_type,
        divergence_value=divergence_value,
        threshold=threshold,
        divergence_metric=divergence_metric,
        decision_trace_id=decision_trace_id,
        feature_name=feature_name,
        model_version=model_version,
    )

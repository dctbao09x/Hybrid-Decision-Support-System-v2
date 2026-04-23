# backend/governance/rule_event_log.py
"""
Rule Event Logger — Persistent Append-Only
===========================================

Writes every rule engine execution event to:
  backend/data/logs/rule_log.jsonl

Each record represents ONE rule evaluated against ONE decision trace.
Records are hash-linked so the log is tamper-detectable across restarts.

Record schema (JSON):
  {
    "event_id":           str,   -- UUID4
    "timestamp":          str,   -- ISO8601 UTC
    "decision_trace_id":  str,
    "rule_id":            str,   -- rule name/identifier
    "rule_version":       str,   -- rule schema version
    "rule_condition":     str,   -- category / condition tag
    "rule_result":        str,   -- "pass_through" | "flagged" | "error"
    "priority":           int,   -- rule priority
    "frozen":             bool,  -- True when rule engine is frozen (no re-rank)
    "chain_record_hash":  str    -- record_hash from hash_chain_logger
  }

Usage::

    from backend.governance.rule_event_log import log_rule_batch

    log_rule_batch(
        trace_id="dec-abc123",
        rules_trace=[
            {"rule": "age_filter", "category": "eligibility",
             "priority": 10, "outcome": "pass_through", "frozen": True}
        ],
    )
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

_log = logging.getLogger("governance.rule_event_log")

# ── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_LOG_PATH = Path("backend/data/logs/rule_log.jsonl")

RULE_VERSION_DEFAULT = "v1.0.0"

RESULT_PASS_THROUGH = "pass_through"
RESULT_FLAGGED      = "flagged"
RESULT_ERROR        = "error"


# ── Schema helper ────────────────────────────────────────────────────────────

def _make_rule_event(
    decision_trace_id: str,
    rule_id: str,
    rule_condition: str,
    rule_result: str,
    rule_version: str = RULE_VERSION_DEFAULT,
    priority: int = 0,
    frozen: bool = True,
    chain_record_hash: str = "",
) -> Dict[str, Any]:
    return {
        "event_id":          str(uuid.uuid4()),
        "timestamp":         datetime.now(timezone.utc).isoformat(),
        "decision_trace_id": decision_trace_id,
        "rule_id":           rule_id,
        "rule_version":      rule_version,
        "rule_condition":    rule_condition,
        "rule_result":       rule_result,
        "priority":          int(priority),
        "frozen":            bool(frozen),
        "chain_record_hash": chain_record_hash,
    }


# ── Logger class ─────────────────────────────────────────────────────────────

class RuleEventLogger:
    """Append-only rule evaluation logger with hash-chain integrity.

    Each call to :meth:`append_batch` writes one JSONL record per rule
    evaluated during Stage 7 of the decision pipeline.

    Args:
        log_path:       Absolute or project-relative path to the JSONL file.
        chain_log_path: Path for the hash-chain audit log (shared by default).
    """

    def __init__(
        self,
        log_path: Optional[Path] = None,
        chain_log_path: Optional[str] = None,
    ) -> None:
        self._log_path: Path = Path(log_path or _DEFAULT_LOG_PATH)
        self._chain_log_path: Optional[str] = chain_log_path
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _write_record(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Hash-chain-link and persist one event record."""
        payload_str = json.dumps(event, sort_keys=True, ensure_ascii=False)
        content_hash = hashlib.sha256(payload_str.encode()).hexdigest()  # 64-char hex

        try:
            chain_kwargs: Dict[str, Any] = {}
            if self._chain_log_path:
                chain_kwargs["log_path"] = self._chain_log_path
            chain_rec = _chain_append(content_hash, **chain_kwargs)
            event["chain_record_hash"] = chain_rec.get("record_hash", content_hash)
        except Exception as exc:
            _log.warning("hash-chain append failed (non-fatal): %s", exc)
            event["chain_record_hash"] = content_hash

        line = json.dumps(event, ensure_ascii=False)
        with open(self._log_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

        _log.debug(
            "rule_event logged: trace=%s rule=%s result=%s",
            event["decision_trace_id"], event["rule_id"], event["rule_result"],
        )
        return event

    # ── Public API ───────────────────────────────────────────────────────────

    def append_batch(
        self,
        trace_id: str,
        rules_trace: List[Dict[str, Any]],
        rule_version: str = RULE_VERSION_DEFAULT,
    ) -> List[Dict[str, Any]]:
        """Persist each rule in *rules_trace* as an individual JSONL record.

        Args:
            trace_id:    Decision pipeline trace ID to link all records.
            rules_trace: List of rule dicts produced by Stage 7 ``_apply_rules``.
                         Expected keys: ``rule``, ``category``, ``priority``,
                         ``outcome``, ``frozen``.
            rule_version: Semantic version of the rule schema.

        Returns:
            List of persisted event dicts (one per rule).
        """
        appended: List[Dict[str, Any]] = []
        for r in rules_trace:
            event = _make_rule_event(
                decision_trace_id=trace_id,
                rule_id=r.get("rule", "_unknown"),
                rule_condition=r.get("category", ""),
                rule_result=r.get("outcome", RESULT_PASS_THROUGH),
                rule_version=rule_version,
                priority=r.get("priority", 0),
                frozen=r.get("frozen", True),
            )
            appended.append(self._write_record(event))
        return appended

    def read_by_trace(
        self,
        trace_id: str,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Return all rule events for a specific decision trace ID.

        Scans the JSONL file linearly (suitable for audit / reconstruction).

        Args:
            trace_id: The decision trace ID to filter for.
            limit:    Maximum records to return.

        Returns:
            List of matching event dicts, in append order.
        """
        results: List[Dict[str, Any]] = []
        if not self._log_path.exists():
            return results
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
                    if rec.get("decision_trace_id") == trace_id:
                        results.append(rec)
                        if len(results) >= limit:
                            break
        except OSError as exc:
            _log.warning("read_by_trace failed: %s", exc)
        return results

    def read_recent_traces(
        self,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return one summary entry per recent trace_id (newest first).

        Reads the entire JSONL, groups by trace_id preserving insertion order,
        then returns the last *limit* traces.

        Returns:
            List of ``{trace_id, rules_count, rules}`` dicts, most-recent first.
        """
        # Build ordered dict: most recently seen trace_id wins ordering slot
        ordered: Dict[str, List[Dict[str, Any]]] = {}
        if not self._log_path.exists():
            return []
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
                    tid = rec.get("decision_trace_id", "")
                    if tid not in ordered:
                        ordered[tid] = []
                    ordered[tid].append(rec)
        except OSError as exc:
            _log.warning("read_recent_traces failed: %s", exc)
            return []

        # Newest-first: reverse insertion order, take limit
        recent_ids = list(ordered.keys())[-limit:]
        return [
            {
                "trace_id": tid,
                "rules_count": len(ordered[tid]),
                "rules": ordered[tid],
            }
            for tid in reversed(recent_ids)
        ]

    def count(self) -> int:
        """Return total number of rule event records in the log."""
        if not self._log_path.exists():
            return 0
        try:
            with open(self._log_path, "r", encoding="utf-8") as fh:
                return sum(1 for line in fh if line.strip())
        except OSError:
            return 0


# ── Module-level singleton ────────────────────────────────────────────────────

_singleton: Optional[RuleEventLogger] = None


def get_rule_event_logger() -> RuleEventLogger:
    """Return the process-wide :class:`RuleEventLogger` singleton."""
    global _singleton
    if _singleton is None:
        _singleton = RuleEventLogger()
    return _singleton


def log_rule_batch(
    trace_id: str,
    rules_trace: List[Dict[str, Any]],
    rule_version: str = RULE_VERSION_DEFAULT,
) -> List[Dict[str, Any]]:
    """Convenience wrapper — logs all rules for a single decision trace.

    Non-fatal: exceptions are caught and logged so that governance logging
    failures never break the decision pipeline.
    """
    try:
        return get_rule_event_logger().append_batch(
            trace_id=trace_id,
            rules_trace=rules_trace,
            rule_version=rule_version,
        )
    except Exception as exc:
        _log.error("log_rule_batch failed (non-fatal): %s", exc)
        return []

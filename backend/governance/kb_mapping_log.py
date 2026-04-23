# backend/governance/kb_mapping_log.py
"""
KB Mapping Audit Logger — Persistent Append-Only
=================================================

Writes every KB alignment event to:
  backend/data/logs/kb_mapping_log.jsonl

Each record captures the full KB mapping performed during Stage 3
of the decision pipeline for a given decision trace.

Record schema (JSON):
  {
    "event_id":                  str,        -- UUID4
    "timestamp":                 str,        -- ISO8601 UTC
    "decision_trace_id":         str,
    "ontology_version":          str,        -- KB reference version string
    "input_skill_cluster":       List[str],  -- skills that matched KB domain clusters
    "input_interest_cluster":    List[str],  -- interests that matched KB domain clusters
    "skills_kb_matches":         Dict,       -- skill → [domain_tags]
    "interests_kb_matches":      Dict,       -- interest → [domain_tags]
    "unrecognised_feature_count":int,        -- count of features not in KB
    "unrecognised_features":     List[str],  -- feature keys unknown to KB
    "chain_record_hash":         str         -- record_hash from hash_chain_logger
  }

Usage::

    from backend.governance.kb_mapping_log import log_kb_mapping

    log_kb_mapping(
        trace_id="dec-abc123",
        kb_alignment_payload={
            "kb_reference_version": "kb-v1.0-20260222",
            "skills_kb_matches": {"python": ["software_engineering"]},
            "interests_kb_matches": {"technology": ["software_engineering"]},
            "unrecognised_keys": [],
        },
        input_skills=["python", "math"],
        input_interests=["technology"],
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

_log = logging.getLogger("governance.kb_mapping_log")

# ── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_LOG_PATH = Path("backend/data/logs/kb_mapping_log.jsonl")

KB_VERSION_UNKNOWN = "unknown"


# ── Schema helper ────────────────────────────────────────────────────────────

def _make_kb_event(
    decision_trace_id: str,
    ontology_version: str,
    input_skill_cluster: List[str],
    input_interest_cluster: List[str],
    skills_kb_matches: Dict[str, List[str]],
    interests_kb_matches: Dict[str, List[str]],
    unrecognised_features: List[str],
    chain_record_hash: str = "",
) -> Dict[str, Any]:
    return {
        "event_id":                   str(uuid.uuid4()),
        "timestamp":                  datetime.now(timezone.utc).isoformat(),
        "decision_trace_id":          decision_trace_id,
        "ontology_version":           ontology_version,
        "input_skill_cluster":        list(input_skill_cluster),
        "input_interest_cluster":     list(input_interest_cluster),
        "skills_kb_matches":          dict(skills_kb_matches),
        "interests_kb_matches":       dict(interests_kb_matches),
        "unrecognised_feature_count": len(unrecognised_features),
        "unrecognised_features":      list(unrecognised_features),
        "chain_record_hash":          chain_record_hash,
    }


# ── Logger class ─────────────────────────────────────────────────────────────

class KBMappingLogger:
    """Append-only KB alignment audit logger with hash-chain integrity.

    One record per decision trace is written, capturing the full KB
    mapping context (ontology version, skill clusters, domain matches).

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
        content_hash = hashlib.sha256(payload_str.encode()).hexdigest()

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
            "kb_mapping logged: trace=%s ontology=%s skills=%d",
            event["decision_trace_id"],
            event["ontology_version"],
            len(event["input_skill_cluster"]),
        )
        return event

    # ── Public API ───────────────────────────────────────────────────────────

    def append(
        self,
        trace_id: str,
        kb_alignment_payload: Dict[str, Any],
        input_skills: Optional[List[str]] = None,
        input_interests: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Persist KB alignment data for one decision trace.

        Args:
            trace_id:            Decision pipeline trace ID.
            kb_alignment_payload: The dict returned by
                                  ``DecisionController._align_with_knowledge_base()``.
                                  Expected keys: ``kb_reference_version``,
                                  ``skills_kb_matches``, ``interests_kb_matches``,
                                  ``unrecognised_keys``.
            input_skills:        Raw skill list from the normalised input.
            input_interests:     Raw interest list from the normalised input.

        Returns:
            The persisted event dict.
        """
        skills_kb = kb_alignment_payload.get("skills_kb_matches", {})
        interests_kb = kb_alignment_payload.get("interests_kb_matches", {})

        # "skill cluster" = skills that actually matched at least one KB domain
        input_skill_cluster = [
            s for s, domains in skills_kb.items() if domains
        ] if skills_kb else (input_skills or [])

        input_interest_cluster = [
            i for i, domains in interests_kb.items() if domains
        ] if interests_kb else (input_interests or [])

        event = _make_kb_event(
            decision_trace_id=trace_id,
            ontology_version=kb_alignment_payload.get(
                "kb_reference_version", KB_VERSION_UNKNOWN
            ),
            input_skill_cluster=input_skill_cluster,
            input_interest_cluster=input_interest_cluster,
            skills_kb_matches=skills_kb,
            interests_kb_matches=interests_kb,
            unrecognised_features=kb_alignment_payload.get("unrecognised_keys", []),
        )
        return self._write_record(event)

    def read_by_trace(
        self,
        trace_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return the KB mapping record for a specific decision trace ID.

        Returns the first matching record (there should be exactly one per trace).

        Args:
            trace_id: The decision trace ID to look up.

        Returns:
            Event dict or ``None`` if not found.
        """
        if not self._log_path.exists():
            return None
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
                        return rec
        except OSError as exc:
            _log.warning("read_by_trace failed: %s", exc)
        return None

    def read_recent(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Return the most recent KB mapping records (newest first).

        Args:
            limit:  Max records to return.
            offset: Number of records to skip from the end.

        Returns:
            List of event dicts, most-recent first.
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
                        all_records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError as exc:
            _log.warning("read_recent failed: %s", exc)
            return []
        total = len(all_records)
        start = max(0, total - offset - limit)
        end   = max(0, total - offset)
        return list(reversed(all_records[start:end]))

    def count(self) -> int:
        """Return total number of KB mapping records in the log."""
        if not self._log_path.exists():
            return 0
        try:
            with open(self._log_path, "r", encoding="utf-8") as fh:
                return sum(1 for line in fh if line.strip())
        except OSError:
            return 0


# ── Module-level singleton ────────────────────────────────────────────────────

_singleton: Optional[KBMappingLogger] = None


def get_kb_mapping_logger() -> KBMappingLogger:
    """Return the process-wide :class:`KBMappingLogger` singleton."""
    global _singleton
    if _singleton is None:
        _singleton = KBMappingLogger()
    return _singleton


def log_kb_mapping(
    trace_id: str,
    kb_alignment_payload: Dict[str, Any],
    input_skills: Optional[List[str]] = None,
    input_interests: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Convenience wrapper — logs KB alignment for one decision trace.

    Non-fatal: exceptions are caught and logged.
    """
    try:
        return get_kb_mapping_logger().append(
            trace_id=trace_id,
            kb_alignment_payload=kb_alignment_payload,
            input_skills=input_skills,
            input_interests=input_interests,
        )
    except Exception as exc:
        _log.error("log_kb_mapping failed (non-fatal): %s", exc)
        return None

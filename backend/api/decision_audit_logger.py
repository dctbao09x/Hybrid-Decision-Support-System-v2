# backend/api/decision_audit_logger.py
"""
Decision Audit Logger — Stage 6 Hash-Chain Implementation
===========================================================

Single authoritative, append-only hash-chain log that captures ALL
semantically significant fields from one complete pipeline decision.

MOTIVATION (Stage 6 audit gaps closed)
---------------------------------------
The per-stage ``hash_chain_logger`` records only opaque ``artifact_hash``
values — it cannot answer "what weights_version was used?" or "what was the
explanation_hash?" for a given decision without replaying every stage payload.

This module closes those gaps with ONE consolidated record per pipeline run:

  RECORD FIELDS
  ─────────────────────────────────────────────────────────────────
  record_index     Monotone counter (0-based).
  trace_id         Pipeline trace identifier (``dec-…``).
  input_hash       SHA-256 of the canonical scoring-input payload.
  breakdown_hash   SHA-256 of the canonical ScoringBreakdown dict.
  explanation_hash SHA-256 of the canonical UnifiedExplanation payload.
                   ``<no-explanation>`` when explanation was skipped.
  final_score      Deterministic weighted-sum final score (float).
  weights_version  Identifier of the SubScoreWeights / WeightArtifact.
  timestamp        ISO-8601 UTC time of the record.
  prev_hash        ``record_hash`` of the preceding record (or GENESIS).
  record_hash      Tamper-evident chain link:
                       SHA-256( prev_hash + canonical_json(payload) )
                   where ``payload`` is the above fields EXCLUDING
                   ``prev_hash`` and ``record_hash`` themselves.
  ─────────────────────────────────────────────────────────────────

HASH FORMULA
────────────
  serialized_payload = canonical_json({
      "record_index":     N,
      "trace_id":         "dec-…",
      "input_hash":       "…64hex…",
      "breakdown_hash":   "…64hex…",
      "explanation_hash": "…64hex… | <no-explanation>",
      "final_score":      float,
      "weights_version":  "v1.2.0",
      "timestamp":        "ISO-8601",
  })
  record_hash = SHA-256( prev_hash + serialized_payload )

APPEND-ONLY GUARANTEE
─────────────────────
  • File is opened exclusively in mode ``'a'``.  No seek, truncate, or
    overwrite is reachable through any public API in this module.
  • ``verify_chain()`` reads the file in read-only mode.
  • There is NO delete path, no update path, no rewrite path.

MANDATORY CALL SITE
────────────────────
  ``append_decision_record()`` MUST be called inside ``run_pipeline()``
  after Stage 9 (explanation) completes and BEFORE ``DecisionResponse``
  is constructed.  The call is mandatory even when:
    • explanation was skipped — pass ``explanation_hash="<no-explanation>"``
    • scoring produced an empty ranking list

  Any scoring execution path that does NOT call this function is a BYPASS
  and MUST be treated as a pipeline integrity violation.

USAGE
─────
  from backend.api.decision_audit_logger import (
      append_decision_record,
      verify_chain,
  )

  # After Stage 9 completes:
  append_decision_record(
      trace_id         = trace_id,
      input_hash       = compute_stage_hash(normalized_input),
      breakdown_hash   = compute_stage_hash(scoring_breakdown.to_dict()),
      explanation_hash = exp_state.explanation_hash or "<no-explanation>",
      final_score      = scoring_breakdown.final_score,
      weights_version  = self._weights_version,
  )

  # Offline audit:
  report = verify_chain()          # returns "VALID" or "INVALID at N"
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("api.decision_audit_logger")

# ─── Configuration ────────────────────────────────────────────────────────────

_DEFAULT_LOG_PATH = "decision_audit.log"

#: Sentinel used when no explanation was produced for a decision.
NO_EXPLANATION_SENTINEL = "<no-explanation>"

#: SHA-256 of b"GENESIS" — prev_hash for the very first record.
_GENESIS_HASH: str = hashlib.sha256(b"GENESIS").hexdigest()


# ─── Serialisation ────────────────────────────────────────────────────────────

def _canonical(data: Any) -> str:
    """Deterministic canonical JSON (sorted keys, no surplus whitespace)."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _compute_record_hash(prev_hash: str, serialized_payload: str) -> str:
    """
    record_hash = SHA-256( prev_hash + serialized_payload )

    Both strings are UTF-8 encoded before hashing so that the formula is
    unambiguous and reproducible across languages and platforms.
    """
    raw = (prev_hash + serialized_payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ─── Last-record reader ───────────────────────────────────────────────────────

def _read_last_record(log_path: str) -> Optional[Dict[str, Any]]:
    """
    Read the last non-empty JSON line from *log_path* without loading the file.

    Scans backward in 4 KiB blocks.  Returns ``None`` when the file does not
    exist or is empty.
    """
    if not os.path.exists(log_path):
        return None

    try:
        with open(log_path, "rb") as fh:
            fh.seek(0, 2)
            file_size = fh.tell()
            if file_size == 0:
                return None

            block_size = 4096
            pos = file_size
            carry = b""

            while pos > 0:
                read_size = min(block_size, pos)
                pos -= read_size
                fh.seek(pos)
                block = fh.read(read_size)
                combined = block + carry
                lines = combined.split(b"\n")
                carry = lines[0]
                non_empty = [ln.strip() for ln in lines[1:] if ln.strip()]
                if non_empty:
                    return json.loads(non_empty[-1].decode("utf-8"))

            if carry.strip():
                return json.loads(carry.strip().decode("utf-8"))

    except (json.JSONDecodeError, OSError) as exc:
        logger.error("[DECISION_AUDIT] Failed to read last record: %s", exc)

    return None


# ─── Public API ───────────────────────────────────────────────────────────────

def append_decision_record(
    *,
    trace_id: str,
    input_hash: str,
    breakdown_hash: str,
    explanation_hash: str,
    final_score: float,
    weights_version: str,
    log_path: str = _DEFAULT_LOG_PATH,
) -> Dict[str, Any]:
    """
    Append one consolidated decision audit record to the hash chain.

    This is the SINGLE, MANDATORY write point for decision provenance.
    Call it exactly once per completed pipeline run, after Stage 9.

    Parameters
    ----------
    trace_id:
        Pipeline trace identifier (e.g. ``"dec-abc123456789"``).
    input_hash:
        SHA-256 of the canonical scoring-input payload (Stage 1 stage_hash).
    breakdown_hash:
        SHA-256 of ``ScoringBreakdown.to_dict()`` (deterministic).
    explanation_hash:
        SHA-256 from ``UnifiedExplanation.explanation_hash``, or the sentinel
        string ``"<no-explanation>"`` when explanation was skipped.
    final_score:
        Deterministic weighted-sum final score from ``ScoringBreakdown``.
    weights_version:
        Identifier of the SubScoreWeights / WeightArtifact used (e.g. ``"v1.2.0"``).
    log_path:
        Path to the append-only audit log file (default ``decision_audit.log``).

    Returns
    -------
    dict
        The written record (for in-process verification / testing).

    Raises
    ------
    ValueError
        If any required hash field is empty or ``trace_id`` is blank.
    OSError
        If the log file cannot be opened for appending.
    """
    # ── Basic validation ──────────────────────────────────────────────────────
    if not trace_id or not trace_id.strip():
        raise ValueError("trace_id must be a non-empty string.")
    if not input_hash or len(input_hash) != 64:
        raise ValueError(
            f"input_hash must be a 64-char hex string, got: {input_hash!r}"
        )
    if not breakdown_hash or len(breakdown_hash) != 64:
        raise ValueError(
            f"breakdown_hash must be a 64-char hex string, got: {breakdown_hash!r}"
        )
    if not explanation_hash:
        raise ValueError("explanation_hash must not be empty — use the sentinel if needed.")
    if not weights_version or not weights_version.strip():
        raise ValueError("weights_version must be a non-empty string.")

    # ── Chain state ───────────────────────────────────────────────────────────
    last = _read_last_record(log_path)
    if last is None:
        prev_hash    = _GENESIS_HASH
        record_index = 0
    else:
        prev_hash    = last["record_hash"]
        record_index = last["record_index"] + 1

    # ── Build payload (the part that's hashed with prev_hash) ─────────────────
    timestamp = datetime.now(timezone.utc).isoformat()

    payload: Dict[str, Any] = {
        "record_index":     record_index,
        "trace_id":         trace_id,
        "input_hash":       input_hash,
        "breakdown_hash":   breakdown_hash,
        "explanation_hash": explanation_hash,
        "final_score":      round(float(final_score), 6),
        "weights_version":  weights_version,
        "timestamp":        timestamp,
    }
    serialized = _canonical(payload)
    record_hash = _compute_record_hash(prev_hash, serialized)

    # ── Full record (payload + chain links) ───────────────────────────────────
    record: Dict[str, Any] = {
        **payload,
        "prev_hash":   prev_hash,
        "record_hash": record_hash,
    }

    # ── Append-only write (mode 'a' — no seek, truncate, or overwrite) ────────
    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(_canonical(record) + "\n")
    except OSError as exc:
        logger.error("[DECISION_AUDIT] Failed to append record to %s: %s", log_path, exc)
        raise

    logger.info(
        "[DECISION_AUDIT] #%d trace=%s final_score=%.4f weights=%s "
        "breakdown=%s... explanation=%s... record=%s...",
        record_index,
        trace_id,
        final_score,
        weights_version,
        breakdown_hash[:12],
        explanation_hash[:12],
        record_hash[:12],
    )

    return record


# ─── Verification ─────────────────────────────────────────────────────────────

def _verify_chain_detail(log_path: str) -> Dict[str, Any]:
    """
    Replay every record in *log_path* and return a detailed verification report.

    For each record checks:
      1. ``record_hash == sha256(prev_hash + canonical_json(payload_fields))``
      2. ``prev_hash`` equals the previous record's ``record_hash``
         (genesis: sha256(b"GENESIS")).
      3. ``record_index`` is strictly monotone from 0.
      4. All mandatory fields present:
         ``trace_id``, ``input_hash``, ``breakdown_hash``,
         ``explanation_hash``, ``final_score``, ``weights_version``.

    Returns
    -------
    dict with keys:
      valid           bool
      total_records   int
      first_broken_at Optional[int]
      errors          List[str]
    """
    _REQUIRED = (
        "record_index", "trace_id", "input_hash", "breakdown_hash",
        "explanation_hash", "final_score", "weights_version", "timestamp",
        "prev_hash", "record_hash",
    )

    errors: List[str] = []
    total = 0
    first_broken: Optional[int] = None
    expected_prev  = _GENESIS_HASH
    expected_index = 0

    if not os.path.exists(log_path):
        return {
            "valid": False,
            "total_records": 0,
            "first_broken_at": None,
            "errors": [f"Log file not found: {log_path}"],
        }

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue

                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"Record {total}: JSON parse error — {exc}")
                    if first_broken is None:
                        first_broken = total
                    total += 1
                    continue

                idx = rec.get("record_index", -1)

                # ── Required field presence ───────────────────────────────
                for field in _REQUIRED:
                    if field not in rec:
                        err = f"Record {idx}: missing field '{field}'."
                        errors.append(err)
                        if first_broken is None:
                            first_broken = idx

                # ── Index monotonicity ────────────────────────────────────
                if idx != expected_index:
                    errors.append(
                        f"Record {total}: expected index {expected_index}, got {idx}."
                    )
                    if first_broken is None:
                        first_broken = total

                # ── prev_hash linkage ─────────────────────────────────────
                if rec.get("prev_hash") != expected_prev:
                    errors.append(
                        f"Record {idx}: prev_hash mismatch — "
                        f"expected {expected_prev[:16]}…  "
                        f"got {str(rec.get('prev_hash',''))[:16]}…"
                    )
                    if first_broken is None:
                        first_broken = idx

                # ── record_hash integrity ─────────────────────────────────
                payload_fields = {
                    k: rec[k]
                    for k in (
                        "record_index", "trace_id", "input_hash",
                        "breakdown_hash", "explanation_hash", "final_score",
                        "weights_version", "timestamp",
                    )
                    if k in rec
                }
                computed = _compute_record_hash(
                    rec.get("prev_hash", ""),
                    _canonical(payload_fields),
                )
                if computed != rec.get("record_hash"):
                    errors.append(
                        f"Record {idx}: record_hash tampered — "
                        f"computed {computed[:16]}…  "
                        f"stored {str(rec.get('record_hash',''))[:16]}…"
                    )
                    if first_broken is None:
                        first_broken = idx

                expected_prev  = rec.get("record_hash", "")
                expected_index = idx + 1
                total += 1

    except OSError as exc:
        errors.append(f"Cannot read log file: {exc}")

    return {
        "valid":           len(errors) == 0,
        "total_records":   total,
        "first_broken_at": first_broken,
        "errors":          errors,
    }


def verify_chain(log_path: str = _DEFAULT_LOG_PATH) -> str:
    """
    Verify the integrity of the decision audit chain.

    Replays every record and checks:
      1. ``record_hash`` matches recomputed value.
      2. ``prev_hash`` links back correctly (genesis = sha256(b"GENESIS")).
      3. ``record_index`` increments monotonically from 0.
      4. All mandatory semantic fields are present in every record.

    Parameters
    ----------
    log_path:
        Path to the decision audit log (default ``decision_audit.log``).

    Returns
    -------
    ``"VALID"`` — if the entire chain passes all checks, or
    ``"INVALID at record_index N"`` — where N is the first broken record.

    Examples
    --------
    >>> verify_chain("decision_audit.log")
    'VALID'

    >>> verify_chain("tampered.log")
    'INVALID at record_index 1'
    """
    detail = _verify_chain_detail(log_path)
    if detail["valid"]:
        logger.info(
            "[DECISION_AUDIT] Chain VALID: %d records verified",
            detail["total_records"],
        )
        return "VALID"

    broken_at = detail["first_broken_at"]
    result = f"INVALID at record_index {broken_at}"
    logger.warning(
        "[DECISION_AUDIT] Chain %s — errors: %s",
        result,
        detail["errors"],
    )
    return result


# ─── Example chain generator (documentation / testing) ───────────────────────

def build_example_chain(n: int = 3, log_path: str = "") -> List[Dict[str, Any]]:
    """
    Generate *n* example decision audit records demonstrating chain continuity.

    Each record referencess the previous record's ``record_hash`` as its
    ``prev_hash``, proving that:
        record_k.prev_hash == record_{k-1}.record_hash

    This function writes to *log_path* when given; otherwise it only
    returns the records in-memory (useful for tests and documentation).

    Parameters
    ----------
    n:        Number of records to generate (default 3).
    log_path: If non-empty, append records to this file *and* return them.

    Returns
    -------
    List of record dicts in chain order.
    """
    import hashlib as _hl

    records: List[Dict[str, Any]] = []

    for i in range(n):
        # Synthetic but realistic hashes
        ih = _hl.sha256(f"input_payload_{i}".encode()).hexdigest()
        bh = _hl.sha256(f"breakdown_payload_{i}".encode()).hexdigest()
        eh = _hl.sha256(f"explanation_payload_{i}".encode()).hexdigest()

        if log_path:
            rec = append_decision_record(
                trace_id         = f"dec-example{i:04d}",
                input_hash       = ih,
                breakdown_hash   = bh,
                explanation_hash = eh,
                final_score      = 60.0 + i * 10.0,
                weights_version  = "v1.0.0",
                log_path         = log_path,
            )
        else:
            # Build in-memory without file I/O
            if records:
                prev_hash    = records[-1]["record_hash"]
                record_index = i
            else:
                prev_hash    = _GENESIS_HASH
                record_index = 0

            timestamp  = datetime.now(timezone.utc).isoformat()
            payload: Dict[str, Any] = {
                "record_index":     record_index,
                "trace_id":         f"dec-example{i:04d}",
                "input_hash":       ih,
                "breakdown_hash":   bh,
                "explanation_hash": eh,
                "final_score":      round(60.0 + i * 10.0, 6),
                "weights_version":  "v1.0.0",
                "timestamp":        timestamp,
            }
            serialized  = _canonical(payload)
            record_hash = _compute_record_hash(prev_hash, serialized)
            rec = {**payload, "prev_hash": prev_hash, "record_hash": record_hash}

        records.append(rec)

    return records

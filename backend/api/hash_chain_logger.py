# backend/api/hash_chain_logger.py
"""
Cryptographic Hash-Chain Logger
================================

Append-only, tamper-detectable audit log for pipeline stage artifacts.

Record format:
  {
    "record_index": int,       -- zero-based position in chain
    "prev_hash":    str,       -- record_hash of the previous record
    "artifact_hash": str,      -- stage_hash from PipelineArtifact
    "timestamp":    str,       -- ISO8601 UTC
    "record_hash":  str        -- sha256(prev_hash + artifact_hash + timestamp)
  }

INVARIANTS:
  - File is opened in append-only mode ('a') — no seek, no overwrite.
  - Genesis record uses sha256("GENESIS") as prev_hash.
  - Each new record reads the LAST line to obtain prev_hash + index.
  - Chain integrity is verifiable by replaying all record_hash values.

USAGE:
  from backend.api.hash_chain_logger import append_record, verify_chain

  append_record("a1b2c3...")          # after each pipeline stage
  report = verify_chain()             # offline audit
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("api.hash_chain_logger")

# ─── Configuration ────────────────────────────────────────────────────────────

# Default audit log path (relative to process cwd, typically project root)
_DEFAULT_LOG_PATH = "audit_chain.log"

# Genesis prev_hash: sha256(b"GENESIS")
_GENESIS_HASH: str = hashlib.sha256(b"GENESIS").hexdigest()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _compute_record_hash(prev_hash: str, artifact_hash: str, timestamp: str) -> str:
    """
    Compute record_hash = SHA256(prev_hash + artifact_hash + timestamp).

    Args:
        prev_hash:     Hex SHA256 of the previous record (or GENESIS).
        artifact_hash: Hex SHA256 of the pipeline stage artifact payload.
        timestamp:     ISO8601 timestamp string.

    Returns:
        Lowercase hex SHA256 string.
    """
    raw = prev_hash + artifact_hash + timestamp
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_last_record(log_path: str) -> Optional[Dict[str, Any]]:
    """
    Read the last record from the log file without loading the entire file.

    Reads the file in 4 KiB blocks from the end to locate the last newline.

    Args:
        log_path: Path to the audit chain log file.

    Returns:
        Parsed dict of the last record, or None if file is empty / missing.
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
            last_line = b""

            # Walk backwards to find the last non-empty line
            while pos > 0:
                read_size = min(block_size, pos)
                pos -= read_size
                fh.seek(pos)
                block = fh.read(read_size)

                # Split on newlines and take tail
                combined = block + last_line
                lines = combined.split(b"\n")

                # The last element may be partial — carry it forward
                last_line = lines[0]
                non_empty = [ln.strip() for ln in lines[1:] if ln.strip()]
                if non_empty:
                    return json.loads(non_empty[-1].decode("utf-8"))

            # Only one line / no newline found
            if last_line.strip():
                return json.loads(last_line.strip().decode("utf-8"))

    except (json.JSONDecodeError, OSError) as exc:
        logger.error(f"[HASH_CHAIN] Failed to read last record from {log_path}: {exc}")

    return None


# ─── Public API ───────────────────────────────────────────────────────────────

def append_record(
    artifact_hash: str,
    log_path: str = _DEFAULT_LOG_PATH,
) -> Dict[str, Any]:
    """
    Append a new record to the audit chain log.

    Reads the last record to obtain prev_hash and record_index, computes
    the new record_hash, then appends one JSON line.

    The file is ALWAYS opened with mode 'a' (append).  No seek, no truncate,
    no overwrite is possible through this function.

    Args:
        artifact_hash: Hex SHA256 of the pipeline stage artifact (stage_hash).
        log_path:      Path to the audit chain log file.

    Returns:
        The newly written record dict.

    Raises:
        ValueError: If artifact_hash is not a 64-char hex string.
        OSError:    If the log file cannot be opened for appending.
    """
    # Validate artifact_hash format
    if not artifact_hash or len(artifact_hash) != 64:
        raise ValueError(
            f"artifact_hash must be a 64-character hex string, got: {repr(artifact_hash)}"
        )

    # Obtain previous chain state
    last_record = _read_last_record(log_path)
    if last_record is None:
        prev_hash = _GENESIS_HASH
        record_index = 0
    else:
        prev_hash = last_record["record_hash"]
        record_index = last_record["record_index"] + 1

    # Build new record
    timestamp = datetime.now(timezone.utc).isoformat()
    record_hash = _compute_record_hash(prev_hash, artifact_hash, timestamp)

    record: Dict[str, Any] = {
        "record_index": record_index,
        "prev_hash": prev_hash,
        "artifact_hash": artifact_hash,
        "timestamp": timestamp,
        "record_hash": record_hash,
    }

    # Append-only write — mode 'a' guarantees no rewrite
    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError as exc:
        logger.error(f"[HASH_CHAIN] Failed to append record to {log_path}: {exc}")
        raise

    logger.debug(
        f"[HASH_CHAIN] Appended record #{record_index}: "
        f"artifact={artifact_hash[:16]}... record_hash={record_hash[:16]}..."
    )

    return record


def _verify_chain_detail(log_path: str) -> Dict[str, Any]:
    """
    Internal: replay log and return detailed verification report.

    For each record checks:
      1. record_hash == sha256(prev_hash + artifact_hash + timestamp)
      2. prev_hash   == previous record's record_hash (or GENESIS for index 0)
      3. record_index is strictly monotone from 0

    Returns:
        Dict with keys:
          - "valid":           bool
          - "total_records":   int
          - "first_broken_at": Optional[int]
          - "errors":          List[str]
    """
    errors: list[str] = []
    total = 0
    first_broken: Optional[int] = None
    expected_prev = _GENESIS_HASH
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
                    err = f"Record {total}: JSON parse error — {exc}"
                    errors.append(err)
                    if first_broken is None:
                        first_broken = total
                    total += 1
                    continue

                idx = rec.get("record_index", -1)

                # Index monotonicity
                if idx != expected_index:
                    err = (
                        f"Record {total}: expected index {expected_index}, got {idx}"
                    )
                    errors.append(err)
                    if first_broken is None:
                        first_broken = idx

                # prev_hash linkage
                if rec.get("prev_hash") != expected_prev:
                    err = (
                        f"Record {idx}: prev_hash mismatch — "
                        f"expected {expected_prev[:16]}... "
                        f"got {str(rec.get('prev_hash', ''))[:16]}..."
                    )
                    errors.append(err)
                    if first_broken is None:
                        first_broken = idx

                # record_hash integrity
                computed = _compute_record_hash(
                    rec.get("prev_hash", ""),
                    rec.get("artifact_hash", ""),
                    rec.get("timestamp", ""),
                )
                if computed != rec.get("record_hash"):
                    err = (
                        f"Record {idx}: record_hash tampered — "
                        f"computed {computed[:16]}... "
                        f"stored {str(rec.get('record_hash', ''))[:16]}..."
                    )
                    errors.append(err)
                    if first_broken is None:
                        first_broken = idx

                expected_prev = rec.get("record_hash", "")
                expected_index = idx + 1
                total += 1

    except OSError as exc:
        errors.append(f"Cannot read log file: {exc}")

    return {
        "valid": len(errors) == 0,
        "total_records": total,
        "first_broken_at": first_broken,
        "errors": errors,
    }


def verify_chain(log_path: str = _DEFAULT_LOG_PATH) -> str:
    """
    Verify the integrity of the audit chain log.

    Replays every record and checks:
      1. record_hash == sha256(prev_hash + artifact_hash + timestamp)
      2. prev_hash   links back to the previous record's record_hash
         (genesis record uses sha256("GENESIS") as prev_hash)
      3. record_index increments monotonically from 0

    Args:
        log_path: Path to the audit chain log file.

    Returns:
        "VALID" if the entire chain passes all checks, or
        "INVALID at record_index N" where N is the zero-based index of the
        first broken record detected.

    Examples:
        >>> verify_chain("audit_chain.log")
        'VALID'

        >>> verify_chain("tampered.log")
        'INVALID at record_index 2'
    """
    detail = _verify_chain_detail(log_path)

    if detail["valid"]:
        logger.info(
            f"[HASH_CHAIN] Chain VALID: {detail['total_records']} records verified"
        )
        return "VALID"

    broken_at = detail["first_broken_at"]
    result = f"INVALID at record_index {broken_at}"
    logger.warning(
        f"[HASH_CHAIN] Chain {result} — "
        f"errors: {detail['errors']}"
    )
    return result

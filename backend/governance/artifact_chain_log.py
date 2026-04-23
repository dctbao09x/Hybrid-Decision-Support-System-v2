# backend/governance/artifact_chain_log.py
"""
Artifact Chain Logger — Prompt-14
==================================

Persists one JSONL record per decision capturing:
  - trace_id
  - schema_hash (from VersionBundle)
  - model_version / rule_version / taxonomy_version / schema_version
  - artifact_chain_root (SHA-256 root from pipeline artifact chain)
  - stage_count
  - logged_at (ISO-8601 UTC)

This gives an immutable audit trail linking every decision to the exact
versions of all four components that produced it.

FILE LOCATION
-------------
``data/governance/artifact_chain_log.jsonl``  (one line per decision)

THREAD SAFETY
-------------
Writes are serialised through a module-level threading.Lock so this logger
is safe for concurrent ASGI requests.

USAGE (inside decision_controller.run_pipeline)::

    from backend.governance.artifact_chain_log import log_artifact_chain
    from backend.governance.version_resolver import VersionBundle

    log_artifact_chain(
        trace_id            = trace_id,
        versions            = version_bundle,
        artifact_chain_root = chain_root,
        stage_count         = len(artifact_chain.artifacts),
    )
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("governance.artifact_chain_log")

# ─── Storage path ─────────────────────────────────────────────────────────────

_DEFAULT_PATH = Path("data/governance/artifact_chain_log.jsonl")

_lock = threading.Lock()
_log_path: Optional[Path] = None


def _get_log_path() -> Path:
    global _log_path
    if _log_path is None:
        env_path = os.environ.get("ARTIFACT_CHAIN_LOG_PATH")
        _log_path = Path(env_path) if env_path else _DEFAULT_PATH
    return _log_path


def set_log_path(path: "str | Path") -> None:
    """Override the JSONL file path (useful for tests)."""
    global _log_path
    _log_path = Path(path)


# ─── Record schema ─────────────────────────────────────────────────────────────

@dataclass
class ArtifactChainRecord:
    """
    Single artifact chain log entry.

    Fields
    ------
    trace_id            : Decision trace ID (``dec-*``).
    model_version       : Active ML model version.
    rule_version        : SHA-256 fingerprint of the rule set (first 16 chars).
    taxonomy_version    : SHA-256 fingerprint of taxonomy data (first 16 chars).
    schema_version      : JSON schema semver (e.g. ``response-v4.0``).
    schema_hash         : Combined SHA-256 of all four version strings.
    artifact_chain_root : SHA-256 root of the pipeline stage artifact chain.
    stage_count         : Number of stages completed.
    logged_at           : ISO-8601 UTC timestamp.
    """
    trace_id:            str
    model_version:       str
    rule_version:        str
    taxonomy_version:    str
    schema_version:      str
    schema_hash:         str
    artifact_chain_root: str
    stage_count:         int
    logged_at:           str

    def to_jsonl_line(self) -> str:
        """Serialize to a single JSON line (no newline appended)."""
        return json.dumps(asdict(self), separators=(",", ":"))


# ─── Logger class ─────────────────────────────────────────────────────────────

class ArtifactChainLogger:
    """
    JSONL-backed artifact chain logger with fault-tolerant writes.

    Parameters
    ----------
    path: str | Path
        Path to the JSONL file.  Parent directories are created on first write.
    """

    def __init__(self, path: "str | Path | None" = None) -> None:
        self._path: Path = Path(path) if path else _get_log_path()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, record: ArtifactChainRecord) -> bool:
        """
        Append one record to the JSONL file.

        Returns
        -------
        bool
            True on success, False if the write failed (error is logged).
        """
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = record.to_jsonl_line() + "\n"
            with _lock:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
            return True
        except Exception as exc:
            logger.error("ArtifactChainLogger.append failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return the number of records in the log (0 if file missing)."""
        try:
            if not self._path.exists():
                return 0
            with self._path.open("r", encoding="utf-8") as fh:
                return sum(1 for line in fh if line.strip())
        except Exception:
            return 0

    def read_all(self) -> list:
        """Return all records as a list of dicts (empty list on error)."""
        if not self._path.exists():
            return []
        records = []
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass  # skip malformed lines
        except Exception as exc:
            logger.error("ArtifactChainLogger.read_all failed: %s", exc)
        return records

    def find_by_trace_id(self, trace_id: str) -> list:
        """Return all records matching *trace_id*."""
        return [r for r in self.read_all() if r.get("trace_id") == trace_id]

    def find_by_schema_hash(self, schema_hash: str) -> list:
        """Return all records matching *schema_hash*."""
        return [r for r in self.read_all() if r.get("schema_hash") == schema_hash]


# ─── Singleton ────────────────────────────────────────────────────────────────

_logger_instance: Optional[ArtifactChainLogger] = None


def get_artifact_chain_logger() -> ArtifactChainLogger:
    """Return the module-level ArtifactChainLogger singleton."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = ArtifactChainLogger()
    return _logger_instance


# ─── Convenience function ─────────────────────────────────────────────────────

def log_artifact_chain(
    trace_id: str,
    versions: "object",   # VersionBundle (avoids circular import)
    artifact_chain_root: str,
    stage_count: int,
) -> bool:
    """
    Convenience wrapper used by ``DecisionController.run_pipeline()``.

    Parameters
    ----------
    trace_id            : Decision trace ID.
    versions            : ``VersionBundle`` from ``version_resolver.resolve_versions()``.
    artifact_chain_root : SHA-256 root from ``ArtifactChain.compute_chain_root()``.
    stage_count         : Number of pipeline stages completed.

    Returns
    -------
    bool
        True if the record was written successfully.
    """
    try:
        record = ArtifactChainRecord(
            trace_id            = trace_id,
            model_version       = getattr(versions, "model_version", "unknown"),
            rule_version        = getattr(versions, "rule_version", "unknown"),
            taxonomy_version    = getattr(versions, "taxonomy_version", "unknown"),
            schema_version      = getattr(versions, "schema_version", "unknown"),
            schema_hash         = getattr(versions, "schema_hash", "unknown"),
            artifact_chain_root = artifact_chain_root,
            stage_count         = stage_count,
            logged_at           = datetime.now(timezone.utc).isoformat(),
        )
        return get_artifact_chain_logger().append(record)
    except Exception as exc:
        logger.error("log_artifact_chain failed: %s", exc)
        return False

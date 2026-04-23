"""
test_hash_chain_gate.py
───────────────────────────────────────────────────────────────────────────────
CI Gate: Hash-chain integrity verification.

GUARANTEE: verify_chain("audit_chain.log") returns "VALID".

Any other result means at least one audit record was:
  • tampered (payload modified after write)
  • injected (record inserted without valid prev_hash linkage)
  • truncated (record deleted mid-chain)

A broken chain is a CRITICAL security event — the merge gate blocks immediately.

Reference: backend/api/hash_chain_logger.py, production-hardening-2026-02-21
───────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# ─── Ensure project root is importable ───────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.api.hash_chain_logger import append_record, verify_chain  # type: ignore

# ─── Paths ───────────────────────────────────────────────────────────────────

_WORKSPACE_ROOT = Path(__file__).parent.parent.resolve()
_LIVE_LOG = _WORKSPACE_ROOT / "audit_chain.log"

_GENESIS_HASH = hashlib.sha256(b"GENESIS").hexdigest()


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _build_clean_chain(path: Path, n: int = 5) -> None:
    """Write an *n*-record clean chain to *path*."""
    for i in range(n):
        fake_artifact_hash = hashlib.sha256(f"artifact_{i}".encode()).hexdigest()
        append_record(fake_artifact_hash, log_path=str(path))


def _tamper_record(path: Path, record_index: int, field: str, new_value: str) -> None:
    """Overwrite *field* in the record at *record_index* (0-based) with *new_value*."""
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[record_index])
    record[field] = new_value
    lines[record_index] = json.dumps(record, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ─── Tests ───────────────────────────────────────────────────────────────────


class TestHashChainGate:
    """Hash-chain integrity gate — all variants must pass."""

    # ------------------------------------------------------------------
    # Live chain
    # ------------------------------------------------------------------

    def test_live_chain_is_valid(self) -> None:
        """
        The production audit_chain.log on disk must be VALID.
        This is the primary CI gate check.
        """
        if not _LIVE_LOG.exists():
            pytest.skip("audit_chain.log not present — skipping live chain check")

        result = verify_chain(str(_LIVE_LOG))
        assert result == "VALID", (
            f"LIVE AUDIT CHAIN IS BROKEN: {result}\n"
            f"Log path: {_LIVE_LOG}\n"
            f"This is a CRITICAL security event — investigate immediately."
        )

    # ------------------------------------------------------------------
    # Clean synthetic chain
    # ------------------------------------------------------------------

    def test_clean_chain_passes(self) -> None:
        """A freshly written chain must verify as VALID."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            tmp = Path(f.name)
        try:
            _build_clean_chain(tmp, n=6)
            result = verify_chain(str(tmp))
            assert result == "VALID", f"Clean chain failed: {result}"
        finally:
            tmp.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Tampering detection
    # ------------------------------------------------------------------

    def test_tampered_artifact_hash_detected(self) -> None:
        """Modifying artifact_hash in any record must invalidate the chain."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            tmp = Path(f.name)
        try:
            _build_clean_chain(tmp, n=5)
            _tamper_record(tmp, record_index=2, field="artifact_hash", new_value="deadbeef" * 8)
            result = verify_chain(str(tmp))
            assert result != "VALID", "Tampered artifact_hash was not detected — chain verification is broken"
            assert "INVALID" in result, f"Expected INVALID message, got: {result}"
        finally:
            tmp.unlink(missing_ok=True)

    def test_tampered_prev_hash_detected(self) -> None:
        """Breaking the prev_hash linkage must invalidate the chain."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            tmp = Path(f.name)
        try:
            _build_clean_chain(tmp, n=5)
            _tamper_record(tmp, record_index=3, field="prev_hash", new_value="00" * 32)
            result = verify_chain(str(tmp))
            assert result != "VALID", "Broken prev_hash linkage was not detected"
            assert "INVALID" in result
        finally:
            tmp.unlink(missing_ok=True)

    def test_injected_record_detected(self) -> None:
        """A record inserted with an invalid prev_hash must be caught."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            tmp = Path(f.name)
        try:
            _build_clean_chain(tmp, n=4)
            # Append a forged record with a garbage prev_hash
            forged = {
                "record_index": 4,
                "prev_hash": "forged_prev_hash",
                "artifact_hash": hashlib.sha256(b"forged").hexdigest(),
                "timestamp": "1970-01-01T00:00:00+00:00",
                "record_hash": "forged_record_hash",
            }
            with tmp.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(forged) + "\n")
            result = verify_chain(str(tmp))
            assert result != "VALID", "Injected record with forged prev_hash was not detected"
        finally:
            tmp.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_missing_log_returns_invalid(self) -> None:
        """verify_chain on a non-existent file must not raise — returns INVALID."""
        result = verify_chain("/tmp/does_not_exist_abc123.log")
        assert result != "VALID", f"Missing log returned VALID unexpectedly: {result}"

    def test_empty_log_returns_valid(self) -> None:
        """An empty log file (genesis state) is trivially valid — no records to break."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            tmp = Path(f.name)
        try:
            tmp.write_text("", encoding="utf-8")
            result = verify_chain(str(tmp))
            # Empty chain → VALID (nothing to verify, genesis intact)
            assert result == "VALID", f"Empty chain returned: {result}"
        finally:
            tmp.unlink(missing_ok=True)

    def test_single_record_chain_valid(self) -> None:
        """A chain with exactly one record must verify as VALID."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            tmp = Path(f.name)
        try:
            _build_clean_chain(tmp, n=1)
            result = verify_chain(str(tmp))
            assert result == "VALID", f"Single-record chain returned: {result}"
        finally:
            tmp.unlink(missing_ok=True)

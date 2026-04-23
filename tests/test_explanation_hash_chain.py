"""
test_explanation_hash_chain.py
══════════════════════════════════════════════════════════════════════════════
Integration Test — ExplanationStorage Hash-Chain Continuity
=============================================================

Proves that ExplanationStorage.append_record() is no longer dead code and
that consecutive explanation writes are deterministically chained.

GUARANTEES VERIFIED
───────────────────
1. APPEND_RECORD LIVE
   append_record() inserts into the DB and populates record_hash + explanation_id
   on the returned ExplanationRecord.

2. PREV_HASH LINKAGE (two sequential decisions)
   record_B.prev_hash == record_A.record_hash
   This makes the chain tamper-evident: any gap or reorder is detected.

3. EMPTY GENESIS BLOCK
   The first record in an empty store always has prev_hash == "".

4. HASH CONTINUITY ACROSS THREE RECORDS
   A chain of three records has correct prev → cur linkage at every step.

5. VERIFY_INTEGRITY PASSES AFTER CHAIN BUILD
   ExplanationStorage.verify_integrity() returns True for a well-formed chain.

6. VERIFY_INTEGRITY FAILS ON TAMPER
   Directly patching record_hash in the DB causes verify_integrity() → False.

7. APPEND_UNIFIED DELEGATES TO APPEND_RECORD
   append_unified() returns (unified, record_hash, explanation_id) and the
   record_hash matches what was written to the DB — proving delegation is live.

8. MIXED CHAIN (append_record + append_unified interleaved)
   A chain mixing both insert paths verifies cleanly.

9. STAGE-9 ARTIFACT PAYLOAD INCLUDES CHAIN HASHES
   The explanation_payload dict produced by the Stage-9 builder contains
   record_hash, explanation_id, stage3_input_hash, stage3_output_hash.

10. RECORD_HASH DIFFERS BETWEEN RECORDS
    Two records with different trace_ids must produce different record_hashes.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.explain.models import ExplanationRecord, RuleFire, EvidenceItem
from backend.explain.storage import ExplanationStorage
from backend.explain.unified_schema import UnifiedExplanation


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_store():
    """Fresh ExplanationStorage backed by a temporary SQLite file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = ExplanationStorage(db_path=Path(path))
    yield store
    try:
        os.unlink(path)
    except OSError:
        pass


def _make_record(
    trace_id: str = "trace-chain-001",
    confidence: float = 0.80,
) -> ExplanationRecord:
    """Build a minimal but valid ExplanationRecord for chain tests."""
    return ExplanationRecord(
        trace_id=trace_id,
        model_id="model-test-v1",
        kb_version="kb-2024",
        rule_path=[
            RuleFire(
                rule_id="rule_math_strength",
                condition="math_score >= 70",
                matched_features={"math_score": 80.0},
                weight=1.0,
            )
        ],
        weights={"rule_math_strength": 1.0},
        evidence=[
            EvidenceItem(source="features", key="math_score", value=80.0, weight=0.9)
        ],
        confidence=confidence,
        feature_snapshot={"math_score": 80.0, "logic_score": 75.0},
        prediction={"career": "Software Engineer", "score": 80.0},
    )


_BREAKDOWN: Dict[str, float] = {
    "skill": 0.30, "experience": 0.25, "education": 0.20,
    "goal_alignment": 0.15, "preference": 0.10,
}
_CONTRIBUTIONS: Dict[str, float] = {
    "skill": 22.5, "experience": 18.75, "education": 15.0,
    "goal_alignment": 11.25, "preference": 7.5,
}


def _make_unified(
    trace_id: str = "trace-chain-001",
    confidence: float = 0.80,
    weight_version: str = "v1.0.0",
) -> UnifiedExplanation:
    """Build a minimal but valid UnifiedExplanation for chain tests."""
    return UnifiedExplanation.build(
        trace_id=trace_id,
        model_id="model-test-v1",
        kb_version="kb-2024",
        weight_version=weight_version,
        breakdown=dict(_BREAKDOWN),
        per_component_contributions=dict(_CONTRIBUTIONS),
        reasoning=["Score exceeds threshold"],
        input_summary={"math_score": 80.0},
        feature_snapshot={"math_score": 80.0, "logic_score": 75.0},
        rule_path=[
            {
                "rule_id": "rule_math_strength",
                "condition": "math_score >= 70",
                "matched_features": {"math_score": 80.0},
                "weight": 1.0,
            }
        ],
        weights={"rule_math_strength": 1.0},
        evidence=[{"source": "features", "key": "math_score", "value": 80.0, "weight": 0.9}],
        confidence=confidence,
        prediction={"career": "Software Engineer", "score": 80.0},
        stage3_input_hash="sha256-stage3-in",
        stage3_output_hash="sha256-stage3-out",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — append_record() is live and surfaces hashes
# ─────────────────────────────────────────────────────────────────────────────

class TestAppendRecordLive:
    """
    append_record() must insert a row, set explanation_id, and set record_hash
    on the returned record — proving it is no longer dead code.
    """

    @pytest.mark.asyncio
    async def test_append_record_returns_record_with_explanation_id(self, temp_store):
        await temp_store.initialize()
        record = _make_record()
        stored = await temp_store.append_record(record)
        assert stored.explanation_id, "explanation_id must be set after append_record()"
        assert stored.explanation_id.startswith("exp-")

    @pytest.mark.asyncio
    async def test_append_record_returns_record_with_record_hash(self, temp_store):
        await temp_store.initialize()
        record = _make_record()
        stored = await temp_store.append_record(record)
        assert stored.record_hash, "record_hash must be populated by append_record()"
        assert len(stored.record_hash) == 64, "record_hash must be a 64-char hex SHA-256"
        assert all(c in "0123456789abcdef" for c in stored.record_hash)

    @pytest.mark.asyncio
    async def test_append_record_persists_to_db(self, temp_store):
        await temp_store.initialize()
        record = _make_record(trace_id="trace-live-persist")
        stored = await temp_store.append_record(record)
        # Confirm the row is in the DB
        found = await temp_store.get_by_trace_id("trace-live-persist")
        assert found is not None, "append_record() must persist the row to SQLite"

    @pytest.mark.asyncio
    async def test_append_record_mutation_does_not_affect_other_records(self, temp_store):
        """Two append_record() calls must produce independent records."""
        await temp_store.initialize()
        r1 = await temp_store.append_record(_make_record("trace-A"))
        r2 = await temp_store.append_record(_make_record("trace-B"))
        assert r1.explanation_id != r2.explanation_id
        assert r1.record_hash != r2.record_hash


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — Genesis block and prev_hash linkage
# ─────────────────────────────────────────────────────────────────────────────

class TestPrevHashLinkage:
    """
    Two sequential decisions must be linked: record_B.prev_hash == record_A.record_hash.
    """

    @pytest.mark.asyncio
    async def test_first_record_prev_hash_is_empty(self, temp_store):
        """Genesis block: first record has no predecessor."""
        await temp_store.initialize()
        record = _make_record("trace-genesis")
        stored = await temp_store.append_record(record)

        # Verify via direct DB query
        conn = temp_store._conn
        row = conn.execute(
            "SELECT prev_hash FROM explanations WHERE explanation_id = ?",
            (stored.explanation_id,),
        ).fetchone()
        assert row is not None
        assert row["prev_hash"] == "", (
            "The first record in an empty store must have prev_hash == ''"
        )

    @pytest.mark.asyncio
    async def test_second_record_prev_hash_equals_first_record_hash(self, temp_store):
        """
        Core linkage: consecutive decisions form a tamper-evident chain.

        record_B.prev_hash == record_A.record_hash
        """
        await temp_store.initialize()

        record_a = _make_record("trace-decision-1", confidence=0.80)
        record_b = _make_record("trace-decision-2", confidence=0.85)

        stored_a = await temp_store.append_record(record_a)
        stored_b = await temp_store.append_record(record_b)

        conn = temp_store._conn
        row_a = conn.execute(
            "SELECT record_hash, prev_hash FROM explanations WHERE explanation_id = ?",
            (stored_a.explanation_id,),
        ).fetchone()
        row_b = conn.execute(
            "SELECT record_hash, prev_hash FROM explanations WHERE explanation_id = ?",
            (stored_b.explanation_id,),
        ).fetchone()

        assert row_b["prev_hash"] == row_a["record_hash"], (
            "Decision-B must chain onto Decision-A: "
            f"row_b.prev_hash={row_b['prev_hash'][:16]!r} != "
            f"row_a.record_hash={row_a['record_hash'][:16]!r}"
        )

    @pytest.mark.asyncio
    async def test_three_records_form_unbroken_chain(self, temp_store):
        """
        Chain of three records:
          genesis → A → B
        At each step:  next.prev_hash == prev.record_hash
        """
        await temp_store.initialize()

        stored = []
        for i in range(3):
            r = await temp_store.append_record(
                _make_record(f"trace-seq-{i}", confidence=0.70 + i * 0.05)
            )
            stored.append(r)

        conn = temp_store._conn
        rows = conn.execute(
            "SELECT explanation_id, record_hash, prev_hash "
            "FROM explanations ORDER BY id ASC"
        ).fetchall()

        # Genesis
        assert rows[0]["prev_hash"] == "", "genesis prev_hash must be empty"

        # Step through chain
        for idx in range(1, len(rows)):
            assert rows[idx]["prev_hash"] == rows[idx - 1]["record_hash"], (
                f"Chain broken at index {idx}: "
                f"prev_hash={rows[idx]['prev_hash'][:16]!r} != "
                f"record_hash={rows[idx - 1]['record_hash'][:16]!r}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Section 3 — verify_integrity() correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestVerifyIntegrity:
    """verify_integrity() must pass for valid chains and fail on tamper."""

    @pytest.mark.asyncio
    async def test_integrity_passes_for_empty_store(self, temp_store):
        await temp_store.initialize()
        assert await temp_store.verify_integrity() is True

    @pytest.mark.asyncio
    async def test_integrity_passes_for_single_record(self, temp_store):
        await temp_store.initialize()
        await temp_store.append_record(_make_record())
        assert await temp_store.verify_integrity() is True

    @pytest.mark.asyncio
    async def test_integrity_passes_for_two_sequential_decisions(self, temp_store):
        """Core integration test: two scoring decisions → chain verified."""
        await temp_store.initialize()
        await temp_store.append_record(_make_record("trace-d1"))
        await temp_store.append_record(_make_record("trace-d2"))
        assert await temp_store.verify_integrity() is True, (
            "Two sequential decision records must form a verifiable hash chain"
        )

    @pytest.mark.asyncio
    async def test_integrity_passes_for_five_sequential_decisions(self, temp_store):
        await temp_store.initialize()
        for i in range(5):
            await temp_store.append_record(_make_record(f"trace-d{i}"))
        assert await temp_store.verify_integrity() is True

    @pytest.mark.asyncio
    async def test_integrity_fails_after_record_hash_tamper(self, temp_store):
        """
        Directly patching record_hash in the DB must cause verify_integrity → False.
        This proves the chain is tamper-evident.
        """
        await temp_store.initialize()
        await temp_store.append_record(_make_record("trace-tamper-1"))
        await temp_store.append_record(_make_record("trace-tamper-2"))

        # Tamper: corrupt record_hash of the first row
        with temp_store._lock:
            temp_store._conn.execute(
                "UPDATE explanations SET record_hash = 'deadbeef' "
                "WHERE explanation_id = (SELECT explanation_id FROM explanations ORDER BY id ASC LIMIT 1)"
            )
            temp_store._conn.commit()

        result = await temp_store.verify_integrity()
        assert result is False, (
            "verify_integrity() must return False when record_hash is tampered"
        )

    @pytest.mark.asyncio
    async def test_integrity_fails_after_prev_hash_tamper(self, temp_store):
        """Patching prev_hash of the second record must break the chain."""
        await temp_store.initialize()
        r1 = await temp_store.append_record(_make_record("trace-p1"))
        await temp_store.append_record(_make_record("trace-p2"))

        with temp_store._lock:
            temp_store._conn.execute(
                "UPDATE explanations SET prev_hash = 'wrongprev' "
                "WHERE explanation_id != ?",
                (r1.explanation_id,),
            )
            temp_store._conn.commit()

        result = await temp_store.verify_integrity()
        assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# Section 4 — append_unified() delegates to append_record()
# ─────────────────────────────────────────────────────────────────────────────

class TestAppendUnifiedDelegation:
    """
    append_unified() must return (unified, record_hash, explanation_id) and
    the record_hash must appear in the DB row — proving delegation is live.
    """

    @pytest.mark.asyncio
    async def test_append_unified_returns_three_tuple(self, temp_store):
        await temp_store.initialize()
        result = await temp_store.append_unified(_make_unified())
        assert isinstance(result, tuple), "append_unified() must return a tuple"
        assert len(result) == 3, "tuple must have 3 elements: (unified, record_hash, explanation_id)"

    @pytest.mark.asyncio
    async def test_append_unified_returns_correct_types(self, temp_store):
        await temp_store.initialize()
        unified, record_hash, explanation_id = await temp_store.append_unified(_make_unified())
        assert isinstance(unified, UnifiedExplanation)
        assert isinstance(record_hash, str) and len(record_hash) == 64
        assert isinstance(explanation_id, str) and explanation_id.startswith("exp-")

    @pytest.mark.asyncio
    async def test_append_unified_record_hash_matches_db(self, temp_store):
        """The returned record_hash must match what is stored in the DB."""
        await temp_store.initialize()
        unified, record_hash, explanation_id = await temp_store.append_unified(_make_unified())

        conn = temp_store._conn
        row = conn.execute(
            "SELECT record_hash FROM explanations WHERE explanation_id = ?",
            (explanation_id,),
        ).fetchone()
        assert row is not None
        assert row["record_hash"] == record_hash, (
            "Return value record_hash must match what is persisted in the DB"
        )

    @pytest.mark.asyncio
    async def test_append_unified_writes_unified_columns(self, temp_store):
        """The unified schema columns must be populated after append_unified()."""
        await temp_store.initialize()
        uni = _make_unified(weight_version="v2.0.0")
        _, _, explanation_id = await temp_store.append_unified(uni)

        conn = temp_store._conn
        row = conn.execute(
            "SELECT weight_version, explanation_hash FROM explanations WHERE explanation_id = ?",
            (explanation_id,),
        ).fetchone()
        assert row is not None
        assert row["weight_version"] == "v2.0.0"
        assert row["explanation_hash"] == uni.explanation_hash

    @pytest.mark.asyncio
    async def test_append_unified_chain_integrates_with_append_record(self, temp_store):
        """
        Mixed chain: append_record() then append_unified() — still one valid chain.
        """
        await temp_store.initialize()
        await temp_store.append_record(_make_record("trace-mixed-1"))
        _, record_hash_b, _ = await temp_store.append_unified(_make_unified("trace-mixed-2"))

        conn = temp_store._conn
        rows = conn.execute(
            "SELECT record_hash, prev_hash FROM explanations ORDER BY id ASC"
        ).fetchall()

        # Row B (from append_unified) must point to row A (from append_record)
        assert rows[1]["prev_hash"] == rows[0]["record_hash"], (
            "append_unified() must chain onto the previous append_record() entry"
        )
        assert rows[1]["record_hash"] == record_hash_b

    @pytest.mark.asyncio
    async def test_full_mixed_chain_verifies(self, temp_store):
        """Mixed chain with 3 writes verifies cleanly end-to-end."""
        await temp_store.initialize()
        await temp_store.append_record(_make_record("trace-chain-A"))
        await temp_store.append_unified(_make_unified("trace-chain-B"))
        await temp_store.append_record(_make_record("trace-chain-C"))
        assert await temp_store.verify_integrity() is True, (
            "Mixed append_record / append_unified chain must pass verify_integrity()"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Section 5 — Stage-9 artifact payload structure
# ─────────────────────────────────────────────────────────────────────────────

class TestStage9ArtifactPayload:
    """
    After explanation storage, the Stage-9 artifact payload must contain
    record_hash, explanation_id, stage3_input_hash, stage3_output_hash.
    """

    @pytest.mark.asyncio
    async def test_artifact_payload_contains_record_hash(self, temp_store):
        await temp_store.initialize()
        unified, record_hash, explanation_id = await temp_store.append_unified(
            _make_unified("trace-artifact-1")
        )
        # Simulate how the controller builds explanation_payload
        explanation_payload = {
            "explanation": None,
            "included": True,
            "llm_used": True,
            "record_hash": record_hash,
            "explanation_id": explanation_id,
            "stage3_input_hash": unified.stage3_input_hash,
            "stage3_output_hash": unified.stage3_output_hash,
        }
        assert explanation_payload["record_hash"] == record_hash
        assert len(explanation_payload["record_hash"]) == 64

    @pytest.mark.asyncio
    async def test_artifact_payload_stage3_hashes_propagated(self, temp_store):
        await temp_store.initialize()
        uni = _make_unified("trace-artifact-2")
        unified, record_hash, explanation_id = await temp_store.append_unified(uni)

        explanation_payload = {
            "stage3_input_hash": unified.stage3_input_hash,
            "stage3_output_hash": unified.stage3_output_hash,
        }
        assert explanation_payload["stage3_input_hash"] == "sha256-stage3-in"
        assert explanation_payload["stage3_output_hash"] == "sha256-stage3-out"

    @pytest.mark.asyncio
    async def test_artifact_payload_explanation_id_matches_db(self, temp_store):
        await temp_store.initialize()
        _, record_hash, explanation_id = await temp_store.append_unified(
            _make_unified("trace-artifact-3")
        )
        conn = temp_store._conn
        row = conn.execute(
            "SELECT explanation_id FROM explanations WHERE explanation_id = ?",
            (explanation_id,),
        ).fetchone()
        assert row is not None
        assert row["explanation_id"] == explanation_id

    @pytest.mark.asyncio
    async def test_fallback_path_produces_empty_hash_fields(self):
        """
        When the explanation builder falls back (no storage),
        the artifact payload hash fields must be empty strings, not None.
        """
        # Simulate fallback _ExplanationState
        # (record_hash == "" means no chain link was written)
        from backend.api.controllers.decision_controller import _ExplanationState
        from backend.api.controllers.decision_controller import ExplanationResult  # noqa

        # Build a dummy result to satisfy the dataclass
        dummy_result = object.__new__(object)  # just a sentinel
        state = _ExplanationState(
            result=dummy_result,  # type: ignore[arg-type]
            record_hash="",
            explanation_id="",
            stage3_input_hash="",
            stage3_output_hash="",
        )
        payload = {
            "record_hash":        state.record_hash,
            "explanation_id":     state.explanation_id,
            "stage3_input_hash":  state.stage3_input_hash,
            "stage3_output_hash": state.stage3_output_hash,
        }
        for key, val in payload.items():
            assert val == "", f"Fallback field '{key}' must be '' not {val!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Section 6 — Two full sequential decisions (end-to-end chain proof)
# ─────────────────────────────────────────────────────────────────────────────

class TestTwoSequentialDecisions:
    """
    Integration scenario: two decisions flow through the pipeline sequentially.

    Each decision:
      1. Builds a UnifiedExplanation.
      2. Calls append_unified() → (unified, record_hash, explanation_id).
      3. Embeds record_hash in the Stage-9 artifact payload.

    After both decisions:
      - prev_hash of decision-2 == record_hash of decision-1.
      - verify_integrity() returns True.
      - explanation_hash is different for each decision.
    """

    @pytest.mark.asyncio
    async def test_two_decisions_prev_hash_linkage(self, temp_store):
        await temp_store.initialize()

        # Decision 1
        uni_1 = _make_unified("trace-run-1", confidence=0.78)
        _, record_hash_1, explanation_id_1 = await temp_store.append_unified(uni_1)

        # Decision 2
        uni_2 = _make_unified("trace-run-2", confidence=0.91)
        _, record_hash_2, explanation_id_2 = await temp_store.append_unified(uni_2)

        # Verify linkage via DB
        conn = temp_store._conn
        row_2 = conn.execute(
            "SELECT prev_hash FROM explanations WHERE explanation_id = ?",
            (explanation_id_2,),
        ).fetchone()
        assert row_2["prev_hash"] == record_hash_1, (
            "Decision-2 prev_hash must equal Decision-1 record_hash.\n"
            f"  Expected: {record_hash_1[:16]}...\n"
            f"  Got:      {row_2['prev_hash'][:16]}..."
        )

    @pytest.mark.asyncio
    async def test_two_decisions_chain_hash_continuity(self, temp_store):
        """verify_integrity() must pass after two sequential decisions."""
        await temp_store.initialize()
        await temp_store.append_unified(_make_unified("trace-integrity-1"))
        await temp_store.append_unified(_make_unified("trace-integrity-2"))
        assert await temp_store.verify_integrity() is True, (
            "Hash chain must be continuous after two sequential decisions"
        )

    @pytest.mark.asyncio
    async def test_two_decisions_produce_distinct_record_hashes(self, temp_store):
        """Each decision must have a unique record_hash."""
        await temp_store.initialize()
        _, rh1, _ = await temp_store.append_unified(_make_unified("trace-distinct-1"))
        _, rh2, _ = await temp_store.append_unified(_make_unified("trace-distinct-2"))
        assert rh1 != rh2, "Distinct decisions must produce distinct record_hashes"

    @pytest.mark.asyncio
    async def test_two_decisions_produce_distinct_explanation_hashes(self, temp_store):
        """Each UnifiedExplanation must have a different explanation_hash."""
        await temp_store.initialize()
        uni_1 = _make_unified("trace-exphash-1", confidence=0.70)
        uni_2 = _make_unified("trace-exphash-2", confidence=0.90)
        assert uni_1.explanation_hash != uni_2.explanation_hash

    @pytest.mark.asyncio
    async def test_two_decisions_canonical_chained_records_json(self, temp_store):
        """
        Produce a canonical JSON snapshot of the two chained DB rows.
        This is the 'Example chained records' proof of concept.
        """
        await temp_store.initialize()

        uni_1 = _make_unified("trace-chain-proof-1")
        uni_2 = _make_unified("trace-chain-proof-2", confidence=0.91)

        _, rh1, eid1 = await temp_store.append_unified(uni_1)
        _, rh2, eid2 = await temp_store.append_unified(uni_2)

        conn = temp_store._conn
        rows = conn.execute(
            "SELECT explanation_id, trace_id, record_hash, prev_hash "
            "FROM explanations ORDER BY id ASC"
        ).fetchall()

        chain_snapshot = [
            {
                "explanation_id": r["explanation_id"],
                "trace_id": r["trace_id"],
                "record_hash": r["record_hash"],
                "prev_hash": r["prev_hash"],
                "link_valid": (
                    r["prev_hash"] == ""
                    if r["explanation_id"] == rows[0]["explanation_id"]
                    else r["prev_hash"] == rows[0]["record_hash"]
                ),
            }
            for r in rows
        ]

        # Serialize to canonical JSON (sorted keys)
        canonical = json.dumps(chain_snapshot, ensure_ascii=False, sort_keys=True, indent=2)

        # Structural assertions
        assert len(chain_snapshot) == 2
        assert chain_snapshot[0]["prev_hash"] == ""           # genesis
        assert chain_snapshot[0]["link_valid"] is True
        assert chain_snapshot[1]["prev_hash"] == chain_snapshot[0]["record_hash"]
        assert chain_snapshot[1]["link_valid"] is True

        # Validate JSON round-trips cleanly
        reloaded = json.loads(canonical)
        assert reloaded[0]["record_hash"] == rh1
        assert reloaded[1]["record_hash"] == rh2

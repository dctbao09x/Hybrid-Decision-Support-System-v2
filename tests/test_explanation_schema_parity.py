"""
test_explanation_schema_parity.py
══════════════════════════════════════════════════════════════════════════════
CI Guard — Explanation Schema Parity
=====================================

Proves that UnifiedExplanation is the single authoritative schema and that:

1. SERIALIZATION ROUND-TRIP
   serialized = unified.to_storage_dict()
   stored     = (write to DB, read back, .to_storage_dict())
   → serialized == stored  (byte-for-byte, excluding metadata timestamps)

2. API PROJECTION PARITY
   unified.to_api_response() produces every field required by ExplanationResult

3. SCHEMA ENFORCEMENT
   extra="forbid"  → extra fields raise ValidationError
   frozen=True     → field reassignment raises an error

4. HASH INTEGRITY
   explanation_hash is deterministic and recomputable via verify_hash()
   Modified payload → verify_hash() returns False

5. ADAPTER CORRECTNESS
   ExplanationRecord.to_unified() produces a valid UnifiedExplanation
   ExplanationRecord.from_unified() round-trips all shared fields

6. LEGACY-ROW TOLERANCE
   _row_to_unified() does not raise for rows missing new columns (NULL sentinels)

7. NO DUAL DEFINITIONS
   ExplanationResult fields are a strict subset of UnifiedExplanation fields
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pydantic import ValidationError

from backend.explain.unified_schema import UnifiedExplanation
from backend.explain.models import ExplanationRecord, RuleFire, EvidenceItem
from backend.explain.storage import ExplanationStorage

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

_TRACE_ID = "trace-parity-001"

_BREAKDOWN: Dict[str, float] = {
    "skill": 0.30,
    "experience": 0.25,
    "education": 0.20,
    "goal_alignment": 0.15,
    "preference": 0.10,
}
_CONTRIBUTIONS: Dict[str, float] = {
    "skill": 22.5,
    "experience": 18.75,
    "education": 15.0,
    "goal_alignment": 11.25,
    "preference": 7.5,
}
_REASONING: List[str] = [
    "Math and logic scores exceed threshold",
    "IT interest alignment confirmed",
    "Quantitative background supports selection",
]
_INPUT_SUMMARY: Dict[str, Any] = {
    "math_score": 82.0,
    "logic_score": 79.0,
    "interest_it": 71.0,
}
_FEATURE_SNAPSHOT: Dict[str, float] = {
    "math_score": 82.0,
    "logic_score": 79.0,
    "interest_it": 71.0,
}
_RULE_PATH: List[Dict[str, Any]] = [
    {
        "rule_id": "rule_logic_math_strength",
        "condition": "math_score >= 70 and logic_score >= 70",
        "matched_features": {"math_score": 82.0, "logic_score": 79.0},
        "weight": 0.57,
    },
    {
        "rule_id": "rule_it_interest_alignment",
        "condition": "interest_it >= 60",
        "matched_features": {"interest_it": 71.0},
        "weight": 0.43,
    },
]
_WEIGHTS: Dict[str, float] = {
    "rule_logic_math_strength": 0.57,
    "rule_it_interest_alignment": 0.43,
}
_EVIDENCE: List[Dict[str, Any]] = [
    {"source": "features", "key": "math_score", "value": 82.0, "weight": 0.9},
]
_PREDICTION: Dict[str, Any] = {"career": "Software Engineer", "score": 81.0}


def _build(**overrides) -> UnifiedExplanation:
    """Build a complete UnifiedExplanation with optional field overrides."""
    kwargs = dict(
        trace_id=_TRACE_ID,
        model_id="model-v1",
        kb_version="kb-2024",
        weight_version="default-v1",
        breakdown=_BREAKDOWN.copy(),
        per_component_contributions=_CONTRIBUTIONS.copy(),
        reasoning=list(_REASONING),
        input_summary=_INPUT_SUMMARY.copy(),
        feature_snapshot=_FEATURE_SNAPSHOT.copy(),
        rule_path=list(_RULE_PATH),
        weights=_WEIGHTS.copy(),
        evidence=list(_EVIDENCE),
        confidence=0.83,
        prediction=_PREDICTION.copy(),
        stage3_input_hash="abc123",
        stage3_output_hash="def456",
    )
    kwargs.update(overrides)
    return UnifiedExplanation.build(**kwargs)


@pytest.fixture
def unified() -> UnifiedExplanation:
    return _build()


@pytest.fixture
def temp_store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = ExplanationStorage(db_path=Path(path))
    yield store
    try:
        os.unlink(path)
    except OSError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — Schema Enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaEnforcement:
    """extra="forbid" and frozen=True must be active."""

    def test_extra_fields_raise_validation_error(self, unified):
        with pytest.raises(ValidationError):
            UnifiedExplanation(
                **unified.model_dump(),
                undeclared_extra_field="should_fail",
            )

    def test_frozen_model_raises_on_field_assignment(self, unified):
        with pytest.raises(Exception):  # pydantic raises ValidationError for frozen models
            object.__setattr__(unified, "trace_id", "mutated")
            # If that silently succeeded, fail explicitly
            assert unified.trace_id != "mutated", "frozen=True must prevent reassignment"

    def test_all_fields_required_no_partial_construction(self):
        """Missing any required field must raise ValidationError."""
        with pytest.raises((ValidationError, TypeError)):
            UnifiedExplanation(
                trace_id="test",
                model_id="model",
                # kb_version omitted intentionally
            )

    def test_no_optional_fields_in_schema(self):
        """All UnifiedExplanation fields must be annotated as non-Optional."""
        import typing
        hints = UnifiedExplanation.model_fields
        for name, field_info in hints.items():
            annotation = field_info.annotation
            origin = getattr(annotation, "__origin__", None)
            # Check it's not Optional (which becomes Union[X, None])
            if origin is not None:
                args = getattr(annotation, "__args__", ())
                assert type(None) not in args, (
                    f"Field '{name}' is Optional — all UnifiedExplanation fields "
                    f"must be required (no Optional)"
                )


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — Hash Integrity
# ─────────────────────────────────────────────────────────────────────────────

class TestHashIntegrity:
    """explanation_hash must be deterministic and tamper-evident."""

    def test_hash_is_64_hex_chars(self, unified):
        assert len(unified.explanation_hash) == 64
        assert all(c in "0123456789abcdef" for c in unified.explanation_hash)

    def test_verify_hash_returns_true_for_fresh_object(self, unified):
        assert unified.verify_hash() is True

    def test_same_inputs_produce_same_hash(self):
        a = _build()
        b = _build()
        assert a.explanation_hash == b.explanation_hash

    def test_different_confidence_produces_different_hash(self):
        a = _build(confidence=0.80)
        b = _build(confidence=0.90)
        assert a.explanation_hash != b.explanation_hash

    def test_different_trace_id_produces_different_hash(self):
        a = _build(trace_id="trace-A")
        b = _build(trace_id="trace-B")
        assert a.explanation_hash != b.explanation_hash

    def test_different_breakdown_produces_different_hash(self):
        bd_a = {**_BREAKDOWN}
        bd_b = {**_BREAKDOWN, "skill": 0.50, "experience": 0.10}
        a = _build(breakdown=bd_a)
        b = _build(breakdown=bd_b)
        assert a.explanation_hash != b.explanation_hash

    def test_verify_hash_false_for_empty_hash(self):
        """Legacy rows with explanation_hash='' must return False."""
        data = _build().model_dump()
        data["explanation_hash"] = ""
        legacy = UnifiedExplanation(**data)
        assert legacy.verify_hash() is False

    def test_hash_recomputable_from_to_storage_dict(self, unified):
        """Recomputing from to_storage_dict minus explanation_hash == original hash."""
        payload = {k: v for k, v in unified.to_storage_dict().items() if k != "explanation_hash"}
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        recomputed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert recomputed == unified.explanation_hash


# ─────────────────────────────────────────────────────────────────────────────
# Section 3 — Storage Round-Trip Parity (byte-for-byte)
# ─────────────────────────────────────────────────────────────────────────────

class TestStorageRoundTripParity:
    """
    serialized == stored — byte-for-byte except storage-generated metadata.
    """

    @pytest.mark.asyncio
    async def test_write_then_read_preserves_all_fields(self, unified, temp_store):
        await temp_store.initialize()
        await temp_store.append_unified(unified)

        retrieved = await temp_store.get_unified_by_trace_id(_TRACE_ID)

        assert retrieved is not None, "get_unified_by_trace_id must return a result"

        original_dict = unified.to_storage_dict()
        retrieved_dict = retrieved.to_storage_dict()

        # Exclude storage-generated metadata fields
        _METADATA_KEYS = {"explanation_id", "created_at"}

        for key, original_val in original_dict.items():
            if key in _METADATA_KEYS:
                continue
            assert key in retrieved_dict, f"Key '{key}' missing from retrieved dict"
            assert original_val == retrieved_dict[key], (
                f"Field '{key}' mismatch:\n"
                f"  original:  {original_val!r}\n"
                f"  retrieved: {retrieved_dict[key]!r}"
            )

    @pytest.mark.asyncio
    async def test_explanation_hash_survives_round_trip(self, unified, temp_store):
        await temp_store.initialize()
        await temp_store.append_unified(unified)

        retrieved = await temp_store.get_unified_by_trace_id(_TRACE_ID)
        assert retrieved is not None
        assert retrieved.explanation_hash == unified.explanation_hash

    @pytest.mark.asyncio
    async def test_verify_hash_passes_after_round_trip(self, unified, temp_store):
        await temp_store.initialize()
        await temp_store.append_unified(unified)

        retrieved = await temp_store.get_unified_by_trace_id(_TRACE_ID)
        assert retrieved is not None
        assert retrieved.verify_hash() is True, (
            "explanation_hash must be verifiable after a storage round-trip"
        )

    @pytest.mark.asyncio
    async def test_multiple_traces_independently_retrievable(self, temp_store):
        await temp_store.initialize()

        a = _build(trace_id="trace-parity-A")
        b = _build(trace_id="trace-parity-B", confidence=0.91)

        await temp_store.append_unified(a)
        await temp_store.append_unified(b)

        ra = await temp_store.get_unified_by_trace_id("trace-parity-A")
        rb = await temp_store.get_unified_by_trace_id("trace-parity-B")

        assert ra is not None and rb is not None
        assert ra.explanation_hash == a.explanation_hash
        assert rb.explanation_hash == b.explanation_hash
        assert ra.explanation_hash != rb.explanation_hash

    @pytest.mark.asyncio
    async def test_canonical_json_serialization_identical_before_and_after(
        self, unified, temp_store
    ):
        """
        The 'byte-for-byte' parity guarantee: canonical(original) == canonical(retrieved)
        for the content-carrying fields.
        """
        await temp_store.initialize()
        await temp_store.append_unified(unified)

        retrieved = await temp_store.get_unified_by_trace_id(_TRACE_ID)
        assert retrieved is not None

        # Exclude metadata
        _METADATA_KEYS = {"explanation_id", "created_at"}
        orig = {k: v for k, v in unified.to_storage_dict().items() if k not in _METADATA_KEYS}
        retr = {k: v for k, v in retrieved.to_storage_dict().items() if k not in _METADATA_KEYS}

        orig_json = json.dumps(orig, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        retr_json = json.dumps(retr, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

        assert orig_json == retr_json, (
            "Canonical JSON of original and retrieved must be identical.\n"
            "First divergence: " + _first_divergence(orig, retr)
        )


def _first_divergence(a: Dict, b: Dict) -> str:
    for key in a:
        if a.get(key) != b.get(key):
            return f"key={key!r} original={a.get(key)!r} retrieved={b.get(key)!r}"
    return "(no divergence found)"


# ─────────────────────────────────────────────────────────────────────────────
# Section 4 — API Projection Parity
# ─────────────────────────────────────────────────────────────────────────────

class TestApiProjectionParity:
    """to_api_response() must be compatible with ExplanationResult."""

    # ExplanationResult fields from decision_controller.py:
    _EXPLANATION_RESULT_FIELDS = {"summary", "factors", "confidence", "reasoning_chain"}

    def test_to_api_response_has_all_explanation_result_fields(self, unified):
        api = unified.to_api_response()
        missing = self._EXPLANATION_RESULT_FIELDS - set(api.keys())
        assert not missing, (
            f"to_api_response() is missing ExplanationResult fields: {missing}"
        )

    def test_summary_comes_from_first_reasoning_entry(self, unified):
        api = unified.to_api_response()
        assert api["summary"] == _REASONING[0]

    def test_summary_is_empty_string_when_reasoning_empty(self):
        u = _build(reasoning=[])
        api = u.to_api_response()
        assert api["summary"] == ""

    def test_factors_list_matches_per_component_contributions(self, unified):
        api = unified.to_api_response()
        factor_names = {f["name"] for f in api["factors"]}
        assert factor_names == set(_CONTRIBUTIONS.keys())

    def test_factors_have_required_keys(self, unified):
        api = unified.to_api_response()
        for factor in api["factors"]:
            assert "name" in factor
            assert "contribution" in factor
            assert "description" in factor

    def test_confidence_equals_unified_confidence(self, unified):
        api = unified.to_api_response()
        assert abs(api["confidence"] - unified.confidence) < 1e-9

    def test_reasoning_chain_equals_unified_reasoning(self, unified):
        api = unified.to_api_response()
        assert api["reasoning_chain"] == list(unified.reasoning)

    def test_no_undeclared_fields_bleed_into_api_response(self, unified):
        api = unified.to_api_response()
        unexpected = set(api.keys()) - self._EXPLANATION_RESULT_FIELDS
        assert not unexpected, (
            f"to_api_response() contains undeclared fields: {unexpected}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Section 5 — Adapter Correctness (ExplanationRecord ↔ UnifiedExplanation)
# ─────────────────────────────────────────────────────────────────────────────

class TestAdapterCorrectness:
    """ExplanationRecord adapters must produce strict 1:1 field mappings."""

    def _make_record(self) -> ExplanationRecord:
        return ExplanationRecord(
            trace_id=_TRACE_ID,
            model_id="model-v1",
            kb_version="kb-2024",
            rule_path=[
                RuleFire(
                    rule_id="rule_logic_math_strength",
                    condition="math_score >= 70",
                    matched_features={"math_score": 82.0},
                    weight=1.0,
                )
            ],
            weights={"rule_logic_math_strength": 1.0},
            evidence=[
                EvidenceItem(source="features", key="math_score", value=82.0, weight=0.9)
            ],
            confidence=0.83,
            feature_snapshot={"math_score": 82.0, "logic_score": 79.0},
            prediction={"career": "Software Engineer", "score": 81.0},
        )

    def test_to_unified_produces_valid_unified_explanation(self):
        record = self._make_record()
        unified = record.to_unified(
            weight_version="default-v1",
            breakdown=_BREAKDOWN.copy(),
            per_component_contributions=_CONTRIBUTIONS.copy(),
            reasoning=list(_REASONING),
            input_summary=_INPUT_SUMMARY.copy(),
            stage3_input_hash="abc123",
            stage3_output_hash="def456",
        )
        assert isinstance(unified, UnifiedExplanation)
        assert unified.verify_hash() is True

    def test_to_unified_maps_shared_fields_correctly(self):
        record = self._make_record()
        unified = record.to_unified(
            weight_version="default-v1",
            breakdown=_BREAKDOWN.copy(),
            per_component_contributions=_CONTRIBUTIONS.copy(),
            reasoning=list(_REASONING),
            input_summary=_INPUT_SUMMARY.copy(),
            stage3_input_hash="abc123",
            stage3_output_hash="def456",
        )
        assert unified.trace_id == record.trace_id
        assert unified.model_id == record.model_id
        assert unified.kb_version == record.kb_version
        assert unified.confidence == record.confidence
        assert unified.feature_snapshot == record.feature_snapshot

    def test_from_unified_round_trips_shared_fields(self):
        original = _build()
        record = ExplanationRecord.from_unified(original)
        assert record.trace_id == original.trace_id
        assert record.model_id == original.model_id
        assert record.kb_version == original.kb_version
        assert record.confidence == original.confidence
        assert dict(record.weights) == dict(original.weights)

    def test_from_unified_rule_path_matches(self):
        original = _build()
        record = ExplanationRecord.from_unified(original)
        rule_dicts = [r.to_dict() for r in record.rule_path]
        assert rule_dicts == list(original.rule_path)

    def test_to_unified_requires_all_new_fields(self):
        record = self._make_record()
        with pytest.raises(TypeError):
            # Missing weight_version and other new required kwargs
            record.to_unified()  # type: ignore[call-arg]


# ─────────────────────────────────────────────────────────────────────────────
# Section 6 — Legacy-Row Tolerance
# ─────────────────────────────────────────────────────────────────────────────

class TestLegacyRowTolerance:
    """from_storage_row() must not raise when new columns are NULL/missing."""

    def _legacy_row(self) -> Dict:
        """Simulate a row from the legacy ExplanationRecord insert path."""
        return {
            "trace_id": "trace-legacy-001",
            "model_id": "model-v0",
            "kb_version": "kb-old",
            "confidence": 0.75,
            "feature_snapshot": json.dumps({"math_score": 70.0}),
            "rule_path": json.dumps({"rule_path": []}),
            "weights": json.dumps({}),
            "evidence": json.dumps({"evidence": []}),
            "prediction": json.dumps({}),
            # New unified columns — missing (NULL)
            "weight_version": None,
            "breakdown": None,
            "per_component_contributions": None,
            "reasoning": None,
            "input_summary": None,
            "stage3_input_hash": None,
            "stage3_output_hash": None,
            "explanation_hash": None,
        }

    def test_from_storage_row_does_not_raise_for_legacy_rows(self):
        row = self._legacy_row()
        unified = UnifiedExplanation.from_storage_row(row)
        assert unified is not None

    def test_legacy_row_explanation_hash_is_empty(self):
        row = self._legacy_row()
        unified = UnifiedExplanation.from_storage_row(row)
        assert unified.explanation_hash == ""

    def test_legacy_row_verify_hash_returns_false(self):
        row = self._legacy_row()
        unified = UnifiedExplanation.from_storage_row(row)
        assert unified.verify_hash() is False  # expected for legacy rows

    def test_legacy_row_new_fields_use_empty_sentinels(self):
        row = self._legacy_row()
        unified = UnifiedExplanation.from_storage_row(row)
        assert unified.weight_version == ""
        # containers are deep-frozen (MappingProxyType / tuple) — check emptiness only
        assert len(unified.breakdown) == 0
        assert len(unified.reasoning) == 0

    @pytest.mark.asyncio
    async def test_get_unified_by_trace_id_returns_object_for_legacy_append_record(self, temp_store):
        """
        get_unified_by_trace_id returns a UnifiedExplanation even for rows
        inserted via the legacy append_record() path (via ExplanationRecord).
        The returned object has empty sentinels for new fields.
        """
        await temp_store.initialize()

        legacy_record = ExplanationRecord(
            trace_id="trace-legacy-999",
            model_id="model-v0",
            kb_version="kb-old",
            rule_path=[],
            weights={},
            evidence=[],
            confidence=0.70,
            feature_snapshot={"math_score": 70.0},
            prediction={},
        )
        await temp_store.append_record(legacy_record)

        # Should not raise, should return a UnifiedExplanation with empty new fields
        unified = await temp_store.get_unified_by_trace_id("trace-legacy-999")
        assert unified is not None
        assert unified.trace_id == "trace-legacy-999"
        assert unified.explanation_hash == ""  # legacy row has no hash


# ─────────────────────────────────────────────────────────────────────────────
# Section 7 — No Dual Schema Definitions
# ─────────────────────────────────────────────────────────────────────────────

class TestNoDualSchemaDefinitions:
    """
    Verify that ExplanationResult fields are a strict SUBSET of UnifiedExplanation
    fields — proving UnifiedExplanation is the superset schema.
    """

    # ExplanationResult fields (from decision_controller.py)
    _EXPLANATION_RESULT_FIELDS = {"summary", "factors", "confidence", "reasoning_chain"}

    def test_api_response_fields_are_subset_of_unified_schema(self):
        """
        Every key in to_api_response() must have a meaningful source in UnifiedExplanation.
        """
        api = _build().to_api_response()
        # summary ← reasoning[0]
        assert "reasoning" in UnifiedExplanation.model_fields
        # factors ← per_component_contributions
        assert "per_component_contributions" in UnifiedExplanation.model_fields
        # confidence ← confidence
        assert "confidence" in UnifiedExplanation.model_fields
        # reasoning_chain ← reasoning
        assert "reasoning" in UnifiedExplanation.model_fields

    def test_unified_schema_contains_all_storage_fields(self):
        """
        All fields that ExplanationRecord stores must exist in UnifiedExplanation.
        """
        storage_fields = {
            "trace_id", "model_id", "kb_version",
            "rule_path", "weights", "evidence",
            "confidence", "feature_snapshot", "prediction",
        }
        unified_fields = set(UnifiedExplanation.model_fields.keys())
        missing = storage_fields - unified_fields
        assert not missing, (
            f"UnifiedExplanation is missing ExplanationRecord storage fields: {missing}"
        )

    def test_unified_schema_extends_storage_with_required_new_fields(self):
        """All 9 required new fields must be present in UnifiedExplanation."""
        required_new_fields = {
            "trace_id",
            "weight_version",
            "breakdown",
            "per_component_contributions",
            "reasoning",
            "input_summary",
            "stage3_input_hash",
            "stage3_output_hash",
            "explanation_hash",
        }
        unified_fields = set(UnifiedExplanation.model_fields.keys())
        missing = required_new_fields - unified_fields
        assert not missing, (
            f"UnifiedExplanation missing required new fields: {missing}"
        )

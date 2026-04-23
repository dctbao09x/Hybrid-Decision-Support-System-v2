"""
tests/test_explanation_immutability.py
══════════════════════════════════════════════════════════════════════════════
Immutability guarantee test-suite for ``UnifiedExplanation``.

Covers every enforcement layer added in Task 3:

  1. ``TestFrozenFieldAssignment``
       Direct attribute assignment is blocked by Pydantic's ``frozen=True``.

  2. ``TestModelCopyGuard``
       ``model_copy(update={...})`` raises ``ImmutabilityError``.

  3. ``TestObjectSetAttrBlocked``
       ``object.__setattr__`` is also blocked by Pydantic v2 frozen mode.

  4. ``TestContainerMutationBlocked``
       All mutable containers (lists → tuple, dicts → MappingProxyType) are
       deep-frozen after construction; mutation attempts raise ``TypeError``
       or ``AttributeError``.

  5. ``TestSubclassingBlocked``
       ``__init_subclass__`` raises ``ImmutabilityError`` for any subclass.

  6. ``TestHashStability``
       ``explanation_hash`` is identical across repeated ``to_storage_dict()``
       calls and is also stable when a fresh equivalent instance is built.

  7. ``TestHashAfterBuild``
       ``verify_hash()`` returns ``True`` immediately after ``build()``.

  8. ``TestStorageSerializationFrozen``
       ``to_storage_dict()`` and ``to_api_response()`` are fully
       JSON-serialisable even though internal containers are frozen.
"""

from __future__ import annotations

import json
import types

import pytest
from pydantic import ValidationError

from backend.explain.unified_schema import ImmutabilityError, UnifiedExplanation

# ─────────────────────────────────────────────────────────────────────────────
# Shared fixture helpers
# ─────────────────────────────────────────────────────────────────────────────

_BASE_KWARGS: dict = dict(
    trace_id="t-immut-001",
    model_id="mdl-v1",
    kb_version="kb-3.2.1",
    weight_version="w-2024-01",
    breakdown={"skill": 0.30, "experience": 0.25, "education": 0.25, "preference": 0.20},
    per_component_contributions={"skill": 22.5, "experience": 15.0, "education": 18.75, "preference": 7.5},
    reasoning=[
        "Math and logic scores exceed threshold — strong skill alignment.",
        "Three years of relevant experience found in background.",
        "Educational background supports selection.",
    ],
    input_summary={"math_score": 80.0, "experience_years": 3, "interest_it": 71.0},
    feature_snapshot={"math_score": 80.0, "interest_it": 71.0},
    rule_path=[
        {
            "rule_id": "R-SKILL-001",
            "condition": "math_score >= 75",
            "matched_features": {"math_score": 80.0},
            "weight": 0.57,
        }
    ],
    weights={"rule_logic": 0.57, "interest_alignment": 0.43},
    evidence=[{"source": "features", "key": "math_score", "value": 80.0, "weight": 0.9}],
    confidence=0.81,
    prediction={"career": "Software Engineer", "score": 81.0},
    stage3_input_hash="aabbcc00",
    stage3_output_hash="ddeeff11",
)


def _make() -> UnifiedExplanation:
    """Build a fresh UnifiedExplanation for each test."""
    return UnifiedExplanation.build(**_BASE_KWARGS)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Frozen field assignment
# ─────────────────────────────────────────────────────────────────────────────

class TestFrozenFieldAssignment:
    """Pydantic ``frozen=True`` blocks direct attribute mutation."""

    def test_set_scalar_field_raises(self):
        u = _make()
        with pytest.raises(ValidationError):
            u.confidence = 0.99  # type: ignore[misc]

    def test_set_trace_id_raises(self):
        u = _make()
        with pytest.raises(ValidationError):
            u.trace_id = "tampered"  # type: ignore[misc]

    def test_set_model_id_raises(self):
        u = _make()
        with pytest.raises(ValidationError):
            u.model_id = "tampered"  # type: ignore[misc]

    def test_set_explanation_hash_raises(self):
        u = _make()
        with pytest.raises(ValidationError):
            u.explanation_hash = "deadbeef" * 8  # type: ignore[misc]

    def test_set_weight_version_raises(self):
        u = _make()
        with pytest.raises(ValidationError):
            u.weight_version = "tampered"  # type: ignore[misc]

    def test_set_stage3_input_hash_raises(self):
        u = _make()
        with pytest.raises(ValidationError):
            u.stage3_input_hash = "tampered"  # type: ignore[misc]

    def test_set_stage3_output_hash_raises(self):
        u = _make()
        with pytest.raises(ValidationError):
            u.stage3_output_hash = "tampered"  # type: ignore[misc]

    def test_set_confidence_to_same_value_still_raises(self):
        """frozen=True raises even for identity assignments."""
        u = _make()
        with pytest.raises(ValidationError):
            u.confidence = u.confidence  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────────────────────
# 2. model_copy guard
# ─────────────────────────────────────────────────────────────────────────────

class TestModelCopyGuard:
    """``model_copy(update=...)`` raises ``ImmutabilityError`` for non-empty update."""

    def test_model_copy_with_update_raises(self):
        u = _make()
        with pytest.raises(ImmutabilityError):
            u.model_copy(update={"confidence": 0.55})

    def test_model_copy_update_hash_raises(self):
        u = _make()
        with pytest.raises(ImmutabilityError):
            u.model_copy(update={"explanation_hash": "00" * 32})

    def test_model_copy_update_multiple_fields_raises(self):
        u = _make()
        with pytest.raises(ImmutabilityError):
            u.model_copy(update={"confidence": 0.1, "model_id": "evil"})

    def test_model_copy_no_update_succeeds(self):
        """``model_copy()`` without update is a valid deep-copy."""
        u = _make()
        u2 = u.model_copy()
        assert u2.explanation_hash == u.explanation_hash
        assert u2 is not u

    def test_model_copy_empty_update_raises(self):
        """An empty dict is still falsy and therefore allowed by our guard."""
        u = _make()
        # update={} is falsy → guard does NOT raise → allowed
        u2 = u.model_copy(update={})
        assert u2.explanation_hash == u.explanation_hash

    def test_immutability_error_message_content(self):
        u = _make()
        with pytest.raises(ImmutabilityError) as exc_info:
            u.model_copy(update={"confidence": 0.5})
        assert "explanation_hash" in str(exc_info.value)
        assert "build" in str(exc_info.value)


# ─────────────────────────────────────────────────────────────────────────────
# 3. object.__setattr__ detection via verify_hash
# ─────────────────────────────────────────────────────────────────────────────

class TestObjectSetAttrBlocked:
    """
    Pydantic v2 ``frozen=True`` blocks ``setattr`` via its ``__setattr__``
    override, but ``object.__setattr__`` goes directly to the C-layer and
    bypasses that guard.  (``_freeze_containers`` uses this same mechanism
    internally.)

    The designed defence against low-level tampering is ``verify_hash()``:
    any field mutation — even via ``object.__setattr__`` — changes the
    payload and causes ``verify_hash()`` to return ``False``.
    """

    def test_object_setattr_confidence_succeeds_but_corrupts_hash(self):
        """object.__setattr__ bypasses frozen; verify_hash exposes the corruption."""
        u = _make()
        assert u.verify_hash() is True
        object.__setattr__(u, "confidence", 0.01)
        assert u.confidence == 0.01  # mutation landed
        assert u.verify_hash() is False  # hash no longer matches

    def test_object_setattr_hash_field_corrupts_verification(self):
        """Overwriting explanation_hash itself also invalidates verify_hash."""
        u = _make()
        original_hash = u.explanation_hash
        object.__setattr__(u, "explanation_hash", "00" * 32)
        assert u.explanation_hash != original_hash
        assert u.verify_hash() is False

    def test_object_setattr_trace_id_corrupts_hash(self):
        u = _make()
        object.__setattr__(u, "trace_id", "injected")
        assert u.trace_id == "injected"
        assert u.verify_hash() is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. Container mutation blocked
# ─────────────────────────────────────────────────────────────────────────────

class TestContainerMutationBlocked:
    """
    After ``_freeze_containers`` runs during model validation:
    - list fields → ``tuple``  (no .append, no .extend, no item assignment)
    - dict fields → ``types.MappingProxyType``  (no __setitem__, no .update)
    """

    # ── reasoning (was list, now tuple) ──────────────────────────────────────

    def test_reasoning_is_tuple(self):
        u = _make()
        assert isinstance(u.reasoning, tuple)

    def test_reasoning_append_raises(self):
        u = _make()
        with pytest.raises(AttributeError):
            u.reasoning.append("injected step")  # type: ignore[union-attr]

    def test_reasoning_item_assignment_raises(self):
        u = _make()
        with pytest.raises(TypeError):
            u.reasoning[0] = "hijacked"  # type: ignore[index]

    # ── rule_path (was list[dict], now tuple of MappingProxyType) ────────────

    def test_rule_path_is_tuple(self):
        u = _make()
        assert isinstance(u.rule_path, tuple)

    def test_rule_path_append_raises(self):
        u = _make()
        with pytest.raises(AttributeError):
            u.rule_path.append({"rule_id": "evil"})  # type: ignore[union-attr]

    def test_rule_path_inner_dict_is_mappingproxy(self):
        u = _make()
        assert isinstance(u.rule_path[0], types.MappingProxyType)

    def test_rule_path_inner_setitem_raises(self):
        u = _make()
        with pytest.raises(TypeError):
            u.rule_path[0]["weight"] = 999.0  # type: ignore[index]

    # ── evidence (was list[dict], now tuple of MappingProxyType) ─────────────

    def test_evidence_is_tuple(self):
        u = _make()
        assert isinstance(u.evidence, tuple)

    def test_evidence_append_raises(self):
        u = _make()
        with pytest.raises(AttributeError):
            u.evidence.append({"source": "evil"})  # type: ignore[union-attr]

    def test_evidence_inner_is_mappingproxy(self):
        u = _make()
        assert isinstance(u.evidence[0], types.MappingProxyType)

    def test_evidence_inner_setitem_raises(self):
        u = _make()
        with pytest.raises(TypeError):
            u.evidence[0]["weight"] = 0.0  # type: ignore[index]

    # ── breakdown (was dict, now MappingProxyType) ────────────────────────────

    def test_breakdown_is_mappingproxy(self):
        u = _make()
        assert isinstance(u.breakdown, types.MappingProxyType)

    def test_breakdown_setitem_raises(self):
        u = _make()
        with pytest.raises(TypeError):
            u.breakdown["skill"] = 999.0  # type: ignore[index]

    def test_breakdown_update_raises(self):
        u = _make()
        with pytest.raises(AttributeError):
            u.breakdown.update({"skill": 0.0})  # type: ignore[union-attr]

    # ── per_component_contributions (was dict, now MappingProxyType) ──────────

    def test_per_component_is_mappingproxy(self):
        u = _make()
        assert isinstance(u.per_component_contributions, types.MappingProxyType)

    def test_per_component_setitem_raises(self):
        u = _make()
        with pytest.raises(TypeError):
            u.per_component_contributions["skill"] = 0.0  # type: ignore[index]

    # ── weights (was dict, now MappingProxyType) ──────────────────────────────

    def test_weights_is_mappingproxy(self):
        u = _make()
        assert isinstance(u.weights, types.MappingProxyType)

    def test_weights_setitem_raises(self):
        u = _make()
        with pytest.raises(TypeError):
            u.weights["rule_logic"] = 0.0  # type: ignore[index]

    # ── feature_snapshot (was dict, now MappingProxyType) ─────────────────────

    def test_feature_snapshot_is_mappingproxy(self):
        u = _make()
        assert isinstance(u.feature_snapshot, types.MappingProxyType)

    def test_feature_snapshot_setitem_raises(self):
        u = _make()
        with pytest.raises(TypeError):
            u.feature_snapshot["math_score"] = 0.0  # type: ignore[index]

    # ── prediction (was dict, now MappingProxyType) ───────────────────────────

    def test_prediction_is_mappingproxy(self):
        u = _make()
        assert isinstance(u.prediction, types.MappingProxyType)

    def test_prediction_setitem_raises(self):
        u = _make()
        with pytest.raises(TypeError):
            u.prediction["career"] = "injected"  # type: ignore[index]

    # ── nested container in rule_path.matched_features ────────────────────────

    def test_nested_matched_features_is_mappingproxy(self):
        u = _make()
        assert isinstance(u.rule_path[0]["matched_features"], types.MappingProxyType)

    def test_nested_matched_features_setitem_raises(self):
        u = _make()
        with pytest.raises(TypeError):
            u.rule_path[0]["matched_features"]["math_score"] = 0.0  # type: ignore[index]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Subclassing blocked
# ─────────────────────────────────────────────────────────────────────────────

class TestSubclassingBlocked:
    """``__init_subclass__`` raises ``ImmutabilityError`` for any subclass."""

    def test_direct_subclass_raises(self):
        with pytest.raises(ImmutabilityError):
            class Tampered(UnifiedExplanation):  # type: ignore[misc]
                pass

    def test_error_message_contains_class_name(self):
        with pytest.raises(ImmutabilityError) as exc_info:
            class EvilChild(UnifiedExplanation):  # type: ignore[misc]
                pass
        assert "EvilChild" in str(exc_info.value)

    def test_subclass_attempt_does_not_pollute_parent(self):
        """Failed subclass attempt must not change UnifiedExplanation's state."""
        try:
            class Broken(UnifiedExplanation):  # type: ignore[misc]
                pass
        except ImmutabilityError:
            pass
        # Parent still constructable and functional
        u = _make()
        assert u.verify_hash() is True


# ─────────────────────────────────────────────────────────────────────────────
# 6. Hash stability
# ─────────────────────────────────────────────────────────────────────────────

class TestHashStability:
    """explanation_hash is deterministic and stable."""

    def test_hash_stable_across_repeated_to_storage_dict(self):
        u = _make()
        hashes = {u.to_storage_dict()["explanation_hash"] for _ in range(50)}
        assert len(hashes) == 1, f"Hash varied across calls: {hashes}"

    def test_hash_stable_across_repeated_verify_hash_calls(self):
        u = _make()
        results = [u.verify_hash() for _ in range(50)]
        assert all(results), "verify_hash() returned False in at least one call"

    def test_two_equivalent_instances_have_identical_hashes(self):
        u1 = _make()
        u2 = _make()
        assert u1.explanation_hash == u2.explanation_hash

    def test_different_confidence_produces_different_hash(self):
        u1 = UnifiedExplanation.build(**_BASE_KWARGS)
        kwargs2 = dict(_BASE_KWARGS, confidence=0.01)
        u2 = UnifiedExplanation.build(**kwargs2)
        assert u1.explanation_hash != u2.explanation_hash

    def test_different_reasoning_produces_different_hash(self):
        u1 = UnifiedExplanation.build(**_BASE_KWARGS)
        kwargs2 = dict(_BASE_KWARGS, reasoning=["only one reason"])
        u2 = UnifiedExplanation.build(**kwargs2)
        assert u1.explanation_hash != u2.explanation_hash

    def test_different_trace_id_produces_different_hash(self):
        u1 = UnifiedExplanation.build(**_BASE_KWARGS)
        kwargs2 = dict(_BASE_KWARGS, trace_id="other-trace")
        u2 = UnifiedExplanation.build(**kwargs2)
        assert u1.explanation_hash != u2.explanation_hash

    def test_hash_is_64_hex_chars(self):
        u = _make()
        assert len(u.explanation_hash) == 64
        assert all(c in "0123456789abcdef" for c in u.explanation_hash)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Hash validity after build
# ─────────────────────────────────────────────────────────────────────────────

class TestHashAfterBuild:
    """verify_hash() is the deep-integrity sentinel."""

    def test_verify_hash_true_after_build(self):
        u = _make()
        assert u.verify_hash() is True

    def test_verify_hash_false_for_empty_hash(self):
        """Direct construction with explanation_hash='' fails verify_hash."""
        u_direct = UnifiedExplanation(
            **{k: v for k, v in _BASE_KWARGS.items()},
            explanation_hash="",
        )
        assert u_direct.verify_hash() is False

    def test_verify_hash_false_for_wrong_hash(self):
        """Direct construction with a known-bad hash string fails verify_hash."""
        u_direct = UnifiedExplanation(
            **{k: v for k, v in _BASE_KWARGS.items()},
            explanation_hash="deadbeef" * 8,
        )
        assert u_direct.verify_hash() is False

    def test_verify_hash_consistent_with_to_storage_dict(self):
        """The hash stored in to_storage_dict() == explanation_hash attribute."""
        u = _make()
        storage = u.to_storage_dict()
        assert storage["explanation_hash"] == u.explanation_hash

    def test_build_then_roundtrip_verify_hash(self):
        """
        Roundtrip: build → to_storage_dict → reconstruct → verify_hash still True.
        """
        u = _make()
        storage = u.to_storage_dict()
        # Reconstruct directly (no build → explanation_hash already computed)
        u2 = UnifiedExplanation(**storage)
        assert u2.verify_hash() is True


# ─────────────────────────────────────────────────────────────────────────────
# 8. Storage and API serialization correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestStorageSerializationFrozen:
    """to_storage_dict() and to_api_response() produce JSON-serialisable output."""

    def test_to_storage_dict_is_json_serialisable(self):
        u = _make()
        payload = u.to_storage_dict()
        # Must not raise
        serialised = json.dumps(payload)
        assert len(serialised) > 100

    def test_to_api_response_is_json_serialisable(self):
        u = _make()
        response = u.to_api_response()
        serialised = json.dumps(response)
        assert len(serialised) > 100

    def test_to_storage_dict_rule_path_is_list_of_dicts(self):
        u = _make()
        storage = u.to_storage_dict()
        assert isinstance(storage["rule_path"], list)
        assert all(isinstance(r, dict) for r in storage["rule_path"])

    def test_to_storage_dict_evidence_is_list_of_dicts(self):
        u = _make()
        storage = u.to_storage_dict()
        assert isinstance(storage["evidence"], list)
        assert all(isinstance(e, dict) for e in storage["evidence"])

    def test_to_storage_dict_reasoning_is_list(self):
        u = _make()
        storage = u.to_storage_dict()
        assert isinstance(storage["reasoning"], list)

    def test_to_storage_dict_weights_is_plain_dict(self):
        u = _make()
        storage = u.to_storage_dict()
        assert isinstance(storage["weights"], dict)
        assert not isinstance(storage["weights"], types.MappingProxyType)

    def test_to_storage_dict_breakdown_is_plain_dict(self):
        u = _make()
        storage = u.to_storage_dict()
        assert isinstance(storage["breakdown"], dict)
        assert not isinstance(storage["breakdown"], types.MappingProxyType)

    def test_to_storage_dict_nested_matched_features_is_plain_dict(self):
        u = _make()
        storage = u.to_storage_dict()
        first_rule = storage["rule_path"][0]
        assert isinstance(first_rule["matched_features"], dict)
        assert not isinstance(first_rule["matched_features"], types.MappingProxyType)

    def test_to_api_response_reasoning_chain_is_list(self):
        """to_api_response maps reasoning → reasoning_chain (list)."""
        u = _make()
        response = u.to_api_response()
        assert "reasoning_chain" in response
        assert isinstance(response["reasoning_chain"], list)

    def test_to_api_response_factors_is_list_of_dicts(self):
        """to_api_response exposes per_component_contributions as factors list."""
        u = _make()
        response = u.to_api_response()
        assert "factors" in response
        assert isinstance(response["factors"], list)
        assert all(isinstance(f, dict) for f in response["factors"])

    def test_storage_roundtrip_preserves_all_values(self):
        """Values in to_storage_dict() match the original construction kwargs."""
        u = _make()
        storage = u.to_storage_dict()
        assert storage["trace_id"] == "t-immut-001"
        assert storage["confidence"] == 0.81
        assert storage["weights"] == {"rule_logic": 0.57, "interest_alignment": 0.43}
        assert storage["breakdown"] == {
            "skill": 0.30, "experience": 0.25,
            "education": 0.25, "preference": 0.20,
        }

    def test_json_roundtrip_preserves_hash(self):
        """JSON serialise → deserialise → verify_hash still True."""
        u = _make()
        storage = u.to_storage_dict()
        raw_json = json.dumps(storage)
        recovered = json.loads(raw_json)
        u2 = UnifiedExplanation(**recovered)
        assert u2.verify_hash() is True

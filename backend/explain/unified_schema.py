"""
backend/explain/unified_schema.py
══════════════════════════════════════════════════════════════════════════════
Unified Explanation Schema — Single Source of Truth
=====================================================

Eliminates dual-schema drift between:
  - ExplanationResult  (API layer  — Pydantic model in decision_controller.py)
  - ExplanationRecord  (storage    — dataclass  in explain/models.py)

Every explanation produced by the pipeline MUST be expressible as a
UnifiedExplanation.  The API projection and the storage projection are
both *derived* from this object.

Design Guarantees
-----------------
``frozen=True``      Instance attributes cannot be reassigned after construction.
``extra="forbid"``   Any undeclared field raises a ValidationError immediately.
No Optional fields   Every field must be explicitly supplied; use ``build()`` to
                     auto-compute ``explanation_hash``.
No implicit defaults ``build()`` enforces all required fields by keyword-only args.

Field Contract
--------------
trace_id                    Correlation ID shared across the whole pipeline.
model_id                    Version of the ML model that produced the ranking.
kb_version                  Knowledge-base version used during rule evaluation.
weight_version              Identifier of the SubScoreWeights / WeightArtifact.

breakdown                   Normalised sub-score weights from ScoringBreakdown.
                            Maps component → weight, e.g. {"skill": 0.30, ...}.
per_component_contributions Weighted contribution per component from
                            ScoringBreakdown.contributions, e.g. {"skill": 21.0}.

reasoning                   Ordered list of human-readable reasoning steps.
input_summary               Sanitised snapshot of the inputs that drove prediction.

feature_snapshot            Raw feature values passed to the rule engine.
rule_path                   List of RuleFire.to_dict() records (ordered).
weights                     Per-rule weights (rule_id → weight ∈ [0,1], sum = 1.0).
evidence                    List of EvidenceItem.to_dict() records (ordered).
confidence                  Model confidence value ∈ [0, 1].
prediction                  Top-career prediction dict (career + probability, etc.).

stage3_input_hash           SHA-256 of Stage-3 input (XAI output before rendering).
stage3_output_hash          SHA-256 of Stage-3 output (rendered reasons + text).
explanation_hash            SHA-256 of the canonical explanation payload, computed
                            by ``build()`` over all fields except explanation_hash
                            itself.  Excludes storage-generated metadata
                            (explanation_id, created_at).
"""

from __future__ import annotations

import hashlib
import json
import types
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, model_validator


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────

class ImmutabilityError(Exception):
    """
    Raised when code attempts to mutate a frozen ``UnifiedExplanation``.

    Covers two paths that ``frozen=True`` alone does not prevent in Pydantic v2:

    1. ``model_copy(update={...})`` — would create a new instance with modified
       fields and a stale/wrong ``explanation_hash``.
    2. Subclassing — a subclass could override ``model_config`` to remove
       ``frozen=True``.

    Use ``UnifiedExplanation.build(**kwargs)`` to create a new instance with
    a freshly computed ``explanation_hash``.
    """


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _canonical(data: Any) -> str:
    """Deterministic canonical JSON representation."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _deep_freeze(value: Any) -> Any:
    """
    Recursively convert mutable containers into immutable equivalents.

    * ``dict``  → ``types.MappingProxyType``
    * ``list``  → ``tuple``
    * All other values are returned unchanged.

    This prevents silent post-build mutation of nested containers that
    ``frozen=True`` alone cannot block (Pydantic v2 freezes field
    reassignment but not the contents of contained lists/dicts).
    """
    if isinstance(value, dict):
        return types.MappingProxyType({k: _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """
    Recursively convert frozen containers back to plain Python types.

    Used by serialisation methods (``to_storage_dict``, ``to_api_response``)
    to produce JSON-serialisable output.
    """
    if isinstance(value, types.MappingProxyType):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────

class UnifiedExplanation(BaseModel):
    """
    Authoritative explanation schema.  IMMUTABLE after construction.

    ┌─────────────────────────────────────────────────────────────────────┐
    │ IMMUTABILITY GUARANTEES                                             │
    │                                                                     │
    │ 1. Field reassignment          → Pydantic ValidationError          │
    │    ``unified.confidence = 0.9``                                     │
    │                                                                     │
    │ 2. model_copy(update={...})    → ImmutabilityError                 │
    │    Prevents creating an instance with a stale explanation_hash.    │
    │                                                                     │
    │ 3. Container mutation          → detected by verify_hash()         │
    │    ``unified.reasoning.append(x)`` mutates the list but            │
    │    ``verify_hash()`` will return False, proving tampering.         │
    │    Containers are stored as immutable types (tuple / MappingProxy) │
    │    after model construction so mutation raises AttributeError.     │
    │                                                                     │
    │ 4. Subclassing to bypass (3)   → ImmutabilityError in              │
    │    __init_subclass__                                                │
    │                                                                     │
    │ 5. explanation_hash is computed AFTER all other fields are         │
    │    finalized, inside build().  It covers every non-hash field.     │
    └─────────────────────────────────────────────────────────────────────┘

    Construct via ``UnifiedExplanation.build(**kwargs)`` to auto-compute
    ``explanation_hash``.  Direct construction is only valid during
    storage round-trip deserialization.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # ── Identity ──────────────────────────────────────────────────────────────
    trace_id: str
    model_id: str
    kb_version: str
    weight_version: str

    # ── Sub-score decomposition (from ScoringBreakdown) ───────────────────────
    breakdown: Dict[str, float]
    per_component_contributions: Dict[str, float]

    # ── Explanation content ───────────────────────────────────────────────────
    reasoning: List[str]
    input_summary: Dict[str, Any]

    # ── Rule engine output ────────────────────────────────────────────────────
    feature_snapshot: Dict[str, float]
    rule_path: List[Dict[str, Any]]
    weights: Dict[str, float]
    evidence: List[Dict[str, Any]]
    confidence: float
    prediction: Dict[str, Any]

    # ── Audit hashes ──────────────────────────────────────────────────────────
    stage3_input_hash: str
    stage3_output_hash: str
    explanation_hash: str  # computed by build(); covers all fields above

    # ─────────────────────────────────────────────────────────────────────────
    # Subclassing guard
    # ─────────────────────────────────────────────────────────────────────────

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """
        Prevent subclassing.

        A subclass could override ``model_config`` to remove ``frozen=True``
        or inject additional mutable state.  Both would silently break the
        immutability contract and the hash guarantee.
        """
        raise ImmutabilityError(
            f"Subclassing UnifiedExplanation is not permitted. "
            f"Class {cls.__name__!r} tried to extend it. "
            "Create a separate schema instead."
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Post-construction deep-freeze
    # ─────────────────────────────────────────────────────────────────────────

    @model_validator(mode="after")
    def _freeze_containers(self) -> "UnifiedExplanation":
        """
        Replace every mutable container with an immutable equivalent AFTER
        Pydantic has validated and accepted the field values.

        * dict  → types.MappingProxyType  (raises TypeError on __setitem__)
        * list  → tuple                   (raises AttributeError on .append etc.)

        This runs once, during construction, and the resulting object
        satisfies ``frozen=True`` at both field-assignment level AND
        container-content level.

        We use ``object.__setattr__`` here because the model is already
        frozen at this point; the normal ``setattr`` path would raise.
        """
        _mutable_container_fields = (
            "breakdown",
            "per_component_contributions",
            "input_summary",
            "feature_snapshot",
            "weights",
            "prediction",
            "reasoning",
            "rule_path",
            "evidence",
        )
        for field_name in _mutable_container_fields:
            raw = object.__getattribute__(self, field_name)
            frozen = _deep_freeze(raw)
            object.__setattr__(self, field_name, frozen)
        return self

    # ─────────────────────────────────────────────────────────────────────────
    # model_copy guard
    # ─────────────────────────────────────────────────────────────────────────

    def model_copy(  # type: ignore[override]
        self,
        *,
        update: Dict[str, Any] | None = None,
        deep: bool = False,
        **kwargs: Any,
    ) -> "UnifiedExplanation":
        """
        Raises ``ImmutabilityError`` if ``update`` is non-empty.

        Passing ``update={}`` on a frozen explanation would create a new
        instance where ``explanation_hash`` no longer matches the content
        of non-hash fields — silently producing a corrupted object.

        If you need a genuinely different explanation, call
        ``UnifiedExplanation.build(**kwargs)`` which always recomputes the hash.
        """
        if update:
            raise ImmutabilityError(
                "UnifiedExplanation.model_copy(update=...) is forbidden. "
                "explanation_hash would become stale after field changes. "
                "Use UnifiedExplanation.build(**kwargs) to create a new "
                "instance with a freshly computed explanation_hash."
            )
        return super().model_copy(update=None, deep=deep, **kwargs)

    # ─────────────────────────────────────────────────────────────────────────
    # Construction
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def build(
        cls,
        *,
        trace_id: str,
        model_id: str,
        kb_version: str,
        weight_version: str,
        breakdown: Dict[str, float],
        per_component_contributions: Dict[str, float],
        reasoning: List[str],
        input_summary: Dict[str, Any],
        feature_snapshot: Dict[str, float],
        rule_path: List[Dict[str, Any]],
        weights: Dict[str, float],
        evidence: List[Dict[str, Any]],
        confidence: float,
        prediction: Dict[str, Any],
        stage3_input_hash: str,
        stage3_output_hash: str,
    ) -> "UnifiedExplanation":
        """
        Primary constructor.  Accepts every field except ``explanation_hash``
        and computes it from a deterministic canonical JSON of all supplied
        fields.  The hash deliberately excludes storage-generated metadata
        (explanation_id, created_at) so it is stable across reads and writes.
        """
        payload: Dict[str, Any] = {
            "trace_id": trace_id,
            "model_id": model_id,
            "kb_version": kb_version,
            "weight_version": weight_version,
            "breakdown": breakdown,
            "per_component_contributions": per_component_contributions,
            "reasoning": reasoning,
            "input_summary": input_summary,
            "feature_snapshot": feature_snapshot,
            "rule_path": rule_path,
            "weights": weights,
            "evidence": evidence,
            "confidence": confidence,
            "prediction": prediction,
            "stage3_input_hash": stage3_input_hash,
            "stage3_output_hash": stage3_output_hash,
        }
        explanation_hash = hashlib.sha256(
            _canonical(payload).encode("utf-8")
        ).hexdigest()
        return cls(**payload, explanation_hash=explanation_hash)

    # ─────────────────────────────────────────────────────────────────────────
    # Projections
    # ─────────────────────────────────────────────────────────────────────────

    def to_storage_dict(self) -> Dict[str, Any]:
        """
        Produce a plain dict ready for insertion into the explanations table.

        Uses ``_thaw()`` to convert frozen containers (``MappingProxyType`` /
        ``tuple``) back to regular ``dict`` / ``list`` before serialisation.
        Deliberately excludes storage-generated fields (explanation_id,
        created_at) so callers can add them without key collisions.
        """
        return {
            "trace_id": self.trace_id,
            "model_id": self.model_id,
            "kb_version": self.kb_version,
            "weight_version": self.weight_version,
            "breakdown": _thaw(self.breakdown),
            "per_component_contributions": _thaw(self.per_component_contributions),
            "reasoning": _thaw(self.reasoning),
            "input_summary": _thaw(self.input_summary),
            "feature_snapshot": _thaw(self.feature_snapshot),
            "rule_path": _thaw(self.rule_path),
            "weights": _thaw(self.weights),
            "evidence": _thaw(self.evidence),
            "confidence": float(self.confidence),
            "prediction": _thaw(self.prediction),
            "stage3_input_hash": self.stage3_input_hash,
            "stage3_output_hash": self.stage3_output_hash,
            "explanation_hash": self.explanation_hash,
        }

    def to_api_response(self) -> Dict[str, Any]:
        """
        Produce a dict compatible with the ExplanationResult Pydantic model
        (decision_controller.py).

        ExplanationResult fields:
          summary         ← first reasoning entry (or empty string)
          factors         ← per_component_contributions as [{name, contribution, description}]
          confidence      ← confidence
          reasoning_chain ← reasoning
        """
        contributions = _thaw(self.per_component_contributions)
        reasoning     = _thaw(self.reasoning)
        factors = [
            {
                "name": component,
                "contribution": float(contribution),
                "description": (
                    f"{component.replace('_', ' ').title()} sub-score contribution: "
                    f"{contribution:.4f}"
                ),
            }
            for component, contribution in contributions.items()
        ]
        return {
            "summary": reasoning[0] if reasoning else "",
            "factors": factors,
            "confidence": float(self.confidence),
            "reasoning_chain": list(reasoning),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Adapter from legacy ExplanationRecord
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def from_record(
        cls,
        record: Any,
        *,
        weight_version: str,
        breakdown: Dict[str, float],
        per_component_contributions: Dict[str, float],
        reasoning: List[str],
        input_summary: Dict[str, Any],
        stage3_input_hash: str,
        stage3_output_hash: str,
    ) -> "UnifiedExplanation":
        """
        Strict adapter from a legacy ``ExplanationRecord`` dataclass.

        Every field in ``UnifiedExplanation`` is explicitly mapped — there is
        no implicit field copying.  The mapping is validated by the Pydantic
        model on construction, so any structural drift between ExplanationRecord
        and UnifiedExplanation will raise a ``ValidationError`` immediately.
        """
        rule_path = [
            (r.to_dict() if hasattr(r, "to_dict") else dict(r))
            for r in record.rule_path
        ]
        evidence = [
            (e.to_dict() if hasattr(e, "to_dict") else dict(e))
            for e in record.evidence
        ]
        return cls.build(
            trace_id=record.trace_id,
            model_id=record.model_id,
            kb_version=record.kb_version,
            weight_version=weight_version,
            breakdown=dict(breakdown),
            per_component_contributions=dict(per_component_contributions),
            reasoning=list(reasoning),
            input_summary=dict(input_summary),
            feature_snapshot=dict(record.feature_snapshot),
            rule_path=rule_path,
            weights=dict(record.weights),
            evidence=evidence,
            confidence=float(record.confidence),
            prediction=dict(record.prediction or {}),
            stage3_input_hash=stage3_input_hash,
            stage3_output_hash=stage3_output_hash,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Deserialization
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def from_storage_row(cls, row: Dict[str, Any]) -> "UnifiedExplanation":
        """
        Reconstruct from a raw storage row dict.

        Legacy rows (inserted before unified schema) have NULL / empty string
        for the new columns; sentinel values are used so the object is valid.
        ``explanation_hash`` will be empty for legacy rows — callers may check
        ``unified.explanation_hash == ""`` to detect them.

        Handles the legacy wrapped storage format where rule_path is stored as
        ``{"rule_path": [...]}`` and evidence as ``{"evidence": [...]}``.
        """
        def _load_json(name: str, default: Any) -> Any:
            raw = row.get(name)
            if raw is None:
                return default
            if isinstance(raw, (dict, list)):
                return raw
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                return default

        # Unwrap legacy storage envelope for rule_path
        rule_path = _load_json("rule_path", [])
        if isinstance(rule_path, dict) and "rule_path" in rule_path:
            rule_path = rule_path["rule_path"]

        # Unwrap legacy storage envelope for evidence
        evidence = _load_json("evidence", [])
        if isinstance(evidence, dict) and "evidence" in evidence:
            evidence = evidence["evidence"]

        return cls(
            trace_id=row.get("trace_id") or "",
            model_id=row.get("model_id") or "",
            kb_version=row.get("kb_version") or "",
            weight_version=row.get("weight_version") or "",
            breakdown=_load_json("breakdown", {}),
            per_component_contributions=_load_json("per_component_contributions", {}),
            reasoning=_load_json("reasoning", []),
            input_summary=_load_json("input_summary", {}),
            feature_snapshot=_load_json("feature_snapshot", {}),
            rule_path=rule_path,
            weights=_load_json("weights", {}),
            evidence=evidence,
            confidence=float(row.get("confidence") or 0.0),
            prediction=_load_json("prediction", {}),
            stage3_input_hash=row.get("stage3_input_hash") or "",
            stage3_output_hash=row.get("stage3_output_hash") or "",
            explanation_hash=row.get("explanation_hash") or "",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Verification
    # ─────────────────────────────────────────────────────────────────────────

    def verify_hash(self) -> bool:
        """
        Recompute the explanation_hash from current field values and compare.

        Returns True if the hash is intact, False if the payload was mutated
        after construction (indicates tampering or deserialization error).
        Legacy rows with explanation_hash=="" always return False.
        """
        if not self.explanation_hash:
            return False
        payload: Dict[str, Any] = {
            k: v for k, v in self.to_storage_dict().items()
            if k != "explanation_hash"
        }
        expected = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
        return self.explanation_hash == expected

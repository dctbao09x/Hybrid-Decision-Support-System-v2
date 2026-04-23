from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.explain.unified_schema import UnifiedExplanation


@dataclass
class RuleFire:
    rule_id: str
    condition: str
    matched_features: Dict[str, float]
    weight: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "condition": self.condition,
            "matched_features": self.matched_features,
            "weight": self.weight,
        }


@dataclass
class EvidenceItem:
    source: str
    key: str
    value: Any
    weight: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "key": self.key,
            "value": self.value,
            "weight": self.weight,
        }


@dataclass
class ExplanationRecord:
    trace_id: str
    model_id: str
    kb_version: str
    rule_path: List[RuleFire]
    weights: Dict[str, float]
    evidence: List[EvidenceItem]
    confidence: float
    feature_snapshot: Dict[str, float]
    prediction: Optional[Dict[str, Any]] = None
    created_at: str = ""
    explanation_id: str = ""
    record_hash: str = ""  # set by ExplanationStorage.append_record() after persistence

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "explanation_id": self.explanation_id,
            "trace_id": self.trace_id,
            "model_id": self.model_id,
            "kb_version": self.kb_version,
            "rule_path": [rule.to_dict() for rule in self.rule_path],
            "weights": self.weights,
            "evidence": [item.to_dict() for item in self.evidence],
            "confidence": self.confidence,
            "feature_snapshot": self.feature_snapshot,
            "prediction": self.prediction or {},
            "created_at": self.created_at,
        }

    # ------------------------------------------------------------------
    # Unified schema bridge
    # ------------------------------------------------------------------

    def to_unified(
        self,
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
        Convert this ExplanationRecord to a UnifiedExplanation.

        The caller must supply the new required fields that ExplanationRecord
        does not carry.  Every field mapping is explicit — no silent defaults.
        """
        from backend.explain.unified_schema import UnifiedExplanation  # late import
        return UnifiedExplanation.from_record(
            self,
            weight_version=weight_version,
            breakdown=breakdown,
            per_component_contributions=per_component_contributions,
            reasoning=reasoning,
            input_summary=input_summary,
            stage3_input_hash=stage3_input_hash,
            stage3_output_hash=stage3_output_hash,
        )

    @classmethod
    def from_unified(cls, unified: "UnifiedExplanation") -> "ExplanationRecord":
        """
        Reconstruct an ExplanationRecord from a UnifiedExplanation.

        Routes through ``unified.to_storage_dict()`` so that all containers
        are thawed (``MappingProxyType`` → ``dict``, ``tuple`` → ``list``)
        before being passed to ``RuleFire`` / ``EvidenceItem`` constructors
        and stored in this record.  This ensures ``record.to_dict()`` produces
        JSON-serialisable output regardless of the frozen state of the source
        ``UnifiedExplanation``.

        Only the fields present in ExplanationRecord are mapped.  New fields
        introduced by UnifiedExplanation (breakdown, per_component_contributions,
        stage3_input_hash, etc.) are not present in ExplanationRecord and are
        silently dropped — this is by design for legacy storage compatibility.
        """
        from backend.explain.models import RuleFire, EvidenceItem  # noqa
        # to_storage_dict() thaws all frozen containers back to plain lists/dicts
        thawed = unified.to_storage_dict()
        rule_path = [RuleFire(**r) for r in thawed["rule_path"]]
        evidence = [EvidenceItem(**e) for e in thawed["evidence"]]
        return cls(
            trace_id=thawed["trace_id"],
            model_id=thawed["model_id"],
            kb_version=thawed["kb_version"],
            rule_path=rule_path,
            weights=thawed["weights"],
            evidence=evidence,
            confidence=float(thawed["confidence"]),
            feature_snapshot=thawed["feature_snapshot"],
            prediction=thawed["prediction"],
        )


@dataclass
class TraceEdge:
    source: str
    target: str
    edge_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "edge_type": self.edge_type,
            "metadata": self.metadata,
        }


@dataclass
class TraceGraph:
    trace_id: str
    nodes: List[Dict[str, Any]]
    edges: List[TraceEdge]
    adjacency: Dict[str, List[str]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "nodes": self.nodes,
            "edges": [edge.to_dict() for edge in self.edges],
            "adjacency": self.adjacency,
        }

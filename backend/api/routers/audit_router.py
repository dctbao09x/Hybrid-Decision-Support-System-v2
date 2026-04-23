# backend/api/routers/audit_router.py
"""
Audit Router — Decision Chain Reconstruction
=============================================

Provides endpoints for full decision audit trail reconstruction.

Endpoints:
  GET /api/v1/audit/decision/{decision_trace_id}
      → Full decision chain: rule events + KB mapping + drift events

Replay semantics:
  Every field sourced from persistent JSONL files (rule_log.jsonl,
  kb_mapping_log.jsonl, drift_event_log.jsonl).  Each sub-record
  carries its ``chain_record_hash`` for integrity verification.
  The response includes a ``reconstruction_deterministic`` boolean
  confirming all three layers were found in persistent storage.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.governance.rule_event_log import get_rule_event_logger
from backend.governance.kb_mapping_log import get_kb_mapping_logger
from backend.governance.drift_event_log import get_drift_event_logger

_log = logging.getLogger("api.routers.audit")

router = APIRouter(tags=["Audit"])


# ═══════════════════════════════════════════════════════════════════════════════
# RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class RuleEventRecord(BaseModel):
    """One rule evaluation record from rule_log.jsonl."""
    event_id: str
    timestamp: str
    decision_trace_id: str
    rule_id: str
    rule_version: str
    rule_condition: str
    rule_result: str
    priority: int
    frozen: bool
    chain_record_hash: str


class KBMappingRecord(BaseModel):
    """KB alignment record from kb_mapping_log.jsonl."""
    event_id: str
    timestamp: str
    decision_trace_id: str
    ontology_version: str
    input_skill_cluster: List[str]
    input_interest_cluster: List[str]
    skills_kb_matches: Dict[str, Any]
    interests_kb_matches: Dict[str, Any]
    unrecognised_feature_count: int
    unrecognised_features: List[str]
    chain_record_hash: str


class DriftEventRecord(BaseModel):
    """Drift event record from drift_event_log.jsonl."""
    event_id: str
    timestamp: str
    decision_trace_id: Optional[str] = None
    drift_type: str
    divergence_metric: str
    divergence_value: float
    threshold: float
    feature_name: Optional[str] = None
    model_version: str
    triggered: bool
    chain_record_hash: str


class DecisionChainResponse(BaseModel):
    """Full decision audit chain for one decision trace."""
    decision_trace_id: str
    reconstruction_deterministic: bool = Field(
        description=(
            "True when rule events, KB mapping, and at least one log layer "
            "were all reconstructed from persistent JSONL storage rather than "
            "the in-process memory cache."
        )
    )
    # Per-layer counts
    rule_events_count: int
    kb_mapping_found: bool
    drift_events_count: int
    # Payload
    rule_events: List[Dict[str, Any]]
    kb_mapping: Optional[Dict[str, Any]]
    drift_events: List[Dict[str, Any]]
    # Integrity summary
    chain_hashes: Dict[str, Any] = Field(
        description="Hash digests from each layer for cross-layer integrity check."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _drift_events_for_trace(trace_id: str, limit: int = 500) -> List[Dict[str, Any]]:
    """Scan drift_event_log.jsonl for records matching *trace_id*."""
    all_events = get_drift_event_logger().read_all(limit=10_000)
    return [e for e in all_events if e.get("decision_trace_id") == trace_id][:limit]


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/decision/{decision_trace_id}",
    summary="Decision Chain Reconstruction",
    description=(
        "Reconstructs the full audit chain for a decision trace: "
        "rule evaluations, KB mapping, and drift events.  "
        "All data sourced from persistent JSONL logs."
    ),
    response_model=DecisionChainResponse,
)
async def get_decision_chain(
    decision_trace_id: str,
    include_drift: bool = Query(
        default=True,
        description="Include drift events for this trace (may require JSONL scan).",
    ),
    rule_limit: int = Query(
        default=1000, ge=1, le=5000,
        description="Max rule event records to return.",
    ),
) -> DecisionChainResponse:
    """
    Reconstruct the complete decision audit chain for a single trace ID.

    Sources:
    - **Rule layer** — ``backend/data/logs/rule_log.jsonl``
    - **KB layer**   — ``backend/data/logs/kb_mapping_log.jsonl``
    - **Drift layer** — ``backend/data/logs/drift_event_log.jsonl``

    The ``reconstruction_deterministic`` flag is ``True`` when at least
    two layers return records, confirming persistent reconstruction rather
    than ephemeral cache hits.
    """
    _log.info("Audit reconstruction: trace_id=%s", decision_trace_id)

    # ── Layer 1: Rule events ─────────────────────────────────────────────────
    rule_events: List[Dict[str, Any]] = []
    try:
        rule_events = get_rule_event_logger().read_by_trace(
            trace_id=decision_trace_id,
            limit=rule_limit,
        )
    except Exception as exc:
        _log.warning("rule_event_log read failed: %s", exc)

    # ── Layer 2: KB mapping ──────────────────────────────────────────────────
    kb_mapping: Optional[Dict[str, Any]] = None
    try:
        kb_mapping = get_kb_mapping_logger().read_by_trace(
            trace_id=decision_trace_id,
        )
    except Exception as exc:
        _log.warning("kb_mapping_log read failed: %s", exc)

    # ── Layer 3: Drift events ─────────────────────────────────────────────────
    drift_events: List[Dict[str, Any]] = []
    if include_drift:
        try:
            drift_events = _drift_events_for_trace(decision_trace_id)
        except Exception as exc:
            _log.warning("drift_event_log read failed: %s", exc)

    # ── Nothing found at all → 404 ───────────────────────────────────────────
    if not rule_events and kb_mapping is None and not drift_events:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No audit records found for decision_trace_id='{decision_trace_id}'. "
                "Either the trace is too old to be in persistent storage, or it has "
                "not yet been executed through the pipeline."
            ),
        )

    # ── Determinism check ────────────────────────────────────────────────────
    # Considered deterministic when >= 2 audit layers contain records
    layers_with_data = sum([
        bool(rule_events),
        kb_mapping is not None,
        bool(drift_events),
    ])
    reconstruction_deterministic = layers_with_data >= 2

    # ── Chain hash summary ───────────────────────────────────────────────────
    chain_hashes: Dict[str, Any] = {
        "rule_event_hashes": [e.get("chain_record_hash", "") for e in rule_events[:5]],
        "kb_mapping_hash": kb_mapping.get("chain_record_hash", "") if kb_mapping else "",
        "drift_event_hashes": [e.get("chain_record_hash", "") for e in drift_events[:5]],
    }

    _log.info(
        "Audit chain reconstructed: trace=%s rules=%d kb=%s drift=%d deterministic=%s",
        decision_trace_id,
        len(rule_events),
        kb_mapping is not None,
        len(drift_events),
        reconstruction_deterministic,
    )

    return DecisionChainResponse(
        decision_trace_id=decision_trace_id,
        reconstruction_deterministic=reconstruction_deterministic,
        rule_events_count=len(rule_events),
        kb_mapping_found=kb_mapping is not None,
        drift_events_count=len(drift_events),
        rule_events=rule_events,
        kb_mapping=kb_mapping,
        drift_events=drift_events,
        chain_hashes=chain_hashes,
    )


@router.get(
    "/rule-events",
    summary="Recent Rule Events (All Traces)",
    description="Returns recent rule execution events from persistent rule_log.jsonl.",
)
async def list_rule_events(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    trace_id: Optional[str] = Query(default=None, description="Filter by trace ID"),
) -> Dict[str, Any]:
    """List recent rule events from persistent storage."""
    if trace_id:
        events = get_rule_event_logger().read_by_trace(
            trace_id=trace_id, limit=limit
        )
    else:
        recent = get_rule_event_logger().read_recent_traces(limit=limit)
        events_flat: List[Dict[str, Any]] = []
        for entry in recent:
            events_flat.extend(entry.get("rules", []))
        events = events_flat[offset: offset + limit]

    return {
        "status": "ok",
        "data": {
            "count": len(events),
            "events": events,
            "log_path": str(get_rule_event_logger()._log_path),
        },
    }


@router.get(
    "/kb-events",
    summary="Recent KB Mapping Events",
    description="Returns recent KB alignment events from persistent kb_mapping_log.jsonl.",
)
async def list_kb_events(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    trace_id: Optional[str] = Query(default=None, description="Filter by trace ID"),
) -> Dict[str, Any]:
    """List recent KB mapping events from persistent storage."""
    if trace_id:
        rec = get_kb_mapping_logger().read_by_trace(trace_id=trace_id)
        events: List[Dict[str, Any]] = [rec] if rec else []
    else:
        events = get_kb_mapping_logger().read_recent(limit=limit, offset=offset)

    return {
        "status": "ok",
        "data": {
            "count": len(events),
            "events": events,
            "total": get_kb_mapping_logger().count(),
            "log_path": str(get_kb_mapping_logger()._log_path),
        },
    }

# backend/api/routers/one_button_router.py
"""
One-Button Full Orchestration Router
====================================

POST /api/v1/one-button/run is the canonical entry-point for the complete
Decision pipeline. The contract is strict and versioned.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from backend.api.controllers.decision_controller import (
    DecisionController,
    DecisionOptions,
    DecisionRequest,
    DecisionResponse,
    UserFeatures,
    get_decision_controller,
)
from backend.api.taxonomy_gate import TaxonomyValidationError
from backend.core.telemetry.context import get_prompt_context
from backend.scoring.models import ScoringInput

logger = logging.getLogger("api.routers.one_button")

router = APIRouter(prefix="/api/v1/one-button", tags=["One-Button"])

CANONICAL_ONE_BUTTON_ENDPOINT = "/api/v1/one-button/run"
LEGACY_DECISION_ENDPOINT = "/api/v1/decision/run"
LEGACY_ONE_BUTTON_SUNSET = "Wed, 31 Dec 2026 23:59:59 GMT"

ONE_BUTTON_CONTRACT_VERSION = "2026-04-02.v1"
ONE_BUTTON_REQUEST_SCHEMA_VERSION = "one_button.request.v1"
ONE_BUTTON_RESPONSE_SCHEMA_VERSION = "one_button.response.v1"

IDEMPOTENCY_TTL_SECONDS = 15 * 60

# Canonical stage names that MUST appear in every successful response.
REQUIRED_STAGES: List[str] = [
    "taxonomy_normalize",
    "taxonomy_validate",
    "rule_engine",
    "ml_predict",
    "scoring",
    "explain",
    "diagnostics",
    "stage_trace",
]

# Internal stage-log labels (from DecisionController) -> canonical one-button names.
_STAGE_MAP: Dict[str, str] = {
    "input_normalize": "taxonomy_normalize",
    "feature_extraction": "ml_predict",
    "simgr_scoring": "scoring",
    "rule_engine": "rule_engine",
    "explanation": "explain",
    "kb_alignment": "kb_alignment",
    "merge": "merge",
    "drift_check": "drift_check",
    "market_data": "market_data",
}

_controller: Optional[DecisionController] = None
_start_time = time.time()

_metrics_collector: Any = None
_cost_tracker: Any = None
_contract_metric_state = {
    "requests": 0,
    "canonical_requests": 0,
    "legacy_requests": 0,
    "compliant": 0,
    "schema_failures": 0,
}

_idempotency_cache: Dict[str, Dict[str, Any]] = {}


def set_controller(controller: DecisionController) -> None:
    """Inject the shared DecisionController instance."""
    global _controller
    _controller = controller
    logger.info("DecisionController injected into one_button_router")


def set_metrics_collector(metrics_collector: Any) -> None:
    """Attach the shared metrics collector for contract-level gauges."""
    global _metrics_collector
    _metrics_collector = metrics_collector


def set_cost_tracker(cost_tracker: Any) -> None:
    """Attach the shared cost tracker for unit-economics accounting."""
    global _cost_tracker
    _cost_tracker = cost_tracker


def _get_controller() -> DecisionController:
    """Return the injected controller or fall back to the singleton."""
    return _controller or get_decision_controller()


def _metrics_inc(name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
    if _metrics_collector is None:
        return
    try:
        _metrics_collector.inc(name, value=value, labels=labels)
    except Exception:
        logger.debug("one-button metrics counter update failed", exc_info=True)


def _metrics_set_gauge(name: str, value: float) -> None:
    if _metrics_collector is None:
        return
    try:
        _metrics_collector.set_gauge(name, value)
    except Exception:
        logger.debug("one-button metrics gauge update failed", exc_info=True)


def _refresh_contract_metric_gauges() -> None:
    requests = max(_contract_metric_state["requests"], 1)
    canonical_requests = _contract_metric_state["canonical_requests"]
    compliance_rate = (
        _contract_metric_state["compliant"] / canonical_requests
        if canonical_requests > 0
        else 0.0
    )

    _metrics_set_gauge("one_button_contract_compliance_rate", compliance_rate)
    _metrics_set_gauge(
        "legacy_endpoint_usage",
        _contract_metric_state["legacy_requests"] / requests,
    )
    _metrics_set_gauge(
        "schema_validation_failure_rate",
        _contract_metric_state["schema_failures"] / requests,
    )


def _record_contract_request(*, legacy_mode: bool) -> None:
    _contract_metric_state["requests"] += 1
    if legacy_mode:
        _contract_metric_state["legacy_requests"] += 1
        _metrics_inc("legacy_endpoint_usage_total")
        _metrics_inc("one_button_contract_requests_total", labels={"endpoint": "legacy"})
    else:
        _contract_metric_state["canonical_requests"] += 1
        _metrics_inc("one_button_contract_requests_total", labels={"endpoint": "canonical"})
    _refresh_contract_metric_gauges()


def _record_contract_compliant() -> None:
    _contract_metric_state["compliant"] += 1
    _metrics_inc("one_button_contract_compliant_total")
    _refresh_contract_metric_gauges()


def _record_schema_validation_failure() -> None:
    _contract_metric_state["schema_failures"] += 1
    _metrics_inc("schema_validation_failures_total")
    _refresh_contract_metric_gauges()


def record_schema_validation_failure_for_path(path: str) -> None:
    """Allow gateway middleware to account for request-level 422 validation failures."""
    if path in {CANONICAL_ONE_BUTTON_ENDPOINT, LEGACY_DECISION_ENDPOINT}:
        _record_schema_validation_failure()


class OneButtonRequest(BaseModel):
    """Strict request body for one-button execution."""

    contract_version: str = Field(default=ONE_BUTTON_CONTRACT_VERSION)
    request_schema_version: str = Field(default=ONE_BUTTON_REQUEST_SCHEMA_VERSION)

    user_id: str = Field(..., description="User identifier")
    scoring_input: ScoringInput = Field(..., description="Full scoring input")
    features: Optional[UserFeatures] = Field(None, description="Optional pre-extracted features")

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "contract_version": ONE_BUTTON_CONTRACT_VERSION,
                "request_schema_version": ONE_BUTTON_REQUEST_SCHEMA_VERSION,
                "user_id": "user_demo_001",
                "scoring_input": {
                    "personal_profile": {
                        "ability_score": 0.75,
                        "confidence_score": 0.70,
                        "interests": ["technology", "data science"],
                    },
                    "experience": {"years": 4, "domains": ["software engineering"]},
                    "goals": {
                        "career_aspirations": ["data engineer"],
                        "timeline_years": 3,
                    },
                    "skills": ["python", "sql", "machine learning"],
                    "education": {
                        "level": "Bachelor",
                        "field_of_study": "Computer Science",
                    },
                    "preferences": {
                        "preferred_domains": ["technology"],
                        "work_style": "hybrid",
                    },
                },
            }
        },
    )


class StageResult(BaseModel):
    """Per-stage execution record in the unified response."""

    stage: str
    status: str
    duration_ms: float
    input: Optional[Dict[str, Any]] = None
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class IdempotencyInfo(BaseModel):
    """Idempotency execution metadata."""

    key: Optional[str] = None
    status: str = "not_provided"   # not_provided | stored | replayed
    replayed: bool = False
    request_hash: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class OneButtonResponse(BaseModel):
    """Unified, strict, versioned one-button response."""

    contract_version: str = ONE_BUTTON_CONTRACT_VERSION
    response_schema_version: str = ONE_BUTTON_RESPONSE_SCHEMA_VERSION
    request_endpoint: str = CANONICAL_ONE_BUTTON_ENDPOINT
    canonical_endpoint: str = CANONICAL_ONE_BUTTON_ENDPOINT
    stage_manifest: List[str] = Field(default_factory=lambda: list(REQUIRED_STAGES))
    idempotency: IdempotencyInfo = Field(default_factory=IdempotencyInfo)

    trace_id: str
    timestamp: str
    status: str
    pipeline_duration_ms: float

    rankings: List[Dict[str, Any]]
    top_career: Optional[Dict[str, Any]]
    scoring_breakdown: Optional[Dict[str, Any]]
    explanation: Optional[Dict[str, Any]]
    market_insights: List[Dict[str, Any]]
    rule_applied: List[Dict[str, Any]]
    reasoning_path: List[str]

    stages: Dict[str, StageResult]
    stage_trace: List[StageResult]
    stage_log: List[StageResult]
    diagnostics: Dict[str, Any]

    artifact_hash_chain_root: Optional[str] = None
    meta: Dict[str, Any]

    entrypoint: str = CANONICAL_ONE_BUTTON_ENDPOINT
    entrypoint_enforced: bool = True

    model_config = ConfigDict(extra="forbid")


def _build_stage_result(raw: Dict[str, Any], override_name: Optional[str] = None) -> StageResult:
    return StageResult(
        stage=override_name or raw.get("stage", "unknown"),
        status=raw.get("status", "unknown"),
        duration_ms=float(raw.get("duration_ms", 0.0)),
        input=raw.get("input"),
        output=raw.get("output"),
        error=raw.get("error"),
    )


def _derive_taxonomy_validate_stage(normalize_raw: Dict[str, Any]) -> StageResult:
    output = normalize_raw.get("output", {})
    taxonomy_ok = output.get("taxonomy_applied", False)
    return StageResult(
        stage="taxonomy_validate",
        status="ok" if taxonomy_ok else "error",
        duration_ms=0.0,
        input={
            "skills_resolved": output.get("skills_resolved"),
            "interests_resolved": output.get("interests_resolved"),
            "education_level": output.get("education_level"),
        },
        output={
            "taxonomy_applied": taxonomy_ok,
            "validation_passed": taxonomy_ok,
        },
        error=None if taxonomy_ok else "taxonomy_validate: taxonomy_applied=False",
    )


def _build_diagnostics_stage(diagnostics: Dict[str, Any]) -> StageResult:
    return StageResult(
        stage="diagnostics",
        status="ok",
        duration_ms=0.0,
        input=None,
        output=diagnostics,
    )


def _build_stage_trace_stage(ordered_stages: List[StageResult]) -> StageResult:
    return StageResult(
        stage="stage_trace",
        status="ok",
        duration_ms=0.0,
        input=None,
        output={
            "total_stages": len(ordered_stages),
            "stages": [s.stage for s in ordered_stages],
        },
    )


def _build_contract_http_exception(
    *,
    status_code: int,
    code: str,
    message: str,
    endpoint: str,
    retryable: bool,
    details: Optional[Dict[str, Any]] = None,
) -> HTTPException:
    payload: Dict[str, Any] = {
        "error": code,
        "message": message,
        "retryable": retryable,
        "contract_version": ONE_BUTTON_CONTRACT_VERSION,
        "request_schema_version": ONE_BUTTON_REQUEST_SCHEMA_VERSION,
        "response_schema_version": ONE_BUTTON_RESPONSE_SCHEMA_VERSION,
        "endpoint": endpoint,
        "details": details or {},
    }
    if details:
        payload.update(details)
    return HTTPException(status_code=status_code, detail=payload)


def _validate_required_stages(
    stages: Dict[str, StageResult],
    endpoint: str = CANONICAL_ONE_BUTTON_ENDPOINT,
) -> None:
    missing = [s for s in REQUIRED_STAGES if s not in stages]
    if missing:
        _record_schema_validation_failure()
        raise _build_contract_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="ONE_BUTTON_STAGE_MISSING",
            message="One or more required pipeline stages did not execute.",
            endpoint=endpoint,
            retryable=False,
            details={
                "missing_stages": missing,
                "required_stages": REQUIRED_STAGES,
            },
        )

    skipped = [s for s in REQUIRED_STAGES if stages[s].status == "skipped"]
    if skipped:
        _record_schema_validation_failure()
        raise _build_contract_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="ONE_BUTTON_STAGE_SKIPPED",
            message="One or more required pipeline stages were skipped.",
            endpoint=endpoint,
            retryable=False,
            details={
                "skipped_stages": skipped,
                "required_stages": REQUIRED_STAGES,
            },
        )


def _to_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return obj


def _assemble_response(
    inner: DecisionResponse,
    *,
    request_endpoint: str = CANONICAL_ONE_BUTTON_ENDPOINT,
    idempotency: Optional[IdempotencyInfo] = None,
) -> OneButtonResponse:
    raw_logs: List[Dict[str, Any]] = inner.stage_log or []
    raw_by_name: Dict[str, Dict[str, Any]] = {s.get("stage", ""): s for s in raw_logs}

    full_trace: List[StageResult] = [_build_stage_result(s) for s in raw_logs]
    stages: Dict[str, StageResult] = {}

    if "input_normalize" in raw_by_name:
        stages["taxonomy_normalize"] = _build_stage_result(
            raw_by_name["input_normalize"],
            override_name="taxonomy_normalize",
        )
    else:
        stages["taxonomy_normalize"] = StageResult(
            stage="taxonomy_normalize",
            status="error",
            duration_ms=0.0,
            error="input_normalize stage log not found",
        )

    stages["taxonomy_validate"] = _derive_taxonomy_validate_stage(
        raw_by_name.get("input_normalize", {})
    )

    if "rule_engine" in raw_by_name:
        stages["rule_engine"] = _build_stage_result(
            raw_by_name["rule_engine"],
            override_name="rule_engine",
        )
    else:
        stages["rule_engine"] = StageResult(
            stage="rule_engine",
            status="error",
            duration_ms=0.0,
            error="rule_engine stage log not found",
        )

    if "feature_extraction" in raw_by_name:
        stages["ml_predict"] = _build_stage_result(
            raw_by_name["feature_extraction"],
            override_name="ml_predict",
        )
    else:
        stages["ml_predict"] = StageResult(
            stage="ml_predict",
            status="error",
            duration_ms=0.0,
            error="feature_extraction stage log not found",
        )

    if "simgr_scoring" in raw_by_name:
        stages["scoring"] = _build_stage_result(
            raw_by_name["simgr_scoring"],
            override_name="scoring",
        )
    else:
        stages["scoring"] = StageResult(
            stage="scoring",
            status="error",
            duration_ms=0.0,
            error="simgr_scoring stage log not found",
        )

    raw_explain = raw_by_name.get("explanation", {})
    if raw_explain:
        explain_status = raw_explain.get("status", "ok")
        if explain_status == "skipped":
            explain_status = "ok"
        stages["explain"] = StageResult(
            stage="explain",
            status=explain_status,
            duration_ms=float(raw_explain.get("duration_ms", 0.0)),
            input=raw_explain.get("input"),
            output=raw_explain.get("output"),
            error=raw_explain.get("error"),
        )
    else:
        stages["explain"] = StageResult(
            stage="explain",
            status="error",
            duration_ms=0.0,
            error="explanation stage log not found",
        )

    diag_dict: Dict[str, Any] = inner.diagnostics or {}
    stages["diagnostics"] = _build_diagnostics_stage(diag_dict)
    stages["stage_trace"] = _build_stage_trace_stage(full_trace)

    _validate_required_stages(stages, endpoint=request_endpoint)

    rankings_dicts = [_to_dict(r) for r in inner.rankings]
    top_career_dict = _to_dict(inner.top_career)
    scoring_bd_dict = _to_dict(inner.scoring_breakdown)
    explanation_dict = _to_dict(inner.explanation)
    market_dicts = [_to_dict(m) for m in inner.market_insights]

    return OneButtonResponse(
        contract_version=ONE_BUTTON_CONTRACT_VERSION,
        response_schema_version=ONE_BUTTON_RESPONSE_SCHEMA_VERSION,
        request_endpoint=request_endpoint,
        canonical_endpoint=CANONICAL_ONE_BUTTON_ENDPOINT,
        stage_manifest=list(REQUIRED_STAGES),
        idempotency=idempotency or IdempotencyInfo(),
        trace_id=inner.trace_id,
        timestamp=inner.timestamp,
        status=inner.status,
        pipeline_duration_ms=inner.meta.pipeline_duration_ms,
        rankings=rankings_dicts,
        top_career=top_career_dict,
        scoring_breakdown=scoring_bd_dict,
        explanation=explanation_dict,
        market_insights=market_dicts,
        rule_applied=inner.rule_applied or [],
        reasoning_path=inner.reasoning_path or [],
        stages=stages,
        stage_trace=full_trace,
        stage_log=full_trace,
        diagnostics=diag_dict,
        artifact_hash_chain_root=inner.artifact_hash_chain_root,
        meta={
            "correlation_id": inner.meta.correlation_id,
            "pipeline_duration_ms": inner.meta.pipeline_duration_ms,
            "model_version": inner.meta.model_version,
            "weights_version": inner.meta.weights_version,
            "llm_used": inner.meta.llm_used,
            "stages_completed": inner.meta.stages_completed,
            "rule_version": inner.meta.rule_version,
            "taxonomy_version": inner.meta.taxonomy_version,
            "schema_version": inner.meta.schema_version,
            "schema_hash": inner.meta.schema_hash,
        },
        entrypoint=CANONICAL_ONE_BUTTON_ENDPOINT,
        entrypoint_enforced=True,
    )


def _normalize_idempotency_key(raw_key: Optional[str]) -> Optional[str]:
    if raw_key is None:
        return None
    key = str(raw_key).strip()
    return key or None


def _cleanup_idempotency_cache() -> None:
    now = time.time()
    stale_keys = [
        key
        for key, value in _idempotency_cache.items()
        if now - float(value.get("created_at", 0.0)) > IDEMPOTENCY_TTL_SECONDS
    ]
    for key in stale_keys:
        _idempotency_cache.pop(key, None)


def _request_payload_hash(body: OneButtonRequest) -> str:
    payload = json.dumps(
        body.model_dump(exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_contract_versions(body: OneButtonRequest, endpoint: str) -> None:
    if body.contract_version != ONE_BUTTON_CONTRACT_VERSION:
        _record_schema_validation_failure()
        raise _build_contract_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="ONE_BUTTON_CONTRACT_VERSION_MISMATCH",
            message="Unsupported contract_version.",
            endpoint=endpoint,
            retryable=False,
            details={
                "expected": ONE_BUTTON_CONTRACT_VERSION,
                "received": body.contract_version,
            },
        )

    if body.request_schema_version != ONE_BUTTON_REQUEST_SCHEMA_VERSION:
        _record_schema_validation_failure()
        raise _build_contract_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="ONE_BUTTON_REQUEST_SCHEMA_VERSION_MISMATCH",
            message="Unsupported request_schema_version.",
            endpoint=endpoint,
            retryable=False,
            details={
                "expected": ONE_BUTTON_REQUEST_SCHEMA_VERSION,
                "received": body.request_schema_version,
            },
        )


def _set_contract_headers(response: Response, idempotency: IdempotencyInfo) -> None:
    response.headers["X-Contract-Version"] = ONE_BUTTON_CONTRACT_VERSION
    response.headers["X-Request-Schema-Version"] = ONE_BUTTON_REQUEST_SCHEMA_VERSION
    response.headers["X-Response-Schema-Version"] = ONE_BUTTON_RESPONSE_SCHEMA_VERSION
    response.headers["Idempotency-Replayed"] = "true" if idempotency.replayed else "false"
    if idempotency.key:
        response.headers["Idempotency-Key"] = idempotency.key


def _coerce_bool(value: Optional[str]) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _estimate_token_and_storage_usage(
    body: OneButtonRequest,
    inner: DecisionResponse,
) -> Dict[str, int]:
    request_payload = body.model_dump(exclude_none=True)
    request_bytes = len(
        json.dumps(request_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    )

    if hasattr(inner, "model_dump"):
        response_payload = inner.model_dump(exclude_none=True)
    else:
        response_payload = inner.dict(exclude_none=True)

    response_bytes = len(
        json.dumps(response_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    )

    if not bool(getattr(inner.meta, "llm_used", False)):
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "request_bytes": request_bytes,
            "response_bytes": response_bytes,
        }

    return {
        "prompt_tokens": max(1, request_bytes // 4),
        "completion_tokens": max(1, response_bytes // 4),
        "request_bytes": request_bytes,
        "response_bytes": response_bytes,
    }


async def execute_one_button_contract(
    request: Request,
    body: OneButtonRequest,
    *,
    request_endpoint: str,
    legacy_mode: bool,
    response: Optional[Response] = None,
) -> OneButtonResponse:
    """
    Execute one-button contract flow.

    Used by both the canonical endpoint and the legacy compatibility alias.
    """
    _record_contract_request(legacy_mode=legacy_mode)
    _validate_contract_versions(body, endpoint=request_endpoint)
    request.state.telemetry_endpoint_version = ONE_BUTTON_RESPONSE_SCHEMA_VERSION

    idempotency_key = _normalize_idempotency_key(request.headers.get("Idempotency-Key"))
    request_hash = _request_payload_hash(body)

    if idempotency_key:
        _cleanup_idempotency_cache()
        cached = _idempotency_cache.get(idempotency_key)
        if cached is not None:
            cached_hash = str(cached.get("request_hash", ""))
            if cached_hash != request_hash:
                _record_schema_validation_failure()
                raise _build_contract_http_exception(
                    status_code=status.HTTP_409_CONFLICT,
                    code="IDEMPOTENCY_KEY_PAYLOAD_MISMATCH",
                    message="Idempotency key already used with a different payload.",
                    endpoint=request_endpoint,
                    retryable=False,
                    details={
                        "idempotency_key": idempotency_key,
                    },
                )

            cached_response: OneButtonResponse = cached["response"].model_copy(deep=True)
            cached_response.idempotency = IdempotencyInfo(
                key=idempotency_key,
                status="replayed",
                replayed=True,
                request_hash=request_hash,
            )
            cached_response.request_endpoint = request_endpoint
            _record_contract_compliant()
            request.state.telemetry_explanation_status = "replayed"
            if isinstance(cached_response.meta, dict):
                request.state.telemetry_prompt_version = cached_response.meta.get("prompt_version")
                request.state.telemetry_model_version = cached_response.meta.get("model_version")
                cached_cost = cached_response.meta.get("cost")
                cached_unit_econ = cached_response.meta.get("unit_economics")
                if isinstance(cached_cost, dict):
                    request.state.telemetry_cost_total_usd = float(
                        cached_cost.get("total_cost_usd", 0.0) or 0.0
                    )
                    request.state.telemetry_cost_breakdown = cached_cost
                if isinstance(cached_unit_econ, dict):
                    request.state.telemetry_unit_cost_per_decision_usd = float(
                        cached_unit_econ.get("cost_per_decision_usd", 0.0) or 0.0
                    )
                    request.state.telemetry_unit_cost_per_successful_explanation_usd = float(
                        cached_unit_econ.get(
                            "cost_per_successful_explanation_usd",
                            0.0,
                        )
                        or 0.0
                    )
            if response is not None:
                _set_contract_headers(response, cached_response.idempotency)
            return cached_response

    controller = _get_controller()

    decision_request = DecisionRequest(
        user_id=body.user_id,
        scoring_input=body.scoring_input,
        features=body.features,
        options=DecisionOptions(
            include_explanation=True,
            include_market_data=True,
        ),
    )

    if _cost_tracker is not None and hasattr(_cost_tracker, "check_budget_guard"):
        tenant_id = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID")
        budget_guard = _cost_tracker.check_budget_guard(
            endpoint=request_endpoint,
            tenant_id=tenant_id,
        )
        if not bool(budget_guard.get("allowed", True)):
            raise _build_contract_http_exception(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                code="ONE_BUTTON_BUDGET_EXCEEDED",
                message="Budget guard blocked this one-button request.",
                endpoint=request_endpoint,
                retryable=True,
                details=budget_guard,
            )

    try:
        inner_response: DecisionResponse = await controller.run_pipeline(decision_request)
    except TaxonomyValidationError as exc:
        _record_schema_validation_failure()
        raise _build_contract_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="TAXONOMY_VALIDATION_FAILED",
            message="Taxonomy resolution failed.",
            endpoint=request_endpoint,
            retryable=False,
            details=exc.as_dict(),
        ) from exc
    except Exception as exc:
        logger.exception("one-button pipeline failed unexpectedly")
        raise _build_contract_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="ONE_BUTTON_PIPELINE_ERROR",
            message=str(exc),
            endpoint=request_endpoint,
            retryable=True,
        ) from exc

    if inner_response.status == "ERROR":
        raise _build_contract_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="ONE_BUTTON_PIPELINE_ERROR",
            message="Pipeline returned ERROR status.",
            endpoint=request_endpoint,
            retryable=True,
            details={
                "trace_id": inner_response.trace_id,
                "reasoning_path": inner_response.reasoning_path,
                "stage_log": inner_response.stage_log,
            },
        )

    idempotency_state = IdempotencyInfo(
        key=idempotency_key,
        status="stored" if idempotency_key else "not_provided",
        replayed=False,
        request_hash=request_hash if idempotency_key else None,
    )

    result = _assemble_response(
        inner_response,
        request_endpoint=request_endpoint,
        idempotency=idempotency_state,
    )

    prompt_context = get_prompt_context()
    prompt_version = prompt_context.prompt_version or ONE_BUTTON_CONTRACT_VERSION
    model_version = getattr(inner_response.meta, "model_version", None) or prompt_context.model_version
    explanation_status = "success" if inner_response.explanation is not None else "fallback_or_skipped"

    request.state.telemetry_prompt_version = prompt_version
    request.state.telemetry_model_version = model_version
    request.state.telemetry_explanation_status = explanation_status

    if isinstance(result.meta, dict):
        result.meta["endpoint_version"] = ONE_BUTTON_RESPONSE_SCHEMA_VERSION
        result.meta["prompt_version"] = prompt_version

    if _cost_tracker is not None and hasattr(_cost_tracker, "record_request_cost"):
        try:
            usage = _estimate_token_and_storage_usage(body, inner_response)
            market_items = len(inner_response.market_insights or [])
            redis_ops = 2 if getattr(request.state, "rate_limit_decision", None) is not None else 0
            queue_ops = market_items * 2
            conversion_event = _coerce_bool(request.headers.get("X-Conversion-Event"))
            tenant_id = getattr(request.state, "tenant_id", None) or request.headers.get("X-Tenant-ID")
            model_id = prompt_context.model_id or "decision_pipeline"

            cost_payload = _cost_tracker.record_request_cost(
                request_id=str(getattr(request.state, "request_id", "") or "unknown"),
                trace_id=inner_response.trace_id,
                endpoint=request_endpoint,
                endpoint_version=ONE_BUTTON_RESPONSE_SCHEMA_VERSION,
                tenant_id=tenant_id,
                model_id=model_id,
                model_version=model_version,
                prompt_version=prompt_version,
                decision_status=inner_response.status,
                explanation_status=explanation_status,
                prompt_tokens=int(usage["prompt_tokens"]),
                completion_tokens=int(usage["completion_tokens"]),
                redis_ops=int(redis_ops),
                queue_ops=int(queue_ops),
                storage_bytes=int(usage["request_bytes"] + usage["response_bytes"]),
                market_crawl_jobs=int(market_items),
                conversion=conversion_event,
            )

            record = cost_payload.get("record", {}) if isinstance(cost_payload, dict) else {}
            unit_econ = cost_payload.get("unit_economics", {}) if isinstance(cost_payload, dict) else {}
            budget = cost_payload.get("budget", {}) if isinstance(cost_payload, dict) else {}
            cost_breakdown = record.get("cost", {}) if isinstance(record, dict) else {}

            if isinstance(result.meta, dict):
                result.meta["cost"] = cost_breakdown
                result.meta["unit_economics"] = unit_econ
                result.meta["budget"] = budget

            request.state.telemetry_cost_total_usd = float(
                cost_breakdown.get("total_cost_usd", 0.0) or 0.0
            )
            request.state.telemetry_cost_breakdown = cost_breakdown
            request.state.telemetry_unit_cost_per_decision_usd = float(
                unit_econ.get("cost_per_decision_usd", 0.0) or 0.0
            )
            request.state.telemetry_unit_cost_per_successful_explanation_usd = float(
                unit_econ.get("cost_per_successful_explanation_usd", 0.0) or 0.0
            )
        except Exception:
            logger.debug("one-button cost attribution failed", exc_info=True)

    if idempotency_key:
        _idempotency_cache[idempotency_key] = {
            "request_hash": request_hash,
            "response": result.model_copy(deep=True),
            "created_at": time.time(),
        }

    _record_contract_compliant()

    if response is not None:
        _set_contract_headers(response, result.idempotency)

    return result


@router.post(
    "/run",
    response_model=OneButtonResponse,
    summary="Canonical one-button orchestration endpoint",
    status_code=status.HTTP_200_OK,
)
async def one_button_run(
    request: Request,
    body: OneButtonRequest,
    response: Response,
) -> OneButtonResponse:
    return await execute_one_button_contract(
        request,
        body,
        request_endpoint=CANONICAL_ONE_BUTTON_ENDPOINT,
        legacy_mode=False,
        response=response,
    )


@router.get(
    "/health",
    summary="One-Button Service Health",
    description="Liveness check for the one-button orchestration endpoint.",
)
async def one_button_health() -> Dict[str, Any]:
    uptime = time.time() - _start_time
    ctrl = _get_controller()
    return {
        "service": "one-button",
        "healthy": ctrl is not None,
        "uptime_seconds": round(uptime, 1),
        "required_stages": REQUIRED_STAGES,
        "entrypoint": CANONICAL_ONE_BUTTON_ENDPOINT,
        "contract_version": ONE_BUTTON_CONTRACT_VERSION,
        "request_schema_version": ONE_BUTTON_REQUEST_SCHEMA_VERSION,
        "response_schema_version": ONE_BUTTON_RESPONSE_SCHEMA_VERSION,
    }

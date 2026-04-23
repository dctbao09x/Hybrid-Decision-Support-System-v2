# backend/api/middleware/telemetry.py
"""
Route Telemetry Middleware (Production)
=======================================
Standardized telemetry with:
    - request_id + correlation_id propagation
    - OTel spans with standard naming
    - structured log event contract
    - PII-redacted payload logging (opt-in)
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.core.telemetry.attributes import TelemetryAttributes
from backend.core.telemetry.context import get_prompt_context, set_request_context
from backend.core.telemetry.contracts import (
    CostBreakdown,
    ModelInfo,
    PromptInfo,
    TelemetryError,
    TelemetryLogEvent,
    TelemetryPipelineEvent,
    TokenUsage,
)
from backend.core.telemetry.custom_metrics import HTTP_REQUEST_LATENCY
from backend.core.telemetry.otel_setup import tracer
from backend.core.telemetry.redaction import redact_dict, redact_text
from backend.core.telemetry.span_naming import SpanNames

logger = logging.getLogger("api.telemetry")


# ─── Payload size config ───────────────────────────────────────────────────────
MAX_BODY_LOG_BYTES: int = int(os.getenv("TELEMETRY_MAX_BODY_LOG_BYTES", "512"))
LOG_BODY: bool = os.getenv("TELEMETRY_LOG_BODY", "false").lower() == "true"
SKIP_PATHS: frozenset[str] = frozenset({"/metrics", "/favicon.ico", "/health", "/health/live", "/health/full"})
HIGH_PRIORITY_PATHS: frozenset[str] = frozenset({"/api/v1/decision", "/api/v1/infer", "/api/v1/explain"})
DEBUG_TRACE_HEADER: str = "x-debug-trace"


class RouteTelemetryMiddleware:
    """
    ASGI middleware — wraps receive so request body is never lost.

    For every request it emits a single structured log line:
        TELEMETRY | <method> <path> | status=<N> | <dur_ms>ms | body=<N>B

    The body is logged as a compact JSON snippet (first MAX_BODY_LOG_BYTES
    bytes) or as raw text for non-JSON payloads.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        path: str = scope.get("path", "")

        # Skip noisy paths
        if path in SKIP_PATHS or path.startswith("/static"):
            await self.app(scope, receive, send)
            return

        raw_body: bytes = b""
        try:
            raw_body = await request.body()
        except Exception:
            raw_body = b""

        # Patch receive so downstream can still read the body
        body_iterator = iter([raw_body])
        body_consumed = False

        async def patched_receive() -> Message:
            nonlocal body_consumed
            if not body_consumed:
                body_consumed = True
                return {"type": "http.request", "body": raw_body, "more_body": False}
            # After the first read, return a disconnect message
            original = await receive()
            return original

        response_status: int = 0

        request_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:12]}"
        correlation_id = request.headers.get("x-correlation-id") or f"corr-{uuid.uuid4().hex[:12]}"
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        set_request_context(request_id, correlation_id)

        method = scope.get("method", "?")
        trace_priority = "high" if path in HIGH_PRIORITY_PATHS or request.headers.get(DEBUG_TRACE_HEADER) else "normal"
        tenant_hint = request.headers.get("x-tenant-id", "")
        endpoint_version_hint = "v1" if path.startswith("/api/v1/") else ""

        prompt_context = get_prompt_context()
        span_attributes = {
            TelemetryAttributes.REQUEST_ID: request_id,
            TelemetryAttributes.CORRELATION_ID: correlation_id,
            TelemetryAttributes.TENANT_ID: tenant_hint,
            TelemetryAttributes.ENDPOINT: path,
            TelemetryAttributes.ENDPOINT_VERSION: endpoint_version_hint,
            TelemetryAttributes.TRACE_PRIORITY: trace_priority,
            TelemetryAttributes.PIPELINE_STAGE: SpanNames.REQUEST_RECEIVE,
            TelemetryAttributes.PROMPT_ID: prompt_context.prompt_id or "",
            TelemetryAttributes.PROMPT_VERSION: prompt_context.prompt_version or "",
            TelemetryAttributes.PROMPT_HASH: prompt_context.prompt_hash or "",
            TelemetryAttributes.MODEL_ID: prompt_context.model_id or "",
            TelemetryAttributes.MODEL_VERSION: prompt_context.model_version or "",
            TelemetryAttributes.SCHEMA_VERSION: prompt_context.schema_version or "",
            TelemetryAttributes.SCORING_VERSION: prompt_context.scoring_version or "",
            TelemetryAttributes.DATASET_VERSION: prompt_context.dataset_version or "",
            "http.method": method,
            "http.target": path,
        }

        async def patched_send(message: Message) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message.get("status", 0)
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                headers.append((b"x-correlation-id", correlation_id.encode()))
                message["headers"] = headers
            await send(message)

        start = time.perf_counter()

        with tracer.start_as_current_span(SpanNames.REQUEST_RECEIVE, attributes=span_attributes) as span:
            try:
                await self.app(scope, patched_receive, patched_send)
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                span.set_attribute(TelemetryAttributes.REQUEST_DURATION_MS, round(duration_ms, 2))
                span.set_attribute("http.status_code", response_status)

                tenant_id = getattr(request.state, "tenant_id", None) or request.headers.get("x-tenant-id")
                endpoint_version = getattr(request.state, "telemetry_endpoint_version", None)
                if not endpoint_version and path.startswith("/api/v1/"):
                    endpoint_version = "v1"

                prompt_version = (
                    getattr(request.state, "telemetry_prompt_version", None)
                    or prompt_context.prompt_version
                )
                model_version = (
                    getattr(request.state, "telemetry_model_version", None)
                    or prompt_context.model_version
                )
                explanation_status = getattr(request.state, "telemetry_explanation_status", None)

                raw_cost_total = getattr(request.state, "telemetry_cost_total_usd", None)
                cost_total = _to_float(raw_cost_total)
                raw_cost_breakdown = getattr(request.state, "telemetry_cost_breakdown", None)
                unit_cost_per_decision = _to_float(
                    getattr(request.state, "telemetry_unit_cost_per_decision_usd", None)
                )
                unit_cost_per_successful_explanation = _to_float(
                    getattr(
                        request.state,
                        "telemetry_unit_cost_per_successful_explanation_usd",
                        None,
                    )
                )

                if tenant_id:
                    span.set_attribute(TelemetryAttributes.TENANT_ID, str(tenant_id))
                span.set_attribute(TelemetryAttributes.ENDPOINT, path)
                if endpoint_version:
                    span.set_attribute(TelemetryAttributes.ENDPOINT_VERSION, str(endpoint_version))
                if explanation_status:
                    span.set_attribute(TelemetryAttributes.EXPLANATION_STATUS, str(explanation_status))
                if cost_total is not None:
                    span.set_attribute(TelemetryAttributes.COST_TOTAL_USD, cost_total)

                # Optional flags for dynamic sampling and incident triage
                low_confidence = bool(getattr(request.state, "low_confidence", False))
                hitl_escalated = bool(getattr(request.state, "hitl_escalated", False))
                span.set_attribute(TelemetryAttributes.LOW_CONFIDENCE, low_confidence)
                span.set_attribute(TelemetryAttributes.HITL_ESCALATED, hitl_escalated)

                cost_breakdown_obj = _build_cost_breakdown(raw_cost_breakdown)
                if cost_breakdown_obj is not None:
                    span.set_attribute(
                        TelemetryAttributes.COST_TOKEN_USD,
                        float(cost_breakdown_obj.token_cost_usd),
                    )
                    span.set_attribute(
                        TelemetryAttributes.COST_REDIS_USD,
                        float(cost_breakdown_obj.redis_cost_usd),
                    )
                    span.set_attribute(
                        TelemetryAttributes.COST_QUEUE_USD,
                        float(cost_breakdown_obj.queue_cost_usd),
                    )
                    span.set_attribute(
                        TelemetryAttributes.COST_STORAGE_USD,
                        float(cost_breakdown_obj.storage_cost_usd),
                    )
                    span.set_attribute(
                        TelemetryAttributes.COST_MARKET_CRAWL_USD,
                        float(cost_breakdown_obj.market_crawl_cost_usd),
                    )

                if unit_cost_per_decision is not None:
                    span.set_attribute(
                        TelemetryAttributes.UNIT_COST_PER_DECISION,
                        unit_cost_per_decision,
                    )
                if unit_cost_per_successful_explanation is not None:
                    span.set_attribute(
                        TelemetryAttributes.UNIT_COST_PER_SUCCESSFUL_EXPLANATION,
                        unit_cost_per_successful_explanation,
                    )

                if response_status:
                    HTTP_REQUEST_LATENCY.labels(
                        route=path,
                        method=method,
                        status=str(response_status),
                    ).observe(duration_ms / 1000.0)

                body_snippet = _summarise_body(raw_body) if LOG_BODY else ""
                if body_snippet:
                    body_snippet = redact_text(body_snippet)

                error = None
                status_label = "ok"
                if response_status >= 500:
                    error = TelemetryError(error_type="server_error", error_code=f"HTTP_{response_status}")
                    status_label = "error"
                elif response_status >= 400:
                    error = TelemetryError(error_type="client_error", error_code=f"HTTP_{response_status}")
                    status_label = "error"

                if error:
                    span.set_attribute(TelemetryAttributes.ERROR_TYPE, error.error_type)

                trace_id = span.get_span_context().trace_id
                event = TelemetryLogEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    event_type="http.request",
                    severity="ERROR" if error else "INFO",
                    component="api",
                    status=status_label,
                    endpoint=path,
                    endpoint_version=endpoint_version,
                    tenant_id=str(tenant_id) if tenant_id is not None else None,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    trace_id=f"{trace_id:032x}" if trace_id else None,
                    span_name=SpanNames.REQUEST_RECEIVE,
                    pipeline_stage=SpanNames.REQUEST_RECEIVE,
                    duration_ms=round(duration_ms, 2),
                    payload_bytes=len(raw_body),
                    payload_snippet=body_snippet or None,
                    error=error,
                    error_code=error.error_code if error else None,
                    prompt_version=prompt_version,
                    model_version=model_version,
                    prompt=PromptInfo(
                        prompt_id=prompt_context.prompt_id,
                        prompt_version=prompt_version,
                        prompt_hash=prompt_context.prompt_hash,
                    ),
                    model=ModelInfo(
                        model_id=prompt_context.model_id,
                        model_version=model_version,
                    ),
                    token_usage=TokenUsage(),
                    cost_usd=cost_total,
                    cost_breakdown=cost_breakdown_obj,
                    explanation_status=explanation_status,
                    unit_cost_per_decision_usd=unit_cost_per_decision,
                    unit_cost_per_successful_explanation_usd=unit_cost_per_successful_explanation,
                    schema_version=prompt_context.schema_version,
                    scoring_version=prompt_context.scoring_version,
                    dataset_version=prompt_context.dataset_version,
                )

                logger.info(event.model_dump_json())

                # Emit minimal pipeline contract event for cross-service correlation
                pipeline_event = TelemetryPipelineEvent(
                    request_id=request_id,
                    trace_id=f"{trace_id:032x}" if trace_id else "",
                    correlation_id=correlation_id,
                    endpoint=path,
                    endpoint_version=endpoint_version,
                    tenant_id=str(tenant_id) if tenant_id is not None else None,
                    pipeline_stage=SpanNames.REQUEST_RECEIVE,
                    status=status_label,
                    duration_ms=round(duration_ms, 2),
                    error_code=error.error_code if error else None,
                    explanation_status=explanation_status,
                    confidence=float(getattr(request.state, "confidence", 0.0))
                    if getattr(request.state, "confidence", None) is not None
                    else None,
                    model_version=model_version,
                    prompt_version=prompt_version,
                    schema_version=prompt_context.schema_version,
                    scoring_version=prompt_context.scoring_version,
                    dataset_version=prompt_context.dataset_version,
                    cost_usd=cost_total,
                    cost_breakdown=cost_breakdown_obj,
                    unit_cost_per_decision_usd=unit_cost_per_decision,
                    unit_cost_per_successful_explanation_usd=unit_cost_per_successful_explanation,
                )
                logger.info(pipeline_event.model_dump_json())


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _summarise_body(raw: bytes) -> str:
    """
    Returns a compact human-readable snippet of the payload.
    Returns empty string for empty bodies.
    """
    if not raw:
        return ""
    # Try JSON first
    try:
        obj = json.loads(raw)
        obj = redact_dict(obj)
        snippet = json.dumps(obj, ensure_ascii=True, separators=(",", ":"))
        if len(snippet) > MAX_BODY_LOG_BYTES:
            snippet = snippet[:MAX_BODY_LOG_BYTES] + "…"
        return snippet
    except (json.JSONDecodeError, ValueError):
        pass
    # Plain text / form data
    try:
        text = raw.decode("utf-8", errors="replace")
        text = redact_text(text)
        if len(text) > MAX_BODY_LOG_BYTES:
            return text[:MAX_BODY_LOG_BYTES] + "…"
        return text
    except Exception:
        return f"<binary {len(raw)}B>"


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _build_cost_breakdown(raw: Any) -> Optional[CostBreakdown]:
    if not isinstance(raw, dict):
        return None
    try:
        return CostBreakdown(
            token_cost_usd=float(raw.get("token_cost_usd", 0.0) or 0.0),
            redis_cost_usd=float(raw.get("redis_cost_usd", 0.0) or 0.0),
            queue_cost_usd=float(raw.get("queue_cost_usd", 0.0) or 0.0),
            storage_cost_usd=float(raw.get("storage_cost_usd", 0.0) or 0.0),
            market_crawl_cost_usd=float(raw.get("market_crawl_cost_usd", 0.0) or 0.0),
            total_cost_usd=float(raw.get("total_cost_usd", 0.0) or 0.0),
        )
    except Exception:
        logger.debug("invalid telemetry cost breakdown payload", exc_info=True)
        return None

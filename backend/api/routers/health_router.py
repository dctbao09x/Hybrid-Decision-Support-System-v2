# backend/api/routers/health_router.py
"""
Health Check Router (Consolidated)
==================================

All health endpoints consolidated under /api/v1/health/*

Endpoints:
  - GET /api/v1/health/live    — Liveness probe
  - GET /api/v1/health/full    — Full readiness probe  
  - GET /api/v1/health/ready   — Alias for /full
  - GET /api/v1/health/scoring — Scoring engine health
  - GET /api/v1/health/llm     — LLM (Ollama) health
  - GET /api/v1/health/warmup  — Combined warmup status
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("api.routers.health")

router = APIRouter(tags=["Health"])


# ==============================================================================
# Response Models
# ==============================================================================

class LivenessResponse(BaseModel):
    """Liveness probe response."""
    status: str = Field(..., description="Service status")
    timestamp: str = Field(..., description="Check timestamp")


class ReadinessResponse(BaseModel):
    """Full readiness probe response."""
    status: str = Field(..., description="Overall status")
    components: Dict[str, Any] = Field(default_factory=dict, description="Component statuses")
    metrics: Optional[Dict[str, Any]] = Field(None, description="Key metrics")
    timestamp: str = Field(..., description="Check timestamp")


class ScoringHealthResponse(BaseModel):
    """Scoring engine health response."""
    status: str = Field(..., description="Scoring status")
    model_loaded: bool = Field(False, description="Model loaded status")
    cache_warm: bool = Field(False, description="Cache status")
    feature_sync: bool = Field(False, description="Feature sync status")


class LLMHealthResponse(BaseModel):
    """LLM health response."""
    ollama_up: bool = Field(False, description="Ollama service status")
    model_ready: bool = Field(False, description="Model ready status")
    last_warmup: Optional[str] = Field(None, description="Last warmup timestamp")


class LLMAnomalyResponse(BaseModel):
    """LLM anomaly rate response."""
    anomaly_rate: float = Field(0.0, description="Anomaly rate percentage")
    error_rate: float = Field(0.0, description="Error rate percentage")
    timeout_rate: float = Field(0.0, description="Timeout rate percentage")
    avg_latency_ms: float = Field(0.0, description="Average latency in ms")
    p95_latency_ms: float = Field(0.0, description="95th percentile latency")
    total_requests: int = Field(0, description="Total requests in window")
    failed_requests: int = Field(0, description="Failed requests in window")
    threshold: float = Field(0.05, description="Anomaly threshold")
    is_anomaly: bool = Field(False, description="Whether anomaly is detected")
    timestamp: str = Field(default="", description="Check timestamp")


class WarmupResponse(BaseModel):
    """Warmup status response."""
    status: str = Field(..., description="Warmup status")
    llm_ready: bool = Field(False, description="LLM ready status")
    model: str = Field(default="", description="LLM model name")
    warmup_time_ms: float = Field(default=0.0, description="Warmup duration")
    message: str = Field(default="", description="Status message")


class FullHealthResponse(BaseModel):
    """
    Governance-grade full system health response (Prompt-13).

    Every component is individually probed; each sub-dict has its own
    ``status`` field (``healthy|degraded|unhealthy``) so the caller
    can tell WHICH component is failing.

    Top-level ``status`` is determined by the worst-performing component,
    weighted by criticality.
    """

    status: str = Field(
        ...,
        description="Overall system status: healthy | degraded | unhealthy",
    )
    timestamp: str = Field(..., description="ISO-8601 UTC timestamp of this check")

    router_status: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Router registry health: registered_count, missing_critical routers, "
            "all_critical_up flag."
        ),
    )
    rule_engine_status: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Rule engine health: rules_loaded, engine_healthy, "
            "governance log accessibility, KB mapping log accessibility."
        ),
    )
    ml_status: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "ML registry health: registry_accessible, active_model_version, "
            "active_model_accuracy, running_job, stuck_job_detected."
        ),
    )
    taxonomy_status: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Taxonomy manager health: manager_available, datasets_loaded, "
            "dataset_counts, total_entries."
        ),
    )
    pipeline_status: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Pipeline controller health: controller_available, "
            "drift_log_accessible, retrain_log_accessible."
        ),
    )


# ==============================================================================
# Store ops reference (injected at startup)
# ==============================================================================

_ops_hub = None


def set_ops_hub(ops):
    """Set the OpsHub reference for health checks."""
    global _ops_hub
    _ops_hub = ops


def get_ops():
    """Get OpsHub instance."""
    return _ops_hub


# ==============================================================================
# Routes
# ==============================================================================

@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description="Lightweight liveness check - no dependency checks",
)
async def health_live():
    """Liveness probe - lightweight, no dependency checks."""
    ops = get_ops()
    if ops and hasattr(ops, 'health') and hasattr(ops.health, 'live'):
        return await ops.health.live()
    
    return LivenessResponse(
        status="alive",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/full",
    response_model=FullHealthResponse,
    summary="Full pipeline health check (Prompt-13)",
    description=(
        "Governance-grade readiness probe.  Runs 5 independent component probes:\n"
        "  • router_status      — all core routers registered & importable\n"
        "  • rule_engine_status — rules loaded, governance logs accessible\n"
        "  • ml_status          — model registry + retrain job log accessible\n"
        "  • taxonomy_status    — taxonomy manager + datasets loaded\n"
        "  • pipeline_status    — main controller + drift/retrain logs\n\n"
        "Overall ``status`` degrades from 'healthy' → 'degraded' → 'unhealthy' "
        "based on the worst-performing component and its criticality level."
    ),
)
async def health_full():
    """
    Full pipeline health check — 5 component probes.

    Suitable for:
    * Kubernetes readiness probe (check ``status != 'unhealthy'``)
    * Admin dashboard early-failure detection
    * Automated alert triggers when ``status == 'unhealthy'``

    None of the probes raise — every failure surfaces as a ``status`` field
    inside the relevant component dict.
    """
    import asyncio

    # Run all probes in a thread pool (they are sync) to avoid blocking the event loop.
    from backend.health.component_probes import assemble_full_health

    try:
        result = await asyncio.to_thread(assemble_full_health)
    except Exception as exc:
        logger.error("[health/full] assemble_full_health raised unexpectedly: %s", exc)
        now = datetime.now(timezone.utc).isoformat()
        result = {
            "status":             "unhealthy",
            "timestamp":          now,
            "router_status":      {"status": "unknown", "error": str(exc), "checked_at": now},
            "rule_engine_status": {"status": "unknown", "error": str(exc), "checked_at": now},
            "ml_status":          {"status": "unknown", "error": str(exc), "checked_at": now},
            "taxonomy_status":    {"status": "unknown", "error": str(exc), "checked_at": now},
            "pipeline_status":    {"status": "unknown", "error": str(exc), "checked_at": now},
        }

    return FullHealthResponse(**result)


@router.get(
    "/ready",
    response_model=FullHealthResponse,
    summary="Readiness probe (alias for /full)",
    description="Kubernetes readiness probe — alias for ``GET /health/full``.",
)
async def health_ready():
    """Readiness probe — alias for /full (backward compat)."""
    return await health_full()


@router.get(
    "/startup",
    summary="Startup probe",
    description="Kubernetes startupProbe — returns 200 when initialization is complete.",
)
async def health_startup():
    """Startup probe — returns 200 once the server has finished initialising."""
    from datetime import datetime, timezone
    return {
        "status": "started",
        "startup_complete": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get(
    "/scoring",
    response_model=ScoringHealthResponse,
    summary="Scoring engine health",
    description="Check scoring engine status including model and cache",
)
async def health_scoring():
    """Scoring engine health check."""
    try:
        from backend.ops.warmup import get_warmup_manager
        warmup = get_warmup_manager()
        return await warmup.get_scoring_health()
    except ImportError:
        return ScoringHealthResponse(
            status="unavailable",
            model_loaded=False,
            cache_warm=False,
            feature_sync=False,
        )


@router.get(
    "/llm",
    response_model=LLMHealthResponse,
    summary="LLM health check",
    description="Check Ollama LLM service status",
)
async def health_llm():
    """LLM (Ollama) health check."""
    try:
        from backend.ops.warmup import get_warmup_manager
        warmup = get_warmup_manager()
        return await warmup.get_llm_health()
    except ImportError:
        return LLMHealthResponse(
            ollama_up=False,
            model_ready=False,
            last_warmup=None,
        )


@router.get(
    "/llm/anomaly-rate",
    response_model=LLMAnomalyResponse,
    summary="LLM anomaly rate",
    description="Get LLM anomaly and error rate metrics",
)
async def health_llm_anomaly():
    """LLM anomaly rate metrics."""
    from datetime import datetime, timezone
    
    # Try to get metrics from ops monitoring
    try:
        from backend.ops.monitoring.metrics import get_metrics_collector
        collector = get_metrics_collector()
        llm_metrics = collector.get_llm_metrics() if hasattr(collector, 'get_llm_metrics') else {}
        
        total = llm_metrics.get("total_requests", 0)
        failed = llm_metrics.get("failed_requests", 0)
        timeouts = llm_metrics.get("timeout_requests", 0)
        
        error_rate = failed / total if total > 0 else 0.0
        timeout_rate = timeouts / total if total > 0 else 0.0
        anomaly_rate = error_rate + timeout_rate
        
        return LLMAnomalyResponse(
            anomaly_rate=round(anomaly_rate, 4),
            error_rate=round(error_rate, 4),
            timeout_rate=round(timeout_rate, 4),
            avg_latency_ms=llm_metrics.get("avg_latency_ms", 0.0),
            p95_latency_ms=llm_metrics.get("p95_latency_ms", 0.0),
            total_requests=total,
            failed_requests=failed,
            threshold=0.05,
            is_anomaly=anomaly_rate > 0.05,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except ImportError:
        # Return default/mock data if monitoring not available
        return LLMAnomalyResponse(
            anomaly_rate=0.0,
            error_rate=0.0,
            timeout_rate=0.0,
            avg_latency_ms=0.0,
            p95_latency_ms=0.0,
            total_requests=0,
            failed_requests=0,
            threshold=0.05,
            is_anomaly=False,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


@router.get(
    "/warmup",
    summary="Warmup status",
    description="Get combined warmup status for all components",
)
async def health_warmup():
    """Combined warmup status for all components."""
    try:
        from backend.ops.warmup import get_warmup_manager
        warmup = get_warmup_manager()
        return warmup.get_status()
    except ImportError:
        return {"status": "warmup_manager_unavailable"}


@router.post(
    "/warmup",
    response_model=WarmupResponse,
    summary="Trigger LLM warmup",
    description="Warm up the LLM model for faster first response",
)
async def trigger_warmup():
    """Warm up LLM for faster responses."""
    start_time = time.time()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "http://127.0.0.1:11434/api/generate",
                json={
                    "model": "llama3.2:1b",
                    "prompt": "Hello",
                    "stream": False,
                },
            )
            warmup_time = (time.time() - start_time) * 1000
            
            if resp.status_code == 200:
                return WarmupResponse(
                    status="success",
                    llm_ready=True,
                    model="llama3.2:1b",
                    warmup_time_ms=warmup_time,
                    message="LLM warmed up successfully",
                )
            else:
                return WarmupResponse(
                    status="error",
                    llm_ready=False,
                    model="llama3.2:1b",
                    warmup_time_ms=warmup_time,
                    message=f"Ollama returned {resp.status_code}",
                )
    except Exception as e:
        warmup_time = (time.time() - start_time) * 1000
        return WarmupResponse(
            status="error",
            llm_ready=False,
            model="llama3.2:1b",
            warmup_time_ms=warmup_time,
            message=str(e),
        )

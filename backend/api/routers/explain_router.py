# backend/api/routers/explain_router.py
"""
Explain API Router
==================

FastAPI router for Explanation API (Stage 5).

Endpoints:
  - POST /api/v1/explain       — Run explanation pipeline
  - GET  /api/v1/explain/{id}  — Get stored explanation by trace_id
  - GET  /api/v1/health        — Health check

All requests go through main-control orchestrator.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, validator

from backend.api.controllers.explain_controller import (
    ExplainController,
    get_explain_controller,
)
from backend.api.middleware.auth import verify_token, AuthResult
from backend.api.middleware.rate_limit import check_rate_limit
from backend.explain.formatter import (
    RuleJustificationEngine,
    EvidenceCollector,
    ConfidenceEstimator,
    build_trace_edges,
)
from backend.explain.models import ExplanationRecord
from backend.explain.storage import get_explanation_storage
from backend.explain.router import router as explain_phase5_router
from backend.feedback.models import TraceRecord
from backend.feedback.storage import get_feedback_storage

logger = logging.getLogger("api.routers.explain")

# Create router with prefix
router = APIRouter(prefix="/api/v1", tags=["explain"])
router.include_router(explain_phase5_router)


# ==============================================================================
# Request/Response Models
# ==============================================================================

class FeaturesInput(BaseModel):
    """Feature input for explanation request."""
    
    math_score: float = Field(..., ge=0, le=10, description="Math score (0-10)")
    logic_score: float = Field(..., ge=0, le=10, description="Logic score (0-10)")
    physics_score: Optional[float] = Field(None, ge=0, le=10, description="Physics score")
    interest_it: Optional[float] = Field(None, ge=0, le=10, description="IT interest")
    language_score: Optional[float] = Field(None, ge=0, le=10, description="Language score")
    creativity_score: Optional[float] = Field(None, ge=0, le=10, description="Creativity score")


class ExplainOptions(BaseModel):
    """Options for explanation request."""
    
    use_llm: bool = Field(True, description="Use LLM formatting (Stage 4)")
    include_meta: bool = Field(True, description="Include metadata in response")


class ExplainRequest(BaseModel):
    """Explanation API request."""
    
    user_id: str = Field(..., min_length=1, max_length=128, description="User identifier")
    request_id: Optional[str] = Field(None, description="Request UUID (auto-generated if not provided)")
    features: FeaturesInput = Field(..., description="User feature scores")
    options: Optional[ExplainOptions] = Field(None, description="Request options")
    
    @validator("request_id", pre=True, always=True)
    def set_request_id(cls, v):
        return v or str(uuid.uuid4())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to controller-compatible dict."""
        return {
            "user_id": self.user_id,
            "request_id": self.request_id,
            "features": self.features.dict(exclude_none=True),
            "options": self.options.dict() if self.options else {},
        }


class MetaInfo(BaseModel):
    """Response metadata."""
    
    model_version: str = Field(..., description="ML model version")
    xai_version: str = Field(..., description="XAI service version")
    stage3_version: str = Field(..., description="Stage 3 engine version")
    stage4_version: str = Field(..., description="Stage 4 engine version")


class ExplainResponse(BaseModel):
    """Explanation API response."""
    
    api_version: str = Field(..., description="API version")
    trace_id: str = Field(..., description="Trace ID for debugging")
    career: str = Field(..., description="Predicted career")
    confidence: float = Field(..., ge=0, le=1, description="Prediction confidence")
    reasons: List[str] = Field(default_factory=list, description="Explanation reasons")
    explain_text: str = Field("", description="Stage 3 explanation text")
    llm_text: str = Field("", description="Stage 4 LLM-formatted text")
    used_llm: bool = Field(False, description="Whether LLM was used")
    meta: Optional[MetaInfo] = Field(None, description="Version metadata")
    explanation_id: Optional[str] = Field(default=None, description="Persistent explanation id")
    model_id: Optional[str] = Field(default=None, description="Model id for deterministic explanation")
    kb_version: Optional[str] = Field(default=None, description="Knowledge base version")
    rule_path: List[Dict[str, Any]] = Field(default_factory=list, description="Rule execution path")
    weights: Dict[str, float] = Field(default_factory=dict, description="Weight mapping")
    evidence: List[Dict[str, Any]] = Field(default_factory=list, description="Collected evidence")
    timestamp: str = Field(..., description="Response timestamp")


class ErrorDetail(BaseModel):
    """Error detail."""
    
    code: str
    message: str


class ErrorResponse(BaseModel):
    """Error response."""
    
    api_version: str
    trace_id: str
    error: ErrorDetail
    timestamp: str


class HealthResponse(BaseModel):
    """Health check response."""
    
    status: str = Field(..., description="Service status")
    api_version: str = Field(..., description="API version")
    components: Dict[str, str] = Field(default_factory=dict, description="Component status")
    uptime_seconds: float = Field(..., description="Service uptime")
    timestamp: str = Field(..., description="Check timestamp")


# ==============================================================================
# Dependency: Controller Instance
# ==============================================================================

_controller: Optional[ExplainController] = None
_start_time = time.time()


def get_controller() -> ExplainController:
    """Get controller instance (for dependency injection)."""
    global _controller
    if _controller is None:
        _controller = get_explain_controller()
    return _controller


def set_controller(controller: ExplainController) -> None:
    """Set controller instance (for testing)."""
    global _controller
    _controller = controller


# ==============================================================================
# Routes
# ==============================================================================

@router.post(
    "/explain",
    response_model=ExplainResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        429: {"description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Internal error"},
        504: {"model": ErrorResponse, "description": "Timeout"},
    },
    summary="Run explanation pipeline",
    description="Run the full career explanation pipeline: Inference → XAI → Stage3 → Stage4",
)
async def explain(
    request: ExplainRequest,
    controller: ExplainController = Depends(get_controller),
    auth: AuthResult = Depends(verify_token),
    _: None = Depends(check_rate_limit),
):
    """
    Run explanation pipeline for career guidance.
    
    This endpoint orchestrates the full pipeline through main-control:
    1. Model inference (prediction)
    2. XAI explanation (Stage 2)
    3. Rule+Template engine (Stage 3)
    4. LLM formatting (Stage 4, optional)
    
    Returns standardized explanation with trace_id for debugging.
    """
    # Convert to dict and handle
    result = await controller.handle(request.to_dict())
    
    # Check for error response
    if "error" in result:
        error = result["error"]
        
        # Map error codes to HTTP status
        if error["code"] == "E400":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result,
            )
        elif error["code"] == "E504":
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=result,
            )
        elif error["code"] == "E502":
            # LLM fail - return 200 with fallback (per spec)
            pass
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result,
            )
    
    # Persist deterministic explanation for compliance/audit replay
    trace_id = result.get("trace_id") or request.request_id
    features = request.features.dict(exclude_none=True)
    model_id = (result.get("meta") or {}).get("model_version", "unknown")
    kb_version = os.getenv("MLOPS_KB_VERSION", "kb-v1")

    rule_engine = RuleJustificationEngine()
    fired_rules = rule_engine.evaluate(
        features=features,
        predicted_career=result.get("career", ""),
        predicted_confidence=float(result.get("confidence", 0.0)),
    )

    feedback_storage = get_feedback_storage()
    await feedback_storage.initialize()
    feedback_stats = await feedback_storage.get_feedback_stats()

    confidence_estimator = ConfidenceEstimator()
    deterministic_confidence = confidence_estimator.estimate(
        probabilities=[],
        fired_rules=len(fired_rules),
        total_rules=4,
        features=features,
        feedback_agreement=float(feedback_stats.get("feedback_rate", 0.5)),
    )

    evidence = EvidenceCollector().collect(features, top_careers=[])
    weights = {rule.rule_id: float(rule.weight) for rule in fired_rules}

    storage = get_explanation_storage()
    await storage.initialize()
    explanation_record = await storage.append_record(
        ExplanationRecord(
            trace_id=trace_id,
            model_id=model_id,
            kb_version=kb_version,
            rule_path=fired_rules,
            weights=weights,
            evidence=evidence,
            confidence=deterministic_confidence,
            feature_snapshot=features,
            prediction={
                "career": result.get("career", ""),
                "confidence": float(result.get("confidence", 0.0)),
            },
        )
    )

    await storage.append_graph_edges(
        trace_id=trace_id,
        edges=build_trace_edges(
            trace_id=trace_id,
            user_id=request.user_id,
            features=features,
            fired_rules=fired_rules,
            score=float(result.get("confidence", 0.0)),
            decision=result.get("career", ""),
        ),
    )

    await feedback_storage.store_trace(
        TraceRecord(
            trace_id=trace_id,
            user_id=request.user_id,
            input_profile=features,
            kb_snapshot_version=kb_version,
            model_version=model_id,
            rule_path=[rule.rule_id for rule in fired_rules],
            score_vector=weights,
            timestamp=datetime.now(timezone.utc).isoformat(),
            predicted_career=result.get("career", ""),
            predicted_confidence=float(result.get("confidence", 0.0)),
            reasons=result.get("reasons", []),
            xai_meta={
                "explanation_id": explanation_record.explanation_id,
                "deterministic": True,
            },
        )
    )

    result["explanation_id"] = explanation_record.explanation_id
    result["model_id"] = model_id
    result["kb_version"] = kb_version
    result["rule_path"] = [rule.to_dict() for rule in fired_rules]
    result["weights"] = weights
    result["evidence"] = [item.to_dict() for item in evidence]

    return result


@router.get(
    "/explain/{trace_id}",
    response_model=ExplainResponse,
    responses={
        404: {"description": "Not found"},
        500: {"model": ErrorResponse, "description": "Internal error"},
    },
    summary="Get stored explanation",
    description="Retrieve a previously generated explanation by trace_id",
)
async def get_explain(
    trace_id: str,
    controller: ExplainController = Depends(get_controller),
    auth: AuthResult = Depends(verify_token),
):
    """
    Get stored explanation by trace_id.
    
    Useful for:
    - Debugging
    - Replay/audit
    - Caching
    """
    storage = get_explanation_storage()
    result = await storage.get_by_trace_id(trace_id)

    if result is None:
        result = await controller.get_by_id(trace_id)
    
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "Explanation not found", "trace_id": trace_id},
        )
    
    prediction = result.get("prediction", {}) if isinstance(result, dict) else {}
    return {
        "api_version": "v1",
        "trace_id": trace_id,
        "career": prediction.get("career", result.get("career", "")),
        "confidence": float(prediction.get("confidence", result.get("confidence", 0.0))),
        "reasons": result.get("reasons", []),
        "explain_text": result.get("explain_text", ""),
        "llm_text": result.get("llm_text", ""),
        "used_llm": bool(result.get("used_llm", False)),
        "meta": result.get("meta", None),
        "timestamp": result.get("created_at", result.get("timestamp", datetime.now(timezone.utc).isoformat())),
        "explanation_id": result.get("explanation_id"),
        "model_id": result.get("model_id"),
        "kb_version": result.get("kb_version"),
        "rule_path": result.get("rule_path", []),
        "weights": result.get("weights", {}),
        "evidence": result.get("evidence", []),
    }


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Check API and component health",
)
async def health():
    """
    Health check endpoint.
    
    Returns status of:
    - API service
    - Main control
    - XAI service
    - Stage 3 engine
    - Stage 4 engine (Ollama)
    """
    global _start_time
    
    components = {}
    
    # Check controller
    try:
        controller = get_controller()
        components["controller"] = "healthy"
        
        # Check main control
        if controller._main_control is not None:
            components["main_control"] = "healthy"
        else:
            components["main_control"] = "not_initialized"
        
        # Check history storage
        if controller._history_storage is not None:
            components["history_storage"] = "healthy"
        else:
            components["history_storage"] = "not_configured"
            
    except Exception as e:
        components["controller"] = f"error: {str(e)[:50]}"
    
    # Overall status
    has_errors = any("error" in v for v in components.values())
    overall_status = "degraded" if has_errors else "healthy"
    
    return HealthResponse(
        status=overall_status,
        api_version="v1",
        components=components,
        uptime_seconds=time.time() - _start_time,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ==============================================================================
# Score Analytics Endpoint
# ==============================================================================

class ScoreAnalyticsRequest(BaseModel):
    """Request body for the score analytics explanation endpoint."""

    # ── Scores from ScoringBreakdown (range [0, 100]) ─────────────────────────
    skill_score: float = Field(..., ge=0, le=100, description="Skill sub-score [0–100]")
    experience_score: float = Field(..., ge=0, le=100, description="Experience sub-score [0–100]")
    education_score: float = Field(..., ge=0, le=100, description="Education sub-score [0–100]")
    goal_alignment_score: float = Field(..., ge=0, le=100, description="Goal alignment sub-score [0–100]")
    preference_score: float = Field(..., ge=0, le=100, description="Preference sub-score [0–100]")

    # ── Confidence [0.0–1.0] ─────────────────────────────────────────────────
    confidence: float = Field(0.7, ge=0.0, le=1.0, description="Explanation confidence")

    # ── Profile fields ────────────────────────────────────────────────────────
    skills: List[str] = Field(default_factory=list)
    interests: List[str] = Field(default_factory=list)
    education_level: str = Field("", description="e.g. Bachelor, Master, PhD")
    years_experience: Optional[float] = Field(None, ge=0)

    # ── Preference / goal fields ──────────────────────────────────────────────
    preferred_industry: Optional[List[str]] = None
    work_style: Optional[str] = None
    # Extended optional fields (surfaced as "Insufficient data provided." if absent)
    excluded_industry: Optional[str] = None
    mobility: Optional[str] = None
    languages: Optional[List[str]] = None
    expected_salary: Optional[str] = None
    priority_weight: Optional[str] = None
    training_horizon_months: Optional[int] = Field(None, ge=0)

    # ── LLM timeout ──────────────────────────────────────────────────────────
    timeout: float = Field(30.0, ge=1.0, le=120.0, description="Max seconds to wait for LLM")


class ScoreAnalyticsResponse(BaseModel):
    """Response from the score analytics explanation endpoint."""

    trace_id: str
    markdown: str = Field(..., description="Structured markdown per analytics prompt spec")
    used_llm: bool
    fallback: bool
    fallback_reason: str = Field("none", description="Typed reason for fallback activation")
    prompt_version: str = Field("unknown", description="Prompt template version string")
    engine_version: str = Field("unknown", description="Engine package version")
    latency_ms: float
    timestamp: str


@router.post(
    "/explain/score-analytics",
    response_model=ScoreAnalyticsResponse,
    summary="Generate deterministic score analytics explanation",
    description=(
        "Fills the deterministic career analytics prompt template with real "
        "SIMGR scoring data and returns structured markdown covering input "
        "summary, 5-dimension score analysis, strengths, limitations, "
        "improvement levers, and confidence justification."
    ),
    tags=["explain"],
)
async def score_analytics(
    request: ScoreAnalyticsRequest,
    response: Response,
    auth: AuthResult = Depends(verify_token),
    _: None = Depends(check_rate_limit),
) -> ScoreAnalyticsResponse:
    """
    POST /api/v1/explain/score-analytics

    Accepts a scoring breakdown + profile fields and produces a
    structured markdown document using the ``score_analytics.txt``
    prompt template, optionally enriched by the Ollama LLM.
    Falls back to a fully deterministic document when Ollama is
    unavailable.  Response headers always carry diagnostic metadata.
    """
    from backend.explain.score_analytics import (
        ScoreAnalyticsInput,
        get_score_analytics_engine,
    )

    trace_id = str(uuid.uuid4())

    # Build a lightweight duck-type that looks like ScoringBreakdown sub-scores
    class _FakeBreakdown:
        def __init__(self, r: ScoreAnalyticsRequest) -> None:
            self.skill_score          = r.skill_score
            self.experience_score     = r.experience_score
            self.education_score      = r.education_score
            self.goal_alignment_score = r.goal_alignment_score
            self.preference_score     = r.preference_score

    breakdown_proxy = _FakeBreakdown(request)

    profile: Dict[str, Any] = {
        "skills":          request.skills,
        "interests":       request.interests,
        "education_level": request.education_level or "Insufficient data provided.",
        "preferences": {
            "preferred_domains": request.preferred_industry or [],
            "work_style":        request.work_style or "",
        },
        "goals": {
            "timeline_years": (
                round(request.training_horizon_months / 12)
                if request.training_horizon_months
                else 0
            ),
        },
    }

    inp = ScoreAnalyticsInput.from_scoring_artifacts(
        scoring_breakdown=breakdown_proxy,
        profile=profile,
        confidence=request.confidence,
        experience_years=request.years_experience or 0.0,
    )
    # Patch optional extended fields
    if request.excluded_industry:
        inp.excluded_industry = request.excluded_industry
    if request.mobility:
        inp.mobility = request.mobility
    if request.languages:
        inp.languages = request.languages
    if request.expected_salary:
        inp.expected_salary = request.expected_salary
    if request.priority_weight:
        inp.priority_weight = request.priority_weight
    if request.training_horizon_months is not None:
        inp.training_horizon_months = request.training_horizon_months

    result = await get_score_analytics_engine().generate(
        inp, trace_id=trace_id, timeout=request.timeout
    )

    # ── Diagnostic response headers ───────────────────────────────────────────
    response.headers["X-Prompt-Version"] = result.prompt_version
    response.headers["X-Engine-Version"] = result.engine_version
    response.headers["X-Fallback-Used"] = str(result.fallback).lower()
    response.headers["X-Fallback-Reason"] = result.fallback_reason
    response.headers["X-Trace-Id"] = trace_id

    return ScoreAnalyticsResponse(
        trace_id=trace_id,
        markdown=result.markdown,
        used_llm=result.used_llm,
        fallback=result.fallback,
        fallback_reason=result.fallback_reason,
        prompt_version=result.prompt_version,
        engine_version=result.engine_version,
        latency_ms=result.latency_ms,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ==============================================================================
# V2 Router (Future)
# ==============================================================================

router_v2 = APIRouter(prefix="/api/v2", tags=["explain-v2"])


@router_v2.post(
    "/explain",
    response_model=ExplainResponse,
    summary="Run explanation pipeline (v2)",
    description="V2 endpoint with LLM enabled by default",
)
async def explain_v2(
    request: ExplainRequest,
    controller: ExplainController = Depends(get_controller),
    auth: AuthResult = Depends(verify_token),
    _: None = Depends(check_rate_limit),
):
    """
    V2 explanation endpoint.
    
    Differences from V1:
    - LLM formatting enabled by default
    - Extended response format (future)
    """
    # Force LLM on for v2
    if request.options is None:
        request.options = ExplainOptions(use_llm=True)
    else:
        request.options.use_llm = True
    
    return await explain(request, controller, auth, _)

# backend/api/routers/decision_router.py
"""
Decision Router (1-Button Pipeline)
===================================

REST API for the atomic decision pipeline.

Endpoints:
    POST /api/v1/decision/run      - Execute full decision pipeline
    GET  /api/v1/decision/health   - Health check for decision service

ARCHITECTURE:
    - SINGLE endpoint for user-facing decision
    - NO partial state exposure
    - NO multi-endpoint orchestration
    - Atomic transaction guarantee

ALL pipeline stages executed server-side:
    1. Input Normalize
    2. LLM Feature Extraction
    3. Merge
    4. SIMGR Scoring (DETERMINISTIC - AUTHORITY)
    5. Rule Engine
    6. Market Data Integration
    7. Explanation Layer
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from backend.api.controllers.decision_controller import (
    DecisionController,
    DecisionRequest,
    DecisionResponse,
    UserProfile,
    UserFeatures,
    DecisionOptions,
    get_decision_controller,
    get_rule_log,
    get_recent_rule_logs,
)
from backend.api.taxonomy_gate import TaxonomyValidationError
from backend.scoring.models import ScoringInput
from backend.api.response_contract import success_response, health_response

logger = logging.getLogger("api.routers.decision")

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER SETUP
# ═══════════════════════════════════════════════════════════════════════════════

router = APIRouter(prefix="/api/v1/decision", tags=["Decision"])

_controller: Optional[DecisionController] = None
_start_time = time.time()


def set_controller(controller: DecisionController) -> None:
    """Inject decision controller."""
    global _controller
    _controller = controller
    logger.info("DecisionController injected into decision router")


def _get_controller() -> DecisionController:
    """Get controller with fallback to singleton."""
    return _controller or get_decision_controller()


# ═══════════════════════════════════════════════════════════════════════════════
# API REQUEST MODELS (for OpenAPI docs)
# ═══════════════════════════════════════════════════════════════════════════════

class DecisionRunRequest(BaseModel):
    """Request body for decision/run endpoint."""
    user_id: str = Field(..., description="User identifier")
    scoring_input: ScoringInput = Field(..., description="Full scoring input (all 6 components required)")
    features: Optional[UserFeatures] = Field(None, description="Feature scores for LLM extraction")
    options: Optional[DecisionOptions] = Field(None, description="Pipeline options")

    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": "user_12345",
                "scoring_input": {
                    "personal_profile": {
                        "ability_score": 0.7,
                        "confidence_score": 0.65,
                        "interests": ["technology", "science"]
                    },
                    "experience": {
                        "years": 3,
                        "domains": ["software development"]
                    },
                    "goals": {
                        "career_aspirations": ["software engineer"],
                        "timeline_years": 5
                    },
                    "skills": ["programming", "problem-solving"],
                    "education": {
                        "level": "Bachelor",
                        "field_of_study": "Computer Science"
                    },
                    "preferences": {
                        "preferred_domains": ["technology"],
                        "work_style": "remote"
                    }
                }
            }
        }
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@router.post(
    "/run",
    response_model=DecisionResponse,
    summary="Execute Decision Pipeline",
    description="""
    Execute the full atomic decision pipeline.
    
    This is the **SINGLE** user-facing endpoint for career recommendations.
    One button → One request → Full result.
    
    **Pipeline Stages (all executed server-side):**
    1. Input Normalize
    2. LLM Feature Extraction  
    3. Merge
    4. SIMGR Scoring (deterministic - AUTHORITY)
    5. Rule Engine
    6. Market Data Integration
    7. Explanation Layer
    
    **Guarantees:**
    - Atomic execution (no partial states)
    - Deterministic scoring is final authority
    - LLM only for extraction + explanation
    - Full trace logging
    """,
)
async def run_decision_pipeline(
    request: Request,
    body: DecisionRunRequest,
) -> DecisionResponse:
    """
    Execute the full decision pipeline.
    
    Returns complete career recommendations with explanation and market data.
    """
    controller = _get_controller()
    
    # Convert to internal request model
    decision_request = DecisionRequest(
        user_id=body.user_id,
        scoring_input=body.scoring_input,
        features=body.features,
        options=body.options,
    )
    
    # Execute atomic pipeline
    try:
        response = await controller.run_pipeline(decision_request)
    except TaxonomyValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.as_dict(),
        ) from exc
    
    # Check for error status
    if response.status == "ERROR":
        logger.error(f"Pipeline failed for trace_id={response.trace_id}")
        # Still return the response (contains trace_id for debugging)
        # Don't raise HTTPException - let client handle based on status
    
    return response


@router.get(
    "/health",
    summary="Decision Service Health",
    description="Check if the decision service is operational.",
)
async def decision_health():
    """Health check endpoint for decision service."""
    uptime = time.time() - _start_time
    controller = _get_controller()

    controller_ready = controller is not None
    main_controller_ready = controller._main_controller is not None if controller else False

    return health_response(
        service="decision",
        healthy=controller_ready,
        uptime_seconds=uptime,
        dependencies={
            "controller_ready": controller_ready,
            "main_controller_connected": main_controller_ready,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# P10: RULE EXECUTION LOG ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get(
    "/rule-log",
    summary="Recent Rule Execution Logs",
    description="Returns rule execution logs from the most recent pipeline runs (max 200 in memory).",
)
async def list_rule_logs(
    limit: int = Query(default=50, ge=1, le=200, description="Max logs to return"),
):
    """
    P10: Retrieve rule execution log for recent pipeline runs.

    Returns the last `limit` rule traces, most recent first.
    Each entry contains the trace_id and per-rule audit entries.
    """
    logs = get_recent_rule_logs(limit=limit)
    return success_response(data={
        "count": len(logs),
        "logs": logs,
    })


@router.get(
    "/rule-log/{trace_id}",
    summary="Rule Execution Log for Trace",
    description="Returns the rule execution log for a specific pipeline trace.",
)
async def get_rule_log_by_trace(
    trace_id: str,
):
    """
    P10: Retrieve rule execution log for a specific trace_id.

    Returns the list of rule audit entries that were evaluated
    during Stage 7 of the decision pipeline for the given trace.
    """
    rules = get_rule_log(trace_id)
    if rules is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No rule log found for trace_id='{trace_id}'. Logs are kept in memory (max 200 runs).",
        )
    return success_response(data={
        "trace_id": trace_id,
        "rules_count": len(rules),
        "rules": rules,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER INFO FOR REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

def get_router_info():
    """Get router metadata for registry."""
    return {
        "name": "decision",
        "router": router,
        "prefix": "/api/v1/decision",
        "tags": ["Decision"],
        "controller": "DecisionController",
        "service": "DecisionService",
        "auth": "USER",
        "version": "v1",
        "critical": True,
    }

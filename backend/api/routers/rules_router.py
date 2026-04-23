# backend/api/routers/rules_router.py
"""
Rules Engine API Router  --  HTTP LAYER ONLY
============================================

REST API for Rule Engine operations.

Endpoints:
    GET  /api/v1/rules/health           - Rules service health
    GET  /api/v1/rules/categories       - List rule categories
    GET  /api/v1/rules                  - List all rules
    GET  /api/v1/rules/{rule_name}      - Get rule details
    POST /api/v1/rules/evaluate         - Evaluate profile against rules
    POST /api/v1/rules/evaluate-job     - Evaluate profile for specific job
    POST /api/v1/rules/reload           - Reload rules

ARCHITECTURE:
    - ZERO business logic in this file.
    - ALL logic lives in backend.rule_engine.rule_service.RuleService.
    - Router parses HTTP request, calls service, returns response.
    - No service module may import this router.

RBAC:
    - Read: Admin, Ops, Auditor, Analyst
    - Write: Admin, Ops
    - Execute: Admin, Ops
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.response_contract import (
    success_response,
    paginated_response,
    health_response,
)
from backend.api.middleware.rbac import (
    require_any_role,
    require_permission,
    Permission,
    READ_ROLES,
    WRITE_ROLES,
)
from backend.api.middleware.auth import AuthResult
from backend.rule_engine.rule_service import RuleService

logger = logging.getLogger("api.routers.rules")

router = APIRouter(tags=["Rules"])


# =========================================================================
#  Request / Response models  (HTTP layer only — shape defines the contract)
# =========================================================================

class ProfileInput(BaseModel):
    """User profile input for rule evaluation."""
    age: Optional[int] = Field(default=None)
    education_level: Optional[str] = Field(default=None)
    skills: List[str] = Field(default_factory=list)
    interests: List[str] = Field(default_factory=list)
    intent: Optional[str] = Field(default=None)
    similarity_scores: Optional[Dict[str, float]] = Field(default=None)
    extra: Optional[Dict[str, Any]] = Field(default=None)


class EvaluateRequest(BaseModel):
    """Request to evaluate profile against all rules."""
    profile: ProfileInput


class EvaluateJobRequest(BaseModel):
    """Request to evaluate profile for a specific job."""
    profile: ProfileInput
    job_name: str


# =========================================================================
#  Endpoints
# =========================================================================

@router.get("/health")
async def rules_health():
    """Rules engine health check."""
    data = RuleService.health()
    return health_response(
        service="rules",
        healthy=data["healthy"],
        uptime_seconds=data["uptime_seconds"],
        dependencies=data["dependencies"],
    )


@router.get("/categories")
async def list_categories(
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """List all rule categories."""
    return success_response(data=RuleService.list_categories())


@router.get("")
async def list_rules(
    category: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """List all loaded rules (with optional category filter + pagination)."""
    try:
        data = RuleService.list_rules(category=category, page=page, page_size=page_size)
    except Exception as exc:
        logger.error("list_rules error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return paginated_response(
        items=data["rules"],
        page=data["page"],
        page_size=data["page_size"],
        total_items=data["total"],
        item_key="rules",
    )


@router.get("/{rule_name}")
async def get_rule(
    rule_name: str,
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """Get details of a specific rule."""
    try:
        rule = RuleService.get_rule(rule_name)
    except Exception as exc:
        logger.error("get_rule error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rule '{rule_name}' not found",
        )
    return success_response(data={"rule": rule})


@router.post("/evaluate")
async def evaluate_profile(
    request: EvaluateRequest,
    auth: AuthResult = Depends(require_permission(Permission.RULES_READ)),
):
    """Evaluate a profile against all rules; returns ranked jobs."""
    try:
        profile_dict = request.profile.model_dump()
        evaluation = RuleService.evaluate_profile(profile_dict)
    except Exception as exc:
        logger.error("evaluate_profile error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return success_response(data={"evaluation": evaluation})


@router.post("/evaluate-job")
async def evaluate_job(
    request: EvaluateJobRequest,
    auth: AuthResult = Depends(require_permission(Permission.RULES_READ)),
):
    """Evaluate a profile for a specific job."""
    try:
        profile_dict = request.profile.model_dump()
        result = RuleService.evaluate_job(profile_dict, request.job_name)
    except Exception as exc:
        logger.error("evaluate_job error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{request.job_name}' not found in job database",
        )
    return success_response(data={"evaluation": result})


@router.post("/reload")
async def reload_rules(
    auth: AuthResult = Depends(require_permission(Permission.RULES_WRITE)),
):
    """Reload all rules from scratch."""
    try:
        result = RuleService.reload()
    except Exception as exc:
        logger.error("reload_rules error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return success_response(data=result)

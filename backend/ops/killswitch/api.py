# backend/ops/killswitch/api.py
"""
Kill-Switch REST API
====================

RESTful API endpoints for kill-switch operations:
- POST /kill/global      - Global kill-switch
- POST /kill/service/{name}
- POST /kill/model/{id}
- POST /resume/{scope}/{id}
- POST /safe-mode/enter
- GET  /status
- POST /approve/{request_id}
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .controller import (
    AutoTriggerRule,
    KillScope,
    KillSwitchController,
    SafeModeLevel,
    TriggerCondition,
    get_killswitch,
)

logger = logging.getLogger("ops.killswitch.api")


# ═══════════════════════════════════════════════════════════════════════
# Request/Response Models
# ═══════════════════════════════════════════════════════════════════════


class KillRequest(BaseModel):
    """Kill-switch activation request."""
    reason: str = Field(..., description="Reason for kill-switch activation")
    actor: str = Field(..., description="User/system initiating the action")
    requires_approval: bool = Field(default=False, description="Require multi-approval")
    min_approvals: int = Field(default=2, description="Minimum approvals needed")


class SafeModeRequest(BaseModel):
    """Safe mode entry request."""
    scope: str = Field(..., description="Scope: global, service, model, endpoint")
    scope_id: str = Field(..., description="ID within scope")
    level: str = Field(..., description="Safe mode level: cache_only, rule_only, static, offline")
    reason: str = Field(..., description="Reason for safe mode entry")
    actor: str = Field(..., description="User/system initiating the action")


class ResumeRequest(BaseModel):
    """Resume normal operation request."""
    reason: str = Field(..., description="Reason for resuming")
    actor: str = Field(..., description="User/system initiating the action")


class ApprovalAction(BaseModel):
    """Approval/rejection action."""
    approver: str = Field(..., description="Approver username")
    action: str = Field(..., description="approve or reject")


class AutoTriggerRuleRequest(BaseModel):
    """Auto-trigger rule configuration."""
    rule_id: str
    name: str
    condition: str
    threshold: float
    scope: str
    scope_id: str
    action: str
    safe_mode_level: Optional[str] = None
    cooldown_minutes: int = 60
    enabled: bool = True
    requires_approval: bool = False
    min_approvals: int = 1


class CanProcessRequest(BaseModel):
    """Request to check if processing is allowed."""
    service: str = Field(..., description="Service name")
    model_id: Optional[str] = Field(None, description="Optional model ID")
    endpoint: Optional[str] = Field(None, description="Optional endpoint name")


class KillSwitchResponse(BaseModel):
    """Standard response for kill-switch operations."""
    success: bool
    message: str
    event_id: Optional[str] = None
    state: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


# ═══════════════════════════════════════════════════════════════════════
# API Handler Class
# ═══════════════════════════════════════════════════════════════════════


class KillSwitchAPI:
    """
    Kill-Switch API Handler.
    
    Provides REST-style methods for kill-switch operations.
    Can be integrated with FastAPI, Flask, or other frameworks.
    """
    
    def __init__(self, controller: Optional[KillSwitchController] = None):
        self._controller = controller or get_killswitch()
    
    # ═══════════════════════════════════════════════════════════════════
    # Kill Operations
    # ═══════════════════════════════════════════════════════════════════
    
    def kill_global(self, request: KillRequest) -> KillSwitchResponse:
        """
        POST /kill/global
        
        Activate global kill-switch - stops ALL AI operations.
        """
        try:
            event = self._controller.kill(
                scope=KillScope.GLOBAL,
                scope_id="*",
                reason=request.reason,
                actor=request.actor,
                trigger=TriggerCondition.MANUAL,
                requires_approval=request.requires_approval,
                min_approvals=request.min_approvals,
            )
            
            if request.requires_approval:
                return KillSwitchResponse(
                    success=True,
                    message="Global kill-switch approval requested",
                    event_id=event.event_id,
                    state="pending_approval",
                )
            
            return KillSwitchResponse(
                success=True,
                message="Global kill-switch ACTIVATED",
                event_id=event.event_id,
                state="killed",
            )
            
        except Exception as e:
            logger.error(f"Global kill failed: {e}")
            return KillSwitchResponse(
                success=False,
                message=f"Failed to activate global kill-switch: {str(e)}",
            )
    
    def kill_service(self, service_name: str, request: KillRequest) -> KillSwitchResponse:
        """
        POST /kill/service/{service_name}
        
        Kill specific service.
        """
        try:
            event = self._controller.kill(
                scope=KillScope.SERVICE,
                scope_id=service_name,
                reason=request.reason,
                actor=request.actor,
                trigger=TriggerCondition.MANUAL,
                requires_approval=request.requires_approval,
                min_approvals=request.min_approvals,
            )
            
            return KillSwitchResponse(
                success=True,
                message=f"Service {service_name} kill-switch ACTIVATED",
                event_id=event.event_id,
                state="killed",
            )
            
        except Exception as e:
            logger.error(f"Service kill failed: {e}")
            return KillSwitchResponse(
                success=False,
                message=f"Failed to kill service {service_name}: {str(e)}",
            )
    
    def kill_model(self, model_id: str, request: KillRequest) -> KillSwitchResponse:
        """
        POST /kill/model/{model_id}
        
        Kill specific model.
        """
        try:
            event = self._controller.kill(
                scope=KillScope.MODEL,
                scope_id=model_id,
                reason=request.reason,
                actor=request.actor,
                trigger=TriggerCondition.MANUAL,
                requires_approval=request.requires_approval,
                min_approvals=request.min_approvals,
            )
            
            return KillSwitchResponse(
                success=True,
                message=f"Model {model_id} kill-switch ACTIVATED",
                event_id=event.event_id,
                state="killed",
            )
            
        except Exception as e:
            logger.error(f"Model kill failed: {e}")
            return KillSwitchResponse(
                success=False,
                message=f"Failed to kill model {model_id}: {str(e)}",
            )
    
    def kill_endpoint(self, endpoint: str, request: KillRequest) -> KillSwitchResponse:
        """
        POST /kill/endpoint/{endpoint}
        
        Kill specific API endpoint.
        """
        try:
            event = self._controller.kill(
                scope=KillScope.ENDPOINT,
                scope_id=endpoint,
                reason=request.reason,
                actor=request.actor,
                trigger=TriggerCondition.MANUAL,
            )
            
            return KillSwitchResponse(
                success=True,
                message=f"Endpoint {endpoint} kill-switch ACTIVATED",
                event_id=event.event_id,
                state="killed",
            )
            
        except Exception as e:
            logger.error(f"Endpoint kill failed: {e}")
            return KillSwitchResponse(
                success=False,
                message=f"Failed to kill endpoint {endpoint}: {str(e)}",
            )
    
    # ═══════════════════════════════════════════════════════════════════
    # Safe Mode Operations
    # ═══════════════════════════════════════════════════════════════════
    
    def enter_safe_mode(self, request: SafeModeRequest) -> KillSwitchResponse:
        """
        POST /safe-mode/enter
        
        Enter safe mode operation.
        """
        try:
            scope = KillScope(request.scope)
            level = SafeModeLevel(request.level)
            
            event = self._controller.enter_safe_mode(
                scope=scope,
                scope_id=request.scope_id,
                level=level,
                reason=request.reason,
                actor=request.actor,
            )
            
            return KillSwitchResponse(
                success=True,
                message=f"Safe mode ({level.value}) ACTIVATED for {scope.value}:{request.scope_id}",
                event_id=event.event_id,
                state="safe_mode",
                data={"safe_mode_level": level.value},
            )
            
        except Exception as e:
            logger.error(f"Safe mode entry failed: {e}")
            return KillSwitchResponse(
                success=False,
                message=f"Failed to enter safe mode: {str(e)}",
            )
    
    # ═══════════════════════════════════════════════════════════════════
    # Resume Operations
    # ═══════════════════════════════════════════════════════════════════
    
    def resume_global(self, request: ResumeRequest) -> KillSwitchResponse:
        """
        POST /resume/global
        
        Resume global operations.
        """
        return self._resume(KillScope.GLOBAL, "*", request)
    
    def resume_service(self, service_name: str, request: ResumeRequest) -> KillSwitchResponse:
        """
        POST /resume/service/{service_name}
        
        Resume service operations.
        """
        return self._resume(KillScope.SERVICE, service_name, request)
    
    def resume_model(self, model_id: str, request: ResumeRequest) -> KillSwitchResponse:
        """
        POST /resume/model/{model_id}
        
        Resume model operations.
        """
        return self._resume(KillScope.MODEL, model_id, request)
    
    def _resume(
        self,
        scope: KillScope,
        scope_id: str,
        request: ResumeRequest,
    ) -> KillSwitchResponse:
        """Internal resume handler."""
        try:
            event = self._controller.resume(
                scope=scope,
                scope_id=scope_id,
                reason=request.reason,
                actor=request.actor,
            )
            
            return KillSwitchResponse(
                success=True,
                message=f"RESUMED {scope.value}:{scope_id}",
                event_id=event.event_id,
                state="active",
            )
            
        except Exception as e:
            logger.error(f"Resume failed: {e}")
            return KillSwitchResponse(
                success=False,
                message=f"Failed to resume {scope.value}:{scope_id}: {str(e)}",
            )
    
    # ═══════════════════════════════════════════════════════════════════
    # Approval Operations
    # ═══════════════════════════════════════════════════════════════════
    
    def get_pending_approvals(self) -> KillSwitchResponse:
        """
        GET /approvals/pending
        
        Get pending approval requests.
        """
        approvals = self._controller.get_pending_approvals()
        
        return KillSwitchResponse(
            success=True,
            message=f"{len(approvals)} pending approval(s)",
            data={
                "approvals": [a.to_dict() for a in approvals],
            },
        )
    
    def process_approval(
        self,
        request_id: str,
        action: ApprovalAction,
    ) -> KillSwitchResponse:
        """
        POST /approvals/{request_id}
        
        Approve or reject a kill-switch request.
        """
        try:
            if action.action == "approve":
                result = self._controller.approve(request_id, action.approver)
            else:
                result = self._controller.reject(request_id, action.approver)
            
            if not result:
                return KillSwitchResponse(
                    success=False,
                    message=f"Approval request {request_id} not found",
                )
            
            return KillSwitchResponse(
                success=True,
                message=f"Approval request {action.action}d",
                data=result.to_dict(),
            )
            
        except Exception as e:
            logger.error(f"Approval action failed: {e}")
            return KillSwitchResponse(
                success=False,
                message=f"Failed to process approval: {str(e)}",
            )
    
    # ═══════════════════════════════════════════════════════════════════
    # Status & Query Operations
    # ═══════════════════════════════════════════════════════════════════
    
    def get_status(self) -> KillSwitchResponse:
        """
        GET /status
        
        Get current kill-switch status.
        """
        status = self._controller.get_status()
        
        return KillSwitchResponse(
            success=True,
            message="Kill-switch status retrieved",
            state=status["global_state"],
            data=status,
        )
    
    def can_process(self, request: CanProcessRequest) -> KillSwitchResponse:
        """
        POST /can-process
        
        Check if a request can be processed.
        """
        can_proceed, reason, safe_level = self._controller.can_process(
            service=request.service,
            model_id=request.model_id,
            endpoint=request.endpoint,
        )
        
        return KillSwitchResponse(
            success=can_proceed,
            message=reason,
            state="active" if can_proceed else "blocked",
            data={
                "can_process": can_proceed,
                "safe_mode_level": safe_level.value,
            },
        )
    
    def get_events(self, limit: int = 100) -> KillSwitchResponse:
        """
        GET /events
        
        Get recent kill-switch events.
        """
        events = self._controller.get_events(limit=limit)
        
        return KillSwitchResponse(
            success=True,
            message=f"{len(events)} events retrieved",
            data={"events": events},
        )
    
    # ═══════════════════════════════════════════════════════════════════
    # Auto-Trigger Rule Management
    # ═══════════════════════════════════════════════════════════════════
    
    def get_rules(self) -> KillSwitchResponse:
        """
        GET /rules
        
        Get auto-trigger rules.
        """
        rules = self._controller.get_rules()
        
        return KillSwitchResponse(
            success=True,
            message=f"{len(rules)} rules configured",
            data={
                "rules": [r.to_dict() for r in rules],
            },
        )
    
    def add_rule(self, request: AutoTriggerRuleRequest) -> KillSwitchResponse:
        """
        POST /rules
        
        Add auto-trigger rule.
        """
        try:
            rule = AutoTriggerRule(
                rule_id=request.rule_id,
                name=request.name,
                condition=TriggerCondition(request.condition),
                threshold=request.threshold,
                scope=KillScope(request.scope),
                scope_id=request.scope_id,
                action=request.action,
                safe_mode_level=SafeModeLevel(request.safe_mode_level) if request.safe_mode_level else None,
                cooldown_minutes=request.cooldown_minutes,
                enabled=request.enabled,
                requires_approval=request.requires_approval,
                min_approvals=request.min_approvals,
            )
            
            self._controller.add_rule(rule)
            
            return KillSwitchResponse(
                success=True,
                message=f"Rule {request.rule_id} added",
                data=rule.to_dict(),
            )
            
        except Exception as e:
            logger.error(f"Add rule failed: {e}")
            return KillSwitchResponse(
                success=False,
                message=f"Failed to add rule: {str(e)}",
            )


# ═══════════════════════════════════════════════════════════════════════
# FastAPI Router Factory
# ═══════════════════════════════════════════════════════════════════════


def create_fastapi_router():
    """
    Create FastAPI router for kill-switch API.
    
    Usage:
        from fastapi import FastAPI
        from backend.ops.killswitch.api import create_fastapi_router
        
        app = FastAPI()
        app.include_router(create_fastapi_router(), prefix="/api/v1/kill-switch")
    """
    try:
        from fastapi import APIRouter, HTTPException, Query
    except ImportError:
        raise ImportError("FastAPI is required for router creation")
    
    router = APIRouter(tags=["Kill-Switch"])
    api = KillSwitchAPI()
    
    @router.post("/kill/global", response_model=KillSwitchResponse)
    async def kill_global(request: KillRequest):
        """Activate global kill-switch."""
        return api.kill_global(request)
    
    @router.post("/kill/service/{service_name}", response_model=KillSwitchResponse)
    async def kill_service(service_name: str, request: KillRequest):
        """Kill specific service."""
        return api.kill_service(service_name, request)
    
    @router.post("/kill/model/{model_id}", response_model=KillSwitchResponse)
    async def kill_model(model_id: str, request: KillRequest):
        """Kill specific model."""
        return api.kill_model(model_id, request)
    
    @router.post("/kill/endpoint/{endpoint}", response_model=KillSwitchResponse)
    async def kill_endpoint(endpoint: str, request: KillRequest):
        """Kill specific endpoint."""
        return api.kill_endpoint(endpoint, request)
    
    @router.post("/safe-mode/enter", response_model=KillSwitchResponse)
    async def enter_safe_mode(request: SafeModeRequest):
        """Enter safe mode."""
        return api.enter_safe_mode(request)
    
    @router.post("/resume/global", response_model=KillSwitchResponse)
    async def resume_global(request: ResumeRequest):
        """Resume global operations."""
        return api.resume_global(request)
    
    @router.post("/resume/service/{service_name}", response_model=KillSwitchResponse)
    async def resume_service(service_name: str, request: ResumeRequest):
        """Resume service."""
        return api.resume_service(service_name, request)
    
    @router.post("/resume/model/{model_id}", response_model=KillSwitchResponse)
    async def resume_model(model_id: str, request: ResumeRequest):
        """Resume model."""
        return api.resume_model(model_id, request)
    
    @router.get("/status", response_model=KillSwitchResponse)
    async def get_status():
        """Get kill-switch status."""
        return api.get_status()
    
    @router.post("/can-process", response_model=KillSwitchResponse)
    async def can_process(request: CanProcessRequest):
        """Check if processing is allowed."""
        return api.can_process(request)
    
    @router.get("/events", response_model=KillSwitchResponse)
    async def get_events(limit: int = Query(default=100, le=1000)):
        """Get recent events."""
        return api.get_events(limit)
    
    @router.get("/approvals/pending", response_model=KillSwitchResponse)
    async def get_pending_approvals():
        """Get pending approvals."""
        return api.get_pending_approvals()
    
    @router.post("/approvals/{request_id}", response_model=KillSwitchResponse)
    async def process_approval(request_id: str, action: ApprovalAction):
        """Process approval request."""
        return api.process_approval(request_id, action)
    
    @router.get("/rules", response_model=KillSwitchResponse)
    async def get_rules():
        """Get auto-trigger rules."""
        return api.get_rules()
    
    @router.post("/rules", response_model=KillSwitchResponse)
    async def add_rule(request: AutoTriggerRuleRequest):
        """Add auto-trigger rule."""
        return api.add_rule(request)
    
    return router


# ═══════════════════════════════════════════════════════════════════════
# Singleton API Handler
# ═══════════════════════════════════════════════════════════════════════

_api: Optional[KillSwitchAPI] = None


def get_killswitch_api() -> KillSwitchAPI:
    """Get singleton API handler."""
    global _api
    if _api is None:
        _api = KillSwitchAPI()
    return _api

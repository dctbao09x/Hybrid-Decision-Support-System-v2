# backend/api/router_registry.py
"""
Deterministic Router Registry
=============================

All routers are imported at module load time (not lazily).
If any router fails to import, the server FAILS FAST with a clear error.

This ensures:
1. All workers have identical routing tables
2. No silent failures from conditional imports
3. Clear error messages when dependencies are missing

Usage:
    from backend.api.router_registry import get_all_routers, RouterInfo
    
    for router_info in get_all_routers():
        app.include_router(router_info.router, prefix=router_info.prefix)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional, TYPE_CHECKING
from enum import Enum

from fastapi import APIRouter

if TYPE_CHECKING:
    from backend.main_controller import MainController
    from backend.ops.integration import OpsHub
    from backend.crawler_manager import CrawlerManager

logger = logging.getLogger("api.registry")


class AuthLevel(Enum):
    """Authentication level for routes."""
    PUBLIC = "public"           # No auth required
    USER = "user"               # User token required
    ADMIN = "admin"             # Admin token required
    INTERNAL = "internal"       # Internal service only


@dataclass
class RouterInfo:
    """
    Router configuration for registration.
    
    Schema (DOC compliant):
      - path: API prefix path
      - method: HTTP methods supported (derived from router)
      - controller: Controller class that handles dispatch
      - service: Service layer class
      - auth: Authentication level required
      - version: API version
    """
    name: str
    router: APIRouter
    prefix: str                           # path
    tags: List[str]
    controller: str = "MainController"    # Controller handling this router
    service: Optional[str] = None         # Service layer class name
    auth: AuthLevel = AuthLevel.PUBLIC    # Auth level required
    version: str = "v1"                   # API version
    setup: Optional[Callable] = None      # Optional setup function
    critical: bool = True                 # If True, server fails if this router fails
    
    def to_schema_dict(self) -> dict:
        """Convert to schema dict for documentation/validation."""
        return {
            "path": self.prefix,
            "method": "*",  # Multiple methods per router
            "controller": self.controller,
            "service": self.service,
            "auth": self.auth.value,
            "version": self.version,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# MANDATORY IMPORTS - These MUST succeed or server fails
# ═══════════════════════════════════════════════════════════════════════════════

# Health & Ops routers
from backend.api.routers.health_router import router as health_router, set_ops_hub as set_health_ops
from backend.api.routers.ops_router import router as ops_router, set_ops_hub as set_ops_ops

# ML & Inference routers
from backend.api.routers.ml_router import router as ml_router, set_main_controller as set_ml_controller
from backend.api.routers.mlops_router import router as mlops_router
from backend.api.routers.infer_router import router as infer_router, set_inference_api as set_infer_api

# Pipeline & Data routers
from backend.api.routers.pipeline_router import router as pipeline_router, set_main_controller as set_pipeline_controller
from backend.api.routers.crawler_router import router as crawler_router, set_crawler_manager as set_crawler_mgr
from backend.api.routers.governance_router import router as governance_router
from backend.api.kb_routes import router as kb_router

# Chat & Feedback routers
from backend.api.routers.chat_router import router as chat_router
from backend.feedback.router import router as feedback_router

# Phase-B routers
from backend.api.routers.eval_router import router as eval_router, set_main_controller as set_eval_controller
from backend.api.routers.rules_router import router as rules_router
from backend.api.routers.taxonomy_router import router as taxonomy_router
from backend.api.routers.scoring_router import router as scoring_router

# Market Intelligence router (Stage 7)
from backend.market.router import router as market_router

# Kill-Switch router (Ops)
from backend.ops.killswitch.api import create_fastapi_router as create_killswitch_router
killswitch_router = create_killswitch_router()

# One-button router (canonical decision entrypoint)
from backend.api.routers.one_button_router import (
    router as one_button_router,
    set_controller as set_one_button_controller,
    set_cost_tracker as set_one_button_cost_tracker,
    set_metrics_collector as set_one_button_metrics_collector,
)
from backend.api.controllers.decision_controller import (
    get_decision_controller,
)

# Explain routers
from backend.api.routers.explain_router import router as explain_router
from backend.api.routers.explain_router import router_v2 as explain_router_v2
from backend.api.routers.explain_router import set_controller as set_explain_controller
from backend.api.controllers.explain_controller import ExplainController

# Admin routers
from backend.modules.admin_auth.routes import admin_auth_router
from backend.modules.admin_gateway.routes import admin_gateway_router
from backend.modules.feedback.routes import public_feedback_router

# LiveOps routers
from backend.api.routers.liveops_router import (
    router as liveops_router,
    liveops_ws_handler,
    set_command_engine,
)
from backend.modules.admin_auth.middleware import auth_admin
from backend.ops.command_engine.engine import CommandEngine
from backend.ops.command_engine.models import CommandType
from backend.ops.command_engine.executor import create_simple_handler


logger.info("All router imports successful")


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER REGISTRY - Central Source of Truth
# ═══════════════════════════════════════════════════════════════════════════════

# Core API routers with their prefixes and schema compliance
CORE_ROUTERS: List[RouterInfo] = [
    RouterInfo(name="health", router=health_router, prefix="/api/v1/health", tags=["Health"],
               controller="OpsHub", service="HealthService", auth=AuthLevel.PUBLIC, version="v1"),
    RouterInfo(name="one_button", router=one_button_router, prefix="", tags=["One-Button"],
               controller="DecisionController", service="OneButtonService", auth=AuthLevel.USER, version="v1",
               critical=True),
    RouterInfo(name="ops", router=ops_router, prefix="/api/v1/ops", tags=["Operations"],
               controller="OpsHub", service="OpsService", auth=AuthLevel.ADMIN, version="v1"),
    RouterInfo(name="ml", router=ml_router, prefix="/api/v1/ml", tags=["ML"],
               controller="MainController", service="MLService", auth=AuthLevel.USER, version="v1"),
    RouterInfo(name="mlops", router=mlops_router, prefix="/api/v1/mlops", tags=["MLOps"],
               controller="MainController", service="MLOpsService", auth=AuthLevel.ADMIN, version="v1"),
    RouterInfo(name="governance", router=governance_router, prefix="/api/v1/governance", tags=["Governance"],
               controller="MainController", service="GovernanceService", auth=AuthLevel.ADMIN, version="v1"),
    RouterInfo(name="infer", router=infer_router, prefix="/api/v1/infer", tags=["Inference"],
               controller="MainController", service="InferenceService", auth=AuthLevel.USER, version="v1"),
    RouterInfo(name="pipeline", router=pipeline_router, prefix="/api/v1/pipeline", tags=["Pipeline"],
               controller="MainController", service="PipelineService", auth=AuthLevel.ADMIN, version="v1"),
    RouterInfo(name="crawlers", router=crawler_router, prefix="/api/v1/crawlers", tags=["Crawlers"],
               controller="MainController", service="CrawlerService", auth=AuthLevel.ADMIN, version="v1"),
    RouterInfo(name="kb", router=kb_router, prefix="/api/v1", tags=["KB"],
               controller="MainController", service="KBService", auth=AuthLevel.USER, version="v1"),
    RouterInfo(name="chat", router=chat_router, prefix="/api/v1/chat", tags=["Chat"],
               controller="MainController", service="ChatService", auth=AuthLevel.USER, version="v1"),
    RouterInfo(name="feedback_infer", router=feedback_router, prefix="", tags=["Feedback"],
               controller="MainController", service="FeedbackService", auth=AuthLevel.USER, version="v1"),
    RouterInfo(name="eval", router=eval_router, prefix="/api/v1/eval", tags=["Eval"],
               controller="MainController", service="EvalService", auth=AuthLevel.ADMIN, version="v1"),
    RouterInfo(name="rules", router=rules_router, prefix="/api/v1/rules", tags=["Rules"],
               controller="MainController", service="RuleEngineService", auth=AuthLevel.USER, version="v1"),
    RouterInfo(name="taxonomy", router=taxonomy_router, prefix="/api/v1/taxonomy", tags=["Taxonomy"],
               controller="MainController", service="TaxonomyService", auth=AuthLevel.USER, version="v1"),
    RouterInfo(name="scoring", router=scoring_router, prefix="/api/v1/scoring", tags=["Scoring"],
               controller="MainController", service="ScoringService", auth=AuthLevel.USER, version="v1"),
    RouterInfo(name="market", router=market_router, prefix="/api/v1/market", tags=["Market Intelligence"],
               controller="MainController", service="MarketService", auth=AuthLevel.USER, version="v1"),
    RouterInfo(name="killswitch", router=killswitch_router, prefix="/api/v1/kill-switch", tags=["Kill-Switch"],
               controller="KillSwitchController", service="KillSwitchService", auth=AuthLevel.ADMIN, version="v1"),
]

EXPLAIN_ROUTERS: List[RouterInfo] = [
    RouterInfo(name="explain", router=explain_router, prefix="", tags=["Explain"],
               controller="ExplainController", service="XAIService", auth=AuthLevel.USER, version="v1"),
    RouterInfo(name="explain_v2", router=explain_router_v2, prefix="", tags=["Explain V2"],
               controller="ExplainController", service="XAIService", auth=AuthLevel.USER, version="v2"),
]

ADMIN_ROUTERS: List[RouterInfo] = [
    RouterInfo(name="admin_auth", router=admin_auth_router, prefix="", tags=["Admin Auth"],
               controller="AdminController", service="AdminAuthService", auth=AuthLevel.PUBLIC, version="v1"),
    RouterInfo(name="admin_gateway", router=admin_gateway_router, prefix="", tags=["Admin Gateway"],
               controller="AdminController", service="AdminGatewayService", auth=AuthLevel.ADMIN, version="v1"),
    RouterInfo(name="public_feedback", router=public_feedback_router, prefix="", tags=["Public Feedback"],
               controller="FeedbackController", service="FeedbackService", auth=AuthLevel.PUBLIC, version="v1"),
]

LIVEOPS_ROUTERS: List[RouterInfo] = [
    # LiveOps requires special handling with auth dependency
    RouterInfo(name="liveops", router=liveops_router, prefix="/api/v1/live", tags=["LiveOps"],
               controller="LiveOpsController", service="CommandEngine", auth=AuthLevel.ADMIN, version="v1"),
]

# Expected minimum route count for validation (updated to include market routes)
EXPECTED_MIN_ROUTE_COUNT = 190


def get_all_routers() -> List[RouterInfo]:
    """Get all routers in correct order."""
    return CORE_ROUTERS + EXPLAIN_ROUTERS + ADMIN_ROUTERS + LIVEOPS_ROUTERS


def get_registry_schema() -> List[dict]:
    """
    Get full registry schema for documentation compliance.
    Returns list of route schema dicts per DOC specification.
    """
    all_routers = get_all_routers()
    return [r.to_schema_dict() for r in all_routers]


def validate_registry_integrity() -> dict:
    """
    Validate registry integrity - all routers have required fields.
    Returns validation result with any issues found.
    """
    issues = []
    # Routers with prefix defined in their own module
    routers_with_internal_prefix = [
        "explain", "explain_v2", "admin_auth", "admin_gateway", 
        "public_feedback", "feedback_infer", "one_button"
    ]
    for router_info in get_all_routers():
        if not router_info.controller:
            issues.append(f"Router '{router_info.name}' missing controller")
        if not router_info.prefix and router_info.name not in routers_with_internal_prefix:
            issues.append(f"Router '{router_info.name}' missing prefix")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "total_routers": len(get_all_routers()),
    }


def setup_dependencies(
    main_control: Optional["MainController"] = None,
    ops_hub: Optional["OpsHub"] = None,
    crawler_manager: Optional["CrawlerManager"] = None,
    inference_api: Optional[object] = None,
) -> None:
    """
    Inject dependencies into routers.
    Called once during app setup.
    
    This is the CENTRAL dependency injection point per DOC specification.
    All routers should receive their dependencies here, not via direct imports.
    """
    # Import setters for scoring router
    from backend.api.routers.scoring_router import set_main_controller as set_scoring_controller
    
    # OpsHub dependencies
    decision_ctrl = get_decision_controller()

    if ops_hub:
        set_health_ops(ops_hub)
        set_ops_ops(ops_hub)
        decision_ctrl.set_ops_hub(ops_hub)
        if hasattr(ops_hub, "metrics"):
            set_one_button_metrics_collector(ops_hub.metrics)
        if hasattr(ops_hub, "cost_tracker"):
            set_one_button_cost_tracker(ops_hub.cost_tracker)
        logger.info("OpsHub injected into health and ops routers")
    
    # MainController dependencies
    if main_control:
        set_ml_controller(main_control)
        set_pipeline_controller(main_control)
        set_eval_controller(main_control)
        set_scoring_controller(main_control)  # NEW: Scoring router now uses controller
        
        # Decision controller (canonical one-button pipeline)
        decision_ctrl.set_main_controller(main_control)
        set_one_button_controller(decision_ctrl)
        logger.info("DecisionController configured with MainController for one-button")
        
        logger.info("MainController injected into ML, pipeline, eval, scoring, and one-button routers")
    
    # CrawlerManager dependency
    if crawler_manager:
        set_crawler_mgr(crawler_manager)
        logger.info("CrawlerManager injected into crawler router")
    
    # InferenceAPI dependency
    if inference_api:
        set_infer_api(inference_api)
        logger.info("InferenceAPI injected into infer router")


def setup_explain_controller(
    main_control: Optional["MainController"] = None,
    model_version: str = "unknown",
) -> ExplainController:
    """
    Setup ExplainController with dependencies.
    Returns the configured controller.
    """
    from backend.storage.explain_history import ExplainHistoryStorage
    
    controller = ExplainController()
    controller.load_config_file()
    
    if main_control:
        controller.set_main_control(main_control)
    
    history_storage = ExplainHistoryStorage()
    controller.set_history_storage(history_storage)
    controller.set_versions(
        model_version=model_version,
        xai_version="1.0.0",
        stage3_version="1.0.0",
        stage4_version="1.0.0",
    )
    
    set_explain_controller(controller)
    logger.info("ExplainController configured and injected")
    
    return controller


def setup_liveops_command_engine() -> CommandEngine:
    """
    Setup LiveOps CommandEngine.
    Returns the configured engine.
    """
    engine = CommandEngine()
    
    async def _rbac_checker(user_id: str, role: str, action: str) -> bool:
        role_lower = (role or "").lower()
        if role_lower == "admin":
            return True
        if role_lower == "operator":
            return action in {
                CommandType.JOB_PAUSE.value,
                CommandType.JOB_RESUME.value,
                CommandType.MLOPS_RETRAIN.value,
            }
        return False
    
    engine.set_rbac_checker(_rbac_checker)
    
    async def _generic_handler(command):
        import time
        return {
            "ok": True,
            "command_id": command.id,
            "type": command.type,
            "target": command.target,
            "processed_at": time.time(),
        }
    
    for command_type in (
        CommandType.CRAWLER_KILL,
        CommandType.JOB_PAUSE,
        CommandType.JOB_RESUME,
        CommandType.KB_ROLLBACK,
        CommandType.MLOPS_FREEZE,
        CommandType.MLOPS_RETRAIN,
        CommandType.CUSTOM,
    ):
        engine.register_command(
            command_type=command_type,
            handler=create_simple_handler(_generic_handler),
            approval_required=command_type in {
                CommandType.CRAWLER_KILL,
                CommandType.KB_ROLLBACK,
                CommandType.MLOPS_FREEZE,
            },
        )
    
    set_command_engine(engine)
    logger.info("LiveOps CommandEngine configured")
    
    return engine


def get_liveops_ws_handler():
    """Get LiveOps WebSocket handler."""
    return liveops_ws_handler


def get_auth_admin_dependency():
    """Get admin auth dependency for protected routes."""
    return auth_admin


def validate_route_count(app) -> bool:
    """
    Validate that all expected routes are registered.
    Returns True if valid, raises RuntimeError if not.
    """
    route_count = len([r for r in app.routes if hasattr(r, 'methods')])
    
    if route_count < EXPECTED_MIN_ROUTE_COUNT:
        raise RuntimeError(
            f"Route count validation FAILED: "
            f"Expected >= {EXPECTED_MIN_ROUTE_COUNT}, got {route_count}. "
            f"Some routers failed to load. Check startup logs."
        )
    
    logger.info(f"Route validation PASSED: {route_count} routes registered")
    return True

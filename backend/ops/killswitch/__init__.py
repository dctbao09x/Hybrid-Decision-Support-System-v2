# backend/ops/killswitch/__init__.py
"""
Kill-Switch & Safe Mode Package
================================

Emergency control system for AI operations.

Components:
- KillSwitchController: Core state machine and control logic
- KillSwitchAPI: REST API layer

Usage:
    from backend.ops.killswitch import (
        get_killswitch,
        get_killswitch_api,
        KillScope,
        SafeModeLevel,
        TriggerCondition,
    )
    
    # Check if processing allowed
    controller = get_killswitch()
    can_proceed, reason, safe_level = controller.can_process(
        service="inference",
        model_id="model_v2"
    )
    
    # Activate kill-switch
    controller.kill(
        scope=KillScope.MODEL,
        scope_id="model_v2",
        reason="Drift detected",
        actor="monitoring_system"
    )
    
    # Enter safe mode
    controller.enter_safe_mode(
        scope=KillScope.SERVICE,
        scope_id="inference",
        level=SafeModeLevel.CACHE_ONLY,
        reason="High error rate",
        actor="auto_trigger"
    )
"""

from .controller import (
    KillSwitchController,
    KillSwitchState,
    SafeModeLevel,
    KillScope,
    TriggerCondition,
    KillSwitchEvent,
    AutoTriggerRule,
    ApprovalRequest,
    get_killswitch,
)

from .api import (
    KillSwitchAPI,
    KillRequest,
    SafeModeRequest,
    ResumeRequest,
    ApprovalAction,
    CanProcessRequest,
    KillSwitchResponse,
    create_fastapi_router,
    get_killswitch_api,
)

__all__ = [
    # Controller
    "KillSwitchController",
    "KillSwitchState",
    "SafeModeLevel",
    "KillScope",
    "TriggerCondition",
    "KillSwitchEvent",
    "AutoTriggerRule",
    "ApprovalRequest",
    "get_killswitch",
    # API
    "KillSwitchAPI",
    "KillRequest",
    "SafeModeRequest",
    "ResumeRequest",
    "ApprovalAction",
    "CanProcessRequest",
    "KillSwitchResponse",
    "create_fastapi_router",
    "get_killswitch_api",
]

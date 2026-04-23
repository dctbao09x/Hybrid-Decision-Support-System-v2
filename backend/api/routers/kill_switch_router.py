"""
Kill Switch Router
==================
Provides unified kill-switch control endpoints that the frontend
opsApi.js and other admin components call.

Endpoints:
  GET  /api/v1/kill-switch/status       — current kill-switch state
  POST /api/v1/kill-switch/activate     — activate kill-switch (halt inference)
  POST /api/v1/kill-switch/deactivate   — deactivate kill-switch (resume)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from backend.ops.killswitch.controller import (
    KillScope,
    KillSwitchState,
    TriggerCondition,
    get_killswitch,
)

logger = logging.getLogger("api.routers.kill_switch")

router = APIRouter(prefix="/api/v1/kill-switch", tags=["Kill Switch"])
_controller = get_killswitch()


class KillSwitchActivateRequest(BaseModel):
    reason: str = "Emergency halt"
    scope: Optional[str] = "all"  # "all" | "inference" | "scoring"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "/status",
    summary="Kill-switch status",
    response_description="Current kill-switch state",
)
async def kill_switch_status() -> Dict[str, Any]:
    """Returns the current kill-switch activation state."""
    state = _controller.get_state(KillScope.GLOBAL, "*")
    active = state in {KillSwitchState.KILLED, KillSwitchState.SAFE_MODE}

    reason = None
    activated_at = None
    activated_by = None

    if active:
        events = _controller.get_events(limit=50)
        for event in events:
            if event.get("scope") == KillScope.GLOBAL.value and event.get("scope_id") == "*":
                reason = event.get("reason")
                activated_at = event.get("timestamp")
                activated_by = event.get("actor")
                break

    return {
        "active": active,
        "reason": reason,
        "activated_at": activated_at,
        "activated_by": activated_by,
        "scope": "all",
    }


@router.post(
    "/activate",
    summary="Activate kill-switch",
    response_description="Kill-switch activated",
)
async def kill_switch_activate(
    body: KillSwitchActivateRequest,
) -> Dict[str, Any]:
    """
    Activates the kill-switch — halts new inference / scoring requests.
    Existing in-flight requests complete normally.
    """
    scope_raw = (body.scope or "all").strip().lower()
    scope = KillScope.GLOBAL if scope_raw == "all" else KillScope.SERVICE
    scope_id = "*" if scope == KillScope.GLOBAL else scope_raw

    _controller.kill(
        scope=scope,
        scope_id=scope_id,
        reason=body.reason,
        actor="admin",
        trigger=TriggerCondition.MANUAL,
    )

    active = _controller.get_state(scope, scope_id) in {KillSwitchState.KILLED, KillSwitchState.SAFE_MODE}

    logger.warning(
        "KILL SWITCH ACTIVATED — reason='%s' scope='%s'",
        body.reason,
        scope_raw,
    )
    return {
        "success": True,
        "active": active,
        "reason": body.reason,
        "scope": scope_raw,
        "message": "Kill-switch activated — inference halted.",
    }


@router.post(
    "/deactivate",
    summary="Deactivate kill-switch",
    response_description="Kill-switch deactivated",
)
async def kill_switch_deactivate() -> Dict[str, Any]:
    """Deactivates the kill-switch — resumes normal operations."""
    _controller.resume(
        scope=KillScope.GLOBAL,
        scope_id="*",
        reason="Kill-switch deactivated via API",
        actor="admin",
    )

    active = _controller.get_state(KillScope.GLOBAL, "*") in {
        KillSwitchState.KILLED,
        KillSwitchState.SAFE_MODE,
    }

    logger.info("Kill switch DEACTIVATED — operations resumed")
    return {
        "success": True,
        "active": active,
        "message": "Kill-switch deactivated — operations resumed.",
    }

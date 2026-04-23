# backend/api/routers/liveops_router.py
"""
LiveOps Router
==============

WebSocket/SSE endpoints for real-time operations monitoring and control.

Endpoints:
  - WS   /api/v1/live/ws              — WebSocket realtime channel
  - GET  /api/v1/live/sse             — Server-Sent Events stream
  - GET  /api/v1/live/poll            — Polling fallback
  - POST /api/v1/ops/crawler/kill     — Kill crawler
  - POST /api/v1/ops/job/pause        — Pause job
  - POST /api/v1/ops/job/resume       — Resume job
  - POST /api/v1/kb/rollback          — Rollback KB
  - POST /api/v1/mlops/freeze         — Freeze model
  - POST /api/v1/mlops/retrain        — Retrain model
  - POST /api/v1/ops/simulate         — Simulation/dry-run
  - GET  /api/v1/ops/commands/{id}    — Command status
  - POST /api/v1/ops/commands/{id}/cancel — Cancel command
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.modules.admin_auth.middleware import auth_admin_websocket, require_role
from backend.ops.security.command_signing import verifier as signing_verifier

# LiveOps event bus and WS auth
from backend.api.routers.liveops.event_bus import (
    emit_event,
    publish_status,
    subscribe_stream,
    unsubscribe,
)
from backend.api.routers.liveops.ws_handler import verify_ws_token, AuthError

logger = logging.getLogger("api.routers.liveops")

router = APIRouter(tags=["LiveOps"])


# ==============================================================================
# Request/Response Models
# ==============================================================================

class CommandRequest(BaseModel):
    """Base command request."""
    target: str = Field(..., description="Target resource identifier")
    params: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None
    dry_run: bool = False
    priority: str = "normal"
    timeout_seconds: int = 300
    nonce: str = Field(..., min_length=8)
    timestamp: int = Field(..., description="Unix timestamp (seconds)")
    signature: str = Field(..., min_length=32)


class CrawlerKillRequest(CommandRequest):
    """Request to kill a crawler."""
    site_name: str = Field(..., description="Crawler site name")
    force: bool = False


class JobControlRequest(CommandRequest):
    """Request to pause/resume a job."""
    job_id: str = Field(..., description="Job identifier")


class KBRollbackRequest(CommandRequest):
    """Request to rollback KB."""
    version: str = Field(..., description="Target version to rollback to")
    backup_current: bool = True


class MLOpsModelRequest(CommandRequest):
    """Request for MLOps model operations."""
    model_id: str = Field(..., description="Model identifier")
    reason: Optional[str] = None


class RetrainRequest(MLOpsModelRequest):
    """Request to retrain a model."""
    config_override: Dict[str, Any] = Field(default_factory=dict)
    schedule: Optional[str] = None  # Cron expression for scheduled retrain


class SimulateRequest(BaseModel):
    """Simulation/dry-run request."""
    command_type: str
    target: str
    params: Dict[str, Any] = Field(default_factory=dict)
    chaos_scenario: Optional[str] = None


class CommandResponse(BaseModel):
    """Standard command response."""
    status: str = "ok"
    data: Dict[str, Any] = Field(default_factory=dict)
    meta: Dict[str, Any] = Field(default_factory=dict)


class ApprovalActionRequest(BaseModel):
    approver_comment: Optional[str] = None


class CommandStatusResponse(BaseModel):
    """Command status response."""
    command_id: str
    state: str
    progress: float = 0.0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# ==============================================================================
# WebSocket Connection Manager
# ==============================================================================

class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""
    
    def __init__(self):
        self._connections: Dict[str, WebSocket] = {}
        self._subscriptions: Dict[str, Set[str]] = {}  # conn_id -> modules
        self._user_connections: Dict[str, Set[str]] = {}  # user_id -> conn_ids
        self._connection_roles: Dict[str, str] = {}  # conn_id -> role
        self._msg_timestamps: Dict[str, List[float]] = {}  # conn_id -> timestamps
        
        # Event buffer for polling
        self._event_buffer: List[Dict[str, Any]] = []
        self._max_buffer_size = 1000
    
    async def connect(self, websocket: WebSocket, user_id: str, role: str) -> str:
        """Accept a WebSocket connection."""
        await websocket.accept()
        conn_id = str(uuid.uuid4())
        
        self._connections[conn_id] = websocket
        self._subscriptions[conn_id] = set()
        self._connection_roles[conn_id] = role.lower()
        self._msg_timestamps[conn_id] = []
        
        if user_id not in self._user_connections:
            self._user_connections[user_id] = set()
        self._user_connections[user_id].add(conn_id)
        
        logger.info(f"WebSocket connected: {conn_id} for user {user_id}")
        return conn_id
    
    def disconnect(self, conn_id: str, user_id: str):
        """Remove a WebSocket connection."""
        self._connections.pop(conn_id, None)
        self._subscriptions.pop(conn_id, None)
        self._connection_roles.pop(conn_id, None)
        self._msg_timestamps.pop(conn_id, None)
        
        if user_id in self._user_connections:
            self._user_connections[user_id].discard(conn_id)
        
        logger.info(f"WebSocket disconnected: {conn_id}")
    
    def subscribe(self, conn_id: str, module: str):
        """Subscribe a connection to a module."""
        if conn_id in self._subscriptions:
            role = self._connection_roles.get(conn_id, "viewer")
            if self._is_module_allowed(role, module):
                self._subscriptions[conn_id].add(module)

    def _is_module_allowed(self, role: str, module: str) -> bool:
        if role == "admin":
            return True
        operator_modules = {"system", "ops", "crawler", "mlops", "kb"}
        return module in operator_modules

    def record_message(self, conn_id: str, now_ts: float) -> bool:
        """Return False when connection exceeds message rate limits."""
        bucket = self._msg_timestamps.setdefault(conn_id, [])
        bucket.append(now_ts)
        cutoff = now_ts - 60.0
        self._msg_timestamps[conn_id] = [ts for ts in bucket if ts >= cutoff]
        return len(self._msg_timestamps[conn_id]) <= 120
    
    def unsubscribe(self, conn_id: str, module: str):
        """Unsubscribe a connection from a module."""
        if conn_id in self._subscriptions:
            self._subscriptions[conn_id].discard(module)
    
    async def broadcast(self, event: Dict[str, Any]):
        """Broadcast event to subscribed connections."""
        module = event.get("module", "system")
        
        # Add to event buffer
        self._event_buffer.append(event)
        if len(self._event_buffer) > self._max_buffer_size:
            self._event_buffer = self._event_buffer[-self._max_buffer_size:]
        
        # Send to subscribed connections
        disconnected = []
        
        for conn_id, subscribed_modules in self._subscriptions.items():
            if module in subscribed_modules or "system" in subscribed_modules:
                ws = self._connections.get(conn_id)
                if ws:
                    try:
                        await ws.send_json(event)
                    except Exception as e:
                        logger.error(f"Failed to send to {conn_id}: {e}")
                        disconnected.append(conn_id)
        
        # Cleanup disconnected
        for conn_id in disconnected:
            self._connections.pop(conn_id, None)
            self._subscriptions.pop(conn_id, None)
    
    async def send_to_user(self, user_id: str, event: Dict[str, Any]):
        """Send event to a specific user."""
        conn_ids = self._user_connections.get(user_id, set())
        
        for conn_id in list(conn_ids):
            ws = self._connections.get(conn_id)
            if ws:
                try:
                    await ws.send_json(event)
                except Exception:
                    conn_ids.discard(conn_id)
    
    def get_recent_events(self, since_ts: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get recent events for polling."""
        if not since_ts:
            return self._event_buffer[-100:]
        
        # Filter events after timestamp
        return [
            e for e in self._event_buffer
            if e.get("ts", "") > since_ts
        ][-100:]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics."""
        return {
            "active_connections": len(self._connections),
            "unique_users": len(self._user_connections),
            "event_buffer_size": len(self._event_buffer),
        }


# Global connection manager
connection_manager = ConnectionManager()


# ==============================================================================
# Command Engine Reference
# ==============================================================================

_command_engine = None


def set_command_engine(engine):
    """Set the CommandEngine reference."""
    global _command_engine
    _command_engine = engine


def get_command_engine():
    """Get CommandEngine instance."""
    return _command_engine


def _get_admin_context(request: Request) -> Dict[str, Any]:
    admin = getattr(request.state, "admin", None)
    if not isinstance(admin, dict):
        raise HTTPException(status_code=401, detail="Admin authentication required")
    return admin


def _verify_signed_request(
    *,
    admin: Dict[str, Any],
    command_type: str,
    payload: CommandRequest,
) -> None:
    user_id = str(admin.get("adminId") or admin.get("sub") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid admin token")

    ok = signing_verifier.verify(
        user_id=user_id,
        command_type=command_type,
        target=payload.target,
        timestamp=payload.timestamp,
        nonce=payload.nonce,
        signature=payload.signature,
    )
    if not ok:
        raise HTTPException(status_code=403, detail="Invalid command signature/nonce/timestamp")


# ==============================================================================
# Module References
# ==============================================================================

_crawler_manager = None
_kb_manager = None
_mlops_manager = None


def set_managers(crawler=None, kb=None, mlops=None):
    """Set manager references."""
    global _crawler_manager, _kb_manager, _mlops_manager
    if crawler:
        _crawler_manager = crawler
    if kb:
        _kb_manager = kb
    if mlops:
        _mlops_manager = mlops


# ==============================================================================
# WebSocket Route
# ==============================================================================

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(None),
):
    """
    WebSocket endpoint for realtime communication.
    
    Protocol:
    - Client sends: {"action": "subscribe|unsubscribe|ping|command", ...}
    - Server sends: {"type": "status|alert|metric|log|heartbeat", "module": "...", "payload": {}, "ts": "..."}
    """
    auth = auth_admin_websocket(websocket, token)
    role = str(auth.get("role", "")).lower()
    if role not in {"admin", "operator"}:
        await websocket.close(code=1008)
        return
    user_id = str(auth.get("adminId") or auth.get("sub") or "")
    if not user_id:
        await websocket.close(code=1008)
        return
    
    conn_id = await connection_manager.connect(websocket, user_id, role)
    
    # Subscribe to event bus for realtime updates
    subscribe_stream(websocket)
    
    try:
        # Send welcome message
        await websocket.send_json({
            "type": "status",
            "module": "system",
            "payload": {"connected": True, "conn_id": conn_id},
            "ts": datetime.utcnow().isoformat(),
        })
        
        # Start heartbeat task
        async def heartbeat():
            while True:
                try:
                    await asyncio.sleep(30)
                    await websocket.send_json({
                        "type": "heartbeat",
                        "module": "system",
                        "payload": {"server_time": datetime.utcnow().isoformat()},
                        "ts": datetime.utcnow().isoformat(),
                    })
                except Exception:
                    break
        
        heartbeat_task = asyncio.create_task(heartbeat())
        
        try:
            while True:
                # Receive and process messages
                data = await websocket.receive_json()
                action = data.get("action")
                
                if action == "ping":
                    await websocket.send_json({
                        "type": "heartbeat",
                        "module": "system",
                        "payload": {"pong": True},
                        "ts": datetime.utcnow().isoformat(),
                    })
                    
                elif action == "subscribe":
                    module = data.get("module", "system")
                    connection_manager.subscribe(conn_id, module)
                    await websocket.send_json({
                        "type": "status",
                        "module": "system",
                        "payload": {"subscribed": module},
                        "ts": datetime.utcnow().isoformat(),
                    })
                    
                elif action == "unsubscribe":
                    module = data.get("module", "system")
                    connection_manager.unsubscribe(conn_id, module)
                    await websocket.send_json({
                        "type": "status",
                        "module": "system",
                        "payload": {"unsubscribed": module},
                        "ts": datetime.utcnow().isoformat(),
                    })
                    
                elif action == "command":
                    # Handle inline command acknowledgement
                    command_type = data.get("command")
                    payload = data.get("payload", {})
                    
                    # Inline ws command ack (execution remains API-driven)
                    await websocket.send_json({
                        "type": "status",
                        "module": "system",
                        "payload": {
                            "command_received": command_type,
                            "status": "queued",
                        },
                        "ts": datetime.utcnow().isoformat(),
                    })
                    
        finally:
            heartbeat_task.cancel()
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {conn_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        # Unsubscribe from event bus
        unsubscribe(websocket)
        connection_manager.disconnect(conn_id, user_id)


async def liveops_ws_handler(websocket: WebSocket):
    """
    WebSocket handler with enhanced token verification.
    
    Uses verify_ws_token() for security validation before accepting connection.
    """
    token = websocket.query_params.get("token")
    
    # Verify token before accepting connection
    try:
        user_payload = await verify_ws_token(token)
        # Token valid, proceed with connection
        await websocket_endpoint(websocket=websocket, token=token)
    except AuthError as e:
        logger.warning(f"WebSocket auth failed: {e.message} (code={e.code})")
        await websocket.close(code=1008)
    except Exception as e:
        logger.error(f"WebSocket handler error: {e}")
        await websocket.close(code=1011)


# ==============================================================================
# SSE Route
# ==============================================================================

@router.get("/sse")
async def sse_endpoint(
    token: str = Query(None),
    modules: str = Query("system", description="Comma-separated modules to subscribe"),
):
    """Server-Sent Events endpoint for realtime updates."""
    
    async def event_generator():
        subscribed = set(modules.split(","))
        last_heartbeat = datetime.utcnow()
        
        while True:
            # Check for new events (simplified - would integrate with actual event system)
            current_time = datetime.utcnow()
            
            # Send heartbeat every 30 seconds
            if (current_time - last_heartbeat).total_seconds() >= 30:
                event = {
                    "type": "heartbeat",
                    "module": "system",
                    "payload": {"server_time": current_time.isoformat()},
                    "ts": current_time.isoformat(),
                }
                yield f"data: {json.dumps(event)}\n\n"
                last_heartbeat = current_time
            
            # Get any pending events
            # This would connect to the actual event stream
            
            await asyncio.sleep(1)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==============================================================================
# Stream Route (Alias for SSE)
# ==============================================================================

@router.get("/stream", summary="LiveOps event stream")
async def stream_endpoint(
    token: str = Query(None),
    modules: str = Query("system", description="Comma-separated modules to subscribe"),
):
    """
    Event stream endpoint for realtime updates (SSE-based).
    
    This is a semantic alias for /sse to match LiveOps Dashboard requirements.
    """
    
    async def event_generator():
        subscribed = set(modules.split(","))
        last_heartbeat = datetime.utcnow()
        
        while True:
            current_time = datetime.utcnow()
            
            # Send heartbeat every 30 seconds
            if (current_time - last_heartbeat).total_seconds() >= 30:
                event = emit_event(
                    event_type="heartbeat",
                    data={"server_time": current_time.isoformat()},
                    module="system",
                )
                yield f"data: {json.dumps(event)}\n\n"
                last_heartbeat = current_time
            
            await asyncio.sleep(1)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==============================================================================
# Polling Route
# ==============================================================================

@router.get("/poll")
async def poll_endpoint(
    since: Optional[str] = Query(None, description="Timestamp to get events since"),
):
    """Polling fallback endpoint."""
    events = connection_manager.get_recent_events(since)
    return events


@router.get("/health", summary="LiveOps health")
async def liveops_health():
    engine = get_command_engine()
    return {
        "status": "ok",
        "router": "liveops",
        "engine_ready": engine is not None,
        "connections": connection_manager.get_stats(),
        "ts": datetime.utcnow().isoformat(),
    }


# ==============================================================================
# Command Routes
# ==============================================================================

@router.post(
    "/crawler/kill",
    response_model=CommandResponse,
    summary="Kill crawler",
    description="Force kill an active crawler process",
    dependencies=[Depends(require_role(["admin", "operator"]))],
)
async def kill_crawler(request: CrawlerKillRequest, raw_request: Request):
    """Kill a crawler."""
    engine = get_command_engine()
    
    if not engine:
        raise HTTPException(status_code=503, detail="Command engine not available")

    admin = _get_admin_context(raw_request)
    _verify_signed_request(admin=admin, command_type="crawler_kill", payload=request)
    
    try:
        from backend.ops.command_engine.models import Command, CommandType, CommandPriority
        
        command = Command(
            type=CommandType.CRAWLER_KILL,
            target=request.site_name,
            params={
                "site_name": request.site_name,
                "force": request.force,
                **request.params,
            },
            idempotency_key=request.idempotency_key,
            priority=CommandPriority(request.priority),
            timeout_seconds=request.timeout_seconds,
            dry_run=request.dry_run,
            user_id=str(admin.get("adminId") or admin.get("sub") or "admin"),
            role=str(admin.get("role", "admin")),
        )
        
        result = await engine.submit(command)
        
        # Broadcast event
        await connection_manager.broadcast({
            "type": "status",
            "module": "crawler",
            "payload": {
                "action": "kill",
                "target": request.site_name,
                "command_id": command.id,
                "state": result.state if isinstance(result.state, str) else result.state.value,
            },
            "ts": datetime.utcnow().isoformat(),
        })
        
        return CommandResponse(
            status="ok" if result.success else "error",
            data={
                "command_id": result.command_id,
                "state": result.state if isinstance(result.state, str) else result.state.value,
            },
            meta={"dry_run": request.dry_run},
        )
        
    except Exception as e:
        logger.error(f"Kill crawler failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/job/pause",
    response_model=CommandResponse,
    summary="Pause job",
    description="Pause an active job",
    dependencies=[Depends(require_role(["admin", "operator"]))],
)
async def pause_job(request: JobControlRequest, raw_request: Request):
    """Pause a job."""
    engine = get_command_engine()
    
    if not engine:
        raise HTTPException(status_code=503, detail="Command engine not available")

    admin = _get_admin_context(raw_request)
    _verify_signed_request(admin=admin, command_type="job_pause", payload=request)
    
    try:
        from backend.ops.command_engine.models import Command, CommandType, CommandPriority
        
        command = Command(
            type=CommandType.JOB_PAUSE,
            target=request.job_id,
            params={"job_id": request.job_id, **request.params},
            idempotency_key=request.idempotency_key,
            priority=CommandPriority(request.priority),
            timeout_seconds=request.timeout_seconds,
            dry_run=request.dry_run,
            user_id=str(admin.get("adminId") or admin.get("sub") or "admin"),
            role=str(admin.get("role", "admin")),
        )
        
        result = await engine.submit(command)
        
        await connection_manager.broadcast({
            "type": "status",
            "module": "ops",
            "payload": {
                "action": "job_pause",
                "target": request.job_id,
                "command_id": command.id,
                "state": result.state if isinstance(result.state, str) else result.state.value,
            },
            "ts": datetime.utcnow().isoformat(),
        })
        
        return CommandResponse(
            status="ok" if result.success else "error",
            data={
                "command_id": result.command_id,
                "state": result.state if isinstance(result.state, str) else result.state.value,
            },
        )
        
    except Exception as e:
        logger.error(f"Pause job failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/job/resume",
    response_model=CommandResponse,
    summary="Resume job",
    description="Resume a paused job",
    dependencies=[Depends(require_role(["admin", "operator"]))],
)
async def resume_job(request: JobControlRequest, raw_request: Request):
    """Resume a job."""
    engine = get_command_engine()
    
    if not engine:
        raise HTTPException(status_code=503, detail="Command engine not available")

    admin = _get_admin_context(raw_request)
    _verify_signed_request(admin=admin, command_type="job_resume", payload=request)
    
    try:
        from backend.ops.command_engine.models import Command, CommandType, CommandPriority
        
        command = Command(
            type=CommandType.JOB_RESUME,
            target=request.job_id,
            params={"job_id": request.job_id, **request.params},
            idempotency_key=request.idempotency_key,
            priority=CommandPriority(request.priority),
            timeout_seconds=request.timeout_seconds,
            dry_run=request.dry_run,
            user_id=str(admin.get("adminId") or admin.get("sub") or "admin"),
            role=str(admin.get("role", "admin")),
        )
        
        result = await engine.submit(command)
        
        await connection_manager.broadcast({
            "type": "status",
            "module": "ops",
            "payload": {
                "action": "job_resume",
                "target": request.job_id,
                "command_id": command.id,
                "state": result.state if isinstance(result.state, str) else result.state.value,
            },
            "ts": datetime.utcnow().isoformat(),
        })
        
        return CommandResponse(
            status="ok" if result.success else "error",
            data={
                "command_id": result.command_id,
                "state": result.state if isinstance(result.state, str) else result.state.value,
            },
        )
        
    except Exception as e:
        logger.error(f"Resume job failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/kb/rollback",
    response_model=CommandResponse,
    summary="Rollback KB",
    description="Rollback knowledge base to a previous version",
    dependencies=[Depends(require_role(["admin"]))],
)
async def rollback_kb(request: KBRollbackRequest, raw_request: Request):
    """Rollback knowledge base."""
    engine = get_command_engine()
    
    if not engine:
        raise HTTPException(status_code=503, detail="Command engine not available")

    admin = _get_admin_context(raw_request)
    _verify_signed_request(admin=admin, command_type="kb_rollback", payload=request)
    
    try:
        from backend.ops.command_engine.models import Command, CommandType, CommandPriority
        
        command = Command(
            type=CommandType.KB_ROLLBACK,
            target=request.target,
            params={
                "version": request.version,
                "backup_current": request.backup_current,
                **request.params,
            },
            idempotency_key=request.idempotency_key,
            priority=CommandPriority(request.priority),
            timeout_seconds=request.timeout_seconds,
            dry_run=request.dry_run,
            user_id=str(admin.get("adminId") or admin.get("sub") or "admin"),
            role=str(admin.get("role", "admin")),
        )
        
        result = await engine.submit(command)
        
        await connection_manager.broadcast({
            "type": "alert",
            "module": "kb",
            "payload": {
                "action": "rollback",
                "target": request.target,
                "version": request.version,
                "command_id": command.id,
                "state": result.state if isinstance(result.state, str) else result.state.value,
            },
            "ts": datetime.utcnow().isoformat(),
        })
        
        return CommandResponse(
            status="ok" if result.success else "error",
            data={
                "command_id": result.command_id,
                "state": result.state if isinstance(result.state, str) else result.state.value,
            },
        )
        
    except Exception as e:
        logger.error(f"KB rollback failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/mlops/freeze",
    response_model=CommandResponse,
    summary="Freeze model",
    description="Freeze a model to prevent updates",
    dependencies=[Depends(require_role(["admin"]))],
)
async def freeze_model(request: MLOpsModelRequest, raw_request: Request):
    """Freeze a model."""
    engine = get_command_engine()
    
    if not engine:
        raise HTTPException(status_code=503, detail="Command engine not available")

    admin = _get_admin_context(raw_request)
    _verify_signed_request(admin=admin, command_type="mlops_freeze", payload=request)
    
    try:
        from backend.ops.command_engine.models import Command, CommandType, CommandPriority
        
        command = Command(
            type=CommandType.MLOPS_FREEZE,
            target=request.model_id,
            params={
                "model_id": request.model_id,
                "reason": request.reason,
                **request.params,
            },
            idempotency_key=request.idempotency_key,
            priority=CommandPriority(request.priority),
            timeout_seconds=request.timeout_seconds,
            dry_run=request.dry_run,
            user_id=str(admin.get("adminId") or admin.get("sub") or "admin"),
            role=str(admin.get("role", "admin")),
        )
        
        result = await engine.submit(command)
        
        await connection_manager.broadcast({
            "type": "alert",
            "module": "mlops",
            "payload": {
                "action": "freeze",
                "model_id": request.model_id,
                "command_id": command.id,
                "state": result.state if isinstance(result.state, str) else result.state.value,
            },
            "ts": datetime.utcnow().isoformat(),
        })
        
        return CommandResponse(
            status="ok" if result.success else "error",
            data={
                "command_id": result.command_id,
                "state": result.state if isinstance(result.state, str) else result.state.value,
            },
        )
        
    except Exception as e:
        logger.error(f"Freeze model failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/mlops/retrain",
    response_model=CommandResponse,
    summary="Retrain model",
    description="Trigger model retraining",
    dependencies=[Depends(require_role(["admin", "operator"]))],
)
async def retrain_model(request: RetrainRequest, raw_request: Request):
    """Retrain a model."""
    engine = get_command_engine()
    
    if not engine:
        raise HTTPException(status_code=503, detail="Command engine not available")

    admin = _get_admin_context(raw_request)
    _verify_signed_request(admin=admin, command_type="mlops_retrain", payload=request)
    
    try:
        from backend.ops.command_engine.models import Command, CommandType, CommandPriority
        
        command = Command(
            type=CommandType.MLOPS_RETRAIN,
            target=request.model_id,
            params={
                "model_id": request.model_id,
                "config_override": request.config_override,
                "schedule": request.schedule,
                **request.params,
            },
            idempotency_key=request.idempotency_key,
            priority=CommandPriority(request.priority),
            timeout_seconds=request.timeout_seconds,
            dry_run=request.dry_run,
            user_id=str(admin.get("adminId") or admin.get("sub") or "admin"),
            role=str(admin.get("role", "admin")),
        )
        
        result = await engine.submit(command)
        
        await connection_manager.broadcast({
            "type": "status",
            "module": "mlops",
            "payload": {
                "action": "retrain",
                "model_id": request.model_id,
                "command_id": command.id,
                "state": result.state if isinstance(result.state, str) else result.state.value,
            },
            "ts": datetime.utcnow().isoformat(),
        })
        
        return CommandResponse(
            status="ok" if result.success else "error",
            data={
                "command_id": result.command_id,
                "state": result.state if isinstance(result.state, str) else result.state.value,
            },
        )
        
    except Exception as e:
        logger.error(f"Retrain model failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/simulate",
    response_model=CommandResponse,
    summary="Simulate operation",
    description="Run a dry-run simulation of an operation",
    dependencies=[Depends(require_role(["admin", "operator"]))],
)
async def simulate_operation(request: SimulateRequest, raw_request: Request):
    """Simulate an operation (dry-run)."""
    engine = get_command_engine()
    
    if not engine:
        raise HTTPException(status_code=503, detail="Command engine not available")

    admin = _get_admin_context(raw_request)
    
    try:
        from backend.ops.command_engine.models import Command, CommandType, CommandPriority
        
        # Map string to CommandType
        try:
            cmd_type = CommandType(request.command_type)
        except ValueError:
            cmd_type = CommandType.CUSTOM
        
        command = Command(
            type=cmd_type,
            target=request.target,
            params={
                "chaos_scenario": request.chaos_scenario,
                **request.params,
            },
            dry_run=True,  # Always dry-run for simulation
            user_id=str(admin.get("adminId") or admin.get("sub") or "admin"),
            role=str(admin.get("role", "admin")),
        )
        
        result = await engine.execute_immediate(command)
        
        return CommandResponse(
            status="ok",
            data={
                "command_id": result.command_id,
                "state": result.state if isinstance(result.state, str) else result.state.value,
                "simulation_result": result.data,
            },
            meta={"dry_run": True, "chaos_scenario": request.chaos_scenario},
        )
        
    except Exception as e:
        logger.error(f"Simulation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/commands/{command_id}",
    response_model=CommandStatusResponse,
    summary="Get command status",
    description="Get the status of a command",
    dependencies=[Depends(require_role(["admin", "operator"]))],
)
async def get_command_status(command_id: str):
    """Get command status."""
    engine = get_command_engine()
    
    if not engine:
        raise HTTPException(status_code=503, detail="Command engine not available")
    
    result = await engine.get_command_status(command_id)
    
    if not result:
        raise HTTPException(status_code=404, detail="Command not found")
    
    return CommandStatusResponse(
        command_id=result.command_id,
        state=result.state if isinstance(result.state, str) else result.state.value,
        progress=0.0,
        result=result.data,
        error=result.error,
    )


@router.get(
    "/commands",
    response_model=List[CommandStatusResponse],
    summary="List commands",
    description="List recent commands",
    dependencies=[Depends(require_role(["admin", "operator"]))],
)
async def list_commands(limit: int = Query(50, ge=1, le=500)):
    engine = get_command_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Command engine not available")

    items = await engine.list_commands(limit=limit)
    return [
        CommandStatusResponse(
            command_id=item.command_id,
            state=item.state if isinstance(item.state, str) else item.state.value,
            progress=float(item.data.get("progress", 0.0) if isinstance(item.data, dict) else 0.0),
            result=item.data,
            error=item.error,
        )
        for item in items
    ]


@router.get(
    "/command/list",
    response_model=List[CommandStatusResponse],
    summary="List commands (alias)",
    description="List recent commands (semantic alias for /commands)",
    dependencies=[Depends(require_role(["admin", "operator"]))],
)
async def list_commands_alias(limit: int = Query(50, ge=1, le=500)):
    """Semantic alias for /commands to match LiveOps Dashboard requirements."""
    engine = get_command_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Command engine not available")

    items = await engine.list_commands(limit=limit)
    return [
        CommandStatusResponse(
            command_id=item.command_id,
            state=item.state if isinstance(item.state, str) else item.state.value,
            progress=float(item.data.get("progress", 0.0) if isinstance(item.data, dict) else 0.0),
            result=item.data,
            error=item.error,
        )
        for item in items
    ]


@router.post(
    "/commands/{command_id}/approve",
    response_model=CommandResponse,
    summary="Approve command",
    description="Approve a command awaiting approval",
    dependencies=[Depends(require_role(["admin"]))],
)
async def approve_command(command_id: str, body: ApprovalActionRequest, raw_request: Request):
    engine = get_command_engine()
    if not engine:
        raise HTTPException(status_code=503, detail="Command engine not available")

    admin = _get_admin_context(raw_request)
    approver_id = str(admin.get("adminId") or admin.get("sub") or "admin")
    approver_role = str(admin.get("role", "admin"))

    result = await engine.approve_command(
        command_id=command_id,
        approver_id=approver_id,
        approver_role=approver_role,
        comment=body.approver_comment,
    )

    if not result:
        raise HTTPException(status_code=404, detail="Command approval request not found")

    return CommandResponse(
        status="ok" if result.success else "error",
        data={
            "command_id": result.command_id,
            "state": result.state if isinstance(result.state, str) else result.state.value,
        },
        meta={"error": result.error} if result.error else {},
    )


@router.get(
    "/widget/{widget_type}",
    response_model=Dict[str, Any],
    summary="Get widget data",
    description="Get data for a specific dashboard widget",
    dependencies=[Depends(require_role(["admin", "operator"]))],
)
async def get_widget_data(widget_type: str):
    now = datetime.utcnow().isoformat()
    if widget_type == "health":
        return {
            "status": "healthy",
            "overallStatus": "healthy",
            "services": [],
            "uptime": 0,
            "lastUpdate": now,
        }
    if widget_type == "drift":
        return {
            "status": "healthy",
            "currentDrift": 0.01,
            "threshold": 0.2,
            "trend": "stable",
            "history": [],
            "alertActive": False,
            "lastUpdate": now,
        }
    if widget_type == "cost":
        return {
            "status": "healthy",
            "currentMonth": 0,
            "budget": 1000,
            "forecast": 0,
            "breakdown": [],
            "trend": "stable",
            "lastUpdate": now,
        }
    if widget_type == "sla":
        return {
            "status": "healthy",
            "compliance": 100.0,
            "target": 99.5,
            "metrics": [],
            "incidents": 0,
            "lastUpdate": now,
        }
    if widget_type == "errors":
        return {
            "status": "healthy",
            "currentRate": 0.0,
            "threshold": 1.0,
            "errors24h": 0,
            "errorsByType": [],
            "trend": "stable",
            "lastUpdate": now,
        }
    if widget_type == "queue":
        return {
            "status": "healthy",
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "avgWaitTime": 0,
            "jobs": [],
            "lastUpdate": now,
        }
    raise HTTPException(status_code=404, detail=f"Unknown widget type: {widget_type}")


@router.post(
    "/commands/{command_id}/cancel",
    response_model=CommandResponse,
    summary="Cancel command",
    description="Cancel a queued or running command",
    dependencies=[Depends(require_role(["admin", "operator"]))],
)
async def cancel_command(command_id: str, raw_request: Request):
    """Cancel a command."""
    engine = get_command_engine()
    
    if not engine:
        raise HTTPException(status_code=503, detail="Command engine not available")
    
    admin = _get_admin_context(raw_request)
    user_id = str(admin.get("adminId") or admin.get("sub") or "admin")
    role = str(admin.get("role", "admin"))
    
    cancelled = await engine.cancel_command(command_id, user_id, role)
    
    if not cancelled:
        raise HTTPException(status_code=404, detail="Command not found or cannot be cancelled")
    
    await connection_manager.broadcast({
        "type": "status",
        "module": "system",
        "payload": {
            "action": "command_cancelled",
            "command_id": command_id,
        },
        "ts": datetime.utcnow().isoformat(),
    })
    
    return CommandResponse(
        status="ok",
        data={"command_id": command_id, "state": "cancelled"},
    )


# ==============================================================================
# Stats & Monitoring
# ==============================================================================

@router.get(
    "/stats",
    summary="LiveOps statistics",
    description="Get live operations statistics",
)
async def get_liveops_stats():
    """Get live operations statistics."""
    engine = get_command_engine()
    
    stats = {
        "connections": connection_manager.get_stats(),
    }
    
    if engine:
        stats["engine"] = engine.get_stats()
    
    return stats

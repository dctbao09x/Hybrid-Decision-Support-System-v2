# backend/api/routers/liveops/__init__.py
"""
LiveOps Package
===============

WebSocket authentication and realtime event bus.
"""

from .event_bus import (
    emit_event,
    publish_status,
    subscribe_stream,
    unsubscribe,
    get_subscriber_count,
    broadcast_progress,
    broadcast_command_done,
)

from .ws_handler import (
    verify_ws_token,
    validate_ws_connection,
    AuthError,
)

__all__ = [
    "emit_event",
    "publish_status",
    "subscribe_stream",
    "unsubscribe",
    "get_subscriber_count",
    "broadcast_progress",
    "broadcast_command_done",
    "verify_ws_token",
    "validate_ws_connection",
    "AuthError",
]

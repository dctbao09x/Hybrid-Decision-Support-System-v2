# backend/api/routers/liveops/event_bus.py
"""
Event Bus for LiveOps Realtime Pipeline
=======================================

Provides:
- subscribe_stream() - Subscribe WebSocket to event stream
- unsubscribe() - Unsubscribe WebSocket from stream  
- publish_status() - Broadcast status update to all subscribers
- emit_event() - Create standardized event payload
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Set
from weakref import WeakSet

logger = logging.getLogger("liveops.event_bus")

# Global subscriber set (WebSocket connections)
_subscribers: Set = set()
_subscriber_lock = asyncio.Lock()


def emit_event(event_type: str, data: Any, module: str = "system") -> Dict[str, Any]:
    """
    Create a standardized event payload.
    
    Args:
        event_type: Type of event (e.g., "EXEC_PROGRESS", "COMMAND_DONE")
        data: Event payload data
        module: Module source (e.g., "system", "ops", "crawler")
        
    Returns:
        Standardized event dict
    """
    return {
        "type": event_type,
        "module": module,
        "data": data,
        "ts": datetime.utcnow().isoformat() + "Z",
    }


async def publish_status(event: Dict[str, Any]) -> int:
    """
    Broadcast a status event to all subscribed WebSockets.
    
    Args:
        event: Event dict (from emit_event or custom)
        
    Returns:
        Number of subscribers that received the event
    """
    if not event:
        return 0
        
    sent_count = 0
    disconnected = []
    
    async with _subscriber_lock:
        for ws in list(_subscribers):
            try:
                await ws.send_json(event)
                sent_count += 1
            except Exception as e:
                logger.warning(f"Failed to send to subscriber: {e}")
                disconnected.append(ws)
        
        # Cleanup disconnected
        for ws in disconnected:
            _subscribers.discard(ws)
    
    if sent_count > 0:
        logger.debug(f"Published event to {sent_count} subscribers: {event.get('type')}")
    
    return sent_count


def subscribe_stream(ws) -> bool:
    """
    Subscribe a WebSocket connection to the event stream.
    
    Args:
        ws: WebSocket connection
        
    Returns:
        True if subscribed successfully
    """
    try:
        _subscribers.add(ws)
        logger.info(f"WebSocket subscribed to event stream. Total: {len(_subscribers)}")
        return True
    except Exception as e:
        logger.error(f"Failed to subscribe WebSocket: {e}")
        return False


def unsubscribe(ws) -> bool:
    """
    Unsubscribe a WebSocket connection from the event stream.
    
    Args:
        ws: WebSocket connection
        
    Returns:
        True if unsubscribed successfully
    """
    try:
        _subscribers.discard(ws)
        logger.info(f"WebSocket unsubscribed from event stream. Total: {len(_subscribers)}")
        return True
    except Exception as e:
        logger.error(f"Failed to unsubscribe WebSocket: {e}")
        return False


def get_subscriber_count() -> int:
    """Get the current number of subscribers."""
    return len(_subscribers)


async def broadcast_progress(command_id: str, progress: float, message: str = "") -> int:
    """
    Convenience method to broadcast execution progress.
    
    Args:
        command_id: Command identifier
        progress: Progress percentage (0.0 - 1.0)
        message: Optional progress message
        
    Returns:
        Number of subscribers notified
    """
    event = emit_event(
        event_type="EXEC_PROGRESS",
        data={
            "command_id": command_id,
            "progress": progress,
            "message": message,
        },
        module="ops",
    )
    return await publish_status(event)


async def broadcast_command_done(command_id: str, success: bool, result: Any = None) -> int:
    """
    Convenience method to broadcast command completion.
    
    Args:
        command_id: Command identifier
        success: Whether command succeeded
        result: Command result data
        
    Returns:
        Number of subscribers notified
    """
    event = emit_event(
        event_type="COMMAND_DONE",
        data={
            "command_id": command_id,
            "success": success,
            "result": result,
        },
        module="ops",
    )
    return await publish_status(event)

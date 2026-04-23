# backend/ops/command_engine/notifier.py
"""
Command Notifier
================

Sends notifications about command execution status.

Features:
- Multi-channel notifications (WebSocket, email, webhook)
- Priority-based routing
- Rate limiting
- Templated messages
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

from .models import Command, CommandResult, CommandState

logger = logging.getLogger("ops.command_engine.notifier")


class NotificationChannel(str, Enum):
    """Available notification channels."""
    WEBSOCKET = "websocket"
    EMAIL = "email"
    WEBHOOK = "webhook"
    SLACK = "slack"
    IN_APP = "in_app"


class NotificationPriority(str, Enum):
    """Notification priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Notification:
    """Notification message."""
    id: str
    channel: NotificationChannel
    priority: NotificationPriority
    title: str
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Targeting
    recipients: List[str] = field(default_factory=list)  # User IDs or addresses
    
    # Context
    command_id: Optional[str] = None
    trace_id: Optional[str] = None
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Delivery tracking
    delivered: bool = False
    delivery_attempts: int = 0
    last_attempt: Optional[datetime] = None
    error: Optional[str] = None


@dataclass
class NotificationRule:
    """Rule for automatic notifications."""
    id: str
    name: str
    enabled: bool = True
    
    # Trigger conditions
    trigger_states: Set[CommandState] = field(default_factory=set)
    trigger_command_types: Set[str] = field(default_factory=set)
    trigger_on_failure: bool = False
    trigger_on_success: bool = False
    
    # Notification settings
    channels: Set[NotificationChannel] = field(default_factory=set)
    priority: NotificationPriority = NotificationPriority.NORMAL
    
    # Recipients
    notify_initiator: bool = True
    notify_roles: Set[str] = field(default_factory=set)
    notify_users: Set[str] = field(default_factory=set)
    
    # Message template
    title_template: str = "Command {command_type}: {state}"
    message_template: str = "Command {command_id} on {target} is now {state}"


# Handler type
NotificationHandler = Callable[[Notification], Coroutine[Any, Any, bool]]


class CommandNotifier:
    """
    Notification service for command events.
    
    Features:
    - Multi-channel delivery
    - Rule-based automation
    - Template support
    - Delivery tracking
    """
    
    def __init__(self):
        # Channel handlers
        self._handlers: Dict[NotificationChannel, NotificationHandler] = {}
        
        # Notification rules
        self._rules: Dict[str, NotificationRule] = {}
        
        # Pending notifications queue
        self._pending: asyncio.Queue[Notification] = asyncio.Queue()
        
        # Delivery statistics
        self._stats = {
            "total_sent": 0,
            "total_delivered": 0,
            "total_failed": 0,
            "by_channel": {},
        }
        
        # Rate limiting
        self._rate_limits: Dict[str, List[float]] = {}
        self._rate_window = 60  # seconds
        self._rate_limit = 100  # per window
        
        # Worker task
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        
        # Register default rules
        self._register_default_rules()
    
    def register_handler(
        self,
        channel: NotificationChannel,
        handler: NotificationHandler,
    ):
        """Register a handler for a notification channel."""
        self._handlers[channel] = handler
        logger.info(f"Registered handler for channel {channel.value}")
    
    def add_rule(self, rule: NotificationRule):
        """Add a notification rule."""
        self._rules[rule.id] = rule
        logger.info(f"Added notification rule: {rule.name}")
    
    def remove_rule(self, rule_id: str):
        """Remove a notification rule."""
        self._rules.pop(rule_id, None)
    
    async def start(self):
        """Start the notification worker."""
        if self._running:
            return
            
        self._running = True
        self._worker_task = asyncio.create_task(self._delivery_worker())
        logger.info("Notification worker started")
    
    async def stop(self):
        """Stop the notification worker."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Notification worker stopped")
    
    async def notify_command_state(
        self,
        command: Command,
        state: CommandState,
        result: Optional[CommandResult] = None,
    ):
        """
        Send notifications based on command state change.
        
        Args:
            command: The command that changed state
            state: New state
            result: Optional execution result
        """
        # Find matching rules
        for rule in self._rules.values():
            if not rule.enabled:
                continue
                
            # Check trigger conditions
            if rule.trigger_states and state not in rule.trigger_states:
                continue
            if rule.trigger_command_types:
                cmd_type = command.type if isinstance(command.type, str) else command.type.value
                if cmd_type not in rule.trigger_command_types:
                    continue
            if rule.trigger_on_failure and state != CommandState.FAILED:
                continue
            if rule.trigger_on_success and state != CommandState.DONE:
                continue
            
            # Build recipient list
            recipients = list(rule.notify_users)
            if rule.notify_initiator:
                recipients.append(command.user_id)
            
            # Create notifications for each channel
            for channel in rule.channels:
                notification = self._create_notification(
                    command=command,
                    state=state,
                    result=result,
                    channel=channel,
                    rule=rule,
                    recipients=recipients,
                )
                
                await self._pending.put(notification)
    
    async def send_direct(
        self,
        channel: NotificationChannel,
        title: str,
        message: str,
        recipients: List[str],
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Send a direct notification."""
        import uuid
        notification = Notification(
            id=str(uuid.uuid4()),
            channel=channel,
            priority=priority,
            title=title,
            message=message,
            recipients=recipients,
            metadata=metadata or {},
        )
        
        await self._pending.put(notification)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get notification statistics."""
        return {
            **self._stats,
            "pending_count": self._pending.qsize(),
            "registered_channels": list(self._handlers.keys()),
            "active_rules": len([r for r in self._rules.values() if r.enabled]),
        }
    
    def _create_notification(
        self,
        command: Command,
        state: CommandState,
        result: Optional[CommandResult],
        channel: NotificationChannel,
        rule: NotificationRule,
        recipients: List[str],
    ) -> Notification:
        """Create a notification from a rule and command."""
        import uuid
        
        # Template variables
        state_str = state if isinstance(state, str) else state.value
        cmd_type = command.type if isinstance(command.type, str) else command.type.value
        
        vars = {
            "command_id": command.id,
            "command_type": cmd_type,
            "target": command.target,
            "state": state_str,
            "user_id": command.user_id,
            "error": result.error if result else None,
        }
        
        title = rule.title_template.format(**vars)
        message = rule.message_template.format(**vars)
        
        return Notification(
            id=str(uuid.uuid4()),
            channel=channel,
            priority=rule.priority,
            title=title,
            message=message,
            recipients=recipients,
            command_id=command.id,
            trace_id=command.trace_id,
            metadata={
                "rule_id": rule.id,
                "command_type": cmd_type,
                "state": state_str,
            },
        )
    
    async def _delivery_worker(self):
        """Worker that delivers pending notifications."""
        while self._running:
            try:
                # Get next notification (with timeout)
                try:
                    notification = await asyncio.wait_for(
                        self._pending.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Check rate limit
                if not self._check_rate_limit(notification.channel.value):
                    logger.warning(f"Rate limit exceeded for channel {notification.channel}")
                    # Re-queue with delay
                    await asyncio.sleep(1)
                    await self._pending.put(notification)
                    continue
                
                # Attempt delivery
                await self._deliver(notification)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Notification worker error: {e}", exc_info=True)
                await asyncio.sleep(1)
    
    async def _deliver(self, notification: Notification):
        """Deliver a notification through its channel."""
        handler = self._handlers.get(notification.channel)
        
        if not handler:
            logger.warning(f"No handler for channel {notification.channel}")
            self._stats["total_failed"] += 1
            return
        
        notification.delivery_attempts += 1
        notification.last_attempt = datetime.utcnow()
        
        try:
            success = await handler(notification)
            
            if success:
                notification.delivered = True
                self._stats["total_delivered"] += 1
                
                channel_key = notification.channel.value
                if channel_key not in self._stats["by_channel"]:
                    self._stats["by_channel"][channel_key] = {"delivered": 0, "failed": 0}
                self._stats["by_channel"][channel_key]["delivered"] += 1
            else:
                self._stats["total_failed"] += 1
                
        except Exception as e:
            logger.error(f"Notification delivery failed: {e}")
            notification.error = str(e)
            self._stats["total_failed"] += 1
        
        self._stats["total_sent"] += 1
    
    def _check_rate_limit(self, key: str) -> bool:
        """Check if within rate limit for a channel."""
        import time
        now = time.time()
        
        if key not in self._rate_limits:
            self._rate_limits[key] = []
        
        # Clean old entries
        self._rate_limits[key] = [
            ts for ts in self._rate_limits[key]
            if now - ts < self._rate_window
        ]
        
        if len(self._rate_limits[key]) >= self._rate_limit:
            return False
        
        self._rate_limits[key].append(now)
        return True
    
    def _register_default_rules(self):
        """Register default notification rules."""
        # Failure notification
        self.add_rule(NotificationRule(
            id="default_failure",
            name="Command Failure Alert",
            enabled=True,
            trigger_on_failure=True,
            channels={NotificationChannel.IN_APP, NotificationChannel.WEBSOCKET},
            priority=NotificationPriority.HIGH,
            notify_initiator=True,
            title_template="Command Failed: {command_type}",
            message_template="Command {command_id} on {target} failed: {error}",
        ))
        
        # Critical command notification
        self.add_rule(NotificationRule(
            id="critical_commands",
            name="Critical Command Notification",
            enabled=True,
            trigger_command_types={"mlops_freeze", "kb_rollback", "system_restore"},
            trigger_states={CommandState.RUNNING, CommandState.DONE, CommandState.FAILED},
            channels={NotificationChannel.IN_APP, NotificationChannel.WEBSOCKET},
            priority=NotificationPriority.CRITICAL,
            notify_initiator=True,
            notify_roles={"admin", "ops"},
            title_template="Critical Operation: {command_type}",
            message_template="Critical command {command_id} is {state}",
        ))

# backend/ops/recovery/failure_handler.py
"""
Failure Handler
===============

Handles command execution failures with:
- Partial failure handling
- Compensating actions
- Auto rollback
- Incident flagging

State Machine:
PENDING → RUNNING → DONE
        → FAILED → RECOVERING → ROLLED_BACK
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger("ops.recovery.failure_handler")


class FailureType(str, Enum):
    """Types of failures."""
    TIMEOUT = "timeout"
    NETWORK = "network"
    RESOURCE = "resource"
    VALIDATION = "validation"
    PERMISSION = "permission"
    DEPENDENCY = "dependency"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class RecoveryState(str, Enum):
    """State of recovery operation."""
    PENDING = "pending"
    ANALYZING = "analyzing"
    RECOVERING = "recovering"
    COMPENSATING = "compensating"
    ROLLING_BACK = "rolling_back"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ESCALATED = "escalated"


@dataclass
class FailureContext:
    """Context for a failure event."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    command_id: str = ""
    command_type: str = ""
    target: str = ""
    
    # Failure details
    failure_type: FailureType = FailureType.UNKNOWN
    error_message: str = ""
    error_code: Optional[str] = None
    stack_trace: Optional[str] = None
    
    # State before failure
    checkpoint_data: Dict[str, Any] = field(default_factory=dict)
    partial_results: Dict[str, Any] = field(default_factory=dict)
    
    # Recovery state
    recovery_state: RecoveryState = RecoveryState.PENDING
    recovery_attempts: int = 0
    max_recovery_attempts: int = 3
    
    # Compensation tracking
    compensating_actions: List[str] = field(default_factory=list)
    executed_compensations: List[str] = field(default_factory=list)
    
    # Timing
    failed_at: datetime = field(default_factory=datetime.utcnow)
    recovery_started_at: Optional[datetime] = None
    recovery_completed_at: Optional[datetime] = None
    
    # Metadata
    user_id: str = ""
    trace_id: str = ""


@dataclass
class RecoveryAction:
    """A recovery or compensation action."""
    id: str
    name: str
    description: str
    action_type: str  # retry, compensate, rollback, escalate
    handler: Callable[[FailureContext], Coroutine[Any, Any, bool]]
    priority: int = 0
    condition: Optional[Callable[[FailureContext], bool]] = None


@dataclass
class IncidentReport:
    """Report of an incident requiring attention."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    failure_id: str = ""
    severity: str = "medium"  # low, medium, high, critical
    title: str = ""
    description: str = ""
    affected_resources: List[str] = field(default_factory=list)
    recommended_actions: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    acknowledged: bool = False
    resolved: bool = False


class FailureHandler:
    """
    Handles failures with recovery and compensation.
    
    Features:
    - Automatic recovery attempts
    - Compensating transactions
    - Rollback support
    - Incident escalation
    """
    
    def __init__(self):
        # Recovery actions by failure type
        self._recovery_actions: Dict[FailureType, List[RecoveryAction]] = {}
        
        # Compensation handlers by command type
        self._compensation_handlers: Dict[str, Callable[[FailureContext], Coroutine[Any, Any, bool]]] = {}
        
        # Rollback handlers by command type
        self._rollback_handlers: Dict[str, Callable[[FailureContext], Coroutine[Any, Any, bool]]] = {}
        
        # Active failures
        self._active_failures: Dict[str, FailureContext] = {}
        
        # Incidents
        self._incidents: Dict[str, IncidentReport] = {}
        
        # Statistics
        self._stats = {
            "total_failures": 0,
            "recovered": 0,
            "compensated": 0,
            "rolled_back": 0,
            "escalated": 0,
        }
        
        # Register default actions
        self._register_default_actions()
    
    def register_recovery_action(
        self,
        failure_type: FailureType,
        action: RecoveryAction,
    ):
        """Register a recovery action for a failure type."""
        if failure_type not in self._recovery_actions:
            self._recovery_actions[failure_type] = []
        self._recovery_actions[failure_type].append(action)
        # Sort by priority
        self._recovery_actions[failure_type].sort(key=lambda a: -a.priority)
    
    def register_compensation(
        self,
        command_type: str,
        handler: Callable[[FailureContext], Coroutine[Any, Any, bool]],
    ):
        """Register a compensation handler for a command type."""
        self._compensation_handlers[command_type] = handler
    
    def register_rollback(
        self,
        command_type: str,
        handler: Callable[[FailureContext], Coroutine[Any, Any, bool]],
    ):
        """Register a rollback handler for a command type."""
        self._rollback_handlers[command_type] = handler
    
    async def handle_failure(
        self,
        command_id: str,
        command_type: str,
        target: str,
        error_message: str,
        error_code: Optional[str] = None,
        checkpoint_data: Optional[Dict[str, Any]] = None,
        partial_results: Optional[Dict[str, Any]] = None,
        user_id: str = "",
        trace_id: str = "",
    ) -> FailureContext:
        """
        Handle a command failure.
        
        Args:
            command_id: ID of the failed command
            command_type: Type of command
            target: Target resource
            error_message: Error message
            error_code: Error code
            checkpoint_data: State at failure point
            partial_results: Any partial results
            user_id: User who initiated command
            trace_id: Trace ID for correlation
            
        Returns:
            FailureContext with recovery status
        """
        self._stats["total_failures"] += 1
        
        # Classify failure
        failure_type = self._classify_failure(error_message, error_code)
        
        # Create context
        context = FailureContext(
            command_id=command_id,
            command_type=command_type,
            target=target,
            failure_type=failure_type,
            error_message=error_message,
            error_code=error_code,
            checkpoint_data=checkpoint_data or {},
            partial_results=partial_results or {},
            user_id=user_id,
            trace_id=trace_id,
        )
        
        self._active_failures[context.id] = context
        
        logger.warning(
            f"Handling failure {context.id} for command {command_id}: "
            f"type={failure_type}, error={error_message}"
        )
        
        # Attempt recovery
        context.recovery_state = RecoveryState.ANALYZING
        context.recovery_started_at = datetime.utcnow()
        
        recovered = await self._attempt_recovery(context)
        
        if recovered:
            context.recovery_state = RecoveryState.SUCCEEDED
            self._stats["recovered"] += 1
        else:
            # Try compensation
            compensated = await self._execute_compensation(context)
            
            if compensated:
                context.recovery_state = RecoveryState.SUCCEEDED
                self._stats["compensated"] += 1
            else:
                # Try rollback
                rolled_back = await self._execute_rollback(context)
                
                if rolled_back:
                    context.recovery_state = RecoveryState.SUCCEEDED
                    self._stats["rolled_back"] += 1
                else:
                    # Escalate
                    context.recovery_state = RecoveryState.ESCALATED
                    self._stats["escalated"] += 1
                    await self._escalate(context)
        
        context.recovery_completed_at = datetime.utcnow()
        return context
    
    async def manual_recover(self, failure_id: str, action: str) -> bool:
        """
        Manually trigger a recovery action.
        
        Args:
            failure_id: ID of the failure
            action: Action to take (retry, compensate, rollback, acknowledge)
            
        Returns:
            True if successful
        """
        context = self._active_failures.get(failure_id)
        if not context:
            return False
        
        if action == "retry":
            return await self._attempt_recovery(context)
        elif action == "compensate":
            return await self._execute_compensation(context)
        elif action == "rollback":
            return await self._execute_rollback(context)
        elif action == "acknowledge":
            context.recovery_state = RecoveryState.SUCCEEDED
            return True
        
        return False
    
    def get_active_failures(self) -> List[FailureContext]:
        """Get all active (unresolved) failures."""
        return [
            f for f in self._active_failures.values()
            if f.recovery_state not in [RecoveryState.SUCCEEDED, RecoveryState.FAILED]
        ]
    
    def get_failure(self, failure_id: str) -> Optional[FailureContext]:
        """Get a specific failure by ID."""
        return self._active_failures.get(failure_id)
    
    def get_incidents(self, unresolved_only: bool = True) -> List[IncidentReport]:
        """Get incident reports."""
        incidents = list(self._incidents.values())
        if unresolved_only:
            incidents = [i for i in incidents if not i.resolved]
        return sorted(incidents, key=lambda i: i.created_at, reverse=True)
    
    def acknowledge_incident(self, incident_id: str) -> bool:
        """Acknowledge an incident."""
        incident = self._incidents.get(incident_id)
        if incident:
            incident.acknowledged = True
            return True
        return False
    
    def resolve_incident(self, incident_id: str) -> bool:
        """Mark an incident as resolved."""
        incident = self._incidents.get(incident_id)
        if incident:
            incident.resolved = True
            return True
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get failure handling statistics."""
        return {
            **self._stats,
            "active_failures": len(self.get_active_failures()),
            "open_incidents": len(self.get_incidents(unresolved_only=True)),
        }
    
    def _classify_failure(
        self,
        error_message: str,
        error_code: Optional[str],
    ) -> FailureType:
        """Classify a failure based on error details."""
        message_lower = error_message.lower()
        
        if error_code == "TIMEOUT" or "timeout" in message_lower:
            return FailureType.TIMEOUT
        if "network" in message_lower or "connection" in message_lower:
            return FailureType.NETWORK
        if "resource" in message_lower or "not found" in message_lower:
            return FailureType.RESOURCE
        if "validation" in message_lower or "invalid" in message_lower:
            return FailureType.VALIDATION
        if "permission" in message_lower or "unauthorized" in message_lower:
            return FailureType.PERMISSION
        if "dependency" in message_lower or "service" in message_lower:
            return FailureType.DEPENDENCY
        if "partial" in message_lower:
            return FailureType.PARTIAL
        
        return FailureType.UNKNOWN
    
    async def _attempt_recovery(self, context: FailureContext) -> bool:
        """Attempt automatic recovery."""
        context.recovery_state = RecoveryState.RECOVERING
        
        # Get recovery actions for this failure type
        actions = self._recovery_actions.get(context.failure_type, [])
        
        for action in actions:
            # Check condition
            if action.condition and not action.condition(context):
                continue
            
            # Check retry limit
            if context.recovery_attempts >= context.max_recovery_attempts:
                logger.info(f"Max recovery attempts reached for {context.id}")
                break
            
            context.recovery_attempts += 1
            
            try:
                logger.info(f"Attempting recovery action: {action.name}")
                success = await action.handler(context)
                
                if success:
                    logger.info(f"Recovery succeeded with action: {action.name}")
                    return True
                    
            except Exception as e:
                logger.error(f"Recovery action {action.name} failed: {e}")
        
        return False
    
    async def _execute_compensation(self, context: FailureContext) -> bool:
        """Execute compensating actions."""
        context.recovery_state = RecoveryState.COMPENSATING
        
        handler = self._compensation_handlers.get(context.command_type)
        if not handler:
            logger.info(f"No compensation handler for {context.command_type}")
            return False
        
        try:
            logger.info(f"Executing compensation for {context.command_id}")
            success = await handler(context)
            
            if success:
                context.executed_compensations.append(context.command_type)
                logger.info(f"Compensation succeeded for {context.command_id}")
                return True
                
        except Exception as e:
            logger.error(f"Compensation failed: {e}")
        
        return False
    
    async def _execute_rollback(self, context: FailureContext) -> bool:
        """Execute rollback."""
        context.recovery_state = RecoveryState.ROLLING_BACK
        
        handler = self._rollback_handlers.get(context.command_type)
        if not handler:
            logger.info(f"No rollback handler for {context.command_type}")
            return False
        
        try:
            logger.info(f"Executing rollback for {context.command_id}")
            success = await handler(context)
            
            if success:
                logger.info(f"Rollback succeeded for {context.command_id}")
                return True
                
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
        
        return False
    
    async def _escalate(self, context: FailureContext):
        """Escalate failure as incident."""
        logger.warning(f"Escalating failure {context.id} as incident")
        
        # Determine severity
        severity = "medium"
        if context.failure_type == FailureType.PARTIAL:
            severity = "high"
        if context.recovery_attempts >= context.max_recovery_attempts:
            severity = "high"
        if "production" in context.target.lower():
            severity = "critical"
        
        incident = IncidentReport(
            failure_id=context.id,
            severity=severity,
            title=f"Failed: {context.command_type} on {context.target}",
            description=f"Command {context.command_id} failed after {context.recovery_attempts} recovery attempts. Error: {context.error_message}",
            affected_resources=[context.target],
            recommended_actions=[
                "Review error logs",
                "Check system health",
                "Manual intervention may be required",
            ],
        )
        
        self._incidents[incident.id] = incident
        logger.info(f"Created incident {incident.id} with severity {severity}")
    
    def _register_default_actions(self):
        """Register default recovery actions."""
        
        # Timeout retry
        async def timeout_retry(ctx: FailureContext) -> bool:
            # Simple retry for timeout - actual implementation would re-execute
            await asyncio.sleep(1)  # Wait before retry
            return False  # Placeholder
            
        self.register_recovery_action(
            FailureType.TIMEOUT,
            RecoveryAction(
                id="timeout_retry",
                name="Timeout Retry",
                description="Retry after timeout with backoff",
                action_type="retry",
                handler=timeout_retry,
                priority=100,
            )
        )
        
        # Network retry
        async def network_retry(ctx: FailureContext) -> bool:
            await asyncio.sleep(2)  # Wait for network
            return False  # Placeholder
            
        self.register_recovery_action(
            FailureType.NETWORK,
            RecoveryAction(
                id="network_retry",
                name="Network Retry",
                description="Retry after network error",
                action_type="retry",
                handler=network_retry,
                priority=100,
            )
        )

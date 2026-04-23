# backend/ops/command_engine/executor.py
"""
Command Executor
================

Executes commands with retry, timeout, and rollback support.

Features:
- Retry with exponential backoff
- Timeout handling
- Rollback/compensation
- Progress tracking
- Realtime event publishing
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional

from .models import (
    Command,
    CommandState,
    CommandResult,
    CommandType,
    RetryPolicy,
    TimeoutPolicy,
)

# Import event bus for realtime updates
try:
    from backend.api.routers.liveops.event_bus import (
        emit_event,
        publish_status,
        broadcast_progress,
        broadcast_command_done,
    )
    _EVENT_BUS_AVAILABLE = True
except ImportError:
    _EVENT_BUS_AVAILABLE = False

logger = logging.getLogger("ops.command_engine.executor")


@dataclass
class ExecutionContext:
    """Context for command execution."""
    command: Command
    attempt: int = 1
    started_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    cancelled: bool = False
    progress: float = 0.0
    checkpoints: List[str] = field(default_factory=list)


@dataclass
class ExecutionResult:
    """Result of command execution."""
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    error_code: Optional[str] = None
    duration_ms: int = 0
    rollback_info: Optional[Dict[str, Any]] = None


# Type aliases for handlers
ExecuteHandler = Callable[[Command, ExecutionContext], Coroutine[Any, Any, ExecutionResult]]
RollbackHandler = Callable[[Command, Dict[str, Any]], Coroutine[Any, Any, bool]]
ProgressCallback = Callable[[str, float], None]


class CommandExecutor:
    """
    Executes commands with full lifecycle management.
    
    Features:
    - Retry with configurable policy
    - Timeout handling
    - Rollback support
    - Progress tracking
    - Heartbeat monitoring
    """
    
    def __init__(
        self,
        retry_policy: Optional[RetryPolicy] = None,
        timeout_policy: Optional[TimeoutPolicy] = None,
    ):
        self._retry_policy = retry_policy or RetryPolicy()
        self._timeout_policy = timeout_policy or TimeoutPolicy()
        
        # Command handlers by type
        self._execute_handlers: Dict[CommandType, ExecuteHandler] = {}
        self._rollback_handlers: Dict[CommandType, RollbackHandler] = {}
        
        # Progress callbacks
        self._progress_callbacks: List[ProgressCallback] = []
        
        # Active executions
        self._active_contexts: Dict[str, ExecutionContext] = {}
        
        # Statistics
        self._total_executed = 0
        self._total_succeeded = 0
        self._total_failed = 0
        self._total_retried = 0
        self._total_rolled_back = 0
    
    def register_handler(
        self,
        command_type: CommandType,
        execute_handler: ExecuteHandler,
        rollback_handler: Optional[RollbackHandler] = None,
    ):
        """Register execute and optional rollback handlers for a command type."""
        self._execute_handlers[command_type] = execute_handler
        if rollback_handler:
            self._rollback_handlers[command_type] = rollback_handler
        logger.info(f"Registered executor for {command_type.value}")
    
    def add_progress_callback(self, callback: ProgressCallback):
        """Add a callback for progress updates."""
        self._progress_callbacks.append(callback)
    
    async def execute(self, command: Command) -> CommandResult:
        """
        Execute a command with retry and rollback support.
        
        Args:
            command: Command to execute
            
        Returns:
            CommandResult with execution outcome
        """
        self._total_executed += 1
        start_time = time.time()
        
        # Create execution context
        context = ExecutionContext(command=command)
        self._active_contexts[command.id] = context
        
        try:
            # Get handler
            cmd_type = CommandType(command.type) if isinstance(command.type, str) else command.type
            handler = self._execute_handlers.get(cmd_type)
            
            if not handler:
                return CommandResult(
                    command_id=command.id,
                    state=CommandState.FAILED,
                    success=False,
                    error=f"No executor registered for {cmd_type}",
                    error_code="NO_EXECUTOR",
                )
            
            # Execute with retry
            result = await self._execute_with_retry(command, context, handler)
            
            # Calculate duration
            duration_ms = int((time.time() - start_time) * 1000)
            
            if result.success:
                self._total_succeeded += 1
                cmd_result = CommandResult(
                    command_id=command.id,
                    state=CommandState.DONE,
                    success=True,
                    data=result.data,
                    duration_ms=duration_ms,
                    started_at=datetime.fromtimestamp(context.started_at),
                    completed_at=datetime.utcnow(),
                    rollback_available=result.rollback_info is not None,
                )
                
                # Publish completion event
                if _EVENT_BUS_AVAILABLE:
                    try:
                        await publish_status(
                            emit_event(
                                "COMMAND_DONE",
                                {"command_id": command.id, "success": True, "result": result.data},
                                module="ops",
                            )
                        )
                    except Exception as e:
                        logger.debug(f"Event bus publish error: {e}")
                
                return cmd_result
            else:
                self._total_failed += 1
                
                # Attempt rollback if available
                rolled_back = False
                if result.rollback_info and cmd_type in self._rollback_handlers:
                    rolled_back = await self._execute_rollback(command, result.rollback_info)
                
                cmd_result = CommandResult(
                    command_id=command.id,
                    state=CommandState.ROLLED_BACK if rolled_back else CommandState.FAILED,
                    success=False,
                    error=result.error,
                    error_code=result.error_code,
                    duration_ms=duration_ms,
                    started_at=datetime.fromtimestamp(context.started_at),
                    completed_at=datetime.utcnow(),
                )
                
                # Publish failure event
                if _EVENT_BUS_AVAILABLE:
                    try:
                        await publish_status(
                            emit_event(
                                "COMMAND_DONE",
                                {"command_id": command.id, "success": False, "error": result.error},
                                module="ops",
                            )
                        )
                    except Exception as e:
                        logger.debug(f"Event bus publish error: {e}")
                
                return cmd_result
                
        finally:
            self._active_contexts.pop(command.id, None)
    
    async def cancel(self, command_id: str) -> bool:
        """
        Cancel an executing command.
        
        Args:
            command_id: ID of command to cancel
            
        Returns:
            True if found and marked for cancellation
        """
        if command_id in self._active_contexts:
            self._active_contexts[command_id].cancelled = True
            return True
        return False
    
    def update_progress(self, command_id: str, progress: float, checkpoint: Optional[str] = None):
        """Update execution progress for a command."""
        if command_id in self._active_contexts:
            ctx = self._active_contexts[command_id]
            ctx.progress = min(1.0, max(0.0, progress))
            if checkpoint:
                ctx.checkpoints.append(checkpoint)
            
            # Notify callbacks
            for callback in self._progress_callbacks:
                try:
                    callback(command_id, ctx.progress)
                except Exception as e:
                    logger.error(f"Progress callback error: {e}")
            
            # Publish to event bus for realtime updates
            if _EVENT_BUS_AVAILABLE:
                try:
                    asyncio.create_task(
                        publish_status(
                            emit_event(
                                "EXEC_PROGRESS",
                                {
                                    "command_id": command_id,
                                    "progress": ctx.progress,
                                    "checkpoint": checkpoint,
                                },
                                module="ops",
                            )
                        )
                    )
                except Exception as e:
                    logger.debug(f"Event bus publish error: {e}")
    
    def heartbeat(self, command_id: str):
        """Record a heartbeat for an executing command."""
        if command_id in self._active_contexts:
            self._active_contexts[command_id].last_heartbeat = time.time()
    
    def get_stats(self) -> Dict[str, int]:
        """Get executor statistics."""
        return {
            "total_executed": self._total_executed,
            "total_succeeded": self._total_succeeded,
            "total_failed": self._total_failed,
            "total_retried": self._total_retried,
            "total_rolled_back": self._total_rolled_back,
            "active_executions": len(self._active_contexts),
        }
    
    async def _execute_with_retry(
        self,
        command: Command,
        context: ExecutionContext,
        handler: ExecuteHandler,
    ) -> ExecutionResult:
        """Execute with retry on failure."""
        last_error: Optional[str] = None
        last_error_code: Optional[str] = None
        
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            context.attempt = attempt
            
            # Check cancellation
            if context.cancelled:
                return ExecutionResult(
                    success=False,
                    error="Command cancelled",
                    error_code="CANCELLED",
                )
            
            try:
                # Execute with timeout
                result = await asyncio.wait_for(
                    handler(command, context),
                    timeout=self._timeout_policy.execution_timeout_ms / 1000,
                )
                
                if result.success:
                    return result
                
                # Check if error is retryable
                if result.error_code not in self._retry_policy.retryable_errors:
                    return result
                
                last_error = result.error
                last_error_code = result.error_code
                
            except asyncio.TimeoutError:
                last_error = "Execution timeout"
                last_error_code = "TIMEOUT"
                
            except Exception as e:
                last_error = str(e)
                last_error_code = "EXECUTION_ERROR"
            
            # Check if should retry
            if attempt < self._retry_policy.max_attempts:
                self._total_retried += 1
                
                # Calculate backoff delay
                delay_ms = min(
                    self._retry_policy.base_delay_ms * (
                        self._retry_policy.exponential_base ** (attempt - 1)
                    ),
                    self._retry_policy.max_delay_ms,
                )
                
                logger.info(
                    f"Retrying command {command.id}, attempt {attempt + 1}, "
                    f"delay {delay_ms}ms"
                )
                
                await asyncio.sleep(delay_ms / 1000)
        
        return ExecutionResult(
            success=False,
            error=last_error or "Max retries exceeded",
            error_code=last_error_code or "MAX_RETRIES",
        )
    
    async def _execute_rollback(
        self,
        command: Command,
        rollback_info: Dict[str, Any],
    ) -> bool:
        """Execute rollback for a failed command."""
        cmd_type = CommandType(command.type) if isinstance(command.type, str) else command.type
        handler = self._rollback_handlers.get(cmd_type)
        
        if not handler:
            return False
        
        try:
            success = await handler(command, rollback_info)
            if success:
                self._total_rolled_back += 1
            return success
        except Exception as e:
            logger.error(f"Rollback failed for {command.id}: {e}", exc_info=True)
            return False


# ==============================================================================
# Built-in Handlers
# ==============================================================================

async def dry_run_handler(command: Command, context: ExecutionContext) -> ExecutionResult:
    """Handler for dry-run mode - simulates execution without side effects."""
    logger.info(f"DRY RUN: Would execute {command.type} on {command.target}")
    
    # Simulate some processing time
    await asyncio.sleep(0.1)
    
    return ExecutionResult(
        success=True,
        data={
            "dry_run": True,
            "command_type": command.type,
            "target": command.target,
            "params": command.params,
            "would_execute": True,
        },
    )


def create_simple_handler(
    action: Callable[[Command], Coroutine[Any, Any, Dict[str, Any]]],
) -> ExecuteHandler:
    """Create a simple handler from an async action function."""
    
    async def handler(command: Command, context: ExecutionContext) -> ExecutionResult:
        try:
            data = await action(command)
            return ExecutionResult(success=True, data=data)
        except Exception as e:
            return ExecutionResult(
                success=False,
                error=str(e),
                error_code="ACTION_ERROR",
            )
    
    return handler

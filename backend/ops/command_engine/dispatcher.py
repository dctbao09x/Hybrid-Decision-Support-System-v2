# backend/ops/command_engine/dispatcher.py
"""
Command Dispatcher
==================

Routes commands to appropriate executors and manages the command queue.

Features:
- Priority queue
- Concurrent execution limits
- Deadlock prevention
- Circuit breaker
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Coroutine, Dict, List, Optional, Any
from datetime import datetime

from .models import Command, CommandState, CommandPriority, CommandResult, CommandType

logger = logging.getLogger("ops.command_engine.dispatcher")


@dataclass
class QueuedCommand:
    """Command wrapper with queue metadata."""
    command: Command
    queued_at: float = field(default_factory=time.time)
    priority_score: float = 0.0


@dataclass
class DispatcherStats:
    """Dispatcher statistics."""
    total_queued: int = 0
    total_dispatched: int = 0
    total_completed: int = 0
    total_failed: int = 0
    total_timeout: int = 0
    avg_queue_time_ms: float = 0.0
    avg_execution_time_ms: float = 0.0
    current_queue_size: int = 0
    active_executions: int = 0


class CommandDispatcher:
    """
    Dispatches commands to executors.
    
    Features:
    - Priority-based queue
    - Concurrent execution limits
    - Module-based routing
    - Circuit breaker pattern
    """
    
    def __init__(
        self,
        max_concurrent: int = 10,
        queue_timeout_ms: int = 60000,
        max_queue_size: int = 5000,
        drop_policy: str = "reject_new",
        storage_path: str = "storage/liveops_queue.db",
    ):
        self._max_concurrent = max_concurrent
        self._queue_timeout_ms = queue_timeout_ms
        self._max_queue_size = max_queue_size
        self._drop_policy = drop_policy
        self._storage_path = Path(storage_path)
        
        # Priority queues (higher priority first)
        self._queues: Dict[CommandPriority, deque[QueuedCommand]] = {
            CommandPriority.CRITICAL: deque(),
            CommandPriority.HIGH: deque(),
            CommandPriority.NORMAL: deque(),
            CommandPriority.LOW: deque(),
        }
        
        # Active commands
        self._active: Dict[str, Command] = {}
        self._active_lock = asyncio.Lock()
        
        # Command handlers by type
        self._handlers: Dict[CommandType, Callable[[Command], Coroutine[Any, Any, CommandResult]]] = {}
        
        # Default handler
        self._default_handler: Optional[Callable[[Command], Coroutine[Any, Any, CommandResult]]] = None
        
        # Statistics
        self._stats = DispatcherStats()
        self._queue_times: List[float] = []
        self._execution_times: List[float] = []
        
        # Circuit breaker
        self._circuit_failures: Dict[str, int] = {}  # module -> failure count
        self._circuit_open: Dict[str, float] = {}  # module -> opened_at
        self._circuit_threshold = 5
        self._circuit_reset_ms = 30000
        
        # Running flag
        self._running = False
        self._dispatch_task: Optional[asyncio.Task] = None

        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self._storage_path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS command_queue (
                id TEXT PRIMARY KEY,
                priority TEXT NOT NULL,
                queued_at REAL NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        self._db.commit()
        self._load_persisted_queue()
    
    def register_handler(
        self,
        command_type: CommandType,
        handler: Callable[[Command], Coroutine[Any, Any, CommandResult]],
    ):
        """Register a handler for a command type."""
        self._handlers[command_type] = handler
        logger.info(f"Registered handler for {command_type.value}")
    
    def set_default_handler(
        self,
        handler: Callable[[Command], Coroutine[Any, Any, CommandResult]],
    ):
        """Set the default handler for unregistered command types."""
        self._default_handler = handler
    
    async def enqueue(self, command: Command) -> bool:
        """
        Add a command to the dispatch queue.
        
        Args:
            command: Command to enqueue
            
        Returns:
            True if successfully queued
        """
        # Check circuit breaker
        module = self._get_module(command.type)
        if self._is_circuit_open(module):
            logger.warning(f"Circuit open for module {module}, rejecting command {command.id}")
            return False

        total = self._get_total_queue_size()
        if total >= self._max_queue_size:
            if self._drop_policy == "drop_low_priority":
                dropped = self._drop_one_low_priority()
                if not dropped:
                    logger.warning("Queue full and unable to drop command, rejecting new command")
                    return False
            else:
                logger.warning("Queue full, rejecting new command due to backpressure")
                return False
        
        # Calculate priority score
        priority_score = self._calculate_priority_score(command)
        
        queued = QueuedCommand(
            command=command,
            queued_at=time.time(),
            priority_score=priority_score,
        )
        
        # Add to appropriate queue
        priority = CommandPriority(command.priority) if isinstance(command.priority, str) else command.priority
        self._queues[priority].append(queued)
        self._persist_enqueue(queued)
        
        # Update stats
        self._stats.total_queued += 1
        self._stats.current_queue_size = self._get_total_queue_size()
        
        logger.debug(f"Enqueued command {command.id} with priority {priority}")
        return True
    
    async def start(self):
        """Start the dispatcher loop."""
        if self._running:
            return
            
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        logger.info("Command dispatcher started")
    
    async def stop(self):
        """Stop the dispatcher."""
        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        logger.info("Command dispatcher stopped")
    
    async def dispatch_immediate(self, command: Command) -> CommandResult:
        """
        Dispatch a command immediately, bypassing the queue.
        
        Args:
            command: Command to execute
            
        Returns:
            CommandResult from execution
        """
        return await self._execute_command(command)
    
    def get_stats(self) -> DispatcherStats:
        """Get dispatcher statistics."""
        self._stats.current_queue_size = self._get_total_queue_size()
        self._stats.active_executions = len(self._active)
        
        if self._queue_times:
            self._stats.avg_queue_time_ms = sum(self._queue_times[-100:]) / len(self._queue_times[-100:])
        if self._execution_times:
            self._stats.avg_execution_time_ms = sum(self._execution_times[-100:]) / len(self._execution_times[-100:])
        
        return self._stats
    
    def get_active_commands(self) -> List[Command]:
        """Get currently executing commands."""
        return list(self._active.values())
    
    def get_queued_commands(self) -> List[Command]:
        """Get all queued commands."""
        commands = []
        for queue in self._queues.values():
            commands.extend([qc.command for qc in queue])
        return commands
    
    async def cancel_command(self, command_id: str) -> bool:
        """
        Cancel a queued or running command.
        
        Args:
            command_id: ID of command to cancel
            
        Returns:
            True if found and cancelled
        """
        # Check queues
        for queue in self._queues.values():
            for qc in list(queue):
                if qc.command.id == command_id:
                    queue.remove(qc)
                    qc.command.state = CommandState.CANCELLED
                    self._persist_remove(qc.command.id)
                    logger.info(f"Cancelled queued command {command_id}")
                    return True
        
        # Check active (can't cancel, but mark for cancellation)
        async with self._active_lock:
            if command_id in self._active:
                self._active[command_id].state = CommandState.CANCELLED
                logger.info(f"Marked active command {command_id} for cancellation")
                return True
        
        return False
    
    async def _dispatch_loop(self):
        """Main dispatch loop."""
        while self._running:
            try:
                # Check for available capacity
                async with self._active_lock:
                    available = self._max_concurrent - len(self._active)
                
                if available > 0:
                    # Get next command from highest priority queue
                    command = self._dequeue_next()
                    if command:
                        # Execute in background
                        asyncio.create_task(self._execute_and_track(command))
                
                # Check for queue timeouts
                await self._check_queue_timeouts()
                
                # Small delay to prevent busy loop
                await asyncio.sleep(0.05)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Dispatch loop error: {e}", exc_info=True)
                await asyncio.sleep(1)
    
    def _dequeue_next(self) -> Optional[Command]:
        """Get next command from queues (priority order)."""
        for priority in [
            CommandPriority.CRITICAL,
            CommandPriority.HIGH,
            CommandPriority.NORMAL,
            CommandPriority.LOW,
        ]:
            queue = self._queues[priority]
            if queue:
                queued = queue.popleft()
                self._persist_remove(queued.command.id)
                
                # Record queue time
                queue_time = (time.time() - queued.queued_at) * 1000
                self._queue_times.append(queue_time)
                
                return queued.command
        
        return None
    
    async def _execute_and_track(self, command: Command):
        """Execute a command and track its state."""
        # Add to active
        async with self._active_lock:
            self._active[command.id] = command
        
        try:
            command.state = CommandState.RUNNING
            command.started_at = datetime.utcnow()
            
            start_time = time.time()
            result = await self._execute_command(command)
            execution_time = (time.time() - start_time) * 1000
            
            # Record execution time
            self._execution_times.append(execution_time)
            
            # Update stats
            self._stats.total_dispatched += 1
            if result.success:
                self._stats.total_completed += 1
                self._record_success(command)
            else:
                self._stats.total_failed += 1
                self._record_failure(command)
            
            return result
            
        except asyncio.TimeoutError:
            self._stats.total_timeout += 1
            command.state = CommandState.TIMEOUT
            self._record_failure(command)
            raise
            
        finally:
            # Remove from active
            async with self._active_lock:
                self._active.pop(command.id, None)
    
    async def _execute_command(self, command: Command) -> CommandResult:
        """Execute a command using the appropriate handler."""
        cmd_type = CommandType(command.type) if isinstance(command.type, str) else command.type
        
        handler = self._handlers.get(cmd_type, self._default_handler)
        
        if not handler:
            logger.error(f"No handler for command type {cmd_type}")
            return CommandResult(
                command_id=command.id,
                state=CommandState.FAILED,
                success=False,
                error=f"No handler for command type: {cmd_type}",
                error_code="NO_HANDLER",
            )
        
        try:
            # Apply timeout
            result = await asyncio.wait_for(
                handler(command),
                timeout=command.timeout_seconds,
            )
            command.state = result.state
            command.completed_at = datetime.utcnow()
            return result
            
        except asyncio.TimeoutError:
            command.state = CommandState.TIMEOUT
            command.completed_at = datetime.utcnow()
            return CommandResult(
                command_id=command.id,
                state=CommandState.TIMEOUT,
                success=False,
                error="Command execution timeout",
                error_code="TIMEOUT",
            )
        except Exception as e:
            command.state = CommandState.FAILED
            command.completed_at = datetime.utcnow()
            logger.error(f"Command {command.id} execution error: {e}", exc_info=True)
            return CommandResult(
                command_id=command.id,
                state=CommandState.FAILED,
                success=False,
                error=str(e),
                error_code="EXECUTION_ERROR",
            )
    
    async def _check_queue_timeouts(self):
        """Check for and handle queue timeouts."""
        now = time.time()
        timeout_threshold = self._queue_timeout_ms / 1000
        
        for queue in self._queues.values():
            timed_out = []
            for qc in list(queue):
                if now - qc.queued_at > timeout_threshold:
                    timed_out.append(qc)
            
            for qc in timed_out:
                queue.remove(qc)
                qc.command.state = CommandState.TIMEOUT
                self._persist_remove(qc.command.id)
                logger.warning(f"Command {qc.command.id} timed out in queue")
                self._stats.total_timeout += 1
    
    def _calculate_priority_score(self, command: Command) -> float:
        """Calculate a priority score for queue ordering."""
        base_scores = {
            CommandPriority.CRITICAL: 1000,
            CommandPriority.HIGH: 100,
            CommandPriority.NORMAL: 10,
            CommandPriority.LOW: 1,
        }
        
        priority = CommandPriority(command.priority) if isinstance(command.priority, str) else command.priority
        return base_scores.get(priority, 10)
    
    def _get_module(self, command_type: CommandType) -> str:
        """Get module name from command type."""
        type_str = command_type.value if isinstance(command_type, CommandType) else command_type
        return type_str.split("_")[0]
    
    def _is_circuit_open(self, module: str) -> bool:
        """Check if circuit breaker is open for a module."""
        if module not in self._circuit_open:
            return False
        
        elapsed = (time.time() - self._circuit_open[module]) * 1000
        if elapsed > self._circuit_reset_ms:
            # Reset circuit
            del self._circuit_open[module]
            self._circuit_failures[module] = 0
            return False
        
        return True
    
    def _record_failure(self, command: Command):
        """Record a failure for circuit breaker."""
        module = self._get_module(command.type)
        self._circuit_failures[module] = self._circuit_failures.get(module, 0) + 1
        
        if self._circuit_failures[module] >= self._circuit_threshold:
            self._circuit_open[module] = time.time()
            logger.warning(f"Circuit breaker opened for module {module}")
    
    def _record_success(self, command: Command):
        """Record a success for circuit breaker."""
        module = self._get_module(command.type)
        self._circuit_failures[module] = 0
    
    def _get_total_queue_size(self) -> int:
        """Get total size of all queues."""
        return sum(len(q) for q in self._queues.values())

    def _persist_enqueue(self, queued: QueuedCommand) -> None:
        command = queued.command
        payload = command.model_dump() if hasattr(command, "model_dump") else command.dict()
        self._db.execute(
            "INSERT OR REPLACE INTO command_queue (id, priority, queued_at, payload) VALUES (?, ?, ?, ?)",
            (
                command.id,
                str(command.priority if isinstance(command.priority, str) else command.priority.value),
                queued.queued_at,
                json.dumps(payload),
            ),
        )
        self._db.commit()

    def _persist_remove(self, command_id: str) -> None:
        self._db.execute("DELETE FROM command_queue WHERE id = ?", (command_id,))
        self._db.commit()

    def _load_persisted_queue(self) -> None:
        rows = self._db.execute(
            "SELECT priority, queued_at, payload FROM command_queue ORDER BY queued_at ASC"
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row[2])
                command = Command(**payload)
                priority = CommandPriority(str(row[0]))
                self._queues[priority].append(
                    QueuedCommand(command=command, queued_at=float(row[1]), priority_score=self._calculate_priority_score(command))
                )
            except Exception as exc:
                logger.error(f"Failed to load persisted command row: {exc}")

    def _drop_one_low_priority(self) -> bool:
        for priority in [CommandPriority.LOW, CommandPriority.NORMAL, CommandPriority.HIGH]:
            queue = self._queues[priority]
            if queue:
                dropped = queue.popleft()
                self._persist_remove(dropped.command.id)
                logger.warning(f"Dropped queued command {dropped.command.id} due to backpressure")
                return True
        return False

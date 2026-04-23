# backend/ops/command_engine/engine.py
"""
Command Engine
==============

Main orchestrator for the command execution pipeline.

Pipeline: UI → Validation → RBAC → Queue → Executor → Audit → Feedback
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional

from .models import Command, CommandResult, CommandState, CommandType
from .validator import CommandValidator, ValidationResult
from .dispatcher import CommandDispatcher
from .executor import CommandExecutor, ExecutionContext, ExecutionResult, dry_run_handler
from .audit import CommandAudit, AuditEntry
from .notifier import CommandNotifier
from backend.ops.governance.safety_policy import PolicyAction, SafetyPolicyEngine
from backend.ops.governance.approval_workflow import ApprovalStatus, ApprovalWorkflow

logger = logging.getLogger("ops.command_engine")


class CommandEngine:
    """
    Orchestrates the complete command execution pipeline.
    
    Pipeline stages:
    1. Validation - Parameter and schema validation
    2. RBAC - Permission verification
    3. Queue - Priority-based queuing
    4. Execution - Actual command execution
    5. Audit - Logging and traceability
    6. Notification - Status updates
    """
    
    def __init__(
        self,
        audit_log_dir: str = "logs/admin_ops",
        max_concurrent: int = 10,
    ):
        # Initialize components
        self._validator = CommandValidator()
        self._dispatcher = CommandDispatcher(max_concurrent=max_concurrent)
        self._executor = CommandExecutor()
        self._audit = CommandAudit(log_dir=audit_log_dir)
        self._notifier = CommandNotifier()
        self._safety_policy = SafetyPolicyEngine()
        self._approval_workflow = ApprovalWorkflow()
        
        # RBAC checker (can be replaced with actual implementation)
        self._rbac_checker: Optional[Callable[[str, str, str], Coroutine[Any, Any, bool]]] = None
        
        # Command registry - maps command types to their handlers
        self._command_registry: Dict[CommandType, Dict[str, Any]] = {}
        self._commands: Dict[str, Command] = {}
        self._pending_approval_by_command: Dict[str, str] = {}
        
        # Running state
        self._running = False
        
        # Wire up executor to dispatcher
        self._setup_dispatcher_handlers()
    
    async def start(self):
        """Start the command engine."""
        if self._running:
            return
            
        self._running = True
        await self._dispatcher.start()
        await self._notifier.start()
        logger.info("Command engine started")
    
    async def stop(self):
        """Stop the command engine."""
        self._running = False
        await self._dispatcher.stop()
        await self._notifier.stop()
        logger.info("Command engine stopped")
    
    def set_rbac_checker(
        self,
        checker: Callable[[str, str, str], Coroutine[Any, Any, bool]],
    ):
        """
        Set the RBAC checker function.
        
        Args:
            checker: Async function(user_id, role, action) -> bool
        """
        self._rbac_checker = checker
    
    def register_command(
        self,
        command_type: CommandType,
        handler: Callable[[Command, ExecutionContext], Coroutine[Any, Any, ExecutionResult]],
        rollback_handler: Optional[Callable[[Command, Dict[str, Any]], Coroutine[Any, Any, bool]]] = None,
        required_permission: Optional[str] = None,
        approval_required: bool = False,
    ):
        """
        Register a command type with its handler.
        
        Args:
            command_type: Type of command
            handler: Async handler function
            rollback_handler: Optional rollback handler
            required_permission: Permission required to execute
            approval_required: Whether approval is needed
        """
        self._command_registry[command_type] = {
            "handler": handler,
            "rollback_handler": rollback_handler,
            "required_permission": required_permission,
            "approval_required": approval_required,
        }
        
        # Register with executor
        self._executor.register_handler(command_type, handler, rollback_handler)
        
        logger.info(f"Registered command type: {command_type.value}")
    
    async def submit(
        self,
        command: Command,
        ip_address: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> CommandResult:
        """
        Submit a command for execution.
        
        Pipeline:
        1. Validate command
        2. Check RBAC permissions
        3. Log audit entry
        4. Queue for execution
        5. Return immediate result (pending)
        
        Args:
            command: Command to execute
            ip_address: Client IP for audit
            session_id: Session ID for audit
            
        Returns:
            CommandResult with pending state
        """
        # Step 1: Validate
        validation = self._validator.validate(command)
        if not validation.valid:
            return CommandResult(
                command_id=command.id,
                state=CommandState.FAILED,
                success=False,
                error="; ".join(validation.errors),
                error_code="VALIDATION_ERROR",
            )
        
        # Apply sanitized params
        command.params = validation.sanitized_params
        
        # Step 2: RBAC check
        if self._rbac_checker:
            cmd_type = command.type if isinstance(command.type, str) else command.type.value
            has_permission = await self._rbac_checker(
                command.user_id,
                command.role,
                cmd_type,
            )
            if not has_permission:
                return CommandResult(
                    command_id=command.id,
                    state=CommandState.FAILED,
                    success=False,
                    error=f"Permission denied for action: {cmd_type}",
                    error_code="PERMISSION_DENIED",
                )

        cmd_type_enum = CommandType(command.type) if isinstance(command.type, str) else command.type
        cmd_type = cmd_type_enum.value if isinstance(cmd_type_enum, CommandType) else str(cmd_type_enum)

        policy_result = self._safety_policy.check(
            user_id=command.user_id,
            role=command.role,
            command_type=cmd_type,
            target=command.target,
            environment=command.environment,
        )
        if not policy_result.allowed:
            return CommandResult(
                command_id=command.id,
                state=CommandState.FAILED,
                success=False,
                error="; ".join(v.reason for v in policy_result.violations) or "Safety policy denied",
                error_code="POLICY_DENIED",
            )
        
        # Step 3: Check approval requirement
        registry_entry = self._command_registry.get(cmd_type_enum, {})
        approval_required = registry_entry.get("approval_required") or policy_result.action == PolicyAction.REQUIRE_APPROVAL
        if approval_required and not command.dry_run:
            req = self._approval_workflow.submit(
                command_id=command.id,
                command_type=cmd_type,
                target=command.target,
                requester_id=command.user_id,
                requester_role=command.role,
                required_approvers=max(1, policy_result.required_approvers or 1),
                allowed_approver_roles=["admin"],
                reason=command.params.get("reason") if isinstance(command.params, dict) else None,
                params=command.params,
            )
            self._pending_approval_by_command[command.id] = req.id
            self._commands[command.id] = command
            command.state = CommandState.AWAITING_APPROVAL
            self._audit.log_command_state_change(
                command=command,
                from_state=CommandState.VALIDATING,
                to_state=CommandState.AWAITING_APPROVAL,
                reason="Approval required by policy",
            )
            return CommandResult(
                command_id=command.id,
                state=CommandState.AWAITING_APPROVAL,
                success=True,
                data={
                    "approval_request_id": req.id,
                    "required_approvers": req.required_approvers,
                    "status": req.status.value if hasattr(req.status, "value") else str(req.status),
                },
            )
        
        # Step 4: Log audit entry
        self._audit.log_command_initiated(
            command=command,
            ip_address=ip_address,
            session_id=session_id,
        )
        self._commands[command.id] = command
        
        # Step 5: Handle dry-run
        if command.dry_run:
            return await self._execute_dry_run(command)
        
        # Step 6: Queue for execution
        command.state = CommandState.QUEUED
        queued = await self._dispatcher.enqueue(command)
        
        if not queued:
            return CommandResult(
                command_id=command.id,
                state=CommandState.FAILED,
                success=False,
                error="Failed to queue command (circuit open or queue full)",
                error_code="QUEUE_ERROR",
            )

        self._safety_policy.record_execution(command.user_id, cmd_type)
        
        # Return pending result
        return CommandResult(
            command_id=command.id,
            state=CommandState.QUEUED,
            success=True,
            data={
                "message": "Command queued for execution",
                "queue_position": self._dispatcher.get_stats().current_queue_size,
            },
        )
    
    async def execute_immediate(
        self,
        command: Command,
        ip_address: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> CommandResult:
        """
        Execute a command immediately (bypass queue).
        
        Args:
            command: Command to execute
            ip_address: Client IP for audit
            session_id: Session ID for audit
            
        Returns:
            CommandResult with execution outcome
        """
        # Validate
        validation = self._validator.validate(command)
        if not validation.valid:
            return CommandResult(
                command_id=command.id,
                state=CommandState.FAILED,
                success=False,
                error="; ".join(validation.errors),
                error_code="VALIDATION_ERROR",
            )
        
        command.params = validation.sanitized_params
        
        # RBAC check
        if self._rbac_checker:
            cmd_type = command.type if isinstance(command.type, str) else command.type.value
            has_permission = await self._rbac_checker(
                command.user_id,
                command.role,
                cmd_type,
            )
            if not has_permission:
                return CommandResult(
                    command_id=command.id,
                    state=CommandState.FAILED,
                    success=False,
                    error=f"Permission denied for action: {cmd_type}",
                    error_code="PERMISSION_DENIED",
                )
        
        # Log audit
        self._audit.log_command_initiated(
            command=command,
            ip_address=ip_address,
            session_id=session_id,
        )
        self._commands[command.id] = command
        
        # Execute
        if command.dry_run:
            result = await self._execute_dry_run(command)
        else:
            result = await self._executor.execute(command)
        
        # Log completion
        self._audit.log_command_completed(command, result)
        
        # Notify
        await self._notifier.notify_command_state(
            command=command,
            state=result.state,
            result=result,
        )
        
        return result

    async def list_commands(self, limit: int = 50) -> List[CommandResult]:
        """List active/queued/recent commands."""
        results: List[CommandResult] = []

        active = self._dispatcher.get_active_commands()
        for cmd in active:
            results.append(
                CommandResult(
                    command_id=cmd.id,
                    state=cmd.state,
                    success=True,
                    data={"progress": cmd.progress, "target": cmd.target, "type": cmd.type},
                )
            )

        queued = self._dispatcher.get_queued_commands()
        for idx, cmd in enumerate(queued):
            results.append(
                CommandResult(
                    command_id=cmd.id,
                    state=CommandState.QUEUED,
                    success=True,
                    data={"position": idx + 1, "target": cmd.target, "type": cmd.type},
                )
            )

        for command_id in self._pending_approval_by_command.keys():
            cmd = self._commands.get(command_id)
            if cmd:
                results.append(
                    CommandResult(
                        command_id=cmd.id,
                        state=CommandState.AWAITING_APPROVAL,
                        success=True,
                        data={"target": cmd.target, "type": cmd.type},
                    )
                )

        if len(results) < limit:
            entries = self._audit.query(limit=limit)
            seen = {item.command_id for item in results}
            for entry in entries:
                if not entry.command_id or entry.command_id in seen or entry.action != "command_completed":
                    continue
                results.append(
                    CommandResult(
                        command_id=entry.command_id,
                        state=CommandState(entry.metadata.get("state", "done")),
                        success=entry.result == "success",
                        error=entry.error,
                        data={"target": entry.target, "type": entry.command_type},
                    )
                )
                if len(results) >= limit:
                    break

        return results[:limit]

    async def approve_command(
        self,
        command_id: str,
        approver_id: str,
        approver_role: str,
        comment: Optional[str] = None,
    ) -> Optional[CommandResult]:
        """Approve a pending command and enqueue when approval threshold met."""
        request_id = self._pending_approval_by_command.get(command_id)
        if not request_id:
            return None

        try:
            req = self._approval_workflow.approve(
                request_id=request_id,
                approver_id=approver_id,
                approver_role=approver_role,
                comment=comment,
            )
        except ValueError as exc:
            return CommandResult(
                command_id=command_id,
                state=CommandState.AWAITING_APPROVAL,
                success=False,
                error=str(exc),
                error_code="APPROVAL_ERROR",
            )

        if req.status != ApprovalStatus.APPROVED:
            return CommandResult(
                command_id=command_id,
                state=CommandState.AWAITING_APPROVAL,
                success=True,
                data={
                    "approval_request_id": req.id,
                    "approvals": req.approval_count,
                    "required": req.required_approvers,
                },
            )

        command = self._commands.get(command_id)
        if not command:
            return CommandResult(
                command_id=command_id,
                state=CommandState.FAILED,
                success=False,
                error="Command record missing",
                error_code="COMMAND_MISSING",
            )

        command.state = CommandState.QUEUED
        queued = await self._dispatcher.enqueue(command)
        if not queued:
            return CommandResult(
                command_id=command.id,
                state=CommandState.FAILED,
                success=False,
                error="Failed to queue after approval",
                error_code="QUEUE_ERROR",
            )

        del self._pending_approval_by_command[command_id]
        self._audit.log_action(
            user_id=approver_id,
            role=approver_role,
            action="command_approved",
            target=command_id,
            target_type="command",
            result="success",
            metadata={"approval_request_id": req.id},
        )
        return CommandResult(
            command_id=command.id,
            state=CommandState.QUEUED,
            success=True,
            data={"message": "Command approved and queued", "approval_request_id": req.id},
        )
    
    async def get_command_status(self, command_id: str) -> Optional[CommandResult]:
        """Get the status of a command."""
        # Check active commands
        active = self._dispatcher.get_active_commands()
        for cmd in active:
            if cmd.id == command_id:
                return CommandResult(
                    command_id=command_id,
                    state=cmd.state,
                    success=True,
                    data={"progress": cmd.progress},
                )
        
        # Check queued
        queued = self._dispatcher.get_queued_commands()
        for cmd in queued:
            if cmd.id == command_id:
                return CommandResult(
                    command_id=command_id,
                    state=CommandState.QUEUED,
                    success=True,
                    data={"position": queued.index(cmd) + 1},
                )
        
        # Check audit log
        entries = self._audit.query(limit=10)
        for entry in entries:
            if entry.command_id == command_id and entry.action == "command_completed":
                return CommandResult(
                    command_id=command_id,
                    state=CommandState(entry.metadata.get("state", "done")),
                    success=entry.result == "success",
                    error=entry.error,
                )
        
        return None
    
    async def cancel_command(self, command_id: str, user_id: str, role: str) -> bool:
        """Cancel a queued or running command."""
        # Try to cancel in dispatcher
        cancelled = await self._dispatcher.cancel_command(command_id)
        
        if cancelled:
            # Log cancellation
            self._audit.log_action(
                user_id=user_id,
                role=role,
                action="command_cancelled",
                target=command_id,
                target_type="command",
                result="success",
            )
        
        return cancelled
    
    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        return {
            "dispatcher": self._dispatcher.get_stats().__dict__,
            "executor": self._executor.get_stats(),
            "audit": self._audit.get_stats(),
            "notifier": self._notifier.get_stats(),
            "registered_commands": [ct.value for ct in self._command_registry.keys()],
        }
    
    def get_audit_log(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditEntry]:
        """Get audit log entries."""
        return self._audit.query(user_id=user_id, action=action, limit=limit)
    
    async def _execute_dry_run(self, command: Command) -> CommandResult:
        """Execute a command in dry-run mode."""
        context = ExecutionContext(command=command)
        result = await dry_run_handler(command, context)
        
        return CommandResult(
            command_id=command.id,
            state=CommandState.DONE,
            success=True,
            data={
                "dry_run": True,
                **result.data,
            },
        )
    
    def _setup_dispatcher_handlers(self):
        """Wire dispatcher to use executor for command handling."""
        
        async def execute_command(command: Command) -> CommandResult:
            result = await self._executor.execute(command)
            
            # Log completion
            self._audit.log_command_completed(command, result)
            
            # Notify
            await self._notifier.notify_command_state(
                command=command,
                state=result.state,
                result=result,
            )
            
            return result
        
        self._dispatcher.set_default_handler(execute_command)

# backend/ops/command_engine/__init__.py
"""
Command Execution Engine
========================

Pipeline: UI → Validation → RBAC → Queue → Executor → Audit → Feedback

Features:
- Idempotency key support
- Retry guard
- Timeout handling
- Rollback support
- Full audit trail
"""

from .validator import CommandValidator, ValidationResult
from .dispatcher import CommandDispatcher
from .executor import CommandExecutor, ExecutionResult
from .audit import CommandAudit, AuditEntry
from .notifier import CommandNotifier
from .models import (
    Command,
    CommandState,
    CommandResult,
    CommandType,
)
from .engine import CommandEngine

__all__ = [
    "CommandEngine",
    "CommandValidator",
    "ValidationResult",
    "CommandDispatcher",
    "CommandExecutor",
    "ExecutionResult",
    "CommandAudit",
    "AuditEntry",
    "CommandNotifier",
    "Command",
    "CommandState",
    "CommandResult",
    "CommandType",
]

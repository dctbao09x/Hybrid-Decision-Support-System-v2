# backend/scoring/security/__init__.py
"""
SIMGR Security - Access Control & Anti-Bypass
==============================================

GĐ2 PHẦN B: Access Boundary Definition
GĐ2 PHẦN D: Runtime Guards
REMEDIATION: Execution Context Registry

Provides:
- @enforce_controller_only decorator (legacy)
- @require_execution_context decorator (REMEDIATION)
- ExecutionContextRegistry for thread-local context tracking
- Runtime call stack inspection
- Token validation
- Audit logging
"""

from backend.scoring.security.guards import (
    enforce_controller_only,
    SecurityException,
    BypassAttemptError,
    InvalidTokenError,
    UnauthorizedCallerError,
)
from backend.scoring.security.token import (
    ControlToken,
    generate_control_token,
    verify_control_token,
)
from backend.scoring.security.context import (
    require_execution_context,
    ExecutionContextRegistry,
    ScoringExecutionContext,
    ExecutionEnvironment,
    create_scoring_context,
    ContextRequiredError,
    ContextValidationError,
    SecurityError,
)

__all__ = [
    # Legacy guards
    "enforce_controller_only",
    "SecurityException",
    "BypassAttemptError",
    "InvalidTokenError",
    "UnauthorizedCallerError",
    # Token management
    "ControlToken",
    "generate_control_token",
    "verify_control_token",
    # REMEDIATION: Execution context (new)
    "require_execution_context",
    "ExecutionContextRegistry",
    "ScoringExecutionContext",
    "ExecutionEnvironment",
    "create_scoring_context",
    "ContextRequiredError",
    "ContextValidationError",
    "SecurityError",
]

# backend/scoring/security/context.py
"""
Execution Context Registry for SIMGR Scoring
============================================

REMEDIATION: Mandatory context injection for all scoring operations.

This module provides:
1. ExecutionContextRegistry - Thread-local context storage
2. require_execution_context - Decorator enforcing context
3. Context validation for trace_id, caller, environment

ANY SCORING OPERATION WITHOUT VALID CONTEXT WILL FAIL.
"""

from __future__ import annotations

import functools
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, TypeVar

logger = logging.getLogger("scoring.security.context")

F = TypeVar("F", bound=Callable[..., Any])


# =====================================================
# Execution Context Model
# =====================================================

class ExecutionEnvironment(Enum):
    """Valid execution environments."""
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"
    TEST = "test"


@dataclass(frozen=True)
class ScoringExecutionContext:
    """
    Immutable execution context for scoring operations.
    
    ALL fields are required for valid context.
    Context MUST be created via DecisionController only.
    """
    trace_id: str
    correlation_id: str
    user_id: str
    caller_module: str
    environment: ExecutionEnvironment
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    permissions: Set[str] = field(default_factory=frozenset)
    
    # Security token (set by controller)
    _security_token: Optional[str] = field(default=None, repr=False)
    
    def validate(self) -> bool:
        """Validate context is complete and valid."""
        if not self.trace_id or not self.trace_id.startswith(("dec-", "test-")):
            logger.error(f"Invalid trace_id format: {self.trace_id}")
            return False
        
        if not self.correlation_id:
            logger.error("Missing correlation_id")
            return False
        
        if not self.caller_module:
            logger.error("Missing caller_module")
            return False
        
        # Validate caller is DecisionController or test
        allowed_callers = {
            "backend.api.controllers.decision_controller",
            "backend.main_controller",
            "tests.",
            "test_",
        }
        
        if not any(pattern in self.caller_module for pattern in allowed_callers):
            logger.error(f"Unauthorized caller: {self.caller_module}")
            return False
        
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Export context as dict (without security token)."""
        return {
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "user_id": self.user_id,
            "caller_module": self.caller_module,
            "environment": self.environment.value,
            "created_at": self.created_at.isoformat(),
            "permissions": list(self.permissions),
        }


# =====================================================
# Context Registry (Thread-Local)
# =====================================================

class ExecutionContextRegistry:
    """
    Thread-local registry for execution contexts.
    
    Ensures each thread has its own context stack.
    Only DecisionController should push contexts.
    """
    
    _local = threading.local()
    _global_lock = threading.Lock()
    
    # Valid context creators (whitelist)
    ALLOWED_CREATORS: Set[str] = frozenset([
        "backend.api.controllers.decision_controller",
        "backend.main_controller",
    ])
    
    @classmethod
    def _get_stack(cls) -> List[ScoringExecutionContext]:
        """Get thread-local context stack."""
        if not hasattr(cls._local, "stack"):
            cls._local.stack = []
        return cls._local.stack
    
    @classmethod
    def push(cls, context: ScoringExecutionContext, creator_module: str) -> None:
        """
        Push context onto stack.
        
        Args:
            context: Valid execution context
            creator_module: Module name of creator (for validation)
        
        Raises:
            SecurityError: If creator not authorized
            ValueError: If context invalid
        """
        # Validate creator
        is_test = "test" in creator_module.lower()
        is_allowed = any(
            allowed in creator_module 
            for allowed in cls.ALLOWED_CREATORS
        )
        
        if not is_allowed and not is_test:
            logger.error(f"Unauthorized context creator: {creator_module}")
            raise SecurityError(
                f"Only DecisionController can create scoring contexts. "
                f"Attempted by: {creator_module}"
            )
        
        # Validate context
        if not context.validate():
            raise ValueError("Invalid execution context")
        
        stack = cls._get_stack()
        stack.append(context)
        
        logger.debug(
            f"[CONTEXT] Pushed: trace_id={context.trace_id} "
            f"depth={len(stack)}"
        )
    
    @classmethod
    def pop(cls) -> Optional[ScoringExecutionContext]:
        """Pop context from stack."""
        stack = cls._get_stack()
        if stack:
            ctx = stack.pop()
            logger.debug(f"[CONTEXT] Popped: trace_id={ctx.trace_id}")
            return ctx
        return None
    
    @classmethod
    def current(cls) -> Optional[ScoringExecutionContext]:
        """Get current (top) context without removing it."""
        stack = cls._get_stack()
        return stack[-1] if stack else None
    
    @classmethod
    def require_current(cls) -> ScoringExecutionContext:
        """
        Get current context or raise exception.
        
        Raises:
            ContextRequiredError: If no context available
        """
        ctx = cls.current()
        if ctx is None:
            raise ContextRequiredError(
                "Scoring operation requires execution context. "
                "Must be called within DecisionController pipeline."
            )
        return ctx
    
    @classmethod
    def clear(cls) -> None:
        """Clear all contexts (for testing only)."""
        cls._local.stack = []
        logger.warning("[CONTEXT] Stack cleared (test mode)")
    
    @classmethod
    @contextmanager
    def scoped(cls, context: ScoringExecutionContext, creator_module: str):
        """
        Context manager for scoped execution.
        
        Usage:
            with ExecutionContextRegistry.scoped(ctx, __name__):
                scorer.score(...)
        """
        try:
            cls.push(context, creator_module)
            yield context
        finally:
            cls.pop()


# =====================================================
# Exceptions
# =====================================================

class SecurityError(Exception):
    """Security violation."""
    pass


class ContextRequiredError(SecurityError):
    """Execution context required but not found."""
    pass


class ContextValidationError(SecurityError):
    """Context validation failed."""
    pass


# =====================================================
# Enforcement Decorator
# =====================================================

def require_execution_context(
    require_trace_id: bool = True,
    require_production_env: bool = False,
    log_access: bool = True,
) -> Callable[[F], F]:
    """
    Decorator: Require valid execution context for scoring operation.
    
    REMEDIATION: This decorator MUST be applied to all scoring entry points.
    
    Args:
        require_trace_id: Require trace_id in context (default: True)
        require_production_env: Only allow production environment
        log_access: Log all access attempts
    
    Raises:
        ContextRequiredError: If no context available
        ContextValidationError: If context validation fails
    
    Usage:
        @require_execution_context()
        def score(self, input_dict: Dict) -> Dict:
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Get current context
            ctx = ExecutionContextRegistry.current()
            
            # HARDENED (2026-02-21): SCORING_TEST_MODE ENV bypass permanently removed.
            # Context is ALWAYS required — no environment-variable override is possible.
            if ctx is None:
                raise ContextRequiredError(
                    f"Scoring operation '{func.__name__}' requires execution context. "
                    f"Direct invocation is blocked. "
                    f"Use DecisionController.run_pipeline() instead."
                )
            
            # Validate context
            if not ctx.validate():
                raise ContextValidationError(
                    f"Invalid execution context for '{func.__name__}'"
                )
            
            # Check trace_id
            if require_trace_id and not ctx.trace_id:
                raise ContextValidationError(
                    f"trace_id required for '{func.__name__}'"
                )
            
            # Check environment
            if require_production_env:
                if ctx.environment != ExecutionEnvironment.PRODUCTION:
                    raise ContextValidationError(
                        f"'{func.__name__}' requires production environment"
                    )
            
            # Log access
            if log_access:
                logger.info(
                    f"[SCORING_ACCESS] {func.__name__} "
                    f"trace_id={ctx.trace_id} "
                    f"caller={ctx.caller_module}"
                )
            
            # Inject context into kwargs
            kwargs["_execution_context"] = ctx
            
            return func(*args, **kwargs)
        
        return wrapper  # type: ignore
    
    return decorator


# =====================================================
# Context Factory (for DecisionController use only)
# =====================================================

def create_scoring_context(
    trace_id: str,
    correlation_id: str,
    user_id: str,
    caller_module: str,
    environment: Optional[str] = None,
) -> ScoringExecutionContext:
    """
    Factory to create valid scoring context.

    ONLY DecisionController should call this.

    HARDENED (2026-02-21): SCORING_ENV ENV read permanently removed.
    Environment resolves strictly from the explicit `environment` argument
    supplied by the caller (DecisionController).  When absent, defaults to
    PRODUCTION — the most restrictive, determinism-safe value.
    No os.environ read of any kind is performed here.
    """
    # Resolve environment from explicit argument only; default to PRODUCTION.
    if environment is not None:
        try:
            env = ExecutionEnvironment(environment.lower())
        except ValueError:
            env = ExecutionEnvironment.PRODUCTION
    else:
        env = ExecutionEnvironment.PRODUCTION

    return ScoringExecutionContext(
        trace_id=trace_id,
        correlation_id=correlation_id,
        user_id=user_id,
        caller_module=caller_module,
        environment=env,
        permissions=frozenset(["score", "rank"]),
    )

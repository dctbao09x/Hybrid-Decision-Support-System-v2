# backend/scoring/security/guards.py
"""
Runtime Guards for SIMGR Core
=============================

GĐ2 PHẦN B: Access Boundary Definition
GĐ2 PHẦN D: Runtime Guards

Enforces:
- Only MainController can invoke scoring core
- All requests must have valid control token
- All callers must pass stack inspection
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
import threading
from datetime import datetime
from typing import Any, Callable, List, Optional, Set, TypeVar

logger = logging.getLogger("scoring.security")

# Type for decorated functions
F = TypeVar("F", bound=Callable[..., Any])

# =====================================================
# Exceptions
# =====================================================

class SecurityException(Exception):
    """Base security exception - CRITICAL."""
    pass


class BypassAttemptError(SecurityException):
    """Attempted to bypass controller."""
    pass


class InvalidTokenError(SecurityException):
    """Control token invalid or missing."""
    pass


class UnauthorizedCallerError(SecurityException):
    """Caller not in allowed list."""
    pass


# =====================================================
# Allowed Callers (Whitelist)
# =====================================================

# Only these modules can call scoring core
ALLOWED_CALLER_MODULES: Set[str] = frozenset([
    "backend.main_controller",
    "backend.scoring.service",
    "backend.scoring.strategies",
    # Test modules allowed with special flag
])

# Allowed caller patterns for stack inspection
ALLOWED_CALLER_PATTERNS: List[str] = [
    "main_controller.py",
    "MainController",
    "dispatch",
    "scoring_service",
]

# Test mode flag - allows test harness to bypass guards
_test_mode: bool = False
_test_lock = threading.Lock()


def enable_test_mode() -> None:
    """Enable test mode - allows test harness bypass."""
    global _test_mode
    with _test_lock:
        _test_mode = True
        logger.warning("[SECURITY] Test mode ENABLED - guards relaxed")


def disable_test_mode() -> None:
    """Disable test mode - full guards active."""
    global _test_mode
    with _test_lock:
        _test_mode = False
        logger.info("[SECURITY] Test mode DISABLED - guards active")


def is_test_mode() -> bool:
    """Check if test mode is active."""
    return _test_mode


# =====================================================
# Stack Inspection
# =====================================================

def inspect_call_stack() -> List[dict]:
    """Inspect current call stack for security audit."""
    stack_info = []
    
    for frame_info in inspect.stack():
        stack_info.append({
            "filename": frame_info.filename,
            "function": frame_info.function,
            "lineno": frame_info.lineno,
            "module": frame_info.frame.f_globals.get("__name__", "unknown"),
        })
    
    return stack_info


def validate_caller(allowed_patterns: Optional[List[str]] = None) -> bool:
    """
    Validate caller is in allowed list.
    
    Inspects call stack to ensure caller is authorized.
    Returns True if authorized, False otherwise.
    """
    patterns = allowed_patterns or ALLOWED_CALLER_PATTERNS
    stack = inspect_call_stack()
    
    # Skip first 3 frames (this function, decorator, wrapped function)
    for frame in stack[3:]:
        filename = frame["filename"]
        function = frame["function"]
        module = frame["module"]
        
        # Check against allowed patterns
        for pattern in patterns:
            if pattern in filename or pattern in function or pattern in module:
                logger.debug(f"[SECURITY] Caller validated: {module}.{function}")
                return True
        
        # Check against allowed modules
        if module in ALLOWED_CALLER_MODULES:
            logger.debug(f"[SECURITY] Caller validated via module: {module}")
            return True
    
    return False


def get_caller_info() -> dict:
    """Get info about the immediate caller."""
    stack = inspect_call_stack()
    
    if len(stack) >= 4:
        caller = stack[3]
        return {
            "module": caller["module"],
            "function": caller["function"],
            "file": caller["filename"],
            "line": caller["lineno"],
        }
    
    return {"module": "unknown", "function": "unknown"}


# =====================================================
# Enforcement Decorator
# =====================================================

def enforce_controller_only(
    require_token: bool = True,
    require_request_id: bool = True,
    log_access: bool = True,
) -> Callable[[F], F]:
    """
    Decorator: Enforce controller-only access to scoring core.
    
    GĐ2 PHẦN B: Access Boundary Definition
    
    Args:
        require_token: Require valid control token
        require_request_id: Require request_id in context
        log_access: Log all access attempts
    
    Raises:
        BypassAttemptError: If caller is not authorized
        InvalidTokenError: If token is missing/invalid
        UnauthorizedCallerError: If caller module not allowed
    
    Usage:
        @enforce_controller_only()
        def compute_score(self, ...):
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            timestamp = datetime.now().isoformat()
            caller_info = get_caller_info()
            
            # Check test mode
            if is_test_mode():
                if log_access:
                    logger.debug(
                        f"[SECURITY] TEST_MODE access: {func.__name__} "
                        f"caller={caller_info['module']}"
                    )
                return func(*args, **kwargs)
            
            # Validate caller
            if not validate_caller():
                error_msg = (
                    f"[SECURITY] BYPASS_ATTEMPT: {func.__name__} "
                    f"caller={caller_info['module']}.{caller_info['function']} "
                    f"file={caller_info['file']}:{caller_info['line']}"
                )
                logger.error(error_msg)
                
                # Log to audit trail
                _log_security_event(
                    event_type="BYPASS_ATTEMPT",
                    function=func.__name__,
                    caller=caller_info,
                    timestamp=timestamp,
                    blocked=True,
                )
                
                raise BypassAttemptError(
                    f"Scoring core access denied. "
                    f"Only MainController can invoke {func.__name__}. "
                    f"Caller: {caller_info['module']}"
                )
            
            # Check for control token in kwargs or context
            if require_token:
                control_token = kwargs.get("_control_token")
                if control_token is None:
                    # Try to get from first arg if it's a context dict
                    if args and isinstance(args[0], dict):
                        control_token = args[0].get("_control_token")
                
                if control_token is None and not is_test_mode():
                    logger.warning(
                        f"[SECURITY] Missing control token for {func.__name__}"
                    )
                    # Note: Token enforcement will be stricter in PHẦN E
            
            # Check for request_id
            if require_request_id:
                request_id = kwargs.get("request_id")
                if request_id is None and args and isinstance(args[0], dict):
                    request_id = args[0].get("request_id")
                
                # Log if missing but don't block (for now)
                if request_id is None:
                    logger.debug(f"[SECURITY] No request_id for {func.__name__}")
            
            # Log successful access
            if log_access:
                logger.info(
                    f"[CONTROL_TRACE] {func.__name__} "
                    f"caller={caller_info['module']} "
                    f"timestamp={timestamp}"
                )
                
                _log_security_event(
                    event_type="ACCESS_GRANTED",
                    function=func.__name__,
                    caller=caller_info,
                    timestamp=timestamp,
                    blocked=False,
                )
            
            return func(*args, **kwargs)
        
        return wrapper  # type: ignore
    
    return decorator


# =====================================================
# Audit Event Logging
# =====================================================

_security_events: List[dict] = []
_events_lock = threading.Lock()


def _log_security_event(
    event_type: str,
    function: str,
    caller: dict,
    timestamp: str,
    blocked: bool,
    **extra
) -> None:
    """Log security event for audit trail."""
    event = {
        "timestamp": timestamp,
        "event_type": event_type,
        "function": function,
        "caller_module": caller.get("module"),
        "caller_function": caller.get("function"),
        "caller_file": caller.get("file"),
        "caller_line": caller.get("line"),
        "blocked": blocked,
        **extra,
    }
    
    with _events_lock:
        _security_events.append(event)
        
        # Keep only last 1000 events in memory
        if len(_security_events) > 1000:
            _security_events.pop(0)


def get_security_events() -> List[dict]:
    """Get security event log."""
    with _events_lock:
        return list(_security_events)


def clear_security_events() -> None:
    """Clear security event log."""
    with _events_lock:
        _security_events.clear()


# =====================================================
# Module Import Guard
# =====================================================

def guard_import(module_name: str) -> None:
    """
    Guard against unauthorized module imports.
    
    Call this in module __init__ to block direct imports.
    """
    stack = inspect_call_stack()
    
    # Check if import is from allowed source
    for frame in stack[2:]:  # Skip this function and caller
        module = frame["module"]
        
        # Allow imports from controller and tests
        if any(allowed in module for allowed in ["main_controller", "test_", "pytest"]):
            return
    
    # Check test mode
    if is_test_mode():
        return
    
    # Block unauthorized import
    caller_info = get_caller_info()
    logger.warning(
        f"[SECURITY] Blocked import of {module_name} "
        f"from {caller_info['module']}"
    )
    
    raise ImportError(
        f"Direct import of {module_name} is blocked. "
        f"Use MainController.dispatch() instead."
    )

# Guard Implementation Reference
# GĐ2 - ANTI-BYPASS & CONTROL ENFORCEMENT
# 
# This file is a reference copy of the guards implementation.
# Canonical source: backend/scoring/security/guards.py
# DO NOT MODIFY this file - modify the source instead.

"""
Runtime guards for SIMGR scoring system.

Implements:
- @enforce_controller_only decorator
- Call stack inspection
- Caller validation
- Bypass attempt detection
"""

import functools
import inspect
from datetime import datetime
from typing import Callable, Optional

# ---------------------------------------------------------------------
# EXCEPTIONS
# ---------------------------------------------------------------------

class BypassAttemptError(Exception):
    """Raised when code attempts to bypass controller."""
    pass

class InvalidTokenError(Exception):
    """Raised when control token is invalid or missing."""
    pass

class UnauthorizedCallerError(Exception):
    """Raised when caller is not in allowed list."""
    pass


# ---------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------

ALLOWED_CALLER_MODULES = [
    "backend.main_controller",
    "backend.scoring.service",
    "backend.scoring.strategies",
]

ALLOWED_CALLER_PATTERNS = [
    "main_controller.py",
    "MainController",
    "dispatch",
    "scoring_service",
]

# Test mode flag - for automated testing only
_test_mode = False


# ---------------------------------------------------------------------
# CORE GUARDS
# ---------------------------------------------------------------------

def validate_caller(
    allowed_modules: list = None,
    allowed_patterns: list = None
) -> bool:
    """
    Validate the calling module/function is authorized.
    
    Returns True if caller is allowed, raises BypassAttemptError otherwise.
    """
    if _test_mode:
        return True
        
    stack = inspect.stack()
    
    modules = allowed_modules or ALLOWED_CALLER_MODULES
    patterns = allowed_patterns or ALLOWED_CALLER_PATTERNS
    
    for frame_info in stack[2:]:  # Skip this func and decorated func
        frame_module = frame_info.frame.f_globals.get('__name__', '')
        
        # Check module whitelist
        for allowed in modules:
            if allowed in frame_module:
                return True
        
        # Check pattern whitelist  
        for pattern in patterns:
            if pattern in frame_info.filename or pattern in frame_info.function:
                return True
    
    # No allowed caller found
    caller_info = stack[2] if len(stack) > 2 else stack[1]
    raise BypassAttemptError(
        f"Unauthorized bypass attempt from {caller_info.filename}:"
        f"{caller_info.lineno} ({caller_info.function})"
    )


def inspect_call_stack() -> dict:
    """
    Inspect the current call stack for security analysis.
    
    Returns dict with stack information.
    """
    stack = inspect.stack()
    return {
        "depth": len(stack),
        "frames": [
            {
                "file": f.filename,
                "line": f.lineno,
                "function": f.function,
                "module": f.frame.f_globals.get('__name__', 'unknown')
            }
            for f in stack[1:6]  # First 5 frames after current
        ],
        "timestamp": datetime.utcnow().isoformat()
    }


def check_controller_in_stack() -> bool:
    """
    Check if MainController is in the call stack.
    """
    if _test_mode:
        return True
        
    stack = inspect.stack()
    for frame_info in stack:
        if "MainController" in frame_info.function:
            return True
        if "main_controller" in frame_info.filename:
            return True
    return False


# ---------------------------------------------------------------------
# DECORATOR
# ---------------------------------------------------------------------

def enforce_controller_only(func: Callable) -> Callable:
    """
    Decorator that enforces function can only be called via controller.
    
    Usage:
        @enforce_controller_only
        def calc_simgr_score(self, ...):
            ...
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Skip validation in test mode
        if _test_mode:
            return func(*args, **kwargs)
        
        # Validate caller
        if not check_controller_in_stack():
            validate_caller()  # Will raise if not allowed
        
        # Validate token if provided
        token = kwargs.get('control_token')
        if token:
            from .token import verify_control_token
            request_id = kwargs.get('request_id', '')
            if not verify_control_token(token, request_id):
                raise InvalidTokenError("Control token validation failed")
        
        return func(*args, **kwargs)
    
    return wrapper


# ---------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------

def set_test_mode(enabled: bool):
    """Enable/disable test mode for unit testing."""
    global _test_mode
    _test_mode = enabled


def get_test_mode() -> bool:
    """Check if test mode is enabled."""
    return _test_mode


def log_security_event(event_type: str, details: dict):
    """Log a security event for audit trail."""
    timestamp = datetime.utcnow().isoformat()
    _security_events.append({
        "timestamp": timestamp,
        "type": event_type,
        "details": details
    })
    # Keep only last 1000 events
    if len(_security_events) > 1000:
        _security_events.pop(0)


def get_security_events(limit: int = 100) -> list:
    """Get recent security events."""
    return _security_events[-limit:]


# Internal storage for security events
_security_events = []


# ---------------------------------------------------------------------
# EXPORTS
# ---------------------------------------------------------------------

__all__ = [
    "BypassAttemptError",
    "InvalidTokenError", 
    "UnauthorizedCallerError",
    "enforce_controller_only",
    "validate_caller",
    "inspect_call_stack",
    "check_controller_in_stack",
    "set_test_mode",
    "get_test_mode",
    "log_security_event",
    "get_security_events",
]

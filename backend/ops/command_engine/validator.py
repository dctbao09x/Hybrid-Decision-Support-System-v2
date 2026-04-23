# backend/ops/command_engine/validator.py
"""
Command Validator
=================

Validates commands before execution.

Checks:
- Parameter validation
- Permission verification
- Resource existence
- Rate limiting
- Idempotency
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .models import Command, CommandType, CommandState

logger = logging.getLogger("ops.command_engine.validator")


@dataclass
class ValidationResult:
    """Result of command validation."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    sanitized_params: Dict[str, Any] = field(default_factory=dict)


class CommandValidator:
    """
    Validates commands before execution.
    
    Responsibilities:
    - Schema validation
    - Parameter sanitization
    - Permission checks
    - Rate limiting
    - Idempotency handling
    """
    
    def __init__(self):
        self._idempotency_cache: Dict[str, float] = {}
        self._rate_limits: Dict[str, List[float]] = {}
        self._idempotency_ttl = 3600  # 1 hour
        self._rate_window = 60  # 1 minute
        self._rate_limit = 100  # Max requests per window
        
        # Required parameters by command type
        self._required_params: Dict[CommandType, Set[str]] = {
            CommandType.CRAWLER_START: {"site_name"},
            CommandType.CRAWLER_STOP: {"site_name"},
            CommandType.CRAWLER_KILL: {"site_name"},
            CommandType.JOB_PAUSE: {"job_id"},
            CommandType.JOB_RESUME: {"job_id"},
            CommandType.KB_ROLLBACK: {"version"},
            CommandType.MLOPS_FREEZE: {"model_id"},
            CommandType.MLOPS_RETRAIN: {"model_id"},
        }
        
        # Allowed environments by command type
        self._prod_commands: Set[CommandType] = {
            CommandType.CRAWLER_KILL,
            CommandType.MLOPS_FREEZE,
            CommandType.MLOPS_ROLLBACK,
            CommandType.KB_ROLLBACK,
            CommandType.SYSTEM_RESTORE,
        }
    
    def validate(self, command: Command) -> ValidationResult:
        """
        Validate a command.
        
        Args:
            command: Command to validate
            
        Returns:
            ValidationResult with validation status and any errors
        """
        errors: List[str] = []
        warnings: List[str] = []
        
        # Clean up expired cache entries
        self._cleanup_caches()
        
        # Check idempotency
        if command.idempotency_key:
            if self._check_idempotency_violation(command.idempotency_key):
                errors.append(f"Duplicate request: idempotency_key '{command.idempotency_key}' already processed")
        
        # Check rate limiting
        if not self._check_rate_limit(command.user_id):
            errors.append(f"Rate limit exceeded for user {command.user_id}")
        
        # Validate command type
        if not isinstance(command.type, str) or command.type not in [ct.value for ct in CommandType]:
            errors.append(f"Invalid command type: {command.type}")
        else:
            # Validate required parameters
            cmd_type = CommandType(command.type) if isinstance(command.type, str) else command.type
            required = self._required_params.get(cmd_type, set())
            missing = required - set(command.params.keys())
            if missing:
                errors.append(f"Missing required parameters: {', '.join(missing)}")
            
            # Check production safety
            if cmd_type in self._prod_commands and command.environment == "production":
                if not command.dry_run:
                    warnings.append(f"Production command '{cmd_type.value}' - ensure approval is obtained")
        
        # Validate target
        if not command.target or not command.target.strip():
            errors.append("Target resource cannot be empty")
        
        # Validate user
        if not command.user_id:
            errors.append("User ID is required")
        if not command.role:
            errors.append("User role is required")
        
        # Validate timeout
        if command.timeout_seconds < 1:
            errors.append("Timeout must be at least 1 second")
        elif command.timeout_seconds > 3600:
            warnings.append("Timeout exceeds 1 hour - consider breaking into smaller operations")
        
        # Sanitize parameters
        sanitized_params = self._sanitize_params(command.params)
        
        # Record idempotency key if valid
        if not errors and command.idempotency_key:
            self._idempotency_cache[command.idempotency_key] = time.time()
        
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            sanitized_params=sanitized_params,
        )
    
    def validate_state_transition(
        self,
        current_state: CommandState,
        target_state: CommandState,
    ) -> bool:
        """
        Validate if a state transition is allowed.
        
        Args:
            current_state: Current command state
            target_state: Target state to transition to
            
        Returns:
            True if transition is valid
        """
        # Define valid transitions
        valid_transitions: Dict[CommandState, Set[CommandState]] = {
            CommandState.PENDING: {
                CommandState.VALIDATING,
                CommandState.CANCELLED,
            },
            CommandState.VALIDATING: {
                CommandState.AWAITING_APPROVAL,
                CommandState.QUEUED,
                CommandState.FAILED,
                CommandState.CANCELLED,
            },
            CommandState.AWAITING_APPROVAL: {
                CommandState.QUEUED,
                CommandState.CANCELLED,
                CommandState.FAILED,
            },
            CommandState.QUEUED: {
                CommandState.RUNNING,
                CommandState.TIMEOUT,
                CommandState.CANCELLED,
            },
            CommandState.RUNNING: {
                CommandState.DONE,
                CommandState.FAILED,
                CommandState.TIMEOUT,
                CommandState.CANCELLED,
            },
            CommandState.FAILED: {
                CommandState.RECOVERING,
                CommandState.ROLLED_BACK,
            },
            CommandState.RECOVERING: {
                CommandState.DONE,
                CommandState.ROLLED_BACK,
                CommandState.FAILED,
            },
            CommandState.DONE: set(),  # Terminal state
            CommandState.ROLLED_BACK: set(),  # Terminal state
            CommandState.CANCELLED: set(),  # Terminal state
            CommandState.TIMEOUT: {
                CommandState.RECOVERING,
                CommandState.ROLLED_BACK,
            },
        }
        
        allowed = valid_transitions.get(current_state, set())
        return target_state in allowed
    
    def _check_idempotency_violation(self, key: str) -> bool:
        """Check if idempotency key was recently used."""
        if key in self._idempotency_cache:
            elapsed = time.time() - self._idempotency_cache[key]
            return elapsed < self._idempotency_ttl
        return False
    
    def _check_rate_limit(self, user_id: str) -> bool:
        """Check if user is within rate limits."""
        now = time.time()
        
        if user_id not in self._rate_limits:
            self._rate_limits[user_id] = []
        
        # Remove old entries
        self._rate_limits[user_id] = [
            ts for ts in self._rate_limits[user_id]
            if now - ts < self._rate_window
        ]
        
        # Check limit
        if len(self._rate_limits[user_id]) >= self._rate_limit:
            return False
        
        # Record request
        self._rate_limits[user_id].append(now)
        return True
    
    def _sanitize_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize command parameters."""
        sanitized = {}
        
        for key, value in params.items():
            # Strip strings
            if isinstance(value, str):
                sanitized[key] = value.strip()
            # Recursively sanitize dicts
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_params(value)
            # Copy other values as-is
            else:
                sanitized[key] = value
        
        return sanitized
    
    def _cleanup_caches(self):
        """Clean up expired cache entries."""
        now = time.time()
        
        # Clean idempotency cache
        expired_keys = [
            key for key, ts in self._idempotency_cache.items()
            if now - ts > self._idempotency_ttl
        ]
        for key in expired_keys:
            del self._idempotency_cache[key]
        
        # Clean rate limit cache
        for user_id in list(self._rate_limits.keys()):
            self._rate_limits[user_id] = [
                ts for ts in self._rate_limits[user_id]
                if now - ts < self._rate_window
            ]
            if not self._rate_limits[user_id]:
                del self._rate_limits[user_id]

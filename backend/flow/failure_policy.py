# backend/flow/failure_policy.py
"""
ONE-BUTTON FLOW: Failure Handling Policy
========================================

III. FAILURE HANDLING POLICY

PRINCIPLES:
1. Fail-fast: Invalid operations fail immediately
2. No partial state: Transactions are atomic
3. Recoverable errors: Client can retry or restart
4. Audit trail: All failures are logged

ERROR CATEGORIES:
    - Validation Errors (400): Invalid input, schema violations
    - State Errors (409): Invalid state transition
    - Processing Errors (500): Internal processing failures
    - Timeout Errors (504): Stage timeout exceeded

RECOVERY STRATEGIES:
    - ValidationError → Fix input, retry same request
    - TransitionError → Check state, use valid action
    - ProcessingError → Retry or create new session
    - TimeoutError → Retry or create new session

Author: System Architecture Team
Date: 2026-02-21
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from backend.flow.state_machine import (
    Session,
    SessionState,
    TransitionEvent,
    TransitionError,
    VALID_EVENTS,
)

logger = logging.getLogger("flow.failure_policy")


# ═══════════════════════════════════════════════════════════════════════════════
#  ERROR CODES
# ═══════════════════════════════════════════════════════════════════════════════

class ErrorCode(Enum):
    """Standardized error codes."""
    
    # Validation Errors (400)
    VALIDATION_FAILED = ("E4001", "Input validation failed", 400)
    INVALID_SESSION_ID = ("E4002", "Invalid session ID format", 400)
    MISSING_REQUIRED_FIELD = ("E4003", "Required field missing", 400)
    INVALID_ANSWER_VALUE = ("E4004", "Answer value out of range", 400)
    MALFORMED_REQUEST = ("E4005", "Malformed request body", 400)
    
    # State Errors (409)
    INVALID_TRANSITION = ("E4091", "Invalid state transition", 409)
    SESSION_NOT_FOUND = ("E4092", "Session not found", 404)
    SESSION_EXPIRED = ("E4093", "Session expired", 410)
    SESSION_ALREADY_CLOSED = ("E4094", "Session already closed", 409)
    INSUFFICIENT_ANSWERS = ("E4095", "Not enough answers to submit", 409)
    
    # Processing Errors (500)
    VALIDATION_STAGE_FAILED = ("E5001", "Validation stage failed", 500)
    SCORING_STAGE_FAILED = ("E5002", "Scoring stage failed", 500)
    DECISION_STAGE_FAILED = ("E5003", "Decision stage failed", 500)
    EXPLAIN_STAGE_FAILED = ("E5004", "Explanation stage failed", 500)
    INTERNAL_ERROR = ("E5005", "Internal server error", 500)
    
    # Timeout Errors (504)
    STAGE_TIMEOUT = ("E5041", "Stage execution timeout", 504)
    SESSION_TIMEOUT = ("E5042", "Session timeout", 504)
    
    # HARDENING: Invariant Violation Errors (500 - Fatal)
    RANKING_REORDER_DETECTED = ("E5101", "Ranking reorder detected (FATAL)", 500)
    RANKING_ORDER_MISMATCH = ("E5102", "Ranking order mismatch (FATAL)", 500)
    DETERMINISTIC_INVARIANCE_ERROR = ("E5103", "Deterministic invariance error (FATAL)", 500)
    CHECKSUM_MISMATCH = ("E5104", "Output checksum mismatch (FATAL)", 500)
    UNAUTHORIZED_SCORING_ACCESS = ("E5105", "Unauthorized scoring access (FATAL)", 500)
    MISSING_EXECUTION_CONTEXT = ("E5106", "Missing execution context (FATAL)", 500)
    INVALID_STATE_FOR_SCORING = ("E5107", "Invalid state for scoring (FATAL)", 500)
    CAREER_COUNT_MISMATCH = ("E5108", "Career count mismatch (FATAL)", 500)
    CAREER_ORDER_VIOLATED = ("E5109", "Career order violated (FATAL)", 500)
    CAREER_INJECTION_DETECTED = ("E5110", "Career injection detected (FATAL)", 500)
    CAREER_REMOVAL_DETECTED = ("E5111", "Career removal detected (FATAL)", 500)
    
    def __init__(self, code: str, message: str, http_status: int):
        self._code = code
        self._message = message
        self._http_status = http_status
    
    @property
    def code(self) -> str:
        return self._code
    
    @property
    def message(self) -> str:
        return self._message
    
    @property
    def http_status(self) -> int:
        return self._http_status


# ═══════════════════════════════════════════════════════════════════════════════
#  ERROR MODELS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class FlowError:
    """
    Immutable error record.
    
    Contains all information needed for:
    1. HTTP response generation
    2. Client-side error handling
    3. Audit logging
    """
    error_code: ErrorCode
    message: str
    session_id: Optional[str] = None
    current_state: Optional[str] = None
    details: Tuple[Tuple[str, Any], ...] = ()
    timestamp: float = field(default_factory=time.time)
    
    @property
    def http_status(self) -> int:
        return self.error_code.http_status
    
    @property
    def code(self) -> str:
        return self.error_code.code
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to API response format."""
        result = {
            "error": True,
            "code": self.error_code.code,
            "message": self.message,
            "details": [{"key": k, "value": v} for k, v in self.details],
            "timestamp": self.timestamp,
        }
        if self.session_id:
            result["session_id"] = self.session_id
        if self.current_state:
            result["current_state"] = self.current_state
            result["valid_actions"] = self._get_valid_actions()
        return result
    
    def _get_valid_actions(self) -> List[str]:
        """Get valid actions for current state."""
        if not self.current_state:
            return []
        try:
            state = SessionState[self.current_state.upper()]
            return [e.value for e in VALID_EVENTS.get(state, frozenset())]
        except KeyError:
            return []


# ═══════════════════════════════════════════════════════════════════════════════
#  FAILURE HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

class FailurePolicy:
    """
    Centralized failure handling policy.
    
    GUARANTEES:
    1. All errors return FlowError with proper code
    2. All errors are logged with context
    3. Recovery hints are always provided
    """
    
    # Stage timeout limits (seconds)
    STAGE_TIMEOUTS: Dict[SessionState, float] = {
        SessionState.VALIDATION: 5.0,
        SessionState.SCORING: 10.0,
        SessionState.DECISION: 5.0,
        SessionState.EXPLAIN: 5.0,
    }
    
    # Session expiry (seconds)
    SESSION_EXPIRY: float = 3600.0  # 1 hour
    
    # Minimum answers for submission
    MIN_ANSWERS_FOR_SUBMIT: int = 10
    
    # ─────────────────────────────────────────────────────────────────────────
    #  Validation Error Handlers
    # ─────────────────────────────────────────────────────────────────────────
    
    @staticmethod
    def handle_validation_error(
        message: str,
        session_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> FlowError:
        """Handle input validation failures."""
        logger.warning(f"Validation error: {message} [session={session_id}]")
        
        return FlowError(
            error_code=ErrorCode.VALIDATION_FAILED,
            message=message,
            session_id=session_id,
            details=tuple(sorted(details.items())) if details else (),
        )
    
    @staticmethod
    def handle_invalid_session_id(session_id: str) -> FlowError:
        """Handle invalid session ID format."""
        logger.warning(f"Invalid session ID: {session_id}")
        
        return FlowError(
            error_code=ErrorCode.INVALID_SESSION_ID,
            message=f"Invalid session ID format: {session_id[:20]}...",
            details=(("received_id", session_id[:50]),),
        )
    
    @staticmethod
    def handle_missing_field(field_name: str, session_id: Optional[str] = None) -> FlowError:
        """Handle missing required field."""
        logger.warning(f"Missing field: {field_name} [session={session_id}]")
        
        return FlowError(
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            message=f"Required field missing: {field_name}",
            session_id=session_id,
            details=(("field", field_name),),
        )
    
    @staticmethod
    def handle_invalid_answer(
        question_id: str,
        value: Any,
        reason: str,
        session_id: Optional[str] = None,
    ) -> FlowError:
        """Handle invalid answer value."""
        logger.warning(f"Invalid answer: {question_id}={value} ({reason}) [session={session_id}]")
        
        return FlowError(
            error_code=ErrorCode.INVALID_ANSWER_VALUE,
            message=f"Invalid answer for question {question_id}: {reason}",
            session_id=session_id,
            details=(
                ("question_id", question_id),
                ("value", str(value)[:50]),
                ("reason", reason),
            ),
        )
    
    # ─────────────────────────────────────────────────────────────────────────
    #  State Error Handlers
    # ─────────────────────────────────────────────────────────────────────────
    
    @staticmethod
    def handle_transition_error(error: TransitionError, session: Session) -> FlowError:
        """Handle invalid state transition."""
        logger.warning(
            f"Transition error: {error} [session={session.session_id}, state={session.current_state.state_name}]"
        )
        
        valid_events = VALID_EVENTS.get(session.current_state, frozenset())
        
        return FlowError(
            error_code=ErrorCode.INVALID_TRANSITION,
            message=str(error),
            session_id=session.session_id,
            current_state=session.current_state.state_name,
            details=(
                ("attempted_event", error.event.value),
                ("valid_events", [e.value for e in valid_events]),
            ),
        )
    
    @staticmethod
    def handle_session_not_found(session_id: str) -> FlowError:
        """Handle session not found."""
        logger.warning(f"Session not found: {session_id}")
        
        return FlowError(
            error_code=ErrorCode.SESSION_NOT_FOUND,
            message=f"Session not found: {session_id[:20]}...",
            session_id=session_id,
            details=(("hint", "Create a new session with POST /session/start"),),
        )
    
    @staticmethod
    def handle_session_expired(session: Session) -> FlowError:
        """Handle expired session."""
        logger.warning(f"Session expired: {session.session_id}")
        
        age = time.time() - session.data.created_at
        
        return FlowError(
            error_code=ErrorCode.SESSION_EXPIRED,
            message="Session has expired",
            session_id=session.session_id,
            current_state=session.current_state.state_name,
            details=(
                ("age_seconds", round(age, 2)),
                ("max_age_seconds", FailurePolicy.SESSION_EXPIRY),
                ("hint", "Create a new session"),
            ),
        )
    
    @staticmethod
    def handle_session_closed(session: Session) -> FlowError:
        """Handle already-closed session."""
        logger.warning(f"Session already closed: {session.session_id}")
        
        return FlowError(
            error_code=ErrorCode.SESSION_ALREADY_CLOSED,
            message="Session is already closed",
            session_id=session.session_id,
            current_state=session.current_state.state_name,
            details=(("hint", "Create a new session"),),
        )
    
    @staticmethod
    def handle_insufficient_answers(
        session: Session,
        current_count: int,
        min_required: int,
    ) -> FlowError:
        """Handle insufficient answers for submission."""
        logger.warning(
            f"Insufficient answers: {current_count}/{min_required} [session={session.session_id}]"
        )
        
        return FlowError(
            error_code=ErrorCode.INSUFFICIENT_ANSWERS,
            message=f"At least {min_required} answers required, only {current_count} provided",
            session_id=session.session_id,
            current_state=session.current_state.state_name,
            details=(
                ("current_count", current_count),
                ("min_required", min_required),
                ("hint", "Submit more answers before calling /assessment/submit"),
            ),
        )
    
    # ─────────────────────────────────────────────────────────────────────────
    #  Processing Error Handlers
    # ─────────────────────────────────────────────────────────────────────────
    
    @staticmethod
    def handle_stage_failure(
        stage: SessionState,
        error: Exception,
        session: Session,
    ) -> FlowError:
        """Handle processing stage failure."""
        logger.error(
            f"Stage failure: {stage.state_name} - {error} [session={session.session_id}]",
            exc_info=True,
        )
        
        # Map stage to error code
        stage_error_map = {
            SessionState.VALIDATION: ErrorCode.VALIDATION_STAGE_FAILED,
            SessionState.SCORING: ErrorCode.SCORING_STAGE_FAILED,
            SessionState.DECISION: ErrorCode.DECISION_STAGE_FAILED,
            SessionState.EXPLAIN: ErrorCode.EXPLAIN_STAGE_FAILED,
        }
        
        error_code = stage_error_map.get(stage, ErrorCode.INTERNAL_ERROR)
        
        return FlowError(
            error_code=error_code,
            message=f"Processing failed at {stage.state_name} stage: {str(error)[:100]}",
            session_id=session.session_id,
            current_state=stage.state_name,
            details=(
                ("stage", stage.state_name),
                ("error_type", type(error).__name__),
                ("hint", "Retry the request or create a new session"),
            ),
        )
    
    @staticmethod
    def handle_internal_error(
        error: Exception,
        session_id: Optional[str] = None,
    ) -> FlowError:
        """Handle unexpected internal error."""
        logger.error(f"Internal error: {error} [session={session_id}]", exc_info=True)
        
        return FlowError(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="An internal error occurred",
            session_id=session_id,
            details=(
                ("error_type", type(error).__name__),
                ("hint", "Please try again or contact support"),
            ),
        )
    
    # ─────────────────────────────────────────────────────────────────────────
    #  Timeout Error Handlers
    # ─────────────────────────────────────────────────────────────────────────
    
    @staticmethod
    def handle_stage_timeout(stage: SessionState, session: Session, elapsed: float) -> FlowError:
        """Handle stage execution timeout."""
        limit = FailurePolicy.STAGE_TIMEOUTS.get(stage, 10.0)
        logger.error(
            f"Stage timeout: {stage.state_name} ({elapsed:.2f}s > {limit:.2f}s) [session={session.session_id}]"
        )
        
        return FlowError(
            error_code=ErrorCode.STAGE_TIMEOUT,
            message=f"Stage {stage.state_name} timed out after {elapsed:.2f}s",
            session_id=session.session_id,
            current_state=stage.state_name,
            details=(
                ("stage", stage.state_name),
                ("elapsed_seconds", round(elapsed, 2)),
                ("limit_seconds", limit),
                ("hint", "Retry the request"),
            ),
        )
    
    # ─────────────────────────────────────────────────────────────────────────
    #  Utility Methods
    # ─────────────────────────────────────────────────────────────────────────
    
    @staticmethod
    def check_session_validity(session: Session) -> Optional[FlowError]:
        """
        Check if session is valid for operations.
        
        Returns FlowError if invalid, None if valid.
        """
        # Check terminal state
        if session.current_state == SessionState.CLOSED:
            return FailurePolicy.handle_session_closed(session)
        
        if session.current_state == SessionState.ERROR:
            return FlowError(
                error_code=ErrorCode.SESSION_ALREADY_CLOSED,
                message="Session is in error state",
                session_id=session.session_id,
                current_state=session.current_state.state_name,
                details=(("hint", "Create a new session"),),
            )
        
        # Check expiry
        age = time.time() - session.data.created_at
        if age > FailurePolicy.SESSION_EXPIRY:
            return FailurePolicy.handle_session_expired(session)
        
        return None
    
    @staticmethod
    def check_submit_readiness(session: Session) -> Optional[FlowError]:
        """
        Check if session is ready for submission.
        
        Returns FlowError if not ready, None if ready.
        """
        answer_count = len(session.data.answers)
        min_required = FailurePolicy.MIN_ANSWERS_FOR_SUBMIT
        
        if answer_count < min_required:
            return FailurePolicy.handle_insufficient_answers(
                session, answer_count, min_required
            )
        
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  RECOVERY STRATEGIES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RecoveryStrategy:
    """Recovery strategy for error types."""
    retry_allowed: bool
    max_retries: int
    backoff_seconds: float
    alternative_action: Optional[str]


RECOVERY_STRATEGIES: Dict[ErrorCode, RecoveryStrategy] = {
    # Validation errors: fix input, retry immediately
    ErrorCode.VALIDATION_FAILED: RecoveryStrategy(True, 3, 0.0, None),
    ErrorCode.INVALID_SESSION_ID: RecoveryStrategy(False, 0, 0.0, "POST /session/start"),
    ErrorCode.MISSING_REQUIRED_FIELD: RecoveryStrategy(True, 3, 0.0, None),
    ErrorCode.INVALID_ANSWER_VALUE: RecoveryStrategy(True, 3, 0.0, None),
    
    # State errors: check state, use correct action
    ErrorCode.INVALID_TRANSITION: RecoveryStrategy(False, 0, 0.0, None),
    ErrorCode.SESSION_NOT_FOUND: RecoveryStrategy(False, 0, 0.0, "POST /session/start"),
    ErrorCode.SESSION_EXPIRED: RecoveryStrategy(False, 0, 0.0, "POST /session/start"),
    ErrorCode.SESSION_ALREADY_CLOSED: RecoveryStrategy(False, 0, 0.0, "POST /session/start"),
    ErrorCode.INSUFFICIENT_ANSWERS: RecoveryStrategy(True, 1, 0.0, "POST /assessment/answer"),
    
    # Processing errors: retry with backoff
    ErrorCode.VALIDATION_STAGE_FAILED: RecoveryStrategy(True, 2, 1.0, None),
    ErrorCode.SCORING_STAGE_FAILED: RecoveryStrategy(True, 2, 1.0, None),
    ErrorCode.DECISION_STAGE_FAILED: RecoveryStrategy(True, 2, 1.0, None),
    ErrorCode.EXPLAIN_STAGE_FAILED: RecoveryStrategy(True, 2, 1.0, None),
    ErrorCode.INTERNAL_ERROR: RecoveryStrategy(True, 1, 2.0, "POST /session/start"),
    
    # Timeout errors: retry with backoff
    ErrorCode.STAGE_TIMEOUT: RecoveryStrategy(True, 2, 2.0, None),
    ErrorCode.SESSION_TIMEOUT: RecoveryStrategy(False, 0, 0.0, "POST /session/start"),
}


def get_recovery_strategy(error: FlowError) -> RecoveryStrategy:
    """Get recovery strategy for error."""
    return RECOVERY_STRATEGIES.get(
        error.error_code,
        RecoveryStrategy(False, 0, 0.0, "POST /session/start"),
    )

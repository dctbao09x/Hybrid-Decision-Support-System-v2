# backend/flow/api_contract.py
"""
ONE-BUTTON FLOW: API Contract Specification
===========================================

FROZEN API ENDPOINTS:
    POST /session/start      → Create session, move to SESSION_CREATED
    POST /assessment/answer  → Submit answer, ASSESSMENT_RUNNING
    POST /assessment/submit  → Submit assessment, triggers VALIDATION → SCORING → DECISION → EXPLAIN → RESULT
    GET  /result             → Get final result (idempotent)

CONSTRAINTS:
    - NO chat-style API (no streaming, no conversational endpoints)
    - ALL operations are request/response (synchronous)
    - ALL decisions are local deterministic
    - NO external API calls during flow

JSON SCHEMA COMPLIANCE:
    - All inputs validated by Pydantic v2
    - All outputs conform to frozen schemas
    - Backward compatible versioning

Author: System Architecture Team
Date: 2026-02-21
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger("flow.api_contract")


# ═══════════════════════════════════════════════════════════════════════════════
#  STRICT MODE BASE CLASS (PRODUCTION HARDENING)
# ═══════════════════════════════════════════════════════════════════════════════

class StrictBaseModel(BaseModel):
    """
    Base model with strict validation for production hardening.
    
    HARDENING RULES:
        - forbid_extra: No unexpected fields allowed
        - validate_assignment: Validate on attribute assignment
        - strict: No implicit type coercion
        - validate_default: Validate default values
    """
    model_config = ConfigDict(
        extra="forbid",           # No unknown fields
        validate_assignment=True,  # Validate on assignment
        strict=True,              # No implicit type coercion
        validate_default=True,    # Validate defaults
        frozen=False,             # Allow assignment for response building
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  II. API CONTRACT SPECIFICATION — INPUT SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
#  POST /session/start
# ─────────────────────────────────────────────────────────────────────────────

class SessionStartRequest(StrictBaseModel):
    """
    POST /session/start — Request Schema
    
    Creates a new assessment session.
    
    INPUT:
        {
            "user_id": "optional-user-id",      // Optional: for tracking
            "locale": "vi-VN",                   // Optional: localization
            "metadata": {}                       // Optional: client metadata
        }
    
    STRICT MODE: No implicit type coercion, no extra fields.
    """
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        strict=False,  # Allow string coercion for locale
    )
    
    user_id: Optional[str] = Field(
        default=None,
        description="Optional user identifier for tracking",
        max_length=128,
    )
    locale: str = Field(
        default="vi-VN",
        description="Locale for response localization",
        pattern=r"^[a-z]{2}-[A-Z]{2}$",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional client metadata",
    )


class SessionStartResponse(StrictBaseModel):
    """
    POST /session/start — Response Schema
    
    OUTPUT:
        {
            "session_id": "uuid",
            "state": "session_created",
            "next_action": "submit_answer",
            "questions": [...],
            "created_at": 1708502400.0
        }
    """
    session_id: str = Field(description="Unique session identifier (UUID)")
    state: Literal["session_created"] = Field(description="Current session state")
    next_action: Literal["submit_answer"] = Field(description="Required next action")
    questions: List[Dict[str, Any]] = Field(
        description="Assessment questions to answer",
        default_factory=list,
    )
    created_at: float = Field(description="Unix timestamp of session creation")


# ─────────────────────────────────────────────────────────────────────────────
#  POST /assessment/answer
# ─────────────────────────────────────────────────────────────────────────────

class AnswerValue(StrictBaseModel):
    """
    Single answer value (supports multiple types).
    
    STRICT VALIDATION:
        - Likert scale: 1-7 only (no silent fallback)
        - response_time_ms: >= 0 (required, not optional with silent default)
    """
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        strict=True,  # STRICT: No implicit coercion for answer values
    )
    
    question_id: str = Field(description="Question identifier")
    value: Union[int, str, List[str], float] = Field(description="Answer value")
    response_time_ms: float = Field(
        ge=0,
        description="Time taken to answer in milliseconds (REQUIRED)",
    )
    
    @field_validator("value")
    @classmethod
    def validate_value_range(cls, v):
        """
        Validate Likert scale values are in range.
        
        STRICT: No silent fallback. Invalid values raise error.
        """
        if isinstance(v, int) and not (1 <= v <= 7):
            raise ValueError(
                f"Likert scale value must be between 1 and 7. Got: {v}. "
                "No silent fallback allowed."
            )
        return v


class AssessmentAnswerRequest(StrictBaseModel):
    """
    POST /assessment/answer — Request Schema
    
    Submit one or more answers to the assessment.
    
    INPUT:
        {
            "session_id": "uuid",
            "answers": [
                {
                    "question_id": "q1",
                    "value": 5,
                    "response_time_ms": 2500  // REQUIRED, no default
                }
            ]
        }
    
    STRICT MODE: session_id and answers are REQUIRED.
    """
    session_id: str = Field(description="Session identifier (REQUIRED)")
    answers: List[AnswerValue] = Field(
        description="List of answers to submit (REQUIRED)",
        min_length=1,
        max_length=50,
    )


class AssessmentAnswerResponse(StrictBaseModel):
    """
    POST /assessment/answer — Response Schema
    
    OUTPUT:
        {
            "session_id": "uuid",
            "state": "assessment_running",
            "answers_recorded": 5,
            "total_questions": 20,
            "progress_percent": 25.0,
            "can_submit": false
        }
    """
    session_id: str = Field(description="Session identifier")
    state: Literal["assessment_running"] = Field(description="Current state")
    answers_recorded: int = Field(ge=0, description="Total answers recorded")
    total_questions: int = Field(ge=0, description="Total questions in assessment")
    progress_percent: float = Field(ge=0, le=100, description="Progress percentage")
    can_submit: bool = Field(description="Whether assessment can be submitted")


# ─────────────────────────────────────────────────────────────────────────────
#  POST /assessment/submit
# ─────────────────────────────────────────────────────────────────────────────

class AssessmentSubmitRequest(StrictBaseModel):
    """
    POST /assessment/submit — Request Schema
    
    Submit the assessment for processing.
    Triggers: VALIDATION → SCORING → DECISION → EXPLAIN → RESULT
    
    INPUT:
        {
            "session_id": "uuid",           // REQUIRED
            "user_profile": {                // REQUIRED (no empty default)
                "skills": ["python", "java"],
                "interests": ["AI", "Data Science"],
                "education_level": "Master"
            }
        }
    
    STRICT MODE: user_profile is REQUIRED unless explicitly optional.
    """
    session_id: str = Field(description="Session identifier (REQUIRED)")
    user_profile: Dict[str, Any] = Field(
        description="User profile for scoring (REQUIRED)",
    )
    
    @model_validator(mode="after")
    def validate_user_profile_required(self):
        """
        Validate user_profile has required fields.
        
        STRICT: No silent empty default.
        """
        if not self.user_profile:
            raise ValueError(
                "user_profile is required and cannot be empty. "
                "No silent fallback to empty dict."
            )
        return self


class ScoreBreakdown(StrictBaseModel):
    """Score breakdown by component. STRICT: All fields required."""
    study: float = Field(ge=0, le=1, description="Study score [0,1] (REQUIRED)")
    interest: float = Field(ge=0, le=1, description="Interest score [0,1] (REQUIRED)")
    market: float = Field(ge=0, le=1, description="Market score [0,1] (REQUIRED)")
    growth: float = Field(ge=0, le=1, description="Growth score [0,1] (REQUIRED)")
    risk: float = Field(ge=0, le=1, description="Risk score [0,1] (REQUIRED)")


class CareerResult(StrictBaseModel):
    """
    Single career result.
    
    INVARIANT: Ranking order is immutable after SIMGR scoring.
    final_score reflects raw SIMGR score for ordering.
    """
    name: str = Field(description="Career name (REQUIRED)")
    final_score: float = Field(ge=0, le=1, description="Final weighted score (raw SIMGR, for ranking)")
    rank: int = Field(ge=1, description="Ranking position (immutable after SIMGR)")
    breakdown: ScoreBreakdown = Field(description="Score breakdown by component (REQUIRED)")
    flags: List[str] = Field(default_factory=list, description="Rule engine flags (metadata only)")
    warnings: List[str] = Field(default_factory=list, description="Warnings (metadata only)")
    # Raw score preserved for determinism verification
    raw_score: Optional[float] = Field(default=None, description="Raw SIMGR score (for checksum)")


class QualityMetrics(StrictBaseModel):
    """Data quality metrics. STRICT: All fields required with valid ranges."""
    confidence_score: float = Field(ge=0, le=1, description="Confidence [0,1] (REQUIRED)")
    confidence_band: Literal["high", "medium", "low", "critical"] = Field(
        description="Confidence band (REQUIRED)"
    )
    speed_penalty: float = Field(ge=0, le=1, description="Speed anomaly penalty (REQUIRED)")
    contradiction_penalty: float = Field(ge=0, le=1, description="Contradiction penalty (REQUIRED)")
    uniformity_penalty: float = Field(ge=0, le=1, description="Uniformity penalty (REQUIRED)")
    entropy_penalty: float = Field(ge=0, le=1, description="Entropy penalty (REQUIRED)")


class AssessmentSubmitResponse(StrictBaseModel):
    """
    POST /assessment/submit — Response Schema
    
    OUTPUT:
        {
            "session_id": "uuid",
            "state": "result",
            "status": "completed",
            "careers": [...],
            "quality": {...},
            "explanation": {...},
            "result_url": "/result?session_id=uuid",
            "checksum": "sha256..."  // Deterministic verification
        }
    
    INVARIANT: careers array order is immutable (from SIMGR).
    """
    session_id: str = Field(description="Session identifier")
    state: Literal["result"] = Field(description="Final state")
    status: Literal["completed", "partial", "error"] = Field(description="Completion status")
    careers: List[CareerResult] = Field(description="Ranked career results (order immutable)")
    quality: QualityMetrics = Field(description="Data quality metrics (REQUIRED)")
    explanation: Dict[str, Any] = Field(
        description="Human-readable explanation",
        default_factory=dict,
    )
    result_url: str = Field(description="URL to fetch result again")
    # Deterministic checksum for verification
    checksum: Optional[str] = Field(
        default=None,
        description="SHA256 checksum for deterministic verification",
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /result
# ─────────────────────────────────────────────────────────────────────────────

class ResultRequest(StrictBaseModel):
    """
    GET /result — Request Schema (query parameters)
    
    INPUT:
        ?session_id=uuid  // REQUIRED
    
    STRICT: session_id is REQUIRED.
    """
    session_id: str = Field(description="Session identifier (REQUIRED)")


class ResultResponse(StrictBaseModel):
    """
    GET /result — Response Schema
    
    Idempotent: Always returns same result for completed session.
    DETERMINISTIC: Same input → same output → same checksum.
    
    OUTPUT:
        {
            "session_id": "uuid",
            "state": "result",
            "status": "completed",
            "careers": [...],
            "quality": {...},
            "explanation": {...},
            "completed_at": 1708502500.0,
            "checksum": "sha256..."  // For deterministic verification
        }
    
    INVARIANT: Multiple GET calls return identical response.
    """
    session_id: str = Field(description="Session identifier")
    state: str = Field(description="Current session state")
    status: str = Field(description="Session status")
    careers: List[CareerResult] = Field(
        default_factory=list,
        description="Ranked career results (order immutable)",
    )
    quality: Optional[QualityMetrics] = Field(
        default=None,
        description="Quality metrics (if completed)",
    )
    explanation: Dict[str, Any] = Field(
        default_factory=dict,
        description="Explanation (if completed)",
    )
    completed_at: Optional[float] = Field(
        default=None,
        description="Completion timestamp (if completed)",
    )
    # Deterministic checksum
    checksum: Optional[str] = Field(
        default=None,
        description="SHA256 checksum for deterministic verification",
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  ERROR RESPONSE SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════

class ErrorDetail(StrictBaseModel):
    """Error detail structure. STRICT: code and message required."""
    code: str = Field(description="Error code (REQUIRED)")
    message: str = Field(description="Human-readable error message (REQUIRED)")
    field: Optional[str] = Field(default=None, description="Field that caused error")


class ErrorResponse(StrictBaseModel):
    """
    Standard error response schema.
    
    OUTPUT:
        {
            "error": true,
            "code": "INVALID_TRANSITION",
            "message": "Cannot submit answer in current state",
            "details": [...],
            "session_id": "uuid",
            "current_state": "init"
        }
    
    STRICT: error, code, message are REQUIRED.
    """
    error: Literal[True] = Field(default=True, description="Error flag (always true)")
    code: str = Field(description="Error code (REQUIRED)")
    message: str = Field(description="Error message (REQUIRED)")
    details: List[ErrorDetail] = Field(default_factory=list, description="Error details")
    session_id: Optional[str] = Field(default=None, description="Session ID if applicable")
    current_state: Optional[str] = Field(default=None, description="Current state if applicable")


# ═══════════════════════════════════════════════════════════════════════════════
#  CONTRACT VALIDATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def validate_session_start(data: Dict[str, Any]) -> SessionStartRequest:
    """Validate session start request."""
    return SessionStartRequest.model_validate(data)


def validate_assessment_answer(data: Dict[str, Any]) -> AssessmentAnswerRequest:
    """Validate assessment answer request."""
    return AssessmentAnswerRequest.model_validate(data)


def validate_assessment_submit(data: Dict[str, Any]) -> AssessmentSubmitRequest:
    """Validate assessment submit request."""
    return AssessmentSubmitRequest.model_validate(data)


def validate_result_request(session_id: str) -> ResultRequest:
    """Validate result request."""
    return ResultRequest(session_id=session_id)


# ═══════════════════════════════════════════════════════════════════════════════
#  API VERSION
# ═══════════════════════════════════════════════════════════════════════════════

API_VERSION = "1.0.0"
API_PREFIX = "/api/v1/flow"

ENDPOINT_REGISTRY = {
    "session_start": {
        "method": "POST",
        "path": f"{API_PREFIX}/session/start",
        "request": SessionStartRequest,
        "response": SessionStartResponse,
    },
    "assessment_answer": {
        "method": "POST",
        "path": f"{API_PREFIX}/assessment/answer",
        "request": AssessmentAnswerRequest,
        "response": AssessmentAnswerResponse,
    },
    "assessment_submit": {
        "method": "POST",
        "path": f"{API_PREFIX}/assessment/submit",
        "request": AssessmentSubmitRequest,
        "response": AssessmentSubmitResponse,
    },
    "result": {
        "method": "GET",
        "path": f"{API_PREFIX}/result",
        "request": ResultRequest,
        "response": ResultResponse,
    },
}

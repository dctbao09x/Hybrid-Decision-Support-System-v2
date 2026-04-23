# backend/feedback/schemas.py
"""
Feedback API Schemas
====================

Pydantic schemas for feedback API endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

from pydantic import BaseModel, Field, field_validator, ConfigDict


# ==============================================================================
# ENUMS
# ==============================================================================

class FeedbackStatusEnum(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED = "flagged"


class FeedbackSourceEnum(str, Enum):
    WEB_UI = "web_ui"
    API = "api"
    ADMIN = "admin"
    BATCH = "batch"


# ==============================================================================
# REQUEST SCHEMAS
# ==============================================================================

class CorrectionData(BaseModel):
    """Correction data submitted by user."""
    
    correct_career: str = Field(..., min_length=1, description="Corrected career prediction")
    skill_adjustments: Optional[Dict[str, Any]] = Field(None, description="Skill score adjustments")
    additional_context: Optional[str] = Field(None, description="Additional context for correction")
    
    model_config = ConfigDict(extra="allow")


class FeedbackSubmitRequest(BaseModel):
    """
    POST /api/v1/feedback
    
    Submit feedback for a trace.
    
    RETRAIN-GRADE REQUIREMENTS (2026-02-20):
    All new fields are REQUIRED for ML retraining pipeline.
    Missing fields will result in HTTP 422.
    """
    
    # === EXISTING FIELDS (backward compatible) ===
    trace_id: str = Field(..., min_length=1, description="Trace ID (required)")
    rating: int = Field(..., ge=1, le=5, description="Rating 1-5")
    correction: Optional[Dict[str, Any]] = Field(None, description="Correction data")
    reason: Optional[str] = Field(None, description="Reason for feedback")
    user_id: Optional[str] = Field(None, description="User ID for tracking")
    
    # === NEW REQUIRED FIELDS (retrain-grade) ===
    career_id: str = Field(..., min_length=1, description="Career being rated (REQUIRED)")
    rank_position: int = Field(..., ge=1, description="Rank position at feedback time (REQUIRED, >= 1)")
    score_snapshot: Dict[str, float] = Field(..., description="Score snapshot at feedback time (REQUIRED, must include matchScore)")
    profile_snapshot: Dict[str, Any] = Field(..., description="User profile snapshot (REQUIRED, cannot be empty)")
    model_version: str = Field(..., min_length=1, description="Model version used (REQUIRED)")
    explicit_accept: bool = Field(..., description="True if rating >= 4, False if rating <= 2 (REQUIRED)")
    
    # === NEW OPTIONAL FIELDS ===
    kb_version: Optional[str] = Field(None, description="Knowledge base version")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Model confidence (0-1)")
    session_id: Optional[str] = Field(None, description="Session ID for tracking")
    
    @field_validator("trace_id")
    @classmethod
    def validate_trace_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("trace_id cannot be empty")
        return v.strip()
    
    @field_validator("career_id")
    @classmethod
    def validate_career_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("career_id cannot be empty - must specify which career is being rated")
        return v.strip()
    
    @field_validator("rank_position")
    @classmethod
    def validate_rank_position(cls, v: int) -> int:
        if v < 1:
            raise ValueError("rank_position must be >= 1 (1-indexed ranking)")
        return v
    
    @field_validator("score_snapshot")
    @classmethod
    def validate_score_snapshot(cls, v: Dict[str, float]) -> Dict[str, float]:
        if not v:
            raise ValueError("score_snapshot cannot be empty")
        if "matchScore" not in v:
            raise ValueError("score_snapshot must contain 'matchScore' key")
        return v
    
    @field_validator("profile_snapshot")
    @classmethod
    def validate_profile_snapshot(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not v:
            raise ValueError("profile_snapshot cannot be empty - must contain user profile data")
        return v
    
    @field_validator("model_version")
    @classmethod
    def validate_model_version(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("model_version cannot be empty")
        return v.strip()


class FeedbackReviewRequest(BaseModel):
    """
    POST /api/v1/feedback/review
    
    Review a feedback entry (admin only).
    """
    
    feedback_id: str = Field(..., description="Feedback ID to review")
    action: str = Field(..., pattern="^(approve|reject|flag)$", description="Review action")
    notes: Optional[str] = Field(None, max_length=1000, description="Review notes")
    reviewer_id: str = Field(..., description="Reviewer ID")


class FeedbackExportRequest(BaseModel):
    """
    GET /api/v1/feedback/export
    
    Export feedback data.
    """
    
    status: Optional[FeedbackStatusEnum] = Field(None, description="Filter by status")
    from_date: Optional[str] = Field(None, description="From date (ISO format)")
    to_date: Optional[str] = Field(None, description="To date (ISO format)")
    limit: int = Field(1000, ge=1, le=10000, description="Max records")
    format: str = Field("json", pattern="^(json|csv)$", description="Export format")


class FeedbackSyncRequest(BaseModel):
    """
    POST /api/v1/feedback/sync-training
    
    Sync approved feedback to training pipeline.
    """
    
    quality_threshold: float = Field(0.5, ge=0, le=1, description="Min quality score")
    max_samples: int = Field(100, ge=1, le=10000, description="Max samples to sync")
    approver_id: Optional[str] = Field(None, description="Approver ID for audit")


# ==============================================================================
# RESPONSE SCHEMAS
# ==============================================================================

class FeedbackSubmitResponse(BaseModel):
    """Response for feedback submission."""
    
    feedback_id: str
    trace_id: str
    status: str
    message: str


class FeedbackDetailResponse(BaseModel):
    """Detailed feedback response."""
    
    feedback_id: str
    trace_id: str
    rating: int
    correction: Dict[str, Any]
    reason: str
    status: str
    created_at: str
    reviewed_at: Optional[str] = None
    reviewer_id: Optional[str] = None
    review_notes: Optional[str] = None
    linked_train_id: Optional[str] = None
    quality_score: float = 0.0


class FeedbackListResponse(BaseModel):
    """List of feedback entries."""
    
    items: List[FeedbackDetailResponse]
    total: int
    limit: int
    offset: int


class TraceDetailResponse(BaseModel):
    """Trace detail for feedback linking."""
    
    trace_id: str
    user_id: Optional[str] = None
    input_profile: Dict[str, Any]
    kb_snapshot_version: Optional[str] = None
    model_version: str
    rule_path: List[Any] = []
    score_vector: Dict[str, Any] = {}
    timestamp: str
    predicted_career: Optional[str] = None
    predicted_confidence: float = 0.0
    top_careers: List[str] = []
    reasons: List[str] = []
    feedback_entries: List[Dict[str, Any]] = []


class FeedbackStatsResponse(BaseModel):
    """
    GET /api/v1/feedback/stats
    
    Feedback analytics and KPIs.
    """
    
    # Volume metrics
    total_feedback: int = 0
    pending_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    flagged_count: int = 0
    
    # Rate metrics
    feedback_rate: float = 0.0  # Feedback / Total traces
    approval_rate: float = 0.0  # Approved / Total feedback
    correction_rate: float = 0.0  # Corrections different from prediction
    
    # Quality metrics
    avg_quality_score: float = 0.0
    avg_rating: float = 0.0
    
    # Training impact
    training_samples_generated: int = 0
    training_samples_used: int = 0
    retrain_impact: float = 0.0
    
    # Drift signals
    drift_signal: float = 0.0
    career_distribution: Dict[str, int] = {}
    
    # Time metrics
    avg_review_time_hours: float = 0.0
    period_start: Optional[str] = None
    period_end: Optional[str] = None


class FeedbackExportResponse(BaseModel):
    """Response for feedback export."""
    
    format: str
    total_records: int
    export_url: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None


class FeedbackReviewResponse(BaseModel):
    """Response for feedback review."""
    
    feedback_id: str
    previous_status: str
    new_status: str
    reviewer_id: str
    reviewed_at: str


class FeedbackSyncResponse(BaseModel):
    """Response for feedback sync to training."""
    
    batch_id: str
    samples_created: int
    samples_skipped: int
    quality_distribution: Dict[str, int] = {}
    message: str


class TrainingCandidateResponse(BaseModel):
    """Training candidate data."""
    
    train_id: str
    trace_id: str
    feedback_id: str
    input: Dict[str, Any]
    target: str
    original_prediction: str
    kb_version: Optional[str] = None
    model_version: str
    quality_score: float = 0.0
    created_at: str


# ==============================================================================
# VALIDATION RESPONSE
# ==============================================================================

class ValidationError(BaseModel):
    """Validation error detail."""
    
    field: str
    message: str
    code: str


class ValidationResponse(BaseModel):
    """Validation result."""
    
    valid: bool
    errors: List[ValidationError] = []
    warnings: List[str] = []

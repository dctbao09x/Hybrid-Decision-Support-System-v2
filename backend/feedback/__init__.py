# backend/feedback/__init__.py
"""
Feedback Loop System
====================

Closed-loop feedback system for ML training data generation.

Components:
  - models: Data models (TraceRecord, FeedbackEntry, TrainingCandidate)
  - schemas: API schemas (Pydantic)
  - storage: SQLite persistence layer
  - router: FastAPI endpoints
  - linker: Trace linking engine
  - validation: Input validation & spam detection
  - analytics: KPI & drift detection
"""

from backend.feedback.models import (
    TraceRecord,
    FeedbackEntry,
    FeedbackStatus,
    FeedbackSource,
    TrainingCandidate,
    TrainingStatus,
    FeedbackAuditLog,
)

from backend.feedback.schemas import (
    FeedbackSubmitRequest,
    FeedbackSubmitResponse,
    FeedbackReviewRequest,
    FeedbackReviewResponse,
    FeedbackStatsResponse,
    FeedbackListResponse,
    FeedbackDetailResponse,
    TraceDetailResponse,
    FeedbackSyncRequest,
    FeedbackSyncResponse,
    TrainingCandidateResponse,
)

from backend.feedback.storage import FeedbackStorage, get_feedback_storage
from backend.feedback.linker import FeedbackLinker, QualityFilter
from backend.feedback.validation import FeedbackValidator, ValidationError, ConsistencyChecker
from backend.feedback.analytics import FeedbackAnalytics, RetrainImpactAnalyzer

__all__ = [
    # Models
    "TraceRecord",
    "FeedbackEntry",
    "FeedbackStatus",
    "FeedbackSource",
    "TrainingCandidate",
    "TrainingStatus",
    "FeedbackAuditLog",
    # Schemas
    "FeedbackSubmitRequest",
    "FeedbackSubmitResponse",
    "FeedbackReviewRequest",
    "FeedbackReviewResponse",
    "FeedbackStatsResponse",
    "FeedbackListResponse",
    "FeedbackDetailResponse",
    "TraceDetailResponse",
    "FeedbackSyncRequest",
    "FeedbackSyncResponse",
    "TrainingCandidateResponse",
    # Storage
    "FeedbackStorage",
    "get_feedback_storage",
    # Services
    "FeedbackLinker",
    "QualityFilter",
    "FeedbackValidator",
    "ValidationError",
    "ConsistencyChecker",
    "FeedbackAnalytics",
    "RetrainImpactAnalyzer",
]

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


class FeedbackStatus(str, Enum):
    NEW = "new"
    REVIEWED = "reviewed"
    CLOSED = "closed"
    ARCHIVED = "archived"


class FeedbackPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FeedbackMeta(BaseModel):
    page: str
    version: str
    sessionId: str


class FeedbackSubmitRequest(BaseModel):
    userId: str = Field(..., min_length=1, max_length=128)
    email: EmailStr
    rating: int = Field(..., ge=1, le=5)
    category: str = Field(..., min_length=2, max_length=64)
    message: str = Field(..., min_length=5, max_length=2000)
    screenshot: Optional[str] = None
    meta: FeedbackMeta


class FeedbackRecord(BaseModel):
    id: str
    user_id: str
    email: str
    rating: int
    category: str
    message: str
    status: FeedbackStatus
    priority: FeedbackPriority
    created_at: str
    reviewed_by: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)
    screenshot: Optional[str] = None


class FeedbackListResponse(BaseModel):
    items: List[FeedbackRecord]
    total: int
    page: int
    pageSize: int


class UpdateStatusRequest(BaseModel):
    status: FeedbackStatus
    priority: Optional[FeedbackPriority] = None


class AssignReviewerRequest(BaseModel):
    reviewer: str = Field(..., min_length=2, max_length=64)


class FeedbackQuery(BaseModel):
    """
    Query parameters for filtering feedback.
    
    RETRAIN-GRADE FILTERS (2026-02-20):
    - career_id: Filter by career
    - model_version: Filter by model version
    - explicit_accept: Filter by accept/reject signal
    - min_confidence / max_confidence: Filter by confidence range
    """
    # Existing filters
    status: Optional[FeedbackStatus] = None
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    category: Optional[str] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    search: Optional[str] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    
    # === RETRAIN-GRADE FILTERS (2026-02-20) ===
    career_id: Optional[str] = Field(default=None, description="Filter by career ID")
    model_version: Optional[str] = Field(default=None, description="Filter by model version")
    explicit_accept: Optional[bool] = Field(default=None, description="Filter by accept/reject signal")
    min_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Minimum confidence")
    max_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Maximum confidence")

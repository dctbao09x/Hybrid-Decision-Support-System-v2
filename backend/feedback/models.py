# backend/feedback/models.py
"""
Feedback Data Models
====================

Core data models for the feedback loop system.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


# ==============================================================================
# ENUMS
# ==============================================================================

class FeedbackStatus(str, Enum):
    """Feedback review status."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED = "flagged"


class FeedbackSource(str, Enum):
    """Source of feedback."""
    WEB_UI = "web_ui"
    API = "api"
    ADMIN = "admin"
    BATCH = "batch"


class TrainingStatus(str, Enum):
    """Training data status."""
    CANDIDATE = "candidate"
    QUEUED = "queued"
    USED = "used"
    EXCLUDED = "excluded"


# ==============================================================================
# TRACE RECORD (TASK 1)
# ==============================================================================

@dataclass
class TraceRecord:
    """
    Standardized trace record for every inference.
    
    TRACE–FEEDBACK CONTRACT:
    Every inference must produce a TraceRecord with:
      - trace_id: Unique identifier
      - user_id: User who made request (optional)
      - input_profile: Input features/profile
      - kb_snapshot_version: KB version used
      - model_version: Model version used
      - rule_path: Rules applied
      - score_vector: Detailed scores
      - timestamp: When inference ran
    """
    
    # Required fields
    trace_id: str
    input_profile: Dict[str, Any]
    model_version: str
    timestamp: str
    
    # Optional fields
    user_id: Optional[str] = None
    kb_snapshot_version: Optional[str] = None
    rule_path: List[str] = field(default_factory=list)
    score_vector: Dict[str, float] = field(default_factory=dict)
    
    # Inference results
    predicted_career: Optional[str] = None
    predicted_confidence: float = 0.0
    top_careers: List[Dict[str, Any]] = field(default_factory=list)
    
    # XAI results
    reasons: List[str] = field(default_factory=list)
    xai_meta: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    latency_ms: float = 0.0
    stage_timings: Dict[str, float] = field(default_factory=dict)
    request_hash: str = ""
    
    def __post_init__(self):
        if not self.request_hash:
            self.request_hash = self._compute_hash()
    
    def _compute_hash(self) -> str:
        """Compute hash of input profile for deduplication."""
        data = json.dumps(self.input_profile, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    @staticmethod
    def generate_trace_id(user_id: Optional[str] = None) -> str:
        """Generate unique trace_id."""
        ts = int(datetime.now().timestamp() * 1000)
        suffix = user_id[:8] if user_id else uuid.uuid4().hex[:8]
        return f"trace_{ts}_{suffix}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "trace_id": self.trace_id,
            "user_id": self.user_id,
            "input_profile": self.input_profile,
            "kb_snapshot_version": self.kb_snapshot_version,
            "model_version": self.model_version,
            "rule_path": self.rule_path,
            "score_vector": self.score_vector,
            "timestamp": self.timestamp,
            "predicted_career": self.predicted_career,
            "predicted_confidence": self.predicted_confidence,
            "top_careers": self.top_careers,
            "reasons": self.reasons,
            "xai_meta": self.xai_meta,
            "latency_ms": self.latency_ms,
            "stage_timings": self.stage_timings,
            "request_hash": self.request_hash,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraceRecord":
        """Create from dictionary."""
        return cls(
            trace_id=data["trace_id"],
            user_id=data.get("user_id"),
            input_profile=data.get("input_profile", {}),
            kb_snapshot_version=data.get("kb_snapshot_version"),
            model_version=data["model_version"],
            rule_path=data.get("rule_path", []),
            score_vector=data.get("score_vector", {}),
            timestamp=data["timestamp"],
            predicted_career=data.get("predicted_career"),
            predicted_confidence=data.get("predicted_confidence", 0.0),
            top_careers=data.get("top_careers", []),
            reasons=data.get("reasons", []),
            xai_meta=data.get("xai_meta", {}),
            latency_ms=data.get("latency_ms", 0.0),
            stage_timings=data.get("stage_timings", {}),
            request_hash=data.get("request_hash", ""),
        )


# ==============================================================================
# FEEDBACK ENTRY (TASK 2)
# ==============================================================================

@dataclass
class FeedbackEntry:
    """
    User feedback on a prediction.
    
    FEEDBACK DATA MODEL:
      - id: Auto-generated
      - trace_id: FK to trace (NOT NULL)
      - rating: 1-5 stars
      - correction: Corrected prediction (JSON)
      - reason: User explanation
      - status: Review status
      - reviewer_id: Admin who reviewed
      - created_at: Submission time
      - linked_train_id: Training sample if approved
    
    RETRAIN-GRADE FIELDS (2026-02-20):
      - career_id: Career being rated
      - rank_position: Rank at feedback time
      - score_snapshot: Scores at feedback time
      - profile_snapshot: User profile snapshot
      - model_version: Model version used
      - explicit_accept: Accept/Reject signal
    """
    
    # Primary key
    id: str
    
    # Required foreign key - CANNOT be NULL
    trace_id: str
    
    # Core feedback data
    rating: int  # 1-5
    correction: Dict[str, Any]  # Corrected values
    reason: str  # User explanation
    
    # Metadata
    source: FeedbackSource = FeedbackSource.WEB_UI
    created_at: str = ""
    
    # Review workflow
    status: FeedbackStatus = FeedbackStatus.PENDING
    reviewer_id: Optional[str] = None
    reviewed_at: Optional[str] = None
    review_notes: Optional[str] = None
    
    # Training linkage
    linked_train_id: Optional[str] = None
    training_status: TrainingStatus = TrainingStatus.CANDIDATE
    
    # Quality metrics
    quality_score: float = 0.0
    consistency_score: float = 0.0
    
    # === RETRAIN-GRADE FIELDS (2026-02-20) ===
    career_id: str = ""
    rank_position: int = 0
    score_snapshot: Dict[str, float] = field(default_factory=dict)
    profile_snapshot: Dict[str, Any] = field(default_factory=dict)
    model_version: str = ""
    kb_version: Optional[str] = None
    confidence: Optional[float] = None
    explicit_accept: Optional[bool] = None
    session_id: Optional[str] = None
    
    def __post_init__(self):
        if not self.id:
            self.id = f"fb_{int(datetime.now().timestamp() * 1000)}_{uuid.uuid4().hex[:8]}"
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "rating": self.rating,
            "correction": self.correction,
            "reason": self.reason,
            "source": self.source.value,
            "created_at": self.created_at,
            "status": self.status.value,
            "reviewer_id": self.reviewer_id,
            "reviewed_at": self.reviewed_at,
            "review_notes": self.review_notes,
            "linked_train_id": self.linked_train_id,
            "training_status": self.training_status.value,
            "quality_score": self.quality_score,
            "consistency_score": self.consistency_score,
            # Retrain-grade fields
            "career_id": self.career_id,
            "rank_position": self.rank_position,
            "score_snapshot": self.score_snapshot,
            "profile_snapshot": self.profile_snapshot,
            "model_version": self.model_version,
            "kb_version": self.kb_version,
            "confidence": self.confidence,
            "explicit_accept": self.explicit_accept,
            "session_id": self.session_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FeedbackEntry":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            trace_id=data["trace_id"],
            rating=data["rating"],
            correction=data.get("correction", {}),
            reason=data.get("reason", ""),
            source=FeedbackSource(data.get("source", "web_ui")),
            created_at=data.get("created_at", ""),
            status=FeedbackStatus(data.get("status", "pending")),
            reviewer_id=data.get("reviewer_id"),
            reviewed_at=data.get("reviewed_at"),
            review_notes=data.get("review_notes"),
            linked_train_id=data.get("linked_train_id"),
            training_status=TrainingStatus(data.get("training_status", "candidate")),
            quality_score=data.get("quality_score", 0.0),
            consistency_score=data.get("consistency_score", 0.0),
            # Retrain-grade fields
            career_id=data.get("career_id", ""),
            rank_position=data.get("rank_position", 0),
            score_snapshot=data.get("score_snapshot", {}),
            profile_snapshot=data.get("profile_snapshot", {}),
            model_version=data.get("model_version", ""),
            kb_version=data.get("kb_version"),
            confidence=data.get("confidence"),
            explicit_accept=data.get("explicit_accept"),
            session_id=data.get("session_id"),
        )


# ==============================================================================
# TRAINING CANDIDATE (TASK 4)
# ==============================================================================

@dataclass
class TrainingCandidate:
    """
    Training sample generated from approved feedback.
    
    OUTPUT from FeedbackLinker:
      - train_id: Unique training sample ID
      - trace_id: Original trace
      - input: Feature vector
      - target: Corrected label
      - kb_version: KB snapshot version
      - model_version: Model at prediction time
    """
    
    train_id: str
    trace_id: str
    feedback_id: str
    
    # Training data
    input_features: Dict[str, Any]
    target_label: str
    original_prediction: str
    
    # Versions for reproducibility
    kb_version: Optional[str] = None
    model_version: str = ""
    
    # Quality metrics
    quality_score: float = 0.0
    
    # Metadata
    created_at: str = ""
    used_in_training: bool = False
    training_batch_id: Optional[str] = None
    
    def __post_init__(self):
        if not self.train_id:
            self.train_id = f"train_{int(datetime.now().timestamp() * 1000)}_{uuid.uuid4().hex[:8]}"
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "train_id": self.train_id,
            "trace_id": self.trace_id,
            "feedback_id": self.feedback_id,
            "input": self.input_features,
            "target": self.target_label,
            "original_prediction": self.original_prediction,
            "kb_version": self.kb_version,
            "model_version": self.model_version,
            "quality_score": self.quality_score,
            "created_at": self.created_at,
            "used_in_training": self.used_in_training,
            "training_batch_id": self.training_batch_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrainingCandidate":
        """Create from dictionary."""
        return cls(
            train_id=data["train_id"],
            trace_id=data["trace_id"],
            feedback_id=data["feedback_id"],
            input_features=data.get("input", {}),
            target_label=data["target"],
            original_prediction=data.get("original_prediction", ""),
            kb_version=data.get("kb_version"),
            model_version=data.get("model_version", ""),
            quality_score=data.get("quality_score", 0.0),
            created_at=data.get("created_at", ""),
            used_in_training=data.get("used_in_training", False),
            training_batch_id=data.get("training_batch_id"),
        )


# ==============================================================================
# AUDIT LOG
# ==============================================================================

@dataclass
class FeedbackAuditLog:
    """Audit log entry for feedback operations."""
    
    id: str
    timestamp: str
    action: str  # submit, review, approve, reject, sync, delete
    entity_type: str  # feedback, trace, training
    entity_id: str
    user_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    ip_address: Optional[str] = None
    
    def __post_init__(self):
        if not self.id:
            self.id = f"audit_{int(datetime.now().timestamp() * 1000)}_{uuid.uuid4().hex[:8]}"
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "user_id": self.user_id,
            "details": self.details,
            "ip_address": self.ip_address,
        }

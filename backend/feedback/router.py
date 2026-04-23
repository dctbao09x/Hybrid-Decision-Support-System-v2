# backend/feedback/router.py
"""
Feedback Router
===============

FastAPI router for feedback loop system endpoints.
Implements POST/GET /feedback, GET /stats, POST /review, GET /export.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from backend.feedback.models import (
    FeedbackEntry,
    FeedbackStatus,
    FeedbackSource,
    FeedbackAuditLog,
    TrainingStatus,
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
)
from backend.feedback.storage import get_feedback_storage

logger = logging.getLogger("feedback.router")

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])


# ==============================================================================
# FEEDBACK SUBMISSION
# ==============================================================================

@router.post("", response_model=FeedbackSubmitResponse)
@router.post("/", response_model=FeedbackSubmitResponse, include_in_schema=False)
async def submit_feedback(
    request: Request,
    payload: FeedbackSubmitRequest,
):
    """
    Submit user feedback for an inference trace.
    
    Constraints:
      - trace_id MUST exist (no orphan feedback)
      - Rating must be 1-5
      - Only one feedback per trace-user combination
    """
    storage = get_feedback_storage()
    await storage.initialize()
    
    # Validate trace exists
    trace_exists = await storage.trace_exists(payload.trace_id)
    if not trace_exists:
        raise HTTPException(
            status_code=404,
            detail=f"Trace not found: {payload.trace_id}. Feedback must be linked to a valid trace."
        )
    
    # Check for duplicate feedback
    existing = await storage.get_feedback_by_trace(payload.trace_id)
    if existing and payload.user_id:
        for fb in existing:
            # Allow resubmission if previous was rejected
            if fb.status != FeedbackStatus.rejected:
                logger.warning(f"Duplicate feedback attempt for trace {payload.trace_id}")
                # Return existing feedback ID
                return FeedbackSubmitResponse(
                    feedback_id=fb.id,
                    trace_id=payload.trace_id,
                    status=fb.status.value,
                    message="Feedback already exists for this trace",
                )
    
    # Create feedback entry
    feedback_id = f"fb-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    
    feedback = FeedbackEntry(
        id=feedback_id,
        trace_id=payload.trace_id,
        rating=payload.rating,
        correction=payload.correction if payload.correction else {},
        reason=payload.reason or "",
        source=FeedbackSource.web_ui,
        created_at=now,
        status=FeedbackStatus.pending,
        training_status=TrainingStatus.candidate,
        # Retrain-grade fields
        career_id=payload.career_id,
        rank_position=payload.rank_position,
        score_snapshot=payload.score_snapshot,
        profile_snapshot=payload.profile_snapshot,
        model_version=payload.model_version,
        kb_version=payload.kb_version,
        confidence=payload.confidence,
        explicit_accept=payload.explicit_accept,
        session_id=payload.session_id,
    )
    
    await storage.store_feedback(feedback)
    
    # Audit log
    client_ip = request.client.host if request.client else "unknown"
    audit = FeedbackAuditLog(
        id=f"audit-{uuid.uuid4().hex[:12]}",
        timestamp=now,
        action="submit_feedback",
        entity_type="feedback",
        entity_id=feedback_id,
        user_id=payload.user_id,
        details={
            "trace_id": payload.trace_id,
            "rating": payload.rating,
            "career_id": payload.career_id,
            "rank_position": payload.rank_position,
            "model_version": payload.model_version,
            "explicit_accept": payload.explicit_accept,
        },
        ip_address=client_ip,
    )
    await storage.log_audit(audit)
    
    logger.info(f"Feedback submitted: {feedback_id} for trace {payload.trace_id}")
    
    return FeedbackSubmitResponse(
        feedback_id=feedback_id,
        trace_id=payload.trace_id,
        status=FeedbackStatus.pending.value,
        message="Feedback submitted successfully. Pending review.",
    )


@router.get("", response_model=FeedbackListResponse)
async def list_feedback(
    status: Optional[str] = Query(None, description="Filter by status"),
    from_date: Optional[str] = Query(None, description="Filter from date (ISO)"),
    to_date: Optional[str] = Query(None, description="Filter to date (ISO)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List feedback entries with filters."""
    storage = get_feedback_storage()
    await storage.initialize()
    
    status_filter = None
    if status:
        try:
            status_filter = FeedbackStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    items, total = await storage.list_feedback(
        status=status_filter,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
    
    return FeedbackListResponse(
        items=[
            FeedbackDetailResponse(
                feedback_id=fb.id,
                trace_id=fb.trace_id,
                rating=fb.rating,
                correction=fb.correction,
                reason=fb.reason,
                status=fb.status.value,
                created_at=fb.created_at,
                reviewer_id=fb.reviewer_id,
                reviewed_at=fb.reviewed_at,
                review_notes=fb.review_notes,
                linked_train_id=fb.linked_train_id,
                quality_score=fb.quality_score,
            )
            for fb in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


# ==============================================================================
# FEEDBACK REVIEW
# ==============================================================================

@router.post("/review", response_model=FeedbackReviewResponse)
async def review_feedback(
    request: Request,
    payload: FeedbackReviewRequest,
):
    """
    Review feedback: approve, reject, or flag for attention.
    
    Approved feedback becomes training candidate.
    Rejected feedback is archived.
    Flagged feedback requires further review.
    """
    storage = get_feedback_storage()
    await storage.initialize()
    
    # Validate feedback exists
    feedback = await storage.get_feedback(payload.feedback_id)
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")
    
    # Map action to status
    action_status_map = {
        "approve": FeedbackStatus.approved,
        "reject": FeedbackStatus.rejected,
        "flag": FeedbackStatus.flagged,
    }
    
    new_status = action_status_map.get(payload.action)
    if not new_status:
        raise HTTPException(status_code=400, detail=f"Invalid action: {payload.action}")
    
    # Update status
    success = await storage.update_feedback_status(
        feedback_id=payload.feedback_id,
        status=new_status,
        reviewer_id=payload.reviewer_id,
        notes=payload.notes,
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update feedback")
    
    # Audit log
    client_ip = request.client.host if request.client else "unknown"
    await storage.log_audit(FeedbackAuditLog(
        id=f"audit-{uuid.uuid4().hex[:12]}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        action=f"review_{payload.action}",
        entity_type="feedback",
        entity_id=payload.feedback_id,
        user_id=payload.reviewer_id,
        details={"previous_status": feedback.status.value, "new_status": new_status.value},
        ip_address=client_ip,
    ))
    
    logger.info(f"Feedback {payload.feedback_id} reviewed: {payload.action} by {payload.reviewer_id}")
    
    return FeedbackReviewResponse(
        feedback_id=payload.feedback_id,
        previous_status=feedback.status.value,
        new_status=new_status.value,
        reviewer_id=payload.reviewer_id,
        reviewed_at=datetime.now(timezone.utc).isoformat(),
    )


# ==============================================================================
# TRACE LINKING
# ==============================================================================

@router.get("/link/{trace_id}", response_model=TraceDetailResponse)
async def get_trace_with_feedback(trace_id: str):
    """
    Get trace details with linked feedback.
    
    Returns full trace context including:
      - Input profile
      - Model predictions
      - KB snapshot version
      - Rule path
      - XAI metadata
      - All feedback entries
    """
    storage = get_feedback_storage()
    await storage.initialize()
    
    trace = await storage.get_trace(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")
    
    feedback_list = await storage.get_feedback_by_trace(trace_id)
    
    return TraceDetailResponse(
        trace_id=trace.trace_id,
        user_id=trace.user_id,
        input_profile=trace.input_profile,
        kb_snapshot_version=trace.kb_snapshot_version,
        model_version=trace.model_version,
        rule_path=trace.rule_path,
        score_vector=trace.score_vector,
        timestamp=trace.timestamp,
        predicted_career=trace.predicted_career,
        predicted_confidence=trace.predicted_confidence,
        top_careers=trace.top_careers,
        reasons=trace.reasons,
        feedback_entries=[
            {
                "feedback_id": fb.id,
                "rating": fb.rating,
                "correction": fb.correction,
                "status": fb.status.value,
                "created_at": fb.created_at,
            }
            for fb in feedback_list
        ],
    )


# ==============================================================================
# STATISTICS
# ==============================================================================

@router.get("/stats", response_model=FeedbackStatsResponse)
async def get_feedback_stats(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    """
    Get feedback analytics and KPIs.
    
    Returns:
      - feedback_rate: % of inferences with feedback
      - approval_rate: % of feedback approved
      - correction_rate: % with correction != prediction
      - avg_rating: Average user rating
      - training_samples: Generated vs used
    """
    storage = get_feedback_storage()
    await storage.initialize()
    
    stats = await storage.get_feedback_stats(from_date=from_date, to_date=to_date)
    
    # Calculate correction rate
    correction_rate = 0.0
    if stats["approved_count"] > 0:
        # Would need to join with traces to calculate actual correction rate
        correction_rate = 0.5  # Placeholder
    
    return FeedbackStatsResponse(
        total_feedback=stats["total_feedback"],
        pending_count=stats["pending_count"],
        approved_count=stats["approved_count"],
        rejected_count=stats["rejected_count"],
        feedback_rate=round(stats["feedback_rate"], 4),
        approval_rate=round(stats["approval_rate"], 4),
        correction_rate=correction_rate,
        avg_rating=round(stats["avg_rating"], 2),
        avg_quality_score=round(stats["avg_quality_score"], 2),
        training_samples_generated=stats["training_samples_generated"],
        training_samples_used=stats["training_samples_used"],
        retrain_impact=stats["training_samples_used"] / max(stats["training_samples_generated"], 1),
        drift_signal=0.0,  # TODO: Calculate from model drift detector
        career_distribution=stats.get("career_distribution", {}),
    )


# ==============================================================================
# EXPORT
# ==============================================================================

@router.get("/export")
async def export_feedback(
    format: str = Query("json", description="Export format: json|csv"),
    status: Optional[str] = Query(None, description="Filter by status"),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    include_traces: bool = Query(False, description="Include full trace data"),
):
    """
    Export feedback data for analysis.
    
    Formats:
      - json: Full structured data
      - csv: Flat table format
    """
    storage = get_feedback_storage()
    await storage.initialize()
    
    status_filter = None
    if status:
        try:
            status_filter = FeedbackStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    items, _ = await storage.list_feedback(
        status=status_filter,
        from_date=from_date,
        to_date=to_date,
        limit=10000,
    )
    
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        headers = [
            "feedback_id", "trace_id", "rating", "reason", "status",
            "created_at", "reviewed_at", "reviewer_id", "quality_score"
        ]
        if include_traces:
            headers.extend(["predicted_career", "correct_career"])
        writer.writerow(headers)
        
        # Data
        for fb in items:
            row = [
                fb.id, fb.trace_id, fb.rating, fb.reason, fb.status.value,
                fb.created_at, fb.reviewed_at, fb.reviewer_id, fb.quality_score
            ]
            if include_traces:
                trace = await storage.get_trace(fb.trace_id)
                if trace:
                    row.extend([
                        trace.predicted_career,
                        fb.correction.get("correct_career", "")
                    ])
                else:
                    row.extend(["", ""])
            writer.writerow(row)
        
        output.seek(0)
        
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=feedback_export.csv"}
        )
    
    # JSON format
    data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "total": len(items),
        "filters": {
            "status": status,
            "from_date": from_date,
            "to_date": to_date,
        },
        "items": [
            {
                "feedback_id": fb.id,
                "trace_id": fb.trace_id,
                "rating": fb.rating,
                "correction": fb.correction,
                "reason": fb.reason,
                "status": fb.status.value,
                "created_at": fb.created_at,
                "reviewed_at": fb.reviewed_at,
                "reviewer_id": fb.reviewer_id,
                "quality_score": fb.quality_score,
            }
            for fb in items
        ],
    }
    
    return data


# ==============================================================================
# TRAINING SYNC
# ==============================================================================

@router.post("/sync-training", response_model=FeedbackSyncResponse)
async def sync_training_data(
    request: Request,
    payload: FeedbackSyncRequest,
):
    """
    Sync approved feedback to training candidates.
    
    This endpoint:
      1. Fetches approved feedback above quality threshold
      2. Creates training samples with frozen KB version
      3. Returns sync summary for curator review
    
    Note: Does NOT directly write to training set.
    Curator must review and approve sync batch.
    """
    from backend.feedback.linker import FeedbackLinker
    
    storage = get_feedback_storage()
    await storage.initialize()
    
    linker = FeedbackLinker(storage)
    
    result = await linker.generate_training_candidates(
        min_quality=payload.quality_threshold,
        max_samples=payload.max_samples,
    )
    
    # Audit log
    client_ip = request.client.host if request.client else "unknown"
    await storage.log_audit(FeedbackAuditLog(
        id=f"audit-{uuid.uuid4().hex[:12]}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        action="sync_training",
        entity_type="training_candidates",
        entity_id=result.get("batch_id", "unknown"),
        user_id=payload.approver_id,
        details={
            "samples_created": result["created"],
            "quality_threshold": payload.quality_threshold,
        },
        ip_address=client_ip,
    ))
    
    return FeedbackSyncResponse(
        batch_id=result.get("batch_id", ""),
        samples_created=result["created"],
        samples_skipped=result["skipped"],
        quality_distribution=result.get("quality_distribution", {}),
        message=f"Created {result['created']} training candidates. Ready for curator review.",
    )


@router.get("/{feedback_id}", response_model=FeedbackDetailResponse)
async def get_feedback(feedback_id: str):
    """Get feedback details by ID."""
    storage = get_feedback_storage()
    await storage.initialize()

    feedback = await storage.get_feedback(feedback_id)
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    return FeedbackDetailResponse(
        feedback_id=feedback.id,
        trace_id=feedback.trace_id,
        rating=feedback.rating,
        correction=feedback.correction,
        reason=feedback.reason,
        status=feedback.status.value,
        created_at=feedback.created_at,
        reviewer_id=feedback.reviewer_id,
        reviewed_at=feedback.reviewed_at,
        review_notes=feedback.review_notes,
        linked_train_id=feedback.linked_train_id,
        quality_score=feedback.quality_score,
    )

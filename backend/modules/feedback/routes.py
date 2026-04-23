from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Deque, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status

from backend.modules.admin_auth.service import get_admin_auth_service

from .controller import FeedbackController
from .model import AssignReviewerRequest, FeedbackQuery, FeedbackStatus, FeedbackSubmitRequest, UpdateStatusRequest
from .repository import FeedbackRepository
from .service import FeedbackService

_feedback_repo = FeedbackRepository()
_feedback_service = FeedbackService(_feedback_repo, audit_writer=lambda admin_id, action, target_id, ip, details: get_admin_auth_service().write_audit(admin_id, action, target_id, ip, details))
_feedback_controller = FeedbackController(_feedback_service)

public_feedback_router = APIRouter(prefix="/api/feedback", tags=["Feedback"])
admin_feedback_router = APIRouter(prefix="/feedback", tags=["Admin Feedback"])

_submit_history: Dict[str, Deque[float]] = defaultdict(deque)


def _throttle_submit(ip: str, max_hits: int = 20, window_seconds: int = 60) -> None:
    now = time.time()
    q = _submit_history[ip]
    while q and now - q[0] > window_seconds:
        q.popleft()
    if len(q) >= max_hits:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many feedback submissions")
    q.append(now)


def _admin_id(request: Request) -> str:
    ctx = getattr(request.state, "admin", None)
    if not ctx:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin authentication required")
    return str(ctx.get("adminId", "unknown"))


@public_feedback_router.post("/submit")
def submit_feedback(payload: FeedbackSubmitRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    _throttle_submit(ip)
    return _feedback_controller.submit(payload, request)


@admin_feedback_router.get("/stats")
def get_feedback_stats(request: Request):
    """Return aggregate feedback stats for the dashboard."""
    admin_id = _admin_id(request)
    ip = request.client.host if request.client else "unknown"
    try:
        items, total = _feedback_repo.list_feedback(FeedbackQuery())
        from collections import Counter
        status_counts = Counter(r.status.value for r in items)
        return {
            "total_feedback": total,
            "feedback_rate": round(total / max(total, 1), 4),
            "status_counts": dict(status_counts),
            "pending_count": status_counts.get("new", 0),
            "approved_count": status_counts.get("reviewed", 0),
            "training_samples_used": 0,
        }
    except Exception as error:
        from fastapi import HTTPException, status as http_status
        raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error))


@admin_feedback_router.get("")
def get_all_feedback(
    request: Request,
    status_filter: Optional[FeedbackStatus] = Query(default=None, alias="status"),
    rating: Optional[int] = Query(default=None, ge=1, le=5),
    category: Optional[str] = Query(default=None),
    from_date: Optional[datetime] = Query(default=None),
    to_date: Optional[datetime] = Query(default=None),
    search: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=100),
    # === RETRAIN-GRADE FILTERS (2026-02-20) ===
    career_id: Optional[str] = Query(default=None, description="Filter by career ID"),
    model_version: Optional[str] = Query(default=None, description="Filter by model version"),
    explicit_accept: Optional[bool] = Query(default=None, description="Filter by accept/reject signal"),
    min_confidence: Optional[float] = Query(default=None, ge=0.0, le=1.0, description="Minimum confidence"),
    max_confidence: Optional[float] = Query(default=None, ge=0.0, le=1.0, description="Maximum confidence"),
):
    query = FeedbackQuery(
        status=status_filter,
        rating=rating,
        category=category,
        from_date=from_date,
        to_date=to_date,
        search=search,
        page=page,
        page_size=pageSize,
        # Retrain-grade filters
        career_id=career_id,
        model_version=model_version,
        explicit_accept=explicit_accept,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
    )
    return _feedback_controller.list_feedback(query, request, _admin_id(request))


@admin_feedback_router.patch("/{feedback_id}/status")
def update_status(feedback_id: str, payload: UpdateStatusRequest, request: Request):
    return _feedback_controller.update_status(feedback_id, payload, request, _admin_id(request))


@admin_feedback_router.patch("/{feedback_id}/reviewer")
def assign_reviewer(feedback_id: str, payload: AssignReviewerRequest, request: Request):
    return _feedback_controller.assign_reviewer(feedback_id, payload, request, _admin_id(request))


@admin_feedback_router.post("/{feedback_id}/archive")
def archive_feedback(feedback_id: str, request: Request):
    return _feedback_controller.archive_feedback(feedback_id, request, _admin_id(request))


@admin_feedback_router.delete("/{feedback_id}")
def delete_feedback(feedback_id: str, request: Request):
    return _feedback_controller.delete_feedback(feedback_id, request, _admin_id(request))


@admin_feedback_router.get("/export/csv")
def export_csv(
    request: Request,
    status_filter: Optional[FeedbackStatus] = Query(default=None, alias="status"),
    rating: Optional[int] = Query(default=None, ge=1, le=5),
    category: Optional[str] = Query(default=None),
    from_date: Optional[datetime] = Query(default=None),
    to_date: Optional[datetime] = Query(default=None),
    search: Optional[str] = Query(default=None),
):
    query = FeedbackQuery(
        status=status_filter,
        rating=rating,
        category=category,
        from_date=from_date,
        to_date=to_date,
        search=search,
        page=1,
        page_size=10000,
    )
    return _feedback_controller.export_csv(query, request, _admin_id(request))

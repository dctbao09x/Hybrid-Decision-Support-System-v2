from __future__ import annotations

from typing import Callable, Optional

from .model import AssignReviewerRequest, FeedbackListResponse, FeedbackQuery, FeedbackRecord, FeedbackSubmitRequest, UpdateStatusRequest
from .repository import FeedbackRepository


AuditWriter = Callable[[str, str, str, str, str], None]


class FeedbackService:
    def __init__(self, repository: FeedbackRepository, audit_writer: Optional[AuditWriter] = None) -> None:
        self._repo = repository
        self._audit = audit_writer

    def submitFeedback(self, payload: FeedbackSubmitRequest, ip: str) -> FeedbackRecord:
        record = self._repo.submit_feedback(payload)
        self._write_audit("anonymous", "submit feedback", record.id, ip)
        return record

    def getAllFeedback(self, query: FeedbackQuery, admin_id: str, ip: str) -> FeedbackListResponse:
        items, total = self._repo.list_feedback(query)
        self._write_audit(admin_id, "view feedback", "list", ip)
        return FeedbackListResponse(items=items, total=total, page=query.page, pageSize=query.page_size)

    def updateStatus(self, feedback_id: str, payload: UpdateStatusRequest, admin_id: str, ip: str) -> Optional[FeedbackRecord]:
        record = self._repo.update_status(feedback_id, payload.status, payload.priority)
        self._write_audit(admin_id, "modify feedback", feedback_id, ip)
        return record

    def assignReviewer(self, feedback_id: str, payload: AssignReviewerRequest, admin_id: str, ip: str) -> Optional[FeedbackRecord]:
        record = self._repo.assign_reviewer(feedback_id, payload.reviewer)
        self._write_audit(admin_id, "assign reviewer", feedback_id, ip)
        return record

    def archiveFeedback(self, feedback_id: str, admin_id: str, ip: str) -> bool:
        ok = self._repo.archive_feedback(feedback_id)
        self._write_audit(admin_id, "archive feedback", feedback_id, ip)
        return ok

    def deleteFeedback(self, feedback_id: str, admin_id: str, ip: str) -> bool:
        ok = self._repo.delete_feedback(feedback_id)
        self._write_audit(admin_id, "delete feedback", feedback_id, ip)
        return ok

    def exportFeedback(self, query: FeedbackQuery, admin_id: str, ip: str) -> list[FeedbackRecord]:
        rows = self._repo.export_feedback(query)
        self._write_audit(admin_id, "export feedback", "csv", ip)
        return rows

    def _write_audit(self, admin_id: str, action: str, target_id: str, ip: str) -> None:
        if self._audit:
            self._audit(admin_id, action, target_id, ip, "")

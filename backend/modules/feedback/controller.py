from __future__ import annotations

import csv
import io
from typing import Optional

from fastapi import HTTPException, Request, status
from fastapi.responses import StreamingResponse

from .model import AssignReviewerRequest, FeedbackQuery, FeedbackSubmitRequest, UpdateStatusRequest
from .service import FeedbackService


class FeedbackController:
    def __init__(self, service: FeedbackService) -> None:
        self._service = service

    def submit(self, payload: FeedbackSubmitRequest, request: Request):
        ip = request.client.host if request.client else "unknown"
        try:
            record = self._service.submitFeedback(payload, ip)
            return {"ok": True, "feedback": record.model_dump()}
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error))

    def list_feedback(self, query: FeedbackQuery, request: Request, admin_id: str):
        ip = request.client.host if request.client else "unknown"
        try:
            return self._service.getAllFeedback(query, admin_id, ip)
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error))

    def update_status(self, feedback_id: str, payload: UpdateStatusRequest, request: Request, admin_id: str):
        ip = request.client.host if request.client else "unknown"
        try:
            record = self._service.updateStatus(feedback_id, payload, admin_id, ip)
            if not record:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")
            return record
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error))

    def assign_reviewer(self, feedback_id: str, payload: AssignReviewerRequest, request: Request, admin_id: str):
        ip = request.client.host if request.client else "unknown"
        try:
            record = self._service.assignReviewer(feedback_id, payload, admin_id, ip)
            if not record:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")
            return record
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error))

    def archive_feedback(self, feedback_id: str, request: Request, admin_id: str):
        ip = request.client.host if request.client else "unknown"
        try:
            ok = self._service.archiveFeedback(feedback_id, admin_id, ip)
            if not ok:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")
            return {"ok": True}
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error))

    def delete_feedback(self, feedback_id: str, request: Request, admin_id: str):
        ip = request.client.host if request.client else "unknown"
        try:
            ok = self._service.deleteFeedback(feedback_id, admin_id, ip)
            if not ok:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")
            return {"ok": True}
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error))

    def export_csv(self, query: FeedbackQuery, request: Request, admin_id: str):
        ip = request.client.host if request.client else "unknown"
        try:
            rows = self._service.exportFeedback(query, admin_id, ip)

            stream = io.StringIO()
            writer = csv.writer(stream)
            writer.writerow(["ID", "User", "Email", "Rating", "Category", "Status", "Priority", "Created", "Reviewer", "Message"])
            for item in rows:
                writer.writerow([
                    item.id,
                    item.user_id,
                    item.email,
                    item.rating,
                    item.category,
                    item.status.value,
                    item.priority.value,
                    item.created_at,
                    item.reviewed_by or "",
                    item.message,
                ])

            filename = "feedback_export.csv"
            return StreamingResponse(
                iter([stream.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error))

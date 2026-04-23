"""
Standardized API Response Contract
==================================

All API endpoints MUST use these response wrappers to ensure consistent format.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from contextvars import ContextVar

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

API_VERSION = "v1"
correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


class ResponseMeta(BaseModel):
    version: str = Field(default=API_VERSION)
    trace_id: str
    timestamp: str


class SuccessResponse(BaseModel):
    status: str = Field(default="ok")
    data: Dict[str, Any] = Field(default_factory=dict)
    meta: ResponseMeta


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    status: str = Field(default="error")
    error: ErrorDetail
    meta: ResponseMeta


def _get_trace_id() -> str:
    return correlation_id_var.get() or str(uuid.uuid4())


def _build_meta(trace_id: Optional[str] = None) -> ResponseMeta:
    return ResponseMeta(
        version=API_VERSION,
        trace_id=trace_id or _get_trace_id(),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def success_response(data: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None) -> Dict[str, Any]:
    return SuccessResponse(status="ok", data=data or {}, meta=_build_meta(trace_id)).model_dump()


def error_response(
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    status_code: int = status.HTTP_400_BAD_REQUEST,
) -> JSONResponse:
    response = ErrorResponse(
        status="error",
        error=ErrorDetail(code=code, message=message, details=details),
        meta=_build_meta(trace_id),
    )
    return JSONResponse(status_code=status_code, content=response.model_dump())


class APIError(HTTPException):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.code = code
        self.message = message
        self.details = details
        super().__init__(status_code=status_code, detail=message)


class ErrorCode:
    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    INVALID_TOKEN = "INVALID_TOKEN"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_EXISTS = "RESOURCE_EXISTS"
    RESOURCE_LOCKED = "RESOURCE_LOCKED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    OPERATION_FAILED = "OPERATION_FAILED"
    INVALID_OPERATION = "INVALID_OPERATION"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"


class PaginationMeta(BaseModel):
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)
    total_items: int = Field(..., ge=0)
    total_pages: int = Field(..., ge=0)
    has_next: bool
    has_prev: bool


def paginated_response(
    items: list,
    page: int,
    page_size: int,
    total_items: int,
    item_key: str = "items",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    total_pages = (total_items + page_size - 1) // page_size if page_size > 0 else 0

    pagination = PaginationMeta(
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
    )

    return SuccessResponse(
        status="ok",
        data={item_key: items, "pagination": pagination.model_dump()},
        meta=_build_meta(trace_id),
    ).model_dump()


class HealthStatus(BaseModel):
    healthy: bool
    service: str
    uptime_seconds: float
    dependencies: Dict[str, bool] = Field(default_factory=dict)


def health_response(
    service: str,
    healthy: bool,
    uptime_seconds: float,
    dependencies: Optional[Dict[str, bool]] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    health = HealthStatus(
        healthy=healthy,
        service=service,
        uptime_seconds=uptime_seconds,
        dependencies=dependencies or {},
    )

    return SuccessResponse(
        status="ok",
        data={"health": health.model_dump()},
        meta=_build_meta(trace_id),
    ).model_dump()

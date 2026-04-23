"""
Errors Router
=============
Collects client-side error reports from the frontend ErrorBoundary
component and other error reporting mechanisms.

Endpoint:
  POST /api/v1/errors/report   — receive and log a client-side error
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger("api.routers.errors")

router = APIRouter(prefix="/api/v1/errors", tags=["Error Reporting"])


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class ErrorReport(BaseModel):
    error: str
    component: Optional[str] = None
    stack: Optional[str] = None
    user_agent: Optional[str] = None
    url: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/report",
    summary="Report a client-side error",
    response_description="Error report received",
    status_code=202,
)
async def report_error(
    body: ErrorReport,
    request: Request,
) -> Dict[str, Any]:
    """
    Receives client-side error reports from the frontend ErrorBoundary.
    Errors are logged server-side for monitoring and alerting.
    """
    client_ip = request.client.host if request.client else "unknown"

    logger.error(
        "CLIENT_ERROR | component=%s | error=%s | url=%s | ip=%s",
        body.component or "unknown",
        body.error[:300],
        body.url or "unknown",
        client_ip,
    )

    return {
        "accepted": True,
        "timestamp": time.time(),
        "message": "Error report received and logged.",
    }

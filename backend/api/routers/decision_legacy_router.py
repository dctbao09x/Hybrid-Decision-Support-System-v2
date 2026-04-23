# backend/api/routers/decision_legacy_router.py
"""Legacy compatibility alias for one-button contract."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from backend.api.routers.one_button_router import (
    CANONICAL_ONE_BUTTON_ENDPOINT,
    LEGACY_DECISION_ENDPOINT,
    LEGACY_ONE_BUTTON_SUNSET,
    ONE_BUTTON_CONTRACT_VERSION,
    OneButtonRequest,
    OneButtonResponse,
    execute_one_button_contract,
)

router = APIRouter(prefix="/api/v1/decision", tags=["Legacy"], include_in_schema=False)


@router.post(
    "/run",
    response_model=OneButtonResponse,
    include_in_schema=False,
    deprecated=True,
    status_code=status.HTTP_200_OK,
)
async def run_decision_legacy(
    request: Request,
    body: OneButtonRequest,
    response: Response,
) -> OneButtonResponse:
    result = await execute_one_button_contract(
        request,
        body,
        request_endpoint=LEGACY_DECISION_ENDPOINT,
        legacy_mode=True,
        response=response,
    )

    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = LEGACY_ONE_BUTTON_SUNSET
    response.headers["Link"] = f"<{CANONICAL_ONE_BUTTON_ENDPOINT}>; rel=\"successor-version\""
    response.headers["Warning"] = (
        f"299 - \"Deprecated endpoint {LEGACY_DECISION_ENDPOINT}; "
        f"use {CANONICAL_ONE_BUTTON_ENDPOINT}\""
    )
    response.headers["X-Contract-Version"] = ONE_BUTTON_CONTRACT_VERSION

    return result

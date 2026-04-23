from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from .model import AdminLoginRequest
from .service import get_admin_auth_service


class RefreshRequest(BaseModel):
    refreshToken: str


class LogoutRequest(BaseModel):
    refreshToken: str


admin_auth_router = APIRouter(prefix="/api/admin", tags=["Admin Auth"])


@admin_auth_router.options("/login")
@admin_auth_router.options("/refresh")
@admin_auth_router.options("/logout")
async def preflight_handler():
    """Handle CORS preflight requests"""
    return {}


@admin_auth_router.post("/login")
def admin_login(payload: AdminLoginRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    result = get_admin_auth_service().login(payload.username, payload.password, ip)
    return result


@admin_auth_router.post("/refresh")
def admin_refresh(payload: RefreshRequest):
    try:
        return get_admin_auth_service().refresh(payload.refreshToken)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc


@admin_auth_router.post("/logout")
def admin_logout(payload: LogoutRequest):
    get_admin_auth_service().revoke_refresh_token(payload.refreshToken)
    return {"ok": True}

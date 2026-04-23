from __future__ import annotations

import os
from typing import Dict, Iterable, Set

from fastapi import Depends, HTTPException, Request, status, WebSocket

from .service import ROLE_PERMISSIONS, get_admin_auth_service


SAFE_METHODS: Set[str] = {"GET", "HEAD", "OPTIONS"}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _is_ip_allowed(ip: str) -> bool:
    whitelist = os.getenv("ADMIN_IP_WHITELIST", "*").strip()
    if whitelist == "*":
        return True
    allowed = {entry.strip() for entry in whitelist.split(",") if entry.strip()}
    return ip in allowed


def auth_admin(request: Request) -> Dict:
    ip = _client_ip(request)
    if not _is_ip_allowed(ip):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IP not allowed")

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    token = auth_header.split(" ", 1)[1].strip()
    payload = get_admin_auth_service().verify_access_token(token)

    role = str(payload.get("role", ""))
    if role not in ROLE_PERMISSIONS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role not authorized")

    if request.method not in SAFE_METHODS:
        csrf_header = request.headers.get("X-CSRF-Token", "")
        if not csrf_header or csrf_header != str(payload.get("csrf", "")):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")

    request.state.admin = payload
    return payload


def require_role(allowed_roles: Iterable[str]):
    """Dependency factory enforcing allowed admin roles."""
    allowed = {r.strip().lower() for r in allowed_roles if r and r.strip()}

    def _dependency(admin: Dict = Depends(auth_admin)) -> Dict:
        role = str(admin.get("role", "")).lower()
        if role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' is not allowed for this operation",
            )
        return admin

    return _dependency


def auth_admin_websocket(websocket: WebSocket, token: str | None = None) -> Dict:
    """Authenticate a websocket using bearer token from query/header."""
    ip = websocket.client.host if websocket.client else "unknown"
    if not _is_ip_allowed(ip):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IP not allowed")

    bearer = token
    if not bearer:
        auth_header = websocket.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            bearer = auth_header.split(" ", 1)[1].strip()

    if not bearer:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    payload = get_admin_auth_service().verify_access_token(bearer)
    role = str(payload.get("role", "")).lower()
    if role not in ROLE_PERMISSIONS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role not authorized")
    return payload

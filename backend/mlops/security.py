from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Set

from fastapi import HTTPException, Request, status

from backend.modules.admin_auth.service import get_admin_auth_service


SAFE_METHODS: Set[str] = {"GET", "HEAD", "OPTIONS"}

ROLE_HIERARCHY = {"viewer": 1, "operator": 2, "admin": 3}


@dataclass
class RoleContext:
    role: str
    roles: List[str]
    admin_id: str = field(default="")


def _verify_jwt_role(request: Request, min_role: str) -> RoleContext:
    """
    Validate admin JWT Bearer token, enforce role hierarchy,
    and validate CSRF for mutating requests.
    This keeps MLOps in sync with the admin_auth middleware.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    token = auth_header.split(" ", 1)[1].strip()
    # verify_access_token raises 401 for invalid/expired tokens
    payload = get_admin_auth_service().verify_access_token(token)

    role = str(payload.get("role", "viewer")).lower()

    # CSRF check for any state-changing request
    if request.method not in SAFE_METHODS:
        csrf_header = request.headers.get("X-CSRF-Token", "")
        expected = str(payload.get("csrf", ""))
        if not csrf_header or csrf_header != expected:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid CSRF token",
            )

    min_value = ROLE_HIERARCHY.get(min_role, 3)
    granted = ROLE_HIERARCHY.get(role, 0)
    if granted < min_value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient role: required={min_role}, got={role}",
        )

    return RoleContext(
        role=role,
        roles=[role],
        admin_id=str(payload.get("adminId", "")),
    )


def viewer_guard(request: Request) -> RoleContext:
    return _verify_jwt_role(request, "viewer")


def operator_guard(request: Request) -> RoleContext:
    return _verify_jwt_role(request, "operator")


def admin_guard(request: Request) -> RoleContext:
    return _verify_jwt_role(request, "admin")

# backend/api/routers/liveops/ws_handler.py
"""
WebSocket Authentication Handler
================================

Provides secure WebSocket token verification for LiveOps realtime streams.

Functions:
- verify_ws_token() - Verify WebSocket authentication token
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("liveops.ws_handler")


class AuthError(Exception):
    """WebSocket authentication error."""
    
    def __init__(self, message: str, code: str = "AUTH_FAILED"):
        self.message = message
        self.code = code
        super().__init__(message)


async def verify_ws_token(token: Optional[str]) -> Dict[str, Any]:
    """
    Verify WebSocket authentication token.
    
    Args:
        token: JWT token from WebSocket query params
        
    Returns:
        User payload dict with adminId, role, etc.
        
    Raises:
        AuthError: If token is invalid or missing
    """
    if not token:
        raise AuthError("Missing WebSocket token", code="NO_TOKEN")
    
    # Try to import and use admin auth verification
    try:
        from backend.modules.admin_auth.service import get_admin_auth_service
        
        # Verify the token using the service
        auth_service = get_admin_auth_service()
        payload = auth_service.verify_access_token(token)
        if not payload:
            raise AuthError("Invalid or expired WebSocket token", code="INVALID_TOKEN")
        
        # Extract user info
        user_id = payload.get("sub") or payload.get("adminId")
        role = payload.get("role", "").lower()
        
        if not user_id:
            raise AuthError("Token missing user identifier", code="NO_USER_ID")
        
        # Validate role for WebSocket access
        if role not in {"admin", "operator"}:
            raise AuthError(
                f"Insufficient role for WebSocket access: {role}",
                code="INSUFFICIENT_ROLE",
            )
        
        logger.info(f"WebSocket token verified for user={user_id}, role={role}")
        
        return {
            "adminId": user_id,
            "sub": user_id,
            "role": role,
            "verified": True,
        }
        
    except AuthError:
        raise
    except ImportError as e:
        logger.error(f"Failed to import auth module: {e}")
        raise AuthError("Auth module unavailable", code="AUTH_MODULE_ERROR")
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        raise AuthError(f"Token verification failed: {str(e)}", code="VERIFY_ERROR")


def validate_ws_connection(
    user_id: str,
    role: str,
    required_roles: Optional[list] = None,
) -> bool:
    """
    Validate that a WebSocket connection meets requirements.
    
    Args:
        user_id: User identifier
        role: User role
        required_roles: List of allowed roles (default: admin, operator)
        
    Returns:
        True if connection is valid
        
    Raises:
        AuthError: If validation fails
    """
    if not user_id:
        raise AuthError("Missing user identifier", code="NO_USER_ID")
    
    allowed_roles = required_roles or ["admin", "operator"]
    if role.lower() not in [r.lower() for r in allowed_roles]:
        raise AuthError(
            f"Role '{role}' not in allowed roles: {allowed_roles}",
            code="ROLE_NOT_ALLOWED",
        )
    
    return True

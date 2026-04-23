# backend/api/middleware/__init__.py
"""
API Middleware
==============

Middleware components for API request processing.
"""

from backend.api.middleware.auth import (
    AuthMiddleware,
    AuthConfig,
    AuthResult,
    verify_token,
)
from backend.api.middleware.rate_limit import (
    RateLimitMiddleware,
    RateLimitConfig,
    check_rate_limit,
)
from backend.api.middleware.rbac import (
    Role,
    Permission,
    require_role,
    require_any_role,
    require_permission,
    require_any_permission,
    optional_auth,
    has_role,
    has_permission,
    READ_ROLES,
    WRITE_ROLES,
    ADMIN_ROLES,
    ANALYST_ROLES,
)

__all__ = [
    # Auth
    "AuthMiddleware",
    "AuthConfig",
    "AuthResult",
    "verify_token",
    # Rate Limit
    "RateLimitMiddleware",
    "RateLimitConfig",
    "check_rate_limit",
    # RBAC
    "Role",
    "Permission",
    "require_role",
    "require_any_role",
    "require_permission",
    "require_any_permission",
    "optional_auth",
    "has_role",
    "has_permission",
    "READ_ROLES",
    "WRITE_ROLES",
    "ADMIN_ROLES",
    "ANALYST_ROLES",
]

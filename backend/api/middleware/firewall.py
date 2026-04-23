# backend/api/middleware/firewall.py
"""
API Firewall - Endpoint Protection
==================================

GĐ2 PHẦN F: API Firewall

Blocks access to internal/debug/test endpoints.
Only allows production routes.

Blocked patterns:
- /_internal/*
- /debug/*
- /test/*
- Any endpoint with include_in_schema=False (hidden routes)

Allowed patterns:
- /api/v1/*
- /health
- /docs, /redoc, /openapi.json
"""

from __future__ import annotations

import logging
import re
from typing import List, Set

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("api.firewall")

# Blocked path patterns (regex)
BLOCKED_PATTERNS: List[str] = [
    r"^/_internal",
    r"^/debug",
    r"^/test",
    r"^/internal",
    r"^/_debug",
    r"^/_test",
    r"^/admin/.*score",  # Block admin scoring bypass
]

# Allowed path patterns (regex) - allowlist
ALLOWED_PATTERNS: List[str] = [
    r"^/api/v1/",
    r"^/health",
    r"^/docs",
    r"^/redoc",
    r"^/openapi\.json",
    r"^/$",  # Root
]

# Compiled patterns for performance
_blocked_re = [re.compile(p, re.IGNORECASE) for p in BLOCKED_PATTERNS]
_allowed_re = [re.compile(p, re.IGNORECASE) for p in ALLOWED_PATTERNS]


def is_blocked_path(path: str) -> bool:
    """Check if path matches blocked patterns."""
    for pattern in _blocked_re:
        if pattern.search(path):
            return True
    return False


def is_allowed_path(path: str) -> bool:
    """Check if path matches allowed patterns."""
    for pattern in _allowed_re:
        if pattern.search(path):
            return True
    return False


class APIFirewall(BaseHTTPMiddleware):
    """
    Middleware to block access to internal endpoints.
    
    Usage:
        app.add_middleware(APIFirewall)
    """
    
    def __init__(self, app, strict_mode: bool = False):
        """
        Initialize firewall.
        
        Args:
            app: FastAPI application
            strict_mode: If True, only allow explicitly allowed paths
        """
        super().__init__(app)
        self.strict_mode = strict_mode
        self._blocked_count = 0
    
    async def dispatch(self, request: Request, call_next):
        """Process request through firewall."""
        path = request.url.path
        method = request.method
        
        # Check blocked patterns first
        if is_blocked_path(path):
            self._blocked_count += 1
            client_ip = request.client.host if request.client else "unknown"
            
            logger.warning(
                f"[FIREWALL] BLOCKED: {method} {path} "
                f"client={client_ip} "
                f"reason=blocked_pattern"
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: This endpoint is not accessible"
            )
        
        # In strict mode, only allow explicitly allowed paths
        if self.strict_mode and not is_allowed_path(path):
            self._blocked_count += 1
            client_ip = request.client.host if request.client else "unknown"
            
            logger.warning(
                f"[FIREWALL] BLOCKED: {method} {path} "
                f"client={client_ip} "
                f"reason=not_in_allowlist"
            )
            
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found"
            )
        
        # Log access
        logger.debug(f"[FIREWALL] ALLOW: {method} {path}")
        
        response = await call_next(request)
        return response
    
    @property
    def blocked_count(self) -> int:
        """Get count of blocked requests."""
        return self._blocked_count


# Helper to add firewall protection to existing routers
def protect_router(router, blocked_paths: List[str] = None):
    """
    Add route-level protection to existing router.
    
    This adds dependency checks to specific routes.
    """
    from fastapi import Depends
    
    def block_internal():
        """Dependency that blocks internal routes."""
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is disabled"
        )
    
    if blocked_paths:
        for path in blocked_paths:
            # Find route and add dependency
            for route in router.routes:
                if hasattr(route, 'path') and route.path == path:
                    route.dependencies.append(Depends(block_internal))
                    logger.info(f"[FIREWALL] Protected route: {path}")


# Blocked endpoint registry
_blocked_endpoints: Set[str] = set()


def block_endpoint(path: str) -> None:
    """Register an endpoint as blocked."""
    _blocked_endpoints.add(path)
    logger.info(f"[FIREWALL] Registered blocked endpoint: {path}")


def is_endpoint_blocked(path: str) -> bool:
    """Check if specific endpoint is blocked."""
    return path in _blocked_endpoints


# Initialize blocked endpoints
block_endpoint("/_internal/score")
block_endpoint("/debug/score")
block_endpoint("/test/score")
block_endpoint("/_internal/rank")
block_endpoint("/debug/rank")
block_endpoint("/test/rank")

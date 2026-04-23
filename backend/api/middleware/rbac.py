# backend/api/middleware/rbac.py
"""
Role-Based Access Control (RBAC)
================================

RBAC middleware and dependency injection for API endpoints.

Roles & Permissions:
    - Admin: Full RW access to all resources
    - Ops: RW access to operational resources (crawlers, pipeline, scoring)
    - Auditor: Read access to all resources, no writes
    - Analyst: Read access to analytical resources (eval, taxonomy, scoring)
    - anonymous: Read access to public endpoints only

Usage::

    from backend.api.middleware.rbac import require_role, require_any_role, ROLES
    
    # Require specific role
    @router.post("/admin-only")
    async def admin_endpoint(auth: AuthResult = Depends(require_role("admin"))):
        ...
    
    # Require any of multiple roles
    @router.get("/read-endpoint")
    async def read_endpoint(auth: AuthResult = Depends(require_any_role(["admin", "auditor", "analyst"]))):
        ...
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Set
from functools import wraps

from fastapi import Request, HTTPException, status, Depends

from backend.api.middleware.auth import verify_token, AuthResult

logger = logging.getLogger("api.rbac")


# ==============================================================================
# Role Definitions
# ==============================================================================

class Role:
    """Role constants."""
    ADMIN = "admin"
    INTERNAL = "internal"
    PUBLIC = "public"
    SERVICE = "service"

    # Backward-compatible legacy roles
    OPS = "ops"
    AUDITOR = "auditor"
    ANALYST = "analyst"
    ANONYMOUS = "anonymous"
    API_USER = "api_user"


ROLE_ALIASES = {
    Role.OPS: Role.INTERNAL,
    Role.AUDITOR: Role.INTERNAL,
    Role.ANALYST: Role.INTERNAL,
    Role.API_USER: Role.SERVICE,
    Role.ANONYMOUS: Role.PUBLIC,
}


def _normalize_role(role: str) -> str:
    role_lower = role.lower()
    return ROLE_ALIASES.get(role_lower, role_lower)


# Role hierarchy (higher roles inherit lower role permissions)
ROLE_HIERARCHY = {
    Role.ADMIN: {
        Role.ADMIN,
        Role.INTERNAL,
        Role.SERVICE,
        Role.PUBLIC,
        Role.OPS,
        Role.AUDITOR,
        Role.ANALYST,
        Role.API_USER,
        Role.ANONYMOUS,
    },
    Role.INTERNAL: {
        Role.INTERNAL,
        Role.SERVICE,
        Role.PUBLIC,
        Role.OPS,
        Role.AUDITOR,
        Role.ANALYST,
        Role.API_USER,
        Role.ANONYMOUS,
    },
    Role.SERVICE: {Role.SERVICE, Role.PUBLIC, Role.API_USER, Role.ANONYMOUS},
    Role.PUBLIC: {Role.PUBLIC, Role.ANONYMOUS},
    Role.OPS: {Role.INTERNAL, Role.SERVICE, Role.PUBLIC, Role.OPS, Role.API_USER, Role.ANONYMOUS},
    Role.AUDITOR: {Role.INTERNAL, Role.PUBLIC, Role.AUDITOR, Role.ANONYMOUS},
    Role.ANALYST: {Role.INTERNAL, Role.PUBLIC, Role.ANALYST, Role.ANONYMOUS},
    Role.API_USER: {Role.SERVICE, Role.PUBLIC, Role.API_USER, Role.ANONYMOUS},
    Role.ANONYMOUS: {Role.PUBLIC, Role.ANONYMOUS},
}


# ==============================================================================
# Permission Definitions
# ==============================================================================

class Permission:
    """Permission constants."""
    # Generic permissions
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EXECUTE = "execute"
    
    # Resource-specific permissions
    CRAWLERS_READ = "crawlers:read"
    CRAWLERS_WRITE = "crawlers:write"
    CRAWLERS_EXECUTE = "crawlers:execute"
    
    PIPELINE_READ = "pipeline:read"
    PIPELINE_WRITE = "pipeline:write"
    PIPELINE_EXECUTE = "pipeline:execute"
    
    EVAL_READ = "eval:read"
    EVAL_WRITE = "eval:write"
    EVAL_EXECUTE = "eval:execute"
    
    RULES_READ = "rules:read"
    RULES_WRITE = "rules:write"
    
    TAXONOMY_READ = "taxonomy:read"
    TAXONOMY_WRITE = "taxonomy:write"
    
    SCORING_READ = "scoring:read"
    SCORING_WRITE = "scoring:write"
    SCORING_EXECUTE = "scoring:execute"
    
    GOVERNANCE_READ = "governance:read"
    GOVERNANCE_WRITE = "governance:write"
    
    MLOPS_READ = "mlops:read"
    MLOPS_WRITE = "mlops:write"
    
    HEALTH_READ = "health:read"
    METRICS_READ = "metrics:read"


# Role -> Permissions mapping
ROLE_PERMISSIONS = {
    Role.ADMIN: {
        # Admin has all permissions
        Permission.READ, Permission.WRITE, Permission.DELETE, Permission.EXECUTE,
        Permission.CRAWLERS_READ, Permission.CRAWLERS_WRITE, Permission.CRAWLERS_EXECUTE,
        Permission.PIPELINE_READ, Permission.PIPELINE_WRITE, Permission.PIPELINE_EXECUTE,
        Permission.EVAL_READ, Permission.EVAL_WRITE, Permission.EVAL_EXECUTE,
        Permission.RULES_READ, Permission.RULES_WRITE,
        Permission.TAXONOMY_READ, Permission.TAXONOMY_WRITE,
        Permission.SCORING_READ, Permission.SCORING_WRITE, Permission.SCORING_EXECUTE,
        Permission.GOVERNANCE_READ, Permission.GOVERNANCE_WRITE,
        Permission.MLOPS_READ, Permission.MLOPS_WRITE,
        Permission.HEALTH_READ, Permission.METRICS_READ,
    },
    Role.INTERNAL: {
        Permission.READ, Permission.WRITE, Permission.EXECUTE,
        Permission.CRAWLERS_READ, Permission.CRAWLERS_WRITE, Permission.CRAWLERS_EXECUTE,
        Permission.PIPELINE_READ, Permission.PIPELINE_WRITE, Permission.PIPELINE_EXECUTE,
        Permission.EVAL_READ, Permission.EVAL_EXECUTE,
        Permission.RULES_READ, Permission.RULES_WRITE,
        Permission.TAXONOMY_READ,
        Permission.SCORING_READ, Permission.SCORING_WRITE, Permission.SCORING_EXECUTE,
        Permission.GOVERNANCE_READ,
        Permission.MLOPS_READ, Permission.MLOPS_WRITE,
        Permission.HEALTH_READ, Permission.METRICS_READ,
    },
    Role.SERVICE: {
        Permission.READ,
        Permission.PIPELINE_READ,
        Permission.SCORING_READ, Permission.SCORING_EXECUTE,
        Permission.TAXONOMY_READ,
        Permission.HEALTH_READ,
    },
    Role.PUBLIC: {
        Permission.HEALTH_READ,
    },
    Role.OPS: {
        # Ops has operational permissions
        Permission.READ, Permission.WRITE, Permission.EXECUTE,
        Permission.CRAWLERS_READ, Permission.CRAWLERS_WRITE, Permission.CRAWLERS_EXECUTE,
        Permission.PIPELINE_READ, Permission.PIPELINE_WRITE, Permission.PIPELINE_EXECUTE,
        Permission.EVAL_READ, Permission.EVAL_EXECUTE,
        Permission.RULES_READ, Permission.RULES_WRITE,
        Permission.TAXONOMY_READ,
        Permission.SCORING_READ, Permission.SCORING_WRITE, Permission.SCORING_EXECUTE,
        Permission.GOVERNANCE_READ,
        Permission.MLOPS_READ, Permission.MLOPS_WRITE,
        Permission.HEALTH_READ, Permission.METRICS_READ,
    },
    Role.AUDITOR: {
        # Auditor has read access to everything
        Permission.READ,
        Permission.CRAWLERS_READ,
        Permission.PIPELINE_READ,
        Permission.EVAL_READ,
        Permission.RULES_READ,
        Permission.TAXONOMY_READ,
        Permission.SCORING_READ,
        Permission.GOVERNANCE_READ,
        Permission.MLOPS_READ,
        Permission.HEALTH_READ, Permission.METRICS_READ,
    },
    Role.ANALYST: {
        # Analyst has read access to analytical resources
        Permission.READ,
        Permission.EVAL_READ,
        Permission.RULES_READ,
        Permission.TAXONOMY_READ,
        Permission.SCORING_READ,
        Permission.HEALTH_READ, Permission.METRICS_READ,
    },
    Role.API_USER: {
        # API user has basic access
        Permission.READ,
        Permission.SCORING_READ, Permission.SCORING_EXECUTE,
        Permission.TAXONOMY_READ,
        Permission.HEALTH_READ,
    },
    Role.ANONYMOUS: {
        # Anonymous has minimal access
        Permission.HEALTH_READ,
    },
}


# ==============================================================================
# Permission Checking
# ==============================================================================

def get_effective_permissions(roles: List[str]) -> Set[str]:
    """
    Get all permissions for a list of roles (including inherited).
    
    Args:
        roles: List of role names
        
    Returns:
        Set of all effective permissions
    """
    permissions = set()
    for role in roles:
        role_lower = _normalize_role(role)
        if role_lower in ROLE_PERMISSIONS:
            permissions.update(ROLE_PERMISSIONS[role_lower])
        # Check role hierarchy for inherited roles
        if role_lower in ROLE_HIERARCHY:
            for inherited_role in ROLE_HIERARCHY[role_lower]:
                normalized_inherited = _normalize_role(inherited_role)
                if normalized_inherited in ROLE_PERMISSIONS:
                    permissions.update(ROLE_PERMISSIONS[normalized_inherited])
    return permissions


def has_permission(auth: AuthResult, permission: str) -> bool:
    """
    Check if auth result has a specific permission.
    
    Args:
        auth: Authentication result
        permission: Permission to check
        
    Returns:
        True if permission is granted
    """
    permissions = get_effective_permissions(auth.roles)
    return permission in permissions


def has_role(auth: AuthResult, role: str) -> bool:
    """
    Check if auth result has a specific role.
    
    Args:
        auth: Authentication result
        role: Role to check
        
    Returns:
        True if role is present
    """
    role_lower = _normalize_role(role)
    for user_role in auth.roles:
        user_role_lower = _normalize_role(user_role)
        if user_role_lower == role_lower:
            return True
        # Check if user has a higher role that includes this role
        if user_role_lower in ROLE_HIERARCHY:
            inherited = {_normalize_role(item) for item in ROLE_HIERARCHY[user_role_lower]}
            if role_lower in inherited:
                return True
    return False


def has_any_role(auth: AuthResult, roles: List[str]) -> bool:
    """
    Check if auth result has any of the specified roles.
    
    Args:
        auth: Authentication result
        roles: List of roles to check
        
    Returns:
        True if any role is present
    """
    return any(has_role(auth, role) for role in roles)


# ==============================================================================
# FastAPI Dependencies
# ==============================================================================

def require_role(role: str) -> Callable:
    """
    Dependency that requires a specific role.
    
    Args:
        role: Required role name
        
    Returns:
        Dependency function
        
    Example:
        @router.post("/admin")
        async def admin_endpoint(auth: AuthResult = Depends(require_role("admin"))):
            ...
    """
    async def dependency(request: Request) -> AuthResult:
        auth = await verify_token(request)
        
        if not has_role(auth, role):
            logger.warning(
                f"Access denied: required role={role}, user_roles={auth.roles}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' required",
            )
        
        return auth
    
    return dependency


def require_any_role(roles: List[str]) -> Callable:
    """
    Dependency that requires any of the specified roles.
    
    Args:
        roles: List of allowed roles
        
    Returns:
        Dependency function
        
    Example:
        @router.get("/data")
        async def data_endpoint(auth: AuthResult = Depends(require_any_role(["admin", "analyst"]))):
            ...
    """
    async def dependency(request: Request) -> AuthResult:
        auth = await verify_token(request)
        
        if not has_any_role(auth, roles):
            logger.warning(
                f"Access denied: required_any={roles}, user_roles={auth.roles}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of roles {roles} required",
            )
        
        return auth
    
    return dependency


def require_permission(permission: str) -> Callable:
    """
    Dependency that requires a specific permission.
    
    Args:
        permission: Required permission
        
    Returns:
        Dependency function
        
    Example:
        @router.post("/crawlers")
        async def create_crawler(auth: AuthResult = Depends(require_permission("crawlers:write"))):
            ...
    """
    async def dependency(request: Request) -> AuthResult:
        auth = await verify_token(request)
        
        if not has_permission(auth, permission):
            logger.warning(
                f"Access denied: required permission={permission}, user_roles={auth.roles}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required",
            )
        
        return auth
    
    return dependency


def require_any_permission(permissions: List[str]) -> Callable:
    """
    Dependency that requires any of the specified permissions.
    
    Args:
        permissions: List of allowed permissions
        
    Returns:
        Dependency function
    """
    async def dependency(request: Request) -> AuthResult:
        auth = await verify_token(request)
        effective_perms = get_effective_permissions(auth.roles)
        
        if not any(p in effective_perms for p in permissions):
            logger.warning(
                f"Access denied: required_any={permissions}, user_roles={auth.roles}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of permissions {permissions} required",
            )
        
        return auth
    
    return dependency


def optional_auth(request: Request) -> AuthResult:
    """
    Dependency that provides auth info but doesn't require it.
    
    Always succeeds, returns anonymous if not authenticated.
    
    Example:
        @router.get("/public")
        async def public_endpoint(auth: AuthResult = Depends(optional_auth)):
            # Works for both authenticated and anonymous users
            ...
    """
    # Return anonymous auth for now (when auth is disabled)
    return AuthResult(
        authenticated=False,
        user_id="anonymous",
        roles=[Role.PUBLIC],
    )


# ==============================================================================
# Endpoint Group Permissions
# ==============================================================================

# Pre-defined permission sets for common endpoint groups
READ_ROLES = [Role.ADMIN, Role.INTERNAL, Role.SERVICE, Role.PUBLIC]
WRITE_ROLES = [Role.ADMIN, Role.INTERNAL]
ADMIN_ROLES = [Role.ADMIN]
ANALYST_ROLES = [Role.ADMIN, Role.INTERNAL]

# Endpoint group -> required permissions
ENDPOINT_PERMISSIONS = {
    # Crawlers
    "crawlers:list": Permission.CRAWLERS_READ,
    "crawlers:get": Permission.CRAWLERS_READ,
    "crawlers:create": Permission.CRAWLERS_WRITE,
    "crawlers:update": Permission.CRAWLERS_WRITE,
    "crawlers:delete": Permission.CRAWLERS_WRITE,
    "crawlers:execute": Permission.CRAWLERS_EXECUTE,
    
    # Pipeline
    "pipeline:list": Permission.PIPELINE_READ,
    "pipeline:get": Permission.PIPELINE_READ,
    "pipeline:create": Permission.PIPELINE_WRITE,
    "pipeline:run": Permission.PIPELINE_EXECUTE,
    
    # Eval
    "eval:list": Permission.EVAL_READ,
    "eval:get": Permission.EVAL_READ,
    "eval:create": Permission.EVAL_WRITE,
    "eval:run": Permission.EVAL_EXECUTE,
    
    # Rules
    "rules:list": Permission.RULES_READ,
    "rules:get": Permission.RULES_READ,
    "rules:create": Permission.RULES_WRITE,
    "rules:update": Permission.RULES_WRITE,
    "rules:delete": Permission.RULES_WRITE,
    
    # Taxonomy
    "taxonomy:list": Permission.TAXONOMY_READ,
    "taxonomy:get": Permission.TAXONOMY_READ,
    "taxonomy:create": Permission.TAXONOMY_WRITE,
    "taxonomy:update": Permission.TAXONOMY_WRITE,
    
    # Scoring
    "scoring:list": Permission.SCORING_READ,
    "scoring:get": Permission.SCORING_READ,
    "scoring:configure": Permission.SCORING_WRITE,
    "scoring:rank": Permission.SCORING_EXECUTE,
    
    # Governance
    "governance:list": Permission.GOVERNANCE_READ,
    "governance:get": Permission.GOVERNANCE_READ,
    "governance:update": Permission.GOVERNANCE_WRITE,
    
    # MLOps
    "mlops:list": Permission.MLOPS_READ,
    "mlops:deploy": Permission.MLOPS_WRITE,
    
    # Health
    "health:check": Permission.HEALTH_READ,
    "metrics:read": Permission.METRICS_READ,
}

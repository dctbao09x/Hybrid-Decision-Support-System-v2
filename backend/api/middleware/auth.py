# backend/api/middleware/auth.py
"""
Authentication Middleware
=========================

Production-grade JWT/API key authentication with RBAC role enforcement.

Capabilities:
  - JWT signature validation
  - Access token expiry validation
  - Issuer/audience claim validation
  - Role claim extraction and RBAC path enforcement
  - Structured authentication error taxonomy
  - Auth rejection metrics
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import jwt
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from jwt import (
    DecodeError,
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    InvalidTokenError,
)
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("api.middleware.auth")

AUTH_REJECT_GAUGE = "auth_reject_rate"
TOKEN_EXPIRED_GAUGE = "token_expired_rate"
INVALID_SIGNATURE_GAUGE = "invalid_signature_rate"

SUPPORTED_ROLES: Set[str] = {"admin", "internal", "public", "service"}


class AuthErrorCode:
    MISSING_CREDENTIALS = "AUTH_MISSING_CREDENTIALS"
    INVALID_TOKEN = "AUTH_INVALID_TOKEN"
    TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
    INVALID_SIGNATURE = "AUTH_INVALID_SIGNATURE"
    INVALID_ISSUER = "AUTH_INVALID_ISSUER"
    INVALID_AUDIENCE = "AUTH_INVALID_AUDIENCE"
    INVALID_API_KEY = "AUTH_INVALID_API_KEY"
    INSUFFICIENT_ROLE = "AUTH_INSUFFICIENT_ROLE"
    CONFIG_ERROR = "AUTH_CONFIG_ERROR"


@dataclass
class AuthConfig:
    """Authentication configuration."""

    enabled: bool = False
    token_header: str = "Authorization"
    api_key_header: str = "X-API-Key"
    tenant_header: str = "X-Tenant-ID"

    jwt_secret: str = ""
    jwt_public_key: str = ""
    jwt_public_key_path: str = ""
    jwt_public_keys: Dict[str, str] = field(default_factory=dict)
    jwt_algorithms: List[str] = field(default_factory=lambda: ["HS256"])
    jwt_issuer: Optional[str] = None
    jwt_audience: Optional[str] = None
    jwt_leeway_seconds: int = 5
    required_claims: List[str] = field(default_factory=lambda: ["exp", "sub"])

    roles_claim: str = "roles"
    role_claim: str = "role"
    user_id_claim: str = "user_id"
    subject_claim: str = "sub"
    tenant_claim: str = "tenant"
    default_role: str = "public"
    enforce_role_claims: bool = True
    allowed_roles: List[str] = field(default_factory=lambda: sorted(SUPPORTED_ROLES))

    allow_anonymous_public_paths: bool = True
    exempt_paths: List[str] = field(
        default_factory=lambda: [
            "/",
            "/health",
            "/healthz",
            "/ready",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/v1/health",
            "/api/v1/ops/metrics",
            "/api/admin/login",
            "/api/admin/refresh",
            "/api/feedback/submit",
            "/api/v1/feedback/submit",
        ]
    )
    protected_path_prefixes: List[str] = field(
        default_factory=lambda: ["/api/v1", "/api/admin", "/api"]
    )
    rbac_rules: Dict[str, List[str]] = field(
        default_factory=lambda: {
            "/api/admin": ["admin", "internal"],
            "/api/v1/liveops": ["admin", "internal"],
            "/api/v1/mlops": ["admin", "internal", "service"],
            "/api/v1/ops": ["admin", "internal", "service"],
            "/api/v1/governance": ["admin", "internal"],
            "/api/v1/audit": ["admin", "internal"],
        }
    )

    # Backward compatibility for existing config files.
    allowed_api_keys: List[str] = field(default_factory=list)
    api_keys: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class AuthResult:
    """Authentication result attached to request.state.auth."""

    authenticated: bool
    user_id: Optional[str] = None
    subject: Optional[str] = None
    tenant_id: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    auth_source: str = "anonymous"
    api_key_id: Optional[str] = None
    token_id: Optional[str] = None
    issuer: Optional[str] = None
    audience: Optional[str] = None
    claims: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def has_role(self, role: str) -> bool:
        role_norm = _normalize_role(role)
        return role_norm in { _normalize_role(r) for r in self.roles }


_auth_config = AuthConfig()
_metrics_collector: Optional[Any] = None

_auth_metric_state: Dict[str, int] = {
    "requests": 0,
    "rejects": 0,
    "expired": 0,
    "invalid_signature": 0,
}


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _parse_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _normalize_role(role: Any) -> str:
    raw = str(role or "").strip().lower()
    if not raw:
        return ""
    if ":" in raw:
        raw = raw.split(":")[-1]

    aliases = {
        "ops": "internal",
        "auditor": "internal",
        "analyst": "internal",
        "employee": "internal",
        "staff": "internal",
        "api_user": "service",
        "m2m": "service",
        "svc": "service",
        "system": "service",
        "anonymous": "public",
        "user": "public",
        "customer": "public",
    }
    return aliases.get(raw, raw)


def _match_path(path: str, pattern: str) -> bool:
    if not pattern:
        return False
    if pattern.endswith("*"):
        return path.startswith(pattern[:-1])
    if pattern == "/":
        return path == "/"
    if path == pattern:
        return True
    base = pattern.rstrip("/")
    return path.startswith(base + "/")


def _is_exempt_path(path: str) -> bool:
    return any(_match_path(path, rule) for rule in _auth_config.exempt_paths)


def _is_protected_path(path: str) -> bool:
    return any(_match_path(path, prefix) for prefix in _auth_config.protected_path_prefixes)


def set_auth_metrics_collector(metrics_collector: Any) -> None:
    """Attach an Ops metrics collector to auth middleware."""
    global _metrics_collector
    _metrics_collector = metrics_collector


def _metrics_inc(name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
    if _metrics_collector is None:
        return
    try:
        _metrics_collector.inc(name, value=value, labels=labels)
    except Exception:
        logger.debug("auth metrics counter update failed", exc_info=True)


def _metrics_set_gauge(name: str, value: float) -> None:
    if _metrics_collector is None:
        return
    try:
        _metrics_collector.set_gauge(name, value)
    except Exception:
        logger.debug("auth metrics gauge update failed", exc_info=True)


def _refresh_auth_metric_rates() -> None:
    requests = max(_auth_metric_state["requests"], 1)
    _metrics_set_gauge(AUTH_REJECT_GAUGE, _auth_metric_state["rejects"] / requests)
    _metrics_set_gauge(TOKEN_EXPIRED_GAUGE, _auth_metric_state["expired"] / requests)
    _metrics_set_gauge(
        INVALID_SIGNATURE_GAUGE,
        _auth_metric_state["invalid_signature"] / requests,
    )


def _record_auth_request() -> None:
    _auth_metric_state["requests"] += 1
    _metrics_inc("auth_requests_total")
    _refresh_auth_metric_rates()


def _record_auth_reject(code: str) -> None:
    _auth_metric_state["rejects"] += 1
    _metrics_inc("auth_reject_total", labels={"code": code})
    if code == AuthErrorCode.TOKEN_EXPIRED:
        _auth_metric_state["expired"] += 1
        _metrics_inc("auth_token_expired_total")
    if code == AuthErrorCode.INVALID_SIGNATURE:
        _auth_metric_state["invalid_signature"] += 1
        _metrics_inc("auth_invalid_signature_total")
    _refresh_auth_metric_rates()


def _build_auth_http_exception(
    *,
    status_code: int,
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> HTTPException:
    _record_auth_reject(code)
    payload = {
        "category": "auth",
        "code": code,
        "message": message,
        "details": details or {},
    }
    return HTTPException(status_code=status_code, detail=payload, headers=headers)


def auth_http_exception_to_response(exc: HTTPException, request: Request) -> JSONResponse:
    """Render HTTPException from auth layer as a structured JSON response."""
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    payload = {
        "status": "error",
        "error": {
            "category": detail.get("category", "auth"),
            "code": detail.get("code", "AUTH_ERROR"),
            "message": detail.get("message", str(exc.detail)),
            "details": detail.get("details", {}),
        },
        "meta": {
            "path": request.url.path,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }
    return JSONResponse(
        status_code=exc.status_code,
        content=payload,
        headers=exc.headers or {},
    )


def _configure_from_auth_settings(auth_settings: Dict[str, Any]) -> AuthConfig:
    jwt_algorithms = auth_settings.get("jwt_algorithms")
    if not jwt_algorithms:
        legacy = auth_settings.get("jwt_algorithm")
        jwt_algorithms = [legacy] if legacy else ["HS256"]

    if isinstance(jwt_algorithms, str):
        jwt_algorithms = [algo.strip() for algo in jwt_algorithms.split(",") if algo.strip()]

    public_keys = auth_settings.get("jwt_public_keys") or {}
    if isinstance(public_keys, str):
        try:
            public_keys = json.loads(public_keys)
        except json.JSONDecodeError:
            public_keys = {}

    required_claims = auth_settings.get("required_claims", ["exp", "sub"])
    if isinstance(required_claims, str):
        required_claims = _parse_csv(required_claims)

    exempt_paths = auth_settings.get("exempt_paths")
    if isinstance(exempt_paths, str):
        exempt_paths = _parse_csv(exempt_paths)

    protected_paths = auth_settings.get("protected_path_prefixes")
    if isinstance(protected_paths, str):
        protected_paths = _parse_csv(protected_paths)

    rules = auth_settings.get("rbac_rules") or {}
    if isinstance(rules, str):
        try:
            rules = json.loads(rules)
        except json.JSONDecodeError:
            rules = {}

    allowed_roles = auth_settings.get("allowed_roles")
    if isinstance(allowed_roles, str):
        allowed_roles = _parse_csv(allowed_roles)

    config = AuthConfig(
        enabled=_parse_bool(auth_settings.get("enabled", False)),
        token_header=auth_settings.get("token_header", "Authorization"),
        api_key_header=auth_settings.get("api_key_header", "X-API-Key"),
        tenant_header=auth_settings.get("tenant_header", "X-Tenant-ID"),
        jwt_secret=auth_settings.get("jwt_secret", ""),
        jwt_public_key=auth_settings.get("jwt_public_key", ""),
        jwt_public_key_path=auth_settings.get("jwt_public_key_path", ""),
        jwt_public_keys=public_keys if isinstance(public_keys, dict) else {},
        jwt_algorithms=jwt_algorithms or ["HS256"],
        jwt_issuer=auth_settings.get("jwt_issuer"),
        jwt_audience=auth_settings.get("jwt_audience"),
        jwt_leeway_seconds=int(auth_settings.get("jwt_leeway_seconds", 5)),
        required_claims=required_claims or ["exp", "sub"],
        roles_claim=auth_settings.get("roles_claim", "roles"),
        role_claim=auth_settings.get("role_claim", "role"),
        user_id_claim=auth_settings.get("user_id_claim", "user_id"),
        subject_claim=auth_settings.get("subject_claim", "sub"),
        tenant_claim=auth_settings.get("tenant_claim", "tenant"),
        default_role=_normalize_role(auth_settings.get("default_role", "public")) or "public",
        enforce_role_claims=_parse_bool(auth_settings.get("enforce_role_claims", True), True),
        allowed_roles=[_normalize_role(r) for r in (allowed_roles or sorted(SUPPORTED_ROLES)) if _normalize_role(r)],
        allow_anonymous_public_paths=_parse_bool(
            auth_settings.get("allow_anonymous_public_paths", True),
            True,
        ),
        exempt_paths=exempt_paths or AuthConfig().exempt_paths,
        protected_path_prefixes=protected_paths or AuthConfig().protected_path_prefixes,
        rbac_rules={k: [_normalize_role(r) for r in v] for k, v in rules.items()} if isinstance(rules, dict) else AuthConfig().rbac_rules,
        allowed_api_keys=auth_settings.get("allowed_api_keys", []) or [],
        api_keys=auth_settings.get("api_keys", {}) or {},
    )

    if config.jwt_public_key_path and not config.jwt_public_key:
        key_path = Path(config.jwt_public_key_path)
        if key_path.exists():
            config.jwt_public_key = key_path.read_text(encoding="utf-8")

    return config


def configure_auth(config: Dict[str, Any]) -> None:
    """Configure authentication settings from app config dictionary."""
    global _auth_config
    auth_settings = config.get("auth", {}) if isinstance(config, dict) else {}
    _auth_config = _configure_from_auth_settings(auth_settings)
    logger.info(
        "Auth configured: enabled=%s algorithms=%s issuer=%s audience=%s",
        _auth_config.enabled,
        ",".join(_auth_config.jwt_algorithms),
        _auth_config.jwt_issuer or "<none>",
        _auth_config.jwt_audience or "<none>",
    )


def configure_auth_from_env() -> None:
    """Configure authentication using environment variables."""
    auth_settings = {
        "enabled": os.getenv("AUTH_ENABLED", "false"),
        "token_header": os.getenv("AUTH_TOKEN_HEADER", "Authorization"),
        "api_key_header": os.getenv("AUTH_API_KEY_HEADER", "X-API-Key"),
        "tenant_header": os.getenv("AUTH_TENANT_HEADER", "X-Tenant-ID"),
        "jwt_secret": os.getenv("JWT_SECRET", ""),
        "jwt_public_key": os.getenv("JWT_PUBLIC_KEY", ""),
        "jwt_public_key_path": os.getenv("JWT_PUBLIC_KEY_PATH", ""),
        "jwt_public_keys": os.getenv("JWT_PUBLIC_KEYS_JSON", "{}"),
        "jwt_algorithms": os.getenv("JWT_ALGORITHMS", "HS256"),
        "jwt_issuer": os.getenv("JWT_ISSUER"),
        "jwt_audience": os.getenv("JWT_AUDIENCE"),
        "jwt_leeway_seconds": os.getenv("JWT_LEEWAY_SECONDS", "5"),
        "required_claims": os.getenv("AUTH_REQUIRED_CLAIMS", "exp,sub"),
        "roles_claim": os.getenv("AUTH_ROLES_CLAIM", "roles"),
        "role_claim": os.getenv("AUTH_ROLE_CLAIM", "role"),
        "user_id_claim": os.getenv("AUTH_USER_ID_CLAIM", "user_id"),
        "subject_claim": os.getenv("AUTH_SUBJECT_CLAIM", "sub"),
        "tenant_claim": os.getenv("AUTH_TENANT_CLAIM", "tenant"),
        "default_role": os.getenv("AUTH_DEFAULT_ROLE", "public"),
        "allowed_roles": os.getenv("AUTH_ALLOWED_ROLES", "admin,internal,public,service"),
        "enforce_role_claims": os.getenv("AUTH_ENFORCE_ROLE_CLAIMS", "true"),
        "allow_anonymous_public_paths": os.getenv("AUTH_ALLOW_ANON_PUBLIC", "true"),
        "exempt_paths": os.getenv("AUTH_EXEMPT_PATHS"),
        "protected_path_prefixes": os.getenv("AUTH_PROTECTED_PATHS"),
        "rbac_rules": os.getenv("AUTH_RBAC_RULES_JSON", "{}"),
        "allowed_api_keys": _parse_csv(os.getenv("AUTH_ALLOWED_API_KEYS", "")),
        "api_keys": os.getenv("AUTH_API_KEYS_JSON", "{}"),
    }
    _settings = {"auth": auth_settings}
    configure_auth(_settings)


def _token_from_header(request: Request) -> Optional[str]:
    auth_header = request.headers.get(_auth_config.token_header, "")
    if not auth_header:
        return None
    if not auth_header.lower().startswith("bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip() or None


def _api_key_from_request(request: Request) -> Optional[str]:
    value = request.headers.get(_auth_config.api_key_header, "").strip()
    return value or None


def _fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]


def _api_key_matches(configured: str, provided: str) -> bool:
    if configured.startswith("sha256:"):
        expected = configured.split(":", 1)[1]
        provided_hash = hashlib.sha256(provided.encode("utf-8")).hexdigest()
        return hmac.compare_digest(expected, provided_hash)
    return hmac.compare_digest(configured, provided)


def _validate_api_key(provided: str) -> Optional[AuthResult]:
    for key_name, profile in _auth_config.api_keys.items():
        if not isinstance(profile, dict):
            continue
        secret = str(profile.get("secret", ""))
        if not secret:
            continue
        if not _api_key_matches(secret, provided):
            continue

        roles_raw = profile.get("roles") or ["service"]
        if isinstance(roles_raw, str):
            roles_raw = _parse_csv(roles_raw)
        roles = [_normalize_role(item) for item in roles_raw if _normalize_role(item)]
        tenant_id = profile.get("tenant_id") or profile.get("tenant")

        user_id = str(profile.get("user_id") or f"service:{key_name}")
        result = AuthResult(
            authenticated=True,
            user_id=user_id,
            subject=user_id,
            tenant_id=str(tenant_id) if tenant_id else None,
            roles=roles or ["service"],
            auth_source="api_key",
            api_key_id=key_name,
            metadata={
                "auth_source": "api_key",
                "api_key_id": key_name,
            },
        )
        return result

    for configured_key in _auth_config.allowed_api_keys:
        if _api_key_matches(str(configured_key), provided):
            key_id = f"legacy-{_fingerprint(provided)}"
            return AuthResult(
                authenticated=True,
                user_id=f"service:{key_id}",
                subject=f"service:{key_id}",
                tenant_id=None,
                roles=["service"],
                auth_source="api_key",
                api_key_id=key_id,
                metadata={
                    "auth_source": "api_key",
                    "api_key_id": key_id,
                },
            )

    return None


def _resolve_signing_key(token: str) -> str:
    headers: Dict[str, Any] = {}
    try:
        headers = jwt.get_unverified_header(token) or {}
    except Exception:
        headers = {}

    kid = str(headers.get("kid", "")).strip()
    if kid and kid in _auth_config.jwt_public_keys:
        return _auth_config.jwt_public_keys[kid]

    if _auth_config.jwt_public_key:
        return _auth_config.jwt_public_key
    if _auth_config.jwt_secret:
        return _auth_config.jwt_secret

    raise _build_auth_http_exception(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=AuthErrorCode.CONFIG_ERROR,
        message="JWT verification key is not configured",
    )


def _extract_roles(claims: Dict[str, Any]) -> List[str]:
    roles_raw: Any = claims.get(_auth_config.roles_claim)
    if roles_raw is None:
        roles_raw = claims.get(_auth_config.role_claim)
    if roles_raw is None:
        roles_raw = claims.get("scope")

    roles: List[str] = []
    if isinstance(roles_raw, str):
        tokens = roles_raw.replace(",", " ").split()
        roles = [_normalize_role(token) for token in tokens if _normalize_role(token)]
    elif isinstance(roles_raw, Sequence):
        roles = [_normalize_role(token) for token in roles_raw if _normalize_role(token)]

    if not roles and _auth_config.default_role:
        roles = [_normalize_role(_auth_config.default_role)]

    deduped: List[str] = []
    seen: Set[str] = set()
    for role in roles:
        if role and role not in seen:
            seen.add(role)
            deduped.append(role)
    return deduped


def _role_validation(roles: Iterable[str]) -> None:
    if not _auth_config.enforce_role_claims:
        return
    allowed = {role for role in (_normalize_role(r) for r in _auth_config.allowed_roles) if role}
    if not allowed:
        allowed = SUPPORTED_ROLES

    effective_roles = [role for role in (_normalize_role(r) for r in roles) if role]
    if not effective_roles:
        raise _build_auth_http_exception(
            status_code=status.HTTP_403_FORBIDDEN,
            code=AuthErrorCode.INSUFFICIENT_ROLE,
            message="Token does not contain required role claims",
            details={"required_roles": sorted(allowed)},
        )

    if not any(role in allowed for role in effective_roles):
        raise _build_auth_http_exception(
            status_code=status.HTTP_403_FORBIDDEN,
            code=AuthErrorCode.INSUFFICIENT_ROLE,
            message="Token role is not allowed",
            details={
                "allowed_roles": sorted(allowed),
                "token_roles": effective_roles,
            },
        )


def _required_roles_for_path(path: str) -> Optional[Set[str]]:
    matched_roles: Optional[Set[str]] = None
    matched_rule_len = -1
    for pattern, roles in _auth_config.rbac_rules.items():
        if _match_path(path, pattern) and len(pattern) > matched_rule_len:
            matched_rule_len = len(pattern)
            matched_roles = {_normalize_role(role) for role in roles if _normalize_role(role)}
    return matched_roles


def _enforce_path_rbac(path: str, auth_result: AuthResult) -> None:
    required_roles = _required_roles_for_path(path)
    if not required_roles:
        return

    user_roles = {_normalize_role(role) for role in auth_result.roles if _normalize_role(role)}
    if user_roles.intersection(required_roles):
        return

    raise _build_auth_http_exception(
        status_code=status.HTTP_403_FORBIDDEN,
        code=AuthErrorCode.INSUFFICIENT_ROLE,
        message="Role claim does not permit access to this route",
        details={
            "path": path,
            "required_roles": sorted(required_roles),
            "user_roles": sorted(user_roles),
        },
    )


def _decode_access_token(token: str) -> Dict[str, Any]:
    options: Dict[str, Any] = {
        "verify_signature": True,
        "verify_exp": True,
        "verify_aud": bool(_auth_config.jwt_audience),
        "verify_iss": bool(_auth_config.jwt_issuer),
    }

    required_claims = list(_auth_config.required_claims)
    if _auth_config.jwt_issuer and "iss" not in required_claims:
        required_claims.append("iss")
    if _auth_config.jwt_audience and "aud" not in required_claims:
        required_claims.append("aud")
    if required_claims:
        options["require"] = required_claims

    signing_key = _resolve_signing_key(token)
    try:
        return jwt.decode(
            token,
            signing_key,
            algorithms=_auth_config.jwt_algorithms,
            audience=_auth_config.jwt_audience,
            issuer=_auth_config.jwt_issuer,
            options=options,
            leeway=_auth_config.jwt_leeway_seconds,
        )
    except ExpiredSignatureError as exc:
        raise _build_auth_http_exception(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=AuthErrorCode.TOKEN_EXPIRED,
            message="Access token has expired",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        ) from exc
    except InvalidSignatureError as exc:
        raise _build_auth_http_exception(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=AuthErrorCode.INVALID_SIGNATURE,
            message="JWT signature verification failed",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        ) from exc
    except InvalidIssuerError as exc:
        raise _build_auth_http_exception(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=AuthErrorCode.INVALID_ISSUER,
            message="Token issuer is not allowed",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        ) from exc
    except InvalidAudienceError as exc:
        raise _build_auth_http_exception(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=AuthErrorCode.INVALID_AUDIENCE,
            message="Token audience is not allowed",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        ) from exc
    except (DecodeError, InvalidTokenError) as exc:
        raise _build_auth_http_exception(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=AuthErrorCode.INVALID_TOKEN,
            message="Invalid access token",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        ) from exc


def _auth_result_from_claims(claims: Dict[str, Any]) -> AuthResult:
    roles = _extract_roles(claims)
    _role_validation(roles)

    subject = claims.get(_auth_config.subject_claim) or claims.get("sub")
    user_id = claims.get(_auth_config.user_id_claim) or subject
    tenant = claims.get(_auth_config.tenant_claim)
    token_id = claims.get("jti")
    issuer = claims.get("iss")
    audience_claim = claims.get("aud")
    if isinstance(audience_claim, list):
        audience = ",".join(str(part) for part in audience_claim)
    elif audience_claim is None:
        audience = None
    else:
        audience = str(audience_claim)

    return AuthResult(
        authenticated=True,
        user_id=str(user_id) if user_id is not None else None,
        subject=str(subject) if subject is not None else None,
        tenant_id=str(tenant) if tenant is not None else None,
        roles=roles,
        auth_source="jwt",
        api_key_id=None,
        token_id=str(token_id) if token_id is not None else None,
        issuer=str(issuer) if issuer is not None else None,
        audience=audience,
        claims=claims,
        metadata={
            "auth_source": "jwt",
            "issuer": issuer,
            "audience": audience,
        },
    )


def _set_request_auth_state(request: Request, auth_result: AuthResult) -> AuthResult:
    request.state.auth = auth_result
    request.state.user_id = auth_result.user_id
    request.state.tenant_id = auth_result.tenant_id
    request.state.api_key_id = auth_result.api_key_id
    request.state._auth_checked = True
    return auth_result


async def verify_token(request: Request) -> AuthResult:
    """
    Verify auth credentials and return resolved principal.

    This method is safe to use both as a FastAPI dependency and in middleware.
    If the request was already authenticated earlier in middleware, the cached
    result is returned.
    """
    cached_checked = getattr(request.state, "_auth_checked", False)
    cached_auth = getattr(request.state, "auth", None)
    if cached_checked and isinstance(cached_auth, AuthResult):
        return cached_auth

    path = request.url.path
    method = request.method.upper()

    # Allow CORS preflight without authentication.
    if method == "OPTIONS":
        return _set_request_auth_state(
            request,
            AuthResult(
                authenticated=False,
                user_id="preflight",
                subject="preflight",
                tenant_id=None,
                roles=["public"],
                auth_source="public",
                metadata={"auth_source": "public"},
            ),
        )

    protected_path = _is_protected_path(path)
    exempt_path = _is_exempt_path(path)

    if _auth_config.enabled and protected_path:
        _record_auth_request()

    if not _auth_config.enabled:
        return _set_request_auth_state(
            request,
            AuthResult(
                authenticated=True,
                user_id="dev_bypass",
                subject="dev_bypass",
                tenant_id=None,
                roles=["admin", "internal", "service", "public"],
                auth_source="disabled",
                metadata={"auth_source": "disabled"},
            ),
        )

    token = _token_from_header(request)
    api_key = _api_key_from_request(request)

    if token:
        claims = _decode_access_token(token)
        auth_result = _auth_result_from_claims(claims)
        if not auth_result.tenant_id:
            tenant_from_header = request.headers.get(_auth_config.tenant_header)
            if tenant_from_header:
                auth_result.tenant_id = tenant_from_header.strip()
        _enforce_path_rbac(path, auth_result)
        return _set_request_auth_state(request, auth_result)

    if api_key:
        auth_result = _validate_api_key(api_key)
        if not auth_result:
            raise _build_auth_http_exception(
                status_code=status.HTTP_401_UNAUTHORIZED,
                code=AuthErrorCode.INVALID_API_KEY,
                message="Invalid API key",
            )

        tenant_from_header = request.headers.get(_auth_config.tenant_header)
        if tenant_from_header and not auth_result.tenant_id:
            auth_result.tenant_id = tenant_from_header.strip()

        _role_validation(auth_result.roles)
        _enforce_path_rbac(path, auth_result)
        return _set_request_auth_state(request, auth_result)

    if exempt_path and _auth_config.allow_anonymous_public_paths:
        return _set_request_auth_state(
            request,
            AuthResult(
                authenticated=False,
                user_id="anonymous",
                subject="anonymous",
                tenant_id=None,
                roles=["public"],
                auth_source="public",
                metadata={"auth_source": "public"},
            ),
        )

    if protected_path:
        raise _build_auth_http_exception(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=AuthErrorCode.MISSING_CREDENTIALS,
            message="Authentication credentials are required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _set_request_auth_state(
        request,
        AuthResult(
            authenticated=False,
            user_id="anonymous",
            subject="anonymous",
            tenant_id=None,
            roles=["public"],
            auth_source="public",
            metadata={"auth_source": "public"},
        ),
    )


class AuthMiddleware(BaseHTTPMiddleware):
    """Gateway authentication middleware."""

    async def dispatch(self, request: Request, call_next):
        try:
            await verify_token(request)
        except HTTPException as exc:
            return auth_http_exception_to_response(exc, request)
        except Exception:
            logger.exception("Unhandled auth middleware error")
            exc = _build_auth_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code=AuthErrorCode.CONFIG_ERROR,
                message="Authentication middleware failed",
            )
            return auth_http_exception_to_response(exc, request)

        return await call_next(request)


# Load defaults from environment on import.
configure_auth_from_env()

# backend/api/middleware/rate_limit.py
"""
Rate Limiting Middleware
========================

Redis-backed distributed rate limiting with:
  - Multi-dimension limiting (IP, user_id, API key, tenant)
  - Sliding-window + burst control
  - Cooldown and temporary ban logic
  - Structured abuse error taxonomy
  - Abuse and rate-limit metrics
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.state import StatePolicy, get_operational_state_store

try:
    import redis.asyncio as redis_async
    from redis.exceptions import RedisError

    _REDIS_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency in local dev
    redis_async = None  # type: ignore[assignment]
    RedisError = Exception  # type: ignore[assignment,misc]
    _REDIS_AVAILABLE = False

logger = logging.getLogger("api.middleware.rate_limit")

RATE_LIMIT_HIT_RATIO_GAUGE = "rate_limit_hit_ratio"
ABUSE_PATTERN_RATE_GAUGE = "abuse_pattern_rate"


class RateLimitErrorCode:
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    RATE_LIMIT_BURST = "RATE_LIMIT_BURST"
    ABUSE_COOLDOWN = "ABUSE_COOLDOWN"
    ABUSE_BANNED = "ABUSE_BANNED"
    RATE_LIMIT_BACKEND_UNAVAILABLE = "RATE_LIMIT_BACKEND_UNAVAILABLE"


@dataclass
class RateLimitPolicy:
    requests_per_window: int
    window_seconds: int
    burst_limit: int
    burst_window_seconds: int
    cooldown_seconds: int
    ban_threshold: int
    ban_seconds: int
    strike_window_seconds: int


@dataclass
class RateLimitConfig:
    enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    redis_prefix: str = "hdss:rl:v1"
    redis_socket_timeout_seconds: float = 0.4
    redis_connect_timeout_seconds: float = 0.4
    fail_open: bool = False

    by_ip: bool = True
    by_user: bool = True
    by_api_key: bool = True
    by_tenant: bool = True

    excluded_paths: List[str] = field(
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

    policy_public: RateLimitPolicy = field(
        default_factory=lambda: RateLimitPolicy(
            requests_per_window=120,
            window_seconds=60,
            burst_limit=30,
            burst_window_seconds=2,
            cooldown_seconds=20,
            ban_threshold=6,
            ban_seconds=600,
            strike_window_seconds=600,
        )
    )
    policy_service: RateLimitPolicy = field(
        default_factory=lambda: RateLimitPolicy(
            requests_per_window=900,
            window_seconds=60,
            burst_limit=180,
            burst_window_seconds=2,
            cooldown_seconds=10,
            ban_threshold=10,
            ban_seconds=300,
            strike_window_seconds=600,
        )
    )
    policy_internal: RateLimitPolicy = field(
        default_factory=lambda: RateLimitPolicy(
            requests_per_window=1500,
            window_seconds=60,
            burst_limit=300,
            burst_window_seconds=2,
            cooldown_seconds=8,
            ban_threshold=12,
            ban_seconds=180,
            strike_window_seconds=600,
        )
    )
    policy_admin: RateLimitPolicy = field(
        default_factory=lambda: RateLimitPolicy(
            requests_per_window=2400,
            window_seconds=60,
            burst_limit=480,
            burst_window_seconds=2,
            cooldown_seconds=5,
            ban_threshold=20,
            ban_seconds=120,
            strike_window_seconds=600,
        )
    )


@dataclass
class RateLimitDecision:
    allowed: bool
    policy_name: str
    key_scope: str
    key_fingerprint: str
    limit: int
    remaining: int
    reset_at_epoch: int
    retry_after: int
    reason: str = "ok"
    abuse_detected: bool = False
    ban_applied: bool = False


_rate_config = RateLimitConfig()
_metrics_collector: Optional[Any] = None

_rate_metrics_store = get_operational_state_store()
_rate_metrics_policy = StatePolicy(ttl_seconds=None, persistent=True, stale_after_seconds=900)
_rate_metrics_namespace = "rate_limit"
_rate_metrics_key = "counters"

_redis_client: Optional[Any] = None
_redis_lock = asyncio.Lock()


_RATE_LIMIT_LUA = """
local now = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local burst_window_ms = tonumber(ARGV[4])
local burst_limit = tonumber(ARGV[5])
local cooldown_ms = tonumber(ARGV[6])
local strike_window_ms = tonumber(ARGV[7])
local ban_threshold = tonumber(ARGV[8])
local ban_ms = tonumber(ARGV[9])
local request_member = ARGV[10]

local sliding_ttl_ms = window_ms + cooldown_ms + 1000
local burst_ttl_ms = burst_window_ms + cooldown_ms + 1000

local ban_ttl = redis.call("PTTL", KEYS[4])
if ban_ttl > 0 then
  return {0, "banned", ban_ttl, 0, now + ban_ttl, 1, 1}
end

local cooldown_ttl = redis.call("PTTL", KEYS[3])
if cooldown_ttl > 0 then
  return {0, "cooldown", cooldown_ttl, 0, now + cooldown_ttl, 1, 0}
end

redis.call("ZREMRANGEBYSCORE", KEYS[1], 0, now - window_ms)
local current = redis.call("ZCARD", KEYS[1])

redis.call("ZREMRANGEBYSCORE", KEYS[2], 0, now - burst_window_ms)
local burst_current = redis.call("ZCARD", KEYS[2])

if burst_current >= burst_limit then
  local strikes = redis.call("INCR", KEYS[5])
  if strikes == 1 then
    redis.call("PEXPIRE", KEYS[5], strike_window_ms)
  end

  local reason = "burst"
  local retry_ms = cooldown_ms
  local ban_applied = 0
  redis.call("PSETEX", KEYS[3], cooldown_ms, "1")

  if strikes >= ban_threshold then
    reason = "banned"
    retry_ms = ban_ms
    ban_applied = 1
    redis.call("PSETEX", KEYS[4], ban_ms, "1")
  end

  return {0, reason, retry_ms, 0, now + retry_ms, 1, ban_applied}
end

if current >= limit then
  local strikes = redis.call("INCR", KEYS[5])
  if strikes == 1 then
    redis.call("PEXPIRE", KEYS[5], strike_window_ms)
  end

  local reason = "limit"
  local retry_ms = cooldown_ms
  local ban_applied = 0
  redis.call("PSETEX", KEYS[3], cooldown_ms, "1")

  if strikes >= ban_threshold then
    reason = "banned"
    retry_ms = ban_ms
    ban_applied = 1
    redis.call("PSETEX", KEYS[4], ban_ms, "1")
  end

  return {0, reason, retry_ms, 0, now + retry_ms, 1, ban_applied}
end

redis.call("ZADD", KEYS[1], now, request_member)
redis.call("PEXPIRE", KEYS[1], sliding_ttl_ms)

redis.call("ZADD", KEYS[2], now, request_member)
redis.call("PEXPIRE", KEYS[2], burst_ttl_ms)

local remaining = limit - current - 1
if remaining < 0 then
  remaining = 0
end

return {1, "ok", 0, remaining, now + window_ms, 0, 0}
"""


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


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


def _is_excluded_path(path: str) -> bool:
    return any(_match_path(path, pattern) for pattern in _rate_config.excluded_paths)


def set_rate_limit_metrics_collector(metrics_collector: Any) -> None:
    global _metrics_collector
    _metrics_collector = metrics_collector


def _metrics_inc(name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
    if _metrics_collector is None:
        return
    try:
        _metrics_collector.inc(name, value=value, labels=labels)
    except Exception:
        logger.debug("rate-limit metrics counter update failed", exc_info=True)


def _metrics_set_gauge(name: str, value: float) -> None:
    if _metrics_collector is None:
        return
    try:
        _metrics_collector.set_gauge(name, value)
    except Exception:
        logger.debug("rate-limit metrics gauge update failed", exc_info=True)


def _default_rate_metric_state() -> Dict[str, int]:
    return {
        "requests": 0,
        "hits": 0,
        "abuse": 0,
    }


def _load_rate_metric_state() -> Dict[str, int]:
    data = _rate_metrics_store.get_json(
        namespace=_rate_metrics_namespace,
        state_key=_rate_metrics_key,
        default=_default_rate_metric_state(),
        policy=_rate_metrics_policy,
    )
    if not isinstance(data, dict):
        return _default_rate_metric_state()
    return {
        "requests": int(data.get("requests", 0)),
        "hits": int(data.get("hits", 0)),
        "abuse": int(data.get("abuse", 0)),
    }


def _save_rate_metric_state(state: Dict[str, int]) -> None:
    _rate_metrics_store.set_json(
        namespace=_rate_metrics_namespace,
        state_key=_rate_metrics_key,
        value={
            "requests": max(int(state.get("requests", 0)), 0),
            "hits": max(int(state.get("hits", 0)), 0),
            "abuse": max(int(state.get("abuse", 0)), 0),
        },
        policy=_rate_metrics_policy,
    )


def _mutate_rate_metric_state(mutator: Callable[[Dict[str, int]], None]) -> Dict[str, int]:
    try:
        with _rate_metrics_store.lock("rate_limit_metrics", ttl_seconds=4.0, wait_timeout_seconds=1.0):
            state = _load_rate_metric_state()
            mutator(state)
            _save_rate_metric_state(state)
            return state
    except Exception:
        logger.debug("rate metric mutation failed", exc_info=True)
        state = _load_rate_metric_state()
        mutator(state)
        return state


def _refresh_rate_metrics(state: Optional[Dict[str, int]] = None) -> None:
    current = state or _load_rate_metric_state()
    requests = max(int(current.get("requests", 0)), 1)
    hits = max(int(current.get("hits", 0)), 0)
    abuse = max(int(current.get("abuse", 0)), 0)
    _metrics_set_gauge(RATE_LIMIT_HIT_RATIO_GAUGE, hits / requests)
    _metrics_set_gauge(ABUSE_PATTERN_RATE_GAUGE, abuse / requests)


def _record_rate_request() -> None:
    state = _mutate_rate_metric_state(lambda counters: counters.__setitem__("requests", counters.get("requests", 0) + 1))
    _metrics_inc("rate_limit_requests_total")
    _refresh_rate_metrics(state)


def _record_rate_allowed() -> None:
    _metrics_inc("rate_limit_allowed_total")
    _refresh_rate_metrics()


def _record_rate_hit(reason: str, scope: str, abuse_detected: bool) -> None:
    def _apply(counters: Dict[str, int]) -> None:
        counters["hits"] = counters.get("hits", 0) + 1
        if abuse_detected:
            counters["abuse"] = counters.get("abuse", 0) + 1

    state = _mutate_rate_metric_state(_apply)
    _metrics_inc("rate_limit_hits_total", labels={"reason": reason, "scope": scope})
    if abuse_detected:
        _metrics_inc("abuse_events_total", labels={"reason": reason, "scope": scope})
    _refresh_rate_metrics(state)


def _default_policy_for_role(role: str) -> RateLimitPolicy:
    role_norm = str(role or "public").strip().lower()
    if role_norm == "admin":
        return _rate_config.policy_admin
    if role_norm == "internal":
        return _rate_config.policy_internal
    if role_norm == "service":
        return _rate_config.policy_service
    return _rate_config.policy_public


def _normalize_role(role: Any) -> str:
    raw = str(role or "").strip().lower()
    aliases = {
        "ops": "internal",
        "auditor": "internal",
        "analyst": "internal",
        "api_user": "service",
        "m2m": "service",
        "svc": "service",
        "anonymous": "public",
        "user": "public",
    }
    return aliases.get(raw, raw)


def _role_for_request(auth_result: Optional[Any]) -> str:
    roles = []
    if auth_result is not None:
        roles = getattr(auth_result, "roles", []) or []

    normalized = [_normalize_role(role) for role in roles if _normalize_role(role)]
    for candidate in ["admin", "internal", "service", "public"]:
        if candidate in normalized:
            return candidate
    return "public"


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _fingerprint(raw_value: str) -> str:
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()[:24]


def _policy_name(policy: RateLimitPolicy, role: str) -> str:
    return f"{role}:{policy.requests_per_window}/{policy.window_seconds}s"


def _collect_subjects(request: Request, auth_result: Optional[Any]) -> List[Tuple[str, str]]:
    subjects: List[Tuple[str, str]] = []

    user_id = None
    tenant_id = None
    api_key_id = None

    if auth_result is not None:
        user_id = getattr(auth_result, "user_id", None)
        tenant_id = getattr(auth_result, "tenant_id", None)
        api_key_id = getattr(auth_result, "api_key_id", None)

    if not user_id:
        user_id = getattr(request.state, "user_id", None)
    if not tenant_id:
        tenant_id = getattr(request.state, "tenant_id", None)
    if not api_key_id:
        api_key_id = getattr(request.state, "api_key_id", None)

    if _rate_config.by_ip:
        subjects.append(("ip", _client_ip(request)))
    if _rate_config.by_user and user_id:
        subjects.append(("user", str(user_id)))
    if _rate_config.by_api_key:
        key_header = request.headers.get("X-API-Key")
        if api_key_id:
            subjects.append(("api_key", str(api_key_id)))
        elif key_header:
            subjects.append(("api_key", f"hdr:{_fingerprint(key_header)}"))
    if _rate_config.by_tenant and tenant_id:
        subjects.append(("tenant", str(tenant_id)))

    if not subjects:
        subjects.append(("global", "global"))

    deduped: List[Tuple[str, str]] = []
    seen = set()
    for scope, raw in subjects:
        key = f"{scope}:{raw}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append((scope, raw))
    return deduped


def _build_redis_keys(scope: str, fingerprint: str) -> Tuple[str, str, str, str, str]:
    base = f"{_rate_config.redis_prefix}:{scope}:{fingerprint}"
    return (
        f"{base}:sw",
        f"{base}:burst",
        f"{base}:cooldown",
        f"{base}:ban",
        f"{base}:strike",
    )


def _decision_headers(decision: RateLimitDecision) -> Dict[str, str]:
    headers = {
        "X-RateLimit-Limit": str(decision.limit),
        "X-RateLimit-Remaining": str(max(decision.remaining, 0)),
        "X-RateLimit-Reset": str(decision.reset_at_epoch),
        "X-RateLimit-Policy": decision.policy_name,
        "X-RateLimit-Scope": decision.key_scope,
    }
    if decision.retry_after > 0:
        headers["Retry-After"] = str(decision.retry_after)
    return headers


def apply_rate_limit_headers(response: Any, decision: Optional[RateLimitDecision]) -> Any:
    if decision is None:
        return response
    headers = _decision_headers(decision)
    for key, value in headers.items():
        response.headers[key] = value
    return response


def _build_rate_limit_http_exception(decision: RateLimitDecision) -> HTTPException:
    reason = decision.reason
    if reason == "banned":
        status_code = status.HTTP_403_FORBIDDEN
        code = RateLimitErrorCode.ABUSE_BANNED
        message = "Client is temporarily banned due to abuse patterns"
    elif reason == "cooldown":
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
        code = RateLimitErrorCode.ABUSE_COOLDOWN
        message = "Client is in cooldown period"
    elif reason == "burst":
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
        code = RateLimitErrorCode.RATE_LIMIT_BURST
        message = "Burst rate limit exceeded"
    else:
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
        code = RateLimitErrorCode.RATE_LIMIT_EXCEEDED
        message = "Rate limit exceeded"

    detail = {
        "category": "abuse",
        "code": code,
        "message": message,
        "details": {
            "scope": decision.key_scope,
            "policy": decision.policy_name,
            "retry_after": decision.retry_after,
            "limit": decision.limit,
            "remaining": decision.remaining,
            "reason": decision.reason,
            "key_fingerprint": decision.key_fingerprint,
        },
    }
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers=_decision_headers(decision),
    )


def rate_limit_http_exception_to_response(exc: HTTPException, request: Request) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    payload = {
        "status": "error",
        "error": {
            "category": detail.get("category", "abuse"),
            "code": detail.get("code", "RATE_LIMIT_EXCEEDED"),
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


def _policy_from_value(value: Any, fallback: RateLimitPolicy) -> RateLimitPolicy:
    if not isinstance(value, dict):
        return fallback

    return RateLimitPolicy(
        requests_per_window=int(value.get("requests_per_window", fallback.requests_per_window)),
        window_seconds=int(value.get("window_seconds", fallback.window_seconds)),
        burst_limit=int(value.get("burst_limit", fallback.burst_limit)),
        burst_window_seconds=int(value.get("burst_window_seconds", fallback.burst_window_seconds)),
        cooldown_seconds=int(value.get("cooldown_seconds", fallback.cooldown_seconds)),
        ban_threshold=int(value.get("ban_threshold", fallback.ban_threshold)),
        ban_seconds=int(value.get("ban_seconds", fallback.ban_seconds)),
        strike_window_seconds=int(value.get("strike_window_seconds", fallback.strike_window_seconds)),
    )


def _load_rate_config(rate_settings: Dict[str, Any]) -> RateLimitConfig:
    role_policies = rate_settings.get("role_policies") or {}
    if isinstance(role_policies, str):
        try:
            role_policies = json.loads(role_policies)
        except json.JSONDecodeError:
            role_policies = {}

    excluded_paths = rate_settings.get("excluded_paths")
    if isinstance(excluded_paths, str):
        excluded_paths = _parse_csv(excluded_paths)

    cfg = RateLimitConfig(
        enabled=_parse_bool(rate_settings.get("enabled", False)),
        redis_url=rate_settings.get("redis_url", "redis://localhost:6379/0"),
        redis_prefix=rate_settings.get("redis_prefix", "hdss:rl:v1"),
        redis_socket_timeout_seconds=float(rate_settings.get("redis_socket_timeout_seconds", 0.4)),
        redis_connect_timeout_seconds=float(rate_settings.get("redis_connect_timeout_seconds", 0.4)),
        fail_open=_parse_bool(rate_settings.get("fail_open", False), False),
        by_ip=_parse_bool(rate_settings.get("by_ip", True), True),
        by_user=_parse_bool(rate_settings.get("by_user", True), True),
        by_api_key=_parse_bool(rate_settings.get("by_api_key", True), True),
        by_tenant=_parse_bool(rate_settings.get("by_tenant", True), True),
        excluded_paths=excluded_paths or RateLimitConfig().excluded_paths,
    )

    if isinstance(role_policies, dict):
        cfg.policy_public = _policy_from_value(role_policies.get("public"), cfg.policy_public)
        cfg.policy_service = _policy_from_value(role_policies.get("service"), cfg.policy_service)
        cfg.policy_internal = _policy_from_value(role_policies.get("internal"), cfg.policy_internal)
        cfg.policy_admin = _policy_from_value(role_policies.get("admin"), cfg.policy_admin)

    return cfg


def configure_rate_limit(config: Dict[str, Any]) -> None:
    """Configure distributed rate limit settings from app config."""
    global _rate_config
    rate_settings = config.get("rate_limit", {}) if isinstance(config, dict) else {}
    _rate_config = _load_rate_config(rate_settings)
    logger.info(
        "Rate limit configured: enabled=%s redis_prefix=%s dimensions=(ip=%s,user=%s,api_key=%s,tenant=%s)",
        _rate_config.enabled,
        _rate_config.redis_prefix,
        _rate_config.by_ip,
        _rate_config.by_user,
        _rate_config.by_api_key,
        _rate_config.by_tenant,
    )


def configure_rate_limit_from_env() -> None:
    """Configure distributed rate limiting from environment variables."""
    settings = {
        "enabled": os.getenv("RATE_LIMIT_ENABLED", "false"),
        "redis_url": os.getenv("RATE_LIMIT_REDIS_URL", "redis://localhost:6379/0"),
        "redis_prefix": os.getenv("RATE_LIMIT_REDIS_PREFIX", "hdss:rl:v1"),
        "redis_socket_timeout_seconds": os.getenv("RATE_LIMIT_REDIS_SOCKET_TIMEOUT", "0.4"),
        "redis_connect_timeout_seconds": os.getenv("RATE_LIMIT_REDIS_CONNECT_TIMEOUT", "0.4"),
        "fail_open": os.getenv("RATE_LIMIT_FAIL_OPEN", "false"),
        "by_ip": os.getenv("RATE_LIMIT_BY_IP", "true"),
        "by_user": os.getenv("RATE_LIMIT_BY_USER", "true"),
        "by_api_key": os.getenv("RATE_LIMIT_BY_API_KEY", "true"),
        "by_tenant": os.getenv("RATE_LIMIT_BY_TENANT", "true"),
        "excluded_paths": os.getenv("RATE_LIMIT_EXCLUDED_PATHS"),
        "role_policies": os.getenv("RATE_LIMIT_ROLE_POLICIES_JSON", "{}"),
    }
    configure_rate_limit({"rate_limit": settings})


async def _get_redis_client() -> Any:
    global _redis_client

    if _redis_client is not None:
        return _redis_client

    if not _REDIS_AVAILABLE:
        raise RuntimeError("redis package is not installed")

    async with _redis_lock:
        if _redis_client is not None:
            return _redis_client

        client = redis_async.from_url(
            _rate_config.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=_rate_config.redis_socket_timeout_seconds,
            socket_connect_timeout=_rate_config.redis_connect_timeout_seconds,
            health_check_interval=15,
        )
        await client.ping()
        _redis_client = client

    return _redis_client


async def _evaluate_subject_limit(
    *,
    client: Any,
    scope: str,
    raw_subject: str,
    policy: RateLimitPolicy,
    request_member: str,
    now_ms: int,
    policy_name: str,
) -> RateLimitDecision:
    fingerprint = _fingerprint(raw_subject)
    keys = _build_redis_keys(scope=scope, fingerprint=fingerprint)

    args: List[Any] = [
        now_ms,
        policy.window_seconds * 1000,
        policy.requests_per_window,
        policy.burst_window_seconds * 1000,
        policy.burst_limit,
        policy.cooldown_seconds * 1000,
        policy.strike_window_seconds * 1000,
        policy.ban_threshold,
        policy.ban_seconds * 1000,
        request_member,
    ]

    result = await client.eval(_RATE_LIMIT_LUA, len(keys), *keys, *args)
    allowed = int(result[0]) == 1
    reason = str(result[1])
    retry_after_ms = int(result[2])
    remaining = int(result[3])
    reset_at_ms = int(result[4])
    abuse_detected = int(result[5]) == 1
    ban_applied = int(result[6]) == 1

    return RateLimitDecision(
        allowed=allowed,
        policy_name=policy_name,
        key_scope=scope,
        key_fingerprint=fingerprint,
        limit=policy.requests_per_window,
        remaining=max(remaining, 0),
        reset_at_epoch=max(int(reset_at_ms / 1000), int(time.time())),
        retry_after=max(int(retry_after_ms / 1000), 0),
        reason=reason,
        abuse_detected=abuse_detected,
        ban_applied=ban_applied,
    )


def _store_cached_decision(request: Request, decision: RateLimitDecision) -> RateLimitDecision:
    request.state._rate_limit_checked = True
    request.state.rate_limit_decision = decision
    return decision


async def check_rate_limit(request: Request, auth_result: Optional[Any] = None) -> RateLimitDecision:
    """
    Enforce distributed rate limits for the request.

    Supports dimensions: IP, user_id, API key, tenant.
    """
    cached_checked = getattr(request.state, "_rate_limit_checked", False)
    cached_decision = getattr(request.state, "rate_limit_decision", None)
    if cached_checked and isinstance(cached_decision, RateLimitDecision):
        if not cached_decision.allowed:
            raise _build_rate_limit_http_exception(cached_decision)
        return cached_decision

    path = request.url.path
    if request.method.upper() == "OPTIONS" or not _rate_config.enabled or _is_excluded_path(path):
        decision = RateLimitDecision(
            allowed=True,
            policy_name="disabled",
            key_scope="none",
            key_fingerprint="none",
            limit=0,
            remaining=0,
            reset_at_epoch=int(time.time()),
            retry_after=0,
            reason="disabled",
        )
        return _store_cached_decision(request, decision)

    _record_rate_request()

    resolved_auth = auth_result if auth_result is not None else getattr(request.state, "auth", None)
    role = _role_for_request(resolved_auth)
    policy = _default_policy_for_role(role)
    policy_name = _policy_name(policy, role)

    try:
        client = await _get_redis_client()
    except Exception as exc:
        logger.error("Rate-limit Redis unavailable: %s", exc)
        _metrics_inc("rate_limit_backend_errors_total")
        if _rate_config.fail_open:
            decision = RateLimitDecision(
                allowed=True,
                policy_name="fail_open",
                key_scope="backend",
                key_fingerprint="backend",
                limit=0,
                remaining=0,
                reset_at_epoch=int(time.time()),
                retry_after=0,
                reason="backend_unavailable",
            )
            return _store_cached_decision(request, decision)

        detail = {
            "category": "abuse",
            "code": RateLimitErrorCode.RATE_LIMIT_BACKEND_UNAVAILABLE,
            "message": "Rate limit backend unavailable",
            "details": {
                "redis_url": _rate_config.redis_url,
                "fail_open": _rate_config.fail_open,
            },
        }
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        ) from exc

    now_ms = int(time.time() * 1000)
    request_member = f"{uuid.uuid4().hex}:{now_ms}"
    subjects = _collect_subjects(request, resolved_auth)

    accepted_decision: Optional[RateLimitDecision] = None
    for scope, raw_subject in subjects:
        decision = await _evaluate_subject_limit(
            client=client,
            scope=scope,
            raw_subject=raw_subject,
            policy=policy,
            request_member=request_member,
            now_ms=now_ms,
            policy_name=policy_name,
        )
        if not decision.allowed:
            _record_rate_hit(
                reason=decision.reason,
                scope=scope,
                abuse_detected=decision.abuse_detected,
            )
            _store_cached_decision(request, decision)
            raise _build_rate_limit_http_exception(decision)

        if accepted_decision is None or decision.remaining < accepted_decision.remaining:
            accepted_decision = decision

    if accepted_decision is None:
        accepted_decision = RateLimitDecision(
            allowed=True,
            policy_name=policy_name,
            key_scope="none",
            key_fingerprint="none",
            limit=policy.requests_per_window,
            remaining=policy.requests_per_window,
            reset_at_epoch=int(time.time() + policy.window_seconds),
            retry_after=0,
            reason="ok",
        )

    _record_rate_allowed()
    return _store_cached_decision(request, accepted_decision)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Gateway-level distributed rate limiting middleware."""

    async def dispatch(self, request: Request, call_next):
        try:
            decision = await check_rate_limit(request)
        except HTTPException as exc:
            return rate_limit_http_exception_to_response(exc, request)
        except Exception:
            logger.exception("Unhandled rate-limit middleware error")
            detail = {
                "category": "abuse",
                "code": RateLimitErrorCode.RATE_LIMIT_BACKEND_UNAVAILABLE,
                "message": "Rate limit middleware failed",
                "details": {},
            }
            exc = HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=detail,
            )
            return rate_limit_http_exception_to_response(exc, request)

        response = await call_next(request)
        apply_rate_limit_headers(response, decision)
        return response


# Load defaults from environment on import.
configure_rate_limit_from_env()

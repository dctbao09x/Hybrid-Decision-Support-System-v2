from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException, Request
from starlette.responses import Response

from backend.api.middleware.auth import (
    AuthErrorCode,
    configure_auth,
    verify_token,
)
from backend.api.middleware.rate_limit import (
    RateLimitDecision,
    RateLimitErrorCode,
    apply_rate_limit_headers,
    check_rate_limit,
    configure_rate_limit,
)


def _make_request(path: str, headers: dict[str, str] | None = None, method: str = "GET") -> Request:
    headers = headers or {}
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "root_path": "",
        "headers": [(k.lower().encode("utf-8"), v.encode("utf-8")) for k, v in headers.items()],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
        "state": {},
    }

    async def _receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, _receive)


def _jwt_token(secret: str, payload: dict[str, object]) -> str:
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.mark.asyncio
async def test_verify_token_accepts_valid_jwt() -> None:
    configure_auth(
        {
            "auth": {
                "enabled": True,
                "jwt_secret": "test-secret",
                "jwt_algorithms": ["HS256"],
                "jwt_issuer": "issuer.test",
                "jwt_audience": "hdss-api",
                "protected_path_prefixes": ["/api/v1"],
                "exempt_paths": ["/health"],
                "rbac_rules": {},
            }
        }
    )

    payload = {
        "sub": "user-01",
        "user_id": "user-01",
        "tenant": "tenant-a",
        "roles": ["public"],
        "iss": "issuer.test",
        "aud": "hdss-api",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
    }
    token = _jwt_token("test-secret", payload)

    request = _make_request(
        "/api/v1/decision/run",
        headers={"Authorization": f"Bearer {token}"},
    )

    auth = await verify_token(request)
    assert auth.authenticated is True
    assert auth.user_id == "user-01"
    assert auth.tenant_id == "tenant-a"
    assert "public" in auth.roles


@pytest.mark.asyncio
async def test_verify_token_rejects_expired_jwt() -> None:
    configure_auth(
        {
            "auth": {
                "enabled": True,
                "jwt_secret": "test-secret",
                "jwt_algorithms": ["HS256"],
                "jwt_issuer": "issuer.test",
                "jwt_audience": "hdss-api",
                "protected_path_prefixes": ["/api/v1"],
                "exempt_paths": ["/health"],
            }
        }
    )

    payload = {
        "sub": "user-01",
        "roles": ["public"],
        "iss": "issuer.test",
        "aud": "hdss-api",
        "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
    }
    token = _jwt_token("test-secret", payload)
    request = _make_request("/api/v1/decision/run", headers={"Authorization": f"Bearer {token}"})

    with pytest.raises(HTTPException) as exc:
        await verify_token(request)

    assert exc.value.status_code == 401
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail.get("code") == AuthErrorCode.TOKEN_EXPIRED


@pytest.mark.asyncio
async def test_verify_token_enforces_rbac_path_rule() -> None:
    configure_auth(
        {
            "auth": {
                "enabled": True,
                "jwt_secret": "test-secret",
                "jwt_algorithms": ["HS256"],
                "jwt_issuer": "issuer.test",
                "jwt_audience": "hdss-api",
                "protected_path_prefixes": ["/api/v1"],
                "exempt_paths": ["/health"],
                "rbac_rules": {"/api/v1/liveops": ["admin", "internal"]},
            }
        }
    )

    payload = {
        "sub": "user-01",
        "roles": ["public"],
        "iss": "issuer.test",
        "aud": "hdss-api",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
    }
    token = _jwt_token("test-secret", payload)
    request = _make_request("/api/v1/liveops/status", headers={"Authorization": f"Bearer {token}"})

    with pytest.raises(HTTPException) as exc:
        await verify_token(request)

    assert exc.value.status_code == 403
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail.get("code") == AuthErrorCode.INSUFFICIENT_ROLE


@pytest.mark.asyncio
async def test_rate_limit_blocks_and_returns_taxonomy(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_rate_limit(
        {
            "rate_limit": {
                "enabled": True,
                "excluded_paths": [],
                "by_ip": True,
                "by_user": True,
                "by_api_key": False,
                "by_tenant": True,
            }
        }
    )

    async def _fake_get_redis_client():
        return object()

    async def _fake_eval(**_: object) -> RateLimitDecision:
        return RateLimitDecision(
            allowed=False,
            policy_name="public:120/60s",
            key_scope="ip",
            key_fingerprint="abc123",
            limit=120,
            remaining=0,
            reset_at_epoch=123456,
            retry_after=12,
            reason="limit",
            abuse_detected=True,
            ban_applied=False,
        )

    monkeypatch.setattr(
        "backend.api.middleware.rate_limit._get_redis_client",
        _fake_get_redis_client,
    )
    monkeypatch.setattr(
        "backend.api.middleware.rate_limit._evaluate_subject_limit",
        _fake_eval,
    )

    request = _make_request("/api/v1/decision/run")
    request.state.user_id = "user-01"
    request.state.tenant_id = "tenant-a"

    with pytest.raises(HTTPException) as exc:
        await check_rate_limit(request, auth_result=None)

    assert exc.value.status_code == 429
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail.get("code") == RateLimitErrorCode.RATE_LIMIT_EXCEEDED


@pytest.mark.asyncio
async def test_rate_limit_adds_response_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_rate_limit(
        {
            "rate_limit": {
                "enabled": True,
                "excluded_paths": [],
                "by_ip": True,
                "by_user": False,
                "by_api_key": False,
                "by_tenant": False,
            }
        }
    )

    async def _fake_get_redis_client():
        return object()

    async def _fake_eval(**_: object) -> RateLimitDecision:
        return RateLimitDecision(
            allowed=True,
            policy_name="public:120/60s",
            key_scope="ip",
            key_fingerprint="abc123",
            limit=120,
            remaining=57,
            reset_at_epoch=123460,
            retry_after=0,
            reason="ok",
            abuse_detected=False,
            ban_applied=False,
        )

    monkeypatch.setattr(
        "backend.api.middleware.rate_limit._get_redis_client",
        _fake_get_redis_client,
    )
    monkeypatch.setattr(
        "backend.api.middleware.rate_limit._evaluate_subject_limit",
        _fake_eval,
    )

    request = _make_request("/api/v1/decision/run")
    decision = await check_rate_limit(request, auth_result=None)

    response = Response(content="ok")
    apply_rate_limit_headers(response, decision)

    assert response.headers["X-RateLimit-Limit"] == "120"
    assert response.headers["X-RateLimit-Remaining"] == "57"
    assert response.headers["X-RateLimit-Policy"] == "public:120/60s"
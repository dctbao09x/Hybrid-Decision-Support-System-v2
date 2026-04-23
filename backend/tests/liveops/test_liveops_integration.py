from __future__ import annotations

import hmac
import hashlib
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.run_api import app


def _login(client: TestClient) -> dict:
    response = client.post(
        "/api/admin/login",
        json={"username": "admin", "password": "trongdongdongson"},
    )
    assert response.status_code == 200
    return response.json()


def _signed_payload(admin_id: str, command_type: str, target: str) -> dict:
    ts = int(time.time())
    nonce = f"nonce-{ts}-{target}"
    raw = f"{admin_id}:{command_type}:{target}:{ts}:{nonce}"
    signature = hmac.new(
        b"liveops-dev-secret",
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "nonce": nonce,
        "timestamp": ts,
        "signature": signature,
    }


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as tc:
        yield tc


def test_liveops_endpoints_mounted_and_not_404(client: TestClient) -> None:
    session = _login(client)
    token = session["accessToken"]

    health = client.get(
        "/api/v1/live/health",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert health.status_code == 200

    poll = client.get(
        "/api/v1/live/poll",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert poll.status_code == 200


def test_liveops_requires_auth(client: TestClient) -> None:
    response = client.get("/api/v1/live/health")
    assert response.status_code == 401


def test_signed_command_and_approval_flow(client: TestClient) -> None:
    session = _login(client)
    token = session["accessToken"]
    csrf = session["csrfToken"]
    admin_id = session["admin"]["adminId"]

    signed = _signed_payload(admin_id, "crawler_kill", "production-site-a")
    body = {
        "target": "production-site-a",
        "site_name": "production-site-a",
        "force": False,
        "params": {"reason": "integration-test"},
        "priority": "normal",
        "timeout_seconds": 120,
        "dry_run": False,
        **signed,
    }

    submit = client.post(
        "/api/v1/live/crawler/kill",
        headers={"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf},
        json=body,
    )
    assert submit.status_code == 200
    payload = submit.json()
    assert payload["data"]["state"] in {"awaiting_approval", "queued"}

    if payload["data"]["state"] == "awaiting_approval":
        command_id = payload["data"]["command_id"]
        approve = client.post(
            f"/api/v1/live/commands/{command_id}/approve",
            headers={"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf},
            json={"approver_comment": "approved by integration test"},
        )
        assert approve.status_code == 200
        assert approve.json()["data"]["state"] in {"queued", "awaiting_approval"}


def test_reject_invalid_signature(client: TestClient) -> None:
    session = _login(client)
    token = session["accessToken"]
    csrf = session["csrfToken"]

    body = {
        "target": "job-1",
        "job_id": "job-1",
        "params": {},
        "priority": "normal",
        "timeout_seconds": 120,
        "dry_run": True,
        "nonce": "bad-nonce",
        "timestamp": int(time.time()),
        "signature": "0" * 64,
    }
    response = client.post(
        "/api/v1/live/job/pause",
        headers={"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf},
        json=body,
    )
    assert response.status_code == 403


def test_websocket_auth_and_connect(client: TestClient) -> None:
    session = _login(client)
    token = session["accessToken"]

    with client.websocket_connect(f"/ws/live?token={token}") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "status"
        assert hello["module"] == "system"


def test_audit_hash_chain_written(client: TestClient) -> None:
    session = _login(client)
    token = session["accessToken"]
    csrf = session["csrfToken"]
    admin_id = session["admin"]["adminId"]

    signed = _signed_payload(admin_id, "job_pause", "job-a")
    body = {
        "target": "job-a",
        "job_id": "job-a",
        "params": {},
        "priority": "normal",
        "timeout_seconds": 30,
        "dry_run": True,
        **signed,
    }
    response = client.post(
        "/api/v1/live/job/pause",
        headers={"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf},
        json=body,
    )
    assert response.status_code == 200

    log_dir = Path("logs/admin_ops")
    files = sorted(log_dir.glob("audit_*.jsonl"))
    assert files, "No audit files found"

    with open(files[-1], "r", encoding="utf-8") as handle:
        lines = [line.strip() for line in handle if line.strip()]
    assert lines, "Audit file empty"

    entry = json.loads(lines[-1])
    assert entry.get("prev_hash")
    assert entry.get("entry_hash")

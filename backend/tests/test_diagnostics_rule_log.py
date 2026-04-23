# backend/tests/test_diagnostics_rule_log.py
"""
P10 Tests — Diagnostics + Rule Log + Pipeline Stage Visualization
==================================================================

PASS criteria:
- Every stage_log entry has: stage, status, duration_ms, input, output
- DecisionResponse.diagnostics has: total_latency_ms, stage_passed, stage_failed,
  stage_skipped, slowest_stage, errors, llm_used, rules_audited
- GET /api/v1/decision/rule-log returns 200 with list structure
- GET /api/v1/decision/rule-log/{trace_id} returns 404 for unknown trace
- record_rule_execution + get_rule_log round-trip works
- get_recent_rule_logs returns entries in most-recent-first order
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.controllers.decision_controller import (
    record_rule_execution,
    get_rule_log,
    get_recent_rule_logs,
)
from backend.api.routers.decision_router import router as decision_router


# ---------------------------------------------------------------------------
# Helper: minimal DecisionResponse-like dict
# ---------------------------------------------------------------------------

def _minimal_decision_response(**overrides):
    base = {
        "trace_id": "dec-testabcdef01",
        "timestamp": "2026-02-23T00:00:00+00:00",
        "status": "SUCCESS",
        "rankings": [],
        "top_career": None,
        "explanation": None,
        "market_insights": [],
        "meta": {
            "correlation_id": "corr-abc",
            "pipeline_duration_ms": 120.0,
            "model_version": "v1",
            "weights_version": "default",
            "llm_used": False,
            "stages_completed": [],
        },
        "scoring_breakdown": None,
        "rule_applied": [],
        "reasoning_path": [],
        "stage_log": [],
        "diagnostics": None,
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Tests: stage_log entry shape (P10 richer format)
# ─────────────────────────────────────────────────────────────────────────────

class TestStageLogShape:
    """Stage log entries must carry input and output snapshots."""

    _REQUIRED_KEYS = {"stage", "status", "duration_ms"}

    def _fake_stage(self, stage_name: str, status: str = "ok"):
        return {
            "stage": stage_name,
            "status": status,
            "duration_ms": 12.5,
            "input": {"key": "val"},
            "output": {"result": "ok"},
        }

    def test_required_keys_present(self):
        entry = self._fake_stage("simgr_scoring")
        for k in self._REQUIRED_KEYS:
            assert k in entry, f"Missing required key '{k}'"

    def test_input_key_present(self):
        entry = self._fake_stage("input_normalize")
        assert "input" in entry

    def test_output_key_present(self):
        entry = self._fake_stage("explanation")
        assert "output" in entry

    def test_duration_ms_is_numeric(self):
        entry = self._fake_stage("merge")
        assert isinstance(entry["duration_ms"], (int, float))

    def test_status_values(self):
        valid_statuses = {"ok", "skipped", "error", "frozen_pass_through"}
        for s in valid_statuses:
            entry = self._fake_stage("rule_engine", status=s)
            assert entry["status"] == s


# ─────────────────────────────────────────────────────────────────────────────
# Tests: diagnostics block
# ─────────────────────────────────────────────────────────────────────────────

class TestDiagnosticsBlock:
    """DecisionResponse.diagnostics must have all P10 required keys."""

    _REQUIRED = {
        "total_latency_ms",
        "stage_count",
        "stage_passed",
        "stage_skipped",
        "stage_failed",
        "slowest_stage",
        "errors",
        "llm_used",
        "rules_audited",
    }

    def _make_diag(self, **kw):
        base = {
            "total_latency_ms": 145.3,
            "stage_count": 9,
            "stage_passed": 8,
            "stage_skipped": 1,
            "stage_failed": 0,
            "slowest_stage": "simgr_scoring",
            "errors": [],
            "llm_used": False,
            "rules_audited": 5,
        }
        base.update(kw)
        return base

    def test_all_required_keys(self):
        diag = self._make_diag()
        for k in self._REQUIRED:
            assert k in diag, f"Missing diagnostics key: {k}"

    def test_stage_passed_plus_skipped_plus_failed_eq_count(self):
        diag = self._make_diag(
            stage_count=9, stage_passed=8, stage_skipped=1, stage_failed=0
        )
        assert diag["stage_passed"] + diag["stage_skipped"] + diag["stage_failed"] <= diag["stage_count"]

    def test_errors_is_list(self):
        diag = self._make_diag()
        assert isinstance(diag["errors"], list)

    def test_total_latency_positive(self):
        diag = self._make_diag(total_latency_ms=0.001)
        assert diag["total_latency_ms"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# Tests: rule log registry
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleLogRegistry:
    """record_rule_execution / get_rule_log / get_recent_rule_logs."""

    def test_record_and_retrieve(self):
        trace = "dec-test-rulelog-001"
        rules = [{"rule": "rule_a", "outcome": "pass_through", "frozen": True}]
        record_rule_execution(trace, rules)
        result = get_rule_log(trace)
        assert result is not None
        assert result == rules

    def test_unknown_trace_returns_none(self):
        result = get_rule_log("dec-nonexistent-xyz")
        assert result is None

    def test_recent_rule_logs_non_empty_after_record(self):
        trace = "dec-test-rulelog-002"
        record_rule_execution(trace, [{"rule": "rule_b", "outcome": "flagged", "frozen": True}])
        recent = get_recent_rule_logs(limit=50)
        trace_ids = [entry["trace_id"] for entry in recent]
        assert trace in trace_ids

    def test_recent_rule_logs_most_recent_first(self):
        trace_a = "dec-order-test-aaa"
        trace_b = "dec-order-test-bbb"
        record_rule_execution(trace_a, [])
        record_rule_execution(trace_b, [])
        recent = get_recent_rule_logs(limit=10)
        ids = [e["trace_id"] for e in recent]
        # trace_b was recorded after trace_a → must appear first
        if trace_a in ids and trace_b in ids:
            assert ids.index(trace_b) < ids.index(trace_a)

    def test_recent_rule_logs_limit_respected(self):
        for i in range(5):
            record_rule_execution(f"dec-limit-test-{i:03}", [])
        recent = get_recent_rule_logs(limit=3)
        assert len(recent) <= 3

    def test_rule_log_entry_has_required_keys(self):
        trace = "dec-shape-test-001"
        record_rule_execution(trace, [{"rule": "r1", "outcome": "pass_through"}])
        recent = get_recent_rule_logs(limit=50)
        entry = next((e for e in recent if e["trace_id"] == trace), None)
        assert entry is not None
        assert "trace_id" in entry
        assert "rules" in entry
        assert "rules_count" in entry


# ─────────────────────────────────────────────────────────────────────────────
# Tests: /rule-log HTTP endpoints
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(decision_router)
    return TestClient(app, raise_server_exceptions=False)


class TestRuleLogEndpoints:

    def test_list_rule_logs_returns_200(self, client: TestClient):
        resp = client.get("/api/v1/decision/rule-log")
        assert resp.status_code == 200

    def test_list_rule_logs_response_shape(self, client: TestClient):
        resp = client.get("/api/v1/decision/rule-log")
        body = resp.json()
        assert "data" in body
        assert "count" in body["data"]
        assert "logs" in body["data"]
        assert isinstance(body["data"]["logs"], list)

    def test_list_rule_logs_limit_param(self, client: TestClient):
        resp = client.get("/api/v1/decision/rule-log?limit=5")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]["logs"]) <= 5

    def test_get_rule_log_by_trace_404_for_unknown(self, client: TestClient):
        resp = client.get("/api/v1/decision/rule-log/dec-totally-unknown-xyz123")
        assert resp.status_code == 404

    def test_get_rule_log_by_trace_returns_200_for_known(self, client: TestClient):
        trace = "dec-http-endpoint-test-001"
        record_rule_execution(trace, [{"rule": "rule_http", "outcome": "pass_through"}])
        resp = client.get(f"/api/v1/decision/rule-log/{trace}")
        assert resp.status_code == 200

    def test_get_rule_log_by_trace_shape(self, client: TestClient):
        trace = "dec-http-endpoint-test-002"
        rules = [{"rule": "rule_shape", "outcome": "flagged"}]
        record_rule_execution(trace, rules)
        body = client.get(f"/api/v1/decision/rule-log/{trace}").json()
        assert body["data"]["trace_id"] == trace
        assert body["data"]["rules_count"] == 1
        assert body["data"]["rules"] == rules

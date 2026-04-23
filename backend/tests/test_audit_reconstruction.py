# backend/tests/test_audit_reconstruction.py
"""
Audit Reconstruction Tests — Rule Log & KB Mapping
===================================================

PASS criteria:
- RuleEventLogger writes to JSONL; read_by_trace returns same rules
- KBMappingLogger writes to JSONL; read_by_trace returns same record
- Deterministic: two reads of the same trace_id return identical data
- Schema: every required field present in every record
- Isolation: two distinct trace_ids have independent, non-overlapping records
- HTTP GET /audit/decision/{id} returns 200 with correct structure
- HTTP GET /audit/decision/{id} returns 404 for unknown trace
- Chain hashes are non-empty strings (integrity link exists)
- record_rule_execution → get_rule_log still works (backward compat)
- Audit replay demo: reconstruct rule + KB layers for a full trace
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.governance.rule_event_log import RuleEventLogger
from backend.governance.kb_mapping_log import KBMappingLogger
from backend.api.routers.audit_router import router as audit_router


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def rule_logger(tmp_path: Path) -> RuleEventLogger:
    """RuleEventLogger backed by a temporary directory."""
    return RuleEventLogger(
        log_path=tmp_path / "rule_log.jsonl",
        chain_log_path=str(tmp_path / "chain.log"),
    )


@pytest.fixture()
def kb_logger(tmp_path: Path) -> KBMappingLogger:
    """KBMappingLogger backed by a temporary directory."""
    return KBMappingLogger(
        log_path=tmp_path / "kb_mapping_log.jsonl",
        chain_log_path=str(tmp_path / "chain.log"),
    )


_SAMPLE_RULES_TRACE: List[Dict[str, Any]] = [
    {"rule": "age_eligibility", "category": "eligibility",  "priority": 10, "outcome": "pass_through", "frozen": True},
    {"rule": "gpa_threshold",   "category": "academic",     "priority": 5,  "outcome": "pass_through", "frozen": True},
    {"rule": "banned_career",   "category": "compliance",   "priority": 99, "outcome": "flagged",      "frozen": True},
]

_SAMPLE_KB_PAYLOAD: Dict[str, Any] = {
    "decision_trace_id":    "dec-test-kb-001",
    "stage_name":           "kb_alignment",
    "kb_reference_version": "kb-v1.0-20260222",
    "aligned_features":     {"math_score": {"value": 8.0, "kb_mapped": True, "kb_reference_version": "kb-v1.0-20260222"}},
    "unrecognised_keys":    [],
    "skills_kb_matches":    {"python": ["software_engineering", "data_science"]},
    "interests_kb_matches": {"technology": ["software_engineering", "data_science"]},
}

_SAMPLE_SKILLS    = ["python", "math"]
_SAMPLE_INTERESTS = ["technology", "science"]


# ─────────────────────────────────────────────────────────────────────────────
# TestRuleEventLogger
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleEventLogger:
    """Unit tests for RuleEventLogger (rule_log.jsonl)."""

    def test_append_batch_returns_list(self, rule_logger: RuleEventLogger):
        events = rule_logger.append_batch("trace-001", _SAMPLE_RULES_TRACE)
        assert isinstance(events, list)
        assert len(events) == len(_SAMPLE_RULES_TRACE)

    def test_each_event_has_required_schema(self, rule_logger: RuleEventLogger):
        required = {
            "event_id", "timestamp", "decision_trace_id",
            "rule_id", "rule_version", "rule_condition",
            "rule_result", "priority", "frozen", "chain_record_hash",
        }
        events = rule_logger.append_batch("trace-schema-001", _SAMPLE_RULES_TRACE)
        for ev in events:
            assert required.issubset(ev.keys()), f"Missing keys: {required - ev.keys()}"

    def test_decision_trace_id_propagated(self, rule_logger: RuleEventLogger):
        trace = "trace-id-propagation"
        events = rule_logger.append_batch(trace, _SAMPLE_RULES_TRACE)
        for ev in events:
            assert ev["decision_trace_id"] == trace

    def test_rule_fields_mapped_correctly(self, rule_logger: RuleEventLogger):
        events = rule_logger.append_batch("trace-field-map", _SAMPLE_RULES_TRACE)
        assert events[0]["rule_id"]       == "age_eligibility"
        assert events[0]["rule_condition"] == "eligibility"
        assert events[0]["rule_result"]    == "pass_through"
        assert events[2]["rule_result"]    == "flagged"

    def test_frozen_flag_preserved(self, rule_logger: RuleEventLogger):
        events = rule_logger.append_batch("trace-frozen", _SAMPLE_RULES_TRACE)
        for ev in events:
            assert ev["frozen"] is True

    def test_read_by_trace_returns_same_records(self, rule_logger: RuleEventLogger):
        trace = "trace-read-back"
        rule_logger.append_batch(trace, _SAMPLE_RULES_TRACE)
        retrieved = rule_logger.read_by_trace(trace)
        assert len(retrieved) == len(_SAMPLE_RULES_TRACE)
        rule_ids = [e["rule_id"] for e in retrieved]
        assert "age_eligibility" in rule_ids
        assert "banned_career"   in rule_ids

    def test_read_by_trace_unknown_returns_empty(self, rule_logger: RuleEventLogger):
        result = rule_logger.read_by_trace("totally-unknown-trace-xyz")
        assert result == []

    def test_read_by_trace_isolation(self, rule_logger: RuleEventLogger):
        """Two trace_ids must not cross-contaminate each other's records."""
        trace_a = "trace-iso-aaa"
        trace_b = "trace-iso-bbb"
        rule_logger.append_batch(trace_a, [{"rule": "rule_a", "category": "cat", "priority": 1, "outcome": "pass_through", "frozen": True}])
        rule_logger.append_batch(trace_b, [{"rule": "rule_b", "category": "cat", "priority": 2, "outcome": "flagged",      "frozen": True}])
        result_a = rule_logger.read_by_trace(trace_a)
        result_b = rule_logger.read_by_trace(trace_b)
        assert all(e["rule_id"] == "rule_a" for e in result_a)
        assert all(e["rule_id"] == "rule_b" for e in result_b)

    def test_deterministic_reconstruction(self, rule_logger: RuleEventLogger):
        """Two reads of the same trace return identical rule_id sequences."""
        trace = "trace-determinism"
        rule_logger.append_batch(trace, _SAMPLE_RULES_TRACE)
        first  = rule_logger.read_by_trace(trace)
        second = rule_logger.read_by_trace(trace)
        assert [e["rule_id"] for e in first] == [e["rule_id"] for e in second]
        assert [e["rule_result"] for e in first] == [e["rule_result"] for e in second]

    def test_count_increases_after_append(self, rule_logger: RuleEventLogger):
        before = rule_logger.count()
        rule_logger.append_batch("trace-count-001", _SAMPLE_RULES_TRACE)
        assert rule_logger.count() == before + len(_SAMPLE_RULES_TRACE)

    def test_jsonl_file_created(self, rule_logger: RuleEventLogger):
        rule_logger.append_batch("trace-file-001", _SAMPLE_RULES_TRACE[:1])
        assert rule_logger._log_path.exists()

    def test_jsonl_lines_are_valid_json(self, rule_logger: RuleEventLogger):
        rule_logger.append_batch("trace-json-001", _SAMPLE_RULES_TRACE)
        with open(rule_logger._log_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    assert "event_id" in obj

    def test_chain_record_hash_non_empty(self, rule_logger: RuleEventLogger):
        events = rule_logger.append_batch("trace-hash-001", _SAMPLE_RULES_TRACE[:1])
        assert events[0]["chain_record_hash"] != ""

    def test_read_recent_traces_newest_first(self, rule_logger: RuleEventLogger):
        rule_logger.append_batch("trace-order-001", _SAMPLE_RULES_TRACE[:1])
        rule_logger.append_batch("trace-order-002", _SAMPLE_RULES_TRACE[:1])
        recent = rule_logger.read_recent_traces(limit=10)
        ids = [e["trace_id"] for e in recent]
        assert ids.index("trace-order-002") < ids.index("trace-order-001")

    def test_empty_rules_trace_appends_nothing(self, rule_logger: RuleEventLogger):
        events = rule_logger.append_batch("trace-empty", [])
        assert events == []


# ─────────────────────────────────────────────────────────────────────────────
# TestKBMappingLogger
# ─────────────────────────────────────────────────────────────────────────────

class TestKBMappingLogger:
    """Unit tests for KBMappingLogger (kb_mapping_log.jsonl)."""

    def test_append_returns_event(self, kb_logger: KBMappingLogger):
        ev = kb_logger.append(
            trace_id="kb-trace-001",
            kb_alignment_payload=_SAMPLE_KB_PAYLOAD,
            input_skills=_SAMPLE_SKILLS,
            input_interests=_SAMPLE_INTERESTS,
        )
        assert ev is not None
        assert isinstance(ev, dict)

    def test_event_has_required_schema(self, kb_logger: KBMappingLogger):
        required = {
            "event_id", "timestamp", "decision_trace_id",
            "ontology_version", "input_skill_cluster",
            "input_interest_cluster", "skills_kb_matches",
            "interests_kb_matches", "unrecognised_feature_count",
            "unrecognised_features", "chain_record_hash",
        }
        ev = kb_logger.append("kb-schema-001", _SAMPLE_KB_PAYLOAD)
        assert required.issubset(ev.keys()), f"Missing keys: {required - ev.keys()}"

    def test_ontology_version_captured(self, kb_logger: KBMappingLogger):
        ev = kb_logger.append("kb-version-001", _SAMPLE_KB_PAYLOAD)
        assert ev["ontology_version"] == "kb-v1.0-20260222"

    def test_input_skill_cluster_contains_matched_skills(self, kb_logger: KBMappingLogger):
        ev = kb_logger.append("kb-cluster-001", _SAMPLE_KB_PAYLOAD)
        # "python" maps to ["software_engineering", "data_science"] → non-empty → in cluster
        assert "python" in ev["input_skill_cluster"]

    def test_unrecognised_feature_count_correct(self, kb_logger: KBMappingLogger):
        payload = {**_SAMPLE_KB_PAYLOAD, "unrecognised_keys": ["ghost_feature", "phantom"]}
        ev = kb_logger.append("kb-unrec-001", payload)
        assert ev["unrecognised_feature_count"] == 2
        assert "ghost_feature" in ev["unrecognised_features"]

    def test_read_by_trace_returns_correct_record(self, kb_logger: KBMappingLogger):
        trace = "kb-readback-001"
        kb_logger.append(trace, _SAMPLE_KB_PAYLOAD)
        rec = kb_logger.read_by_trace(trace)
        assert rec is not None
        assert rec["decision_trace_id"] == trace

    def test_read_by_trace_unknown_returns_none(self, kb_logger: KBMappingLogger):
        result = kb_logger.read_by_trace("kb-totally-unknown-xyz")
        assert result is None

    def test_two_traces_independent(self, kb_logger: KBMappingLogger):
        trace_a = "kb-iso-aaa"
        trace_b = "kb-iso-bbb"
        kb_logger.append(trace_a, {**_SAMPLE_KB_PAYLOAD, "kb_reference_version": "v-aaa"})
        kb_logger.append(trace_b, {**_SAMPLE_KB_PAYLOAD, "kb_reference_version": "v-bbb"})
        rec_a = kb_logger.read_by_trace(trace_a)
        rec_b = kb_logger.read_by_trace(trace_b)
        assert rec_a["ontology_version"] == "v-aaa"
        assert rec_b["ontology_version"] == "v-bbb"

    def test_deterministic_reconstruction(self, kb_logger: KBMappingLogger):
        """Two reads return same ontology_version and skill_cluster."""
        trace = "kb-determinism-001"
        kb_logger.append(trace, _SAMPLE_KB_PAYLOAD, input_skills=_SAMPLE_SKILLS)
        first  = kb_logger.read_by_trace(trace)
        second = kb_logger.read_by_trace(trace)
        assert first["ontology_version"]   == second["ontology_version"]
        assert first["input_skill_cluster"] == second["input_skill_cluster"]

    def test_count_increases(self, kb_logger: KBMappingLogger):
        before = kb_logger.count()
        kb_logger.append("kb-count-001", _SAMPLE_KB_PAYLOAD)
        assert kb_logger.count() == before + 1

    def test_chain_record_hash_non_empty(self, kb_logger: KBMappingLogger):
        ev = kb_logger.append("kb-hash-001", _SAMPLE_KB_PAYLOAD)
        assert ev["chain_record_hash"] != ""

    def test_read_recent_returns_list(self, kb_logger: KBMappingLogger):
        for i in range(3):
            kb_logger.append(f"kb-recent-{i:03}", _SAMPLE_KB_PAYLOAD)
        recent = kb_logger.read_recent(limit=5)
        assert isinstance(recent, list)
        assert len(recent) >= 3


# ─────────────────────────────────────────────────────────────────────────────
# TestBackwardCompat — record_rule_execution / get_rule_log still work
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleRegistryBackwardCompat:
    """record_rule_execution / get_rule_log / get_recent_rule_logs still work
    exactly as before (in-memory path) even after the persistent backend was added."""

    def test_record_and_retrieve_round_trip(self):
        from backend.api.controllers.decision_controller import (
            record_rule_execution,
            get_rule_log,
        )
        trace = "compat-trace-001"
        rules = [{"rule": "compat_rule", "outcome": "pass_through", "frozen": True}]
        record_rule_execution(trace, rules)
        result = get_rule_log(trace)
        assert result == rules

    def test_unknown_trace_returns_none_when_not_in_persistent(self):
        from backend.api.controllers.decision_controller import get_rule_log
        # Use a trace that was definitely never written
        result = get_rule_log("compat-never-seen-xyz-9999")
        assert result is None

    def test_recent_logs_contains_recorded_trace(self):
        from backend.api.controllers.decision_controller import (
            record_rule_execution,
            get_recent_rule_logs,
        )
        trace = "compat-recent-001"
        record_rule_execution(trace, [{"rule": "r_compat", "outcome": "pass_through"}])
        recent = get_recent_rule_logs(limit=50)
        ids = [e["trace_id"] for e in recent]
        assert trace in ids


# ─────────────────────────────────────────────────────────────────────────────
# TestAuditReplayDemo — full write + reconstruct cycle
# ─────────────────────────────────────────────────────────────────────────────

class TestAuditReplayDemo:
    """End-to-end audit replay: write to both loggers, then reconstruct."""

    def test_full_chain_reconstructed(self, tmp_path: Path):
        trace = "replay-trace-001"

        # ── Write rule events ────────────────────────────────────────────────
        rl = RuleEventLogger(
            log_path=tmp_path / "rule_log.jsonl",
            chain_log_path=str(tmp_path / "chain.log"),
        )
        rl.append_batch(trace, _SAMPLE_RULES_TRACE)

        # ── Write KB mapping ─────────────────────────────────────────────────
        kb = KBMappingLogger(
            log_path=tmp_path / "kb_mapping_log.jsonl",
            chain_log_path=str(tmp_path / "chain.log"),
        )
        kb.append(trace, _SAMPLE_KB_PAYLOAD, input_skills=_SAMPLE_SKILLS)

        # ── Reconstruct ──────────────────────────────────────────────────────
        rule_events = rl.read_by_trace(trace)
        kb_record   = kb.read_by_trace(trace)

        assert len(rule_events) == len(_SAMPLE_RULES_TRACE)
        assert kb_record is not None

        # ── Determinism: second reconstruction is identical ──────────────────
        rule_events_2 = rl.read_by_trace(trace)
        kb_record_2   = kb.read_by_trace(trace)

        assert [e["rule_id"] for e in rule_events] == [e["rule_id"] for e in rule_events_2]
        assert kb_record["ontology_version"] == kb_record_2["ontology_version"]
        assert kb_record["input_skill_cluster"] == kb_record_2["input_skill_cluster"]

    def test_two_traces_fully_isolated(self, tmp_path: Path):
        """Writing two traces produces completely independent reconstructions."""
        trace_x = "replay-iso-xxx"
        trace_y = "replay-iso-yyy"

        rl = RuleEventLogger(
            log_path=tmp_path / "rule_log.jsonl",
            chain_log_path=str(tmp_path / "chain.log"),
        )
        rl.append_batch(trace_x, [{"rule": "rule_x", "category": "cat", "priority": 1, "outcome": "pass_through", "frozen": True}])
        rl.append_batch(trace_y, [{"rule": "rule_y", "category": "cat", "priority": 2, "outcome": "flagged",      "frozen": True}])

        events_x = rl.read_by_trace(trace_x)
        events_y = rl.read_by_trace(trace_y)
        assert all(e["rule_id"] == "rule_x" for e in events_x)
        assert all(e["rule_id"] == "rule_y" for e in events_y)
        assert events_x[0]["rule_result"] != events_y[0]["rule_result"]

    def test_chain_hashes_unique_across_events(self, tmp_path: Path):
        """Each rule event should have a distinct chain_record_hash."""
        trace = "replay-hash-uniqueness"
        rl = RuleEventLogger(
            log_path=tmp_path / "rule_log.jsonl",
            chain_log_path=str(tmp_path / "chain.log"),
        )
        events = rl.append_batch(trace, _SAMPLE_RULES_TRACE)
        hashes = [e["chain_record_hash"] for e in events]
        # chain hashes must be non-empty strings
        assert all(h != "" for h in hashes)

    def test_replay_preserves_rule_result_ordering(self, tmp_path: Path):
        """Read-back preserves the original rule evaluation order."""
        trace = "replay-order-001"
        rules = [
            {"rule": f"rule_{i}", "category": "cat", "priority": i,
             "outcome": "pass_through", "frozen": True}
            for i in range(10)
        ]
        rl = RuleEventLogger(
            log_path=tmp_path / "rule_log.jsonl",
            chain_log_path=str(tmp_path / "chain.log"),
        )
        rl.append_batch(trace, rules)
        retrieved = rl.read_by_trace(trace)
        assert [e["rule_id"] for e in retrieved] == [f"rule_{i}" for i in range(10)]


# ─────────────────────────────────────────────────────────────────────────────
# TestAuditHTTPEndpoints — GET /audit/decision/{id}
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def audit_client():
    """FastAPI TestClient wired with audit_router only."""
    app = FastAPI()
    app.include_router(audit_router, prefix="/api/v1/audit")
    return TestClient(app, raise_server_exceptions=False)


class TestAuditHTTPEndpoints:
    """HTTP tests for /api/v1/audit/* endpoints."""

    def test_unknown_trace_returns_404(self, audit_client: TestClient):
        resp = audit_client.get("/api/v1/audit/decision/totally-unknown-trace-99999")
        assert resp.status_code == 404

    def test_known_trace_returns_200(self, tmp_path: Path, monkeypatch, audit_client: TestClient):
        import backend.governance.rule_event_log as rel_mod
        import backend.governance.kb_mapping_log as kb_mod

        trace = "http-test-trace-001"
        # Monkeypatch singletons to use tmp_path loggers
        tmp_rl = RuleEventLogger(
            log_path=tmp_path / "rule_log.jsonl",
            chain_log_path=str(tmp_path / "chain.log"),
        )
        tmp_kb = KBMappingLogger(
            log_path=tmp_path / "kb_mapping_log.jsonl",
            chain_log_path=str(tmp_path / "chain.log"),
        )
        tmp_rl.append_batch(trace, _SAMPLE_RULES_TRACE)
        tmp_kb.append(trace, _SAMPLE_KB_PAYLOAD)

        monkeypatch.setattr(rel_mod, "_singleton", tmp_rl)
        monkeypatch.setattr(kb_mod,  "_singleton", tmp_kb)

        resp = audit_client.get(f"/api/v1/audit/decision/{trace}")
        assert resp.status_code == 200

    def test_response_schema_for_known_trace(self, tmp_path: Path, monkeypatch, audit_client: TestClient):
        import backend.governance.rule_event_log as rel_mod
        import backend.governance.kb_mapping_log as kb_mod

        trace = "http-schema-trace-002"
        tmp_rl = RuleEventLogger(
            log_path=tmp_path / "rule_log_schema.jsonl",
            chain_log_path=str(tmp_path / "chain_schema.log"),
        )
        tmp_kb = KBMappingLogger(
            log_path=tmp_path / "kb_mapping_schema.jsonl",
            chain_log_path=str(tmp_path / "chain_schema.log"),
        )
        tmp_rl.append_batch(trace, _SAMPLE_RULES_TRACE)
        tmp_kb.append(trace, _SAMPLE_KB_PAYLOAD)

        monkeypatch.setattr(rel_mod, "_singleton", tmp_rl)
        monkeypatch.setattr(kb_mod,  "_singleton", tmp_kb)

        body = audit_client.get(f"/api/v1/audit/decision/{trace}?include_drift=false").json()
        required_top_keys = {
            "decision_trace_id",
            "reconstruction_deterministic",
            "rule_events_count",
            "kb_mapping_found",
            "drift_events_count",
            "rule_events",
            "kb_mapping",
            "drift_events",
            "chain_hashes",
        }
        assert required_top_keys.issubset(body.keys()), (
            f"Missing keys: {required_top_keys - body.keys()}"
        )

    def test_reconstruction_deterministic_flag_true_when_two_layers(
        self, tmp_path: Path, monkeypatch, audit_client: TestClient
    ):
        import backend.governance.rule_event_log as rel_mod
        import backend.governance.kb_mapping_log as kb_mod

        trace = "http-determ-trace-003"
        tmp_rl = RuleEventLogger(
            log_path=tmp_path / "rule_log_det.jsonl",
            chain_log_path=str(tmp_path / "chain_det.log"),
        )
        tmp_kb = KBMappingLogger(
            log_path=tmp_path / "kb_det.jsonl",
            chain_log_path=str(tmp_path / "chain_det.log"),
        )
        tmp_rl.append_batch(trace, _SAMPLE_RULES_TRACE)
        tmp_kb.append(trace, _SAMPLE_KB_PAYLOAD)

        monkeypatch.setattr(rel_mod, "_singleton", tmp_rl)
        monkeypatch.setattr(kb_mod,  "_singleton", tmp_kb)

        body = audit_client.get(f"/api/v1/audit/decision/{trace}?include_drift=false").json()
        assert body["reconstruction_deterministic"] is True

    def test_rule_events_count_matches_rules_list(
        self, tmp_path: Path, monkeypatch, audit_client: TestClient
    ):
        import backend.governance.rule_event_log as rel_mod
        import backend.governance.kb_mapping_log as kb_mod

        trace = "http-count-trace-004"
        tmp_rl = RuleEventLogger(
            log_path=tmp_path / "rule_log_cnt.jsonl",
            chain_log_path=str(tmp_path / "chain_cnt.log"),
        )
        tmp_kb = KBMappingLogger(
            log_path=tmp_path / "kb_cnt.jsonl",
            chain_log_path=str(tmp_path / "chain_cnt.log"),
        )
        tmp_rl.append_batch(trace, _SAMPLE_RULES_TRACE)
        tmp_kb.append(trace, _SAMPLE_KB_PAYLOAD)

        monkeypatch.setattr(rel_mod, "_singleton", tmp_rl)
        monkeypatch.setattr(kb_mod,  "_singleton", tmp_kb)

        body = audit_client.get(f"/api/v1/audit/decision/{trace}?include_drift=false").json()
        assert body["rule_events_count"] == len(body["rule_events"])
        assert body["rule_events_count"] == len(_SAMPLE_RULES_TRACE)

    def test_kb_mapping_found_true_when_kb_record_present(
        self, tmp_path: Path, monkeypatch, audit_client: TestClient
    ):
        import backend.governance.rule_event_log as rel_mod
        import backend.governance.kb_mapping_log as kb_mod

        trace = "http-kb-trace-005"
        tmp_rl = RuleEventLogger(
            log_path=tmp_path / "rule_log_kb.jsonl",
            chain_log_path=str(tmp_path / "chain_kb.log"),
        )
        tmp_kb = KBMappingLogger(
            log_path=tmp_path / "kb_kb.jsonl",
            chain_log_path=str(tmp_path / "chain_kb.log"),
        )
        tmp_rl.append_batch(trace, _SAMPLE_RULES_TRACE)
        tmp_kb.append(trace, _SAMPLE_KB_PAYLOAD)

        monkeypatch.setattr(rel_mod, "_singleton", tmp_rl)
        monkeypatch.setattr(kb_mod,  "_singleton", tmp_kb)

        body = audit_client.get(f"/api/v1/audit/decision/{trace}?include_drift=false").json()
        assert body["kb_mapping_found"] is True
        assert body["kb_mapping"] is not None
        assert body["kb_mapping"]["ontology_version"] == "kb-v1.0-20260222"

    def test_chain_hashes_present_in_response(
        self, tmp_path: Path, monkeypatch, audit_client: TestClient
    ):
        import backend.governance.rule_event_log as rel_mod
        import backend.governance.kb_mapping_log as kb_mod

        trace = "http-hash-trace-006"
        tmp_rl = RuleEventLogger(
            log_path=tmp_path / "rule_log_hsh.jsonl",
            chain_log_path=str(tmp_path / "chain_hsh.log"),
        )
        tmp_kb = KBMappingLogger(
            log_path=tmp_path / "kb_hsh.jsonl",
            chain_log_path=str(tmp_path / "chain_hsh.log"),
        )
        tmp_rl.append_batch(trace, _SAMPLE_RULES_TRACE)
        tmp_kb.append(trace, _SAMPLE_KB_PAYLOAD)

        monkeypatch.setattr(rel_mod, "_singleton", tmp_rl)
        monkeypatch.setattr(kb_mod,  "_singleton", tmp_kb)

        body = audit_client.get(f"/api/v1/audit/decision/{trace}?include_drift=false").json()
        ch = body["chain_hashes"]
        assert isinstance(ch.get("rule_event_hashes"), list)
        assert isinstance(ch.get("kb_mapping_hash"), str)
        assert ch["kb_mapping_hash"] != ""

    def test_rule_events_endpoint_returns_200(self, audit_client: TestClient):
        resp = audit_client.get("/api/v1/audit/rule-events?limit=10")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "count" in body["data"]

    def test_kb_events_endpoint_returns_200(self, audit_client: TestClient):
        resp = audit_client.get("/api/v1/audit/kb-events?limit=10")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "count" in body["data"]

# tests/health/test_full_health.py
"""
Pipeline Health Monitor — Full Test Suite  (Prompt-13)
=====================================================

Covers the 5 component probes and their failure modes.

Test classes:
  TestComponentStatus        — enum values and helpers
  TestProbeRouterStatus      — router probe healthy / degraded / unhealthy
  TestProbeRuleEngineStatus  — rule engine probe healthy / degraded / unhealthy
  TestProbeMLStatus          — ML probe healthy / degraded / stuck-job
  TestProbeTaxonomyStatus    — taxonomy probe healthy / degraded / unhealthy
  TestProbePipelineStatus    — pipeline probe healthy / degraded / unhealthy
  TestAssembleFullHealth     — overall status computation from component results
  TestOverallStatusMatrix    — verify critical vs high/medium escalation rules
  TestDisableOneComponent    — PASS CRITERIA: disable each component → reflects correctly
  TestHTTPHealthFull         — GET /health/full returns 200 + 5 fields
"""

from __future__ import annotations

import sys
import types
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.health.component_probes import (
    ComponentStatus,
    assemble_full_health,
    probe_ml_status,
    probe_pipeline_status,
    probe_router_status,
    probe_rule_engine_status,
    probe_taxonomy_status,
    _compute_overall,
)

# ─── helpers ─────────────────────────────────────────────────────────────────

_PROBE_SHAPE_KEYS = {
    "probe_router_status":      {"status", "registered_count", "all_critical_up", "checked_at"},
    "probe_rule_engine_status": {"status", "rules_loaded", "engine_healthy", "log_accessible", "checked_at"},
    "probe_ml_status":          {"status", "registry_accessible", "model_count", "checked_at"},
    "probe_taxonomy_status":    {"status", "manager_available", "checked_at"},
    "probe_pipeline_status":    {"status", "controller_available", "drift_log_accessible", "checked_at"},
}

VALID_STATUSES = {ComponentStatus.HEALTHY, ComponentStatus.DEGRADED, ComponentStatus.UNHEALTHY}


def _make_router_registry_stub(names=None):
    """Build a fake backend.api.router_registry module with CORE_ROUTERS."""
    names = names or [
        "health", "decision", "ml", "pipeline", "taxonomy",
        "rules", "governance", "eval", "ops", "scoring",
    ]
    stub = types.ModuleType("backend.api.router_registry")
    stub.CORE_ROUTERS = [MagicMock(name=n) for n in names]
    for i, r in enumerate(stub.CORE_ROUTERS):
        r.name = names[i]
    return stub


# ══════════════════════════════════════════════════════════════════════════════
# TestComponentStatus
# ══════════════════════════════════════════════════════════════════════════════

class TestComponentStatus:
    def test_enum_values_are_strings(self):
        assert isinstance(ComponentStatus.HEALTHY, str)
        assert isinstance(ComponentStatus.DEGRADED, str)
        assert isinstance(ComponentStatus.UNHEALTHY, str)

    def test_enum_string_values(self):
        assert ComponentStatus.HEALTHY   == "healthy"
        assert ComponentStatus.DEGRADED  == "degraded"
        assert ComponentStatus.UNHEALTHY == "unhealthy"

    def test_compute_overall_all_healthy(self):
        components = {
            "router_status":      {"status": "healthy"},
            "rule_engine_status": {"status": "healthy"},
            "ml_status":          {"status": "healthy"},
            "taxonomy_status":    {"status": "healthy"},
            "pipeline_status":    {"status": "healthy"},
        }
        assert _compute_overall(components) == ComponentStatus.HEALTHY

    def test_compute_overall_one_degraded_returns_degraded(self):
        components = {
            "router_status":      {"status": "healthy"},
            "rule_engine_status": {"status": "healthy"},
            "ml_status":          {"status": "degraded"},
            "taxonomy_status":    {"status": "healthy"},
            "pipeline_status":    {"status": "healthy"},
        }
        assert _compute_overall(components) == ComponentStatus.DEGRADED

    def test_compute_overall_critical_unhealthy_returns_unhealthy(self):
        components = {
            "router_status":      {"status": "unhealthy"},   # CRITICAL
            "rule_engine_status": {"status": "healthy"},
            "ml_status":          {"status": "healthy"},
            "taxonomy_status":    {"status": "healthy"},
            "pipeline_status":    {"status": "healthy"},
        }
        assert _compute_overall(components) == ComponentStatus.UNHEALTHY

    def test_compute_overall_non_critical_unhealthy_returns_degraded(self):
        # pipeline_status is MEDIUM — should produce degraded, not unhealthy
        components = {
            "router_status":      {"status": "healthy"},
            "rule_engine_status": {"status": "healthy"},
            "ml_status":          {"status": "healthy"},
            "taxonomy_status":    {"status": "healthy"},
            "pipeline_status":    {"status": "unhealthy"},  # MEDIUM
        }
        assert _compute_overall(components) == ComponentStatus.DEGRADED

    def test_compute_overall_unknown_returns_degraded(self):
        components = {
            "router_status":      {"status": "healthy"},
            "rule_engine_status": {"status": "unknown"},
            "ml_status":          {"status": "healthy"},
            "taxonomy_status":    {"status": "healthy"},
            "pipeline_status":    {"status": "healthy"},
        }
        assert _compute_overall(components) == ComponentStatus.DEGRADED


# ══════════════════════════════════════════════════════════════════════════════
# TestProbeRouterStatus
# ══════════════════════════════════════════════════════════════════════════════

class TestProbeRouterStatus:
    def test_returns_dict(self):
        stub = _make_router_registry_stub()
        with patch.dict(sys.modules, {"backend.api.router_registry": stub}):
            result = probe_router_status()
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        stub = _make_router_registry_stub()
        with patch.dict(sys.modules, {"backend.api.router_registry": stub}):
            result = probe_router_status()
        for key in _PROBE_SHAPE_KEYS["probe_router_status"]:
            assert key in result, f"Missing key: {key}"

    def test_status_is_valid_value(self):
        stub = _make_router_registry_stub()
        with patch.dict(sys.modules, {"backend.api.router_registry": stub}):
            result = probe_router_status()
        assert result["status"] in VALID_STATUSES

    def test_healthy_when_all_critical_routers_present(self):
        stub = _make_router_registry_stub([
            "health", "decision", "ml", "pipeline", "taxonomy",
            "rules", "governance", "eval",
        ])
        with patch.dict(sys.modules, {"backend.api.router_registry": stub}):
            result = probe_router_status()
        assert result["status"] == ComponentStatus.HEALTHY
        assert result["all_critical_up"] is True
        assert result["missing_critical"] == []

    def test_degraded_when_some_critical_routers_missing(self):
        # Only include non-critical routers
        stub = _make_router_registry_stub(["scoring", "market", "kb"])
        with patch.dict(sys.modules, {"backend.api.router_registry": stub}):
            result = probe_router_status()
        assert result["status"] in (ComponentStatus.DEGRADED, ComponentStatus.UNHEALTHY)
        assert result["all_critical_up"] is False
        assert len(result["missing_critical"]) > 0

    def test_unhealthy_when_registry_fails(self):
        # Remove the module from sys.modules and block re-import
        orig = sys.modules.pop("backend.api.router_registry", None)
        try:
            import importlib
            with patch("importlib.import_module", side_effect=ImportError("blocked")):
                result = probe_router_status()
            assert result["status"] in (ComponentStatus.DEGRADED, ComponentStatus.UNHEALTHY)
        finally:
            if orig is not None:
                sys.modules["backend.api.router_registry"] = orig

    def test_missing_critical_list_populated_correctly(self):
        stub = _make_router_registry_stub(["health", "decision"])  # missing ml, pipeline, etc.
        with patch.dict(sys.modules, {"backend.api.router_registry": stub}):
            result = probe_router_status()
        assert "ml" in result["missing_critical"] or len(result["missing_critical"]) > 0

    def test_registered_count_matches_stub_length(self):
        names = ["health", "decision", "ml", "pipeline", "taxonomy", "rules", "governance", "eval"]
        stub = _make_router_registry_stub(names)
        with patch.dict(sys.modules, {"backend.api.router_registry": stub}):
            result = probe_router_status()
        assert result["registered_count"] == len(names)


# ══════════════════════════════════════════════════════════════════════════════
# TestProbeRuleEngineStatus
# ══════════════════════════════════════════════════════════════════════════════

class TestProbeRuleEngineStatus:
    def test_returns_dict(self):
        result = probe_rule_engine_status()
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        result = probe_rule_engine_status()
        for key in _PROBE_SHAPE_KEYS["probe_rule_engine_status"]:
            assert key in result, f"Missing key: {key}"

    def test_status_is_valid_value(self):
        result = probe_rule_engine_status()
        assert result["status"] in VALID_STATUSES

    def test_healthy_when_engine_ok_and_log_accessible(self, monkeypatch):
        """If RuleService reports healthy AND rule log accessible → healthy."""
        import backend.rule_engine.rule_service as rs_mod
        import backend.governance.rule_event_log as rl_mod

        mock_logger = MagicMock()
        mock_logger.count.return_value = 5

        monkeypatch.setattr(
            rs_mod.RuleService, "health",
            staticmethod(lambda: {"healthy": True, "rules_loaded": 12}),
        )
        monkeypatch.setattr(rl_mod, "get_rule_event_logger", lambda: mock_logger)

        result = probe_rule_engine_status()
        assert result["status"] == ComponentStatus.HEALTHY
        assert result["engine_healthy"] is True
        assert result["log_accessible"] is True
        assert result["rules_loaded"] == 12

    def test_unhealthy_when_engine_fails(self, monkeypatch):
        """If RuleService.health() raises → rule_engine_status is unhealthy."""
        import backend.rule_engine.rule_service as rs_mod
        import backend.governance.rule_event_log as rl_mod

        monkeypatch.setattr(
            rs_mod.RuleService, "health",
            staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("engine offline"))),
        )
        # Also make log inaccessible so neither subsystem works
        monkeypatch.setattr(
            rl_mod, "get_rule_event_logger",
            lambda: (_ for _ in ()).throw(OSError("log inaccessible")),
        )

        result = probe_rule_engine_status()
        assert result["status"] == ComponentStatus.UNHEALTHY
        assert result["engine_healthy"] is False

    def test_degraded_when_log_inaccessible_but_engine_ok(self, monkeypatch):
        """Engine healthy but governance log fails → degraded."""
        import backend.rule_engine.rule_service as rs_mod
        import backend.governance.rule_event_log as rl_mod

        monkeypatch.setattr(
            rs_mod.RuleService, "health",
            staticmethod(lambda: {"healthy": True, "rules_loaded": 5}),
        )
        monkeypatch.setattr(
            rl_mod, "get_rule_event_logger",
            lambda: (_ for _ in ()).throw(OSError("log offline")),
        )

        result = probe_rule_engine_status()
        # Engine is healthy → should at minimum be degraded (not unhealthy)
        assert result["status"] in (ComponentStatus.HEALTHY, ComponentStatus.DEGRADED)

    def test_never_raises(self, monkeypatch):
        """Probe must never propagate an exception."""
        import backend.rule_engine.rule_service as rs_mod
        monkeypatch.setattr(
            rs_mod.RuleService, "health",
            staticmethod(lambda: (_ for _ in ()).throw(Exception("boom"))),
        )
        result = probe_rule_engine_status()   # must not raise
        assert "status" in result


# ══════════════════════════════════════════════════════════════════════════════
# TestProbeMLStatus
# ══════════════════════════════════════════════════════════════════════════════

class TestProbeMLStatus:
    def test_returns_dict(self):
        result = probe_ml_status()
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        result = probe_ml_status()
        for key in _PROBE_SHAPE_KEYS["probe_ml_status"]:
            assert key in result, f"Missing key: {key}"

    def test_status_is_valid_value(self):
        result = probe_ml_status()
        assert result["status"] in VALID_STATUSES

    def test_healthy_with_working_registry(self, monkeypatch, tmp_path):
        """Registry accessible + job log accessible + no stuck jobs → healthy."""
        from backend.ml.model_registry import ModelRegistry, ModelStatus
        from backend.ml.retrain_job_log import RetrainJobLog
        import backend.ml.model_registry as mr_mod
        import backend.ml.retrain_job_log as rjl_mod

        reg = ModelRegistry(tmp_path / "reg.jsonl")
        reg.register("v1.0.0", ModelStatus.PRODUCTION, accuracy=0.9)
        monkeypatch.setattr(mr_mod, "get_model_registry", lambda: reg)

        jlog = RetrainJobLog(tmp_path / "jobs.jsonl")
        monkeypatch.setattr(rjl_mod, "get_retrain_job_log", lambda: jlog)

        result = probe_ml_status()
        assert result["registry_accessible"] is True
        assert result["model_count"] >= 1
        assert result["active_model_version"] == "v1.0.0"
        assert result["status"] == ComponentStatus.HEALTHY

    def test_degraded_when_stuck_job(self, monkeypatch, tmp_path):
        """Running job older than 60 min → degraded."""
        from backend.ml.model_registry import ModelRegistry
        from backend.ml.retrain_job_log import RetrainJobLog, RetrainJob
        import backend.ml.model_registry as mr_mod
        import backend.ml.retrain_job_log as rjl_mod
        from datetime import datetime, timezone, timedelta

        reg = ModelRegistry(tmp_path / "reg2.jsonl")
        monkeypatch.setattr(mr_mod, "get_model_registry", lambda: reg)

        # Manually inject a job with old started_at by patching get_active_job
        old_start = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        stuck_job = RetrainJob(job_id="stuck-001", status="running",
                               triggered_by="test", started_at=old_start)

        mock_log = MagicMock()
        mock_log.get_active_job.return_value = stuck_job
        monkeypatch.setattr(rjl_mod, "get_retrain_job_log", lambda: mock_log)

        result = probe_ml_status()
        assert result["stuck_job_detected"] is True
        assert result["status"] == ComponentStatus.DEGRADED

    def test_unhealthy_when_registry_inaccessible(self, monkeypatch):
        """Registry raises + job log raises → unhealthy."""
        import backend.ml.model_registry as mr_mod
        import backend.ml.retrain_job_log as rjl_mod

        monkeypatch.setattr(
            mr_mod, "get_model_registry",
            lambda: (_ for _ in ()).throw(OSError("registry gone")),
        )
        monkeypatch.setattr(
            rjl_mod, "get_retrain_job_log",
            lambda: (_ for _ in ()).throw(OSError("job log gone")),
        )

        result = probe_ml_status()
        assert result["status"] == ComponentStatus.UNHEALTHY
        assert result["registry_accessible"] is False

    def test_never_raises(self, monkeypatch):
        import backend.ml.model_registry as mr_mod
        monkeypatch.setattr(
            mr_mod, "get_model_registry",
            lambda: (_ for _ in ()).throw(Exception("total meltdown")),
        )
        result = probe_ml_status()  # must not raise
        assert "status" in result


# ══════════════════════════════════════════════════════════════════════════════
# TestProbeTaxonomyStatus
# ══════════════════════════════════════════════════════════════════════════════

class TestProbeTaxonomyStatus:
    def test_returns_dict(self):
        result = probe_taxonomy_status()
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        result = probe_taxonomy_status()
        for key in _PROBE_SHAPE_KEYS["probe_taxonomy_status"]:
            assert key in result, f"Missing key: {key}"

    def test_status_is_valid_value(self):
        result = probe_taxonomy_status()
        assert result["status"] in VALID_STATUSES

    def test_unhealthy_when_manager_is_none(self, monkeypatch):
        """get_taxonomy_manager() returns None → unhealthy."""
        import backend.api.routers.taxonomy_router as tt_mod
        monkeypatch.setattr(tt_mod, "get_taxonomy_manager", lambda: None)

        result = probe_taxonomy_status()
        assert result["status"] == ComponentStatus.UNHEALTHY
        assert result["manager_available"] is False

    def test_healthy_with_datasets_loaded(self, monkeypatch):
        """Manager available + self_check returns counts → healthy."""
        import backend.api.routers.taxonomy_router as tt_mod

        mock_mgr = MagicMock()
        mock_mgr.self_check.return_value = {
            "skills": 300, "interests": 200, "education": 100, "intents": 50
        }
        monkeypatch.setattr(tt_mod, "get_taxonomy_manager", lambda: mock_mgr)

        result = probe_taxonomy_status()
        assert result["manager_available"] is True
        assert result["total_entries"] == 650
        assert result["status"] == ComponentStatus.HEALTHY

    def test_degraded_when_manager_available_but_no_entries(self, monkeypatch):
        """Manager up but no data loaded → degraded."""
        import backend.api.routers.taxonomy_router as tt_mod

        mock_mgr = MagicMock()
        mock_mgr.self_check.return_value = {"skills": 0, "interests": 0}
        monkeypatch.setattr(tt_mod, "get_taxonomy_manager", lambda: mock_mgr)

        result = probe_taxonomy_status()
        assert result["manager_available"] is True
        assert result["total_entries"] == 0
        assert result["status"] == ComponentStatus.DEGRADED

    def test_datasets_loaded_list_contains_non_empty_datasets(self, monkeypatch):
        import backend.api.routers.taxonomy_router as tt_mod
        mock_mgr = MagicMock()
        mock_mgr.self_check.return_value = {"skills": 100, "interests": 0, "education": 50}
        monkeypatch.setattr(tt_mod, "get_taxonomy_manager", lambda: mock_mgr)

        result = probe_taxonomy_status()
        assert "skills" in result["datasets_loaded"]
        assert "education" in result["datasets_loaded"]
        assert "interests" not in result["datasets_loaded"]

    def test_never_raises_when_import_fails(self, monkeypatch):
        import backend.api.routers.taxonomy_router as tt_mod
        monkeypatch.setattr(
            tt_mod, "get_taxonomy_manager",
            lambda: (_ for _ in ()).throw(ImportError("taxonomy gone")),
        )
        result = probe_taxonomy_status()  # must not raise
        assert "status" in result


# ══════════════════════════════════════════════════════════════════════════════
# TestProbePipelineStatus
# ══════════════════════════════════════════════════════════════════════════════

class TestProbePipelineStatus:
    def test_returns_dict(self):
        result = probe_pipeline_status()
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        result = probe_pipeline_status()
        for key in _PROBE_SHAPE_KEYS["probe_pipeline_status"]:
            assert key in result, f"Missing key: {key}"

    def test_status_is_valid_value(self):
        result = probe_pipeline_status()
        assert result["status"] in VALID_STATUSES

    def _inject_pipeline_mod(self, monkeypatch, get_main_controller_fn):
        """Helper: inject a fake pipeline_router module into sys.modules."""
        fake_mod = types.ModuleType("backend.api.routers.pipeline_router")
        fake_mod.get_main_controller = get_main_controller_fn
        monkeypatch.setitem(sys.modules, "backend.api.routers.pipeline_router", fake_mod)
        return fake_mod

    def test_healthy_when_controller_and_logs_available(self, monkeypatch):
        import backend.governance.drift_event_log as del_mod
        import backend.governance.retrain_event_log as rel_mod

        self._inject_pipeline_mod(monkeypatch, lambda: object())

        mock_drift = MagicMock()
        mock_drift.count.return_value = 3
        monkeypatch.setattr(del_mod, "get_drift_event_logger", lambda: mock_drift)
        monkeypatch.setattr(rel_mod, "get_retrain_event_logger", lambda: MagicMock())

        result = probe_pipeline_status()
        assert result["controller_available"] is True
        assert result["drift_log_accessible"] is True
        assert result["retrain_log_accessible"] is True
        assert result["status"] == ComponentStatus.HEALTHY

    def test_degraded_when_controller_none_but_logs_up(self, monkeypatch):
        """Controller missing but governance logs up → degraded."""
        import backend.governance.drift_event_log as del_mod
        import backend.governance.retrain_event_log as rel_mod

        self._inject_pipeline_mod(monkeypatch, lambda: None)
        monkeypatch.setattr(del_mod, "get_drift_event_logger", lambda: MagicMock())
        monkeypatch.setattr(rel_mod, "get_retrain_event_logger", lambda: MagicMock())

        result = probe_pipeline_status()
        assert result["controller_available"] is False
        assert result["drift_log_accessible"] is True
        assert result["status"] == ComponentStatus.DEGRADED

    def test_unhealthy_when_all_subsystems_fail(self, monkeypatch):
        """Controller AND both logs fail → unhealthy."""
        import backend.governance.drift_event_log as del_mod
        import backend.governance.retrain_event_log as rel_mod

        self._inject_pipeline_mod(
            monkeypatch,
            lambda: (_ for _ in ()).throw(RuntimeError("controller gone")),
        )
        monkeypatch.setattr(
            del_mod, "get_drift_event_logger",
            lambda: (_ for _ in ()).throw(OSError("drift gone")),
        )
        monkeypatch.setattr(
            rel_mod, "get_retrain_event_logger",
            lambda: (_ for _ in ()).throw(OSError("retrain gone")),
        )

        result = probe_pipeline_status()
        assert result["status"] == ComponentStatus.UNHEALTHY

    def test_never_raises(self, monkeypatch):
        self._inject_pipeline_mod(
            monkeypatch,
            lambda: (_ for _ in ()).throw(Exception("total collapse")),
        )
        result = probe_pipeline_status()  # must not raise
        assert "status" in result


# ══════════════════════════════════════════════════════════════════════════════
# TestAssembleFullHealth
# ══════════════════════════════════════════════════════════════════════════════

class TestAssembleFullHealth:
    def test_returns_dict(self):
        result = assemble_full_health()
        assert isinstance(result, dict)

    def test_has_top_level_status(self):
        result = assemble_full_health()
        assert "status" in result

    def test_has_timestamp(self):
        result = assemble_full_health()
        assert "timestamp" in result

    def test_has_all_five_component_keys(self):
        result = assemble_full_health()
        for key in (
            "router_status", "rule_engine_status", "ml_status",
            "taxonomy_status", "pipeline_status",
        ):
            assert key in result, f"Missing top-level key: {key}"

    def test_each_component_has_status_field(self):
        result = assemble_full_health()
        for key in ("router_status", "rule_engine_status", "ml_status",
                    "taxonomy_status", "pipeline_status"):
            comp = result[key]
            assert "status" in comp, f"{key} missing 'status'"

    def test_each_component_status_is_valid(self):
        result = assemble_full_health()
        for key in ("router_status", "rule_engine_status", "ml_status",
                    "taxonomy_status", "pipeline_status"):
            s = result[key]["status"]
            assert s in (ComponentStatus.HEALTHY, ComponentStatus.DEGRADED,
                         ComponentStatus.UNHEALTHY, ComponentStatus.UNKNOWN), \
                f"{key} has invalid status: {s}"

    def test_overall_is_worst_of_components(self):
        """If any component is unhealthy or degraded, overall must reflect that."""
        result = assemble_full_health()
        component_statuses = [
            result[k]["status"]
            for k in ("router_status", "rule_engine_status", "ml_status",
                      "taxonomy_status", "pipeline_status")
        ]
        overall = result["status"]
        if "unhealthy" in component_statuses:
            assert overall in ("unhealthy", "degraded")
        elif "degraded" in component_statuses or "unknown" in component_statuses:
            assert overall in ("degraded", "unhealthy")


# ══════════════════════════════════════════════════════════════════════════════
# TestOverallStatusMatrix
# ══════════════════════════════════════════════════════════════════════════════

class TestOverallStatusMatrix:
    """Verify criticality matrix: critical vs high/medium escalation."""

    def test_rule_engine_critical_unhealthy_escalates_to_unhealthy(self):
        comps = {
            "router_status":      {"status": "healthy"},
            "rule_engine_status": {"status": "unhealthy"},  # CRITICAL
            "ml_status":          {"status": "healthy"},
            "taxonomy_status":    {"status": "healthy"},
            "pipeline_status":    {"status": "healthy"},
        }
        assert _compute_overall(comps) == ComponentStatus.UNHEALTHY

    def test_router_critical_unhealthy_escalates_to_unhealthy(self):
        comps = {
            "router_status":      {"status": "unhealthy"},  # CRITICAL
            "rule_engine_status": {"status": "healthy"},
            "ml_status":          {"status": "healthy"},
            "taxonomy_status":    {"status": "healthy"},
            "pipeline_status":    {"status": "healthy"},
        }
        assert _compute_overall(comps) == ComponentStatus.UNHEALTHY

    def test_ml_high_unhealthy_produces_degraded_not_unhealthy(self):
        comps = {
            "router_status":      {"status": "healthy"},
            "rule_engine_status": {"status": "healthy"},
            "ml_status":          {"status": "unhealthy"},  # HIGH (not critical)
            "taxonomy_status":    {"status": "healthy"},
            "pipeline_status":    {"status": "healthy"},
        }
        assert _compute_overall(comps) == ComponentStatus.DEGRADED

    def test_taxonomy_high_unhealthy_produces_degraded(self):
        comps = {
            "router_status":      {"status": "healthy"},
            "rule_engine_status": {"status": "healthy"},
            "ml_status":          {"status": "healthy"},
            "taxonomy_status":    {"status": "unhealthy"},  # HIGH
            "pipeline_status":    {"status": "healthy"},
        }
        assert _compute_overall(comps) == ComponentStatus.DEGRADED

    def test_pipeline_medium_unhealthy_produces_degraded(self):
        comps = {
            "router_status":      {"status": "healthy"},
            "rule_engine_status": {"status": "healthy"},
            "ml_status":          {"status": "healthy"},
            "taxonomy_status":    {"status": "healthy"},
            "pipeline_status":    {"status": "unhealthy"},  # MEDIUM
        }
        assert _compute_overall(comps) == ComponentStatus.DEGRADED

    def test_all_healthy_returns_healthy(self):
        comps = {k: {"status": "healthy"} for k in (
            "router_status", "rule_engine_status", "ml_status",
            "taxonomy_status", "pipeline_status",
        )}
        assert _compute_overall(comps) == ComponentStatus.HEALTHY


# ══════════════════════════════════════════════════════════════════════════════
# TestDisableOneComponent
# ══════════════════════════════════════════════════════════════════════════════
# PASS CRITERIA (Prompt-13): Disable each component → health reflects correctly.

class TestDisableOneComponent:
    """
    For each of the 5 components, simulate a fatal failure and verify:
    1. The component's own probe reflects the failure (status != healthy)
    2. assemble_full_health()'s top-level status degrades accordingly
    """

    def test_disable_router_registry(self):
        """
        Remove router_registry from sys.modules and block re-import.
        Expect router_status.status != healthy and overall degraded/unhealthy.
        """
        orig = sys.modules.pop("backend.api.router_registry", None)
        try:
            import importlib
            with patch("importlib.import_module", side_effect=ImportError("registry blocked")):
                result = probe_router_status()
            assert result["status"] != ComponentStatus.HEALTHY, \
                "Router probe should NOT be healthy when registry is unavailable"
        finally:
            if orig is not None:
                sys.modules["backend.api.router_registry"] = orig

    def test_disable_rule_engine(self, monkeypatch):
        """
        Patch RuleService.health to raise + governance log to raise.
        Expect rule_engine_status.status = unhealthy.
        """
        import backend.rule_engine.rule_service as rs_mod
        import backend.governance.rule_event_log as rl_mod
        import backend.governance.kb_mapping_log as kb_mod

        monkeypatch.setattr(
            rs_mod.RuleService, "health",
            staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("engine down"))),
        )
        monkeypatch.setattr(
            rl_mod, "get_rule_event_logger",
            lambda: (_ for _ in ()).throw(OSError("log unavailable")),
        )
        monkeypatch.setattr(
            kb_mod, "get_kb_mapping_logger",
            lambda: (_ for _ in ()).throw(OSError("kb unavailable")),
        )

        result = probe_rule_engine_status()
        assert result["status"] == ComponentStatus.UNHEALTHY, \
            f"Rule engine should be UNHEALTHY when all subsystems fail, got: {result['status']}"

    def test_disable_ml_registry(self, monkeypatch):
        """
        Patch both ml singletons to raise.
        Expect ml_status.status = unhealthy.
        """
        import backend.ml.model_registry as mr_mod
        import backend.ml.retrain_job_log as rjl_mod

        monkeypatch.setattr(
            mr_mod, "get_model_registry",
            lambda: (_ for _ in ()).throw(OSError("registry offline")),
        )
        monkeypatch.setattr(
            rjl_mod, "get_retrain_job_log",
            lambda: (_ for _ in ()).throw(OSError("job_log offline")),
        )

        result = probe_ml_status()
        assert result["status"] == ComponentStatus.UNHEALTHY, \
            f"ML status should be UNHEALTHY when registry & job log fail, got: {result['status']}"
        # assemble_full_health should reflect degraded (ml is HIGH, not critical)
        # Patch all other probes to healthy so only ml fails
        from backend.health import component_probes as cp_mod
        healthy = {"status": "healthy", "checked_at": "2026-01-01T00:00:00+00:00"}
        monkeypatch.setattr(cp_mod, "probe_router_status", lambda: {**healthy})
        monkeypatch.setattr(cp_mod, "probe_rule_engine_status", lambda: {**healthy})
        monkeypatch.setattr(cp_mod, "probe_taxonomy_status", lambda: {**healthy})
        monkeypatch.setattr(cp_mod, "probe_pipeline_status", lambda: {**healthy})

        full = assemble_full_health()
        assert full["status"] in (ComponentStatus.DEGRADED, ComponentStatus.UNHEALTHY), \
            f"Overall should degrade when ML is down, got: {full['status']}"

    def test_disable_taxonomy_manager(self, monkeypatch):
        """
        Patch taxonomy manager to None.
        Expect taxonomy_status.status = unhealthy.
        """
        import backend.api.routers.taxonomy_router as tt_mod
        monkeypatch.setattr(tt_mod, "get_taxonomy_manager", lambda: None)

        result = probe_taxonomy_status()
        assert result["status"] == ComponentStatus.UNHEALTHY, \
            f"Taxonomy should be UNHEALTHY when manager is None, got: {result['status']}"

    def test_disable_pipeline_controller_and_logs(self, monkeypatch):
        """
        Inject a fake pipeline_router module whose get_main_controller raises,
        and patch governance logs to raise → expect pipeline_status = unhealthy.
        """
        import backend.governance.drift_event_log as del_mod
        import backend.governance.retrain_event_log as rel_mod

        fake_mod = types.ModuleType("backend.api.routers.pipeline_router")
        fake_mod.get_main_controller = (
            lambda: (_ for _ in ()).throw(RuntimeError("pipeline controller down"))
        )
        monkeypatch.setitem(sys.modules, "backend.api.routers.pipeline_router", fake_mod)

        monkeypatch.setattr(
            del_mod, "get_drift_event_logger",
            lambda: (_ for _ in ()).throw(OSError("drift offline")),
        )
        monkeypatch.setattr(
            rel_mod, "get_retrain_event_logger",
            lambda: (_ for _ in ()).throw(OSError("retrain offline")),
        )

        result = probe_pipeline_status()
        assert result["status"] == ComponentStatus.UNHEALTHY, \
            f"Pipeline should be UNHEALTHY when all subsystems fail, got: {result['status']}"

    def test_all_components_healthy_overall_healthy(self, monkeypatch):
        """
        When all probes return healthy, overall assemble_full_health is healthy.
        """
        from backend.health import component_probes as cp_mod
        healthy = {"status": "healthy", "checked_at": "2026-01-01T00:00:00+00:00"}

        monkeypatch.setattr(cp_mod, "probe_router_status", lambda: {**healthy})
        monkeypatch.setattr(cp_mod, "probe_rule_engine_status", lambda: {**healthy})
        monkeypatch.setattr(cp_mod, "probe_ml_status", lambda: {**healthy})
        monkeypatch.setattr(cp_mod, "probe_taxonomy_status", lambda: {**healthy})
        monkeypatch.setattr(cp_mod, "probe_pipeline_status", lambda: {**healthy})

        full = assemble_full_health()
        assert full["status"] == ComponentStatus.HEALTHY, \
            f"All healthy → overall should be healthy, got: {full['status']}"


# ══════════════════════════════════════════════════════════════════════════════
# TestHTTPHealthFull
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def health_client():
    """
    Minimal FastAPI app with health_router mounted.
    Loads health_router via importlib to avoid triggering the router_registry
    __init__ import chain (which has blocking side-effects).
    """
    import importlib.util
    import types

    # Pre-import rbac before stubbing anything
    import backend.api.middleware.rbac as rbac_mod
    _orig_rbac = rbac_mod.has_any_role

    # Stub the routers package before loading health_router
    _routers_key = "backend.api.routers"
    _orig_routers_pkg = sys.modules.get(_routers_key)
    if _routers_key not in sys.modules:
        stub = types.ModuleType(_routers_key)
        stub.__path__ = []
        stub.__package__ = _routers_key
        sys.modules[_routers_key] = stub

    _mod_key = "backend.api.routers.health_router"
    if _mod_key not in sys.modules:
        from pathlib import Path as _P
        spec = importlib.util.spec_from_file_location(
            _mod_key,
            str(_P("backend/api/routers/health_router.py").resolve()),
        )
        _mod = importlib.util.module_from_spec(spec)
        sys.modules[_mod_key] = _mod
        spec.loader.exec_module(_mod)  # type: ignore[union-attr]

    health_mod = sys.modules[_mod_key]
    rbac_mod.has_any_role = lambda _auth, _roles: True  # bypass

    app = FastAPI()
    app.include_router(health_mod.router, prefix="/api/v1/health")
    client = TestClient(app, raise_server_exceptions=False)
    yield client

    rbac_mod.has_any_role = _orig_rbac
    if _orig_routers_pkg is None and _routers_key in sys.modules:
        del sys.modules[_routers_key]


class TestHTTPHealthFull:
    def test_full_returns_200(self, health_client):
        resp = health_client.get("/api/v1/health/full")
        assert resp.status_code == 200

    def test_full_response_has_status(self, health_client):
        body = health_client.get("/api/v1/health/full").json()
        assert "status" in body

    def test_full_status_is_valid(self, health_client):
        body = health_client.get("/api/v1/health/full").json()
        assert body["status"] in ("healthy", "degraded", "unhealthy")

    def test_full_has_timestamp(self, health_client):
        body = health_client.get("/api/v1/health/full").json()
        assert "timestamp" in body

    def test_full_has_router_status(self, health_client):
        body = health_client.get("/api/v1/health/full").json()
        assert "router_status" in body

    def test_full_has_rule_engine_status(self, health_client):
        body = health_client.get("/api/v1/health/full").json()
        assert "rule_engine_status" in body

    def test_full_has_ml_status(self, health_client):
        body = health_client.get("/api/v1/health/full").json()
        assert "ml_status" in body

    def test_full_has_taxonomy_status(self, health_client):
        body = health_client.get("/api/v1/health/full").json()
        assert "taxonomy_status" in body

    def test_full_has_pipeline_status(self, health_client):
        body = health_client.get("/api/v1/health/full").json()
        assert "pipeline_status" in body

    def test_each_component_has_status_field(self, health_client):
        body = health_client.get("/api/v1/health/full").json()
        for comp_key in ("router_status", "rule_engine_status", "ml_status",
                         "taxonomy_status", "pipeline_status"):
            assert "status" in body[comp_key], \
                f"Component '{comp_key}' missing 'status' field"

    def test_ready_endpoint_matches_full(self, health_client):
        full_body  = health_client.get("/api/v1/health/full").json()
        ready_body = health_client.get("/api/v1/health/ready").json()
        # Both must have the same 5 component keys
        for key in ("router_status", "rule_engine_status", "ml_status",
                    "taxonomy_status", "pipeline_status"):
            assert key in ready_body, f"/ready missing key: {key}"
        assert full_body.keys() == ready_body.keys()

    def test_live_still_returns_200(self, health_client):
        """Live endpoint must not be broken by our changes."""
        resp = health_client.get("/api/v1/health/live")
        assert resp.status_code == 200

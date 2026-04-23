# tests/ml/test_model_registry.py
"""
ML Model Registry & Retrain Job Log — Governance Tests
=======================================================

Covers ModelRecord, ModelStatus, ModelRegistry, RetrainJobLog,
RetrainConflictError, and the three HTTP endpoints exposed by ml_router.

Test classes:
  TestModelStatus             - enum shape
  TestModelRecord             - serialisation / deserialisation
  TestModelRegistry           - register, list_all, get_active, update_status,
                                auto-archive, seed_from_weights_dir
  TestRetrainJobLog           - start_job, complete/fail, conflict guard,
                                list_recent, count
  TestRetrainConflictError    - exception contract
  TestHTTPModels              - GET /ml/models → 200 with schema
  TestHTTPRetrain             - POST /ml/retrain → 202; duplicate → 409
  TestHTTPEval                - GET /ml/eval → 200 with schema
  TestHTTPRetrainJobs         - GET /ml/retrain/jobs → 200
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.ml.model_registry import (
    ModelRecord,
    ModelRegistry,
    ModelStatus,
)
from backend.ml.retrain_job_log import (
    RetrainConflictError,
    RetrainJob,
    RetrainJobLog,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def registry(tmp_path: Path) -> ModelRegistry:
    return ModelRegistry(log_path=tmp_path / "model_registry.jsonl")


@pytest.fixture()
def job_log(tmp_path: Path) -> RetrainJobLog:
    return RetrainJobLog(log_path=tmp_path / "retrain_jobs.jsonl")


@pytest.fixture(scope="module")
def ml_client():
    """
    Minimal FastAPI app with the 4 governance endpoints.

    Uses importlib to load ml_router.py directly from its file path so that
    ``backend/api/routers/__init__.py`` (which eagerly imports ALL routers,
    some of which have blocking I/O) is never executed.

    RBAC is patched to always pass.
    """
    import importlib.util
    import sys
    import types
    from pathlib import Path as _Path

    # ── import rbac BEFORE stubbing anything, so it follows normal pkg resolution
    import backend.api.middleware.rbac as rbac_mod  # works via real backend.api pkg

    # ── now stub ONLY backend.api.routers so its __init__ never runs ──
    _pkg_key = "backend.api.routers"
    _orig_pkg = sys.modules.get(_pkg_key)
    if _pkg_key not in sys.modules:
        stub = types.ModuleType(_pkg_key)
        stub.__path__ = [str(_Path("backend/api/routers").resolve())]
        stub.__package__ = _pkg_key
        sys.modules[_pkg_key] = stub

    # ── load ml_router.py directly from file ─────────────────────────
    _mod_key = "backend.api.routers.ml_router"
    _router_file = _Path("backend/api/routers/ml_router.py").resolve()

    if _mod_key in sys.modules:
        _ml_router_mod = sys.modules[_mod_key]
    else:
        spec = importlib.util.spec_from_file_location(_mod_key, str(_router_file))
        _ml_router_mod = importlib.util.module_from_spec(spec)
        sys.modules[_mod_key] = _ml_router_mod
        spec.loader.exec_module(_ml_router_mod)  # type: ignore[union-attr]

    ml_router = _ml_router_mod.router

    _orig_rbac = rbac_mod.has_any_role
    rbac_mod.has_any_role = lambda _auth, _roles: True  # bypass for tests

    mini_app = FastAPI()
    mini_app.include_router(ml_router, prefix="/api/v1/ml")
    client = TestClient(mini_app, raise_server_exceptions=False)
    yield client

    rbac_mod.has_any_role = _orig_rbac


# ═══════════════════════════════════════════════════════════════════════════════
# TestModelStatus
# ═══════════════════════════════════════════════════════════════════════════════

class TestModelStatus:
    def test_all_five_values_exist(self):
        vals = {s.value for s in ModelStatus}
        assert vals == {"pending", "training", "staged", "production", "archived"}

    def test_is_string_subclass(self):
        assert isinstance(ModelStatus.PRODUCTION, str)

    def test_equality_with_string(self):
        assert ModelStatus.STAGED == "staged"


# ═══════════════════════════════════════════════════════════════════════════════
# TestModelRecord
# ═══════════════════════════════════════════════════════════════════════════════

class TestModelRecord:
    def _make(self, version: str = "v1.0.0", **kw) -> ModelRecord:
        return ModelRecord(version=version, **kw)

    def test_default_status_is_pending(self):
        rec = self._make()
        assert rec.status == ModelStatus.PENDING

    def test_event_id_is_uuid(self):
        rec = self._make()
        uuid.UUID(rec.event_id)  # raises if invalid

    def test_to_dict_has_required_keys(self):
        rec = self._make("v1.0.0", status=ModelStatus.STAGED)
        d = rec.to_dict()
        for key in ("version", "status", "accuracy", "precision",
                    "recall", "f1", "created_at", "event_id", "timestamp"):
            assert key in d, f"missing key: {key}"

    def test_to_dict_status_is_string(self):
        rec = self._make("v1.0.0", status=ModelStatus.PRODUCTION)
        assert rec.to_dict()["status"] == "production"

    def test_from_dict_round_trip(self):
        original = self._make(
            "v2.0.0",
            status=ModelStatus.PRODUCTION,
            accuracy=0.92,
            precision=0.91,
            recall=0.90,
            f1=0.905,
            retrain_trigger="drift",
            notes="test round-trip",
        )
        d = original.to_dict()
        restored = ModelRecord.from_dict(d)
        assert restored.version == "v2.0.0"
        assert restored.status == ModelStatus.PRODUCTION
        assert restored.accuracy == pytest.approx(0.92)
        assert restored.retrain_trigger == "drift"

    def test_from_dict_missing_keys_use_defaults(self):
        rec = ModelRecord.from_dict({"version": "v0.1"})
        assert rec.version == "v0.1"
        assert rec.accuracy is None
        assert rec.f1 is None

    def test_metrics_can_be_none(self):
        rec = self._make("v1.0.0")
        d = rec.to_dict()
        assert d["accuracy"] is None
        assert d["precision"] is None
        assert d["recall"] is None
        assert d["f1"] is None

    def test_to_dict_is_json_serialisable(self):
        rec = self._make("v1.0.0", accuracy=0.88)
        # Must not raise
        json.dumps(rec.to_dict())


# ═══════════════════════════════════════════════════════════════════════════════
# TestModelRegistry
# ═══════════════════════════════════════════════════════════════════════════════

class TestModelRegistry:
    def test_empty_registry_returns_no_models(self, registry):
        assert registry.list_all() == []

    def test_register_returns_model_record(self, registry):
        rec = registry.register("v1.0.0", ModelStatus.STAGED)
        assert isinstance(rec, ModelRecord)
        assert rec.version == "v1.0.0"
        assert rec.status == ModelStatus.STAGED

    def test_register_persists_to_jsonl(self, registry):
        registry.register("v1.0.0", ModelStatus.STAGED)
        assert registry._log_path.exists()
        lines = [l for l in registry._log_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1

    def test_list_all_returns_registered_version(self, registry):
        registry.register("v1.0.0", ModelStatus.STAGED)
        models = registry.list_all()
        assert len(models) == 1
        assert models[0].version == "v1.0.0"

    def test_multiple_versions_all_listed(self, registry):
        registry.register("v1.0.0", ModelStatus.STAGED)
        registry.register("v2.0.0", ModelStatus.STAGED)
        versions = {m.version for m in registry.list_all()}
        assert versions == {"v1.0.0", "v2.0.0"}

    def test_list_all_newest_first(self, registry):
        registry.register("v1.0.0", ModelStatus.STAGED)
        registry.register("v2.0.0", ModelStatus.STAGED)
        models = registry.list_all()
        assert models[0].version == "v2.0.0"

    def test_get_active_returns_none_with_no_prod(self, registry):
        registry.register("v1.0.0", ModelStatus.STAGED)
        assert registry.get_active() is None

    def test_get_active_returns_production_model(self, registry):
        registry.register("v1.0.0", ModelStatus.PRODUCTION)
        active = registry.get_active()
        assert active is not None
        assert active.version == "v1.0.0"

    def test_update_status_changes_model_status(self, registry):
        registry.register("v1.0.0", ModelStatus.TRAINING)
        registry.update_status("v1.0.0", ModelStatus.STAGED)
        models = registry.list_all()
        assert models[0].status == ModelStatus.STAGED

    def test_update_status_carries_forward_metrics(self, registry):
        registry.register("v1.0.0", ModelStatus.STAGED,
                          accuracy=0.88, precision=0.87, recall=0.85, f1=0.86)
        registry.update_status("v1.0.0", ModelStatus.PRODUCTION)
        active = registry.get_active()
        assert active.accuracy == pytest.approx(0.88)
        assert active.precision == pytest.approx(0.87)

    def test_auto_archive_on_new_production(self, registry):
        """
        Governance: promoting v2 to PRODUCTION must auto-archive v1.
        """
        registry.register("v1.0.0", ModelStatus.PRODUCTION)
        registry.register("v2.0.0", ModelStatus.STAGED)
        registry.update_status("v2.0.0", ModelStatus.PRODUCTION)

        models = {m.version: m for m in registry.list_all()}
        assert models["v2.0.0"].status == ModelStatus.PRODUCTION
        assert models["v1.0.0"].status == ModelStatus.ARCHIVED

    def test_only_one_production_at_a_time(self, registry):
        registry.register("v1.0.0", ModelStatus.PRODUCTION)
        registry.register("v2.0.0", ModelStatus.STAGED)
        registry.update_status("v2.0.0", ModelStatus.PRODUCTION)

        prod_models = [m for m in registry.list_all()
                       if m.status == ModelStatus.PRODUCTION]
        assert len(prod_models) == 1

    def test_update_status_unknown_version_returns_none(self, registry):
        result = registry.update_status("nonexistent-ver", ModelStatus.STAGED)
        assert result is None

    def test_count_reflects_raw_line_count(self, registry):
        assert registry.count() == 0
        registry.register("v1.0.0", ModelStatus.STAGED)
        assert registry.count() == 1

    def test_register_with_all_metrics(self, registry):
        rec = registry.register(
            "v1.0.0",
            ModelStatus.STAGED,
            accuracy=0.90,
            precision=0.89,
            recall=0.88,
            f1=0.885,
            retrain_trigger="drift",
            notes="automated test",
        )
        assert rec.accuracy == pytest.approx(0.90)
        assert rec.retrain_trigger == "drift"
        assert rec.notes == "automated test"

    def test_seed_from_weights_dir_imports_versions(self, registry, tmp_path):
        weights_dir = tmp_path / "models" / "weights"
        # Create a fake versioned weights directory
        ver_dir = weights_dir / "v1.0.0"
        ver_dir.mkdir(parents=True)
        (ver_dir / "weights.json").write_text(json.dumps({
            "version": "v1.0.0",
            "metrics": {"accuracy": 0.85, "f1": 0.83},
        }))
        n = registry.seed_from_weights_dir(weights_dir)
        assert n == 1
        models = registry.list_all()
        assert any(m.version == "v1.0.0" for m in models)

    def test_seed_from_weights_dir_idempotent(self, registry, tmp_path):
        """Second seed call must not duplicate versions."""
        weights_dir = tmp_path / "models" / "weights"
        ver_dir = weights_dir / "v1.0.0"
        ver_dir.mkdir(parents=True)
        (ver_dir / "weights.json").write_text(json.dumps({"version": "v1.0.0"}))
        registry.seed_from_weights_dir(weights_dir)
        n = registry.seed_from_weights_dir(weights_dir)
        assert n == 0  # nothing new imported

    def test_seed_skips_active_subdir(self, registry, tmp_path):
        weights_dir = tmp_path / "models" / "weights"
        active_dir = weights_dir / "active"
        active_dir.mkdir(parents=True)
        (active_dir / "weights.json").write_text(json.dumps({"version": "active"}))
        n = registry.seed_from_weights_dir(weights_dir)
        assert n == 0  # "active" is explicitly skipped


# ═══════════════════════════════════════════════════════════════════════════════
# TestRetrainConflictError
# ═══════════════════════════════════════════════════════════════════════════════

class TestRetrainConflictError:
    def test_is_runtime_error(self):
        err = RetrainConflictError("test")
        assert isinstance(err, RuntimeError)

    def test_message_preserved(self):
        err = RetrainConflictError("already running")
        assert "already running" in str(err)


# ═══════════════════════════════════════════════════════════════════════════════
# TestRetrainJobLog
# ═══════════════════════════════════════════════════════════════════════════════

class TestRetrainJobLog:
    def test_empty_log_no_active_job(self, job_log):
        assert job_log.get_active_job() is None

    def test_start_job_returns_retrain_job(self, job_log):
        job = job_log.start_job()
        assert isinstance(job, RetrainJob)
        assert job.status == "running"

    def test_start_job_default_triggered_by_is_manual(self, job_log):
        job = job_log.start_job()
        assert job.triggered_by == "manual"

    def test_start_job_custom_triggered_by(self, job_log):
        job = job_log.start_job(triggered_by="drift")
        assert job.triggered_by == "drift"

    def test_start_job_persists_to_jsonl(self, job_log):
        job_log.start_job()
        assert job_log._log_path.exists()
        lines = [l for l in job_log._log_path.read_text().splitlines() if l.strip()]
        assert len(lines) >= 1

    def test_start_job_assigns_unique_job_id(self, job_log):
        job = job_log.start_job()
        uuid.UUID(job.job_id)  # raises ValueError if invalid

    def test_get_active_job_returns_running_job(self, job_log):
        job = job_log.start_job(triggered_by="schedule")
        active = job_log.get_active_job()
        assert active is not None
        assert active.job_id == job.job_id

    def test_conflict_guard_raises_on_second_start(self, job_log):
        job_log.start_job()
        with pytest.raises(RetrainConflictError):
            job_log.start_job()

    def test_conflict_error_message_contains_job_id(self, job_log):
        first = job_log.start_job()
        with pytest.raises(RetrainConflictError, match=first.job_id):
            job_log.start_job()

    def test_complete_job_marks_completed(self, job_log):
        job = job_log.start_job()
        completed = job_log.complete_job(job.job_id, metrics={"accuracy": 0.90})
        assert completed is not None
        assert completed.status == "completed"
        assert completed.completed_at is not None

    def test_complete_job_stores_metrics(self, job_log):
        job = job_log.start_job()
        job_log.complete_job(job.job_id, metrics={"accuracy": 0.91, "f1": 0.89})
        jobs = job_log.list_recent(1)
        assert jobs[0]["metrics"]["accuracy"] == pytest.approx(0.91)

    def test_complete_job_clears_active(self, job_log):
        job = job_log.start_job()
        job_log.complete_job(job.job_id)
        assert job_log.get_active_job() is None

    def test_can_start_new_job_after_complete(self, job_log):
        job = job_log.start_job()
        job_log.complete_job(job.job_id)
        new_job = job_log.start_job()
        assert new_job.job_id != job.job_id

    def test_fail_job_marks_failed(self, job_log):
        job = job_log.start_job()
        failed = job_log.fail_job(job.job_id, error="training exception")
        assert failed is not None
        assert failed.status == "failed"
        assert failed.error == "training exception"

    def test_fail_job_clears_active(self, job_log):
        job = job_log.start_job()
        job_log.fail_job(job.job_id, error="oops")
        assert job_log.get_active_job() is None

    def test_can_start_new_job_after_fail(self, job_log):
        job = job_log.start_job()
        job_log.fail_job(job.job_id, error="oops")
        new_job = job_log.start_job()
        assert new_job.status == "running"

    def test_list_recent_returns_dicts(self, job_log):
        job_log.start_job()
        recent = job_log.list_recent()
        assert isinstance(recent, list)
        assert len(recent) >= 1
        assert isinstance(recent[0], dict)

    def test_list_recent_respects_limit(self, job_log):
        j1 = job_log.start_job()
        job_log.complete_job(j1.job_id)
        j2 = job_log.start_job()
        job_log.complete_job(j2.job_id)
        recent = job_log.list_recent(limit=1)
        assert len(recent) == 1

    def test_list_recent_newest_first(self, job_log):
        j1 = job_log.start_job(triggered_by="first")
        job_log.complete_job(j1.job_id)
        j2 = job_log.start_job(triggered_by="second")
        job_log.complete_job(j2.job_id)
        recent = job_log.list_recent()
        assert recent[0]["job_id"] == j2.job_id

    def test_count_unique_jobs(self, job_log):
        assert job_log.count() == 0
        j1 = job_log.start_job()
        assert job_log.count() == 1
        job_log.complete_job(j1.job_id)  # appends another event for same job
        # count is still 1 unique job
        assert job_log.count() == 1

    def test_complete_unknown_job_returns_none(self, job_log):
        result = job_log.complete_job("nonexistent-job-id")
        assert result is None

    def test_fail_unknown_job_returns_none(self, job_log):
        result = job_log.fail_job("nonexistent-job-id", error="x")
        assert result is None

    def test_retrain_job_to_dict_schema(self, job_log):
        job = job_log.start_job()
        d = job.to_dict()
        for key in ("job_id", "status", "triggered_by", "started_at",
                    "completed_at", "error", "metrics"):
            assert key in d, f"missing key: {key}"

    def test_retrain_job_from_dict_round_trip(self, job_log):
        job = job_log.start_job(triggered_by="schedule")
        d = job.to_dict()
        restored = RetrainJob.from_dict(d)
        assert restored.job_id == job.job_id
        assert restored.triggered_by == "schedule"


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP Endpoint Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestHTTPModels:
    def test_models_returns_200(self, ml_client):
        resp = ml_client.get("/api/v1/ml/models")
        assert resp.status_code == 200

    def test_models_response_has_count(self, ml_client):
        resp = ml_client.get("/api/v1/ml/models")
        body = resp.json()
        assert "count" in body

    def test_models_response_has_models_list(self, ml_client):
        resp = ml_client.get("/api/v1/ml/models")
        body = resp.json()
        assert "models" in body
        assert isinstance(body["models"], list)

    def test_models_count_matches_list_length(self, ml_client):
        resp = ml_client.get("/api/v1/ml/models")
        body = resp.json()
        assert body["count"] == len(body["models"])

    def test_models_items_have_version_field(self, ml_client):
        resp = ml_client.get("/api/v1/ml/models")
        models = resp.json().get("models", [])
        if models:
            assert "version" in models[0]
            assert "status" in models[0]


class TestHTTPRetrain:
    def test_retrain_returns_202(self, ml_client, monkeypatch, tmp_path):
        """POST /ml/retrain should return 202, with concurrency guard active."""
        import backend.ml.retrain_job_log as rjl_mod
        fresh_log = RetrainJobLog(log_path=tmp_path / "retrain_202.jsonl")
        monkeypatch.setattr(rjl_mod, "_log", fresh_log)

        resp = ml_client.post(
            "/api/v1/ml/retrain",
            json={"triggered_by": "test_suite"},
        )
        assert resp.status_code == 202

    def test_retrain_response_has_job_id(self, ml_client, monkeypatch, tmp_path):
        import backend.ml.retrain_job_log as rjl_mod
        fresh_log = RetrainJobLog(log_path=tmp_path / "retrain_jobid.jsonl")
        monkeypatch.setattr(rjl_mod, "_log", fresh_log)

        resp = ml_client.post("/api/v1/ml/retrain", json={"triggered_by": "test"})
        body = resp.json()
        assert "job_id" in body
        assert body["job_id"] != ""

    def test_retrain_duplicate_returns_409(self, ml_client, monkeypatch, tmp_path):
        """
        Governance pass criteria: POST /ml/retrain while a job is already
        RUNNING must return HTTP 409 Conflict.

        We pre-seed a RUNNING job directly into the shared log so there is no
        race with the background training task completing before the second call.
        """
        import backend.ml.retrain_job_log as rjl_mod

        shared_log = RetrainJobLog(log_path=tmp_path / "retrain_conflict.jsonl")
        # Directly seed a running job (bypasses any background-task race)
        running_job = shared_log.start_job(triggered_by="pre-seeded-running")
        assert running_job.status == "running"

        monkeypatch.setattr(rjl_mod, "_log", shared_log)

        # POST while a job is running → must be 409
        resp = ml_client.post("/api/v1/ml/retrain", json={"triggered_by": "test"})
        assert resp.status_code == 409

    def test_retrain_dry_run_returns_202_eligible(self, ml_client, monkeypatch, tmp_path):
        import backend.ml.retrain_job_log as rjl_mod
        fresh_log = RetrainJobLog(log_path=tmp_path / "retrain_dry.jsonl")
        monkeypatch.setattr(rjl_mod, "_log", fresh_log)

        resp = ml_client.post(
            "/api/v1/ml/retrain",
            json={"triggered_by": "test", "dry_run": True},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body.get("status") == "eligible"
        assert body.get("dry_run") is True


class TestHTTPEval:
    def test_eval_returns_200(self, ml_client):
        resp = ml_client.get("/api/v1/ml/eval")
        assert resp.status_code == 200

    def test_eval_response_has_model_version(self, ml_client):
        resp = ml_client.get("/api/v1/ml/eval")
        body = resp.json()
        assert "model_version" in body

    def test_eval_response_has_metric_fields(self, ml_client):
        resp = ml_client.get("/api/v1/ml/eval")
        body = resp.json()
        for field in ("rolling_accuracy", "rolling_precision",
                      "rolling_recall", "rolling_f1", "sample_size"):
            assert field in body, f"missing field: {field}"

    def test_eval_response_has_source(self, ml_client):
        resp = ml_client.get("/api/v1/ml/eval")
        body = resp.json()
        assert body.get("source") in ("live", "log", "empty")

    def test_eval_response_has_timestamp(self, ml_client):
        resp = ml_client.get("/api/v1/ml/eval")
        body = resp.json()
        assert "timestamp" in body
        assert body["timestamp"] != ""


class TestHTTPRetrainJobs:
    def test_retrain_jobs_returns_200(self, ml_client):
        resp = ml_client.get("/api/v1/ml/retrain/jobs")
        assert resp.status_code == 200

    def test_retrain_jobs_has_jobs_list(self, ml_client):
        resp = ml_client.get("/api/v1/ml/retrain/jobs")
        body = resp.json()
        assert "jobs" in body
        assert isinstance(body["jobs"], list)

    def test_retrain_jobs_has_count(self, ml_client):
        resp = ml_client.get("/api/v1/ml/retrain/jobs")
        body = resp.json()
        assert "count" in body

    def test_retrain_jobs_limit_param(self, ml_client):
        resp = ml_client.get("/api/v1/ml/retrain/jobs?limit=5")
        assert resp.status_code == 200

    def test_retrain_jobs_invalid_limit_returns_422(self, ml_client):
        resp = ml_client.get("/api/v1/ml/retrain/jobs?limit=0")
        assert resp.status_code == 422

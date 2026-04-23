# backend/tests/test_ops_extended.py
"""Unit tests for ops modules with no/partial coverage:
    - security.disaster_recovery
    - maintenance.dependency_manager
    - quality.quality_gate, schema_validator, drift_report
    - versioning.dataset, config_version, snapshot, reproducible
    - reproducibility.version_manager, snapshot_manager, seed_control
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DisasterRecoveryPlan
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestDisasterRecovery:
    @pytest.fixture
    def plan(self):
        from backend.ops.security.disaster_recovery import DisasterRecoveryPlan
        return DisasterRecoveryPlan()

    def test_default_rpo_rto(self, plan):
        assert plan.rpo_hours == 6.0
        assert plan.rto_hours == 2.0

    def test_list_scenarios(self, plan):
        scenarios = plan.list_scenarios()
        assert "data_corruption" in scenarios
        assert "crawler_failure" in scenarios
        assert "scoring_failure" in scenarios
        assert "full_recovery" in scenarios

    def test_get_scenario(self, plan):
        steps = plan.get_scenario("data_corruption")
        assert isinstance(steps, list)
        assert len(steps) >= 1
        assert "title" in steps[0]

    def test_get_scenario_unknown(self, plan):
        steps = plan.get_scenario("nonexistent")
        assert steps == [] or steps is None  # depends on impl

    def test_estimate_recovery_time(self, plan):
        for s in plan.list_scenarios():
            t = plan.estimate_recovery_time(s)
            assert t > 0

    def test_plan_summary(self, plan):
        summary = plan.get_plan_summary()
        assert "rpo_hours" in summary
        assert "rto_hours" in summary
        assert isinstance(summary, dict)

    def test_export_plan(self, plan, tmp_dir):
        path = plan.export_plan(tmp_dir / "plan.json")
        assert path.exists()
        data = json.loads(path.read_text())
        assert isinstance(data, dict)

    def test_recovery_step_to_dict(self):
        from backend.ops.security.disaster_recovery import RecoveryStep
        step = RecoveryStep(
            order=1, title="Stop pipeline",
            description="Halt the running pipeline", command="kill -9",
        )
        d = step.to_dict()
        assert d["order"] == 1
        assert d["title"] == "Stop pipeline"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DependencyManager
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestDependencyManager:
    @pytest.fixture
    def dm(self):
        from backend.ops.maintenance.dependency_manager import DependencyManager
        return DependencyManager()

    def test_freeze_environment(self, dm):
        env = dm.freeze_environment()
        assert isinstance(env, dict)
        assert len(env) > 0
        # pip should always be installed
        assert any("pip" in k.lower() for k in env)

    def test_check_requirements(self, dm):
        result = dm.check_requirements()
        assert isinstance(result, dict)
        assert "installed_count" in result or "missing" in result

    def test_generate_lockfile(self, dm, tmp_dir):
        lock = dm.generate_lockfile(tmp_dir / "requirements.lock")
        assert lock.exists()
        content = lock.read_text()
        assert "==" in content  # pinned versions

    def test_parse_requirements(self, dm, tmp_dir):
        req_file = tmp_dir / "req.txt"
        req_file.write_text("fastapi==0.104.0\nuvicorn>=0.24.0\nrequests\n# comment\n")
        result = dm._parse_requirements(req_file)
        assert "fastapi" in result
        assert result["fastapi"] == "0.104.0"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PipelineSchemaValidator
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestPipelineSchemaValidator:
    @pytest.fixture
    def validator(self):
        from backend.ops.quality.schema_validator import PipelineSchemaValidator
        return PipelineSchemaValidator()

    def test_register_and_validate(self, validator):
        from pydantic import BaseModel
        class TestSchema(BaseModel):
            name: str
            value: int
        validator.register_schema("test_stage", TestSchema)
        result = validator.validate_batch("test_stage", [{"name": "ok", "value": 1}])
        assert result.valid_count == 1
        assert result.passed is True

    def test_validate_invalid_records(self, validator):
        from pydantic import BaseModel
        class TestSchema(BaseModel):
            name: str
            value: int
        validator.register_schema("test_stage", TestSchema)
        result = validator.validate_batch("test_stage", [{"name": "ok"}])  # missing value
        assert result.invalid_count >= 1

    def test_validation_result_properties(self):
        from backend.ops.quality.schema_validator import SchemaValidationResult
        r = SchemaValidationResult()
        r.valid_count = 8
        r.invalid_count = 2
        assert r.pass_rate == 0.8
        assert r.passed is False

    def test_validation_result_to_dict(self):
        from backend.ops.quality.schema_validator import SchemaValidationResult
        r = SchemaValidationResult()
        d = r.to_dict()
        assert isinstance(d, dict)
        assert "valid" in d

    def test_custom_rule(self, validator):
        from pydantic import BaseModel
        class TestSchema(BaseModel):
            name: str
            value: int
        validator.register_schema("custom_stage", TestSchema)
        validator.add_custom_rule(
            "custom_stage", "positive_value",
            lambda rec: rec.get("value", 0) > 0,
            "Value must be positive",
        )
        result = validator.validate_batch("custom_stage", [{"name": "ok", "value": -1}])
        assert len(result.warnings) >= 1 or result.invalid_count >= 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DriftReport
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestDriftReport:
    @pytest.fixture
    def report(self):
        from backend.ops.quality.drift_report import DriftReport
        return DriftReport(
            run_id="r001",
            timestamp="2026-01-01T00:00:00",
            blocked=False,
            severity="info",
            message="No drift",
            max_psi=0.05,
            max_jsd=0.03,
            feature_drifts={"salary_min": {"psi": 0.05, "jsd": 0.03}},
            volume_drift={"old": 100, "new": 105, "change_pct": 5.0},
            schema_drift={"added": [], "removed": []},
        )

    def test_to_dict(self, report):
        d = report.to_dict()
        assert d["run_id"] == "r001"
        assert "feature_drifts" in d

    def test_to_json(self, report):
        j = report.to_json()
        parsed = json.loads(j)
        assert parsed["run_id"] == "r001"

    def test_to_text(self, report):
        text = report.to_text()
        assert "r001" in text
        assert isinstance(text, str)

    def test_save(self, report, tmp_dir):
        path = report.save(tmp_dir)
        assert path.exists()

    def test_to_alert_payload(self, report):
        payload = report.to_alert_payload()
        assert isinstance(payload, dict)
        assert "severity" in payload


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DatasetVersionManager
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestDatasetVersionManager:
    @pytest.fixture
    def dvm(self, tmp_dir):
        from backend.ops.versioning.dataset import DatasetVersionManager
        return DatasetVersionManager(base_dir=tmp_dir / "versions")

    @pytest.fixture
    def sample_csv(self, tmp_dir):
        csv_path = tmp_dir / "data.csv"
        csv_path.write_text("id,title,company\n1,Dev,Corp\n2,QA,Tech\n")
        return csv_path

    def test_create_and_get_version(self, dvm, sample_csv):
        ver = dvm.create_version("jobs", sample_csv)
        assert ver is not None
        assert ver.dataset_name == "jobs"
        got = dvm.get_version("jobs", ver.version_id)
        assert got is not None

    def test_list_versions(self, dvm, sample_csv):
        dvm.create_version("jobs", sample_csv)
        versions = dvm.list_versions("jobs")
        assert len(versions) >= 1

    def test_get_latest_version(self, dvm, sample_csv):
        dvm.create_version("jobs", sample_csv)
        latest = dvm.get_latest_version("jobs")
        assert latest is not None

    def test_verify_integrity(self, dvm, sample_csv):
        ver = dvm.create_version("jobs", sample_csv)
        result = dvm.verify_integrity("jobs", ver.version_id)
        assert result.get("valid", result.get("verified", result.get("integrity"))) is not False

    def test_diff_versions(self, dvm, sample_csv, tmp_dir):
        ver1 = dvm.create_version("jobs", sample_csv)
        csv2 = tmp_dir / "data2.csv"
        csv2.write_text("id,title,company\n1,Dev,Corp\n2,QA,Tech\n3,PM,Biz\n")
        ver2 = dvm.create_version("jobs", csv2)
        diff = dvm.diff_versions("jobs", ver1.version_id, ver2.version_id)
        assert isinstance(diff, dict)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ConfigVersionManager
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestConfigVersionManager:
    @pytest.fixture
    def cvm(self, tmp_dir):
        from backend.ops.versioning.config_version import ConfigVersionManager
        return ConfigVersionManager(base_dir=tmp_dir / "config_versions")

    def test_save_and_get(self, cvm):
        vid = cvm.save_version({"key": "value"}, "initial config")
        assert vid is not None
        v = cvm.get_version(vid)
        assert v is not None

    def test_skip_duplicate(self, cvm):
        vid1 = cvm.save_version({"key": "value"}, "first")
        vid2 = cvm.save_version({"key": "value"}, "same")
        assert vid1 == vid2  # identical config not saved twice

    def test_get_latest(self, cvm):
        cvm.save_version({"k": 1}, "v1")
        latest = cvm.get_latest()
        assert latest is not None

    def test_list_versions(self, cvm):
        cvm.save_version({"k": 1}, "v1")
        cvm.save_version({"k": 2}, "v2")
        versions = cvm.list_versions()
        assert len(versions) >= 1

    def test_diff(self, cvm):
        vid1 = cvm.save_version({"a": 1, "b": 2}, "v1")
        vid2 = cvm.save_version({"a": 1, "c": 3}, "v2")
        diff = cvm.diff(vid1, vid2)
        assert diff["is_different"] is True

    def test_rollback(self, cvm):
        vid1 = cvm.save_version({"k": "original"}, "v1")
        cvm.save_version({"k": "changed"}, "v2")
        rolled = cvm.rollback_to(vid1)
        assert rolled is not None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PipelineSnapshotManager
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestPipelineSnapshotManager:
    @pytest.fixture
    def sm(self, tmp_dir):
        from backend.ops.versioning.snapshot import PipelineSnapshotManager
        return PipelineSnapshotManager(base_dir=tmp_dir / "snapshots")

    def test_create_snapshot(self, sm):
        snap = sm.create_snapshot("run001", config={"key": "val"})
        assert isinstance(snap, dict)
        assert snap.get("run_id") == "run001"

    def test_load_snapshot(self, sm):
        sm.create_snapshot("run002", config={"k": "v"})
        loaded = sm.load_snapshot("run002")
        assert loaded is not None

    def test_list_snapshots(self, sm):
        sm.create_snapshot("run003", config={})
        snaps = sm.list_snapshots()
        assert len(snaps) >= 1

    def test_compare_snapshots(self, sm):
        sm.create_snapshot("runA", config={"a": 1})
        sm.create_snapshot("runB", config={"b": 2})
        diff = sm.compare_snapshots("runA", "runB")
        assert isinstance(diff, dict)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ReproducibleRunManager
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestReproducibleRunManager:
    @pytest.fixture
    def rrm(self, tmp_dir):
        from backend.ops.versioning.reproducible import ReproducibleRunManager
        return ReproducibleRunManager(base_dir=tmp_dir / "runs")

    @pytest.fixture
    def input_file(self, tmp_dir):
        f = tmp_dir / "input.csv"
        f.write_text("id,data\n1,hello\n2,world\n")
        return f

    def test_prepare_run(self, rrm, input_file):
        ctx = rrm.prepare_run("run001", config={"k": "v"}, input_path=input_file)
        assert ctx["status"] == "prepared"
        assert "seed" in ctx

    def test_finalize_run(self, rrm, input_file, tmp_dir):
        rrm.prepare_run("run002", config={}, input_path=input_file)
        output = tmp_dir / "output.csv"
        output.write_text("id,score\n1,0.8\n")
        ctx = rrm.finalize_run("run002", output_path=output, status="completed")
        assert ctx["status"] == "completed"

    def test_list_runs(self, rrm, input_file):
        rrm.prepare_run("run003", config={}, input_path=input_file)
        runs = rrm.list_runs()
        assert len(runs) >= 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SeedController
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestSeedController:
    @pytest.fixture
    def sc(self):
        from backend.ops.reproducibility.seed_control import SeedController
        return SeedController()

    def test_generate_seed_deterministic(self, sc):
        s1 = sc.generate_seed("run_abc")
        s2 = sc.generate_seed("run_abc")
        assert s1 == s2

    def test_generate_seed_different_ids(self, sc):
        s1 = sc.generate_seed("run_a")
        s2 = sc.generate_seed("run_b")
        assert s1 != s2

    def test_set_seeds(self, sc):
        import random
        state = sc.set_seeds(42)
        assert state.seed == 42
        assert state.sources_set["python_random"] is True
        # random should produce deterministic output after seeding
        val1 = random.random()
        sc.set_seeds(42)
        val2 = random.random()
        assert val1 == val2

    def test_set_from_run_id(self, sc):
        state = sc.set_from_run_id("run_test")
        assert state.seed is not None
        assert sc.current_seed == state.seed

    def test_capture_and_restore_state(self, sc):
        import random
        sc.set_seeds(42)
        state = sc.capture_state()
        # Generate some values
        vals_before = [random.random() for _ in range(5)]
        # Restore state
        sc.restore_state(state)
        vals_after = [random.random() for _ in range(5)]
        assert vals_before == vals_after

    def test_seed_state_to_dict(self, sc):
        state = sc.set_seeds(42)
        d = state.to_dict()
        assert d["seed"] == 42
        assert isinstance(d, dict)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Reproducibility VersionManager
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestReproVersionManager:
    @pytest.fixture
    def vm(self, tmp_dir):
        from backend.ops.reproducibility.version_manager import VersionManager
        return VersionManager(base_dir=tmp_dir / "runs")

    def test_init_run(self, vm):
        manifest = vm.init_run("run_001", config={"key": "value"}, seed=42)
        assert manifest.run_id == "run_001"
        assert manifest.status == "running"

    def test_save_artifact_list(self, vm):
        vm.init_run("run_002", config={}, seed=1)
        data = [{"id": 1, "name": "test"}, {"id": 2, "name": "test2"}]
        artifact = vm.save_artifact("run_002", "raw", data, "raw_data.csv")
        assert artifact.filename == "raw_data.csv"
        assert artifact.record_count == 2

    def test_save_artifact_dict(self, vm):
        vm.init_run("run_003", config={}, seed=1)
        data = {"summary": "ok", "count": 5}
        artifact = vm.save_artifact("run_003", "score", data, "summary.json")
        assert artifact.filename == "summary.json"

    def test_finalize_run(self, vm):
        vm.init_run("run_004", config={}, seed=1)
        manifest = vm.finalize_run("run_004", status="completed")
        assert manifest.status == "completed"
        assert manifest.duration_seconds >= 0

    def test_verify_run(self, vm):
        vm.init_run("run_005", config={}, seed=1)
        vm.save_artifact("run_005", "raw", [{"x": 1}], "data.csv")
        vm.finalize_run("run_005", status="completed")
        result = vm.verify_run("run_005")
        assert result["verified"] is True

    def test_list_runs(self, vm):
        vm.init_run("run_006", config={}, seed=1)
        runs = vm.list_runs()
        assert len(runs) >= 1

    def test_hash_data(self, vm):
        h1 = vm.hash_data("hello")
        h2 = vm.hash_data("hello")
        assert h1 == h2
        h3 = vm.hash_data("world")
        assert h1 != h3

    def test_compare_runs(self, vm):
        vm.init_run("runA", config={"k": 1}, seed=42)
        vm.save_artifact("runA", "raw", [{"x": 1}], "data.csv")
        vm.finalize_run("runA", status="completed")

        vm.init_run("runB", config={"k": 1}, seed=42)
        vm.save_artifact("runB", "raw", [{"x": 1}], "data.csv")
        vm.finalize_run("runB", status="completed")

        result = vm.compare_runs("runA", "runB")
        assert result["reproduced"] is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Reproducibility SnapshotManager
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestReproSnapshotManager:
    @pytest.fixture
    def sm(self, tmp_dir):
        from backend.ops.reproducibility.snapshot_manager import SnapshotManager
        (tmp_dir / "run_001").mkdir(parents=True, exist_ok=True)
        return SnapshotManager(base_dir=tmp_dir)

    def test_capture_snapshot(self, sm):
        snap = sm.capture("run_001", config_hash="abc123", seed=42)
        assert snap.run_id == "run_001"
        assert snap.seed == 42

    def test_save_and_load(self, sm):
        snap = sm.capture("run_001", config_hash="abc", seed=1)
        sm.save("run_001", snap)
        loaded = sm.load("run_001")
        assert loaded is not None
        assert loaded.run_id == "run_001"

    def test_list_snapshots(self, sm):
        snap = sm.capture("run_001", config_hash="abc", seed=1)
        sm.save("run_001", snap)
        snaps = sm.list_snapshots()
        assert len(snaps) >= 1

    def test_diff_snapshots(self, sm, tmp_dir):
        (tmp_dir / "run_002").mkdir(parents=True, exist_ok=True)
        snap1 = sm.capture("run_001", config_hash="abc", seed=1)
        snap2 = sm.capture("run_002", config_hash="xyz", seed=2)
        sm.save("run_001", snap1)
        sm.save("run_002", snap2)
        diff = sm.diff("run_001", "run_002")
        assert diff["identical"] is False

    def test_verify_env(self, sm):
        snap = sm.capture("run_001", config_hash="abc", seed=1)
        result = sm.verify_env(snap)
        assert isinstance(result, dict)
        assert "match" in result or "checks" in result

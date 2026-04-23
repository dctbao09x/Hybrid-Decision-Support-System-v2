# backend/ops/tests/test_ops_modules.py
"""
Tests for ops modules that were previously untested:
- Resource: BrowserResourceMonitor, LeakDetector, ConcurrencyController, BottleneckTracer
- Monitoring: AlertManager, SLAMonitor, AnomalyDetector, HealthCheckService, ExplanationMonitor
- Security: SecretManager, AccessLogger, BackupManager
- Maintenance: RetentionManager, AuditTrail, UpdatePolicy, DependencyManager
- Integration: OpsHub
"""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest


# ─── Resource ────────────────────────────────────────────────────

class TestBottleneckTracer:
    """Tests for BottleneckTracer."""

    def test_sync_span(self):
        from backend.ops.resource.bottleneck import BottleneckTracer
        tracer = BottleneckTracer()
        with tracer.span("test_stage", "test_op"):
            pass
        analysis = tracer.analyze()
        assert "test_stage" in analysis.get("per_stage", {})

    @pytest.mark.asyncio
    async def test_async_span(self):
        from backend.ops.resource.bottleneck import BottleneckTracer
        tracer = BottleneckTracer()
        async with tracer.async_span("crawl", "fetch_page"):
            await asyncio.sleep(0.01)
        analysis = tracer.analyze()
        assert "crawl" in analysis.get("per_stage", {})

    def test_top_n(self):
        from backend.ops.resource.bottleneck import BottleneckTracer
        tracer = BottleneckTracer()
        for i in range(5):
            with tracer.span("stage", f"op_{i}"):
                pass
        analysis = tracer.analyze(top_n=3)
        assert len(analysis.get("top_slowest", [])) <= 3


class TestConcurrencyController:
    """Tests for ConcurrencyController."""

    @pytest.mark.asyncio
    async def test_acquire_release_browser(self):
        from backend.ops.resource.concurrency import ConcurrencyController
        ctrl = ConcurrencyController(max_browsers=2)
        result = await ctrl.acquire_browser()
        assert result is True
        ctrl.release_browser()

    @pytest.mark.asyncio
    async def test_rate_limiting(self):
        from backend.ops.resource.concurrency import ConcurrencyController
        ctrl = ConcurrencyController(max_browsers=2)
        # Should not block for first request
        await asyncio.wait_for(ctrl.rate_limit("test.com"), timeout=2.0)


class TestLeakDetector:
    """Tests for LeakDetector."""

    def test_collect_and_analyze(self):
        from backend.ops.resource.leak_detector import LeakDetector
        detector = LeakDetector()
        # analyze with insufficient samples should still return a report
        report = detector.analyze()
        assert hasattr(report, "memory_leak")
        assert hasattr(report, "cpu_leak")
        assert report.severity == "none"


# ─── Monitoring ──────────────────────────────────────────────────

class TestAlertManager:
    """Tests for AlertManager."""

    @pytest.mark.asyncio
    async def test_fire_alert(self, tmp_dir):
        from backend.ops.monitoring.alerts import AlertManager, FileAlertChannel
        mgr = AlertManager()
        # Replace file channel with tmp
        mgr._channels = [FileAlertChannel(path=tmp_dir / "alerts.jsonl")]
        result = await mgr.fire("Test Alert", "This is a test", source="unit_test")
        assert result is True
        assert (tmp_dir / "alerts.jsonl").exists()

    @pytest.mark.asyncio
    async def test_deduplication(self):
        from backend.ops.monitoring.alerts import AlertManager
        mgr = AlertManager(cooldown_seconds=60.0)
        await mgr.fire("Dedup Test", "msg1", source="test", force=True)
        result = await mgr.fire("Dedup Test", "msg2", source="test")
        assert result is False  # deduplicated

    @pytest.mark.asyncio
    async def test_fire_if(self):
        from backend.ops.monitoring.alerts import AlertManager
        mgr = AlertManager()
        r1 = await mgr.fire_if(False, "Nope", "should not fire", force=True)
        assert r1 is False
        r2 = await mgr.fire_if(True, "Yes", "should fire", force=True)
        assert r2 is True

    def test_summary(self):
        from backend.ops.monitoring.alerts import AlertManager
        mgr = AlertManager()
        summary = mgr.get_summary()
        assert "total_alerts" in summary


class TestSLAMonitor:
    """Tests for SLAMonitor."""

    def test_record_and_check(self):
        from backend.ops.monitoring.sla import SLAMonitor
        sla = SLAMonitor()
        sla.record_metric("pipeline_duration_seconds", 3000)
        dashboard = sla.get_dashboard()
        assert len(dashboard["slas"]) >= 5

    def test_violation_detection(self):
        from backend.ops.monitoring.sla import SLAMonitor
        sla = SLAMonitor()
        # Exceed pipeline_duration SLA (default max 7200s)
        sla.record_metric("pipeline_duration_seconds", 9999)
        violations = sla.get_violations()
        assert len(violations) >= 1


class TestAnomalyDetector:
    """Tests for AnomalyDetector."""

    def test_record_and_detect(self):
        from backend.ops.monitoring.anomaly import AnomalyDetector
        detector = AnomalyDetector()
        # Feed normal values
        for v in [100, 102, 98, 101, 99, 100, 103, 97]:
            detector.record("metric", v)
        # Feed anomalous value
        detector.record("metric", 500)
        stats = detector.get_stats("metric")
        assert stats is not None

    def test_batch_anomalies(self):
        from backend.ops.monitoring.anomaly import AnomalyDetector
        detector = AnomalyDetector()
        for v in range(50):
            detector.record("metric_a", v)
        anomalies = detector.detect_batch_anomalies({"metric_a": 999})
        assert isinstance(anomalies, list)


class TestHealthCheckService:
    """Tests for HealthCheckService."""

    @pytest.mark.asyncio
    async def test_check_disk_space(self):
        from backend.ops.monitoring.health import HealthCheckService
        result = await HealthCheckService.check_disk_space()
        assert result["status"] in ("healthy", "unhealthy")

    @pytest.mark.asyncio
    async def test_check_memory(self):
        from backend.ops.monitoring.health import HealthCheckService
        result = await HealthCheckService.check_memory()
        assert "percent" in result.get("details", {})

    @pytest.mark.asyncio
    async def test_check_all_basic(self):
        from backend.ops.monitoring.health import HealthCheckService
        service = HealthCheckService()
        service.register_check("disk_space", HealthCheckService.check_disk_space)
        service.register_check("memory", HealthCheckService.check_memory)
        result = await service.check_all()
        assert "status" in result
        assert "components" in result


class TestExplanationMonitor:
    """Tests for ExplanationMonitor."""

    def test_record_complete_explanation(self):
        from backend.ops.monitoring.explanation import ExplanationMonitor
        mon = ExplanationMonitor()
        mon.record_scored_career("Software Engineer")
        trace = {
            "components": [
                {"component_name": "study", "score": 0.8},
                {"component_name": "interest", "score": 0.7},
                {"component_name": "market", "score": 0.6},
                {"component_name": "growth", "score": 0.5},
                {"component_name": "risk", "score": 0.3},
            ],
            "total_score": 0.65,
        }
        metrics = mon.record_explanation("Software Engineer", trace, latency_ms=50)
        assert metrics.has_all_components is True

    def test_record_incomplete_explanation(self):
        from backend.ops.monitoring.explanation import ExplanationMonitor
        mon = ExplanationMonitor()
        mon.record_scored_career("Designer")
        trace = {
            "components": [
                {"component_name": "study", "score": 0.8},
                {"component_name": "interest", "score": 0.7},
            ],
            "total_score": 0.75,
        }
        metrics = mon.record_explanation("Designer", trace, latency_ms=30)
        assert metrics.has_all_components is False

    def test_dashboard(self):
        from backend.ops.monitoring.explanation import ExplanationMonitor
        mon = ExplanationMonitor()
        for i in range(5):
            mon.record_scored_career(f"Career_{i}")
            trace = {
                "components": [
                    {"component_name": c, "score": 0.5}
                    for c in ["study", "interest", "market", "growth", "risk"]
                ],
                "total_score": 0.5,
            }
            mon.record_explanation(f"Career_{i}", trace, latency_ms=10 + i)
        dashboard = mon.get_dashboard()
        assert dashboard["total_explanations"] == 5
        assert dashboard["completeness_rate"] == 1.0

    def test_quality_check(self):
        from backend.ops.monitoring.explanation import ExplanationMonitor
        mon = ExplanationMonitor()
        result = mon.check_quality()
        assert "healthy" in result


# ─── Security ────────────────────────────────────────────────────

class TestSecretManager:
    """Tests for SecretManager."""

    def test_get_from_env(self, monkeypatch):
        from backend.ops.security.secrets import SecretManager
        monkeypatch.setenv("LLM_API_KEY", "test-key-123")
        mgr = SecretManager()
        assert mgr.get("LLM_API_KEY") == "test-key-123"

    def test_mask(self, monkeypatch):
        from backend.ops.security.secrets import SecretManager
        monkeypatch.setenv("LLM_API_KEY", "sk-1234567890abcdef")
        mgr = SecretManager()
        masked = mgr.mask("LLM_API_KEY")
        assert masked.startswith("sk-1")
        assert masked.endswith("cdef")
        assert "****" in masked

    def test_validate(self, monkeypatch):
        from backend.ops.security.secrets import SecretManager
        monkeypatch.setenv("LLM_API_KEY", "test")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
        mgr = SecretManager()
        result = mgr.validate()
        assert result["all_required_present"] is True

    def test_env_template(self):
        from backend.ops.security.secrets import SecretManager
        template = SecretManager.generate_env_template()
        assert "LLM_API_KEY" in template
        assert "DATABASE_URL" in template


class TestAccessLogger:
    """Tests for AccessLogger."""

    def test_log_and_retrieve(self, tmp_dir):
        from backend.ops.security.access_log import AccessLogger
        logger = AccessLogger(log_path=tmp_dir / "access.jsonl")
        logger.log("test_action", actor="tester", resource="data.csv")
        recent = logger.get_recent(limit=5)
        assert len(recent) == 1
        assert recent[0]["action"] == "test_action"

    def test_convenience_methods(self, tmp_dir):
        from backend.ops.security.access_log import AccessLogger
        logger = AccessLogger(log_path=tmp_dir / "access.jsonl")
        logger.log_pipeline_start("run_001")
        logger.log_crawl_complete("topcv", 150)
        logger.log_config_change("scoring_weights", "old", "new")
        assert len(logger.get_recent()) == 3


class TestBackupManager:
    """Tests for BackupManager."""

    def test_create_full_backup(self, tmp_dir):
        from backend.ops.security.backup import BackupManager
        # Create some test data
        data_dir = tmp_dir / "data"
        data_dir.mkdir()
        (data_dir / "test.csv").write_text("a,b\n1,2\n")
        config_dir = tmp_dir / "config"
        config_dir.mkdir()
        (config_dir / "test.yaml").write_text("key: value\n")

        mgr = BackupManager(
            backup_dir=tmp_dir / "backups",
            data_dirs=[data_dir],
            config_dirs=[config_dir],
        )
        result = mgr.create_full_backup(label="test")
        assert "error" not in result
        assert result["files"] >= 2

    def test_list_backups(self, tmp_dir):
        from backend.ops.security.backup import BackupManager
        mgr = BackupManager(backup_dir=tmp_dir / "backups")
        backups = mgr.list_backups()
        assert isinstance(backups, list)


# ─── Maintenance ─────────────────────────────────────────────────

class TestRetentionManager:
    """Tests for RetentionManager."""

    def test_dry_run(self, tmp_dir):
        from backend.ops.maintenance.retention import RetentionManager, RetentionPolicy
        # Create some old files
        policy = RetentionPolicy("test", tmp_dir, max_age_days=0, pattern="*.txt")
        (tmp_dir / "old.txt").write_text("old data")
        mgr = RetentionManager(policies=[policy], dry_run=True)
        result = mgr.enforce_all()
        assert result["details"]["test"]["dry_run"] is True
        # File should still exist in dry run
        assert (tmp_dir / "old.txt").exists()

    def test_status(self, tmp_dir):
        from backend.ops.maintenance.retention import RetentionManager, RetentionPolicy
        policy = RetentionPolicy("logs", tmp_dir, max_age_days=30, pattern="*.log")
        mgr = RetentionManager(policies=[policy])
        status = mgr.get_status()
        assert "logs" in status


class TestAuditTrail:
    """Tests for AuditTrail."""

    def test_record_and_query(self, tmp_dir):
        from backend.ops.maintenance.audit_trail import AuditTrail
        trail = AuditTrail(log_dir=tmp_dir / "audit")
        trail.record("test_event", "pipeline", "Test description")
        results = trail.query(category="pipeline")
        assert len(results) == 1
        assert results[0]["event_type"] == "test_event"

    def test_convenience_methods(self, tmp_dir):
        from backend.ops.maintenance.audit_trail import AuditTrail
        trail = AuditTrail(log_dir=tmp_dir / "audit")
        trail.record_pipeline_run("run_01", "success", stages=4, duration=120.0)
        trail.record_data_change("jobs", "insert", records=100)
        trail.record_config_change("weights", old_value="0.25", new_value="0.30")
        summary = trail.get_summary()
        assert summary["total_events"] == 3

    def test_persistence(self, tmp_dir):
        from backend.ops.maintenance.audit_trail import AuditTrail
        trail = AuditTrail(log_dir=tmp_dir / "audit")
        trail.record("persist_test", "data", "Should be persisted")
        # Check file was written
        log_files = list((tmp_dir / "audit").glob("audit_*.jsonl"))
        assert len(log_files) == 1
        content = log_files[0].read_text()
        assert "persist_test" in content


class TestUpdatePolicy:
    """Tests for UpdatePolicy."""

    def test_check_updates_due(self, tmp_dir):
        from backend.ops.maintenance.update_policy import UpdatePolicy
        policy = UpdatePolicy(state_path=tmp_dir / "update_state.json")
        due = policy.check_updates_due()
        # All components should be due since no checks recorded
        assert len(due) > 0

    def test_record_check(self, tmp_dir):
        from backend.ops.maintenance.update_policy import UpdatePolicy
        policy = UpdatePolicy(state_path=tmp_dir / "update_state.json")
        policy.record_check("dependencies")
        policy.record_update("dependencies", version="2025.01")
        dashboard = policy.get_dashboard()
        assert dashboard["total_components"] == 5


# ─── Integration ─────────────────────────────────────────────────

class TestOpsHub:
    """Tests for OpsHub integration layer."""

    def test_lazy_initialization(self):
        from backend.ops.integration import OpsHub
        hub = OpsHub()
        # Accessing property should not raise
        assert hub.scheduler is not None
        assert hub.checkpoint is not None
        assert hub.alerts is not None

    def test_same_instance_returned(self):
        from backend.ops.integration import OpsHub
        hub = OpsHub()
        a1 = hub.alerts
        a2 = hub.alerts
        assert a1 is a2

    @pytest.mark.asyncio
    async def test_startup_shutdown(self):
        from backend.ops.integration import OpsHub
        hub = OpsHub()
        await hub.startup()
        assert hub._started is True
        await hub.shutdown()
        assert hub._started is False

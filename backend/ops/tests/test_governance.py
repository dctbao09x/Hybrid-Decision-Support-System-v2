# backend/ops/tests/test_governance.py
"""
Governance Platform Tests
=========================

Comprehensive tests for Stage 6 - OPS/Governance Platform
Target: ≥80% coverage
"""

import pytest
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import json


class TestOpsModels:
    """Tests for governance models."""

    def test_ops_record_creation(self):
        """Test OpsRecord creation with default values."""
        from backend.ops.governance.models import OpsRecord, InferenceStatus
        
        record = OpsRecord(
            request_id="req-001",
            endpoint="/api/v1/infer",
            latency_ms=150.0,
            status=InferenceStatus.SUCCESS,
        )
        
        assert record.request_id == "req-001"
        assert record.endpoint == "/api/v1/infer"
        assert record.latency_ms == 150.0
        assert record.status == InferenceStatus.SUCCESS
        assert record.cached is False

    def test_ops_record_to_dict(self):
        """Test OpsRecord serialization."""
        from backend.ops.governance.models import OpsRecord, InferenceStatus
        
        record = OpsRecord(
            request_id="req-002",
            endpoint="/api/v1/chat",
            latency_ms=250.0,
            status=InferenceStatus.SUCCESS,
            model="gpt-4",
            tokens_in=100,
            tokens_out=200,
        )
        
        data = record.to_dict()
        
        assert data["request_id"] == "req-002"
        assert data["latency_ms"] == 250.0
        assert data["status"] == "success"
        assert data["model"] == "gpt-4"

    def test_inference_status_enum(self):
        """Test InferenceStatus enum values."""
        from backend.ops.governance.models import InferenceStatus
        
        assert InferenceStatus.SUCCESS.value == "success"
        assert InferenceStatus.ERROR.value == "error"
        assert InferenceStatus.TIMEOUT.value == "timeout"
        assert InferenceStatus.DEGRADED.value == "degraded"
        assert InferenceStatus.CACHED.value == "cached"

    def test_cost_record(self):
        """Test CostRecord creation."""
        from backend.ops.governance.models import CostRecord
        
        record = CostRecord(
            request_id="req-003",
            component="llm",
            cost_usd=0.05,
        )
        
        assert record.request_id == "req-003"
        assert record.component == "llm"
        assert record.cost_usd == 0.05

    def test_drift_record(self):
        """Test DriftRecord creation."""
        from backend.ops.governance.models import DriftRecord
        
        record = DriftRecord(
            feature="age",
            drift_score=0.15,
            threshold=0.1,
            baseline_mean=30.0,
            current_mean=35.0,
        )
        
        assert record.feature == "age"
        assert record.drift_score == 0.15
        assert record.is_drifted is True  # 0.15 > 0.1


class TestSLAContracts:
    """Tests for SLA contracts module."""

    def test_sla_target_creation(self):
        """Test SLATarget creation."""
        from backend.ops.sla.contracts import SLATarget, SLASeverity
        
        target = SLATarget(
            name="latency_p95",
            metric="latency_p95_ms",
            threshold=500,
            comparison="<=",
            severity=SLASeverity.WARNING,
        )
        
        assert target.name == "latency_p95"
        assert target.threshold == 500
        assert target.severity == SLASeverity.WARNING

    def test_sla_target_check_passed(self):
        """Test SLA target check when value is within threshold."""
        from backend.ops.sla.contracts import SLATarget
        
        target = SLATarget(
            name="error_rate",
            metric="error_rate",
            threshold=0.05,
            comparison="<=",
        )
        
        result = target.check(0.03)
        
        assert result["passed"] is True
        assert result["actual_value"] == 0.03

    def test_sla_target_check_failed(self):
        """Test SLA target check when value exceeds threshold."""
        from backend.ops.sla.contracts import SLATarget
        
        target = SLATarget(
            name="latency",
            metric="latency_ms",
            threshold=200,
            comparison="<=",
        )
        
        result = target.check(350)
        
        assert result["passed"] is False
        assert result["actual_value"] == 350
        assert result["threshold"] == 200

    def test_sla_target_comparison_operators(self):
        """Test different comparison operators."""
        from backend.ops.sla.contracts import SLATarget
        
        # Greater than or equal
        target_gte = SLATarget(
            name="availability",
            metric="uptime",
            threshold=0.999,
            comparison=">=",
        )
        assert target_gte.check(0.9999)["passed"] is True
        assert target_gte.check(0.998)["passed"] is False
        
        # Less than
        target_lt = SLATarget(
            name="errors",
            metric="error_count",
            threshold=10,
            comparison="<",
        )
        assert target_lt.check(5)["passed"] is True
        assert target_lt.check(10)["passed"] is False

    def test_sla_contract_creation(self):
        """Test SLAContract creation."""
        from backend.ops.sla.contracts import SLAContract, SLATarget
        
        targets = [
            SLATarget(name="latency", metric="latency_ms", threshold=500),
            SLATarget(name="errors", metric="error_rate", threshold=0.01),
        ]
        
        contract = SLAContract(
            contract_id="sla-001",
            name="Standard SLA",
            targets=targets,
        )
        
        assert contract.contract_id == "sla-001"
        assert len(contract.targets) == 2
        assert contract.enabled is True

    def test_sla_contract_evaluate(self):
        """Test SLA contract evaluation."""
        from backend.ops.sla.contracts import SLAContract, SLATarget
        
        contract = SLAContract(
            contract_id="sla-002",
            name="Test SLA",
            targets=[
                SLATarget(name="latency", metric="latency_ms", threshold=500),
                SLATarget(name="errors", metric="error_rate", threshold=0.05),
            ],
        )
        
        metrics = {"latency_ms": 300, "error_rate": 0.02}
        results = contract.evaluate(metrics)
        
        assert len(results) == 2
        assert all(r["passed"] for r in results)

    def test_default_contracts_exist(self):
        """Test default contracts are defined."""
        from backend.ops.sla.contracts import (
            DEFAULT_CONTRACT,
            CRITICAL_CONTRACT,
            BATCH_CONTRACT,
        )
        
        assert DEFAULT_CONTRACT is not None
        assert DEFAULT_CONTRACT.contract_id == "default"
        assert CRITICAL_CONTRACT.contract_id == "critical"
        assert BATCH_CONTRACT.contract_id == "batch"


class TestSLAEvaluator:
    """Tests for SLA evaluator module."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_sla.db"

    def test_evaluator_initialization(self, temp_db):
        """Test SLAEvaluator initialization."""
        from backend.ops.sla.evaluator import SLAEvaluator
        
        evaluator = SLAEvaluator(db_path=temp_db)
        
        assert evaluator is not None
        assert len(evaluator._contracts) > 0  # Default contracts registered

    def test_register_contract(self, temp_db):
        """Test registering a custom contract."""
        from backend.ops.sla.evaluator import SLAEvaluator
        from backend.ops.sla.contracts import SLAContract, SLATarget
        
        evaluator = SLAEvaluator(db_path=temp_db)
        
        contract = SLAContract(
            contract_id="custom-001",
            name="Custom SLA",
            targets=[SLATarget(name="test", metric="test_metric", threshold=100)],
        )
        
        evaluator.register_contract(contract)
        
        assert "custom-001" in evaluator._contracts

    def test_evaluate_success(self, temp_db):
        """Test successful evaluation."""
        from backend.ops.sla.evaluator import SLAEvaluator
        
        evaluator = SLAEvaluator(db_path=temp_db)
        
        metrics = {
            "uptime": 0.9999,
            "latency_p95_ms": 300,
            "latency_p99_ms": 450,
            "error_rate": 0.001,
        }
        
        result = evaluator.evaluate("default", metrics)
        
        assert result["contract_id"] == "default"
        assert "results" in result
        assert "violations" in result

    def test_evaluate_with_violation(self, temp_db):
        """Test evaluation that produces violations."""
        from backend.ops.sla.evaluator import SLAEvaluator
        from backend.ops.sla.contracts import SLAContract, SLATarget, SLASeverity
        
        evaluator = SLAEvaluator(db_path=temp_db)
        
        # Register a strict contract
        contract = SLAContract(
            contract_id="strict",
            name="Strict SLA",
            targets=[
                SLATarget(
                    name="latency",
                    metric="latency_ms",
                    threshold=100,
                    severity=SLASeverity.CRITICAL,
                ),
            ],
        )
        evaluator.register_contract(contract)
        
        # Evaluate with high latency
        metrics = {"latency_ms": 500}
        result = evaluator.evaluate("strict", metrics)
        
        assert len(result["violations"]) > 0
        assert result["violations"][0]["severity"] == "critical"

    def test_get_recent_violations(self, temp_db):
        """Test fetching recent violations."""
        from backend.ops.sla.evaluator import SLAEvaluator
        from backend.ops.sla.contracts import SLAContract, SLATarget
        
        evaluator = SLAEvaluator(db_path=temp_db)
        
        # Create violations
        contract = SLAContract(
            contract_id="test",
            name="Test",
            targets=[SLATarget(name="test", metric="m", threshold=10)],
        )
        evaluator.register_contract(contract)
        evaluator.evaluate("test", {"m": 100})
        
        violations = evaluator.get_recent_violations(hours=1)
        
        assert len(violations) >= 1

    def test_get_dashboard(self, temp_db):
        """Test dashboard data generation."""
        from backend.ops.sla.evaluator import SLAEvaluator
        
        evaluator = SLAEvaluator(db_path=temp_db)
        
        dashboard = evaluator.get_dashboard()
        
        assert "contracts" in dashboard
        assert "current_status" in dashboard
        assert "compliance_rate" in dashboard


class TestSLAReporter:
    """Tests for SLA reporter module."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for reports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_reporter_initialization(self, temp_dir):
        """Test SLAReporter initialization."""
        from backend.ops.sla.reporter import SLAReporter
        
        reporter = SLAReporter(output_dir=temp_dir)
        
        assert reporter is not None

    def test_generate_report(self, temp_dir):
        """Test report generation."""
        from backend.ops.sla.reporter import SLAReporter, SLAReportPeriod
        
        reporter = SLAReporter(output_dir=temp_dir)
        period = SLAReportPeriod.weekly()
        
        report = reporter.generate_report(period, "weekly")
        
        assert report.report_type == "weekly"
        assert report.period.days == 7
        assert report.overall_compliance >= 0

    def test_export_csv(self, temp_dir):
        """Test CSV export."""
        from backend.ops.sla.reporter import SLAReporter, SLAReportPeriod
        
        reporter = SLAReporter(output_dir=temp_dir)
        report = reporter.generate_report(SLAReportPeriod.weekly(), "weekly")
        
        csv_content = reporter.export_csv(report)
        
        assert "SLA Compliance Report" in csv_content
        assert report.report_id in csv_content

    def test_export_json(self, temp_dir):
        """Test JSON export."""
        from backend.ops.sla.reporter import SLAReporter, SLAReportPeriod
        
        reporter = SLAReporter(output_dir=temp_dir)
        report = reporter.generate_report(SLAReportPeriod.weekly(), "weekly")
        
        json_content = reporter.export_json(report)
        data = json.loads(json_content)
        
        assert data["report_id"] == report.report_id
        assert data["report_type"] == "weekly"


class TestRiskManager:
    """Tests for risk management module."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_risk.db"

    def test_risk_manager_initialization(self, temp_db):
        """Test RiskManager initialization."""
        from backend.ops.governance.risk import RiskManager
        
        manager = RiskManager(db_path=temp_db)
        
        assert manager is not None

    def test_risk_weights_normalization(self):
        """Test risk weights normalization."""
        from backend.ops.governance.risk import RiskWeights
        
        weights = RiskWeights(drift=2.0, latency=2.0, error_rate=2.0, cost_overrun=2.0)
        normalized = weights.normalize()
        
        total = (
            normalized.drift +
            normalized.latency +
            normalized.error_rate +
            normalized.cost_overrun
        )
        assert abs(total - 1.0) < 0.001

    def test_calculate_risk_low(self, temp_db):
        """Test risk calculation for low risk scenario."""
        from backend.ops.governance.risk import RiskManager, RiskMetrics, RiskLevel
        
        manager = RiskManager(db_path=temp_db)
        
        metrics = RiskMetrics(
            drift_score=0.05,
            latency_score=0.1,
            error_rate=0.02,
            cost_overrun=0.05,
        )
        
        score = manager.calculate_risk(metrics)
        
        assert score.level == RiskLevel.LOW
        assert score.score < 0.3

    def test_calculate_risk_high(self, temp_db):
        """Test risk calculation for high risk scenario."""
        from backend.ops.governance.risk import RiskManager, RiskMetrics, RiskLevel
        
        manager = RiskManager(db_path=temp_db)
        
        metrics = RiskMetrics(
            drift_score=0.8,
            latency_score=0.7,
            error_rate=0.6,
            cost_overrun=0.5,
        )
        
        score = manager.calculate_risk(metrics)
        
        assert score.level in [RiskLevel.HIGH, RiskLevel.CRITICAL]
        assert score.score > 0.5

    def test_risk_components(self, temp_db):
        """Test risk component breakdown."""
        from backend.ops.governance.risk import RiskManager, RiskMetrics
        
        manager = RiskManager(db_path=temp_db)
        
        metrics = RiskMetrics(
            drift_score=0.5,
            latency_score=0.3,
            error_rate=0.2,
            cost_overrun=0.1,
        )
        
        score = manager.calculate_risk(metrics)
        
        assert "drift" in score.components
        assert "latency" in score.components
        assert "error_rate" in score.components
        assert "cost_overrun" in score.components

    def test_get_risk_history(self, temp_db):
        """Test fetching risk history."""
        from backend.ops.governance.risk import RiskManager, RiskMetrics
        
        manager = RiskManager(db_path=temp_db)
        
        # Generate some history
        for i in range(5):
            metrics = RiskMetrics(
                drift_score=0.1 * i,
                latency_score=0.1 * i,
                error_rate=0.05 * i,
                cost_overrun=0.02 * i,
            )
            manager.calculate_risk(metrics)
        
        history = manager.get_risk_history(hours=1)
        
        assert len(history) >= 5

    def test_mitigation_registration(self, temp_db):
        """Test mitigation action registration."""
        from backend.ops.governance.risk import RiskManager
        
        manager = RiskManager(db_path=temp_db)
        
        callback_called = []
        
        manager.register_mitigation(
            action_id="test_mitigation",
            name="Test Mitigation",
            description="A test mitigation",
            trigger_condition="risk_level == 'critical'",
            callback=lambda s: callback_called.append(s),
            cooldown_minutes=1,
        )
        
        assert "test_mitigation" in manager._mitigation_actions

    def test_get_dashboard_data(self, temp_db):
        """Test dashboard data generation."""
        from backend.ops.governance.risk import RiskManager
        
        manager = RiskManager(db_path=temp_db)
        
        dashboard = manager.get_dashboard_data()
        
        assert "current_risk" in dashboard
        assert "level_distribution" in dashboard
        assert "weights" in dashboard
        assert "mitigations" in dashboard


class TestReportGenerator:
    """Tests for report generator module."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for reports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_report_generator_initialization(self, temp_dir):
        """Test ReportGenerator initialization."""
        from backend.ops.governance.reporting import ReportGenerator
        
        generator = ReportGenerator(output_dir=temp_dir)
        
        assert generator is not None

    def test_generate_weekly_sla_report(self, temp_dir):
        """Test weekly SLA report generation."""
        from backend.ops.governance.reporting import ReportGenerator
        
        generator = ReportGenerator(output_dir=temp_dir)
        
        report = generator.generate_weekly_sla_report()
        
        assert report.metadata.report_type == "weekly_sla"
        assert report.metadata.title.startswith("Weekly SLA Report")

    def test_generate_monthly_risk_report(self, temp_dir):
        """Test monthly risk report generation."""
        from backend.ops.governance.reporting import ReportGenerator
        
        generator = ReportGenerator(output_dir=temp_dir)
        
        report = generator.generate_monthly_risk_report()
        
        assert report.metadata.report_type == "monthly_risk"

    def test_generate_incident_report(self, temp_dir):
        """Test incident report generation."""
        from backend.ops.governance.reporting import ReportGenerator
        
        generator = ReportGenerator(output_dir=temp_dir)
        
        report = generator.generate_incident_report(
            incident_id="INC-001",
            title="Test Incident",
            severity="high",
            occurred_at=datetime.now(timezone.utc).isoformat(),
            description="A test incident",
            affected_services=["api", "inference"],
        )
        
        assert report.incident_id == "INC-001"
        assert report.severity == "high"
        assert report.status == "open"

    def test_export_sla_report_csv(self, temp_dir):
        """Test SLA report CSV export."""
        from backend.ops.governance.reporting import ReportGenerator
        
        generator = ReportGenerator(output_dir=temp_dir)
        report = generator.generate_weekly_sla_report()
        
        csv_content = generator._export_sla_report_csv(report)
        
        assert "Weekly SLA Report" in csv_content
        assert "Overall Uptime" in csv_content

    def test_save_report(self, temp_dir):
        """Test saving report to files."""
        from backend.ops.governance.reporting import ReportGenerator
        
        generator = ReportGenerator(output_dir=temp_dir)
        report = generator.generate_weekly_sla_report()
        
        saved = generator.save_report(report, formats=["json", "csv"])
        
        assert "json" in saved
        assert "csv" in saved
        assert saved["json"].exists()
        assert saved["csv"].exists()


class TestGovernanceIntegration:
    """Integration tests for governance components."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_end_to_end_sla_monitoring(self, temp_dir):
        """Test end-to-end SLA monitoring flow."""
        from backend.ops.sla.evaluator import SLAEvaluator
        from backend.ops.sla.reporter import SLAReporter
        
        # Setup
        db_path = temp_dir / "sla.db"
        evaluator = SLAEvaluator(db_path=db_path)
        reporter = SLAReporter(evaluator=evaluator, output_dir=temp_dir)
        
        # Simulate some evaluations
        for i in range(10):
            metrics = {
                "uptime": 0.999 + (i * 0.0001),
                "latency_p95_ms": 200 + (i * 10),
                "error_rate": 0.001 + (i * 0.001),
            }
            evaluator.evaluate("default", metrics)
        
        # Generate and save report
        report = reporter.generate_weekly_report()
        saved = reporter.save_report(report)
        
        # Verify
        assert report.total_violations >= 0
        assert saved.get("json").exists()

    def test_end_to_end_risk_management(self, temp_dir):
        """Test end-to-end risk management flow."""
        from backend.ops.governance.risk import RiskManager, RiskMetrics
        from backend.ops.governance.reporting import ReportGenerator
        
        # Setup
        db_path = temp_dir / "risk.db"
        manager = RiskManager(db_path=db_path)
        generator = ReportGenerator(output_dir=temp_dir)
        
        # Simulate risk events
        for i in range(5):
            metrics = RiskMetrics(
                drift_score=0.1 + (i * 0.1),
                latency_score=0.2 + (i * 0.05),
                error_rate=0.01 + (i * 0.01),
                cost_overrun=0.05 + (i * 0.02),
            )
            manager.calculate_risk(metrics)
        
        # Generate report
        report = generator.generate_monthly_risk_report(risk_manager=manager)
        
        # Verify
        assert report.average_risk_score >= 0
        assert len(report.risk_level_distribution) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

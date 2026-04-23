# backend/ops/integration.py
"""
Ops Integration Layer.

Bridges ops infrastructure ↔ production pipeline code.
Provides a single OpsHub that MainController, FastAPI app,
and crawlers use to access all ops services.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.integration")


class OpsHub:
    """
    Central access point for all ops services.

    Lazily initializes each subsystem on first access.
    Wire into MainController / FastAPI app via:

        ops = OpsHub()

        # In MainController.__init__:
        self.ops = ops

        # In FastAPI startup:
        app.state.ops = ops
        await ops.startup()
    """

    def __init__(self):
        # Lazy-init caches
        self._scheduler = None
        self._checkpoint = None
        self._rollback = None
        self._retry = None
        self._supervisor = None
        self._browser_monitor = None
        self._concurrency = None
        self._bottleneck = None
        self._leak_detector = None
        self._schema_validator = None
        self._completeness = None
        self._outlier = None
        self._drift = None
        self._source_reliability = None
        self._dataset_version = None
        self._config_version = None
        self._snapshot = None
        self._health = None
        self._sla = None
        self._alerts = None
        self._anomaly = None
        self._cost_tracker = None
        self._explanation_monitor = None
        self._secrets = None
        self._access_log = None
        self._backup = None
        self._retention = None
        self._audit = None
        self._update_policy = None

        # Reproducibility
        self._version_mgr = None
        self._seed_ctrl = None
        self._snapshot_mgr = None

        # Observability
        self._metrics = None

        # Recovery
        self._recovery = None
        self._failure_catalog = None

        self._started = False

    # ── Lifecycle ─────────────────────────────────────

    async def startup(self) -> None:
        """Initialize ops services on application startup."""
        if self._started:
            return

        logger.info("OpsHub starting up...")

        # ── Metrics collector (before health so health can embed it) ──
        _ = self.metrics  # force init
        _ = self.cost_tracker

        # Register built-in health checks
        health = self.health
        health.set_metrics(self.metrics)
        health.register_check("disk_space", health.check_disk_space)
        health.register_check("memory", health.check_memory)
        health.register_check("data_dir", health.check_data_dir)
        health.register_check("scoring_engine", health.check_scoring_engine)
        health.register_check("llm_service", self._check_llm_service)

        # Configure webhook alerts if SLACK_WEBHOOK_URL set
        slack_url = os.environ.get("SLACK_WEBHOOK_URL")
        if slack_url:
            from backend.ops.monitoring.alerts import WebhookAlertChannel
            self.alerts.add_channel(WebhookAlertChannel(slack_url))

        # Configure email alerts if ALERT_SMTP_HOST set
        if os.environ.get("ALERT_SMTP_HOST"):
            from backend.ops.monitoring.alerts import EmailAlertChannel
            self.alerts.add_channel(EmailAlertChannel())

        # Set supervisor hooks for alert integration
        self.supervisor.set_hooks(
            on_crash=self._on_process_crash,
            on_max_restart=self._on_max_restart,
        )

        # ── Recovery manager (force init to validate wiring) ──
        _ = self.recovery

        self._started = True
        logger.info(
            "OpsHub ready (metrics + %d health checks + recovery)",
            len(health._checks),
        )

    async def shutdown(self) -> None:
        """Clean shutdown of ops services."""
        logger.info("OpsHub shutting down...")
        await self.supervisor.shutdown()
        if self._browser_monitor and hasattr(self._browser_monitor, 'stop'):
            await self._browser_monitor.stop()
        self._started = False

    # ── Alert hooks ───────────────────────────────────

    async def _on_process_crash(self, name: str, error: Exception) -> None:
        from backend.ops.monitoring.alerts import AlertSeverity
        await self.alerts.fire(
            title=f"Process crashed: {name}",
            message=str(error)[:500],
            severity=AlertSeverity.CRITICAL,
            source="supervisor",
            context={"process": name},
        )

    async def _on_max_restart(self, name: str) -> None:
        from backend.ops.monitoring.alerts import AlertSeverity
        await self.alerts.fire(
            title=f"Max restarts exceeded: {name}",
            message=f"Process '{name}' has exceeded max restart attempts and is now in failed state.",
            severity=AlertSeverity.FATAL,
            source="supervisor",
            context={"process": name},
            force=True,
        )

    async def _check_llm_service(self) -> dict:
        """Health check for LLM (Ollama) service using pre-warmed status."""
        try:
            from backend.ops.warmup import get_warmup_manager
            warmup = get_warmup_manager()
            status = await warmup.get_llm_health()
            
            if status.get("status") == "ready":
                return {
                    "status": "healthy",
                    "message": "LLM service ready (pre-warmed)",
                    "details": {
                        "ollama_up": status.get("ollama_up", False),
                        "model_ready": status.get("model_ready", False),
                        "model_name": status.get("model_name", ""),
                    },
                }
            elif status.get("ollama_up"):
                return {
                    "status": "degraded",
                    "message": "LLM service up but model not ready",
                    "details": status,
                }
            else:
                return {
                    "status": "degraded",
                    "message": status.get("error", "LLM service not available"),
                    "details": status,
                }
        except Exception as e:
            return {
                "status": "degraded",
                "message": f"LLM health check error: {str(e)[:200]}",
            }

    # ── Lazy accessors ────────────────────────────────

    @property
    def scheduler(self):
        if not self._scheduler:
            from backend.ops.orchestration.scheduler import PipelineScheduler
            self._scheduler = PipelineScheduler()
        return self._scheduler

    @property
    def checkpoint(self):
        if not self._checkpoint:
            from backend.ops.orchestration.checkpoint import CheckpointManager
            self._checkpoint = CheckpointManager()
        return self._checkpoint

    @property
    def rollback(self):
        if not self._rollback:
            from backend.ops.orchestration.rollback import RollbackManager
            self._rollback = RollbackManager()
        return self._rollback

    @property
    def retry(self):
        if not self._retry:
            from backend.ops.orchestration.retry import RetryExecutor, RetryPolicy
            self._retry = RetryExecutor(RetryPolicy())
        return self._retry

    @property
    def supervisor(self):
        if not self._supervisor:
            from backend.ops.orchestration.supervisor import PipelineSupervisor
            self._supervisor = PipelineSupervisor()
        return self._supervisor

    @property
    def browser_monitor(self):
        if not self._browser_monitor:
            from backend.ops.resource.browser_monitor import BrowserResourceMonitor
            self._browser_monitor = BrowserResourceMonitor()
        return self._browser_monitor

    @property
    def concurrency(self):
        if not self._concurrency:
            from backend.ops.resource.concurrency import ConcurrencyController
            self._concurrency = ConcurrencyController()
        return self._concurrency

    @property
    def bottleneck(self):
        if not self._bottleneck:
            from backend.ops.resource.bottleneck import BottleneckTracer
            self._bottleneck = BottleneckTracer()
        return self._bottleneck

    @property
    def leak_detector(self):
        if not self._leak_detector:
            from backend.ops.resource.leak_detector import LeakDetector
            self._leak_detector = LeakDetector()
        return self._leak_detector

    @property
    def schema_validator(self):
        if not self._schema_validator:
            from backend.ops.quality.schema_validator import PipelineSchemaValidator
            self._schema_validator = PipelineSchemaValidator()
        return self._schema_validator

    @property
    def completeness(self):
        if not self._completeness:
            from backend.ops.quality.completeness import CompletenessChecker
            self._completeness = CompletenessChecker()
        return self._completeness

    @property
    def outlier(self):
        if not self._outlier:
            from backend.ops.quality.outlier import OutlierDetector
            self._outlier = OutlierDetector()
        return self._outlier

    @property
    def drift(self):
        if not self._drift:
            from backend.ops.quality.drift import DriftMonitor
            self._drift = DriftMonitor()
        return self._drift

    @property
    def source_reliability(self):
        if not self._source_reliability:
            from backend.ops.quality.source_reliability import SourceReliabilityScorer
            self._source_reliability = SourceReliabilityScorer()
        return self._source_reliability

    @property
    def dataset_version(self):
        if not self._dataset_version:
            from backend.ops.versioning.dataset import DatasetVersionManager
            self._dataset_version = DatasetVersionManager()
        return self._dataset_version

    @property
    def config_version(self):
        if not self._config_version:
            from backend.ops.versioning.config_version import ConfigVersionManager
            self._config_version = ConfigVersionManager()
        return self._config_version

    @property
    def snapshot(self):
        if not self._snapshot:
            from backend.ops.versioning.snapshot import PipelineSnapshotManager
            self._snapshot = PipelineSnapshotManager()
        return self._snapshot

    @property
    def health(self):
        if not self._health:
            from backend.ops.monitoring.health import HealthCheckService
            self._health = HealthCheckService()
        return self._health

    @property
    def sla(self):
        if not self._sla:
            from backend.ops.monitoring.sla import SLAMonitor
            self._sla = SLAMonitor()
        return self._sla

    @property
    def alerts(self):
        if not self._alerts:
            from backend.ops.monitoring.alerts import AlertManager
            self._alerts = AlertManager()
        return self._alerts

    @property
    def anomaly(self):
        if not self._anomaly:
            from backend.ops.monitoring.anomaly import AnomalyDetector
            self._anomaly = AnomalyDetector()
        return self._anomaly

    @property
    def cost_tracker(self):
        if not self._cost_tracker:
            from backend.ops.monitoring.costs import CostTracker
            self._cost_tracker = CostTracker(
                metrics=self.metrics,
                alerts=self.alerts,
                anomaly=self.anomaly,
            )
        return self._cost_tracker

    @property
    def explanation_monitor(self):
        if not self._explanation_monitor:
            from backend.ops.monitoring.explanation import ExplanationMonitor
            self._explanation_monitor = ExplanationMonitor()
        return self._explanation_monitor

    @property
    def secrets(self):
        if not self._secrets:
            from backend.ops.security.secrets import SecretManager
            self._secrets = SecretManager()
        return self._secrets

    @property
    def access_log(self):
        if not self._access_log:
            from backend.ops.security.access_log import AccessLogger
            self._access_log = AccessLogger()
        return self._access_log

    @property
    def backup(self):
        if not self._backup:
            from backend.ops.security.backup import BackupManager
            self._backup = BackupManager()
        return self._backup

    @property
    def retention(self):
        if not self._retention:
            from backend.ops.maintenance.retention import RetentionManager
            self._retention = RetentionManager()
        return self._retention

    @property
    def audit(self):
        if not self._audit:
            from backend.ops.maintenance.audit_trail import AuditTrail
            self._audit = AuditTrail()
        return self._audit

    @property
    def update_policy(self):
        if not self._update_policy:
            from backend.ops.maintenance.update_policy import UpdatePolicy
            self._update_policy = UpdatePolicy()
        return self._update_policy

    # ── Reproducibility ───────────────────────────────

    @property
    def version_mgr(self):
        if not self._version_mgr:
            from backend.ops.reproducibility.version_manager import VersionManager
            self._version_mgr = VersionManager()
        return self._version_mgr

    @property
    def seed_ctrl(self):
        if not self._seed_ctrl:
            from backend.ops.reproducibility.seed_control import SeedController
            self._seed_ctrl = SeedController()
        return self._seed_ctrl

    @property
    def snapshot_mgr(self):
        if not self._snapshot_mgr:
            from backend.ops.reproducibility.snapshot_manager import SnapshotManager
            self._snapshot_mgr = SnapshotManager()
        return self._snapshot_mgr

    @property
    def metrics(self):
        if not self._metrics:
            from backend.ops.monitoring.metrics import MetricsCollector
            self._metrics = MetricsCollector()
        return self._metrics

    # ── Recovery ──────────────────────────────────────

    @property
    def failure_catalog(self):
        if not self._failure_catalog:
            from backend.ops.recovery.failure_catalog import FailureCatalog
            self._failure_catalog = FailureCatalog()
        return self._failure_catalog

    @property
    def recovery(self):
        if not self._recovery:
            from backend.ops.recovery.recovery_manager import RecoveryManager
            from backend.ops.recovery.stage_retry import StageRetryExecutor
            from backend.ops.recovery.stage_rollback import StageRollbackManager
            from backend.ops.recovery.stage_checkpoint import RecoveryCheckpointManager
            self._recovery = RecoveryManager(
                catalog=self.failure_catalog,
                retry_executor=StageRetryExecutor(catalog=self.failure_catalog),
                rollback_manager=StageRollbackManager(),
                checkpoint_manager=RecoveryCheckpointManager(),
            )
        return self._recovery

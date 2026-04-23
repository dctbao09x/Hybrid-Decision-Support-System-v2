# backend/evaluation/stability_service.py
"""
Stability Service
=================
Orchestrates all stability checks for the ML Evaluation pipeline:

  • Dataset fingerprinting
  • Run registry (persistent run history)
  • Baseline management
  • Regression guard
  • Drift monitoring
  • Reproducibility snapshot

Integrates with MLEvaluationService to validate runs before publishing.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.evaluation.fingerprint import DatasetFingerprint, FingerprintGenerator
from backend.evaluation.regression_guard import (
    RegressionGuard,
    RegressionCheckResult,
    RegressionStatus,
    RegressionError,
)
from backend.evaluation.drift_monitor import (
    DriftMonitor,
    DriftReport,
    DriftSeverity,
    DriftError,
)

logger = logging.getLogger("ml_evaluation.stability")


# ═══════════════════════════════════════════════════════════════════════════
#  Environment Snapshot
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class EnvironmentSnapshot:
    """Snapshot of the execution environment for reproducibility."""
    python_version: str
    platform: str
    platform_version: str
    processor: str
    libraries: Dict[str, str]
    git_commit: str
    git_branch: str
    working_directory: str
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "python_version": self.python_version,
            "platform": self.platform,
            "platform_version": self.platform_version,
            "processor": self.processor,
            "libraries": self.libraries,
            "git_commit": self.git_commit,
            "git_branch": self.git_branch,
            "working_directory": self.working_directory,
            "timestamp": self.timestamp,
        }

    @classmethod
    def capture(cls) -> "EnvironmentSnapshot":
        """Capture current environment snapshot."""
        # Get library versions
        libraries = {}
        try:
            import sklearn
            libraries["scikit-learn"] = sklearn.__version__
        except Exception:
            pass
        try:
            import pandas
            libraries["pandas"] = pandas.__version__
        except Exception:
            pass
        try:
            import numpy
            libraries["numpy"] = numpy.__version__
        except Exception:
            pass
        try:
            import yaml
            libraries["pyyaml"] = yaml.__version__
        except Exception:
            pass

        # Get git info
        git_commit = ""
        git_branch = ""
        try:
            git_commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                stderr=subprocess.DEVNULL,
                encoding="utf-8",
            ).strip()
            git_branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL,
                encoding="utf-8",
            ).strip()
        except Exception:
            pass

        return cls(
            python_version=sys.version,
            platform=platform.system(),
            platform_version=platform.version(),
            processor=platform.processor(),
            libraries=libraries,
            git_commit=git_commit,
            git_branch=git_branch,
            working_directory=os.getcwd(),
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Run Record
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class RunRecord:
    """Complete record of a single ML evaluation run."""
    run_id: str
    timestamp: str
    dataset_hash: str
    model_type: str
    model_config: Dict[str, Any]
    kfold: int
    random_state: int
    metrics: Dict[str, Any]
    quality_passed: bool
    regression_status: str
    drift_status: str
    environment: Dict[str, Any]
    system_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "dataset_hash": self.dataset_hash,
            "model_type": self.model_type,
            "model_config": self.model_config,
            "kfold": self.kfold,
            "random_state": self.random_state,
            "metrics": self.metrics,
            "quality_passed": self.quality_passed,
            "regression_status": self.regression_status,
            "drift_status": self.drift_status,
            "environment": self.environment,
            "system_version": self.system_version,
        }


# ═══════════════════════════════════════════════════════════════════════════
#  Stability Report
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class StabilityReport:
    """Complete stability validation report."""
    run_id: str
    dataset_hash: str
    baseline_hash: str
    regression_status: str
    drift_status: str
    delta_metrics: Dict[str, float]
    recommendations: List[str] = field(default_factory=list)
    should_publish: bool = True
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "dataset_hash": self.dataset_hash,
            "baseline_hash": self.baseline_hash,
            "regression_status": self.regression_status,
            "drift_status": self.drift_status,
            "delta_metrics": self.delta_metrics,
            "recommendations": self.recommendations,
            "should_publish": self.should_publish,
            "timestamp": self.timestamp,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ═══════════════════════════════════════════════════════════════════════════
#  Stability Service
# ═══════════════════════════════════════════════════════════════════════════

class StabilityService:
    """
    Orchestrates all stability checks for ML evaluation.

    Usage::

        stability = StabilityService()
        stability.load_config(config)

        # Before pipeline
        fingerprint = stability.fingerprint_dataset("data/training.csv")

        # After pipeline
        report = stability.validate(run_result, fingerprint)
        if not report.should_publish:
            # Handle blocking
    """

    SYSTEM_VERSION = "1.0.0"

    def __init__(
        self,
        runs_dir: str = "runs",
        baseline_dir: str = "baseline",
        output_dir: str = "outputs",
    ):
        self._project_root = Path(__file__).resolve().parents[2]
        self._runs_dir = self._project_root / runs_dir
        self._baseline_dir = self._project_root / baseline_dir
        self._output_dir = self._project_root / output_dir

        # Components
        self._fingerprint_gen = FingerprintGenerator()
        self._regression_guard: Optional[RegressionGuard] = None
        self._drift_monitor: Optional[DriftMonitor] = None

        # Config
        self._config: Dict[str, Any] = {}
        self._threshold = 0.03
        self._block_on_regression = True
        self._block_on_critical_drift = True

    def load_config(self, config: Dict[str, Any]) -> None:
        """Load configuration from system.yaml stability section."""
        stability_cfg = config.get("stability", {})
        self._config = stability_cfg

        self._threshold = stability_cfg.get("regression_threshold", 0.03)
        self._block_on_regression = stability_cfg.get("block_on_regression", True)
        self._block_on_critical_drift = stability_cfg.get("block_on_critical_drift", True)

        # Initialize components with config
        self._regression_guard = RegressionGuard(
            threshold=self._threshold,
            block_on_fail=self._block_on_regression,
            baseline_path=str(self._baseline_dir / "baseline_metrics.json"),
        )

        self._drift_monitor = DriftMonitor(
            baseline_fingerprint_path=str(self._baseline_dir / "dataset_fingerprint.json"),
        )

        logger.info(
            "Stability config loaded: threshold=%.3f block_regression=%s block_drift=%s",
            self._threshold, self._block_on_regression, self._block_on_critical_drift,
        )

    # ──────────────────────────────────────────────────────────────
    #  Dataset Fingerprinting
    # ──────────────────────────────────────────────────────────────

    def fingerprint_dataset(self, data_path: str) -> DatasetFingerprint:
        """Compute fingerprint for the training dataset."""
        full_path = self._project_root / data_path
        return self._fingerprint_gen.compute(str(full_path))

    # ──────────────────────────────────────────────────────────────
    #  Baseline Management
    # ──────────────────────────────────────────────────────────────

    def load_baselines(self) -> bool:
        """Load both metric and fingerprint baselines."""
        loaded = False

        if self._regression_guard:
            if self._regression_guard.load_baseline():
                loaded = True

        if self._drift_monitor:
            if self._drift_monitor.load_baseline_fingerprint():
                loaded = True

        return loaded

    def update_baselines(
        self,
        metrics: Dict[str, Any],
        fingerprint: DatasetFingerprint,
        model_type: str,
        kfold: int,
        run_id: str,
    ) -> None:
        """Update both baselines with new values."""
        # Ensure baseline directory exists
        self._baseline_dir.mkdir(parents=True, exist_ok=True)

        # Update metric baseline
        if self._regression_guard:
            self._regression_guard.save_baseline(
                metrics=metrics,
                dataset_hash=fingerprint.hash,
                model_type=model_type,
                kfold=kfold,
                run_id=run_id,
            )

        # Update fingerprint baseline
        if self._drift_monitor:
            self._drift_monitor.save_baseline_fingerprint(fingerprint)

        logger.info("Baselines updated for run %s", run_id)

    def should_update_baseline(self, metrics: Dict[str, Any]) -> bool:
        """Check if baseline should be updated based on metrics."""
        if not self._regression_guard:
            return True
        return self._regression_guard.should_update_baseline(metrics)

    # ──────────────────────────────────────────────────────────────
    #  Validation Pipeline
    # ──────────────────────────────────────────────────────────────

    def validate(
        self,
        run_result: Dict[str, Any],
        fingerprint: DatasetFingerprint,
    ) -> StabilityReport:
        """
        Validate a run result for stability.

        Args:
            run_result:  Output from MLEvaluationService.run_pipeline().
            fingerprint: Dataset fingerprint for this run.

        Returns:
            StabilityReport with regression/drift status.
        """
        run_id = run_result.get("run_id", "unknown")
        metrics = run_result.get("metrics", {})

        logger.info("Validating stability for run %s", run_id)

        # 1. Regression check
        regression_result = self._check_regression(metrics)

        # 2. Drift check
        drift_report = self._check_drift(fingerprint, run_id)

        # 3. Determine if should publish
        should_publish = True
        recommendations = []

        if regression_result.should_block:
            should_publish = False
            recommendations.append(f"BLOCKED: {regression_result.message}")

        if drift_report.overall_severity == DriftSeverity.CRITICAL and self._block_on_critical_drift:
            should_publish = False
            recommendations.append("BLOCKED: Critical data drift detected")

        recommendations.extend(drift_report.recommendations)

        # 4. Build delta metrics
        delta_metrics = {
            "accuracy_delta": regression_result.accuracy_delta,
            "f1_delta": regression_result.f1_delta,
            "precision_delta": regression_result.precision_delta,
            "recall_delta": regression_result.recall_delta,
        }

        # 5. Get baseline hash
        baseline_hash = ""
        if self._regression_guard and self._regression_guard.baseline:
            baseline_hash = self._regression_guard.baseline.dataset_hash

        # 6. Create stability report
        report = StabilityReport(
            run_id=run_id,
            dataset_hash=fingerprint.hash,
            baseline_hash=baseline_hash,
            regression_status=regression_result.status.value,
            drift_status=drift_report.overall_severity.value,
            delta_metrics=delta_metrics,
            recommendations=recommendations,
            should_publish=should_publish,
        )

        # 7. Save stability report
        self._save_stability_report(report)

        # 8. Save drift report
        self._save_drift_report(drift_report)

        logger.info(
            "Stability validation: regression=%s drift=%s publish=%s",
            report.regression_status,
            report.drift_status,
            report.should_publish,
        )

        return report

    def _check_regression(self, metrics: Dict[str, Any]) -> RegressionCheckResult:
        """Run regression check against baseline."""
        if not self._regression_guard:
            self._regression_guard = RegressionGuard(threshold=self._threshold)
            self._regression_guard.load_baseline()

        return self._regression_guard.check(metrics)

    def _check_drift(
        self,
        fingerprint: DatasetFingerprint,
        run_id: str,
    ) -> DriftReport:
        """Run drift analysis against baseline."""
        if not self._drift_monitor:
            self._drift_monitor = DriftMonitor()
            self._drift_monitor.load_baseline_fingerprint()

        return self._drift_monitor.analyze(fingerprint, run_id)

    # ──────────────────────────────────────────────────────────────
    #  Run Registry
    # ──────────────────────────────────────────────────────────────

    def save_run(
        self,
        run_result: Dict[str, Any],
        fingerprint: DatasetFingerprint,
        config: Dict[str, Any],
        regression_status: str,
        drift_status: str,
    ) -> str:
        """
        Save run to the registry.

        Creates a new file: runs/run_YYYYMMDD_HHMMSS.json
        Never overwrites existing runs.
        """
        self._runs_dir.mkdir(parents=True, exist_ok=True)

        # Generate timestamp-based filename
        ts = datetime.now()
        filename = f"run_{ts.strftime('%Y%m%d_%H%M%S')}.json"
        run_path = self._runs_dir / filename

        # Capture environment
        env_snapshot = EnvironmentSnapshot.capture()

        # Build run record
        record = RunRecord(
            run_id=run_result.get("run_id", "unknown"),
            timestamp=run_result.get("timestamp", ts.isoformat()),
            dataset_hash=fingerprint.hash,
            model_type=run_result.get("model", config.get("model_type", "")),
            model_config=config.get("model_params", {}).get(
                config.get("model_type", ""), {}
            ),
            kfold=run_result.get("kfold", config.get("kfold", 5)),
            random_state=config.get("random_state", 42),
            metrics=run_result.get("metrics", {}),
            quality_passed=run_result.get("quality_passed", False),
            regression_status=regression_status,
            drift_status=drift_status,
            environment=env_snapshot.to_dict(),
            system_version=self.SYSTEM_VERSION,
        )

        # Save
        with open(run_path, "w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, indent=2)

        logger.info("Saved run to registry: %s", filename)

        # Also save environment snapshot separately
        self._save_env_snapshot(env_snapshot)

        return str(run_path)

    def _save_env_snapshot(self, env: EnvironmentSnapshot) -> None:
        """Save environment snapshot to runs/env_snapshot.json."""
        env_path = self._runs_dir / "env_snapshot.json"
        with open(env_path, "w", encoding="utf-8") as f:
            json.dump(env.to_dict(), f, indent=2)

    def list_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent runs from the registry."""
        if not self._runs_dir.exists():
            return []

        run_files = sorted(
            self._runs_dir.glob("run_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]

        runs = []
        for run_file in run_files:
            try:
                with open(run_file, "r", encoding="utf-8") as f:
                    runs.append(json.load(f))
            except Exception as e:
                logger.warning("Failed to load run %s: %s", run_file.name, e)

        return runs

    # ──────────────────────────────────────────────────────────────
    #  Report Persistence
    # ──────────────────────────────────────────────────────────────

    def _save_stability_report(self, report: StabilityReport) -> None:
        """Save stability report to outputs/stability_report.json."""
        self._output_dir.mkdir(parents=True, exist_ok=True)
        report_path = self._output_dir / "stability_report.json"

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report.to_json())

        logger.info("Saved stability report → %s", report_path)

    def _save_drift_report(self, report: DriftReport) -> None:
        """Save drift report to outputs/drift_report.json."""
        self._output_dir.mkdir(parents=True, exist_ok=True)
        report_path = self._output_dir / "drift_report.json"

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report.to_json())

        logger.info("Saved drift report → %s", report_path)

    # ──────────────────────────────────────────────────────────────
    #  Event Publishing
    # ──────────────────────────────────────────────────────────────

    def publish_stability_event(
        self,
        report: StabilityReport,
        event_bus: Any = None,
    ) -> None:
        """Publish stability events to monitoring system."""
        # Log as structured event
        event = {
            "type": "stability_check",
            "run_id": report.run_id,
            "regression_status": report.regression_status,
            "drift_status": report.drift_status,
            "should_publish": report.should_publish,
            "timestamp": report.timestamp,
        }

        if report.regression_status == "FAIL":
            logger.warning("[STABILITY_EVENT] Regression detected: %s", json.dumps(event))
        elif report.drift_status in ("HIGH", "CRITICAL"):
            logger.warning("[STABILITY_EVENT] High drift detected: %s", json.dumps(event))
        else:
            logger.info("[STABILITY_EVENT] %s", json.dumps(event))

        # If event bus provided, publish
        if event_bus:
            try:
                from backend.evaluation.event_bus import EvaluationEvent
                # Could extend EvaluationEvent or create StabilityEvent
                pass
            except Exception as e:
                logger.debug("Event bus publish: %s", e)

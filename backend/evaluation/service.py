# backend/evaluation/service.py
"""
ML Evaluation Service — Core Orchestrator
==========================================
Entry point for the ML evaluation pipeline.  Designed to be called by
MainController, *not* run as a standalone script.

Pipeline flow (Phase 2 — with Stability Layer):
  load_config → run_pipeline:
      fingerprint_dataset → load_baseline → load_dataset → preprocess
      → build_model → cross-validate → aggregate_metrics
      → validate_regression → detect_drift → save_run
      → update_baseline (if improved) → persist_output → publish

All parameters are read from config/system.yaml (no hardcoding).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from backend.evaluation.dataset_loader import DatasetLoader
from backend.evaluation.models import ModelFactory
from backend.evaluation.train_eval import CrossValidator, CVResult
from backend.evaluation.metrics import MetricsEngine, AggregatedMetrics
from backend.evaluation.event_bus import (
    EventBus,
    EvaluationEvent,
    create_default_event_bus,
)
from backend.evaluation.fingerprint import DatasetFingerprint, FingerprintGenerator
from backend.evaluation.stability_service import StabilityService, StabilityReport

logger = logging.getLogger("ml_evaluation.service")


# ═══════════════════════════════════════════════════════════════════════════
#  Config schema
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "system.yaml"


# ═══════════════════════════════════════════════════════════════════════════
#  Service
# ═══════════════════════════════════════════════════════════════════════════

class MLEvaluationService:
    """
    Orchestrates ML model evaluation (Phase 1 + Phase 2 Stability Layer).

    Usage (from MainController)::

        service = MLEvaluationService()
        service.load_config()
        result = service.run_pipeline()
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        event_bus: Optional[EventBus] = None,
        stability_service: Optional[StabilityService] = None,
    ) -> None:
        self._config_path = config_path or DEFAULT_CONFIG_PATH
        self._config: Dict[str, Any] = {}
        self._event_bus = event_bus or create_default_event_bus()
        self._stability = stability_service or StabilityService()
        self._run_id: Optional[str] = None
        self._fingerprint: Optional[DatasetFingerprint] = None
        self._stability_report: Optional[StabilityReport] = None

    # ──────────────────────────────────────────────────────────────
    #  Configuration
    # ──────────────────────────────────────────────────────────────

    def load_config(self, path: Optional[Path] = None) -> Dict[str, Any]:
        """Load and validate config/system.yaml."""
        path = path or self._config_path
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        ml_cfg = raw.get("ml_evaluation")
        if not ml_cfg:
            raise ValueError("Missing 'ml_evaluation' section in config")

        # Validate required keys
        required_keys = [
            "data_path", "model_type", "kfold",
            "random_state", "output_path", "enable_publish",
        ]
        missing = [k for k in required_keys if k not in ml_cfg]
        if missing:
            raise ValueError(f"Missing config keys: {missing}")

        self._config = ml_cfg
        logger.info("Loaded config from %s: %s", path, list(ml_cfg.keys()))
        return self._config

    @property
    def config(self) -> Dict[str, Any]:
        return self._config

    # ──────────────────────────────────────────────────────────────
    #  Main Pipeline
    # ──────────────────────────────────────────────────────────────

    def run_pipeline(self, run_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute the full ML evaluation pipeline with stability checks.

        Steps:
          1. Generate run_id (trace ID)
          2. Fingerprint dataset
          3. Load baselines (metrics + fingerprint)
          4. Load & preprocess dataset
          5. Build model from config
          6. Run cross-validation
          7. Compute aggregated metrics
          8. Validate regression (compare to baseline)
          9. Detect drift (compare fingerprints)
          10. Save run to registry
          11. Update baseline (if improved)
          12. Persist cv_results.json
          13. Publish to downstream layers (if stability checks pass)
          14. Persist stability_report.json
          15. Return structured result

        Returns:
            Dict with run_id, metrics, stability info, output_path, publish_status.
        """
        self._run_id = run_id or f"eval_{uuid.uuid4().hex[:12]}"
        timestamp = datetime.now(timezone.utc).isoformat()

        self.audit_log("pipeline_start", {"run_id": self._run_id})
        logger.info("=" * 60)
        logger.info("ML Evaluation Pipeline — run_id=%s", self._run_id)
        logger.info("=" * 60)

        # Ensure config is loaded
        if not self._config:
            self.load_config()

        # ── 1) Fingerprint dataset ──
        self.audit_log("fingerprint_dataset", {"path": self._config["data_path"]})
        data_path = self._resolve_path(self._config["data_path"])
        fingerprint_gen = FingerprintGenerator()
        self._fingerprint = fingerprint_gen.compute(str(data_path))
        logger.info(
            "Dataset fingerprint: hash=%s rows=%d",
            self._fingerprint.hash[:16], self._fingerprint.rows,
        )

        # ── 2) Load stability baselines ──
        stability_cfg = self._config.get("stability", {})
        if stability_cfg.get("enabled", True):
            self._stability.load_config(self._config)
            self._stability.load_baselines()
            self.audit_log("load_baseline", {"status": "loaded"})
        else:
            logger.info("Stability checks disabled")

        # ── 3) Load dataset ──
        self.audit_log("load_data", {"path": self._config["data_path"]})
        loader = DatasetLoader(str(data_path))
        loader.load()
        X, y, label_encoder = loader.export_arrays()

        # ── 4) Build model ──
        model_type = self._config["model_type"]
        model_params = self._config.get("model_params", {}).get(model_type, {})
        random_state = self._config["random_state"]

        self.audit_log("build_model", {"model_type": model_type, "params": model_params})
        model = ModelFactory.get_model(model_type, model_params, random_state)

        # ── 5) Cross-validate ──
        kfold = self._config["kfold"]
        self.audit_log("train_start", {"kfold": kfold})

        cv = CrossValidator(kfold=kfold, random_state=random_state)
        cv_result = cv.run(model, X, y)

        self.audit_log("train_complete", {"total_time_s": cv_result.total_time_s})

        # ── 6) Compute metrics ──
        metrics_engine = MetricsEngine()
        fold_metrics, agg_metrics = metrics_engine.compute(cv_result)

        self.audit_log("eval_complete", agg_metrics.to_dict())

        # ── 7) Quality gate check ──
        quality_gate = self._config.get("quality_gate", {})
        quality_passed = self._check_quality_gate(agg_metrics, quality_gate)

        # ══════════════════════════════════════════════════════════════
        #  STABILITY LAYER (Phase 2)
        # ══════════════════════════════════════════════════════════════

        regression_status = "PASS"
        drift_status = "LOW"
        should_publish = True

        if stability_cfg.get("enabled", True):
            # ── 8) Validate regression ──
            self.audit_log("validate_regression", {"threshold": stability_cfg.get("regression_threshold", 0.03)})

            # Build preliminary result for stability validation
            prelim_result = {
                "run_id": self._run_id,
                "timestamp": timestamp,
                "model": model_type,
                "kfold": kfold,
                "metrics": agg_metrics.to_dict(),
                "quality_passed": quality_passed,
            }

            # Run stability validation
            self._stability_report = self._stability.validate(
                run_result=prelim_result,
                fingerprint=self._fingerprint,
            )

            regression_status = self._stability_report.regression_status
            drift_status = self._stability_report.drift_status
            should_publish = self._stability_report.should_publish

            self.audit_log("stability_check", {
                "regression_status": regression_status,
                "drift_status": drift_status,
                "should_publish": should_publish,
            })

            # ── 9) Save run to registry ──
            self._stability.save_run(
                run_result=prelim_result,
                fingerprint=self._fingerprint,
                config=self._config,
                regression_status=regression_status,
                drift_status=drift_status,
            )
            self.audit_log("save_run", {"registry": "runs/"})

            # ── 10) Update baseline if improved ──
            if self._stability.should_update_baseline(agg_metrics.to_dict()):
                self._stability.update_baselines(
                    metrics=agg_metrics.to_dict(),
                    fingerprint=self._fingerprint,
                    model_type=model_type,
                    kfold=kfold,
                    run_id=self._run_id,
                )
                self.audit_log("update_baseline", {"status": "updated"})
            else:
                self.audit_log("update_baseline", {"status": "skipped"})

        # ══════════════════════════════════════════════════════════════

        # ── 11) Persist output ──
        output_path = self._resolve_path(self._config["output_path"])
        output_data = self._build_output(
            run_id=self._run_id,
            timestamp=timestamp,
            model_type=model_type,
            kfold=kfold,
            agg_metrics=agg_metrics,
            quality_passed=quality_passed,
            cv_time_s=cv_result.total_time_s,
            num_samples=loader.num_samples,
            num_classes=loader.num_classes,
            dataset_hash=self._fingerprint.hash if self._fingerprint else "",
            regression_status=regression_status,
            drift_status=drift_status,
        )
        self._persist_output(output_path, output_data)
        self.audit_log("persist_output", {"path": str(output_path)})

        # ── 12) Publish (if enabled AND stability checks pass) ──
        publish_status: Dict[str, bool] = {}
        if self._config.get("enable_publish", False):
            if should_publish:
                publish_status = self.publish_results(
                    EvaluationEvent(
                        run_id=self._run_id,
                        model_type=model_type,
                        kfold=kfold,
                        metrics=agg_metrics.to_dict(),
                        output_path=str(output_path),
                        timestamp=timestamp,
                        quality_passed=quality_passed,
                    )
                )
                self.audit_log("publish_complete", publish_status)
            else:
                logger.warning(
                    "Publishing BLOCKED: regression=%s drift=%s",
                    regression_status, drift_status,
                )
                self.audit_log("publish_blocked", {
                    "regression_status": regression_status,
                    "drift_status": drift_status,
                })
        else:
            logger.info("Publishing disabled — skipping.")

        # ── 13) Final result ──
        result = {
            "run_id": self._run_id,
            "timestamp": timestamp,
            "model": model_type,
            "kfold": kfold,
            "metrics": agg_metrics.to_dict(),
            "quality_passed": quality_passed,
            "output_path": str(output_path),
            "publish_status": publish_status,
            # Stability info
            "stability": {
                "dataset_hash": self._fingerprint.hash if self._fingerprint else "",
                "regression_status": regression_status,
                "drift_status": drift_status,
                "should_publish": should_publish,
            },
        }

        logger.info("Pipeline complete — run_id=%s", self._run_id)
        self.audit_log("pipeline_end", {"status": "success"})

        return result

    # ──────────────────────────────────────────────────────────────
    #  Publish
    # ──────────────────────────────────────────────────────────────

    def publish_results(self, event: EvaluationEvent) -> Dict[str, bool]:
        """Broadcast evaluation results to downstream layers."""
        logger.info("Publishing to %d subscribers...", self._event_bus.publisher_count)
        return self._event_bus.publish(event)

    # ──────────────────────────────────────────────────────────────
    #  Audit
    # ──────────────────────────────────────────────────────────────

    def audit_log(self, step: str, data: Any) -> None:
        """Write an audit entry to the logger (and any external audit sinks)."""
        entry = {
            "run_id": self._run_id,
            "step": step,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        logger.info("[AUDIT] %s", json.dumps(entry, default=str))

    # ──────────────────────────────────────────────────────────────
    #  Helpers
    # ──────────────────────────────────────────────────────────────

    def _resolve_path(self, relative: str) -> Path:
        """Resolve a path relative to project root."""
        project_root = Path(__file__).resolve().parents[2]
        return project_root / relative

    def _check_quality_gate(
        self, agg: AggregatedMetrics, gate: Dict[str, float]
    ) -> bool:
        """Check if metrics meet the quality gate thresholds."""
        min_acc = gate.get("min_accuracy", 0.0)
        min_f1 = gate.get("min_f1", 0.0)

        passed = agg.accuracy_mean >= min_acc and agg.f1_mean >= min_f1

        if not passed:
            logger.warning(
                "Quality gate FAILED — acc=%.4f (need %.2f), f1=%.4f (need %.2f)",
                agg.accuracy_mean, min_acc, agg.f1_mean, min_f1,
            )
        else:
            logger.info(
                "Quality gate PASSED — acc=%.4f ≥ %.2f, f1=%.4f ≥ %.2f",
                agg.accuracy_mean, min_acc, agg.f1_mean, min_f1,
            )
        return passed

    def _build_output(
        self,
        run_id: str,
        timestamp: str,
        model_type: str,
        kfold: int,
        agg_metrics: AggregatedMetrics,
        quality_passed: bool,
        cv_time_s: float,
        num_samples: int,
        num_classes: int,
        dataset_hash: str = "",
        regression_status: str = "PASS",
        drift_status: str = "LOW",
    ) -> Dict[str, Any]:
        """Build the canonical cv_results.json structure with stability info."""
        return {
            "run_id": run_id,
            "timestamp": timestamp,
            "model": model_type,
            "kfold": kfold,
            "metrics": agg_metrics.to_dict(),
            "quality_passed": quality_passed,
            "meta": {
                "cv_time_s": round(cv_time_s, 4),
                "num_samples": num_samples,
                "num_classes": num_classes,
            },
            "stability": {
                "dataset_hash": dataset_hash,
                "regression_status": regression_status,
                "drift_status": drift_status,
            },
        }

    def _persist_output(self, path: Path, data: Dict[str, Any]) -> None:
        """Write JSON output, creating directories as needed."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info("Persisted cv_results → %s", path)

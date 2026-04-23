# backend/evaluation/__init__.py
"""
ML Evaluation Module
====================

Phase 1: ML Evaluation Core
  - service.py           — MLEvaluationService (orchestration)
  - dataset_loader.py    — DatasetLoader (CSV ingestion)
  - models.py            — ModelFactory (RF, LR)
  - train_eval.py        — CrossValidator (K-Fold CV)
  - metrics.py           — MetricsEngine (accuracy, f1, precision, recall)
  - event_bus.py         — EvaluationEvent (downstream publishing)

Phase 2: Stability Layer
  - fingerprint.py       — Dataset fingerprinting (SHA256, stats)
  - regression_guard.py  — Regression protection (baseline comparison)
  - drift_monitor.py     — Drift detection (PSI, distribution shift)
  - stability_service.py — StabilityService (orchestration)

Phase 3: Governance-Grade Real-Time Evaluation
  - rolling_evaluator.py — RollingEvaluator (F1/P/R/calibration/ECE/Brier)
  - eval_metrics_log.py  — EvalMetricsLogger (evaluation_metrics.jsonl)
"""

from backend.evaluation.service import MLEvaluationService
from backend.evaluation.event_bus import EvaluationEvent
from backend.evaluation.fingerprint import DatasetFingerprint, FingerprintGenerator
from backend.evaluation.regression_guard import RegressionGuard, RegressionCheckResult
from backend.evaluation.drift_monitor import DriftMonitor, DriftReport
from backend.evaluation.stability_service import StabilityService, StabilityReport
from backend.evaluation.rolling_evaluator import (
    RollingEvaluator,
    EvalSample,
    EvalSnapshot,
    AlertEvent,
    AlertRules,
    compute_brier_score,
    compute_ece,
    get_rolling_evaluator,
)
from backend.evaluation.eval_metrics_log import (
    EvalMetricsLogger,
    get_eval_metrics_logger,
    log_eval_snapshot,
)

__all__ = [
    # Phase 1
    "MLEvaluationService",
    "EvaluationEvent",
    # Phase 2
    "DatasetFingerprint",
    "FingerprintGenerator",
    "RegressionGuard",
    "RegressionCheckResult",
    "DriftMonitor",
    "DriftReport",
    "StabilityService",
    "StabilityReport",
    # Phase 3
    "RollingEvaluator",
    "EvalSample",
    "EvalSnapshot",
    "AlertEvent",
    "AlertRules",
    "compute_brier_score",
    "compute_ece",
    "get_rolling_evaluator",
    "EvalMetricsLogger",
    "get_eval_metrics_logger",
    "log_eval_snapshot",
]

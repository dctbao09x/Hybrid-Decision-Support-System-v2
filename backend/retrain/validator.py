# backend/retrain/validator.py
"""
Retrain Validator
=================

Validates retrained models before deployment.

Validation ensures:
  - Phase 1: Quality gate passed (accuracy, F1)
  - Phase 2: No regression, acceptable drift
  - Comparison vs active model
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("ml_retrain.validator")


@dataclass
class ValidationResult:
    """Result of model validation."""
    valid: bool
    version: str
    
    # Quality checks
    quality_passed: bool
    accuracy: float
    f1: float
    
    # Regression check
    regression_status: str
    accuracy_delta: float
    f1_delta: float
    
    # Drift check
    drift_status: str
    
    # Comparison with active
    beats_active: bool
    active_version: str
    active_accuracy: float
    active_f1: float
    
    # Blocking reasons
    blocking_reasons: list
    
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "version": self.version,
            "quality": {
                "passed": self.quality_passed,
                "accuracy": self.accuracy,
                "f1": self.f1,
            },
            "regression": {
                "status": self.regression_status,
                "accuracy_delta": self.accuracy_delta,
                "f1_delta": self.f1_delta,
            },
            "drift_status": self.drift_status,
            "vs_active": {
                "beats_active": self.beats_active,
                "active_version": self.active_version,
                "active_accuracy": self.active_accuracy,
                "active_f1": self.active_f1,
            },
            "blocking_reasons": self.blocking_reasons,
            "timestamp": self.timestamp,
        }


class RetrainValidator:
    """
    Validates models before deployment.
    
    Usage::
    
        validator = RetrainValidator()
        validator.load_config(config)
        
        result = validator.validate(
            version="v2",
            train_result=train_result,
        )
        
        if result.valid:
            # Safe to deploy
    """
    
    def __init__(self):
        self._project_root = Path(__file__).resolve().parents[2]
        
        # Thresholds (config-driven)
        self._min_accuracy = 0.90
        self._min_f1 = 0.88
        self._regression_threshold = 0.01  # Stricter for deployment
        self._allow_drift_high = False
        
        # Paths
        self._models_dir = self._project_root / "models"
        self._baseline_dir = self._project_root / "baseline"
    
    def load_config(self, config: Dict[str, Any]) -> None:
        """Load configuration."""
        deploy_cfg = config.get("deploy", {})
        quality_cfg = config.get("ml_evaluation", {}).get("quality_gate", {})
        
        self._min_accuracy = quality_cfg.get("min_accuracy", 0.90)
        self._min_f1 = quality_cfg.get("min_f1", 0.88)
        self._regression_threshold = deploy_cfg.get("regression_threshold", 0.01)
        self._allow_drift_high = deploy_cfg.get("allow_drift_high", False)
        
        logger.info(
            "Validator config: min_acc=%.2f min_f1=%.2f reg_thresh=%.3f",
            self._min_accuracy, self._min_f1, self._regression_threshold,
        )
    
    def validate(
        self,
        version: str,
        metrics: Dict[str, Any],
        regression_status: str = "PASS",
        drift_status: str = "LOW",
    ) -> ValidationResult:
        """
        Validate a model for deployment.
        
        Args:
            version: Model version (e.g., "v2")
            metrics: Training metrics (accuracy, f1, etc.)
            regression_status: From stability layer
            drift_status: From drift monitor
        
        Returns:
            ValidationResult
        """
        blocking_reasons = []
        
        # Extract metrics
        accuracy = metrics.get("accuracy", {}).get("mean", 0)
        f1 = metrics.get("f1", {}).get("mean", 0)
        
        # 1. Quality gate check
        quality_passed = accuracy >= self._min_accuracy and f1 >= self._min_f1
        if not quality_passed:
            blocking_reasons.append(
                f"Quality gate failed: acc={accuracy:.4f} < {self._min_accuracy} or "
                f"f1={f1:.4f} < {self._min_f1}"
            )
        
        # 2. Regression check
        baseline_metrics = self._load_baseline_metrics()
        baseline_acc = baseline_metrics.get("accuracy", 0)
        baseline_f1 = baseline_metrics.get("f1", 0)
        
        accuracy_delta = accuracy - baseline_acc
        f1_delta = f1 - baseline_f1
        
        if regression_status == "FAIL":
            blocking_reasons.append(f"Regression FAIL: acc_delta={accuracy_delta:.4f}")
        
        # Stricter: must not regress more than threshold
        if accuracy_delta < -self._regression_threshold:
            blocking_reasons.append(
                f"Accuracy regression: {accuracy_delta:.4f} < -{self._regression_threshold}"
            )
            regression_status = "FAIL"
        if f1_delta < -self._regression_threshold:
            blocking_reasons.append(
                f"F1 regression: {f1_delta:.4f} < -{self._regression_threshold}"
            )
            regression_status = "FAIL"
        
        # 3. Drift check
        if drift_status == "CRITICAL":
            blocking_reasons.append("Data drift is CRITICAL")
        elif drift_status == "HIGH" and not self._allow_drift_high:
            blocking_reasons.append("Data drift is HIGH (not allowed)")
        
        # 4. Comparison with active model
        active_metrics = self._load_active_metrics()
        active_version = active_metrics.get("version", "unknown")
        active_accuracy = active_metrics.get("accuracy", 0)
        active_f1 = active_metrics.get("f1", 0)
        
        beats_active = accuracy >= active_accuracy - self._regression_threshold
        
        if not beats_active:
            blocking_reasons.append(
                f"Does not beat active model: {accuracy:.4f} < {active_accuracy:.4f} - {self._regression_threshold}"
            )
        
        # Determine validity
        valid = len(blocking_reasons) == 0
        
        result = ValidationResult(
            valid=valid,
            version=version,
            quality_passed=quality_passed,
            accuracy=accuracy,
            f1=f1,
            regression_status=regression_status,
            accuracy_delta=accuracy_delta,
            f1_delta=f1_delta,
            drift_status=drift_status,
            beats_active=beats_active,
            active_version=active_version,
            active_accuracy=active_accuracy,
            active_f1=active_f1,
            blocking_reasons=blocking_reasons,
        )
        
        logger.info(
            "Validation for %s: valid=%s beats_active=%s reasons=%d",
            version, valid, beats_active, len(blocking_reasons),
        )
        
        return result
    
    def _load_baseline_metrics(self) -> Dict[str, Any]:
        """Load baseline metrics."""
        baseline_path = self._baseline_dir / "baseline_metrics.json"
        
        if not baseline_path.exists():
            return {}
        
        try:
            with open(baseline_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    
    def _load_active_metrics(self) -> Dict[str, Any]:
        """Load active model metrics."""
        active_path = self._models_dir / "active" / "metrics.json"
        
        if not active_path.exists():
            # Try to find any version
            for item in self._models_dir.iterdir():
                if item.is_dir() and item.name.startswith("v"):
                    metrics_path = item / "metrics.json"
                    if metrics_path.exists():
                        try:
                            with open(metrics_path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                                data["version"] = item.name
                                return data
                        except Exception:
                            continue
            return {}
        
        try:
            with open(active_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["version"] = "active"
                return data
        except Exception:
            return {}

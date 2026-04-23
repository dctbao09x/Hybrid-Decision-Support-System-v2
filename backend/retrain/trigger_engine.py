# backend/retrain/trigger_engine.py
"""
Trigger Engine
==============

Determines when auto-retraining should be triggered.

Trigger conditions:
  - Drift: PSI ≥ threshold (from drift_monitor)
  - Regression: Status == FAIL (from regression_guard)
  - Dataset: Change > X% (from fingerprint)
  - Feedback: Online accuracy drop
  - Scheduled: Periodic retraining
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ml_retrain.trigger")


class TriggerType(Enum):
    """Types of retrain triggers."""
    DRIFT = "drift"
    REGRESSION = "regression"
    DATASET_CHANGE = "dataset_change"
    FEEDBACK_DROP = "feedback_drop"
    SCHEDULED = "scheduled"
    MANUAL = "manual"


@dataclass
class TriggerResult:
    """Result of trigger evaluation."""
    should_trigger: bool
    trigger_type: Optional[TriggerType]
    reason: str
    details: Dict[str, Any]
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_trigger": self.should_trigger,
            "trigger_type": self.trigger_type.value if self.trigger_type else None,
            "reason": self.reason,
            "details": self.details,
            "timestamp": self.timestamp,
        }


class TriggerEngine:
    """
    Evaluates conditions for auto-retraining.
    
    Usage::
    
        engine = TriggerEngine()
        engine.load_config(config)
        
        result = engine.evaluate()
        if result.should_trigger:
            # Start retraining
    """
    
    def __init__(self):
        self._project_root = Path(__file__).resolve().parents[2]
        
        # Thresholds (config-driven)
        self._drift_threshold: float = 0.25  # PSI threshold for HIGH
        self._regression_block: bool = True
        self._dataset_change_threshold: float = 0.10  # 10% change
        self._feedback_accuracy_threshold: float = 0.85
        self._min_feedback_samples: int = 50
        
        # Paths
        self._stability_report_path = self._project_root / "outputs" / "stability_report.json"
        self._drift_report_path = self._project_root / "outputs" / "drift_report.json"
        self._feedback_log_path = self._project_root / "feedback_logs" / "matched.jsonl"
    
    def load_config(self, config: Dict[str, Any]) -> None:
        """Load configuration from system.yaml."""
        retrain_cfg = config.get("retrain", {})
        
        self._drift_threshold = retrain_cfg.get("drift_threshold", 0.25)
        self._regression_block = retrain_cfg.get("block_on_regression", True)
        self._dataset_change_threshold = retrain_cfg.get("dataset_change_threshold", 0.10)
        self._feedback_accuracy_threshold = retrain_cfg.get("feedback_accuracy_threshold", 0.85)
        self._min_feedback_samples = retrain_cfg.get("min_feedback_samples", 50)
        
        logger.info(
            "Trigger config: drift_threshold=%.2f dataset_change=%.2f feedback_acc=%.2f",
            self._drift_threshold,
            self._dataset_change_threshold,
            self._feedback_accuracy_threshold,
        )
    
    def evaluate(self) -> TriggerResult:
        """
        Evaluate all trigger conditions.
        
        Returns:
            TriggerResult indicating if retraining should start
        """
        # Check in priority order
        
        # 1. Regression FAIL
        regression_check = self._check_regression()
        if regression_check.should_trigger:
            return regression_check
        
        # 2. Drift HIGH/CRITICAL
        drift_check = self._check_drift()
        if drift_check.should_trigger:
            return drift_check
        
        # 3. Dataset change
        dataset_check = self._check_dataset_change()
        if dataset_check.should_trigger:
            return dataset_check
        
        # 4. Feedback accuracy drop
        feedback_check = self._check_feedback_accuracy()
        if feedback_check.should_trigger:
            return feedback_check
        
        # No trigger
        return TriggerResult(
            should_trigger=False,
            trigger_type=None,
            reason="All checks passed",
            details={
                "regression": regression_check.details,
                "drift": drift_check.details,
                "dataset": dataset_check.details,
                "feedback": feedback_check.details,
            },
        )
    
    def force_trigger(self, reason: str = "manual") -> TriggerResult:
        """Force a manual retrain trigger."""
        return TriggerResult(
            should_trigger=True,
            trigger_type=TriggerType.MANUAL,
            reason=f"Manual trigger: {reason}",
            details={"manual": True},
        )
    
    def _check_regression(self) -> TriggerResult:
        """Check for regression FAIL status."""
        details = {"status": "unknown", "checked": False}
        
        if not self._stability_report_path.exists():
            return TriggerResult(
                should_trigger=False,
                trigger_type=TriggerType.REGRESSION,
                reason="No stability report found",
                details=details,
            )
        
        try:
            with open(self._stability_report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
            
            regression_status = report.get("regression_status", "PASS")
            details = {
                "status": regression_status,
                "delta_metrics": report.get("delta_metrics", {}),
                "checked": True,
            }
            
            if regression_status == "FAIL" and self._regression_block:
                return TriggerResult(
                    should_trigger=True,
                    trigger_type=TriggerType.REGRESSION,
                    reason=f"Regression FAIL detected",
                    details=details,
                )
            
        except Exception as e:
            logger.error("Error checking regression: %s", e)
            details["error"] = str(e)
        
        return TriggerResult(
            should_trigger=False,
            trigger_type=TriggerType.REGRESSION,
            reason="No regression failure",
            details=details,
        )
    
    def _check_drift(self) -> TriggerResult:
        """Check for drift above threshold."""
        details = {"severity": "unknown", "psi": 0.0, "checked": False}
        
        if not self._drift_report_path.exists():
            return TriggerResult(
                should_trigger=False,
                trigger_type=TriggerType.DRIFT,
                reason="No drift report found",
                details=details,
            )
        
        try:
            with open(self._drift_report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
            
            severity = report.get("overall_severity", "LOW")
            psi = report.get("overall_psi", 0.0)
            
            details = {
                "severity": severity,
                "psi": psi,
                "threshold": self._drift_threshold,
                "checked": True,
            }
            
            if psi >= self._drift_threshold or severity in ("HIGH", "CRITICAL"):
                return TriggerResult(
                    should_trigger=True,
                    trigger_type=TriggerType.DRIFT,
                    reason=f"Drift {severity} (PSI={psi:.3f} >= {self._drift_threshold})",
                    details=details,
                )
            
        except Exception as e:
            logger.error("Error checking drift: %s", e)
            details["error"] = str(e)
        
        return TriggerResult(
            should_trigger=False,
            trigger_type=TriggerType.DRIFT,
            reason="Drift within threshold",
            details=details,
        )
    
    def _check_dataset_change(self) -> TriggerResult:
        """Check for significant dataset changes."""
        details = {"change_ratio": 0.0, "checked": False}
        
        # Compare baseline fingerprint vs current
        baseline_path = self._project_root / "baseline" / "dataset_fingerprint.json"
        current_path = self._project_root / "outputs" / "stability_report.json"
        
        if not baseline_path.exists() or not current_path.exists():
            return TriggerResult(
                should_trigger=False,
                trigger_type=TriggerType.DATASET_CHANGE,
                reason="Cannot compare datasets",
                details=details,
            )
        
        try:
            with open(baseline_path, "r", encoding="utf-8") as f:
                baseline = json.load(f)
            with open(current_path, "r", encoding="utf-8") as f:
                current = json.load(f)
            
            baseline_hash = baseline.get("hash", "")
            current_hash = current.get("dataset_hash", "")
            
            details = {
                "baseline_hash": baseline_hash[:16] if baseline_hash else "",
                "current_hash": current_hash[:16] if current_hash else "",
                "hash_changed": baseline_hash != current_hash,
                "checked": True,
            }
            
            # For now, trigger if hash changed
            # In production, would compare row counts, schema, etc.
            if baseline_hash and current_hash and baseline_hash != current_hash:
                # Check if we have new feedback data
                feedback_count = self._count_new_feedback()
                details["new_feedback_count"] = feedback_count
                
                if feedback_count >= self._min_feedback_samples:
                    return TriggerResult(
                        should_trigger=True,
                        trigger_type=TriggerType.DATASET_CHANGE,
                        reason=f"Dataset changed with {feedback_count} new feedback samples",
                        details=details,
                    )
            
        except Exception as e:
            logger.error("Error checking dataset change: %s", e)
            details["error"] = str(e)
        
        return TriggerResult(
            should_trigger=False,
            trigger_type=TriggerType.DATASET_CHANGE,
            reason="No significant dataset change",
            details=details,
        )
    
    def _check_feedback_accuracy(self) -> TriggerResult:
        """Check for online accuracy drop from feedback."""
        details = {"accuracy": 0.0, "sample_count": 0, "checked": False}
        
        if not self._feedback_log_path.exists():
            return TriggerResult(
                should_trigger=False,
                trigger_type=TriggerType.FEEDBACK_DROP,
                reason="No feedback log found",
                details=details,
            )
        
        try:
            total = 0
            correct = 0
            
            with open(self._feedback_log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        total += 1
                        if record.get("is_correct"):
                            correct += 1
                    except json.JSONDecodeError:
                        continue
            
            accuracy = correct / total if total > 0 else 0.0
            
            details = {
                "accuracy": accuracy,
                "sample_count": total,
                "threshold": self._feedback_accuracy_threshold,
                "min_samples": self._min_feedback_samples,
                "checked": True,
            }
            
            if total >= self._min_feedback_samples and accuracy < self._feedback_accuracy_threshold:
                return TriggerResult(
                    should_trigger=True,
                    trigger_type=TriggerType.FEEDBACK_DROP,
                    reason=f"Online accuracy {accuracy:.2%} < {self._feedback_accuracy_threshold:.2%}",
                    details=details,
                )
            
        except Exception as e:
            logger.error("Error checking feedback accuracy: %s", e)
            details["error"] = str(e)
        
        return TriggerResult(
            should_trigger=False,
            trigger_type=TriggerType.FEEDBACK_DROP,
            reason="Online accuracy OK",
            details=details,
        )
    
    def _count_new_feedback(self) -> int:
        """Count new feedback samples since last retrain."""
        if not self._feedback_log_path.exists():
            return 0
        
        count = 0
        try:
            with open(self._feedback_log_path, "r", encoding="utf-8") as f:
                for line in f:
                    count += 1
        except Exception:
            pass
        
        return count

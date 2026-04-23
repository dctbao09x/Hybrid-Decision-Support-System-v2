# backend/evaluation/regression_guard.py
"""
Regression Guard
================
Protects against ML model quality regression by comparing new metrics
against a baseline snapshot.

If metrics drop below the baseline minus a configurable threshold,
the guard raises a warning and optionally blocks publishing.

Threshold logic:
  FAIL if: accuracy_new < accuracy_baseline - threshold
       OR: f1_new < f1_baseline - threshold
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("ml_evaluation.regression_guard")


class RegressionStatus(Enum):
    """Regression check result status."""
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    NO_BASELINE = "NO_BASELINE"


@dataclass
class BaselineMetrics:
    """
    Baseline metrics snapshot for regression comparison.

    Attributes:
        accuracy:      Best accuracy achieved.
        f1:            Best F1 score achieved.
        precision:     Best precision achieved.
        recall:        Best recall achieved.
        dataset_hash:  Hash of the dataset used to produce baseline.
        model_type:    Model type (e.g., "random_forest").
        kfold:         Number of CV folds used.
        run_id:        Run ID that produced this baseline.
        created_at:    ISO timestamp.
    """
    accuracy: float
    f1: float
    precision: float = 0.0
    recall: float = 0.0
    dataset_hash: str = ""
    model_type: str = ""
    kfold: int = 5
    run_id: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accuracy": self.accuracy,
            "f1": self.f1,
            "precision": self.precision,
            "recall": self.recall,
            "dataset_hash": self.dataset_hash,
            "model_type": self.model_type,
            "kfold": self.kfold,
            "run_id": self.run_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaselineMetrics":
        return cls(
            accuracy=data["accuracy"],
            f1=data["f1"],
            precision=data.get("precision", 0.0),
            recall=data.get("recall", 0.0),
            dataset_hash=data.get("dataset_hash", ""),
            model_type=data.get("model_type", ""),
            kfold=data.get("kfold", 5),
            run_id=data.get("run_id", ""),
            created_at=data.get("created_at", ""),
        )


@dataclass
class RegressionCheckResult:
    """Result of a regression check."""
    status: RegressionStatus
    accuracy_delta: float
    f1_delta: float
    precision_delta: float
    recall_delta: float
    threshold: float
    message: str
    should_block: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "accuracy_delta": round(self.accuracy_delta, 6),
            "f1_delta": round(self.f1_delta, 6),
            "precision_delta": round(self.precision_delta, 6),
            "recall_delta": round(self.recall_delta, 6),
            "threshold": self.threshold,
            "message": self.message,
            "should_block": self.should_block,
        }


class RegressionGuard:
    """
    Guards against regression in ML metrics.

    Usage::

        guard = RegressionGuard(threshold=0.03)
        guard.load_baseline("baseline/baseline_metrics.json")
        result = guard.check(new_metrics)
        if result.should_block:
            raise RegressionError(result.message)
    """

    DEFAULT_THRESHOLD = 0.03
    DEFAULT_BASELINE_PATH = "baseline/baseline_metrics.json"

    def __init__(
        self,
        threshold: Optional[float] = None,
        block_on_fail: bool = True,
        baseline_path: Optional[str] = None,
    ):
        """
        Initialize the regression guard.

        Args:
            threshold:     Max allowed drop from baseline (default: 0.03).
            block_on_fail: If True, should_block=True on FAIL status.
            baseline_path: Path to baseline metrics JSON.
        """
        self._threshold = threshold if threshold is not None else self.DEFAULT_THRESHOLD
        self._block_on_fail = block_on_fail
        self._baseline_path = baseline_path or self.DEFAULT_BASELINE_PATH
        self._baseline: Optional[BaselineMetrics] = None
        self._project_root = Path(__file__).resolve().parents[2]

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def baseline(self) -> Optional[BaselineMetrics]:
        return self._baseline

    @property
    def has_baseline(self) -> bool:
        return self._baseline is not None

    def load_baseline(self, path: Optional[str] = None) -> Optional[BaselineMetrics]:
        """Load baseline metrics from JSON file."""
        path = path or self._baseline_path
        full_path = self._project_root / path

        if not full_path.exists():
            logger.warning("Baseline not found: %s", full_path)
            return None

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._baseline = BaselineMetrics.from_dict(data)
            logger.info(
                "Loaded baseline: acc=%.4f f1=%.4f from %s",
                self._baseline.accuracy, self._baseline.f1, path,
            )
            return self._baseline
        except Exception as e:
            logger.error("Failed to load baseline: %s", e)
            return None

    def save_baseline(
        self,
        metrics: Dict[str, Any],
        dataset_hash: str,
        model_type: str,
        kfold: int,
        run_id: str,
        path: Optional[str] = None,
    ) -> BaselineMetrics:
        """Save new baseline metrics to JSON file."""
        path = path or self._baseline_path
        full_path = self._project_root / path

        baseline = BaselineMetrics(
            accuracy=metrics.get("accuracy", {}).get("mean", 0.0),
            f1=metrics.get("f1", {}).get("mean", 0.0),
            precision=metrics.get("precision", {}).get("mean", 0.0),
            recall=metrics.get("recall", {}).get("mean", 0.0),
            dataset_hash=dataset_hash,
            model_type=model_type,
            kfold=kfold,
            run_id=run_id,
        )

        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(baseline.to_dict(), f, indent=2)

        self._baseline = baseline
        logger.info("Saved new baseline: acc=%.4f f1=%.4f → %s", baseline.accuracy, baseline.f1, path)
        return baseline

    def check(
        self,
        new_metrics: Dict[str, Any],
        strict: bool = False,
    ) -> RegressionCheckResult:
        """
        Check new metrics against baseline.

        Args:
            new_metrics: Dict with accuracy/f1/precision/recall (mean values).
            strict:      If True, also check precision and recall.

        Returns:
            RegressionCheckResult with status and deltas.
        """
        # No baseline → automatic pass (first run)
        if not self._baseline:
            logger.info("No baseline — skipping regression check")
            return RegressionCheckResult(
                status=RegressionStatus.NO_BASELINE,
                accuracy_delta=0.0,
                f1_delta=0.0,
                precision_delta=0.0,
                recall_delta=0.0,
                threshold=self._threshold,
                message="No baseline available — first run",
                should_block=False,
            )

        # Extract new metric values
        new_acc = new_metrics.get("accuracy", {}).get("mean", 0.0)
        new_f1 = new_metrics.get("f1", {}).get("mean", 0.0)
        new_prec = new_metrics.get("precision", {}).get("mean", 0.0)
        new_rec = new_metrics.get("recall", {}).get("mean", 0.0)

        # Compute deltas (positive = improvement, negative = regression)
        acc_delta = new_acc - self._baseline.accuracy
        f1_delta = new_f1 - self._baseline.f1
        prec_delta = new_prec - self._baseline.precision
        rec_delta = new_rec - self._baseline.recall

        # Check for regression
        acc_regressed = acc_delta < -self._threshold
        f1_regressed = f1_delta < -self._threshold

        if acc_regressed or f1_regressed:
            status = RegressionStatus.FAIL
            regressed_metrics = []
            if acc_regressed:
                regressed_metrics.append(f"accuracy ({acc_delta:+.4f})")
            if f1_regressed:
                regressed_metrics.append(f"f1 ({f1_delta:+.4f})")

            message = (
                f"REGRESSION DETECTED: {', '.join(regressed_metrics)} "
                f"exceeded threshold ({self._threshold})"
            )
            logger.warning(message)
            should_block = self._block_on_fail
        elif acc_delta < 0 or f1_delta < 0:
            # Minor drop but within threshold
            status = RegressionStatus.WARN
            message = (
                f"Minor regression: acc={acc_delta:+.4f} f1={f1_delta:+.4f} "
                f"(within threshold {self._threshold})"
            )
            logger.warning(message)
            should_block = False
        else:
            status = RegressionStatus.PASS
            message = f"Metrics stable/improved: acc={acc_delta:+.4f} f1={f1_delta:+.4f}"
            logger.info(message)
            should_block = False

        return RegressionCheckResult(
            status=status,
            accuracy_delta=acc_delta,
            f1_delta=f1_delta,
            precision_delta=prec_delta,
            recall_delta=rec_delta,
            threshold=self._threshold,
            message=message,
            should_block=should_block,
        )

    def should_update_baseline(
        self,
        new_metrics: Dict[str, Any],
        policy: str = "any_improvement",
    ) -> bool:
        """
        Determine if baseline should be updated.

        Policies:
          - "any_improvement": Update if accuracy OR f1 improved.
          - "both_improvement": Update only if BOTH improved.
          - "f1_improvement": Update only if f1 improved.

        Args:
            new_metrics: New metrics dict.
            policy:      Update policy.

        Returns:
            True if baseline should be updated.
        """
        if not self._baseline:
            return True

        new_acc = new_metrics.get("accuracy", {}).get("mean", 0.0)
        new_f1 = new_metrics.get("f1", {}).get("mean", 0.0)

        if policy == "both_improvement":
            return new_acc > self._baseline.accuracy and new_f1 > self._baseline.f1
        elif policy == "f1_improvement":
            return new_f1 > self._baseline.f1
        else:  # any_improvement
            return new_acc > self._baseline.accuracy or new_f1 > self._baseline.f1


class RegressionError(Exception):
    """Raised when regression check fails and blocking is enabled."""

    def __init__(self, message: str, result: RegressionCheckResult):
        super().__init__(message)
        self.result = result

# backend/evaluation/metrics.py
"""
Metrics Engine
==============
Computes classification metrics from raw CV fold results.

Metrics computed per fold & aggregated (mean ± std):
  • Accuracy
  • Precision  (macro)
  • Recall     (macro)
  • F1-score   (macro)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
)

from backend.evaluation.train_eval import CVResult, FoldResult

logger = logging.getLogger("ml_evaluation.metrics")


@dataclass
class FoldMetrics:
    """Metrics for a single fold."""
    fold_index: int
    accuracy: float
    precision: float
    recall: float
    f1: float


@dataclass
class AggregatedMetrics:
    """Mean ± std across all folds."""
    accuracy_mean: float
    accuracy_std: float
    precision_mean: float
    precision_std: float
    recall_mean: float
    recall_std: float
    f1_mean: float
    f1_std: float

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the canonical output format."""
        return {
            "accuracy": {"mean": round(self.accuracy_mean, 6), "std": round(self.accuracy_std, 6)},
            "precision": {"mean": round(self.precision_mean, 6), "std": round(self.precision_std, 6)},
            "recall": {"mean": round(self.recall_mean, 6), "std": round(self.recall_std, 6)},
            "f1": {"mean": round(self.f1_mean, 6), "std": round(self.f1_std, 6)},
        }


class MetricsEngine:
    """
    Compute and aggregate classification metrics from CVResult.

    Usage::

        engine = MetricsEngine()
        fold_metrics, agg = engine.compute(cv_result)
    """

    AVERAGE = "macro"  # multi-class averaging strategy

    def compute_fold(self, fold: FoldResult) -> FoldMetrics:
        """Compute metrics for a single fold."""
        return FoldMetrics(
            fold_index=fold.fold_index,
            accuracy=accuracy_score(fold.y_true, fold.y_pred),
            precision=precision_score(
                fold.y_true, fold.y_pred,
                average=self.AVERAGE, zero_division=0,
            ),
            recall=recall_score(
                fold.y_true, fold.y_pred,
                average=self.AVERAGE, zero_division=0,
            ),
            f1=f1_score(
                fold.y_true, fold.y_pred,
                average=self.AVERAGE, zero_division=0,
            ),
        )

    def compute(
        self, cv_result: CVResult
    ) -> tuple[List[FoldMetrics], AggregatedMetrics]:
        """
        Compute per-fold metrics and aggregate.

        Returns:
            (list_of_fold_metrics, aggregated_metrics)
        """
        fold_metrics: List[FoldMetrics] = []

        for fold in cv_result.fold_results:
            fm = self.compute_fold(fold)
            fold_metrics.append(fm)
            logger.info(
                "Fold %d metrics — acc=%.4f  prec=%.4f  rec=%.4f  f1=%.4f",
                fm.fold_index + 1,
                fm.accuracy,
                fm.precision,
                fm.recall,
                fm.f1,
            )

        accuracies = np.array([m.accuracy for m in fold_metrics])
        precisions = np.array([m.precision for m in fold_metrics])
        recalls = np.array([m.recall for m in fold_metrics])
        f1s = np.array([m.f1 for m in fold_metrics])

        agg = AggregatedMetrics(
            accuracy_mean=float(accuracies.mean()),
            accuracy_std=float(accuracies.std()),
            precision_mean=float(precisions.mean()),
            precision_std=float(precisions.std()),
            recall_mean=float(recalls.mean()),
            recall_std=float(recalls.std()),
            f1_mean=float(f1s.mean()),
            f1_std=float(f1s.std()),
        )

        logger.info(
            "Aggregated — acc=%.4f±%.4f  f1=%.4f±%.4f",
            agg.accuracy_mean, agg.accuracy_std,
            agg.f1_mean, agg.f1_std,
        )

        return fold_metrics, agg

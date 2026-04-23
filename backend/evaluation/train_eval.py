# backend/evaluation/train_eval.py
"""
Training & Cross-Validation Engine
===================================
Performs K-Fold cross-validation, returning raw per-fold metrics
without printing results directly.  All output goes through logging.

Designed to be called by MLEvaluationService.run_pipeline().
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
from sklearn.base import ClassifierMixin, clone
from sklearn.model_selection import KFold

logger = logging.getLogger("ml_evaluation.train_eval")


@dataclass
class FoldResult:
    """Metric container for a single CV fold."""
    fold_index: int
    y_true: np.ndarray
    y_pred: np.ndarray
    train_time_s: float = 0.0
    predict_time_s: float = 0.0


@dataclass
class CVResult:
    """Aggregate container for the full cross-validation run."""
    fold_results: List[FoldResult] = field(default_factory=list)
    total_time_s: float = 0.0


class CrossValidator:
    """
    K-Fold Cross-Validator.

    Usage::

        cv = CrossValidator(kfold=5, random_state=42)
        cv_result = cv.run(model, X, y)
    """

    def __init__(
        self,
        kfold: int = 5,
        random_state: int = 42,
        shuffle: bool = True,
    ) -> None:
        if kfold < 2:
            raise ValueError("kfold must be ≥ 2")
        self._kfold = kfold
        self._random_state = random_state
        self._shuffle = shuffle

    @property
    def kfold(self) -> int:
        return self._kfold

    def run(
        self,
        model: ClassifierMixin,
        X: np.ndarray,
        y: np.ndarray,
    ) -> CVResult:
        """
        Execute K-Fold CV and return raw fold results.

        Args:
            model: Unfitted sklearn classifier (will be cloned per fold).
            X:     Feature matrix  (n_samples, n_features).
            y:     Label vector    (n_samples,).

        Returns:
            CVResult with per-fold y_true / y_pred arrays.
        """
        kf = KFold(
            n_splits=self._kfold,
            shuffle=self._shuffle,
            random_state=self._random_state,
        )

        cv_result = CVResult()
        t0 = time.perf_counter()

        for fold_idx, (train_idx, test_idx) in enumerate(kf.split(X)):
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]

            fold_model = clone(model)

            # Train
            train_t0 = time.perf_counter()
            fold_model.fit(X_train, y_train)
            train_time = time.perf_counter() - train_t0

            # Predict
            pred_t0 = time.perf_counter()
            y_pred = fold_model.predict(X_test)
            pred_time = time.perf_counter() - pred_t0

            fold_result = FoldResult(
                fold_index=fold_idx,
                y_true=y_test,
                y_pred=y_pred,
                train_time_s=train_time,
                predict_time_s=pred_time,
            )
            cv_result.fold_results.append(fold_result)

            logger.info(
                "Fold %d/%d — train=%.3fs  predict=%.3fs  samples=%d",
                fold_idx + 1,
                self._kfold,
                train_time,
                pred_time,
                len(y_test),
            )

        cv_result.total_time_s = time.perf_counter() - t0
        logger.info(
            "Cross-validation complete — %d folds in %.3fs",
            self._kfold,
            cv_result.total_time_s,
        )
        return cv_result

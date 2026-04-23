# backend/evaluation/models.py
"""
Model Layer
===========
Factory pattern for ML classifiers used by the evaluation pipeline.

Supported models:
  • RandomForestClassifier
  • LogisticRegression

All hyper-parameters are injected via config — nothing hardcoded.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.base import ClassifierMixin

logger = logging.getLogger("ml_evaluation.models")

# ── Registry (extensible) ───────────────────────────────────────
_MODEL_REGISTRY: Dict[str, type] = {
    "random_forest": RandomForestClassifier,
    "logistic_regression": LogisticRegression,
}


class UnsupportedModelError(Exception):
    """Raised when the requested model type is not in the registry."""


class ModelFactory:
    """
    Create sklearn classifier instances from config.

    Usage::

        factory = ModelFactory()
        clf = factory.get_model("random_forest", {
            "n_estimators": 200,
            "max_depth": 12,
            "random_state": 42,
        })
    """

    @staticmethod
    def available_models() -> list[str]:
        """Return list of registered model type keys."""
        return list(_MODEL_REGISTRY.keys())

    @staticmethod
    def get_model(
        model_type: str,
        params: Optional[Dict[str, Any]] = None,
        random_state: Optional[int] = None,
    ) -> ClassifierMixin:
        """
        Instantiate a classifier.

        Args:
            model_type:   Key in the model registry (e.g. "random_forest").
            params:       Hyper-parameters forwarded to the constructor.
            random_state: If provided, injected as ``random_state`` param.

        Returns:
            A scikit-learn compatible classifier instance.

        Raises:
            UnsupportedModelError: If model_type is not registered.
        """
        if model_type not in _MODEL_REGISTRY:
            raise UnsupportedModelError(
                f"Unknown model type '{model_type}'. "
                f"Available: {list(_MODEL_REGISTRY.keys())}"
            )

        cls = _MODEL_REGISTRY[model_type]
        params = dict(params or {})

        # Inject random_state if the estimator accepts it
        if random_state is not None:
            params.setdefault("random_state", random_state)

        logger.info(
            "Creating model '%s' with params: %s", model_type, params
        )

        return cls(**params)

    @staticmethod
    def register(name: str, cls: type) -> None:
        """Register a custom model class at runtime."""
        _MODEL_REGISTRY[name] = cls
        logger.info("Registered custom model: %s → %s", name, cls.__name__)

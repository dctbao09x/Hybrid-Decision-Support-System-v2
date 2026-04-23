# backend/scoring/explain/__init__.py
"""
Explainable AI (XAI) Module
===========================

Provides explainability for ML predictions through:
  - Feature Importance extraction
  - SHAP value computation
  - Human-readable reason generation
  - Audit logging

Components:
  - FeatureImportance: Extract and normalize feature importances
  - SHAPEngine: Compute SHAP values with auto-explainer selection
  - ReasonGenerator: Convert importance to human-readable reasons
  - XAIService: Core service integrating all components
"""

from backend.scoring.explain.feature_importance import (
    FeatureImportance,
    FeatureImportanceResult,
)
from backend.scoring.explain.shap_engine import (
    SHAPEngine,
    SHAPResult,
)
from backend.scoring.explain.reason_generator import (
    ReasonGenerator,
    ReasonResult,
)
from backend.scoring.explain.xai import (
    XAIService,
    ExplanationResult,
    get_xai_service,
)
from backend.scoring.explain.tracer import (
    ScoringTrace,
    ComponentTrace,
)

__all__ = [
    # Feature Importance
    "FeatureImportance",
    "FeatureImportanceResult",
    # SHAP
    "SHAPEngine",
    "SHAPResult",
    # Reason Generator
    "ReasonGenerator",
    "ReasonResult",
    # XAI Service
    "XAIService",
    "ExplanationResult",
    "get_xai_service",
    # Tracer
    "ScoringTrace",
    "ComponentTrace",
]

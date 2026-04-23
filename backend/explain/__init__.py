# backend/explain/__init__.py
"""
Explain Pipeline
================

Multi-stage explanation pipeline for career guidance predictions.

Stages:
  - Stage 2: XAI (SHAP, Feature Importance) - backend/scoring/explain/
  - Stage 3: Rule + Template Engine - backend/explain/stage3/
  - Stage 4: LLM Enhancement (optional) - backend/explain/stage4/

Pipeline:
    Inference → XAI (Stage 2) → Rule+Template (Stage 3) → LLM (Stage 4) → API → Frontend
"""

from backend.explain.models import ExplanationRecord, RuleFire, EvidenceItem, TraceGraph
from backend.explain.storage import ExplanationStorage, get_explanation_storage
from backend.explain.retention import ExplainRetentionManager
from backend.explain.consistency_validator import (
    ExplanationInconsistencyError,
    validate_explanation_consistency,
)

__all__ = [
  "ExplanationRecord",
  "RuleFire",
  "EvidenceItem",
  "TraceGraph",
  "ExplanationStorage",
  "get_explanation_storage",
  "ExplainRetentionManager",
  "ExplanationInconsistencyError",
  "validate_explanation_consistency",
]

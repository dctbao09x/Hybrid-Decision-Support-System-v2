# backend/quality/__init__.py
"""
Data Quality Enhancement Module
===============================

This module provides response consistency validation and adaptive questioning
WITHOUT modifying deterministic scoring.

SYSTEM RULES (IMMUTABLE):
- SIMGRScorer MUST remain untouched
- Confidence score CANNOT influence base score
- Confidence only affects explanation and flagging

Components:
- ConsistencyValidator: Aggregates detector results
- Detectors: Speed, Contradiction, Uniformity, Entropy
- AdaptiveQuestionInjector: Confidence-based follow-up questions
- ConfidenceThresholdPolicy: Action thresholds
- ExplanationDegradationStrategy: Explanation quality control
"""

from backend.quality.consistency_validator import ConsistencyValidator
from backend.quality.confidence_policy import ConfidenceThresholdPolicy
from backend.quality.adaptive_questions import (
    AdaptiveQuestionInjector,
    AdaptiveQuestionTrigger,
    AdaptiveQuestionConfig,
)
from backend.quality.explanation_degradation import ExplanationDegradationStrategy

__all__ = [
    "ConsistencyValidator",
    "ConfidenceThresholdPolicy",
    "AdaptiveQuestionInjector",
    "AdaptiveQuestionTrigger",
    "AdaptiveQuestionConfig",
    "ExplanationDegradationStrategy",
]

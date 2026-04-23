# backend/quality/detectors/__init__.py
"""
Consistency Detectors Package
=============================

Provides four independent detectors for identifying response anomalies.

Each detector returns a penalty ∈ [0, 1] where:
- 0 = no anomaly detected
- 1 = maximum anomaly

CRITICAL: These penalties are used ONLY for confidence calculation,
NOT for modifying base scores.
"""

from backend.quality.detectors.speed_anomaly import SpeedAnomalyDetector
from backend.quality.detectors.trait_contradiction import TraitContradictionMatrix
from backend.quality.detectors.likert_uniformity import LikertUniformityDetector
from backend.quality.detectors.entropy_analyzer import RandomPatternEntropyAnalyzer

__all__ = [
    "SpeedAnomalyDetector",
    "TraitContradictionMatrix",
    "LikertUniformityDetector",
    "RandomPatternEntropyAnalyzer",
]

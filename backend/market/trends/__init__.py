# backend/market/trends/__init__.py
"""
Skill Trend & Drift Detector
============================

Analyze and detect skill market trends:
- Frequency velocity
- Salary correlation
- Co-skill emergence
- Trend classification
- Change point detection
"""

from .models import (
    SkillTrend,
    SkillDrift,
    TrendDirection,
    TrendSignal,
    CoSkillPair,
    TrendSnapshot,
    ChangePoint,
)
from .detector import (
    TrendDetector,
    DriftAnalyzer,
    get_trend_detector,
)

__all__ = [
    "SkillTrend",
    "SkillDrift",
    "TrendDirection",
    "TrendSignal",
    "CoSkillPair",
    "TrendSnapshot",
    "ChangePoint",
    "TrendDetector",
    "DriftAnalyzer",
    "get_trend_detector",
]

# backend/market/gap/__init__.py
"""
Career Gap Analyzer
===================

Gap analysis and learning path generation:
- User profile vs market demand matching
- Skill gap identification
- Learning path optimization
- Career trajectory suggestions
"""

from .models import (
    UserProfile,
    SkillLevel,
    SkillGap,
    CareerTarget,
    LearningPath,
    LearningResource,
    GapAnalysisResult,
    CareerTrajectory,
)
from .analyzer import (
    GapAnalyzer,
    PathOptimizer,
    get_gap_analyzer,
)

__all__ = [
    "UserProfile",
    "SkillLevel",
    "SkillGap",
    "CareerTarget",
    "LearningPath",
    "LearningResource",
    "GapAnalysisResult",
    "CareerTrajectory",
    "GapAnalyzer",
    "PathOptimizer",
    "get_gap_analyzer",
]

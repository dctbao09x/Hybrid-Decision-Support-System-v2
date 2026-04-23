# backend/explain/score_analytics/__init__.py
"""
Score Analytics Explanation Module
===================================

Generates a structured 6-stage analytical explanation of SIMGR scoring
results by filling the ``score_analytics.txt`` prompt template and
dispatching to the Ollama LLM.

Public API::

    from backend.explain.score_analytics import render_score_analytics

    markdown_text = await render_score_analytics(
        scoring_breakdown=breakdown,
        profile=profile_dict,
        confidence=0.87,
    )
"""

from backend.explain.score_analytics.engine import (
    ScoreAnalyticsEngine,
    ScoreAnalyticsInput,
    ScoreAnalyticsResult,
    render_score_analytics,
    get_score_analytics_engine,
)

__all__ = [
    "ScoreAnalyticsEngine",
    "ScoreAnalyticsInput",
    "ScoreAnalyticsResult",
    "render_score_analytics",
    "get_score_analytics_engine",
]

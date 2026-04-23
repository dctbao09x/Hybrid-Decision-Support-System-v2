# backend/explain/stage3/__init__.py
"""
Stage 3 - Rule + Template Engine
================================

Transforms XAI output (Stage 2) into stable, deterministic explanation text.

Components:
  - rule_map: Reason code to text mapping
  - engine: Stage 3 builder (run_stage3)
  - templates: Jinja2 templates for rendering

Usage:
    from backend.explain.stage3 import run_stage3
    
    result = run_stage3(xai_output)
"""

from backend.explain.stage3.rule_map import (
    REASON_MAP,
    VALID_SOURCES,
    get_reason_text,
    bind_evidence,
    map_reasons,
)
from backend.explain.stage3.engine import run_stage3, Stage3Engine

__all__ = [
    "REASON_MAP",
    "VALID_SOURCES",
    "get_reason_text",
    "bind_evidence",
    "map_reasons",
    "run_stage3",
    "Stage3Engine",
]

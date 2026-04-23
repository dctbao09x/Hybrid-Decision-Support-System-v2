# backend/explanation/__init__.py
"""
Explanation Layer Module
========================

Optimized explanation generation for minimal UI system.

CONSTRAINTS:
- Explanations derive strictly from computed data
- No hallucination
- Single LLM call max
- No interactive chat

EXPORTS:
- MinimalExplanationLayer: Main explanation generator
- ExplanationTier: Tier definitions (DEFAULT, ONDEMAND)
- create_explanation_layer: Factory function
- explain_career: Convenience function
"""

from backend.explanation.minimal_explanation import (
    # Core classes
    MinimalExplanationLayer,
    ExplanationTier,
    Tier1Generator,
    Tier2Generator,
    LLMFormatter,
    
    # Data sources
    ScoreBreakdownSource,
    RuleTraceSource,
    FeatureVectorSource,
    
    # Content types
    Tier1Content,
    Tier2Content,
    LLMFormatRequest,
    
    # Factory functions
    create_explanation_layer,
    explain_career,
    
    # Constants
    FROZEN_WEIGHTS,
    COMPONENT_DISPLAY_NAMES,
)

__all__ = [
    # Core
    "MinimalExplanationLayer",
    "ExplanationTier",
    "Tier1Generator",
    "Tier2Generator",
    "LLMFormatter",
    
    # Data sources
    "ScoreBreakdownSource",
    "RuleTraceSource",
    "FeatureVectorSource",
    
    # Content
    "Tier1Content",
    "Tier2Content",
    "LLMFormatRequest",
    
    # Functions
    "create_explanation_layer",
    "explain_career",
    
    # Constants
    "FROZEN_WEIGHTS",
    "COMPONENT_DISPLAY_NAMES",
]

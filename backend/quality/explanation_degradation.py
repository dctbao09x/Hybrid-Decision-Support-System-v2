# backend/quality/explanation_degradation.py
"""
Explanation Degradation Strategy
================================

Strategy for degrading explanation based on confidence.

PRINCIPLE: Low confidence = less specific explanations.
This prevents fabricated specificity when data is unreliable.

CRITICAL: Does NOT modify scores. Only explanation content.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from backend.quality.confidence_policy import (
    ConfidenceThresholdPolicy,
    ExplanationMode,
    DEFAULT_POLICY,
)

logger = logging.getLogger("quality.explanation_degradation")


@dataclass(frozen=True)
class DegradationRules:
    """
    Rules for explanation content at different degradation levels.
    
    These rules determine what content is included in explanations
    based on data confidence level.
    """
    include_score_breakdown: bool = True
    include_feature_impacts: bool = True
    include_specific_recommendations: bool = True
    include_career_comparisons: bool = True
    llm_temperature: float = 0.3
    disclaimer: Optional[str] = None


# Degradation rules per mode
DEGRADATION_RULES: Dict[ExplanationMode, DegradationRules] = {
    ExplanationMode.FULL: DegradationRules(
        include_score_breakdown=True,
        include_feature_impacts=True,
        include_specific_recommendations=True,
        include_career_comparisons=True,
        llm_temperature=0.3,           # More deterministic
        disclaimer=None,
    ),
    ExplanationMode.DEGRADED: DegradationRules(
        include_score_breakdown=True,
        include_feature_impacts=False,  # Too unreliable
        include_specific_recommendations=False,
        include_career_comparisons=True,
        llm_temperature=0.5,
        disclaimer=(
            "Note: Some response patterns suggest uncertainty in your answers. "
            "Consider retaking the assessment for more detailed guidance."
        ),
    ),
    ExplanationMode.MINIMAL: DegradationRules(
        include_score_breakdown=False,
        include_feature_impacts=False,
        include_specific_recommendations=False,
        include_career_comparisons=False,
        llm_temperature=0.7,           # Generic is fine
        disclaimer=(
            "Warning: Response quality is low. Results are tentative. "
            "We strongly recommend retaking the assessment carefully."
        ),
    ),
}


class ExplanationDegradationStrategy:
    """
    Strategy for degrading explanation based on confidence.
    
    PRINCIPLE: Low confidence = less specific explanations.
    High confidence = full detail.
    
    CRITICAL: This DOES NOT MODIFY SCORES. Only explanation content.
    Rankings remain unchanged regardless of confidence level.
    """
    
    def __init__(
        self,
        policy: Optional[ConfidenceThresholdPolicy] = None,
        rules: Optional[Dict[ExplanationMode, DegradationRules]] = None,
    ):
        """
        Initialize strategy.
        
        Args:
            policy: Optional custom threshold policy
            rules: Optional custom degradation rules
        """
        self._policy = policy or DEFAULT_POLICY
        self._rules = rules or DEGRADATION_RULES
        logger.debug("ExplanationDegradationStrategy initialized")
    
    def apply(
        self,
        base_explanation: Dict[str, Any],
        confidence_score: float,
    ) -> Dict[str, Any]:
        """
        Apply degradation to explanation based on confidence.
        
        DOES NOT MODIFY SCORES. Only explanation content.
        
        Args:
            base_explanation: Original explanation dict
            confidence_score: Confidence score ∈ [0, 1]
        
        Returns:
            Degraded explanation dict with metadata
        """
        mode = self._policy.get_explanation_mode(confidence_score)
        rules = self._rules.get(mode, DEGRADATION_RULES[ExplanationMode.FULL])
        
        # Start with copy of original
        degraded = base_explanation.copy()
        
        # Apply degradation rules
        if not rules.include_score_breakdown:
            degraded.pop("score_breakdown", None)
            degraded.pop("breakdown", None)
        
        if not rules.include_feature_impacts:
            degraded.pop("feature_impacts", None)
            degraded.pop("feature_importances", None)
            degraded.pop("contributing_factors", None)
        
        if not rules.include_specific_recommendations:
            degraded.pop("specific_recommendations", None)
            degraded.pop("action_items", None)
            degraded.pop("next_steps", None)
        
        if not rules.include_career_comparisons:
            degraded.pop("career_comparisons", None)
            degraded.pop("alternatives", None)
            degraded.pop("comparison_matrix", None)
        
        # Add disclaimer if present
        if rules.disclaimer:
            degraded["disclaimer"] = rules.disclaimer
        
        # Add metadata about degradation
        degraded["_quality_meta"] = {
            "explanation_mode": mode.value,
            "confidence_score": confidence_score,
            "degradation_applied": mode != ExplanationMode.FULL,
            "llm_temperature_used": rules.llm_temperature,
        }
        
        logger.debug(
            f"Explanation degradation applied: mode={mode.value}, "
            f"confidence={confidence_score:.3f}"
        )
        
        return degraded
    
    def get_llm_temperature(self, confidence_score: float) -> float:
        """
        Get recommended LLM temperature based on confidence.
        
        Lower confidence = higher temperature (more generic).
        Higher confidence = lower temperature (more specific).
        
        Args:
            confidence_score: Confidence score ∈ [0, 1]
        
        Returns:
            LLM temperature value
        """
        mode = self._policy.get_explanation_mode(confidence_score)
        rules = self._rules.get(mode, DEGRADATION_RULES[ExplanationMode.FULL])
        return rules.llm_temperature
    
    def should_include_detail(
        self,
        detail_type: str,
        confidence_score: float,
    ) -> bool:
        """
        Check if a specific detail type should be included.
        
        Args:
            detail_type: One of "score_breakdown", "feature_impacts",
                        "specific_recommendations", "career_comparisons"
            confidence_score: Confidence score ∈ [0, 1]
        
        Returns:
            True if detail should be included
        """
        mode = self._policy.get_explanation_mode(confidence_score)
        rules = self._rules.get(mode, DEGRADATION_RULES[ExplanationMode.FULL])
        
        mapping = {
            "score_breakdown": rules.include_score_breakdown,
            "feature_impacts": rules.include_feature_impacts,
            "specific_recommendations": rules.include_specific_recommendations,
            "career_comparisons": rules.include_career_comparisons,
        }
        
        return mapping.get(detail_type, True)
    
    def get_degradation_summary(self, confidence_score: float) -> Dict[str, Any]:
        """
        Get summary of what degradation will be applied.
        
        Args:
            confidence_score: Confidence score ∈ [0, 1]
        
        Returns:
            Dict describing degradation effects
        """
        mode = self._policy.get_explanation_mode(confidence_score)
        rules = self._rules.get(mode, DEGRADATION_RULES[ExplanationMode.FULL])
        
        return {
            "mode": mode.value,
            "confidence_score": confidence_score,
            "included_sections": {
                "score_breakdown": rules.include_score_breakdown,
                "feature_impacts": rules.include_feature_impacts,
                "specific_recommendations": rules.include_specific_recommendations,
                "career_comparisons": rules.include_career_comparisons,
            },
            "llm_temperature": rules.llm_temperature,
            "has_disclaimer": rules.disclaimer is not None,
        }

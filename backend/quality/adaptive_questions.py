# backend/quality/adaptive_questions.py
"""
HARDENED: Adaptive Question Injection — Section C
=================================================

MICRO-ADAPTIVE PROBING SPECIFICATION:
------------------------------------
PURPOSE: Clarify trait contradictions when confidence < TRIGGER_THRESHOLD
SCOPE: Maximum 2 questions per session (HARD LIMIT)
TIMING: After initial validation, before result display

INVARIANTS:
1. Probing CANNOT affect SIMGRScorer base scores
2. Probing can only reduce confidence penalty (never increase base score)
3. Maximum 2 questions per session
4. Triggered ONLY when confidence < 0.60 AND contradiction_penalty > 0.40

FEATURE MAPPING GUARANTEE:
--------------------------
Adaptive responses are mapped to CLARIFICATION metrics only:
    clarification_engagement: float ∈ [0, 1]
    clarification_consistency: float ∈ [0, 1]

These metrics CANNOT be used by SIMGRScorer (enforced by pipeline order).

Author: Quality Layer Hardening v2
Revision: HARDENED 2026 — Section C
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("quality.adaptive_questions")

# ===========================================================================
# FORMAL CONSTANTS (IMMUTABLE)
# ===========================================================================
MAX_PROBE_QUESTIONS: int = 2  # HARD LIMIT — reduced from 5

# Trigger thresholds (strict)
TRIGGER_CONFIDENCE_THRESHOLD: float = 0.60
TRIGGER_CONTRADICTION_THRESHOLD: float = 0.40

# High confidence bypass
HIGH_CONFIDENCE_SKIP: float = 0.80

# Maximum confidence adjustment from probing
MAX_CONFIDENCE_BOOST: float = 0.10


@dataclass(frozen=True)
class AdaptiveQuestionConfig:
    """
    HARDENED configuration for adaptive questioning.
    
    CONSTRAINTS:
        - max_additional_questions: 2 (HARD LIMIT)
        - Cannot affect base scoring
        - Only for confidence adjustment
    """
    max_additional_questions: int = MAX_PROBE_QUESTIONS
    trigger_confidence_threshold: float = TRIGGER_CONFIDENCE_THRESHOLD
    trigger_contradiction_threshold: float = TRIGGER_CONTRADICTION_THRESHOLD
    high_confidence_skip: float = HIGH_CONFIDENCE_SKIP
    max_confidence_boost: float = MAX_CONFIDENCE_BOOST
    
    def __post_init__(self):
        assert self.max_additional_questions <= MAX_PROBE_QUESTIONS, \
            f"Max questions cannot exceed {MAX_PROBE_QUESTIONS}"


@dataclass(frozen=True)
class AdaptiveQuestion:
    """IMMUTABLE adaptive question."""
    id: str
    text: str
    question_type: str  # "likert_7" | "multiple_choice"
    targets: Tuple[str, ...]
    options: Optional[Tuple[str, ...]] = None
    anchors: Optional[Tuple[str, str]] = None
    category: str = "clarification"


# ===========================================================================
# QUESTION BANK (REDUCED TO ESSENTIALS)
# ===========================================================================
CLARIFICATION_QUESTIONS: Tuple[AdaptiveQuestion, ...] = (
    AdaptiveQuestion(
        id="clarify_work_style",
        text="To help us better understand: Do you prefer working independently or collaboratively?",
        question_type="likert_7",
        targets=("work_alone_pref", "team_collab_pref"),
        anchors=("Strongly prefer alone", "Strongly prefer with others"),
        category="clarification",
    ),
    AdaptiveQuestion(
        id="clarify_decision_style",
        text="How do you typically approach decisions?",
        question_type="multiple_choice",
        targets=("detail_planning", "spontaneous_decision"),
        options=(
            "Careful analysis and planning",
            "Quick intuition",
            "Mix of both depending on context",
        ),
        category="clarification",
    ),
)


class AdaptiveQuestionInjector:
    """
    HARDENED Adaptive Question Injector.
    
    INVARIANTS:
        1. Max 2 questions per session (HARD LIMIT)
        2. Cannot affect base scoring
        3. Only clarification questions (no speed/uniformity)
    """
    
    def __init__(
        self,
        config: Optional[AdaptiveQuestionConfig] = None,
        question_bank: Optional[Tuple[AdaptiveQuestion, ...]] = None,
    ):
        self._config = config or AdaptiveQuestionConfig()
        self._question_bank = question_bank or CLARIFICATION_QUESTIONS
        logger.debug("AdaptiveQuestionInjector (HARDENED) initialized")
    
    def select_questions(
        self,
        confidence_breakdown: Dict[str, float],
    ) -> List[AdaptiveQuestion]:
        """
        Select clarification questions.
        
        GUARANTEE: Returns at most MAX_PROBE_QUESTIONS (2)
        
        TRIGGER: Only contradiction_penalty > threshold
        """
        contradiction_penalty = confidence_breakdown.get("contradiction_penalty", 0.0)
        
        if contradiction_penalty <= self._config.trigger_contradiction_threshold:
            logger.debug(f"No probing: contradiction={contradiction_penalty:.3f} <= threshold")
            return []
        
        # Select questions (max 2)
        selected = list(self._question_bank[:MAX_PROBE_QUESTIONS])
        logger.info(f"Selected {len(selected)} clarification questions")
        return selected
    
    def questions_to_dict(self, questions: List[AdaptiveQuestion]) -> List[Dict[str, Any]]:
        """Convert to serializable format."""
        result = []
        for q in questions:
            item = {
                "id": q.id,
                "text": q.text,
                "type": q.question_type,
                "category": q.category,
            }
            if q.options:
                item["options"] = list(q.options)
            if q.anchors:
                item["anchors"] = {"low": q.anchors[0], "high": q.anchors[1]}
            result.append(item)
        return result
    
    def compute_confidence_adjustment(
        self,
        adaptive_responses: List[Dict[str, Any]],
        original_confidence: float,
    ) -> float:
        """
        Compute confidence adjustment from clarification responses.
        
        GUARANTEE:
            - adjustment ∈ [0, MAX_CONFIDENCE_BOOST]
            - Cannot reduce confidence
            - new_confidence ∈ [original, min(1.0, original + MAX_CONFIDENCE_BOOST)]
        
        NON-INTERFERENCE:
            This adjustment is applied to confidence only.
            SIMGRScorer base_score is FROZEN before this runs.
        """
        if not adaptive_responses:
            return original_confidence
        
        answered = [r for r in adaptive_responses if r.get("answered", False)]
        
        if not answered:
            return original_confidence
        
        # Engagement score: proportion answered
        engagement = len(answered) / min(len(adaptive_responses), MAX_PROBE_QUESTIONS)
        
        # Consistency score
        consistency = self._evaluate_consistency(answered)
        
        # Combined score → adjustment
        combined = (engagement + consistency) / 2.0
        adjustment = combined * MAX_CONFIDENCE_BOOST
        adjustment = min(MAX_CONFIDENCE_BOOST, max(0.0, adjustment))
        
        new_confidence = min(1.0, original_confidence + adjustment)
        
        logger.debug(
            f"Confidence: {original_confidence:.3f} → {new_confidence:.3f} "
            f"(engagement={engagement:.2f}, consistency={consistency:.2f})"
        )
        
        return round(new_confidence, 4)
    
    def _evaluate_consistency(self, responses: List[Dict[str, Any]]) -> float:
        """
        Evaluate response consistency.
        
        Returns: score ∈ [0, 1]
        """
        if not responses:
            return 0.0
        
        points = 0.0
        max_points = len(responses)
        
        for r in responses:
            q_type = r.get("type", "")
            value = r.get("value")
            
            if q_type == "likert_7" and isinstance(value, int):
                # Middle values indicate considered response
                if 2 <= value <= 6:
                    points += 1.0
                else:
                    points += 0.5
            elif q_type == "multiple_choice" and value is not None:
                if "not sure" not in str(value).lower():
                    points += 1.0
                else:
                    points += 0.3
        
        return points / max_points if max_points > 0 else 0.0


class AdaptiveQuestionTrigger:
    """
    HARDENED trigger for adaptive questioning.
    
    TRIGGER CONDITION (STRICT AND):
        confidence_score < 0.60 AND contradiction_penalty > 0.40
    
    SKIP CONDITIONS:
        - confidence_score >= 0.80
        - user opted out
        - session already completed probing
    
    NON-INTERFERENCE:
        Trigger decision does not affect base scoring.
    """
    
    def __init__(
        self,
        confidence_threshold: float = TRIGGER_CONFIDENCE_THRESHOLD,
        contradiction_threshold: float = TRIGGER_CONTRADICTION_THRESHOLD,
        high_confidence_skip: float = HIGH_CONFIDENCE_SKIP,
    ):
        self._confidence_threshold = confidence_threshold
        self._contradiction_threshold = contradiction_threshold
        self._high_skip = high_confidence_skip
    
    def should_trigger(
        self,
        confidence_score: float,
        confidence_breakdown: Dict[str, float],
        user_preferences: Optional[Dict[str, bool]] = None,
        session_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        """
        Determine if probing should trigger.
        
        Returns:
            (should_trigger, reason)
        
        GUARANTEE: Trigger decision cannot affect base scoring.
        """
        prefs = user_preferences or {}
        state = session_state or {}
        
        # Skip conditions (checked first)
        if prefs.get("opt_out_adaptive", False):
            return False, "user_opted_out"
        
        if state.get("adaptive_completed", False):
            return False, "already_completed"
        
        if confidence_score >= self._high_skip:
            return False, "confidence_sufficient"
        
        # STRICT TRIGGER: Both conditions must be met
        contradiction = confidence_breakdown.get("contradiction_penalty", 0.0)
        
        below_confidence = confidence_score < self._confidence_threshold
        high_contradiction = contradiction > self._contradiction_threshold
        
        if below_confidence and high_contradiction:
            return True, f"trigger: confidence={confidence_score:.2f}, contradiction={contradiction:.2f}"
        
        return False, "no_trigger"

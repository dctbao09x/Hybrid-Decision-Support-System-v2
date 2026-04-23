# backend/quality/consistency_validator.py
"""
HARDENED: Consistency Validator — Section B Formalization
=========================================================

MATHEMATICAL FOUNDATION:
-----------------------
Let P_i ∈ [0, 1] be the penalty from detector i, where i ∈ {speed, contradiction, uniformity, entropy}
Let W_i ∈ (0, 1) be the weight for detector i, where Σ W_i = 1

Total Penalty:
    P_total = Σ (W_i × P_i)
    
Since each P_i ∈ [0, 1] and Σ W_i = 1:
    P_total ∈ [0, 1]   (convex combination)

Confidence Score:
    C = 1 - P_total
    C ∈ [0, 1]   (guaranteed by P_total bounds)

BOUNDEDNESS PROOF:
-----------------
Given:
    ∀ i: P_i ∈ [0, 1]   (detector guarantee)
    ∀ i: W_i > 0        (positive weights)
    Σ W_i = 1           (normalization)

Then:
    P_total = W_speed × P_speed + W_contradiction × P_contradiction +
              W_uniformity × P_uniformity + W_entropy × P_entropy
              
    min(P_total) = W_speed × 0 + W_contradiction × 0 + W_uniformity × 0 + W_entropy × 0 = 0
    max(P_total) = W_speed × 1 + W_contradiction × 1 + W_uniformity × 1 + W_entropy × 1 = 1
    
    ∴ P_total ∈ [0, 1]  ⟹  C = 1 - P_total ∈ [0, 1]  QED

NON-INTERFERENCE CONTRACT:
-------------------------
INVARIANT: confidence_score CANNOT influence SIMGRScorer base_score
    
Pipeline Order (ENFORCED):
    1. Feature Extraction → features frozen
    2. SIMGRScorer.score(features) → base_score computed
    3. ConsistencyValidator.compute_confidence_score() → confidence computed
    4. confidence used ONLY for: explanation detail, flagging, adaptive probe trigger

Author: Quality Layer Hardening v2
Revision: HARDENED 2026 — Section B
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.quality.detectors import (
    SpeedAnomalyDetector,
    TraitContradictionMatrix,
    LikertUniformityDetector,
    RandomPatternEntropyAnalyzer,
)

logger = logging.getLogger("quality.consistency_validator")

# ===========================================================================
# FORMAL WEIGHT CONSTANTS (IMMUTABLE)
# ===========================================================================
W_SPEED: float = 0.25
W_CONTRADICTION: float = 0.30
W_UNIFORMITY: float = 0.25
W_ENTROPY: float = 0.20

# Compile-time assertion
assert abs(W_SPEED + W_CONTRADICTION + W_UNIFORMITY + W_ENTROPY - 1.0) < 0.0001, \
    "Weights must sum to 1.0"


@dataclass(frozen=True)
class ConfidenceWeights:
    """
    IMMUTABLE weights for confidence aggregation.
    
    CONSTRAINT: speed + contradiction + uniformity + entropy = 1.0
    VERIFIED: at construction time
    """
    speed: float = W_SPEED
    contradiction: float = W_CONTRADICTION
    uniformity: float = W_UNIFORMITY
    entropy: float = W_ENTROPY
    
    def __post_init__(self):
        total = self.speed + self.contradiction + self.uniformity + self.entropy
        assert abs(total - 1.0) < 0.001, f"Weights must sum to 1.0, got {total}"


@dataclass(frozen=True)
class ConsistencyValidationResult:
    """
    IMMUTABLE result of consistency validation.
    
    GUARANTEE: confidence_score ∈ [0.0, 1.0]
    
    NON-INTERFERENCE: This result is computed AFTER base scoring.
    SIMGRScorer has already completed and returned before this exists.
    """
    confidence_score: float
    total_penalty: float
    breakdown: Dict[str, float]
    speed_details: Dict[str, Any] = field(default_factory=dict)
    contradiction_details: Dict[str, Any] = field(default_factory=dict)
    uniformity_details: Dict[str, Any] = field(default_factory=dict)
    entropy_details: Dict[str, Any] = field(default_factory=dict)
    weights_used: Tuple[Tuple[str, float], ...] = ()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "confidence_score": self.confidence_score,
            "total_penalty": self.total_penalty,
            "breakdown": self.breakdown,
            "speed_details": self.speed_details,
            "contradiction_details": self.contradiction_details,
            "uniformity_details": self.uniformity_details,
            "entropy_details": self.entropy_details,
            "weights_used": dict(self.weights_used),
        }


class ConsistencyValidator:
    """
    HARDENED Consistency Validator with formal guarantees.
    
    MATHEMATICAL GUARANTEE:
        confidence_score = 1 - total_penalty
        where total_penalty = Σ (W_i × P_i)
        ∴ confidence_score ∈ [0, 1]
    
    NON-INTERFERENCE PROTOCOL:
        This validator CANNOT modify SIMGRScorer's input features.
        Confidence is computed AFTER base scoring.
    """
    
    DEFAULT_WEIGHTS = ConfidenceWeights()
    
    def __init__(
        self,
        weights: Optional[ConfidenceWeights] = None,
        speed_detector: Optional[SpeedAnomalyDetector] = None,
        contradiction_detector: Optional[TraitContradictionMatrix] = None,
        uniformity_detector: Optional[LikertUniformityDetector] = None,
        entropy_detector: Optional[RandomPatternEntropyAnalyzer] = None,
    ):
        self._weights = weights or self.DEFAULT_WEIGHTS
        self._speed_detector = speed_detector or SpeedAnomalyDetector()
        self._contradiction_detector = contradiction_detector or TraitContradictionMatrix()
        self._uniformity_detector = uniformity_detector or LikertUniformityDetector()
        self._entropy_detector = entropy_detector or RandomPatternEntropyAnalyzer()
        
        logger.info("ConsistencyValidator (HARDENED) initialized")
    
    def validate(
        self,
        response_times_ms: Optional[List[int]] = None,
        likert_responses: Optional[List[int]] = None,
        trait_responses: Optional[Dict[str, int]] = None,
    ) -> ConsistencyValidationResult:
        """
        Run full consistency validation.
        
        GUARANTEE: confidence_score ∈ [0, 1]
        
        NON-INTERFERENCE: This method is called AFTER SIMGRScorer has
        completed base scoring. It cannot affect the base score.
        """
        response_times = response_times_ms or []
        likert = likert_responses or []
        traits = trait_responses or {}
        
        # Run detectors (each returns penalty ∈ [0, 1])
        speed_result = self._speed_detector.detect(response_times)
        contradiction_result = self._contradiction_detector.detect(traits)
        uniformity_result = self._uniformity_detector.detect(likert)
        entropy_result = self._entropy_detector.detect(likert)
        
        # Extract bounded penalties
        p_speed = max(0.0, min(1.0, speed_result.penalty))
        p_contradiction = max(0.0, min(1.0, contradiction_result.penalty))
        p_uniformity = max(0.0, min(1.0, uniformity_result.penalty))
        p_entropy = max(0.0, min(1.0, entropy_result.penalty))
        
        # Weighted aggregation (convex combination → bounded)
        w = self._weights
        total_penalty = (
            w.speed * p_speed +
            w.contradiction * p_contradiction +
            w.uniformity * p_uniformity +
            w.entropy * p_entropy
        )
        
        # CLAMP (defensive, should already be bounded)
        total_penalty = max(0.0, min(1.0, total_penalty))
        confidence_score = 1.0 - total_penalty
        
        logger.info(
            f"Validation complete: confidence={confidence_score:.4f}, "
            f"penalty={total_penalty:.4f}"
        )
        
        return ConsistencyValidationResult(
            confidence_score=round(confidence_score, 4),
            total_penalty=round(total_penalty, 4),
            breakdown={
                "speed_penalty": round(p_speed, 4),
                "contradiction_penalty": round(p_contradiction, 4),
                "uniformity_penalty": round(p_uniformity, 4),
                "entropy_penalty": round(p_entropy, 4),
            },
            speed_details={
                "penalty": p_speed,
                "questions_too_fast": speed_result.questions_too_fast,
                "questions_too_slow": speed_result.questions_too_slow,
                "median_response_ms": speed_result.median_response_ms,
            },
            contradiction_details={
                "penalty": p_contradiction,
                "contradictions_found": contradiction_result.contradictions_found,
                "pairs_analyzed": contradiction_result.pairs_analyzed,
                "coverage_ratio": contradiction_result.coverage_ratio,
            },
            uniformity_details={
                "penalty": p_uniformity,
                "unique_values_used": uniformity_result.unique_values_used,
                "mode_frequency": uniformity_result.mode_frequency,
                "edge_ratio": uniformity_result.edge_ratio,
                "legitimate_extreme_detected": uniformity_result.legitimate_extreme_detected,
            },
            entropy_details={
                "penalty": p_entropy,
                "shannon_entropy": entropy_result.shannon_entropy,
                "entropy_status": entropy_result.entropy_status,
            },
            weights_used=(
                ("speed", w.speed),
                ("contradiction", w.contradiction),
                ("uniformity", w.uniformity),
                ("entropy", w.entropy),
            ),
        )
    
    def compute_confidence_score(
        self,
        response_times_ms: Optional[List[int]] = None,
        likert_responses: Optional[List[int]] = None,
        trait_responses: Optional[Dict[str, int]] = None,
    ) -> float:
        """
        GUARANTEE: returns confidence_score ∈ [0, 1]
        
        NON-INTERFERENCE: Computed AFTER base scoring completes.
        """
        return self.validate(response_times_ms, likert_responses, trait_responses).confidence_score
    
    def get_breakdown(
        self,
        response_times_ms: Optional[List[int]] = None,
        likert_responses: Optional[List[int]] = None,
        trait_responses: Optional[Dict[str, int]] = None,
    ) -> Dict[str, float]:
        """Get penalty breakdown."""
        result = self.validate(response_times_ms, likert_responses, trait_responses)
        return result.breakdown

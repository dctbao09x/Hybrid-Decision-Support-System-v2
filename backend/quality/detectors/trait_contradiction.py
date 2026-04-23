# backend/quality/detectors/trait_contradiction.py
"""
Trait Contradiction Matrix (HARDENED)
=====================================

HARDENING REMEDIATION: Stage 2 - Quality Control Layer
Section A: Validation Logic Correction

FORMAL SPECIFICATION:
━━━━━━━━━━━━━━━━━━━━━
Input Domain: R = {(q_i, v_i)} where q_i ∈ Q (question IDs), v_i ∈ {1,...,7}
Method: Pairwise contradiction detection with formal inverse relationship
Threshold: Tolerance-based with weighted severity
False-Positive Mitigation: Tolerance window, coverage requirement, ambivalent allowance

MATHEMATICAL DEFINITION:
━━━━━━━━━━━━━━━━━━━━━━━━
Let (q_a, q_b) be a contradiction pair with inverse=True.
Let v_a, v_b be responses to q_a, q_b respectively.
Expected inverse: v_b' = (scale_max + 1) - v_a

Contradiction strength:
    S(v_a, v_b) = max(0, |v_b - v_b'| - tolerance) / (scale_max - 1 - tolerance)

Weighted penalty:
    P = Σ(w_i × S_i) / Σ(w_i)  for all analyzed pairs

GUARANTEES:
- PURE FUNCTION: f(R) → penalty ∈ [0,1], no side effects
- DETERMINISTIC: Same input always produces same output
- INDEPENDENT: Does not access or modify scoring weights

DOES NOT AFFECT SCORING - only contributes to confidence calculation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger("quality.detectors.contradiction")


# ═══════════════════════════════════════════════════════════════════════════════
# FORMAL CONTRADICTION MATRIX DEFINITION (HARDENING FIX #2)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ContradictionPair:
    """
    FORMALLY DEFINED contradiction pair.
    
    Mathematical relationship:
        If is_inverse=True: high(q_a) ⟹ low(q_b) expected
        Expected value: v_b' = (scale_max + 1) - v_a
        Contradiction: |v_b - v_b'| > tolerance
    """
    question_a: str
    question_b: str
    weight: float = 0.8                  # w ∈ [0.5, 1.0], contribution weight
    is_inverse: bool = True              # True = inverse relationship expected
    tolerance: int = 2                   # Allowable deviation from expected
    
    def __post_init__(self):
        """HARDENING: Validate constraints."""
        assert 0.5 <= self.weight <= 1.0, f"Weight must be in [0.5, 1.0], got {self.weight}"
        assert self.tolerance >= 0, f"Tolerance must be non-negative, got {self.tolerance}"


@dataclass(frozen=True)
class ContradictionMatrixSpec:
    """
    FORMAL SPECIFICATION of the contradiction matrix.
    
    HARDENING: Immutable, validated, mathematically defined.
    """
    scale_min: int = 1
    scale_max: int = 7
    min_pairs_for_analysis: int = 2      # Minimum pairs needed for reliable detection
    min_coverage_ratio: float = 0.3      # At least 30% of pairs must be analyzable
    ambivalent_center: int = 4           # Middle of scale (ambivalent responses)
    ambivalent_tolerance: int = 1        # Responses within center±1 are ambivalent
    
    # FALSE-POSITIVE MITIGATION: Ambivalent responses get reduced weight
    ambivalent_weight_factor: float = 0.5


@dataclass(frozen=True)
class ContradictionResult:
    """
    IMMUTABLE result of contradiction detection.
    
    HARDENING: Frozen dataclass ensures results cannot be modified.
    """
    penalty: float                       # ∈ [0, 1], GUARANTEED bounded
    contradictions_found: int
    pairs_analyzed: int
    coverage_ratio: float                # Proportion of pairs that could be analyzed
    contradiction_details: Tuple[Dict, ...] = field(default_factory=tuple)  # Immutable


# ═══════════════════════════════════════════════════════════════════════════════
# FORMAL CONTRADICTION MATRIX (12 PAIRS)
# ═══════════════════════════════════════════════════════════════════════════════

FORMAL_CONTRADICTION_PAIRS: Tuple[ContradictionPair, ...] = (
    # Work style contradictions (highest weight - most reliable)
    ContradictionPair("work_alone_pref", "team_collab_pref", weight=0.95, is_inverse=True, tolerance=2),
    ContradictionPair("social_work_pref", "solo_work_pref", weight=0.90, is_inverse=True, tolerance=2),
    
    # Decision-making contradictions
    ContradictionPair("detail_planning", "spontaneous_decision", weight=0.85, is_inverse=True, tolerance=2),
    ContradictionPair("analytical_thinking", "intuitive_only", weight=0.70, is_inverse=True, tolerance=2),
    
    # Technical preference contradictions (very reliable)
    ContradictionPair("math_strength", "avoid_quantitative", weight=1.00, is_inverse=True, tolerance=1),
    ContradictionPair("tech_interest", "tech_avoidance", weight=1.00, is_inverse=True, tolerance=1),
    
    # Creative vs structured
    ContradictionPair("creative_expression", "structured_tasks_only", weight=0.75, is_inverse=True, tolerance=2),
    ContradictionPair("routine_preference", "variety_seeking", weight=0.75, is_inverse=True, tolerance=2),
    
    # Leadership contradictions
    ContradictionPair("leadership_desire", "follower_preference", weight=0.85, is_inverse=True, tolerance=2),
    
    # Risk preference
    ContradictionPair("risk_tolerance", "security_priority", weight=0.80, is_inverse=True, tolerance=2),
    
    # Environment preference (lower weight - less reliable contradiction)
    ContradictionPair("outdoor_preference", "indoor_preference", weight=0.60, is_inverse=True, tolerance=3),
    ContradictionPair("hands_on_pref", "theoretical_pref", weight=0.65, is_inverse=True, tolerance=2),
)


class TraitContradictionMatrix:
    """
    HARDENED Trait Contradiction Detector.
    
    MATHEMATICAL SPECIFICATION:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━
    Given responses R = {(q_i, v_i)} and contradiction pairs P = {(q_a, q_b, w, inverse, tol)}:
    
    For each pair p ∈ P where both q_a, q_b ∈ R:
        v_a, v_b = responses
        v_expected = (scale_max + 1) - v_a  (if inverse=True)
        deviation = |v_b - v_expected|
        
        if deviation > tolerance:
            strength = (deviation - tolerance) / (scale_max - 1 - tolerance)
            strength = clamp(strength, 0, 1)
        else:
            strength = 0
        
        contribution = w × strength × ambivalent_factor(v_a, v_b)
    
    penalty = Σ(contribution) / Σ(w)  (for analyzed pairs only)
    penalty = clamp(penalty, 0, 1)
    
    GUARANTEES:
    - Pure function
    - Deterministic
    - Output bounded to [0, 1]
    - Independent of scoring weights
    """
    
    def __init__(
        self,
        pairs: Optional[Tuple[ContradictionPair, ...]] = None,
        spec: Optional[ContradictionMatrixSpec] = None,
    ):
        """Initialize with formal matrix specification."""
        self._pairs: Tuple[ContradictionPair, ...] = pairs or FORMAL_CONTRADICTION_PAIRS
        self._spec: ContradictionMatrixSpec = spec or ContradictionMatrixSpec()
        self._validate_pairs()
        logger.debug(f"TraitContradictionMatrix (HARDENED) initialized with {len(self._pairs)} pairs")
    
    def _validate_pairs(self) -> None:
        """HARDENING: Validate all pairs at initialization."""
        for pair in self._pairs:
            assert pair.question_a != pair.question_b, "Pair cannot reference same question"
            assert 0.5 <= pair.weight <= 1.0, f"Invalid weight: {pair.weight}"
    
    def detect(self, responses: Dict[str, int]) -> ContradictionResult:
        """
        Detect contradictions using formal matrix.
        
        FORMAL DEFINITION:
            Input: R: Q → {1,...,7} (partial function from questions to responses)
            Output: ContradictionResult with penalty ∈ [0, 1]
        
        FALSE-POSITIVE MITIGATION:
            1. Tolerance window allows minor deviations
            2. Ambivalent responses (center of scale) get reduced weight
            3. Insufficient coverage returns zero penalty
        
        CRITICAL: Penalty is used ONLY for confidence, not scoring.
        """
        if not responses:
            return self._create_result(0.0, 0, 0, 0.0, ())
        
        # Validate and clamp all responses to valid range
        valid_responses = self._validate_responses(responses)
        
        contradictions: List[Dict] = []
        total_weight = 0.0
        contradiction_weight = 0.0
        pairs_analyzed = 0
        
        for pair in self._pairs:
            # Check if both questions are answered
            if pair.question_a not in valid_responses or pair.question_b not in valid_responses:
                continue
            
            pairs_analyzed += 1
            v_a = valid_responses[pair.question_a]
            v_b = valid_responses[pair.question_b]
            
            # Calculate ambivalent factor (FALSE-POSITIVE MITIGATION)
            ambivalent_factor = self._calculate_ambivalent_factor(v_a, v_b)
            
            # Effective weight for this pair
            effective_weight = pair.weight * ambivalent_factor
            total_weight += effective_weight
            
            # Check for contradiction
            is_contradiction, strength = self._check_contradiction(v_a, v_b, pair)
            
            if is_contradiction:
                contribution = effective_weight * strength
                contradiction_weight += contribution
                contradictions.append({
                    "pair": (pair.question_a, pair.question_b),
                    "values": (v_a, v_b),
                    "weight": pair.weight,
                    "effective_weight": round(effective_weight, 4),
                    "strength": round(strength, 4),
                    "contribution": round(contribution, 4),
                })
        
        # Calculate coverage ratio
        coverage_ratio = pairs_analyzed / len(self._pairs) if self._pairs else 0.0
        
        # FALSE-POSITIVE MITIGATION: Require minimum coverage
        if coverage_ratio < self._spec.min_coverage_ratio or pairs_analyzed < self._spec.min_pairs_for_analysis:
            return self._create_result(0.0, 0, pairs_analyzed, coverage_ratio, ())
        
        # Calculate final penalty (BOUNDED)
        if total_weight > 0:
            penalty = contradiction_weight / total_weight
        else:
            penalty = 0.0
        
        # HARDENING: Explicit clamping
        penalty = self._clamp(penalty, 0.0, 1.0)
        
        return self._create_result(
            penalty=round(penalty, 4),
            contradictions_found=len(contradictions),
            pairs_analyzed=pairs_analyzed,
            coverage_ratio=round(coverage_ratio, 4),
            contradiction_details=tuple(contradictions),
        )
    
    def _validate_responses(self, responses: Dict[str, int]) -> Dict[str, int]:
        """Validate and clamp responses to valid range."""
        return {
            q: self._clamp(int(v), self._spec.scale_min, self._spec.scale_max)
            for q, v in responses.items()
            if isinstance(v, (int, float))
        }
    
    def _calculate_ambivalent_factor(self, v_a: int, v_b: int) -> float:
        """
        Calculate ambivalent reduction factor.
        
        FALSE-POSITIVE MITIGATION: Ambivalent responses (near center) are
        less reliable indicators of contradiction.
        """
        center = self._spec.ambivalent_center
        tol = self._spec.ambivalent_tolerance
        
        a_ambivalent = abs(v_a - center) <= tol
        b_ambivalent = abs(v_b - center) <= tol
        
        if a_ambivalent and b_ambivalent:
            return self._spec.ambivalent_weight_factor ** 2
        elif a_ambivalent or b_ambivalent:
            return self._spec.ambivalent_weight_factor
        else:
            return 1.0
    
    def _check_contradiction(
        self,
        v_a: int,
        v_b: int,
        pair: ContradictionPair,
    ) -> Tuple[bool, float]:
        """
        FORMAL CONTRADICTION CHECK.
        
        For inverse pairs:
            expected_b = (scale_max + 1) - v_a
            deviation = |v_b - expected_b|
            strength = max(0, deviation - tolerance) / (scale_max - 1 - tolerance)
        """
        if pair.is_inverse:
            expected_b = (self._spec.scale_max + 1) - v_a
            deviation = abs(v_b - expected_b)
        else:
            # For non-inverse pairs, expect similar values
            deviation = abs(v_a - v_b)
        
        if deviation <= pair.tolerance:
            return False, 0.0
        
        # Calculate strength (normalized to [0, 1])
        max_deviation = self._spec.scale_max - self._spec.scale_min
        denominator = max_deviation - pair.tolerance
        
        if denominator <= 0:
            return True, 1.0
        
        strength = (deviation - pair.tolerance) / denominator
        strength = self._clamp(strength, 0.0, 1.0)
        
        return True, strength
    
    @staticmethod
    def _clamp(value: float, min_val: float, max_val: float) -> float:
        """Clamp value to [min_val, max_val]. PURE FUNCTION."""
        return max(min_val, min(max_val, value))
    
    def _create_result(self, penalty: float, contradictions_found: int,
                       pairs_analyzed: int, coverage_ratio: float,
                       contradiction_details: Tuple[Dict, ...]) -> ContradictionResult:
        """Create immutable result."""
        return ContradictionResult(
            penalty=penalty,
            contradictions_found=contradictions_found,
            pairs_analyzed=pairs_analyzed,
            coverage_ratio=coverage_ratio,
            contradiction_details=contradiction_details,
        )
    
    def calculate_penalty(self, responses: Dict[str, int]) -> float:
        """
        Pure function to calculate penalty.
        
        MATHEMATICAL GUARANTEE:
            ∀ R: calculate_penalty(R) ∈ [0, 1]
        """
        result = self.detect(responses)
        return result.penalty

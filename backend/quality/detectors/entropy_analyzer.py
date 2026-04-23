# backend/quality/detectors/entropy_analyzer.py
"""
HARDENED: Random Pattern Entropy Analyzer
=========================================

MATHEMATICAL FOUNDATION:
- Shannon Entropy: H(X) = -Σ p(x) log₂ p(x)
- For k-point scale: H_max = log₂(k)
- 7-point Likert: H_max = log₂(7) ≈ 2.807 bits

BOUNDEDNESS PROOF:
- H ∈ [0, H_max] by information theory
- penalty = f(H) where f: [0, H_max] → [0, 1]
- Output is mathematically guaranteed bounded

FALSE-POSITIVE MITIGATION:
- Normal zone: entropy ∈ [H_min_expected, H_max_expected] → penalty = 0
- Low zone: entropy < H_min_expected → linear penalty
- High zone: entropy > H_max_expected → linear penalty
- Zone boundaries are configurable with defaults from empirical data

NON-INTERFERENCE:
- DOES NOT AFFECT SCORING
- Only contributes to confidence calculation
- SIMGRScorer receives features BEFORE this analysis runs

Author: Quality Layer Hardening v2
Revision: HARDENED 2026
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("quality.detectors.entropy")

# ===========================================================================
# FORMAL CONSTANTS (IMMUTABLE)
# ===========================================================================
SCALE_POINTS: int = 7
MAX_ENTROPY_7PT: float = math.log2(SCALE_POINTS)  # ≈ 2.807

# Expected entropy zone (EMPIRICAL from calibration study)
ENTROPY_NORMAL_MIN: float = 1.5
ENTROPY_NORMAL_MAX: float = 2.5

# Weight asymmetry: random clicking is worse than over-consistency
WEIGHT_LOW_PENALTY: float = 0.35   # Too predictable
WEIGHT_HIGH_PENALTY: float = 0.65  # Too random

# ===========================================================================
# CONFIGURATION
# ===========================================================================
@dataclass(frozen=True)
class EntropyConfig:
    """
    HARDENED configuration for entropy analysis.
    
    BOUNDS:
    - entropy_min_expected ∈ [0, entropy_max_expected]
    - entropy_max_expected ∈ [entropy_min_expected, max_entropy_7point]
    """
    entropy_min_expected: float = ENTROPY_NORMAL_MIN
    entropy_max_expected: float = ENTROPY_NORMAL_MAX
    max_entropy_7point: float = MAX_ENTROPY_7PT
    min_responses_for_analysis: int = 10
    scale_min: int = 1
    scale_max: int = SCALE_POINTS
    
    def __post_init__(self):
        assert 0 <= self.entropy_min_expected <= self.entropy_max_expected
        assert self.entropy_max_expected <= self.max_entropy_7point


@dataclass(frozen=True)
class EntropyResult:
    """
    IMMUTABLE result of entropy analysis.
    
    GUARANTEE: penalty ∈ [0, 1]
    """
    penalty: float
    shannon_entropy: float
    normalized_entropy: float
    entropy_status: str  # "low" | "normal" | "high" | "insufficient"
    low_zone_penalty: float = 0.0
    high_zone_penalty: float = 0.0
    value_distribution: Dict[int, float] = field(default_factory=dict)
    details: Dict[str, any] = field(default_factory=dict)


class RandomPatternEntropyAnalyzer:
    """
    HARDENED Entropy Analyzer with formal bounding.
    
    MATHEMATICAL GUARANTEE:
        penalty ∈ [0, 1] for all valid inputs
    
    PENALTY FORMULA (piecewise linear):
        If H < H_min: penalty = W_low * (H_min - H) / H_min
        If H > H_max: penalty = W_high * (H - H_max) / (H_max_possible - H_max)
        Else: penalty = 0
    
    Where:
        W_low = 0.35, W_high = 0.65
        H_min = 1.5, H_max = 2.5, H_max_possible = 2.807
    """
    
    DEFAULT_CONFIG = EntropyConfig()
    
    def __init__(self, config: Optional[EntropyConfig] = None):
        self._config = config or self.DEFAULT_CONFIG
        logger.debug("RandomPatternEntropyAnalyzer (HARDENED) initialized")
    
    def detect(self, responses: List[int]) -> EntropyResult:
        """
        Analyze entropy with BOUNDED output.
        
        GUARANTEE: penalty ∈ [0, 1]
        """
        cfg = self._config
        total = len(responses)
        
        if total < cfg.min_responses_for_analysis:
            return self._empty_result("insufficient_data")
        
        valid = [r for r in responses if cfg.scale_min <= r <= cfg.scale_max]
        
        if len(valid) < cfg.min_responses_for_analysis:
            return self._empty_result("insufficient_valid")
        
        # Distribution calculation
        counter = Counter(valid)
        distribution = {k: v / len(valid) for k, v in counter.items()}
        
        # Shannon entropy: H(X) = -Σ p(x) log₂ p(x)
        entropy = self._shannon_entropy(distribution.values())
        normalized = entropy / cfg.max_entropy_7point
        
        # Bounded penalty calculation
        low_penalty, high_penalty, status = self._calculate_zone_penalties(entropy)
        
        # Weighted aggregate
        total_penalty = WEIGHT_LOW_PENALTY * low_penalty + WEIGHT_HIGH_PENALTY * high_penalty
        total_penalty = max(0.0, min(1.0, total_penalty))  # CLAMP
        
        return EntropyResult(
            penalty=round(total_penalty, 4),
            shannon_entropy=round(entropy, 4),
            normalized_entropy=round(normalized, 4),
            entropy_status=status,
            low_zone_penalty=round(low_penalty, 4),
            high_zone_penalty=round(high_penalty, 4),
            value_distribution=distribution,
            details={
                "w_low": WEIGHT_LOW_PENALTY,
                "w_high": WEIGHT_HIGH_PENALTY,
                "zone_min": cfg.entropy_min_expected,
                "zone_max": cfg.entropy_max_expected,
                "max_possible": cfg.max_entropy_7point,
            },
        )
    
    def _empty_result(self, reason: str) -> EntropyResult:
        return EntropyResult(
            penalty=0.0,
            shannon_entropy=0.0,
            normalized_entropy=0.0,
            entropy_status=reason,
            value_distribution={},
            details={"reason": reason},
        )
    
    def _calculate_zone_penalties(self, h: float) -> Tuple[float, float, str]:
        """
        Calculate bounded zone penalties.
        
        Returns:
            (low_penalty, high_penalty, status)
        
        GUARANTEE: both penalties ∈ [0, 1]
        """
        cfg = self._config
        h_min = cfg.entropy_min_expected
        h_max = cfg.entropy_max_expected
        h_possible = cfg.max_entropy_7point
        
        if h < h_min:
            # Too predictable (gaming/straight-lining)
            denom = h_min if h_min > 0 else 1.0
            low_p = min(1.0, (h_min - h) / denom)
            return (low_p, 0.0, "low")
        
        if h > h_max:
            # Too random (disengaged clicking)
            denom = h_possible - h_max if (h_possible - h_max) > 0.01 else 0.307
            high_p = min(1.0, (h - h_max) / denom)
            return (0.0, high_p, "high")
        
        # Normal zone
        return (0.0, 0.0, "normal")
    
    @staticmethod
    def _shannon_entropy(probabilities) -> float:
        """
        Shannon entropy: H(X) = -Σ p(x) log₂ p(x)
        
        BOUND: returns value ∈ [0, log₂(k)] where k = support size
        """
        entropy = 0.0
        for p in probabilities:
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy
    
    def calculate_penalty(self, responses: List[int]) -> float:
        """GUARANTEE: returns penalty ∈ [0, 1]."""
        return self.detect(responses).penalty

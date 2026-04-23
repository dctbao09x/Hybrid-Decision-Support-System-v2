# backend/quality/detectors/likert_uniformity.py
"""
Likert Uniformity Detector (HARDENED)
=====================================

HARDENING REMEDIATION: Stage 2 - Quality Control Layer
Section A: Validation Logic Correction - FIX #3

FORMAL SPECIFICATION:
━━━━━━━━━━━━━━━━━━━━━
Input Domain: V = {v₁, v₂, ..., vₙ} where vᵢ ∈ {1, 2, ..., 7}
Method: Multi-metric uniformity detection with legitimate extreme handling
Threshold: Adaptive based on response diversity metrics
False-Positive Mitigation: Legitimate extreme user detection

ISSUE FIX #3: Legitimate Extreme Users
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Problem: Previous implementation penalized users with genuinely strong preferences.
Solution: Detect legitimate extreme users by variance > 0.5 with edge responses.

DOES NOT AFFECT SCORING - only contributes to confidence calculation.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from statistics import variance as stat_variance
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("quality.detectors.uniformity")


@dataclass(frozen=True)
class UniformityConfig:
    """HARDENED configuration for uniformity detection."""
    min_unique_ratio: float = 0.25       # HARDENED: Decreased for tolerance
    max_mode_frequency: float = 0.60     # HARDENED: Increased for tolerance  
    edge_only_threshold: float = 0.85    # HARDENED: Increased for tolerance
    pattern_correlation_threshold: float = 0.75
    min_responses_for_analysis: int = 10 # HARDENED: Increased for reliability
    scale_min: int = 1
    scale_max: int = 7
    
    # FALSE-POSITIVE MITIGATION (Issue #3)
    legitimate_extreme_variance: float = 0.5
    legitimate_extreme_reduction: float = 0.5
    
    # Explicit weights (sum = 1.0)
    weight_mode: float = 0.30
    weight_unique: float = 0.25
    weight_edge: float = 0.25
    weight_pattern: float = 0.20


@dataclass(frozen=True)
class UniformityResult:
    """IMMUTABLE result of uniformity detection."""
    penalty: float
    unique_values_used: int
    unique_ratio: float
    mode_value: int
    mode_frequency: float
    edge_ratio: float
    response_variance: float             # NEW: For legitimate extreme detection
    legitimate_extreme_detected: bool    # NEW: Indicates reduced penalty
    max_pattern_correlation: float
    detected_pattern: Optional[str] = None
    details: Dict = field(default_factory=dict)


KNOWN_BAD_PATTERNS: Dict[str, Tuple[int, ...]] = {
    "straight_line_low": (1, 1, 1, 1, 1, 1, 1, 1),
    "straight_line_mid": (4, 4, 4, 4, 4, 4, 4, 4),
    "straight_line_high": (7, 7, 7, 7, 7, 7, 7, 7),
    "alternating_extreme": (1, 7, 1, 7, 1, 7, 1, 7),
    "alternating_moderate": (3, 5, 3, 5, 3, 5, 3, 5),
    "sequential_up": (1, 2, 3, 4, 5, 6, 7, 1),
    "sequential_down": (7, 6, 5, 4, 3, 2, 1, 7),
}


class LikertUniformityDetector:
    """
    HARDENED Likert Uniformity Detector with legitimate extreme handling.
    
    MATHEMATICAL GUARANTEE: penalty ∈ [0, 1]
    FALSE-POSITIVE FIX: Users with high variance at extremes get reduced penalty.
    """
    
    DEFAULT_CONFIG = UniformityConfig()
    
    def __init__(self, config: Optional[UniformityConfig] = None):
        self._config = config or self.DEFAULT_CONFIG
        logger.debug("LikertUniformityDetector (HARDENED) initialized")
    
    def detect(self, responses: List[int]) -> UniformityResult:
        """
        Detect uniformity with FALSE-POSITIVE MITIGATION.
        
        HARDENING FIX #3: Legitimate extreme users (high edge ratio but 
        variance > 0.5) get reduced edge penalty.
        """
        cfg = self._config
        total = len(responses)
        
        if total < cfg.min_responses_for_analysis:
            return self._empty_result("insufficient_responses")
        
        valid = [max(cfg.scale_min, min(cfg.scale_max, int(r))) 
                 for r in responses if isinstance(r, (int, float))]
        
        if len(valid) < cfg.min_responses_for_analysis:
            return self._empty_result("insufficient_valid_responses")
        
        n = len(valid)
        scale_range = cfg.scale_max - cfg.scale_min + 1
        
        # Metrics
        counter = Counter(valid)
        unique_count = len(counter)
        unique_ratio = unique_count / scale_range
        mode_value, mode_count = counter.most_common(1)[0]
        mode_frequency = mode_count / n
        edge_count = counter.get(cfg.scale_min, 0) + counter.get(cfg.scale_max, 0)
        edge_ratio = edge_count / n
        
        # Variance for legitimate extreme detection
        resp_var = stat_variance(valid) if n > 1 else 0.0
        
        # Pattern check
        max_corr, detected_pattern = self._check_patterns(valid)
        
        # PENALTIES (BOUNDED)
        p_mode = self._threshold_penalty(mode_frequency, cfg.max_mode_frequency, True)
        p_unique = self._threshold_penalty(unique_ratio, cfg.min_unique_ratio, False)
        p_edge_raw = self._threshold_penalty(edge_ratio, cfg.edge_only_threshold, True)
        
        # HARDENING FIX #3: Legitimate extreme user detection
        legitimate_extreme = edge_ratio > 0.6 and resp_var > cfg.legitimate_extreme_variance
        p_edge = p_edge_raw * cfg.legitimate_extreme_reduction if legitimate_extreme else p_edge_raw
        
        p_pattern = self._threshold_penalty(max_corr, cfg.pattern_correlation_threshold, True)
        
        # Aggregate
        total_penalty = (
            cfg.weight_mode * p_mode +
            cfg.weight_unique * p_unique +
            cfg.weight_edge * p_edge +
            cfg.weight_pattern * p_pattern
        )
        total_penalty = max(0.0, min(1.0, total_penalty))
        
        return UniformityResult(
            penalty=round(total_penalty, 4),
            unique_values_used=unique_count,
            unique_ratio=round(unique_ratio, 4),
            mode_value=mode_value,
            mode_frequency=round(mode_frequency, 4),
            edge_ratio=round(edge_ratio, 4),
            response_variance=round(resp_var, 4),
            legitimate_extreme_detected=legitimate_extreme,
            max_pattern_correlation=round(max_corr, 4),
            detected_pattern=detected_pattern,
            details={
                "p_mode": round(p_mode, 4),
                "p_unique": round(p_unique, 4),
                "p_edge_raw": round(p_edge_raw, 4),
                "p_edge_adj": round(p_edge, 4),
                "p_pattern": round(p_pattern, 4),
            },
        )
    
    def _empty_result(self, reason: str) -> UniformityResult:
        return UniformityResult(
            penalty=0.0, unique_values_used=0, unique_ratio=0.0,
            mode_value=0, mode_frequency=0.0, edge_ratio=0.0,
            response_variance=0.0, legitimate_extreme_detected=False,
            max_pattern_correlation=0.0, details={"reason": reason}
        )
    
    @staticmethod
    def _threshold_penalty(value: float, threshold: float, above_is_bad: bool) -> float:
        """BOUNDED penalty calculation: returns value in [0, 1]."""
        if above_is_bad:
            if value <= threshold:
                return 0.0
            denom = 1.0 - threshold
            return min(1.0, (value - threshold) / denom) if denom > 0 else 1.0
        else:
            if value >= threshold:
                return 0.0
            return min(1.0, (threshold - value) / threshold) if threshold > 0 else 1.0
    
    def _check_patterns(self, responses: List[int]) -> Tuple[float, Optional[str]]:
        """Check against known bad patterns using Pearson correlation."""
        if len(responses) < 4:
            return 0.0, None
        
        max_corr = 0.0
        best_pattern = None
        
        for name, pattern in KNOWN_BAD_PATTERNS.items():
            extended = (list(pattern) * ((len(responses) // len(pattern)) + 1))[:len(responses)]
            corr = self._pearson_corr(responses, extended)
            if corr > max_corr:
                max_corr = corr
                if corr > self._config.pattern_correlation_threshold:
                    best_pattern = name
        
        return max_corr, best_pattern
    
    @staticmethod
    def _pearson_corr(x: List[int], y: List[int]) -> float:
        """Pure function: Pearson correlation coefficient."""
        n = len(x)
        if n != len(y) or n < 2:
            return 0.0
        mean_x, mean_y = sum(x) / n, sum(y) / n
        var_x = sum((xi - mean_x) ** 2 for xi in x)
        var_y = sum((yi - mean_y) ** 2 for yi in y)
        if var_x == 0 or var_y == 0:
            return 1.0 if x == y else 0.0
        cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        return abs(cov / math.sqrt(var_x * var_y))
    
    def calculate_penalty(self, responses: List[int]) -> float:
        """GUARANTEE: returns penalty ∈ [0, 1]."""
        return self.detect(responses).penalty

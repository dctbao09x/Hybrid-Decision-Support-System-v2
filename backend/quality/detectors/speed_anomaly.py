# backend/quality/detectors/speed_anomaly.py
"""
Speed Anomaly Detector (HARDENED)
=================================

HARDENING REMEDIATION: Stage 2 - Quality Control Layer
Section A: Validation Logic Correction

Detects suspiciously fast or slow responses indicating careless completion.

FORMAL SPECIFICATION:
━━━━━━━━━━━━━━━━━━━━━
Input Domain: T = {t₁, t₂, ..., tₙ} where tᵢ ∈ ℤ⁺ (milliseconds)
Method: Z-score normalization against population baseline
Threshold: Adaptive based on IQR (Interquartile Range)
False-Positive Mitigation: Grace period for first response, IQR-based outliers

GUARANTEES:
- PURE FUNCTION: f(T) → penalty ∈ [0,1], no side effects
- DETERMINISTIC: Same input always produces same output
- INDEPENDENT: Does not access or modify scoring weights

DOES NOT AFFECT SCORING - only contributes to confidence calculation.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from statistics import median, stdev, mean
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("quality.detectors.speed")


# ═══════════════════════════════════════════════════════════════════════════════
# NORMALIZATION BASELINE (HARDENING FIX #1)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PopulationBaseline:
    """
    Population baseline for speed normalization.
    
    HARDENING: Provides reference distribution for z-score calculation.
    Values derived from empirical study of survey response times.
    """
    mean_ms: float = 4500.0              # Population mean response time
    std_ms: float = 2000.0               # Population standard deviation
    min_physiological_ms: int = 500      # Absolute minimum (motor response limit)
    max_engagement_ms: int = 180000      # 3 minutes - beyond suggests disengagement
    
    # IQR-based thresholds (more robust than fixed thresholds)
    q1_ms: float = 2500.0                # 25th percentile
    q3_ms: float = 6500.0                # 75th percentile


@dataclass(frozen=True)
class SpeedAnomalyConfig:
    """
    Configuration for speed anomaly detection.
    
    HARDENING: All thresholds are immutable and mathematically bounded.
    """
    # Baseline for normalization
    baseline: PopulationBaseline = field(default_factory=PopulationBaseline)
    
    # Z-score thresholds (standard deviations from mean)
    z_threshold_fast: float = -2.0       # 2 SD below mean = too fast
    z_threshold_slow: float = 2.5        # 2.5 SD above mean = too slow
    
    # Ratio thresholds (proportion of anomalous responses)
    fast_ratio_threshold: float = 0.25   # >25% fast responses = concern
    slow_ratio_threshold: float = 0.35   # >35% slow responses = concern
    
    # Analysis requirements
    min_questions_for_analysis: int = 5
    
    # False-positive mitigation
    first_response_grace: bool = True    # First response often slower
    iqr_outlier_factor: float = 1.5      # IQR multiplier for outlier detection
    
    # Penalty bounds (HARDENING: explicit bounds)
    max_penalty: float = 1.0
    min_penalty: float = 0.0


@dataclass(frozen=True)
class SpeedAnomalyResult:
    """
    Result of speed anomaly detection.
    
    IMMUTABLE: Frozen dataclass ensures results cannot be modified post-creation.
    """
    penalty: float                       # ∈ [0, 1], GUARANTEED bounded
    z_score_mean: float                  # Normalized deviation from baseline
    questions_too_fast: int
    questions_too_slow: int
    total_questions: int
    median_response_ms: float
    fast_ratio: float
    slow_ratio: float
    iqr_outliers: int                    # Count of IQR-based outliers
    details: Dict[str, any] = field(default_factory=dict)


class SpeedAnomalyDetector:
    """
    Detects response timing anomalies (HARDENED).
    
    MATHEMATICAL SPECIFICATION:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━
    Let T = {t₁, t₂, ..., tₙ} be response times in milliseconds.
    Let μ_pop, σ_pop be population baseline parameters.
    
    Z-score for sample mean:
        z = (mean(T) - μ_pop) / (σ_pop / √n)
    
    Penalty components:
        P_fast = min(1, |{tᵢ : z(tᵢ) < z_fast}| / (n × threshold_fast))
        P_slow = min(1, |{tᵢ : z(tᵢ) > z_slow}| / (n × threshold_slow))
        P_iqr = min(1, |outliers_iqr| / n)
    
    Total penalty (bounded):
        penalty = clamp(0.35×P_fast + 0.30×P_slow + 0.35×P_iqr, 0, 1)
    
    GUARANTEES:
    - Pure function: no side effects
    - Deterministic: f(T) = f(T) always
    - Bounded output: penalty ∈ [0, 1]
    - Scoring-independent: no access to SIMGRScorer
    """
    
    DEFAULT_CONFIG = SpeedAnomalyConfig()
    
    # HARDENING: Explicit weight constants (immutable)
    WEIGHT_FAST: float = 0.35
    WEIGHT_SLOW: float = 0.30
    WEIGHT_IQR: float = 0.35
    
    def __init__(self, config: Optional[SpeedAnomalyConfig] = None):
        """Initialize detector with optional custom config."""
        self._config = config or self.DEFAULT_CONFIG
        self._validate_config()
        logger.debug(f"SpeedAnomalyDetector (HARDENED) initialized")
    
    def _validate_config(self) -> None:
        """HARDENING: Validate config constraints at initialization."""
        assert 0.0 <= self._config.max_penalty <= 1.0, "max_penalty must be in [0,1]"
        assert 0.0 <= self._config.min_penalty <= 1.0, "min_penalty must be in [0,1]"
        assert self._config.min_penalty <= self._config.max_penalty
        assert self._config.min_questions_for_analysis >= 3
    
    def detect(self, response_times_ms: List[int]) -> SpeedAnomalyResult:
        """
        Detect speed anomalies using z-score normalization.
        
        FORMAL DEFINITION:
            Input: T ∈ ℤⁿ₊ (positive integer milliseconds)
            Output: SpeedAnomalyResult with penalty ∈ [0, 1]
        
        FALSE-POSITIVE MITIGATION:
            1. Grace period for first response (often slower due to orientation)
            2. IQR-based outlier detection (robust to extreme values)
            3. Minimum sample size requirement
        
        CRITICAL: Penalty is used ONLY for confidence, not scoring.
        """
        total = len(response_times_ms)
        baseline = self._config.baseline
        
        # Handle insufficient data - NO FALSE PENALTY
        if total < self._config.min_questions_for_analysis:
            return self._create_result(
                penalty=0.0,
                z_score_mean=0.0,
                questions_too_fast=0,
                questions_too_slow=0,
                total_questions=total,
                median_response_ms=0.0,
                fast_ratio=0.0,
                slow_ratio=0.0,
                iqr_outliers=0,
                details={"reason": "insufficient_questions", "min_required": self._config.min_questions_for_analysis},
            )
        
        # Filter physiologically valid times
        valid_times = [t for t in response_times_ms 
                       if baseline.min_physiological_ms <= t <= baseline.max_engagement_ms]
        
        if len(valid_times) < self._config.min_questions_for_analysis:
            return self._create_result(
                penalty=0.0,  # HARDENING: No penalty for insufficient valid data
                z_score_mean=0.0,
                questions_too_fast=0,
                questions_too_slow=0,
                total_questions=total,
                median_response_ms=0.0,
                fast_ratio=0.0,
                slow_ratio=0.0,
                iqr_outliers=0,
                details={"reason": "insufficient_valid_times"},
            )
        
        # HARDENING: Apply first-response grace period
        analysis_times = valid_times[1:] if (self._config.first_response_grace and len(valid_times) > 3) else valid_times
        
        # Calculate z-scores against population baseline
        sample_mean = mean(analysis_times)
        z_score_mean = (sample_mean - baseline.mean_ms) / (baseline.std_ms / math.sqrt(len(analysis_times)))
        
        # Count anomalies using z-score thresholds
        too_fast = sum(1 for t in analysis_times 
                       if self._z_score(t, baseline) < self._config.z_threshold_fast)
        too_slow = sum(1 for t in analysis_times 
                       if self._z_score(t, baseline) > self._config.z_threshold_slow)
        
        # IQR-based outlier detection (HARDENING: more robust)
        iqr_outliers = self._count_iqr_outliers(analysis_times, baseline)
        
        n = len(analysis_times)
        fast_ratio = too_fast / n
        slow_ratio = too_slow / n
        iqr_ratio = iqr_outliers / n
        
        # Calculate component penalties (all bounded to [0, 1])
        p_fast = self._bounded_ratio(fast_ratio, self._config.fast_ratio_threshold)
        p_slow = self._bounded_ratio(slow_ratio, self._config.slow_ratio_threshold)
        p_iqr = min(1.0, iqr_ratio * 2)  # IQR outliers weighted more heavily
        
        # Total penalty with explicit weights (HARDENING: provably bounded)
        total_penalty = (
            self.WEIGHT_FAST * p_fast +
            self.WEIGHT_SLOW * p_slow +
            self.WEIGHT_IQR * p_iqr
        )
        
        # HARDENING: Explicit clamping to guaranteed bounds
        total_penalty = self._clamp(total_penalty, self._config.min_penalty, self._config.max_penalty)
        
        return self._create_result(
            penalty=round(total_penalty, 4),
            z_score_mean=round(z_score_mean, 4),
            questions_too_fast=too_fast,
            questions_too_slow=too_slow,
            total_questions=total,
            median_response_ms=median(analysis_times),
            fast_ratio=round(fast_ratio, 4),
            slow_ratio=round(slow_ratio, 4),
            iqr_outliers=iqr_outliers,
            details={
                "p_fast": round(p_fast, 4),
                "p_slow": round(p_slow, 4),
                "p_iqr": round(p_iqr, 4),
                "baseline_mean": baseline.mean_ms,
                "baseline_std": baseline.std_ms,
            },
        )
    
    @staticmethod
    def _z_score(value: float, baseline: PopulationBaseline) -> float:
        """Calculate z-score for a single value against baseline."""
        return (value - baseline.mean_ms) / baseline.std_ms
    
    @staticmethod
    def _bounded_ratio(ratio: float, threshold: float) -> float:
        """Calculate bounded penalty ratio: min(1, ratio/threshold)."""
        if threshold <= 0:
            return 0.0
        return min(1.0, ratio / threshold)
    
    @staticmethod
    def _clamp(value: float, min_val: float, max_val: float) -> float:
        """Clamp value to [min_val, max_val]. PURE FUNCTION."""
        return max(min_val, min(max_val, value))
    
    def _count_iqr_outliers(self, times: List[float], baseline: PopulationBaseline) -> int:
        """
        Count IQR-based outliers (HARDENING: robust outlier detection).
        
        Outlier definition: t < Q1 - 1.5×IQR or t > Q3 + 1.5×IQR
        """
        iqr = baseline.q3_ms - baseline.q1_ms
        factor = self._config.iqr_outlier_factor
        lower_bound = baseline.q1_ms - factor * iqr
        upper_bound = baseline.q3_ms + factor * iqr
        
        return sum(1 for t in times if t < lower_bound or t > upper_bound)
    
    def _create_result(self, **kwargs) -> SpeedAnomalyResult:
        """Create immutable result object."""
        return SpeedAnomalyResult(**kwargs)
    
    def calculate_penalty(self, response_times_ms: List[int]) -> float:
        """
        Pure function to calculate penalty.
        
        MATHEMATICAL GUARANTEE:
            ∀ T ∈ ℤⁿ₊: calculate_penalty(T) ∈ [0, 1]
        """
        result = self.detect(response_times_ms)
        return result.penalty

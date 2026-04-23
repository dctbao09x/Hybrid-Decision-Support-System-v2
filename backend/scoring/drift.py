# backend/scoring/drift.py
"""
Score Distribution Drift Detection - SIMGR Stage 3 Compliant
=============================================================

Monitors SIMGR score distributions for:
- Distribution drift (KL divergence, PSI, Jensen-Shannon Divergence)
- Score mean/std shifts
- Component correlation changes
- Adaptive thresholding (mean + k * std of history)

Drift classification:
  - feature_drift:    shift in input feature distributions
  - prediction_drift: shift in model output (score) distributions
  - label_drift:      shift in ground-truth label distribution (when available)

Triggers alerts when PSI > 0.25 or JSD > adaptive threshold.
"""

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Drift classification constants ────────────────────────────────────────────
DRIFT_TYPE_FEATURE    = "feature_drift"
DRIFT_TYPE_PREDICTION = "prediction_drift"
DRIFT_TYPE_LABEL      = "label_drift"


@dataclass
class DriftMetrics:
    """Drift detection metrics."""
    metric_name: str
    psi: float              # Population Stability Index
    kl_divergence: float    # KL Divergence (asymmetric)
    js_divergence: float    # Jensen-Shannon Divergence (symmetric, bounded [0,1])
    mean_shift: float       # Change in mean
    std_shift: float        # Change in std
    sample_size: int
    drift_type: str = DRIFT_TYPE_FEATURE   # feature_drift | prediction_drift | label_drift
    timestamp: datetime = field(default_factory=datetime.now)
    is_drift: bool = False
    adaptive_threshold: Optional[float] = None   # threshold used for this check

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "psi": round(self.psi, 4),
            "kl_divergence": round(self.kl_divergence, 4),
            "js_divergence": round(self.js_divergence, 4),
            "mean_shift": round(self.mean_shift, 4),
            "std_shift": round(self.std_shift, 4),
            "sample_size": self.sample_size,
            "drift_type": self.drift_type,
            "timestamp": self.timestamp.isoformat(),
            "is_drift": self.is_drift,
            "adaptive_threshold": (
                round(self.adaptive_threshold, 4)
                if self.adaptive_threshold is not None
                else None
            ),
        }


@dataclass
class DriftAlert:
    """Alert for detected drift."""
    metric: str
    severity: str  # LOW, MEDIUM, HIGH
    psi_value: float
    js_divergence: float
    drift_type: str
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    acknowledged: bool = False


class DistributionDriftDetector:
    """Detects distribution drift in SIMGR scores.

    Uses:
    - PSI (Population Stability Index) > 0.25 = drift
    - KL Divergence for probabilistic comparison
    - Jensen-Shannon Divergence (symmetric, bounded [0,1])
    - Adaptive thresholding: threshold = mean(history) + k * std(history)
    - Drift classification: feature_drift / prediction_drift / label_drift
    - Sliding window comparisons
    """

    PSI_LOW_THRESHOLD    = 0.10  # Slight change
    PSI_MEDIUM_THRESHOLD = 0.25  # Significant change - TRIGGER
    PSI_HIGH_THRESHOLD   = 0.50  # Major drift

    KL_THRESHOLD  = 0.10   # KL divergence threshold (static fallback)
    JSD_THRESHOLD = 0.10   # JSD static fallback threshold [0, 1]

    def __init__(
        self,
        reference_window: int = 1000,
        comparison_window: int = 100,
        n_bins: int = 10,
        adaptive_k: float = 2.0,          # k multiplier for adaptive threshold
        adaptive_min_history: int = 10,   # minimum JSD history points before adaptive kicks in
    ):
        self.reference_window    = reference_window
        self.comparison_window   = comparison_window
        self.n_bins              = n_bins
        self.adaptive_k          = adaptive_k
        self.adaptive_min_history = adaptive_min_history

        # Score history by component
        self._history: Dict[str, List[float]] = defaultdict(list)
        self._reference: Dict[str, List[float]] = {}
        self._alerts: List[DriftAlert] = []
        self._metrics_history: List[DriftMetrics] = []

        # JSD divergence history per component (for adaptive threshold)
        self._jsd_history: Dict[str, List[float]] = defaultdict(list)
    
    def record_score(
        self,
        component: str,
        score: float,
        drift_type: str = DRIFT_TYPE_FEATURE,
    ) -> Optional[DriftMetrics]:
        """Record a score and check for drift.

        Args:
            component:  Score component (study, interest, market, growth, risk, final)
            score:      Score value [0, 1]
            drift_type: Classification – feature_drift | prediction_drift | label_drift

        Returns:
            DriftMetrics if drift detected, None otherwise.
        """
        self._history[component].append(score)

        # Trim to reference window
        if len(self._history[component]) > self.reference_window:
            self._history[component] = self._history[component][-self.reference_window:]

        # Initialize reference if needed
        if component not in self._reference and len(self._history[component]) >= self.comparison_window:
            self._reference[component] = self._history[component][:self.comparison_window].copy()

        # Check for drift
        if len(self._history[component]) >= self.comparison_window:
            return self._check_drift(component, drift_type=drift_type)

        return None

    def record_scores(
        self,
        scores: Dict[str, float],
        drift_type: str = DRIFT_TYPE_FEATURE,
    ) -> List[DriftMetrics]:
        """Record multiple component scores at once.

        Args:
            scores:     Dict of component -> score
            drift_type: Classification applied to all components in this batch

        Returns:
            List of DriftMetrics for components with drift.
        """
        drifts = []
        for component, score in scores.items():
            result = self.record_score(component, score, drift_type=drift_type)
            if result and result.is_drift:
                drifts.append(result)
        return drifts
    
    def _check_drift(
        self,
        component: str,
        drift_type: str = DRIFT_TYPE_FEATURE,
    ) -> Optional[DriftMetrics]:
        """Check for distribution drift using PSI, KL divergence, and JSD."""
        reference = self._reference.get(component, [])
        if len(reference) < self.comparison_window:
            return None

        # Recent scores for comparison
        recent = self._history[component][-self.comparison_window:]

        # Compute metrics
        psi    = self._compute_psi(reference, recent)
        kl_div = self._compute_kl_divergence(reference, recent)
        jsd    = self._compute_js_divergence(reference, recent)

        # Update JSD history for adaptive threshold
        self._jsd_history[component].append(jsd)

        # Compute mean/std shifts
        ref_mean    = sum(reference) / len(reference)
        ref_std     = self._compute_std(reference)
        recent_mean = sum(recent) / len(recent)
        recent_std  = self._compute_std(recent)
        mean_shift  = recent_mean - ref_mean
        std_shift   = recent_std  - ref_std

        # Adaptive JSD threshold: mean + k * std of observed JSD history
        adaptive_threshold = self._compute_adaptive_threshold(component)

        # Determine if drift occurred (PSI static OR JSD adaptive)
        is_drift = (
            psi > self.PSI_MEDIUM_THRESHOLD
            or kl_div > self.KL_THRESHOLD
            or jsd > adaptive_threshold
        )

        metrics = DriftMetrics(
            metric_name=component,
            psi=psi,
            kl_divergence=kl_div,
            js_divergence=jsd,
            mean_shift=mean_shift,
            std_shift=std_shift,
            sample_size=len(recent),
            drift_type=drift_type,
            is_drift=is_drift,
            adaptive_threshold=adaptive_threshold,
        )

        self._metrics_history.append(metrics)

        if is_drift:
            self._create_alert(metrics)
            logger.warning(
                f"DRIFT DETECTED [{drift_type}]: {component} "
                f"PSI={psi:.4f} KL={kl_div:.4f} JSD={jsd:.4f} "
                f"adaptive_thr={adaptive_threshold:.4f}"
            )

        return metrics
    
    def _compute_psi(self, reference: List[float], current: List[float]) -> float:
        """Compute Population Stability Index.
        
        PSI = Σ (actual% - expected%) * ln(actual% / expected%)
        
        Returns:
            PSI value (0 = identical, >0.25 = significant drift)
        """
        # Create histograms
        ref_hist = self._create_histogram(reference)
        cur_hist = self._create_histogram(current)
        
        # Add small epsilon to avoid division by zero
        eps = 1e-10
        
        psi = 0.0
        for i in range(self.n_bins):
            ref_pct = ref_hist[i] + eps
            cur_pct = cur_hist[i] + eps
            
            psi += (cur_pct - ref_pct) * math.log(cur_pct / ref_pct)
        
        return abs(psi)
    
    def _compute_kl_divergence(self, reference: List[float], current: List[float]) -> float:
        """Compute KL Divergence D_KL(P || Q).
        
        Returns:
            KL divergence value.
        """
        ref_hist = self._create_histogram(reference)
        cur_hist = self._create_histogram(current)
        
        eps = 1e-10
        
        kl_div = 0.0
        for i in range(self.n_bins):
            ref_pct = ref_hist[i] + eps
            cur_pct = cur_hist[i] + eps
            
            if cur_pct > eps:
                kl_div += cur_pct * math.log(cur_pct / ref_pct)
        
        return abs(kl_div)

    def _compute_js_divergence(self, p: List[float], q: List[float]) -> float:
        """Compute Jensen-Shannon Divergence between two distributions.

        JSD is the symmetric, smoothed version of KL divergence.
        It is bounded in [0, 1] (using base-2 logarithm convention).

        JSD(P || Q) = (KL(P || M) + KL(Q || M)) / 2
        where M = (P + Q) / 2

        Properties guaranteed:
          • 0 ≤ JSD ≤ 1
          • JSD(P, Q) = JSD(Q, P)   (symmetric)
          • JSD = 0 iff P == Q

        Args:
            p: Reference distribution samples (list of floats in [0, 1]).
            q: Current  distribution samples (list of floats in [0, 1]).

        Returns:
            JSD in [0, 1].
        """
        p_hist = self._create_histogram(p)
        q_hist = self._create_histogram(q)

        eps = 1e-12

        js = 0.0
        for pi, qi in zip(p_hist, q_hist):
            pi = pi + eps
            qi = qi + eps
            mi = (pi + qi) / 2.0
            # Use natural log then normalise to [0,1] at the end
            js += pi * math.log(pi / mi) + qi * math.log(qi / mi)

        # js = KL(P||M) + KL(Q||M); halve → [0, ln2]; divide by ln(2) → [0, 1]
        jsd = (js / 2.0) / math.log(2)
        return min(max(jsd, 0.0), 1.0)   # clamp to [0, 1] for numerical safety

    def _compute_adaptive_threshold(self, component: str) -> float:
        """Compute adaptive JSD threshold for a component.

        Threshold = mean(jsd_history) + k * std(jsd_history)

        Falls back to JSD_THRESHOLD constant when there is insufficient history.

        Args:
            component: Score component name.

        Returns:
            Adaptive threshold value in (0, 1].
        """
        history = self._jsd_history.get(component, [])
        if len(history) < self.adaptive_min_history:
            return self.JSD_THRESHOLD

        mean_jsd = sum(history) / len(history)
        variance  = sum((x - mean_jsd) ** 2 for x in history) / len(history)
        std_jsd   = math.sqrt(variance)
        threshold = mean_jsd + self.adaptive_k * std_jsd

        # Clamp to sensible range
        return min(max(threshold, 1e-4), 1.0)
    
    def _create_histogram(self, values: List[float]) -> List[float]:
        """Create normalized histogram."""
        # Bins from 0 to 1
        bin_width = 1.0 / self.n_bins
        counts = [0] * self.n_bins
        
        for v in values:
            v = max(0.0, min(1.0, v))  # Clamp to [0, 1]
            bin_idx = min(int(v / bin_width), self.n_bins - 1)
            counts[bin_idx] += 1
        
        # Normalize
        total = sum(counts) or 1
        return [c / total for c in counts]
    
    def _compute_std(self, values: List[float]) -> float:
        """Compute standard deviation."""
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return math.sqrt(variance)
    
    def _create_alert(self, metrics: DriftMetrics) -> None:
        """Create a drift alert."""
        if metrics.psi > self.PSI_HIGH_THRESHOLD:
            severity = "HIGH"
        elif metrics.psi > self.PSI_MEDIUM_THRESHOLD:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        alert = DriftAlert(
            metric=metrics.metric_name,
            severity=severity,
            psi_value=metrics.psi,
            js_divergence=metrics.js_divergence,
            drift_type=metrics.drift_type,
            message=(
                f"Distribution drift detected [{metrics.drift_type}] "
                f"for {metrics.metric_name}: "
                f"PSI={metrics.psi:.4f}, KL={metrics.kl_divergence:.4f}, "
                f"JSD={metrics.js_divergence:.4f}"
            ),
        )

        self._alerts.append(alert)
    
    def get_alerts(self, unacknowledged_only: bool = True) -> List[DriftAlert]:
        """Get drift alerts."""
        if unacknowledged_only:
            return [a for a in self._alerts if not a.acknowledged]
        return self._alerts.copy()
    
    def acknowledge_alert(self, index: int) -> bool:
        """Acknowledge an alert by index."""
        if 0 <= index < len(self._alerts):
            self._alerts[index].acknowledged = True
            return True
        return False
    
    def get_drift_status(self) -> Dict[str, Any]:
        """Get overall drift status for all components."""
        status = {}

        for component, history in self._history.items():
            if len(history) < self.comparison_window:
                status[component] = {"status": "INSUFFICIENT_DATA", "samples": len(history)}
                continue

            reference = self._reference.get(component, [])
            recent    = history[-self.comparison_window:]

            if reference:
                psi = self._compute_psi(reference, recent)
                jsd = self._compute_js_divergence(reference, recent)
                adaptive_thr = self._compute_adaptive_threshold(component)

                if psi > self.PSI_HIGH_THRESHOLD or jsd > adaptive_thr * 2:
                    drift_status = "HIGH_DRIFT"
                elif psi > self.PSI_MEDIUM_THRESHOLD or jsd > adaptive_thr:
                    drift_status = "DRIFT"
                elif psi > self.PSI_LOW_THRESHOLD:
                    drift_status = "SLIGHT_CHANGE"
                else:
                    drift_status = "STABLE"

                status[component] = {
                    "status": drift_status,
                    "psi": round(psi, 4),
                    "jsd": round(jsd, 4),
                    "adaptive_threshold": round(adaptive_thr, 4),
                    "samples": len(history),
                    "mean": round(sum(recent) / len(recent), 4),
                }
            else:
                status[component] = {"status": "NO_REFERENCE", "samples": len(history)}

        return status
    
    def reset_reference(self, component: Optional[str] = None) -> None:
        """Reset reference distribution for recalibration."""
        if component:
            if component in self._history and len(self._history[component]) >= self.comparison_window:
                self._reference[component] = self._history[component][-self.comparison_window:].copy()
        else:
            # Reset all
            for comp, hist in self._history.items():
                if len(hist) >= self.comparison_window:
                    self._reference[comp] = hist[-self.comparison_window:].copy()


# Singleton instance
_detector: Optional[DistributionDriftDetector] = None


def get_drift_detector() -> DistributionDriftDetector:
    """Get singleton drift detector."""
    global _detector
    if _detector is None:
        _detector = DistributionDriftDetector()
    return _detector


def record_simgr_scores(scores: Dict[str, float]) -> List[DriftMetrics]:
    """Record SIMGR scores and check for drift."""
    return get_drift_detector().record_scores(scores)


def get_drift_status() -> Dict[str, Any]:
    """Get drift status for all components."""
    return get_drift_detector().get_drift_status()


def get_drift_alerts() -> List[Dict]:
    """Get current drift alerts."""
    alerts = get_drift_detector().get_alerts()
    return [
        {
            "metric": a.metric,
            "severity": a.severity,
            "psi": a.psi_value,
            "jsd": a.js_divergence,
            "drift_type": a.drift_type,
            "message": a.message,
            "timestamp": a.timestamp.isoformat(),
        }
        for a in alerts
    ]

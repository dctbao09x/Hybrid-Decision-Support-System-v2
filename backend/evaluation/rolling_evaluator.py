# backend/evaluation/rolling_evaluator.py
"""
Rolling Evaluator — Governance-Grade Real-Time Metrics
=======================================================

Tracks model performance and explanation quality on a rolling window
of **live inference decisions**.  Designed to run in-process alongside
the decision pipeline (zero external dependencies beyond numpy).

Two confidence axes (kept separate):
  model_performance_confidence
      → calibration quality of the SIMGR score → probability mapping
      → measured via Brier Score and Expected Calibration Error (ECE)

  explanation_confidence
      → mean confidence emitted by the ExplanationResult layer
      → tracks LLM explanation quality independent of scoring

Rolling metrics:
  • Accuracy, Precision (macro), Recall (macro), F1 (macro)
  • Brier Score  — calibration loss (lower = better)
  • ECE          — Expected Calibration Error (lower = better)

Alert rules (configurable):
  • f1_drop_pct   — alert when rolling F1 drops > X% from baseline
  • calibration_threshold — alert when Brier Score or ECE exceeds threshold

Usage::

    from backend.evaluation.rolling_evaluator import RollingEvaluator

    evaluator = RollingEvaluator(window=500)

    # Log every decision (no ground truth yet):
    evaluator.log_prediction(
        trace_id="dec-abc",
        predicted_label="Software Engineer",
        probability=0.82,
        model_version="v1.0.0",
        explanation_confidence=0.74,
    )

    # When ground truth arrives:
    evaluator.update_ground_truth(trace_id="dec-abc", true_label="Software Engineer")

    # Get current snapshot:
    snapshot = evaluator.snapshot()
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

_log = logging.getLogger("evaluation.rolling_evaluator")

# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_WINDOW        = 500     # rolling window size (samples)
DEFAULT_F1_DROP_PCT   = 10.0    # alert threshold: F1 drop percent from baseline
DEFAULT_BRIER_THRESH  = 0.25    # alert threshold: Brier Score
DEFAULT_ECE_THRESH    = 0.10    # alert threshold: ECE
ECE_BINS              = 10      # bins for ECE computation


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class EvalSample:
    """One decision logged for rolling evaluation.

    Fields set at prediction time::

        trace_id            — unique decision trace
        predicted_label     — top-ranked career name
        probability         — SIMGR normalised score in [0, 1]
                              (used as predicted probability for calibration)
        model_version       — active SIMGR model version string
        explanation_confidence — confidence emitted by ExplanationResult (or None)
        timestamp           — ISO8601 UTC

    Fields added when ground truth becomes available::

        true_label          — actual outcome (e.g. from feedback)
        labelled            — True once true_label is set
    """
    trace_id: str
    predicted_label: str
    probability: float
    model_version: str
    timestamp: str
    explanation_confidence: Optional[float] = None
    true_label: Optional[str] = None
    labelled: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id":             self.trace_id,
            "predicted_label":      self.predicted_label,
            "probability":          round(self.probability, 6),
            "model_version":        self.model_version,
            "timestamp":            self.timestamp,
            "explanation_confidence": round(self.explanation_confidence, 6)
                                       if self.explanation_confidence is not None else None,
            "true_label":           self.true_label,
            "labelled":             self.labelled,
        }


@dataclass
class AlertEvent:
    """Fired when a metric crosses an alert threshold."""
    alert_type: str      # "f1_drop" | "calibration_brier" | "calibration_ece"
    metric_name: str
    current_value: float
    threshold: float
    message: str
    timestamp: str
    model_version: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_type":    self.alert_type,
            "metric_name":   self.metric_name,
            "current_value": round(self.current_value, 6),
            "threshold":     round(self.threshold, 6),
            "message":       self.message,
            "timestamp":     self.timestamp,
            "model_version": self.model_version,
        }


@dataclass
class EvalSnapshot:
    """Point-in-time evaluation metrics snapshot.

    model_performance_confidence and explanation_confidence are kept
    as separate fields so consumers can reason about each axis independently.
    """
    timestamp: str
    model_version: str
    sample_size: int          # total predictions logged
    labelled_size: int        # predictions with ground truth

    # ── Classification metrics (require ground truth) ────────────────────────
    rolling_accuracy:  Optional[float] = None
    rolling_precision: Optional[float] = None
    rolling_recall:    Optional[float] = None
    rolling_f1:        Optional[float] = None

    # ── Calibration (require ground truth) ───────────────────────────────────
    brier_score:       Optional[float] = None   # lower is better
    ece:               Optional[float] = None   # Expected Calibration Error

    # ── Confidence axes ───────────────────────────────────────────────────────
    model_performance_confidence: Optional[float] = None  # 1 - brier_score (proxy)
    explanation_confidence_mean:  Optional[float] = None  # mean of explanation_confidence

    # ── Active alerts ─────────────────────────────────────────────────────────
    active_alerts: List[AlertEvent] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp":                   self.timestamp,
            "model_version":               self.model_version,
            "sample_size":                 self.sample_size,
            "labelled_size":               self.labelled_size,
            "rolling_accuracy":            _r(self.rolling_accuracy),
            "rolling_precision":           _r(self.rolling_precision),
            "rolling_recall":              _r(self.rolling_recall),
            "rolling_f1":                  _r(self.rolling_f1),
            "brier_score":                 _r(self.brier_score),
            "ece":                         _r(self.ece),
            "model_performance_confidence": _r(self.model_performance_confidence),
            "explanation_confidence_mean":  _r(self.explanation_confidence_mean),
            "active_alerts":               [a.to_dict() for a in self.active_alerts],
        }


def _r(v: Optional[float], digits: int = 6) -> Optional[float]:
    return round(v, digits) if v is not None else None


# ═══════════════════════════════════════════════════════════════════════════════
# ALERT RULES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AlertRules:
    """Alert thresholds configurable at construction time.

    Args:
        f1_drop_pct:         Relative F1 drop (%) from baseline to trigger alert.
        brier_threshold:     Brier Score threshold; alert when exceeded.
        ece_threshold:       ECE threshold; alert when exceeded.
        f1_baseline:         Baseline F1 used for relative drop computation.
                             If None, uses the first computed snapshot F1.
    """
    f1_drop_pct: float   = DEFAULT_F1_DROP_PCT
    brier_threshold: float = DEFAULT_BRIER_THRESH
    ece_threshold: float   = DEFAULT_ECE_THRESH
    f1_baseline: Optional[float] = None

    def check(
        self,
        snapshot: EvalSnapshot,
        model_version: str,
    ) -> List[AlertEvent]:
        """Evaluate all rules against *snapshot*; return fired alerts."""
        ts  = datetime.now(timezone.utc).isoformat()
        alerts: List[AlertEvent] = []

        # ── F1 drop alert ────────────────────────────────────────────────────
        if snapshot.rolling_f1 is not None:
            baseline = self.f1_baseline
            if baseline is None:
                # Auto-set baseline on first available F1
                self.f1_baseline = snapshot.rolling_f1
                baseline = snapshot.rolling_f1

            if baseline > 0:
                drop_pct = (baseline - snapshot.rolling_f1) / baseline * 100.0
                if drop_pct > self.f1_drop_pct:
                    alerts.append(AlertEvent(
                        alert_type="f1_drop",
                        metric_name="rolling_f1",
                        current_value=snapshot.rolling_f1,
                        threshold=baseline * (1 - self.f1_drop_pct / 100.0),
                        message=(
                            f"Rolling F1 dropped {drop_pct:.1f}% from baseline "
                            f"{baseline:.4f} → {snapshot.rolling_f1:.4f} "
                            f"(threshold: {self.f1_drop_pct:.1f}%)"
                        ),
                        timestamp=ts,
                        model_version=model_version,
                    ))

        # ── Calibration: Brier Score alert ───────────────────────────────────
        if snapshot.brier_score is not None and snapshot.brier_score > self.brier_threshold:
            alerts.append(AlertEvent(
                alert_type="calibration_brier",
                metric_name="brier_score",
                current_value=snapshot.brier_score,
                threshold=self.brier_threshold,
                message=(
                    f"Brier Score {snapshot.brier_score:.4f} exceeds "
                    f"threshold {self.brier_threshold:.4f}"
                ),
                timestamp=ts,
                model_version=model_version,
            ))

        # ── Calibration: ECE alert ────────────────────────────────────────────
        if snapshot.ece is not None and snapshot.ece > self.ece_threshold:
            alerts.append(AlertEvent(
                alert_type="calibration_ece",
                metric_name="ece",
                current_value=snapshot.ece,
                threshold=self.ece_threshold,
                message=(
                    f"ECE {snapshot.ece:.4f} exceeds threshold {self.ece_threshold:.4f}"
                ),
                timestamp=ts,
                model_version=model_version,
            ))

        return alerts


# ═══════════════════════════════════════════════════════════════════════════════
# CALIBRATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def compute_brier_score(
    probabilities: List[float],
    outcomes: List[int],          # 1 = correct prediction, 0 = incorrect
) -> float:
    """Brier Score: mean squared error between probability and binary outcome.

    Args:
        probabilities: Predicted probability for each sample.
        outcomes:      1 if predicted_label == true_label else 0.

    Returns:
        float in [0, 1]; lower is better (0 = perfect calibration).
    """
    if not probabilities:
        return 0.0
    p = np.array(probabilities, dtype=float)
    o = np.array(outcomes, dtype=float)
    return float(np.mean((p - o) ** 2))


def compute_ece(
    probabilities: List[float],
    outcomes: List[int],
    n_bins: int = ECE_BINS,
) -> float:
    """Expected Calibration Error (uniform binning).

    Args:
        probabilities: Predicted probability for each sample.
        outcomes:      1 if prediction correct, 0 otherwise.
        n_bins:        Number of equal-width bins (default 10).

    Returns:
        float in [0, 1]; lower is better.
    """
    if not probabilities:
        return 0.0
    p = np.array(probabilities, dtype=float)
    o = np.array(outcomes, dtype=float)
    n = len(p)
    ece_acc = 0.0
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        mask = (p >= lo) & (p < hi if hi < 1.0 else p <= hi)
        n_bin = int(mask.sum())
        if n_bin == 0:
            continue
        acc_bin  = float(o[mask].mean())
        conf_bin = float(p[mask].mean())
        ece_acc += (n_bin / n) * abs(acc_bin - conf_bin)
    return float(ece_acc)


# ═══════════════════════════════════════════════════════════════════════════════
# ROLLING EVALUATOR
# ═══════════════════════════════════════════════════════════════════════════════

class RollingEvaluator:
    """Real-time rolling evaluation tracker.

    Maintains a bounded deque of :class:`EvalSample` objects.
    Classification metrics are computed over the labelled subset;
    calibration metrics are computed whenever ≥ 10 labelled samples exist.

    Thread safety: single-threaded (caller must synchronise if shared).

    Args:
        window:        Maximum rolling window size (samples, default 500).
        alert_rules:   :class:`AlertRules` instance (created with defaults if None).
        min_labelled:  Minimum labelled samples required before computing metrics.
    """

    def __init__(
        self,
        window: int = DEFAULT_WINDOW,
        alert_rules: Optional[AlertRules] = None,
        min_labelled: int = 10,
    ) -> None:
        self._window     = window
        self._rules      = alert_rules or AlertRules()
        self._min_labelled = min_labelled
        self._samples: Deque[EvalSample] = deque(maxlen=window)
        self._index: Dict[str, EvalSample] = {}  # trace_id → sample

    # ── Public write API ─────────────────────────────────────────────────────

    def log_prediction(
        self,
        trace_id: str,
        predicted_label: str,
        probability: float,
        model_version: str,
        explanation_confidence: Optional[float] = None,
        timestamp: Optional[str] = None,
    ) -> EvalSample:
        """Record a new prediction.  Ground truth may be added later via
        :meth:`update_ground_truth`.

        Args:
            trace_id:              Decision pipeline trace ID.
            predicted_label:       Top-ranked career (label).
            probability:           SIMGR normalised score → treated as P(correct).
            model_version:         Active model version string.
            explanation_confidence: Confidence from the XAI layer (None if no explanation).
            timestamp:             ISO8601 UTC string (defaults to now).

        Returns:
            The :class:`EvalSample` that was stored.
        """
        probability = float(np.clip(probability, 0.0, 1.0))
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        sample = EvalSample(
            trace_id=trace_id,
            predicted_label=predicted_label,
            probability=probability,
            model_version=model_version,
            timestamp=ts,
            explanation_confidence=explanation_confidence,
        )
        # If window is full, remove the oldest sample from the index too
        if len(self._samples) == self._window:
            oldest = self._samples[0]
            self._index.pop(oldest.trace_id, None)
        self._samples.append(sample)
        self._index[trace_id] = sample
        _log.debug(
            "Prediction logged: trace=%s label=%s prob=%.4f model=%s",
            trace_id, predicted_label, probability, model_version,
        )
        return sample

    def update_ground_truth(
        self,
        trace_id: str,
        true_label: str,
    ) -> Optional[EvalSample]:
        """Attach ground truth to a previously logged prediction.

        Args:
            trace_id:  The decision trace ID that was logged earlier.
            true_label: The actual career outcome.

        Returns:
            Updated :class:`EvalSample` or None if trace_id not in window.
        """
        sample = self._index.get(trace_id)
        if sample is None:
            _log.debug("update_ground_truth: trace_id=%s not in window", trace_id)
            return None
        sample.true_label = true_label
        sample.labelled   = True
        _log.debug(
            "Ground truth attached: trace=%s predicted=%s actual=%s",
            trace_id, sample.predicted_label, true_label,
        )
        return sample

    # ── Public read API ──────────────────────────────────────────────────────

    def snapshot(self) -> EvalSnapshot:
        """Compute and return a point-in-time :class:`EvalSnapshot`.

        Metrics are computed over the current window; calibration metrics
        require at least ``min_labelled`` labelled samples.

        Returns:
            :class:`EvalSnapshot` with all computable metrics populated.
        """
        samples  = list(self._samples)
        labelled = [s for s in samples if s.labelled and s.true_label is not None]

        model_version = samples[-1].model_version if samples else "unknown"

        snap = EvalSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            model_version=model_version,
            sample_size=len(samples),
            labelled_size=len(labelled),
        )

        if len(labelled) >= self._min_labelled:
            snap = self._compute_classification(snap, labelled)
            snap = self._compute_calibration(snap, labelled)

        # Explanation confidence — computed over all samples with a value
        exp_confs = [
            s.explanation_confidence
            for s in samples
            if s.explanation_confidence is not None
        ]
        if exp_confs:
            snap.explanation_confidence_mean = float(np.mean(exp_confs))

        # Model performance confidence = 1 − Brier Score (proxy)
        if snap.brier_score is not None:
            snap.model_performance_confidence = max(0.0, 1.0 - snap.brier_score)

        # Fire alert rules
        snap.active_alerts = self._rules.check(snap, model_version)

        return snap

    def get_sample(self, trace_id: str) -> Optional[EvalSample]:
        """Return the stored sample for a trace_id (or None)."""
        return self._index.get(trace_id)

    def drain_alerts(self) -> List[AlertEvent]:
        """Return active alerts from the latest snapshot without recomputing all metrics."""
        return self.snapshot().active_alerts

    # ── Internal computation ─────────────────────────────────────────────────

    def _compute_classification(
        self,
        snap: EvalSnapshot,
        labelled: List[EvalSample],
    ) -> EvalSnapshot:
        """Populate accuracy/precision/recall/F1 on *snap* from *labelled*."""
        y_pred = [s.predicted_label for s in labelled]
        y_true = [s.true_label      for s in labelled]

        labels = sorted(set(y_true) | set(y_pred))
        label_idx = {lbl: i for i, lbl in enumerate(labels)}
        n = len(labels)

        # Build confusion-matrix-like per-class TP, FP, FN
        tp = np.zeros(n, dtype=float)
        fp = np.zeros(n, dtype=float)
        fn = np.zeros(n, dtype=float)
        correct = 0
        for yt, yp in zip(y_true, y_pred):
            if yt == yp:
                tp[label_idx[yt]] += 1
                correct += 1
            else:
                fp[label_idx[yp]] += 1
                fn[label_idx[yt]] += 1

        total = len(labelled)
        snap.rolling_accuracy = correct / total if total > 0 else 0.0

        # Macro precision / recall / F1
        per_precision = np.divide(tp, tp + fp, out=np.zeros(n), where=(tp + fp) > 0)
        per_recall    = np.divide(tp, tp + fn, out=np.zeros(n), where=(tp + fn) > 0)
        per_f1 = np.divide(
            2 * per_precision * per_recall,
            per_precision + per_recall,
            out=np.zeros(n),
            where=(per_precision + per_recall) > 0,
        )
        snap.rolling_precision = float(per_precision.mean())
        snap.rolling_recall    = float(per_recall.mean())
        snap.rolling_f1        = float(per_f1.mean())

        _log.debug(
            "Classification metrics: acc=%.4f prec=%.4f rec=%.4f f1=%.4f (n=%d)",
            snap.rolling_accuracy, snap.rolling_precision,
            snap.rolling_recall, snap.rolling_f1, total,
        )
        return snap

    def _compute_calibration(
        self,
        snap: EvalSnapshot,
        labelled: List[EvalSample],
    ) -> EvalSnapshot:
        """Populate Brier Score and ECE on *snap* from *labelled*."""
        probs    = [s.probability for s in labelled]
        outcomes = [1 if s.predicted_label == s.true_label else 0 for s in labelled]

        snap.brier_score = compute_brier_score(probs, outcomes)
        snap.ece         = compute_ece(probs, outcomes)

        _log.debug(
            "Calibration: brier=%.4f ece=%.4f (n=%d)",
            snap.brier_score, snap.ece, len(labelled),
        )
        return snap


# ── Module-level singleton ────────────────────────────────────────────────────

_singleton: Optional[RollingEvaluator] = None


def get_rolling_evaluator(
    window: int = DEFAULT_WINDOW,
    alert_rules: Optional[AlertRules] = None,
) -> RollingEvaluator:
    """Return (or create) the process-wide :class:`RollingEvaluator` singleton."""
    global _singleton
    if _singleton is None:
        _singleton = RollingEvaluator(window=window, alert_rules=alert_rules)
    return _singleton

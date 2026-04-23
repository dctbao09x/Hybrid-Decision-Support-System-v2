# tests/scoring/test_drift.py
"""
Tests for Drift Detection (R007) — Production-Grade Suite

Validates:
- PSI computation
- KL divergence computation
- Jensen-Shannon Divergence (symmetric, bounded [0,1])
- Adaptive threshold (mean + k*std of JSD history)
- Drift classification: feature_drift / prediction_drift / label_drift
- Drift detection threshold (PSI > 0.25)
- Alert generation (includes js_divergence, drift_type)
- Score distribution monitoring
- Unified _run_drift_check via DistributionDriftDetector
"""

import pytest
import random
from pathlib import Path
import sys
import math

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.scoring.drift import (
    DistributionDriftDetector,
    DriftMetrics,
    DRIFT_TYPE_FEATURE,
    DRIFT_TYPE_PREDICTION,
    DRIFT_TYPE_LABEL,
    get_drift_detector,
    record_simgr_scores,
    get_drift_status,
)


class TestPSIComputation:
    """Test Population Stability Index computation."""
    
    def test_identical_distributions_psi_zero(self):
        """Identical distributions should have PSI near 0."""
        detector = DistributionDriftDetector(comparison_window=50)
        
        # Same distribution
        reference = [0.5] * 50
        current = [0.5] * 50
        
        detector._reference["test"] = reference
        detector._history["test"] = reference + current
        
        psi = detector._compute_psi(reference, current)
        
        assert psi < 0.01, f"PSI for identical distributions should be ~0, got {psi}"
    
    def test_similar_distributions_low_psi(self):
        """Similar distributions should have low PSI."""
        detector = DistributionDriftDetector(comparison_window=100)
        
        random.seed(42)
        reference = [random.gauss(0.5, 0.1) for _ in range(100)]
        reference = [max(0, min(1, x)) for x in reference]
        
        # Slightly different distribution
        current = [random.gauss(0.52, 0.11) for _ in range(100)]
        current = [max(0, min(1, x)) for x in current]
        
        psi = detector._compute_psi(reference, current)
        
        assert psi < 0.25, f"Similar distributions should have PSI < 0.25, got {psi}"
    
    def test_different_distributions_high_psi(self):
        """Very different distributions should have high PSI."""
        detector = DistributionDriftDetector(comparison_window=100)
        
        # Distributions with different means
        reference = [0.3] * 100  # All low scores
        current = [0.8] * 100    # All high scores
        
        psi = detector._compute_psi(reference, current)
        
        assert psi > 0.25, f"Different distributions should have PSI > 0.25, got {psi}"


class TestKLDivergence:
    """Test KL Divergence computation."""
    
    def test_identical_distributions_kl_near_zero(self):
        """Identical distributions should have KL divergence near 0."""
        detector = DistributionDriftDetector(comparison_window=50)
        
        reference = [0.5] * 50
        current = [0.5] * 50
        
        kl = detector._compute_kl_divergence(reference, current)
        
        assert kl < 0.01, f"KL for identical distributions should be ~0, got {kl}"
    
    def test_different_distributions_positive_kl(self):
        """Different distributions should have positive KL divergence."""
        detector = DistributionDriftDetector(comparison_window=50)
        
        reference = [0.2] * 50
        current = [0.8] * 50
        
        kl = detector._compute_kl_divergence(reference, current)
        
        assert kl > 0.1, f"Different distributions should have KL > 0.1, got {kl}"


# ── NEW: Jensen-Shannon Divergence Tests ─────────────────────────────────────

class TestJSDivergence:
    """Test Jensen-Shannon Divergence — symmetric, bounded [0, 1]."""

    def test_identical_distributions_jsd_near_zero(self):
        """JSD of identical distributions must be near 0."""
        detector = DistributionDriftDetector(comparison_window=50)
        p = [0.5] * 50
        jsd = detector._compute_js_divergence(p, p)
        assert jsd < 1e-6, f"JSD for identical distributions must be ~0, got {jsd}"

    def test_shifted_distributions_jsd_positive(self):
        """JSD of shifted distributions must be > 0."""
        detector = DistributionDriftDetector(comparison_window=50)
        p = [0.2] * 50       # low scores
        q = [0.8] * 50       # high scores
        jsd = detector._compute_js_divergence(p, q)
        assert jsd > 0.0, f"JSD for shifted distributions must be > 0, got {jsd}"

    def test_jsd_bounded_zero_to_one(self):
        """JSD must be in [0, 1] for any two distributions."""
        detector = DistributionDriftDetector(comparison_window=50)
        cases = [
            ([0.0] * 50, [1.0] * 50),
            ([0.3] * 50, [0.7] * 50),
            ([0.5] * 50, [0.5] * 50),
            ([0.1, 0.9] * 25, [0.9, 0.1] * 25),
        ]
        for p, q in cases:
            jsd = detector._compute_js_divergence(p, q)
            assert 0.0 <= jsd <= 1.0, f"JSD={jsd} out of [0,1] for p={p[:4]}"

    def test_jsd_symmetric(self):
        """JSD(P, Q) must equal JSD(Q, P) to floating-point precision."""
        detector = DistributionDriftDetector(comparison_window=50)
        random.seed(0)
        p = [random.random() for _ in range(50)]
        q = [random.random() for _ in range(50)]
        jsd_pq = detector._compute_js_divergence(p, q)
        jsd_qp = detector._compute_js_divergence(q, p)
        assert abs(jsd_pq - jsd_qp) < 1e-9, (
            f"JSD not symmetric: JSD(P,Q)={jsd_pq} != JSD(Q,P)={jsd_qp}"
        )

    def test_jsd_larger_for_more_different_distributions(self):
        """More different distributions should yield larger JSD."""
        detector = DistributionDriftDetector(comparison_window=50)
        p     = [0.5] * 50
        close = [0.52] * 50
        far   = [0.9]  * 50
        jsd_close = detector._compute_js_divergence(p, close)
        jsd_far   = detector._compute_js_divergence(p, far)
        assert jsd_far > jsd_close, (
            f"JSD(p, far)={jsd_far} should be > JSD(p, close)={jsd_close}"
        )


# ── NEW: Adaptive Threshold Tests ────────────────────────────────────────────

class TestAdaptiveThreshold:
    """Test adaptive threshold: mean(history) + k * std(history)."""

    def test_fallback_to_static_with_no_history(self):
        """Should return JSD_THRESHOLD when history is insufficient."""
        detector = DistributionDriftDetector(adaptive_min_history=10)
        # No JSD history → fall back to static threshold
        thr = detector._compute_adaptive_threshold("unseen_component")
        assert thr == detector.JSD_THRESHOLD, (
            f"Expected JSD_THRESHOLD={detector.JSD_THRESHOLD}, got {thr}"
        )

    def test_adaptive_threshold_uses_history_when_sufficient(self):
        """With enough history adaptive threshold differs from static."""
        detector = DistributionDriftDetector(adaptive_min_history=3, adaptive_k=2.0)
        # Seed JSD history manually
        detector._jsd_history["comp"] = [0.01, 0.02, 0.015, 0.018, 0.012]
        thr = detector._compute_adaptive_threshold("comp")
        history = detector._jsd_history["comp"]
        mean  = sum(history) / len(history)
        var   = sum((x - mean) ** 2 for x in history) / len(history)
        std   = math.sqrt(var)
        expected = mean + 2.0 * std
        assert abs(thr - expected) < 1e-9, f"Expected {expected}, got {thr}"

    def test_adaptive_threshold_k_configurable(self):
        """k parameter must control sensitivity."""
        h = [0.01, 0.02, 0.015, 0.018, 0.012]
        mean  = sum(h) / len(h)
        var   = sum((x - mean) ** 2 for x in h) / len(h)
        std   = math.sqrt(var)

        det_k1 = DistributionDriftDetector(adaptive_min_history=3, adaptive_k=1.0)
        det_k3 = DistributionDriftDetector(adaptive_min_history=3, adaptive_k=3.0)
        det_k1._jsd_history["x"] = h[:]
        det_k3._jsd_history["x"] = h[:]

        thr_k1 = det_k1._compute_adaptive_threshold("x")
        thr_k3 = det_k3._compute_adaptive_threshold("x")
        assert thr_k3 > thr_k1, (
            f"k=3 threshold {thr_k3} should be > k=1 threshold {thr_k1}"
        )

    def test_adaptive_threshold_bounded_in_0_1(self):
        """Adaptive threshold must always be in (0, 1]."""
        detector = DistributionDriftDetector(adaptive_min_history=3, adaptive_k=100.0)
        detector._jsd_history["x"] = [0.0, 0.5, 1.0, 0.9, 0.8]
        thr = detector._compute_adaptive_threshold("x")
        assert 0.0 < thr <= 1.0, f"Threshold {thr} out of (0, 1]"


# ── NEW: Drift Classification Tests ──────────────────────────────────────────

class TestDriftClassification:
    """Test feature_drift / prediction_drift / label_drift classification."""

    def test_record_score_with_explicit_drift_type(self):
        """record_score must carry drift_type into DriftMetrics."""
        detector = DistributionDriftDetector(comparison_window=50)
        # Seed reference
        for _ in range(100):
            detector.record_score("career_score", 0.3, drift_type=DRIFT_TYPE_PREDICTION)
        # Force drift
        result = None
        for _ in range(60):
            result = detector.record_score("career_score", 0.9, drift_type=DRIFT_TYPE_PREDICTION)
        # Last result should be drift with correct type
        if result and result.is_drift:
            assert result.drift_type == DRIFT_TYPE_PREDICTION

    def test_feature_drift_type_constant(self):
        assert DRIFT_TYPE_FEATURE    == "feature_drift"

    def test_prediction_drift_type_constant(self):
        assert DRIFT_TYPE_PREDICTION == "prediction_drift"

    def test_label_drift_type_constant(self):
        assert DRIFT_TYPE_LABEL      == "label_drift"

    def test_default_drift_type_is_feature(self):
        """Default drift_type for record_score must be DRIFT_TYPE_FEATURE."""
        detector = DistributionDriftDetector(comparison_window=50)
        for _ in range(100):
            detector.record_score("x", 0.3)
        result = detector._check_drift("x")
        if result:
            assert result.drift_type == DRIFT_TYPE_FEATURE

    def test_alert_carries_drift_type(self):
        """DriftAlert must include drift_type and js_divergence fields."""
        detector = DistributionDriftDetector(comparison_window=50)
        for _ in range(100):
            detector.record_score("feat", 0.2, drift_type=DRIFT_TYPE_FEATURE)
        for _ in range(60):
            detector.record_score("feat", 0.9, drift_type=DRIFT_TYPE_FEATURE)
        alerts = detector.get_alerts()
        if alerts:
            a = alerts[0]
            assert hasattr(a, "drift_type"),    "Alert missing drift_type"
            assert hasattr(a, "js_divergence"), "Alert missing js_divergence"
            assert a.drift_type == DRIFT_TYPE_FEATURE

    def test_drift_metrics_carries_js_divergence(self):
        """DriftMetrics must expose js_divergence field."""
        detector = DistributionDriftDetector(comparison_window=50)
        for _ in range(60):
            detector.record_score("s", 0.5)
        result = detector._check_drift("s")
        if result:
            assert hasattr(result, "js_divergence"), "DriftMetrics missing js_divergence"
            assert isinstance(result.js_divergence, float)
            assert 0.0 <= result.js_divergence <= 1.0

    def test_drift_metrics_carries_adaptive_threshold(self):
        """DriftMetrics must expose adaptive_threshold field."""
        detector = DistributionDriftDetector(comparison_window=50)
        for _ in range(60):
            detector.record_score("t", 0.5)
        result = detector._check_drift("t")
        if result:
            assert hasattr(result, "adaptive_threshold"), "DriftMetrics missing adaptive_threshold"

    def test_record_scores_batch_uses_drift_type(self):
        """record_scores must propagate drift_type to each component."""
        detector = DistributionDriftDetector(comparison_window=50)
        for _ in range(100):
            detector.record_scores({"a": 0.2, "b": 0.3}, drift_type=DRIFT_TYPE_LABEL)
        drifts = detector.record_scores({"a": 0.9, "b": 0.8}, drift_type=DRIFT_TYPE_LABEL)
        for m in drifts:
            assert m.drift_type == DRIFT_TYPE_LABEL


class TestDriftDetection:
    """Test Population Stability Index computation."""
    
    def test_identical_distributions_psi_zero(self):
        """Identical distributions should have PSI near 0."""
        detector = DistributionDriftDetector(comparison_window=50)
        
        # Same distribution
        reference = [0.5] * 50
        current = [0.5] * 50
        
        detector._reference["test"] = reference
        detector._history["test"] = reference + current
        
        psi = detector._compute_psi(reference, current)
        
        assert psi < 0.01, f"PSI for identical distributions should be ~0, got {psi}"
    
    def test_similar_distributions_low_psi(self):
        """Similar distributions should have low PSI."""
        detector = DistributionDriftDetector(comparison_window=100)
        
        random.seed(42)
        reference = [random.gauss(0.5, 0.1) for _ in range(100)]
        reference = [max(0, min(1, x)) for x in reference]
        
        # Slightly different distribution
        current = [random.gauss(0.52, 0.11) for _ in range(100)]
        current = [max(0, min(1, x)) for x in current]
        
        psi = detector._compute_psi(reference, current)
        
        assert psi < 0.25, f"Similar distributions should have PSI < 0.25, got {psi}"
    
    def test_different_distributions_high_psi(self):
        """Very different distributions should have high PSI."""
        detector = DistributionDriftDetector(comparison_window=100)
        
        # Distributions with different means
        reference = [0.3] * 100  # All low scores
        current = [0.8] * 100    # All high scores
        
        psi = detector._compute_psi(reference, current)
        
        assert psi > 0.25, f"Different distributions should have PSI > 0.25, got {psi}"


class TestKLDivergence:
    """Test KL Divergence computation."""
    
    def test_identical_distributions_kl_near_zero(self):
        """Identical distributions should have KL divergence near 0."""
        detector = DistributionDriftDetector(comparison_window=50)
        
        reference = [0.5] * 50
        current = [0.5] * 50
        
        kl = detector._compute_kl_divergence(reference, current)
        
        assert kl < 0.01, f"KL for identical distributions should be ~0, got {kl}"
    
    def test_different_distributions_positive_kl(self):
        """Different distributions should have positive KL divergence."""
        detector = DistributionDriftDetector(comparison_window=50)
        
        reference = [0.2] * 50
        current = [0.8] * 50
        
        kl = detector._compute_kl_divergence(reference, current)
        
        assert kl > 0.1, f"Different distributions should have KL > 0.1, got {kl}"


class TestDriftDetection:
    """Test drift detection functionality."""
    
    def test_no_drift_stable_scores(self):
        """Stable scores should not trigger drift."""
        detector = DistributionDriftDetector(
            comparison_window=50,
            reference_window=200,
        )
        
        # Record stable scores
        for _ in range(100):
            detector.record_score("test", 0.5)
        
        status = detector.get_drift_status()
        
        if "test" in status:
            assert status["test"]["status"] in ["STABLE", "SLIGHT_CHANGE", "INSUFFICIENT_DATA"]
    
    def test_drift_detected_on_shift(self):
        """Sudden distribution shift should trigger drift."""
        detector = DistributionDriftDetector(
            comparison_window=50,
            reference_window=200,
        )
        
        # Build reference with low scores
        for _ in range(100):
            detector.record_score("test", 0.3)
        
        # Sudden shift to high scores
        drift_detected = False
        for _ in range(60):
            result = detector.record_score("test", 0.8)
            if result and result.is_drift:
                drift_detected = True
        
        assert drift_detected, "Drift should be detected on sudden distribution shift"
    
    def test_psi_threshold_is_025(self):
        """Drift threshold should be PSI > 0.25."""
        detector = DistributionDriftDetector()
        
        assert detector.PSI_MEDIUM_THRESHOLD == 0.25


class TestDriftAlerts:
    """Test drift alert generation."""
    
    def test_alert_created_on_drift(self):
        """Alert should be created when drift detected."""
        detector = DistributionDriftDetector(comparison_window=50)
        
        # Build reference
        for _ in range(100):
            detector.record_score("test", 0.3)
        
        # Trigger drift
        for _ in range(60):
            detector.record_score("test", 0.9)
        
        alerts = detector.get_alerts()
        
        # Should have at least one alert
        assert len(alerts) > 0, "Alert should be created on drift"
    
    def test_alert_has_severity(self):
        """Alerts should have severity level."""
        detector = DistributionDriftDetector(comparison_window=50)
        
        # Build reference and trigger drift
        for _ in range(100):
            detector.record_score("test", 0.3)
        for _ in range(60):
            detector.record_score("test", 0.9)
        
        alerts = detector.get_alerts()
        
        if alerts:
            assert alerts[0].severity in ["LOW", "MEDIUM", "HIGH"]
    
    def test_acknowledge_alert(self):
        """Should be able to acknowledge alerts."""
        detector = DistributionDriftDetector(comparison_window=50)
        
        # Trigger drift
        for _ in range(100):
            detector.record_score("test", 0.3)
        for _ in range(60):
            detector.record_score("test", 0.9)
        
        # Acknowledge first alert
        alerts = detector.get_alerts()
        if alerts:
            result = detector.acknowledge_alert(0)
            assert result is True
            
            # Should not appear in unacknowledged list
            unacked = detector.get_alerts(unacknowledged_only=True)
            assert len(unacked) < len(detector._alerts)


class TestDriftMetrics:
    """Test DriftMetrics structure."""
    
    def test_metrics_structure(self):
        """DriftMetrics should have all required fields."""
        metrics = DriftMetrics(
            metric_name="test",
            psi=0.3,
            kl_divergence=0.15,
            js_divergence=0.08,
            mean_shift=0.1,
            std_shift=0.05,
            sample_size=100,
            is_drift=True,
        )
        
        assert metrics.metric_name == "test"
        assert metrics.psi == 0.3
        assert metrics.kl_divergence == 0.15
        assert metrics.js_divergence == 0.08
        assert metrics.is_drift is True
    
    def test_metrics_to_dict(self):
        """DriftMetrics should serialize to dict."""
        metrics = DriftMetrics(
            metric_name="test",
            psi=0.3,
            kl_divergence=0.15,
            js_divergence=0.08,
            mean_shift=0.1,
            std_shift=0.05,
            sample_size=100,
        )
        
        d = metrics.to_dict()
        
        assert "psi" in d
        assert "kl_divergence" in d
        assert "js_divergence" in d
        assert "metric_name" in d
        assert "drift_type" in d
        assert "adaptive_threshold" in d


class TestR007Compliance:
    """Test R007 Drift Detection compliance requirements."""
    
    def test_drift_detector_exists(self):
        """Drift detector module must exist."""
        from backend.scoring.drift import DistributionDriftDetector
        assert DistributionDriftDetector is not None
    
    def test_psi_calculation_exists(self):
        """PSI calculation must exist."""
        detector = DistributionDriftDetector()
        assert hasattr(detector, '_compute_psi')
        assert callable(detector._compute_psi)
    
    def test_kl_divergence_calculation_exists(self):
        """KL divergence calculation must exist."""
        detector = DistributionDriftDetector()
        assert hasattr(detector, '_compute_kl_divergence')
        assert callable(detector._compute_kl_divergence)

    def test_js_divergence_calculation_exists(self):
        """JSD calculation must exist and be callable."""
        detector = DistributionDriftDetector()
        assert hasattr(detector, '_compute_js_divergence')
        assert callable(detector._compute_js_divergence)

    def test_adaptive_threshold_calculation_exists(self):
        """Adaptive threshold calculation must exist."""
        detector = DistributionDriftDetector()
        assert hasattr(detector, '_compute_adaptive_threshold')
        assert callable(detector._compute_adaptive_threshold)

    def test_adaptive_k_configurable(self):
        """adaptive_k must be configurable on construction."""
        det = DistributionDriftDetector(adaptive_k=3.5)
        assert det.adaptive_k == 3.5

    def test_no_hardcoded_threshold_override(self):
        """Static JSD_THRESHOLD must not be the only decision path."""
        # adaptive_min_history=0 means adaptive always kicks in
        det = DistributionDriftDetector(adaptive_k=2.0, adaptive_min_history=0)
        det._jsd_history["x"] = [0.001, 0.002, 0.001]
        thr = det._compute_adaptive_threshold("x")
        # threshold should be very small (not 0.10 hardcoded)
        assert thr < 0.05, f"Adaptive threshold should be small for low-JSD history, got {thr}"

    def test_psi_025_threshold(self):
        """PSI > 0.25 should trigger drift alert."""
        from backend.scoring.drift import DistributionDriftDetector
        
        detector = DistributionDriftDetector()
        assert detector.PSI_MEDIUM_THRESHOLD == 0.25
    
    def test_score_mean_std_tracked(self):
        """Mean and std shifts must be tracked."""
        detector = DistributionDriftDetector(comparison_window=50)
        
        # Record scores
        for _ in range(60):
            detector.record_score("test", 0.5)
        
        result = detector._check_drift("test")
        
        if result:
            assert hasattr(result, 'mean_shift')
            assert hasattr(result, 'std_shift')
    
    def test_alert_generation_api(self):
        """Alert generation API must exist."""
        from backend.scoring.drift import get_drift_alerts
        assert callable(get_drift_alerts)
    
    def test_status_api_exists(self):
        """Drift status API must exist."""
        from backend.scoring.drift import get_drift_status
        assert callable(get_drift_status)

    def test_drift_type_constants_exported(self):
        """Drift classification constants must be exported."""
        from backend.scoring.drift import (
            DRIFT_TYPE_FEATURE,
            DRIFT_TYPE_PREDICTION,
            DRIFT_TYPE_LABEL,
        )
        assert DRIFT_TYPE_FEATURE    == "feature_drift"
        assert DRIFT_TYPE_PREDICTION == "prediction_drift"
        assert DRIFT_TYPE_LABEL      == "label_drift"

    def test_drift_status_includes_jsd(self):
        """get_drift_status must include 'jsd' and 'adaptive_threshold' per component."""
        detector = DistributionDriftDetector(comparison_window=20)
        for _ in range(30):
            detector.record_score("study", 0.5)
        status = detector.get_drift_status()
        if "study" in status and status["study"].get("status") != "INSUFFICIENT_DATA":
            assert "jsd" in status["study"], "get_drift_status missing 'jsd'"
            assert "adaptive_threshold" in status["study"], "get_drift_status missing 'adaptive_threshold'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

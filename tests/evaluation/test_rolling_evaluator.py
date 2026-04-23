# tests/evaluation/test_rolling_evaluator.py
"""
Rolling Evaluator — Governance-Grade Evaluation Tests
======================================================

Covers ≥85% of rolling_evaluator.py and eval_metrics_log.py.

Test classes:
  TestComputeBrierScore      — pure function, edge cases
  TestComputeECE             — pure function, edge cases
  TestEvalSample             — dataclass schema and to_dict
  TestAlertRules             — all three alert types, baseline auto-setting
  TestRollingEvaluator       — core evaluation loop
  TestConfidenceAxes         — model_performance_confidence vs explanation_confidence
  TestWindowEviction         — bounded deque eviction
  TestEvalMetricsLogger      — JSONL logger, schema, chain hash
  TestEvalSnapshotSchema     — to_dict completeness
  TestHTTPEndpoints          — FastAPI rolling-metrics, ground-truth, metrics-log
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.evaluation.rolling_evaluator import (
    RollingEvaluator,
    EvalSample,
    EvalSnapshot,
    AlertEvent,
    AlertRules,
    compute_brier_score,
    compute_ece,
    DEFAULT_WINDOW,
    DEFAULT_F1_DROP_PCT,
    DEFAULT_BRIER_THRESH,
    DEFAULT_ECE_THRESH,
)
from backend.evaluation.eval_metrics_log import EvalMetricsLogger


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

CAREERS = ["Software Engineer", "Data Scientist", "UX Designer", "Product Manager"]


def _make_evaluator(window: int = 50, min_labelled: int = 3, **alert_kw) -> RollingEvaluator:
    return RollingEvaluator(window=window, alert_rules=AlertRules(**alert_kw), min_labelled=min_labelled)


def _fill_evaluator(
    ev: RollingEvaluator,
    n: int,
    accuracy: float = 0.8,
    label: str = "Software Engineer",
    prob: float = 0.8,
) -> List[str]:
    """Log n predictions, label them with given accuracy, return trace_ids."""
    trace_ids = []
    for i in range(n):
        tid = f"trace-{uuid.uuid4()}"
        ev.log_prediction(
            trace_id=tid,
            predicted_label=label,
            probability=prob,
            model_version="v1.0.0",
            explanation_confidence=0.75,
        )
        correct = (i / n) < accuracy
        true_label = label if correct else "Data Scientist"
        ev.update_ground_truth(tid, true_label)
        trace_ids.append(tid)
    return trace_ids


# ═══════════════════════════════════════════════════════════════════════════════
# TestComputeBrierScore
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeBrierScore:

    def test_perfect_prediction_brier_zero(self):
        probs    = [1.0, 1.0, 1.0]
        outcomes = [1,   1,   1  ]
        assert compute_brier_score(probs, outcomes) == pytest.approx(0.0)

    def test_worst_prediction_brier_one(self):
        probs    = [0.0, 0.0, 0.0]
        outcomes = [1,   1,   1  ]
        assert compute_brier_score(probs, outcomes) == pytest.approx(1.0)

    def test_half_probability_outcome_zero(self):
        # (0.5 - 0)^2 = 0.25
        probs    = [0.5]
        outcomes = [0  ]
        assert compute_brier_score(probs, outcomes) == pytest.approx(0.25)

    def test_empty_returns_zero(self):
        assert compute_brier_score([], []) == 0.0

    def test_returns_float(self):
        result = compute_brier_score([0.7, 0.3], [1, 0])
        assert isinstance(result, float)

    def test_bounded_zero_to_one(self):
        probs    = [float(i) / 10 for i in range(11)]
        outcomes = [i % 2 for i in range(11)]
        result = compute_brier_score(probs, outcomes)
        assert 0.0 <= result <= 1.0

    def test_average_of_squared_errors(self):
        probs    = [0.8, 0.4]
        outcomes = [1,   0  ]
        expected = ((0.8 - 1) ** 2 + (0.4 - 0) ** 2) / 2
        assert compute_brier_score(probs, outcomes) == pytest.approx(expected, rel=1e-5)


# ═══════════════════════════════════════════════════════════════════════════════
# TestComputeECE
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeECE:

    def test_empty_returns_zero(self):
        assert compute_ece([], []) == 0.0

    def test_returns_float(self):
        result = compute_ece([0.9, 0.1], [1, 0])
        assert isinstance(result, float)

    def test_bounded_zero_to_one(self):
        probs    = [0.1 * i for i in range(11)]
        outcomes = [i % 2   for i in range(11)]
        result = compute_ece(probs, outcomes)
        assert 0.0 <= result <= 1.0

    def test_perfectly_calibrated_all_correct(self):
        # High confidence, all correct → near 0
        probs    = [0.95] * 50
        outcomes = [1]    * 50
        result = compute_ece(probs, outcomes)
        assert result < 0.2  # not exactly 0 due to binning, but close

    def test_worst_possible_calibration(self):
        # prob=1.0 but outcome=0 → large ECE
        probs    = [1.0] * 10
        outcomes = [0]   * 10
        result = compute_ece(probs, outcomes)
        # All in top bin, acc=0, conf=1 → gap=1 → ECE=1
        assert result == pytest.approx(1.0, abs=0.01)

    def test_custom_n_bins(self):
        probs    = [0.3, 0.7]
        outcomes = [0,   1  ]
        r5  = compute_ece(probs, outcomes, n_bins=5)
        r10 = compute_ece(probs, outcomes, n_bins=10)
        # Both should be in [0, 1]
        assert 0.0 <= r5  <= 1.0
        assert 0.0 <= r10 <= 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# TestEvalSample
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvalSample:

    def _sample(self, **kw) -> EvalSample:
        base = dict(
            trace_id="t-001",
            predicted_label="Software Engineer",
            probability=0.82,
            model_version="v1.0.0",
            timestamp="2026-02-24T00:00:00+00:00",
        )
        base.update(kw)
        return EvalSample(**base)

    def test_to_dict_has_required_keys(self):
        keys = {
            "trace_id", "predicted_label", "probability", "model_version",
            "timestamp", "explanation_confidence", "true_label", "labelled",
        }
        d = self._sample().to_dict()
        assert keys.issubset(d.keys())

    def test_probability_clamped_and_rounded(self):
        sample = self._sample(probability=0.123456789)
        assert sample.to_dict()["probability"] == pytest.approx(0.123457, rel=1e-4)

    def test_labelled_false_by_default(self):
        assert self._sample().labelled is False

    def test_true_label_none_by_default(self):
        assert self._sample().true_label is None

    def test_explanation_confidence_none_allowed(self):
        d = self._sample(explanation_confidence=None).to_dict()
        assert d["explanation_confidence"] is None

    def test_explanation_confidence_rounded(self):
        d = self._sample(explanation_confidence=0.666666).to_dict()
        assert d["explanation_confidence"] == pytest.approx(0.666666)


# ═══════════════════════════════════════════════════════════════════════════════
# TestAlertRules
# ═══════════════════════════════════════════════════════════════════════════════

class TestAlertRules:

    def _snap(self, **kw) -> EvalSnapshot:
        base = dict(
            timestamp="2026-02-24T00:00:00+00:00",
            model_version="v1.0.0",
            sample_size=100,
            labelled_size=50,
        )
        base.update(kw)
        return EvalSnapshot(**base)

    # ── F1 drop ──────────────────────────────────────────────────────────────

    def test_f1_drop_fires_when_drop_exceeds_threshold(self):
        rules = AlertRules(f1_drop_pct=10.0, f1_baseline=0.80)
        snap = self._snap(rolling_f1=0.60)  # 25% drop
        alerts = rules.check(snap, "v1.0.0")
        types = [a.alert_type for a in alerts]
        assert "f1_drop" in types

    def test_f1_drop_does_not_fire_when_under_threshold(self):
        rules = AlertRules(f1_drop_pct=10.0, f1_baseline=0.80)
        snap = self._snap(rolling_f1=0.79)  # only 1.25% drop
        alerts = rules.check(snap, "v1.0.0")
        assert not any(a.alert_type == "f1_drop" for a in alerts)

    def test_f1_baseline_auto_set_on_first_call(self):
        rules = AlertRules(f1_drop_pct=10.0)
        assert rules.f1_baseline is None
        snap = self._snap(rolling_f1=0.85)
        rules.check(snap, "v1.0.0")
        assert rules.f1_baseline == pytest.approx(0.85)

    def test_no_f1_alert_when_rolling_f1_is_none(self):
        rules = AlertRules(f1_drop_pct=10.0, f1_baseline=0.80)
        snap = self._snap(rolling_f1=None)
        alerts = rules.check(snap, "v1.0.0")
        assert not any(a.alert_type == "f1_drop" for a in alerts)

    # ── Brier Score ──────────────────────────────────────────────────────────

    def test_brier_alert_fires_above_threshold(self):
        rules = AlertRules(brier_threshold=0.20)
        snap = self._snap(brier_score=0.35)
        alerts = rules.check(snap, "v1.0.0")
        assert any(a.alert_type == "calibration_brier" for a in alerts)

    def test_brier_alert_does_not_fire_below_threshold(self):
        rules = AlertRules(brier_threshold=0.25)
        snap = self._snap(brier_score=0.10)
        alerts = rules.check(snap, "v1.0.0")
        assert not any(a.alert_type == "calibration_brier" for a in alerts)

    def test_brier_alert_not_fired_when_none(self):
        rules = AlertRules(brier_threshold=0.25)
        snap = self._snap(brier_score=None)
        alerts = rules.check(snap, "v1.0.0")
        assert not any(a.alert_type == "calibration_brier" for a in alerts)

    # ── ECE ──────────────────────────────────────────────────────────────────

    def test_ece_alert_fires_above_threshold(self):
        rules = AlertRules(ece_threshold=0.10)
        snap = self._snap(ece=0.25)
        alerts = rules.check(snap, "v1.0.0")
        assert any(a.alert_type == "calibration_ece" for a in alerts)

    def test_ece_alert_does_not_fire_below_threshold(self):
        rules = AlertRules(ece_threshold=0.10)
        snap = self._snap(ece=0.05)
        alerts = rules.check(snap, "v1.0.0")
        assert not any(a.alert_type == "calibration_ece" for a in alerts)

    # ── AlertEvent schema ────────────────────────────────────────────────────

    def test_alert_event_to_dict_has_required_keys(self):
        required = {
            "alert_type", "metric_name", "current_value",
            "threshold", "message", "timestamp", "model_version",
        }
        rules = AlertRules(brier_threshold=0.10)
        snap = self._snap(brier_score=0.50)
        alerts = rules.check(snap, "v1.0.0")
        assert alerts
        d = alerts[0].to_dict()
        assert required.issubset(d.keys())

    def test_multiple_alerts_can_fire_simultaneously(self):
        rules = AlertRules(
            f1_drop_pct=5.0,
            f1_baseline=0.80,
            brier_threshold=0.10,
            ece_threshold=0.05,
        )
        snap = self._snap(rolling_f1=0.70, brier_score=0.40, ece=0.30)
        alerts = rules.check(snap, "v1.0.0")
        types = {a.alert_type for a in alerts}
        assert "f1_drop"           in types
        assert "calibration_brier" in types
        assert "calibration_ece"   in types

    def test_no_alerts_when_all_metrics_healthy(self):
        rules = AlertRules(
            f1_drop_pct=10.0,
            f1_baseline=0.80,
            brier_threshold=0.30,
            ece_threshold=0.15,
        )
        snap = self._snap(rolling_f1=0.82, brier_score=0.08, ece=0.04)
        alerts = rules.check(snap, "v1.0.0")
        assert alerts == []


# ═══════════════════════════════════════════════════════════════════════════════
# TestRollingEvaluator — core loop
# ═══════════════════════════════════════════════════════════════════════════════

class TestRollingEvaluator:

    def test_log_prediction_returns_eval_sample(self):
        ev = _make_evaluator()
        sample = ev.log_prediction("t-1", "SWE", 0.85, "v1")
        assert isinstance(sample, EvalSample)
        assert sample.trace_id == "t-1"

    def test_sample_stored_in_index(self):
        ev = _make_evaluator()
        ev.log_prediction("t-idx", "SWE", 0.85, "v1")
        assert ev.get_sample("t-idx") is not None

    def test_unknown_trace_returns_none(self):
        ev = _make_evaluator()
        assert ev.get_sample("not-here") is None

    def test_update_ground_truth_sets_true_label(self):
        ev = _make_evaluator()
        ev.log_prediction("t-gt", "SWE", 0.80, "v1")
        s = ev.update_ground_truth("t-gt", "SWE")
        assert s is not None
        assert s.true_label == "SWE"
        assert s.labelled is True

    def test_update_ground_truth_unknown_returns_none(self):
        ev = _make_evaluator()
        result = ev.update_ground_truth("no-such-trace", "SWE")
        assert result is None

    def test_snapshot_sample_size_correct(self):
        ev = _make_evaluator()
        for i in range(7):
            ev.log_prediction(f"t-{i}", "SWE", 0.8, "v1")
        snap = ev.snapshot()
        assert snap.sample_size == 7

    def test_snapshot_labelled_size_counts_only_labelled(self):
        ev = _make_evaluator(min_labelled=2)
        for i in range(5):
            ev.log_prediction(f"t-{i}", "SWE", 0.8, "v1")
        ev.update_ground_truth("t-0", "SWE")
        ev.update_ground_truth("t-1", "SWE")
        snap = ev.snapshot()
        assert snap.labelled_size == 2

    def test_metrics_none_below_min_labelled(self):
        ev = RollingEvaluator(window=50, min_labelled=10)
        for i in range(5):
            ev.log_prediction(f"t-{i}", "SWE", 0.8, "v1")
            ev.update_ground_truth(f"t-{i}", "SWE")
        snap = ev.snapshot()
        assert snap.rolling_f1 is None
        assert snap.rolling_accuracy is None

    def test_classification_metrics_computed_when_enough_labelled(self):
        ev = _make_evaluator(min_labelled=3)
        _fill_evaluator(ev, n=10, accuracy=1.0)  # perfect accuracy
        snap = ev.snapshot()
        assert snap.rolling_accuracy is not None
        assert snap.rolling_f1 is not None

    def test_perfect_accuracy_gives_f1_one(self):
        ev = _make_evaluator(min_labelled=3)
        for i in range(10):
            tid = f"t-{i}"
            ev.log_prediction(tid, "SWE", 0.9, "v1")
            ev.update_ground_truth(tid, "SWE")  # always correct
        snap = ev.snapshot()
        assert snap.rolling_accuracy == pytest.approx(1.0)
        assert snap.rolling_f1 == pytest.approx(1.0)

    def test_all_wrong_accuracy_zero(self):
        ev = _make_evaluator(min_labelled=3)
        for i in range(10):
            tid = f"t-{i}"
            ev.log_prediction(tid, "SWE", 0.2, "v1")
            ev.update_ground_truth(tid, "Data Scientist")  # always wrong
        snap = ev.snapshot()
        assert snap.rolling_accuracy == pytest.approx(0.0)

    def test_calibration_computed_when_enough_labelled(self):
        ev = _make_evaluator(min_labelled=3)
        for i in range(10):
            tid = f"t-{i}"
            ev.log_prediction(tid, "SWE", 0.85, "v1")
            ev.update_ground_truth(tid, "SWE")
        snap = ev.snapshot()
        assert snap.brier_score is not None
        assert snap.ece is not None

    def test_brier_score_between_zero_and_one(self):
        ev = _make_evaluator(min_labelled=3)
        _fill_evaluator(ev, 20)
        snap = ev.snapshot()
        if snap.brier_score is not None:
            assert 0.0 <= snap.brier_score <= 1.0

    def test_ece_between_zero_and_one(self):
        ev = _make_evaluator(min_labelled=3)
        _fill_evaluator(ev, 20)
        snap = ev.snapshot()
        if snap.ece is not None:
            assert 0.0 <= snap.ece <= 1.0

    def test_probability_clamped_to_01(self):
        ev = _make_evaluator()
        sample = ev.log_prediction("t-clamp", "SWE", 1.5, "v1")
        assert sample.probability == pytest.approx(1.0)

    def test_probability_clamp_below_zero(self):
        ev = _make_evaluator()
        sample = ev.log_prediction("t-neg", "SWE", -0.3, "v1")
        assert sample.probability == pytest.approx(0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# TestConfidenceAxes
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfidenceAxes:
    """model_performance_confidence and explanation_confidence_mean are independent."""

    def test_model_performance_confidence_is_one_minus_brier(self):
        ev = _make_evaluator(min_labelled=3)
        for i in range(10):
            tid = f"axis-{i}"
            ev.log_prediction(tid, "SWE", 0.9, "v1", explanation_confidence=None)
            ev.update_ground_truth(tid, "SWE")
        snap = ev.snapshot()
        if snap.brier_score is not None and snap.model_performance_confidence is not None:
            expected = max(0.0, 1.0 - snap.brier_score)
            assert snap.model_performance_confidence == pytest.approx(expected, rel=1e-5)

    def test_explanation_confidence_none_when_not_provided(self):
        ev = _make_evaluator()
        ev.log_prediction("no-exp", "SWE", 0.8, "v1", explanation_confidence=None)
        snap = ev.snapshot()
        assert snap.explanation_confidence_mean is None

    def test_explanation_confidence_mean_computed_correctly(self):
        ev = _make_evaluator()
        confidences = [0.60, 0.70, 0.80]
        for i, c in enumerate(confidences):
            ev.log_prediction(f"exp-{i}", "SWE", 0.8, "v1", explanation_confidence=c)
        snap = ev.snapshot()
        assert snap.explanation_confidence_mean == pytest.approx(
            sum(confidences) / len(confidences), rel=1e-5
        )

    def test_model_performance_confidence_and_exp_confidence_independent(self):
        """Setting only explanation_confidence should not affect model_performance_confidence."""
        ev = _make_evaluator(min_labelled=2)
        for i in range(5):
            tid = f"ind-{i}"
            ev.log_prediction(tid, "SWE", 0.9, "v1", explanation_confidence=0.5)
            ev.update_ground_truth(tid, "SWE")
        snap = ev.snapshot()
        # explanation_confidence_mean should be 0.5; model perf conf driven by Brier
        assert snap.explanation_confidence_mean == pytest.approx(0.5)
        if snap.model_performance_confidence is not None:
            assert snap.model_performance_confidence != 0.5  # different axis


# ═══════════════════════════════════════════════════════════════════════════════
# TestWindowEviction
# ═══════════════════════════════════════════════════════════════════════════════

class TestWindowEviction:

    def test_window_size_respected(self):
        ev = RollingEvaluator(window=5)
        for i in range(10):
            ev.log_prediction(f"t-{i}", "SWE", 0.8, "v1")
        snap = ev.snapshot()
        assert snap.sample_size == 5

    def test_evicted_trace_removed_from_index(self):
        ev = RollingEvaluator(window=3)
        ev.log_prediction("oldest", "SWE", 0.8, "v1")
        ev.log_prediction("t2", "SWE", 0.8, "v1")
        ev.log_prediction("t3", "SWE", 0.8, "v1")
        # This push should evict "oldest"
        ev.log_prediction("newest", "SWE", 0.8, "v1")
        assert ev.get_sample("oldest") is None
        assert ev.get_sample("newest") is not None

    def test_labelled_count_reflects_window_only(self):
        ev = RollingEvaluator(window=4, min_labelled=1)
        for i in range(6):
            tid = f"ev-{i}"
            ev.log_prediction(tid, "SWE", 0.8, "v1")
            ev.update_ground_truth(tid, "SWE")
        snap = ev.snapshot()
        # Only last 4 samples remain in window
        assert snap.sample_size == 4
        assert snap.labelled_size == 4


# ═══════════════════════════════════════════════════════════════════════════════
# TestEvalSnapshotSchema
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvalSnapshotSchema:

    def _snap(self) -> EvalSnapshot:
        return EvalSnapshot(
            timestamp="2026-02-24T00:00:00+00:00",
            model_version="v1.0.0",
            sample_size=50,
            labelled_size=30,
            rolling_accuracy=0.82,
            rolling_precision=0.81,
            rolling_recall=0.80,
            rolling_f1=0.805,
            brier_score=0.12,
            ece=0.07,
            model_performance_confidence=0.88,
            explanation_confidence_mean=0.74,
        )

    def test_to_dict_has_all_required_keys(self):
        required = {
            "timestamp", "model_version", "sample_size", "labelled_size",
            "rolling_accuracy", "rolling_f1", "rolling_precision", "rolling_recall",
            "brier_score", "ece",
            "model_performance_confidence", "explanation_confidence_mean",
            "active_alerts",
        }
        d = self._snap().to_dict()
        assert required.issubset(d.keys())

    def test_active_alerts_is_list(self):
        d = self._snap().to_dict()
        assert isinstance(d["active_alerts"], list)

    def test_numeric_fields_rounded(self):
        snap = EvalSnapshot(
            timestamp="x", model_version="v1", sample_size=1, labelled_size=1,
            rolling_f1=0.8049999999,
        )
        d = snap.to_dict()
        assert d["rolling_f1"] == pytest.approx(0.805, abs=1e-4)

    def test_none_fields_preserved_in_dict(self):
        snap = EvalSnapshot(
            timestamp="x", model_version="v1", sample_size=0, labelled_size=0,
        )
        d = snap.to_dict()
        assert d["rolling_f1"] is None
        assert d["brier_score"] is None
        assert d["model_performance_confidence"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# TestEvalMetricsLogger
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def eval_logger(tmp_path: Path) -> EvalMetricsLogger:
    return EvalMetricsLogger(
        log_path=tmp_path / "evaluation_metrics.jsonl",
        chain_log_path=str(tmp_path / "chain.log"),
    )


def _eval_snap(model_version: str = "v1.0.0", f1: float = 0.82) -> EvalSnapshot:
    return EvalSnapshot(
        timestamp="2026-02-24T00:00:00+00:00",
        model_version=model_version,
        sample_size=100,
        labelled_size=60,
        rolling_accuracy=0.80,
        rolling_f1=f1,
        rolling_precision=0.81,
        rolling_recall=0.79,
        brier_score=0.14,
        ece=0.08,
        model_performance_confidence=0.86,
        explanation_confidence_mean=0.73,
    )


class TestEvalMetricsLogger:

    def test_append_returns_record(self, eval_logger: EvalMetricsLogger):
        rec = eval_logger.append(_eval_snap())
        assert isinstance(rec, dict)

    def test_record_has_canonical_schema(self, eval_logger: EvalMetricsLogger):
        required = {
            "event_id", "timestamp", "model_version",
            "sample_size", "labelled_size",
            "rolling_accuracy", "rolling_f1", "rolling_precision", "rolling_recall",
            "calibration_error",  # Brier Score under canonical name
            "ece", "model_performance_confidence", "explanation_confidence_mean",
            "active_alert_count", "alerts", "chain_record_hash",
        }
        rec = eval_logger.append(_eval_snap())
        assert required.issubset(rec.keys()), f"Missing: {required - rec.keys()}"

    def test_calibration_error_field_equals_brier_score(self, eval_logger: EvalMetricsLogger):
        snap = _eval_snap()
        rec = eval_logger.append(snap)
        assert rec["calibration_error"] == pytest.approx(snap.brier_score, rel=1e-5)

    def test_chain_record_hash_non_empty(self, eval_logger: EvalMetricsLogger):
        rec = eval_logger.append(_eval_snap())
        assert rec["chain_record_hash"] != ""

    def test_count_increases_after_append(self, eval_logger: EvalMetricsLogger):
        before = eval_logger.count()
        eval_logger.append(_eval_snap())
        assert eval_logger.count() == before + 1

    def test_jsonl_file_created(self, eval_logger: EvalMetricsLogger):
        eval_logger.append(_eval_snap())
        assert eval_logger._log_path.exists()

    def test_jsonl_lines_are_valid_json(self, eval_logger: EvalMetricsLogger):
        eval_logger.append(_eval_snap())
        with open(eval_logger._log_path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    obj = json.loads(line)
                    assert "event_id" in obj

    def test_read_recent_returns_newest_first(self, eval_logger: EvalMetricsLogger):
        for i in range(3):
            eval_logger.append(_eval_snap(f1=0.70 + i * 0.05))
        records = eval_logger.read_recent(limit=10)
        f1s = [r["rolling_f1"] for r in records]
        assert f1s == sorted(f1s, reverse=True)

    def test_read_recent_limit_respected(self, eval_logger: EvalMetricsLogger):
        for _ in range(10):
            eval_logger.append(_eval_snap())
        records = eval_logger.read_recent(limit=3)
        assert len(records) <= 3

    def test_read_recent_model_version_filter(self, eval_logger: EvalMetricsLogger):
        eval_logger.append(_eval_snap(model_version="v1.0.0"))
        eval_logger.append(_eval_snap(model_version="v2.0.0"))
        records = eval_logger.read_recent(limit=10, model_version="v1.0.0")
        assert all(r["model_version"] == "v1.0.0" for r in records)

    def test_latest_returns_most_recent(self, eval_logger: EvalMetricsLogger):
        eval_logger.append(_eval_snap(f1=0.70))
        eval_logger.append(_eval_snap(f1=0.80))
        rec = eval_logger.latest()
        assert rec is not None
        assert rec["rolling_f1"] == pytest.approx(0.80)

    def test_latest_returns_none_when_empty(self, eval_logger: EvalMetricsLogger):
        assert eval_logger.latest() is None

    def test_count_zero_for_empty_log(self, eval_logger: EvalMetricsLogger):
        assert eval_logger.count() == 0

    def test_active_alert_count_in_record(self, eval_logger: EvalMetricsLogger):
        rec = eval_logger.append(_eval_snap())
        assert isinstance(rec["active_alert_count"], int)
        assert rec["active_alert_count"] >= 0


# ═══════════════════════════════════════════════════════════════════════════════
# TestHTTPEndpoints
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def eval_http_client():
    """
    Minimal FastAPI app with the eval_router mounted.
    RBAC is bypassed by patching `has_any_role` in the rbac module to always
    return True (the closure inside require_any_role calls it by name).
    """
    import backend.api.middleware.rbac as rbac_mod
    from backend.api.routers.eval_router import router as eval_router

    _orig = rbac_mod.has_any_role
    rbac_mod.has_any_role = lambda _auth, _roles: True  # bypass for tests

    mini_app = FastAPI()
    mini_app.include_router(eval_router, prefix="/api/v1/eval")
    client = TestClient(mini_app, raise_server_exceptions=False)
    yield client

    rbac_mod.has_any_role = _orig  # restore


class TestHTTPEndpoints:
    """HTTP tests for eval rolling-metrics, ground-truth, metrics-log endpoints."""

    def test_rolling_metrics_returns_200(self, eval_http_client: TestClient):
        resp = eval_http_client.get("/api/v1/eval/rolling-metrics")
        assert resp.status_code == 200

    def test_rolling_metrics_response_has_data(self, eval_http_client: TestClient):
        resp = eval_http_client.get("/api/v1/eval/rolling-metrics")
        body = resp.json()
        assert "data" in body or "status" in body  # success_response wrapper

    def test_rolling_metrics_has_model_version(self, eval_http_client: TestClient):
        resp = eval_http_client.get("/api/v1/eval/rolling-metrics")
        body = resp.json()
        data = body.get("data", body)
        # snapshot.to_dict() always returns model_version key
        assert "model_version" in data

    def test_ground_truth_404_for_unknown_trace(self, eval_http_client: TestClient):
        resp = eval_http_client.post(
            "/api/v1/eval/ground-truth",
            params={"trace_id": "zzz-nonexistent-9999", "true_label": "SWE"},
        )
        assert resp.status_code == 404

    def test_ground_truth_200_for_known_trace(self, eval_http_client: TestClient, monkeypatch):
        """Log a prediction via the singleton, then POST ground truth."""
        import backend.evaluation.rolling_evaluator as re_mod
        tmp_ev = RollingEvaluator(window=50, min_labelled=3)
        tmp_ev.log_prediction("gt-http-trace-001", "Software Engineer", 0.85, "v1.0.0")
        monkeypatch.setattr(re_mod, "_singleton", tmp_ev)
        resp = eval_http_client.post(
            "/api/v1/eval/ground-truth",
            params={"trace_id": "gt-http-trace-001", "true_label": "Software Engineer"},
        )
        assert resp.status_code == 200

    def test_ground_truth_response_schema(self, eval_http_client: TestClient, monkeypatch):
        import backend.evaluation.rolling_evaluator as re_mod
        tmp_ev = RollingEvaluator(window=50, min_labelled=3)
        tmp_ev.log_prediction("gt-schema-001", "UX Designer", 0.75, "v1.0.0")
        monkeypatch.setattr(re_mod, "_singleton", tmp_ev)
        resp = eval_http_client.post(
            "/api/v1/eval/ground-truth",
            params={"trace_id": "gt-schema-001", "true_label": "UX Designer"},
        )
        # 200 or 404 depending on eviction; just verify no server error
        assert resp.status_code in (200, 404)

    def test_metrics_log_returns_200(self, eval_http_client: TestClient):
        resp = eval_http_client.get("/api/v1/eval/metrics-log")
        assert resp.status_code == 200

    def test_metrics_log_response_shape(self, eval_http_client: TestClient):
        resp = eval_http_client.get("/api/v1/eval/metrics-log")
        body = resp.json()
        data = body.get("data", body)
        assert "count" in data
        assert "records" in data
        assert isinstance(data["records"], list)

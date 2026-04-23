# backend/tests/test_calibration.py
"""
Comprehensive tests for Confidence Calibration module.

Tests:
    - Brier Score computation
    - Expected Calibration Error (ECE)
    - Reliability diagram data generation
    - CalibrationDataset persistence
"""

import json
import pytest
from pathlib import Path

from backend.explain.calibration import (
    CalibrationSample,
    CalibrationBin,
    CalibrationReport,
    ConfidenceCalibrator,
    CalibrationDataset,
)


class TestCalibrationSample:
    """Tests for CalibrationSample dataclass."""

    def test_sample_creation(self):
        sample = CalibrationSample(
            trace_id="trace_001",
            predicted_confidence=0.85,
            actual_outcome=1,
        )
        assert sample.trace_id == "trace_001"
        assert sample.predicted_confidence == 0.85
        assert sample.actual_outcome == 1

    def test_confidence_clamping_high(self):
        sample = CalibrationSample(
            trace_id="trace_002",
            predicted_confidence=1.5,  # Above 1.0
            actual_outcome=1,
        )
        assert sample.predicted_confidence == 1.0

    def test_confidence_clamping_low(self):
        sample = CalibrationSample(
            trace_id="trace_003",
            predicted_confidence=-0.2,  # Below 0.0
            actual_outcome=0,
        )
        assert sample.predicted_confidence == 0.0

    def test_outcome_binary_conversion(self):
        sample = CalibrationSample(
            trace_id="trace_004",
            predicted_confidence=0.5,
            actual_outcome=5,  # Non-binary
        )
        assert sample.actual_outcome == 1  # Converted to 1


class TestCalibrationBin:
    """Tests for CalibrationBin dataclass."""

    def test_empty_bin(self):
        bin_ = CalibrationBin(bin_start=0.0, bin_end=0.1)
        assert bin_.count == 0
        assert bin_.mean_confidence == 0.0
        assert bin_.accuracy == 0.0
        assert bin_.gap == 0.0

    def test_bin_metrics(self):
        bin_ = CalibrationBin(
            bin_start=0.8,
            bin_end=0.9,
            count=10,
            sum_confidence=8.5,  # avg = 0.85
            sum_outcome=7.0,  # accuracy = 0.7
        )
        assert bin_.mean_confidence == 0.85
        assert bin_.accuracy == 0.7
        assert bin_.gap == pytest.approx(0.15, abs=0.001)

    def test_bin_to_dict(self):
        bin_ = CalibrationBin(
            bin_start=0.5,
            bin_end=0.6,
            count=5,
            sum_confidence=2.75,
            sum_outcome=3.0,
        )
        result = bin_.to_dict()
        assert result["bin_start"] == 0.5
        assert result["bin_end"] == 0.6
        assert result["count"] == 5
        assert "mean_confidence" in result
        assert "accuracy" in result
        assert "gap" in result


class TestConfidenceCalibrator:
    """Tests for ConfidenceCalibrator class."""

    def test_init_default_bins(self):
        cal = ConfidenceCalibrator()
        assert cal.n_bins == 10
        assert cal.sample_count == 0

    def test_init_custom_bins(self):
        cal = ConfidenceCalibrator(n_bins=20)
        assert cal.n_bins == 20

    def test_init_invalid_bins(self):
        with pytest.raises(ValueError):
            ConfidenceCalibrator(n_bins=1)

    def test_add_sample(self):
        cal = ConfidenceCalibrator()
        cal.add_sample("trace_001", 0.85, 1)
        assert cal.sample_count == 1

    def test_add_samples_from_list(self):
        cal = ConfidenceCalibrator()
        samples = [
            {"trace_id": "t1", "predicted_confidence": 0.9, "actual_outcome": 1},
            {"trace_id": "t2", "predicted_confidence": 0.8, "actual_outcome": 1},
            {"trace_id": "t3", "predicted_confidence": 0.7, "actual_outcome": 0},
        ]
        added = cal.add_samples_from_list(samples)
        assert added == 3
        assert cal.sample_count == 3


class TestBrierScore:
    """Tests for Brier Score computation."""

    def test_brier_perfect_prediction(self):
        """Perfect predictions should have Brier Score = 0."""
        cal = ConfidenceCalibrator()
        cal.add_sample("t1", 1.0, 1)  # 100% confident, correct
        cal.add_sample("t2", 0.0, 0)  # 0% confident, incorrect (as expected)
        
        brier = cal.compute_brier_score()
        assert brier == pytest.approx(0.0, abs=0.001)

    def test_brier_worst_prediction(self):
        """Completely wrong predictions should have Brier Score = 1."""
        cal = ConfidenceCalibrator()
        cal.add_sample("t1", 1.0, 0)  # 100% confident, wrong
        cal.add_sample("t2", 0.0, 1)  # 0% confident, but was correct
        
        brier = cal.compute_brier_score()
        assert brier == pytest.approx(1.0, abs=0.001)

    def test_brier_moderate_prediction(self):
        """50% confidence predictions should have Brier Score = 0.25."""
        cal = ConfidenceCalibrator()
        cal.add_sample("t1", 0.5, 0)
        cal.add_sample("t2", 0.5, 1)
        
        # (0.5 - 0)^2 + (0.5 - 1)^2 = 0.25 + 0.25 = 0.5
        # avg = 0.5 / 2 = 0.25
        brier = cal.compute_brier_score()
        assert brier == pytest.approx(0.25, abs=0.001)

    def test_brier_empty_samples(self):
        cal = ConfidenceCalibrator()
        brier = cal.compute_brier_score()
        assert brier == 0.0


class TestECE:
    """Tests for Expected Calibration Error (ECE)."""

    def test_ece_perfect_calibration(self):
        """Perfectly calibrated model should have ECE close to 0."""
        cal = ConfidenceCalibrator(n_bins=10)
        
        # Add perfectly calibrated samples
        # 90% confidence bin: 9 out of 10 correct
        for i in range(9):
            cal.add_sample(f"high_{i}", 0.9, 1)
        cal.add_sample("high_9", 0.9, 0)
        
        # 50% confidence bin: 5 out of 10 correct
        for i in range(5):
            cal.add_sample(f"mid_{i}_correct", 0.5, 1)
            cal.add_sample(f"mid_{i}_wrong", 0.5, 0)
        
        ece, mce, bins = cal.compute_ece()
        # With perfect calibration, ECE should be close to 0
        assert ece < 0.1  # Allow some tolerance

    def test_ece_overconfident(self):
        """Overconfident model should have high ECE."""
        cal = ConfidenceCalibrator(n_bins=10)
        
        # Model predicts 95% confidence but only 50% are correct
        for i in range(50):
            cal.add_sample(f"over_{i}", 0.95, 1 if i < 25 else 0)
        
        ece, mce, bins = cal.compute_ece()
        # Gap = |0.95 - 0.5| = 0.45
        assert ece > 0.3  # Should be high

    def test_ece_empty_samples(self):
        cal = ConfidenceCalibrator()
        ece, mce, bins = cal.compute_ece()
        assert ece == 0.0
        assert mce == 0.0
        assert bins == []

    def test_ece_returns_bins(self):
        cal = ConfidenceCalibrator(n_bins=5)
        for i in range(10):
            cal.add_sample(f"t{i}", 0.1 * i, i % 2)
        
        ece, mce, bins = cal.compute_ece()
        assert len(bins) == 5
        assert all(isinstance(b, CalibrationBin) for b in bins)


class TestCalibrationReport:
    """Tests for CalibrationReport generation."""

    def test_compute_report(self):
        cal = ConfidenceCalibrator(n_bins=10)
        
        # Add diverse samples
        for i in range(100):
            confidence = (i % 10) / 10 + 0.05
            outcome = 1 if i % 3 != 0 else 0
            cal.add_sample(f"trace_{i}", confidence, outcome)
        
        report = cal.compute_report()
        
        assert isinstance(report, CalibrationReport)
        assert report.total_samples == 100
        assert 0 <= report.brier_score <= 1
        assert 0 <= report.expected_calibration_error <= 1
        assert 0 <= report.max_calibration_error <= 1
        assert len(report.bins) == 10

    def test_report_to_dict(self):
        cal = ConfidenceCalibrator()
        cal.add_sample("t1", 0.8, 1)
        cal.add_sample("t2", 0.7, 0)
        
        report = cal.compute_report()
        result = report.to_dict()
        
        assert "brier_score" in result
        assert "expected_calibration_error" in result
        assert "max_calibration_error" in result
        assert "overall_accuracy" in result
        assert "total_samples" in result
        assert "bins" in result
        assert "timestamp" in result

    def test_is_well_calibrated_true(self):
        report = CalibrationReport(
            brier_score=0.05,
            expected_calibration_error=0.05,  # < 0.1
            max_calibration_error=0.08,
            bins=[],
            total_samples=100,
            correct_predictions=90,
        )
        assert report.is_well_calibrated is True

    def test_is_well_calibrated_false(self):
        report = CalibrationReport(
            brier_score=0.25,
            expected_calibration_error=0.15,  # >= 0.1
            max_calibration_error=0.30,
            bins=[],
            total_samples=100,
            correct_predictions=50,
        )
        assert report.is_well_calibrated is False


class TestReliabilityDiagram:
    """Tests for reliability diagram data generation."""

    def test_generate_diagram_data(self):
        cal = ConfidenceCalibrator(n_bins=10)
        
        for i in range(50):
            confidence = i / 50
            outcome = 1 if i > 25 else 0
            cal.add_sample(f"t{i}", confidence, outcome)
        
        diagram = cal.generate_reliability_diagram_data()
        
        assert "diagonal" in diagram
        assert diagram["diagonal"] == [[0, 0], [1, 1]]
        assert "calibration_curve" in diagram
        assert "histogram" in diagram
        assert diagram["n_bins"] == 10
        assert diagram["total_samples"] == 50


class TestCalibrationDataset:
    """Tests for CalibrationDataset persistence."""

    def test_add_outcome(self, tmp_path):
        dataset = CalibrationDataset(data_path=tmp_path / "calibration.jsonl")
        
        dataset.add_outcome(
            trace_id="trace_001",
            predicted_confidence=0.85,
            predicted_class="Data Scientist",
            actual_class="Data Scientist",
        )
        
        # Verify file was created
        assert (tmp_path / "calibration.jsonl").exists()

    def test_load_samples(self, tmp_path):
        dataset = CalibrationDataset(data_path=tmp_path / "cal_load.jsonl")
        
        # Add some outcomes
        dataset.add_outcome("t1", 0.9, "A", "A")  # correct
        dataset.add_outcome("t2", 0.8, "B", "A")  # wrong
        dataset.add_outcome("t3", 0.7, "C", "C")  # correct
        
        samples = dataset.load_samples()
        
        assert len(samples) == 3
        assert samples[0]["actual_outcome"] == 1  # A == A
        assert samples[1]["actual_outcome"] == 0  # B != A
        assert samples[2]["actual_outcome"] == 1  # C == C

    def test_generate_report(self, tmp_path):
        dataset = CalibrationDataset(data_path=tmp_path / "cal_report.jsonl")
        
        # Add calibration data
        for i in range(20):
            confidence = 0.7 + (i % 3) * 0.1
            predicted = "Career_A" if i % 2 == 0 else "Career_B"
            actual = "Career_A" if i % 3 != 0 else "Career_B"
            dataset.add_outcome(f"trace_{i}", confidence, predicted, actual)
        
        report = dataset.generate_report(n_bins=5)
        
        assert isinstance(report, CalibrationReport)
        assert report.total_samples == 20

    def test_load_samples_with_date_filter(self, tmp_path):
        data_file = tmp_path / "cal_date.jsonl"
        
        # Write samples with specific timestamps
        samples = [
            {"trace_id": "t1", "predicted_confidence": 0.9, "actual_outcome": 1, "timestamp": "2026-01-01T00:00:00"},
            {"trace_id": "t2", "predicted_confidence": 0.8, "actual_outcome": 0, "timestamp": "2026-02-01T00:00:00"},
            {"trace_id": "t3", "predicted_confidence": 0.7, "actual_outcome": 1, "timestamp": "2026-03-01T00:00:00"},
        ]
        for s in samples:
            with open(data_file, "a") as f:
                f.write(json.dumps(s) + "\n")
        
        dataset = CalibrationDataset(data_path=data_file)
        
        # Filter by date
        filtered = dataset.load_samples(from_date="2026-01-15", to_date="2026-02-15")
        assert len(filtered) == 1
        assert filtered[0]["trace_id"] == "t2"


class TestJSONSerialization:
    """Tests for JSON import/export."""

    def test_to_json(self):
        cal = ConfidenceCalibrator()
        cal.add_sample("t1", 0.9, 1, "A", "A")
        cal.add_sample("t2", 0.8, 0, "B", "A")
        
        json_str = cal.to_json()
        data = json.loads(json_str)
        
        assert len(data) == 2
        assert data[0]["trace_id"] == "t1"
        assert data[1]["predicted_confidence"] == 0.8

    def test_from_json(self):
        json_data = json.dumps([
            {"trace_id": "x1", "predicted_confidence": 0.95, "actual_outcome": 1},
            {"trace_id": "x2", "predicted_confidence": 0.55, "actual_outcome": 0},
        ])
        
        cal = ConfidenceCalibrator.from_json(json_data, n_bins=5)
        
        assert cal.sample_count == 2
        assert cal.n_bins == 5

    def test_clear(self):
        cal = ConfidenceCalibrator()
        cal.add_sample("t1", 0.9, 1)
        cal.add_sample("t2", 0.8, 0)
        assert cal.sample_count == 2
        
        cal.clear()
        assert cal.sample_count == 0


# Ground truth dataset test with realistic data
class TestGroundTruthDataset:
    """Integration tests with realistic calibration scenarios."""

    def test_career_prediction_calibration(self):
        """
        Simulate career prediction calibration with ground truth data.
        
        Scenario: Model predicts careers with various confidence levels.
        After follow-up surveys, we have actual career outcomes.
        """
        cal = ConfidenceCalibrator(n_bins=10)
        
        # Simulated ground truth dataset
        ground_truth = [
            # High confidence predictions (0.8-1.0)
            ("user_001", 0.95, "Data Scientist", "Data Scientist"),  # Correct
            ("user_002", 0.92, "Software Engineer", "Software Engineer"),  # Correct
            ("user_003", 0.88, "Data Scientist", "ML Engineer"),  # Wrong
            ("user_004", 0.91, "AI Engineer", "AI Engineer"),  # Correct
            ("user_005", 0.85, "Data Analyst", "Data Analyst"),  # Correct
            
            # Medium confidence (0.5-0.8)
            ("user_006", 0.72, "Software Engineer", "DevOps"),  # Wrong
            ("user_007", 0.68, "Data Scientist", "Data Scientist"),  # Correct
            ("user_008", 0.75, "ML Engineer", "ML Engineer"),  # Correct
            ("user_009", 0.55, "AI Engineer", "Data Scientist"),  # Wrong
            ("user_010", 0.62, "Data Analyst", "Data Analyst"),  # Correct
            
            # Low confidence (0.0-0.5)
            ("user_011", 0.45, "Software Engineer", "Data Engineer"),  # Wrong
            ("user_012", 0.38, "Data Scientist", "Software Engineer"),  # Wrong
            ("user_013", 0.42, "ML Engineer", "ML Engineer"),  # Correct
            ("user_014", 0.28, "AI Engineer", "Data Analyst"),  # Wrong
            ("user_015", 0.35, "Data Analyst", "Data Analyst"),  # Correct
        ]
        
        for trace_id, confidence, predicted, actual in ground_truth:
            outcome = 1 if predicted == actual else 0
            cal.add_sample(trace_id, confidence, outcome, predicted, actual)
        
        report = cal.compute_report()
        
        # Verify report metrics are reasonable
        assert report.total_samples == 15
        assert report.correct_predictions == 9  # 9 correct predictions
        assert report.overall_accuracy == pytest.approx(0.6, abs=0.01)
        
        # Brier score should be moderate (not perfect, not terrible)
        assert 0.1 < report.brier_score < 0.4
        
        # ECE should be reasonable
        assert 0.0 <= report.expected_calibration_error <= 0.5
        
        # Print report for inspection
        print("\n=== Calibration Report ===")
        print(f"Brier Score: {report.brier_score:.4f}")
        print(f"ECE: {report.expected_calibration_error:.4f}")
        print(f"MCE: {report.max_calibration_error:.4f}")
        print(f"Well Calibrated: {report.is_well_calibrated}")

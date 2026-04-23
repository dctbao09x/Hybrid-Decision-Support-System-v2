# backend/explain/calibration.py
"""
Confidence Calibration Module
=============================

Implements calibration metrics for XAI confidence scores:
  - Brier Score: Mean squared error of probability predictions
  - Expected Calibration Error (ECE): Measures miscalibration
  - Reliability Diagram: Visual binning for calibration curves

Requirements:
  - Ground truth dataset with actual outcomes
  - Predicted probabilities (confidence scores)
  - No fake metrics - uses real data only
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class CalibrationSample:
    """Single calibration data point."""
    
    trace_id: str
    predicted_confidence: float  # Model's confidence [0, 1]
    actual_outcome: int  # 1 if correct prediction, 0 otherwise
    predicted_class: str = ""
    actual_class: str = ""
    timestamp: str = ""
    
    def __post_init__(self):
        # Clamp confidence to valid range
        self.predicted_confidence = max(0.0, min(1.0, self.predicted_confidence))
        # Ensure binary outcome
        self.actual_outcome = 1 if self.actual_outcome else 0
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class CalibrationBin:
    """Aggregated bin for reliability diagram."""
    
    bin_start: float
    bin_end: float
    count: int = 0
    sum_confidence: float = 0.0
    sum_outcome: float = 0.0
    
    @property
    def mean_confidence(self) -> float:
        """Average predicted confidence in bin."""
        return self.sum_confidence / self.count if self.count > 0 else 0.0
    
    @property
    def accuracy(self) -> float:
        """Fraction of correct predictions in bin."""
        return self.sum_outcome / self.count if self.count > 0 else 0.0
    
    @property
    def gap(self) -> float:
        """Absolute difference between confidence and accuracy."""
        return abs(self.mean_confidence - self.accuracy)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "bin_start": self.bin_start,
            "bin_end": self.bin_end,
            "count": self.count,
            "mean_confidence": round(self.mean_confidence, 4),
            "accuracy": round(self.accuracy, 4),
            "gap": round(self.gap, 4),
        }


@dataclass
class CalibrationReport:
    """Full calibration analysis report."""
    
    brier_score: float
    expected_calibration_error: float
    max_calibration_error: float
    bins: List[CalibrationBin]
    total_samples: int
    correct_predictions: int
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    @property
    def overall_accuracy(self) -> float:
        return self.correct_predictions / self.total_samples if self.total_samples > 0 else 0.0
    
    @property
    def is_well_calibrated(self) -> bool:
        """ECE < 0.1 is generally considered well-calibrated."""
        return self.expected_calibration_error < 0.10
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "brier_score": round(self.brier_score, 6),
            "expected_calibration_error": round(self.expected_calibration_error, 6),
            "max_calibration_error": round(self.max_calibration_error, 6),
            "overall_accuracy": round(self.overall_accuracy, 4),
            "total_samples": self.total_samples,
            "correct_predictions": self.correct_predictions,
            "is_well_calibrated": self.is_well_calibrated,
            "bins": [b.to_dict() for b in self.bins],
            "timestamp": self.timestamp,
        }


class ConfidenceCalibrator:
    """
    Computes calibration metrics for model confidence.
    
    Usage:
        calibrator = ConfidenceCalibrator(n_bins=10)
        
        # Add samples
        calibrator.add_sample("trace_1", 0.85, 1)  # 85% confidence, correct
        calibrator.add_sample("trace_2", 0.90, 0)  # 90% confidence, wrong
        
        # Get report
        report = calibrator.compute_report()
        print(f"Brier Score: {report.brier_score}")
        print(f"ECE: {report.expected_calibration_error}")
    """
    
    def __init__(self, n_bins: int = 10):
        """
        Initialize calibrator.
        
        Args:
            n_bins: Number of bins for ECE/reliability diagram (default: 10)
        """
        if n_bins < 2:
            raise ValueError("n_bins must be at least 2")
        
        self._n_bins = n_bins
        self._samples: List[CalibrationSample] = []
    
    @property
    def n_bins(self) -> int:
        return self._n_bins
    
    @property
    def sample_count(self) -> int:
        return len(self._samples)
    
    def add_sample(
        self,
        trace_id: str,
        predicted_confidence: float,
        actual_outcome: int,
        predicted_class: str = "",
        actual_class: str = "",
    ) -> None:
        """Add a calibration sample."""
        sample = CalibrationSample(
            trace_id=trace_id,
            predicted_confidence=predicted_confidence,
            actual_outcome=actual_outcome,
            predicted_class=predicted_class,
            actual_class=actual_class,
        )
        self._samples.append(sample)
    
    def add_samples_from_list(self, samples: List[Dict[str, Any]]) -> int:
        """
        Add multiple samples from list of dicts.
        
        Expected dict format:
            {
                "trace_id": str,
                "predicted_confidence": float,
                "actual_outcome": int,
                "predicted_class": str (optional),
                "actual_class": str (optional),
            }
        
        Returns:
            Number of samples added.
        """
        added = 0
        for item in samples:
            try:
                self.add_sample(
                    trace_id=str(item.get("trace_id", f"sample_{added}")),
                    predicted_confidence=float(item.get("predicted_confidence", 0.0)),
                    actual_outcome=int(item.get("actual_outcome", 0)),
                    predicted_class=str(item.get("predicted_class", "")),
                    actual_class=str(item.get("actual_class", "")),
                )
                added += 1
            except (TypeError, ValueError):
                continue
        return added
    
    def compute_brier_score(self) -> float:
        """
        Compute Brier Score.
        
        Brier Score = (1/N) * Σ (predicted_confidence - actual_outcome)²
        
        Range: [0, 1]
        - 0 = perfect calibration
        - 1 = worst calibration
        """
        if not self._samples:
            return 0.0
        
        total_sq_error = 0.0
        for sample in self._samples:
            error = sample.predicted_confidence - sample.actual_outcome
            total_sq_error += error * error
        
        return total_sq_error / len(self._samples)
    
    def compute_ece(self) -> Tuple[float, float, List[CalibrationBin]]:
        """
        Compute Expected Calibration Error (ECE) and Max Calibration Error (MCE).
        
        ECE = Σ (|B_m| / N) * |acc(B_m) - conf(B_m)|
        
        Where:
          B_m = samples in bin m
          acc(B_m) = accuracy in bin m
          conf(B_m) = mean confidence in bin m
        
        Returns:
            Tuple of (ECE, MCE, bins)
        """
        if not self._samples:
            return 0.0, 0.0, []
        
        # Create uniform bins
        bin_width = 1.0 / self._n_bins
        bins = [
            CalibrationBin(
                bin_start=i * bin_width,
                bin_end=(i + 1) * bin_width,
            )
            for i in range(self._n_bins)
        ]
        
        # Assign samples to bins
        n_samples = len(self._samples)
        for sample in self._samples:
            bin_idx = min(int(sample.predicted_confidence / bin_width), self._n_bins - 1)
            bins[bin_idx].count += 1
            bins[bin_idx].sum_confidence += sample.predicted_confidence
            bins[bin_idx].sum_outcome += sample.actual_outcome
        
        # Compute ECE and MCE
        ece = 0.0
        mce = 0.0
        for b in bins:
            if b.count > 0:
                weight = b.count / n_samples
                ece += weight * b.gap
                mce = max(mce, b.gap)
        
        return ece, mce, bins
    
    def compute_report(self) -> CalibrationReport:
        """Generate full calibration report."""
        brier = self.compute_brier_score()
        ece, mce, bins = self.compute_ece()
        
        correct = sum(1 for s in self._samples if s.actual_outcome == 1)
        
        return CalibrationReport(
            brier_score=brier,
            expected_calibration_error=ece,
            max_calibration_error=mce,
            bins=bins,
            total_samples=len(self._samples),
            correct_predictions=correct,
        )
    
    def generate_reliability_diagram_data(self) -> Dict[str, Any]:
        """
        Generate data for reliability diagram visualization.
        
        Returns dict suitable for frontend charting:
            {
                "diagonal": [[0, 0], [1, 1]],  # Perfect calibration line
                "calibration_curve": [[conf, acc], ...],  # Actual calibration
                "histogram": [[bin_center, count], ...],  # Sample distribution
            }
        """
        _, _, bins = self.compute_ece()
        
        # Perfect calibration diagonal
        diagonal = [[0, 0], [1, 1]]
        
        # Calibration curve points (only non-empty bins)
        calibration_curve = []
        histogram = []
        
        for b in bins:
            bin_center = (b.bin_start + b.bin_end) / 2
            if b.count > 0:
                calibration_curve.append([b.mean_confidence, b.accuracy])
            histogram.append([bin_center, b.count])
        
        return {
            "diagonal": diagonal,
            "calibration_curve": calibration_curve,
            "histogram": histogram,
            "n_bins": self._n_bins,
            "total_samples": len(self._samples),
        }
    
    def clear(self) -> None:
        """Clear all samples."""
        self._samples.clear()
    
    def to_json(self) -> str:
        """Export samples as JSON."""
        return json.dumps(
            [
                {
                    "trace_id": s.trace_id,
                    "predicted_confidence": s.predicted_confidence,
                    "actual_outcome": s.actual_outcome,
                    "predicted_class": s.predicted_class,
                    "actual_class": s.actual_class,
                    "timestamp": s.timestamp,
                }
                for s in self._samples
            ],
            indent=2,
        )
    
    @classmethod
    def from_json(cls, json_str: str, n_bins: int = 10) -> "ConfidenceCalibrator":
        """Load calibrator from JSON."""
        calibrator = cls(n_bins=n_bins)
        data = json.loads(json_str)
        calibrator.add_samples_from_list(data)
        return calibrator


class CalibrationDataset:
    """
    Persistent calibration ground truth dataset.
    
    Stores prediction outcomes for calibration analysis.
    """
    
    def __init__(self, data_path: Optional[Path] = None):
        self._data_path = data_path or Path("storage/calibration_data.jsonl")
        self._data_path.parent.mkdir(parents=True, exist_ok=True)
    
    def add_outcome(
        self,
        trace_id: str,
        predicted_confidence: float,
        predicted_class: str,
        actual_class: str,
    ) -> None:
        """
        Record a prediction outcome.
        
        actual_outcome is computed as: predicted_class == actual_class
        """
        actual_outcome = 1 if predicted_class == actual_class else 0
        record = {
            "trace_id": trace_id,
            "predicted_confidence": predicted_confidence,
            "predicted_class": predicted_class,
            "actual_class": actual_class,
            "actual_outcome": actual_outcome,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with open(self._data_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    def load_samples(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 10000,
    ) -> List[Dict[str, Any]]:
        """Load samples from dataset, optionally filtered by date."""
        if not self._data_path.exists():
            return []
        
        samples = []
        with open(self._data_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    ts = record.get("timestamp", "")
                    
                    # Filter by date range
                    if from_date and ts < from_date:
                        continue
                    if to_date and ts > to_date:
                        continue
                    
                    samples.append(record)
                    if len(samples) >= limit:
                        break
                except json.JSONDecodeError:
                    continue
        
        return samples
    
    def generate_report(
        self,
        n_bins: int = 10,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> CalibrationReport:
        """Generate calibration report from stored data."""
        samples = self.load_samples(from_date=from_date, to_date=to_date)
        
        calibrator = ConfidenceCalibrator(n_bins=n_bins)
        calibrator.add_samples_from_list(samples)
        
        return calibrator.compute_report()


# Singleton for global calibration dataset
_calibration_dataset: Optional[CalibrationDataset] = None


def get_calibration_dataset() -> CalibrationDataset:
    """Get global calibration dataset instance."""
    global _calibration_dataset
    if _calibration_dataset is None:
        _calibration_dataset = CalibrationDataset()
    return _calibration_dataset

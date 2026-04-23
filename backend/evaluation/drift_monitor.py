# backend/evaluation/drift_monitor.py
"""
Drift Monitor
=============
Detects data drift between the current dataset and a baseline.

Drift types detected:
  • Feature mean shift
  • Feature std shift
  • Label distribution shift
  • Population Stability Index (PSI)

Severity levels:
  • LOW:    PSI < 0.1, minor shifts
  • MEDIUM: 0.1 <= PSI < 0.25, moderate drift
  • HIGH:   PSI >= 0.25, significant drift (action required)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backend.evaluation.fingerprint import DatasetFingerprint

logger = logging.getLogger("ml_evaluation.drift_monitor")


class DriftSeverity(Enum):
    """Drift severity levels."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class FeatureDrift:
    """Drift metrics for a single feature."""
    feature_name: str
    mean_shift: float
    std_shift: float
    mean_baseline: float
    mean_current: float
    std_baseline: float
    std_current: float
    psi: float = 0.0
    severity: DriftSeverity = DriftSeverity.LOW

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature_name": self.feature_name,
            "mean_shift": round(self.mean_shift, 6),
            "std_shift": round(self.std_shift, 6),
            "mean_baseline": round(self.mean_baseline, 6),
            "mean_current": round(self.mean_current, 6),
            "std_baseline": round(self.std_baseline, 6),
            "std_current": round(self.std_current, 6),
            "psi": round(self.psi, 6),
            "severity": self.severity.value,
        }


@dataclass
class LabelDrift:
    """Drift metrics for label distribution."""
    labels: List[str]
    baseline_distribution: Dict[str, float]
    current_distribution: Dict[str, float]
    psi: float
    severity: DriftSeverity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "labels": self.labels,
            "baseline_distribution": self.baseline_distribution,
            "current_distribution": self.current_distribution,
            "psi": round(self.psi, 6),
            "severity": self.severity.value,
        }


@dataclass
class DriftReport:
    """Complete drift analysis report."""
    run_id: str
    baseline_hash: str
    current_hash: str
    overall_severity: DriftSeverity
    overall_psi: float
    feature_drifts: List[FeatureDrift] = field(default_factory=list)
    label_drift: Optional[LabelDrift] = None
    schema_changed: bool = False
    row_count_change: int = 0
    timestamp: str = ""
    recommendations: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "baseline_hash": self.baseline_hash,
            "current_hash": self.current_hash,
            "overall_severity": self.overall_severity.value,
            "overall_psi": round(self.overall_psi, 6),
            "feature_drifts": [fd.to_dict() for fd in self.feature_drifts],
            "label_drift": self.label_drift.to_dict() if self.label_drift else None,
            "schema_changed": self.schema_changed,
            "row_count_change": self.row_count_change,
            "timestamp": self.timestamp,
            "recommendations": self.recommendations,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DriftReport":
        feature_drifts = [
            FeatureDrift(
                feature_name=fd["feature_name"],
                mean_shift=fd["mean_shift"],
                std_shift=fd["std_shift"],
                mean_baseline=fd["mean_baseline"],
                mean_current=fd["mean_current"],
                std_baseline=fd["std_baseline"],
                std_current=fd["std_current"],
                psi=fd.get("psi", 0.0),
                severity=DriftSeverity(fd.get("severity", "LOW")),
            )
            for fd in data.get("feature_drifts", [])
        ]

        label_drift = None
        if data.get("label_drift"):
            ld = data["label_drift"]
            label_drift = LabelDrift(
                labels=ld["labels"],
                baseline_distribution=ld["baseline_distribution"],
                current_distribution=ld["current_distribution"],
                psi=ld["psi"],
                severity=DriftSeverity(ld["severity"]),
            )

        return cls(
            run_id=data["run_id"],
            baseline_hash=data["baseline_hash"],
            current_hash=data["current_hash"],
            overall_severity=DriftSeverity(data["overall_severity"]),
            overall_psi=data["overall_psi"],
            feature_drifts=feature_drifts,
            label_drift=label_drift,
            schema_changed=data.get("schema_changed", False),
            row_count_change=data.get("row_count_change", 0),
            timestamp=data.get("timestamp", ""),
            recommendations=data.get("recommendations", []),
        )


class DriftMonitor:
    """
    Monitors data drift between baseline and current datasets.

    Usage::

        monitor = DriftMonitor()
        monitor.load_baseline_fingerprint("baseline/dataset_fingerprint.json")
        report = monitor.analyze(current_fingerprint, current_df)
    """

    # PSI thresholds
    PSI_LOW = 0.1
    PSI_MEDIUM = 0.25
    PSI_HIGH = 0.5

    # Mean shift thresholds (as fraction of std)
    MEAN_SHIFT_LOW = 0.2
    MEAN_SHIFT_MEDIUM = 0.5
    MEAN_SHIFT_HIGH = 1.0

    def __init__(
        self,
        target_column: str = "target_career",
        baseline_fingerprint_path: str = "baseline/dataset_fingerprint.json",
    ):
        self._target_column = target_column
        self._baseline_fingerprint_path = baseline_fingerprint_path
        self._baseline_fingerprint: Optional[DatasetFingerprint] = None
        self._project_root = Path(__file__).resolve().parents[2]

    @property
    def has_baseline(self) -> bool:
        return self._baseline_fingerprint is not None

    def load_baseline_fingerprint(
        self, path: Optional[str] = None
    ) -> Optional[DatasetFingerprint]:
        """Load baseline fingerprint from JSON file."""
        path = path or self._baseline_fingerprint_path
        full_path = self._project_root / path

        if not full_path.exists():
            logger.warning("Baseline fingerprint not found: %s", full_path)
            return None

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._baseline_fingerprint = DatasetFingerprint.from_dict(data)
            logger.info(
                "Loaded baseline fingerprint: hash=%s rows=%d",
                self._baseline_fingerprint.hash[:16],
                self._baseline_fingerprint.rows,
            )
            return self._baseline_fingerprint
        except Exception as e:
            logger.error("Failed to load baseline fingerprint: %s", e)
            return None

    def save_baseline_fingerprint(
        self,
        fingerprint: DatasetFingerprint,
        path: Optional[str] = None,
    ) -> None:
        """Save fingerprint as the new baseline."""
        path = path or self._baseline_fingerprint_path
        full_path = self._project_root / path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(fingerprint.to_json())

        self._baseline_fingerprint = fingerprint
        logger.info("Saved baseline fingerprint → %s", path)

    def analyze(
        self,
        current_fingerprint: DatasetFingerprint,
        run_id: str,
        current_df: Optional[pd.DataFrame] = None,
    ) -> DriftReport:
        """
        Analyze drift between baseline and current dataset.

        Args:
            current_fingerprint: Fingerprint of current dataset.
            run_id:              Current run ID.
            current_df:          Current DataFrame (optional, for detailed PSI).

        Returns:
            DriftReport with all drift metrics.
        """
        if not self._baseline_fingerprint:
            logger.warning("No baseline — creating initial drift report")
            return self._create_no_baseline_report(current_fingerprint, run_id)

        baseline = self._baseline_fingerprint

        # Schema change check
        schema_changed = not current_fingerprint.schema_matches(baseline)
        if schema_changed:
            logger.warning("Schema change detected!")

        # Row count change
        row_count_change = current_fingerprint.rows - baseline.rows

        # Feature drift analysis
        feature_drifts = self._analyze_feature_drift(baseline, current_fingerprint)

        # Label distribution drift
        label_drift = self._analyze_label_drift(baseline, current_fingerprint)

        # Calculate overall PSI
        feature_psis = [fd.psi for fd in feature_drifts]
        overall_psi = np.mean(feature_psis) if feature_psis else 0.0

        # Include label PSI if available
        if label_drift:
            overall_psi = (overall_psi + label_drift.psi) / 2

        # Determine overall severity
        overall_severity = self._classify_severity(overall_psi)

        # Generate recommendations
        recommendations = self._generate_recommendations(
            feature_drifts, label_drift, schema_changed, row_count_change
        )

        report = DriftReport(
            run_id=run_id,
            baseline_hash=baseline.hash,
            current_hash=current_fingerprint.hash,
            overall_severity=overall_severity,
            overall_psi=overall_psi,
            feature_drifts=feature_drifts,
            label_drift=label_drift,
            schema_changed=schema_changed,
            row_count_change=row_count_change,
            recommendations=recommendations,
        )

        self._log_report_summary(report)
        return report

    def _analyze_feature_drift(
        self,
        baseline: DatasetFingerprint,
        current: DatasetFingerprint,
    ) -> List[FeatureDrift]:
        """Analyze drift for each numeric feature."""
        drifts = []

        for feature_name, baseline_stats in baseline.feature_stats.items():
            if feature_name not in current.feature_stats:
                continue

            current_stats = current.feature_stats[feature_name]

            mean_baseline = baseline_stats["mean"]
            mean_current = current_stats["mean"]
            std_baseline = baseline_stats["std"]
            std_current = current_stats["std"]

            # Calculate shifts
            mean_shift = mean_current - mean_baseline
            std_shift = std_current - std_baseline

            # Calculate PSI-like metric for feature
            # Simplified: use normalized mean shift
            if std_baseline > 0:
                normalized_shift = abs(mean_shift) / std_baseline
            else:
                normalized_shift = abs(mean_shift) if mean_baseline != 0 else 0.0

            psi = self._calculate_simple_psi(normalized_shift)
            severity = self._classify_severity(psi)

            drifts.append(FeatureDrift(
                feature_name=feature_name,
                mean_shift=mean_shift,
                std_shift=std_shift,
                mean_baseline=mean_baseline,
                mean_current=mean_current,
                std_baseline=std_baseline,
                std_current=std_current,
                psi=psi,
                severity=severity,
            ))

        return drifts

    def _analyze_label_drift(
        self,
        baseline: DatasetFingerprint,
        current: DatasetFingerprint,
    ) -> Optional[LabelDrift]:
        """Analyze label distribution drift."""
        if not baseline.label_distribution or not current.label_distribution:
            return None

        # Normalize distributions to percentages
        baseline_total = sum(baseline.label_distribution.values())
        current_total = sum(current.label_distribution.values())

        if baseline_total == 0 or current_total == 0:
            return None

        all_labels = list(set(baseline.label_distribution.keys()) |
                          set(current.label_distribution.keys()))

        baseline_dist = {
            label: baseline.label_distribution.get(label, 0) / baseline_total
            for label in all_labels
        }
        current_dist = {
            label: current.label_distribution.get(label, 0) / current_total
            for label in all_labels
        }

        # Calculate PSI for label distribution
        psi = self._calculate_distribution_psi(
            list(baseline_dist.values()),
            list(current_dist.values()),
        )

        severity = self._classify_severity(psi)

        return LabelDrift(
            labels=all_labels,
            baseline_distribution={k: round(v, 4) for k, v in baseline_dist.items()},
            current_distribution={k: round(v, 4) for k, v in current_dist.items()},
            psi=psi,
            severity=severity,
        )

    def _calculate_simple_psi(self, normalized_shift: float) -> float:
        """Convert normalized shift to PSI-like score."""
        # Map normalized shift to 0-1 PSI range
        return min(normalized_shift * 0.2, 1.0)

    def _calculate_distribution_psi(
        self,
        expected: List[float],
        actual: List[float],
        epsilon: float = 1e-10,
    ) -> float:
        """
        Calculate Population Stability Index.

        PSI = Σ (Actual% - Expected%) × ln(Actual% / Expected%)
        """
        psi = 0.0
        for e, a in zip(expected, actual):
            e = max(e, epsilon)
            a = max(a, epsilon)
            psi += (a - e) * np.log(a / e)
        return abs(psi)

    def _classify_severity(self, psi: float) -> DriftSeverity:
        """Classify drift severity based on PSI."""
        if psi >= self.PSI_HIGH:
            return DriftSeverity.CRITICAL
        elif psi >= self.PSI_MEDIUM:
            return DriftSeverity.HIGH
        elif psi >= self.PSI_LOW:
            return DriftSeverity.MEDIUM
        else:
            return DriftSeverity.LOW

    def _generate_recommendations(
        self,
        feature_drifts: List[FeatureDrift],
        label_drift: Optional[LabelDrift],
        schema_changed: bool,
        row_count_change: int,
    ) -> List[str]:
        """Generate actionable recommendations based on drift analysis."""
        recommendations = []

        if schema_changed:
            recommendations.append(
                "CRITICAL: Schema changed — verify feature engineering pipeline"
            )

        if abs(row_count_change) > 50:
            change_pct = abs(row_count_change) / max(1, row_count_change)
            recommendations.append(
                f"Dataset size changed by {row_count_change} rows — investigate data source"
            )

        high_drift_features = [
            fd.feature_name for fd in feature_drifts
            if fd.severity in (DriftSeverity.HIGH, DriftSeverity.CRITICAL)
        ]
        if high_drift_features:
            recommendations.append(
                f"High drift in features: {', '.join(high_drift_features)} — consider retraining"
            )

        if label_drift and label_drift.severity in (DriftSeverity.HIGH, DriftSeverity.CRITICAL):
            recommendations.append(
                "Label distribution shifted significantly — update baseline or retrain model"
            )

        if not recommendations:
            recommendations.append("No significant drift detected — continue monitoring")

        return recommendations

    def _create_no_baseline_report(
        self,
        fingerprint: DatasetFingerprint,
        run_id: str,
    ) -> DriftReport:
        """Create a report when no baseline exists."""
        return DriftReport(
            run_id=run_id,
            baseline_hash="",
            current_hash=fingerprint.hash,
            overall_severity=DriftSeverity.LOW,
            overall_psi=0.0,
            recommendations=["First run — this will become the baseline"],
        )

    def _log_report_summary(self, report: DriftReport) -> None:
        """Log a summary of the drift report."""
        level = logging.WARNING if report.overall_severity in (
            DriftSeverity.HIGH, DriftSeverity.CRITICAL
        ) else logging.INFO

        logger.log(
            level,
            "Drift Report: severity=%s psi=%.4f schema_changed=%s",
            report.overall_severity.value,
            report.overall_psi,
            report.schema_changed,
        )

    def save_report(self, report: DriftReport, path: str) -> None:
        """Save drift report to JSON file."""
        full_path = self._project_root / path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(report.to_json())

        logger.info("Saved drift report → %s", path)


class DriftError(Exception):
    """Raised when critical drift is detected."""

    def __init__(self, message: str, report: DriftReport):
        super().__init__(message)
        self.report = report

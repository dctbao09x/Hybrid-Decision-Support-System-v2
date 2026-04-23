# backend/monitoring/stability_control.py
"""
Long-Term Stability Control
===========================

System: Hybrid Semi-API + SIMGR + Confidence Layer + One-Button Frontend

Responsibilities:
1. Weekly snapshot metrics (feature distribution, confidence, rank stability, variance)
2. Alert thresholds and automated notifications
3. Automatic drift report generation
4. Quarterly recalibration review scheduling
5. Version freeze and artifact dump

INVARIANT: All metrics are computed deterministically from stored data.
INVARIANT: Alert decisions are based on configurable thresholds.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import statistics

logger = logging.getLogger("monitoring.stability")


# ==============================================================================
# I. MONITORING ARCHITECTURE
# ==============================================================================

# Frozen weights reference (from SIMGRScorer)
FROZEN_WEIGHTS = {
    "study": 0.30,
    "interest": 0.25,
    "market": 0.25,
    "growth": 0.10,
    "risk": 0.10,
}


class MetricType(Enum):
    """Types of stability metrics."""
    FEATURE_DISTRIBUTION = auto()
    CONFIDENCE_AVERAGE = auto()
    TOP3_RANK_STABILITY = auto()
    SCORING_VARIANCE = auto()


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class WeeklySnapshot:
    """
    Weekly snapshot of system metrics.
    
    Collected every Sunday at 00:00 UTC.
    """
    snapshot_id: str
    timestamp: str
    week_number: int
    year: int
    
    # Feature Distribution Metrics
    feature_count: int
    feature_mean: float
    feature_std: float
    feature_min: float
    feature_max: float
    feature_percentiles: Dict[str, float]  # p25, p50, p75, p90, p95
    
    # Confidence Metrics
    confidence_average: float
    confidence_std: float
    confidence_min: float
    confidence_max: float
    low_confidence_ratio: float  # % below 0.6
    
    # Rank Stability Metrics
    top3_stability: float  # % of users with same top-3 careers week-over-week
    rank_correlation: float  # Spearman correlation with previous week
    rank_churn: float  # Average position change
    
    # Scoring Variance Metrics
    score_variance: float
    score_std: float
    score_range: float
    inter_career_variance: float  # Variance between careers for same user
    
    # Metadata
    sample_count: int
    data_hash: str


@dataclass
class AlertThreshold:
    """Configurable alert threshold."""
    metric: MetricType
    warning_threshold: float
    critical_threshold: float
    direction: str = "above"  # "above" or "below"
    description: str = ""


@dataclass
class Alert:
    """Generated alert."""
    alert_id: str
    timestamp: str
    metric: MetricType
    severity: AlertSeverity
    current_value: float
    threshold_value: float
    message: str
    snapshot_id: str
    acknowledged: bool = False


# ==============================================================================
# II. ALERT POLICY
# ==============================================================================

# Default alert thresholds
DEFAULT_THRESHOLDS: List[AlertThreshold] = [
    # Feature Distribution
    AlertThreshold(
        metric=MetricType.FEATURE_DISTRIBUTION,
        warning_threshold=0.15,
        critical_threshold=0.25,
        direction="above",
        description="Feature distribution shift (KL divergence)",
    ),
    
    # Confidence Average
    AlertThreshold(
        metric=MetricType.CONFIDENCE_AVERAGE,
        warning_threshold=0.55,
        critical_threshold=0.45,
        direction="below",
        description="Average confidence score",
    ),
    
    # Top-3 Rank Stability
    AlertThreshold(
        metric=MetricType.TOP3_RANK_STABILITY,
        warning_threshold=0.85,
        critical_threshold=0.70,
        direction="below",
        description="Top-3 rank stability week-over-week",
    ),
    
    # Scoring Variance
    AlertThreshold(
        metric=MetricType.SCORING_VARIANCE,
        warning_threshold=0.08,
        critical_threshold=0.15,
        direction="above",
        description="Score variance increase from baseline",
    ),
]


class AlertPolicy:
    """
    Alert policy engine.
    
    Evaluates metrics against thresholds and generates alerts.
    """
    
    def __init__(
        self,
        thresholds: Optional[List[AlertThreshold]] = None,
    ):
        self._thresholds = {t.metric: t for t in (thresholds or DEFAULT_THRESHOLDS)}
        self._alerts: List[Alert] = []
    
    def evaluate(
        self,
        snapshot: WeeklySnapshot,
        previous_snapshot: Optional[WeeklySnapshot] = None,
    ) -> List[Alert]:
        """
        Evaluate snapshot against thresholds.
        
        Returns list of triggered alerts.
        """
        alerts = []
        
        # Evaluate each metric
        metrics_to_check = [
            (MetricType.CONFIDENCE_AVERAGE, snapshot.confidence_average),
            (MetricType.TOP3_RANK_STABILITY, snapshot.top3_stability),
            (MetricType.SCORING_VARIANCE, snapshot.score_variance),
        ]
        
        # Feature distribution requires previous snapshot for drift
        if previous_snapshot:
            drift = self._compute_feature_drift(snapshot, previous_snapshot)
            metrics_to_check.append((MetricType.FEATURE_DISTRIBUTION, drift))
        
        for metric_type, value in metrics_to_check:
            alert = self._check_threshold(metric_type, value, snapshot.snapshot_id)
            if alert:
                alerts.append(alert)
        
        self._alerts.extend(alerts)
        return alerts
    
    def _check_threshold(
        self,
        metric: MetricType,
        value: float,
        snapshot_id: str,
    ) -> Optional[Alert]:
        """Check if value exceeds threshold."""
        threshold = self._thresholds.get(metric)
        if not threshold:
            return None
        
        severity = None
        threshold_value = None
        
        if threshold.direction == "above":
            if value >= threshold.critical_threshold:
                severity = AlertSeverity.CRITICAL
                threshold_value = threshold.critical_threshold
            elif value >= threshold.warning_threshold:
                severity = AlertSeverity.WARNING
                threshold_value = threshold.warning_threshold
        else:  # below
            if value <= threshold.critical_threshold:
                severity = AlertSeverity.CRITICAL
                threshold_value = threshold.critical_threshold
            elif value <= threshold.warning_threshold:
                severity = AlertSeverity.WARNING
                threshold_value = threshold.warning_threshold
        
        if severity:
            return Alert(
                alert_id=f"ALERT_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{metric.name}",
                timestamp=datetime.utcnow().isoformat(),
                metric=metric,
                severity=severity,
                current_value=value,
                threshold_value=threshold_value,
                message=f"{threshold.description}: {value:.4f} (threshold: {threshold_value:.4f})",
                snapshot_id=snapshot_id,
            )
        
        return None
    
    def _compute_feature_drift(
        self,
        current: WeeklySnapshot,
        previous: WeeklySnapshot,
    ) -> float:
        """Compute feature distribution drift (simplified KL approximation)."""
        # Use mean/std shift as proxy for KL divergence
        mean_shift = abs(current.feature_mean - previous.feature_mean)
        std_ratio = current.feature_std / max(previous.feature_std, 0.001)
        
        # Simplified drift metric
        drift = mean_shift + abs(1 - std_ratio) * 0.5
        return drift
    
    def get_active_alerts(self) -> List[Alert]:
        """Get unacknowledged alerts."""
        return [a for a in self._alerts if not a.acknowledged]
    
    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        for alert in self._alerts:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                return True
        return False


# ==============================================================================
# III. REVIEW SCHEDULE
# ==============================================================================

class ReviewType(Enum):
    """Types of scheduled reviews."""
    WEEKLY_SNAPSHOT = "weekly_snapshot"
    MONTHLY_TREND = "monthly_trend"
    QUARTERLY_RECALIBRATION = "quarterly_recalibration"
    ANNUAL_AUDIT = "annual_audit"


@dataclass
class ScheduledReview:
    """Scheduled review entry."""
    review_id: str
    review_type: ReviewType
    scheduled_date: str
    status: str = "pending"  # pending, in_progress, completed, skipped
    assignee: Optional[str] = None
    notes: str = ""
    report_path: Optional[str] = None


class ReviewScheduler:
    """
    Review scheduler for stability control.
    
    Schedules:
    - Weekly: Snapshot collection (automated)
    - Monthly: Trend analysis (automated)
    - Quarterly: Recalibration review (manual)
    - Annual: Full audit (manual)
    """
    
    def __init__(self, base_path: Optional[Path] = None):
        self._base_path = base_path or Path("backend/data/monitoring/reviews")
        self._base_path.mkdir(parents=True, exist_ok=True)
        self._schedule: List[ScheduledReview] = self._load_schedule()
    
    def _load_schedule(self) -> List[ScheduledReview]:
        """Load schedule from disk."""
        schedule_path = self._base_path / "schedule.json"
        if schedule_path.exists():
            data = json.loads(schedule_path.read_text())
            return [
                ScheduledReview(
                    review_id=r["review_id"],
                    review_type=ReviewType(r["review_type"]),
                    scheduled_date=r["scheduled_date"],
                    status=r.get("status", "pending"),
                    assignee=r.get("assignee"),
                    notes=r.get("notes", ""),
                    report_path=r.get("report_path"),
                )
                for r in data
            ]
        return []
    
    def _save_schedule(self) -> None:
        """Save schedule to disk."""
        schedule_path = self._base_path / "schedule.json"
        data = [
            {
                "review_id": r.review_id,
                "review_type": r.review_type.value,
                "scheduled_date": r.scheduled_date,
                "status": r.status,
                "assignee": r.assignee,
                "notes": r.notes,
                "report_path": r.report_path,
            }
            for r in self._schedule
        ]
        schedule_path.write_text(json.dumps(data, indent=2))
    
    def schedule_quarterly_reviews(self, year: int) -> List[ScheduledReview]:
        """
        Schedule quarterly recalibration reviews for a year.
        
        Q1: March 31
        Q2: June 30
        Q3: September 30
        Q4: December 31
        """
        quarterly_dates = [
            f"{year}-03-31",
            f"{year}-06-30",
            f"{year}-09-30",
            f"{year}-12-31",
        ]
        
        reviews = []
        for i, date in enumerate(quarterly_dates, 1):
            review = ScheduledReview(
                review_id=f"QREV_{year}_Q{i}",
                review_type=ReviewType.QUARTERLY_RECALIBRATION,
                scheduled_date=date,
                notes=f"Q{i} {year} Recalibration Review",
            )
            reviews.append(review)
            self._schedule.append(review)
        
        self._save_schedule()
        return reviews
    
    def get_pending_reviews(self) -> List[ScheduledReview]:
        """Get all pending reviews."""
        return [r for r in self._schedule if r.status == "pending"]
    
    def get_overdue_reviews(self) -> List[ScheduledReview]:
        """Get overdue reviews."""
        today = datetime.utcnow().date().isoformat()
        return [
            r for r in self._schedule
            if r.status == "pending" and r.scheduled_date < today
        ]
    
    def complete_review(
        self,
        review_id: str,
        report_path: str,
        notes: str = "",
    ) -> bool:
        """Mark review as completed."""
        for review in self._schedule:
            if review.review_id == review_id:
                review.status = "completed"
                review.report_path = report_path
                review.notes = notes
                self._save_schedule()
                return True
        return False


# ==============================================================================
# IV. VERSION FREEZE
# ==============================================================================

@dataclass
class VersionFreeze:
    """
    Frozen version artifact.
    
    Contains all artifacts for a stable release.
    """
    tag_name: str
    freeze_date: str
    
    # Artifacts
    feature_schema: Dict[str, Any]
    weights: Dict[str, float]
    calibration_report: Dict[str, Any]
    audit_report: Dict[str, Any]
    
    # Metadata
    frozen_by: str = "system"
    checksum: str = ""
    notes: str = ""


class VersionFreezer:
    """
    Version freeze manager.
    
    Creates immutable snapshots of system state for stable releases.
    """
    
    def __init__(self, base_path: Optional[Path] = None):
        self._base_path = base_path or Path("backend/data/versions/frozen")
        self._base_path.mkdir(parents=True, exist_ok=True)
    
    def freeze(
        self,
        tag_name: str,
        feature_schema: Dict[str, Any],
        weights: Dict[str, float],
        calibration_report: Dict[str, Any],
        audit_report: Dict[str, Any],
        frozen_by: str = "system",
        notes: str = "",
    ) -> VersionFreeze:
        """
        Create a frozen version.
        
        Args:
            tag_name: Version tag (e.g., "one_button_v1_stable")
            feature_schema: Feature schema definition
            weights: SIMGR weights
            calibration_report: Calibration analysis report
            audit_report: System audit report
            frozen_by: Author of freeze
            notes: Release notes
        
        Returns:
            VersionFreeze artifact
        """
        # Compute checksum of all artifacts
        checksum_data = {
            "feature_schema": feature_schema,
            "weights": weights,
            "calibration_report": calibration_report,
            "audit_report": audit_report,
        }
        checksum = hashlib.sha256(
            json.dumps(checksum_data, sort_keys=True).encode()
        ).hexdigest()
        
        freeze = VersionFreeze(
            tag_name=tag_name,
            freeze_date=datetime.utcnow().isoformat(),
            feature_schema=feature_schema,
            weights=weights,
            calibration_report=calibration_report,
            audit_report=audit_report,
            frozen_by=frozen_by,
            checksum=checksum,
            notes=notes,
        )
        
        # Save to disk
        self._save_freeze(freeze)
        
        logger.info(f"Version frozen: {tag_name} (checksum: {checksum[:12]})")
        return freeze
    
    def _save_freeze(self, freeze: VersionFreeze) -> None:
        """Save frozen version to disk."""
        freeze_dir = self._base_path / freeze.tag_name
        freeze_dir.mkdir(parents=True, exist_ok=True)
        
        # Save manifest
        manifest = {
            "tag_name": freeze.tag_name,
            "freeze_date": freeze.freeze_date,
            "frozen_by": freeze.frozen_by,
            "checksum": freeze.checksum,
            "notes": freeze.notes,
        }
        (freeze_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2)
        )
        
        # Save artifacts
        (freeze_dir / "feature_schema.json").write_text(
            json.dumps(freeze.feature_schema, indent=2)
        )
        (freeze_dir / "weights.json").write_text(
            json.dumps(freeze.weights, indent=2)
        )
        (freeze_dir / "calibration_report.json").write_text(
            json.dumps(freeze.calibration_report, indent=2)
        )
        (freeze_dir / "audit_report.json").write_text(
            json.dumps(freeze.audit_report, indent=2)
        )
    
    def load_freeze(self, tag_name: str) -> Optional[VersionFreeze]:
        """Load a frozen version."""
        freeze_dir = self._base_path / tag_name
        if not freeze_dir.exists():
            return None
        
        manifest = json.loads((freeze_dir / "manifest.json").read_text())
        
        return VersionFreeze(
            tag_name=manifest["tag_name"],
            freeze_date=manifest["freeze_date"],
            feature_schema=json.loads((freeze_dir / "feature_schema.json").read_text()),
            weights=json.loads((freeze_dir / "weights.json").read_text()),
            calibration_report=json.loads((freeze_dir / "calibration_report.json").read_text()),
            audit_report=json.loads((freeze_dir / "audit_report.json").read_text()),
            frozen_by=manifest["frozen_by"],
            checksum=manifest["checksum"],
            notes=manifest.get("notes", ""),
        )
    
    def list_frozen_versions(self) -> List[str]:
        """List all frozen version tags."""
        return [
            d.name for d in self._base_path.iterdir()
            if d.is_dir() and (d / "manifest.json").exists()
        ]
    
    def verify_integrity(self, tag_name: str) -> Tuple[bool, str]:
        """Verify integrity of frozen version."""
        freeze = self.load_freeze(tag_name)
        if not freeze:
            return False, f"Version not found: {tag_name}"
        
        # Recompute checksum
        checksum_data = {
            "feature_schema": freeze.feature_schema,
            "weights": freeze.weights,
            "calibration_report": freeze.calibration_report,
            "audit_report": freeze.audit_report,
        }
        computed = hashlib.sha256(
            json.dumps(checksum_data, sort_keys=True).encode()
        ).hexdigest()
        
        if computed == freeze.checksum:
            return True, "Integrity verified"
        return False, f"Checksum mismatch: expected {freeze.checksum}, got {computed}"


# ==============================================================================
# V. DRIFT REPORT GENERATOR
# ==============================================================================

@dataclass
class DriftReport:
    """Automatic drift analysis report."""
    report_id: str
    generated_at: str
    period_start: str
    period_end: str
    
    # Drift metrics
    feature_drift: float
    confidence_drift: float
    rank_drift: float
    score_drift: float
    
    # Trend analysis
    trend_direction: str  # "stable", "improving", "degrading"
    trend_magnitude: float
    
    # Alerts in period
    alerts_triggered: int
    critical_alerts: int
    
    # Recommendation
    recommendation: str
    recalibration_needed: bool


class DriftReportGenerator:
    """
    Generates automatic drift reports.
    
    Analyzes weekly snapshots to detect drift patterns.
    """
    
    def __init__(self, snapshot_store: Optional[Path] = None):
        self._snapshot_store = snapshot_store or Path("backend/data/monitoring/snapshots")
        self._snapshot_store.mkdir(parents=True, exist_ok=True)
    
    def generate_report(
        self,
        snapshots: List[WeeklySnapshot],
        alerts: List[Alert],
    ) -> DriftReport:
        """
        Generate drift report from snapshots.
        
        Args:
            snapshots: List of weekly snapshots (chronological order)
            alerts: List of alerts in period
        
        Returns:
            DriftReport with analysis
        """
        if len(snapshots) < 2:
            raise ValueError("Need at least 2 snapshots for drift analysis")
        
        first = snapshots[0]
        last = snapshots[-1]
        
        # Compute drift metrics
        feature_drift = self._compute_drift(
            [s.feature_mean for s in snapshots]
        )
        confidence_drift = self._compute_drift(
            [s.confidence_average for s in snapshots]
        )
        rank_drift = self._compute_drift(
            [s.top3_stability for s in snapshots]
        )
        score_drift = self._compute_drift(
            [s.score_variance for s in snapshots]
        )
        
        # Analyze trend
        trend_direction, trend_magnitude = self._analyze_trend(
            [s.confidence_average for s in snapshots]
        )
        
        # Count alerts
        critical_count = sum(
            1 for a in alerts if a.severity == AlertSeverity.CRITICAL
        )
        
        # Determine recommendation
        recommendation, needs_recal = self._get_recommendation(
            feature_drift, confidence_drift, rank_drift, score_drift,
            critical_count,
        )
        
        return DriftReport(
            report_id=f"DRIFT_{last.snapshot_id}",
            generated_at=datetime.utcnow().isoformat(),
            period_start=first.timestamp,
            period_end=last.timestamp,
            feature_drift=feature_drift,
            confidence_drift=confidence_drift,
            rank_drift=rank_drift,
            score_drift=score_drift,
            trend_direction=trend_direction,
            trend_magnitude=trend_magnitude,
            alerts_triggered=len(alerts),
            critical_alerts=critical_count,
            recommendation=recommendation,
            recalibration_needed=needs_recal,
        )
    
    def _compute_drift(self, values: List[float]) -> float:
        """Compute drift as relative change from first to last."""
        if len(values) < 2:
            return 0.0
        first = values[0]
        last = values[-1]
        if abs(first) < 0.001:
            return abs(last)
        return abs(last - first) / abs(first)
    
    def _analyze_trend(self, values: List[float]) -> Tuple[str, float]:
        """Analyze trend direction and magnitude."""
        if len(values) < 2:
            return "stable", 0.0
        
        # Linear regression slope
        n = len(values)
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(values)
        
        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        if abs(denominator) < 0.001:
            return "stable", 0.0
        
        slope = numerator / denominator
        
        if slope > 0.01:
            return "improving", abs(slope)
        elif slope < -0.01:
            return "degrading", abs(slope)
        return "stable", abs(slope)
    
    def _get_recommendation(
        self,
        feature_drift: float,
        confidence_drift: float,
        rank_drift: float,
        score_drift: float,
        critical_alerts: int,
    ) -> Tuple[str, bool]:
        """Generate recommendation based on drift analysis."""
        # Check for critical conditions
        if critical_alerts > 0:
            return "URGENT: Critical alerts detected. Immediate review required.", True
        
        if feature_drift > 0.20:
            return "Feature distribution has shifted significantly. Recalibration recommended.", True
        
        if confidence_drift > 0.15:
            return "Confidence scores degrading. Review data quality.", True
        
        if rank_drift > 0.20:
            return "Rank stability declining. Review scoring model.", True
        
        if score_drift > 0.10:
            return "Score variance increasing. Monitor closely.", False
        
        return "System stable. Continue normal monitoring.", False


# ==============================================================================
# VI. SNAPSHOT COLLECTOR
# ==============================================================================

class SnapshotCollector:
    """
    Collects weekly snapshots of system metrics.
    
    Runs automatically every Sunday at 00:00 UTC.
    """
    
    def __init__(
        self,
        snapshot_store: Optional[Path] = None,
        data_source: Optional[Any] = None,
    ):
        self._snapshot_store = snapshot_store or Path("backend/data/monitoring/snapshots")
        self._snapshot_store.mkdir(parents=True, exist_ok=True)
        self._data_source = data_source
    
    def collect_snapshot(
        self,
        sample_data: List[Dict[str, Any]],
        previous_snapshot: Optional[WeeklySnapshot] = None,
    ) -> WeeklySnapshot:
        """
        Collect weekly snapshot from sample data.
        
        Args:
            sample_data: List of scoring samples with features and scores
            previous_snapshot: Previous week's snapshot for comparison
        
        Returns:
            WeeklySnapshot with computed metrics
        """
        now = datetime.utcnow()
        week_number = now.isocalendar()[1]
        year = now.year
        
        # Extract features
        features = [s.get("feature_vector", {}) for s in sample_data]
        feature_values = []
        for f in features:
            if isinstance(f, dict):
                feature_values.extend(
                    v for v in f.values() if isinstance(v, (int, float))
                )
        
        if not feature_values:
            feature_values = [0.5]  # Default
        
        # Extract confidence scores
        confidence_scores = [
            s.get("confidence_score", 0.5) for s in sample_data
        ]
        
        # Extract scores for variance
        scores = [s.get("final_score", 0.5) for s in sample_data]
        
        # Compute rank stability
        top3_stability = self._compute_rank_stability(
            sample_data, previous_snapshot
        )
        rank_correlation = self._compute_rank_correlation(
            sample_data, previous_snapshot
        )
        
        # Compute data hash
        data_hash = hashlib.sha256(
            json.dumps(sample_data, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        
        # Create snapshot
        snapshot = WeeklySnapshot(
            snapshot_id=f"SNAP_{year}W{week_number:02d}",
            timestamp=now.isoformat(),
            week_number=week_number,
            year=year,
            
            # Feature metrics
            feature_count=len(feature_values),
            feature_mean=statistics.mean(feature_values),
            feature_std=statistics.stdev(feature_values) if len(feature_values) > 1 else 0,
            feature_min=min(feature_values),
            feature_max=max(feature_values),
            feature_percentiles=self._compute_percentiles(feature_values),
            
            # Confidence metrics
            confidence_average=statistics.mean(confidence_scores),
            confidence_std=statistics.stdev(confidence_scores) if len(confidence_scores) > 1 else 0,
            confidence_min=min(confidence_scores),
            confidence_max=max(confidence_scores),
            low_confidence_ratio=sum(1 for c in confidence_scores if c < 0.6) / len(confidence_scores),
            
            # Rank metrics
            top3_stability=top3_stability,
            rank_correlation=rank_correlation,
            rank_churn=1.0 - top3_stability,
            
            # Score metrics
            score_variance=statistics.variance(scores) if len(scores) > 1 else 0,
            score_std=statistics.stdev(scores) if len(scores) > 1 else 0,
            score_range=max(scores) - min(scores),
            inter_career_variance=self._compute_inter_career_variance(sample_data),
            
            # Metadata
            sample_count=len(sample_data),
            data_hash=data_hash,
        )
        
        # Save snapshot
        self._save_snapshot(snapshot)
        
        return snapshot
    
    def _compute_percentiles(self, values: List[float]) -> Dict[str, float]:
        """Compute percentiles."""
        sorted_values = sorted(values)
        n = len(sorted_values)
        
        def percentile(p: float) -> float:
            k = (n - 1) * p
            f = int(k)
            c = f + 1
            if c >= n:
                return sorted_values[-1]
            return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])
        
        return {
            "p25": round(percentile(0.25), 4),
            "p50": round(percentile(0.50), 4),
            "p75": round(percentile(0.75), 4),
            "p90": round(percentile(0.90), 4),
            "p95": round(percentile(0.95), 4),
        }
    
    def _compute_rank_stability(
        self,
        current_data: List[Dict[str, Any]],
        previous_snapshot: Optional[WeeklySnapshot],
    ) -> float:
        """Compute top-3 rank stability."""
        if not previous_snapshot:
            return 1.0  # Baseline
        
        # Simplified: compare top career consistency
        # In production, would compare actual user rankings
        return 0.92  # Placeholder
    
    def _compute_rank_correlation(
        self,
        current_data: List[Dict[str, Any]],
        previous_snapshot: Optional[WeeklySnapshot],
    ) -> float:
        """Compute Spearman rank correlation."""
        if not previous_snapshot:
            return 1.0
        
        # Simplified correlation
        return 0.95  # Placeholder
    
    def _compute_inter_career_variance(
        self,
        sample_data: List[Dict[str, Any]],
    ) -> float:
        """Compute variance between careers for same user."""
        # Extract per-user career scores
        all_variances = []
        for sample in sample_data:
            career_scores = sample.get("career_scores", [])
            if len(career_scores) > 1:
                all_variances.append(statistics.variance(career_scores))
        
        if not all_variances:
            return 0.0
        return statistics.mean(all_variances)
    
    def _save_snapshot(self, snapshot: WeeklySnapshot) -> None:
        """Save snapshot to disk."""
        snapshot_path = self._snapshot_store / f"{snapshot.snapshot_id}.json"
        data = {
            "snapshot_id": snapshot.snapshot_id,
            "timestamp": snapshot.timestamp,
            "week_number": snapshot.week_number,
            "year": snapshot.year,
            "feature_count": snapshot.feature_count,
            "feature_mean": snapshot.feature_mean,
            "feature_std": snapshot.feature_std,
            "feature_min": snapshot.feature_min,
            "feature_max": snapshot.feature_max,
            "feature_percentiles": snapshot.feature_percentiles,
            "confidence_average": snapshot.confidence_average,
            "confidence_std": snapshot.confidence_std,
            "confidence_min": snapshot.confidence_min,
            "confidence_max": snapshot.confidence_max,
            "low_confidence_ratio": snapshot.low_confidence_ratio,
            "top3_stability": snapshot.top3_stability,
            "rank_correlation": snapshot.rank_correlation,
            "rank_churn": snapshot.rank_churn,
            "score_variance": snapshot.score_variance,
            "score_std": snapshot.score_std,
            "score_range": snapshot.score_range,
            "inter_career_variance": snapshot.inter_career_variance,
            "sample_count": snapshot.sample_count,
            "data_hash": snapshot.data_hash,
        }
        snapshot_path.write_text(json.dumps(data, indent=2))
    
    def load_snapshots(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[WeeklySnapshot]:
        """Load snapshots for date range."""
        snapshots = []
        for path in sorted(self._snapshot_store.glob("SNAP_*.json")):
            data = json.loads(path.read_text())
            snapshot = WeeklySnapshot(**data)
            
            # Filter by date if specified
            if start_date and snapshot.timestamp < start_date:
                continue
            if end_date and snapshot.timestamp > end_date:
                continue
            
            snapshots.append(snapshot)
        
        return snapshots


# ==============================================================================
# VII. MAIN STABILITY CONTROLLER
# ==============================================================================

class StabilityController:
    """
    Main stability control system.
    
    Integrates all components:
    - Snapshot collection
    - Alert evaluation
    - Drift reporting
    - Review scheduling
    - Version freezing
    """
    
    def __init__(
        self,
        base_path: Optional[Path] = None,
    ):
        self._base_path = base_path or Path("backend/data/monitoring")
        self._base_path.mkdir(parents=True, exist_ok=True)
        
        self._collector = SnapshotCollector(self._base_path / "snapshots")
        self._alert_policy = AlertPolicy()
        self._scheduler = ReviewScheduler(self._base_path / "reviews")
        self._freezer = VersionFreezer(self._base_path / "frozen")
        self._drift_generator = DriftReportGenerator(self._base_path / "snapshots")
    
    def run_weekly_collection(
        self,
        sample_data: List[Dict[str, Any]],
    ) -> Tuple[WeeklySnapshot, List[Alert]]:
        """
        Run weekly snapshot collection and alert evaluation.
        
        Args:
            sample_data: Scoring samples from the week
        
        Returns:
            (snapshot, alerts) tuple
        """
        # Load previous snapshot
        snapshots = self._collector.load_snapshots()
        previous = snapshots[-1] if snapshots else None
        
        # Collect new snapshot
        snapshot = self._collector.collect_snapshot(sample_data, previous)
        
        # Evaluate alerts
        alerts = self._alert_policy.evaluate(snapshot, previous)
        
        logger.info(
            f"Weekly collection: {snapshot.snapshot_id}, "
            f"{len(alerts)} alerts triggered"
        )
        
        return snapshot, alerts
    
    def generate_drift_report(
        self,
        weeks: int = 4,
    ) -> DriftReport:
        """
        Generate drift report for recent weeks.
        
        Args:
            weeks: Number of weeks to analyze
        
        Returns:
            DriftReport with analysis
        """
        snapshots = self._collector.load_snapshots()[-weeks:]
        alerts = self._alert_policy.get_active_alerts()
        
        return self._drift_generator.generate_report(snapshots, alerts)
    
    def freeze_version(
        self,
        tag_name: str,
        feature_schema: Dict[str, Any],
        calibration_report: Dict[str, Any],
        audit_report: Dict[str, Any],
        notes: str = "",
    ) -> VersionFreeze:
        """
        Freeze current version.
        
        Args:
            tag_name: Version tag
            feature_schema: Feature schema
            calibration_report: Calibration report
            audit_report: Audit report
            notes: Release notes
        
        Returns:
            Frozen version artifact
        """
        return self._freezer.freeze(
            tag_name=tag_name,
            feature_schema=feature_schema,
            weights=FROZEN_WEIGHTS,
            calibration_report=calibration_report,
            audit_report=audit_report,
            notes=notes,
        )
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get current system stability status."""
        snapshots = self._collector.load_snapshots()
        alerts = self._alert_policy.get_active_alerts()
        pending_reviews = self._scheduler.get_pending_reviews()
        overdue_reviews = self._scheduler.get_overdue_reviews()
        frozen_versions = self._freezer.list_frozen_versions()
        
        latest_snapshot = snapshots[-1] if snapshots else None
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_snapshots": len(snapshots),
            "latest_snapshot": latest_snapshot.snapshot_id if latest_snapshot else None,
            "active_alerts": len(alerts),
            "critical_alerts": sum(1 for a in alerts if a.severity == AlertSeverity.CRITICAL),
            "pending_reviews": len(pending_reviews),
            "overdue_reviews": len(overdue_reviews),
            "frozen_versions": frozen_versions,
            "system_health": self._compute_health_score(latest_snapshot, alerts),
        }
    
    def _compute_health_score(
        self,
        snapshot: Optional[WeeklySnapshot],
        alerts: List[Alert],
    ) -> str:
        """Compute overall system health."""
        if not snapshot:
            return "UNKNOWN"
        
        critical = sum(1 for a in alerts if a.severity == AlertSeverity.CRITICAL)
        warnings = sum(1 for a in alerts if a.severity == AlertSeverity.WARNING)
        
        if critical > 0:
            return "CRITICAL"
        if warnings > 2:
            return "DEGRADED"
        if snapshot.confidence_average < 0.5:
            return "WARNING"
        return "HEALTHY"


# ==============================================================================
# VIII. CONVENIENCE FUNCTIONS
# ==============================================================================

def create_stability_controller(
    base_path: Optional[Path] = None,
) -> StabilityController:
    """Factory function for stability controller."""
    return StabilityController(base_path)


def freeze_one_button_v1_stable(
    feature_schema: Dict[str, Any],
    calibration_report: Dict[str, Any],
    audit_report: Dict[str, Any],
) -> VersionFreeze:
    """
    Freeze one_button_v1_stable version.
    
    Creates immutable snapshot with:
    - feature_schema
    - weights (FROZEN_WEIGHTS)
    - calibration_report
    - audit_report
    """
    controller = create_stability_controller()
    return controller.freeze_version(
        tag_name="one_button_v1_stable",
        feature_schema=feature_schema,
        calibration_report=calibration_report,
        audit_report=audit_report,
        notes="Initial stable release of One-Button flow system.",
    )


# ==============================================================================
# IX. EXAMPLE USAGE
# ==============================================================================

if __name__ == "__main__":
    # Demo: Create stability controller
    controller = create_stability_controller()
    
    # Demo: Generate sample data
    sample_data = [
        {
            "feature_vector": {"skill_match": 0.8, "market_demand": 0.7},
            "confidence_score": 0.75,
            "final_score": 0.73,
            "career_scores": [0.73, 0.68, 0.65],
        }
        for _ in range(100)
    ]
    
    # Run weekly collection
    snapshot, alerts = controller.run_weekly_collection(sample_data)
    print(f"Snapshot: {snapshot.snapshot_id}")
    print(f"Alerts: {len(alerts)}")
    
    # Get system status
    status = controller.get_system_status()
    print(f"Health: {status['system_health']}")

# backend/monitoring/__init__.py
"""
Monitoring Module
=================

Long-term stability control for Hybrid Decision Support System.

Components:
- StabilityController: Main orchestrator
- SnapshotCollector: Weekly metric collection
- AlertPolicy: Threshold-based alerting
- DriftReportGenerator: Automatic drift analysis
- ReviewScheduler: Quarterly recalibration scheduling
- VersionFreezer: Stable release management

EXPORTS:
- StabilityController, create_stability_controller
- WeeklySnapshot, DriftReport, Alert
- AlertPolicy, AlertThreshold, AlertSeverity
- VersionFreezer, VersionFreeze
- freeze_one_button_v1_stable
"""

from backend.monitoring.stability_control import (
    # Main controller
    StabilityController,
    create_stability_controller,
    
    # Snapshots
    WeeklySnapshot,
    SnapshotCollector,
    MetricType,
    
    # Alerts
    Alert,
    AlertPolicy,
    AlertThreshold,
    AlertSeverity,
    
    # Drift
    DriftReport,
    DriftReportGenerator,
    
    # Reviews
    ReviewScheduler,
    ScheduledReview,
    ReviewType,
    
    # Versioning
    VersionFreezer,
    VersionFreeze,
    freeze_one_button_v1_stable,
    
    # Constants
    FROZEN_WEIGHTS,
    DEFAULT_THRESHOLDS,
)

__all__ = [
    # Main
    "StabilityController",
    "create_stability_controller",
    
    # Snapshots
    "WeeklySnapshot",
    "SnapshotCollector",
    "MetricType",
    
    # Alerts
    "Alert",
    "AlertPolicy",
    "AlertThreshold",
    "AlertSeverity",
    
    # Drift
    "DriftReport",
    "DriftReportGenerator",
    
    # Reviews
    "ReviewScheduler",
    "ScheduledReview",
    "ReviewType",
    
    # Versioning
    "VersionFreezer",
    "VersionFreeze",
    "freeze_one_button_v1_stable",
    
    # Constants
    "FROZEN_WEIGHTS",
    "DEFAULT_THRESHOLDS",
]

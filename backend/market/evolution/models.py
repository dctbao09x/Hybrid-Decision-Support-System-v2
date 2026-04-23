# backend/market/evolution/models.py
"""
Data models for Autonomous Evolution Loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class EvolutionStage(Enum):
    """Stages in the evolution cycle."""
    COLLECT = "collect"         # Gather market data
    ANALYZE = "analyze"         # Analyze trends and drift
    PREDICT = "predict"         # Generate forecasts
    UPDATE = "update"           # Update taxonomy/scoring
    VALIDATE = "validate"       # Validate changes
    DEPLOY = "deploy"           # Deploy changes
    MONITOR = "monitor"         # Monitor impact
    LEARN = "learn"             # Learn from outcomes


class CycleStatus(Enum):
    """Status of evolution cycle."""
    PENDING = "pending"
    RUNNING = "running"
    VALIDATING = "validating"
    AWAITING_APPROVAL = "awaiting_approval"
    DEPLOYING = "deploying"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class EvolutionState:
    """
    Current state of the evolution system.
    
    Attributes:
        state_id: Unique identifier
        current_stage: Current stage in cycle
        last_cycle_id: Most recent completed cycle
        last_update: When state was last changed
        health_status: Overall system health
        pending_changes: Number of pending changes
        active_experiments: Running A/B tests
        error_count: Recent errors
        metrics: Key performance metrics
    """
    state_id: str
    current_stage: Optional[EvolutionStage] = None
    last_cycle_id: Optional[str] = None
    last_update: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    health_status: str = "healthy"
    pending_changes: int = 0
    active_experiments: int = 0
    error_count: int = 0
    metrics: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_id": self.state_id,
            "current_stage": self.current_stage.value if self.current_stage else None,
            "last_cycle_id": self.last_cycle_id,
            "last_update": self.last_update.isoformat(),
            "health_status": self.health_status,
            "pending_changes": self.pending_changes,
            "active_experiments": self.active_experiments,
            "error_count": self.error_count,
            "metrics": self.metrics,
        }


@dataclass
class StageResult:
    """
    Result from executing a stage.
    """
    stage: EvolutionStage
    success: bool
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    items_processed: int = 0
    changes_proposed: int = 0
    errors: List[str] = field(default_factory=list)
    outputs: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage.value,
            "success": self.success,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "items_processed": self.items_processed,
            "changes_proposed": self.changes_proposed,
            "errors": self.errors,
            "outputs": self.outputs,
        }


@dataclass
class EvolutionCycle:
    """
    Complete evolution cycle record.
    
    Attributes:
        cycle_id: Unique identifier
        started_at: When cycle began
        completed_at: When cycle ended
        status: Current status
        trigger: What triggered this cycle
        stage_results: Results from each stage
        total_changes: Total changes made
        rolled_back: Whether changes were rolled back
        summary: Human-readable summary
    """
    cycle_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    status: CycleStatus = CycleStatus.PENDING
    trigger: str = "scheduled"
    stage_results: List[StageResult] = field(default_factory=list)
    total_changes: int = 0
    rolled_back: bool = False
    summary: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status.value,
            "trigger": self.trigger,
            "stage_results": [r.to_dict() for r in self.stage_results],
            "total_changes": self.total_changes,
            "rolled_back": self.rolled_back,
            "summary": self.summary,
        }


@dataclass
class ValidationResult:
    """
    Result of change validation.
    
    Attributes:
        validation_id: Unique identifier
        cycle_id: Related cycle
        passed: Whether validation passed
        checks_run: Number of validation checks
        checks_passed: Number passed
        checks_failed: Number failed
        failures: Details of failures
        warnings: Non-blocking warnings
        recommendations: Validation recommendations
    """
    validation_id: str
    cycle_id: str
    passed: bool
    checks_run: int = 0
    checks_passed: int = 0
    checks_failed: int = 0
    failures: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "validation_id": self.validation_id,
            "cycle_id": self.cycle_id,
            "passed": self.passed,
            "checks_run": self.checks_run,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "failures": self.failures,
            "warnings": self.warnings,
            "recommendations": self.recommendations,
        }


@dataclass
class DeploymentPlan:
    """
    Plan for deploying changes.
    
    Attributes:
        plan_id: Unique identifier
        cycle_id: Related cycle
        changes: List of changes to deploy
        deployment_strategy: Blue-green, canary, etc.
        rollout_percentage: Initial rollout percentage
        success_criteria: Criteria for full rollout
        rollback_trigger: Automatic rollback triggers
        scheduled_at: When deployment is scheduled
    """
    plan_id: str
    cycle_id: str
    changes: List[Dict[str, Any]] = field(default_factory=list)
    deployment_strategy: str = "canary"
    rollout_percentage: float = 10.0
    success_criteria: Dict[str, float] = field(default_factory=dict)
    rollback_trigger: Dict[str, float] = field(default_factory=dict)
    scheduled_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "cycle_id": self.cycle_id,
            "changes": self.changes,
            "deployment_strategy": self.deployment_strategy,
            "rollout_percentage": self.rollout_percentage,
            "success_criteria": self.success_criteria,
            "rollback_trigger": self.rollback_trigger,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
        }


@dataclass
class MonitoringReport:
    """
    Monitoring report after deployment.
    
    Attributes:
        report_id: Unique identifier
        cycle_id: Related cycle
        period_start: Monitoring period start
        period_end: Monitoring period end
        metrics_before: Metrics before change
        metrics_after: Metrics after change
        anomalies_detected: Any anomalies found
        user_feedback: User feedback received
        recommendation: Continue/rollback recommendation
    """
    report_id: str
    cycle_id: str
    period_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    period_end: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metrics_before: Dict[str, float] = field(default_factory=dict)
    metrics_after: Dict[str, float] = field(default_factory=dict)
    anomalies_detected: List[str] = field(default_factory=list)
    user_feedback: Dict[str, Any] = field(default_factory=dict)
    recommendation: str = "continue"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "cycle_id": self.cycle_id,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "metrics_before": self.metrics_before,
            "metrics_after": self.metrics_after,
            "anomalies_detected": self.anomalies_detected,
            "user_feedback": self.user_feedback,
            "recommendation": self.recommendation,
        }


@dataclass
class LearningInsight:
    """
    Insight learned from cycle outcomes.
    
    Attributes:
        insight_id: Unique identifier
        cycle_id: Source cycle
        insight_type: Type of insight
        description: What was learned
        confidence: Confidence in insight
        applicable_to: What components this applies to
        action_taken: What action was taken
        impact: Impact of the learning
    """
    insight_id: str
    cycle_id: str
    insight_type: str = ""
    description: str = ""
    confidence: float = 1.0
    applicable_to: List[str] = field(default_factory=list)
    action_taken: str = ""
    impact: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "insight_id": self.insight_id,
            "cycle_id": self.cycle_id,
            "insight_type": self.insight_type,
            "description": self.description,
            "confidence": self.confidence,
            "applicable_to": self.applicable_to,
            "action_taken": self.action_taken,
            "impact": self.impact,
        }


@dataclass
class EvolutionConfig:
    """
    Configuration for evolution system.
    """
    # Scheduling
    cycle_interval_hours: int = 24
    min_data_points_for_cycle: int = 100
    
    # Validation
    required_validation_pass_rate: float = 0.9
    max_change_per_cycle: float = 0.2  # Max 20% change
    
    # Deployment
    default_canary_percentage: float = 10.0
    canary_duration_hours: int = 24
    full_rollout_threshold: float = 0.95  # 95% success for full rollout
    
    # Rollback
    auto_rollback_error_rate: float = 0.05  # 5% error triggers rollback
    auto_rollback_latency_increase: float = 2.0  # 2x latency triggers rollback
    
    # Learning
    min_samples_for_learning: int = 50
    learning_lookback_cycles: int = 10

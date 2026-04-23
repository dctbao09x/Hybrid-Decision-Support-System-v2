# backend/ops/governance/models.py
"""
Governance Data Models
======================

Core data structures for operational governance:
- OpsRecord: Per-inference operational record
- CostRecord: Cost tracking per call/user/model
- DriftRecord: Data and concept drift metrics
- RiskScore: Composite risk assessment
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class InferenceStatus(str, Enum):
    """Status of an inference operation."""
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    DEGRADED = "degraded"
    CACHED = "cached"


class DriftType(str, Enum):
    """Types of drift."""
    DATA = "data"
    CONCEPT = "concept"
    FEATURE = "feature"
    LABEL = "label"


class RiskLevel(str, Enum):
    """Risk severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class OpsRecord:
    """
    Per-inference operational record.
    
    Emitted for every inference call to track:
    - Performance (latency)
    - Cost
    - Model/trace identification
    - Drift indicators
    - Status
    """
    trace_id: str
    latency_ms: float
    cost_usd: float
    model_id: str
    drift_score: float
    status: InferenceStatus
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    # Optional enrichment
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    endpoint: Optional[str] = None
    input_size: Optional[int] = None
    output_size: Optional[int] = None
    confidence: Optional[float] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if isinstance(self.status, str):
            self.status = InferenceStatus(self.status)
    
    @property
    def record_id(self) -> str:
        """Generate unique record ID from trace_id and timestamp."""
        data = f"{self.trace_id}:{self.timestamp}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "record_id": self.record_id,
            "trace_id": self.trace_id,
            "latency_ms": round(self.latency_ms, 2),
            "cost_usd": round(self.cost_usd, 6),
            "model_id": self.model_id,
            "drift_score": round(self.drift_score, 4),
            "status": self.status.value,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "endpoint": self.endpoint,
            "input_size": self.input_size,
            "output_size": self.output_size,
            "confidence": round(self.confidence, 4) if self.confidence else None,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OpsRecord":
        """Create from dictionary."""
        return cls(
            trace_id=data["trace_id"],
            latency_ms=data["latency_ms"],
            cost_usd=data["cost_usd"],
            model_id=data["model_id"],
            drift_score=data["drift_score"],
            status=data["status"],
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            endpoint=data.get("endpoint"),
            input_size=data.get("input_size"),
            output_size=data.get("output_size"),
            confidence=data.get("confidence"),
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class CostRecord:
    """
    Cost tracking record.
    
    Tracks costs per:
    - Individual call
    - User
    - Model
    - Time period
    """
    timestamp: str
    cost_usd: float
    model_id: str
    call_count: int = 1
    user_id: Optional[str] = None
    endpoint: Optional[str] = None
    
    # Cost breakdown
    compute_cost: float = 0.0
    api_cost: float = 0.0
    storage_cost: float = 0.0
    network_cost: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "cost_usd": round(self.cost_usd, 6),
            "model_id": self.model_id,
            "call_count": self.call_count,
            "user_id": self.user_id,
            "endpoint": self.endpoint,
            "breakdown": {
                "compute": round(self.compute_cost, 6),
                "api": round(self.api_cost, 6),
                "storage": round(self.storage_cost, 6),
                "network": round(self.network_cost, 6),
            },
        }


@dataclass
class DriftRecord:
    """
    Drift measurement record.
    
    Tracks:
    - Data drift: Distribution changes in input features
    - Concept drift: Changes in input-output relationships
    - Feature drift: Individual feature distribution changes
    """
    timestamp: str
    drift_type: DriftType
    score: float  # 0.0 (no drift) to 1.0 (severe drift)
    model_id: str
    
    # Detailed metrics
    feature_drifts: Dict[str, float] = field(default_factory=dict)
    reference_period: Optional[str] = None
    comparison_period: Optional[str] = None
    sample_size: int = 0
    
    # Statistical tests
    test_statistic: Optional[float] = None
    p_value: Optional[float] = None
    test_method: Optional[str] = None
    
    threshold: float = 0.3  # Drift threshold for alerts
    
    @property
    def is_significant(self) -> bool:
        """Check if drift exceeds threshold."""
        return self.score >= self.threshold
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "drift_type": self.drift_type.value,
            "score": round(self.score, 4),
            "model_id": self.model_id,
            "is_significant": self.is_significant,
            "feature_drifts": {k: round(v, 4) for k, v in self.feature_drifts.items()},
            "reference_period": self.reference_period,
            "comparison_period": self.comparison_period,
            "sample_size": self.sample_size,
            "statistics": {
                "test_statistic": self.test_statistic,
                "p_value": self.p_value,
                "test_method": self.test_method,
            },
            "threshold": self.threshold,
        }


@dataclass
class RiskScore:
    """
    Composite risk assessment.
    
    Combines multiple risk factors:
    - Drift risk
    - Latency risk
    - Error risk
    - Cost overrun risk
    
    Formula:
        risk = w1*drift + w2*latency + w3*error + w4*cost_overrun
    """
    timestamp: str
    composite_score: float
    risk_level: RiskLevel
    
    # Component scores (0.0 to 1.0)
    drift_risk: float = 0.0
    latency_risk: float = 0.0
    error_risk: float = 0.0
    cost_risk: float = 0.0
    
    # Weights used in calculation
    weights: Dict[str, float] = field(default_factory=lambda: {
        "drift": 0.3,
        "latency": 0.25,
        "error": 0.3,
        "cost": 0.15,
    })
    
    # Context
    model_id: Optional[str] = None
    period: Optional[str] = None
    sample_count: int = 0
    
    # Recommendations
    recommendations: List[str] = field(default_factory=list)
    auto_mitigate: bool = False
    
    @classmethod
    def calculate(
        cls,
        drift_risk: float,
        latency_risk: float,
        error_risk: float,
        cost_risk: float,
        weights: Optional[Dict[str, float]] = None,
        model_id: Optional[str] = None,
        sample_count: int = 0,
    ) -> "RiskScore":
        """Calculate composite risk score from components."""
        w = weights or {
            "drift": 0.3,
            "latency": 0.25,
            "error": 0.3,
            "cost": 0.15,
        }
        
        # Clamp inputs to [0, 1]
        d = max(0.0, min(1.0, drift_risk))
        l = max(0.0, min(1.0, latency_risk))
        e = max(0.0, min(1.0, error_risk))
        c = max(0.0, min(1.0, cost_risk))
        
        # Calculate composite score
        composite = (
            w["drift"] * d +
            w["latency"] * l +
            w["error"] * e +
            w["cost"] * c
        )
        
        # Determine risk level
        if composite < 0.25:
            level = RiskLevel.LOW
        elif composite < 0.5:
            level = RiskLevel.MEDIUM
        elif composite < 0.75:
            level = RiskLevel.HIGH
        else:
            level = RiskLevel.CRITICAL
        
        # Generate recommendations
        recs = []
        if d > 0.5:
            recs.append("Monitor data drift closely; consider model retraining")
        if l > 0.5:
            recs.append("Investigate latency spikes; review infrastructure scaling")
        if e > 0.5:
            recs.append("High error rate detected; review error patterns and logs")
        if c > 0.5:
            recs.append("Cost overrun detected; review resource allocation")
        
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            composite_score=round(composite, 4),
            risk_level=level,
            drift_risk=round(d, 4),
            latency_risk=round(l, 4),
            error_risk=round(e, 4),
            cost_risk=round(c, 4),
            weights=w,
            model_id=model_id,
            sample_count=sample_count,
            recommendations=recs,
            auto_mitigate=composite >= 0.75,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "composite_score": self.composite_score,
            "risk_level": self.risk_level.value,
            "components": {
                "drift": self.drift_risk,
                "latency": self.latency_risk,
                "error": self.error_risk,
                "cost": self.cost_risk,
            },
            "weights": self.weights,
            "model_id": self.model_id,
            "period": self.period,
            "sample_count": self.sample_count,
            "recommendations": self.recommendations,
            "auto_mitigate": self.auto_mitigate,
        }


@dataclass
class SLAMetrics:
    """
    SLA-related metrics snapshot.
    
    Tracks:
    - Availability (uptime percentage)
    - Latency percentiles
    - Error rates
    """
    timestamp: str
    availability: float  # 0.0 to 1.0 (target: 0.999)
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    error_rate: float  # 0.0 to 1.0
    
    # Period covered
    period_start: str = ""
    period_end: str = ""
    sample_count: int = 0
    
    # SLA compliance
    target_availability: float = 0.999
    target_p95_latency_ms: float = 500.0
    target_error_rate: float = 0.01
    
    @property
    def availability_met(self) -> bool:
        return self.availability >= self.target_availability
    
    @property
    def latency_met(self) -> bool:
        return self.p95_latency_ms <= self.target_p95_latency_ms
    
    @property
    def error_rate_met(self) -> bool:
        return self.error_rate <= self.target_error_rate
    
    @property
    def overall_compliance(self) -> bool:
        return self.availability_met and self.latency_met and self.error_rate_met
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "metrics": {
                "availability": round(self.availability, 6),
                "p50_latency_ms": round(self.p50_latency_ms, 2),
                "p95_latency_ms": round(self.p95_latency_ms, 2),
                "p99_latency_ms": round(self.p99_latency_ms, 2),
                "error_rate": round(self.error_rate, 6),
            },
            "period": {
                "start": self.period_start,
                "end": self.period_end,
                "sample_count": self.sample_count,
            },
            "targets": {
                "availability": self.target_availability,
                "p95_latency_ms": self.target_p95_latency_ms,
                "error_rate": self.target_error_rate,
            },
            "compliance": {
                "availability_met": self.availability_met,
                "latency_met": self.latency_met,
                "error_rate_met": self.error_rate_met,
                "overall": self.overall_compliance,
            },
        }


@dataclass
class IncidentReport:
    """
    Incident record for tracking and replay.
    """
    incident_id: str
    title: str
    severity: str
    status: str  # open, investigating, resolved, closed
    
    timestamp_start: str
    timestamp_end: Optional[str] = None
    
    description: str = ""
    root_cause: str = ""
    resolution: str = ""
    
    affected_services: List[str] = field(default_factory=list)
    affected_users: int = 0
    
    # Timeline of events
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    
    # Related records
    related_alerts: List[str] = field(default_factory=list)
    related_traces: List[str] = field(default_factory=list)
    
    # Post-mortem
    lessons_learned: List[str] = field(default_factory=list)
    action_items: List[Dict[str, Any]] = field(default_factory=list)
    
    def add_timeline_event(self, event: str, details: Optional[Dict[str, Any]] = None):
        """Add event to incident timeline."""
        self.timeline.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "details": details or {},
        })
    
    def resolve(self, resolution: str):
        """Mark incident as resolved."""
        self.status = "resolved"
        self.resolution = resolution
        self.timestamp_end = datetime.now(timezone.utc).isoformat()
        self.add_timeline_event("Incident resolved", {"resolution": resolution})
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "title": self.title,
            "severity": self.severity,
            "status": self.status,
            "timestamps": {
                "start": self.timestamp_start,
                "end": self.timestamp_end,
            },
            "description": self.description,
            "root_cause": self.root_cause,
            "resolution": self.resolution,
            "affected_services": self.affected_services,
            "affected_users": self.affected_users,
            "timeline": self.timeline,
            "related": {
                "alerts": self.related_alerts,
                "traces": self.related_traces,
            },
            "post_mortem": {
                "lessons_learned": self.lessons_learned,
                "action_items": self.action_items,
            },
        }

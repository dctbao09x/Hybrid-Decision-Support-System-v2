# backend/ops/sla/contracts.py
"""
SLA Contracts
=============

Defines Service Level Agreement contracts and targets.

A contract specifies:
- Target uptime (availability)
- Maximum latency (p95)
- Maximum error rate
- Evaluation window

Violations are tracked when targets are not met.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class SLASeverity(str, Enum):
    """Severity level for SLA violations."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class SLAStatus(str, Enum):
    """Status of an SLA contract."""
    HEALTHY = "healthy"
    AT_RISK = "at_risk"
    BREACHED = "breached"


@dataclass
class SLATarget:
    """Individual SLA target metric."""
    name: str
    metric: str
    threshold: float
    comparison: str = "lte"  # "lte" (<=), "gte" (>=), "lt" (<), "gt" (>)
    severity: SLASeverity = SLASeverity.WARNING
    
    def evaluate(self, value: float) -> bool:
        """
        Evaluate if the target is met.
        
        Returns True if target is met, False if breached.
        """
        if self.comparison == "lte":
            return value <= self.threshold
        elif self.comparison == "gte":
            return value >= self.threshold
        elif self.comparison == "lt":
            return value < self.threshold
        elif self.comparison == "gt":
            return value > self.threshold
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "metric": self.metric,
            "threshold": self.threshold,
            "comparison": self.comparison,
            "severity": self.severity.value,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SLATarget":
        return cls(
            name=data["name"],
            metric=data["metric"],
            threshold=data["threshold"],
            comparison=data.get("comparison", "lte"),
            severity=SLASeverity(data.get("severity", "warning")),
        )


@dataclass
class SLAViolation:
    """Record of an SLA violation."""
    violation_id: str
    contract_id: str
    target_name: str
    metric: str
    threshold: float
    actual_value: float
    severity: SLASeverity
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    acknowledged: bool = False
    resolution: Optional[str] = None
    resolved_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "violation_id": self.violation_id,
            "contract_id": self.contract_id,
            "target_name": self.target_name,
            "metric": self.metric,
            "threshold": self.threshold,
            "actual_value": round(self.actual_value, 4),
            "severity": self.severity.value,
            "timestamp": self.timestamp,
            "acknowledged": self.acknowledged,
            "resolution": self.resolution,
            "resolved_at": self.resolved_at,
        }
    
    def acknowledge(self, resolution: Optional[str] = None) -> None:
        """Acknowledge the violation."""
        self.acknowledged = True
        if resolution:
            self.resolution = resolution
            self.resolved_at = datetime.now(timezone.utc).isoformat()


@dataclass
class SLAContract:
    """
    Service Level Agreement Contract.
    
    Defines targets for:
    - Availability (uptime percentage)
    - Latency (response time percentiles)
    - Error rate
    
    Example:
        contract = SLAContract(
            name="Production API",
            target_uptime=0.999,  # 99.9%
            max_latency_p95_ms=500,
            max_error_rate=0.01,  # 1%
        )
    """
    name: str
    target_uptime: float = 0.999  # 99.9%
    max_latency_p95_ms: float = 500.0
    max_error_rate: float = 0.01  # 1%
    
    # Optional targets
    max_latency_p99_ms: Optional[float] = None
    max_latency_avg_ms: Optional[float] = None
    min_throughput_rps: Optional[float] = None
    max_cost_per_request: Optional[float] = None
    max_drift_score: Optional[float] = None
    
    # Evaluation settings
    evaluation_window_minutes: int = 60
    grace_period_minutes: int = 5
    
    # Alert settings
    alert_channels: List[str] = field(default_factory=lambda: ["log", "file"])
    
    # Metadata
    contract_id: str = ""
    description: str = ""
    owner: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def __post_init__(self):
        if not self.contract_id:
            self.contract_id = self._generate_id()
    
    def _generate_id(self) -> str:
        """Generate unique contract ID."""
        data = f"{self.name}:{self.created_at}"
        return hashlib.sha256(data.encode()).hexdigest()[:12]
    
    @property
    def targets(self) -> List[SLATarget]:
        """Get all targets as SLATarget objects."""
        targets = [
            SLATarget(
                name="availability",
                metric="availability",
                threshold=self.target_uptime,
                comparison="gte",
                severity=SLASeverity.CRITICAL,
            ),
            SLATarget(
                name="latency_p95",
                metric="p95_latency_ms",
                threshold=self.max_latency_p95_ms,
                comparison="lte",
                severity=SLASeverity.WARNING,
            ),
            SLATarget(
                name="error_rate",
                metric="error_rate",
                threshold=self.max_error_rate,
                comparison="lte",
                severity=SLASeverity.CRITICAL,
            ),
        ]
        
        if self.max_latency_p99_ms is not None:
            targets.append(SLATarget(
                name="latency_p99",
                metric="p99_latency_ms",
                threshold=self.max_latency_p99_ms,
                comparison="lte",
                severity=SLASeverity.WARNING,
            ))
        
        if self.max_drift_score is not None:
            targets.append(SLATarget(
                name="drift_score",
                metric="drift_score",
                threshold=self.max_drift_score,
                comparison="lte",
                severity=SLASeverity.WARNING,
            ))
        
        if self.max_cost_per_request is not None:
            targets.append(SLATarget(
                name="cost_per_request",
                metric="avg_cost_per_request",
                threshold=self.max_cost_per_request,
                comparison="lte",
                severity=SLASeverity.INFO,
            ))
        
        return targets
    
    def evaluate(self, metrics: Dict[str, float]) -> Dict[str, Any]:
        """
        Evaluate metrics against the contract.
        
        Args:
            metrics: Dictionary of metric values
                Required: availability, p95_latency_ms, error_rate
                Optional: p99_latency_ms, drift_score, avg_cost_per_request
        
        Returns:
            Evaluation result with status and violations
        """
        violations = []
        results = {}
        
        for target in self.targets:
            value = metrics.get(target.metric)
            if value is None:
                results[target.name] = {"status": "unknown", "reason": "metric not provided"}
                continue
            
            met = target.evaluate(value)
            results[target.name] = {
                "met": met,
                "threshold": target.threshold,
                "actual": round(value, 4),
                "comparison": target.comparison,
            }
            
            if not met:
                violations.append(SLAViolation(
                    violation_id=hashlib.sha256(
                        f"{self.contract_id}:{target.metric}:{datetime.now().isoformat()}".encode()
                    ).hexdigest()[:16],
                    contract_id=self.contract_id,
                    target_name=target.name,
                    metric=target.metric,
                    threshold=target.threshold,
                    actual_value=value,
                    severity=target.severity,
                ))
        
        # Determine overall status
        if not violations:
            status = SLAStatus.HEALTHY
        elif any(v.severity == SLASeverity.CRITICAL for v in violations):
            status = SLAStatus.BREACHED
        else:
            status = SLAStatus.AT_RISK
        
        return {
            "contract_id": self.contract_id,
            "contract_name": self.name,
            "status": status.value,
            "evaluation_time": datetime.now(timezone.utc).isoformat(),
            "results": results,
            "violations": [v.to_dict() for v in violations],
            "violation_count": len(violations),
        }
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "name": self.name,
            "targets": {
                "uptime": self.target_uptime,
                "max_latency_p95_ms": self.max_latency_p95_ms,
                "max_latency_p99_ms": self.max_latency_p99_ms,
                "max_error_rate": self.max_error_rate,
                "max_drift_score": self.max_drift_score,
                "max_cost_per_request": self.max_cost_per_request,
            },
            "settings": {
                "evaluation_window_minutes": self.evaluation_window_minutes,
                "grace_period_minutes": self.grace_period_minutes,
                "alert_channels": self.alert_channels,
            },
            "metadata": {
                "description": self.description,
                "owner": self.owner,
                "created_at": self.created_at,
            },
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SLAContract":
        """Create contract from dictionary."""
        targets = data.get("targets", {})
        settings = data.get("settings", {})
        metadata = data.get("metadata", {})
        
        return cls(
            name=data.get("name", "default"),
            contract_id=data.get("contract_id", ""),
            target_uptime=targets.get("uptime", 0.999),
            max_latency_p95_ms=targets.get("max_latency_p95_ms", 500.0),
            max_latency_p99_ms=targets.get("max_latency_p99_ms"),
            max_error_rate=targets.get("max_error_rate", 0.01),
            max_drift_score=targets.get("max_drift_score"),
            max_cost_per_request=targets.get("max_cost_per_request"),
            evaluation_window_minutes=settings.get("evaluation_window_minutes", 60),
            grace_period_minutes=settings.get("grace_period_minutes", 5),
            alert_channels=settings.get("alert_channels", ["log", "file"]),
            description=metadata.get("description", ""),
            owner=metadata.get("owner", ""),
            created_at=metadata.get("created_at", datetime.now(timezone.utc).isoformat()),
        )


# Default production contract
DEFAULT_CONTRACT = SLAContract(
    name="Production API",
    description="Default SLA contract for production inference API",
    target_uptime=0.999,
    max_latency_p95_ms=500.0,
    max_latency_p99_ms=1000.0,
    max_error_rate=0.01,
    max_drift_score=0.3,
    evaluation_window_minutes=60,
)

# Stricter contract for critical endpoints
CRITICAL_CONTRACT = SLAContract(
    name="Critical Endpoints",
    description="Strict SLA for critical business endpoints",
    target_uptime=0.9999,  # 99.99%
    max_latency_p95_ms=200.0,
    max_latency_p99_ms=500.0,
    max_error_rate=0.001,  # 0.1%
    max_drift_score=0.2,
    evaluation_window_minutes=15,
)

# Relaxed contract for batch processing
BATCH_CONTRACT = SLAContract(
    name="Batch Processing",
    description="Relaxed SLA for batch/async processing",
    target_uptime=0.99,  # 99%
    max_latency_p95_ms=5000.0,  # 5s
    max_latency_p99_ms=10000.0,  # 10s
    max_error_rate=0.05,  # 5%
    evaluation_window_minutes=240,  # 4 hours
)

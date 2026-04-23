# -*- coding: utf-8 -*-
"""
Governance & Risk Control - Data Models
Enterprise-grade safety controls for autonomous system operations
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


# =============================================================================
# APPROVAL WORKFLOW MODELS
# =============================================================================

class ApprovalStatus(Enum):
    """Status of an approval request."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"
    ESCALATED = "escalated"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class ApprovalDecision(Enum):
    """Decision types for approval."""
    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"
    ESCALATE = "escalate"
    REQUEST_INFO = "request_info"


@dataclass
class ApprovalGate:
    """
    Defines an approval gate that requires human review.
    
    Gates are triggered by specific change types or risk levels.
    """
    gate_id: str
    name: str
    description: str
    
    # Trigger conditions
    trigger_change_types: List[str] = field(default_factory=list)  # e.g., ["taxonomy_merge", "scoring_update"]
    trigger_risk_levels: List[str] = field(default_factory=list)  # e.g., ["high", "critical"]
    trigger_confidence_below: float = 0.0  # Trigger if confidence below this
    
    # Approval requirements
    required_approvers: int = 1
    approver_roles: List[str] = field(default_factory=lambda: ["admin", "data_scientist"])
    
    # Timeouts
    timeout_hours: int = 24
    auto_approve_after_timeout: bool = False
    escalation_after_hours: int = 12
    escalation_roles: List[str] = field(default_factory=lambda: ["senior_admin"])
    
    # Metadata
    enabled: bool = True
    priority: int = 100  # Lower = higher priority
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "name": self.name,
            "description": self.description,
            "trigger_change_types": self.trigger_change_types,
            "trigger_risk_levels": self.trigger_risk_levels,
            "trigger_confidence_below": self.trigger_confidence_below,
            "required_approvers": self.required_approvers,
            "approver_roles": self.approver_roles,
            "timeout_hours": self.timeout_hours,
            "auto_approve_after_timeout": self.auto_approve_after_timeout,
            "escalation_after_hours": self.escalation_after_hours,
            "escalation_roles": self.escalation_roles,
            "enabled": self.enabled,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApprovalGate":
        data = data.copy()
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


@dataclass
class ApprovalRequest:
    """
    A request for human approval of a system change.
    
    Tracks the full lifecycle from creation to resolution.
    """
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    gate_id: str = ""
    
    # Change details
    change_type: str = ""
    change_summary: str = ""
    change_details: Dict[str, Any] = field(default_factory=dict)
    
    # Risk context
    risk_level: str = "low"
    risk_score: float = 0.0
    confidence_score: float = 1.0
    
    # Impact assessment
    affected_records: int = 0
    affected_components: List[str] = field(default_factory=list)
    rollback_possible: bool = True
    
    # Approval tracking
    status: ApprovalStatus = ApprovalStatus.PENDING
    approvals: List[Dict[str, Any]] = field(default_factory=list)  # {user, role, decision, timestamp, comment}
    rejections: List[Dict[str, Any]] = field(default_factory=list)
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    
    # Metadata
    requestor_id: str = "system"
    urgency: str = "normal"  # low, normal, high, critical
    tags: List[str] = field(default_factory=list)
    
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
    
    def approval_count(self) -> int:
        return len(self.approvals)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "gate_id": self.gate_id,
            "change_type": self.change_type,
            "change_summary": self.change_summary,
            "change_details": self.change_details,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "confidence_score": self.confidence_score,
            "affected_records": self.affected_records,
            "affected_components": self.affected_components,
            "rollback_possible": self.rollback_possible,
            "status": self.status.value,
            "approvals": self.approvals,
            "rejections": self.rejections,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "requestor_id": self.requestor_id,
            "urgency": self.urgency,
            "tags": self.tags,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApprovalRequest":
        data = data.copy()
        for dt_field in ["created_at", "updated_at", "expires_at", "resolved_at"]:
            if dt_field in data and isinstance(data[dt_field], str):
                data[dt_field] = datetime.fromisoformat(data[dt_field])
        if "status" in data and isinstance(data["status"], str):
            data["status"] = ApprovalStatus(data["status"])
        return cls(**data)


# =============================================================================
# RISK ASSESSMENT MODELS
# =============================================================================

class RiskLevel(Enum):
    """Risk level classification."""
    NEGLIGIBLE = "negligible"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskFactor:
    """
    A single risk factor contributing to overall risk assessment.
    """
    factor_id: str
    name: str
    category: str  # e.g., "data_quality", "model_drift", "compliance", "operational"
    
    # Scoring
    weight: float = 1.0
    score: float = 0.0  # 0.0 - 1.0
    weighted_score: float = 0.0
    
    # Details
    description: str = ""
    evidence: List[str] = field(default_factory=list)
    mitigation_actions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "name": self.name,
            "category": self.category,
            "weight": self.weight,
            "score": self.score,
            "weighted_score": self.weighted_score,
            "description": self.description,
            "evidence": self.evidence,
            "mitigation_actions": self.mitigation_actions,
        }


@dataclass
class RiskAssessment:
    """
    Comprehensive risk assessment for a proposed change.
    """
    assessment_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    change_type: str = ""
    change_id: str = ""
    
    # Risk scoring
    overall_risk_level: RiskLevel = RiskLevel.LOW
    overall_risk_score: float = 0.0  # 0.0 - 1.0
    confidence_in_assessment: float = 1.0
    
    # Risk breakdown
    risk_factors: List[RiskFactor] = field(default_factory=list)
    
    # Thresholds
    auto_approve_threshold: float = 0.3
    human_review_threshold: float = 0.6
    block_threshold: float = 0.9
    
    # Decision
    recommended_action: str = "auto_approve"  # auto_approve, human_review, block
    requires_approval: bool = False
    blocking_factors: List[str] = field(default_factory=list)
    
    # Metadata
    assessed_at: datetime = field(default_factory=datetime.utcnow)
    assessor: str = "risk_engine"
    notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "change_type": self.change_type,
            "change_id": self.change_id,
            "overall_risk_level": self.overall_risk_level.value,
            "overall_risk_score": self.overall_risk_score,
            "confidence_in_assessment": self.confidence_in_assessment,
            "risk_factors": [f.to_dict() for f in self.risk_factors],
            "auto_approve_threshold": self.auto_approve_threshold,
            "human_review_threshold": self.human_review_threshold,
            "block_threshold": self.block_threshold,
            "recommended_action": self.recommended_action,
            "requires_approval": self.requires_approval,
            "blocking_factors": self.blocking_factors,
            "assessed_at": self.assessed_at.isoformat(),
            "assessor": self.assessor,
            "notes": self.notes,
        }


# =============================================================================
# COMPLIANCE MODELS
# =============================================================================

@dataclass
class ComplianceRule:
    """
    A compliance rule that must be satisfied.
    """
    rule_id: str
    name: str
    category: str  # e.g., "data_privacy", "fairness", "transparency", "security"
    
    # Rule specification
    description: str = ""
    condition_type: str = "threshold"  # threshold, pattern, custom
    condition_params: Dict[str, Any] = field(default_factory=dict)
    
    # Severity
    severity: str = "warning"  # info, warning, error, critical
    blocking: bool = False  # If true, failure blocks the change
    
    # Applicability
    applies_to_change_types: List[str] = field(default_factory=list)
    enabled: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "condition_type": self.condition_type,
            "condition_params": self.condition_params,
            "severity": self.severity,
            "blocking": self.blocking,
            "applies_to_change_types": self.applies_to_change_types,
            "enabled": self.enabled,
        }


@dataclass
class ComplianceCheck:
    """
    Result of a compliance check against a rule.
    """
    check_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    rule_id: str = ""
    rule_name: str = ""
    
    # Result
    passed: bool = True
    severity: str = "info"
    blocking: bool = False
    
    # Details
    message: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    remediation_steps: List[str] = field(default_factory=list)
    
    # Context
    checked_at: datetime = field(default_factory=datetime.utcnow)
    change_type: str = ""
    change_id: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_id": self.check_id,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "passed": self.passed,
            "severity": self.severity,
            "blocking": self.blocking,
            "message": self.message,
            "evidence": self.evidence,
            "remediation_steps": self.remediation_steps,
            "checked_at": self.checked_at.isoformat(),
            "change_type": self.change_type,
            "change_id": self.change_id,
        }


# =============================================================================
# AUDIT MODELS
# =============================================================================

class AuditEventType(Enum):
    """Types of audit events."""
    # System events
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"
    CONFIG_CHANGE = "config_change"
    
    # Data events
    DATA_COLLECTION = "data_collection"
    DATA_PROCESSING = "data_processing"
    DATA_EXPORT = "data_export"
    
    # Model events
    MODEL_TRAINING = "model_training"
    MODEL_DEPLOYMENT = "model_deployment"
    MODEL_ROLLBACK = "model_rollback"
    
    # Taxonomy events
    TAXONOMY_UPDATE = "taxonomy_update"
    SKILL_ADDED = "skill_added"
    SKILL_MERGED = "skill_merged"
    SKILL_DEPRECATED = "skill_deprecated"
    
    # Scoring events
    SCORING_UPDATE = "scoring_update"
    SCORING_ROLLBACK = "scoring_rollback"
    
    # Approval events
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_ESCALATED = "approval_escalated"
    
    # Security events
    AUTH_SUCCESS = "auth_success"
    AUTH_FAILURE = "auth_failure"
    ACCESS_DENIED = "access_denied"
    EMERGENCY_OVERRIDE = "emergency_override"
    
    # Compliance events
    COMPLIANCE_CHECK = "compliance_check"
    COMPLIANCE_VIOLATION = "compliance_violation"
    
    # Evolution events
    EVOLUTION_CYCLE_START = "evolution_cycle_start"
    EVOLUTION_CYCLE_END = "evolution_cycle_end"
    EVOLUTION_STAGE_COMPLETE = "evolution_stage_complete"


@dataclass
class AuditEntry:
    """
    An immutable audit log entry.
    """
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: AuditEventType = AuditEventType.SYSTEM_START
    
    # Event details
    summary: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    
    # Actor
    actor_type: str = "system"  # system, user, service
    actor_id: str = ""
    actor_role: str = ""
    
    # Target
    target_type: str = ""  # e.g., "skill", "scoring_config", "model"
    target_id: str = ""
    
    # Context
    component: str = ""  # e.g., "taxonomy_engine", "scoring_adapter"
    session_id: str = ""
    correlation_id: str = ""  # Links related events
    
    # Outcome
    success: bool = True
    error_message: str = ""
    
    # Immutable timestamp
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Compliance metadata
    retention_days: int = 365
    sensitive_data: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "event_type": self.event_type.value,
            "summary": self.summary,
            "details": self.details,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "actor_role": self.actor_role,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "component": self.component,
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "success": self.success,
            "error_message": self.error_message,
            "timestamp": self.timestamp.isoformat(),
            "retention_days": self.retention_days,
            "sensitive_data": self.sensitive_data,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditEntry":
        data = data.copy()
        if "event_type" in data and isinstance(data["event_type"], str):
            data["event_type"] = AuditEventType(data["event_type"])
        if "timestamp" in data and isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)


# =============================================================================
# POLICY & VIOLATION MODELS
# =============================================================================

@dataclass
class GovernancePolicy:
    """
    A governance policy defining acceptable system behavior.
    """
    policy_id: str
    name: str
    category: str  # e.g., "data_governance", "model_governance", "operational"
    
    # Policy specification
    description: str = ""
    rules: List[str] = field(default_factory=list)  # List of rule_ids
    
    # Enforcement
    enforcement_level: str = "advisory"  # advisory, enforced, strict
    violation_action: str = "warn"  # warn, block, escalate
    
    # Metadata
    version: str = "1.0.0"
    effective_from: datetime = field(default_factory=datetime.utcnow)
    effective_until: Optional[datetime] = None
    owner: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "rules": self.rules,
            "enforcement_level": self.enforcement_level,
            "violation_action": self.violation_action,
            "version": self.version,
            "effective_from": self.effective_from.isoformat(),
            "effective_until": self.effective_until.isoformat() if self.effective_until else None,
            "owner": self.owner,
        }


@dataclass
class PolicyViolation:
    """
    A detected policy violation.
    """
    violation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    policy_id: str = ""
    policy_name: str = ""
    
    # Violation details
    severity: str = "warning"
    description: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    
    # Context
    change_type: str = ""
    change_id: str = ""
    component: str = ""
    
    # Resolution
    status: str = "open"  # open, acknowledged, resolved, waived
    resolution_notes: str = ""
    resolved_by: str = ""
    resolved_at: Optional[datetime] = None
    
    # Timestamps
    detected_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "violation_id": self.violation_id,
            "policy_id": self.policy_id,
            "policy_name": self.policy_name,
            "severity": self.severity,
            "description": self.description,
            "evidence": self.evidence,
            "change_type": self.change_type,
            "change_id": self.change_id,
            "component": self.component,
            "status": self.status,
            "resolution_notes": self.resolution_notes,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "detected_at": self.detected_at.isoformat(),
        }


# =============================================================================
# EMERGENCY OVERRIDE MODEL
# =============================================================================

@dataclass
class EmergencyOverride:
    """
    An emergency override action bypassing normal governance.
    
    Requires special authorization and creates a detailed audit trail.
    """
    override_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # Override details
    reason: str = ""
    justification: str = ""
    override_type: str = ""  # e.g., "skip_approval", "force_rollback", "disable_rule"
    
    # Scope
    affected_gates: List[str] = field(default_factory=list)
    affected_rules: List[str] = field(default_factory=list)
    affected_changes: List[str] = field(default_factory=list)
    
    # Authorization
    authorized_by: str = ""
    authorizer_role: str = ""
    secondary_authorization: Optional[str] = None
    
    # Time bounds
    effective_from: datetime = field(default_factory=datetime.utcnow)
    effective_until: datetime = field(default_factory=datetime.utcnow)
    
    # Status
    active: bool = True
    revoked: bool = False
    revoked_by: str = ""
    revoked_at: Optional[datetime] = None
    revocation_reason: str = ""
    
    # Audit
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def is_active(self) -> bool:
        """Check if override is currently active."""
        if self.revoked:
            return False
        now = datetime.utcnow()
        return self.effective_from <= now <= self.effective_until
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "override_id": self.override_id,
            "reason": self.reason,
            "justification": self.justification,
            "override_type": self.override_type,
            "affected_gates": self.affected_gates,
            "affected_rules": self.affected_rules,
            "affected_changes": self.affected_changes,
            "authorized_by": self.authorized_by,
            "authorizer_role": self.authorizer_role,
            "secondary_authorization": self.secondary_authorization,
            "effective_from": self.effective_from.isoformat(),
            "effective_until": self.effective_until.isoformat(),
            "active": self.active,
            "revoked": self.revoked,
            "revoked_by": self.revoked_by,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "revocation_reason": self.revocation_reason,
            "created_at": self.created_at.isoformat(),
        }


# =============================================================================
# CONFIGURATION MODEL
# =============================================================================

@dataclass  
class GovernanceConfig:
    """
    Configuration for the governance engine.
    """
    # Approval settings
    default_approval_timeout_hours: int = 24
    auto_approve_low_risk: bool = True
    auto_reject_blocked: bool = True
    
    # Risk thresholds
    risk_auto_approve_threshold: float = 0.3
    risk_human_review_threshold: float = 0.6
    risk_block_threshold: float = 0.9
    
    # Confidence thresholds
    confidence_auto_threshold: float = 0.8
    confidence_review_threshold: float = 0.5
    
    # Compliance settings
    compliance_strict_mode: bool = False
    compliance_blocking_enabled: bool = True
    
    # Audit settings
    audit_retention_days: int = 365
    audit_sensitive_data_masking: bool = True
    
    # Emergency settings
    emergency_override_enabled: bool = True
    emergency_dual_authorization: bool = True
    emergency_max_duration_hours: int = 4
    
    # Notification settings
    notify_on_approval_request: bool = True
    notify_on_escalation: bool = True
    notify_on_violation: bool = True
    notification_channels: List[str] = field(default_factory=lambda: ["email", "slack"])
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "default_approval_timeout_hours": self.default_approval_timeout_hours,
            "auto_approve_low_risk": self.auto_approve_low_risk,
            "auto_reject_blocked": self.auto_reject_blocked,
            "risk_auto_approve_threshold": self.risk_auto_approve_threshold,
            "risk_human_review_threshold": self.risk_human_review_threshold,
            "risk_block_threshold": self.risk_block_threshold,
            "confidence_auto_threshold": self.confidence_auto_threshold,
            "confidence_review_threshold": self.confidence_review_threshold,
            "compliance_strict_mode": self.compliance_strict_mode,
            "compliance_blocking_enabled": self.compliance_blocking_enabled,
            "audit_retention_days": self.audit_retention_days,
            "audit_sensitive_data_masking": self.audit_sensitive_data_masking,
            "emergency_override_enabled": self.emergency_override_enabled,
            "emergency_dual_authorization": self.emergency_dual_authorization,
            "emergency_max_duration_hours": self.emergency_max_duration_hours,
            "notify_on_approval_request": self.notify_on_approval_request,
            "notify_on_escalation": self.notify_on_escalation,
            "notify_on_violation": self.notify_on_violation,
            "notification_channels": self.notification_channels,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GovernanceConfig":
        return cls(**data)

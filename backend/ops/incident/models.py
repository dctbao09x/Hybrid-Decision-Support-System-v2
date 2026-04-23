# backend/ops/incident/models.py
"""
Incident Management Models
==========================

Enterprise-grade incident management data structures:
- Incident taxonomy (P0-P3)
- Alert classification
- RCA (Root Cause Analysis)
- Playbooks
- Postmortems
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class IncidentPriority(str, Enum):
    """Incident priority levels (severity)."""
    P0 = "P0"  # System Down / Total Outage
    P1 = "P1"  # Decision Corruption / Major Impact
    P2 = "P2"  # Degradation / Moderate Impact
    P3 = "P3"  # Minor Fault / Low Impact


class IncidentStatus(str, Enum):
    """Incident lifecycle status."""
    DETECTED = "detected"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    MITIGATING = "mitigating"
    RESOLVED = "resolved"
    CLOSED = "closed"
    POSTMORTEM = "postmortem"


class IncidentCategory(str, Enum):
    """Incident categories."""
    SYSTEM = "system"           # Infrastructure issues
    DATA = "data"               # Data quality/corruption
    MODEL = "model"             # ML model issues
    SECURITY = "security"       # Security incidents
    PERFORMANCE = "performance" # Performance degradation
    INTEGRATION = "integration" # External service issues
    COST = "cost"               # Budget/cost incidents
    COMPLIANCE = "compliance"   # Policy violations


class AlertChannel(str, Enum):
    """Alert notification channels."""
    LOG = "log"
    EMAIL = "email"
    SLACK = "slack"
    PAGERDUTY = "pagerduty"
    WEBHOOK = "webhook"
    SMS = "sms"


class EscalationLevel(str, Enum):
    """Escalation levels."""
    L1 = "L1"  # On-call engineer
    L2 = "L2"  # Senior engineer / Team lead
    L3 = "L3"  # Engineering manager / Architect
    L4 = "L4"  # VP / C-level


@dataclass
class IncidentTimeline:
    """Single timeline entry for an incident."""
    timestamp: str
    event_type: str
    description: str
    actor: str = "system"
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "description": self.description,
            "actor": self.actor,
            "metadata": self.metadata,
        }


@dataclass
class EscalationRule:
    """Escalation rule configuration."""
    level: EscalationLevel
    trigger_minutes: int           # Minutes before escalating
    notify_roles: List[str]
    channels: List[AlertChannel]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "trigger_minutes": self.trigger_minutes,
            "notify_roles": self.notify_roles,
            "channels": [c.value for c in self.channels],
        }


@dataclass
class Incident:
    """
    Main incident record.
    
    Tracks full lifecycle from detection to postmortem.
    """
    incident_id: str
    title: str
    description: str
    priority: IncidentPriority
    category: IncidentCategory
    status: IncidentStatus
    
    # Detection
    detected_at: str
    detected_by: str = "system"
    detection_source: str = ""
    
    # Impact
    impact_summary: str = ""
    affected_services: List[str] = field(default_factory=list)
    affected_users: int = 0
    financial_impact_usd: float = 0.0
    
    # Response
    acknowledged_at: Optional[str] = None
    acknowledged_by: Optional[str] = None
    assigned_to: Optional[str] = None
    escalation_level: EscalationLevel = EscalationLevel.L1
    
    # Resolution
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    resolution_summary: str = ""
    time_to_detect_minutes: float = 0.0
    time_to_acknowledge_minutes: float = 0.0
    time_to_resolve_minutes: float = 0.0
    
    # Timeline
    timeline: List[IncidentTimeline] = field(default_factory=list)
    
    # Metadata
    tags: List[str] = field(default_factory=list)
    related_incidents: List[str] = field(default_factory=list)
    playbook_id: Optional[str] = None
    rca_id: Optional[str] = None
    postmortem_id: Optional[str] = None
    
    def add_timeline_event(
        self,
        event_type: str,
        description: str,
        actor: str = "system",
    ) -> None:
        """Add event to timeline."""
        self.timeline.append(IncidentTimeline(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            description=description,
            actor=actor,
        ))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority.value,
            "category": self.category.value,
            "status": self.status.value,
            "detected_at": self.detected_at,
            "detected_by": self.detected_by,
            "detection_source": self.detection_source,
            "impact_summary": self.impact_summary,
            "affected_services": self.affected_services,
            "affected_users": self.affected_users,
            "financial_impact_usd": round(self.financial_impact_usd, 2),
            "acknowledged_at": self.acknowledged_at,
            "acknowledged_by": self.acknowledged_by,
            "assigned_to": self.assigned_to,
            "escalation_level": self.escalation_level.value,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
            "resolution_summary": self.resolution_summary,
            "time_to_detect_minutes": round(self.time_to_detect_minutes, 2),
            "time_to_acknowledge_minutes": round(self.time_to_acknowledge_minutes, 2),
            "time_to_resolve_minutes": round(self.time_to_resolve_minutes, 2),
            "timeline": [t.to_dict() for t in self.timeline],
            "tags": self.tags,
            "related_incidents": self.related_incidents,
            "playbook_id": self.playbook_id,
            "rca_id": self.rca_id,
            "postmortem_id": self.postmortem_id,
        }


# ═══════════════════════════════════════════════════════════════════════
# RCA (Root Cause Analysis) Models
# ═══════════════════════════════════════════════════════════════════════

class RCAStatus(str, Enum):
    """RCA workflow status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    APPROVED = "approved"
    PUBLISHED = "published"


@dataclass
class FiveWhyEntry:
    """Single 'Why' in 5-Why analysis."""
    level: int               # 1-5
    question: str
    answer: str
    evidence: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "question": self.question,
            "answer": self.answer,
            "evidence": self.evidence,
        }


@dataclass
class FaultChainNode:
    """Node in fault chain tree."""
    node_id: str
    fault_type: str
    description: str
    timestamp: Optional[str] = None
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    is_root: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "fault_type": self.fault_type,
            "description": self.description,
            "timestamp": self.timestamp,
            "parent_id": self.parent_id,
            "children_ids": self.children_ids,
            "evidence": self.evidence,
            "is_root": self.is_root,
        }


@dataclass
class RootCauseAnalysis:
    """
    Root Cause Analysis document.
    
    Includes:
    - 5-Why analysis
    - Fault chain tree
    - Evidence mapping
    - Contributing factors
    - Recommendations
    """
    rca_id: str
    incident_id: str
    title: str
    status: RCAStatus
    
    # Analysis
    summary: str = ""
    root_cause: str = ""
    contributing_factors: List[str] = field(default_factory=list)
    
    # 5-Why
    five_whys: List[FiveWhyEntry] = field(default_factory=list)
    
    # Fault chain
    fault_chain: List[FaultChainNode] = field(default_factory=list)
    
    # Evidence
    evidence: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    metrics_snapshots: List[str] = field(default_factory=list)
    
    # Impact
    impact_assessment: str = ""
    blast_radius: List[str] = field(default_factory=list)
    
    # Recommendations
    immediate_actions: List[str] = field(default_factory=list)
    long_term_recommendations: List[str] = field(default_factory=list)
    
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = ""
    reviewed_by: Optional[str] = None
    approved_by: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "rca_id": self.rca_id,
            "incident_id": self.incident_id,
            "title": self.title,
            "status": self.status.value,
            "summary": self.summary,
            "root_cause": self.root_cause,
            "contributing_factors": self.contributing_factors,
            "five_whys": [w.to_dict() for w in self.five_whys],
            "fault_chain": [n.to_dict() for n in self.fault_chain],
            "evidence": self.evidence,
            "logs": self.logs,
            "metrics_snapshots": self.metrics_snapshots,
            "impact_assessment": self.impact_assessment,
            "blast_radius": self.blast_radius,
            "immediate_actions": self.immediate_actions,
            "long_term_recommendations": self.long_term_recommendations,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "reviewed_by": self.reviewed_by,
            "approved_by": self.approved_by,
        }


# ═══════════════════════════════════════════════════════════════════════
# Playbook Models
# ═══════════════════════════════════════════════════════════════════════

class PlaybookStepType(str, Enum):
    """Types of playbook steps."""
    COMMAND = "command"         # Run a command
    CHECK = "check"             # Verify condition
    DECISION = "decision"       # Branch based on condition
    NOTIFY = "notify"           # Send notification
    MANUAL = "manual"           # Requires manual action
    ROLLBACK = "rollback"       # Trigger rollback
    ESCALATE = "escalate"       # Escalate to next level


@dataclass
class PlaybookStep:
    """Single step in a playbook."""
    step_id: str
    step_number: int
    step_type: PlaybookStepType
    title: str
    description: str
    
    # Execution
    command: Optional[str] = None
    expected_output: Optional[str] = None
    timeout_seconds: int = 300
    
    # Decision branching
    condition: Optional[str] = None
    on_success_step: Optional[str] = None
    on_failure_step: Optional[str] = None
    
    # Manual override
    requires_approval: bool = False
    approval_roles: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_number": self.step_number,
            "step_type": self.step_type.value,
            "title": self.title,
            "description": self.description,
            "command": self.command,
            "expected_output": self.expected_output,
            "timeout_seconds": self.timeout_seconds,
            "condition": self.condition,
            "on_success_step": self.on_success_step,
            "on_failure_step": self.on_failure_step,
            "requires_approval": self.requires_approval,
            "approval_roles": self.approval_roles,
        }


@dataclass
class Playbook:
    """
    Incident response playbook.
    
    Defines step-by-step response procedures.
    """
    playbook_id: str
    name: str
    description: str
    version: str
    
    # Triggers
    trigger_priority: List[IncidentPriority] = field(default_factory=list)
    trigger_category: List[IncidentCategory] = field(default_factory=list)
    trigger_keywords: List[str] = field(default_factory=list)
    
    # Steps
    steps: List[PlaybookStep] = field(default_factory=list)
    
    # Configuration
    auto_execute: bool = True
    max_auto_steps: int = 5        # Auto-execute only first N steps
    requires_approval: bool = False
    
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = ""
    enabled: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "playbook_id": self.playbook_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "trigger_priority": [p.value for p in self.trigger_priority],
            "trigger_category": [c.value for c in self.trigger_category],
            "trigger_keywords": self.trigger_keywords,
            "steps": [s.to_dict() for s in self.steps],
            "auto_execute": self.auto_execute,
            "max_auto_steps": self.max_auto_steps,
            "requires_approval": self.requires_approval,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "enabled": self.enabled,
        }


# ═══════════════════════════════════════════════════════════════════════
# Postmortem Models
# ═══════════════════════════════════════════════════════════════════════

class PostmortemStatus(str, Enum):
    """Postmortem workflow status."""
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    PUBLISHED = "published"


@dataclass
class ActionItem:
    """Post-incident action item."""
    item_id: str
    title: str
    description: str
    priority: str                  # P0-P3
    owner: str
    due_date: str
    status: str = "open"           # open, in_progress, completed
    completed_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "owner": self.owner,
            "due_date": self.due_date,
            "status": self.status,
            "completed_at": self.completed_at,
        }


@dataclass
class Postmortem:
    """
    Incident postmortem document.
    
    Blameless post-incident review template.
    """
    postmortem_id: str
    incident_id: str
    title: str
    status: PostmortemStatus
    
    # Summary
    executive_summary: str = ""
    incident_summary: str = ""
    
    # Timeline
    detection_time: str = ""
    acknowledgement_time: str = ""
    mitigation_time: str = ""
    resolution_time: str = ""
    total_duration_minutes: float = 0.0
    
    # Impact
    impact_description: str = ""
    customer_impact: str = ""
    financial_impact_usd: float = 0.0
    sla_breached: bool = False
    
    # Root cause
    root_cause_summary: str = ""
    rca_id: Optional[str] = None
    
    # What went well
    what_went_well: List[str] = field(default_factory=list)
    
    # What went wrong
    what_went_wrong: List[str] = field(default_factory=list)
    
    # Lessons learned
    lessons_learned: List[str] = field(default_factory=list)
    
    # Action items
    action_items: List[ActionItem] = field(default_factory=list)
    
    # Learning registry
    learning_tags: List[str] = field(default_factory=list)
    similar_incidents: List[str] = field(default_factory=list)
    
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = ""
    reviewed_by: List[str] = field(default_factory=list)
    approved_by: Optional[str] = None
    published_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "postmortem_id": self.postmortem_id,
            "incident_id": self.incident_id,
            "title": self.title,
            "status": self.status.value,
            "executive_summary": self.executive_summary,
            "incident_summary": self.incident_summary,
            "detection_time": self.detection_time,
            "acknowledgement_time": self.acknowledgement_time,
            "mitigation_time": self.mitigation_time,
            "resolution_time": self.resolution_time,
            "total_duration_minutes": round(self.total_duration_minutes, 2),
            "impact_description": self.impact_description,
            "customer_impact": self.customer_impact,
            "financial_impact_usd": round(self.financial_impact_usd, 2),
            "sla_breached": self.sla_breached,
            "root_cause_summary": self.root_cause_summary,
            "rca_id": self.rca_id,
            "what_went_well": self.what_went_well,
            "what_went_wrong": self.what_went_wrong,
            "lessons_learned": self.lessons_learned,
            "action_items": [a.to_dict() for a in self.action_items],
            "learning_tags": self.learning_tags,
            "similar_incidents": self.similar_incidents,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "reviewed_by": self.reviewed_by,
            "approved_by": self.approved_by,
            "published_at": self.published_at,
        }


# ═══════════════════════════════════════════════════════════════════════
# Default Escalation Policies
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_ESCALATION_POLICIES = {
    IncidentPriority.P0: [
        EscalationRule(EscalationLevel.L1, 0, ["on_call"], [AlertChannel.PAGERDUTY, AlertChannel.SLACK]),
        EscalationRule(EscalationLevel.L2, 15, ["team_lead"], [AlertChannel.PAGERDUTY, AlertChannel.SLACK]),
        EscalationRule(EscalationLevel.L3, 30, ["engineering_manager"], [AlertChannel.PAGERDUTY, AlertChannel.EMAIL]),
        EscalationRule(EscalationLevel.L4, 60, ["vp_engineering"], [AlertChannel.PAGERDUTY, AlertChannel.EMAIL, AlertChannel.SMS]),
    ],
    IncidentPriority.P1: [
        EscalationRule(EscalationLevel.L1, 0, ["on_call"], [AlertChannel.PAGERDUTY, AlertChannel.SLACK]),
        EscalationRule(EscalationLevel.L2, 30, ["team_lead"], [AlertChannel.SLACK, AlertChannel.EMAIL]),
        EscalationRule(EscalationLevel.L3, 60, ["engineering_manager"], [AlertChannel.EMAIL]),
    ],
    IncidentPriority.P2: [
        EscalationRule(EscalationLevel.L1, 0, ["on_call"], [AlertChannel.SLACK]),
        EscalationRule(EscalationLevel.L2, 60, ["team_lead"], [AlertChannel.SLACK, AlertChannel.EMAIL]),
    ],
    IncidentPriority.P3: [
        EscalationRule(EscalationLevel.L1, 0, ["team"], [AlertChannel.SLACK]),
    ],
}

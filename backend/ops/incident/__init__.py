# backend/ops/incident/__init__.py
"""
Incident Management Package
===========================

Enterprise-grade incident management for AI operations:
- Incident taxonomy (P0-P3)
- Alert pipeline with escalation
- RCA framework (5-Why, Fault Chain)
- Playbook system
- Postmortem workflow
"""

from backend.ops.incident.models import (
    ActionItem,
    AlertChannel,
    EscalationLevel,
    EscalationRule,
    FaultChainNode,
    FiveWhyEntry,
    Incident,
    IncidentCategory,
    IncidentPriority,
    IncidentStatus,
    IncidentTimeline,
    Playbook,
    PlaybookStep,
    PlaybookStepType,
    Postmortem,
    PostmortemStatus,
    RCAStatus,
    RootCauseAnalysis,
)
from backend.ops.incident.manager import IncidentManager, get_incident_manager

__all__ = [
    # Models
    "ActionItem",
    "AlertChannel",
    "EscalationLevel",
    "EscalationRule",
    "FaultChainNode",
    "FiveWhyEntry",
    "Incident",
    "IncidentCategory",
    "IncidentPriority",
    "IncidentStatus",
    "IncidentTimeline",
    "Playbook",
    "PlaybookStep",
    "PlaybookStepType",
    "Postmortem",
    "PostmortemStatus",
    "RCAStatus",
    "RootCauseAnalysis",
    # Manager
    "IncidentManager",
    "get_incident_manager",
]

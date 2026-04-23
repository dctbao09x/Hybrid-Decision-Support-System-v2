# backend/ops/governance/__init__.py
"""
Governance Platform Module
==========================

Provides:
- OPS Data Pipeline
- Metrics Aggregation
- Risk Management
- Compliance Reporting
"""

from backend.ops.governance.models import (
    OpsRecord,
    CostRecord,
    DriftRecord,
    InferenceStatus,
    SLAMetrics,
    IncidentReport as IncidentReportModel,
)
from backend.ops.governance.pipeline import OpsPipeline, get_ops_pipeline
from backend.ops.governance.aggregator import OpsAggregator, get_ops_aggregator
from backend.ops.governance.risk import (
    RiskManager,
    RiskWeights,
    RiskThresholds,
    RiskMetrics,
    RiskScore,
    RiskLevel,
    MitigationAction,
    MitigationEvent,
    MitigationStatus,
    get_risk_manager,
)
from backend.ops.governance.reporting import (
    ReportGenerator,
    WeeklySLAReport,
    MonthlyRiskReport,
    IncidentReport,
    ReportMetadata,
    get_report_generator,
)
from backend.ops.governance.coordinator import (
    GovernanceCoordinator,
    GovernanceDecision,
    GovernanceAction,
    AuthorityLevel,
    EscalationPath,
    Override,
    get_governance_coordinator,
)
from backend.ops.governance.safety_policy import (
    SafetyPolicy,
    SafetyPolicyEngine,
    PolicyViolation,
    PolicyAction,
    PolicyCheckResult,
)
from backend.ops.governance.approval_workflow import (
    ApprovalWorkflow,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalDecision,
)

__all__ = [
    # Models
    "OpsRecord",
    "CostRecord",
    "DriftRecord",
    "InferenceStatus",
    "SLAMetrics",
    "IncidentReportModel",
    # Pipeline
    "OpsPipeline",
    "get_ops_pipeline",
    # Aggregator
    "OpsAggregator",
    "get_ops_aggregator",
    # Risk
    "RiskManager",
    "RiskWeights",
    "RiskThresholds",
    "RiskMetrics",
    "RiskScore",
    "RiskLevel",
    "MitigationAction",
    "MitigationEvent",
    "MitigationStatus",
    "get_risk_manager",
    # Reporting
    "ReportGenerator",
    "WeeklySLAReport",
    "MonthlyRiskReport",
    "IncidentReport",
    "ReportMetadata",
    "get_report_generator",
    # Integrated Governance Coordinator
    "GovernanceCoordinator",
    "GovernanceDecision",
    "GovernanceAction",
    "AuthorityLevel",
    "EscalationPath",
    "Override",
    "get_governance_coordinator",
    # Safety Policy Engine
    "SafetyPolicy",
    "SafetyPolicyEngine",
    "PolicyViolation",
    "PolicyAction",
    "PolicyCheckResult",
    # Approval Workflow
    "ApprovalWorkflow",
    "ApprovalRequest",
    "ApprovalStatus",
    "ApprovalDecision",
]

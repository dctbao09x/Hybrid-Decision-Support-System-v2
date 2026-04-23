# -*- coding: utf-8 -*-
"""
Governance & Risk Control - Engine
Enterprise-grade governance for autonomous system operations
"""

import hashlib
import json
import logging
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .models import (
    ApprovalGate,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalDecision,
    RiskLevel,
    RiskAssessment,
    RiskFactor,
    ComplianceRule,
    ComplianceCheck,
    AuditEntry,
    AuditEventType,
    GovernancePolicy,
    PolicyViolation,
    EmergencyOverride,
    GovernanceConfig,
)

logger = logging.getLogger(__name__)


# =============================================================================
# APPROVAL WORKFLOW
# =============================================================================

class ApprovalWorkflow:
    """
    Manages the human-in-the-loop approval workflow.
    
    Features:
    - Multi-level approval gates
    - Timeout and escalation handling
    - Auto-approval for low-risk changes
    - Comprehensive audit trail
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path("storage/market/governance.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        
        # In-memory caches
        self._gates: Dict[str, ApprovalGate] = {}
        self._pending_requests: Dict[str, ApprovalRequest] = {}
        
        # Callbacks
        self._on_approval_requested: List[Callable] = []
        self._on_approval_resolved: List[Callable] = []
        self._on_escalation: List[Callable] = []
        
        self._init_db()
        self._load_gates()
        self._init_default_gates()
    
    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS approval_gates (
                    gate_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    config TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                
                CREATE TABLE IF NOT EXISTS approval_requests (
                    request_id TEXT PRIMARY KEY,
                    gate_id TEXT,
                    status TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    FOREIGN KEY (gate_id) REFERENCES approval_gates(gate_id)
                );
                
                CREATE INDEX IF NOT EXISTS idx_requests_status ON approval_requests(status);
                CREATE INDEX IF NOT EXISTS idx_requests_gate ON approval_requests(gate_id);
            """)
    
    def _load_gates(self):
        """Load gates from database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT gate_id, name, config, enabled FROM approval_gates WHERE enabled = 1"
            )
            for row in cursor:
                gate_data = json.loads(row[2])
                gate_data["gate_id"] = row[0]
                gate_data["name"] = row[1]
                gate_data["enabled"] = bool(row[3])
                self._gates[row[0]] = ApprovalGate.from_dict(gate_data)
    
    def _init_default_gates(self):
        """Initialize default approval gates."""
        default_gates = [
            ApprovalGate(
                gate_id="taxonomy_major_change",
                name="Taxonomy Major Change",
                description="Requires approval for major taxonomy changes (merges, deprecations)",
                trigger_change_types=["taxonomy_merge", "skill_deprecated", "taxonomy_restructure"],
                trigger_risk_levels=["high", "critical"],
                required_approvers=2,
                timeout_hours=48,
            ),
            ApprovalGate(
                gate_id="scoring_update",
                name="Scoring Algorithm Update",
                description="Requires approval for scoring configuration changes",
                trigger_change_types=["scoring_update", "scoring_weights_change"],
                trigger_confidence_below=0.7,
                required_approvers=1,
                timeout_hours=24,
            ),
            ApprovalGate(
                gate_id="model_deployment",
                name="Model Deployment",
                description="Requires approval for model deployments",
                trigger_change_types=["model_deployment", "model_update"],
                trigger_risk_levels=["medium", "high", "critical"],
                required_approvers=2,
                approver_roles=["ml_engineer", "data_scientist", "admin"],
                timeout_hours=24,
            ),
            ApprovalGate(
                gate_id="emergency_changes",
                name="Emergency Changes",
                description="Fast-track gate for emergency changes",
                trigger_change_types=["emergency_rollback", "emergency_fix"],
                required_approvers=1,
                timeout_hours=1,
                auto_approve_after_timeout=False,
            ),
        ]
        
        for gate in default_gates:
            if gate.gate_id not in self._gates:
                self.register_gate(gate)
    
    def register_gate(self, gate: ApprovalGate):
        """Register an approval gate."""
        with self._lock:
            self._gates[gate.gate_id] = gate
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO approval_gates 
                       (gate_id, name, config, enabled, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (gate.gate_id, gate.name, json.dumps(gate.to_dict()),
                     1 if gate.enabled else 0, gate.created_at.isoformat())
                )
    
    def get_applicable_gates(
        self,
        change_type: str,
        risk_level: str = "low",
        confidence: float = 1.0
    ) -> List[ApprovalGate]:
        """Get gates that apply to a given change."""
        applicable = []
        
        for gate in self._gates.values():
            if not gate.enabled:
                continue
            
            # Check change type trigger
            if change_type in gate.trigger_change_types:
                applicable.append(gate)
                continue
            
            # Check risk level trigger
            if risk_level in gate.trigger_risk_levels:
                applicable.append(gate)
                continue
            
            # Check confidence threshold trigger
            if gate.trigger_confidence_below > 0 and confidence < gate.trigger_confidence_below:
                applicable.append(gate)
                continue
        
        # Sort by priority
        applicable.sort(key=lambda g: g.priority)
        return applicable
    
    def create_request(
        self,
        gate_id: str,
        change_type: str,
        change_summary: str,
        change_details: Dict[str, Any],
        risk_level: str = "low",
        risk_score: float = 0.0,
        confidence_score: float = 1.0,
        affected_records: int = 0,
        affected_components: List[str] = None,
        requestor_id: str = "system",
        urgency: str = "normal",
    ) -> ApprovalRequest:
        """Create a new approval request."""
        gate = self._gates.get(gate_id)
        if not gate:
            raise ValueError(f"Unknown gate: {gate_id}")
        
        request = ApprovalRequest(
            gate_id=gate_id,
            change_type=change_type,
            change_summary=change_summary,
            change_details=change_details,
            risk_level=risk_level,
            risk_score=risk_score,
            confidence_score=confidence_score,
            affected_records=affected_records,
            affected_components=affected_components or [],
            requestor_id=requestor_id,
            urgency=urgency,
            expires_at=datetime.utcnow() + timedelta(hours=gate.timeout_hours),
        )
        
        with self._lock:
            self._pending_requests[request.request_id] = request
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT INTO approval_requests
                       (request_id, gate_id, status, data, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (request.request_id, gate_id, request.status.value,
                     json.dumps(request.to_dict()), request.created_at.isoformat())
                )
        
        # Trigger callbacks
        for callback in self._on_approval_requested:
            try:
                callback(request)
            except Exception as e:
                logger.error(f"Approval request callback error: {e}")
        
        logger.info(f"Created approval request: {request.request_id} for gate {gate_id}")
        return request
    
    def submit_decision(
        self,
        request_id: str,
        decision: ApprovalDecision,
        user_id: str,
        user_role: str,
        comment: str = ""
    ) -> ApprovalRequest:
        """Submit an approval decision."""
        with self._lock:
            request = self._pending_requests.get(request_id)
            if not request:
                # Try loading from DB
                request = self._load_request(request_id)
            
            if not request:
                raise ValueError(f"Unknown request: {request_id}")
            
            if request.status not in [ApprovalStatus.PENDING, ApprovalStatus.ESCALATED]:
                raise ValueError(f"Request {request_id} is not pending")
            
            gate = self._gates.get(request.gate_id)
            decision_record = {
                "user_id": user_id,
                "user_role": user_role,
                "decision": decision.value,
                "comment": comment,
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            if decision == ApprovalDecision.APPROVE:
                request.approvals.append(decision_record)
                
                # Check if enough approvals
                if len(request.approvals) >= (gate.required_approvers if gate else 1):
                    request.status = ApprovalStatus.APPROVED
                    request.resolved_at = datetime.utcnow()
                    
            elif decision == ApprovalDecision.REJECT:
                request.rejections.append(decision_record)
                request.status = ApprovalStatus.REJECTED
                request.resolved_at = datetime.utcnow()
                
            elif decision == ApprovalDecision.ESCALATE:
                request.status = ApprovalStatus.ESCALATED
                for callback in self._on_escalation:
                    try:
                        callback(request)
                    except Exception as e:
                        logger.error(f"Escalation callback error: {e}")
            
            request.updated_at = datetime.utcnow()
            self._save_request(request)
            
            if request.status in [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED]:
                self._pending_requests.pop(request_id, None)
                for callback in self._on_approval_resolved:
                    try:
                        callback(request)
                    except Exception as e:
                        logger.error(f"Approval resolved callback error: {e}")
            
            return request
    
    def check_expired_requests(self) -> List[ApprovalRequest]:
        """Check and handle expired requests."""
        expired = []
        with self._lock:
            for request_id, request in list(self._pending_requests.items()):
                if request.is_expired():
                    gate = self._gates.get(request.gate_id)
                    
                    if gate and gate.auto_approve_after_timeout:
                        request.status = ApprovalStatus.AUTO_APPROVED
                    else:
                        request.status = ApprovalStatus.EXPIRED
                    
                    request.resolved_at = datetime.utcnow()
                    request.updated_at = datetime.utcnow()
                    self._save_request(request)
                    self._pending_requests.pop(request_id)
                    expired.append(request)
                    
                    logger.warning(f"Request {request_id} expired with status {request.status}")
        
        return expired
    
    def _load_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """Load request from database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT data FROM approval_requests WHERE request_id = ?",
                (request_id,)
            )
            row = cursor.fetchone()
            if row:
                return ApprovalRequest.from_dict(json.loads(row[0]))
        return None
    
    def _save_request(self, request: ApprovalRequest):
        """Save request to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE approval_requests 
                   SET status = ?, data = ?, resolved_at = ?
                   WHERE request_id = ?""",
                (request.status.value, json.dumps(request.to_dict()),
                 request.resolved_at.isoformat() if request.resolved_at else None,
                 request.request_id)
            )
    
    def get_pending_requests(self, gate_id: Optional[str] = None) -> List[ApprovalRequest]:
        """Get all pending requests."""
        requests = list(self._pending_requests.values())
        if gate_id:
            requests = [r for r in requests if r.gate_id == gate_id]
        return requests
    
    def on_approval_requested(self, callback: Callable):
        """Register callback for new approval requests."""
        self._on_approval_requested.append(callback)
    
    def on_approval_resolved(self, callback: Callable):
        """Register callback for resolved approvals."""
        self._on_approval_resolved.append(callback)
    
    def on_escalation(self, callback: Callable):
        """Register callback for escalations."""
        self._on_escalation.append(callback)


# =============================================================================
# RISK ASSESSOR
# =============================================================================

class RiskAssessor:
    """
    Assesses risk for proposed changes.
    
    Uses multiple risk factors to compute overall risk score and level.
    """
    
    def __init__(self, config: Optional[GovernanceConfig] = None):
        self.config = config or GovernanceConfig()
        
        # Risk factor weights by category
        self._category_weights = {
            "data_quality": 1.2,
            "model_drift": 1.5,
            "compliance": 2.0,
            "operational": 1.0,
            "security": 2.0,
            "business_impact": 1.3,
        }
    
    def assess(
        self,
        change_type: str,
        change_id: str,
        context: Dict[str, Any]
    ) -> RiskAssessment:
        """
        Perform comprehensive risk assessment.
        
        Args:
            change_type: Type of change (e.g., taxonomy_merge, scoring_update)
            change_id: Unique identifier for the change
            context: Additional context including metrics and affected entities
        
        Returns:
            RiskAssessment with overall score, factors, and recommendation
        """
        factors = []
        
        # Assess data quality risk
        factors.append(self._assess_data_quality(context))
        
        # Assess model drift risk
        factors.append(self._assess_model_drift(context))
        
        # Assess compliance risk
        factors.append(self._assess_compliance(change_type, context))
        
        # Assess operational risk
        factors.append(self._assess_operational(change_type, context))
        
        # Assess business impact
        factors.append(self._assess_business_impact(context))
        
        # Calculate overall score
        total_weight = sum(f.weight for f in factors)
        overall_score = sum(f.weighted_score for f in factors) / total_weight if total_weight > 0 else 0.0
        
        # Determine risk level
        risk_level = self._score_to_level(overall_score)
        
        # Determine recommended action
        if overall_score < self.config.risk_auto_approve_threshold:
            recommended_action = "auto_approve"
            requires_approval = False
        elif overall_score < self.config.risk_human_review_threshold:
            recommended_action = "human_review"
            requires_approval = True
        elif overall_score < self.config.risk_block_threshold:
            recommended_action = "human_review"
            requires_approval = True
        else:
            recommended_action = "block"
            requires_approval = True
        
        # Identify blocking factors
        blocking_factors = [
            f.name for f in factors 
            if f.score >= 0.9 and f.category in ["compliance", "security"]
        ]
        
        assessment = RiskAssessment(
            change_type=change_type,
            change_id=change_id,
            overall_risk_level=risk_level,
            overall_risk_score=overall_score,
            risk_factors=factors,
            auto_approve_threshold=self.config.risk_auto_approve_threshold,
            human_review_threshold=self.config.risk_human_review_threshold,
            block_threshold=self.config.risk_block_threshold,
            recommended_action=recommended_action,
            requires_approval=requires_approval,
            blocking_factors=blocking_factors,
        )
        
        logger.info(
            f"Risk assessment for {change_type}/{change_id}: "
            f"score={overall_score:.3f}, level={risk_level.value}, "
            f"action={recommended_action}"
        )
        
        return assessment
    
    def _assess_data_quality(self, context: Dict[str, Any]) -> RiskFactor:
        """Assess data quality risk factor."""
        score = 0.0
        evidence = []
        
        # Check data completeness
        completeness = context.get("data_completeness", 1.0)
        if completeness < 0.9:
            score += 0.3 * (1 - completeness)
            evidence.append(f"Data completeness: {completeness:.1%}")
        
        # Check data freshness
        data_age_days = context.get("data_age_days", 0)
        if data_age_days > 7:
            score += min(0.3, data_age_days / 30 * 0.3)
            evidence.append(f"Data age: {data_age_days} days")
        
        # Check sample size
        sample_size = context.get("sample_size", 1000)
        if sample_size < 100:
            score += 0.4
            evidence.append(f"Small sample size: {sample_size}")
        elif sample_size < 500:
            score += 0.2
            evidence.append(f"Limited sample size: {sample_size}")
        
        weight = self._category_weights.get("data_quality", 1.0)
        
        return RiskFactor(
            factor_id="data_quality",
            name="Data Quality Risk",
            category="data_quality",
            weight=weight,
            score=min(1.0, score),
            weighted_score=min(1.0, score) * weight,
            description="Risk from data quality issues",
            evidence=evidence,
            mitigation_actions=["Improve data collection", "Wait for more data"],
        )
    
    def _assess_model_drift(self, context: Dict[str, Any]) -> RiskFactor:
        """Assess model/data drift risk factor."""
        score = 0.0
        evidence = []
        
        # Check distribution drift
        drift_score = context.get("drift_score", 0.0)
        if drift_score > 0.5:
            score += drift_score * 0.6
            evidence.append(f"Distribution drift: {drift_score:.2f}")
        
        # Check performance degradation
        perf_delta = context.get("performance_delta", 0.0)
        if perf_delta < -0.05:
            score += abs(perf_delta) * 2
            evidence.append(f"Performance drop: {perf_delta:.1%}")
        
        # Check prediction stability
        stability = context.get("prediction_stability", 1.0)
        if stability < 0.8:
            score += (1 - stability) * 0.5
            evidence.append(f"Prediction stability: {stability:.1%}")
        
        weight = self._category_weights.get("model_drift", 1.0)
        
        return RiskFactor(
            factor_id="model_drift",
            name="Model Drift Risk",
            category="model_drift",
            weight=weight,
            score=min(1.0, score),
            weighted_score=min(1.0, score) * weight,
            description="Risk from model or data drift",
            evidence=evidence,
            mitigation_actions=["Monitor drift metrics", "Trigger retraining"],
        )
    
    def _assess_compliance(self, change_type: str, context: Dict[str, Any]) -> RiskFactor:
        """Assess compliance risk factor."""
        score = 0.0
        evidence = []
        
        # Check for compliance-sensitive changes
        sensitive_types = ["scoring_update", "user_data_change", "model_deployment"]
        if change_type in sensitive_types:
            score += 0.2
            evidence.append(f"Compliance-sensitive change type: {change_type}")
        
        # Check affected user count
        affected_users = context.get("affected_users", 0)
        if affected_users > 1000:
            score += min(0.3, affected_users / 10000 * 0.3)
            evidence.append(f"Affects {affected_users} users")
        
        # Check for PII involvement
        involves_pii = context.get("involves_pii", False)
        if involves_pii:
            score += 0.4
            evidence.append("Involves PII data")
        
        # Check audit requirements
        requires_audit = context.get("requires_audit", False)
        if requires_audit:
            score += 0.1
            evidence.append("Requires audit trail")
        
        weight = self._category_weights.get("compliance", 1.0)
        
        return RiskFactor(
            factor_id="compliance",
            name="Compliance Risk",
            category="compliance",
            weight=weight,
            score=min(1.0, score),
            weighted_score=min(1.0, score) * weight,
            description="Risk from compliance and regulatory requirements",
            evidence=evidence,
            mitigation_actions=["Document changes", "Get compliance review"],
        )
    
    def _assess_operational(self, change_type: str, context: Dict[str, Any]) -> RiskFactor:
        """Assess operational risk factor."""
        score = 0.0
        evidence = []
        
        # Check rollback capability
        rollback_possible = context.get("rollback_possible", True)
        if not rollback_possible:
            score += 0.4
            evidence.append("Rollback not possible")
        
        # Check affected components
        affected_components = context.get("affected_components", [])
        if len(affected_components) > 3:
            score += min(0.3, len(affected_components) / 10 * 0.3)
            evidence.append(f"Affects {len(affected_components)} components")
        
        # Check deployment complexity
        complexity = context.get("deployment_complexity", "low")
        if complexity == "high":
            score += 0.3
            evidence.append("High deployment complexity")
        elif complexity == "medium":
            score += 0.15
            evidence.append("Medium deployment complexity")
        
        # Check downtime requirements
        requires_downtime = context.get("requires_downtime", False)
        if requires_downtime:
            score += 0.2
            evidence.append("Requires system downtime")
        
        weight = self._category_weights.get("operational", 1.0)
        
        return RiskFactor(
            factor_id="operational",
            name="Operational Risk",
            category="operational",
            weight=weight,
            score=min(1.0, score),
            weighted_score=min(1.0, score) * weight,
            description="Risk from operational impact",
            evidence=evidence,
            mitigation_actions=["Prepare rollback plan", "Test in staging"],
        )
    
    def _assess_business_impact(self, context: Dict[str, Any]) -> RiskFactor:
        """Assess business impact risk factor."""
        score = 0.0
        evidence = []
        
        # Check revenue impact
        revenue_impact = context.get("revenue_impact", 0)
        if revenue_impact > 0:
            score += min(0.4, revenue_impact / 100000 * 0.4)
            evidence.append(f"Potential revenue impact: ${revenue_impact:,.0f}")
        
        # Check user experience impact
        ux_impact = context.get("ux_impact", "none")
        if ux_impact == "high":
            score += 0.3
            evidence.append("High user experience impact")
        elif ux_impact == "medium":
            score += 0.15
            evidence.append("Medium user experience impact")
        
        # Check SLA implications
        affects_sla = context.get("affects_sla", False)
        if affects_sla:
            score += 0.3
            evidence.append("May affect SLA")
        
        weight = self._category_weights.get("business_impact", 1.0)
        
        return RiskFactor(
            factor_id="business_impact",
            name="Business Impact Risk",
            category="business_impact",
            weight=weight,
            score=min(1.0, score),
            weighted_score=min(1.0, score) * weight,
            description="Risk from business impact",
            evidence=evidence,
            mitigation_actions=["Communicate with stakeholders", "Plan gradual rollout"],
        )
    
    def _score_to_level(self, score: float) -> RiskLevel:
        """Convert numeric score to risk level."""
        if score < 0.2:
            return RiskLevel.NEGLIGIBLE
        elif score < 0.4:
            return RiskLevel.LOW
        elif score < 0.6:
            return RiskLevel.MEDIUM
        elif score < 0.8:
            return RiskLevel.HIGH
        else:
            return RiskLevel.CRITICAL


# =============================================================================
# COMPLIANCE ENGINE
# =============================================================================

class ComplianceEngine:
    """
    Enforces compliance rules on system changes.
    
    Features:
    - Rule-based compliance checking
    - Policy enforcement
    - Violation tracking
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path("storage/market/governance.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        
        # In-memory caches
        self._rules: Dict[str, ComplianceRule] = {}
        self._policies: Dict[str, GovernancePolicy] = {}
        
        self._init_db()
        self._init_default_rules()
    
    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS compliance_rules (
                    rule_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    config TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1
                );
                
                CREATE TABLE IF NOT EXISTS governance_policies (
                    policy_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    config TEXT NOT NULL,
                    version TEXT NOT NULL
                );
                
                CREATE TABLE IF NOT EXISTS policy_violations (
                    violation_id TEXT PRIMARY KEY,
                    policy_id TEXT,
                    data TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                
                CREATE TABLE IF NOT EXISTS compliance_checks (
                    check_id TEXT PRIMARY KEY,
                    rule_id TEXT,
                    passed INTEGER,
                    data TEXT NOT NULL,
                    checked_at TEXT NOT NULL
                );
                
                CREATE INDEX IF NOT EXISTS idx_violations_status ON policy_violations(status);
                CREATE INDEX IF NOT EXISTS idx_checks_rule ON compliance_checks(rule_id);
            """)
    
    def _init_default_rules(self):
        """Initialize default compliance rules."""
        default_rules = [
            ComplianceRule(
                rule_id="min_confidence",
                name="Minimum Confidence Threshold",
                category="model_governance",
                description="Changes must meet minimum confidence threshold",
                condition_type="threshold",
                condition_params={"field": "confidence", "min": 0.5},
                severity="error",
                blocking=True,
                applies_to_change_types=["scoring_update", "model_deployment"],
            ),
            ComplianceRule(
                rule_id="max_affected_users",
                name="Maximum Affected Users",
                category="data_privacy",
                description="Single change cannot affect too many users without review",
                condition_type="threshold",
                condition_params={"field": "affected_users", "max": 10000},
                severity="warning",
                blocking=False,
                applies_to_change_types=["scoring_update", "taxonomy_merge"],
            ),
            ComplianceRule(
                rule_id="require_rollback",
                name="Rollback Capability Required",
                category="operational",
                description="Critical changes must have rollback capability",
                condition_type="threshold",
                condition_params={"field": "rollback_possible", "equals": True},
                severity="error",
                blocking=True,
                applies_to_change_types=["model_deployment", "scoring_update"],
            ),
            ComplianceRule(
                rule_id="data_freshness",
                name="Data Freshness Requirement",
                category="data_governance",
                description="Changes based on stale data require review",
                condition_type="threshold",
                condition_params={"field": "data_age_days", "max": 14},
                severity="warning",
                blocking=False,
            ),
            ComplianceRule(
                rule_id="audit_trail",
                name="Audit Trail Required",
                category="compliance",
                description="All changes must be auditable",
                condition_type="custom",
                condition_params={"check": "audit_enabled"},
                severity="error",
                blocking=True,
            ),
        ]
        
        for rule in default_rules:
            if rule.rule_id not in self._rules:
                self.register_rule(rule)
    
    def register_rule(self, rule: ComplianceRule):
        """Register a compliance rule."""
        with self._lock:
            self._rules[rule.rule_id] = rule
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO compliance_rules
                       (rule_id, name, config, enabled)
                       VALUES (?, ?, ?, ?)""",
                    (rule.rule_id, rule.name, json.dumps(rule.to_dict()),
                     1 if rule.enabled else 0)
                )
    
    def register_policy(self, policy: GovernancePolicy):
        """Register a governance policy."""
        with self._lock:
            self._policies[policy.policy_id] = policy
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO governance_policies
                       (policy_id, name, config, version)
                       VALUES (?, ?, ?, ?)""",
                    (policy.policy_id, policy.name,
                     json.dumps(policy.to_dict()), policy.version)
                )
    
    def check_compliance(
        self,
        change_type: str,
        change_id: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, List[ComplianceCheck]]:
        """
        Check compliance for a proposed change.
        
        Returns:
            Tuple of (all_passed, list_of_checks)
        """
        checks = []
        all_passed = True
        has_blocking_failure = False
        
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            
            # Check if rule applies to this change type
            if rule.applies_to_change_types and change_type not in rule.applies_to_change_types:
                continue
            
            check = self._evaluate_rule(rule, context, change_type, change_id)
            checks.append(check)
            
            if not check.passed:
                all_passed = False
                if check.blocking:
                    has_blocking_failure = True
            
            # Persist check
            self._save_check(check)
        
        logger.info(
            f"Compliance check for {change_type}/{change_id}: "
            f"passed={all_passed}, blocking_failure={has_blocking_failure}, "
            f"checks={len(checks)}"
        )
        
        return not has_blocking_failure, checks
    
    def _evaluate_rule(
        self,
        rule: ComplianceRule,
        context: Dict[str, Any],
        change_type: str,
        change_id: str
    ) -> ComplianceCheck:
        """Evaluate a single compliance rule."""
        passed = True
        message = ""
        evidence = {}
        
        if rule.condition_type == "threshold":
            params = rule.condition_params
            field = params.get("field", "")
            value = context.get(field)
            
            if value is not None:
                if "min" in params and value < params["min"]:
                    passed = False
                    message = f"{field} ({value}) is below minimum ({params['min']})"
                    evidence = {field: value, "min_required": params["min"]}
                    
                elif "max" in params and value > params["max"]:
                    passed = False
                    message = f"{field} ({value}) exceeds maximum ({params['max']})"
                    evidence = {field: value, "max_allowed": params["max"]}
                    
                elif "equals" in params and value != params["equals"]:
                    passed = False
                    message = f"{field} ({value}) does not equal required ({params['equals']})"
                    evidence = {field: value, "required": params["equals"]}
        
        elif rule.condition_type == "pattern":
            # Pattern matching rules
            params = rule.condition_params
            field = params.get("field", "")
            pattern = params.get("pattern", "")
            value = context.get(field, "")
            
            import re
            if not re.match(pattern, str(value)):
                passed = False
                message = f"{field} does not match required pattern"
                evidence = {field: value, "pattern": pattern}
        
        elif rule.condition_type == "custom":
            # Custom rule evaluation
            check_name = rule.condition_params.get("check", "")
            passed, message, evidence = self._evaluate_custom_rule(check_name, context)
        
        return ComplianceCheck(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            passed=passed,
            severity=rule.severity,
            blocking=rule.blocking,
            message=message if not passed else "Compliant",
            evidence=evidence,
            remediation_steps=self._get_remediation_steps(rule) if not passed else [],
            change_type=change_type,
            change_id=change_id,
        )
    
    def _evaluate_custom_rule(
        self,
        check_name: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Evaluate custom compliance rules."""
        if check_name == "audit_enabled":
            audit_enabled = context.get("audit_enabled", True)
            if not audit_enabled:
                return False, "Audit trail is not enabled", {"audit_enabled": False}
            return True, "", {}
        
        # Unknown custom rule - pass by default
        return True, "", {}
    
    def _get_remediation_steps(self, rule: ComplianceRule) -> List[str]:
        """Get remediation steps for a failed rule."""
        remediation_map = {
            "min_confidence": [
                "Review model predictions for accuracy",
                "Gather more training data",
                "Consider hybrid approach with human review",
            ],
            "max_affected_users": [
                "Consider phased rollout",
                "Get additional approvals",
                "Implement A/B testing",
            ],
            "require_rollback": [
                "Implement rollback mechanism",
                "Create backup before change",
                "Document manual rollback procedure",
            ],
            "data_freshness": [
                "Refresh data before proceeding",
                "Document staleness justification",
                "Request exception approval",
            ],
            "audit_trail": [
                "Enable audit logging",
                "Configure audit retention",
                "Review audit configuration",
            ],
        }
        
        return remediation_map.get(rule.rule_id, ["Review rule requirements", "Contact compliance team"])
    
    def _save_check(self, check: ComplianceCheck):
        """Save compliance check to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO compliance_checks
                   (check_id, rule_id, passed, data, checked_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (check.check_id, check.rule_id, 1 if check.passed else 0,
                 json.dumps(check.to_dict()), check.checked_at.isoformat())
            )
    
    def record_violation(self, violation: PolicyViolation):
        """Record a policy violation."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT INTO policy_violations
                       (violation_id, policy_id, data, detected_at, status)
                       VALUES (?, ?, ?, ?, ?)""",
                    (violation.violation_id, violation.policy_id,
                     json.dumps(violation.to_dict()),
                     violation.detected_at.isoformat(), violation.status)
                )
        
        logger.warning(f"Policy violation recorded: {violation.violation_id}")
    
    def get_open_violations(self) -> List[PolicyViolation]:
        """Get all open policy violations."""
        violations = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT data FROM policy_violations WHERE status = 'open'"
            )
            for row in cursor:
                data = json.loads(row[0])
                violations.append(PolicyViolation(**data))
        return violations


# =============================================================================
# AUDIT LOGGER
# =============================================================================

class AuditLogger:
    """
    Immutable audit logging for all system actions.
    
    Features:
    - Tamper-evident logging with hash chain
    - Structured event recording
    - Retention management
    - Query capabilities
    """
    
    def __init__(self, db_path: Optional[Path] = None, config: Optional[GovernanceConfig] = None):
        self.db_path = db_path or Path("storage/market/audit.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.config = config or GovernanceConfig()
        self._lock = threading.RLock()
        
        # Hash chain for tamper detection
        self._last_hash: Optional[str] = None
        
        self._init_db()
        self._load_last_hash()
    
    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    entry_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    summary TEXT,
                    actor_type TEXT,
                    actor_id TEXT,
                    target_type TEXT,
                    target_id TEXT,
                    component TEXT,
                    success INTEGER,
                    data TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    hash TEXT NOT NULL,
                    prev_hash TEXT
                );
                
                CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
                CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_log(event_type);
                CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor_id);
                CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_log(target_type, target_id);
                CREATE INDEX IF NOT EXISTS idx_audit_component ON audit_log(component);
            """)
    
    def _load_last_hash(self):
        """Load the last hash from the audit chain."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT hash FROM audit_log ORDER BY timestamp DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row:
                self._last_hash = row[0]
    
    def _compute_hash(self, entry: AuditEntry, prev_hash: Optional[str]) -> str:
        """Compute hash for audit entry (hash chain)."""
        content = json.dumps({
            "entry_id": entry.entry_id,
            "event_type": entry.event_type.value,
            "timestamp": entry.timestamp.isoformat(),
            "actor_id": entry.actor_id,
            "target_id": entry.target_id,
            "prev_hash": prev_hash or "",
        }, sort_keys=True)
        
        return hashlib.sha256(content.encode()).hexdigest()
    
    def log(self, entry: AuditEntry) -> str:
        """
        Log an audit entry.
        
        Returns the entry ID.
        """
        with self._lock:
            # Compute hash chain
            entry_hash = self._compute_hash(entry, self._last_hash)
            
            # Mask sensitive data if configured
            data = entry.to_dict()
            if self.config.audit_sensitive_data_masking and entry.sensitive_data:
                data = self._mask_sensitive_data(data)
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT INTO audit_log
                       (entry_id, event_type, summary, actor_type, actor_id,
                        target_type, target_id, component, success, data,
                        timestamp, hash, prev_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (entry.entry_id, entry.event_type.value, entry.summary,
                     entry.actor_type, entry.actor_id, entry.target_type,
                     entry.target_id, entry.component, 1 if entry.success else 0,
                     json.dumps(data), entry.timestamp.isoformat(),
                     entry_hash, self._last_hash)
                )
            
            self._last_hash = entry_hash
            
            logger.debug(f"Audit logged: {entry.event_type.value} - {entry.summary}")
            return entry.entry_id
    
    def _mask_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Mask sensitive fields in audit data."""
        masked = data.copy()
        sensitive_fields = ["password", "token", "api_key", "secret", "credential"]
        
        def mask_recursive(obj):
            if isinstance(obj, dict):
                for key in obj:
                    if any(sf in key.lower() for sf in sensitive_fields):
                        obj[key] = "***MASKED***"
                    else:
                        mask_recursive(obj[key])
            elif isinstance(obj, list):
                for item in obj:
                    mask_recursive(item)
        
        mask_recursive(masked)
        return masked
    
    def log_event(
        self,
        event_type: AuditEventType,
        summary: str,
        details: Dict[str, Any] = None,
        actor_type: str = "system",
        actor_id: str = "",
        target_type: str = "",
        target_id: str = "",
        component: str = "",
        success: bool = True,
        correlation_id: str = "",
    ) -> str:
        """Convenience method to log an event."""
        entry = AuditEntry(
            event_type=event_type,
            summary=summary,
            details=details or {},
            actor_type=actor_type,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            component=component,
            success=success,
            correlation_id=correlation_id,
            retention_days=self.config.audit_retention_days,
        )
        return self.log(entry)
    
    def query(
        self,
        event_types: List[AuditEventType] = None,
        actor_id: str = None,
        target_type: str = None,
        target_id: str = None,
        component: str = None,
        start_time: datetime = None,
        end_time: datetime = None,
        success_only: bool = None,
        limit: int = 100,
    ) -> List[AuditEntry]:
        """Query audit log with filters."""
        conditions = []
        params = []
        
        if event_types:
            placeholders = ",".join("?" * len(event_types))
            conditions.append(f"event_type IN ({placeholders})")
            params.extend([et.value for et in event_types])
        
        if actor_id:
            conditions.append("actor_id = ?")
            params.append(actor_id)
        
        if target_type:
            conditions.append("target_type = ?")
            params.append(target_type)
        
        if target_id:
            conditions.append("target_id = ?")
            params.append(target_id)
        
        if component:
            conditions.append("component = ?")
            params.append(component)
        
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time.isoformat())
        
        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time.isoformat())
        
        if success_only is not None:
            conditions.append("success = ?")
            params.append(1 if success_only else 0)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        entries = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"""SELECT data FROM audit_log
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT ?""",
                params + [limit]
            )
            for row in cursor:
                entries.append(AuditEntry.from_dict(json.loads(row[0])))
        
        return entries
    
    def verify_integrity(self) -> Tuple[bool, List[str]]:
        """
        Verify the integrity of the audit chain.
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT entry_id, data, hash, prev_hash FROM audit_log ORDER BY timestamp"
            )
            
            prev_hash = None
            for row in cursor:
                entry_id, data_json, stored_hash, stored_prev_hash = row
                data = json.loads(data_json)
                entry = AuditEntry.from_dict(data)
                
                # Verify prev_hash chain
                if stored_prev_hash != prev_hash:
                    errors.append(f"Entry {entry_id}: prev_hash mismatch")
                
                # Verify entry hash
                computed_hash = self._compute_hash(entry, stored_prev_hash)
                if computed_hash != stored_hash:
                    errors.append(f"Entry {entry_id}: hash mismatch (tampered?)")
                
                prev_hash = stored_hash
        
        is_valid = len(errors) == 0
        if not is_valid:
            logger.error(f"Audit integrity check failed: {len(errors)} errors")
        else:
            logger.info("Audit integrity check passed")
        
        return is_valid, errors
    
    def cleanup_old_entries(self) -> int:
        """Remove entries older than retention period."""
        cutoff = datetime.utcnow() - timedelta(days=self.config.audit_retention_days)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM audit_log WHERE timestamp < ?",
                (cutoff.isoformat(),)
            )
            deleted = cursor.rowcount
        
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old audit entries")
        
        return deleted


# =============================================================================
# GOVERNANCE ENGINE (UNIFIED)
# =============================================================================

class GovernanceEngine:
    """
    Unified governance engine coordinating all governance components.
    
    Provides single entry point for:
    - Risk assessment
    - Compliance checking
    - Approval workflow
    - Audit logging
    - Emergency overrides
    """
    
    _instance: Optional["GovernanceEngine"] = None
    _lock = threading.Lock()
    
    def __init__(self, config: Optional[GovernanceConfig] = None):
        self.config = config or GovernanceConfig()
        
        # Initialize components
        db_path = Path("storage/market/governance.db")
        audit_db_path = Path("storage/market/audit.db")
        
        self.approval_workflow = ApprovalWorkflow(db_path)
        self.risk_assessor = RiskAssessor(self.config)
        self.compliance_engine = ComplianceEngine(db_path)
        self.audit_logger = AuditLogger(audit_db_path, self.config)
        
        # Emergency overrides
        self._active_overrides: Dict[str, EmergencyOverride] = {}
        
        # Wire up internal callbacks
        self._setup_callbacks()
        
        logger.info("Governance Engine initialized")
    
    @classmethod
    def get_instance(cls, config: Optional[GovernanceConfig] = None) -> "GovernanceEngine":
        """Get singleton instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(config)
            return cls._instance
    
    def _setup_callbacks(self):
        """Setup internal event callbacks."""
        # Log approval events
        self.approval_workflow.on_approval_requested(self._on_approval_requested)
        self.approval_workflow.on_approval_resolved(self._on_approval_resolved)
        self.approval_workflow.on_escalation(self._on_escalation)
    
    def _on_approval_requested(self, request: ApprovalRequest):
        """Handle new approval request."""
        self.audit_logger.log_event(
            event_type=AuditEventType.APPROVAL_REQUESTED,
            summary=f"Approval requested: {request.change_summary}",
            details=request.to_dict(),
            target_type="approval_request",
            target_id=request.request_id,
            component="approval_workflow",
        )
    
    def _on_approval_resolved(self, request: ApprovalRequest):
        """Handle resolved approval."""
        event_type = (AuditEventType.APPROVAL_GRANTED 
                     if request.status == ApprovalStatus.APPROVED 
                     else AuditEventType.APPROVAL_REJECTED)
        
        self.audit_logger.log_event(
            event_type=event_type,
            summary=f"Approval {request.status.value}: {request.change_summary}",
            details=request.to_dict(),
            target_type="approval_request",
            target_id=request.request_id,
            component="approval_workflow",
        )
    
    def _on_escalation(self, request: ApprovalRequest):
        """Handle approval escalation."""
        self.audit_logger.log_event(
            event_type=AuditEventType.APPROVAL_ESCALATED,
            summary=f"Approval escalated: {request.change_summary}",
            details=request.to_dict(),
            target_type="approval_request",
            target_id=request.request_id,
            component="approval_workflow",
        )
    
    def evaluate_change(
        self,
        change_type: str,
        change_id: str,
        change_summary: str,
        change_details: Dict[str, Any],
        context: Dict[str, Any],
        requestor_id: str = "system",
    ) -> Dict[str, Any]:
        """
        Evaluate a proposed change through the governance pipeline.
        
        Returns:
            Dict with decision, risk assessment, compliance checks, and approval info
        """
        # Step 1: Risk Assessment
        risk_assessment = self.risk_assessor.assess(change_type, change_id, context)
        
        # Step 2: Compliance Check
        compliance_passed, compliance_checks = self.compliance_engine.check_compliance(
            change_type, change_id, context
        )
        
        # Step 3: Check for active emergency overrides
        override = self._get_active_override(change_type)
        if override:
            self.audit_logger.log_event(
                event_type=AuditEventType.EMERGENCY_OVERRIDE,
                summary=f"Emergency override active for {change_type}",
                details={"override_id": override.override_id, "reason": override.reason},
                target_type=change_type,
                target_id=change_id,
                component="governance_engine",
            )
            
            return {
                "decision": "approved_override",
                "risk_assessment": risk_assessment.to_dict(),
                "compliance_passed": compliance_passed,
                "compliance_checks": [c.to_dict() for c in compliance_checks],
                "requires_approval": False,
                "approval_request": None,
                "override": override.to_dict(),
            }
        
        # Step 4: Determine if approval is needed
        requires_approval = (
            risk_assessment.requires_approval or
            not compliance_passed or
            risk_assessment.overall_risk_score >= self.config.risk_human_review_threshold or
            context.get("confidence", 1.0) < self.config.confidence_auto_threshold
        )
        
        # Step 5: Auto-approve low risk changes if configured
        if not requires_approval and self.config.auto_approve_low_risk:
            self.audit_logger.log_event(
                event_type=AuditEventType.CONFIG_CHANGE,
                summary=f"Auto-approved: {change_summary}",
                details={
                    "change_type": change_type,
                    "change_id": change_id,
                    "risk_score": risk_assessment.overall_risk_score,
                },
                target_type=change_type,
                target_id=change_id,
                component="governance_engine",
            )
            
            return {
                "decision": "auto_approved",
                "risk_assessment": risk_assessment.to_dict(),
                "compliance_passed": compliance_passed,
                "compliance_checks": [c.to_dict() for c in compliance_checks],
                "requires_approval": False,
                "approval_request": None,
            }
        
        # Step 6: Block if risk is too high
        blocking_compliance = any(c.blocking and not c.passed for c in compliance_checks)
        if (risk_assessment.overall_risk_score >= self.config.risk_block_threshold or
            blocking_compliance) and self.config.auto_reject_blocked:
            
            self.audit_logger.log_event(
                event_type=AuditEventType.COMPLIANCE_VIOLATION,
                summary=f"Blocked: {change_summary}",
                details={
                    "change_type": change_type,
                    "change_id": change_id,
                    "risk_score": risk_assessment.overall_risk_score,
                    "blocking_factors": risk_assessment.blocking_factors,
                },
                target_type=change_type,
                target_id=change_id,
                component="governance_engine",
                success=False,
            )
            
            return {
                "decision": "blocked",
                "risk_assessment": risk_assessment.to_dict(),
                "compliance_passed": compliance_passed,
                "compliance_checks": [c.to_dict() for c in compliance_checks],
                "requires_approval": True,
                "approval_request": None,
                "blocking_reasons": risk_assessment.blocking_factors + 
                    [c.rule_name for c in compliance_checks if c.blocking and not c.passed],
            }
        
        # Step 7: Create approval request
        applicable_gates = self.approval_workflow.get_applicable_gates(
            change_type,
            risk_assessment.overall_risk_level.value,
            context.get("confidence", 1.0)
        )
        
        if applicable_gates:
            gate = applicable_gates[0]  # Use highest priority gate
            
            approval_request = self.approval_workflow.create_request(
                gate_id=gate.gate_id,
                change_type=change_type,
                change_summary=change_summary,
                change_details=change_details,
                risk_level=risk_assessment.overall_risk_level.value,
                risk_score=risk_assessment.overall_risk_score,
                confidence_score=context.get("confidence", 1.0),
                affected_records=context.get("affected_records", 0),
                affected_components=context.get("affected_components", []),
                requestor_id=requestor_id,
                urgency="high" if risk_assessment.overall_risk_level in 
                    [RiskLevel.HIGH, RiskLevel.CRITICAL] else "normal",
            )
            
            return {
                "decision": "pending_approval",
                "risk_assessment": risk_assessment.to_dict(),
                "compliance_passed": compliance_passed,
                "compliance_checks": [c.to_dict() for c in compliance_checks],
                "requires_approval": True,
                "approval_request": approval_request.to_dict(),
                "gate": gate.to_dict(),
            }
        
        # No applicable gates - auto approve
        return {
            "decision": "auto_approved",
            "risk_assessment": risk_assessment.to_dict(),
            "compliance_passed": compliance_passed,
            "compliance_checks": [c.to_dict() for c in compliance_checks],
            "requires_approval": False,
            "approval_request": None,
        }
    
    def create_emergency_override(
        self,
        reason: str,
        justification: str,
        override_type: str,
        authorized_by: str,
        authorizer_role: str,
        duration_hours: int = 4,
        affected_gates: List[str] = None,
        affected_rules: List[str] = None,
        secondary_authorization: str = None,
    ) -> EmergencyOverride:
        """
        Create an emergency override.
        
        Requires dual authorization if configured.
        """
        # Check if dual authorization is required
        if self.config.emergency_dual_authorization and not secondary_authorization:
            raise ValueError("Emergency overrides require dual authorization")
        
        # Enforce max duration
        duration_hours = min(duration_hours, self.config.emergency_max_duration_hours)
        
        override = EmergencyOverride(
            reason=reason,
            justification=justification,
            override_type=override_type,
            authorized_by=authorized_by,
            authorizer_role=authorizer_role,
            secondary_authorization=secondary_authorization,
            affected_gates=affected_gates or [],
            affected_rules=affected_rules or [],
            effective_from=datetime.utcnow(),
            effective_until=datetime.utcnow() + timedelta(hours=duration_hours),
        )
        
        self._active_overrides[override.override_id] = override
        
        # Audit
        self.audit_logger.log_event(
            event_type=AuditEventType.EMERGENCY_OVERRIDE,
            summary=f"Emergency override created: {reason}",
            details=override.to_dict(),
            actor_type="user",
            actor_id=authorized_by,
            target_type="emergency_override",
            target_id=override.override_id,
            component="governance_engine",
        )
        
        logger.warning(f"Emergency override created: {override.override_id} by {authorized_by}")
        return override
    
    def revoke_override(
        self,
        override_id: str,
        revoked_by: str,
        reason: str = ""
    ):
        """Revoke an emergency override."""
        override = self._active_overrides.get(override_id)
        if not override:
            raise ValueError(f"Unknown override: {override_id}")
        
        override.revoked = True
        override.revoked_by = revoked_by
        override.revoked_at = datetime.utcnow()
        override.revocation_reason = reason
        override.active = False
        
        # Audit
        self.audit_logger.log_event(
            event_type=AuditEventType.EMERGENCY_OVERRIDE,
            summary=f"Emergency override revoked: {override_id}",
            details={"override_id": override_id, "reason": reason},
            actor_type="user",
            actor_id=revoked_by,
            target_type="emergency_override",
            target_id=override_id,
            component="governance_engine",
        )
        
        logger.info(f"Emergency override revoked: {override_id}")
    
    def _get_active_override(self, change_type: str) -> Optional[EmergencyOverride]:
        """Get active override for change type."""
        for override in self._active_overrides.values():
            if override.is_active():
                # Check if override applies to all or specific change types
                if not override.affected_changes or change_type in override.affected_changes:
                    return override
        return None
    
    def get_governance_status(self) -> Dict[str, Any]:
        """Get overall governance status."""
        return {
            "pending_approvals": len(self.approval_workflow.get_pending_requests()),
            "active_overrides": len([o for o in self._active_overrides.values() if o.is_active()]),
            "open_violations": len(self.compliance_engine.get_open_violations()),
            "config": self.config.to_dict(),
        }


# Singleton accessor
def get_governance_engine(config: Optional[GovernanceConfig] = None) -> GovernanceEngine:
    """Get the governance engine singleton."""
    return GovernanceEngine.get_instance(config)

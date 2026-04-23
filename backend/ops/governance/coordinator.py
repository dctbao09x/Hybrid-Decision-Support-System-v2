# backend/ops/governance/coordinator.py
"""
Integrated Governance Coordinator
==================================

Central integration hub that connects:
- Cost & Budget Engine
- Incident Management System
- Kill-Switch Controller
- Policy Engine
- Monitoring Integration
- MLOps Integration

Control Flow:
1. Request → Policy Check → Cost Check → Processing
2. Anomaly → Alert → Incident → Response
3. Threshold → Auto-Trigger → Kill-Switch → Safe Mode
4. Recovery → Resume → Post-mortem

Authority Chain:
- L0: Automated systems (auto-triggers, enforcement)
- L1: On-call operators
- L2: Team leads / Incident commanders
- L3: Directors / Senior management
- L4: VP / C-level (emergency override)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from threading import RLock, Thread
from typing import Any, Callable, Dict, List, Optional, Set

# Import subsystems
from ..cost import (
    BudgetManager,
    CostEnforcementEngine,
    CostIntelligence,
    AlertLevel,
    EnforcementAction,
    get_budget_manager,
    get_enforcement_engine,
    get_cost_intelligence,
)
from ..incident import (
    IncidentManager,
    IncidentPriority,
    IncidentStatus,
    get_incident_manager,
)
from ..killswitch import (
    KillSwitchController,
    KillScope,
    KillSwitchState,
    SafeModeLevel,
    TriggerCondition,
    get_killswitch,
)

logger = logging.getLogger("ops.governance")


class AuthorityLevel(str, Enum):
    """Authority levels for governance decisions."""
    L0_AUTOMATED = "l0_automated"      # Auto-triggers
    L1_OPERATOR = "l1_operator"        # On-call
    L2_TEAM_LEAD = "l2_team_lead"      # Incident commander
    L3_DIRECTOR = "l3_director"        # Senior management
    L4_EXECUTIVE = "l4_executive"      # C-level override


class GovernanceAction(str, Enum):
    """Governance actions."""
    ALLOW = "allow"
    THROTTLE = "throttle"
    DEGRADE = "degrade"
    BLOCK = "block"
    KILL = "kill"
    ESCALATE = "escalate"


@dataclass
class GovernanceDecision:
    """Result of governance evaluation."""
    request_id: str
    timestamp: str
    action: GovernanceAction
    reason: str
    authority: AuthorityLevel
    
    # Cost context
    cost_ok: bool = True
    cost_utilization: float = 0.0
    cost_action: Optional[EnforcementAction] = None
    
    # Kill-switch context
    killswitch_state: KillSwitchState = KillSwitchState.ACTIVE
    safe_mode_level: SafeModeLevel = SafeModeLevel.NONE
    
    # Incident context
    active_incidents: int = 0
    highest_priority: Optional[IncidentPriority] = None
    
    # Override
    override_applied: bool = False
    override_by: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "action": self.action.value,
            "reason": self.reason,
            "authority": self.authority.value,
            "cost_ok": self.cost_ok,
            "cost_utilization": self.cost_utilization,
            "cost_action": self.cost_action.value if self.cost_action else None,
            "killswitch_state": self.killswitch_state.value,
            "safe_mode_level": self.safe_mode_level.value,
            "active_incidents": self.active_incidents,
            "highest_priority": self.highest_priority.value if self.highest_priority else None,
            "override_applied": self.override_applied,
            "override_by": self.override_by,
        }


@dataclass
class EscalationPath:
    """Escalation path definition."""
    path_id: str
    name: str
    levels: List[AuthorityLevel]
    contacts: Dict[AuthorityLevel, List[str]]
    auto_escalation_minutes: Dict[AuthorityLevel, int]
    
    def get_next_level(self, current: AuthorityLevel) -> Optional[AuthorityLevel]:
        """Get next escalation level."""
        try:
            idx = self.levels.index(current)
            if idx < len(self.levels) - 1:
                return self.levels[idx + 1]
        except ValueError:
            pass
        return None


@dataclass 
class Override:
    """Governance override record."""
    override_id: str
    timestamp: str
    authority: AuthorityLevel
    actor: str
    scope: KillScope
    scope_id: str
    original_action: GovernanceAction
    new_action: GovernanceAction
    reason: str
    expires_at: str
    active: bool = True


class GovernanceCoordinator:
    """
    Central governance coordination.
    
    Integrates:
    - Cost checking before requests
    - Kill-switch state awareness
    - Incident-driven restrictions
    - Policy enforcement
    - Authority-based overrides
    """
    
    def __init__(
        self,
        budget_manager: Optional[BudgetManager] = None,
        enforcement_engine: Optional[CostEnforcementEngine] = None,
        cost_intelligence: Optional[CostIntelligence] = None,
        incident_manager: Optional[IncidentManager] = None,
        killswitch: Optional[KillSwitchController] = None,
    ):
        # Initialize subsystems
        self._budget = budget_manager or get_budget_manager()
        self._enforcement = enforcement_engine or get_enforcement_engine()
        self._intelligence = cost_intelligence or get_cost_intelligence()
        self._incidents = incident_manager or get_incident_manager()
        self._killswitch = killswitch or get_killswitch()
        
        self._lock = RLock()
        
        # Overrides
        self._overrides: Dict[str, Override] = {}
        
        # Escalation paths
        self._escalation_paths: Dict[str, EscalationPath] = {}
        
        # Monitoring loop
        self._monitoring_active = False
        self._monitoring_thread: Optional[Thread] = None
        
        # Register callbacks
        self._setup_integrations()
        self._init_escalation_paths()
    
    def _setup_integrations(self) -> None:
        """Wire up subsystem integrations."""
        # Cost enforcement → Incident creation
        # When cost hits CRITICAL, create incident
        
        # Kill-switch → Incident creation
        self._killswitch.on_kill(self._on_killswitch_activated)
        self._killswitch.on_safe_mode(self._on_safe_mode_activated)
    
    def _init_escalation_paths(self) -> None:
        """Initialize default escalation paths."""
        self._escalation_paths["default"] = EscalationPath(
            path_id="default",
            name="Default Escalation",
            levels=[
                AuthorityLevel.L1_OPERATOR,
                AuthorityLevel.L2_TEAM_LEAD,
                AuthorityLevel.L3_DIRECTOR,
                AuthorityLevel.L4_EXECUTIVE,
            ],
            contacts={
                AuthorityLevel.L1_OPERATOR: ["ops-oncall@company.com"],
                AuthorityLevel.L2_TEAM_LEAD: ["team-lead@company.com"],
                AuthorityLevel.L3_DIRECTOR: ["ai-director@company.com"],
                AuthorityLevel.L4_EXECUTIVE: ["cto@company.com", "cmo@company.com"],
            },
            auto_escalation_minutes={
                AuthorityLevel.L1_OPERATOR: 15,
                AuthorityLevel.L2_TEAM_LEAD: 30,
                AuthorityLevel.L3_DIRECTOR: 60,
            },
        )
        
        self._escalation_paths["critical"] = EscalationPath(
            path_id="critical",
            name="Critical Fast-Track",
            levels=[
                AuthorityLevel.L2_TEAM_LEAD,
                AuthorityLevel.L3_DIRECTOR,
                AuthorityLevel.L4_EXECUTIVE,
            ],
            contacts={
                AuthorityLevel.L2_TEAM_LEAD: ["team-lead@company.com", "incident-commander@company.com"],
                AuthorityLevel.L3_DIRECTOR: ["ai-director@company.com"],
                AuthorityLevel.L4_EXECUTIVE: ["cto@company.com", "ceo@company.com"],
            },
            auto_escalation_minutes={
                AuthorityLevel.L2_TEAM_LEAD: 10,
                AuthorityLevel.L3_DIRECTOR: 20,
            },
        )
    
    # ═══════════════════════════════════════════════════════════════════
    # Request Evaluation
    # ═══════════════════════════════════════════════════════════════════
    
    def evaluate_request(
        self,
        request_id: str,
        service: str,
        model_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        estimated_cost: float = 0.0,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> GovernanceDecision:
        """
        Evaluate a request against all governance controls.
        
        Control flow:
        1. Check kill-switch state
        2. Check active incidents
        3. Check cost limits
        4. Check overrides
        5. Return decision
        
        Args:
            request_id: Unique request identifier
            service: Service name (inference, retrain, etc.)
            model_id: Optional model identifier
            endpoint: Optional API endpoint
            estimated_cost: Estimated cost of request
            user_id: Optional user making request
            project_id: Optional project identifier
            
        Returns:
            GovernanceDecision with action and context
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # 1. Check kill-switch
        can_proceed, ks_reason, safe_level = self._killswitch.can_process(
            service=service,
            model_id=model_id,
            endpoint=endpoint,
        )
        
        if not can_proceed:
            return GovernanceDecision(
                request_id=request_id,
                timestamp=timestamp,
                action=GovernanceAction.KILL,
                reason=ks_reason,
                authority=AuthorityLevel.L0_AUTOMATED,
                killswitch_state=KillSwitchState.KILLED,
                safe_mode_level=safe_level,
            )
        
        # 2. Check active incidents
        stats = self._incidents.get_incident_stats()
        active_p0 = stats.get("by_priority", {}).get("P0", 0)
        active_p1 = stats.get("by_priority", {}).get("P1", 0)
        
        # Block new work during critical incidents
        if active_p0 > 0:
            return GovernanceDecision(
                request_id=request_id,
                timestamp=timestamp,
                action=GovernanceAction.BLOCK,
                reason=f"Active P0 incident(s): {active_p0}",
                authority=AuthorityLevel.L2_TEAM_LEAD,
                active_incidents=stats.get("open", 0),
                highest_priority=IncidentPriority.P0,
            )
        
        # 3. Check cost limits
        cost_can_process, cost_reason, throttle_factor = self._enforcement.can_process_request(
            service=service,
            estimated_cost=estimated_cost,
        )
        
        # Get budget utilization
        budget_status = self._budget.get_budget_status(
            self._budget._default_budgets.get("global_monthly", "global_monthly")
        )
        cost_util = budget_status.utilization if budget_status else 0.0
        
        if not cost_can_process:
            return GovernanceDecision(
                request_id=request_id,
                timestamp=timestamp,
                action=GovernanceAction.BLOCK,
                reason=cost_reason,
                authority=AuthorityLevel.L0_AUTOMATED,
                cost_ok=False,
                cost_utilization=cost_util,
                cost_action=EnforcementAction.SHUTDOWN,
            )
        
        # 4. Check for active overrides
        override_key = f"{service}:{model_id or '*'}"
        override = self._get_active_override(override_key)
        
        if override:
            return GovernanceDecision(
                request_id=request_id,
                timestamp=timestamp,
                action=override.new_action,
                reason=f"Override active: {override.reason}",
                authority=override.authority,
                cost_ok=True,
                cost_utilization=cost_util,
                safe_mode_level=safe_level,
                override_applied=True,
                override_by=override.actor,
            )
        
        # 5. Determine final action based on safe mode
        action = GovernanceAction.ALLOW
        reason = "All checks passed"
        
        if safe_level == SafeModeLevel.CACHE_ONLY:
            action = GovernanceAction.DEGRADE
            reason = "Safe mode: cache-only responses"
        elif safe_level == SafeModeLevel.RULE_ONLY:
            action = GovernanceAction.DEGRADE
            reason = "Safe mode: rule-based decisions only"
        elif safe_level == SafeModeLevel.STATIC:
            action = GovernanceAction.DEGRADE
            reason = "Safe mode: static fallback responses"
        elif throttle_factor < 1.0:
            action = GovernanceAction.THROTTLE
            reason = f"Throttled to {throttle_factor*100:.0f}% capacity"
        
        return GovernanceDecision(
            request_id=request_id,
            timestamp=timestamp,
            action=action,
            reason=reason,
            authority=AuthorityLevel.L0_AUTOMATED,
            cost_ok=True,
            cost_utilization=cost_util,
            killswitch_state=self._killswitch.get_state(KillScope.GLOBAL, "*"),
            safe_mode_level=safe_level,
            active_incidents=stats.get("open", 0),
            highest_priority=IncidentPriority.P1 if active_p1 > 0 else None,
        )
    
    # ═══════════════════════════════════════════════════════════════════
    # Override Management
    # ═══════════════════════════════════════════════════════════════════
    
    def create_override(
        self,
        scope: KillScope,
        scope_id: str,
        original_action: GovernanceAction,
        new_action: GovernanceAction,
        reason: str,
        actor: str,
        authority: AuthorityLevel,
        duration_hours: int = 4,
    ) -> Override:
        """
        Create governance override.
        
        Override logic:
        - Higher authority can override lower
        - Overrides have time limits
        - All overrides are logged
        """
        override = Override(
            override_id=f"override_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            authority=authority,
            actor=actor,
            scope=scope,
            scope_id=scope_id,
            original_action=original_action,
            new_action=new_action,
            reason=reason,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=duration_hours)).isoformat(),
        )
        
        key = f"{scope.value}:{scope_id}"
        with self._lock:
            self._overrides[key] = override
        
        logger.warning(
            f"OVERRIDE CREATED by {actor} [{authority.value}]: "
            f"{scope.value}:{scope_id} {original_action.value} → {new_action.value}"
        )
        
        return override
    
    def _get_active_override(self, key: str) -> Optional[Override]:
        """Get active override for key."""
        override = self._overrides.get(key)
        if not override:
            return None
        
        if not override.active:
            return None
        
        # Check expiration
        expires = datetime.fromisoformat(override.expires_at.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) > expires:
            override.active = False
            return None
        
        return override
    
    def revoke_override(self, override_id: str, actor: str) -> bool:
        """Revoke an active override."""
        for key, override in self._overrides.items():
            if override.override_id == override_id:
                override.active = False
                logger.info(f"Override {override_id} revoked by {actor}")
                return True
        return False
    
    # ═══════════════════════════════════════════════════════════════════
    # Event Callbacks
    # ═══════════════════════════════════════════════════════════════════
    
    def _on_killswitch_activated(self, scope_id: str, scope: KillScope) -> None:
        """Handle kill-switch activation."""
        # Create incident for kill-switch activation
        self._incidents.create_incident(
            title=f"Kill-switch activated: {scope.value}:{scope_id}",
            description=f"Kill-switch was activated for {scope.value}:{scope_id}",
            priority=IncidentPriority.P1,
            source="killswitch_controller",
        )
    
    def _on_safe_mode_activated(self, scope_id: str, level: SafeModeLevel) -> None:
        """Handle safe mode activation."""
        priority = IncidentPriority.P2
        if level in [SafeModeLevel.STATIC, SafeModeLevel.OFFLINE]:
            priority = IncidentPriority.P1
        
        self._incidents.create_incident(
            title=f"Safe mode activated: {scope_id} → {level.value}",
            description=f"Service {scope_id} entered safe mode: {level.value}",
            priority=priority,
            source="killswitch_controller",
        )
    
    # ═══════════════════════════════════════════════════════════════════
    # Escalation
    # ═══════════════════════════════════════════════════════════════════
    
    def escalate(
        self,
        incident_id: str,
        current_level: AuthorityLevel,
        escalation_path: str = "default",
    ) -> Optional[AuthorityLevel]:
        """
        Escalate an incident to next authority level.
        
        Returns next level or None if at max.
        """
        path = self._escalation_paths.get(escalation_path)
        if not path:
            logger.error(f"Escalation path {escalation_path} not found")
            return None
        
        next_level = path.get_next_level(current_level)
        if not next_level:
            logger.warning(f"At maximum escalation level for incident {incident_id}")
            return None
        
        contacts = path.contacts.get(next_level, [])
        
        logger.warning(
            f"ESCALATION: Incident {incident_id} → {next_level.value} "
            f"Contacts: {contacts}"
        )
        
        # Update incident
        self._incidents.assign_incident(
            incident_id,
            contact=contacts[0] if contacts else "unassigned",
        )
        
        return next_level
    
    # ═══════════════════════════════════════════════════════════════════
    # Monitoring Loop
    # ═══════════════════════════════════════════════════════════════════
    
    def start_monitoring(self, interval_seconds: int = 60) -> None:
        """Start background monitoring loop."""
        if self._monitoring_active:
            return
        
        self._monitoring_active = True
        
        def _loop():
            while self._monitoring_active:
                try:
                    self._monitoring_cycle()
                except Exception as e:
                    logger.error(f"Monitoring cycle error: {e}")
                
                import time
                time.sleep(interval_seconds)
        
        self._monitoring_thread = Thread(target=_loop, daemon=True)
        self._monitoring_thread.start()
        logger.info("Governance monitoring started")
    
    def stop_monitoring(self) -> None:
        """Stop background monitoring."""
        self._monitoring_active = False
        if self._monitoring_thread:
            self._monitoring_thread.join(timeout=5)
        logger.info("Governance monitoring stopped")
    
    def _monitoring_cycle(self) -> None:
        """Single monitoring cycle."""
        # 1. Check cost forecasts
        forecasts = {}
        for budget_id in ["global_monthly", "llm_daily", "inference_daily"]:
            forecast = self._intelligence.forecast_budget(budget_id)
            if forecast:
                forecasts[budget_id] = forecast
                
                if forecast.will_exceed:
                    logger.warning(
                        f"Budget {budget_id} projected to exceed "
                        f"in {forecast.days_until_limit or 0} days"
                    )
        
        # 2. Detect cost anomalies
        anomalies = self._intelligence.detect_anomalies()
        for anomaly in anomalies:
            if anomaly.z_score > 3.0:
                self._incidents.create_incident(
                    title=f"Cost anomaly detected: {anomaly.category}",
                    description=f"Anomaly: {anomaly.description}. Z-score: {anomaly.z_score:.2f}",
                    priority=IncidentPriority.P2,
                    source="cost_intelligence",
                )
        
        # 3. Check incident escalations
        stats = self._incidents.get_incident_stats()
        
        # 4. Run cost enforcement checks
        asyncio.run(self._enforcement.check_and_enforce())
        
        # 5. Build metrics for auto-triggers
        metrics = {
            "cost_utilization": forecasts.get("global_monthly", {}).utilization if forecasts.get("global_monthly") else 0,
            "error_rate": 0.0,  # Would come from monitoring
            "drift_score": 0.0,  # Would come from drift detector
        }
        
        asyncio.run(self._killswitch.check_auto_triggers(metrics))
    
    # ═══════════════════════════════════════════════════════════════════
    # Dashboard
    # ═══════════════════════════════════════════════════════════════════
    
    def get_dashboard(self) -> Dict[str, Any]:
        """Get comprehensive governance dashboard."""
        # Kill-switch status
        ks_status = self._killswitch.get_status()
        
        # Incident stats
        incident_stats = self._incidents.get_incident_stats()
        
        # Cost status
        budget_statuses = []
        for budget_id in ["global_monthly", "llm_daily", "inference_daily"]:
            status = self._budget.get_budget_status(budget_id)
            if status:
                budget_statuses.append({
                    "budget_id": budget_id,
                    "utilization": status.utilization,
                    "alert_level": status.alert_level.value,
                    "amount_remaining": status.amount_remaining,
                })
        
        # Enforcement state
        enforcement_state = self._enforcement.get_enforcement_state()
        
        # Active overrides
        active_overrides = [
            o.to_dict() if hasattr(o, 'to_dict') else {
                "override_id": o.override_id,
                "scope": o.scope.value,
                "scope_id": o.scope_id,
                "new_action": o.new_action.value,
                "expires_at": o.expires_at,
            }
            for o in self._overrides.values()
            if o.active
        ]
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overall_status": self._calculate_overall_status(ks_status, incident_stats),
            "killswitch": ks_status,
            "incidents": incident_stats,
            "cost": {
                "budgets": budget_statuses,
                "enforcement": enforcement_state,
            },
            "overrides": active_overrides,
            "pending_approvals": ks_status.get("pending_approvals", 0),
        }
    
    def _calculate_overall_status(
        self,
        ks_status: Dict[str, Any],
        incident_stats: Dict[str, Any],
    ) -> str:
        """Calculate overall governance status."""
        # Critical issues
        if ks_status.get("global_state") == "killed":
            return "CRITICAL"
        
        if incident_stats.get("by_priority", {}).get("P0", 0) > 0:
            return "CRITICAL"
        
        # Warning states
        if ks_status.get("global_state") == "safe_mode":
            return "DEGRADED"
        
        if incident_stats.get("by_priority", {}).get("P1", 0) > 0:
            return "WARNING"
        
        if ks_status.get("active_kills"):
            return "WARNING"
        
        return "HEALTHY"


# ═══════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════

_coordinator: Optional[GovernanceCoordinator] = None


def get_governance_coordinator() -> GovernanceCoordinator:
    """Get singleton GovernanceCoordinator instance."""
    global _coordinator
    if _coordinator is None:
        _coordinator = GovernanceCoordinator()
    return _coordinator

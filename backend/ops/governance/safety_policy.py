# backend/ops/governance/safety_policy.py
"""
Safety Policy Engine
====================

Enforces safety policies for operational commands.

Features:
- Role-based execution limits
- Approval requirements
- Cooldown periods
- Scope restrictions
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("ops.governance.safety_policy")


class PolicyAction(str, Enum):
    """Actions that can be policy-controlled."""
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    RATE_LIMIT = "rate_limit"


@dataclass
class SafetyPolicy:
    """
    Safety policy configuration.
    
    Defines restrictions and requirements for operational actions.
    """
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    
    # Role restrictions
    role: str = "*"  # * = all roles
    
    # Scope restrictions
    max_scope: List[str] = field(default_factory=list)  # Allowed targets/environments
    denied_scope: List[str] = field(default_factory=list)  # Explicitly denied
    
    # Action restrictions
    allowed_actions: Set[str] = field(default_factory=set)  # Empty = all
    denied_actions: Set[str] = field(default_factory=set)
    
    # Approval requirements
    approval_required: bool = False
    approval_roles: Set[str] = field(default_factory=set)  # Who can approve
    min_approvers: int = 1
    
    # Rate limiting
    rate_limit_per_hour: int = 0  # 0 = unlimited
    cooldown_seconds: int = 0  # Seconds between same action
    
    # Time restrictions
    allowed_hours: Optional[List[int]] = None  # 0-23
    allowed_days: Optional[List[int]] = None  # 0-6 (Mon-Sun)
    
    # Environment restrictions
    allowed_environments: Set[str] = field(default_factory=lambda: {"development", "staging", "production"})
    production_extra_approval: bool = False
    
    # Priority (higher = evaluated first)
    priority: int = 0


@dataclass
class PolicyViolation:
    """Record of a policy violation."""
    policy_id: str
    policy_name: str
    action: PolicyAction
    reason: str
    user_id: str
    role: str
    command_type: str
    target: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyCheckResult:
    """Result of a policy check."""
    allowed: bool
    action: PolicyAction
    violations: List[PolicyViolation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    approval_required: bool = False
    required_approvers: int = 0
    cooldown_remaining: int = 0


class SafetyPolicyEngine:
    """
    Evaluates and enforces safety policies.
    
    Pipeline: Policy → Approval → Execution → Log
    """
    
    def __init__(self):
        self._policies: Dict[str, SafetyPolicy] = {}
        self._rate_tracking: Dict[str, List[float]] = {}  # user:action -> timestamps
        self._cooldown_tracking: Dict[str, float] = {}  # user:action -> last_execution
        
        # Register default policies
        self._register_default_policies()
    
    def add_policy(self, policy: SafetyPolicy):
        """Add or update a policy."""
        self._policies[policy.id] = policy
        logger.info(f"Added policy: {policy.name}")
    
    def remove_policy(self, policy_id: str):
        """Remove a policy."""
        self._policies.pop(policy_id, None)
    
    def get_policy(self, policy_id: str) -> Optional[SafetyPolicy]:
        """Get a policy by ID."""
        return self._policies.get(policy_id)
    
    def list_policies(self, role: Optional[str] = None) -> List[SafetyPolicy]:
        """List all policies, optionally filtered by role."""
        policies = list(self._policies.values())
        if role:
            policies = [p for p in policies if p.role == "*" or p.role == role]
        return sorted(policies, key=lambda p: -p.priority)
    
    def check(
        self,
        user_id: str,
        role: str,
        command_type: str,
        target: str,
        environment: str = "production",
    ) -> PolicyCheckResult:
        """
        Check if an action is allowed by policies.
        
        Args:
            user_id: User attempting the action
            role: User's role
            command_type: Type of command
            target: Target resource
            environment: Target environment
            
        Returns:
            PolicyCheckResult with decision and any violations
        """
        violations = []
        warnings = []
        approval_required = False
        required_approvers = 0
        cooldown_remaining = 0
        
        # Get applicable policies (sorted by priority)
        applicable = self._get_applicable_policies(role)
        
        for policy in applicable:
            if not policy.enabled:
                continue
            
            # Check denied actions
            if policy.denied_actions and command_type in policy.denied_actions:
                violations.append(PolicyViolation(
                    policy_id=policy.id,
                    policy_name=policy.name,
                    action=PolicyAction.DENY,
                    reason=f"Action {command_type} is explicitly denied",
                    user_id=user_id,
                    role=role,
                    command_type=command_type,
                    target=target,
                ))
                continue
            
            # Check allowed actions
            if policy.allowed_actions and command_type not in policy.allowed_actions:
                # Action-scoped policy is not applicable to this command
                continue
            
            # Check denied scope
            if policy.denied_scope:
                for denied in policy.denied_scope:
                    if denied in target:
                        violations.append(PolicyViolation(
                            policy_id=policy.id,
                            policy_name=policy.name,
                            action=PolicyAction.DENY,
                            reason=f"Target {target} is in denied scope",
                            user_id=user_id,
                            role=role,
                            command_type=command_type,
                            target=target,
                        ))
                        break
            
            # Check allowed scope
            if policy.max_scope:
                scope_allowed = any(allowed in target for allowed in policy.max_scope)
                if not scope_allowed:
                    violations.append(PolicyViolation(
                        policy_id=policy.id,
                        policy_name=policy.name,
                        action=PolicyAction.DENY,
                        reason=f"Target {target} is outside allowed scope",
                        user_id=user_id,
                        role=role,
                        command_type=command_type,
                        target=target,
                    ))
                    continue
            
            # Check environment
            if environment not in policy.allowed_environments:
                violations.append(PolicyViolation(
                    policy_id=policy.id,
                    policy_name=policy.name,
                    action=PolicyAction.DENY,
                    reason=f"Environment {environment} not allowed",
                    user_id=user_id,
                    role=role,
                    command_type=command_type,
                    target=target,
                ))
                continue
            
            # Check time restrictions
            if not self._check_time_restrictions(policy):
                violations.append(PolicyViolation(
                    policy_id=policy.id,
                    policy_name=policy.name,
                    action=PolicyAction.DENY,
                    reason="Action not allowed at current time",
                    user_id=user_id,
                    role=role,
                    command_type=command_type,
                    target=target,
                ))
                continue
            
            # Check rate limit
            if policy.rate_limit_per_hour > 0:
                rate_key = f"{user_id}:{command_type}"
                if not self._check_rate_limit(rate_key, policy.rate_limit_per_hour):
                    violations.append(PolicyViolation(
                        policy_id=policy.id,
                        policy_name=policy.name,
                        action=PolicyAction.RATE_LIMIT,
                        reason=f"Rate limit exceeded ({policy.rate_limit_per_hour}/hour)",
                        user_id=user_id,
                        role=role,
                        command_type=command_type,
                        target=target,
                    ))
                    continue
            
            # Check cooldown
            if policy.cooldown_seconds > 0:
                cooldown_key = f"{user_id}:{command_type}"
                remaining = self._check_cooldown(cooldown_key, policy.cooldown_seconds)
                if remaining > 0:
                    cooldown_remaining = max(cooldown_remaining, remaining)
                    warnings.append(f"Cooldown active: {remaining}s remaining")
            
            # Check approval requirement
            if policy.approval_required:
                approval_required = True
                required_approvers = max(required_approvers, policy.min_approvers)
            
            # Extra approval for production
            if environment == "production" and policy.production_extra_approval:
                approval_required = True
                required_approvers = max(required_approvers, 2)
        
        # Determine final result
        has_blocking_violations = any(
            v.action == PolicyAction.DENY for v in violations
        )
        
        if has_blocking_violations:
            return PolicyCheckResult(
                allowed=False,
                action=PolicyAction.DENY,
                violations=violations,
                warnings=warnings,
            )
        
        if cooldown_remaining > 0:
            return PolicyCheckResult(
                allowed=False,
                action=PolicyAction.RATE_LIMIT,
                violations=violations,
                warnings=warnings,
                cooldown_remaining=cooldown_remaining,
            )
        
        if approval_required:
            return PolicyCheckResult(
                allowed=True,
                action=PolicyAction.REQUIRE_APPROVAL,
                violations=violations,
                warnings=warnings,
                approval_required=True,
                required_approvers=required_approvers,
            )
        
        return PolicyCheckResult(
            allowed=True,
            action=PolicyAction.ALLOW,
            violations=violations,
            warnings=warnings,
        )
    
    def record_execution(self, user_id: str, command_type: str):
        """Record a command execution for rate limiting and cooldown."""
        key = f"{user_id}:{command_type}"
        now = time.time()
        
        # Update rate tracking
        if key not in self._rate_tracking:
            self._rate_tracking[key] = []
        self._rate_tracking[key].append(now)
        # Keep only last hour
        self._rate_tracking[key] = [
            ts for ts in self._rate_tracking[key]
            if now - ts < 3600
        ]
        
        # Update cooldown tracking
        self._cooldown_tracking[key] = now
    
    def _get_applicable_policies(self, role: str) -> List[SafetyPolicy]:
        """Get policies applicable to a role."""
        applicable = []
        for policy in self._policies.values():
            if policy.role == "*" or policy.role == role:
                applicable.append(policy)
        return sorted(applicable, key=lambda p: -p.priority)
    
    def _check_time_restrictions(self, policy: SafetyPolicy) -> bool:
        """Check if current time is within allowed time window."""
        now = datetime.utcnow()
        
        if policy.allowed_hours is not None:
            if now.hour not in policy.allowed_hours:
                return False
        
        if policy.allowed_days is not None:
            if now.weekday() not in policy.allowed_days:
                return False
        
        return True
    
    def _check_rate_limit(self, key: str, limit: int) -> bool:
        """Check if within rate limit."""
        if key not in self._rate_tracking:
            return True
        
        now = time.time()
        recent = [ts for ts in self._rate_tracking[key] if now - ts < 3600]
        return len(recent) < limit
    
    def _check_cooldown(self, key: str, cooldown_seconds: int) -> int:
        """Check cooldown and return remaining seconds (0 if clear)."""
        if key not in self._cooldown_tracking:
            return 0
        
        elapsed = time.time() - self._cooldown_tracking[key]
        remaining = cooldown_seconds - elapsed
        return max(0, int(remaining))
    
    def _register_default_policies(self):
        """Register default safety policies."""
        # Production crawler kill requires approval
        self.add_policy(SafetyPolicy(
            id="prod_crawler_kill",
            name="Production Crawler Kill Approval",
            description="Killing production crawlers requires approval",
            role="*",
            allowed_actions={"crawler_kill"},
            approval_required=True,
            approval_roles={"admin", "ops_lead"},
            min_approvers=1,
            allowed_environments={"production"},
            priority=100,
        ))
        
        # Model freeze requires approval
        self.add_policy(SafetyPolicy(
            id="model_freeze",
            name="Model Freeze Approval",
            description="Freezing models requires approval",
            role="*",
            allowed_actions={"mlops_freeze"},
            approval_required=True,
            approval_roles={"admin", "ml_lead"},
            min_approvers=1,
            priority=100,
        ))
        
        # KB rollback requires approval
        self.add_policy(SafetyPolicy(
            id="kb_rollback",
            name="KB Rollback Approval",
            description="Knowledge base rollback requires approval",
            role="*",
            allowed_actions={"kb_rollback"},
            approval_required=True,
            approval_roles={"admin"},
            min_approvers=1,
            production_extra_approval=True,
            priority=100,
        ))
        
        # Dev job controls - no approval needed
        self.add_policy(SafetyPolicy(
            id="dev_job_controls",
            name="Dev Job Controls",
            description="Job controls in dev environment",
            role="*",
            allowed_actions={"job_pause", "job_resume"},
            allowed_environments={"development", "staging", "production"},
            approval_required=False,
            priority=50,
        ))
        
        # Rate limit for retrain
        self.add_policy(SafetyPolicy(
            id="retrain_rate_limit",
            name="Retrain Rate Limit",
            description="Limit retraining frequency",
            role="*",
            allowed_actions={"mlops_retrain"},
            rate_limit_per_hour=5,
            cooldown_seconds=300,
            priority=50,
        ))
        
        # Viewer role - read only
        self.add_policy(SafetyPolicy(
            id="viewer_restrictions",
            name="Viewer Restrictions",
            description="Viewers cannot execute commands",
            role="viewer",
            denied_actions={
                "crawler_kill", "crawler_stop",
                "job_pause", "job_resume", "job_cancel",
                "kb_rollback", "kb_rebuild",
                "mlops_freeze", "mlops_retrain", "mlops_rollback",
                "system_backup", "system_restore",
            },
            priority=200,
        ))

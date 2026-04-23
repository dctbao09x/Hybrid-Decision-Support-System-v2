# backend/ops/cost/enforcement.py
"""
Cost Enforcement Engine
=======================

Automated cost control with:
- Threshold-based enforcement
- Auto throttle / degrade / shutdown
- Multi-level escalation
- Safe mode triggers
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from backend.ops.cost.models import (
    AlertLevel,
    BudgetDefinition,
    BudgetScope,
    BudgetStatus,
    BudgetThreshold,
    EnforcementAction,
    LimitType,
)
from backend.ops.cost.budget_manager import BudgetManager, get_budget_manager

logger = logging.getLogger("ops.cost.enforcement")


class ThrottleLevel(str, Enum):
    """Throttle intensity levels."""
    NONE = "none"
    LIGHT = "light"       # 75% throughput
    MODERATE = "moderate" # 50% throughput
    HEAVY = "heavy"       # 25% throughput
    BLOCKED = "blocked"   # 0% throughput


class DegradeLevel(str, Enum):
    """Service degradation levels."""
    NONE = "none"
    CACHE_ONLY = "cache_only"           # Use cached responses only
    REDUCED_QUALITY = "reduced_quality" # Use cheaper models
    MINIMAL = "minimal"                 # Bare minimum functionality
    OFFLINE = "offline"                 # Service unavailable


@dataclass
class EnforcementState:
    """Current enforcement state for a budget."""
    budget_id: str
    is_enforced: bool = False
    throttle_level: ThrottleLevel = ThrottleLevel.NONE
    degrade_level: DegradeLevel = DegradeLevel.NONE
    is_shutdown: bool = False
    reason: str = ""
    enforced_at: Optional[str] = None
    alert_level: Optional[AlertLevel] = None
    utilization: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "budget_id": self.budget_id,
            "is_enforced": self.is_enforced,
            "throttle_level": self.throttle_level.value,
            "degrade_level": self.degrade_level.value,
            "is_shutdown": self.is_shutdown,
            "reason": self.reason,
            "enforced_at": self.enforced_at,
            "alert_level": self.alert_level.value if self.alert_level else None,
            "utilization": round(self.utilization * 100, 2),
        }


@dataclass
class EnforcementEvent:
    """Record of an enforcement action."""
    event_id: str
    budget_id: str
    action: EnforcementAction
    alert_level: AlertLevel
    utilization: float
    throttle_level: Optional[ThrottleLevel] = None
    degrade_level: Optional[DegradeLevel] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved: bool = False
    resolved_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "budget_id": self.budget_id,
            "action": self.action.value,
            "alert_level": self.alert_level.value,
            "utilization": round(self.utilization * 100, 2),
            "throttle_level": self.throttle_level.value if self.throttle_level else None,
            "degrade_level": self.degrade_level.value if self.degrade_level else None,
            "timestamp": self.timestamp,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at,
        }


class CostEnforcementEngine:
    """
    Automated cost enforcement engine.
    
    Features:
    - Real-time budget monitoring
    - Automatic throttling
    - Service degradation
    - Emergency shutdown
    - Alert escalation
    """
    
    def __init__(
        self,
        budget_manager: Optional[BudgetManager] = None,
        check_interval_seconds: int = 60,
    ):
        self._manager = budget_manager or get_budget_manager()
        self._check_interval = check_interval_seconds
        self._lock = RLock()
        
        # Current enforcement states
        self._states: Dict[str, EnforcementState] = {}
        
        # Event history
        self._events: List[EnforcementEvent] = []
        
        # Callbacks
        self._on_throttle: List[Callable[[str, ThrottleLevel], None]] = []
        self._on_degrade: List[Callable[[str, DegradeLevel], None]] = []
        self._on_shutdown: List[Callable[[str], None]] = []
        self._on_alert: List[Callable[[str, AlertLevel, float], None]] = []
        
        # Services currently blocked
        self._blocked_services: Set[str] = set()
        
        # Cooldown tracking (prevent alert spam)
        self._last_alert: Dict[str, datetime] = {}
        self._alert_cooldown = timedelta(minutes=15)
        
        # Running state
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    # ═══════════════════════════════════════════════════════════════════
    # Callback Registration
    # ═══════════════════════════════════════════════════════════════════
    
    def on_throttle(self, callback: Callable[[str, ThrottleLevel], None]) -> None:
        """Register callback for throttle events."""
        self._on_throttle.append(callback)
    
    def on_degrade(self, callback: Callable[[str, DegradeLevel], None]) -> None:
        """Register callback for degradation events."""
        self._on_degrade.append(callback)
    
    def on_shutdown(self, callback: Callable[[str], None]) -> None:
        """Register callback for shutdown events."""
        self._on_shutdown.append(callback)
    
    def on_alert(self, callback: Callable[[str, AlertLevel, float], None]) -> None:
        """Register callback for alerts."""
        self._on_alert.append(callback)
    
    # ═══════════════════════════════════════════════════════════════════
    # State Management
    # ═══════════════════════════════════════════════════════════════════
    
    def get_state(self, budget_id: str) -> EnforcementState:
        """Get current enforcement state for a budget."""
        if budget_id not in self._states:
            self._states[budget_id] = EnforcementState(budget_id=budget_id)
        return self._states[budget_id]
    
    def get_all_states(self) -> List[EnforcementState]:
        """Get all enforcement states."""
        return list(self._states.values())
    
    def is_service_blocked(self, service: str) -> bool:
        """Check if a service is currently blocked."""
        return service in self._blocked_services
    
    def get_throttle_level(self, service: str) -> ThrottleLevel:
        """Get current throttle level for a service."""
        # Check all budgets that apply to this service
        budgets = self._manager.list_budgets(scope=BudgetScope.SERVICE, scope_id=service)
        
        max_throttle = ThrottleLevel.NONE
        for budget in budgets:
            state = self.get_state(budget.budget_id)
            if state.throttle_level.value > max_throttle.value:
                max_throttle = state.throttle_level
        
        return max_throttle
    
    def get_degrade_level(self, service: str) -> DegradeLevel:
        """Get current degradation level for a service."""
        budgets = self._manager.list_budgets(scope=BudgetScope.SERVICE, scope_id=service)
        
        max_degrade = DegradeLevel.NONE
        for budget in budgets:
            state = self.get_state(budget.budget_id)
            if state.degrade_level.value > max_degrade.value:
                max_degrade = state.degrade_level
        
        return max_degrade
    
    # ═══════════════════════════════════════════════════════════════════
    # Enforcement Logic
    # ═══════════════════════════════════════════════════════════════════
    
    async def check_and_enforce(self) -> List[EnforcementEvent]:
        """Check all budgets and enforce as needed."""
        events: List[EnforcementEvent] = []
        
        for status in self._manager.get_all_budget_statuses():
            budget = self._manager.get_budget(status.budget_id)
            if not budget:
                continue
            
            event = await self._evaluate_budget(budget, status)
            if event:
                events.append(event)
        
        return events
    
    async def _evaluate_budget(
        self,
        budget: BudgetDefinition,
        status: BudgetStatus,
    ) -> Optional[EnforcementEvent]:
        """Evaluate a single budget and take action if needed."""
        state = self.get_state(budget.budget_id)
        utilization = status.utilization_percentage
        
        # Find applicable threshold
        applicable_threshold: Optional[BudgetThreshold] = None
        for threshold in sorted(budget.thresholds, key=lambda t: t.percentage, reverse=True):
            if utilization >= threshold.percentage:
                applicable_threshold = threshold
                break
        
        if not applicable_threshold:
            # Under all thresholds - clear any enforcement
            if state.is_enforced:
                return self._clear_enforcement(budget, status)
            return None
        
        # Check cooldown
        if self._in_cooldown(budget.budget_id, applicable_threshold.alert_level):
            return None
        
        # Take action based on threshold
        event = await self._take_action(budget, status, applicable_threshold)
        
        if event:
            self._events.append(event)
            self._last_alert[budget.budget_id] = datetime.now(timezone.utc)
            self._manager.record_alert(
                budget.budget_id,
                applicable_threshold.alert_level,
                utilization,
                applicable_threshold.action,
            )
        
        return event
    
    async def _take_action(
        self,
        budget: BudgetDefinition,
        status: BudgetStatus,
        threshold: BudgetThreshold,
    ) -> Optional[EnforcementEvent]:
        """Execute enforcement action."""
        state = self.get_state(budget.budget_id)
        utilization = status.utilization_percentage
        
        event_id = f"enf_{budget.budget_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        
        event = EnforcementEvent(
            event_id=event_id,
            budget_id=budget.budget_id,
            action=threshold.action,
            alert_level=threshold.alert_level,
            utilization=utilization,
        )
        
        # Update state
        state.is_enforced = True
        state.alert_level = threshold.alert_level
        state.utilization = utilization
        state.enforced_at = datetime.now(timezone.utc).isoformat()
        
        if threshold.action == EnforcementAction.NOTIFY:
            state.reason = f"Budget utilization at {utilization*100:.1f}%"
            self._fire_alerts(budget.budget_id, threshold.alert_level, utilization)
        
        elif threshold.action == EnforcementAction.THROTTLE:
            # Determine throttle level
            if utilization >= 0.95:
                throttle = ThrottleLevel.HEAVY
            elif utilization >= 0.85:
                throttle = ThrottleLevel.MODERATE
            else:
                throttle = ThrottleLevel.LIGHT
            
            state.throttle_level = throttle
            state.reason = f"Throttled to {throttle.value} due to {utilization*100:.1f}% utilization"
            event.throttle_level = throttle
            
            self._fire_throttle(budget.budget_id, throttle)
            self._fire_alerts(budget.budget_id, threshold.alert_level, utilization)
            logger.warning(f"Budget {budget.budget_id} throttled: {throttle.value}")
        
        elif threshold.action == EnforcementAction.DEGRADE:
            # Determine degradation level
            if utilization >= 0.95:
                degrade = DegradeLevel.MINIMAL
            elif utilization >= 0.90:
                degrade = DegradeLevel.REDUCED_QUALITY
            else:
                degrade = DegradeLevel.CACHE_ONLY
            
            state.degrade_level = degrade
            state.reason = f"Degraded to {degrade.value} due to {utilization*100:.1f}% utilization"
            event.degrade_level = degrade
            
            self._fire_degrade(budget.budget_id, degrade)
            self._fire_alerts(budget.budget_id, threshold.alert_level, utilization)
            logger.warning(f"Budget {budget.budget_id} degraded: {degrade.value}")
        
        elif threshold.action == EnforcementAction.SHUTDOWN:
            if budget.limit_type == LimitType.HARD:
                state.is_shutdown = True
                state.reason = f"SHUTDOWN: Hard limit exceeded at {utilization*100:.1f}%"
                
                # Block service
                if budget.scope == BudgetScope.SERVICE:
                    self._blocked_services.add(budget.scope_id)
                
                self._fire_shutdown(budget.budget_id)
                self._fire_alerts(budget.budget_id, threshold.alert_level, utilization)
                logger.critical(f"Budget {budget.budget_id} triggered SHUTDOWN")
            else:
                # Soft limit - escalate instead
                state.reason = f"Soft limit exceeded at {utilization*100:.1f}% - escalating"
                event.action = EnforcementAction.ESCALATE
                self._fire_alerts(budget.budget_id, threshold.alert_level, utilization)
        
        elif threshold.action == EnforcementAction.ESCALATE:
            state.reason = f"Escalation triggered at {utilization*100:.1f}%"
            self._fire_alerts(budget.budget_id, AlertLevel.EMERGENCY, utilization)
        
        return event
    
    def _clear_enforcement(
        self,
        budget: BudgetDefinition,
        status: BudgetStatus,
    ) -> EnforcementEvent:
        """Clear enforcement when budget returns to normal."""
        state = self.get_state(budget.budget_id)
        
        # Record resolution
        event = EnforcementEvent(
            event_id=f"clear_{budget.budget_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            budget_id=budget.budget_id,
            action=EnforcementAction.NOTIFY,
            alert_level=AlertLevel.INFO,
            utilization=status.utilization_percentage,
            resolved=True,
            resolved_at=datetime.now(timezone.utc).isoformat(),
        )
        
        # Reset state
        state.is_enforced = False
        state.throttle_level = ThrottleLevel.NONE
        state.degrade_level = DegradeLevel.NONE
        state.is_shutdown = False
        state.reason = ""
        state.alert_level = None
        
        # Unblock service
        if budget.scope == BudgetScope.SERVICE:
            self._blocked_services.discard(budget.scope_id)
        
        logger.info(f"Enforcement cleared for budget {budget.budget_id}")
        return event
    
    def _in_cooldown(self, budget_id: str, alert_level: AlertLevel) -> bool:
        """Check if alert is in cooldown period."""
        if budget_id not in self._last_alert:
            return False
        
        # Emergency alerts bypass cooldown
        if alert_level == AlertLevel.EMERGENCY:
            return False
        
        elapsed = datetime.now(timezone.utc) - self._last_alert[budget_id]
        return elapsed < self._alert_cooldown
    
    # ═══════════════════════════════════════════════════════════════════
    # Callback Firing
    # ═══════════════════════════════════════════════════════════════════
    
    def _fire_throttle(self, budget_id: str, level: ThrottleLevel) -> None:
        for callback in self._on_throttle:
            try:
                callback(budget_id, level)
            except Exception as e:
                logger.error(f"Throttle callback error: {e}")
    
    def _fire_degrade(self, budget_id: str, level: DegradeLevel) -> None:
        for callback in self._on_degrade:
            try:
                callback(budget_id, level)
            except Exception as e:
                logger.error(f"Degrade callback error: {e}")
    
    def _fire_shutdown(self, budget_id: str) -> None:
        for callback in self._on_shutdown:
            try:
                callback(budget_id)
            except Exception as e:
                logger.error(f"Shutdown callback error: {e}")
    
    def _fire_alerts(self, budget_id: str, level: AlertLevel, utilization: float) -> None:
        for callback in self._on_alert:
            try:
                callback(budget_id, level, utilization)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")
    
    # ═══════════════════════════════════════════════════════════════════
    # Request Gating
    # ═══════════════════════════════════════════════════════════════════
    
    def can_process_request(
        self,
        service: str,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Check if a request can be processed given current budget state.
        
        Returns:
            (can_proceed, reason)
        """
        # Check service-level blocks
        if service in self._blocked_services:
            return False, f"Service {service} is blocked due to budget limits"
        
        # Check throttle level
        throttle = self.get_throttle_level(service)
        if throttle == ThrottleLevel.BLOCKED:
            return False, f"Service {service} is throttled (blocked)"
        
        # For other throttle levels, implement probabilistic gating
        if throttle == ThrottleLevel.HEAVY:
            import random
            if random.random() > 0.25:
                return False, f"Service {service} is heavily throttled (75% rejection)"
        elif throttle == ThrottleLevel.MODERATE:
            import random
            if random.random() > 0.50:
                return False, f"Service {service} is moderately throttled (50% rejection)"
        elif throttle == ThrottleLevel.LIGHT:
            import random
            if random.random() > 0.75:
                return False, f"Service {service} is lightly throttled (25% rejection)"
        
        return True, "OK"
    
    # ═══════════════════════════════════════════════════════════════════
    # Event History
    # ═══════════════════════════════════════════════════════════════════
    
    def get_events(self, limit: int = 100) -> List[EnforcementEvent]:
        """Get recent enforcement events."""
        return sorted(self._events, key=lambda e: e.timestamp, reverse=True)[:limit]
    
    # ═══════════════════════════════════════════════════════════════════
    # Background Runner
    # ═══════════════════════════════════════════════════════════════════
    
    async def start(self) -> None:
        """Start background enforcement loop."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Cost enforcement engine started")
    
    async def stop(self) -> None:
        """Stop background enforcement loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Cost enforcement engine stopped")
    
    async def _run_loop(self) -> None:
        """Background enforcement loop."""
        while self._running:
            try:
                await self.check_and_enforce()
            except Exception as e:
                logger.error(f"Enforcement check error: {e}")
            
            await asyncio.sleep(self._check_interval)


# ═══════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════

_enforcement_engine: Optional[CostEnforcementEngine] = None


def get_enforcement_engine() -> CostEnforcementEngine:
    """Get singleton CostEnforcementEngine instance."""
    global _enforcement_engine
    if _enforcement_engine is None:
        _enforcement_engine = CostEnforcementEngine()
    return _enforcement_engine

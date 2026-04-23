# backend/ops/killswitch/controller.py
"""
Kill-Switch Controller
======================

Emergency control system for AI operations:
- Global kill-switch
- Service-level kill-switches
- Model-level kill-switches
- Safe mode operations
- Auto-trigger conditions
- Multi-approval workflow
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Set

from backend.state import StatePolicy, get_operational_state_store

logger = logging.getLogger("ops.killswitch")


class KillSwitchState(str, Enum):
    """Kill-switch states."""
    ACTIVE = "active"           # Normal operation
    SAFE_MODE = "safe_mode"     # Degraded safe mode
    KILLED = "killed"           # Completely stopped


class SafeModeLevel(str, Enum):
    """Safe mode operation levels."""
    NONE = "none"               # Normal operation
    CACHE_ONLY = "cache_only"   # Use cached responses only
    RULE_ONLY = "rule_only"     # Use rule-based decisions only
    STATIC = "static"           # Return static fallback responses
    OFFLINE = "offline"         # Service unavailable


class KillScope(str, Enum):
    """Scope of kill-switch activation."""
    GLOBAL = "global"           # All services
    SERVICE = "service"         # Specific service
    MODEL = "model"             # Specific model
    ENDPOINT = "endpoint"       # Specific API endpoint


class TriggerCondition(str, Enum):
    """Auto-trigger conditions."""
    DRIFT_THRESHOLD = "drift_threshold"
    ERROR_RATE = "error_rate"
    LATENCY = "latency"
    COST_OVERRUN = "cost_overrun"
    LEGAL_RISK = "legal_risk"
    SECURITY_BREACH = "security_breach"
    MANUAL = "manual"


@dataclass
class KillSwitchEvent:
    """Record of kill-switch activation/deactivation."""
    event_id: str
    timestamp: str
    action: str                    # kill, safe_mode, resume
    scope: KillScope
    scope_id: str
    reason: str
    trigger: TriggerCondition
    actor: str
    previous_state: KillSwitchState
    new_state: KillSwitchState
    safe_mode_level: Optional[SafeModeLevel] = None
    requires_approval: bool = False
    approved_by: List[str] = field(default_factory=list)
    auto_triggered: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "action": self.action,
            "scope": self.scope.value,
            "scope_id": self.scope_id,
            "reason": self.reason,
            "trigger": self.trigger.value,
            "actor": self.actor,
            "previous_state": self.previous_state.value,
            "new_state": self.new_state.value,
            "safe_mode_level": self.safe_mode_level.value if self.safe_mode_level else None,
            "requires_approval": self.requires_approval,
            "approved_by": self.approved_by,
            "auto_triggered": self.auto_triggered,
        }


@dataclass
class AutoTriggerRule:
    """Auto-trigger rule configuration."""
    rule_id: str
    name: str
    condition: TriggerCondition
    threshold: float
    scope: KillScope
    scope_id: str
    action: str                    # kill, safe_mode
    safe_mode_level: Optional[SafeModeLevel] = None
    cooldown_minutes: int = 60
    enabled: bool = True
    requires_approval: bool = False
    min_approvals: int = 1
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "condition": self.condition.value,
            "threshold": self.threshold,
            "scope": self.scope.value,
            "scope_id": self.scope_id,
            "action": self.action,
            "safe_mode_level": self.safe_mode_level.value if self.safe_mode_level else None,
            "cooldown_minutes": self.cooldown_minutes,
            "enabled": self.enabled,
            "requires_approval": self.requires_approval,
            "min_approvals": self.min_approvals,
        }


@dataclass
class ApprovalRequest:
    """Multi-approval request for kill-switch activation."""
    request_id: str
    event_id: str
    scope: KillScope
    scope_id: str
    action: str
    reason: str
    requested_by: str
    requested_at: str
    min_approvals: int
    current_approvals: List[str] = field(default_factory=list)
    rejections: List[str] = field(default_factory=list)
    status: str = "pending"        # pending, approved, rejected, expired
    expires_at: str = ""
    
    @property
    def is_approved(self) -> bool:
        return len(self.current_approvals) >= self.min_approvals
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "event_id": self.event_id,
            "scope": self.scope.value,
            "scope_id": self.scope_id,
            "action": self.action,
            "reason": self.reason,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "min_approvals": self.min_approvals,
            "current_approvals": self.current_approvals,
            "rejections": self.rejections,
            "status": self.status,
            "expires_at": self.expires_at,
            "is_approved": self.is_approved,
        }


class KillSwitchController:
    """
    Central kill-switch controller.
    
    Features:
    - Global, service, model, endpoint kill-switches
    - Safe mode operations
    - Multi-approval workflow
    - Auto-trigger rules
    - Audit trail
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self._root = Path(__file__).resolve().parents[3]
        self._db_path = db_path or self._root / "storage/ops/killswitch.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._op_state = get_operational_state_store()
        self._op_namespace = "killswitch"
        self._op_policy = StatePolicy(ttl_seconds=None, persistent=True, stale_after_seconds=3600)
        
        # Callbacks
        self._on_kill: List[Callable[[str, KillScope], None]] = []
        self._on_safe_mode: List[Callable[[str, SafeModeLevel], None]] = []
        self._on_resume: List[Callable[[str], None]] = []
        
        self._init_db()
        self._load_state()
        self._init_default_rules()

    def _state_lock(self, name: str = "core"):
        return self._op_state.lock(
            name=f"killswitch:{name}",
            ttl_seconds=15.0,
            wait_timeout_seconds=3.0,
            retry_interval_seconds=0.05,
        )

    def _get_map(self, key: str) -> Dict[str, Any]:
        data = self._op_state.get_json(
            namespace=self._op_namespace,
            state_key=key,
            default={},
            policy=self._op_policy,
        )
        if isinstance(data, dict):
            return data
        return {}

    def _set_map(self, key: str, value: Dict[str, Any]) -> None:
        self._op_state.set_json(
            namespace=self._op_namespace,
            state_key=key,
            value=value,
            policy=self._op_policy,
        )

    def _state_map(self) -> Dict[str, str]:
        data = self._get_map("states")
        return {str(k): str(v) for k, v in data.items()}

    def _safe_mode_map(self) -> Dict[str, str]:
        data = self._get_map("safe_mode_levels")
        return {str(k): str(v) for k, v in data.items()}

    def _rules_map(self) -> Dict[str, Dict[str, Any]]:
        data = self._get_map("rules")
        return {
            str(k): v
            for k, v in data.items()
            if isinstance(v, dict)
        }

    def _approvals_map(self) -> Dict[str, Dict[str, Any]]:
        data = self._get_map("approvals")
        return {
            str(k): v
            for k, v in data.items()
            if isinstance(v, dict)
        }

    def _last_trigger_map(self) -> Dict[str, str]:
        data = self._get_map("last_trigger")
        return {str(k): str(v) for k, v in data.items()}

    @staticmethod
    def _rule_from_dict(data: Dict[str, Any]) -> Optional[AutoTriggerRule]:
        try:
            safe_mode = data.get("safe_mode_level")
            return AutoTriggerRule(
                rule_id=str(data.get("rule_id")),
                name=str(data.get("name")),
                condition=TriggerCondition(str(data.get("condition"))),
                threshold=float(data.get("threshold", 0.0)),
                scope=KillScope(str(data.get("scope"))),
                scope_id=str(data.get("scope_id", "*")),
                action=str(data.get("action", "safe_mode")),
                safe_mode_level=SafeModeLevel(str(safe_mode)) if safe_mode else None,
                cooldown_minutes=int(data.get("cooldown_minutes", 60)),
                enabled=bool(data.get("enabled", True)),
                requires_approval=bool(data.get("requires_approval", False)),
                min_approvals=int(data.get("min_approvals", 1)),
            )
        except Exception:
            logger.warning("invalid auto-trigger rule payload: %s", data)
            return None

    @staticmethod
    def _approval_from_dict(data: Dict[str, Any]) -> Optional[ApprovalRequest]:
        try:
            return ApprovalRequest(
                request_id=str(data.get("request_id")),
                event_id=str(data.get("event_id", "")),
                scope=KillScope(str(data.get("scope"))),
                scope_id=str(data.get("scope_id", "*")),
                action=str(data.get("action", "kill")),
                reason=str(data.get("reason", "")),
                requested_by=str(data.get("requested_by", "")),
                requested_at=str(data.get("requested_at", "")),
                min_approvals=int(data.get("min_approvals", 1)),
                current_approvals=[str(v) for v in data.get("current_approvals", [])],
                rejections=[str(v) for v in data.get("rejections", [])],
                status=str(data.get("status", "pending")),
                expires_at=str(data.get("expires_at", "")),
            )
        except Exception:
            logger.warning("invalid approval payload: %s", data)
            return None
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS killswitch_state (
                    scope_key TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    safe_mode_level TEXT,
                    updated_at TEXT NOT NULL,
                    reason TEXT
                );
                
                CREATE TABLE IF NOT EXISTS killswitch_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    reason TEXT,
                    trigger_condition TEXT,
                    actor TEXT,
                    previous_state TEXT,
                    new_state TEXT,
                    safe_mode_level TEXT,
                    auto_triggered INTEGER DEFAULT 0,
                    approved_by TEXT
                );
                
                CREATE TABLE IF NOT EXISTS auto_trigger_rules (
                    rule_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    condition TEXT NOT NULL,
                    threshold REAL NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    safe_mode_level TEXT,
                    cooldown_minutes INTEGER DEFAULT 60,
                    enabled INTEGER DEFAULT 1,
                    requires_approval INTEGER DEFAULT 0,
                    min_approvals INTEGER DEFAULT 1
                );
                
                CREATE TABLE IF NOT EXISTS approval_requests (
                    request_id TEXT PRIMARY KEY,
                    event_id TEXT,
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT,
                    requested_by TEXT,
                    requested_at TEXT,
                    min_approvals INTEGER DEFAULT 1,
                    current_approvals TEXT,
                    rejections TEXT,
                    status TEXT DEFAULT 'pending',
                    expires_at TEXT
                );
                
                CREATE INDEX IF NOT EXISTS idx_events_timestamp ON killswitch_events(timestamp);
            """)
    
    def _load_state(self) -> None:
        """Load state from database."""
        if self._state_map() or self._safe_mode_map():
            return

        states: Dict[str, str] = {}
        safe_modes: Dict[str, str] = {}
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM killswitch_state").fetchall()
            
            for row in rows:
                states[str(row["scope_key"])] = str(row["state"])
                if row["safe_mode_level"]:
                    safe_modes[str(row["scope_key"])] = str(row["safe_mode_level"])

        if states:
            self._set_map("states", states)
        if safe_modes:
            self._set_map("safe_mode_levels", safe_modes)
    
    def _init_default_rules(self) -> None:
        """Initialize default auto-trigger rules."""
        existing = self._rules_map()
        default_rules = [
            AutoTriggerRule(
                rule_id="rule_drift_critical",
                name="Critical Drift Auto-Kill",
                condition=TriggerCondition.DRIFT_THRESHOLD,
                threshold=0.8,
                scope=KillScope.MODEL,
                scope_id="*",
                action="safe_mode",
                safe_mode_level=SafeModeLevel.CACHE_ONLY,
                cooldown_minutes=120,
            ),
            AutoTriggerRule(
                rule_id="rule_error_rate",
                name="High Error Rate Auto-Kill",
                condition=TriggerCondition.ERROR_RATE,
                threshold=0.15,
                scope=KillScope.SERVICE,
                scope_id="inference",
                action="safe_mode",
                safe_mode_level=SafeModeLevel.RULE_ONLY,
                cooldown_minutes=60,
            ),
            AutoTriggerRule(
                rule_id="rule_cost_emergency",
                name="Cost Emergency Kill",
                condition=TriggerCondition.COST_OVERRUN,
                threshold=0.95,
                scope=KillScope.GLOBAL,
                scope_id="*",
                action="safe_mode",
                safe_mode_level=SafeModeLevel.STATIC,
                cooldown_minutes=30,
                requires_approval=True,
                min_approvals=2,
            ),
            AutoTriggerRule(
                rule_id="rule_security",
                name="Security Breach Kill",
                condition=TriggerCondition.SECURITY_BREACH,
                threshold=1.0,
                scope=KillScope.GLOBAL,
                scope_id="*",
                action="kill",
                cooldown_minutes=0,
            ),
        ]
        
        for rule in default_rules:
            if rule.rule_id not in existing:
                self.add_rule(rule)
    
    # ═══════════════════════════════════════════════════════════════════
    # Callback Registration
    # ═══════════════════════════════════════════════════════════════════
    
    def on_kill(self, callback: Callable[[str, KillScope], None]) -> None:
        """Register callback for kill events."""
        self._on_kill.append(callback)
    
    def on_safe_mode(self, callback: Callable[[str, SafeModeLevel], None]) -> None:
        """Register callback for safe mode events."""
        self._on_safe_mode.append(callback)
    
    def on_resume(self, callback: Callable[[str], None]) -> None:
        """Register callback for resume events."""
        self._on_resume.append(callback)
    
    # ═══════════════════════════════════════════════════════════════════
    # State Queries
    # ═══════════════════════════════════════════════════════════════════
    
    def _scope_key(self, scope: KillScope, scope_id: str) -> str:
        """Generate scope key for state lookup."""
        return f"{scope.value}:{scope_id}"
    
    def get_state(self, scope: KillScope, scope_id: str) -> KillSwitchState:
        """Get current state for a scope."""
        key = self._scope_key(scope, scope_id)
        states = self._state_map()
        
        # Check specific state
        if key in states:
            try:
                return KillSwitchState(states[key])
            except Exception:
                pass
        
        # Check global state
        global_key = self._scope_key(KillScope.GLOBAL, "*")
        if global_key in states:
            try:
                return KillSwitchState(states[global_key])
            except Exception:
                pass
        
        return KillSwitchState.ACTIVE
    
    def get_safe_mode_level(self, scope: KillScope, scope_id: str) -> SafeModeLevel:
        """Get safe mode level for a scope."""
        key = self._scope_key(scope, scope_id)
        safe_modes = self._safe_mode_map()
        
        if key in safe_modes:
            try:
                return SafeModeLevel(safe_modes[key])
            except Exception:
                pass
        
        # Check global
        global_key = self._scope_key(KillScope.GLOBAL, "*")
        if global_key in safe_modes:
            try:
                return SafeModeLevel(safe_modes[global_key])
            except Exception:
                pass
        
        return SafeModeLevel.NONE
    
    def is_killed(self, scope: KillScope = KillScope.GLOBAL, scope_id: str = "*") -> bool:
        """Check if scope is killed."""
        return self.get_state(scope, scope_id) == KillSwitchState.KILLED
    
    def is_safe_mode(self, scope: KillScope = KillScope.GLOBAL, scope_id: str = "*") -> bool:
        """Check if scope is in safe mode."""
        return self.get_state(scope, scope_id) == KillSwitchState.SAFE_MODE
    
    def can_process(
        self,
        service: str,
        model_id: Optional[str] = None,
        endpoint: Optional[str] = None,
    ) -> tuple[bool, str, SafeModeLevel]:
        """
        Check if a request can be processed.
        
        Returns:
            (can_proceed, reason, safe_mode_level)
        """
        # Check global kill
        if self.is_killed(KillScope.GLOBAL, "*"):
            return False, "Global kill-switch active", SafeModeLevel.OFFLINE
        
        # Check service kill
        if self.is_killed(KillScope.SERVICE, service):
            return False, f"Service {service} killed", SafeModeLevel.OFFLINE
        
        # Check model kill
        if model_id and self.is_killed(KillScope.MODEL, model_id):
            return False, f"Model {model_id} killed", SafeModeLevel.OFFLINE
        
        # Check endpoint kill
        if endpoint and self.is_killed(KillScope.ENDPOINT, endpoint):
            return False, f"Endpoint {endpoint} killed", SafeModeLevel.OFFLINE
        
        # Check safe mode
        safe_level = SafeModeLevel.NONE
        
        for scope, sid in [
            (KillScope.GLOBAL, "*"),
            (KillScope.SERVICE, service),
            (KillScope.MODEL, model_id or ""),
            (KillScope.ENDPOINT, endpoint or ""),
        ]:
            if sid:
                level = self.get_safe_mode_level(scope, sid)
                if level != SafeModeLevel.NONE:
                    if level == SafeModeLevel.OFFLINE:
                        return False, f"{scope.value} {sid} in offline mode", level
                    safe_level = level
        
        return True, "OK", safe_level
    
    # ═══════════════════════════════════════════════════════════════════
    # Kill-Switch Operations
    # ═══════════════════════════════════════════════════════════════════
    
    def kill(
        self,
        scope: KillScope,
        scope_id: str,
        reason: str,
        actor: str,
        trigger: TriggerCondition = TriggerCondition.MANUAL,
        requires_approval: bool = False,
        min_approvals: int = 1,
    ) -> KillSwitchEvent:
        """
        Activate kill-switch.
        
        Args:
            scope: Kill scope (global, service, model, endpoint)
            scope_id: ID within scope
            reason: Reason for kill
            actor: Person/system initiating kill
            trigger: What triggered the kill
            requires_approval: If True, creates approval request
            min_approvals: Minimum approvals needed
        
        Returns:
            KillSwitchEvent record
        """
        key = self._scope_key(scope, scope_id)
        states = self._state_map()
        previous_state = KillSwitchState(states.get(key, KillSwitchState.ACTIVE.value))
        
        event = KillSwitchEvent(
            event_id=f"kill_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{scope.value}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            action="kill",
            scope=scope,
            scope_id=scope_id,
            reason=reason,
            trigger=trigger,
            actor=actor,
            previous_state=previous_state,
            new_state=KillSwitchState.KILLED,
            requires_approval=requires_approval,
            auto_triggered=(trigger != TriggerCondition.MANUAL),
        )
        
        if requires_approval:
            # Create approval request
            self._create_approval_request(event, min_approvals)
            logger.warning(f"Kill-switch approval requested: {scope.value}:{scope_id}")
        else:
            # Execute immediately
            self._execute_kill(key, event)
        
        return event
    
    def enter_safe_mode(
        self,
        scope: KillScope,
        scope_id: str,
        level: SafeModeLevel,
        reason: str,
        actor: str,
        trigger: TriggerCondition = TriggerCondition.MANUAL,
    ) -> KillSwitchEvent:
        """Enter safe mode operation."""
        key = self._scope_key(scope, scope_id)
        states = self._state_map()
        previous_state = KillSwitchState(states.get(key, KillSwitchState.ACTIVE.value))
        
        event = KillSwitchEvent(
            event_id=f"safe_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{scope.value}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            action="safe_mode",
            scope=scope,
            scope_id=scope_id,
            reason=reason,
            trigger=trigger,
            actor=actor,
            previous_state=previous_state,
            new_state=KillSwitchState.SAFE_MODE,
            safe_mode_level=level,
            auto_triggered=(trigger != TriggerCondition.MANUAL),
        )
        
        self._execute_safe_mode(key, level, event)
        return event
    
    def resume(
        self,
        scope: KillScope,
        scope_id: str,
        reason: str,
        actor: str,
    ) -> KillSwitchEvent:
        """Resume normal operation."""
        key = self._scope_key(scope, scope_id)
        states = self._state_map()
        previous_state = KillSwitchState(states.get(key, KillSwitchState.ACTIVE.value))
        
        event = KillSwitchEvent(
            event_id=f"resume_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{scope.value}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            action="resume",
            scope=scope,
            scope_id=scope_id,
            reason=reason,
            trigger=TriggerCondition.MANUAL,
            actor=actor,
            previous_state=previous_state,
            new_state=KillSwitchState.ACTIVE,
        )
        
        self._execute_resume(key, event)
        return event
    
    def _execute_kill(self, key: str, event: KillSwitchEvent) -> None:
        """Execute kill-switch activation."""
        with self._lock, self._state_lock("state"):
            states = self._state_map()
            states[key] = KillSwitchState.KILLED.value
            self._set_map("states", states)
            self._save_state(key, KillSwitchState.KILLED, None, event.reason)
            self._save_event(event)
        
        logger.critical(f"KILL-SWITCH ACTIVATED: {event.scope.value}:{event.scope_id} - {event.reason}")
        
        for callback in self._on_kill:
            try:
                callback(event.scope_id, event.scope)
            except Exception as e:
                logger.error(f"Kill callback error: {e}")
    
    def _execute_safe_mode(
        self,
        key: str,
        level: SafeModeLevel,
        event: KillSwitchEvent,
    ) -> None:
        """Execute safe mode transition."""
        with self._lock, self._state_lock("state"):
            states = self._state_map()
            safe_modes = self._safe_mode_map()
            states[key] = KillSwitchState.SAFE_MODE.value
            safe_modes[key] = level.value
            self._set_map("states", states)
            self._set_map("safe_mode_levels", safe_modes)
            self._save_state(key, KillSwitchState.SAFE_MODE, level, event.reason)
            self._save_event(event)
        
        logger.warning(f"SAFE MODE ACTIVATED: {event.scope.value}:{event.scope_id} → {level.value}")
        
        for callback in self._on_safe_mode:
            try:
                callback(event.scope_id, level)
            except Exception as e:
                logger.error(f"Safe mode callback error: {e}")
    
    def _execute_resume(self, key: str, event: KillSwitchEvent) -> None:
        """Execute resume operation."""
        with self._lock, self._state_lock("state"):
            states = self._state_map()
            safe_modes = self._safe_mode_map()
            states[key] = KillSwitchState.ACTIVE.value
            if key in safe_modes:
                del safe_modes[key]
            self._set_map("states", states)
            self._set_map("safe_mode_levels", safe_modes)
            self._save_state(key, KillSwitchState.ACTIVE, None, event.reason)
            self._save_event(event)
        
        logger.info(f"RESUMED: {event.scope.value}:{event.scope_id}")
        
        for callback in self._on_resume:
            try:
                callback(event.scope_id)
            except Exception as e:
                logger.error(f"Resume callback error: {e}")
    
    def _save_state(
        self,
        key: str,
        state: KillSwitchState,
        safe_mode_level: Optional[SafeModeLevel],
        reason: str,
    ) -> None:
        """Save state to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO killswitch_state
                (scope_key, state, safe_mode_level, updated_at, reason)
                VALUES (?, ?, ?, ?, ?)
            """, (
                key,
                state.value,
                safe_mode_level.value if safe_mode_level else None,
                datetime.now(timezone.utc).isoformat(),
                reason,
            ))
    
    def _save_event(self, event: KillSwitchEvent) -> None:
        """Save event to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT INTO killswitch_events
                (event_id, timestamp, action, scope, scope_id, reason,
                 trigger_condition, actor, previous_state, new_state,
                 safe_mode_level, auto_triggered, approved_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.event_id,
                event.timestamp,
                event.action,
                event.scope.value,
                event.scope_id,
                event.reason,
                event.trigger.value,
                event.actor,
                event.previous_state.value,
                event.new_state.value,
                event.safe_mode_level.value if event.safe_mode_level else None,
                1 if event.auto_triggered else 0,
                json.dumps(event.approved_by),
            ))

        self._op_state.append_event(
            namespace=self._op_namespace,
            event_type=event.action,
            payload=event.to_dict(),
            state_key=self._scope_key(event.scope, event.scope_id),
        )
    
    # ═══════════════════════════════════════════════════════════════════
    # Approval Workflow
    # ═══════════════════════════════════════════════════════════════════
    
    def _create_approval_request(
        self,
        event: KillSwitchEvent,
        min_approvals: int,
    ) -> ApprovalRequest:
        """Create approval request for kill-switch."""
        request = ApprovalRequest(
            request_id=f"approval_{event.event_id}",
            event_id=event.event_id,
            scope=event.scope,
            scope_id=event.scope_id,
            action=event.action,
            reason=event.reason,
            requested_by=event.actor,
            requested_at=datetime.now(timezone.utc).isoformat(),
            min_approvals=min_approvals,
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        )

        with self._state_lock("approvals"):
            approvals = self._approvals_map()
            approvals[request.request_id] = request.to_dict()
            self._set_map("approvals", approvals)
        self._save_approval_request(request)
        
        return request
    
    def approve(self, request_id: str, approver: str) -> Optional[ApprovalRequest]:
        """Approve a kill-switch request."""
        approvals = self._approvals_map()
        request_payload = approvals.get(request_id)
        request = self._approval_from_dict(request_payload) if request_payload else None
        if not request:
            return None
        
        if approver in request.current_approvals:
            return request
        
        if approver == request.requested_by:
            logger.warning(f"Approver {approver} is same as requester - skipping")
            return request
        
        request.current_approvals.append(approver)
        
        if request.is_approved:
            request.status = "approved"
            # Execute the kill
            key = self._scope_key(request.scope, request.scope_id)
            states = self._state_map()
            event = KillSwitchEvent(
                event_id=request.event_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                action=request.action,
                scope=request.scope,
                scope_id=request.scope_id,
                reason=request.reason,
                trigger=TriggerCondition.MANUAL,
                actor=request.requested_by,
                previous_state=KillSwitchState(states.get(key, KillSwitchState.ACTIVE.value)),
                new_state=KillSwitchState.KILLED,
                approved_by=request.current_approvals,
            )
            self._execute_kill(key, event)

        with self._state_lock("approvals"):
            approvals = self._approvals_map()
            approvals[request.request_id] = request.to_dict()
            self._set_map("approvals", approvals)

        self._save_approval_request(request)
        return request
    
    def reject(self, request_id: str, rejector: str) -> Optional[ApprovalRequest]:
        """Reject a kill-switch request."""
        approvals = self._approvals_map()
        request_payload = approvals.get(request_id)
        request = self._approval_from_dict(request_payload) if request_payload else None
        if not request:
            return None
        
        request.rejections.append(rejector)
        request.status = "rejected"

        with self._state_lock("approvals"):
            approvals = self._approvals_map()
            approvals[request.request_id] = request.to_dict()
            self._set_map("approvals", approvals)
        
        self._save_approval_request(request)
        return request
    
    def _save_approval_request(self, request: ApprovalRequest) -> None:
        """Save approval request to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO approval_requests
                (request_id, event_id, scope, scope_id, action, reason,
                 requested_by, requested_at, min_approvals, current_approvals,
                 rejections, status, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                request.request_id,
                request.event_id,
                request.scope.value,
                request.scope_id,
                request.action,
                request.reason,
                request.requested_by,
                request.requested_at,
                request.min_approvals,
                json.dumps(request.current_approvals),
                json.dumps(request.rejections),
                request.status,
                request.expires_at,
            ))
    
    def get_pending_approvals(self) -> List[ApprovalRequest]:
        """Get all pending approval requests."""
        approvals: List[ApprovalRequest] = []
        for payload in self._approvals_map().values():
            request = self._approval_from_dict(payload)
            if request and request.status == "pending":
                approvals.append(request)
        return approvals
    
    # ═══════════════════════════════════════════════════════════════════
    # Auto-Trigger Rules
    # ═══════════════════════════════════════════════════════════════════
    
    def add_rule(self, rule: AutoTriggerRule) -> None:
        """Add auto-trigger rule."""
        with self._state_lock("rules"):
            rules = self._rules_map()
            rules[rule.rule_id] = rule.to_dict()
            self._set_map("rules", rules)
        self._save_rule(rule)
    
    def get_rules(self) -> List[AutoTriggerRule]:
        """Get all auto-trigger rules."""
        rules: List[AutoTriggerRule] = []
        for payload in self._rules_map().values():
            rule = self._rule_from_dict(payload)
            if rule:
                rules.append(rule)
        return rules
    
    def _save_rule(self, rule: AutoTriggerRule) -> None:
        """Save rule to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO auto_trigger_rules
                (rule_id, name, condition, threshold, scope, scope_id,
                 action, safe_mode_level, cooldown_minutes, enabled,
                 requires_approval, min_approvals)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rule.rule_id,
                rule.name,
                rule.condition.value,
                rule.threshold,
                rule.scope.value,
                rule.scope_id,
                rule.action,
                rule.safe_mode_level.value if rule.safe_mode_level else None,
                rule.cooldown_minutes,
                1 if rule.enabled else 0,
                1 if rule.requires_approval else 0,
                rule.min_approvals,
            ))
    
    async def check_auto_triggers(
        self,
        metrics: Dict[str, float],
    ) -> List[KillSwitchEvent]:
        """
        Check auto-trigger rules against current metrics.
        
        Args:
            metrics: Dict of metric_name -> value
                e.g., {"drift_score": 0.85, "error_rate": 0.12}
        
        Returns:
            List of triggered events
        """
        events: List[KillSwitchEvent] = []
        
        for rule in self.get_rules():
            if not rule.enabled:
                continue
            
            # Map condition to metric
            metric_map = {
                TriggerCondition.DRIFT_THRESHOLD: "drift_score",
                TriggerCondition.ERROR_RATE: "error_rate",
                TriggerCondition.LATENCY: "latency_p95",
                TriggerCondition.COST_OVERRUN: "cost_utilization",
            }
            
            metric_name = metric_map.get(rule.condition)
            if not metric_name or metric_name not in metrics:
                continue
            
            value = metrics[metric_name]
            
            if value >= rule.threshold:
                # Check cooldown
                if not self._check_cooldown(rule):
                    continue
                
                logger.warning(
                    f"Auto-trigger rule {rule.name} triggered: "
                    f"{metric_name}={value} >= {rule.threshold}"
                )
                
                if rule.action == "kill":
                    event = self.kill(
                        rule.scope,
                        rule.scope_id,
                        f"Auto-triggered: {rule.name} ({metric_name}={value})",
                        "auto_trigger_engine",
                        rule.condition,
                        rule.requires_approval,
                        rule.min_approvals,
                    )
                else:
                    event = self.enter_safe_mode(
                        rule.scope,
                        rule.scope_id,
                        rule.safe_mode_level or SafeModeLevel.CACHE_ONLY,
                        f"Auto-triggered: {rule.name} ({metric_name}={value})",
                        "auto_trigger_engine",
                        rule.condition,
                    )
                
                events.append(event)
                with self._state_lock("last_trigger"):
                    last_trigger = self._last_trigger_map()
                    last_trigger[rule.rule_id] = datetime.now(timezone.utc).isoformat()
                    self._set_map("last_trigger", last_trigger)
        
        return events
    
    def _check_cooldown(self, rule: AutoTriggerRule) -> bool:
        """Check if rule is in cooldown period."""
        last_trigger = self._last_trigger_map()
        if rule.rule_id not in last_trigger:
            return True

        try:
            previous = datetime.fromisoformat(last_trigger[rule.rule_id])
        except Exception:
            return True

        elapsed = datetime.now(timezone.utc) - previous
        return elapsed >= timedelta(minutes=rule.cooldown_minutes)
    
    # ═══════════════════════════════════════════════════════════════════
    # Dashboard & Stats
    # ═══════════════════════════════════════════════════════════════════
    
    def get_status(self) -> Dict[str, Any]:
        """Get current kill-switch status."""
        states = self._state_map()
        safe_modes = self._safe_mode_map()
        rules = self.get_rules()
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "global_state": self.get_state(KillScope.GLOBAL, "*").value,
            "global_safe_mode": self.get_safe_mode_level(KillScope.GLOBAL, "*").value,
            "active_kills": [
                {"scope": key, "state": value}
                for key, value in states.items()
                if value == KillSwitchState.KILLED.value
            ],
            "safe_mode_services": [
                {"scope": key, "level": value}
                for key, value in safe_modes.items()
            ],
            "pending_approvals": len(self.get_pending_approvals()),
            "active_rules": len([rule for rule in rules if rule.enabled]),
        }
    
    def get_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent kill-switch events."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM killswitch_events
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,)).fetchall()
            
            return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════

_killswitch: Optional[KillSwitchController] = None


def get_killswitch() -> KillSwitchController:
    """Get singleton KillSwitchController instance."""
    global _killswitch
    if _killswitch is None:
        _killswitch = KillSwitchController()
    return _killswitch

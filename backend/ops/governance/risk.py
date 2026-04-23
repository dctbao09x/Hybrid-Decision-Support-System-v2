# backend/ops/governance/risk.py
"""
Risk Management Module
======================

Provides:
- Composite risk scoring: risk = w1*drift + w2*latency + w3*error + w4*cost_overrun
- Auto-mitigation triggers
- Risk history tracking
- Risk alerts
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("ops.governance.risk")


class RiskLevel(Enum):
    """Risk severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MitigationStatus(Enum):
    """Mitigation action status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class RiskWeights:
    """Weights for risk calculation."""
    drift: float = 0.3
    latency: float = 0.25
    error_rate: float = 0.30
    cost_overrun: float = 0.15
    
    def normalize(self) -> "RiskWeights":
        """Normalize weights to sum to 1.0."""
        total = self.drift + self.latency + self.error_rate + self.cost_overrun
        if total == 0:
            return RiskWeights(0.25, 0.25, 0.25, 0.25)
        return RiskWeights(
            drift=self.drift / total,
            latency=self.latency / total,
            error_rate=self.error_rate / total,
            cost_overrun=self.cost_overrun / total,
        )


@dataclass
class RiskThresholds:
    """Thresholds for risk level classification."""
    low_max: float = 0.3
    medium_max: float = 0.5
    high_max: float = 0.7
    # Above high_max = critical


@dataclass
class RiskMetrics:
    """Input metrics for risk calculation."""
    drift_score: float = 0.0       # 0.0 - 1.0 (0 = no drift, 1 = severe drift)
    latency_score: float = 0.0    # 0.0 - 1.0 (normalized latency deviation)
    error_rate: float = 0.0       # 0.0 - 1.0 (error ratio)
    cost_overrun: float = 0.0     # 0.0 - 1.0 (cost deviation from budget)
    
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class RiskScore:
    """Calculated risk score."""
    score: float
    level: RiskLevel
    components: Dict[str, float]
    timestamp: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "level": self.level.value,
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "timestamp": self.timestamp,
        }


@dataclass
class MitigationAction:
    """Auto-mitigation action."""
    action_id: str
    name: str
    description: str
    trigger_condition: str  # e.g., "risk_level == 'critical'"
    callback: Optional[Callable] = None
    enabled: bool = True
    cooldown_minutes: int = 30
    last_triggered: Optional[str] = None


@dataclass
class MitigationEvent:
    """Record of a mitigation action execution."""
    event_id: str
    action_id: str
    action_name: str
    triggered_at: str
    risk_score: float
    risk_level: str
    status: MitigationStatus
    result_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "action_id": self.action_id,
            "action_name": self.action_name,
            "triggered_at": self.triggered_at,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "status": self.status.value,
            "result_message": self.result_message,
        }


class RiskManager:
    """
    Risk Management Engine.
    
    Features:
    - Composite risk scoring with configurable weights
    - Auto-mitigation triggers
    - Risk history tracking
    - Dashboard data generation
    """
    
    def __init__(
        self,
        weights: Optional[RiskWeights] = None,
        thresholds: Optional[RiskThresholds] = None,
        db_path: Optional[Path] = None,
    ):
        self._weights = (weights or RiskWeights()).normalize()
        self._thresholds = thresholds or RiskThresholds()
        self._db_path = db_path or Path("backend/data/ops/risk.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._lock = Lock()
        self._mitigation_actions: Dict[str, MitigationAction] = {}
        self._alert_callbacks: List[Callable[[RiskScore], None]] = []
        
        self._init_db()
        self._register_default_mitigations()
        
        logger.info(f"RiskManager initialized with weights: {self._weights}")
    
    def _init_db(self) -> None:
        """Initialize database tables."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS risk_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    score REAL NOT NULL,
                    level TEXT NOT NULL,
                    drift_component REAL,
                    latency_component REAL,
                    error_component REAL,
                    cost_component REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mitigation_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    action_name TEXT NOT NULL,
                    triggered_at TEXT NOT NULL,
                    risk_score REAL NOT NULL,
                    risk_level TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_message TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_risk_timestamp ON risk_scores(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_mitigation_timestamp ON mitigation_events(triggered_at)
            """)
            conn.commit()
    
    def _register_default_mitigations(self) -> None:
        """Register default mitigation actions."""
        self.register_mitigation(
            action_id="alert_team",
            name="Alert Team",
            description="Send alert to operations team",
            trigger_condition="risk_level in ['high', 'critical']",
            callback=lambda score: logger.warning(f"RISK ALERT: {score.level.value} risk detected - score: {score.score:.3f}"),
            cooldown_minutes=15,
        )
        
        self.register_mitigation(
            action_id="enable_cache_fallback",
            name="Enable Cache Fallback",
            description="Enable aggressive caching for degraded performance",
            trigger_condition="risk_level == 'critical' and components['latency'] > 0.7",
            callback=lambda score: logger.info("Mitigation: Enabling cache fallback mode"),
            cooldown_minutes=60,
        )
        
        self.register_mitigation(
            action_id="throttle_requests",
            name="Throttle Requests",
            description="Reduce request rate to prevent overload",
            trigger_condition="risk_level == 'critical' and components['error_rate'] > 0.6",
            callback=lambda score: logger.info("Mitigation: Throttling incoming requests"),
            cooldown_minutes=30,
        )
    
    def calculate_risk(self, metrics: RiskMetrics) -> RiskScore:
        """
        Calculate composite risk score.
        
        Formula: risk = w1*drift + w2*latency + w3*error + w4*cost
        """
        # Calculate weighted components
        components = {
            "drift": self._weights.drift * metrics.drift_score,
            "latency": self._weights.latency * metrics.latency_score,
            "error_rate": self._weights.error_rate * metrics.error_rate,
            "cost_overrun": self._weights.cost_overrun * metrics.cost_overrun,
        }
        
        # Sum to get total risk score
        score = sum(components.values())
        
        # Clamp to [0, 1]
        score = max(0.0, min(1.0, score))
        
        # Determine level
        level = self._determine_level(score)
        
        risk_score = RiskScore(
            score=score,
            level=level,
            components=components,
            timestamp=metrics.timestamp,
        )
        
        # Record to database
        self._record_score(risk_score)
        
        # Trigger alerts and mitigations
        self._trigger_alerts(risk_score)
        self._trigger_mitigations(risk_score)
        
        return risk_score
    
    def _determine_level(self, score: float) -> RiskLevel:
        """Determine risk level from score."""
        if score <= self._thresholds.low_max:
            return RiskLevel.LOW
        elif score <= self._thresholds.medium_max:
            return RiskLevel.MEDIUM
        elif score <= self._thresholds.high_max:
            return RiskLevel.HIGH
        else:
            return RiskLevel.CRITICAL
    
    def _record_score(self, score: RiskScore) -> None:
        """Record risk score to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT INTO risk_scores (
                    timestamp, score, level,
                    drift_component, latency_component, error_component, cost_component
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                score.timestamp,
                score.score,
                score.level.value,
                score.components.get("drift", 0),
                score.components.get("latency", 0),
                score.components.get("error_rate", 0),
                score.components.get("cost_overrun", 0),
            ))
            conn.commit()
    
    def _trigger_alerts(self, score: RiskScore) -> None:
        """Trigger alert callbacks."""
        for callback in self._alert_callbacks:
            try:
                callback(score)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")
    
    def _trigger_mitigations(self, score: RiskScore) -> None:
        """Trigger auto-mitigation actions if conditions are met."""
        now = datetime.now(timezone.utc)
        
        for action in self._mitigation_actions.values():
            if not action.enabled:
                continue
            
            # Check cooldown
            if action.last_triggered:
                last = datetime.fromisoformat(action.last_triggered.replace("Z", "+00:00"))
                if now - last < timedelta(minutes=action.cooldown_minutes):
                    continue
            
            # Evaluate condition
            if self._evaluate_condition(action.trigger_condition, score):
                self._execute_mitigation(action, score)
    
    def _evaluate_condition(self, condition: str, score: RiskScore) -> bool:
        """Evaluate mitigation trigger condition."""
        try:
            # Build context for evaluation
            context = {
                "risk_level": score.level.value,
                "score": score.score,
                "components": score.components,
            }
            
            # Safe evaluation (limited scope)
            return eval(condition, {"__builtins__": {}}, context)
        except Exception as e:
            logger.warning(f"Condition evaluation failed: {condition} - {e}")
            return False
    
    def _execute_mitigation(self, action: MitigationAction, score: RiskScore) -> None:
        """Execute a mitigation action."""
        import hashlib
        
        event_id = hashlib.sha256(
            f"{action.action_id}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]
        
        event = MitigationEvent(
            event_id=event_id,
            action_id=action.action_id,
            action_name=action.name,
            triggered_at=datetime.now(timezone.utc).isoformat(),
            risk_score=score.score,
            risk_level=score.level.value,
            status=MitigationStatus.IN_PROGRESS,
        )
        
        try:
            if action.callback:
                action.callback(score)
            
            event.status = MitigationStatus.COMPLETED
            event.result_message = "Mitigation executed successfully"
            action.last_triggered = datetime.now(timezone.utc).isoformat()
            
            logger.info(f"Mitigation '{action.name}' executed for risk level {score.level.value}")
            
        except Exception as e:
            event.status = MitigationStatus.FAILED
            event.result_message = str(e)
            logger.error(f"Mitigation '{action.name}' failed: {e}")
        
        # Record event
        self._record_mitigation_event(event)
    
    def _record_mitigation_event(self, event: MitigationEvent) -> None:
        """Record mitigation event to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT INTO mitigation_events (
                    event_id, action_id, action_name, triggered_at,
                    risk_score, risk_level, status, result_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.event_id,
                event.action_id,
                event.action_name,
                event.triggered_at,
                event.risk_score,
                event.risk_level,
                event.status.value,
                event.result_message,
            ))
            conn.commit()
    
    def register_mitigation(
        self,
        action_id: str,
        name: str,
        description: str,
        trigger_condition: str,
        callback: Optional[Callable] = None,
        cooldown_minutes: int = 30,
    ) -> None:
        """Register a mitigation action."""
        self._mitigation_actions[action_id] = MitigationAction(
            action_id=action_id,
            name=name,
            description=description,
            trigger_condition=trigger_condition,
            callback=callback,
            cooldown_minutes=cooldown_minutes,
        )
    
    def enable_mitigation(self, action_id: str, enabled: bool = True) -> None:
        """Enable or disable a mitigation action."""
        if action_id in self._mitigation_actions:
            self._mitigation_actions[action_id].enabled = enabled
    
    def add_alert_callback(self, callback: Callable[[RiskScore], None]) -> None:
        """Add alert callback for risk score changes."""
        self._alert_callbacks.append(callback)
    
    def set_weights(self, weights: RiskWeights) -> None:
        """Update risk weights."""
        self._weights = weights.normalize()
    
    def set_thresholds(self, thresholds: RiskThresholds) -> None:
        """Update risk thresholds."""
        self._thresholds = thresholds
    
    def get_risk_history(
        self,
        hours: int = 24,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Get recent risk score history."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        with sqlite3.connect(str(self._db_path)) as conn:
            rows = conn.execute("""
                SELECT timestamp, score, level,
                       drift_component, latency_component, error_component, cost_component
                FROM risk_scores
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (cutoff, limit)).fetchall()
        
        return [
            {
                "timestamp": row[0],
                "score": row[1],
                "level": row[2],
                "components": {
                    "drift": row[3],
                    "latency": row[4],
                    "error_rate": row[5],
                    "cost_overrun": row[6],
                },
            }
            for row in rows
        ]
    
    def get_mitigation_history(
        self,
        hours: int = 24,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get recent mitigation event history."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        with sqlite3.connect(str(self._db_path)) as conn:
            rows = conn.execute("""
                SELECT event_id, action_id, action_name, triggered_at,
                       risk_score, risk_level, status, result_message
                FROM mitigation_events
                WHERE triggered_at >= ?
                ORDER BY triggered_at DESC
                LIMIT ?
            """, (cutoff, limit)).fetchall()
        
        return [
            {
                "event_id": row[0],
                "action_id": row[1],
                "action_name": row[2],
                "triggered_at": row[3],
                "risk_score": row[4],
                "risk_level": row[5],
                "status": row[6],
                "result_message": row[7],
            }
            for row in rows
        ]
    
    def get_current_risk_level(self) -> Optional[RiskLevel]:
        """Get the most recent risk level."""
        with sqlite3.connect(str(self._db_path)) as conn:
            row = conn.execute("""
                SELECT level FROM risk_scores
                ORDER BY timestamp DESC
                LIMIT 1
            """).fetchone()
        
        if row:
            return RiskLevel(row[0])
        return None
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get data for risk dashboard."""
        history = self.get_risk_history(hours=24, limit=288)  # 5-min intervals for 24h
        mitigation_history = self.get_mitigation_history(hours=24)
        
        # Current risk
        current = history[0] if history else None
        
        # Level distribution
        level_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        for h in history:
            level_counts[h["level"]] = level_counts.get(h["level"], 0) + 1
        
        # Average by component
        if history:
            avg_components = {
                "drift": sum(h["components"]["drift"] for h in history) / len(history),
                "latency": sum(h["components"]["latency"] for h in history) / len(history),
                "error_rate": sum(h["components"]["error_rate"] for h in history) / len(history),
                "cost_overrun": sum(h["components"]["cost_overrun"] for h in history) / len(history),
            }
        else:
            avg_components = {"drift": 0, "latency": 0, "error_rate": 0, "cost_overrun": 0}
        
        return {
            "current_risk": current,
            "level_distribution": level_counts,
            "average_components": avg_components,
            "history_24h": history[:50],  # Last 50 data points
            "mitigation_events": mitigation_history[:20],
            "weights": {
                "drift": self._weights.drift,
                "latency": self._weights.latency,
                "error_rate": self._weights.error_rate,
                "cost_overrun": self._weights.cost_overrun,
            },
            "mitigations": [
                {
                    "action_id": a.action_id,
                    "name": a.name,
                    "description": a.description,
                    "enabled": a.enabled,
                    "cooldown_minutes": a.cooldown_minutes,
                }
                for a in self._mitigation_actions.values()
            ],
        }


# Global risk manager instance
_risk_manager: Optional[RiskManager] = None


def get_risk_manager() -> RiskManager:
    """Get or create the global risk manager instance."""
    global _risk_manager
    if _risk_manager is None:
        _risk_manager = RiskManager()
    return _risk_manager

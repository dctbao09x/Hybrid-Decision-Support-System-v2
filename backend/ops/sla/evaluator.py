# backend/ops/sla/evaluator.py
"""
SLA Evaluator
=============

Real-time SLA evaluation engine.

Responsibilities:
- Continuous monitoring of metrics against contracts
- Real-time violation detection
- Alert triggering on breaches
- Violation history tracking
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from backend.ops.sla.contracts import (
    SLAContract,
    SLAViolation,
    SLAStatus,
    SLASeverity,
    DEFAULT_CONTRACT,
)

logger = logging.getLogger("ops.sla.evaluator")


class SLAEvaluator:
    """
    Real-time SLA evaluation engine.
    
    Features:
    - Register multiple SLA contracts
    - Continuous evaluation against metrics
    - Violation detection with deduplication
    - Alert notification on breaches
    - Historical violation tracking
    """
    
    def __init__(
        self,
        db_path: Optional[Path] = None,
        dedup_window_minutes: int = 15,
        max_violations: int = 1000,
    ):
        self._db_path = db_path or Path("backend/data/ops/sla.db")
        self._dedup_window = dedup_window_minutes * 60  # Convert to seconds
        self._max_violations = max_violations
        
        # Registered contracts
        self._contracts: Dict[str, SLAContract] = {}
        
        # Violation tracking
        self._violations: Deque[SLAViolation] = deque(maxlen=max_violations)
        self._violation_times: Dict[str, float] = {}  # For deduplication
        
        # Alert callbacks
        self._alert_callbacks: List[Callable[[SLAViolation], None]] = []
        
        # Lock for thread safety
        self._lock = threading.RLock()
        
        # Storage
        self._conn: Optional[sqlite3.Connection] = None
        self._initialized = False
        
        # Register default contract
        self.register_contract(DEFAULT_CONTRACT)
        
        logger.info("SLAEvaluator initialized")
    
    async def initialize(self) -> None:
        """Initialize storage."""
        if self._initialized:
            return
        
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        self._initialized = True
    
    def _create_tables(self) -> None:
        """Create database tables."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sla_violations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                violation_id TEXT NOT NULL UNIQUE,
                contract_id TEXT NOT NULL,
                target_name TEXT NOT NULL,
                metric TEXT NOT NULL,
                threshold REAL NOT NULL,
                actual_value REAL NOT NULL,
                severity TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                acknowledged INTEGER DEFAULT 0,
                resolution TEXT,
                resolved_at TEXT,
                created_at TEXT NOT NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_violations_contract ON sla_violations(contract_id);
            CREATE INDEX IF NOT EXISTS idx_violations_timestamp ON sla_violations(timestamp);
            CREATE INDEX IF NOT EXISTS idx_violations_severity ON sla_violations(severity);
            
            CREATE TABLE IF NOT EXISTS sla_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_id TEXT NOT NULL,
                status TEXT NOT NULL,
                availability REAL,
                p95_latency REAL,
                error_rate REAL,
                violation_count INTEGER NOT NULL,
                evaluation_time TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_evaluations_contract ON sla_evaluations(contract_id);
            CREATE INDEX IF NOT EXISTS idx_evaluations_time ON sla_evaluations(evaluation_time);
        """)
        self._conn.commit()
    
    def register_contract(self, contract: SLAContract) -> None:
        """Register an SLA contract."""
        with self._lock:
            self._contracts[contract.contract_id] = contract
            logger.info(f"Registered SLA contract: {contract.name} ({contract.contract_id})")
    
    def unregister_contract(self, contract_id: str) -> bool:
        """Unregister an SLA contract."""
        with self._lock:
            if contract_id in self._contracts:
                del self._contracts[contract_id]
                logger.info(f"Unregistered SLA contract: {contract_id}")
                return True
            return False
    
    def get_contract(self, contract_id: str) -> Optional[SLAContract]:
        """Get a contract by ID."""
        return self._contracts.get(contract_id)
    
    def list_contracts(self) -> List[Dict[str, Any]]:
        """List all registered contracts."""
        with self._lock:
            return [c.to_dict() for c in self._contracts.values()]
    
    def on_violation(self, callback: Callable[[SLAViolation], None]) -> None:
        """Register a callback for violation notifications."""
        self._alert_callbacks.append(callback)
    
    def evaluate(
        self,
        metrics: Dict[str, float],
        contract_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate metrics against SLA contracts.
        
        Args:
            metrics: Dictionary of metric values
            contract_id: Specific contract to evaluate (None = all contracts)
        
        Returns:
            Evaluation results for all evaluated contracts
        """
        now = time.time()
        results = {}
        
        with self._lock:
            contracts_to_eval = (
                [self._contracts[contract_id]] if contract_id and contract_id in self._contracts
                else list(self._contracts.values())
            )
        
        for contract in contracts_to_eval:
            result = contract.evaluate(metrics)
            results[contract.contract_id] = result
            
            # Process violations
            for violation_dict in result.get("violations", []):
                violation = SLAViolation(
                    violation_id=violation_dict["violation_id"],
                    contract_id=violation_dict["contract_id"],
                    target_name=violation_dict["target_name"],
                    metric=violation_dict["metric"],
                    threshold=violation_dict["threshold"],
                    actual_value=violation_dict["actual_value"],
                    severity=SLASeverity(violation_dict["severity"]),
                    timestamp=violation_dict["timestamp"],
                )
                
                # Check for deduplication
                dedup_key = f"{contract.contract_id}:{violation.metric}"
                last_time = self._violation_times.get(dedup_key, 0)
                
                if now - last_time >= self._dedup_window:
                    # New violation (not deduplicated)
                    self._violation_times[dedup_key] = now
                    self._record_violation(violation)
                    
                    # Notify callbacks
                    for callback in self._alert_callbacks:
                        try:
                            callback(violation)
                        except Exception as e:
                            logger.warning(f"Alert callback error: {e}")
        
        return {
            "evaluations": results,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "contracts_evaluated": len(results),
        }
    
    def _record_violation(self, violation: SLAViolation) -> None:
        """Record a violation."""
        with self._lock:
            self._violations.append(violation)
        
        # Persist if initialized
        if self._initialized and self._conn:
            try:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO sla_violations
                    (violation_id, contract_id, target_name, metric, threshold,
                     actual_value, severity, timestamp, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        violation.violation_id,
                        violation.contract_id,
                        violation.target_name,
                        violation.metric,
                        violation.threshold,
                        violation.actual_value,
                        violation.severity.value,
                        violation.timestamp,
                        datetime.now(timezone.utc).isoformat(),
                    )
                )
                self._conn.commit()
            except sqlite3.Error as e:
                logger.warning(f"Failed to persist violation: {e}")
    
    def get_recent_violations(
        self,
        hours: float = 24.0,
        severity: Optional[SLASeverity] = None,
        contract_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent violations."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_str = cutoff.isoformat()
        
        with self._lock:
            violations = list(self._violations)
        
        # Filter
        filtered = []
        for v in violations:
            if v.timestamp < cutoff_str:
                continue
            if severity and v.severity != severity:
                continue
            if contract_id and v.contract_id != contract_id:
                continue
            filtered.append(v.to_dict())
        
        return sorted(filtered, key=lambda x: x["timestamp"], reverse=True)
    
    def acknowledge_violation(
        self,
        violation_id: str,
        resolution: Optional[str] = None,
    ) -> bool:
        """Acknowledge a violation."""
        with self._lock:
            for v in self._violations:
                if v.violation_id == violation_id:
                    v.acknowledge(resolution)
                    
                    # Update in storage
                    if self._initialized and self._conn:
                        self._conn.execute(
                            """
                            UPDATE sla_violations
                            SET acknowledged = 1, resolution = ?, resolved_at = ?
                            WHERE violation_id = ?
                            """,
                            (resolution, datetime.now(timezone.utc).isoformat(), violation_id)
                        )
                        self._conn.commit()
                    
                    return True
        return False
    
    def get_compliance_summary(
        self,
        window_hours: float = 24.0,
    ) -> Dict[str, Any]:
        """Get SLA compliance summary."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        cutoff_str = cutoff.isoformat()
        
        with self._lock:
            violations = [v for v in self._violations if v.timestamp >= cutoff_str]
        
        # Group by contract
        by_contract: Dict[str, List[SLAViolation]] = {}
        for v in violations:
            by_contract.setdefault(v.contract_id, []).append(v)
        
        # Calculate compliance per contract
        contract_summaries = {}
        for contract_id, contract in self._contracts.items():
            contract_violations = by_contract.get(contract_id, [])
            critical_violations = [v for v in contract_violations if v.severity == SLASeverity.CRITICAL]
            
            # Determine status
            if critical_violations:
                status = SLAStatus.BREACHED
            elif contract_violations:
                status = SLAStatus.AT_RISK
            else:
                status = SLAStatus.HEALTHY
            
            contract_summaries[contract_id] = {
                "contract_name": contract.name,
                "status": status.value,
                "total_violations": len(contract_violations),
                "critical_violations": len(critical_violations),
                "unacknowledged": len([v for v in contract_violations if not v.acknowledged]),
            }
        
        return {
            "window_hours": window_hours,
            "total_violations": len(violations),
            "critical_count": len([v for v in violations if v.severity == SLASeverity.CRITICAL]),
            "warning_count": len([v for v in violations if v.severity == SLASeverity.WARNING]),
            "contracts": contract_summaries,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    def get_dashboard(self) -> Dict[str, Any]:
        """Get full SLA dashboard data."""
        return {
            "compliance_24h": self.get_compliance_summary(window_hours=24),
            "compliance_1h": self.get_compliance_summary(window_hours=1),
            "recent_violations": self.get_recent_violations(hours=24)[:20],
            "contracts": self.list_contracts(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# Global evaluator instance
_evaluator: Optional[SLAEvaluator] = None


def get_sla_evaluator() -> SLAEvaluator:
    """Get or create the global SLA evaluator instance."""
    global _evaluator
    if _evaluator is None:
        _evaluator = SLAEvaluator()
    return _evaluator

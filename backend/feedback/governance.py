# backend/feedback/governance.py
"""
Data Governance & Retention
===========================

Implements data retention policies, audit trail, and compliance controls.

Retention Policy (configurable):
  - Raw feedback: 2 years
  - Approved training data: permanent
  - Rejected feedback: 6 months
  - Audit logs: 7 years
  - Orphan traces (no feedback): 1 year
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.feedback.models import FeedbackAuditLog
from backend.feedback.storage import FeedbackStorage

logger = logging.getLogger("feedback.governance")


# ==============================================================================
# RETENTION POLICY
# ==============================================================================

class RetentionPolicy:
    """
    Configurable data retention policy.
    
    Default policy:
      - raw_feedback_days: 730 (2 years)
      - rejected_feedback_days: 180 (6 months)
      - approved_data: permanent (never deleted)
      - orphan_traces_days: 365 (1 year)
      - audit_logs_days: 2555 (7 years)
    """
    
    def __init__(
        self,
        raw_feedback_days: int = 730,
        rejected_feedback_days: int = 180,
        orphan_traces_days: int = 365,
        audit_logs_days: int = 2555,
    ):
        self.raw_feedback_days = raw_feedback_days
        self.rejected_feedback_days = rejected_feedback_days
        self.orphan_traces_days = orphan_traces_days
        self.audit_logs_days = audit_logs_days
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_feedback_days": self.raw_feedback_days,
            "rejected_feedback_days": self.rejected_feedback_days,
            "orphan_traces_days": self.orphan_traces_days,
            "audit_logs_days": self.audit_logs_days,
            "approved_data": "permanent",
        }
    
    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "RetentionPolicy":
        return cls(
            raw_feedback_days=config.get("raw_feedback_days", 730),
            rejected_feedback_days=config.get("rejected_feedback_days", 180),
            orphan_traces_days=config.get("orphan_traces_days", 365),
            audit_logs_days=config.get("audit_logs_days", 2555),
        )


class RetentionManager:
    """
    Manages data retention cleanup.
    
    Should be run as scheduled job (e.g., daily via cron or scheduler).
    """
    
    def __init__(
        self,
        storage: FeedbackStorage,
        policy: Optional[RetentionPolicy] = None,
    ):
        self._storage = storage
        self._policy = policy or RetentionPolicy()
    
    async def run_cleanup(self) -> Dict[str, Any]:
        """
        Execute retention cleanup.
        
        Returns:
            Summary of deleted records
        """
        await self._storage.initialize()
        
        result = await self._storage.cleanup_old_data()
        
        # Log cleanup action
        await self._storage.log_audit(FeedbackAuditLog(
            id=f"audit-cleanup-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            action="retention_cleanup",
            entity_type="system",
            entity_id="scheduled_cleanup",
            user_id="system",
            details={
                "policy": self._policy.to_dict(),
                "deleted": result,
            },
        ))
        
        logger.info(f"Retention cleanup completed: {result}")
        return result
    
    async def get_retention_report(self) -> Dict[str, Any]:
        """Generate retention status report."""
        await self._storage.initialize()
        
        now = datetime.now(timezone.utc)
        
        # Get data age statistics
        stats = await self._storage.get_feedback_stats()
        
        # Calculate upcoming deletions
        rejected_cutoff = (now - timedelta(days=self._policy.rejected_feedback_days)).isoformat()
        raw_cutoff = (now - timedelta(days=self._policy.raw_feedback_days)).isoformat()
        
        return {
            "policy": self._policy.to_dict(),
            "current_counts": {
                "total_feedback": stats["total_feedback"],
                "pending": stats["pending_count"],
                "approved": stats["approved_count"],
                "rejected": stats["rejected_count"],
                "training_samples": stats["training_samples_generated"],
            },
            "retention_info": {
                "rejected_cutoff_date": rejected_cutoff,
                "raw_cutoff_date": raw_cutoff,
            },
            "generated_at": now.isoformat(),
        }


# ==============================================================================
# AUDIT SERVICE
# ==============================================================================

class AuditService:
    """
    Comprehensive audit trail management.
    
    Records all feedback operations for compliance.
    """
    
    def __init__(self, storage: FeedbackStorage):
        self._storage = storage
    
    async def log_action(
        self,
        action: str,
        entity_type: str,
        entity_id: str,
        user_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> str:
        """Log an audit action."""
        import uuid
        
        audit = FeedbackAuditLog(
            id=f"audit-{uuid.uuid4().hex[:12]}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            details=details or {},
            ip_address=ip_address,
        )
        
        await self._storage.log_audit(audit)
        return audit.id
    
    async def get_audit_trail(
        self,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query audit trail."""
        await self._storage.initialize()
        
        # Build query
        conditions = []
        params = []
        
        if entity_type:
            conditions.append("entity_type = ?")
            params.append(entity_type)
        
        if entity_id:
            conditions.append("entity_id = ?")
            params.append(entity_id)
        
        if from_date:
            conditions.append("timestamp >= ?")
            params.append(from_date)
        
        if to_date:
            conditions.append("timestamp <= ?")
            params.append(to_date)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        with self._storage._lock:
            cursor = self._storage._conn.execute(
                f"""SELECT * FROM audit_log WHERE {where_clause}
                    ORDER BY timestamp DESC LIMIT ?""",
                params + [limit]
            )
            
            return [
                {
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "action": row["action"],
                    "entity_type": row["entity_type"],
                    "entity_id": row["entity_id"],
                    "user_id": row["user_id"],
                    "details": json.loads(row["details"] or "{}"),
                    "ip_address": row["ip_address"],
                }
                for row in cursor.fetchall()
            ]


# ==============================================================================
# COMPLIANCE CHECKS
# ==============================================================================

class ComplianceChecker:
    """
    Validates data governance compliance.
    
    Checks:
      - No orphan feedback (all feedback has trace)
      - Audit completeness
      - Retention policy adherence
    """
    
    def __init__(self, storage: FeedbackStorage):
        self._storage = storage
    
    async def run_compliance_check(self) -> Dict[str, Any]:
        """Run compliance validation."""
        await self._storage.initialize()
        
        issues = []
        
        # Check for orphan feedback (should not exist)
        orphan_check = await self._check_orphan_feedback()
        if orphan_check["count"] > 0:
            issues.append({
                "type": "orphan_feedback",
                "severity": "error",
                "message": f"Found {orphan_check['count']} feedback entries without trace",
                "details": orphan_check,
            })
        
        # Check audit completeness
        audit_check = await self._check_audit_coverage()
        if audit_check["coverage"] < 0.95:
            issues.append({
                "type": "audit_gap",
                "severity": "warning",
                "message": f"Audit coverage is {audit_check['coverage']:.1%}",
                "details": audit_check,
            })
        
        return {
            "status": "passed" if not issues else "failed",
            "issues": issues,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    
    async def _check_orphan_feedback(self) -> Dict[str, Any]:
        """Check for feedback without associated trace."""
        with self._storage._lock:
            cursor = self._storage._conn.execute("""
                SELECT COUNT(*) as cnt FROM feedback f
                LEFT JOIN traces t ON f.trace_id = t.trace_id
                WHERE t.trace_id IS NULL
            """)
            count = cursor.fetchone()[0]
            
            return {"count": count}
    
    async def _check_audit_coverage(self) -> Dict[str, Any]:
        """Check audit log coverage."""
        with self._storage._lock:
            # Count feedback operations
            cursor = self._storage._conn.execute("SELECT COUNT(*) FROM feedback")
            feedback_count = cursor.fetchone()[0]
            
            # Count related audit entries
            cursor = self._storage._conn.execute("""
                SELECT COUNT(*) FROM audit_log
                WHERE entity_type = 'feedback' AND action LIKE 'submit%'
            """)
            audit_count = cursor.fetchone()[0]
            
            coverage = audit_count / max(feedback_count, 1)
            
            return {
                "feedback_count": feedback_count,
                "audit_count": audit_count,
                "coverage": coverage,
            }

# backend/ops/incident/manager.py
"""
Incident Manager
================

Central incident management system:
- Incident CRUD and lifecycle
- Alert pipeline
- Escalation management
- Playbook triggering
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.ops.incident.models import (
    ActionItem,
    AlertChannel,
    DEFAULT_ESCALATION_POLICIES,
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

logger = logging.getLogger("ops.incident.manager")


class IncidentManager:
    """
    Central incident management system.
    
    Features:
    - Full incident lifecycle management
    - Alert detection and classification
    - Escalation management
    - Playbook triggering and execution
    - RCA and postmortem workflows
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self._root = Path(__file__).resolve().parents[3]
        self._db_path = db_path or self._root / "storage/ops/incidents.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        
        # Callbacks
        self._on_incident: List[Callable[[Incident], None]] = []
        self._on_escalation: List[Callable[[Incident, EscalationLevel], None]] = []
        
        # Escalation tracking
        self._escalation_tasks: Dict[str, asyncio.Task] = {}
        
        self._init_db()
        self._init_default_playbooks()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    priority TEXT NOT NULL,
                    category TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    detected_by TEXT,
                    detection_source TEXT,
                    impact_summary TEXT,
                    affected_services TEXT,
                    affected_users INTEGER DEFAULT 0,
                    financial_impact_usd REAL DEFAULT 0,
                    acknowledged_at TEXT,
                    acknowledged_by TEXT,
                    assigned_to TEXT,
                    escalation_level TEXT,
                    resolved_at TEXT,
                    resolved_by TEXT,
                    resolution_summary TEXT,
                    time_to_detect_minutes REAL DEFAULT 0,
                    time_to_acknowledge_minutes REAL DEFAULT 0,
                    time_to_resolve_minutes REAL DEFAULT 0,
                    timeline TEXT,
                    tags TEXT,
                    related_incidents TEXT,
                    playbook_id TEXT,
                    rca_id TEXT,
                    postmortem_id TEXT
                );
                
                CREATE TABLE IF NOT EXISTS rcas (
                    rca_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT,
                    root_cause TEXT,
                    contributing_factors TEXT,
                    five_whys TEXT,
                    fault_chain TEXT,
                    evidence TEXT,
                    logs TEXT,
                    metrics_snapshots TEXT,
                    impact_assessment TEXT,
                    blast_radius TEXT,
                    immediate_actions TEXT,
                    long_term_recommendations TEXT,
                    created_at TEXT,
                    created_by TEXT,
                    reviewed_by TEXT,
                    approved_by TEXT
                );
                
                CREATE TABLE IF NOT EXISTS playbooks (
                    playbook_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    version TEXT,
                    trigger_priority TEXT,
                    trigger_category TEXT,
                    trigger_keywords TEXT,
                    steps TEXT,
                    auto_execute INTEGER DEFAULT 1,
                    max_auto_steps INTEGER DEFAULT 5,
                    requires_approval INTEGER DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT,
                    created_by TEXT,
                    enabled INTEGER DEFAULT 1
                );
                
                CREATE TABLE IF NOT EXISTS postmortems (
                    postmortem_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    content TEXT,
                    created_at TEXT,
                    created_by TEXT,
                    published_at TEXT
                );
                
                CREATE INDEX IF NOT EXISTS idx_incident_status ON incidents(status);
                CREATE INDEX IF NOT EXISTS idx_incident_priority ON incidents(priority);
                CREATE INDEX IF NOT EXISTS idx_incident_detected ON incidents(detected_at);
            """)
    
    # ═══════════════════════════════════════════════════════════════════
    # Callback Registration
    # ═══════════════════════════════════════════════════════════════════
    
    def on_incident(self, callback: Callable[[Incident], None]) -> None:
        """Register callback for new incidents."""
        self._on_incident.append(callback)
    
    def on_escalation(self, callback: Callable[[Incident, EscalationLevel], None]) -> None:
        """Register callback for escalations."""
        self._on_escalation.append(callback)
    
    # ═══════════════════════════════════════════════════════════════════
    # Incident CRUD
    # ═══════════════════════════════════════════════════════════════════
    
    def create_incident(
        self,
        title: str,
        description: str,
        priority: IncidentPriority,
        category: IncidentCategory,
        detected_by: str = "system",
        detection_source: str = "",
        affected_services: Optional[List[str]] = None,
    ) -> Incident:
        """Create a new incident."""
        incident_id = f"INC-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{priority.value}"
        
        incident = Incident(
            incident_id=incident_id,
            title=title,
            description=description,
            priority=priority,
            category=category,
            status=IncidentStatus.DETECTED,
            detected_at=datetime.now(timezone.utc).isoformat(),
            detected_by=detected_by,
            detection_source=detection_source,
            affected_services=affected_services or [],
        )
        
        # Add initial timeline
        incident.add_timeline_event(
            "detected",
            f"Incident detected by {detected_by}",
            detected_by,
        )
        
        self._save_incident(incident)
        
        # Fire callbacks
        for callback in self._on_incident:
            try:
                callback(incident)
            except Exception as e:
                logger.error(f"Incident callback error: {e}")
        
        logger.warning(f"Incident created: {incident_id} - {title} [{priority.value}]")
        
        # Start escalation timer
        asyncio.create_task(self._start_escalation_timer(incident))
        
        return incident
    
    def get_incident(self, incident_id: str) -> Optional[Incident]:
        """Get incident by ID."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM incidents WHERE incident_id = ?",
                (incident_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return self._row_to_incident(dict(row))
    
    def list_incidents(
        self,
        status: Optional[IncidentStatus] = None,
        priority: Optional[IncidentPriority] = None,
        category: Optional[IncidentCategory] = None,
        limit: int = 100,
    ) -> List[Incident]:
        """List incidents with filters."""
        query = "SELECT * FROM incidents WHERE 1=1"
        params: List[Any] = []
        
        if status:
            query += " AND status = ?"
            params.append(status.value)
        
        if priority:
            query += " AND priority = ?"
            params.append(priority.value)
        
        if category:
            query += " AND category = ?"
            params.append(category.value)
        
        query += " ORDER BY detected_at DESC LIMIT ?"
        params.append(limit)
        
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_incident(dict(r)) for r in rows]
    
    def update_incident(
        self,
        incident_id: str,
        updates: Dict[str, Any],
    ) -> Optional[Incident]:
        """Update an incident."""
        incident = self.get_incident(incident_id)
        if not incident:
            return None
        
        # Apply updates
        if "status" in updates:
            incident.status = IncidentStatus(updates["status"])
            incident.add_timeline_event(
                "status_change",
                f"Status changed to {incident.status.value}",
                updates.get("actor", "system"),
            )
        
        if "assigned_to" in updates:
            incident.assigned_to = updates["assigned_to"]
            incident.add_timeline_event(
                "assigned",
                f"Assigned to {incident.assigned_to}",
                updates.get("actor", "system"),
            )
        
        if "resolution_summary" in updates:
            incident.resolution_summary = updates["resolution_summary"]
        
        self._save_incident(incident)
        return incident
    
    def acknowledge_incident(
        self,
        incident_id: str,
        acknowledged_by: str,
    ) -> Optional[Incident]:
        """Acknowledge an incident."""
        incident = self.get_incident(incident_id)
        if not incident:
            return None
        
        now = datetime.now(timezone.utc)
        incident.status = IncidentStatus.ACKNOWLEDGED
        incident.acknowledged_at = now.isoformat()
        incident.acknowledged_by = acknowledged_by
        
        # Calculate TTA
        detected = datetime.fromisoformat(incident.detected_at.replace('Z', '+00:00'))
        incident.time_to_acknowledge_minutes = (now - detected).total_seconds() / 60
        
        incident.add_timeline_event(
            "acknowledged",
            f"Incident acknowledged by {acknowledged_by}",
            acknowledged_by,
        )
        
        self._save_incident(incident)
        logger.info(f"Incident {incident_id} acknowledged by {acknowledged_by}")
        
        return incident
    
    def resolve_incident(
        self,
        incident_id: str,
        resolved_by: str,
        resolution_summary: str,
    ) -> Optional[Incident]:
        """Resolve an incident."""
        incident = self.get_incident(incident_id)
        if not incident:
            return None
        
        now = datetime.now(timezone.utc)
        incident.status = IncidentStatus.RESOLVED
        incident.resolved_at = now.isoformat()
        incident.resolved_by = resolved_by
        incident.resolution_summary = resolution_summary
        
        # Calculate TTR
        detected = datetime.fromisoformat(incident.detected_at.replace('Z', '+00:00'))
        incident.time_to_resolve_minutes = (now - detected).total_seconds() / 60
        
        incident.add_timeline_event(
            "resolved",
            f"Incident resolved by {resolved_by}: {resolution_summary}",
            resolved_by,
        )
        
        self._save_incident(incident)
        logger.info(f"Incident {incident_id} resolved by {resolved_by}")
        
        # Cancel escalation timer
        if incident_id in self._escalation_tasks:
            self._escalation_tasks[incident_id].cancel()
            del self._escalation_tasks[incident_id]
        
        return incident
    
    def _save_incident(self, incident: Incident) -> None:
        """Save incident to database."""
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO incidents
                    (incident_id, title, description, priority, category, status,
                     detected_at, detected_by, detection_source, impact_summary,
                     affected_services, affected_users, financial_impact_usd,
                     acknowledged_at, acknowledged_by, assigned_to, escalation_level,
                     resolved_at, resolved_by, resolution_summary,
                     time_to_detect_minutes, time_to_acknowledge_minutes, time_to_resolve_minutes,
                     timeline, tags, related_incidents, playbook_id, rca_id, postmortem_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    incident.incident_id,
                    incident.title,
                    incident.description,
                    incident.priority.value,
                    incident.category.value,
                    incident.status.value,
                    incident.detected_at,
                    incident.detected_by,
                    incident.detection_source,
                    incident.impact_summary,
                    json.dumps(incident.affected_services),
                    incident.affected_users,
                    incident.financial_impact_usd,
                    incident.acknowledged_at,
                    incident.acknowledged_by,
                    incident.assigned_to,
                    incident.escalation_level.value,
                    incident.resolved_at,
                    incident.resolved_by,
                    incident.resolution_summary,
                    incident.time_to_detect_minutes,
                    incident.time_to_acknowledge_minutes,
                    incident.time_to_resolve_minutes,
                    json.dumps([t.to_dict() for t in incident.timeline]),
                    json.dumps(incident.tags),
                    json.dumps(incident.related_incidents),
                    incident.playbook_id,
                    incident.rca_id,
                    incident.postmortem_id,
                ))
    
    def _row_to_incident(self, row: Dict[str, Any]) -> Incident:
        """Convert database row to Incident."""
        timeline_data = json.loads(row.get("timeline") or "[]")
        
        return Incident(
            incident_id=row["incident_id"],
            title=row["title"],
            description=row.get("description", ""),
            priority=IncidentPriority(row["priority"]),
            category=IncidentCategory(row["category"]),
            status=IncidentStatus(row["status"]),
            detected_at=row["detected_at"],
            detected_by=row.get("detected_by", "system"),
            detection_source=row.get("detection_source", ""),
            impact_summary=row.get("impact_summary", ""),
            affected_services=json.loads(row.get("affected_services") or "[]"),
            affected_users=row.get("affected_users", 0),
            financial_impact_usd=row.get("financial_impact_usd", 0),
            acknowledged_at=row.get("acknowledged_at"),
            acknowledged_by=row.get("acknowledged_by"),
            assigned_to=row.get("assigned_to"),
            escalation_level=EscalationLevel(row.get("escalation_level", "L1")),
            resolved_at=row.get("resolved_at"),
            resolved_by=row.get("resolved_by"),
            resolution_summary=row.get("resolution_summary", ""),
            time_to_detect_minutes=row.get("time_to_detect_minutes", 0),
            time_to_acknowledge_minutes=row.get("time_to_acknowledge_minutes", 0),
            time_to_resolve_minutes=row.get("time_to_resolve_minutes", 0),
            timeline=[IncidentTimeline(**t) for t in timeline_data],
            tags=json.loads(row.get("tags") or "[]"),
            related_incidents=json.loads(row.get("related_incidents") or "[]"),
            playbook_id=row.get("playbook_id"),
            rca_id=row.get("rca_id"),
            postmortem_id=row.get("postmortem_id"),
        )
    
    # ═══════════════════════════════════════════════════════════════════
    # Escalation Management
    # ═══════════════════════════════════════════════════════════════════
    
    async def _start_escalation_timer(self, incident: Incident) -> None:
        """Start escalation timer for an incident."""
        policy = DEFAULT_ESCALATION_POLICIES.get(incident.priority, [])
        
        for rule in policy:
            if rule.trigger_minutes == 0:
                # Immediate notification
                await self._escalate(incident, rule)
            else:
                # Scheduled escalation
                task = asyncio.create_task(
                    self._scheduled_escalation(incident, rule)
                )
                self._escalation_tasks[incident.incident_id] = task
    
    async def _scheduled_escalation(
        self,
        incident: Incident,
        rule: EscalationRule,
    ) -> None:
        """Wait and escalate if not resolved."""
        try:
            await asyncio.sleep(rule.trigger_minutes * 60)
            
            # Check if still not resolved
            current = self.get_incident(incident.incident_id)
            if current and current.status not in [IncidentStatus.RESOLVED, IncidentStatus.CLOSED]:
                await self._escalate(current, rule)
        except asyncio.CancelledError:
            pass
    
    async def _escalate(self, incident: Incident, rule: EscalationRule) -> None:
        """Execute escalation."""
        incident.escalation_level = rule.level
        incident.add_timeline_event(
            "escalation",
            f"Escalated to {rule.level.value}: {rule.notify_roles}",
            "escalation_engine",
        )
        
        self._save_incident(incident)
        
        logger.warning(
            f"Incident {incident.incident_id} escalated to {rule.level.value}"
        )
        
        # Fire callbacks
        for callback in self._on_escalation:
            try:
                callback(incident, rule.level)
            except Exception as e:
                logger.error(f"Escalation callback error: {e}")
    
    # ═══════════════════════════════════════════════════════════════════
    # RCA Management
    # ═══════════════════════════════════════════════════════════════════
    
    def create_rca(
        self,
        incident_id: str,
        created_by: str,
    ) -> Optional[RootCauseAnalysis]:
        """Create RCA for an incident."""
        incident = self.get_incident(incident_id)
        if not incident:
            return None
        
        rca_id = f"RCA-{incident_id}"
        
        rca = RootCauseAnalysis(
            rca_id=rca_id,
            incident_id=incident_id,
            title=f"Root Cause Analysis: {incident.title}",
            status=RCAStatus.PENDING,
            created_by=created_by,
        )
        
        self._save_rca(rca)
        
        # Update incident
        incident.rca_id = rca_id
        self._save_incident(incident)
        
        logger.info(f"RCA created: {rca_id}")
        return rca
    
    def get_rca(self, rca_id: str) -> Optional[RootCauseAnalysis]:
        """Get RCA by ID."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM rcas WHERE rca_id = ?",
                (rca_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return self._row_to_rca(dict(row))
    
    def update_rca(
        self,
        rca_id: str,
        updates: Dict[str, Any],
    ) -> Optional[RootCauseAnalysis]:
        """Update RCA."""
        rca = self.get_rca(rca_id)
        if not rca:
            return None
        
        if "summary" in updates:
            rca.summary = updates["summary"]
        if "root_cause" in updates:
            rca.root_cause = updates["root_cause"]
        if "contributing_factors" in updates:
            rca.contributing_factors = updates["contributing_factors"]
        if "five_whys" in updates:
            rca.five_whys = [FiveWhyEntry(**w) for w in updates["five_whys"]]
        if "immediate_actions" in updates:
            rca.immediate_actions = updates["immediate_actions"]
        if "long_term_recommendations" in updates:
            rca.long_term_recommendations = updates["long_term_recommendations"]
        if "status" in updates:
            rca.status = RCAStatus(updates["status"])
        
        self._save_rca(rca)
        return rca
    
    def _save_rca(self, rca: RootCauseAnalysis) -> None:
        """Save RCA to database."""
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO rcas
                    (rca_id, incident_id, title, status, summary, root_cause,
                     contributing_factors, five_whys, fault_chain, evidence,
                     logs, metrics_snapshots, impact_assessment, blast_radius,
                     immediate_actions, long_term_recommendations,
                     created_at, created_by, reviewed_by, approved_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rca.rca_id,
                    rca.incident_id,
                    rca.title,
                    rca.status.value,
                    rca.summary,
                    rca.root_cause,
                    json.dumps(rca.contributing_factors),
                    json.dumps([w.to_dict() for w in rca.five_whys]),
                    json.dumps([n.to_dict() for n in rca.fault_chain]),
                    json.dumps(rca.evidence),
                    json.dumps(rca.logs),
                    json.dumps(rca.metrics_snapshots),
                    rca.impact_assessment,
                    json.dumps(rca.blast_radius),
                    json.dumps(rca.immediate_actions),
                    json.dumps(rca.long_term_recommendations),
                    rca.created_at,
                    rca.created_by,
                    rca.reviewed_by,
                    rca.approved_by,
                ))
    
    def _row_to_rca(self, row: Dict[str, Any]) -> RootCauseAnalysis:
        """Convert row to RCA."""
        five_whys = [FiveWhyEntry(**w) for w in json.loads(row.get("five_whys") or "[]")]
        fault_chain = [FaultChainNode(**n) for n in json.loads(row.get("fault_chain") or "[]")]
        
        return RootCauseAnalysis(
            rca_id=row["rca_id"],
            incident_id=row["incident_id"],
            title=row["title"],
            status=RCAStatus(row["status"]),
            summary=row.get("summary", ""),
            root_cause=row.get("root_cause", ""),
            contributing_factors=json.loads(row.get("contributing_factors") or "[]"),
            five_whys=five_whys,
            fault_chain=fault_chain,
            evidence=json.loads(row.get("evidence") or "{}"),
            logs=json.loads(row.get("logs") or "[]"),
            metrics_snapshots=json.loads(row.get("metrics_snapshots") or "[]"),
            impact_assessment=row.get("impact_assessment", ""),
            blast_radius=json.loads(row.get("blast_radius") or "[]"),
            immediate_actions=json.loads(row.get("immediate_actions") or "[]"),
            long_term_recommendations=json.loads(row.get("long_term_recommendations") or "[]"),
            created_at=row.get("created_at", ""),
            created_by=row.get("created_by", ""),
            reviewed_by=row.get("reviewed_by"),
            approved_by=row.get("approved_by"),
        )
    
    # ═══════════════════════════════════════════════════════════════════
    # Postmortem Management  
    # ═══════════════════════════════════════════════════════════════════
    
    def create_postmortem(
        self,
        incident_id: str,
        created_by: str,
    ) -> Optional[Postmortem]:
        """Create postmortem for an incident."""
        incident = self.get_incident(incident_id)
        if not incident:
            return None
        
        postmortem_id = f"PM-{incident_id}"
        
        postmortem = Postmortem(
            postmortem_id=postmortem_id,
            incident_id=incident_id,
            title=f"Postmortem: {incident.title}",
            status=PostmortemStatus.DRAFT,
            incident_summary=incident.description,
            detection_time=incident.detected_at,
            acknowledgement_time=incident.acknowledged_at or "",
            resolution_time=incident.resolved_at or "",
            total_duration_minutes=incident.time_to_resolve_minutes,
            created_by=created_by,
        )
        
        self._save_postmortem(postmortem)
        
        # Update incident
        incident.postmortem_id = postmortem_id
        self._save_incident(incident)
        
        logger.info(f"Postmortem created: {postmortem_id}")
        return postmortem
    
    def get_postmortem(self, postmortem_id: str) -> Optional[Postmortem]:
        """Get postmortem by ID."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM postmortems WHERE postmortem_id = ?",
                (postmortem_id,)
            ).fetchone()
            
            if not row:
                return None
            
            content = json.loads(row.get("content") or "{}")
            return Postmortem(
                postmortem_id=row["postmortem_id"],
                incident_id=row["incident_id"],
                title=row["title"],
                status=PostmortemStatus(row["status"]),
                created_at=row.get("created_at", ""),
                created_by=row.get("created_by", ""),
                published_at=row.get("published_at"),
                **content,
            )
    
    def _save_postmortem(self, postmortem: Postmortem) -> None:
        """Save postmortem to database."""
        content = {
            "executive_summary": postmortem.executive_summary,
            "incident_summary": postmortem.incident_summary,
            "detection_time": postmortem.detection_time,
            "acknowledgement_time": postmortem.acknowledgement_time,
            "mitigation_time": postmortem.mitigation_time,
            "resolution_time": postmortem.resolution_time,
            "total_duration_minutes": postmortem.total_duration_minutes,
            "impact_description": postmortem.impact_description,
            "customer_impact": postmortem.customer_impact,
            "financial_impact_usd": postmortem.financial_impact_usd,
            "sla_breached": postmortem.sla_breached,
            "root_cause_summary": postmortem.root_cause_summary,
            "what_went_well": postmortem.what_went_well,
            "what_went_wrong": postmortem.what_went_wrong,
            "lessons_learned": postmortem.lessons_learned,
            "action_items": [a.to_dict() for a in postmortem.action_items],
            "learning_tags": postmortem.learning_tags,
        }
        
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO postmortems
                    (postmortem_id, incident_id, title, status, content, created_at, created_by, published_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    postmortem.postmortem_id,
                    postmortem.incident_id,
                    postmortem.title,
                    postmortem.status.value,
                    json.dumps(content),
                    postmortem.created_at,
                    postmortem.created_by,
                    postmortem.published_at,
                ))
    
    # ═══════════════════════════════════════════════════════════════════
    # Playbook Management
    # ═══════════════════════════════════════════════════════════════════
    
    def _init_default_playbooks(self) -> None:
        """Initialize default playbooks."""
        playbooks = [
            self._create_high_error_rate_playbook(),
            self._create_model_drift_playbook(),
            self._create_system_down_playbook(),
            self._create_cost_overrun_playbook(),
        ]
        
        for playbook in playbooks:
            existing = self.get_playbook(playbook.playbook_id)
            if not existing:
                self.save_playbook(playbook)
                logger.info(f"Created default playbook: {playbook.name}")
    
    def _create_high_error_rate_playbook(self) -> Playbook:
        """Create high error rate playbook."""
        return Playbook(
            playbook_id="pb_high_error_rate",
            name="High Error Rate Response",
            description="Response procedure for high error rates",
            version="1.0",
            trigger_priority=[IncidentPriority.P1, IncidentPriority.P2],
            trigger_category=[IncidentCategory.SYSTEM, IncidentCategory.MODEL],
            trigger_keywords=["error rate", "failures", "exceptions"],
            steps=[
                PlaybookStep(
                    step_id="step_1",
                    step_number=1,
                    step_type=PlaybookStepType.CHECK,
                    title="Check Error Rate",
                    description="Verify current error rate from monitoring",
                    command="python -m backend.ops.scripts.check_error_rate",
                ),
                PlaybookStep(
                    step_id="step_2",
                    step_number=2,
                    step_type=PlaybookStepType.DECISION,
                    title="Evaluate Severity",
                    description="Determine if rate > 10%",
                    condition="error_rate > 0.10",
                    on_success_step="step_3",
                    on_failure_step="step_4",
                ),
                PlaybookStep(
                    step_id="step_3",
                    step_number=3,
                    step_type=PlaybookStepType.ROLLBACK,
                    title="Rollback to Last Good",
                    description="Rollback to last known good configuration",
                    command="python -m backend.ops.scripts.rollback --last-good",
                    requires_approval=True,
                ),
                PlaybookStep(
                    step_id="step_4",
                    step_number=4,
                    step_type=PlaybookStepType.NOTIFY,
                    title="Alert Team",
                    description="Notify on-call team",
                ),
            ],
        )
    
    def _create_model_drift_playbook(self) -> Playbook:
        """Create model drift playbook."""
        return Playbook(
            playbook_id="pb_model_drift",
            name="Model Drift Response",
            description="Response procedure for model drift alerts",
            version="1.0",
            trigger_priority=[IncidentPriority.P2],
            trigger_category=[IncidentCategory.MODEL],
            trigger_keywords=["drift", "model performance", "accuracy"],
            steps=[
                PlaybookStep(
                    step_id="step_1",
                    step_number=1,
                    step_type=PlaybookStepType.CHECK,
                    title="Validate Drift Score",
                    description="Check drift metrics",
                    command="python -m backend.ops.scripts.check_drift",
                ),
                PlaybookStep(
                    step_id="step_2",
                    step_number=2,
                    step_type=PlaybookStepType.COMMAND,
                    title="Enable Caching",
                    description="Switch to cached model responses",
                    command="python -m backend.ops.scripts.enable_cache_mode",
                ),
                PlaybookStep(
                    step_id="step_3",
                    step_number=3,
                    step_type=PlaybookStepType.MANUAL,
                    title="Evaluate Retrain",
                    description="Determine if model needs retraining",
                    requires_approval=True,
                    approval_roles=["ml_engineer", "data_scientist"],
                ),
            ],
        )
    
    def _create_system_down_playbook(self) -> Playbook:
        """Create system down (P0) playbook."""
        return Playbook(
            playbook_id="pb_system_down",
            name="System Down Emergency Response",
            description="Emergency response for total system outage",
            version="1.0",
            trigger_priority=[IncidentPriority.P0],
            trigger_category=[IncidentCategory.SYSTEM],
            trigger_keywords=["down", "outage", "unavailable"],
            steps=[
                PlaybookStep(
                    step_id="step_1",
                    step_number=1,
                    step_type=PlaybookStepType.NOTIFY,
                    title="Emergency Alert",
                    description="Page all on-call and leadership",
                ),
                PlaybookStep(
                    step_id="step_2",
                    step_number=2,
                    step_type=PlaybookStepType.CHECK,
                    title="Check Infrastructure",
                    description="Verify infrastructure health",
                    command="python -m backend.ops.scripts.check_infra",
                ),
                PlaybookStep(
                    step_id="step_3",
                    step_number=3,
                    step_type=PlaybookStepType.COMMAND,
                    title="Activate DR",
                    description="Activate disaster recovery procedures",
                    command="python -m backend.ops.scripts.activate_dr",
                    requires_approval=True,
                    approval_roles=["engineering_manager"],
                ),
            ],
            auto_execute=True,
            max_auto_steps=2,
        )
    
    def _create_cost_overrun_playbook(self) -> Playbook:
        """Create cost overrun playbook."""
        return Playbook(
            playbook_id="pb_cost_overrun",
            name="Cost Overrun Response",
            description="Response procedure for budget limit breaches",
            version="1.0",
            trigger_priority=[IncidentPriority.P1, IncidentPriority.P2],
            trigger_category=[IncidentCategory.COST],
            trigger_keywords=["budget", "cost", "spending", "overrun"],
            steps=[
                PlaybookStep(
                    step_id="step_1",
                    step_number=1,
                    step_type=PlaybookStepType.CHECK,
                    title="Check Budget Status",
                    description="Get current budget utilization",
                    command="python -m backend.ops.scripts.check_budget",
                ),
                PlaybookStep(
                    step_id="step_2",
                    step_number=2,
                    step_type=PlaybookStepType.COMMAND,
                    title="Throttle Services",
                    description="Enable cost throttling",
                    command="python -m backend.ops.scripts.throttle_costs",
                ),
                PlaybookStep(
                    step_id="step_3",
                    step_number=3,
                    step_type=PlaybookStepType.ESCALATE,
                    title="Escalate to Finance",
                    description="Notify finance team for budget review",
                ),
            ],
        )
    
    def get_playbook(self, playbook_id: str) -> Optional[Playbook]:
        """Get playbook by ID."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM playbooks WHERE playbook_id = ?",
                (playbook_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return self._row_to_playbook(dict(row))
    
    def list_playbooks(self, enabled_only: bool = True) -> List[Playbook]:
        """List all playbooks."""
        query = "SELECT * FROM playbooks"
        if enabled_only:
            query += " WHERE enabled = 1"
        
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query).fetchall()
            return [self._row_to_playbook(dict(r)) for r in rows]
    
    def save_playbook(self, playbook: Playbook) -> None:
        """Save playbook to database."""
        with self._lock:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO playbooks
                    (playbook_id, name, description, version, trigger_priority,
                     trigger_category, trigger_keywords, steps, auto_execute,
                     max_auto_steps, requires_approval, created_at, updated_at,
                     created_by, enabled)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    playbook.playbook_id,
                    playbook.name,
                    playbook.description,
                    playbook.version,
                    json.dumps([p.value for p in playbook.trigger_priority]),
                    json.dumps([c.value for c in playbook.trigger_category]),
                    json.dumps(playbook.trigger_keywords),
                    json.dumps([s.to_dict() for s in playbook.steps]),
                    1 if playbook.auto_execute else 0,
                    playbook.max_auto_steps,
                    1 if playbook.requires_approval else 0,
                    playbook.created_at,
                    playbook.updated_at,
                    playbook.created_by,
                    1 if playbook.enabled else 0,
                ))
    
    def _row_to_playbook(self, row: Dict[str, Any]) -> Playbook:
        """Convert row to Playbook."""
        steps_data = json.loads(row.get("steps") or "[]")
        steps = []
        for s in steps_data:
            steps.append(PlaybookStep(
                step_id=s["step_id"],
                step_number=s["step_number"],
                step_type=PlaybookStepType(s["step_type"]),
                title=s["title"],
                description=s["description"],
                command=s.get("command"),
                expected_output=s.get("expected_output"),
                timeout_seconds=s.get("timeout_seconds", 300),
                condition=s.get("condition"),
                on_success_step=s.get("on_success_step"),
                on_failure_step=s.get("on_failure_step"),
                requires_approval=s.get("requires_approval", False),
                approval_roles=s.get("approval_roles", []),
            ))
        
        return Playbook(
            playbook_id=row["playbook_id"],
            name=row["name"],
            description=row.get("description", ""),
            version=row.get("version", "1.0"),
            trigger_priority=[IncidentPriority(p) for p in json.loads(row.get("trigger_priority") or "[]")],
            trigger_category=[IncidentCategory(c) for c in json.loads(row.get("trigger_category") or "[]")],
            trigger_keywords=json.loads(row.get("trigger_keywords") or "[]"),
            steps=steps,
            auto_execute=bool(row.get("auto_execute", 1)),
            max_auto_steps=row.get("max_auto_steps", 5),
            requires_approval=bool(row.get("requires_approval", 0)),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
            created_by=row.get("created_by", ""),
            enabled=bool(row.get("enabled", 1)),
        )
    
    # ═══════════════════════════════════════════════════════════════════
    # Dashboard & Stats
    # ═══════════════════════════════════════════════════════════════════
    
    def get_incident_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get incident statistics."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        with sqlite3.connect(str(self._db_path)) as conn:
            # Total incidents
            total = conn.execute(
                "SELECT COUNT(*) FROM incidents WHERE detected_at >= ?",
                (cutoff,)
            ).fetchone()[0]
            
            # By priority
            by_priority = {}
            for p in IncidentPriority:
                count = conn.execute(
                    "SELECT COUNT(*) FROM incidents WHERE detected_at >= ? AND priority = ?",
                    (cutoff, p.value)
                ).fetchone()[0]
                by_priority[p.value] = count
            
            # By status
            by_status = {}
            for s in IncidentStatus:
                count = conn.execute(
                    "SELECT COUNT(*) FROM incidents WHERE detected_at >= ? AND status = ?",
                    (cutoff, s.value)
                ).fetchone()[0]
                by_status[s.value] = count
            
            # MTTR (Mean Time To Resolve)
            resolved = conn.execute("""
                SELECT AVG(time_to_resolve_minutes)
                FROM incidents
                WHERE detected_at >= ? AND resolved_at IS NOT NULL
            """, (cutoff,)).fetchone()[0] or 0
            
            # MTTA (Mean Time To Acknowledge)
            mtta = conn.execute("""
                SELECT AVG(time_to_acknowledge_minutes)
                FROM incidents
                WHERE detected_at >= ? AND acknowledged_at IS NOT NULL
            """, (cutoff,)).fetchone()[0] or 0
        
        return {
            "period_days": days,
            "total_incidents": total,
            "by_priority": by_priority,
            "by_status": by_status,
            "mttr_minutes": round(resolved, 2),
            "mtta_minutes": round(mtta, 2),
            "active_incidents": by_status.get("detected", 0) + by_status.get("investigating", 0),
        }


# ═══════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════

_incident_manager: Optional[IncidentManager] = None


def get_incident_manager() -> IncidentManager:
    """Get singleton IncidentManager instance."""
    global _incident_manager
    if _incident_manager is None:
        _incident_manager = IncidentManager()
    return _incident_manager

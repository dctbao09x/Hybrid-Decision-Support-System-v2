# backend/ops/maintenance/audit_trail.py
"""
Audit Trail for governance and compliance.

Tracks:
- All pipeline operations
- Data lineage
- Configuration changes
- User actions
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.maintenance.audit")


class AuditEvent:
    """A single audit trail event."""

    def __init__(
        self,
        event_type: str,
        category: str,
        description: str,
        actor: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.event_type = event_type
        self.category = category
        self.description = description
        self.actor = actor
        self.metadata = metadata or {}
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "category": self.category,
            "description": self.description,
            "actor": self.actor,
            "metadata": self.metadata,
        }


class AuditTrail:
    """
    Immutable audit trail for governance compliance.

    Categories:
    - pipeline: Pipeline execution events
    - data: Data access and modification
    - config: Configuration changes
    - security: Security-related events
    - maintenance: System maintenance events
    """

    CATEGORIES = ["pipeline", "data", "config", "security", "maintenance"]

    def __init__(
        self,
        log_dir: Optional[Path] = None,
        max_memory_events: int = 10000,
    ):
        self.log_dir = log_dir or Path("backend/data/logs/audit")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._events: List[AuditEvent] = []
        self._max_events = max_memory_events

    def record(
        self,
        event_type: str,
        category: str,
        description: str,
        actor: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record an audit event."""
        event = AuditEvent(
            event_type=event_type,
            category=category,
            description=description,
            actor=actor,
            metadata=metadata,
        )

        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]

        self._persist(event)

    def record_pipeline_run(
        self, run_id: str, status: str, stages: int = 0, duration: float = 0.0,
    ) -> None:
        self.record(
            "pipeline_run", "pipeline",
            f"Pipeline run {run_id} completed with status '{status}'",
            metadata={"run_id": run_id, "status": status, "stages": stages, "duration_s": duration},
        )

    def record_data_change(
        self, dataset: str, action: str, records: int = 0,
    ) -> None:
        self.record(
            "data_change", "data",
            f"Dataset '{dataset}' {action}: {records} records",
            metadata={"dataset": dataset, "action": action, "records": records},
        )

    def record_config_change(
        self, config_key: str, old_value: Any = None, new_value: Any = None,
    ) -> None:
        self.record(
            "config_change", "config",
            f"Configuration '{config_key}' changed",
            metadata={"key": config_key, "old_value": str(old_value), "new_value": str(new_value)},
        )

    def record_deployment(
        self, version: str, component: str = "pipeline",
    ) -> None:
        self.record(
            "deployment", "maintenance",
            f"Deployed {component} version {version}",
            metadata={"version": version, "component": component},
        )

    def query(
        self,
        category: Optional[str] = None,
        event_type: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query audit trail events."""
        results = []
        for event in reversed(self._events):
            if category and event.category != category:
                continue
            if event_type and event.event_type != event_type:
                continue
            if start_time and event.timestamp < start_time:
                continue
            if end_time and event.timestamp > end_time:
                continue
            results.append(event.to_dict())
            if len(results) >= limit:
                break
        return results

    def get_summary(
        self,
        hours: int = 24,
    ) -> Dict[str, Any]:
        """Get audit trail summary for last N hours."""
        cutoff = datetime.now().isoformat()
        # Simple: just count recent events from memory
        counts: Dict[str, int] = {}
        for event in self._events:
            key = f"{event.category}.{event.event_type}"
            counts[key] = counts.get(key, 0) + 1

        return {
            "total_events": len(self._events),
            "event_counts": counts,
            "categories": {
                cat: sum(1 for e in self._events if e.category == cat)
                for cat in self.CATEGORIES
            },
        }

    def _persist(self, event: AuditEvent) -> None:
        """Write event to daily log file."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = self.log_dir / f"audit_{date_str}.jsonl"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except Exception as e:
            logger.error(f"Failed to persist audit event: {e}")

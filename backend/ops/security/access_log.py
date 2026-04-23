# backend/ops/security/access_log.py
"""
Access Logging for pipeline operations.

Tracks:
- API access
- Pipeline operations
- Data access patterns
- Admin actions
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.security.access")


class AccessEntry:
    """A single access log entry."""

    def __init__(
        self,
        action: str,
        actor: str = "system",
        resource: str = "",
        details: Optional[Dict[str, Any]] = None,
        ip_address: str = "",
        status: str = "success",
    ):
        self.action = action
        self.actor = actor
        self.resource = resource
        self.details = details or {}
        self.ip_address = ip_address
        self.status = status
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "action": self.action,
            "actor": self.actor,
            "resource": self.resource,
            "ip_address": self.ip_address,
            "status": self.status,
            "details": self.details,
        }


class AccessLogger:
    """
    Structured access logging for audit trails.

    All pipeline operations are logged with:
    - Who (actor)
    - What (action)
    - When (timestamp)
    - Where (resource)
    - How (details)
    - Result (status)
    """

    def __init__(
        self,
        log_path: Optional[Path] = None,
        max_memory_entries: int = 5000,
    ):
        self.log_path = log_path or Path("backend/data/logs/access.jsonl")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: List[AccessEntry] = []
        self._max_entries = max_memory_entries

    def log(
        self,
        action: str,
        actor: str = "system",
        resource: str = "",
        details: Optional[Dict[str, Any]] = None,
        ip_address: str = "",
        status: str = "success",
    ) -> None:
        """Log an access event."""
        entry = AccessEntry(
            action=action,
            actor=actor,
            resource=resource,
            details=details,
            ip_address=ip_address,
            status=status,
        )

        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]

        # Write to file
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")
        except Exception as e:
            logger.error(f"Failed to write access log: {e}")

    def log_pipeline_start(self, run_id: str, trigger: str = "manual") -> None:
        self.log("pipeline_start", resource=run_id, details={"trigger": trigger})

    def log_pipeline_complete(self, run_id: str, status: str = "success") -> None:
        self.log("pipeline_complete", resource=run_id, status=status)

    def log_crawl_start(self, site: str) -> None:
        self.log("crawl_start", resource=site)

    def log_crawl_complete(self, site: str, records: int) -> None:
        self.log("crawl_complete", resource=site, details={"records": records})

    def log_data_access(self, dataset: str, action: str = "read") -> None:
        self.log("data_access", resource=dataset, details={"data_action": action})

    def log_config_change(self, key: str, old_value: str = "", new_value: str = "") -> None:
        self.log(
            "config_change",
            resource=key,
            details={"old": old_value, "new": new_value},
        )

    def log_rollback(self, run_id: str, target_stage: str) -> None:
        self.log("rollback", resource=run_id, details={"target_stage": target_stage})

    def get_recent(
        self,
        limit: int = 100,
        action: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent access log entries."""
        entries = self._entries
        if action:
            entries = [e for e in entries if e.action == action]
        if actor:
            entries = [e for e in entries if e.actor == actor]
        return [e.to_dict() for e in entries[-limit:]]

    def search(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        action: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search access logs."""
        results = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if action and entry.get("action") != action:
                            continue
                        if start_time and entry.get("timestamp", "") < start_time:
                            continue
                        if end_time and entry.get("timestamp", "") > end_time:
                            continue
                        results.append(entry)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            pass
        return results

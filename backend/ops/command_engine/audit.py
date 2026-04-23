# backend/ops/command_engine/audit.py
"""
Command Audit Logger
====================

Records all command operations for compliance and traceability.

Features:
- Structured audit entries
- File-based persistence
- Query capabilities
- Retention management
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Command, CommandResult, CommandState

logger = logging.getLogger("ops.command_engine.audit")


@dataclass
class AuditEntry:
    """Structured audit log entry."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # User context
    user_id: str = ""
    role: str = ""
    session_id: Optional[str] = None
    ip_address: Optional[str] = None
    
    # Action details
    action: str = ""
    target: str = ""
    target_type: str = ""
    
    # Command reference
    command_id: Optional[str] = None
    command_type: Optional[str] = None
    
    # Result
    result: str = ""  # success, failure, pending
    error: Optional[str] = None
    error_code: Optional[str] = None
    
    # Tracing
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_trace_id: Optional[str] = None
    prev_hash: str = ""
    entry_hash: str = ""
    
    # Additional context
    metadata: Dict[str, Any] = field(default_factory=dict)
    changes: Dict[str, Any] = field(default_factory=dict)  # Before/after values
    
    # Timing
    duration_ms: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditEntry":
        """Create from dictionary."""
        return cls(**data)


class CommandAudit:
    """
    Audit logger for command operations.
    
    Features:
    - Persistent audit log
    - Structured entries
    - Query capabilities
    - Retention management
    """
    
    def __init__(
        self,
        log_dir: str = "logs/admin_ops",
        retention_days: int = 90,
        max_file_size_mb: int = 100,
    ):
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        
        self._retention_days = retention_days
        self._max_file_size_mb = max_file_size_mb
        
        # Current log file
        self._current_log_file: Optional[Path] = None
        self._current_file_size = 0
        
        # In-memory cache for recent entries
        self._recent_entries: List[AuditEntry] = []
        self._max_cache_size = 1000
        
        # Initialize log file
        self._last_hash = "GENESIS"
        self._rotate_if_needed()
    
    def log_command_initiated(
        self,
        command: Command,
        ip_address: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AuditEntry:
        """Log when a command is initiated."""
        entry = AuditEntry(
            user_id=command.user_id,
            role=command.role,
            session_id=session_id,
            ip_address=ip_address,
            action="command_initiated",
            target=command.target,
            target_type=command.type if isinstance(command.type, str) else command.type.value,
            command_id=command.id,
            command_type=command.type if isinstance(command.type, str) else command.type.value,
            result="pending",
            trace_id=command.trace_id,
            metadata={
                "params": command.params,
                "priority": command.priority if isinstance(command.priority, str) else command.priority.value,
                "environment": command.environment,
                "dry_run": command.dry_run,
            },
        )
        
        self._write_entry(entry)
        return entry
    
    def log_command_completed(
        self,
        command: Command,
        result: CommandResult,
    ) -> AuditEntry:
        """Log when a command completes."""
        entry = AuditEntry(
            user_id=command.user_id,
            role=command.role,
            action="command_completed",
            target=command.target,
            target_type=command.type if isinstance(command.type, str) else command.type.value,
            command_id=command.id,
            command_type=command.type if isinstance(command.type, str) else command.type.value,
            result="success" if result.success else "failure",
            error=result.error,
            error_code=result.error_code,
            trace_id=command.trace_id,
            duration_ms=result.duration_ms,
            metadata={
                "state": result.state if isinstance(result.state, str) else result.state.value,
                "data": result.data,
                "rollback_available": result.rollback_available,
            },
        )
        
        self._write_entry(entry)
        return entry
    
    def log_command_state_change(
        self,
        command: Command,
        from_state: CommandState,
        to_state: CommandState,
        reason: Optional[str] = None,
    ) -> AuditEntry:
        """Log command state transitions."""
        entry = AuditEntry(
            user_id=command.user_id,
            role=command.role,
            action="command_state_change",
            target=command.target,
            target_type=command.type if isinstance(command.type, str) else command.type.value,
            command_id=command.id,
            command_type=command.type if isinstance(command.type, str) else command.type.value,
            result="success",
            trace_id=command.trace_id,
            changes={
                "from_state": from_state if isinstance(from_state, str) else from_state.value,
                "to_state": to_state if isinstance(to_state, str) else to_state.value,
            },
            metadata={
                "reason": reason,
            },
        )
        
        self._write_entry(entry)
        return entry
    
    def log_action(
        self,
        user_id: str,
        role: str,
        action: str,
        target: str,
        target_type: str,
        result: str,
        trace_id: Optional[str] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        """Log a generic action."""
        entry = AuditEntry(
            user_id=user_id,
            role=role,
            action=action,
            target=target,
            target_type=target_type,
            result=result,
            trace_id=trace_id or str(uuid.uuid4()),
            error=error,
            metadata=metadata or {},
        )
        
        self._write_entry(entry)
        return entry
    
    def query(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        target: Optional[str] = None,
        result: Optional[str] = None,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[AuditEntry]:
        """
        Query audit entries.
        
        Args:
            user_id: Filter by user ID
            action: Filter by action type
            target: Filter by target (contains)
            result: Filter by result
            from_time: Start time filter
            to_time: End time filter
            limit: Maximum entries to return
            
        Returns:
            List of matching audit entries
        """
        results = []
        
        # Read from log files
        log_files = sorted(self._log_dir.glob("audit_*.jsonl"), reverse=True)
        
        for log_file in log_files:
            if len(results) >= limit:
                break
                
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if len(results) >= limit:
                            break
                            
                        try:
                            data = json.loads(line.strip())
                            entry = AuditEntry.from_dict(data)
                            
                            # Apply filters
                            if user_id and entry.user_id != user_id:
                                continue
                            if action and entry.action != action:
                                continue
                            if target and target not in entry.target:
                                continue
                            if result and entry.result != result:
                                continue
                            if from_time:
                                entry_time = datetime.fromisoformat(entry.timestamp.replace("Z", "+00:00"))
                                if entry_time < from_time:
                                    continue
                            if to_time:
                                entry_time = datetime.fromisoformat(entry.timestamp.replace("Z", "+00:00"))
                                if entry_time > to_time:
                                    continue
                            
                            results.append(entry)
                            
                        except (json.JSONDecodeError, KeyError):
                            continue
                            
            except Exception as e:
                logger.error(f"Error reading audit log {log_file}: {e}")
        
        return results
    
    def get_recent(self, count: int = 100) -> List[AuditEntry]:
        """Get recent audit entries from cache."""
        return list(reversed(self._recent_entries[-count:]))
    
    def get_by_trace_id(self, trace_id: str) -> List[AuditEntry]:
        """Get all entries for a trace ID."""
        return self.query(limit=1000)  # Search all, filter by trace
    
    def cleanup_old_logs(self):
        """Remove audit logs older than retention period."""
        cutoff = datetime.utcnow() - timedelta(days=self._retention_days)
        
        for log_file in self._log_dir.glob("audit_*.jsonl"):
            try:
                # Parse date from filename: audit_YYYYMMDD_HHMMSS.jsonl
                date_str = log_file.stem.split("_")[1]
                file_date = datetime.strptime(date_str, "%Y%m%d")
                
                if file_date < cutoff:
                    log_file.unlink()
                    logger.info(f"Deleted old audit log: {log_file}")
                    
            except (IndexError, ValueError):
                continue
    
    def get_stats(self) -> Dict[str, Any]:
        """Get audit statistics."""
        total_entries = 0
        total_size = 0
        oldest_entry = None
        newest_entry = None
        
        log_files = list(self._log_dir.glob("audit_*.jsonl"))
        
        for log_file in log_files:
            stat = log_file.stat()
            total_size += stat.st_size
            
            # Count lines
            with open(log_file, "r", encoding="utf-8") as f:
                total_entries += sum(1 for _ in f)
        
        return {
            "total_entries": total_entries,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "log_files": len(log_files),
            "retention_days": self._retention_days,
            "cache_size": len(self._recent_entries),
        }
    
    def _write_entry(self, entry: AuditEntry):
        """Write an entry to the audit log."""
        self._rotate_if_needed()

        entry.prev_hash = self._last_hash
        hash_payload = {
            "id": entry.id,
            "timestamp": entry.timestamp,
            "user_id": entry.user_id,
            "role": entry.role,
            "action": entry.action,
            "target": entry.target,
            "target_type": entry.target_type,
            "command_id": entry.command_id,
            "command_type": entry.command_type,
            "result": entry.result,
            "error": entry.error,
            "error_code": entry.error_code,
            "trace_id": entry.trace_id,
            "parent_trace_id": entry.parent_trace_id,
            "metadata": entry.metadata,
            "changes": entry.changes,
            "duration_ms": entry.duration_ms,
            "prev_hash": entry.prev_hash,
        }
        canonical = json.dumps(hash_payload, sort_keys=True, ensure_ascii=False)
        entry.entry_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        
        # Write to file
        try:
            with open(self._current_log_file, "a", encoding="utf-8") as f:
                line = json.dumps(entry.to_dict()) + "\n"
                f.write(line)
                self._current_file_size += len(line.encode("utf-8"))
                self._last_hash = entry.entry_hash
                self._write_daily_checksum(entry.entry_hash)
                
        except Exception as e:
            logger.error(f"Failed to write audit entry: {e}")
        
        # Add to cache
        self._recent_entries.append(entry)
        if len(self._recent_entries) > self._max_cache_size:
            self._recent_entries = self._recent_entries[-self._max_cache_size:]

    def _write_daily_checksum(self, entry_hash: str):
        date_key = datetime.utcnow().strftime("%Y%m%d")
        checksum_file = self._log_dir / f"audit_checksum_{date_key}.sha256"
        prev = "GENESIS"
        if checksum_file.exists():
            try:
                with open(checksum_file, "r", encoding="utf-8") as f:
                    lines = [line.strip() for line in f if line.strip()]
                    if lines:
                        prev = lines[-1]
            except Exception:
                prev = "GENESIS"
        chained = hashlib.sha256(f"{prev}:{entry_hash}".encode("utf-8")).hexdigest()
        with open(checksum_file, "a", encoding="utf-8") as f:
            f.write(chained + "\n")
    
    def _rotate_if_needed(self):
        """Rotate log file if needed."""
        should_rotate = (
            self._current_log_file is None or
            not self._current_log_file.exists() or
            self._current_file_size >= self._max_file_size_mb * 1024 * 1024
        )
        
        if should_rotate:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            self._current_log_file = self._log_dir / f"audit_{timestamp}.jsonl"
            self._current_file_size = 0
            logger.info(f"Rotated to new audit log: {self._current_log_file}")

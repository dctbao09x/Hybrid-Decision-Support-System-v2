# backend/scoring/security/audit.py
"""
Control Trace Audit Logging
===========================

GĐ2 PHẦN H: Audit Logging

Provides immutable (append-only) audit logging for:
- Request tracing
- Token validation
- Weight version used
- Latency tracking
- Security events

Log format:
[CONTROL_TRACE] request_id=X caller=Y token_hash=Z weight_version=W latency=L
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("scoring.security.audit")

# Audit log file path
AUDIT_LOG_DIR = Path("control_enforcement")
AUDIT_LOG_FILE = AUDIT_LOG_DIR / "control_trace.log"


@dataclass
class ControlTraceEntry:
    """Single audit log entry."""
    timestamp: str
    request_id: str
    caller: str
    caller_module: str
    token_hash: str
    weight_version: str
    operation: str
    latency_ms: float
    status: str  # SUCCESS, BLOCKED, ERROR
    details: Optional[Dict[str, Any]] = None
    
    def to_log_line(self) -> str:
        """Format as log line."""
        parts = [
            f"[CONTROL_TRACE]",
            f"ts={self.timestamp}",
            f"req={self.request_id}",
            f"caller={self.caller}",
            f"module={self.caller_module}",
            f"token={self.token_hash[:16] if self.token_hash else 'NONE'}",
            f"weights={self.weight_version}",
            f"op={self.operation}",
            f"latency={self.latency_ms:.2f}ms",
            f"status={self.status}",
        ]
        if self.details:
            parts.append(f"details={json.dumps(self.details)}")
        return " ".join(parts)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return asdict(self)


class ControlTraceLogger:
    """
    Audit logger for control trace.
    
    Features:
    - Append-only log file
    - Thread-safe
    - In-memory buffer for recent entries
    - Structured logging
    """
    
    _instance: Optional['ControlTraceLogger'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._entries: List[ControlTraceEntry] = []
        self._file_lock = threading.Lock()
        self._max_memory_entries = 1000
        
        # Ensure log directory exists
        AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        
        self._initialized = True
    
    def log(
        self,
        request_id: str,
        caller: str,
        caller_module: str,
        token_hash: str,
        weight_version: str,
        operation: str,
        latency_ms: float,
        status: str,
        details: Optional[Dict] = None,
    ) -> ControlTraceEntry:
        """
        Log control trace entry.
        
        Args:
            request_id: Unique request ID
            caller: Calling function name
            caller_module: Calling module name
            token_hash: Hash of control token
            weight_version: Weight version used
            operation: Operation performed
            latency_ms: Operation latency in ms
            status: SUCCESS, BLOCKED, ERROR
            details: Additional details
        
        Returns:
            Created log entry
        """
        entry = ControlTraceEntry(
            timestamp=datetime.utcnow().isoformat(),
            request_id=request_id,
            caller=caller,
            caller_module=caller_module,
            token_hash=token_hash or "",
            weight_version=weight_version,
            operation=operation,
            latency_ms=latency_ms,
            status=status,
            details=details,
        )
        
        # Add to memory buffer
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._max_memory_entries:
                self._entries.pop(0)
        
        # Write to log file
        self._write_to_file(entry)
        
        # Also log via standard logging
        logger.info(entry.to_log_line())
        
        return entry
    
    def _write_to_file(self, entry: ControlTraceEntry) -> None:
        """Write entry to log file (append-only)."""
        try:
            with self._file_lock:
                with open(AUDIT_LOG_FILE, "a") as f:
                    f.write(entry.to_log_line() + "\n")
        except Exception as e:
            logger.error(f"[AUDIT] Failed to write to file: {e}")
    
    def get_entries(
        self,
        limit: int = 100,
        request_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[ControlTraceEntry]:
        """
        Get audit entries from memory buffer.
        
        Args:
            limit: Max entries to return
            request_id: Filter by request ID
            status: Filter by status
        
        Returns:
            List of entries
        """
        with self._lock:
            entries = list(self._entries)
        
        # Apply filters
        if request_id:
            entries = [e for e in entries if e.request_id == request_id]
        if status:
            entries = [e for e in entries if e.status == status]
        
        return entries[-limit:]
    
    def get_blocked_entries(self, limit: int = 50) -> List[ControlTraceEntry]:
        """Get blocked/failed entries."""
        return self.get_entries(limit=limit, status="BLOCKED")
    
    def export_json(self, path: Optional[Path] = None) -> str:
        """Export entries as JSON."""
        path = path or (AUDIT_LOG_DIR / "audit_export.json")
        
        with self._lock:
            data = [e.to_dict() for e in self._entries]
        
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        
        return str(path)


# Global logger instance
_trace_logger: Optional[ControlTraceLogger] = None


def get_trace_logger() -> ControlTraceLogger:
    """Get global trace logger."""
    global _trace_logger
    if _trace_logger is None:
        _trace_logger = ControlTraceLogger()
    return _trace_logger


def log_control_trace(
    request_id: str,
    caller: str,
    caller_module: str,
    token_hash: str,
    weight_version: str,
    operation: str,
    latency_ms: float,
    status: str,
    details: Optional[Dict] = None,
) -> ControlTraceEntry:
    """Convenience function to log control trace."""
    return get_trace_logger().log(
        request_id=request_id,
        caller=caller,
        caller_module=caller_module,
        token_hash=token_hash,
        weight_version=weight_version,
        operation=operation,
        latency_ms=latency_ms,
        status=status,
        details=details,
    )


class ControlTraceContext:
    """
    Context manager for tracing operations.
    
    Usage:
        with ControlTraceContext(request_id, operation) as ctx:
            # do work
            ctx.set_weight_version("v1")
        # Automatically logs on exit with latency
    """
    
    def __init__(
        self,
        request_id: str,
        operation: str,
        caller: str = "unknown",
        caller_module: str = "unknown",
        token_hash: str = "",
    ):
        self.request_id = request_id
        self.operation = operation
        self.caller = caller
        self.caller_module = caller_module
        self.token_hash = token_hash
        self.weight_version = "unknown"
        self.status = "SUCCESS"
        self.details: Dict = {}
        self._start_time: float = 0
    
    def __enter__(self):
        self._start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        latency_ms = (time.perf_counter() - self._start_time) * 1000
        
        if exc_type is not None:
            self.status = "ERROR"
            self.details["error"] = str(exc_val)
        
        log_control_trace(
            request_id=self.request_id,
            caller=self.caller,
            caller_module=self.caller_module,
            token_hash=self.token_hash,
            weight_version=self.weight_version,
            operation=self.operation,
            latency_ms=latency_ms,
            status=self.status,
            details=self.details if self.details else None,
        )
        
        return False  # Don't suppress exceptions
    
    def set_weight_version(self, version: str) -> None:
        """Set weight version used."""
        self.weight_version = version
    
    def set_token_hash(self, token_hash: str) -> None:
        """Set token hash."""
        self.token_hash = token_hash
    
    def add_detail(self, key: str, value: Any) -> None:
        """Add detail to log entry."""
        self.details[key] = value
    
    def mark_blocked(self, reason: str) -> None:
        """Mark operation as blocked."""
        self.status = "BLOCKED"
        self.details["block_reason"] = reason

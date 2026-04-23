# backend/ops/command_engine/models.py
"""
Command Engine Data Models
==========================

Core data structures for command execution pipeline.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CommandState(str, Enum):
    """State machine for command execution."""
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    VALIDATING = "validating"
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    RECOVERING = "recovering"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class CommandType(str, Enum):
    """Types of operational commands."""
    # Crawler commands
    CRAWLER_START = "crawler_start"
    CRAWLER_STOP = "crawler_stop"
    CRAWLER_KILL = "crawler_kill"
    CRAWLER_PAUSE = "crawler_pause"
    CRAWLER_RESUME = "crawler_resume"
    
    # Job commands
    JOB_PAUSE = "job_pause"
    JOB_RESUME = "job_resume"
    JOB_CANCEL = "job_cancel"
    JOB_RETRY = "job_retry"
    
    # KB commands
    KB_ROLLBACK = "kb_rollback"
    KB_REBUILD = "kb_rebuild"
    KB_SYNC = "kb_sync"
    
    # MLOps commands
    MLOPS_FREEZE = "mlops_freeze"
    MLOPS_UNFREEZE = "mlops_unfreeze"
    MLOPS_RETRAIN = "mlops_retrain"
    MLOPS_ROLLBACK = "mlops_rollback"
    
    # System commands
    SYSTEM_BACKUP = "system_backup"
    SYSTEM_RESTORE = "system_restore"
    SYSTEM_MAINTENANCE = "system_maintenance"
    
    # Custom
    CUSTOM = "custom"


class CommandPriority(str, Enum):
    """Command execution priority."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class Command(BaseModel):
    """Command execution request."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: CommandType
    target: str  # Target resource identifier
    params: Dict[str, Any] = Field(default_factory=dict)
    
    # Execution control
    idempotency_key: Optional[str] = None
    priority: CommandPriority = CommandPriority.NORMAL
    timeout_seconds: int = 300
    retry_count: int = 0
    max_retries: int = 3
    
    # State
    state: CommandState = CommandState.PENDING
    progress: float = 0.0
    
    # Metadata
    user_id: str
    role: str
    initiated_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Tracing
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    parent_command_id: Optional[str] = None
    
    # Environment
    environment: str = "production"
    dry_run: bool = False
    
    class Config:
        use_enum_values = True


class CommandResult(BaseModel):
    """Result of command execution."""
    command_id: str
    state: CommandState
    success: bool
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    error_code: Optional[str] = None
    
    # Timing
    duration_ms: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Rollback info
    rollback_available: bool = False
    rollback_command_id: Optional[str] = None
    
    # Compensation
    compensation_actions: List[str] = Field(default_factory=list)
    
    class Config:
        use_enum_values = True


class CommandStateTransition(BaseModel):
    """Record of state transition."""
    command_id: str
    from_state: CommandState
    to_state: CommandState
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    reason: Optional[str] = None
    actor: Optional[str] = None  # System or user ID


class RetryPolicy(BaseModel):
    """Retry configuration for commands."""
    max_attempts: int = 3
    base_delay_ms: int = 1000
    max_delay_ms: int = 30000
    exponential_base: float = 2.0
    retryable_errors: List[str] = Field(default_factory=lambda: [
        "TIMEOUT",
        "TEMPORARY_ERROR",
        "RESOURCE_BUSY",
        "CONNECTION_ERROR",
    ])


class TimeoutPolicy(BaseModel):
    """Timeout configuration for commands."""
    execution_timeout_ms: int = 300000  # 5 minutes
    queue_timeout_ms: int = 60000  # 1 minute
    heartbeat_interval_ms: int = 10000  # 10 seconds
    heartbeat_timeout_ms: int = 30000  # 30 seconds

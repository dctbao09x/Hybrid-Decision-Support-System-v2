from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class CrawlStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    STARTED = "started"
    ERROR = "error"
    STOPPING = "stopping"
    NOT_FOUND = "not_found"
    ALREADY_STOPPED = "already_stopped"
    QUEUE_FULL = "queue_full"
    COMPLETED = "completed"


class CrawlRequest(BaseModel):
    site_name: str
    limit: Optional[int] = 0
    config_path: Optional[str] = None


class CrawlResult(BaseModel):
    status: CrawlStatus
    message: str
    data: Optional[Dict[str, Any]] = Field(default=None)
    job_count: Optional[int] = Field(default=0)
    duration_seconds: Optional[float] = Field(default=0.0)

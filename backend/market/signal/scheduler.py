# backend/market/signal/scheduler.py
"""
Market Crawl Scheduler
======================

Automated scheduling for market data collection:
- Time-based scheduling
- Priority queuing
- Adaptive frequency
- Compliance windows
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from threading import RLock, Thread
from typing import Any, Callable, Dict, List, Optional

from .models import DataSource, CrawlJob
from .collector import MarketSignalCollector, get_market_collector

logger = logging.getLogger("market.signal.scheduler")


@dataclass
class ScheduleConfig:
    """Schedule configuration for a source."""
    source: DataSource
    enabled: bool = True
    
    # Frequency
    interval_hours: int = 24  # How often to crawl
    
    # Queries to run
    queries: List[Dict[str, Any]] = field(default_factory=list)
    
    # Compliance windows (hours in UTC)
    allowed_hours_start: int = 1  # 1 AM UTC
    allowed_hours_end: int = 6    # 6 AM UTC (off-peak)
    
    # Priority (lower = higher priority)
    priority: int = 5
    
    # Limits
    max_pages_per_query: int = 10
    max_queries_per_run: int = 5
    
    def is_within_window(self) -> bool:
        """Check if current time is within allowed window."""
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        
        if self.allowed_hours_start <= self.allowed_hours_end:
            return self.allowed_hours_start <= current_hour < self.allowed_hours_end
        else:
            # Window spans midnight
            return current_hour >= self.allowed_hours_start or current_hour < self.allowed_hours_end


@dataclass
class ScheduledTask:
    """A scheduled crawl task."""
    task_id: str
    source: DataSource
    query: Dict[str, Any]
    scheduled_for: datetime
    priority: int = 5
    status: str = "pending"  # pending, running, completed, failed, skipped
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "source": self.source.value,
            "query": self.query,
            "scheduled_for": self.scheduled_for.isoformat(),
            "priority": self.priority,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }


class CrawlScheduler:
    """
    Market data crawl scheduler.
    
    Features:
    - Cron-like scheduling
    - Priority queue
    - Compliance time windows
    - Adaptive frequency based on change rate
    """
    
    def __init__(
        self,
        collector: Optional[MarketSignalCollector] = None,
        db_path: Optional[Path] = None,
    ):
        self._collector = collector or get_market_collector()
        self._root = Path(__file__).resolve().parents[3]
        self._db_path = db_path or self._root / "storage/market/scheduler.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._lock = RLock()
        
        # Schedule configs by source
        self._configs: Dict[DataSource, ScheduleConfig] = {}
        
        # Task queue
        self._queue: List[ScheduledTask] = []
        
        # Running state
        self._running = False
        self._worker_thread: Optional[Thread] = None
        
        # Callbacks
        self._on_task_complete: List[Callable[[ScheduledTask, CrawlJob], None]] = []
        
        self._init_db()
        self._init_default_schedules()
    
    def _init_db(self) -> None:
        """Initialize scheduler database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS schedule_configs (
                    source TEXT PRIMARY KEY,
                    config JSON
                );
                
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    task_id TEXT PRIMARY KEY,
                    source TEXT,
                    query TEXT,
                    scheduled_for TEXT,
                    priority INTEGER,
                    status TEXT,
                    created_at TEXT,
                    completed_at TEXT,
                    result_job_id TEXT
                );
                
                CREATE TABLE IF NOT EXISTS run_history (
                    run_id TEXT PRIMARY KEY,
                    source TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    tasks_completed INTEGER,
                    jobs_found INTEGER,
                    new_jobs INTEGER,
                    updated_jobs INTEGER
                );
                
                CREATE INDEX IF NOT EXISTS idx_tasks_scheduled ON scheduled_tasks(scheduled_for);
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON scheduled_tasks(status);
            """)
    
    def _init_default_schedules(self) -> None:
        """Initialize default schedule configs."""
        default_queries = [
            {"keywords": "software engineer", "location": "Ho Chi Minh"},
            {"keywords": "data analyst", "location": "Ho Chi Minh"},
            {"keywords": "product manager", "location": "Ha Noi"},
            {"keywords": "marketing", "location": "Ho Chi Minh"},
            {"keywords": "DevOps", "location": "Ho Chi Minh"},
            {"keywords": "AI Engineer", "location": "Ho Chi Minh"},
            {"keywords": "business analyst", "location": "Ha Noi"},
        ]
        
        self._configs = {
            DataSource.VIETNAMWORKS: ScheduleConfig(
                source=DataSource.VIETNAMWORKS,
                enabled=True,
                interval_hours=24,
                queries=default_queries,
                allowed_hours_start=1,
                allowed_hours_end=6,
                priority=1,
                max_pages_per_query=10,
            ),
            DataSource.TOPCV: ScheduleConfig(
                source=DataSource.TOPCV,
                enabled=True,
                interval_hours=24,
                queries=default_queries,
                allowed_hours_start=2,
                allowed_hours_end=7,
                priority=2,
                max_pages_per_query=10,
            ),
            DataSource.LINKEDIN: ScheduleConfig(
                source=DataSource.LINKEDIN,
                enabled=False,  # Requires API access
                interval_hours=48,
                queries=default_queries[:3],
                priority=3,
            ),
        }
    
    # ═══════════════════════════════════════════════════════════════════
    # Configuration
    # ═══════════════════════════════════════════════════════════════════
    
    def set_config(self, config: ScheduleConfig) -> None:
        """Set schedule config for a source."""
        self._configs[config.source] = config
        self._save_config(config)
    
    def get_config(self, source: DataSource) -> Optional[ScheduleConfig]:
        """Get schedule config for a source."""
        return self._configs.get(source)
    
    def _save_config(self, config: ScheduleConfig) -> None:
        """Save config to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO schedule_configs (source, config)
                VALUES (?, ?)
            """, (config.source.value, json.dumps({
                "enabled": config.enabled,
                "interval_hours": config.interval_hours,
                "queries": config.queries,
                "allowed_hours_start": config.allowed_hours_start,
                "allowed_hours_end": config.allowed_hours_end,
                "priority": config.priority,
                "max_pages_per_query": config.max_pages_per_query,
                "max_queries_per_run": config.max_queries_per_run,
            })))
    
    # ═══════════════════════════════════════════════════════════════════
    # Task Management
    # ═══════════════════════════════════════════════════════════════════
    
    def schedule_task(
        self,
        source: DataSource,
        query: Dict[str, Any],
        scheduled_for: Optional[datetime] = None,
        priority: int = 5,
    ) -> ScheduledTask:
        """Schedule a crawl task."""
        task = ScheduledTask(
            task_id=f"task_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{source.value}",
            source=source,
            query=query,
            scheduled_for=scheduled_for or datetime.now(timezone.utc),
            priority=priority,
        )
        
        with self._lock:
            self._queue.append(task)
            self._queue.sort(key=lambda t: (t.scheduled_for, t.priority))
        
        self._save_task(task)
        return task
    
    def _save_task(self, task: ScheduledTask) -> None:
        """Save task to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO scheduled_tasks
                (task_id, source, query, scheduled_for, priority, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                task.task_id,
                task.source.value,
                json.dumps(task.query),
                task.scheduled_for.isoformat(),
                task.priority,
                task.status,
                task.created_at.isoformat(),
            ))
    
    def get_pending_tasks(self) -> List[ScheduledTask]:
        """Get all pending tasks."""
        with self._lock:
            return [t for t in self._queue if t.status == "pending"]
    
    def get_due_tasks(self) -> List[ScheduledTask]:
        """Get tasks that are due for execution."""
        now = datetime.now(timezone.utc)
        with self._lock:
            return [
                t for t in self._queue
                if t.status == "pending" and t.scheduled_for <= now
            ]
    
    # ═══════════════════════════════════════════════════════════════════
    # Schedule Generation
    # ═══════════════════════════════════════════════════════════════════
    
    def generate_schedule(self, days_ahead: int = 7) -> List[ScheduledTask]:
        """Generate scheduled tasks for the next N days."""
        tasks = []
        now = datetime.now(timezone.utc)
        
        for source, config in self._configs.items():
            if not config.enabled:
                continue
            
            # Find next run time within allowed window
            next_run = self._find_next_run_time(config, now)
            
            while next_run < now + timedelta(days=days_ahead):
                for i, query in enumerate(config.queries[:config.max_queries_per_run]):
                    task = self.schedule_task(
                        source=source,
                        query=query,
                        scheduled_for=next_run + timedelta(minutes=i * 5),  # Stagger by 5 min
                        priority=config.priority,
                    )
                    tasks.append(task)
                
                # Next interval
                next_run = next_run + timedelta(hours=config.interval_hours)
                next_run = self._find_next_run_time(config, next_run)
        
        return tasks
    
    def _find_next_run_time(self, config: ScheduleConfig, after: datetime) -> datetime:
        """Find next valid run time within allowed window."""
        candidate = after
        
        # Move to allowed window if needed
        if not config.is_within_window():
            # Move to next allowed window start
            candidate = candidate.replace(
                hour=config.allowed_hours_start,
                minute=0,
                second=0,
                microsecond=0,
            )
            if candidate <= after:
                candidate += timedelta(days=1)
        
        return candidate
    
    # ═══════════════════════════════════════════════════════════════════
    # Execution
    # ═══════════════════════════════════════════════════════════════════
    
    async def execute_task(self, task: ScheduledTask) -> Optional[CrawlJob]:
        """Execute a single task."""
        config = self._configs.get(task.source)
        
        # Check compliance window
        if config and not config.is_within_window():
            logger.info(f"Task {task.task_id} skipped - outside allowed window")
            task.status = "skipped"
            self._save_task(task)
            return None
        
        try:
            task.status = "running"
            self._save_task(task)
            
            crawl_job = await self._collector.run_crawl(
                source=task.source,
                query=task.query,
                max_pages=config.max_pages_per_query if config else 10,
            )
            
            task.status = "completed"
            self._save_task(task)
            
            # Trigger callbacks
            for callback in self._on_task_complete:
                try:
                    callback(task, crawl_job)
                except Exception as e:
                    logger.error(f"Task callback error: {e}")
            
            return crawl_job
            
        except Exception as e:
            task.status = "failed"
            self._save_task(task)
            logger.error(f"Task {task.task_id} failed: {e}")
            return None
    
    async def run_due_tasks(self) -> List[CrawlJob]:
        """Run all due tasks."""
        due_tasks = self.get_due_tasks()
        jobs = []
        
        for task in due_tasks:
            job = await self.execute_task(task)
            if job:
                jobs.append(job)
        
        return jobs
    
    # ═══════════════════════════════════════════════════════════════════
    # Background Worker
    # ═══════════════════════════════════════════════════════════════════
    
    def start(self, check_interval_sec: int = 300) -> None:
        """Start background scheduler."""
        if self._running:
            return
        
        self._running = True
        
        def _worker():
            while self._running:
                try:
                    # Run due tasks
                    asyncio.run(self.run_due_tasks())
                except Exception as e:
                    logger.error(f"Scheduler worker error: {e}")
                
                # Wait for next check
                import time
                time.sleep(check_interval_sec)
        
        self._worker_thread = Thread(target=_worker, daemon=True)
        self._worker_thread.start()
        logger.info("Crawl scheduler started")
    
    def stop(self) -> None:
        """Stop background scheduler."""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=10)
        logger.info("Crawl scheduler stopped")
    
    # ═══════════════════════════════════════════════════════════════════
    # Adaptive Frequency
    # ═══════════════════════════════════════════════════════════════════
    
    def adjust_frequency(self, source: DataSource, change_rate: float) -> None:
        """
        Adjust crawl frequency based on detected change rate.
        
        Args:
            source: Data source to adjust
            change_rate: Recent change rate (0-1)
        """
        config = self._configs.get(source)
        if not config:
            return
        
        if change_rate > 0.3:
            # High change rate - increase frequency
            config.interval_hours = max(12, config.interval_hours - 6)
        elif change_rate < 0.1:
            # Low change rate - decrease frequency
            config.interval_hours = min(72, config.interval_hours + 6)
        
        self._save_config(config)
        logger.info(f"Adjusted {source.value} interval to {config.interval_hours}h (change_rate={change_rate:.2f})")
    
    # ═══════════════════════════════════════════════════════════════════
    # Status
    # ═══════════════════════════════════════════════════════════════════
    
    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status."""
        pending = len(self.get_pending_tasks())
        due = len(self.get_due_tasks())
        
        return {
            "running": self._running,
            "pending_tasks": pending,
            "due_tasks": due,
            "configs": {
                source.value: {
                    "enabled": config.enabled,
                    "interval_hours": config.interval_hours,
                    "queries_count": len(config.queries),
                    "in_window": config.is_within_window(),
                }
                for source, config in self._configs.items()
            },
        }


# ═══════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════

_scheduler: Optional[CrawlScheduler] = None


def get_crawl_scheduler() -> CrawlScheduler:
    """Get singleton scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = CrawlScheduler()
    return _scheduler

# backend/scoring/scheduler.py
"""
Data Refresh Scheduler - SIMGR Stage 3 Compliant

Schedules periodic data refresh for SIMGR components:
- Growth data refresh (TTL < 90 days)
- Market data updates
- Career lifecycle updates
"""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """Represents a scheduled refresh task."""
    name: str
    interval_hours: int
    callback: Callable
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    enabled: bool = True
    
    def should_run(self) -> bool:
        if not self.enabled:
            return False
        if self.next_run is None:
            return True
        return datetime.now() >= self.next_run
    
    def update_schedule(self):
        self.last_run = datetime.now()
        self.next_run = self.last_run + timedelta(hours=self.interval_hours)


class RefreshScheduler:
    """Scheduler for periodic data refresh tasks."""
    
    def __init__(self):
        self._tasks: Dict[str, ScheduledTask] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
    
    def register_task(
        self,
        name: str,
        callback: Callable,
        interval_hours: int = 24,
    ) -> None:
        """Register a refresh task."""
        with self._lock:
            self._tasks[name] = ScheduledTask(
                name=name,
                interval_hours=interval_hours,
                callback=callback,
            )
        logger.info(f"Registered task: {name} (every {interval_hours}h)")
    
    def unregister_task(self, name: str) -> None:
        """Unregister a refresh task."""
        with self._lock:
            if name in self._tasks:
                del self._tasks[name]
                logger.info(f"Unregistered task: {name}")
    
    def enable_task(self, name: str, enabled: bool = True) -> None:
        """Enable or disable a task."""
        with self._lock:
            if name in self._tasks:
                self._tasks[name].enabled = enabled
    
    def run_task(self, name: str) -> Dict:
        """Run a task immediately."""
        with self._lock:
            task = self._tasks.get(name)
        
        if task is None:
            return {"status": "ERROR", "message": f"Task not found: {name}"}
        
        return self._execute_task(task)
    
    def _execute_task(self, task: ScheduledTask) -> Dict:
        """Execute a single task."""
        logger.info(f"Executing task: {task.name}")
        
        try:
            result = task.callback()
            task.update_schedule()
            
            return {
                "status": "SUCCESS",
                "task": task.name,
                "result": result,
                "next_run": task.next_run.isoformat() if task.next_run else None,
            }
        except Exception as e:
            logger.error(f"Task {task.name} failed: {e}")
            return {
                "status": "ERROR",
                "task": task.name,
                "error": str(e),
            }
    
    def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Scheduler started")
    
    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Scheduler stopped")
    
    def _run_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            with self._lock:
                tasks = list(self._tasks.values())
            
            for task in tasks:
                if task.should_run():
                    self._execute_task(task)
            
            # Check every minute
            time.sleep(60)
    
    def get_status(self) -> Dict:
        """Get scheduler status."""
        with self._lock:
            tasks_status = []
            for task in self._tasks.values():
                tasks_status.append({
                    "name": task.name,
                    "enabled": task.enabled,
                    "interval_hours": task.interval_hours,
                    "last_run": task.last_run.isoformat() if task.last_run else None,
                    "next_run": task.next_run.isoformat() if task.next_run else None,
                })
        
        return {
            "running": self._running,
            "tasks": tasks_status,
        }


# Global scheduler instance
_scheduler: Optional[RefreshScheduler] = None


def get_scheduler() -> RefreshScheduler:
    """Get global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = RefreshScheduler()
        _register_default_tasks()
    return _scheduler


def _register_default_tasks() -> None:
    """Register default refresh tasks."""
    from backend.scoring.components.growth_refresh import trigger_growth_refresh
    
    scheduler = _scheduler
    if scheduler:
        # Growth data refresh every 24 hours
        scheduler.register_task(
            name="growth_data_refresh",
            callback=lambda: trigger_growth_refresh(force=False),
            interval_hours=24,
        )


def start_scheduler() -> None:
    """Start the global scheduler."""
    get_scheduler().start()


def stop_scheduler() -> None:
    """Stop the global scheduler."""
    if _scheduler:
        _scheduler.stop()

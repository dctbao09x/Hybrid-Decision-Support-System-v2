"""Retrain Scheduler - Automated model retraining based on metrics and feedback."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable, Dict, List, Optional

from backend.mlops.scheduler.policies import (
    AntiStormPolicy,
    CooldownPolicy,
    CooldownStatus,
    CooldownViolation,
    get_anti_storm_policy,
    get_cooldown_policy,
)
from backend.mlops.scheduler.state_store import StateStore, get_state_store

logger = logging.getLogger(__name__)


_metrics_collector: Optional[Any] = None


def set_scheduler_metrics_collector(metrics_collector: Any) -> None:
    global _metrics_collector
    _metrics_collector = metrics_collector


def _metrics_set_gauge(name: str, value: float) -> None:
    if _metrics_collector is None:
        return
    try:
        _metrics_collector.set_gauge(name, float(value))
    except Exception:
        logger.debug("scheduler gauge update failed: %s", name, exc_info=True)


@dataclass
class RetrainTriggerCondition:
    """Conditions that can trigger automatic retraining."""
    metric_name: str
    threshold: float
    comparison: str  # 'gt', 'lt', 'gte', 'lte'
    weight: float = 1.0

    def evaluate(self, value: float) -> bool:
        """Check if the condition is met."""
        if self.comparison == "gt":
            return value > self.threshold
        elif self.comparison == "lt":
            return value < self.threshold
        elif self.comparison == "gte":
            return value >= self.threshold
        elif self.comparison == "lte":
            return value <= self.threshold
        return False


@dataclass
class SchedulerConfig:
    """Configuration for the retrain scheduler."""
    enabled: bool = True
    poll_interval_seconds: int = 300  # 5 minutes
    min_feedback_count: int = 100  # Minimum feedback before considering retrain
    accuracy_drop_threshold: float = 0.05
    drift_score_threshold: float = 0.25
    error_rate_threshold: float = 0.03
    feedback_negative_rate_threshold: float = 0.15
    max_consecutive_failures: int = 5

    @classmethod
    def from_env(cls) -> "SchedulerConfig":
        """Load configuration from environment variables."""
        config = cls(
            enabled=os.getenv("MLOPS_SCHEDULER_ENABLED", "true").lower() in ("true", "1", "yes"),
            poll_interval_seconds=int(os.getenv("MLOPS_SCHEDULER_POLL_INTERVAL", "300")),
            min_feedback_count=int(os.getenv("MLOPS_SCHEDULER_MIN_FEEDBACK", "100")),
            accuracy_drop_threshold=float(os.getenv("MLOPS_SCHEDULER_ACCURACY_DROP", "0.05")),
            drift_score_threshold=float(os.getenv("MLOPS_SCHEDULER_DRIFT_THRESHOLD", "0.25")),
            error_rate_threshold=float(os.getenv("MLOPS_SCHEDULER_ERROR_RATE", "0.03")),
            feedback_negative_rate_threshold=float(os.getenv("MLOPS_SCHEDULER_NEGATIVE_FEEDBACK", "0.15")),
            max_consecutive_failures=int(os.getenv("MLOPS_SCHEDULER_MAX_CONSECUTIVE_FAILURES", "5")),
        )
        return config.validated()

    def validated(self) -> "SchedulerConfig":
        """Return a normalized, safe scheduler configuration."""
        return SchedulerConfig(
            enabled=bool(self.enabled),
            poll_interval_seconds=max(5, int(self.poll_interval_seconds)),
            min_feedback_count=max(0, int(self.min_feedback_count)),
            accuracy_drop_threshold=max(0.0, float(self.accuracy_drop_threshold)),
            drift_score_threshold=max(0.0, float(self.drift_score_threshold)),
            error_rate_threshold=max(0.0, float(self.error_rate_threshold)),
            feedback_negative_rate_threshold=max(0.0, float(self.feedback_negative_rate_threshold)),
            max_consecutive_failures=max(1, int(self.max_consecutive_failures)),
        )


class RetrainScheduler:
    """Automated retrain scheduler with cooldown and anti-storm protection.
    
    Polls metrics and feedback statistics to determine when retraining is needed.
    Enforces cooldown between retrains and prevents retrain storms.
    
    Example usage:
        scheduler = RetrainScheduler()
        await scheduler.start()
        
        # Or manually trigger check
        result = await scheduler.check_and_trigger()
    """

    def __init__(
        self,
        config: Optional[SchedulerConfig] = None,
        state_store: Optional[StateStore] = None,
        cooldown_policy: Optional[CooldownPolicy] = None,
        anti_storm_policy: Optional[AntiStormPolicy] = None,
    ):
        """Initialize the scheduler.
        
        Args:
            config: Scheduler configuration. If None, loads from env.
            state_store: State persistence store. If None, uses default.
            cooldown_policy: Cooldown policy. If None, uses default.
            anti_storm_policy: Anti-storm policy. If None, uses default.
        """
        base_config = config or SchedulerConfig.from_env()
        self._config = base_config.validated()
        self._state_store = state_store or get_state_store()
        self._cooldown_policy = cooldown_policy or get_cooldown_policy()
        self._anti_storm_policy = anti_storm_policy or get_anti_storm_policy()
        
        self._lock = RLock()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._checks_total = 0
        self._failures_total = 0
        self._consecutive_failures = 0
        
        # Callbacks for metric and feedback retrieval
        self._metric_provider: Optional[Callable[[], Dict[str, Any]]] = None
        self._feedback_provider: Optional[Callable[[], Dict[str, Any]]] = None
        self._train_callback: Optional[Callable[[str], Any]] = None
        
        # Default trigger conditions
        self._conditions = [
            RetrainTriggerCondition("accuracy_drop", self._config.accuracy_drop_threshold, "gte", 2.0),
            RetrainTriggerCondition("drift_score", self._config.drift_score_threshold, "gte", 1.5),
            RetrainTriggerCondition("error_rate", self._config.error_rate_threshold, "gte", 1.5),
            RetrainTriggerCondition("negative_feedback_rate", self._config.feedback_negative_rate_threshold, "gte", 1.0),
        ]

        state = self._state_store.get_state()
        self._checks_total = int(getattr(state, "total_scheduler_checks", 0) or 0)
        self._failures_total = int(getattr(state, "total_scheduler_failures", 0) or 0)
        self._refresh_failure_rate_metric()

    def configure(
        self,
        metric_provider: Callable[[], Dict[str, Any]],
        feedback_provider: Callable[[], Dict[str, Any]],
        train_callback: Callable[[str], Any],
    ) -> None:
        """Configure the scheduler with data providers and training callback.
        
        Args:
            metric_provider: Function that returns current metrics
            feedback_provider: Function that returns feedback statistics
            train_callback: Function to call for training (receives trigger type)
        """
        if not callable(metric_provider):
            raise ValueError("metric_provider must be callable")
        if not callable(feedback_provider):
            raise ValueError("feedback_provider must be callable")
        if not callable(train_callback):
            raise ValueError("train_callback must be callable")

        self._metric_provider = metric_provider
        self._feedback_provider = feedback_provider
        self._train_callback = train_callback

    @property
    def enabled(self) -> bool:
        """Check if the scheduler is enabled."""
        return self._config.enabled

    @property
    def running(self) -> bool:
        """Check if the scheduler is currently running."""
        return self._running

    def get_cooldown_status(self) -> CooldownStatus:
        """Get the current cooldown status."""
        last_retrain = self._state_store.get_last_retrain_at()
        return self._cooldown_policy.check(last_retrain)

    def get_status(self) -> Dict[str, Any]:
        """Get full scheduler status including cooldown and state."""
        state = self._state_store.get_state()
        cooldown = self.get_cooldown_status()
        recent_runs = self._state_store.get_recent_runs(self._anti_storm_policy.window_hours)
        storm_status = self._anti_storm_policy.check(recent_runs)
        
        return {
            "enabled": self.enabled,
            "running": self.running,
            "poll_interval_seconds": self._config.poll_interval_seconds,
            "cooldown": cooldown.to_dict(),
            "anti_storm": storm_status.to_dict(),
            "last_retrain_at": state.last_retrain_at,
            "last_trigger": state.last_trigger,
            "last_status": state.last_status,
            "total_auto_retrains": state.total_auto_retrains,
            "total_blocked_by_cooldown": state.total_blocked_by_cooldown,
            "total_blocked_by_storm": state.total_blocked_by_storm,
            "total_scheduler_checks": getattr(state, "total_scheduler_checks", self._checks_total),
            "total_scheduler_failures": getattr(state, "total_scheduler_failures", self._failures_total),
            "scheduler_failure_rate": (
                float(getattr(state, "total_scheduler_failures", self._failures_total))
                / max(1.0, float(getattr(state, "total_scheduler_checks", self._checks_total)))
            ),
            "consecutive_failures": state.consecutive_failures,
            "consecutive_scheduler_failures": self._consecutive_failures,
        }

    def _refresh_failure_rate_metric(self) -> None:
        denominator = max(float(self._checks_total), 1.0)
        _metrics_set_gauge("scheduler_failure_rate", float(self._failures_total) / denominator)

    def _record_scheduler_check(self, success: bool, reason: Optional[str] = None) -> None:
        self._checks_total += 1
        if success:
            self._consecutive_failures = 0
        else:
            self._failures_total += 1
            self._consecutive_failures += 1
        self._refresh_failure_rate_metric()
        try:
            self._state_store.record_scheduler_check(success=success, reason=reason)
        except Exception:
            logger.debug("failed to persist scheduler check result", exc_info=True)

    def _collect_metrics(self) -> Dict[str, Any]:
        """Collect current metrics from the configured provider."""
        if self._metric_provider is None:
            raise RuntimeError("No metric provider configured")

        payload = self._metric_provider()
        if not isinstance(payload, dict):
            raise ValueError("metric provider must return a dict")
        return payload

    def _collect_feedback_stats(self) -> Dict[str, Any]:
        """Collect feedback statistics from the configured provider."""
        if self._feedback_provider is None:
            raise RuntimeError("No feedback provider configured")

        payload = self._feedback_provider()
        if not isinstance(payload, dict):
            raise ValueError("feedback provider must return a dict")
        return payload

    def _evaluate_conditions(
        self,
        metrics: Dict[str, Any],
        feedback_stats: Dict[str, Any],
    ) -> tuple[bool, List[str]]:
        """Evaluate trigger conditions against current data.
        
        Args:
            metrics: Current metrics
            feedback_stats: Current feedback statistics
            
        Returns:
            Tuple of (should_trigger, list of triggered reasons)
        """
        triggered_reasons: List[str] = []
        total_weight = 0.0
        
        combined = {**metrics, **feedback_stats}
        
        for condition in self._conditions:
            value = combined.get(condition.metric_name)
            if value is None:
                continue
            try:
                numeric_value = float(value)
            except Exception:
                continue
            if condition.evaluate(numeric_value):
                reason = f"{condition.metric_name}={value} ({condition.comparison} {condition.threshold})"
                triggered_reasons.append(reason)
                total_weight += condition.weight
        
        # Require at least one condition to trigger, or high weight
        should_trigger = len(triggered_reasons) >= 1 and total_weight >= 1.0
        
        return should_trigger, triggered_reasons

    async def check_and_trigger(self, force: bool = False) -> Dict[str, Any]:
        """Check conditions and trigger retrain if needed.
        
        Args:
            force: Force retrain even if conditions are not met (still respects cooldown)
            
        Returns:
            Result dictionary with status and details
        """
        with self._lock:
            result: Dict[str, Any] = {
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "triggered": False,
                "blocked": False,
                "reason": None,
                "train_result": None,
            }

            def _finish(success: bool, reason: Optional[str] = None) -> Dict[str, Any]:
                self._record_scheduler_check(success=success, reason=reason)
                result["scheduler_failure_rate"] = (
                    float(self._failures_total) / max(1.0, float(self._checks_total))
                )
                result["consecutive_scheduler_failures"] = self._consecutive_failures
                return result

            if self._train_callback is None:
                result["blocked"] = True
                result["reason"] = "No train callback configured"
                result["train_result"] = {"status": "error", "error": result["reason"]}
                return _finish(False, result["reason"])
            
            # Check cooldown
            last_retrain = self._state_store.get_last_retrain_at()
            cooldown_status = self._cooldown_policy.check(last_retrain)
            result["cooldown_status"] = cooldown_status.to_dict()
            
            if cooldown_status.active and not force:
                self._state_store.record_block("cooldown", f"Remaining: {cooldown_status.remaining_hours:.2f}h")
                result["blocked"] = True
                result["reason"] = f"Cooldown active: {cooldown_status.remaining_hours:.2f}h remaining"
                logger.info("Retrain blocked by cooldown: %s", result["reason"])
                return _finish(True, "cooldown_blocked")
            
            # Check anti-storm
            recent_runs = self._state_store.get_recent_runs(self._anti_storm_policy.window_hours)
            storm_status = self._anti_storm_policy.check(recent_runs)
            result["anti_storm_status"] = storm_status.to_dict()
            
            if storm_status.blocked:
                self._state_store.record_block("storm", storm_status.reason or "Storm protection")
                result["blocked"] = True
                result["reason"] = storm_status.reason
                logger.info("Retrain blocked by anti-storm: %s", result["reason"])
                return _finish(True, "storm_blocked")
            
            # Collect data
            try:
                metrics = self._collect_metrics()
                feedback_stats = self._collect_feedback_stats()
            except Exception as exc:
                result["blocked"] = True
                result["reason"] = f"Scheduler validation failed: {exc}"
                result["train_result"] = {"status": "error", "error": str(exc)}
                logger.error("Scheduler validation failed: %s", exc)
                return _finish(False, result["reason"])

            result["metrics"] = metrics
            result["feedback_stats"] = feedback_stats

            raw_feedback_count = feedback_stats.get("feedback_count")
            if raw_feedback_count is not None and not force:
                try:
                    feedback_count = int(raw_feedback_count)
                except Exception:
                    feedback_count = 0
                if feedback_count < self._config.min_feedback_count:
                    result["reason"] = (
                        f"Insufficient feedback_count={feedback_count}; "
                        f"minimum required={self._config.min_feedback_count}"
                    )
                    return _finish(True, "insufficient_feedback")
            
            # Evaluate conditions
            if not force:
                should_trigger, reasons = self._evaluate_conditions(metrics, feedback_stats)
                result["trigger_reasons"] = reasons
                
                if not should_trigger:
                    result["reason"] = "No trigger conditions met"
                    return _finish(True, "no_trigger")
            else:
                result["trigger_reasons"] = ["forced"]
            
            # Trigger retrain
            result["triggered"] = True
            
            try:
                logger.info("Triggering auto retrain. Reasons: %s", result.get("trigger_reasons"))
                train_result = await self._train_callback("auto")
                if not isinstance(train_result, dict):
                    train_result = {
                        "status": "failed",
                        "error": "Train callback returned non-dict payload",
                    }
                result["train_result"] = train_result

                train_status = str(train_result.get("status", "unknown")).lower()
                if train_status == "success":
                    logger.info("Auto retrain completed: %s", train_status)
                    return _finish(True, "trigger_success")
                if train_status == "blocked":
                    result["blocked"] = True
                    result["reason"] = str(train_result.get("reason", "train callback blocked retrain"))
                    return _finish(True, "train_blocked")

                result["reason"] = str(train_result.get("error", "train callback failed"))
                return _finish(False, result["reason"])
            except CooldownViolation as e:
                result["triggered"] = False
                result["blocked"] = True
                result["reason"] = str(e)
                result["train_result"] = {"status": "blocked", "error": str(e)}
                return _finish(True, "cooldown_violation")
            except Exception as e:
                logger.error("Auto retrain failed: %s", e)
                result["train_result"] = {"status": "failed", "error": str(e)}
                result["reason"] = str(e)
                return _finish(False, str(e))

    async def _poll_loop(self) -> None:
        """Background polling loop."""
        logger.info(
            "Retrain scheduler started. Poll interval: %ds",
            self._config.poll_interval_seconds,
        )
        
        while self._running:
            try:
                await self.check_and_trigger()
                if self._consecutive_failures >= self._config.max_consecutive_failures:
                    logger.error(
                        "Scheduler stopped after %d consecutive failures (max=%d)",
                        self._consecutive_failures,
                        self._config.max_consecutive_failures,
                    )
                    self._running = False
                    break
            except Exception as e:
                logger.error("Poll loop error: %s", e)
                self._record_scheduler_check(False, f"poll_loop_error:{e}")
                if self._consecutive_failures >= self._config.max_consecutive_failures:
                    logger.error(
                        "Scheduler stopped after poll-loop errors exceeded threshold (%d)",
                        self._config.max_consecutive_failures,
                    )
                    self._running = False
                    break
            
            await asyncio.sleep(self._config.poll_interval_seconds)

    async def start(self) -> None:
        """Start the background scheduler."""
        if not self._config.enabled:
            logger.info("Retrain scheduler is disabled")
            return

        if self._metric_provider is None or self._feedback_provider is None or self._train_callback is None:
            logger.error("Retrain scheduler start aborted: providers/train callback are not fully configured")
            self._record_scheduler_check(False, "startup_validation_failed")
            return
        
        if self._running:
            logger.warning("Retrain scheduler already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Retrain scheduler started")

    async def stop(self) -> None:
        """Stop the background scheduler."""
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("Retrain scheduler stopped")


# Singleton instance
_scheduler: Optional[RetrainScheduler] = None


def get_retrain_scheduler() -> RetrainScheduler:
    """Get the singleton RetrainScheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = RetrainScheduler()
    return _scheduler


async def initialize_scheduler(
    metric_provider: Callable[[], Dict[str, Any]],
    feedback_provider: Callable[[], Dict[str, Any]],
    train_callback: Callable[[str], Any],
) -> RetrainScheduler:
    """Initialize and start the scheduler with providers.
    
    Args:
        metric_provider: Function that returns current metrics
        feedback_provider: Function that returns feedback statistics
        train_callback: Async function to call for training
        
    Returns:
        The configured and started scheduler
    """
    scheduler = get_retrain_scheduler()
    scheduler.configure(
        metric_provider=metric_provider,
        feedback_provider=feedback_provider,
        train_callback=train_callback,
    )
    await scheduler.start()
    return scheduler

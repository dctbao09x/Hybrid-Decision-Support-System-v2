"""
Stage Retry — Failure-aware retry with per-stage policies.
==========================================================
Builds on top of the base RetryExecutor to add:

  • Per-stage retry policies (crawl gets more retries than explain)
  • Failure-catalog-aware retry (skip non-retryable errors immediately)
  • Retry budget tracking + telemetry
  • Circuit breaker per stage
  • Cooldown between retries (for RESOURCE failures)
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

from backend.ops.recovery.failure_catalog import (
    ClassifiedFailure,
    FailureCatalog,
    FailureCategory,
    RecoveryStrategy,
)
from backend.state import StatePolicy, get_operational_state_store

logger = logging.getLogger("ops.recovery.retry")


# ── Per-Stage Retry Policy ──────────────────────────────────────────────

@dataclass
class StageRetryPolicy:
    """Custom retry policy for a specific pipeline stage."""
    stage: str
    max_retries: int = 3
    base_delay: float = 2.0
    max_delay: float = 120.0
    jitter: bool = True
    resource_cooldown: float = 30.0   # extra wait for RESOURCE errors
    circuit_threshold: int = 5        # open circuit after N consecutive fails
    circuit_recovery: float = 60.0    # seconds before half-open
    budget_window: float = 900.0      # 15 min budget window
    budget_max_retries: int = 10      # max retries per stage per window

    def get_delay(self, attempt: int, category: FailureCategory = FailureCategory.UNKNOWN) -> float:
        """Exponential backoff with jitter + category-aware adjustment."""
        delay = self.base_delay * (2 ** attempt)
        delay = min(delay, self.max_delay)

        # Longer delay for rate limits
        if category == FailureCategory.EXTERNAL:
            delay = max(delay, 10.0)

        # Cooldown for resource errors
        if category == FailureCategory.RESOURCE:
            delay = max(delay, self.resource_cooldown)

        if self.jitter:
            delay *= (0.5 + random.random())

        return round(delay, 2)


# ── Default stage policies ──────────────────────────────────────────────

DEFAULT_STAGE_POLICIES: Dict[str, StageRetryPolicy] = {
    "crawl": StageRetryPolicy(
        stage="crawl",
        max_retries=3,
        base_delay=5.0,
        max_delay=120.0,
        resource_cooldown=30.0,
        circuit_threshold=5,
        budget_max_retries=10,
    ),
    "validate": StageRetryPolicy(
        stage="validate",
        max_retries=2,
        base_delay=2.0,
        max_delay=30.0,
        resource_cooldown=10.0,
        circuit_threshold=3,
        budget_max_retries=5,
    ),
    "score": StageRetryPolicy(
        stage="score",
        max_retries=2,
        base_delay=3.0,
        max_delay=60.0,
        resource_cooldown=15.0,
        circuit_threshold=3,
        budget_max_retries=5,
    ),
    "explain": StageRetryPolicy(
        stage="explain",
        max_retries=1,
        base_delay=2.0,
        max_delay=30.0,
        resource_cooldown=10.0,
        circuit_threshold=3,
        budget_max_retries=3,
    ),
}


# ── Circuit Breaker per stage ───────────────────────────────────────────

class StageCircuitBreaker:
    """Per-stage circuit breaker with half-open probe."""

    def __init__(self, threshold: int = 5, recovery_timeout: float = 60.0):
        self.threshold = threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count: int = 0
        self.last_failure_time: float = 0.0
        self.state: str = "closed"  # closed | open | half_open

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = "closed"

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.threshold:
            self.state = "open"
            logger.warning(
                f"Circuit breaker OPEN after {self.failure_count} failures"
            )

    def can_execute(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = "half_open"
                return True
            return False
        # half_open — allow one probe
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "threshold": self.threshold,
        }


# ── Retry Budget Tracker ───────────────────────────────────────────────

@dataclass
class RetryBudget:
    """Tracks retry budget consumption per stage within a time window."""
    window_seconds: float = 900.0  # 15 min
    max_retries: int = 10
    _events: List[float] = field(default_factory=list)

    def consume(self) -> bool:
        """Try to consume one retry. Returns True if budget allows."""
        now = time.time()
        cutoff = now - self.window_seconds
        self._events = [t for t in self._events if t > cutoff]
        if len(self._events) >= self.max_retries:
            return False
        self._events.append(now)
        return True

    @property
    def remaining(self) -> int:
        now = time.time()
        cutoff = now - self.window_seconds
        active = sum(1 for t in self._events if t > cutoff)
        return max(0, self.max_retries - active)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "remaining": self.remaining,
            "max": self.max_retries,
            "window_seconds": self.window_seconds,
        }


# ── Retry Result ────────────────────────────────────────────────────────

@dataclass
class RetryResult:
    """Outcome of a retry-wrapped execution."""
    success: bool
    result: Any = None
    attempts: int = 0
    total_delay: float = 0.0
    last_error: Optional[Exception] = None
    classified: Optional[ClassifiedFailure] = None
    circuit_opened: bool = False
    budget_exhausted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "attempts": self.attempts,
            "total_delay": round(self.total_delay, 2),
            "last_error": str(self.last_error) if self.last_error else None,
            "category": (
                self.classified.category.value if self.classified else None
            ),
            "circuit_opened": self.circuit_opened,
            "budget_exhausted": self.budget_exhausted,
        }


# ═══════════════════════════════════════════════════════════════════════
#  StageRetryExecutor
# ═══════════════════════════════════════════════════════════════════════

class StageRetryExecutor:
    """
    Failure-aware retry executor for pipeline stages.

    Key differences from base RetryExecutor:
      1. Uses FailureCatalog to classify errors → non-retryable errors
         are raised immediately.
      2. Per-stage retry policies with different backoff curves.
      3. Per-stage circuit breakers.
      4. Retry budget enforcement (max retries per time window).
      5. Telemetry: tracks retry count, delay, success/fail per stage.
    """

    def __init__(
        self,
        catalog: Optional[FailureCatalog] = None,
        policies: Optional[Dict[str, StageRetryPolicy]] = None,
    ) -> None:
        self.catalog = catalog or FailureCatalog()
        self._policies = policies or dict(DEFAULT_STAGE_POLICIES)
        self._state_store = get_operational_state_store()
        self._state_namespace = "stage_retry"
        self._state_policy = StatePolicy(ttl_seconds=None, persistent=True, stale_after_seconds=1800)

    def _circuit_state_key(self, stage: str) -> str:
        return f"circuit:{stage}"

    def _budget_state_key(self, stage: str) -> str:
        return f"budget:{stage}"

    def _telemetry_state_key(self) -> str:
        return "telemetry"

    def _lock(self, lock_name: str):
        return self._state_store.lock(
            name=f"stage_retry:{lock_name}",
            ttl_seconds=8.0,
            wait_timeout_seconds=2.0,
            retry_interval_seconds=0.05,
        )

    def _load_circuit_state(self, stage: str) -> StageCircuitBreaker:
        policy = self.get_policy(stage)
        data = self._state_store.get_json(
            namespace=self._state_namespace,
            state_key=self._circuit_state_key(stage),
            default=None,
            policy=self._state_policy,
        )

        circuit = StageCircuitBreaker(
            threshold=policy.circuit_threshold,
            recovery_timeout=policy.circuit_recovery,
        )

        if isinstance(data, dict):
            circuit.failure_count = int(data.get("failure_count", 0))
            circuit.last_failure_time = float(data.get("last_failure_time", 0.0))
            circuit.state = str(data.get("state", "closed"))
            circuit.threshold = int(data.get("threshold", policy.circuit_threshold))
            circuit.recovery_timeout = float(data.get("recovery_timeout", policy.circuit_recovery))

        return circuit

    def _save_circuit_state(self, stage: str, circuit: StageCircuitBreaker) -> None:
        self._state_store.set_json(
            namespace=self._state_namespace,
            state_key=self._circuit_state_key(stage),
            value={
                "state": circuit.state,
                "failure_count": circuit.failure_count,
                "last_failure_time": circuit.last_failure_time,
                "threshold": circuit.threshold,
                "recovery_timeout": circuit.recovery_timeout,
            },
            policy=self._state_policy,
        )

    def _load_budget_state(self, stage: str) -> RetryBudget:
        policy = self.get_policy(stage)
        data = self._state_store.get_json(
            namespace=self._state_namespace,
            state_key=self._budget_state_key(stage),
            default=None,
            policy=self._state_policy,
        )

        budget = RetryBudget(
            window_seconds=policy.budget_window,
            max_retries=policy.budget_max_retries,
        )

        if isinstance(data, dict):
            budget.window_seconds = float(data.get("window_seconds", policy.budget_window))
            budget.max_retries = int(data.get("max_retries", policy.budget_max_retries))
            raw_events = data.get("events", [])
            if isinstance(raw_events, list):
                budget._events = [float(v) for v in raw_events if isinstance(v, (int, float))][-500:]

        return budget

    def _save_budget_state(self, stage: str, budget: RetryBudget) -> None:
        self._state_store.set_json(
            namespace=self._state_namespace,
            state_key=self._budget_state_key(stage),
            value={
                "window_seconds": budget.window_seconds,
                "max_retries": budget.max_retries,
                "events": budget._events[-500:],
            },
            policy=self._state_policy,
        )

    def _load_telemetry(self) -> List[Dict[str, Any]]:
        data = self._state_store.get_json(
            namespace=self._state_namespace,
            state_key=self._telemetry_state_key(),
            default=[],
            policy=self._state_policy,
        )
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    def _save_telemetry(self, telemetry: List[Dict[str, Any]]) -> None:
        self._state_store.set_json(
            namespace=self._state_namespace,
            state_key=self._telemetry_state_key(),
            value=telemetry[-200:],
            policy=self._state_policy,
        )

    # ── Policy management ──────────────────────────────────────────

    def get_policy(self, stage: str) -> StageRetryPolicy:
        if stage not in self._policies:
            self._policies[stage] = StageRetryPolicy(stage=stage)
        return self._policies[stage]

    def set_policy(self, stage: str, policy: StageRetryPolicy) -> None:
        self._policies[stage] = policy

    # ── Circuit breaker ────────────────────────────────────────────

    def get_circuit(self, stage: str) -> StageCircuitBreaker:
        return self._load_circuit_state(stage)

    # ── Budget ─────────────────────────────────────────────────────

    def get_budget(self, stage: str) -> RetryBudget:
        return self._load_budget_state(stage)

    # ── Execute with retry ─────────────────────────────────────────

    async def execute(
        self,
        stage: str,
        func: Callable[..., Coroutine],
        *args: Any,
        run_id: str = "",
        max_retries_override: Optional[int] = None,
        **kwargs: Any,
    ) -> RetryResult:
        """
        Execute an async function with failure-aware retry.

        Returns a RetryResult (never raises — caller inspects .success).
        """
        policy = self.get_policy(stage)

        max_retries = max_retries_override if max_retries_override is not None else policy.max_retries
        total_delay = 0.0
        last_error: Optional[Exception] = None
        classified: Optional[ClassifiedFailure] = None

        for attempt in range(max_retries + 1):
            # ── Circuit breaker and retry budget checks ──
            with self._lock(stage):
                circuit = self.get_circuit(stage)
                budget = self.get_budget(stage)

                if not circuit.can_execute():
                    logger.warning(
                        f"[{run_id}] Stage '{stage}' circuit OPEN — "
                        f"skipping (attempt {attempt + 1})"
                    )
                    return RetryResult(
                        success=False,
                        attempts=attempt,
                        total_delay=total_delay,
                        last_error=last_error,
                        classified=classified,
                        circuit_opened=True,
                    )

                if attempt > 0 and not budget.consume():
                    self._save_budget_state(stage, budget)
                    logger.warning(
                        f"[{run_id}] Stage '{stage}' retry budget exhausted "
                        f"(attempt {attempt + 1})"
                    )
                    return RetryResult(
                        success=False,
                        attempts=attempt,
                        total_delay=total_delay,
                        last_error=last_error,
                        classified=classified,
                        budget_exhausted=True,
                    )

                if attempt > 0:
                    self._save_budget_state(stage, budget)

            try:
                result = await func(*args, **kwargs)

                with self._lock(stage):
                    circuit = self.get_circuit(stage)
                    circuit.record_success()
                    self._save_circuit_state(stage, circuit)

                # Telemetry
                self._record_telemetry(
                    stage, run_id, attempt + 1, True, total_delay
                )

                return RetryResult(
                    success=True,
                    result=result,
                    attempts=attempt + 1,
                    total_delay=total_delay,
                )

            except Exception as e:
                last_error = e
                classified = self.catalog.classify(e, stage=stage, run_id=run_id)

                with self._lock(stage):
                    circuit = self.get_circuit(stage)
                    circuit.record_failure()
                    self._save_circuit_state(stage, circuit)

                logger.warning(
                    f"[{run_id}] Stage '{stage}' attempt {attempt + 1} failed: "
                    f"{classified.category.value}/{type(e).__name__}: "
                    f"{str(e)[:200]}"
                )

                # ── Non-retryable → stop immediately ──
                if not classified.retryable:
                    logger.info(
                        f"[{run_id}] Error is non-retryable "
                        f"(category={classified.category.value}) — "
                        f"stopping retry"
                    )
                    self._record_telemetry(
                        stage, run_id, attempt + 1, False, total_delay
                    )
                    return RetryResult(
                        success=False,
                        attempts=attempt + 1,
                        total_delay=total_delay,
                        last_error=e,
                        classified=classified,
                    )

                # ── Last attempt → no delay ──
                if attempt >= max_retries:
                    break

                # ── Compute backoff delay ──
                # Use catalog's max_retries as a cap too
                effective_max = min(
                    max_retries, classified.max_retries
                )
                if attempt >= effective_max:
                    break

                delay = policy.get_delay(attempt, classified.category)
                total_delay += delay

                logger.info(
                    f"[{run_id}] Retrying stage '{stage}' in {delay:.1f}s "
                    f"(attempt {attempt + 2}/{max_retries + 1})"
                )
                await asyncio.sleep(delay)

        # All retries exhausted
        self._record_telemetry(
            stage, run_id, max_retries + 1, False, total_delay
        )
        return RetryResult(
            success=False,
            attempts=max_retries + 1,
            total_delay=total_delay,
            last_error=last_error,
            classified=classified,
        )

    # ── Telemetry ──────────────────────────────────────────────────

    def _record_telemetry(
        self,
        stage: str,
        run_id: str,
        attempts: int,
        success: bool,
        total_delay: float,
    ) -> None:
        entry = {
            "stage": stage,
            "run_id": run_id,
            "attempts": attempts,
            "success": success,
            "total_delay": round(total_delay, 2),
            "timestamp": time.time(),
        }

        with self._lock("telemetry"):
            telemetry = self._load_telemetry()
            telemetry.append(entry)
            self._save_telemetry(telemetry)

    def get_telemetry(
        self,
        stage: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        results = self._load_telemetry()
        if stage:
            results = [t for t in results if t["stage"] == stage]
        return results[-limit:]

    def get_retry_stats(self) -> Dict[str, Any]:
        """Aggregate retry statistics across all stages."""
        telemetry = self._load_telemetry()
        if not telemetry:
            return {"total_executions": 0, "by_stage": {}}

        by_stage: Dict[str, Dict[str, Any]] = {}
        for t in telemetry:
            s = t["stage"]
            if s not in by_stage:
                by_stage[s] = {
                    "executions": 0,
                    "successes": 0,
                    "total_retries": 0,
                    "total_delay": 0.0,
                }
            by_stage[s]["executions"] += 1
            if t["success"]:
                by_stage[s]["successes"] += 1
            by_stage[s]["total_retries"] += t["attempts"] - 1
            by_stage[s]["total_delay"] += t["total_delay"]

        stages = set(self._policies.keys()) | set(by_stage.keys())

        return {
            "total_executions": len(telemetry),
            "by_stage": by_stage,
            "circuits": {
                s: self.get_circuit(s).to_dict() for s in sorted(stages)
            },
            "budgets": {
                s: self.get_budget(s).to_dict() for s in sorted(stages)
            },
        }

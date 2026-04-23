# backend/ops/orchestration/retry.py
"""
Retry policies and execution for pipeline stages.

Provides:
- Configurable retry policies (exponential backoff, linear, fixed)
- Circuit breaker pattern
- Per-stage retry budgets
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("ops.retry")


class BackoffStrategy(str, Enum):
    FIXED = "fixed"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


@dataclass
class RetryPolicy:
    """Configurable retry policy."""
    max_retries: int = 3
    base_delay: float = 2.0
    max_delay: float = 120.0
    backoff: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    jitter: bool = True
    retryable_exceptions: tuple = (Exception,)

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for an attempt."""
        if self.backoff == BackoffStrategy.FIXED:
            delay = self.base_delay
        elif self.backoff == BackoffStrategy.LINEAR:
            delay = self.base_delay * (attempt + 1)
        else:  # exponential
            delay = self.base_delay * (2 ** attempt)

        delay = min(delay, self.max_delay)

        if self.jitter:
            import random
            delay *= (0.5 + random.random())

        return delay


class CircuitState(str, Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreaker:
    """Circuit breaker for protecting downstream services."""
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    half_open_max_calls: int = 1

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    half_open_calls: int = 0

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.half_open_calls = 0

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit breaker OPEN (failures={self.failure_count})")

    def can_execute(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
                logger.info("Circuit breaker → HALF_OPEN")
                return True
            return False
        # HALF_OPEN
        if self.half_open_calls < self.half_open_max_calls:
            self.half_open_calls += 1
            return True
        return False


class RetryExecutor:
    """Execute async functions with retry policy and optional circuit breaker."""

    def __init__(
        self,
        policy: Optional[RetryPolicy] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        self.policy = policy or RetryPolicy()
        self.circuit_breaker = circuit_breaker

    async def execute(
        self,
        func: Callable[..., Coroutine],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute function with retry and circuit breaker logic."""
        if self.circuit_breaker and not self.circuit_breaker.can_execute():
            raise RuntimeError("Circuit breaker is OPEN, request rejected")

        last_exc = None
        for attempt in range(self.policy.max_retries + 1):
            try:
                result = await func(*args, **kwargs)
                if self.circuit_breaker:
                    self.circuit_breaker.record_success()
                return result

            except self.policy.retryable_exceptions as e:
                last_exc = e
                if self.circuit_breaker:
                    self.circuit_breaker.record_failure()

                if attempt < self.policy.max_retries:
                    delay = self.policy.get_delay(attempt)
                    logger.warning(
                        f"Attempt {attempt+1} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"All {self.policy.max_retries+1} attempts failed")

        raise last_exc  # type: ignore[misc]

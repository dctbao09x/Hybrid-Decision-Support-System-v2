# backend/ops/resilience/bulkhead.py
"""
Bulkhead Pattern Implementation
===============================

Isolates resources between different services to prevent cascade failures.

Features:
- Concurrent request limiting per service
- Queue with timeout for overflow
- Graceful degradation with fallback
- Metrics collection

Usage:
    bulkhead = Bulkhead(BulkheadConfig(max_concurrent=10, max_wait_ms=500))
    
    async with bulkhead.acquire("kb_api"):
        result = await call_kb_service()
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Optional, TypeVar

logger = logging.getLogger("ops.resilience.bulkhead")

T = TypeVar("T")


class BulkheadState(str, Enum):
    """Bulkhead operational state."""
    NORMAL = "normal"          # Under capacity
    SATURATED = "saturated"    # At capacity, queueing
    OVERLOADED = "overloaded"  # Rejecting requests


@dataclass
class BulkheadConfig:
    """Configuration for a bulkhead."""
    max_concurrent: int = 10          # Max parallel requests
    max_wait_ms: int = 1000           # Max queue wait time
    max_queue_size: int = 50          # Max pending requests
    fallback_enabled: bool = True     # Allow fallback on rejection
    metrics_enabled: bool = True      # Collect metrics


@dataclass
class BulkheadMetrics:
    """Metrics for bulkhead monitoring."""
    total_requests: int = 0
    accepted_requests: int = 0
    rejected_requests: int = 0
    fallback_requests: int = 0
    current_concurrent: int = 0
    current_queue_size: int = 0
    avg_wait_time_ms: float = 0.0
    max_wait_time_ms: float = 0.0
    _wait_times: list = field(default_factory=list)
    
    def record_wait_time(self, wait_ms: float) -> None:
        self._wait_times.append(wait_ms)
        # Keep last 1000 samples
        if len(self._wait_times) > 1000:
            self._wait_times = self._wait_times[-1000:]
        self.avg_wait_time_ms = sum(self._wait_times) / len(self._wait_times)
        self.max_wait_time_ms = max(self.max_wait_time_ms, wait_ms)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "accepted_requests": self.accepted_requests,
            "rejected_requests": self.rejected_requests,
            "fallback_requests": self.fallback_requests,
            "current_concurrent": self.current_concurrent,
            "current_queue_size": self.current_queue_size,
            "avg_wait_time_ms": round(self.avg_wait_time_ms, 2),
            "max_wait_time_ms": round(self.max_wait_time_ms, 2),
            "acceptance_rate": round(
                self.accepted_requests / max(self.total_requests, 1) * 100, 2
            ),
        }


class BulkheadFull(Exception):
    """Raised when bulkhead rejects a request."""
    def __init__(self, name: str, message: str = ""):
        self.name = name
        self.message = message or f"Bulkhead '{name}' is full"
        super().__init__(self.message)


class Bulkhead:
    """
    Bulkhead for isolating resources.
    
    Limits concurrent requests to a service and provides
    queueing with timeout for overflow scenarios.
    """
    
    def __init__(
        self,
        name: str,
        config: Optional[BulkheadConfig] = None,
    ):
        self.name = name
        self.config = config or BulkheadConfig()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        self._queue_size = 0
        self._metrics = BulkheadMetrics()
        self._state = BulkheadState.NORMAL
        self._lock = asyncio.Lock()
    
    @property
    def state(self) -> BulkheadState:
        """Current bulkhead state."""
        return self._state
    
    @property
    def metrics(self) -> BulkheadMetrics:
        """Current metrics."""
        return self._metrics
    
    def _update_state(self) -> None:
        """Update bulkhead state based on current load."""
        concurrent = self.config.max_concurrent - self._semaphore._value
        self._metrics.current_concurrent = concurrent
        self._metrics.current_queue_size = self._queue_size
        
        if concurrent < self.config.max_concurrent and self._queue_size == 0:
            self._state = BulkheadState.NORMAL
        elif self._queue_size < self.config.max_queue_size:
            self._state = BulkheadState.SATURATED
        else:
            self._state = BulkheadState.OVERLOADED
    
    async def acquire(self) -> "BulkheadContext":
        """
        Acquire a slot in the bulkhead.
        
        Returns a context manager that releases the slot on exit.
        Raises BulkheadFull if queue is full and timeout expires.
        """
        self._metrics.total_requests += 1
        
        # Check if queue is full
        async with self._lock:
            if self._queue_size >= self.config.max_queue_size:
                if self._semaphore._value == 0:
                    self._metrics.rejected_requests += 1
                    raise BulkheadFull(self.name, "Queue full, request rejected")
            self._queue_size += 1
            self._update_state()
        
        start_wait = time.monotonic()
        try:
            # Wait for semaphore with timeout
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self.config.max_wait_ms / 1000.0,
            )
        except asyncio.TimeoutError:
            async with self._lock:
                self._queue_size -= 1
                self._metrics.rejected_requests += 1
                self._update_state()
            raise BulkheadFull(
                self.name,
                f"Timeout waiting for slot (waited {self.config.max_wait_ms}ms)",
            )
        
        wait_time = (time.monotonic() - start_wait) * 1000
        async with self._lock:
            self._queue_size -= 1
            self._metrics.accepted_requests += 1
            self._metrics.record_wait_time(wait_time)
            self._update_state()
        
        return BulkheadContext(self)
    
    def release(self) -> None:
        """Release a slot back to the bulkhead."""
        self._semaphore.release()
        self._update_state()
    
    async def execute(
        self,
        func: Callable[..., Coroutine[Any, Any, T]],
        *args: Any,
        fallback: Optional[Callable[..., Coroutine[Any, Any, T]]] = None,
        **kwargs: Any,
    ) -> T:
        """
        Execute a function within the bulkhead.
        
        Args:
            func: Async function to execute
            fallback: Optional fallback function if bulkhead is full
            *args, **kwargs: Arguments for func
            
        Returns:
            Result of func or fallback
        """
        try:
            async with await self.acquire():
                return await func(*args, **kwargs)
        except BulkheadFull:
            if fallback and self.config.fallback_enabled:
                self._metrics.fallback_requests += 1
                logger.warning(
                    f"Bulkhead '{self.name}' full, using fallback",
                    extra={"bulkhead": self.name},
                )
                return await fallback(*args, **kwargs)
            raise


class BulkheadContext:
    """Context manager for bulkhead slot."""
    
    def __init__(self, bulkhead: Bulkhead):
        self._bulkhead = bulkhead
    
    async def __aenter__(self) -> "BulkheadContext":
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self._bulkhead.release()


class BulkheadRegistry:
    """
    Registry for managing multiple bulkheads.
    
    Provides centralized access and configuration for all bulkheads.
    """
    
    _instance: Optional["BulkheadRegistry"] = None
    
    def __init__(self):
        self._bulkheads: Dict[str, Bulkhead] = {}
        self._default_config = BulkheadConfig()
    
    @classmethod
    def get_instance(cls) -> "BulkheadRegistry":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None
    
    def configure(
        self,
        name: str,
        config: BulkheadConfig,
    ) -> None:
        """Configure a bulkhead."""
        if name in self._bulkheads:
            logger.warning(f"Reconfiguring bulkhead: {name}")
        self._bulkheads[name] = Bulkhead(name, config)
        logger.info(
            f"Bulkhead configured: {name} "
            f"(max_concurrent={config.max_concurrent}, "
            f"max_wait_ms={config.max_wait_ms})"
        )
    
    def get(self, name: str) -> Bulkhead:
        """Get a bulkhead by name, creating with defaults if needed."""
        if name not in self._bulkheads:
            self._bulkheads[name] = Bulkhead(name, self._default_config)
            logger.info(f"Created default bulkhead: {name}")
        return self._bulkheads[name]
    
    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all bulkheads."""
        return {
            name: bh.metrics.to_dict()
            for name, bh in self._bulkheads.items()
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get overall status of all bulkheads."""
        states = {name: bh.state.value for name, bh in self._bulkheads.items()}
        overloaded = sum(1 for s in states.values() if s == "overloaded")
        saturated = sum(1 for s in states.values() if s == "saturated")
        
        return {
            "bulkhead_count": len(self._bulkheads),
            "overloaded_count": overloaded,
            "saturated_count": saturated,
            "states": states,
            "overall": (
                "critical" if overloaded > 0
                else "warning" if saturated > 0
                else "healthy"
            ),
        }


# ══════════════════════════════════════════════════════════════════════════════
# Default Bulkhead Configurations for HDSS Services
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_BULKHEAD_CONFIGS: Dict[str, BulkheadConfig] = {
    # Knowledge Base API - moderate concurrency, quick timeout
    "kb_api": BulkheadConfig(
        max_concurrent=15,
        max_wait_ms=800,
        max_queue_size=30,
    ),
    # MLOps API - lower concurrency (heavier operations)
    "mlops_api": BulkheadConfig(
        max_concurrent=8,
        max_wait_ms=1500,
        max_queue_size=20,
    ),
    # Scoring Engine - high concurrency (fast operations)
    "scoring": BulkheadConfig(
        max_concurrent=25,
        max_wait_ms=500,
        max_queue_size=50,
    ),
    # LLM Service - low concurrency (slow, expensive)
    "llm": BulkheadConfig(
        max_concurrent=5,
        max_wait_ms=2000,
        max_queue_size=10,
        fallback_enabled=True,
    ),
    # Crawler Service - moderate concurrency
    "crawler": BulkheadConfig(
        max_concurrent=10,
        max_wait_ms=1000,
        max_queue_size=20,
    ),
    # Database - high concurrency (pooled)
    "database": BulkheadConfig(
        max_concurrent=30,
        max_wait_ms=300,
        max_queue_size=100,
    ),
    # External APIs (careers, domains, etc.) - moderate
    "external_api": BulkheadConfig(
        max_concurrent=20,
        max_wait_ms=600,
        max_queue_size=40,
    ),
}


def init_default_bulkheads() -> BulkheadRegistry:
    """Initialize bulkheads with default configurations."""
    registry = BulkheadRegistry.get_instance()
    for name, config in DEFAULT_BULKHEAD_CONFIGS.items():
        registry.configure(name, config)
    return registry

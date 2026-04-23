# backend/ops/resilience/timeout_manager.py
"""
Timeout Manager
===============

Provides per-layer timeout configuration and enforcement.

Features:
- Configurable timeouts per endpoint/service
- Cascading timeout budgets
- Timeout tracking and alerting
- Graceful timeout handling

Usage:
    timeout_mgr = TimeoutManager()
    
    async with timeout_mgr.timeout("scoring", budget_ms=1000):
        result = await do_scoring()
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Coroutine, Dict, Optional, TypeVar

logger = logging.getLogger("ops.resilience.timeout")

T = TypeVar("T")


class TimeoutExceeded(Exception):
    """Raised when an operation exceeds its timeout budget."""
    def __init__(
        self,
        name: str,
        budget_ms: float,
        elapsed_ms: float,
    ):
        self.name = name
        self.budget_ms = budget_ms
        self.elapsed_ms = elapsed_ms
        self.message = (
            f"Operation '{name}' exceeded timeout: "
            f"{elapsed_ms:.1f}ms > {budget_ms:.1f}ms"
        )
        super().__init__(self.message)


@dataclass
class TimeoutConfig:
    """Configuration for a timeout layer."""
    default_ms: float = 5000.0        # Default timeout
    min_ms: float = 100.0             # Minimum allowed timeout
    max_ms: float = 30000.0           # Maximum allowed timeout
    warn_threshold_pct: float = 80.0  # Warn at this % of budget
    track_metrics: bool = True        # Track timeout metrics


@dataclass
class TimeoutMetrics:
    """Metrics for timeout tracking."""
    total_operations: int = 0
    timeout_count: int = 0
    warning_count: int = 0
    avg_elapsed_ms: float = 0.0
    p95_elapsed_ms: float = 0.0
    p99_elapsed_ms: float = 0.0
    _elapsed_times: list = field(default_factory=list)
    
    def record(self, elapsed_ms: float, timed_out: bool, warned: bool) -> None:
        self.total_operations += 1
        if timed_out:
            self.timeout_count += 1
        if warned:
            self.warning_count += 1
        
        self._elapsed_times.append(elapsed_ms)
        # Keep last 1000 samples
        if len(self._elapsed_times) > 1000:
            self._elapsed_times = self._elapsed_times[-1000:]
        
        sorted_times = sorted(self._elapsed_times)
        n = len(sorted_times)
        self.avg_elapsed_ms = sum(sorted_times) / n
        self.p95_elapsed_ms = sorted_times[int(n * 0.95)] if n > 0 else 0
        self.p99_elapsed_ms = sorted_times[int(n * 0.99)] if n > 0 else 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_operations": self.total_operations,
            "timeout_count": self.timeout_count,
            "timeout_rate_pct": round(
                self.timeout_count / max(self.total_operations, 1) * 100, 2
            ),
            "warning_count": self.warning_count,
            "avg_elapsed_ms": round(self.avg_elapsed_ms, 2),
            "p95_elapsed_ms": round(self.p95_elapsed_ms, 2),
            "p99_elapsed_ms": round(self.p99_elapsed_ms, 2),
        }


class TimeoutManager:
    """
    Manages timeouts across the system.
    
    Provides:
    - Per-layer timeout configuration
    - Context manager for timeout enforcement
    - Timeout budget tracking
    - Metrics collection
    """
    
    _instance: Optional["TimeoutManager"] = None
    
    def __init__(self):
        self._configs: Dict[str, TimeoutConfig] = {}
        self._metrics: Dict[str, TimeoutMetrics] = {}
        self._default_config = TimeoutConfig()
    
    @classmethod
    def get_instance(cls) -> "TimeoutManager":
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
        config: TimeoutConfig,
    ) -> None:
        """Configure timeout for a layer/operation."""
        self._configs[name] = config
        self._metrics[name] = TimeoutMetrics()
        logger.info(f"Timeout configured: {name} (default={config.default_ms}ms)")
    
    def get_config(self, name: str) -> TimeoutConfig:
        """Get configuration for a layer."""
        return self._configs.get(name, self._default_config)
    
    def get_timeout_ms(self, name: str, override_ms: Optional[float] = None) -> float:
        """Get effective timeout in milliseconds."""
        config = self.get_config(name)
        
        if override_ms is not None:
            # Clamp to configured bounds
            return max(config.min_ms, min(override_ms, config.max_ms))
        
        return config.default_ms
    
    @asynccontextmanager
    async def timeout(
        self,
        name: str,
        budget_ms: Optional[float] = None,
    ) -> AsyncIterator[None]:
        """
        Context manager that enforces a timeout.
        
        Usage:
            async with timeout_mgr.timeout("scoring", budget_ms=1000):
                await do_scoring()
        """
        config = self.get_config(name)
        effective_ms = self.get_timeout_ms(name, budget_ms)
        warn_ms = effective_ms * (config.warn_threshold_pct / 100.0)
        
        start = time.monotonic()
        timed_out = False
        warned = False
        
        try:
            yield
        except asyncio.TimeoutError:
            timed_out = True
            elapsed_ms = (time.monotonic() - start) * 1000
            raise TimeoutExceeded(name, effective_ms, elapsed_ms)
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            
            if not timed_out and elapsed_ms > warn_ms:
                warned = True
                logger.warning(
                    f"Operation '{name}' approaching timeout: "
                    f"{elapsed_ms:.1f}ms / {effective_ms:.1f}ms "
                    f"({elapsed_ms / effective_ms * 100:.0f}%)"
                )
            
            if config.track_metrics and name in self._metrics:
                self._metrics[name].record(elapsed_ms, timed_out, warned)
    
    async def execute(
        self,
        name: str,
        func: Callable[..., Coroutine[Any, Any, T]],
        *args: Any,
        budget_ms: Optional[float] = None,
        fallback: Optional[Callable[..., Coroutine[Any, Any, T]]] = None,
        **kwargs: Any,
    ) -> T:
        """
        Execute a function with timeout.
        
        Args:
            name: Timeout layer name
            func: Async function to execute
            budget_ms: Optional timeout override
            fallback: Fallback function on timeout
            *args, **kwargs: Arguments for func
            
        Returns:
            Result of func or fallback
        """
        effective_ms = self.get_timeout_ms(name, budget_ms)
        
        try:
            async with self.timeout(name, effective_ms):
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=effective_ms / 1000.0,
                )
        except (asyncio.TimeoutError, TimeoutExceeded):
            if fallback:
                logger.warning(
                    f"Timeout in '{name}', using fallback",
                    extra={"layer": name, "timeout_ms": effective_ms},
                )
                return await fallback(*args, **kwargs)
            raise
    
    def get_metrics(self, name: str) -> Optional[TimeoutMetrics]:
        """Get metrics for a layer."""
        return self._metrics.get(name)
    
    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all layers."""
        return {
            name: metrics.to_dict()
            for name, metrics in self._metrics.items()
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get overall timeout status."""
        total_ops = sum(m.total_operations for m in self._metrics.values())
        total_timeouts = sum(m.timeout_count for m in self._metrics.values())
        
        return {
            "configured_layers": len(self._configs),
            "total_operations": total_ops,
            "total_timeouts": total_timeouts,
            "timeout_rate_pct": round(
                total_timeouts / max(total_ops, 1) * 100, 2
            ),
            "layer_status": {
                name: {
                    "timeout_rate_pct": m.to_dict()["timeout_rate_pct"],
                    "p95_ms": m.to_dict()["p95_elapsed_ms"],
                }
                for name, m in self._metrics.items()
            },
        }


# ══════════════════════════════════════════════════════════════════════════════
# Default Timeout Configurations for HDSS
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_TIMEOUT_CONFIGS: Dict[str, TimeoutConfig] = {
    # Gateway layer - overall request timeout
    "gateway": TimeoutConfig(
        default_ms=10000.0,
        min_ms=1000.0,
        max_ms=30000.0,
        warn_threshold_pct=70.0,
    ),
    # Knowledge Base operations
    "kb_api": TimeoutConfig(
        default_ms=3000.0,
        min_ms=500.0,
        max_ms=10000.0,
    ),
    # MLOps operations (can be slower)
    "mlops_api": TimeoutConfig(
        default_ms=5000.0,
        min_ms=1000.0,
        max_ms=15000.0,
    ),
    # Scoring engine (should be fast)
    "scoring": TimeoutConfig(
        default_ms=2000.0,
        min_ms=200.0,
        max_ms=5000.0,
        warn_threshold_pct=60.0,
    ),
    # LLM operations (slow by nature)
    "llm": TimeoutConfig(
        default_ms=8000.0,
        min_ms=2000.0,
        max_ms=30000.0,
        warn_threshold_pct=80.0,
    ),
    # Database queries
    "database": TimeoutConfig(
        default_ms=1000.0,
        min_ms=100.0,
        max_ms=5000.0,
        warn_threshold_pct=70.0,
    ),
    # External API calls (careers, domains, etc.)
    "external_api": TimeoutConfig(
        default_ms=3000.0,
        min_ms=500.0,
        max_ms=8000.0,
    ),
    # Health checks
    "health": TimeoutConfig(
        default_ms=5000.0,
        min_ms=500.0,
        max_ms=10000.0,
    ),
}


def init_default_timeouts() -> TimeoutManager:
    """Initialize timeout manager with default configurations."""
    manager = TimeoutManager.get_instance()
    for name, config in DEFAULT_TIMEOUT_CONFIGS.items():
        manager.configure(name, config)
    return manager

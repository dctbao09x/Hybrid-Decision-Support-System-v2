# backend/ops/resilience/__init__.py
"""
Resilience Module
=================

Production-grade resilience patterns for the HDSS backend.

Components:
- Bulkhead: Resource isolation between services
- CircuitBreaker: Failure detection and recovery
- RateLimiter: Request throttling
- Timeout: Per-layer timeout management
"""

from .bulkhead import Bulkhead, BulkheadConfig, BulkheadRegistry
from .timeout_manager import TimeoutManager, TimeoutConfig

__all__ = [
    "Bulkhead",
    "BulkheadConfig",
    "BulkheadRegistry",
    "TimeoutManager",
    "TimeoutConfig",
]

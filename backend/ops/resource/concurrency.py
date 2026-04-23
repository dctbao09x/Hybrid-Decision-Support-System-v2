# backend/ops/resource/concurrency.py
"""
Concurrency Controller for crawler and pipeline operations.

Provides:
- Semaphore-based browser pool limiting
- Rate limiting per domain
- Fair scheduling across crawl targets
- Back-pressure mechanism
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger("ops.resource.concurrency")


@dataclass
class RateLimitConfig:
    """Rate limit configuration per domain."""
    requests_per_second: float = 1.0
    burst_size: int = 5
    cooldown_on_429: float = 60.0  # seconds to wait on HTTP 429


class TokenBucket:
    """Token bucket rate limiter."""

    def __init__(self, rate: float, burst: int):
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, timeout: float = 30.0) -> bool:
        """Acquire a token, blocking until available or timeout."""
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            async with self._lock:
                self._refill()
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return True

            # Wait proportional to token refill rate
            wait = 1.0 / self.rate if self.rate > 0 else 1.0
            await asyncio.sleep(min(wait, deadline - time.monotonic()))

        return False

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_refill = now


class ConcurrencyController:
    """
    Controls concurrency for crawler operations.

    Features:
    - Global browser pool semaphore
    - Per-domain rate limiting
    - Request queue with priority
    - Back-pressure signaling
    """

    def __init__(
        self,
        max_browsers: int = 3,
        max_pages_per_browser: int = 5,
        default_rate: float = 1.0,
        default_burst: int = 5,
    ):
        self._browser_semaphore = asyncio.Semaphore(max_browsers)
        self._page_semaphore = asyncio.Semaphore(max_browsers * max_pages_per_browser)
        self._rate_limiters: Dict[str, TokenBucket] = {}
        self._default_rate = default_rate
        self._default_burst = default_burst
        self._active_browsers = 0
        self._active_pages = 0
        self._stats: Dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    def configure_domain(
        self, domain: str, config: RateLimitConfig
    ) -> None:
        """Set rate limit for a specific domain."""
        self._rate_limiters[domain] = TokenBucket(
            rate=config.requests_per_second,
            burst=config.burst_size,
        )
        logger.info(f"Rate limit configured for {domain}: {config.requests_per_second} req/s")

    async def acquire_browser(self) -> bool:
        """Acquire a browser slot. Blocks until available."""
        await self._browser_semaphore.acquire()
        async with self._lock:
            self._active_browsers += 1
            self._stats["browsers_acquired"] += 1
        return True

    def release_browser(self) -> None:
        """Release a browser slot."""
        self._browser_semaphore.release()
        # Use asyncio.get_event_loop() safe pattern
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._decrement_browsers())
        except RuntimeError:
            pass

    async def _decrement_browsers(self) -> None:
        async with self._lock:
            self._active_browsers = max(0, self._active_browsers - 1)

    async def acquire_page(self) -> bool:
        """Acquire a page slot within a browser."""
        await self._page_semaphore.acquire()
        async with self._lock:
            self._active_pages += 1
            self._stats["pages_acquired"] += 1
        return True

    def release_page(self) -> None:
        """Release a page slot."""
        self._page_semaphore.release()
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._decrement_pages())
        except RuntimeError:
            pass

    async def _decrement_pages(self) -> None:
        async with self._lock:
            self._active_pages = max(0, self._active_pages - 1)

    async def rate_limit(self, domain: str, timeout: float = 30.0) -> bool:
        """Wait for rate limit clearance for a domain."""
        if domain not in self._rate_limiters:
            self._rate_limiters[domain] = TokenBucket(
                rate=self._default_rate,
                burst=self._default_burst,
            )

        acquired = await self._rate_limiters[domain].acquire(timeout)
        if acquired:
            async with self._lock:
                self._stats[f"requests_{domain}"] += 1
        return acquired

    async def apply_backpressure(self, domain: str, seconds: float) -> None:
        """Apply back-pressure for a domain (e.g., on HTTP 429)."""
        logger.warning(f"Back-pressure: {domain} throttled for {seconds}s")
        async with self._lock:
            self._stats[f"backpressure_{domain}"] += 1
        await asyncio.sleep(seconds)

    def get_stats(self) -> Dict[str, Any]:
        """Get concurrency statistics."""
        return {
            "active_browsers": self._active_browsers,
            "active_pages": self._active_pages,
            "stats": dict(self._stats),
        }

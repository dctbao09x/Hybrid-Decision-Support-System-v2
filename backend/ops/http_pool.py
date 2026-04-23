"""
HTTP Client Pool Management
===========================

Provides a shared, optimized HTTP client pool for all backend services.
Prevents connection pool exhaustion under high load.

Usage:
    from backend.ops.http_pool import get_http_client, get_async_client
    
    # Sync usage
    client = get_http_client()
    response = client.get("https://api.example.com/data")
    
    # Async usage
    async with get_async_client() as client:
        response = await client.get("https://api.example.com/data")
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

import httpx

logger = logging.getLogger("ops.http_pool")


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration from environment
# ═══════════════════════════════════════════════════════════════════════════════

MAX_CONNECTIONS = int(os.getenv("HTTP_MAX_CONNECTIONS", 200))
MAX_CONNECTIONS_PER_HOST = int(os.getenv("HTTP_MAX_PER_HOST", 50))
KEEPALIVE_TIMEOUT = int(os.getenv("HTTP_KEEPALIVE", 30))
CONNECT_TIMEOUT = float(os.getenv("HTTP_CONNECT_TIMEOUT", 5.0))
READ_TIMEOUT = float(os.getenv("HTTP_READ_TIMEOUT", 30.0))
TOTAL_TIMEOUT = float(os.getenv("HTTP_TOTAL_TIMEOUT", 60.0))


# ═══════════════════════════════════════════════════════════════════════════════
# Connection Pool Limits
# ═══════════════════════════════════════════════════════════════════════════════

_limits = httpx.Limits(
    max_connections=MAX_CONNECTIONS,
    max_keepalive_connections=MAX_CONNECTIONS_PER_HOST,
    keepalive_expiry=KEEPALIVE_TIMEOUT,
)

_timeout = httpx.Timeout(
    connect=CONNECT_TIMEOUT,
    read=READ_TIMEOUT,
    write=30.0,
    pool=10.0,  # Wait for connection from pool
)


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton Clients
# ═══════════════════════════════════════════════════════════════════════════════

_sync_client: Optional[httpx.Client] = None
_async_client: Optional[httpx.AsyncClient] = None
_lock = asyncio.Lock()


def get_http_client() -> httpx.Client:
    """
    Get the shared synchronous HTTP client.
    
    Thread-safe, reuses connections via pool.
    """
    global _sync_client
    
    if _sync_client is None:
        _sync_client = httpx.Client(
            limits=_limits,
            timeout=_timeout,
            http2=True,  # Enable HTTP/2 for better performance
            follow_redirects=True,
        )
        logger.info(
            f"HTTP sync client initialized: max_conn={MAX_CONNECTIONS}, "
            f"per_host={MAX_CONNECTIONS_PER_HOST}"
        )
    
    return _sync_client


async def get_async_client_instance() -> httpx.AsyncClient:
    """
    Get the shared asynchronous HTTP client singleton.
    
    Uses a lock to prevent race conditions during initialization.
    """
    global _async_client
    
    async with _lock:
        if _async_client is None:
            _async_client = httpx.AsyncClient(
                limits=_limits,
                timeout=_timeout,
                http2=True,
                follow_redirects=True,
            )
            logger.info(
                f"HTTP async client initialized: max_conn={MAX_CONNECTIONS}, "
                f"per_host={MAX_CONNECTIONS_PER_HOST}"
            )
    
    return _async_client


@asynccontextmanager
async def get_async_client():
    """
    Context manager for async HTTP client.
    
    For one-off requests where you don't want to manage the client lifecycle.
    Uses the shared pool if available, otherwise creates a temporary one.
    
    Usage:
        async with get_async_client() as client:
            response = await client.get(url)
    """
    # Try to use singleton first
    if _async_client is not None:
        yield _async_client
    else:
        # Create temporary client with same pool settings
        async with httpx.AsyncClient(
            limits=_limits,
            timeout=_timeout,
            http2=True,
            follow_redirects=True,
        ) as client:
            yield client


async def close_async_client():
    """Close the async client (call on shutdown)."""
    global _async_client
    
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None
        logger.info("HTTP async client closed")


def close_sync_client():
    """Close the sync client (call on shutdown)."""
    global _sync_client
    
    if _sync_client is not None:
        _sync_client.close()
        _sync_client = None
        logger.info("HTTP sync client closed")


async def cleanup():
    """Cleanup all HTTP clients."""
    await close_async_client()
    close_sync_client()


# ═══════════════════════════════════════════════════════════════════════════════
# Health Check
# ═══════════════════════════════════════════════════════════════════════════════

def get_pool_status() -> dict:
    """Get current pool status for monitoring."""
    return {
        "config": {
            "max_connections": MAX_CONNECTIONS,
            "max_per_host": MAX_CONNECTIONS_PER_HOST,
            "keepalive_timeout": KEEPALIVE_TIMEOUT,
            "connect_timeout": CONNECT_TIMEOUT,
            "read_timeout": READ_TIMEOUT,
        },
        "sync_client_active": _sync_client is not None,
        "async_client_active": _async_client is not None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Module Exports
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "get_http_client",
    "get_async_client",
    "get_async_client_instance",
    "close_async_client",
    "close_sync_client",
    "cleanup",
    "get_pool_status",
]

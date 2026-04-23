"""
Server Performance Configuration
================================

Centralized configuration for HTTP pools, database pools, and system tuning.
Optimized for:
- Target: ≥100 RPS
- CPU: 4 cores
- RAM: 16GB
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class HTTPPoolConfig:
    """HTTP client connection pool settings."""
    
    # Max total connections across all hosts
    max_connections: int = 200
    
    # Max connections per host
    max_connections_per_host: int = 50
    
    # Keep-alive timeout (seconds)
    keepalive_timeout: int = 30
    
    # Connection timeout (seconds)
    connect_timeout: float = 5.0
    
    # Read timeout (seconds)
    read_timeout: float = 30.0
    
    # Total request timeout (seconds)
    total_timeout: float = 60.0
    
    # Enable TCP keep-alive
    tcp_keepalive: bool = True
    
    # DNS cache TTL (seconds)
    dns_cache_ttl: int = 300


@dataclass
class DatabasePoolConfig:
    """Database connection pool settings (for PostgreSQL/MySQL)."""
    
    # Pool size (concurrent connections)
    pool_size: int = 20
    
    # Max overflow (temporary extra connections)
    max_overflow: int = 30
    
    # Pool timeout (seconds to wait for connection)
    pool_timeout: int = 30
    
    # Connection recycle time (seconds)
    pool_recycle: int = 1800
    
    # Pre-ping connections before use
    pool_pre_ping: bool = True


@dataclass
class ServerConfig:
    """Main server configuration."""
    
    # Workers (Gunicorn/Uvicorn)
    workers: int = 8
    
    # Backlog queue size
    backlog: int = 2048
    
    # Worker connections (async)
    worker_connections: int = 1000
    
    # Request timeout
    request_timeout: float = 30.0
    
    # Keep-alive timeout
    keepalive_timeout: int = 5
    
    # Max requests before worker restart
    max_requests: int = 10000
    
    # Preload application
    preload_app: bool = True
    
    # HTTP pool config
    http_pool: HTTPPoolConfig = field(default_factory=HTTPPoolConfig)
    
    # Database pool config
    db_pool: DatabasePoolConfig = field(default_factory=DatabasePoolConfig)
    
    def to_env_dict(self) -> Dict[str, str]:
        """Export as environment variables."""
        return {
            "GUNICORN_WORKERS": str(self.workers),
            "GUNICORN_BACKLOG": str(self.backlog),
            "GUNICORN_TIMEOUT": str(int(self.request_timeout)),
            "HTTP_MAX_CONNECTIONS": str(self.http_pool.max_connections),
            "HTTP_MAX_PER_HOST": str(self.http_pool.max_connections_per_host),
            "HTTP_KEEPALIVE": str(self.http_pool.keepalive_timeout),
            "HTTP_CONNECT_TIMEOUT": str(self.http_pool.connect_timeout),
            "HTTP_READ_TIMEOUT": str(self.http_pool.read_timeout),
            "DB_POOL_SIZE": str(self.db_pool.pool_size),
            "DB_MAX_OVERFLOW": str(self.db_pool.max_overflow),
            "DB_POOL_TIMEOUT": str(self.db_pool.pool_timeout),
        }


# Default production config for 4-core CPU
PRODUCTION_CONFIG = ServerConfig(
    workers=8,
    backlog=2048,
    worker_connections=1000,
    request_timeout=30.0,
    keepalive_timeout=5,
    max_requests=10000,
    preload_app=True,
    http_pool=HTTPPoolConfig(
        max_connections=200,
        max_connections_per_host=50,
        keepalive_timeout=30,
        connect_timeout=5.0,
        read_timeout=30.0,
    ),
    db_pool=DatabasePoolConfig(
        pool_size=20,
        max_overflow=30,
        pool_timeout=30,
        pool_recycle=1800,
    ),
)


# Development config (single worker)
DEVELOPMENT_CONFIG = ServerConfig(
    workers=1,
    backlog=128,
    worker_connections=100,
    request_timeout=60.0,
    keepalive_timeout=5,
    max_requests=0,  # No limit
    preload_app=False,
    http_pool=HTTPPoolConfig(
        max_connections=20,
        max_connections_per_host=10,
    ),
    db_pool=DatabasePoolConfig(
        pool_size=5,
        max_overflow=10,
    ),
)


def get_config() -> ServerConfig:
    """Get configuration based on environment."""
    env = os.getenv("ENVIRONMENT", "development").lower()
    if env in ("production", "prod"):
        return PRODUCTION_CONFIG
    return DEVELOPMENT_CONFIG


def apply_config():
    """Apply configuration to environment."""
    config = get_config()
    for key, value in config.to_env_dict().items():
        if key not in os.environ:
            os.environ[key] = value
    return config


# Export for use in other modules
__all__ = [
    "HTTPPoolConfig",
    "DatabasePoolConfig", 
    "ServerConfig",
    "PRODUCTION_CONFIG",
    "DEVELOPMENT_CONFIG",
    "get_config",
    "apply_config",
]


if __name__ == "__main__":
    config = PRODUCTION_CONFIG
    print("=" * 60)
    print("PRODUCTION SERVER CONFIGURATION")
    print("=" * 60)
    print(f"\n[Server]")
    print(f"  Workers: {config.workers}")
    print(f"  Backlog: {config.backlog}")
    print(f"  Worker Connections: {config.worker_connections}")
    print(f"  Request Timeout: {config.request_timeout}s")
    print(f"  Max Requests: {config.max_requests}")
    
    print(f"\n[HTTP Pool]")
    print(f"  Max Connections: {config.http_pool.max_connections}")
    print(f"  Per Host: {config.http_pool.max_connections_per_host}")
    print(f"  Keepalive: {config.http_pool.keepalive_timeout}s")
    
    print(f"\n[Database Pool]")
    print(f"  Pool Size: {config.db_pool.pool_size}")
    print(f"  Max Overflow: {config.db_pool.max_overflow}")
    print(f"  Recycle: {config.db_pool.pool_recycle}s")
    print("=" * 60)

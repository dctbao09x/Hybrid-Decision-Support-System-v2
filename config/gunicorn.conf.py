"""
Gunicorn Configuration for Production Deployment
=================================================

Optimized for:
- Intel i5-7500 (4 cores @ 3.4GHz)
- 16GB RAM
- Target: ≥100 RPS, p95 <100ms, 99.5% success

Formula:
- Workers = 2 * CPU_CORES + 1 = 2 * 4 + 1 = 9 (recommended)
- For I/O-bound async: workers = CPU_CORES * 2 = 8
- Memory per worker: ~200MB -> 8 workers = 1.6GB (safe)

Usage:
    gunicorn -c config/gunicorn.conf.py backend.run_api:app
"""

import multiprocessing
import os

# ═══════════════════════════════════════════════════════════════════════════════
# Server Socket
# ═══════════════════════════════════════════════════════════════════════════════

bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")
backlog = 2048  # TCP backlog queue size

# ═══════════════════════════════════════════════════════════════════════════════
# Worker Processes
# ═══════════════════════════════════════════════════════════════════════════════

# Worker class: UvicornWorker for async FastAPI
worker_class = "uvicorn.workers.UvicornWorker"

# Number of workers (I/O-bound async optimal = CPU * 2)
# For 4 cores: 8 workers (can handle ~25 RPS each = 200 RPS theoretical)
workers = int(os.getenv("GUNICORN_WORKERS", min(multiprocessing.cpu_count() * 2, 8)))

# Worker connections (for async workers, this is concurrent connections per worker)
# Each worker can handle many concurrent connections
worker_connections = 1000

# Threads per worker (not used with UvicornWorker, but set for sync workers)
threads = 1

# ═══════════════════════════════════════════════════════════════════════════════
# Timeouts
# ═══════════════════════════════════════════════════════════════════════════════

# Worker timeout (seconds) - kill worker if no response
timeout = 30

# Request timeout - how long to wait for request
graceful_timeout = 30

# Keep-alive connections (seconds)
keepalive = 5

# ═══════════════════════════════════════════════════════════════════════════════
# Performance Tuning
# ═══════════════════════════════════════════════════════════════════════════════

# Preload app before forking workers (saves memory, faster startup)
preload_app = True

# Max requests before worker restart (prevents memory leaks)
max_requests = 10000

# Jitter to prevent all workers restarting at once
max_requests_jitter = 1000

# ═══════════════════════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════════════════════

# Access log (- for stdout)
accesslog = "-"

# Error log (- for stderr)
errorlog = "-"

# Log level
loglevel = os.getenv("LOG_LEVEL", "info")

# Access log format
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# ═══════════════════════════════════════════════════════════════════════════════
# Process Naming
# ═══════════════════════════════════════════════════════════════════════════════

# Process name prefix
proc_name = "hdss_api"

# ═══════════════════════════════════════════════════════════════════════════════
# Server Hooks
# ═══════════════════════════════════════════════════════════════════════════════

def on_starting(server):
    """Called just before the master process is initialized."""
    pass

def on_reload(server):
    """Called on SIGHUP reload."""
    pass

def pre_fork(server, worker):
    """Called just before a worker is forked."""
    pass

def post_fork(server, worker):
    """Called just after a worker has been forked."""
    pass

def pre_exec(server):
    """Called just before a new master process is forked."""
    pass

def when_ready(server):
    """Called just after the server is started."""
    print(f"[Gunicorn] Server ready with {workers} workers")

def worker_int(worker):
    """Called when worker receives INT or QUIT signal."""
    pass

def worker_abort(worker):
    """Called when worker receives SIGABRT signal."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("GUNICORN CONFIGURATION SUMMARY")
    print("=" * 60)
    print(f"  Bind: {bind}")
    print(f"  Workers: {workers}")
    print(f"  Worker Class: {worker_class}")
    print(f"  Worker Connections: {worker_connections}")
    print(f"  Timeout: {timeout}s")
    print(f"  Keepalive: {keepalive}s")
    print(f"  Preload: {preload_app}")
    print(f"  Max Requests: {max_requests} ± {max_requests_jitter}")
    print(f"  Backlog: {backlog}")
    print("=" * 60)

# backend/run_api.py
"""
Unified API Gateway Entry Point
===============================

**SINGLE PRODUCTION ENTRYPOINT**

Usage: 
    python -m uvicorn backend.run_api:app --host 0.0.0.0 --port 8000

All endpoints are under /api/v1/*:
  /api/v1/health/*    — Health checks
  /api/v1/ops/*       — Operations
  /api/v1/ml/*        — ML operations
  /api/v1/infer/*     — Inference
  /api/v1/explain/*   — Explanations
  /api/v1/pipeline/*  — Data pipeline
  /api/v1/crawlers/*  — Crawlers
  /api/v1/kb/*        — Knowledge base
  /api/v1/chat/*      — Chat
  
Phase-B Endpoints:
  /api/v1/eval/*      — ML Evaluation runs
  /api/v1/rules/*     — Rule Engine
  /api/v1/taxonomy/*  — Taxonomy management
  /api/v1/scoring/*   — Career scoring
"""

import logging
import sys
import time
import asyncio
from pathlib import Path
from threading import Lock

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("run_api")

# Ensure backend is in path
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import unified API gateway
from backend.inference.api_server_v2 import (
    CANONICAL_STARTUP_ENTRYPOINT,
    create_inference_api,
)

# Initialize components
main_control = None
ops_hub = None
crawler_manager = None

# Try to initialize MainController
try:
    from backend.main_controller import MainController
    from backend.crawler_manager import CrawlerManager
    from backend.ops.integration import OpsHub
    
    ops_hub = OpsHub()
    crawler_manager = CrawlerManager()
    main_control = MainController(
        crawler_manager=crawler_manager,
        ops=ops_hub,
    )
    logger.info("Full system initialized: MainController + OpsHub + CrawlerManager")
except Exception as e:
    logger.warning(f"Running in minimal mode (some features disabled): {e}")

# Create unified API gateway
_api = create_inference_api(
    main_control=main_control,
    ops_hub=ops_hub,
    crawler_manager=crawler_manager,
    strict_startup_validation=True,
)

CANONICAL_ENTRYPOINT = CANONICAL_STARTUP_ENTRYPOINT

# Export app for uvicorn
app = _api.app

REQUEST_TIMEOUT_SECONDS = 10.0   # Reduced from 12s for faster failure detection
# LLM-backed and end-to-end decision routes need longer timeout
# because they include extraction/explanation stages.
LLM_ROUTE_TIMEOUT_SECONDS = 60.0
LLM_ROUTES = {
    "/api/v1/explain/score-analytics",
    "/api/v1/one-button/run",
    "/api/v1/decision/run",
}
SLOW_REQUEST_THRESHOLD_SECONDS = 2.0  # Reduced from 3s for earlier warnings
PENDING_ALERT_THRESHOLD = 15    # Reduced from 20 for earlier load detection
_pending_request_count = 0
_pending_lock = Lock()

# ══════════════════════════════════════════════════════════════════════════════
# Resilience Infrastructure
# ══════════════════════════════════════════════════════════════════════════════

from backend.ops.resilience.bulkhead import (
    BulkheadRegistry,
    init_default_bulkheads,
)
from backend.ops.resilience.timeout_manager import (
    TimeoutManager,
    init_default_timeouts,
)
from backend.ops.resilience.readiness import (
    get_readiness_probe,
    ReadinessProbe,
)

# Initialize resilience components
bulkhead_registry = init_default_bulkheads()
timeout_manager = init_default_timeouts()
readiness_probe = get_readiness_probe()


# ══════════════════════════════════════════════════════════════════════════════
# Additional Health Endpoints (not in health_router)
# NOTE: /api/v1/health/ready and /api/v1/health/* are in health_router via router_registry
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/health/startup", tags=["Health"])
async def health_startup():
    """
    Startup probe - returns 200 when initialization is complete.
    
    Use this for Kubernetes startupProbe.
    """
    result = await readiness_probe.check_startup()
    startup_contract = _api.get_startup_contract()
    result["canonical_entrypoint"] = CANONICAL_ENTRYPOINT
    result["startup_validation"] = startup_contract.get("validation", {})
    result["startup_contract_version"] = "v1"
    if not result.get("startup_complete", False):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content=result)
    return result


@app.get("/api/v1/health/startup/contract", tags=["Health"])
async def health_startup_contract():
    """Return canonical startup contract and latest validation report."""
    report = _api.get_startup_contract()
    report["canonical_entrypoint"] = CANONICAL_ENTRYPOINT
    report["strict_startup_validation"] = True
    return report


@app.get("/api/v1/resilience/bulkheads", tags=["Resilience"])
async def resilience_bulkheads():
    """Get bulkhead status and metrics."""
    return {
        "status": bulkhead_registry.get_status(),
        "metrics": bulkhead_registry.get_all_metrics(),
    }


@app.get("/api/v1/resilience/timeouts", tags=["Resilience"])
async def resilience_timeouts():
    """Get timeout manager status and metrics."""
    return {
        "status": timeout_manager.get_status(),
        "metrics": timeout_manager.get_all_metrics(),
    }


@app.middleware("http")
async def request_timeout_and_monitoring(request: Request, call_next):
    global _pending_request_count

    started_at = time.perf_counter()
    with _pending_lock:
        _pending_request_count += 1
        pending = _pending_request_count

    if pending > PENDING_ALERT_THRESHOLD:
        logger.warning("Pending request count exceeded threshold", extra={"pending": pending, "path": request.url.path})

    try:
        route_timeout = LLM_ROUTE_TIMEOUT_SECONDS if request.url.path in LLM_ROUTES else REQUEST_TIMEOUT_SECONDS
        response = await asyncio.wait_for(call_next(request), timeout=route_timeout)
        return response
    except asyncio.TimeoutError:
        logger.error("Request timeout", extra={"path": request.url.path, "timeout_seconds": REQUEST_TIMEOUT_SECONDS})
        return JSONResponse(status_code=504, content={"error": "request_timeout", "message": "Request timed out"})
    except Exception as error:
        logger.exception("Unhandled request error", extra={"path": request.url.path})
        return JSONResponse(status_code=500, content={"error": "internal_error", "message": str(error)})
    finally:
        duration = time.perf_counter() - started_at
        with _pending_lock:
            _pending_request_count -= 1
            pending_after = _pending_request_count

        if duration > SLOW_REQUEST_THRESHOLD_SECONDS:
            logger.warning(
                "Slow API request",
                extra={
                    "path": request.url.path,
                    "duration_seconds": round(duration, 3),
                    "pending": pending_after,
                },
            )


# ══════════════════════════════════════════════════════════════════════════════
# Readiness Probe Registration
# ══════════════════════════════════════════════════════════════════════════════

# Register health checks for readiness probe
async def _check_ops_hub():
    """Check OpsHub health."""
    if ops_hub:
        try:
            result = await ops_hub.health.live()
            return {"status": "healthy", "message": "OpsHub responding"}
        except Exception as e:
            return {"status": "unhealthy", "message": str(e)[:200]}
    return {"status": "degraded", "message": "OpsHub not initialized"}


async def _check_main_controller():
    """Check MainController availability."""
    if main_control:
        return {"status": "healthy", "message": "MainController ready"}
    return {"status": "degraded", "message": "MainController not initialized"}


async def _check_api_gateway():
    """Check API gateway health."""
    return {"status": "healthy", "message": "API Gateway responding"}


# Register checks
readiness_probe.register_check("api_gateway", _check_api_gateway, critical=True)
readiness_probe.register_check("ops_hub", _check_ops_hub, critical=False)
readiness_probe.register_check("main_controller", _check_main_controller, critical=False)


@app.on_event("startup")
async def _init_resilience():
    """Initialize resilience infrastructure on startup."""
    import time as _time
    startup_start = _time.monotonic()
    
    logger.info("Initializing resilience infrastructure...")
    
    # Initialize OpsHub if available
    if ops_hub:
        await ops_hub.startup()
    
    # Mark startup complete
    startup_ms = (_time.monotonic() - startup_start) * 1000
    readiness_probe.mark_startup_complete(startup_ms)
    logger.info(f"Resilience infrastructure ready in {startup_ms:.1f}ms")


# ══════════════════════════════════════════════════════════════════════════════
# Router Registration Note
# ══════════════════════════════════════════════════════════════════════════════
# All routers (including Admin Auth, Admin Gateway, LiveOps) are now registered
# via backend.api.router_registry for DETERMINISTIC startup.
#
# See: backend/api/router_registry.py
#
# This ensures:
# 1. All workers have identical routing tables
# 2. No silent failures from conditional imports
# 3. Server fails fast if any router dependency is missing
# ══════════════════════════════════════════════════════════════════════════════

# LiveOps lifecycle events - get command engine from registry
@app.on_event("startup")
async def _start_liveops_engine():
    """Start LiveOps command engine on app startup."""
    from backend.api.router_registry import setup_liveops_command_engine
    # Engine is already set up during router registration
    # We just need to start it
    try:
        from backend.ops.command_engine.engine import CommandEngine
        engine = CommandEngine._instance if hasattr(CommandEngine, '_instance') else None
        if engine:
            await engine.start()
            logger.info("LiveOps CommandEngine started")
    except Exception as e:
        logger.warning(f"LiveOps engine start skipped: {e}")


@app.on_event("shutdown")
async def _stop_liveops_engine():
    """Stop LiveOps command engine on app shutdown."""
    try:
        from backend.ops.command_engine.engine import CommandEngine
        engine = CommandEngine._instance if hasattr(CommandEngine, '_instance') else None
        if engine:
            await engine.stop()
            logger.info("LiveOps CommandEngine stopped")
    except Exception as e:
        logger.warning(f"LiveOps engine stop skipped: {e}")


logger.info("API Gateway ready: http://localhost:8000/api/v1")


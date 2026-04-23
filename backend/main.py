import sys
import os
import io
import uuid
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

import asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# --------------------------------------------------
# PATH SETUP
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))


from backend.core.telemetry.context import correlation_id_var, request_id_var
from backend.core.telemetry.otel_setup import setup_telemetry
from backend.core.telemetry.redaction import RedactionFilter
from backend.api.middleware.auth import (
    auth_http_exception_to_response,
    configure_auth_from_env,
    set_auth_metrics_collector,
    verify_token,
)
from backend.api.middleware.rate_limit import (
    apply_rate_limit_headers,
    check_rate_limit,
    configure_rate_limit_from_env,
    rate_limit_http_exception_to_response,
    set_rate_limit_metrics_collector,
)
from backend.state import set_operational_state_metrics_collector


class CorrelationIdFilter(logging.Filter):
    def filter(self, record):
        # Always set correlation_id and request_id to avoid KeyError in format
        if not hasattr(record, 'correlation_id'):
            record.correlation_id = correlation_id_var.get() or "-"
        if not hasattr(record, 'request_id'):
            record.request_id = request_id_var.get() or "-"
        return True


# --------------------------------------------------
# LOGGING
# --------------------------------------------------

# Use a safe format that works even if correlation_id is missing
LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | corr=%(correlation_id)s | req=%(request_id)s | %(message)s"
)

# ------------------------------------------------------------------
# Force UTF-8 on the console stream so Unicode chars in log messages
# (e.g. check marks, Vietnamese text) never crash the handler on
# Windows where the default console codec is cp1252.
# ------------------------------------------------------------------
try:
    _utf8_stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
except AttributeError:
    # In environments without .buffer (e.g. some IDEs) fall back gracefully.
    _utf8_stdout = sys.stdout  # type: ignore[assignment]

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(_utf8_stdout)],
)

root_logger = logging.getLogger()
root_logger.addFilter(CorrelationIdFilter())
root_logger.addFilter(RedactionFilter())

setup_telemetry(service_name=os.getenv("SERVICE_NAME", "hdss-backend"))

logger = logging.getLogger(__name__)


# --------------------------------------------------
# SCHEMAS
# --------------------------------------------------

class PersonalInfo(BaseModel):
    fullName: str
    age: str
    education: str


class ChatMessage(BaseModel):
    role: str
    text: str


class UserProfileRequest(BaseModel):
    personalInfo: PersonalInfo
    interests: List[str]
    skills: str
    careerGoal: str
    chatHistory: Optional[List[ChatMessage]] = []


class UserProfileResponse(BaseModel):
    age: int
    education_level: str
    interest_tags: List[str]
    skill_tags: List[str]
    goal_cleaned: str
    intent: str
    chat_summary: str
    confidence_score: float


class RecommendationsRequest(BaseModel):
    processedProfile: Optional[Dict[str, Any]] = None
    userProfile: Optional[Dict[str, Any]] = None
    assessmentAnswers: Optional[Dict[str, Any]] = None
    chatHistory: Optional[List[ChatMessage]] = None


# --------------------------------------------------
# CORE IMPORTS
# --------------------------------------------------

try:
    from backend.crawler_manager import CrawlerManager
    from backend.schemas.crawler import CrawlStatus, CrawlRequest
    _crawler_available = True
except ImportError as _crawler_import_err:
    logger.warning(f"Crawler module unavailable (likely missing playwright): {_crawler_import_err}")
    CrawlerManager = None  # type: ignore[assignment,misc]
    CrawlStatus = None  # type: ignore[assignment]
    CrawlRequest = None  # type: ignore[assignment]
    _crawler_available = False

try:
    from backend.main_controller import MainController
    _main_controller_available = True
except ImportError as _mc_err:
    logger.warning(f"MainController unavailable: {_mc_err}")
    MainController = None  # type: ignore[assignment,misc]
    _main_controller_available = False

try:
    from backend.processor import process_user_profile
except ImportError:
    process_user_profile = None  # type: ignore[assignment]

try:
    from backend.ops.integration import OpsHub
except ImportError as _ops_err:
    logger.warning(f"OpsHub unavailable: {_ops_err}")
    OpsHub = None  # type: ignore[assignment,misc]


# --------------------------------------------------
# APP INIT
# --------------------------------------------------

app = FastAPI(
    title="Hybrid Decision Support System API",
    description=(
        "Full-stack Decision Support System.\n\n"
        "**Core Pipeline**\n"
        "- `/api/v1/decision` — One-button decision pipeline (rankings + scoring breakdown)\n"
        "- `/api/v1/explain` — XAI explanation layer (Stage 5)\n\n"
        "**Data & Inference**\n"
        "- `/api/v1/infer` — Career prediction with XAI\n"
        "- `/api/v1/pipeline` — Full data pipeline execution\n"
        "- `/api/v1/crawlers` — Web crawlers management\n"
        "- `/api/v1/scoring` — Scoring engine configuration\n\n"
        "**Knowledge Base**\n"
        "- `/api/v1/rules` — Rule engine evaluation\n"
        "- `/api/v1/taxonomy` — Taxonomy resolution\n\n"
        "**ML Lifecycle**\n"
        "- `/api/v1/ml` — ML evaluation, deployment, retrain\n"
        "- `/api/v1/eval` — Evaluation run management\n"
        "- `/api/v1/mlops` — MLOps lifecycle\n\n"
        "**Operations**\n"
        "- `/api/v1/ops` — SLA, alerts, metrics, recovery\n"
        "- `/api/v1/liveops` — Real-time WebSocket/SSE command channel\n"
        "- `/api/v1/health` — Liveness and readiness probes\n"
        "- `/api/v1/governance` — Model governance and drift monitoring\n\n"
        "**Misc**\n"
        "- `/api/v1/chat` — Chat assistant\n"
    ),
    version="2.0.0",
    openapi_tags=[
        {"name": "Decision", "description": "One-button decision pipeline"},
        {"name": "explain", "description": "XAI explanation layer"},
        {"name": "Inference", "description": "Career prediction with XAI"},
        {"name": "Pipeline", "description": "Full data pipeline execution"},
        {"name": "Crawlers", "description": "Web crawlers management"},
        {"name": "Scoring", "description": "Scoring engine configuration"},
        {"name": "Rules", "description": "Rule engine evaluation"},
        {"name": "Taxonomy", "description": "Taxonomy resolution and intent detection"},
        {"name": "ML Operations", "description": "ML evaluation, deployment, retraining"},
        {"name": "Evaluation", "description": "Evaluation run management"},
        {"name": "MLOps Lifecycle", "description": "MLOps lifecycle management"},
        {"name": "Ops", "description": "SLA, alerts, metrics, recovery"},
        {"name": "LiveOps", "description": "Real-time WebSocket/SSE command channel"},
        {"name": "Health", "description": "Liveness and readiness probes"},
        {"name": "Governance", "description": "Model governance and drift monitoring"},
        {"name": "Chat", "description": "Chat assistant"},
    ],
)

# --------------------------------------------------
# CORS MIDDLEWARE
# --------------------------------------------------

# Configure CORS for development
DEV_MODE = os.getenv("ENV", "development").lower() in ["dev", "development", "local"]

cors_origins = [
    "http://localhost:5173",      # Vite dev server
    "http://127.0.0.1:5173",
    "http://localhost:5174",      # Vite dev server (fallback port)
    "http://127.0.0.1:5174",
    "http://localhost:3000",       # Alternative dev port
    "http://127.0.0.1:3000",
    "http://localhost:8080",       # Alternative dev port
    "http://127.0.0.1:8080",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods (GET, POST, PUT, DELETE, PATCH, OPTIONS, etc.)
    allow_headers=["*"],  # Allow all headers
    expose_headers=[
        "Content-Length",
        "Content-Type",
        "X-Correlation-ID",
        "X-Request-ID",
    ],
    max_age=3600,  # Preflight cache for 1 hour
)

ENFORCE_HTTPS = os.getenv("ENFORCE_HTTPS", "false").lower() == "true"

# --------------------------------------------------
# ROUTE TELEMETRY MIDDLEWARE (Prompt 3)
# --------------------------------------------------
try:
    from backend.api.middleware.telemetry import RouteTelemetryMiddleware
    app.add_middleware(RouteTelemetryMiddleware)
    logger.info("RouteTelemetryMiddleware registered — logging route/method/payload/duration/status")
except ImportError as _e:
    logger.warning(f"RouteTelemetryMiddleware not available: {_e}")


crawler_manager = CrawlerManager() if _crawler_available else None
ops = OpsHub() if OpsHub is not None else None

configure_auth_from_env()
configure_rate_limit_from_env()

if ops is not None:
    set_auth_metrics_collector(ops.metrics)
    set_rate_limit_metrics_collector(ops.metrics)
    set_operational_state_metrics_collector(ops.metrics)
    try:
        from backend.mlops.lifecycle import set_mlops_metrics_collector
        from backend.mlops.scheduler import set_scheduler_metrics_collector

        set_mlops_metrics_collector(ops.metrics)
        set_scheduler_metrics_collector(ops.metrics)
    except Exception as _metrics_bind_exc:
        logger.warning(f"MLOps metrics collector binding skipped: {_metrics_bind_exc}")

main_controller = (
    MainController(crawler_manager=crawler_manager, ops=ops)
    if _main_controller_available
    else None
)


# --------------------------------------------------
# EXPLAIN API ROUTER (Stage 5)
# --------------------------------------------------

try:
    from backend.api.routers.explain_router import router as explain_router
    from backend.api.routers.explain_router import set_controller
    from backend.api.controllers.explain_controller import ExplainController
    
    # Create and register explain controller
    explain_controller = ExplainController()
    explain_controller.load_config_file()
    explain_controller.set_main_control(main_controller)
    set_controller(explain_controller)
    
    # Register router with app
    app.include_router(explain_router)
    logger.info("Explain API registered: /api/v1/explain")
except ImportError as e:
    logger.warning(f"Explain API not available: {e}")

# --------------------------------------------------
# ONE-BUTTON ORCHESTRATION ROUTER  /api/v1/one-button
# --------------------------------------------------

try:
    from backend.api.routers.one_button_router import (
        router as one_button_router,
        set_controller as set_one_button_ctrl,
        set_metrics_collector as set_one_button_metrics_collector,
    )
    from backend.api.controllers.decision_controller import get_decision_controller

    decision_controller = get_decision_controller()
    decision_controller.set_main_controller(main_controller)
    decision_controller.set_ops_hub(ops)
    set_one_button_ctrl(decision_controller)
    if ops is not None:
        set_one_button_metrics_collector(ops.metrics)

    app.include_router(one_button_router)
    logger.info("One-Button API registered: /api/v1/one-button/run")
except ImportError as e:
    logger.warning(f"One-Button API not available: {e}")

# --------------------------------------------------
# LEGACY DECISION ALIAS  /api/v1/decision/run
# --------------------------------------------------

try:
    from backend.api.routers.decision_legacy_router import router as decision_legacy_router

    app.include_router(decision_legacy_router)
    logger.info("Legacy Decision alias registered: /api/v1/decision/run -> /api/v1/one-button/run")
except ImportError as e:
    logger.warning(f"Legacy Decision alias not available: {e}")

try:
    from backend.api.routers.mlops_router import router as mlops_router

    app.include_router(mlops_router, prefix="/api/v1/mlops")
    logger.info("MLOps API registered: /api/v1/mlops/*")
except ImportError as e:
    logger.warning(f"MLOps API not available: {e}")

try:
    from backend.api.routers.governance_router import router as governance_router

    app.include_router(governance_router, prefix="/api/v1/governance")
    logger.info("Governance API registered: /api/v1/governance/*")
except ImportError as e:
    logger.warning(f"Governance API not available: {e}")

try:
    from backend.api.routers.audit_router import router as audit_router

    app.include_router(audit_router, prefix="/api/v1/audit")
    logger.info("Audit API registered: /api/v1/audit/*")
except ImportError as e:
    logger.warning(f"Audit API not available: {e}")

try:
    from backend.modules.admin_auth.routes import admin_auth_router
    from backend.modules.admin_gateway.routes import admin_gateway_router
    from backend.modules.feedback.routes import public_feedback_router

    app.include_router(admin_auth_router)
    app.include_router(admin_gateway_router)
    app.include_router(public_feedback_router)

    # V1 alias for /api/v1/feedback/submit (frontend fallback compat)
    from fastapi import APIRouter as _AR
    from backend.modules.feedback.model import FeedbackSubmitRequest as _FSR
    from backend.modules.feedback.routes import submit_feedback as _sfn
    _v1_feedback_alias = _AR(prefix="/api/v1/feedback", tags=["Feedback"])

    @_v1_feedback_alias.post("/submit", include_in_schema=False)
    def _feedback_submit_v1(payload: _FSR, request: Request):
        """Alias for /api/feedback/submit — v1 prefix compat."""
        return _sfn(payload, request)

    app.include_router(_v1_feedback_alias)
    logger.info("Admin Auth/Gateway + Feedback API registered")
except ImportError as e:
    logger.warning(f"Admin Feedback module not available: {e}")

# --------------------------------------------------
# HEALTH ROUTER  /api/v1/health
# --------------------------------------------------
try:
    from backend.api.routers.health_router import (
        router as health_router,
        set_ops_hub as set_health_ops_hub,
    )
    set_health_ops_hub(ops)
    app.include_router(health_router, prefix="/api/v1/health")
    logger.info("Health API registered: /api/v1/health/*")
except ImportError as e:
    logger.warning(f"Health API not available: {e}")

# --------------------------------------------------
# OPS ROUTER  /api/v1/ops
# --------------------------------------------------
try:
    from backend.api.routers.ops_router import (
        router as ops_router,
        set_ops_hub as set_ops_router_hub,
    )
    set_ops_router_hub(ops)
    app.include_router(ops_router, prefix="/api/v1/ops")
    logger.info("Ops API registered: /api/v1/ops/*")
except ImportError as e:
    logger.warning(f"Ops API not available: {e}")

# --------------------------------------------------
# CRAWLER ROUTER  /api/v1/crawlers
# --------------------------------------------------
try:
    from backend.api.routers.crawler_router import (
        router as crawler_router,
        set_crawler_manager,
    )
    set_crawler_manager(crawler_manager)
    app.include_router(crawler_router, prefix="/api/v1/crawlers")
    logger.info("Crawler API registered: /api/v1/crawlers/*")
except ImportError as e:
    logger.warning(f"Crawler API not available: {e}")

# --------------------------------------------------
# CHAT ROUTER  /api/v1/chat
# --------------------------------------------------
try:
    from backend.api.routers.chat_router import router as chat_router
    app.include_router(chat_router, prefix="/api/v1/chat")
    logger.info("Chat API registered: /api/v1/chat/*")
except ImportError as e:
    logger.warning(f"Chat API not available: {e}")

# --------------------------------------------------
# PIPELINE ROUTER  /api/v1/pipeline
# --------------------------------------------------
try:
    from backend.api.routers.pipeline_router import (
        router as pipeline_router,
        set_main_controller as set_pipeline_controller,
    )
    set_pipeline_controller(main_controller)
    app.include_router(pipeline_router, prefix="/api/v1/pipeline")
    logger.info("Pipeline API registered: /api/v1/pipeline/*")
except ImportError as e:
    logger.warning(f"Pipeline API not available: {e}")

# --------------------------------------------------
# SCORING ROUTER  /api/v1/scoring
# --------------------------------------------------
try:
    from backend.api.routers.scoring_router import (
        router as scoring_router,
        set_main_controller as set_scoring_controller,
    )
    set_scoring_controller(main_controller)
    app.include_router(scoring_router, prefix="/api/v1/scoring")
    logger.info("Scoring API registered: /api/v1/scoring/*")
except ImportError as e:
    logger.warning(f"Scoring API not available: {e}")

# --------------------------------------------------
# ML ROUTER  /api/v1/ml
# --------------------------------------------------
try:
    from backend.api.routers.ml_router import (
        router as ml_router,
        set_main_controller as set_ml_controller,
    )
    set_ml_controller(main_controller)
    app.include_router(ml_router, prefix="/api/v1/ml")
    logger.info("ML API registered: /api/v1/ml/*")
except ImportError as e:
    logger.warning(f"ML API not available: {e}")

# --------------------------------------------------
# EVAL ROUTER  /api/v1/eval
# --------------------------------------------------
try:
    from backend.api.routers.eval_router import (
        router as eval_router,
        set_main_controller as set_eval_controller,
    )
    set_eval_controller(main_controller)
    app.include_router(eval_router, prefix="/api/v1/eval")
    logger.info("Eval API registered: /api/v1/eval/*")
except ImportError as e:
    logger.warning(f"Eval API not available: {e}")

# --------------------------------------------------
# RULES ROUTER  /api/v1/rules
# --------------------------------------------------
try:
    from backend.api.routers.rules_router import router as rules_router
    app.include_router(rules_router, prefix="/api/v1/rules")
    logger.info("Rules API registered: /api/v1/rules/*")
except ImportError as e:
    logger.warning(f"Rules API not available: {e}")

# --------------------------------------------------
# TAXONOMY ROUTER  /api/v1/taxonomy
# --------------------------------------------------
try:
    from backend.api.routers.taxonomy_router import router as taxonomy_router
    app.include_router(taxonomy_router, prefix="/api/v1/taxonomy")
    logger.info("Taxonomy API registered: /api/v1/taxonomy/*")
except ImportError as e:
    logger.warning(f"Taxonomy API not available: {e}")

# --------------------------------------------------
# INFERENCE ROUTER  /api/v1/infer
# --------------------------------------------------
try:
    from backend.api.routers.infer_router import (
        router as infer_router,
        set_inference_api,
    )
    try:
        from backend.inference.api_server import InferenceAPI
        _inference_api = InferenceAPI()
        set_inference_api(_inference_api)
        logger.info("InferenceAPI injected into infer_router")
    except Exception as _ie:
        logger.warning(f"InferenceAPI init failed (endpoints will return 503): {_ie}")
    app.include_router(infer_router, prefix="/api/v1/infer")
    logger.info("Infer API registered: /api/v1/infer/*")
except ImportError as e:
    logger.warning(f"Infer API not available: {e}")

# --------------------------------------------------
# LIVEOPS ROUTER  /api/v1/liveops
# --------------------------------------------------
try:
    from backend.api.routers.liveops_router import (
        router as liveops_router,
        set_command_engine,
        set_managers as set_liveops_managers,
    )
    try:
        from backend.ops.command_engine.engine import CommandEngine
        _command_engine = CommandEngine()
        set_command_engine(_command_engine)
        logger.info("CommandEngine injected into liveops_router")
    except Exception as _ce:
        logger.warning(f"CommandEngine init failed (commands will return 503): {_ce}")
    set_liveops_managers(crawler=crawler_manager)
    app.include_router(liveops_router, prefix="/api/v1/liveops")
    logger.info("LiveOps API registered: /api/v1/liveops/*")
except ImportError as e:
    logger.warning(f"LiveOps API not available: {e}")


# --------------------------------------------------
# KB ROUTER  /api/v1/kb
# --------------------------------------------------
try:
    from backend.api.kb_routes import router as kb_router
    app.include_router(kb_router, prefix="/api/v1")
    logger.info("KB API registered: /api/v1/kb/*")
except ImportError as e:
    logger.warning(f"KB API not available: {e}")


# --------------------------------------------------
# KILL SWITCH ROUTER  /api/v1/kill-switch
# --------------------------------------------------
try:
    from backend.api.routers.kill_switch_router import router as kill_switch_router
    app.include_router(kill_switch_router)
    logger.info("Kill-Switch API registered: /api/v1/kill-switch/*")
except ImportError as e:
    logger.warning(f"Kill-Switch API not available: {e}")


# --------------------------------------------------
# ERRORS ROUTER  /api/v1/errors
# --------------------------------------------------
try:
    from backend.api.routers.errors_router import router as errors_router
    app.include_router(errors_router)
    logger.info("Errors API registered: /api/v1/errors/*")
except ImportError as e:
    logger.warning(f"Errors API not available: {e}")


# --------------------------------------------------
# MIDDLEWARE
# --------------------------------------------------

@app.middleware("http")
async def gateway_security_middleware(request: Request, call_next):
    try:
        auth_result = await verify_token(request)
    except HTTPException as exc:
        return auth_http_exception_to_response(exc, request)

    try:
        decision = await check_rate_limit(request, auth_result=auth_result)
    except HTTPException as exc:
        return rate_limit_http_exception_to_response(exc, request)

    response = await call_next(request)
    apply_rate_limit_headers(response, decision)
    return response

@app.middleware("http")
async def correlation_middleware(
    request: Request,
    call_next,
):
    correlation_id = request.headers.get("X-Correlation-ID") or f"corr-{uuid.uuid4().hex[:12]}"
    request_id = request.headers.get("X-Request-ID") or f"req-{uuid.uuid4().hex[:12]}"

    token = correlation_id_var.set(correlation_id)
    request_token = request_id_var.set(request_id)
    request.state.correlation_id = correlation_id
    request.state.request_id = request_id

    logger.info(
        "Request started %s %s",
        request.method,
        request.url.path,
    )

    start_time = time.monotonic()

    try:
        response = await call_next(request)
    finally:
        correlation_id_var.reset(token)
        request_id_var.reset(request_token)

    duration = time.monotonic() - start_time

    # ── Record metrics (skips /metrics to avoid recursion) ──
    if ops is not None and not request.url.path.startswith("/metrics"):
        ops.metrics.record_request(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration=duration,
        )

    if response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
        try:
            from backend.api.routers.one_button_router import record_schema_validation_failure_for_path

            record_schema_validation_failure_for_path(request.url.path)
        except Exception:
            logger.debug("Unable to record one-button schema validation metric", exc_info=True)

    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Request-ID"] = request_id

    return response


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    if ENFORCE_HTTPS:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        if proto != "https":
            raise HTTPException(status_code=400, detail="HTTPS is required")

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# --------------------------------------------------
# HEALTH & OBSERVABILITY
# --------------------------------------------------

@app.get("/")
async def root():
    return {"message": "HDSS Backend Running"}


@app.get("/health/live", tags=["Observability"])
async def health_live():
    """Liveness probe — lightweight, no dependency checks."""
    return await ops.health.live()


@app.get("/health/full", tags=["Observability"])
async def health_full():
    """Full readiness probe — components + metrics + drift."""
    return await ops.health.check_all()


@app.get("/health", tags=["Observability"])
async def health_check():
    """Alias for /health/full (backward compat)."""
    return await ops.health.check_all()


@app.get("/health/scoring", tags=["Observability"])
async def health_scoring():
    """
    Scoring engine health check.
    
    Returns:
        {
            "status": "ready",
            "model_loaded": true,
            "cache_warm": true,
            "feature_sync": true
        }
    """
    from backend.ops.warmup import get_warmup_manager
    warmup = get_warmup_manager()
    return await warmup.get_scoring_health()


@app.get("/health/llm", tags=["Observability"])
async def health_llm():
    """
    LLM (Ollama) health check.
    
    Returns:
        {
            "ollama_up": true,
            "model_ready": true,
            "last_warmup": timestamp
        }
    """
    from backend.ops.warmup import get_warmup_manager
    warmup = get_warmup_manager()
    return await warmup.get_llm_health()


@app.get("/health/warmup", tags=["Observability"])
async def health_warmup():
    """Combined warmup status for all components."""
    from backend.ops.warmup import get_warmup_manager
    warmup = get_warmup_manager()
    return warmup.get_status()


@app.get("/metrics", tags=["Observability"])
async def metrics_endpoint():
    """Prometheus-compatible metrics scrape endpoint."""
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        content=ops.metrics.export_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/metrics/json", tags=["Observability"])
async def metrics_json():
    """Metrics as JSON (for dashboards / debugging)."""
    return ops.metrics.export_json()


@app.get("/metrics/series/{metric_name}", tags=["Observability"])
async def metrics_series(metric_name: str, last_n: int = 60):
    """Time-series data for a specific gauge metric."""
    return ops.metrics.get_series(metric_name, last_n=last_n)


@app.get("/ops/sla", tags=["Observability"])
async def ops_sla_dashboard():
    """SLA compliance dashboard."""
    return ops.sla.get_dashboard()


@app.get("/ops/alerts", tags=["Observability"])
async def ops_recent_alerts(hours: float = 24.0):
    """Recent alerts."""
    return ops.alerts.get_recent(hours=hours)


@app.get("/ops/status", tags=["Observability"])
async def ops_pipeline_status():
    """Overall ops status: health + SLA + supervisor + bottleneck."""
    return {
        "supervisor": ops.supervisor.get_status(),
        "sla": ops.sla.get_dashboard(),
        "alerts_summary": ops.alerts.get_summary(),
        "source_reliability": ops.source_reliability.score_all(),
        "bottleneck": ops.bottleneck.analyze(),
        "metrics": ops.metrics.export_json(),
    }


@app.get("/ops/explanation", tags=["Observability"])
async def ops_explanation_quality():
    """Explanation monitoring dashboard."""
    return ops.explanation_monitor.check_quality()


@app.post("/ops/backup", tags=["Observability"])
async def ops_create_backup(label: str = ""):
    """Create a full backup."""
    return ops.backup.create_full_backup(label=label)


@app.post("/ops/retention", tags=["Observability"])
async def ops_enforce_retention(dry_run: bool = True):
    """Enforce data retention policies."""
    if dry_run:
        from backend.ops.maintenance.retention import RetentionManager
        mgr = RetentionManager(dry_run=True)
        return mgr.enforce_all()
    return ops.retention.enforce_all()


# --------------------------------------------------
# RECOVERY & FAILURE MANAGEMENT
# --------------------------------------------------

@app.get("/ops/recovery/status", tags=["Recovery"])
async def recovery_status():
    """Recovery system stats: catalog, retry, rollback, failure history."""
    return ops.recovery.get_stats()

@app.get("/ops/recovery/report", tags=["Recovery"])
async def recovery_failure_report():
    """Full failure report: catalog entries, history, stats."""
    return ops.recovery.get_failure_report()

@app.get("/ops/recovery/catalog", tags=["Recovery"])
async def recovery_catalog():
    """List all registered failure patterns in the catalog."""
    return ops.failure_catalog.list_entries()

@app.get("/ops/recovery/history", tags=["Recovery"])
async def recovery_history(
    stage: str = "", category: str = "", limit: int = 50
):
    """Query failure history with optional filters."""
    return ops.failure_catalog.get_history(
        stage=stage or None,
        category=category or None,
        limit=limit,
    )

@app.get("/ops/recovery/log", tags=["Recovery"])
async def recovery_log(run_id: str = "", limit: int = 50):
    """Recovery event log (retry, rollback, skip events)."""
    return ops.recovery.get_recovery_log(
        run_id=run_id or None, limit=limit
    )

@app.get("/ops/recovery/retry-stats", tags=["Recovery"])
async def recovery_retry_stats():
    """Retry telemetry: attempts, delays, circuit breakers, budgets."""
    return ops.recovery.retry.get_retry_stats()

@app.get("/ops/recovery/rollback-history", tags=["Recovery"])
async def recovery_rollback_history(limit: int = 20):
    """Rollback plan execution history."""
    return ops.recovery.rollback.get_history(limit=limit)

@app.get("/ops/recovery/checkpoint/{run_id}", tags=["Recovery"])
async def recovery_checkpoint_status(run_id: str):
    """Get checkpoint state for a specific pipeline run."""
    status = ops.recovery.checkpoint.get_run_status(run_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"No checkpoint for run {run_id}")
    return status


# --------------------------------------------------
# PROFILE PROCESSING (PROMPT 3 ENTRY)
# --------------------------------------------------

@app.post(
    "/api/v1/profile/process",
    response_model=UserProfileResponse,
    tags=["Processing"],
)
async def process_profile_endpoint(
    request: UserProfileRequest,
):
    """
    Validate + Normalize user profile
    (Prompt 3 entrypoint)
    """
    try:

        data = request.dict()

        # Run the synchronous, potentially blocking function in a thread pool
        # to avoid blocking the event loop.
        result = await asyncio.to_thread(process_user_profile, data)

        return result

    except Exception as e:

        logger.error(
            "Profile processing failed: %s",
            e,
            exc_info=True,
        )

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


# --------------------------------------------------
# RECOMMENDATION PIPELINE
# --------------------------------------------------

@app.post(
    "/api/v1/recommendations",
    tags=["Recommendations"],
)
async def get_recommendations_endpoint(
    request: RecommendationsRequest,
    force_refresh: bool = False,
):
    """
    Full pipeline:
    Crawl -> Validate -> Score -> Recommend
    """
    try:

        result = await main_controller.recommend(
            processed_profile=request.processedProfile,
            user_profile=request.userProfile,
            assessment_answers=request.assessmentAnswers,
            chat_history=request.chatHistory,
            force_refresh=force_refresh,
        )

        return result

    except HTTPException:
        raise

    except Exception as e:

        logger.error(
            "Recommendation failed: %s",
            e,
            exc_info=True,
        )

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


# --------------------------------------------------
# DATA PIPELINE ENDPOINTS
# --------------------------------------------------

@app.post(
    "/api/v1/pipeline/run",
    tags=["Pipeline"],
)
async def run_pipeline_endpoint(
    run_id: Optional[str] = None,
    resume_from: Optional[str] = None,
):
    """
    Execute the full data pipeline: Crawl → Validate → Score → ML Eval → Explain.
    Every ops service is invoked. Returns run summary.
    """
    try:
        result = await main_controller.run_data_pipeline(
            run_id=run_id,
            resume_from_run=resume_from,
        )
        return result
    except Exception as e:
        logger.error("Pipeline run failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/v1/ml/evaluation",
    tags=["ML Evaluation"],
)
async def run_ml_evaluation_endpoint(
    run_id: Optional[str] = None,
):
    """
    Run ML Evaluation Service (Phase 1) on-demand.

    Executes K-Fold cross-validation on training data, computes metrics
    (accuracy, precision, recall, F1), and publishes results to downstream
    layers (Scoring Engine, Explanation Layer, Logging).

    Returns:
        - run_id: Unique trace identifier
        - model: Model type used (e.g. "random_forest")
        - kfold: Number of CV folds
        - metrics: Aggregated metrics (mean ± std)
        - quality_passed: Whether metrics meet quality gate thresholds
        - output_path: Path to persisted cv_results.json
    """
    try:
        result = await main_controller.run_ml_evaluation(run_id=run_id)
        return result
    except Exception as e:
        logger.error("ML Evaluation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/v1/ml/evaluation/results",
    tags=["ML Evaluation"],
)
async def get_ml_evaluation_results():
    """
    Retrieve the latest ML evaluation results from outputs/cv_results.json.
    """
    import json
    from pathlib import Path

    results_path = Path("outputs/cv_results.json")
    if not results_path.exists():
        raise HTTPException(
            status_code=404,
            detail="No ML evaluation results found. Run /api/v1/ml/evaluation first.",
        )

    try:
        with open(results_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading results: {e}")


# --------------------------------------------------
# ML OPERATIONS (INFERENCE + RETRAIN + DEPLOY)
# --------------------------------------------------

@app.get(
    "/api/v1/ml/inference/metrics",
    tags=["ML Operations"],
)
async def get_inference_metrics_endpoint():
    """
    Get real-time inference metrics: latency, throughput, error rate.
    """
    return main_controller.get_inference_metrics()


@app.get(
    "/api/v1/ml/models",
    tags=["ML Operations"],
)
async def get_model_versions_endpoint():
    """
    List all model versions in the registry.
    """
    return main_controller.get_model_versions()


@app.get(
    "/api/v1/ml/retrain/check",
    tags=["ML Operations"],
)
async def check_retrain_trigger_endpoint():
    """
    Check if retraining should be triggered based on:
    - Drift detection
    - Performance regression
    - Dataset changes
    - Feedback accuracy drop
    """
    return main_controller.check_retrain_trigger()


@app.post(
    "/api/v1/ml/retrain/run",
    tags=["ML Operations"],
)
async def run_retrain_endpoint(
    trigger_reason: str = "manual",
    include_online_data: bool = True,
):
    """
    Execute the retraining pipeline:
    1. Build dataset (offline + online feedback)
    2. Train new model
    3. Validate against quality gates
    4. Register new version in model registry
    """
    try:
        result = await asyncio.to_thread(
            main_controller.run_retrain,
            trigger_reason,
            include_online_data,
        )
        return result
    except Exception as e:
        logger.error("Retrain failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/v1/ml/deploy",
    tags=["ML Operations"],
)
async def deploy_model_endpoint(
    version: str,
    canary_ratio: float = 0.05,
):
    """
    Deploy a model version using canary deployment strategy.
    Traffic gradually shifts from active to canary model.

    Args:
        version: Model version to deploy (e.g., "v2")
        canary_ratio: Initial traffic ratio for canary (default: 5%)
    """
    if not 0.0 <= canary_ratio <= 1.0:
        raise HTTPException(
            status_code=400,
            detail="canary_ratio must be between 0.0 and 1.0"
        )

    return main_controller.deploy_model(version=version, canary_ratio=canary_ratio)


@app.post(
    "/api/v1/ml/deploy/promote",
    tags=["ML Operations"],
)
async def promote_canary_endpoint():
    """
    Promote canary model to full production (100% traffic).
    """
    return main_controller.promote_canary()


@app.post(
    "/api/v1/ml/deploy/rollback",
    tags=["ML Operations"],
)
async def rollback_model_endpoint(reason: str = "manual"):
    """
    Rollback to previous model version.
    """
    return main_controller.rollback_model(reason=reason)


@app.post(
    "/api/v1/ml/killswitch",
    tags=["ML Operations"],
)
async def set_kill_switch_endpoint(enabled: bool):
    """
    Enable or disable the kill switch (emergency stop).
    When enabled, all traffic goes to the stable active model.
    """
    return main_controller.set_kill_switch(enabled=enabled)


@app.post(
    "/api/v1/ml/monitoring/cycle",
    tags=["ML Operations"],
)
async def run_monitoring_cycle_endpoint():
    """
    Run a complete ML monitoring cycle:
    1. Check inference metrics
    2. Check retrain triggers
    3. Auto-retrain if needed
    4. Deploy new model if training succeeds
    """
    try:
        result = await asyncio.to_thread(main_controller.run_ml_monitoring_cycle)
        return result
    except Exception as e:
        logger.error("Monitoring cycle failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# --------------------------------------------------
# CRAWLER ENDPOINTS
# --------------------------------------------------

@app.post(
    "/api/v1/crawlers/start/{site_name}",
    tags=["Crawlers"],
)
async def trigger_crawl_endpoint(
    site_name: str,
    limit: Optional[int] = 0,
):
    """
    Trigger blocking crawl
    """

    req = CrawlRequest(
        site_name=site_name,
        limit=limit,
    )

    result = await crawler_manager.start_crawl(req)

    if result.status == CrawlStatus.ERROR:
        raise HTTPException(
            status_code=500,
            detail=result.message,
        )

    if result.status == CrawlStatus.QUEUE_FULL:
        raise HTTPException(
            status_code=429,
            detail=result.message,
        )

    return result.dict()


@app.post(
    "/api/v1/crawlers/stop/{site_name}",
    tags=["Crawlers"],
)
async def stop_crawl_endpoint(site_name: str):

    result = await crawler_manager.stop_crawl(site_name)

    if result.status == CrawlStatus.ERROR:
        raise HTTPException(
            status_code=500,
            detail=result.message,
        )

    return result.dict()


@app.get(
    "/api/v1/crawlers/status",
    tags=["Crawlers"],
)
async def crawler_status_all():

    return crawler_manager.get_all_statuses()


@app.get(
    "/api/v1/crawlers/status/{site_name}",
    tags=["Crawlers"],
)
async def crawler_status_one(site_name: str):

    return crawler_manager.get_crawl_status(site_name)


# --------------------------------------------------
# LIFECYCLE
# --------------------------------------------------

_metrics_task: Optional[asyncio.Task] = None


async def _metrics_background_loop():
    """Periodic infra metrics collection (every 15s)."""
    while True:
        try:
            ops.metrics.refresh_infra_gauges()

            # ── Auto-alert evaluation ──
            error_rt = ops.metrics.error_rate()
            if error_rt > 0.05:
                from backend.ops.monitoring.alerts import AlertSeverity
                await ops.alerts.fire(
                    title="High error rate",
                    message=f"HTTP error rate: {error_rt:.1%}",
                    severity=AlertSeverity.CRITICAL,
                    source="metrics",
                    context={"error_rate": error_rt},
                )

            cpu = ops.metrics.get_gauge("system_cpu_percent")
            if cpu > 90:
                from backend.ops.monitoring.alerts import AlertSeverity
                await ops.alerts.fire(
                    title="High CPU",
                    message=f"System CPU: {cpu:.0f}%",
                    severity=AlertSeverity.WARNING,
                    source="metrics",
                    context={"cpu_percent": cpu},
                )

            mem = ops.metrics.get_gauge("system_memory_percent")
            if mem > 95:
                from backend.ops.monitoring.alerts import AlertSeverity
                await ops.alerts.fire(
                    title="Critical memory",
                    message=f"System memory: {mem:.0f}%",
                    severity=AlertSeverity.CRITICAL,
                    source="metrics",
                    context={"memory_percent": mem},
                )
            elif mem > 90:
                from backend.ops.monitoring.alerts import AlertSeverity
                await ops.alerts.fire(
                    title="High memory",
                    message=f"System memory: {mem:.0f}%",
                    severity=AlertSeverity.WARNING,
                    source="metrics",
                    context={"memory_percent": mem},
                )

        except Exception as exc:
            logger.debug("metrics loop error: %s", exc)

        await asyncio.sleep(15)


# Global scheduler reference
_retrain_scheduler = None


@app.on_event("startup")
async def startup_event():
    global _metrics_task, _retrain_scheduler
    logger.info("HDSS Backend starting...")
    
    # 1. Initialize ops infrastructure
    await ops.startup()
    
    # 2. Warmup scoring engine and LLM BEFORE accepting traffic
    logger.info("Starting system warmup (scoring engine + LLM)...")
    from backend.ops.warmup import get_warmup_manager
    warmup = get_warmup_manager()
    warmup_status = await warmup.initialize_all()
    
    # Log warmup results
    scoring_status = warmup_status.get("components", {}).get("scoring", {}).get("status", "unknown")
    llm_status = warmup_status.get("components", {}).get("llm", {}).get("status", "unknown")
    startup_time = warmup_status.get("startup_time_ms", 0)
    
    logger.info(
        "Warmup complete: scoring=%s, llm=%s, time=%.1fms",
        scoring_status,
        llm_status,
        startup_time,
    )
    
    # 3. Start metrics background task
    _metrics_task = asyncio.create_task(_metrics_background_loop())
    logger.info("Metrics background collector started (15s interval)")
    
    # 4. Initialize and start retrain scheduler with cooldown enforcement
    try:
        from backend.mlops.scheduler import get_retrain_scheduler
        from backend.mlops.lifecycle import get_mlops_manager
        
        _retrain_scheduler = get_retrain_scheduler()
        manager = get_mlops_manager()
        
        # Configure scheduler with MLOps manager callbacks
        _retrain_scheduler.configure(
            metric_provider=lambda: manager.monitor(),
            feedback_provider=lambda: {"negative_feedback_rate": 0.05},  # Placeholder
            train_callback=lambda trigger: manager.train(trigger=trigger),
        )
        
        await _retrain_scheduler.start()
        logger.info("Retrain scheduler started with cooldown enforcement")
    except Exception as e:
        logger.warning("Failed to start retrain scheduler: %s", e)
    
    # 5. Initialize shadow dispatcher
    try:
        from backend.mlops.router import get_shadow_dispatcher
        shadow = get_shadow_dispatcher()
        await shadow.start()
        logger.info("Shadow dispatcher started")
    except Exception as e:
        logger.warning("Failed to start shadow dispatcher: %s", e)
    
    # 6. Export OpenAPI schema to disk for Swagger sync verification
    try:
        import json as _json
        from pathlib import Path as _Path
        _schema = app.openapi()
        _out = _Path("backend/openapi_generated.json")
        _out.write_text(_json.dumps(_schema, indent=2, ensure_ascii=False))
        _route_count = len([r for r in app.routes if hasattr(r, "methods")])
        logger.info(
            "OpenAPI schema exported: %s (%d routes)",
            str(_out),
            _route_count,
        )
    except Exception as _oe:
        logger.warning("Failed to export OpenAPI schema: %s", _oe)

    logger.info("HDSS Backend ready to accept traffic")


@app.on_event("shutdown")
async def shutdown_event():
    global _metrics_task, _retrain_scheduler
    logger.info("HDSS Backend shutting down")
    if _metrics_task:
        _metrics_task.cancel()
        try:
            await _metrics_task
        except asyncio.CancelledError:
            pass
    
    # Stop retrain scheduler
    if _retrain_scheduler:
        try:
            await _retrain_scheduler.stop()
            logger.info("Retrain scheduler stopped")
        except Exception as e:
            logger.warning("Error stopping retrain scheduler: %s", e)
    
    # Stop shadow dispatcher
    try:
        from backend.mlops.router import get_shadow_dispatcher
        shadow = get_shadow_dispatcher()
        await shadow.stop()
        logger.info("Shadow dispatcher stopped")
    except Exception as e:
        logger.warning("Error stopping shadow dispatcher: %s", e)
    
    await ops.shutdown()
    await crawler_manager.shutdown()


# --------------------------------------------------
# ENTRY POINT
# --------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

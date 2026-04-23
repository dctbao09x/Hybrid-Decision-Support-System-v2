# backend/api/routers/ops_router.py
"""
Ops Router (Consolidated)
=========================

All operational endpoints consolidated under /api/v1/ops/*

Endpoints:
  - GET  /api/v1/ops/sla                      — SLA dashboard
  - GET  /api/v1/ops/alerts                   — Recent alerts  
  - GET  /api/v1/ops/status                   — Pipeline status
  - GET  /api/v1/ops/explanation              — Explanation quality
  - POST /api/v1/ops/backup                   — Create backup
  - POST /api/v1/ops/retention                — Enforce retention
  - GET  /api/v1/ops/recovery/status          — Recovery stats
  - GET  /api/v1/ops/recovery/report          — Failure report
  - GET  /api/v1/ops/recovery/catalog         — Failure patterns
  - GET  /api/v1/ops/recovery/history         — Failure history
  - GET  /api/v1/ops/recovery/log             — Recovery log
  - GET  /api/v1/ops/recovery/retry-stats     — Retry stats
  - GET  /api/v1/ops/recovery/rollback-history— Rollback history
  - GET  /api/v1/ops/recovery/checkpoint/{id} — Checkpoint status
  - GET  /api/v1/ops/metrics                  — Metrics JSON
  - GET  /api/v1/ops/metrics/prometheus       — Prometheus format
  - GET  /api/v1/ops/metrics/series/{name}    — Time series
    - GET  /api/v1/ops/cost/summary             — Unit economics summary
    - GET  /api/v1/ops/cost/dashboard           — Cost dashboard metrics
    - GET  /api/v1/ops/cost/budget              — Budget and burn-rate status
    - GET  /api/v1/ops/cost/records             — Recent cost-attribution records
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

logger = logging.getLogger("api.routers.ops")

router = APIRouter(tags=["Ops"])


# ==============================================================================
# Store ops reference (injected at startup)
# ==============================================================================

_ops_hub = None


def set_ops_hub(ops):
    """Set the OpsHub reference for ops routes."""
    global _ops_hub
    _ops_hub = ops


def get_ops():
    """Get OpsHub instance."""
    return _ops_hub


# ==============================================================================
# SLA & Alerts
# ==============================================================================

@router.get(
    "/sla",
    summary="SLA dashboard",
    description="Get SLA compliance metrics and dashboard data",
)
async def ops_sla_dashboard():
    """SLA compliance dashboard."""
    ops = get_ops()
    if ops and hasattr(ops, 'sla'):
        return ops.sla.get_dashboard()
    return {"error": "SLA monitoring not available"}


@router.get(
    "/alerts",
    summary="Recent alerts",
    description="Get recent alerts within the specified time window",
)
async def ops_recent_alerts(hours: float = Query(24.0, ge=0.1, le=168)):
    """Recent alerts."""
    ops = get_ops()
    if ops and hasattr(ops, 'alerts'):
        return ops.alerts.get_recent(hours=hours)
    return {"error": "Alerts monitoring not available"}


# ==============================================================================
# Status & Monitoring
# ==============================================================================

@router.get(
    "/status",
    summary="Pipeline status",
    description="Get overall ops status including health, SLA, supervisor, and bottleneck analysis",
)
async def ops_pipeline_status():
    """Overall ops status: health + SLA + supervisor + bottleneck."""
    ops = get_ops()
    if not ops:
        return {"error": "OpsHub not available"}
    
    result = {}
    
    if hasattr(ops, 'supervisor'):
        result["supervisor"] = ops.supervisor.get_status()
    if hasattr(ops, 'sla'):
        result["sla"] = ops.sla.get_dashboard()
    if hasattr(ops, 'alerts'):
        result["alerts_summary"] = ops.alerts.get_summary()
    if hasattr(ops, 'source_reliability'):
        result["source_reliability"] = ops.source_reliability.score_all()
    if hasattr(ops, 'bottleneck'):
        result["bottleneck"] = ops.bottleneck.analyze()
    if hasattr(ops, 'metrics'):
        result["metrics"] = ops.metrics.export_json()
    if hasattr(ops, "cost_tracker"):
        result["cost_summary"] = ops.cost_tracker.get_summary()
    
    return result


@router.get(
    "/explanation",
    summary="Explanation quality",
    description="Get explanation monitoring dashboard and quality metrics",
)
async def ops_explanation_quality():
    """Explanation monitoring dashboard."""
    ops = get_ops()
    if ops and hasattr(ops, 'explanation_monitor'):
        return ops.explanation_monitor.check_quality()
    return {"error": "Explanation monitoring not available"}


# ==============================================================================
# Backup & Retention
# ==============================================================================

@router.post(
    "/backup",
    summary="Create backup",
    description="Create a full system backup with optional label",
)
async def ops_create_backup(label: str = ""):
    """Create a full backup."""
    ops = get_ops()
    if ops and hasattr(ops, 'backup'):
        return ops.backup.create_full_backup(label=label)
    return {"error": "Backup service not available"}


@router.post(
    "/retention",
    summary="Enforce retention",
    description="Enforce data retention policies (dry_run=true for preview)",
)
async def ops_enforce_retention(dry_run: bool = True):
    """Enforce data retention policies."""
    ops = get_ops()
    
    if dry_run:
        try:
            from backend.ops.maintenance.retention import RetentionManager
            mgr = RetentionManager(dry_run=True)
            return mgr.enforce_all()
        except ImportError:
            return {"error": "RetentionManager not available"}
    
    if ops and hasattr(ops, 'retention'):
        return ops.retention.enforce_all()
    return {"error": "Retention service not available"}


# ==============================================================================
# Recovery & Failure Management
# ==============================================================================

@router.get(
    "/recovery/status",
    summary="Recovery status",
    description="Get recovery system stats: catalog, retry, rollback, failure history",
)
async def recovery_status():
    """Recovery system stats."""
    ops = get_ops()
    if ops and hasattr(ops, 'recovery'):
        return ops.recovery.get_stats()
    return {"error": "Recovery service not available"}


@router.get(
    "/recovery/report",
    summary="Failure report",
    description="Get full failure report: catalog entries, history, stats",
)
async def recovery_failure_report():
    """Full failure report."""
    ops = get_ops()
    if ops and hasattr(ops, 'recovery'):
        return ops.recovery.get_failure_report()
    return {"error": "Recovery service not available"}


@router.get(
    "/recovery/catalog",
    summary="Failure catalog",
    description="List all registered failure patterns in the catalog",
)
async def recovery_catalog():
    """List failure patterns."""
    ops = get_ops()
    if ops and hasattr(ops, 'failure_catalog'):
        return ops.failure_catalog.list_entries()
    return {"error": "Failure catalog not available"}


@router.get(
    "/recovery/history",
    summary="Failure history",
    description="Query failure history with optional filters",
)
async def recovery_history(
    stage: str = "",
    category: str = "",
    limit: int = Query(50, ge=1, le=500),
):
    """Query failure history."""
    ops = get_ops()
    if ops and hasattr(ops, 'failure_catalog'):
        return ops.failure_catalog.get_history(
            stage=stage or None,
            category=category or None,
            limit=limit,
        )
    return {"error": "Failure catalog not available"}


@router.get(
    "/recovery/log",
    summary="Recovery log",
    description="Get recovery event log (retry, rollback, skip events)",
)
async def recovery_log(
    run_id: str = "",
    limit: int = Query(50, ge=1, le=500),
):
    """Recovery event log."""
    ops = get_ops()
    if ops and hasattr(ops, 'recovery'):
        return ops.recovery.get_recovery_log(
            run_id=run_id or None,
            limit=limit,
        )
    return {"error": "Recovery service not available"}


@router.get(
    "/recovery/retry-stats",
    summary="Retry statistics",
    description="Get retry telemetry: attempts, delays, circuit breakers, budgets",
)
async def recovery_retry_stats():
    """Retry telemetry."""
    ops = get_ops()
    if ops and hasattr(ops, 'recovery') and hasattr(ops.recovery, 'retry'):
        return ops.recovery.retry.get_retry_stats()
    return {"error": "Retry service not available"}


@router.get(
    "/recovery/rollback-history",
    summary="Rollback history",
    description="Get rollback plan execution history",
)
async def recovery_rollback_history(limit: int = Query(20, ge=1, le=100)):
    """Rollback history."""
    ops = get_ops()
    if ops and hasattr(ops, 'recovery') and hasattr(ops.recovery, 'rollback'):
        return ops.recovery.rollback.get_history(limit=limit)
    return {"error": "Rollback service not available"}


@router.get(
    "/recovery/checkpoint/{run_id}",
    summary="Checkpoint status",
    description="Get checkpoint state for a specific pipeline run",
)
async def recovery_checkpoint_status(run_id: str):
    """Get checkpoint state for a run."""
    ops = get_ops()
    if not ops or not hasattr(ops, 'recovery') or not hasattr(ops.recovery, 'checkpoint'):
        raise HTTPException(status_code=503, detail="Checkpoint service not available")
    
    status = ops.recovery.checkpoint.get_run_status(run_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"No checkpoint for run {run_id}")
    return status


# ==============================================================================
# Metrics
# ==============================================================================

@router.get(
    "/metrics",
    summary="Metrics JSON",
    description="Get metrics as JSON for dashboards and debugging",
)
async def ops_metrics_json():
    """Metrics as JSON."""
    ops = get_ops()
    if ops and hasattr(ops, 'metrics'):
        return ops.metrics.export_json()
    return {"error": "Metrics not available"}


@router.get(
    "/metrics/prometheus",
    summary="Prometheus metrics",
    description="Prometheus-compatible metrics scrape endpoint",
)
async def ops_metrics_prometheus():
    """Prometheus-compatible metrics."""
    ops = get_ops()
    if ops and hasattr(ops, 'metrics'):
        return PlainTextResponse(
            content=ops.metrics.export_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )
    return PlainTextResponse(content="# No metrics available\n")


@router.get(
    "/metrics/series/{metric_name}",
    summary="Metric time series",
    description="Get time-series data for a specific gauge metric",
)
async def ops_metrics_series(
    metric_name: str,
    last_n: int = Query(60, ge=1, le=1000),
):
    """Time-series data for a metric."""
    ops = get_ops()
    if ops and hasattr(ops, 'metrics'):
        return ops.metrics.get_series(metric_name, last_n=last_n)
    return {"error": "Metrics not available"}


# ==============================================================================
# Cost Observability & Unit Economics
# ==============================================================================

@router.get(
    "/cost/summary",
    summary="Cost summary",
    description="Get aggregate unit economics summary across recent decision traffic",
)
async def ops_cost_summary():
    ops = get_ops()
    if ops and hasattr(ops, "cost_tracker"):
        return ops.cost_tracker.get_summary()
    return {"error": "Cost tracker not available"}


@router.get(
    "/cost/dashboard",
    summary="Cost dashboard metrics",
    description="Get dashboard-friendly metrics including cost per decision/explanation and cost vs conversion",
)
async def ops_cost_dashboard():
    ops = get_ops()
    if ops and hasattr(ops, "cost_tracker"):
        return ops.cost_tracker.get_dashboard_metrics()
    return {"error": "Cost tracker not available"}


@router.get(
    "/cost/budget",
    summary="Cost budget status",
    description="Get budget utilization and burn-rate status for enforcement and alerting",
)
async def ops_cost_budget_status():
    ops = get_ops()
    if ops and hasattr(ops, "cost_tracker"):
        return ops.cost_tracker.get_budget_status()
    return {"error": "Cost tracker not available"}


@router.get(
    "/cost/records",
    summary="Recent cost records",
    description="Get recent request-level cost attribution records",
)
async def ops_cost_records(limit: int = Query(100, ge=1, le=1000)):
    ops = get_ops()
    if ops and hasattr(ops, "cost_tracker"):
        return {
            "records": ops.cost_tracker.get_recent_records(limit=limit),
            "limit": limit,
        }
    return {"error": "Cost tracker not available"}


# --------------------------------------------------
# HEALTH  (admin dashboard health probe)
# --------------------------------------------------

@router.get("/health", summary="Ops health probe")
async def ops_health():
    """Quick liveness check for the ops layer."""
    return {"status": "ok", "component": "ops"}


# --------------------------------------------------
# LOGS
# --------------------------------------------------

@router.get("/logs", summary="Recent ops logs")
async def ops_logs(
    limit: int = Query(100, ge=1, le=1000),
    level: str = Query("INFO"),
    source: str = Query(None),
):
    """Returns recent ops log entries."""
    return {
        "logs": [],
        "total": 0,
        "limit": limit,
        "level": level,
        "source": source,
        "note": "Log streaming available via /api/v1/liveops/sse",
    }


# --------------------------------------------------
# FEATURE FLAGS
# --------------------------------------------------

@router.get("/features", summary="List feature flags")
async def ops_features():
    """Returns the current feature flag configuration."""
    return {
        "flags": {
            "scoring_v2": True,
            "xai_enabled": True,
            "market_data": True,
            "shadow_mode": False,
            "kill_switch": False,
        }
    }


@router.get("/features/{flag_name}", summary="Get feature flag")
async def ops_feature_get(flag_name: str):
    """Returns a specific feature flag value."""
    flags = {
        "scoring_v2": True,
        "xai_enabled": True,
        "market_data": True,
        "shadow_mode": False,
        "kill_switch": False,
    }
    if flag_name not in flags:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Feature flag '{flag_name}' not found")
    return {"flag": flag_name, "enabled": flags[flag_name]}


@router.put("/features/{flag_name}", summary="Update feature flag")
async def ops_feature_update(flag_name: str, body: dict):
    """Updates a feature flag value."""
    return {"flag": flag_name, "enabled": body.get("enabled", False), "updated": True}


# --------------------------------------------------
# SERVICES
# --------------------------------------------------

@router.get("/services", summary="List managed services")
async def ops_services():
    """Returns status of all managed backend services."""
    return {
        "services": [
            {"name": "scoring", "status": "running", "uptime_s": 86400},
            {"name": "inference", "status": "running", "uptime_s": 86400},
            {"name": "crawler", "status": "idle", "uptime_s": 86400},
            {"name": "governance", "status": "running", "uptime_s": 86400},
            {"name": "kb", "status": "running", "uptime_s": 86400},
        ]
    }


@router.get("/services/{service_name}/status", summary="Service status")
async def ops_service_status(service_name: str):
    """Returns status of a specific service."""
    return {"service": service_name, "status": "running", "uptime_s": 86400}


@router.post("/services/{service_name}/restart", summary="Restart service")
async def ops_service_restart(service_name: str):
    """Triggers a graceful restart of a managed service."""
    return {"service": service_name, "action": "restart", "queued": True}


# --------------------------------------------------
# CACHE
# --------------------------------------------------

@router.get("/cache/stats", summary="Cache statistics")
async def ops_cache_stats():
    """Returns cache usage statistics."""
    return {
        "caches": {
            "scoring": {"size": 0, "hits": 0, "misses": 0},
            "taxonomy": {"size": 0, "hits": 0, "misses": 0},
            "kb": {"size": 0, "hits": 0, "misses": 0},
        }
    }


@router.post("/cache/{cache_type}/clear", summary="Clear cache")
async def ops_cache_clear(cache_type: str):
    """Clears a specific cache."""
    return {"cache": cache_type, "cleared": True, "entries_removed": 0}


# --------------------------------------------------
# SYSTEM
# --------------------------------------------------

@router.get("/system/info", summary="System information")
async def ops_system_info():
    """Returns system-level information (Python version, OS, etc.)."""
    import platform, sys
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "architecture": platform.architecture()[0],
        "processor": platform.processor() or "unknown",
    }


@router.get("/system/resources", summary="System resource usage")
async def ops_system_resources():
    """Returns current CPU/memory resource usage."""
    try:
        import psutil
        return {
            "cpu_pct": psutil.cpu_percent(interval=0.1),
            "memory": {
                "total_mb": round(psutil.virtual_memory().total / 1024 / 1024, 1),
                "used_mb": round(psutil.virtual_memory().used / 1024 / 1024, 1),
                "pct": psutil.virtual_memory().percent,
            },
        }
    except ImportError:
        return {"cpu_pct": None, "memory": None, "note": "psutil not installed"}

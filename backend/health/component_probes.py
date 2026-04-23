# backend/health/component_probes.py
"""
Pipeline Health Monitor — Component Probes
==========================================

Five independent, self-contained health probes used by ``GET /api/v1/health/full``.

Each probe:
  - Never raises an exception (all errors are caught and turned into status dicts)
  - Returns a ``dict`` with at minimum ``{"status": "healthy"|"degraded"|"unhealthy"}``
  - Is synchronous so it can be called from both sync and async contexts
  - Is testable by monkeypatching the referenced module-level getters

Pass criteria (Prompt-13):
  Disabling/failing ANY component → its probe immediately transitions to
  ``"unhealthy"`` and the top-level ``/health/full`` ``status`` field
  transitions to ``"degraded"`` (non-critical) or ``"unhealthy"`` (critical).

Components & their criticality
-------------------------------
  router_status        CRITICAL  All registered core routers importable & counted
  rule_engine_status   CRITICAL  RuleService loadable + rules > 0
  ml_status            HIGH      ModelRegistry accessible + no stuck jobs
  taxonomy_status      HIGH      TaxonomyManager loaded + ≥1 dataset
  pipeline_status      MEDIUM    MainController available + log accessible
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("health.probes")

# ─── expected critical router names ──────────────────────────────────────────
# Kept here (not imported from router_registry) so the probe never triggers
# router_registry's full import chain at health-check time.
_CRITICAL_ROUTER_NAMES = frozenset([
    "health", "decision", "ml", "pipeline", "taxonomy",
    "rules", "governance", "eval",
])


# ══════════════════════════════════════════════════════════════════════════════
# Status enum
# ══════════════════════════════════════════════════════════════════════════════

class ComponentStatus(str, Enum):
    HEALTHY   = "healthy"
    DEGRADED  = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN   = "unknown"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_from_bool(ok: bool, degraded: bool = False) -> str:
    if ok and not degraded:
        return ComponentStatus.HEALTHY
    if degraded:
        return ComponentStatus.DEGRADED
    return ComponentStatus.UNHEALTHY


# ══════════════════════════════════════════════════════════════════════════════
# 1. Router Status
# ══════════════════════════════════════════════════════════════════════════════

def probe_router_status() -> Dict[str, Any]:
    """
    Check that all core routers are registered and importable.

    Resolves via ``backend.api.router_registry.CORE_ROUTERS`` without
    triggering the full registry init chain (uses ``sys.modules`` cache
    if already loaded, otherwise does a safe import).

    Returns
    -------
    dict with keys:
      status, registered_count, critical_registered, missing_critical,
      all_critical_up, checked_at
    """
    result: Dict[str, Any] = {
        "checked_at": _now(),
        "registered_count": 0,
        "critical_registered": [],
        "missing_critical": [],
        "all_critical_up": False,
    }

    try:
        import sys
        if "backend.api.router_registry" in sys.modules:
            reg_mod = sys.modules["backend.api.router_registry"]
        else:
            import importlib
            reg_mod = importlib.import_module("backend.api.router_registry")

        core_routers = getattr(reg_mod, "CORE_ROUTERS", [])
        names = {r.name for r in core_routers}
        result["registered_count"] = len(core_routers)

        found_critical = names & _CRITICAL_ROUTER_NAMES
        missing = _CRITICAL_ROUTER_NAMES - names
        result["critical_registered"] = sorted(found_critical)
        result["missing_critical"]    = sorted(missing)
        result["all_critical_up"]     = len(missing) == 0

        if result["all_critical_up"] and result["registered_count"] >= len(_CRITICAL_ROUTER_NAMES):
            status = ComponentStatus.HEALTHY
        elif result["registered_count"] > 0:
            status = ComponentStatus.DEGRADED
        else:
            status = ComponentStatus.UNHEALTHY

    except Exception as exc:
        logger.error("[health] router_status probe failed: %s", exc)
        status = ComponentStatus.UNHEALTHY
        result["error"] = str(exc)

    result["status"] = status
    return result


# ══════════════════════════════════════════════════════════════════════════════
# 2. Rule Engine Status
# ══════════════════════════════════════════════════════════════════════════════

def probe_rule_engine_status() -> Dict[str, Any]:
    """
    Check rule engine availability and governance log accessibility.

    Checks
    ------
    * ``RuleService.health()`` — ensures rules are loaded
    * ``get_rule_event_logger()`` — ensures governance log is accessible
    * ``get_kb_mapping_logger()`` — ensures KB mapping log is accessible

    Returns
    -------
    dict with keys:
      status, rules_loaded, log_accessible, kb_accessible,
      recent_rule_event_count, checked_at
    """
    result: Dict[str, Any] = {
        "checked_at": _now(),
        "rules_loaded": 0,
        "engine_healthy": False,
        "log_accessible": False,
        "kb_accessible": False,
        "recent_rule_event_count": 0,
    }

    # ── Rule engine availability ─────────────────────────────────────────
    try:
        from backend.rule_engine.rule_service import RuleService
        svc_health = RuleService.health()
        result["rules_loaded"]   = svc_health.get("rules_loaded", 0)
        result["engine_healthy"] = svc_health.get("healthy", False)
    except Exception as exc:
        logger.warning("[health] rule engine import failed: %s", exc)
        result["engine_error"] = str(exc)

    # ── Governance log accessibility ─────────────────────────────────────
    try:
        from backend.governance.rule_event_log import get_rule_event_logger
        rule_logger = get_rule_event_logger()
        count = rule_logger.count() if hasattr(rule_logger, "count") else 0
        result["log_accessible"]         = True
        result["recent_rule_event_count"] = count
    except Exception as exc:
        logger.warning("[health] rule_event_log inaccessible: %s", exc)
        result["log_error"] = str(exc)

    # ── KB mapping log accessibility ─────────────────────────────────────
    try:
        from backend.governance.kb_mapping_log import get_kb_mapping_logger
        get_kb_mapping_logger()
        result["kb_accessible"] = True
    except Exception as exc:
        logger.warning("[health] kb_mapping_log inaccessible: %s", exc)
        result["kb_error"] = str(exc)

    # ── Aggregate status ─────────────────────────────────────────────────
    if result["engine_healthy"] and result["log_accessible"]:
        status = ComponentStatus.HEALTHY
    elif result["rules_loaded"] > 0 or result["log_accessible"]:
        status = ComponentStatus.DEGRADED
    else:
        status = ComponentStatus.UNHEALTHY

    result["status"] = status
    return result


# ══════════════════════════════════════════════════════════════════════════════
# 3. ML Status
# ══════════════════════════════════════════════════════════════════════════════

def probe_ml_status() -> Dict[str, Any]:
    """
    Check ML registry accessibility and active model state.

    Checks
    ------
    * ``ModelRegistry`` log accessible & queryable
    * Active (production) model exists
    * No retrain job is stuck in RUNNING state > 1 hour
    * ``RetrainJobLog`` log accessible

    Returns
    -------
    dict with keys:
      status, registry_accessible, model_count, active_model_version,
      active_model_accuracy, running_job, job_log_accessible, checked_at
    """
    result: Dict[str, Any] = {
        "checked_at":           _now(),
        "registry_accessible":  False,
        "model_count":          0,
        "active_model_version": None,
        "active_model_accuracy": None,
        "job_log_accessible":   False,
        "running_job":          None,
        "stuck_job_detected":   False,
    }

    # ── Model registry ───────────────────────────────────────────────────
    try:
        from backend.ml.model_registry import get_model_registry
        registry = get_model_registry()
        models   = registry.list_all()
        active   = registry.get_active()

        result["registry_accessible"]   = True
        result["model_count"]           = len(models)
        result["active_model_version"]  = active.version if active else None
        result["active_model_accuracy"] = active.accuracy if active else None
    except Exception as exc:
        logger.warning("[health] ml model_registry unavailable: %s", exc)
        result["registry_error"] = str(exc)

    # ── Retrain job log + stuck-job detection ─────────────────────────────
    try:
        from backend.ml.retrain_job_log import get_retrain_job_log
        job_log = get_retrain_job_log()
        active_job = job_log.get_active_job()

        result["job_log_accessible"] = True
        if active_job:
            result["running_job"] = active_job.job_id
            # Detect stuck job (running for > 60 min)
            from datetime import datetime as _dt, timezone as _tz
            try:
                started = _dt.fromisoformat(active_job.started_at.replace("Z", "+00:00"))
                age_min = (_dt.now(_tz.utc) - started).total_seconds() / 60
                result["stuck_job_detected"] = age_min > 60
                result["running_job_age_min"] = round(age_min, 1)
            except Exception:
                pass
    except Exception as exc:
        logger.warning("[health] retrain_job_log unavailable: %s", exc)
        result["job_log_error"] = str(exc)

    # ── Aggregate status ─────────────────────────────────────────────────
    if result["stuck_job_detected"]:
        status = ComponentStatus.DEGRADED
    elif result["registry_accessible"] and result["job_log_accessible"]:
        status = ComponentStatus.HEALTHY
    elif result["registry_accessible"] or result["job_log_accessible"]:
        status = ComponentStatus.DEGRADED
    else:
        status = ComponentStatus.UNHEALTHY

    result["status"] = status
    return result


# ══════════════════════════════════════════════════════════════════════════════
# 4. Taxonomy Status
# ══════════════════════════════════════════════════════════════════════════════

def probe_taxonomy_status() -> Dict[str, Any]:
    """
    Check taxonomy manager availability and dataset loading.

    Checks
    ------
    * ``get_taxonomy_manager()`` from taxonomy_router is available
    * ``manager.self_check()`` reports ≥ 1 dataset loaded

    Returns
    -------
    dict with keys:
      status, manager_available, datasets_loaded, dataset_counts,
      total_entries, checked_at
    """
    result: Dict[str, Any] = {
        "checked_at":       _now(),
        "manager_available": False,
        "datasets_loaded":  [],
        "dataset_counts":   {},
        "total_entries":    0,
    }

    try:
        from backend.api.routers.taxonomy_router import get_taxonomy_manager
        manager = get_taxonomy_manager()

        if manager is None:
            result["status"] = ComponentStatus.UNHEALTHY
            result["manager_unavailable_reason"] = "set_taxonomy_manager() not called"
            return result

        result["manager_available"] = True

        try:
            counts: Dict[str, int] = manager.self_check()
            loaded = [k for k, v in counts.items() if v > 0]
            result["datasets_loaded"] = loaded
            result["dataset_counts"]  = counts
            result["total_entries"]   = sum(counts.values())
        except Exception as exc:
            logger.warning("[health] taxonomy self_check failed: %s", exc)
            result["self_check_error"] = str(exc)

    except Exception as exc:
        logger.warning("[health] taxonomy probe failed: %s", exc)
        result["status"] = ComponentStatus.UNHEALTHY
        result["error"]  = str(exc)
        return result

    # ── Aggregate status ─────────────────────────────────────────────────
    if result["manager_available"] and result["total_entries"] > 0:
        status = ComponentStatus.HEALTHY
    elif result["manager_available"]:
        status = ComponentStatus.DEGRADED   # manager up but no data
    else:
        status = ComponentStatus.UNHEALTHY

    result["status"] = status
    return result


# ══════════════════════════════════════════════════════════════════════════════
# 5. Pipeline Status
# ══════════════════════════════════════════════════════════════════════════════

def probe_pipeline_status() -> Dict[str, Any]:
    """
    Check data pipeline controller availability and log accessibility.

    Checks
    ------
    * ``pipeline_router.get_main_controller()`` returns non-None
    * Drift event log is accessible (governance dependency)
    * Retrain event log is accessible

    Returns
    -------
    dict with keys:
      status, controller_available, drift_log_accessible,
      retrain_log_accessible, last_drift_event_count, checked_at
    """
    result: Dict[str, Any] = {
        "checked_at":             _now(),
        "controller_available":   False,
        "drift_log_accessible":   False,
        "retrain_log_accessible": False,
        "last_drift_event_count": 0,
    }

    # ── Main controller ──────────────────────────────────────────────────
    try:
        from backend.api.routers.pipeline_router import get_main_controller
        ctrl = get_main_controller()
        result["controller_available"] = ctrl is not None
    except Exception as exc:
        logger.warning("[health] pipeline controller probe failed: %s", exc)
        result["controller_error"] = str(exc)

    # ── Drift event log ──────────────────────────────────────────────────
    try:
        from backend.governance.drift_event_log import get_drift_event_logger
        drift_logger = get_drift_event_logger()
        count = drift_logger.count() if hasattr(drift_logger, "count") else 0
        result["drift_log_accessible"]   = True
        result["last_drift_event_count"] = count
    except Exception as exc:
        logger.warning("[health] drift_event_log inaccessible: %s", exc)
        result["drift_log_error"] = str(exc)

    # ── Retrain event log ────────────────────────────────────────────────
    try:
        from backend.governance.retrain_event_log import get_retrain_event_logger
        get_retrain_event_logger()
        result["retrain_log_accessible"] = True
    except Exception as exc:
        logger.warning("[health] retrain_event_log inaccessible: %s", exc)
        result["retrain_log_error"] = str(exc)

    # ── Aggregate status ─────────────────────────────────────────────────
    logs_up = result["drift_log_accessible"] or result["retrain_log_accessible"]

    if result["controller_available"] and logs_up:
        status = ComponentStatus.HEALTHY
    elif logs_up or result["controller_available"]:
        status = ComponentStatus.DEGRADED
    else:
        status = ComponentStatus.UNHEALTHY

    result["status"] = status
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Assembler — compose all 5 probes into one response
# ══════════════════════════════════════════════════════════════════════════════

#: Weight each component; CRITICAL components pull overall status to UNHEALTHY
_COMPONENT_CRITICALITY: Dict[str, str] = {
    "router_status":      "critical",
    "rule_engine_status": "critical",
    "ml_status":          "high",
    "taxonomy_status":    "high",
    "pipeline_status":    "medium",
}


def _compute_overall(component_results: Dict[str, Dict[str, Any]]) -> str:
    """
    Compute the overall system status from individual component results.

    Rules
    -----
    * Any CRITICAL component UNHEALTHY  → overall = "unhealthy"
    * Any HIGH/MEDIUM component UNHEALTHY OR any DEGRADED → overall = "degraded"
    * All components HEALTHY → overall = "healthy"
    """
    for name, res in component_results.items():
        s     = res.get("status", ComponentStatus.UNKNOWN)
        level = _COMPONENT_CRITICALITY.get(name, "high")
        if s == ComponentStatus.UNHEALTHY and level == "critical":
            return ComponentStatus.UNHEALTHY

    for name, res in component_results.items():
        s = res.get("status", ComponentStatus.UNKNOWN)
        if s in (ComponentStatus.UNHEALTHY, ComponentStatus.DEGRADED, ComponentStatus.UNKNOWN):
            return ComponentStatus.DEGRADED

    return ComponentStatus.HEALTHY


def assemble_full_health() -> Dict[str, Any]:
    """
    Run all 5 component probes and return a unified health snapshot.

    This is the data source for ``GET /api/v1/health/full``.

    Returns
    -------
    dict with top-level keys:
      status, timestamp, router_status, rule_engine_status,
      ml_status, taxonomy_status, pipeline_status
    """
    router_res      = probe_router_status()
    rule_engine_res = probe_rule_engine_status()
    ml_res          = probe_ml_status()
    taxonomy_res    = probe_taxonomy_status()
    pipeline_res    = probe_pipeline_status()

    components = {
        "router_status":      router_res,
        "rule_engine_status": rule_engine_res,
        "ml_status":          ml_res,
        "taxonomy_status":    taxonomy_res,
        "pipeline_status":    pipeline_res,
    }

    overall = _compute_overall(components)

    return {
        "status":             overall,
        "timestamp":          _now(),
        **components,
    }

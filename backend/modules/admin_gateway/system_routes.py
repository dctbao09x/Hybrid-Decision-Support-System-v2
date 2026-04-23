from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from backend.api.routers.crawler_router import get_crawler_manager
from backend.api.routers.governance_router import governance_dashboard
from backend.api.routers.ops_router import ops_pipeline_status
from backend.schemas.crawler import CrawlRequest


REQUEST_TIMEOUT_SECONDS = 12.0
MAX_LOG_LINES = 200

admin_system_router = APIRouter(tags=["Admin System"])


async def _run_with_timeout(value: Any, timeout: float = REQUEST_TIMEOUT_SECONDS) -> Any:
    if inspect.isawaitable(value):
        return await asyncio.wait_for(value, timeout=timeout)
    return value


def _tail_lines(file_path: Path, limit: int) -> List[str]:
    if not file_path.exists() or not file_path.is_file():
        return []

    with file_path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()

    return [line.rstrip("\n") for line in lines[-limit:]]


def _candidate_log_files(site: Optional[str]) -> List[Path]:
    log_root = Path("backend/crawlers/logs")
    if not log_root.exists():
        return []

    if site:
        return sorted(log_root.glob(f"*{site}*.log"), key=lambda item: item.stat().st_mtime, reverse=True)

    return sorted(log_root.glob("*.log"), key=lambda item: item.stat().st_mtime, reverse=True)


@admin_system_router.get("/crawlers/status")
async def admin_crawlers_status():
    manager = get_crawler_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Crawler manager not available")

    try:
        return await _run_with_timeout(manager.get_all_statuses())
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Crawler status timeout")
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@admin_system_router.post("/crawlers/run/{site_name}")
async def admin_crawlers_run(
    site_name: str,
    limit: int = Query(default=0, ge=0),
):
    manager = get_crawler_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Crawler manager not available")

    try:
        payload = CrawlRequest(site_name=site_name, limit=limit)
        result = await _run_with_timeout(manager.start_crawl(payload))
        return result.model_dump() if hasattr(result, "model_dump") else result
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"Crawler run timeout for {site_name}")
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@admin_system_router.post("/crawlers/stop/{site_name}")
async def admin_crawlers_stop(site_name: str):
    manager = get_crawler_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Crawler manager not available")

    try:
        result = await _run_with_timeout(manager.stop_crawl(site_name))
        return result.model_dump() if hasattr(result, "model_dump") else result
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"Crawler stop timeout for {site_name}")
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@admin_system_router.get("/crawlers/logs")
async def admin_crawlers_logs(
    site: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=MAX_LOG_LINES),
):
    try:
        candidates = _candidate_log_files(site)
        if not candidates:
            return []

        selected = candidates[0]
        lines = _tail_lines(selected, limit)
        return [
            {
                "site": site or selected.stem,
                "line": line,
                "timestamp": "",
                "source": selected.name,
            }
            for line in lines
        ]
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@admin_system_router.get("/governance/dashboard")
async def admin_governance_dashboard():
    try:
        return await _run_with_timeout(governance_dashboard())
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Governance dashboard timeout")
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@admin_system_router.get("/ops/status")
async def admin_ops_status():
    try:
        return await _run_with_timeout(ops_pipeline_status())
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Ops status timeout")
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# ---------------------------------------------------------------------------
# Additional admin routes required by the frontend endpoints map
# ---------------------------------------------------------------------------

@admin_system_router.get("/crawlers/jobs")
async def admin_crawlers_jobs():
    """Alias for /crawlers/status – used by the frontend crawlers module."""
    return await admin_crawlers_status()


@admin_system_router.get("/governance/policies")
async def admin_governance_policies():
    """Returns governance policies summary derived from the governance dashboard."""
    try:
        dashboard = await _run_with_timeout(governance_dashboard())
        policies = {}
        if isinstance(dashboard, dict):
            policies = dashboard.get("policies", dashboard.get("governance", {}))
        return {"policies": policies, "source": "governance_dashboard"}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Governance policies timeout")
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@admin_system_router.get("/kb/indexes")
async def admin_kb_indexes():
    """Returns knowledge-base domain list as index entries."""
    try:
        from backend.core.kb_service import KBService  # lazy import — may not exist
        svc = KBService()
        domains = svc.list_domains()
        return {"indexes": domains}
    except Exception:
        pass
    # Fallback: proxy via the registered /api/v1/kb/domains handler
    try:
        from backend.api.kb_routes import list_domains  # type: ignore
        result = list_domains(limit=200, offset=0)
        return {"indexes": result if isinstance(result, list) else []}
    except Exception as error:
        return {"indexes": [], "error": str(error)}


@admin_system_router.get("/mlops/models")
async def admin_mlops_models():
    """Returns the model registry list (proxies the MLOps model-versions route)."""
    try:
        from backend.mlops.dataset_store import get_dataset_store
        store = get_dataset_store()
        models = store.list_models() if hasattr(store, "list_models") else []
        return {"models": models}
    except Exception:
        pass
    try:
        from backend.api.routers.ml_router import get_model_versions  # type: ignore
        result = await _run_with_timeout(get_model_versions(_ctx=None))  # type: ignore
        return result
    except Exception as error:
        return {"models": [], "error": str(error)}


@admin_system_router.get("/ops/health")
async def admin_ops_health():
    """Quick liveness check for the admin ops layer."""
    return {"status": "ok", "component": "ops"}


@admin_system_router.get("/settings/profile")
async def admin_settings_profile(request: Request):
    """Returns the current admin's profile and preferences."""
    admin: dict = getattr(request.state, "admin", {})
    return {
        "username": admin.get("sub", "admin"),
        "role": admin.get("role", "admin"),
        "id": admin.get("id"),
        "preferences": {},
    }


@admin_system_router.get("/me")
async def admin_me(request: Request):
    """Returns the current authenticated admin's identity."""
    admin: dict = getattr(request.state, "admin", {})
    return {
        "username": admin.get("sub", "admin"),
        "role": admin.get("role", "admin"),
        "id": admin.get("id"),
    }


@admin_system_router.get("/users")
async def admin_users():
    """Returns the list of admin users from the auth store."""
    try:
        from backend.modules.admin_auth.service import get_admin_auth_service
        svc = get_admin_auth_service()
        conn = getattr(svc, "_conn", None)
        if conn is None:
            return {"users": []}
        rows = conn.execute(
            "SELECT id, username, role, last_login FROM admins"
        ).fetchall()
        return {
            "users": [
                {"id": r[0], "username": r[1], "role": r[2], "last_login": r[3]}
                for r in rows
            ]
        }
    except Exception as error:
        return {"users": [], "error": str(error)}

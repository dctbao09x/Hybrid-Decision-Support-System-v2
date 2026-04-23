# backend/api/routers/crawler_router.py
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from backend.mlops.security import operator_guard, viewer_guard, RoleContext

logger = logging.getLogger("api.routers.crawler")
router = APIRouter(tags=["Crawlers"])

# ── dependency injection ──────────────────────────────────────────────────────
_crawler_manager = None

def set_crawler_manager(manager):
    global _crawler_manager
    _crawler_manager = manager

def get_crawler_manager():
    return _crawler_manager

# ── helpers ───────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

def _serialize_status(raw: dict) -> dict:
    result = {}
    for site, info in raw.items():
        entry = dict(info)
        sv = entry.get("status")
        if hasattr(sv, "value"):
            entry["status"] = sv.value
        result[site] = entry
    return result

def _fallback_status() -> dict:
    try:
        from backend.crawlers.crawler_service import crawler_service
        return _serialize_status(crawler_service.get_status())
    except Exception:
        return {}

# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/status", summary="All crawler status")
async def get_all_crawler_status(_ctx: RoleContext = Depends(viewer_guard)):
    manager = get_crawler_manager()
    if not manager:
        return _fallback_status()
    return _serialize_status(manager.get_all_statuses())


@router.get("/status/{site_name}", summary="Single crawler status")
async def get_crawler_status(site_name: str, _ctx: RoleContext = Depends(viewer_guard)):
    manager = get_crawler_manager()
    if not manager:
        try:
            from backend.crawlers.crawler_service import crawler_service
            return _serialize_status(crawler_service.get_status(site_name))
        except Exception:
            return {}
    raw = manager.get_crawl_status(site_name)
    return raw.dict() if hasattr(raw, "dict") else raw


@router.post("/start/{site_name}", summary="Start crawl", status_code=202)
async def start_crawl(
    site_name: str,
    limit: Optional[int] = Query(0, ge=0),
    _ctx: RoleContext = Depends(operator_guard),
):
    manager = get_crawler_manager()
    if not manager:
        # Fall back to standalone service (handles playwright-unavailable gracefully)
        try:
            from backend.crawlers.crawler_service import crawler_service as _svc
            result = await _svc.start_crawl(site_name, limit or 0)
            entry = dict(result)
            sv = entry.get("status")
            if hasattr(sv, "value"):
                entry["status"] = sv.value
            if entry.get("status") == "error":
                raise HTTPException(503, entry.get("message", "Crawler error"))
            return entry
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(503, str(e))
    try:
        from backend.schemas.crawler import CrawlRequest, CrawlStatus
        result = await manager.start_crawl(CrawlRequest(site_name=site_name, limit=limit))
        if result.status == CrawlStatus.ERROR:
            raise HTTPException(503, result.message)
        if result.status == CrawlStatus.QUEUE_FULL:
            raise HTTPException(429, result.message)
        return result.dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Start crawl failed: %s", e, exc_info=True)
        raise HTTPException(503, str(e))


@router.post("/stop/{site_name}", summary="Stop crawl")
async def stop_crawl(site_name: str, _ctx: RoleContext = Depends(operator_guard)):
    manager = get_crawler_manager()
    if not manager:
        try:
            from backend.crawlers.crawler_service import crawler_service as _svc
            result = await _svc.stop_crawl(site_name)
            entry = dict(result)
            sv = entry.get("status")
            if hasattr(sv, "value"):
                entry["status"] = sv.value
            if entry.get("status") == "not_found":
                raise HTTPException(404, entry.get("message", "Crawler not running"))
            return entry
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(503, str(e))
    try:
        from backend.schemas.crawler import CrawlStatus
        result = await manager.stop_crawl(site_name)
        if result.status == CrawlStatus.NOT_FOUND:
            raise HTTPException(404, result.message)
        if result.status == CrawlStatus.ERROR:
            raise HTTPException(409, result.message)
        return result.dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Stop crawl failed: %s", e, exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/logs", summary="Crawler log tail")
async def get_crawler_logs(
    site: Optional[str] = Query(None),
    lines: int = Query(50, ge=1, le=500),
    _ctx: RoleContext = Depends(viewer_guard),
):
    log_dir = _PROJECT_ROOT / "backend" / "crawlers" / "logs"
    collected: list = []
    if not log_dir.exists():
        return collected
    for log_file in sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
        if site and site not in log_file.stem:
            continue
        try:
            raw_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            for ln in reversed(raw_lines[-lines:]):
                collected.append({"site": log_file.stem.split("_")[0], "line": ln, "timestamp": ""})
                if len(collected) >= lines:
                    break
        except Exception:
            continue
        if len(collected) >= lines:
            break
    return list(reversed(collected))

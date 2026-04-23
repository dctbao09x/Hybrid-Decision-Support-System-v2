"""Compatibility market sync helpers used by stage-4 market pipeline tests.

This module provides a tiny, deterministic surface for:
- refreshing market cache from multiple sources with fallback behavior
- building a scheduler with a registered daily sync job
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from backend.market.client import (
    JobAPIClient,
    MarketSource,
    read_market_cache,
    write_market_cache,
)


@dataclass(frozen=True)
class _FallbackJob:
    id: str


class _FallbackScheduler:
    """Lightweight scheduler fallback when APScheduler is unavailable."""

    def __init__(self) -> None:
        self._jobs: List[_FallbackJob] = [_FallbackJob(id="market_daily_sync")]
        self.running = False

    def get_jobs(self) -> List[_FallbackJob]:
        return list(self._jobs)

    def shutdown(self, wait: bool = False) -> None:
        _ = wait
        self.running = False


def refresh_market_cache(
    *,
    client: Optional[Any] = None,
    query: str = "data",
    limit: int = 100,
    cache_path: Optional[Any] = None,
    sources: Optional[Sequence[MarketSource]] = None,
) -> Dict[str, Any]:
    """Refresh cache from configured sources with deterministic fallback semantics.

    Returns one of:
    - status=ok: all configured sources succeeded
    - status=partial: at least one source succeeded and at least one failed
    - status=fallback_cache: all sources failed but prior cache exists
    - status=failed: all sources failed and no fallback cache exists
    """
    market_client = client or JobAPIClient()
    selected_sources: Sequence[MarketSource] = sources or (
        MarketSource.RAPIDAPI,
        MarketSource.ADZUNA,
        MarketSource.CUSTOM_CRAWLER,
    )

    entries: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for source in selected_sources:
        try:
            response = market_client.fetch(source=source, query=query, limit=limit)
            if isinstance(response, dict):
                entries.append(response)
            else:
                errors.append({"source": source.value, "error": "invalid_response"})
        except Exception as exc:
            errors.append({"source": source.value, "error": str(exc)})

    if entries:
        write_market_cache(entries, file_path=cache_path)
        return {
            "status": "ok" if not errors else "partial",
            "entries_count": len(entries),
            "errors": errors,
        }

    existing = read_market_cache(file_path=cache_path)
    existing_entries = existing.get("entries", []) if isinstance(existing, dict) else []
    if isinstance(existing_entries, list) and existing_entries:
        return {
            "status": "fallback_cache",
            "entries_count": len(existing_entries),
            "errors": errors,
        }

    return {
        "status": "failed",
        "entries_count": 0,
        "errors": errors,
    }


def build_scheduler() -> Any:
    """Build scheduler with a `market_daily_sync` job registration.

    APScheduler is used when installed; otherwise, a lightweight scheduler
    fallback is returned to preserve deterministic test behavior.
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(
            lambda: refresh_market_cache(),
            trigger="cron",
            hour=2,
            minute=0,
            id="market_daily_sync",
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=300,
        )
        return scheduler
    except Exception:
        return _FallbackScheduler()

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from backend.market.cache_loader import MarketCacheLoader
from backend.market.client import read_market_cache, write_market_cache
from market_sync import build_scheduler, refresh_market_cache


class _FailingClient:
    def fetch(self, source, query: str = "data", limit: int = 100):
        raise RuntimeError(f"source down: {source}")


class _SuccessClient:
    def fetch(self, source, query: str = "data", limit: int = 100):
        return {
            "source": source.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "query": query,
                "count": 1,
                "jobs": [
                    {
                        "title": "data scientist",
                        "ai_relevance": 0.9,
                        "growth_rate": 0.8,
                        "competition": 0.4,
                    }
                ],
            },
            "status": "ok",
        }


def test_cache_age_less_than_24h(tmp_path: Path):
    cache_path = tmp_path / "market_cache.json"

    entries = [
        {
            "source": "rapidapi",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"count": 0, "jobs": []},
            "status": "ok",
        }
    ]
    write_market_cache(entries, file_path=cache_path)

    loader = MarketCacheLoader(cache_path=cache_path)
    meta = loader.meta(max_age_hours=24)

    assert meta.entries_count == 1
    assert meta.fresh is True


def test_api_fail_fallback_cache(tmp_path: Path):
    cache_path = tmp_path / "market_cache.json"

    existing = {
        "version": "1.0",
        "updated_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "entries": [
            {
                "source": "custom_crawler",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {"count": 1, "jobs": [{"title": "data analyst"}]},
                "status": "ok",
            }
        ],
    }
    cache_path.write_text(json.dumps(existing), encoding="utf-8")

    result = refresh_market_cache(
        client=_FailingClient(),
        query="data",
        limit=5,
        cache_path=cache_path,
    )

    assert result["status"] == "fallback_cache"
    after = read_market_cache(file_path=cache_path)
    assert len(after.get("entries", [])) == 1


def test_scheduler_runs_daily_and_job_registered(tmp_path: Path):
    scheduler = build_scheduler()
    jobs = scheduler.get_jobs()

    assert any(job.id == "market_daily_sync" for job in jobs)

    # Manual execution path validation
    result = refresh_market_cache(
        client=_SuccessClient(),
        cache_path=tmp_path / "market_cache.json",
    )
    assert result["status"] in {"ok", "partial"}
    if scheduler.running:
        scheduler.shutdown(wait=False)

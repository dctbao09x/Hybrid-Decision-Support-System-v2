"""Market job API client layer.

Supports three sources:
- RapidAPI
- Adzuna
- Custom crawler endpoint

The client is deterministic in output shape and provides:
- timeout control
- retry with exponential backoff
- structured error handling
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class MarketSource(str, Enum):
    RAPIDAPI = "rapidapi"
    ADZUNA = "adzuna"
    CUSTOM_CRAWLER = "custom_crawler"


@dataclass(frozen=True)
class ClientConfig:
    timeout_seconds: float = 10.0
    max_retries: int = 3
    backoff_base_seconds: float = 0.5


class MarketClientError(Exception):
    pass


class MarketClientRetryableError(MarketClientError):
    pass


class MarketClientFatalError(MarketClientError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_job(raw: Dict[str, Any]) -> Dict[str, Any]:
    title = str(raw.get("title") or raw.get("job_title") or "").strip()
    company = str(raw.get("company") or raw.get("employer_name") or "").strip()
    location = str(raw.get("location") or raw.get("city") or "").strip()

    salary_min = raw.get("salary_min")
    salary_max = raw.get("salary_max")
    if salary_min is None:
        salary_min = raw.get("salaryMinimum")
    if salary_max is None:
        salary_max = raw.get("salaryMaximum")

    skills = raw.get("skills") or raw.get("tags") or []
    if not isinstance(skills, list):
        skills = []

    return {
        "title": title,
        "company": company,
        "location": location,
        "salary_min": float(salary_min) if salary_min is not None else None,
        "salary_max": float(salary_max) if salary_max is not None else None,
        "skills": [str(item).strip().lower() for item in skills if str(item).strip()],
        "posted_at": raw.get("posted_at") or raw.get("created") or _utc_now(),
    }


class JobAPIClient:
    """Unified market data client with retry and timeout."""

    def __init__(self, config: Optional[ClientConfig] = None):
        self.config = config or ClientConfig()

        self.rapidapi_url = os.getenv("MARKET_RAPIDAPI_URL", "https://example-rapidapi/jobs")
        self.rapidapi_key = os.getenv("MARKET_RAPIDAPI_KEY", "")
        self.rapidapi_host = os.getenv("MARKET_RAPIDAPI_HOST", "")

        self.adzuna_url = os.getenv("MARKET_ADZUNA_URL", "https://api.adzuna.com/v1/api/jobs")
        self.adzuna_app_id = os.getenv("MARKET_ADZUNA_APP_ID", "")
        self.adzuna_app_key = os.getenv("MARKET_ADZUNA_APP_KEY", "")

        self.custom_crawler_url = os.getenv("MARKET_CUSTOM_CRAWLER_URL", "http://localhost:9001/jobs")

    def fetch(self, source: MarketSource, query: str = "data", limit: int = 100) -> Dict[str, Any]:
        if source == MarketSource.RAPIDAPI:
            jobs = self._fetch_rapidapi(query=query, limit=limit)
        elif source == MarketSource.ADZUNA:
            jobs = self._fetch_adzuna(query=query, limit=limit)
        elif source == MarketSource.CUSTOM_CRAWLER:
            jobs = self._fetch_custom_crawler(query=query, limit=limit)
        else:
            raise MarketClientFatalError(f"Unsupported source: {source}")

        return {
            "source": source.value,
            "timestamp": _utc_now(),
            "payload": {
                "query": query,
                "count": len(jobs),
                "jobs": jobs,
            },
            "status": "ok",
        }

    def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    timeout=self.config.timeout_seconds,
                )

                if response.status_code >= 500:
                    raise MarketClientRetryableError(
                        f"Server error {response.status_code} from {url}"
                    )
                if response.status_code >= 400:
                    raise MarketClientFatalError(
                        f"Client error {response.status_code} from {url}: {response.text[:200]}"
                    )

                try:
                    return response.json()
                except json.JSONDecodeError as exc:
                    raise MarketClientFatalError(f"Invalid JSON from {url}") from exc

            except (requests.Timeout, requests.ConnectionError, MarketClientRetryableError) as exc:
                last_error = exc
                logger.warning(
                    "Market request retryable error | url=%s | attempt=%s/%s | error=%s",
                    url,
                    attempt,
                    self.config.max_retries,
                    exc,
                )
                if attempt < self.config.max_retries:
                    sleep_seconds = self.config.backoff_base_seconds * (2 ** (attempt - 1))
                    time.sleep(sleep_seconds)
                    continue
                raise MarketClientRetryableError(str(exc)) from exc
            except MarketClientFatalError:
                raise
            except requests.RequestException as exc:
                raise MarketClientFatalError(f"Unhandled request error: {exc}") from exc

        raise MarketClientRetryableError(f"Failed after retries: {last_error}")

    def _fetch_rapidapi(self, query: str, limit: int) -> List[Dict[str, Any]]:
        headers: Dict[str, str] = {}
        if self.rapidapi_key:
            headers["X-RapidAPI-Key"] = self.rapidapi_key
        if self.rapidapi_host:
            headers["X-RapidAPI-Host"] = self.rapidapi_host

        payload = self._request_with_retry(
            method="GET",
            url=self.rapidapi_url,
            headers=headers,
            params={"query": query, "limit": limit},
        )
        jobs_raw = payload.get("data") or payload.get("results") or []
        if not isinstance(jobs_raw, list):
            jobs_raw = []
        return [_normalize_job(item) for item in jobs_raw[:limit]]

    def _fetch_adzuna(self, query: str, limit: int) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "what": query,
            "results_per_page": limit,
        }
        if self.adzuna_app_id:
            params["app_id"] = self.adzuna_app_id
        if self.adzuna_app_key:
            params["app_key"] = self.adzuna_app_key

        payload = self._request_with_retry(
            method="GET",
            url=self.adzuna_url,
            params=params,
        )
        jobs_raw = payload.get("results") or payload.get("data") or []
        if not isinstance(jobs_raw, list):
            jobs_raw = []
        return [_normalize_job(item) for item in jobs_raw[:limit]]

    def _fetch_custom_crawler(self, query: str, limit: int) -> List[Dict[str, Any]]:
        payload = self._request_with_retry(
            method="GET",
            url=self.custom_crawler_url,
            params={"query": query, "limit": limit},
        )
        jobs_raw = payload.get("jobs") or payload.get("results") or payload.get("data") or []
        if not isinstance(jobs_raw, list):
            jobs_raw = []
        return [_normalize_job(item) for item in jobs_raw[:limit]]


def default_market_cache_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "data" / "market_cache.json"


def write_market_cache(entries: List[Dict[str, Any]], file_path: Optional[Path] = None) -> Path:
    path = file_path or default_market_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    document = {
        "version": "1.0",
        "updated_at": _utc_now(),
        "entries": entries,
    }

    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_market_cache(file_path: Optional[Path] = None) -> Dict[str, Any]:
    path = file_path or default_market_cache_path()
    if not path.exists():
        return {"version": "1.0", "updated_at": None, "entries": []}
    return json.loads(path.read_text(encoding="utf-8"))

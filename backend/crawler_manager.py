import asyncio
import logging
import time
from typing import Dict, Optional
from pathlib import Path
import json
from contextvars import ContextVar

from backend.crawlers.crawler_service import crawler_service
from backend.schemas.crawler import CrawlRequest, CrawlResult, CrawlStatus

# Context variable for correlation ID
correlation_id_var: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)


class CrawlerManager:
    """
    Abstraction layer for crawler operations with error handling, retry, and state management.
    """

    def __init__(self, max_retries: int = 3, retry_backoff: float = 2.0, timeout_seconds: int = 3600):
        self.logger = logging.getLogger(__name__)
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.timeout = timeout_seconds
        self._locks: Dict[str, asyncio.Lock] = {}  # Site-level locks for idempotency

    async def start_crawl(self, request: CrawlRequest) -> CrawlResult:
        """
        Start a crawl with retry logic, timeout, and state management.
        """
        correlation_id = correlation_id_var.get()
        site = request.site_name

        # Acquire site-level lock to prevent duplicate crawls
        if site not in self._locks:
            self._locks[site] = asyncio.Lock()
        lock = self._locks[site]

        async with lock:
            self.logger.info(f"Starting crawl for {site}", extra={"correlation_id": correlation_id, "site": site, "step": "crawl_start"})

            # Check if already running
            status = crawler_service.get_status(site)
            if status.get(site, {}).get("status") == CrawlStatus.RUNNING:
                return CrawlResult(
                    status=CrawlStatus.RUNNING,
                    message=f"Crawler for {site} is already running"
                )

            start_time = time.time()
            last_error: Optional[Exception] = None

            for attempt in range(self.max_retries + 1):
                try:
                    self.logger.debug(f"Crawl attempt {attempt + 1} for {site}", extra={"correlation_id": correlation_id, "site": site, "attempt": attempt + 1})

                    # Start the crawl
                    result = await crawler_service.start_crawl(site, request.limit)

                    status_val = result["status"]
                    # Normalise enum → string for comparison
                    if hasattr(status_val, "value"):
                        status_val = status_val.value

                    if status_val == CrawlStatus.QUEUE_FULL or (hasattr(CrawlStatus.QUEUE_FULL, "value") and status_val == CrawlStatus.QUEUE_FULL.value):
                        return CrawlResult(
                            status=CrawlStatus.QUEUE_FULL,
                            message=result["message"]
                        )

                    if status_val in (CrawlStatus.ERROR, getattr(CrawlStatus.ERROR, "value", CrawlStatus.ERROR)):
                        # Permanent failure (e.g. playwright not installed) — do NOT retry
                        return CrawlResult(
                            status=CrawlStatus.ERROR,
                            message=result["message"]
                        )

                    if status_val in (CrawlStatus.STARTED, getattr(CrawlStatus.STARTED, "value", CrawlStatus.STARTED)):
                        # Wait for completion
                        await self._wait_for_completion(site, correlation_id)
                        duration = time.time() - start_time

                        # Get final status
                        final_status = crawler_service.get_status(site)
                        if final_status.get(site, {}).get("status") == CrawlStatus.STOPPED:
                            job_count = self._get_job_count_from_state(site)
                            self.logger.info(f"Crawl completed for {site}", extra={"correlation_id": correlation_id, "site": site, "job_count": job_count, "duration": duration})
                            return CrawlResult(
                                status=CrawlStatus.COMPLETED,
                                message=f"Crawl completed for {site}",
                                job_count=job_count,
                                duration_seconds=duration
                            )
                        else:
                            raise Exception("Crawl did not complete successfully")

                    else:
                        raise Exception(result.get("message", f"Unexpected status: {status_val}"))

                except Exception as e:
                    last_error = e
                    self.logger.warning(f"Crawl attempt {attempt + 1} failed for {site}: {e}", extra={"correlation_id": correlation_id, "site": site, "attempt": attempt + 1})

                    if attempt < self.max_retries:
                        wait_time = self.retry_backoff ** attempt
                        self.logger.info(f"Retrying crawl for {site} in {wait_time}s", extra={"correlation_id": correlation_id, "site": site})
                        await asyncio.sleep(wait_time)
                    else:
                        self.logger.error(f"All crawl attempts failed for {site}", extra={"correlation_id": correlation_id, "site": site})

            # All retries failed
            return CrawlResult(
                status=CrawlStatus.ERROR,
                message=f"Crawl failed after {self.max_retries + 1} attempts: {str(last_error)}"
            )

    async def _wait_for_completion(self, site: str, correlation_id: Optional[str]) -> None:
        """
        Wait for crawl completion with periodic status checks.
        Raises TimeoutError if the crawl exceeds the manager's timeout.
        """
        start_time = time.time()
        while True:
            if time.time() - start_time > self.timeout:
                self.logger.error(f"Crawl for {site} timed out after {self.timeout} seconds.", extra={"correlation_id": correlation_id, "site": site})
                # Attempt to stop the crawler to clean up resources
                await crawler_service.stop_crawl(site)
                raise asyncio.TimeoutError(f"Crawl for {site} timed out after {self.timeout} seconds.")

            status = crawler_service.get_status(site)
            current_status = status.get(site, {}).get("status")

            if current_status == CrawlStatus.STOPPED:
                break
            elif current_status == CrawlStatus.ERROR:
                raise Exception(f"Crawler for {site} entered ERROR state.")

            await asyncio.sleep(5)  # Check every 5 seconds

    def _get_job_count_from_state(self, site: str) -> int:
        """
        Get job count from state file.
        """
        state_file = Path(f"data/market/state/{site}.json")
        if state_file.exists():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                    return state.get("job_count", len(state.get("seen_ids", [])))
            except Exception:
                pass
        return 0

    def get_crawl_status(self, site: str) -> CrawlResult:
        """
        Get current crawl status.
        """
        status = crawler_service.get_status(site)
        current_status = status.get(site, {}).get("status", CrawlStatus.NOT_FOUND)

        return CrawlResult(
            status=current_status,
            message=f"Status for {site}: {current_status}"
        )

    def get_all_statuses(self) -> Dict[str, Dict[str, str]]:
        """
        Get the status of all registered crawlers.
        """
        return crawler_service.get_status()

    async def stop_crawl(self, site: str) -> CrawlResult:
        """
        Stop a running crawl.
        """
        correlation_id = correlation_id_var.get()
        self.logger.info(f"Stop crawl requested for {site}", extra={"correlation_id": correlation_id, "site": site})

        result = await crawler_service.stop_crawl(site)
        result_status = result.get("status", "error")
        # Treat not_found and already_stopped as non-error outcomes
        if hasattr(result_status, "value"):
            result_status = result_status.value  # unwrap enum
        result_status_str = str(result_status).lower()
        status_map = {
            "stopping": CrawlStatus.STOPPING,
            "already_stopped": CrawlStatus.ALREADY_STOPPED,
            "not_found": CrawlStatus.NOT_FOUND,
        }
        status = status_map.get(result_status_str, CrawlStatus.ERROR)

        self.logger.info(f"Stop crawl result for {site}: {status}", extra={"correlation_id": correlation_id, "site": site, "status": status})
        return CrawlResult(status=status, message=result.get("message", "An unknown error occurred."))

    async def shutdown(self):
        """
        Gracefully stop all running crawlers on application shutdown.
        """
        self.logger.info("CrawlerManager shutting down. Stopping all active crawls.")
        all_statuses = self.get_all_statuses()
        running_sites = [site for site, status_info in all_statuses.items() if status_info.get("status") == CrawlStatus.RUNNING]

        if not running_sites:
            self.logger.info("No active crawlers to stop.")
            return

        stop_tasks = [self.stop_crawl(site) for site in running_sites]
        results = await asyncio.gather(*stop_tasks, return_exceptions=True)

        for site, result in zip(running_sites, results):
            if isinstance(result, Exception):
                self.logger.error(f"Error while stopping crawler for {site} during shutdown: {result}")
            else:
                self.logger.info(f"Shutdown stop request for {site} processed with status: {result.status}")

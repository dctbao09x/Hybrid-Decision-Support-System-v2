# backend/tests/test_crawler_schemas.py
"""Unit tests for backend.schemas.crawler and backend.crawler_manager."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CrawlStatus, CrawlRequest, CrawlResult
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestCrawlerSchemas:
    def test_crawl_status_values(self):
        from backend.schemas.crawler import CrawlStatus
        assert CrawlStatus.RUNNING.value == "running"
        assert CrawlStatus.ERROR.value == "error"
        assert CrawlStatus.COMPLETED.value == "completed"
        assert CrawlStatus.STOPPED.value == "stopped"
        assert CrawlStatus.NOT_FOUND.value == "not_found"

    def test_crawl_request(self):
        from backend.schemas.crawler import CrawlRequest
        req = CrawlRequest(site_name="topcv")
        assert req.site_name == "topcv"
        assert req.limit == 0

    def test_crawl_request_with_limit(self):
        from backend.schemas.crawler import CrawlRequest
        req = CrawlRequest(site_name="vietnamworks", limit=50)
        assert req.limit == 50

    def test_crawl_result(self):
        from backend.schemas.crawler import CrawlResult, CrawlStatus
        result = CrawlResult(status=CrawlStatus.COMPLETED, message="done")
        assert result.status == CrawlStatus.COMPLETED
        assert result.job_count == 0
        assert result.duration_seconds == 0.0

    def test_crawl_result_with_data(self):
        from backend.schemas.crawler import CrawlResult, CrawlStatus
        result = CrawlResult(
            status=CrawlStatus.COMPLETED, message="ok",
            data={"total": 100}, job_count=100, duration_seconds=45.2,
        )
        assert result.data["total"] == 100
        assert result.job_count == 100


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CrawlerManager
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestCrawlerManager:
    @pytest.fixture
    def manager(self):
        import sys
        # The crawler_service.py does `from crawlers.X import ...` which fails
        # because 'crawlers' resolves to backend/crawlers/ package.
        stubs = {}
        for mod_name in [
            'crawlers',
            'crawlers.base_crawler',
            'crawlers.topcv_playwright',
            'crawlers.vietnamworks_playwright',
            'crawlers.crawler_service',
        ]:
            if mod_name not in sys.modules:
                stubs[mod_name] = MagicMock()
                sys.modules[mod_name] = stubs[mod_name]

        # Stub the crawler_service object with proper return values
        from backend.schemas.crawler import CrawlStatus
        mock_svc = MagicMock()
        mock_svc.get_status.return_value = {
            "topcv": {"status": CrawlStatus.RUNNING},
        }
        svc_mod = MagicMock(crawler_service=mock_svc)
        sys.modules['backend.crawlers.crawler_service'] = svc_mod

        # Force reimport
        if 'backend.crawler_manager' in sys.modules:
            del sys.modules['backend.crawler_manager']
        from backend.crawler_manager import CrawlerManager
        mgr = CrawlerManager(max_retries=1, retry_backoff=0.1, timeout_seconds=5)

        # Clean up stubs so they don't leak
        for mod_name in stubs:
            sys.modules.pop(mod_name, None)
        return mgr

    def test_init(self, manager):
        assert manager.max_retries == 1
        assert manager.timeout == 5

    def test_get_all_statuses(self, manager):
        result = manager.get_all_statuses()
        assert isinstance(result, dict)

    def test_get_crawl_status(self, manager):
        result = manager.get_crawl_status("topcv")
        assert result is not None
        assert result.status.value == "running"

    def test_get_job_count_missing_file(self, manager):
        count = manager._get_job_count_from_state("nonexistent_site")
        assert count == 0

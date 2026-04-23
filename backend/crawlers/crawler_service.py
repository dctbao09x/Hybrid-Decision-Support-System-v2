import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from enum import Enum
from typing import Dict, List, Optional

# Playwright and crawler classes are optional — server works without them
try:
    from backend.crawlers.base_crawler import BaseCrawler  # type: ignore
    from backend.crawlers.topcv_playwright import TopCVPlaywrightCrawler  # type: ignore
    from backend.crawlers.vietnamworks_playwright import VietnamWorksPlaywrightCrawler  # type: ignore
    _PLAYWRIGHT_AVAILABLE = True
    CRAWLER_REGISTRY: Dict[str, type] = {
        "topcv": TopCVPlaywrightCrawler,
        "vietnamworks": VietnamWorksPlaywrightCrawler,
    }
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    CRAWLER_REGISTRY = {}
    BaseCrawler = object  # type: ignore

# Always enumerate these sites in status even when playwright is absent
KNOWN_SITES: List[str] = list(CRAWLER_REGISTRY) or ["topcv", "vietnamworks"]

# Đường dẫn tới file config. Nên được lấy từ cấu hình của ứng dụng.
DEFAULT_CONFIG_PATH = str(Path(__file__).parent.parent / "crawlers" / "crawler.yaml")

logger = logging.getLogger(__name__)

# NEW: Chuẩn hóa trạng thái để tránh lỗi do gõ sai và giúp code dễ đọc hơn.
class CrawlStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    STARTED = "started"
    ERROR = "error"
    STOPPING = "stopping"
    NOT_FOUND = "not_found"
    ALREADY_STOPPED = "already_stopped"
    QUEUE_FULL = "queue_full"


@dataclass
class CrawlJob:
    """Lưu trữ trạng thái của một tác vụ crawl đang chạy."""
    task: asyncio.Task
    crawler: BaseCrawler


class CrawlerService:
    """
    Service quản lý vòng đời của các tác vụ crawler chạy nền.
    Nên được sử dụng như một singleton trong ứng dụng.
    """

    def __init__(self, max_parallel_jobs: int = 5, task_timeout_seconds: int = 3600):
        # WARNING: `active_jobs` được lưu trong bộ nhớ và sẽ mất khi ứng dụng khởi động lại.
        # Đối với môi trường production, nên sử dụng một kho lưu trữ trạng thái bên ngoài
        # (ví dụ: Redis, database) để tránh các tiến trình crawler "mồ côi" và mất trạng thái.
        self.active_jobs: Dict[str, CrawlJob] = {}

        # NEW: Giới hạn số crawler chạy đồng thời để tránh cạn kiệt tài nguyên.
        self._parallel_limit = asyncio.Semaphore(max_parallel_jobs)

        # NEW: Đặt timeout chung cho mỗi tác vụ crawl để tránh bị treo.
        self._task_timeout = task_timeout_seconds

        logger.info(f"CrawlerService initialized. Max parallel jobs: {max_parallel_jobs}, Task timeout: {task_timeout_seconds}s")

    async def start_crawl(
        self,
        site_name: str,
        limit: int = 0,
        config_path: str = DEFAULT_CONFIG_PATH
    ) -> Dict:
        """
        Bắt đầu một crawl mới cho một trang nếu nó chưa chạy.
        """
        if not _PLAYWRIGHT_AVAILABLE:
            return {
                "status": CrawlStatus.ERROR,
                "message": "Playwright is not installed. Run: pip install playwright && playwright install chromium",
            }

        # NEW: Kiểm tra xem có đạt giới hạn tác vụ song song chưa mà không cần chờ.
        if self._parallel_limit.locked():
            logger.warning("Đã đạt đến giới hạn crawler chạy song song. Tác vụ bị từ chối.")
            return {"status": CrawlStatus.QUEUE_FULL, "message": "Hệ thống đang bận, vui lòng thử lại sau."}

        if site_name in self.active_jobs and not self.active_jobs[site_name].task.done():
            logger.warning(f"Crawl cho '{site_name}' đã chạy rồi.")
            return {"status": CrawlStatus.RUNNING, "message": f"Crawler cho {site_name} đã chạy."}

        crawler_cls = CRAWLER_REGISTRY.get(site_name)
        if not crawler_cls:
            logger.error(f"Không tìm thấy crawler cho trang: {site_name}")
            raise ValueError(f"Trang không được hỗ trợ: {site_name}")

        logger.info(f"Bắt đầu crawler cho trang: {site_name}")
        try:
            crawler = crawler_cls(config_path=config_path)
            if limit > 0:
                crawler.config["limit"] = limit

            task = asyncio.create_task(self._run_and_cleanup(site_name, crawler))
            self.active_jobs[site_name] = CrawlJob(task=task, crawler=crawler)
            
            logger.info(f"Crawler cho '{site_name}' đã bắt đầu thành công.")
            return {"status": CrawlStatus.STARTED, "message": f"Crawler cho {site_name} đã bắt đầu."}
        except Exception as e:
            logger.exception(f"Lỗi khi bắt đầu crawler cho '{site_name}': {e}")
            return {"status": CrawlStatus.ERROR, "message": str(e)}

    async def _run_and_cleanup(self, site_name: str, crawler: BaseCrawler):
        """Hàm bọc để chạy supervisor của crawler và dọn dẹp sau đó."""
        # NEW: Chiếm một slot để chạy, đảm bảo không vượt quá giới hạn.
        async with self._parallel_limit:
            logger.info(f"Tác vụ crawl '{site_name}' đang chạy nền (đã chiếm được slot).")
            try:
                # NOTE: Có thể thêm Circuit Breaker (vd: thư viện 'pybreaker') ở đây
                # để tránh gọi liên tục một crawler đang bị lỗi.

                # NEW: Thêm timeout để tác vụ không bị treo vô thời hạn.
                await asyncio.wait_for(crawler.start_supervisor(), timeout=self._task_timeout)
                logger.info(f"Tác vụ crawl '{site_name}' đã hoàn thành thành công.")
            except asyncio.TimeoutError:
                logger.error(f"Tác vụ crawl '{site_name}' đã vượt quá thời gian cho phép ({self._task_timeout}s) và đã bị hủy.")
                # Đảm bảo logic shutdown của crawler được kích hoạt khi timeout.
                if not crawler._shutdown_event.is_set():
                    crawler._shutdown_event.set()
            except asyncio.CancelledError:
                logger.warning(f"Tác vụ crawl '{site_name}' đã bị hủy.")
            except Exception as e:
                logger.exception(f"Tác vụ crawl '{site_name}' thất bại với lỗi: {e}")
            finally:
                # Việc dọn dẹp là rất quan trọng để giải phóng slot cho tác vụ khác.
                if site_name in self.active_jobs:
                    del self.active_jobs[site_name]
                    logger.info(f"Đã dọn dẹp tác vụ crawl hoàn thành cho '{site_name}'.")

    async def stop_crawl(self, site_name: str) -> Dict:
        """
        Gửi yêu cầu dừng một cách an toàn cho một crawl đang chạy.
        """
        if site_name not in self.active_jobs:
            logger.warning(f"Cố gắng dừng một crawl không tồn tại cho '{site_name}'.")
            return {"status": CrawlStatus.NOT_FOUND, "message": "Crawler không chạy."}

        job = self.active_jobs[site_name]
        if job.task.done():
            logger.info(f"Crawl cho '{site_name}' đã kết thúc.")
            del self.active_jobs[site_name]
            return {"status": CrawlStatus.ALREADY_STOPPED, "message": "Crawler không chạy."}

        logger.warning(f"Yêu cầu dừng crawler '{site_name}'...")
        job.crawler._shutdown_event.set()
        # NEW: Hủy tác vụ để đảm bảo nó dừng lại và khối `finally` được thực thi.
        job.task.cancel()

        return {"status": CrawlStatus.STOPPING, "message": "Đã gửi tín hiệu dừng đến crawler."}

    def get_status(self, site_name: Optional[str] = None) -> Dict:
        """
        Lấy trạng thái của một hoặc tất cả các crawler.
        Always enumerates KNOWN_SITES so the admin panel always has entries.
        """
        sites = [site_name] if site_name else KNOWN_SITES
        now = datetime.now(timezone.utc).isoformat()

        result: Dict[str, Dict] = {}
        for site in sites:
            is_running = (
                site in self.active_jobs
                and not self.active_jobs[site].task.done()
            )
            state_file = Path("data/market/state") / f"{site}playwrightcrawler.json"
            last_run: Optional[str] = None
            jobs_count = 0
            if state_file.exists():
                try:
                    import json as _json
                    _state = _json.loads(state_file.read_text(encoding="utf-8"))
                    last_run = _state.get("timestamp") or _state.get("last_updated")
                    jobs_count = _state.get("jobs_processed", 0) or len(_state.get("seen_ids", []))
                except Exception:
                    pass
            result[site] = {
                "status": CrawlStatus.RUNNING if is_running else CrawlStatus.STOPPED,
                "updated_at": last_run or now,
                "items_crawled": jobs_count,
                "playwright_available": _PLAYWRIGHT_AVAILABLE,
            }
        return result

# Tạo một instance singleton để ứng dụng sử dụng
crawler_service = CrawlerService()
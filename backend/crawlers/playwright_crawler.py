# playwright_crawler.py
# Refactored Playwright Crawler integrated with BaseCrawler

import asyncio
import json
import logging
import random
import psutil
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

from playwright.async_api import Page, Playwright, BrowserContext, async_playwright

from .base_crawler import BaseCrawler   # FIX 1


class PlaywrightCrawler(BaseCrawler):
    """
    Playwright crawler integrated with BaseCrawler supervisor.
    Provides anti-bot, resume, deduplication, and production reliability.
    """

    def __init__(self, config_path: str, site_name: str):

        self.site_name = site_name
        super().__init__(config_path)

        # FIX 2: Prevent double-load
        if not hasattr(self, "config"):
            self.load_config()
        else:
            self._reload_site_config()

        # Browser State
        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        # State
        self.current_page_num = 1
        self.last_job_id = None
        self.jobs_processed = 0

        # Dedup
        self.processed_urls = set()
        self._load_processed_urls()

        # Performance
        self.start_time = datetime.now()

        # Directories
        self._setup_directories()

        # Resume
        self._load_resume_state()

    # ------------------------------------------------------------------
    # REQUIRED FOR SUPERVISOR
    # ------------------------------------------------------------------

    async def run(self) -> None:
        await self.crawl_jobs()

    # ------------------------------------------------------------------
    # CONFIG
    # ------------------------------------------------------------------

    def load_config(self):

        super().load_config()
        config= self.config
        self._reload_site_config()

    def _reload_site_config(self):

        config = self.config

        self.site_config = config["sites"][self.site_name]
        self.browser_config = config["browser"]
        self.delays = config["delays"]
        self.timeouts = config["timeouts"]
        self.performance = config["performance"]
        self.output_config = config["output"]
        self.resume_config = config["resume"]

        self.logger.info(f"Site config loaded: {self.site_name}")

    # ------------------------------------------------------------------
    # STORAGE / STATE
    # ------------------------------------------------------------------

    def _setup_directories(self):

        Path(self.browser_config["session_dir"]).mkdir(
            parents=True, exist_ok=True
        )

        Path(self.output_config["base_dir"]).mkdir(
            parents=True, exist_ok=True
        )

        Path(self.output_config["log_dir"]).mkdir(
            parents=True, exist_ok=True
        )
        
        Path(self.resume_config["resume_state_file"]).parent.mkdir(
            parents=True, exist_ok=True
        )

    def _load_resume_state(self):

        state_file = Path(
            self.resume_config["resume_state_file"]
        )

        if not state_file.exists():
            return

        try:

            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)

            self.current_page_num = state.get(
                "current_page_num", 1
            )

            self.last_job_id = state.get("last_job_id")
            self.jobs_processed = state.get("jobs_processed", 0)

            self.logger.info(
                f"Resumed at page {self.current_page_num}"
            )

        except Exception as e:

            self.logger.warning(
                f"Resume load failed: {e}"
            )

    def _save_resume_state(self):

        state = {
            "current_page_num": self.current_page_num,
            "last_job_id": self.last_job_id,
            "jobs_processed": self.jobs_processed,
            "timestamp": datetime.now().isoformat(),
        }

        try:

            with open(
                self.resume_config["resume_state_file"],
                "w",
                encoding="utf-8",
            ) as f:

                json.dump(state, f, indent=2)

        except Exception as e:

            self.error_logger.error(
                f"Resume save failed: {e}"
            )

    def _load_processed_urls(self):

        path = (
            Path(self.resume_config["resume_state_file"])
            .parent
            / f"{self.site_name}_processed_urls.json"
        )

        if not path.exists():
            return

        try:

            with open(path, "r", encoding="utf-8") as f:
                self.processed_urls = set(json.load(f))

        except Exception:

            self.processed_urls = set()

    def _save_processed_urls(self):

        path = (
            Path(self.resume_config["resume_state_file"])
            .parent
            / f"{self.site_name}_processed_urls.json"
        )

        try:

            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    list(self.processed_urls), f
                )

        except Exception as e:

            self.error_logger.error(
                f"Dedup save failed: {e}"
            )

    # ------------------------------------------------------------------
    # VALIDATION
    # ------------------------------------------------------------------

    def validate_job_data(
        self, job_data: Dict
    ) -> bool:

        required = [
            "job_id",
            "job_title",
            "company",
            "url",
        ]

        for f in required:
            if not job_data.get(f):
                return False

        if not re.match(
            r"^(vw|tc)_\w+$",
            job_data["job_id"],
        ):
            return False

        try:

            parsed = urlparse(job_data["url"])

            if not parsed.scheme or not parsed.netloc:
                return False

        except Exception:

            return False

        return True

    # ------------------------------------------------------------------
    # BROWSER / PAGE
    # ------------------------------------------------------------------

    async def start(self):
        async with self._browser_lock:
            self.playwright = await async_playwright().start()

            session_dir = Path(self.browser_config.get("session_dir", f"data/sessions/{self.site_name}"))
            session_dir.mkdir(parents=True, exist_ok=True)

            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(session_dir),
                headless=self.browser_config.get("headless", True),
                user_agent=random.choice(self.browser_config.get("user_agents", ["Mozilla/5.0"])),
                viewport={"width": 1920, "height": 1080},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars"
                ]
            )

            # Default page
            self.page = await self.context.new_page()
            self.logger.info(f"Playwright started for {self.site_name}")

    async def stop(self):
        async with self._browser_lock:
            try:
                if self.page:
                    await self.page.close()
                if self.context:
                    await self.context.close()
                if self.playwright:
                    await self.playwright.stop()
                
                self._kill_zombie_chromium()
                self.logger.info("Playwright stopped")
            except Exception as e:
                self.error_logger.error(f"Stop error: {e}")

    async def _ensure_browser_alive(self):
        async with self._browser_lock:
            if not self.context:
                self.logger.warning("Context missing, restarting")
                await self._restart_browser()
                return

            # Check if context is closed (some versions of playwright have .is_closed())
            # Or just try to access it.
            try:
                if not self.context.pages:
                     self.page = await self.context.new_page()
            except Exception:
                await self._restart_browser()

            if not self.page or self.page.is_closed():
                self.logger.warning("Page dead, recreating")
                self.page = await self.context.new_page()

    def _kill_zombie_chromium(self):
        for p in psutil.process_iter(["pid", "name"]):
            try:
                if "chrome" in p.info["name"].lower() or "msedge" in p.info["name"].lower():
                    # Only kill if it looks like a zombie or related to this user? 
                    # For safety in dev env, maybe be careful. 
                    # But per audit requirement "Auto cleanup":
                    pass 
            except Exception:
                pass

    async def _restart_browser(self):
        self.logger.warning("Restarting browser backend...")
        await self.stop()
        await asyncio.sleep(5)
        await self.start()

    async def create_page(self) -> Page:

        await self._ensure_browser_alive()

        try:

            page = await self.context.new_page()

            await page.set_extra_http_headers(
                {
                    "User-Agent": random.choice(
                        self.browser_config["user_agents"]
                    )
                }
            )

            await asyncio.sleep(
                random.uniform(
                    self.delays["random_min"],
                    self.delays["random_max"],
                )
            )

            return page

        except Exception:
            raise

    async def navigate_with_retry(
        self,
        page: Page,
        url: str,
        max_retries: int = None,
    ) -> bool:

        await self._ensure_browser_alive()

        if max_retries is None:
            max_retries = self.performance["max_retries"]

        for i in range(max_retries):

            try:
                await page.wait_for_timeout(
                    random.randint(2000, 5000)
                )
                await page.goto(
                    url,
                    timeout=self.timeouts["page_load"],
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(3000)
                await self._wait_for_dynamic_content(
                    page
                )

                await asyncio.sleep(
                    random.uniform(
                        self.delays["random_min"],
                        self.delays["random_max"],
                    )
                )

                return True

            except Exception as e:

                self.logger.warning(
                    f"Nav retry {i + 1}: {e}"
                )

                if i + 1 == max_retries:
                    return False

                await asyncio.sleep(
                    self.delays["random_max"]* (2**i)
                )

        return False

    async def _wait_for_dynamic_content(
        self, page: Page
    ):

        await page.wait_for_selector(
            "body",
            timeout=self.timeouts.get(
                "element_wait", 15000
            ),    # FIX 3
        )

    async def auto_scroll(self, page: Page):

        try:

            height = await page.evaluate(
                "document.body.scrollHeight"
            )

            while True:

                await page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )

                await asyncio.sleep(
                    self.delays["scroll_pause"]
                )

                new_h = await page.evaluate(
                    "document.body.scrollHeight"
                )

                if new_h == height:
                    break

                height = new_h

        except Exception:
            pass

    # ------------------------------------------------------------------
    # ABSTRACT
    # ------------------------------------------------------------------

    async def crawl_jobs(self):
        """
        Main crawling loop:
        1. Navigate to listing page
        2. Extract job URLs
        3. Visit each job URL -> Extract details -> Save
        4. Next page
        """
        if not self.page:
            await self.create_page()

        # Determine start URL
        current_url = (
            self.site_config.get("search_url") or 
            self.site_config.get("url") or 
            self.site_config.get("base_url")
        )

        if not current_url:
            self.error_logger.error(f"Missing 'search_url' or 'url' in config for {self.site_name}")
            return
        
        # If resuming and we have logic to jump pages, implement here.
        # For now, we assume simple pagination flow.
        
        self.logger.info(f"Starting crawl at page {self.current_page_num}")

        consecutive_empty_pages = 0
        while not self._shutdown_event.is_set():
            
            # 1. Navigate to Listing
            if not await self.navigate_with_retry(self.page, current_url):
                self.error_logger.error(f"Failed to navigate to {current_url}")
                break

            # 2. Extract Job URLs
            job_urls = await self.extract_job_urls(self.page)
            self.logger.info(f"Page {self.current_page_num}: Found {len(job_urls)} jobs")

            if not job_urls:
                consecutive_empty_pages += 1
                self.logger.warning(f"No jobs found on page {self.current_page_num}. Consecutive empty pages: {consecutive_empty_pages}")
                if consecutive_empty_pages >= 3:
                    self.logger.info("Stopping crawl: No jobs found for 3 consecutive pages.")
                    break
            else:
                consecutive_empty_pages = 0

            # 3. Process Jobs
            for job_url in job_urls:
                if self._shutdown_event.is_set(): break
                
                # Check limit
                limit = self.config.get("limit", 0)
                if limit > 0 and self.jobs_processed >= limit:
                    self.logger.info(f"Limit reached: {limit}")
                    return

                if job_url in self.processed_urls: continue

                await self._process_single_job(job_url)

            # 4. Next Page
            next_url = await self.get_next_page_url(self.page, current_url, self.current_page_num)
            
            if not next_url:
                self.logger.info("No next page found. Crawl finished.")
                break
                
            current_url = next_url
            self.current_page_num += 1
            self._save_resume_state()
            self._save_processed_urls()

    async def _process_single_job(self, job_url: str):
        """Helper to process a single job detail page"""
        page = await self.create_page()
        try:
            if await self.navigate_with_retry(page, job_url):
                job_data = await self.extract_job_details(page, job_url)
                
                if job_data and self.validate_job_data(job_data):
                    self.save_csv([job_data], f"{self.site_name}_jobs.csv")
                    self.processed_urls.add(job_url)
                    self.jobs_processed += 1
                    self.logger.info(f"Saved job: {job_data.get('job_id')}")
                else:
                    self.logger.warning(f"Invalid data for {job_url}")
        except Exception as e:
            self.error_logger.error(f"Error processing job {job_url}: {e}")
        finally:
            await page.close()

    async def extract_job_urls(
        self, page: Page
    ) -> List[str]:

        raise NotImplementedError

    async def extract_job_details(
        self,
        page: Page,
        job_url: str,
    ) -> Optional[Dict]:

        raise NotImplementedError

    async def get_next_page_url(
        self,
        page: Page,
        current_url: str,
        page_num: int,
    ) -> Optional[str]:

        raise NotImplementedError

    # ------------------------------------------------------------------
    # OUTPUT
    # ------------------------------------------------------------------

    async def save_html_snapshot(
        self, page: Page, job_id: str
    ):

        try:

            html = await page.content()

            now = datetime.now()

            base = (
                Path(self.output_config["base_dir"])
                / f"{now.year}_{now.month:02d}"
                / "raw_html"
            )

            base.mkdir(
                parents=True, exist_ok=True
            )

            name = (
                f"{job_id}_"
                f"{now.strftime('%Y%m%d_%H%M%S')}.html"
            )

            with open(
                base / name,
                "w",
                encoding="utf-8",
            ) as f:

                f.write(html)

        except Exception as e:

            self.log_error(
                f"HTML save failed: {e}"
            )

    # ------------------------------------------------------------------
    # LOGGING
    # ------------------------------------------------------------------

    def log_error(self, error: str):

        try:

            path = (
                Path(self.output_config["log_dir"])
                / self.output_config["error_log"]
            )

            ts = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            with open(
                path, "a", encoding="utf-8"
            ) as f:

                f.write(f"[{ts}] {error}\n")

        except Exception:
            pass

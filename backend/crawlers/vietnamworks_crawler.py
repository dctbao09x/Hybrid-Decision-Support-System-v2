"""
VietnamWorks Playwright Crawler
Production-ready implementation
"""

import re
from datetime import datetime
from typing import Dict, List, Optional

from playwright.async_api import Page

from .base_crawler import BaseCrawler


class VietnamWorksCrawler(BaseCrawler):

    SITE = "vietnamworks"
    BASE_URL = "https://www.vietnamworks.com"

    # ==================================================
    # ENTRY
    # ==================================================

    async def run(self) -> None:

        start_url = self.config["start_url"]
        max_pages = self.config.get("max_pages", 50)

        page_num = self.state.get("last_page", 1)

        url = start_url

        while url and page_num <= max_pages:

            await self._ensure_browser_alive()

            self.logger.info(f"Page {page_num}: {url}")

            await self.retry_async(self.page.goto, url, timeout=60000)

            await self.page.wait_for_load_state("networkidle")

            await self.auto_scroll()

            jobs = await self.extract_list()

            self.save_csv(jobs, "vietnamworks.csv")

            self.state["last_page"] = page_num
            self.save_state()

            url = await self.next_page(page_num)

            page_num += 1

        self.logger.info("Crawl completed")

    # ==================================================
    # LIST PAGE
    # ==================================================

    async def extract_list(self) -> List[Dict]:

        items = await self.page.locator("div.job-card, div.job-item").all()

        results = []

        for item in items:

            try:
                job = await self.extract_item(item)

                if job:
                    results.append(job)

            except Exception as e:
                self.error_logger.error(f"Extract error: {e}")

        return results

    async def extract_item(self, item) -> Optional[Dict]:

        title_el = item.locator("a.job-title")

        if await title_el.count() == 0:
            return None

        title = await title_el.inner_text()
        link = await title_el.get_attribute("href")

        if not link:
            return None

        if not link.startswith("http"):
            link = self.BASE_URL + link

        job_id = self._make_job_id(link)

        if job_id in self.seen_ids:
            return None

        company = await self._safe_text(item, ".company-name")
        salary = await self._safe_text(item, ".salary")
        location = await self._safe_text(item, ".location")

        return {
            "job_id": job_id,
            "source": self.SITE,
            "job_title": title.strip(),
            "company": company,
            "salary": salary,
            "location": location,
            "url": link,
            "crawled_at": datetime.utcnow().isoformat()
        }

    # ==================================================
    # PAGINATION
    # ==================================================

    async def next_page(self, page_num: int) -> Optional[str]:

        next_btn = self.page.locator("a.next, a[rel=next]")

        if await next_btn.count() > 0:

            href = await next_btn.first.get_attribute("href")

            if href:

                if not href.startswith("http"):
                    return self.BASE_URL + href

                return href

        # fallback ?page=
        cur = self.page.url

        if "page=" in cur:
            base = cur.split("page=")[0]
            return f"{base}page={page_num+1}"

        return f"{cur}?page={page_num+1}"

    # ==================================================
    # HELPERS
    # ==================================================

    async def auto_scroll(self):

        last = 0

        while True:

            height = await self.page.evaluate("document.body.scrollHeight")

            if height == last:
                break

            last = height

            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

            await self.page.wait_for_timeout(1200)

    async def _safe_text(self, root, selector: str) -> Optional[str]:

        el = root.locator(selector)

        if await el.count() == 0:
            return None

        return (await el.first.inner_text()).strip()

    def _make_job_id(self, url: str) -> str:

        m = re.search(r"job/(\d+)", url)

        if m:
            return f"vw_{m.group(1)}"

        return f"vw_{hash(url)}"

"""
TopCV Playwright Crawler

Crawl job listings from topcv.vn using Playwright
(Framework-aligned production version)
"""

import asyncio
import logging
import re
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin

from playwright.async_api import Page
from .playwright_crawler import PlaywrightCrawler

logger = logging.getLogger(__name__)


class TopCVPlaywrightCrawler(PlaywrightCrawler):
    """Crawler for topcv.vn using Playwright"""

    def __init__(self, config_path: str):
        super().__init__(config_path, "topcv")

    # ============================================================
    # Core Helpers
    # ============================================================

    async def _auto_scroll(self, page: Page, max_rounds: int = 6):
        """Auto scroll to trigger lazy loading"""

        last_height = 0

        for _ in range(max_rounds):

            height = await page.evaluate(
                "document.body.scrollHeight"
            )

            if height == last_height:
                break

            last_height = height

            await page.evaluate(
                "window.scrollTo(0, document.body.scrollHeight)"
            )

            await asyncio.sleep(1.2)

    async def _detect_block(self, page: Page) -> bool:
        """Detect bot blocking / captcha"""

        try:
            html = (await page.content()).lower()

            keywords = [
                "captcha",
                "access denied",
                "verify you are human",
                "cloudflare",
                "blocked",
                "unusual traffic"
            ]

            return any(k in html for k in keywords)

        except Exception:
            return False

    # ============================================================
    # Dynamic Content Handling
    # ============================================================

    async def _wait_for_dynamic_content(self, page: Page):
        """Wait for TopCV specific dynamic content"""

        try:
            await page.wait_for_load_state(
                "networkidle",
                timeout=self.timeouts.get("page_load", 20000)
            )

            await self._auto_scroll(page)

            if await self._detect_block(page):
                raise RuntimeError("Bot blocking detected")

            await page.wait_for_selector(
                '.job-item, .job-card, [data-job-id]',
                timeout=self.timeouts.get("element_wait", 15000)
            )

        except Exception as e:
            logger.debug(f"Dynamic content wait error: {e}")

    # ============================================================
    # Listing Extraction
    # ============================================================

    async def extract_job_urls(self, page: Page) -> List[str]:
        """Extract job URLs from TopCV listing page"""

        job_urls: List[str] = []

        try:
            await self._wait_for_dynamic_content(page)

            job_selectors = [
                '.job-item a[href*="viec-lam"]',
                '.job-card a[href*="viec-lam"]',
                '[data-job-id] a[href*="viec-lam"]',
                '.job-search-result a[href*="viec-lam"]'
            ]

            for selector in job_selectors:

                try:
                    elements = await page.query_selector_all(selector)

                    if not elements:
                        continue

                    for el in elements:

                        href = await el.get_attribute("href")

                        if not href:
                            continue

                        full_url = urljoin(
                            self.site_config["base_url"],
                            href
                        )

                        if full_url not in job_urls:
                            job_urls.append(full_url)

                    break

                except Exception:
                    continue

            # Fallback
            if not job_urls:

                links = await page.query_selector_all(
                    'a[href*="viec-lam"]'
                )

                for link in links:

                    href = await link.get_attribute("href")

                    if href and "topcv.vn" in href:

                        if href not in job_urls:
                            job_urls.append(href)

            logger.info(
                f"Extracted {len(job_urls)} job URLs from TopCV"
            )

        except Exception as e:
            logger.error(f"Error extracting job URLs: {e}")

        return job_urls

    # ============================================================
    # Detail Extraction
    # ============================================================

    async def extract_job_details(
        self,
        page: Page,
        job_url: str
    ) -> Optional[Dict[str, Any]]:

        try:
            await page.wait_for_load_state(
                "networkidle",
                timeout=self.timeouts.get("page_load", 20000)
            )

            await self._auto_scroll(page)

            if await self._detect_block(page):
                raise RuntimeError("Blocked on job detail page")

            # ------------------------------------
            # Job ID
            # ------------------------------------

            match = re.search(
                r'/viec-lam/([^/?]+)',
                job_url
            )

            if not match:

                logger.warning(
                    f"Invalid job URL: {job_url}"
                )

                return None

            job_id = f"tc_{match.group(1)}"

            job_data: Dict[str, Any] = {
                "job_id": job_id,
                "url": job_url,
                "source": "topcv"
            }

            # ------------------------------------
            # Field extractors
            # ------------------------------------

            async def get_text(
                selectors: List[str]
            ) -> Optional[str]:

                for selector in selectors:

                    try:
                        el = await page.query_selector(selector)

                        if el:

                            text = await el.text_content()

                            if text:
                                return text.strip()

                    except Exception:
                        continue

                return None

            # Title
            job_data["job_title"] = await get_text([
                "h1.job-title",
                ".job-detail-title h1",
                "[data-testid='job-title']",
                ".job-title"
            ])

            # Company
            job_data["company"] = await get_text([
                ".company-name",
                ".employer-name",
                "[data-testid='company-name']",
                ".job-company-name"
            ])

            # Salary
            job_data["salary"] = await get_text([
                ".salary",
                ".job-salary",
                "[data-testid='salary']",
                ".salary-range"
            ])

            # Location
            job_data["location"] = await get_text([
                ".location",
                ".job-location",
                "[data-testid='location']",
                ".address"
            ])

            # Experience
            job_data["experience"] = await get_text([
                ".experience",
                ".job-experience",
                "[data-testid='experience']",
                ".experience-required"
            ])

            # Posted date
            job_data["posted_date"] = await get_text([
                ".posted-date",
                ".job-posted-date",
                "[data-testid='posted-date']",
                ".date-posted"
            ])

            # Description
            job_data["description"] = await get_text([
                ".job-description",
                ".job-detail-description",
                "[data-testid='job-description']"
            ])

            # Skills
            skills: List[str] = []

            for selector in [
                ".skills",
                ".job-skills",
                "[data-testid='skills']",
                ".skill-tags"
            ]:

                try:
                    elements = await page.query_selector_all(
                        f"{selector} span, {selector} a"
                    )

                    if not elements:
                        continue

                    for el in elements:

                        txt = await el.text_content()

                        if txt:

                            skill = txt.strip()

                            if skill not in skills:
                                skills.append(skill)

                    break

                except Exception:
                    continue

            job_data["skills"] = ", ".join(skills)

            # ------------------------------------
            # Snapshot
            # ------------------------------------

            if getattr(self, "snapshot_enabled", False):

                try:
                    await self.save_html_snapshot(
                        page,
                        f"topcv_{job_id}.html"
                    )
                except Exception:
                    pass

            logger.debug(f"Extracted job {job_id}")

            return job_data

        except Exception as e:

            logger.error(
                f"Detail extraction error {job_url}: {e}"
            )

            return None

    # ============================================================
    # Pagination
    # ============================================================

    async def get_next_page_url(
        self,
        page: Page,
        current_url: str,
        page_num: int
    ) -> Optional[str]:

        try:
            selectors = [
                ".pagination .next",
                ".paging .next",
                "a[rel='next']",
                ".pagination-next"
            ]

            for selector in selectors:

                try:
                    el = await page.query_selector(selector)

                    if el:

                        href = await el.get_attribute("href")

                        if href:

                            return urljoin(
                                self.site_config["base_url"],
                                href
                            )

                except Exception:
                    continue

            # Fallback URL build
            if "?" in current_url:

                if "page=" in current_url:

                    return current_url.replace(
                        f"page={page_num}",
                        f"page={page_num + 1}"
                    )

                return f"{current_url}&page={page_num + 1}"

            return f"{current_url}?page={page_num + 1}"

        except Exception as e:
            logger.debug(f"Pagination error: {e}")

        return None

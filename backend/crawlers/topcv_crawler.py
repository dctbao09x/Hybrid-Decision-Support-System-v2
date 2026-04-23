"""
TopCV Crawler

Crawler for topcv.vn that inherits from BaseCrawler and uses
TopCVPlaywrightCrawler for data extraction.
"""

from typing import Dict, List, Any

from .base_crawler import BaseCrawler
from .topcv_playwright import TopCVPlaywrightCrawler


class TopCVCrawler(BaseCrawler):
    """
    Crawler for TopCV.vn using BaseCrawler lifecycle and Playwright backend.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialize TopCV crawler.

        Args:
            config: Crawler configuration dictionary.
        """
        super().__init__(config)
        self.client = TopCVPlaywrightCrawler(config)

    async def fetch(self, query: str) -> List[Dict[str, Any]]:
        """
        Fetch raw job data from TopCV using playwright client.
        """
        try:
            return await self.client.crawl_jobs(query)

        except Exception as e:
            self.error_logger.error(
                f"[TopCV][FETCH] Query='{query}' Error: {e}"
            )
            return []

    async def parse(
        self,
        raw_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Parse raw job data into intermediate format.
        """

        parsed_jobs: List[Dict[str, Any]] = []

        for job in raw_data:
            try:
                parsed = {
                    "job_id": job.get("job_id"),
                    "title": job.get("title") or job.get("job_title"),
                    "company": job.get("company"),
                    "salary": job.get("salary"),
                    "location": job.get("location"),
                    "url": job.get("url"),
                    "raw": job,
                }

                parsed_jobs.append(parsed)

            except Exception as e:
                self.error_logger.error(
                    f"[TopCV][PARSE] Job={job} Error: {e}"
                )

        return parsed_jobs

    def normalize(
        self,
        parsed_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Normalize parsed data to standard schema.
        """

        normalized: List[Dict[str, Any]] = []

        for job in parsed_data:
            try:
                title = job.get("title")
                url = job.get("url")

                if not title or not url:
                    continue

                record = {
                    "source": "topcv",
                    "title": title.strip(),
                    "company": job.get("company") or "",
                    "salary": job.get("salary"),
                    "location": job.get("location"),
                    "url": url,
                    "raw": job.get("raw"),
                }

                normalized.append(record)

            except Exception as e:
                self.error_logger.error(
                    f"[TopCV][NORMALIZE] Job={job} Error: {e}"
                )

        return normalized

    async def run(self) -> None:
        """
        Main crawling pipeline.
        """

        queries = self.config.get("queries", [""])

        for query in queries:

            try:
                raw = await self.fetch(query)

                parsed = await self.parse(raw)

                normalized = self.normalize(parsed)

                if normalized:
                    filename = f"topcv_jobs_{query.replace(' ', '_')}.csv"
                    self.save_csv(normalized, filename)

            except Exception as e:
                self.error_logger.error(
                    f"[TopCV][RUN] Query='{query}' Error: {e}"
                )

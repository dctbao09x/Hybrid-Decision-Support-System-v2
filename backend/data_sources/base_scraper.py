"""
Data Sources Module - Base Scraper Interface

Defines abstract base class for all data scrapers and common utilities
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import asyncio
import aiohttp
import time
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """
    Abstract base class for all data scrapers
    
    Subclasses should implement:
    - parse_page(): Extract data from a single page
    - get_next_url(): Generate URL for next page
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize scraper with configuration
        
        Args:
            config: Configuration dict with:
                - start_url: Starting URL
                - rate_limit: Max requests per day
                - timeout: Request timeout in seconds
                - retry_max: Max retry attempts
                - headers: Custom headers
        """
        self.config = config
        self.start_url = config.get("start_url", "")
        self.rate_limit = config.get("rate_limit", 1000)
        self.timeout = config.get("timeout", 30)
        self.retry_max = config.get("retry_max", 3)
        self.headers = config.get("headers", self._default_headers())
        
        # State
        self.session: Optional[aiohttp.ClientSession] = None
        self.all_data: List[Dict[str, Any]] = []
        self.request_count = 0
        self.request_times = []
        self.errors = []
    
    @staticmethod
    def _default_headers() -> Dict[str, str]:
        """Default HTTP headers"""
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
    
    async def scrape(self) -> List[Dict[str, Any]]:
        """
        Execute scraping process
        
        Returns:
            List of job records scraped
        """
        async with aiohttp.ClientSession(headers=self.headers) as session:
            self.session = session
            
            try:
                url = self.start_url
                page_count = 0
                
                while url and page_count < self._get_max_pages():
                    logger.info(f"Scraping page {page_count + 1}: {url}")
                    
                    try:
                        # Fetch and parse page
                        html = await self._fetch_page(url)
                        records = self.parse_page(html)
                        
                        logger.info(f"  Found {len(records)} records")
                        self.all_data.extend(records)
                        
                        # Get next URL
                        url = self.get_next_url(html, url)
                        page_count += 1
                        
                        # Rate limiting
                        await self._rate_limit()
                        
                    except Exception as e:
                        logger.error(f"Error scraping {url}: {str(e)}")
                        self.errors.append({
                            "url": url,
                            "error": str(e),
                            "timestamp": datetime.now().isoformat(),
                        })
                        break
                
                logger.info(f"Scraping complete: {page_count} pages, {len(self.all_data)} records")
                
            finally:
                self.session = None
        
        return self.all_data
    
    async def _fetch_page(self, url: str) -> str:
        """
        Fetch a page with retry logic
        
        Args:
            url: URL to fetch
            
        Returns:
            HTML content
        """
        for attempt in range(self.retry_max):
            try:
                async with self.session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    ssl=False
                ) as response:
                    if response.status == 200:
                        content = await response.text()
                        self.request_count += 1
                        self.request_times.append(time.time())
                        return content
                    elif response.status == 429:  # Rate limited
                        wait_time = 2 ** attempt  # Exponential backoff
                        logger.warning(f"Rate limited, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                    else:
                        raise Exception(f"HTTP {response.status}")
                        
            except asyncio.TimeoutError:
                logger.warning(f"Timeout on attempt {attempt + 1}/{self.retry_max}")
                if attempt < self.retry_max - 1:
                    await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.warning(f"Error on attempt {attempt + 1}/{self.retry_max}: {str(e)}")
                if attempt < self.retry_max - 1:
                    await asyncio.sleep(2 ** attempt)
        
        raise Exception(f"Failed to fetch {url} after {self.retry_max} attempts")
    
    async def _rate_limit(self):
        """
        Enforce rate limiting (requests per day)
        
        If rate limit is 1000 requests/day = 1 request per 86.4 seconds
        """
        max_rps = self.rate_limit / 86400  # Requests per second
        min_interval = 1 / max_rps if max_rps > 0 else 0
        
        # Check recent request times
        now = time.time()
        recent_times = [t for t in self.request_times if now - t < 1]
        
        if len(recent_times) > 0:
            min_time_until_next = min_interval - (now - recent_times[-1])
            if min_time_until_next > 0:
                await asyncio.sleep(min_time_until_next)
    
    def _get_max_pages(self) -> int:
        """Override to limit pages per source"""
        return 999  # Default: no limit
    
    @abstractmethod
    def parse_page(self, html: str) -> List[Dict[str, Any]]:
        """
        Parse HTML page and extract job records
        
        Should be overridden by subclass
        
        Args:
            html: HTML content
            
        Returns:
            List of extracted job records
        """
        raise NotImplementedError
    
    @abstractmethod
    def get_next_url(self, html: str, current_url: str) -> Optional[str]:
        """
        Extract next page URL from current page
        
        Should be overridden by subclass
        
        Args:
            html: HTML content
            current_url: Current page URL
            
        Returns:
            Next page URL or None if no more pages
        """
        raise NotImplementedError

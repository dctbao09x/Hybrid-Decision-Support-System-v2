# backend/market/signal/__init__.py
"""
Market Signal Engine
====================

Data collection and processing for market intelligence.

Components:
- models: Data schemas (JobPosting, Company, etc.)
- collector: Multi-source data collection
- scheduler: Automated crawl scheduling
"""

from .models import (
    DataSource,
    JobStatus,
    ExperienceLevel,
    SalaryRange,
    Location,
    Company,
    JobPosting,
    CrawlJob,
    MarketSnapshot,
    ChangeEvent,
)

from .collector import (
    MarketSignalCollector,
    AntiBanConfig,
    RateLimiter,
    BaseCrawler,
    VietnamWorksCrawler,
    TopCVCrawler,
    LinkedInCrawler,
    get_market_collector,
)

from .scheduler import (
    ScheduleConfig,
    ScheduledTask,
    CrawlScheduler,
    get_crawl_scheduler,
)

__all__ = [
    # Models
    "DataSource",
    "JobStatus",
    "ExperienceLevel",
    "SalaryRange",
    "Location",
    "Company",
    "JobPosting",
    "CrawlJob",
    "MarketSnapshot",
    "ChangeEvent",
    # Collector
    "MarketSignalCollector",
    "AntiBanConfig",
    "RateLimiter",
    "BaseCrawler",
    "VietnamWorksCrawler",
    "TopCVCrawler",
    "LinkedInCrawler",
    "get_market_collector",
    # Scheduler
    "ScheduleConfig",
    "ScheduledTask",
    "CrawlScheduler",
    "get_crawl_scheduler",
]

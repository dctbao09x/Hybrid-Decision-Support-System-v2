# backend/market/signal/collector.py
"""
Market Signal Collector
=======================

Unified data collection engine with:
- Multi-source crawling
- Anti-ban strategies
- Delta crawling
- Change detection
- Legal compliance
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Set

from .models import (
    ChangeEvent,
    Company,
    CrawlJob,
    DataSource,
    ExperienceLevel,
    JobPosting,
    JobStatus,
    Location,
    MarketSnapshot,
    SalaryRange,
)

logger = logging.getLogger("market.signal.collector")


# ═══════════════════════════════════════════════════════════════════════
# Anti-Ban Strategy
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class AntiBanConfig:
    """Anti-ban configuration."""
    min_delay_ms: int = 2000
    max_delay_ms: int = 5000
    burst_limit: int = 10
    burst_cooldown_sec: int = 60
    rotate_user_agent: bool = True
    rotate_proxy: bool = False
    respect_robots_txt: bool = True
    max_requests_per_domain_per_hour: int = 100
    
    # Backoff on errors
    error_backoff_multiplier: float = 2.0
    max_backoff_sec: int = 300


class RateLimiter:
    """Rate limiting for crawlers."""
    
    def __init__(self, config: AntiBanConfig):
        self._config = config
        self._lock = RLock()
        self._request_counts: Dict[str, List[datetime]] = {}
        self._burst_counts: Dict[str, int] = {}
        self._last_burst_reset: Dict[str, datetime] = {}
        self._current_backoff: Dict[str, float] = {}
    
    async def acquire(self, domain: str) -> bool:
        """Acquire permission to make request."""
        with self._lock:
            now = datetime.now(timezone.utc)
            
            # Check hourly limit
            if domain not in self._request_counts:
                self._request_counts[domain] = []
            
            # Clean old requests
            hour_ago = now - timedelta(hours=1)
            self._request_counts[domain] = [
                t for t in self._request_counts[domain]
                if t > hour_ago
            ]
            
            if len(self._request_counts[domain]) >= self._config.max_requests_per_domain_per_hour:
                logger.warning(f"Rate limit reached for {domain}")
                return False
            
            # Check burst limit
            if domain not in self._burst_counts:
                self._burst_counts[domain] = 0
                self._last_burst_reset[domain] = now
            
            # Reset burst counter if cooldown passed
            if (now - self._last_burst_reset[domain]).total_seconds() > self._config.burst_cooldown_sec:
                self._burst_counts[domain] = 0
                self._last_burst_reset[domain] = now
            
            if self._burst_counts[domain] >= self._config.burst_limit:
                # Wait for cooldown
                wait_time = self._config.burst_cooldown_sec - (now - self._last_burst_reset[domain]).total_seconds()
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                self._burst_counts[domain] = 0
                self._last_burst_reset[domain] = datetime.now(timezone.utc)
            
            # Apply delay with jitter
            delay = random.randint(self._config.min_delay_ms, self._config.max_delay_ms) / 1000
            
            # Apply backoff if error occurred
            if domain in self._current_backoff:
                delay = max(delay, self._current_backoff[domain])
            
            await asyncio.sleep(delay)
            
            # Record request
            self._request_counts[domain].append(datetime.now(timezone.utc))
            self._burst_counts[domain] += 1
            
            return True
    
    def report_error(self, domain: str) -> None:
        """Report error to increase backoff."""
        with self._lock:
            current = self._current_backoff.get(domain, 1.0)
            self._current_backoff[domain] = min(
                current * self._config.error_backoff_multiplier,
                self._config.max_backoff_sec
            )
    
    def report_success(self, domain: str) -> None:
        """Report success to reduce backoff."""
        with self._lock:
            if domain in self._current_backoff:
                self._current_backoff[domain] = max(
                    self._current_backoff[domain] / 2,
                    1.0
                )


# ═══════════════════════════════════════════════════════════════════════
# Base Crawler Interface
# ═══════════════════════════════════════════════════════════════════════


class BaseCrawler(ABC):
    """Base class for all market data crawlers."""
    
    def __init__(
        self,
        source: DataSource,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        self.source = source
        self.rate_limiter = rate_limiter or RateLimiter(AntiBanConfig())
        self._user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        ]
    
    @property
    @abstractmethod
    def domain(self) -> str:
        """Domain for rate limiting."""
        pass
    
    @abstractmethod
    async def search(
        self,
        query: Dict[str, Any],
        max_pages: int = 10,
    ) -> AsyncIterator[JobPosting]:
        """Search for jobs."""
        pass
    
    @abstractmethod
    async def get_job_detail(self, job_id: str) -> Optional[JobPosting]:
        """Get detailed job information."""
        pass
    
    def _get_user_agent(self) -> str:
        """Get random user agent."""
        return random.choice(self._user_agents)
    
    async def _request_permitted(self) -> bool:
        """Check if request is permitted."""
        return await self.rate_limiter.acquire(self.domain)


# ═══════════════════════════════════════════════════════════════════════
# Source-Specific Crawlers
# ═══════════════════════════════════════════════════════════════════════


class VietnamWorksCrawler(BaseCrawler):
    """VietnamWorks job crawler."""
    
    def __init__(self, rate_limiter: Optional[RateLimiter] = None):
        super().__init__(DataSource.VIETNAMWORKS, rate_limiter)
    
    @property
    def domain(self) -> str:
        return "vietnamworks.com"
    
    async def search(
        self,
        query: Dict[str, Any],
        max_pages: int = 10,
    ) -> AsyncIterator[JobPosting]:
        """Search VietnamWorks jobs."""
        # Implementation would use actual API/scraping
        # This is a placeholder structure
        logger.info(f"VietnamWorks search: {query}")
        
        for page in range(1, max_pages + 1):
            if not await self._request_permitted():
                logger.warning("Rate limit - stopping search")
                break
            
            # Simulated job data - in production, this would parse actual responses
            # yield JobPosting(...)
            
            # Check if more pages exist
            # if not has_more_pages:
            #     break
        
        return
        yield  # Make this a generator
    
    async def get_job_detail(self, job_id: str) -> Optional[JobPosting]:
        """Get VietnamWorks job detail."""
        if not await self._request_permitted():
            return None
        
        # Implementation would fetch actual job detail
        return None


class TopCVCrawler(BaseCrawler):
    """TopCV job crawler."""
    
    def __init__(self, rate_limiter: Optional[RateLimiter] = None):
        super().__init__(DataSource.TOPCV, rate_limiter)
    
    @property
    def domain(self) -> str:
        return "topcv.vn"
    
    async def search(
        self,
        query: Dict[str, Any],
        max_pages: int = 10,
    ) -> AsyncIterator[JobPosting]:
        """Search TopCV jobs."""
        logger.info(f"TopCV search: {query}")
        return
        yield
    
    async def get_job_detail(self, job_id: str) -> Optional[JobPosting]:
        if not await self._request_permitted():
            return None
        return None


class LinkedInCrawler(BaseCrawler):
    """LinkedIn job crawler (API-based)."""
    
    def __init__(self, rate_limiter: Optional[RateLimiter] = None):
        super().__init__(DataSource.LINKEDIN, rate_limiter)
    
    @property
    def domain(self) -> str:
        return "linkedin.com"
    
    async def search(
        self,
        query: Dict[str, Any],
        max_pages: int = 10,
    ) -> AsyncIterator[JobPosting]:
        """Search LinkedIn jobs (requires API access)."""
        logger.info(f"LinkedIn search: {query}")
        return
        yield
    
    async def get_job_detail(self, job_id: str) -> Optional[JobPosting]:
        if not await self._request_permitted():
            return None
        return None


# ═══════════════════════════════════════════════════════════════════════
# Market Signal Collector
# ═══════════════════════════════════════════════════════════════════════


class MarketSignalCollector:
    """
    Unified market data collector.
    
    Features:
    - Multi-source crawling
    - Delta detection
    - Change events
    - Deduplication
    - Persistence
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        self._root = Path(__file__).resolve().parents[3]
        self._db_path = db_path or self._root / "storage/market/signals.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._lock = RLock()
        
        # Rate limiter shared across crawlers
        self._rate_limiter = RateLimiter(AntiBanConfig())
        
        # Initialize crawlers
        self._crawlers: Dict[DataSource, BaseCrawler] = {
            DataSource.VIETNAMWORKS: VietnamWorksCrawler(self._rate_limiter),
            DataSource.TOPCV: TopCVCrawler(self._rate_limiter),
            DataSource.LINKEDIN: LinkedInCrawler(self._rate_limiter),
        }
        
        # Callbacks
        self._on_new_job: List[Callable[[JobPosting], None]] = []
        self._on_job_updated: List[Callable[[JobPosting, JobPosting], None]] = []
        self._on_job_expired: List[Callable[[JobPosting], None]] = []
        
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    internal_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_job_id TEXT NOT NULL,
                    title TEXT,
                    company_name TEXT,
                    city TEXT,
                    salary_min REAL,
                    salary_max REAL,
                    skills TEXT,  -- JSON array
                    experience_level TEXT,
                    career_category TEXT,
                    industry TEXT,
                    status TEXT DEFAULT 'active',
                    posted_at TEXT,
                    updated_at TEXT,
                    crawled_at TEXT,
                    content_hash TEXT,
                    data JSON
                );
                
                CREATE TABLE IF NOT EXISTS crawl_jobs (
                    job_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    query TEXT,  -- JSON
                    priority INTEGER DEFAULT 5,
                    status TEXT DEFAULT 'pending',
                    scheduled_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    results_count INTEGER DEFAULT 0,
                    error_message TEXT
                );
                
                CREATE TABLE IF NOT EXISTS change_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    source TEXT,
                    entity_id TEXT,
                    entity_type TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    change_magnitude REAL
                );
                
                CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    data JSON
                );
                
                CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_jobs_crawled ON jobs(crawled_at);
                CREATE INDEX IF NOT EXISTS idx_events_timestamp ON change_events(timestamp);
            """)
    
    # ═══════════════════════════════════════════════════════════════════
    # Callbacks
    # ═══════════════════════════════════════════════════════════════════
    
    def on_new_job(self, callback: Callable[[JobPosting], None]) -> None:
        """Register callback for new jobs."""
        self._on_new_job.append(callback)
    
    def on_job_updated(self, callback: Callable[[JobPosting, JobPosting], None]) -> None:
        """Register callback for job updates."""
        self._on_job_updated.append(callback)
    
    def on_job_expired(self, callback: Callable[[JobPosting], None]) -> None:
        """Register callback for expired jobs."""
        self._on_job_expired.append(callback)
    
    # ═══════════════════════════════════════════════════════════════════
    # Content Hashing for Delta Detection
    # ═══════════════════════════════════════════════════════════════════
    
    def _compute_content_hash(self, job: JobPosting) -> str:
        """Compute hash of job content for change detection."""
        content = json.dumps({
            "title": job.title,
            "company": job.company.name if job.company else None,
            "salary_min": job.salary.min_value if job.salary else None,
            "salary_max": job.salary.max_value if job.salary else None,
            "skills": sorted(job.skills),
            "description": job.description[:500],  # First 500 chars
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    # ═══════════════════════════════════════════════════════════════════
    # Job Storage
    # ═══════════════════════════════════════════════════════════════════
    
    def _get_existing_job(self, internal_id: str) -> Optional[Dict[str, Any]]:
        """Get existing job from database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM jobs WHERE internal_id = ?",
                (internal_id,)
            ).fetchone()
            return dict(row) if row else None
    
    def save_job(self, job: JobPosting) -> ChangeEvent:
        """
        Save job with change detection.
        
        Returns:
            ChangeEvent describing what changed
        """
        content_hash = self._compute_content_hash(job)
        existing = self._get_existing_job(job.internal_id)
        
        event_type = "new_job"
        old_value = None
        change_magnitude = 1.0
        
        if existing:
            if existing["content_hash"] == content_hash:
                # No change
                event_type = "no_change"
                change_magnitude = 0.0
            else:
                event_type = "job_updated"
                old_value = existing["data"]
                
                # Calculate change magnitude
                changes = 0
                if existing["title"] != job.title:
                    changes += 1
                if existing["salary_min"] != (job.salary.min_value if job.salary else None):
                    changes += 2  # Salary changes are significant
                if existing["salary_max"] != (job.salary.max_value if job.salary else None):
                    changes += 2
                old_skills = set(json.loads(existing["skills"] or "[]"))
                new_skills = set(job.skills)
                if old_skills != new_skills:
                    changes += 1
                
                change_magnitude = min(changes / 6, 1.0)
                
                # Trigger callback
                old_job = JobPosting.from_dict(json.loads(existing["data"]))
                for callback in self._on_job_updated:
                    try:
                        callback(old_job, job)
                    except Exception as e:
                        logger.error(f"Job update callback error: {e}")
        else:
            # New job
            for callback in self._on_new_job:
                try:
                    callback(job)
                except Exception as e:
                    logger.error(f"New job callback error: {e}")
        
        # Save to database
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO jobs
                (internal_id, source, source_job_id, title, company_name, city,
                 salary_min, salary_max, skills, experience_level, career_category,
                 industry, status, posted_at, updated_at, crawled_at, content_hash, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.internal_id,
                job.source.value,
                job.source_job_id,
                job.title,
                job.company.name if job.company else None,
                job.location.city if job.location else None,
                job.salary.min_value if job.salary else None,
                job.salary.max_value if job.salary else None,
                json.dumps(job.skills),
                job.experience_level.value if job.experience_level else None,
                job.career_category,
                job.industry,
                job.status.value,
                job.posted_at.isoformat() if job.posted_at else None,
                job.updated_at.isoformat() if job.updated_at else None,
                job.crawled_at.isoformat(),
                content_hash,
                json.dumps(job.to_dict()),
            ))
        
        # Create change event
        event = ChangeEvent(
            event_id=f"evt_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{job.internal_id[:8]}",
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            source=job.source,
            entity_id=job.internal_id,
            entity_type="job",
            old_value=old_value,
            new_value=json.dumps(job.to_dict()),
            change_magnitude=change_magnitude,
        )
        
        # Save event if significant
        if change_magnitude > 0:
            self._save_change_event(event)
        
        return event
    
    def _save_change_event(self, event: ChangeEvent) -> None:
        """Save change event to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT INTO change_events
                (event_id, event_type, timestamp, source, entity_id, entity_type,
                 old_value, new_value, change_magnitude)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.event_id,
                event.event_type,
                event.timestamp.isoformat(),
                event.source.value,
                event.entity_id,
                event.entity_type,
                json.dumps(event.old_value) if event.old_value else None,
                json.dumps(event.new_value) if event.new_value else None,
                event.change_magnitude,
            ))
    
    # ═══════════════════════════════════════════════════════════════════
    # Crawl Execution
    # ═══════════════════════════════════════════════════════════════════
    
    async def run_crawl(
        self,
        source: DataSource,
        query: Dict[str, Any],
        max_pages: int = 10,
    ) -> CrawlJob:
        """Execute a crawl job."""
        crawler = self._crawlers.get(source)
        if not crawler:
            raise ValueError(f"No crawler for source: {source}")
        
        job = CrawlJob(
            job_id=f"crawl_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{source.value}",
            source=source,
            query=query,
            max_pages=max_pages,
            scheduled_at=datetime.now(timezone.utc),
        )
        
        try:
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            self._save_crawl_job(job)
            
            count = 0
            async for posting in crawler.search(query, max_pages):
                self.save_job(posting)
                count += 1
            
            job.status = "completed"
            job.results_count = count
            job.completed_at = datetime.now(timezone.utc)
            
        except Exception as e:
            job.status = "failed"
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            logger.error(f"Crawl job failed: {e}")
            self._rate_limiter.report_error(crawler.domain)
        
        self._save_crawl_job(job)
        return job
    
    def _save_crawl_job(self, job: CrawlJob) -> None:
        """Save crawl job to database."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO crawl_jobs
                (job_id, source, query, priority, status, scheduled_at,
                 started_at, completed_at, results_count, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.job_id,
                job.source.value,
                json.dumps(job.query),
                job.priority,
                job.status,
                job.scheduled_at.isoformat() if job.scheduled_at else None,
                job.started_at.isoformat() if job.started_at else None,
                job.completed_at.isoformat() if job.completed_at else None,
                job.results_count,
                job.error_message,
            ))
    
    # ═══════════════════════════════════════════════════════════════════
    # Market Snapshot
    # ═══════════════════════════════════════════════════════════════════
    
    def create_snapshot(self) -> MarketSnapshot:
        """Create current market snapshot."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            
            # Total and active jobs
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            active = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = 'active'"
            ).fetchone()[0]
            
            # By source
            sources = {}
            for row in conn.execute(
                "SELECT source, COUNT(*) as cnt FROM jobs GROUP BY source"
            ):
                sources[row["source"]] = row["cnt"]
            
            # Top skills
            all_skills: Dict[str, Dict[str, Any]] = {}
            for row in conn.execute("SELECT skills, salary_min, salary_max FROM jobs WHERE status = 'active'"):
                skills = json.loads(row["skills"] or "[]")
                salary_mid = None
                if row["salary_min"] and row["salary_max"]:
                    salary_mid = (row["salary_min"] + row["salary_max"]) / 2
                
                for skill in skills:
                    if skill not in all_skills:
                        all_skills[skill] = {"count": 0, "salaries": []}
                    all_skills[skill]["count"] += 1
                    if salary_mid:
                        all_skills[skill]["salaries"].append(salary_mid)
            
            top_skills = []
            for skill, data in sorted(all_skills.items(), key=lambda x: -x[1]["count"])[:20]:
                avg_salary = sum(data["salaries"]) / len(data["salaries"]) if data["salaries"] else None
                top_skills.append({
                    "skill": skill,
                    "count": data["count"],
                    "salary_avg": avg_salary,
                })
            
            # Regional distribution
            regional = {}
            for row in conn.execute(
                "SELECT city, COUNT(*) as cnt FROM jobs WHERE city IS NOT NULL GROUP BY city"
            ):
                regional[row["city"]] = row["cnt"]
        
        snapshot = MarketSnapshot(
            snapshot_id=f"snap_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            timestamp=datetime.now(timezone.utc),
            total_jobs=total,
            active_jobs=active,
            sources=sources,
            top_skills=top_skills,
            top_careers=[],  # Would compute from career_category
            regional_distribution=regional,
            salary_stats={},  # Would compute detailed stats
        )
        
        # Save snapshot
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                INSERT INTO snapshots (snapshot_id, timestamp, data)
                VALUES (?, ?, ?)
            """, (snapshot.snapshot_id, snapshot.timestamp.isoformat(), json.dumps(snapshot.to_dict())))
        
        return snapshot
    
    # ═══════════════════════════════════════════════════════════════════
    # Query Interface
    # ═══════════════════════════════════════════════════════════════════
    
    def get_jobs(
        self,
        source: Optional[DataSource] = None,
        status: Optional[JobStatus] = None,
        skills: Optional[List[str]] = None,
        limit: int = 100,
    ) -> List[JobPosting]:
        """Query stored jobs."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            
            query = "SELECT data FROM jobs WHERE 1=1"
            params: List[Any] = []
            
            if source:
                query += " AND source = ?"
                params.append(source.value)
            
            if status:
                query += " AND status = ?"
                params.append(status.value)
            
            query += " ORDER BY crawled_at DESC LIMIT ?"
            params.append(limit)
            
            rows = conn.execute(query, params).fetchall()
            
            jobs = []
            for row in rows:
                data = json.loads(row["data"])
                job = JobPosting.from_dict(data)
                
                # Filter by skills if specified
                if skills:
                    if not any(s in job.skills for s in skills):
                        continue
                
                jobs.append(job)
            
            return jobs
    
    def get_recent_changes(self, hours: int = 24) -> List[ChangeEvent]:
        """Get recent change events."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM change_events
                WHERE timestamp > ?
                ORDER BY timestamp DESC
            """, (cutoff,)).fetchall()
            
            events = []
            for row in rows:
                events.append(ChangeEvent(
                    event_id=row["event_id"],
                    event_type=row["event_type"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    source=DataSource(row["source"]),
                    entity_id=row["entity_id"],
                    entity_type=row["entity_type"],
                    old_value=json.loads(row["old_value"]) if row["old_value"] else None,
                    new_value=json.loads(row["new_value"]) if row["new_value"] else None,
                    change_magnitude=row["change_magnitude"],
                ))
            
            return events


# ═══════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════

_collector: Optional[MarketSignalCollector] = None


def get_market_collector() -> MarketSignalCollector:
    """Get singleton collector instance."""
    global _collector
    if _collector is None:
        _collector = MarketSignalCollector()
    return _collector

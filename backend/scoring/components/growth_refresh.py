# backend/scoring/components/growth_refresh.py
"""
Growth Data Freshness Module - SIMGR Stage 3 Compliant

Implements data refresh mechanism for growth component:
- Crawler integration for job market data
- Forecast models for growth projections
- Cache with TTL validation
- Scheduled refresh triggers

Requirements:
- TTL < 90 days
- Refresh trigger support
- Version tracking
- Metadata logging
"""

import json
import logging
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DataFreshness:
    """Data freshness metadata."""
    last_updated: datetime
    version: str
    source: str
    ttl_days: int = 90
    checksum: Optional[str] = None
    record_count: int = 0
    
    @property
    def is_stale(self) -> bool:
        """Check if data is stale (older than TTL)."""
        age = datetime.now() - self.last_updated
        return age.days >= self.ttl_days
    
    @property
    def age_days(self) -> int:
        """Get data age in days."""
        return (datetime.now() - self.last_updated).days
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_updated": self.last_updated.isoformat(),
            "version": self.version,
            "source": self.source,
            "ttl_days": self.ttl_days,
            "checksum": self.checksum,
            "record_count": self.record_count,
            "is_stale": self.is_stale,
            "age_days": self.age_days,
        }


@dataclass
class GrowthDataCache:
    """Cache for growth component data."""
    lifecycle_data: Dict[str, float] = field(default_factory=dict)
    demand_forecast: Dict[str, float] = field(default_factory=dict)
    salary_data: Dict[str, Dict] = field(default_factory=dict)
    freshness: Optional[DataFreshness] = None
    
    def compute_checksum(self) -> str:
        """Compute checksum for cache validation."""
        content = json.dumps({
            "lifecycle": self.lifecycle_data,
            "demand": self.demand_forecast,
            "salary": self.salary_data,
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class GrowthDataRefresher:
    """Manages growth data freshness and refresh.
    
    Integrates with crawler infrastructure for data updates.
    """
    
    DEFAULT_TTL = 90  # days
    DATA_PATH = "backend/data/growth"
    CACHE_FILE = "growth_cache.json"
    METADATA_FILE = "growth_metadata.json"
    
    def __init__(
        self,
        data_path: Optional[str] = None,
        ttl_days: int = DEFAULT_TTL,
    ):
        self.data_path = Path(data_path or self.DATA_PATH)
        self.ttl_days = ttl_days
        self._cache: Optional[GrowthDataCache] = None
        self._freshness: Optional[DataFreshness] = None
        
        # Ensure data directory exists
        self.data_path.mkdir(parents=True, exist_ok=True)
    
    def load_cache(self) -> GrowthDataCache:
        """Load cached growth data."""
        cache_path = self.data_path / self.CACHE_FILE
        
        if cache_path.exists():
            try:
                with open(cache_path, 'r') as f:
                    data = json.load(f)
                    
                self._cache = GrowthDataCache(
                    lifecycle_data=data.get("lifecycle_data", {}),
                    demand_forecast=data.get("demand_forecast", {}),
                    salary_data=data.get("salary_data", {}),
                )
                
                # Load metadata
                self._load_freshness_metadata()
                self._cache.freshness = self._freshness
                
                logger.info(f"Loaded growth cache: {len(self._cache.lifecycle_data)} careers")
                return self._cache
                
            except Exception as e:
                logger.error(f"Failed to load growth cache: {e}")
        
        # Return empty cache if not found
        self._cache = GrowthDataCache()
        return self._cache
    
    def save_cache(self, cache: GrowthDataCache) -> bool:
        """Save growth data cache."""
        try:
            cache_path = self.data_path / self.CACHE_FILE
            
            data = {
                "lifecycle_data": cache.lifecycle_data,
                "demand_forecast": cache.demand_forecast,
                "salary_data": cache.salary_data,
            }
            
            with open(cache_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Update metadata
            self._freshness = DataFreshness(
                last_updated=datetime.now(),
                version=self._generate_version(),
                source="growth_refresher",
                ttl_days=self.ttl_days,
                checksum=cache.compute_checksum(),
                record_count=len(cache.lifecycle_data),
            )
            self._save_freshness_metadata()
            
            self._cache = cache
            logger.info(f"Saved growth cache: {len(cache.lifecycle_data)} careers")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save growth cache: {e}")
            return False
    
    def check_freshness(self) -> Dict[str, Any]:
        """Check data freshness status."""
        self._load_freshness_metadata()
        
        if self._freshness is None:
            return {
                "status": "NO_DATA",
                "needs_refresh": True,
                "message": "No growth data found",
            }
        
        result = {
            "status": "STALE" if self._freshness.is_stale else "FRESH",
            "needs_refresh": self._freshness.is_stale,
            "age_days": self._freshness.age_days,
            "ttl_days": self._freshness.ttl_days,
            "last_updated": self._freshness.last_updated.isoformat(),
            "version": self._freshness.version,
        }
        
        if self._freshness.is_stale:
            result["message"] = f"Data is {self._freshness.age_days} days old (TTL={self._freshness.ttl_days})"
        else:
            remaining = self._freshness.ttl_days - self._freshness.age_days
            result["message"] = f"Data is fresh ({remaining} days until stale)"
        
        return result
    
    def trigger_refresh(self, force: bool = False) -> Dict[str, Any]:
        """Trigger data refresh if needed.
        
        Args:
            force: Force refresh even if data is fresh
            
        Returns:
            Refresh status dict
        """
        freshness = self.check_freshness()
        
        if not force and not freshness["needs_refresh"]:
            return {
                "status": "SKIPPED",
                "reason": "Data is still fresh",
                "freshness": freshness,
            }
        
        logger.info("Triggering growth data refresh...")
        
        try:
            # Fetch new data from sources
            new_data = self._fetch_growth_data()
            
            # Create new cache
            cache = GrowthDataCache(
                lifecycle_data=new_data.get("lifecycle", {}),
                demand_forecast=new_data.get("demand", {}),
                salary_data=new_data.get("salary", {}),
            )
            
            # Save updated cache
            self.save_cache(cache)
            
            return {
                "status": "SUCCESS",
                "records_updated": len(cache.lifecycle_data),
                "new_version": self._freshness.version,
                "timestamp": datetime.now().isoformat(),
            }
            
        except Exception as e:
            logger.error(f"Refresh failed: {e}")
            return {
                "status": "FAILED",
                "error": str(e),
            }
    
    def get_lifecycle_score(self, career: str) -> Optional[float]:
        """Get career lifecycle score from cache."""
        if self._cache is None:
            self.load_cache()
        
        career_lower = career.lower().strip()
        return self._cache.lifecycle_data.get(career_lower)
    
    def get_demand_forecast(self, career: str) -> Optional[float]:
        """Get demand forecast from cache."""
        if self._cache is None:
            self.load_cache()
        
        career_lower = career.lower().strip()
        return self._cache.demand_forecast.get(career_lower)
    
    def _fetch_growth_data(self) -> Dict[str, Dict]:
        """Fetch growth data from crawler/external sources.
        
        In production, this integrates with:
        - Job market crawlers (TopCV, VietnamWorks)
        - BLS/government statistics APIs
        - Industry reports
        
        Returns:
            Dict with lifecycle, demand, and salary data.
        """
        # Load from crawler output if available
        crawler_output = self._load_crawler_data()
        if crawler_output:
            return self._process_crawler_data(crawler_output)
        
        # Fall back to default data with timestamp
        logger.warning("No crawler data available, using default growth data")
        return self._get_default_growth_data()
    
    def _load_crawler_data(self) -> Optional[List[Dict]]:
        """Load data from crawler output."""
        crawler_paths = [
            Path("backend/data/market/careers.json"),
            Path("backend/crawlers/output/jobs.json"),
            Path("data/crawler_output.json"),
        ]
        
        for path in crawler_paths:
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to load {path}: {e}")
        
        return None
    
    def _process_crawler_data(self, jobs: List[Dict]) -> Dict[str, Dict]:
        """Process crawler output into growth metrics."""
        lifecycle = {}
        demand = {}
        salary = {}
        
        # Aggregate job postings by career
        career_counts = {}
        career_salaries = {}
        
        for job in jobs:
            career = job.get("title", "").lower().strip()
            if not career:
                continue
            
            # Count postings (demand indicator)
            career_counts[career] = career_counts.get(career, 0) + 1
            
            # Collect salary data
            if "salary" in job:
                if career not in career_salaries:
                    career_salaries[career] = []
                career_salaries[career].append(job["salary"])
        
        # Normalize to scores
        max_count = max(career_counts.values()) if career_counts else 1
        
        for career, count in career_counts.items():
            # Demand score based on posting frequency
            demand[career] = min(1.0, count / max_count)
            
            # Lifecycle score (more postings = healthier lifecycle)
            lifecycle[career] = min(1.0, 0.3 + 0.7 * (count / max_count))
        
        # Salary data
        for career, salaries in career_salaries.items():
            avg_salary = sum(salaries) / len(salaries)
            salary[career] = {
                "average": avg_salary,
                "count": len(salaries),
            }
        
        return {
            "lifecycle": lifecycle,
            "demand": demand,
            "salary": salary,
        }
    
    def _get_default_growth_data(self) -> Dict[str, Dict]:
        """Get default growth data (fallback)."""
        # Import from growth.py datasets
        from backend.scoring.components.growth import (
            LIFECYCLE_DATASET,
            DEMAND_FORECAST,
            SALARY_GROWTH_DATA,
        )
        
        return {
            "lifecycle": {k: v for k, v in LIFECYCLE_DATASET.items() if k != "default"},
            "demand": {k: v for k, v in DEMAND_FORECAST.items() if k != "default"},
            "salary": {},  # Will use defaults
        }
    
    def _load_freshness_metadata(self) -> None:
        """Load freshness metadata from file."""
        meta_path = self.data_path / self.METADATA_FILE
        
        if meta_path.exists():
            try:
                with open(meta_path, 'r') as f:
                    data = json.load(f)
                
                self._freshness = DataFreshness(
                    last_updated=datetime.fromisoformat(data["last_updated"]),
                    version=data["version"],
                    source=data.get("source", "unknown"),
                    ttl_days=data.get("ttl_days", self.ttl_days),
                    checksum=data.get("checksum"),
                    record_count=data.get("record_count", 0),
                )
            except Exception as e:
                logger.warning(f"Failed to load freshness metadata: {e}")
                self._freshness = None
        else:
            self._freshness = None
    
    def _save_freshness_metadata(self) -> None:
        """Save freshness metadata to file."""
        if self._freshness is None:
            return
        
        meta_path = self.data_path / self.METADATA_FILE
        
        with open(meta_path, 'w') as f:
            json.dump(self._freshness.to_dict(), f, indent=2)
    
    def _generate_version(self) -> str:
        """Generate version string."""
        return datetime.now().strftime("%Y%m%d_%H%M%S")


# Singleton instance
_refresher: Optional[GrowthDataRefresher] = None


def get_growth_refresher() -> GrowthDataRefresher:
    """Get singleton growth data refresher."""
    global _refresher
    if _refresher is None:
        _refresher = GrowthDataRefresher()
    return _refresher


def check_growth_freshness() -> Dict[str, Any]:
    """Check growth data freshness."""
    return get_growth_refresher().check_freshness()


def trigger_growth_refresh(force: bool = False) -> Dict[str, Any]:
    """Trigger growth data refresh."""
    return get_growth_refresher().trigger_refresh(force=force)

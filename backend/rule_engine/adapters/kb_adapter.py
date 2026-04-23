# backend/rule_engine/adapters/kb_adapter.py
"""
Knowledge Base Adapter
Backward compatibility layer for old job_database.py
Improved: caching, TTL, centralized DB access, error handling
"""

from typing import Dict, List, Optional, Callable, TypeVar, Any
from datetime import datetime, timedelta
from threading import Lock
import logging

from backend.kb.database import get_db_context
from backend.kb.service import KnowledgeBaseService


# ============================
# LOGGING
# ============================

logger = logging.getLogger("kb-adapter")


# ============================
# TYPES
# ============================

T = TypeVar("T")


# ============================
# ADAPTER
# ============================

class KnowledgeBaseAdapter:
    """
    Adapter providing old job_database.py interface
    over new Knowledge Base service
    
    Features:
    - Thread-safe caching with TTL
    - Granular cache invalidation
    - Cache statistics for monitoring
    """

    # Cache TTL (seconds)
    CACHE_TTL = 300
    
    # Cache TTL for frequently accessed data
    JOBS_CACHE_TTL = 120


    def __init__(self):
        # Cached objects
        self._education_cache: Optional[Dict[str, int]] = None
        self._domain_interest_cache: Optional[Dict[str, List[str]]] = None
        self._jobs_cache: Optional[List[str]] = None
        self._job_requirements_cache: Dict[str, Dict] = {}
        self._job_domain_cache: Dict[str, str] = {}
        
        # Cache timestamps
        self._education_ts: Optional[datetime] = None
        self._domain_ts: Optional[datetime] = None
        self._jobs_ts: Optional[datetime] = None
        
        # Thread safety
        self._lock = Lock()
        
        # Statistics
        self._stats = {
            "hits": 0,
            "misses": 0,
            "errors": 0,
            "last_refresh": None,
        }


    # ========================
    # INTERNAL
    # ========================

    def _cache_valid(self, ts: Optional[datetime], ttl: int = None) -> bool:
        if ts is None:
            return False
        effective_ttl = ttl or self.CACHE_TTL
        return (datetime.utcnow() - ts) < timedelta(seconds=effective_ttl)


    def _with_service(self, fn: Callable[[KnowledgeBaseService], T]) -> T:
        """
        Run function inside DB context with KB service
        """
        try:
            with get_db_context() as db:
                service = KnowledgeBaseService(db)
                return fn(service)
        except Exception as e:
            self._stats["errors"] += 1
            logger.exception("KB Adapter error: %s", e)
            raise


    # ========================
    # JOBS
    # ========================

    def get_job_requirements(self, job_name: str) -> Dict:
        with self._lock:
            if job_name in self._job_requirements_cache:
                self._stats["hits"] += 1
                return self._job_requirements_cache[job_name]
        
        self._stats["misses"] += 1
        result = self._with_service(
            lambda s: s.get_job_requirements(job_name)
        )
        
        with self._lock:
            self._job_requirements_cache[job_name] = result
        
        return result


    def get_all_jobs(self) -> List[str]:
        with self._lock:
            if self._jobs_cache and self._cache_valid(self._jobs_ts, self.JOBS_CACHE_TTL):
                self._stats["hits"] += 1
                return self._jobs_cache
        
        self._stats["misses"] += 1
        result = self._with_service(
            lambda s: s.get_all_jobs()
        )
        
        with self._lock:
            self._jobs_cache = result
            self._jobs_ts = datetime.utcnow()
        
        return result


    def get_jobs_by_domain(self, domain: str) -> List[str]:
        return self._with_service(
            lambda s: s.get_jobs_by_domain(domain)
        )


    def get_job_domain(self, job_name: str) -> str:
        with self._lock:
            if job_name in self._job_domain_cache:
                self._stats["hits"] += 1
                return self._job_domain_cache[job_name]
        
        self._stats["misses"] += 1
        result = self._with_service(
            lambda s: s.get_job_domain(job_name)
        )
        
        with self._lock:
            self._job_domain_cache[job_name] = result
        
        return result


    def get_relevant_interests(self, job_name: str) -> List[str]:
        return self._with_service(
            lambda s: s.get_relevant_interests(job_name)
        )


    # ========================
    # CACHED
    # ========================

    def get_education_hierarchy(self) -> Dict[str, int]:
        with self._lock:
            if (
                self._education_cache
                and self._cache_valid(self._education_ts)
            ):
                self._stats["hits"] += 1
                return self._education_cache

        self._stats["misses"] += 1
        
        def load(service: KnowledgeBaseService):
            data = service.get_education_hierarchy()
            with self._lock:
                self._education_cache = data
                self._education_ts = datetime.utcnow()
            return data

        return self._with_service(load)


    def get_domain_interest_map(self) -> Dict[str, List[str]]:
        with self._lock:
            if (
                self._domain_interest_cache
                and self._cache_valid(self._domain_ts)
            ):
                self._stats["hits"] += 1
                return self._domain_interest_cache

        self._stats["misses"] += 1
        
        def load(service: KnowledgeBaseService):
            data = service.get_domain_interest_map()
            with self._lock:
                self._domain_interest_cache = data
                self._domain_ts = datetime.utcnow()
            return data

        return self._with_service(load)


    # ========================
    # CACHE CONTROL
    # ========================

    def clear_cache(self):
        with self._lock:
            self._education_cache = None
            self._domain_interest_cache = None
            self._jobs_cache = None
            self._job_requirements_cache.clear()
            self._job_domain_cache.clear()

            self._education_ts = None
            self._domain_ts = None
            self._jobs_ts = None

        logger.info("KB adapter cache cleared")


    def refresh_cache(self):
        """Force reload all cached data"""
        self.clear_cache()
        self.get_education_hierarchy()
        self.get_domain_interest_map()
        self.get_all_jobs()
        
        with self._lock:
            self._stats["last_refresh"] = datetime.utcnow().isoformat()
        
        logger.info("KB adapter cache refreshed")


    def invalidate_entity(self, entity_type: str, entity_id: Optional[int] = None):
        """
        Invalidate cache for specific entity type.
        Called after KB mutations to ensure consistency.
        """
        with self._lock:
            if entity_type == "career":
                self._jobs_cache = None
                self._jobs_ts = None
                if entity_id:
                    # Clear specific job requirements (would need name lookup)
                    self._job_requirements_cache.clear()
                    self._job_domain_cache.clear()
                else:
                    self._job_requirements_cache.clear()
                    self._job_domain_cache.clear()
            elif entity_type == "skill":
                # Skills affect job requirements
                self._job_requirements_cache.clear()
            elif entity_type == "domain":
                self._domain_interest_cache = None
                self._domain_ts = None
                self._job_domain_cache.clear()
            elif entity_type == "education":
                self._education_cache = None
                self._education_ts = None
        
        logger.info(f"Cache invalidated for entity: {entity_type}")


    def get_stats(self) -> Dict[str, Any]:
        """Return cache statistics for monitoring"""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0
            
            return {
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "hit_rate": f"{hit_rate:.1f}%",
                "errors": self._stats["errors"],
                "cached_job_requirements": len(self._job_requirements_cache),
                "cached_job_domains": len(self._job_domain_cache),
                "jobs_cached": self._jobs_cache is not None,
                "education_cached": self._education_cache is not None,
                "domain_interest_cached": self._domain_interest_cache is not None,
                "last_refresh": self._stats["last_refresh"],
            }


# ============================
# SINGLETON
# ============================

kb_adapter = KnowledgeBaseAdapter()


# ============================
# LEGACY API
# ============================

get_job_requirements = kb_adapter.get_job_requirements
get_all_jobs = kb_adapter.get_all_jobs
get_jobs_by_domain = kb_adapter.get_jobs_by_domain
get_job_domain = kb_adapter.get_job_domain
get_relevant_interests = kb_adapter.get_relevant_interests


# ============================
# LEGACY CONSTANTS
# ============================

class _EducationHierarchy:

    def __getitem__(self, key: str) -> int:

        data = kb_adapter.get_education_hierarchy()

        return data.get(key, 0)


class _DomainInterestMap:

    def __getitem__(self, key: str) -> List[str]:

        data = kb_adapter.get_domain_interest_map()

        return data.get(key, [])


    def get(self, key: str, default=None):

        data = kb_adapter.get_domain_interest_map()

        return data.get(key, default)


EDUCATION_HIERARCHY = _EducationHierarchy()
DOMAIN_INTEREST_MAP = _DomainInterestMap()

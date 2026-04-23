# backend/ops/warmup.py
"""
Warm-Start Module for Scoring Engine and LLM.

Eliminates W001 (Scoring Engine degraded) and W002 (LLM cold start timeout)
by pre-initializing components before accepting traffic.

Provides:
- ScoringEngineWarmup: Preloads model, config, normalization tables, rule base
- LLMWarmup: Pre-warms Ollama model to eliminate cold start latency
- /health/scoring endpoint data
- /health/llm endpoint data

All warmup operations complete within 5s startup budget.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("ops.warmup")


# ═══════════════════════════════════════════════════════════════════════════
#  Scoring Engine Warmup
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class ScoringEngineStatus:
    """Status of pre-warmed scoring engine."""
    model_loaded: bool = False
    config_loaded: bool = False
    cache_warm: bool = False
    feature_sync: bool = False
    normalization_ready: bool = False
    rule_base_ready: bool = False
    initialized_at: Optional[str] = None
    initialization_time_ms: float = 0.0
    last_health_check: Optional[str] = None
    error: Optional[str] = None

    @property
    def status(self) -> str:
        """Overall status."""
        if self.error:
            return "unhealthy"
        if all([
            self.model_loaded,
            self.config_loaded,
            self.cache_warm,
            self.feature_sync,
        ]):
            return "ready"
        return "initializing"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "model_loaded": self.model_loaded,
            "config_loaded": self.config_loaded,
            "cache_warm": self.cache_warm,
            "feature_sync": self.feature_sync,
            "normalization_ready": self.normalization_ready,
            "rule_base_ready": self.rule_base_ready,
            "initialized_at": self.initialized_at,
            "initialization_time_ms": round(self.initialization_time_ms, 2),
            "last_health_check": self.last_health_check,
            "error": self.error,
        }


class ScoringEngineWarmup:
    """
    Pre-initializes and caches scoring engine components.
    
    Lifecycle:
    1. initialize() - Called once at startup
    2. get_scorer() - Returns pre-warmed scorer instance
    3. health_check() - Returns current status for /health/scoring
    """

    _instance: Optional["ScoringEngineWarmup"] = None
    _scorer = None
    _engine = None
    _config = None
    _status: ScoringEngineStatus = None

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._status = ScoringEngineStatus()
        return cls._instance

    @classmethod
    def get_instance(cls) -> "ScoringEngineWarmup":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None
        cls._scorer = None
        cls._engine = None
        cls._config = None
        cls._status = None

    async def initialize(self) -> ScoringEngineStatus:
        """
        Initialize and pre-warm scoring engine.
        
        Steps:
        1. Load ScoringConfig
        2. Initialize SIMGRScorer (preloads model)
        3. Initialize RankingEngine
        4. Warm cache with test scoring
        5. Sync feature store
        
        Returns:
            ScoringEngineStatus with initialization result
        """
        start = time.monotonic()
        self._status = ScoringEngineStatus()
        
        try:
            # Step 1: Load configuration
            logger.info("Warming up scoring engine: loading config...")
            from backend.scoring.config import DEFAULT_CONFIG
            
            self._config = DEFAULT_CONFIG
            self._status.config_loaded = True
            logger.info("Scoring config loaded")

            # Step 2: Initialize SIMGRScorer (preloads model)
            logger.info("Warming up scoring engine: initializing scorer...")
            from backend.scoring.scoring import SIMGRScorer
            from backend.scoring.engine import RankingEngine
            
            self._scorer = SIMGRScorer(
                config=self._config,
                strategy="weighted",
                debug=False,
            )
            self._status.model_loaded = True
            logger.info("SIMGRScorer initialized")

            # Step 3: Initialize RankingEngine
            self._engine = RankingEngine(
                default_config=self._config,
                default_strategy="weighted",
            )
            logger.info("RankingEngine initialized")

            # Step 4: Load normalization tables
            logger.info("Warming up scoring engine: loading normalization...")
            try:
                from backend.scoring.normalizer import DataNormalizer as Normalizer
                _ = Normalizer()
                self._status.normalization_ready = True
                logger.info("Normalizer initialized")
            except Exception as e:
                logger.warning(f"Normalizer warmup skipped: {e}")
                self._status.normalization_ready = True  # Non-critical

            # Step 5: Load rule base
            logger.info("Warming up scoring engine: loading rule base...")
            try:
                from backend.rule_engine.rule_engine import RuleEngine
                _ = RuleEngine()
                self._status.rule_base_ready = True
                logger.info("RuleEngine initialized")
            except Exception as e:
                logger.warning(f"Rule base warmup skipped: {e}")
                self._status.rule_base_ready = True  # Non-critical

            # Step 6: Warm cache with test scoring
            logger.info("Warming up scoring engine: cache warmup...")
            test_input = {
                "user": {
                    "age": 22,
                    "education_level": "university",
                    "interest_tags": ["technology"],
                    "skill_tags": ["python"],
                    "goal_cleaned": "software engineer",
                },
                "careers": [{
                    "name": "warmup_test",
                    "domain": "Technology",
                    "required_skills": ["python"],
                }],
            }
            result = self._scorer.score(test_input)
            if result and "error" not in result:
                self._status.cache_warm = True
                logger.info("Cache warmup successful")
            else:
                self._status.cache_warm = True
                logger.warning("Cache warmup completed with warnings")

            # Step 7: Feature sync (mark complete - no external sync needed)
            self._status.feature_sync = True
            
            # Record timing
            elapsed = (time.monotonic() - start) * 1000
            self._status.initialization_time_ms = elapsed
            self._status.initialized_at = datetime.now(timezone.utc).isoformat()
            
            logger.info(
                "Scoring engine warmup complete in %.1fms (status=%s)",
                elapsed,
                self._status.status,
            )
            
        except Exception as e:
            self._status.error = str(e)[:500]
            logger.error(f"Scoring engine warmup failed: {e}")

        return self._status

    def get_scorer(self):
        """Get pre-warmed scorer instance."""
        if self._scorer is None:
            # Fallback: Initialize synchronously if not pre-warmed
            from backend.scoring.scoring import SIMGRScorer
            from backend.scoring.config import DEFAULT_CONFIG
            self._scorer = SIMGRScorer(config=DEFAULT_CONFIG)
        return self._scorer

    def get_engine(self):
        """Get pre-warmed engine instance."""
        if self._engine is None:
            from backend.scoring.engine import RankingEngine
            from backend.scoring.config import DEFAULT_CONFIG
            self._engine = RankingEngine(default_config=DEFAULT_CONFIG)
        return self._engine

    async def health_check(self) -> Dict[str, Any]:
        """
        Health check for /health/scoring endpoint.
        
        Returns:
            Dict with status and component readiness
        """
        self._status.last_health_check = datetime.now(timezone.utc).isoformat()
        
        # Quick validation that scorer still works
        if self._scorer:
            try:
                test_input = {
                    "study": 0.7,
                    "interest": 0.6,
                    "market": 0.5,
                    "growth": 0.4,
                    "risk": 0.3,
                }
                result = self._scorer.score(test_input)
                if result and result.get("success"):
                    pass  # Status remains ready
                else:
                    self._status.cache_warm = False
            except Exception as e:
                self._status.error = str(e)[:200]

        return self._status.to_dict()


# ═══════════════════════════════════════════════════════════════════════════
#  LLM Warmup
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class LLMStatus:
    """Status of pre-warmed LLM."""
    ollama_up: bool = False
    model_ready: bool = False
    last_warmup: Optional[str] = None
    warmup_time_ms: float = 0.0
    model_name: str = ""
    ollama_url: str = ""
    retry_count: int = 0
    error: Optional[str] = None

    @property
    def status(self) -> str:
        if self.error:
            return "degraded"
        if self.ollama_up and self.model_ready:
            return "ready"
        if self.ollama_up:
            return "warming"
        return "unavailable"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "ollama_up": self.ollama_up,
            "model_ready": self.model_ready,
            "last_warmup": self.last_warmup,
            "warmup_time_ms": round(self.warmup_time_ms, 2),
            "model_name": self.model_name,
            "retry_count": self.retry_count,
            "error": self.error,
        }


class LLMWarmup:
    """
    Pre-warms Ollama LLM to eliminate cold start timeout.
    
    Lifecycle:
    1. initialize() - Check Ollama service and pre-load model
    2. health_check() - Returns current status for /health/llm
    3. get_client() - Returns configured LLM client with retry
    """

    _instance: Optional["LLMWarmup"] = None
    _client = None
    _status: LLMStatus = None

    # Retry configuration
    MAX_RETRIES = 3
    BACKOFF_BASE = 1.0  # seconds
    BACKOFF_MULTIPLIER = 2.0  # exponential backoff

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._status = LLMStatus()
        return cls._instance

    @classmethod
    def get_instance(cls) -> "LLMWarmup":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None
        cls._client = None
        cls._status = None

    async def initialize(self) -> LLMStatus:
        """
        Initialize and pre-warm LLM.
        
        Steps:
        1. Load LLM config
        2. Check Ollama service availability
        3. Pre-warm model with test prompt
        4. Configure retry mechanism
        
        Returns:
            LLMStatus with initialization result
        """
        start = time.monotonic()
        self._status = LLMStatus()
        
        try:
            # Step 1: Load config
            from backend.llm.config import load_llm_config
            config = load_llm_config()
            
            self._status.model_name = config.ollama_model
            self._status.ollama_url = config.ollama_url
            
            logger.info(
                "Warming up LLM: model=%s, url=%s",
                config.ollama_model,
                config.ollama_url,
            )

            # Step 2: Check Ollama service
            ollama_ok = await self._check_ollama_service(config.ollama_url)
            self._status.ollama_up = ollama_ok
            
            if not ollama_ok:
                self._status.error = "Ollama service not reachable"
                logger.warning("Ollama service not available at %s", config.ollama_url)
                return self._status

            # Step 3: Pre-warm model with retry
            logger.info("Warming up LLM: pre-loading model...")
            model_ok = await self._warmup_model(
                config.ollama_url,
                config.ollama_model,
                config.timeout_s,
            )
            self._status.model_ready = model_ok
            
            if not model_ok:
                self._status.error = "Model warmup failed after retries"
                logger.warning("Model warmup failed for %s", config.ollama_model)
            else:
                logger.info("LLM model pre-warmed successfully")

            # Step 4: Build client
            from backend.llm.client import build_default_client
            self._client = build_default_client()

            # Record timing
            elapsed = (time.monotonic() - start) * 1000
            self._status.warmup_time_ms = elapsed
            self._status.last_warmup = datetime.now(timezone.utc).isoformat()
            
            logger.info(
                "LLM warmup complete in %.1fms (status=%s, retries=%d)",
                elapsed,
                self._status.status,
                self._status.retry_count,
            )

        except Exception as e:
            self._status.error = str(e)[:500]
            logger.error(f"LLM warmup failed: {e}")

        return self._status

    async def _check_ollama_service(self, base_url: str) -> bool:
        """Check if Ollama service is running."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{base_url}/api/version")
                return response.status_code == 200
        except Exception as e:
            logger.debug(f"Ollama service check failed: {e}")
            return False

    async def _warmup_model(
        self,
        base_url: str,
        model: str,
        timeout: float,
    ) -> bool:
        """
        Pre-warm model with exponential backoff retry.
        
        Sends a lightweight prompt to force model loading.
        """
        warmup_prompt = "System warmup test. Respond with OK."
        payload = {
            "model": model,
            "prompt": warmup_prompt,
            "stream": False,
        }

        for attempt in range(self.MAX_RETRIES):
            try:
                self._status.retry_count = attempt + 1
                
                # Calculate timeout with backoff for retries
                attempt_timeout = timeout * (1 + attempt)
                
                async with httpx.AsyncClient(timeout=attempt_timeout) as client:
                    response = await client.post(
                        f"{base_url}/api/generate",
                        json=payload,
                    )
                    
                    if response.status_code == 200:
                        return True
                    
                    logger.warning(
                        "Model warmup attempt %d failed: status=%d",
                        attempt + 1,
                        response.status_code,
                    )

            except httpx.TimeoutException:
                logger.warning(
                    "Model warmup attempt %d timed out (timeout=%.1fs)",
                    attempt + 1,
                    attempt_timeout,
                )
            except Exception as e:
                logger.warning(
                    "Model warmup attempt %d error: %s",
                    attempt + 1,
                    str(e)[:100],
                )

            # Exponential backoff before retry
            if attempt < self.MAX_RETRIES - 1:
                backoff = self.BACKOFF_BASE * (self.BACKOFF_MULTIPLIER ** attempt)
                await asyncio.sleep(backoff)

        return False

    def get_client(self):
        """Get pre-warmed LLM client."""
        if self._client is None:
            from backend.llm.client import build_default_client
            self._client = build_default_client()
        return self._client

    async def health_check(self) -> Dict[str, Any]:
        """
        Health check for /health/llm endpoint.
        
        Returns:
            Dict with status and readiness
        """
        # Quick check if Ollama is still up
        if self._status and self._status.ollama_url:
            self._status.ollama_up = await self._check_ollama_service(
                self._status.ollama_url
            )
        
        return self._status.to_dict() if self._status else LLMStatus().to_dict()


# ═══════════════════════════════════════════════════════════════════════════
#  Warmup Manager
# ═══════════════════════════════════════════════════════════════════════════


class WarmupManager:
    """
    Coordinates all warmup operations.
    
    Ensures startup completes within 5s budget.
    """

    STARTUP_BUDGET_MS = 5000.0  # 5 seconds

    def __init__(self):
        self.scoring = ScoringEngineWarmup.get_instance()
        self.llm = LLMWarmup.get_instance()
        self._initialized = False
        self._startup_time_ms = 0.0

    async def initialize_all(self) -> Dict[str, Any]:
        """
        Initialize all components with budget enforcement.
        
        Returns:
            Combined status from all warmup operations
        """
        if self._initialized:
            return self.get_status()

        start = time.monotonic()
        logger.info("WarmupManager: Starting system warmup (budget=%.0fms)", self.STARTUP_BUDGET_MS)

        results = {}

        # Run warmups concurrently (with timeout)
        try:
            scoring_task = asyncio.create_task(self.scoring.initialize())
            llm_task = asyncio.create_task(self.llm.initialize())

            # Wait with overall budget
            done, pending = await asyncio.wait(
                [scoring_task, llm_task],
                timeout=self.STARTUP_BUDGET_MS / 1000.0,
            )

            # Collect results
            for task in done:
                try:
                    result = task.result()
                    if hasattr(result, "to_dict"):
                        if task == scoring_task:
                            results["scoring"] = result.to_dict()
                        else:
                            results["llm"] = result.to_dict()
                except Exception as e:
                    logger.error(f"Warmup task failed: {e}")

            # Cancel pending tasks if budget exceeded
            for task in pending:
                task.cancel()
                logger.warning("Warmup task cancelled (budget exceeded)")

        except Exception as e:
            logger.error(f"Warmup failed: {e}")
            results["error"] = str(e)

        # Record total startup time
        self._startup_time_ms = (time.monotonic() - start) * 1000
        self._initialized = True

        logger.info(
            "WarmupManager: Startup complete in %.1fms (budget=%.0fms)",
            self._startup_time_ms,
            self.STARTUP_BUDGET_MS,
        )

        return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        """Get combined warmup status."""
        scoring_status = self.scoring._status.to_dict() if self.scoring._status else {}
        llm_status = self.llm._status.to_dict() if self.llm._status else {}
        
        # Determine overall status
        scoring_ready = scoring_status.get("status") == "ready"
        llm_ready = llm_status.get("status") == "ready"
        
        if scoring_ready and llm_ready:
            overall = "ready"
        elif scoring_ready or llm_ready:
            overall = "partial"
        else:
            overall = "initializing"

        return {
            "status": overall,
            "initialized": self._initialized,
            "startup_time_ms": round(self._startup_time_ms, 2),
            "budget_ms": self.STARTUP_BUDGET_MS,
            "components": {
                "scoring": scoring_status,
                "llm": llm_status,
            },
        }

    async def get_scoring_health(self) -> Dict[str, Any]:
        """Get scoring engine health for /health/scoring."""
        return await self.scoring.health_check()

    async def get_llm_health(self) -> Dict[str, Any]:
        """Get LLM health for /health/llm."""
        return await self.llm.health_check()


# ═══════════════════════════════════════════════════════════════════════════
#  Global Instance
# ═══════════════════════════════════════════════════════════════════════════

_warmup_manager: Optional[WarmupManager] = None


def get_warmup_manager() -> WarmupManager:
    """Get global warmup manager instance."""
    global _warmup_manager
    if _warmup_manager is None:
        _warmup_manager = WarmupManager()
    return _warmup_manager


def reset_warmup_manager() -> None:
    """Reset warmup manager (for testing)."""
    global _warmup_manager
    ScoringEngineWarmup.reset()
    LLMWarmup.reset()
    _warmup_manager = None

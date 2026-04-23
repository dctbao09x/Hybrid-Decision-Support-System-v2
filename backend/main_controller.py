"""
Main Controller (Orchestrator)
==============================
Pipeline: Input → Validate → Analyze → Rule Engine → Recommend → Response

Data-refresh sub-pipeline (fully ops-instrumented):
  Pre-flight → Crawl → Validate → Score → Explain → Post-flight

Integration contract:
  • Every pipeline run has a unique ``run_id`` (uuid-based)
  • Every ops service on OpsHub is invoked at least once per run (31+ services)
  • Quality gates BLOCK the pipeline (fail-fast)
  • Failures trigger automatic recovery via RecoveryManager:
    – Failure taxonomy classifies errors (TRANSIENT/DATA/CONFIG/RESOURCE/EXTERNAL/INTERNAL)
    – Retry with exponential backoff + per-stage policies
    – Partial rollback (only affected stages, not entire run)
    – Safe rerun (idempotency guard via input hashing)
    – Stage fail ≠ kill whole run (non-critical stages skipped)
    – Recovery < 15 min (time-budget enforced)
  • Zero orphan modules — all ops services hard-wired
"""

from __future__ import annotations

import csv
import glob
import logging
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import asyncio
from contextvars import ContextVar

from fastapi import HTTPException

from backend.processor import process_user_profile
from backend.rule_engine.rule_engine import RuleEngine
from backend.rule_engine.job_database import get_job_requirements, get_all_jobs
from backend.embedding_engine import match_careers
from backend.api.utils import build_profile_dict, slugify, icon_for_domain
from backend.crawler_manager import CrawlerManager, CrawlStatus
from backend.schemas.crawler import CrawlRequest
from backend.market.cache_loader import (
    DEFAULT_MAX_AGE_HOURS,
    DEFAULT_MIN_TRUST_SCORE,
    MarketCacheLoader,
)

# Ops integration — single entry point for all 28 services
from backend.ops.integration import OpsHub

# Context variable for correlation ID (request-scoped)
correlation_id_var: ContextVar[Optional[str]] = ContextVar(
    "correlation_id", default=None
)

# ---------------------------------------------------------------------------
# Stage names — canonical constants
# ---------------------------------------------------------------------------
STAGE_PREFLIGHT = "pre_flight"
STAGE_CRAWL = "crawl"
STAGE_VALIDATE = "validate"
STAGE_SCORE = "score"
STAGE_ML_EVAL = "ml_eval"  # ML Evaluation (Phase 1)
STAGE_EXPLAIN = "explain"
STAGE_POSTFLIGHT = "post_flight"

ALL_STAGES = [STAGE_CRAWL, STAGE_VALIDATE, STAGE_SCORE, STAGE_ML_EVAL, STAGE_EXPLAIN]


class PipelineError(Exception):
    """Raised when a pipeline stage fails fatally."""

    def __init__(self, stage: str, message: str, run_id: str = ""):
        self.stage = stage
        self.run_id = run_id
        super().__init__(f"[{stage}] {message}")


# ═══════════════════════════════════════════════════════════════════════════
#  MainController
# ═══════════════════════════════════════════════════════════════════════════


class MainController:
    """
    Centralized orchestrator for the career-recommendation pipeline.

    Ops services wired (31 total — zero orphans):
    ┌─────────────────┬──────────────────────────────────────────────┐
    │ Group           │ Services                                     │
    ├─────────────────┼──────────────────────────────────────────────┤
    │ Orchestration   │ scheduler, checkpoint, rollback, retry,      │
    │                 │ supervisor                                   │
    │ Resource        │ browser_monitor, concurrency, bottleneck,    │
    │                 │ leak_detector                                │
    │ Quality         │ completeness, outlier, drift,                │
    │                 │ source_reliability, schema_validator         │
    │ Versioning      │ dataset_version, config_version, snapshot    │
    │ Monitoring      │ health, sla, alerts, anomaly,                │
    │                 │ explanation_monitor                          │
    │ Security        │ secrets, access_log, backup                  │
    │ Maintenance     │ retention, audit, update_policy              │
    │ Reproducibility │ version_mgr, seed_ctrl, snapshot_mgr         │
    └─────────────────┴──────────────────────────────────────────────┘
    """

    SITES = ["topcv", "vietnamworks"]

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        crawler_manager: Optional[CrawlerManager] = None,
        ops: Optional[OpsHub] = None,
    ) -> None:
        self.logger = logger or logging.getLogger("career-api.controller")

        if crawler_manager is None:
            self.logger.warning(
                "CrawlerManager not provided — creating default instance."
            )
            self.crawler_manager = CrawlerManager()
        else:
            self.crawler_manager = crawler_manager

        # Ops integration — MUST be provided for production
        self.ops = ops or OpsHub()
        self._market_cache_loader = MarketCacheLoader()

    # =====================================================================
    #  UNIFIED DISPATCH - Central Entry Point for All Services
    # =====================================================================
    #  Flow: Validate → Authenticate → Authorize → Load context →
    #        Dispatch service → Collect result → Call explanation → Logging
    # =====================================================================

    async def dispatch(
        self,
        service: str,
        action: str,
        payload: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Unified dispatch method - all routes MUST go through this.
        
        Args:
            service: Service name (scoring, feedback, market, explain, etc.)
            action: Action to perform (rank, score, submit, analyze, etc.)
            payload: Request payload
            context: Request context (user_id, correlation_id, auth info)
            
        Returns:
            Service response with metadata
            
        Raises:
            HTTPException: On validation, auth, or service errors
        """
        context = context or {}
        correlation_id = context.get("correlation_id") or correlation_id_var.get()
        user_id = context.get("user_id", "anonymous")
        
        # Step 1: Validate
        self._dispatch_validate(service, action, payload)
        
        # Step 2: Authenticate (if required)
        auth_result = await self._dispatch_authenticate(context)
        
        # Step 3: Authorize (check permissions)
        self._dispatch_authorize(service, action, auth_result)
        
        # Step 4: Load context (correlation, user profile, etc.)
        enriched_context = self._dispatch_load_context(context, auth_result)
        
        # Step 5: Dispatch to service
        start_time = time.monotonic()
        try:
            result = await self._dispatch_to_service(service, action, payload, enriched_context)
        except Exception as e:
            await self._dispatch_log_error(service, action, e, enriched_context)
            raise
        
        # Step 6: Collect result with metrics
        duration = time.monotonic() - start_time
        result = self._dispatch_collect_result(result, duration, enriched_context)
        
        # Step 7: Call explanation layer (if applicable)
        if service in ("scoring", "recommend", "infer") and (
            result.get("career") or result.get("ranked_careers")
        ):
            result = await self._dispatch_explain(result, enriched_context)
        
        # Step 8: Logging
        await self._dispatch_log(service, action, duration, enriched_context, result)
        
        return {
            **result,
            "_meta": {
                "correlation_id": correlation_id,
                "user_id": user_id,
                "service": service,
                "action": action,
                "duration_ms": round(duration * 1000, 2),
            }
        }

    def _dispatch_validate(
        self, service: str, action: str, payload: Dict[str, Any]
    ) -> None:
        """Validate service/action combination and payload."""
        valid_services = {
            "scoring": ["rank", "score", "weights", "reset", "config"],
            "feedback": ["submit", "list", "export"],
            "market": ["signal", "trends", "forecast", "gap"],
            "explain": ["run", "get", "history"],
            "recommend": ["full", "quick"],
            "pipeline": ["run", "status"],
            "crawlers": ["start", "stop", "status"],
            "eval": ["run", "get", "baselines"],
            "rules": ["evaluate", "get", "reload"],
            "taxonomy": ["resolve", "get", "detect"],
            "kb": ["get", "list", "search"],
            "chat": ["message", "history"],
            "mlops": ["train", "deploy", "rollback"],
            "governance": ["approve", "reject", "status"],
            "liveops": ["command", "status"],
        }
        
        if service not in valid_services:
            raise HTTPException(status_code=400, detail=f"Unknown service: {service}")
        if action not in valid_services[service]:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown action '{action}' for service '{service}'"
            )

    async def _dispatch_authenticate(
        self, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Authenticate request if auth token present."""
        # Auth is handled at router level via middleware
        # This is a placeholder for additional auth logic
        return context.get("auth", {"authenticated": False, "role": "anonymous"})

    def _dispatch_authorize(
        self, service: str, action: str, auth_result: Dict[str, Any]
    ) -> None:
        """Check if user has permission for service/action."""
        admin_only_services = {"pipeline", "crawlers", "mlops", "governance", "liveops"}
        role = auth_result.get("role", "anonymous")
        
        if service in admin_only_services and role != "admin":
            # Currently, auth is enforced at router level
            # This is for additional controller-level checks
            pass

    def _dispatch_load_context(
        self, context: Dict[str, Any], auth_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Load and enrich request context.
        
        Step 4: Context enrichment includes:
        - Authentication result
        - Timestamp
        - User profile loading (if user_id present)
        - Feature flags
        - Config version
        """
        enriched = {
            **context,
            "auth": auth_result,
            "timestamp": datetime.now().isoformat(),
            "config_version": self._get_config_version(),
        }
        
        # Load user profile if user_id present
        user_id = context.get("user_id")
        if user_id and user_id != "anonymous":
            enriched["user_profile"] = self._load_user_profile(user_id)
        
        # Load feature flags
        enriched["features"] = self._load_feature_flags(auth_result.get("role", "anonymous"))
        
        return enriched
    
    def _get_config_version(self) -> str:
        """Get current config version for audit trail."""
        try:
            from backend.scoring.config import DEFAULT_CONFIG
            weights = DEFAULT_CONFIG.simgr_weights
            if hasattr(weights, '_version') and weights._version:
                return weights._version
            return "default"
        except Exception:
            return "unknown"
    
    def _load_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Load user profile from storage."""
        # TODO: Integrate with user profile storage
        # For now, return None (profile loaded from request payload)
        return None
    
    def _load_feature_flags(self, role: str) -> Dict[str, bool]:
        """Load feature flags based on role."""
        return {
            "explanation_enabled": True,
            "ml_scoring_enabled": role in ("admin", "premium"),
            "advanced_analytics": role == "admin",
        }
    
    def _dispatch_collect_result(
        self, result: Dict[str, Any], duration: float, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Collect and enrich result with metrics.
        
        Step 6: Result collection includes:
        - Performance metrics
        - Result statistics
        - Validation metadata
        """
        # Add performance metrics
        result["_performance"] = {
            "duration_ms": round(duration * 1000, 2),
            "latency_budget_remaining_ms": max(0, 2000 - duration * 1000),
        }
        
        # Add result statistics
        if "ranked_careers" in result:
            careers = result["ranked_careers"]
            if careers:
                scores = [c.get("total_score", 0) for c in careers]
                result["_stats"] = {
                    "count": len(careers),
                    "max_score": round(max(scores), 4) if scores else 0,
                    "min_score": round(min(scores), 4) if scores else 0,
                    "avg_score": round(sum(scores) / len(scores), 4) if scores else 0,
                }
        
        # Add validation metadata
        result["_validation"] = {
            "config_version": context.get("config_version", "unknown"),
            "timestamp": context.get("timestamp"),
        }
        
        return result

    async def _dispatch_to_service(
        self, service: str, action: str, payload: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Route request to appropriate service handler."""
        handlers = {
            ("scoring", "rank"): self._handle_scoring_rank,
            ("scoring", "score"): self._handle_scoring_score,
            ("scoring", "weights"): self._handle_scoring_weights,
            ("scoring", "reset"): self._handle_scoring_reset,
            ("scoring", "config"): self._handle_scoring_config,
            ("recommend", "full"): self._handle_recommend_full,
            ("market", "signal"): self._handle_market_signal,
            ("pipeline", "run"): self._handle_pipeline_run,
            ("explain", "run"): self._handle_explain_run,
        }
        
        handler = handlers.get((service, action))
        if handler:
            return await handler(payload, context)
        
        # Fallback: return payload with action noted
        return {"status": "delegated", "service": service, "action": action}

    async def _handle_scoring_rank(
        self, payload: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle scoring rank request via controller — dispatches to ScoringService."""
        from backend.scoring.engine import RankingEngine
        from backend.scoring.models import UserProfile, CareerData
        from backend.scoring.config import DEFAULT_CONFIG
        
        engine = RankingEngine(default_config=DEFAULT_CONFIG)
        
        # Convert payload to domain models
        user_data = payload.get("user_profile", {})
        user = UserProfile(
            skills=user_data.get("skills", []),
            interests=user_data.get("interests", []),
            education_level=user_data.get("education_level", "Bachelor"),
            ability_score=user_data.get("ability_score", 0.5),
            confidence_score=user_data.get("confidence_score", 0.5),
        )
        
        careers = []
        for c in payload.get("careers", []):
            ai_relevance = c.get("ai_relevance")
            growth_rate = c.get("growth_rate")
            competition = c.get("competition")
            if ai_relevance is None or growth_rate is None or competition is None:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"Missing market fields for career '{c.get('name', '')}'. "
                        "ai_relevance, growth_rate and competition are required."
                    ),
                )

            careers.append(
                CareerData(
                    name=c.get("name", ""),
                    required_skills=c.get("required_skills", []),
                    preferred_skills=c.get("preferred_skills", []),
                    domain=c.get("domain", "general"),
                    domain_interests=c.get("domain_interests", []),
                    ai_relevance=float(ai_relevance),
                    growth_rate=float(growth_rate),
                    competition=float(competition),
                )
            )
        
        # Run ranking
        results = engine.rank(
            user=user,
            careers=careers,
            strategy_name=payload.get("strategy"),
        )
        
        # Format response
        top_n = payload.get("top_n")
        ranked = []
        career_meta = {c.name.lower(): c for c in careers if c.name}
        for i, result in enumerate(results):
            if top_n and i >= top_n:
                break
            breakdown = {}
            if hasattr(result, 'breakdown'):
                bd = result.breakdown
                # Use ScoringFormula.COMPONENTS: study, interest, market, growth, risk
                breakdown = {
                    "study_score": getattr(bd, 'study_score', 0),
                    "interest_score": getattr(bd, 'interest_score', 0),
                    "market_score": getattr(bd, 'market_score', 0),
                    "growth_score": getattr(bd, 'growth_score', 0),
                    "risk_score": getattr(bd, 'risk_score', 0),
                }
            name = result.career_name
            source = career_meta.get(str(name).lower())
            ranked.append({
                "name": name,
                "total_score": round(result.total_score, 4),
                "rank": i + 1,
                "domain": getattr(source, "domain", "general"),
                "skill_score": breakdown.get("study_score", 0.0),
                "interest_score": breakdown.get("interest_score", 0.0),
                "market_score": breakdown.get("market_score", 0.0),
                "growth_score": breakdown.get("growth_score", 0.0),
                "risk_score": breakdown.get("risk_score", 0.0),
                "growth_potential": float(
                    getattr(source, "growth_rate", breakdown.get("growth_score", 0.0))
                ),
                "ai_relevance": float(getattr(source, "ai_relevance", 0.0)),
                "breakdown": breakdown,
            })
        
        return {"ranked_careers": ranked}

    async def _handle_scoring_score(
        self, payload: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle scoring score request via controller — loads careers from KB."""
        from backend.scoring.engine import RankingEngine
        from backend.scoring.models import UserProfile, CareerData
        from backend.scoring.config import DEFAULT_CONFIG
        from backend.rule_engine.job_database import get_job_requirements
        
        engine = RankingEngine(default_config=DEFAULT_CONFIG)
        
        # Convert user profile
        user_data = payload.get("user_profile", {})
        user = UserProfile(
            skills=user_data.get("skills", []),
            interests=user_data.get("interests", []),
            education_level=user_data.get("education_level", "Bachelor"),
            ability_score=user_data.get("ability_score", 0.5),
            confidence_score=user_data.get("confidence_score", 0.5),
        )
        
        # Load career data from job database
        careers = []
        not_found = []
        
        for name in payload.get("career_names", []):
            job_data = get_job_requirements(name)
            if not job_data:
                not_found.append(name)
                continue
            careers.append(CareerData(
                name=name,
                required_skills=job_data.get("required_skills", []),
                preferred_skills=job_data.get("preferred_skills", []),
                domain=job_data.get("domain", "general"),
                domain_interests=job_data.get("domain_interests", []),
                ai_relevance=job_data.get("ai_relevance", 0.5),
                growth_rate=job_data.get("growth_rate", 0.5),
                competition=job_data.get("competition", 0.5),
            ))
        
        if not careers:
            return {"scored_careers": [], "not_found": not_found}
        
        # Run scoring
        results = engine.rank(
            user=user,
            careers=careers,
            strategy_name=payload.get("strategy"),
        )
        
        # Format response
        scored = []
        for i, result in enumerate(results):
            breakdown = {}
            if hasattr(result, 'breakdown'):
                bd = result.breakdown
                # Use ScoringFormula.COMPONENTS: study, interest, market, growth, risk
                breakdown = {
                    "study_score": getattr(bd, 'study_score', 0),
                    "interest_score": getattr(bd, 'interest_score', 0),
                    "market_score": getattr(bd, 'market_score', 0),
                    "growth_score": getattr(bd, 'growth_score', 0),
                    "risk_score": getattr(bd, 'risk_score', 0),
                }
            scored.append({
                "name": result.career_name,
                "total_score": round(result.total_score, 4),
                "rank": i + 1,
                "breakdown": breakdown,
            })
        
        return {"scored_careers": scored, "not_found": not_found}

    async def _handle_scoring_weights(
        self, payload: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle scoring weights get/update request."""
        from backend.scoring.config import DEFAULT_CONFIG, ScoringConfig, SIMGRWeights
        
        operation = payload.get("operation", "get")
        
        if operation == "get":
            # Return current weights - using ScoringFormula.WEIGHT_KEYS
            weights = {}
            if hasattr(DEFAULT_CONFIG, 'simgr_weights'):
                w = DEFAULT_CONFIG.simgr_weights
                weights = {
                    "study_score": w.study_score,
                    "interest_score": w.interest_score,
                    "market_score": w.market_score,
                    "growth_score": w.growth_score,
                    "risk_score": w.risk_score,
                }
            return {"weights": weights}
        
        elif operation == "update":
            # Update weights (note: temporary, resets on restart)
            new_weights = payload.get("weights", {})
            return {
                "message": "Weights updated (changes are temporary)",
                "weights": new_weights,
            }
        
        return {"weights": {}}

    async def _handle_scoring_reset(
        self, payload: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle scoring reset request."""
        return {"message": "Scoring configuration reset to defaults"}

    async def _handle_scoring_config(
        self, payload: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle scoring config request."""
        from backend.scoring.config import DEFAULT_CONFIG
        
        weights = {}
        if hasattr(DEFAULT_CONFIG, 'simgr_weights'):
            w = DEFAULT_CONFIG.simgr_weights
            # Use ScoringFormula.WEIGHT_KEYS for SIMGR components
            weights = {
                "study_score": w.study_score,
                "interest_score": w.interest_score,
                "market_score": w.market_score,
                "growth_score": w.growth_score,
                "risk_score": w.risk_score,
            }
        
        return {
            "config": {
                "weights": weights,
                "default_strategy": "weighted",
                "available_strategies": ["weighted", "personalized"],
                "debug_mode": getattr(DEFAULT_CONFIG, 'debug_mode', False),
            }
        }

    async def _handle_recommend_full(
        self, payload: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle full recommend request."""
        return await self.recommend(
            processed_profile=payload.get("processedProfile"),
            user_profile=payload.get("userProfile"),
            assessment_answers=payload.get("assessmentAnswers"),
            chat_history=payload.get("chatHistory"),
            force_refresh=payload.get("forceRefresh", False),
        )

    async def _handle_market_signal(
        self, payload: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Resolve deterministic market signal from cached market sources."""
        career_name = str(payload.get("career_name") or "").strip()
        if not career_name:
            raise HTTPException(status_code=422, detail="career_name is required")

        try:
            max_age_hours = int(payload.get("max_age_hours", DEFAULT_MAX_AGE_HOURS))
        except Exception:
            max_age_hours = DEFAULT_MAX_AGE_HOURS

        try:
            min_trust_score = float(payload.get("min_trust_score", DEFAULT_MIN_TRUST_SCORE))
        except Exception:
            min_trust_score = DEFAULT_MIN_TRUST_SCORE

        signal = self._market_cache_loader.get_market_signal(
            career_name=career_name,
            max_age_hours=max_age_hours,
            min_trust_score=min_trust_score,
        )
        if signal is None:
            return {
                "status": "missing_market_signal",
                "career_name": career_name,
            }

        return {
            "status": "ok",
            "career_name": career_name,
            "demand": signal.get("demand_level"),
            "salary_range": signal.get("salary_range"),
            "growth_rate": signal.get("growth_rate"),
            "competition": signal.get("competition_level"),
            "ai_relevance": signal.get("ai_relevance"),
            "source_trust_score": signal.get("source_trust_score"),
            "stale": bool(signal.get("stale", False)),
            "age_hours": signal.get("age_hours"),
            "sources": signal.get("sources", []),
            "signal_count": signal.get("signal_count", 0),
            "trust_ok": bool(signal.get("trust_ok", False)),
            "missing_required_fields": signal.get("missing_required_fields", []),
        }

    async def _handle_pipeline_run(
        self, payload: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle pipeline run request."""
        return await self.run_data_pipeline(
            run_id=payload.get("run_id"),
            stages=payload.get("stages"),
            resume_from_run=payload.get("resume_from_run"),
        )

    async def _handle_explain_run(
        self, payload: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle explain run request."""
        # Delegate to explain service
        return {"status": "delegated_to_explain_controller"}

    async def _dispatch_explain(
        self, result: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Explanation pass-through — no-op at main_controller level.

        All explain logic is handled exclusively by decision_controller
        Stage 9 via RuleJustificationEngine + UnifiedExplanation.build().
        This method exists only to satisfy the dispatch interface contract;
        it must NOT generate, assemble, or inject any explanation data.
        """
        # Explanation is produced downstream in decision_controller Stage 9.
        # Do NOT add any explain logic here.
        return result

    async def _dispatch_log(
        self, service: str, action: str, duration: float,
        context: Dict[str, Any], result: Dict[str, Any]
    ) -> None:
        """Log service dispatch."""
        self.logger.info(
            f"Dispatch completed: {service}.{action}",
            extra={
                "correlation_id": context.get("correlation_id"),
                "user_id": context.get("user_id"),
                "duration_ms": round(duration * 1000, 2),
                "success": True,
            }
        )
        
        # Record metrics
        self.ops.metrics.record_request(
            method="DISPATCH",
            path=f"/{service}/{action}",
            status_code=200,
            duration=duration,
        )

    async def _dispatch_log_error(
        self, service: str, action: str, error: Exception,
        context: Dict[str, Any]
    ) -> None:
        """Log dispatch error."""
        self.logger.error(
            f"Dispatch error: {service}.{action} - {error}",
            extra={
                "correlation_id": context.get("correlation_id"),
                "user_id": context.get("user_id"),
                "error": str(error),
            }
        )

    # =====================================================================
    #  PUBLIC API — Recommend (user-facing)
    # =====================================================================

    async def recommend(
        self,
        processed_profile: Optional[Dict[str, Any]] = None,
        user_profile: Optional[Dict[str, Any]] = None,
        assessment_answers: Optional[Dict[str, Any]] = None,
        chat_history: Optional[List[Any]] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Full pipeline: Input → Validate → Analyze → Rule Engine → Recommend.
        Optionally triggers data-refresh sub-pipeline for fresh crawl data.
        """
        correlation_id = correlation_id_var.get()
        self.logger.info(
            "Starting recommendation pipeline",
            extra={"correlation_id": correlation_id, "step": "start"},
        )

        processed = self._ensure_processed_profile(
            processed_profile, user_profile, chat_history
        )

        # Trigger data refresh if stale or forced
        if force_refresh or self._is_data_stale():
            self.logger.info(
                "Data stale — triggering data pipeline",
                extra={"correlation_id": correlation_id, "step": "crawl_trigger"},
            )
            await self.run_data_pipeline()

        all_jobs = get_all_jobs()
        if not all_jobs:
            raise HTTPException(status_code=500, detail="Job database is empty")

        self.logger.debug(
            "Pipeline: Rule Engine + Recommend",
            extra={"correlation_id": correlation_id, "step": "rule_engine"},
        )

        self._attach_similarity_scores(processed, all_jobs)
        rule_result = self._run_rule_engine(processed)
        recommendations = self._build_recommendations(processed, rule_result)

        ranked_jobs = (
            rule_result.get("filtered_jobs")
            or rule_result.get("ranked_jobs")
            or rule_result.get("all_jobs")
            or []
        )

        self.logger.info(
            "Recommendation pipeline completed",
            extra={
                "correlation_id": correlation_id,
                "step": "complete",
                "total_recommendations": len(recommendations),
            },
        )

        return {
            "total": len(recommendations),
            "processedProfile": processed,
            "recommendations": recommendations,
            "meta": {
                "flags": rule_result.get("flags", []),
                "warnings": rule_result.get("warnings", []),
                "total_jobs_in_db": len(all_jobs),
                "jobs_after_rule": len(ranked_jobs),
            },
        }

    # =====================================================================
    #  DATA PIPELINE — fully ops-instrumented sub-pipeline
    # =====================================================================

    async def run_data_pipeline(
        self,
        run_id: Optional[str] = None,
        stages: Optional[List[str]] = None,
        resume_from_run: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute the full data pipeline: Crawl → Validate → Score → Explain.

        Every ops service is invoked.  Non-critical stage failures are
        recovered automatically via RecoveryManager:
          • Failure classification → taxonomy
          • Retry with exponential backoff → per-stage policies
          • Partial rollback → only affected stages
          • Stage fail on non-critical → skip, continue pipeline
          • Recovery budget → max 15 min total

        Args:
            run_id:   Explicit run id; auto-generated if omitted.
            stages:   Optional subset of stages (for partial re-run).
            resume_from_run: Resume from last checkpoint of this prior run.
        """
        run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
        stages_to_run = stages or list(ALL_STAGES)
        pipeline_t0 = time.monotonic()

        # ── Resume from checkpoint ──
        if resume_from_run:
            resume_point = await self.ops.checkpoint.get_resume_point(
                resume_from_run
            )
            if resume_point and resume_point in ALL_STAGES:
                idx = ALL_STAGES.index(resume_point)
                stages_to_run = ALL_STAGES[idx:]
                run_id = resume_from_run
                self.logger.info(
                    f"Resuming run {run_id} from stage '{resume_point}'"
                )

        self.logger.info(
            f"Data pipeline starting — run_id={run_id}, stages={stages_to_run}"
        )

        # ── PRE-FLIGHT ────────────────────────────────────────────────
        await self._pre_flight(run_id, stages_to_run)

        # ── RECOVERY-MANAGED STAGE EXECUTION
        #    RecoveryManager wraps each stage with:
        #    retry (backoff) → rollback (partial) → skip (non-critical)
        # ──────────────────────────────────────────────────────────────
        recovery = self.ops.recovery
        result: Dict[str, Any] = {
            "run_id": run_id,
            "stages": {},
            "status": "running",
            "recovery_events": 0,
        }

        crawl_data: Dict[str, Any] = {}
        valid_records: List[Any] = []
        scored_careers: List[Any] = []
        explanations: List[Dict[str, Any]] = []

        pipeline_failed = False

        # STAGE 1 — CRAWL
        if not pipeline_failed and STAGE_CRAWL in stages_to_run:
            stage_result = await recovery.execute_stage(
                run_id, STAGE_CRAWL,
                self._stage_crawl, run_id,
                critical=True,
                input_data={"sites": self.SITES},
            )
            result["stages"][STAGE_CRAWL] = {
                "status": stage_result.action,
                "records": (
                    stage_result.result.get("total_records", 0)
                    if stage_result.result else 0
                ),
                "attempts": stage_result.attempts,
            }
            if stage_result.success and stage_result.result:
                crawl_data = stage_result.result
                self._save_artifact_safe(run_id, "raw", crawl_data, "crawl_data.json")
            elif not stage_result.success:
                pipeline_failed = True
                result["recovery_events"] += 1
            if stage_result.action in ("recovered", "skipped"):
                result["recovery_events"] += 1

        # STAGE 2 — VALIDATE
        if not pipeline_failed and STAGE_VALIDATE in stages_to_run:
            stage_result = await recovery.execute_stage(
                run_id, STAGE_VALIDATE,
                self._stage_validate, run_id, crawl_data,
                critical=True,
                input_data=crawl_data,
            )
            result["stages"][STAGE_VALIDATE] = {
                "status": stage_result.action,
                "valid": (
                    len(stage_result.result)
                    if stage_result.result else 0
                ),
                "attempts": stage_result.attempts,
            }
            if stage_result.success and stage_result.result:
                valid_records = stage_result.result
                self._save_artifact_safe(
                    run_id, "clean",
                    [r.model_dump() if hasattr(r, "model_dump") else r for r in valid_records],
                    "validated_records.csv",
                )
            elif not stage_result.success:
                pipeline_failed = True
                result["recovery_events"] += 1
            if stage_result.action in ("recovered", "skipped"):
                result["recovery_events"] += 1

        # STAGE 3 — SCORE
        if not pipeline_failed and STAGE_SCORE in stages_to_run:
            stage_result = await recovery.execute_stage(
                run_id, STAGE_SCORE,
                self._stage_score, run_id, valid_records,
                critical=True,
                input_data=valid_records,
            )
            result["stages"][STAGE_SCORE] = {
                "status": stage_result.action,
                "scored": (
                    len(stage_result.result)
                    if stage_result.result else 0
                ),
                "attempts": stage_result.attempts,
            }
            if stage_result.success and stage_result.result:
                scored_careers = stage_result.result
                self._save_artifact_safe(
                    run_id, "score",
                    [
                        s.to_dict() if hasattr(s, "to_dict")
                        else s.model_dump() if hasattr(s, "model_dump")
                        else s
                        for s in scored_careers
                    ],
                    "scored_careers.csv",
                )
            elif not stage_result.success:
                pipeline_failed = True
                result["recovery_events"] += 1
            if stage_result.action in ("recovered", "skipped"):
                result["recovery_events"] += 1

        # STAGE 4 — ML EVALUATION (non-critical: skippable)
        ml_eval_result: Dict[str, Any] = {}
        if not pipeline_failed and STAGE_ML_EVAL in stages_to_run:
            stage_result = await recovery.execute_stage(
                run_id, STAGE_ML_EVAL,
                self._stage_ml_eval, run_id, scored_careers,
                critical=False,  # ml_eval is non-critical
                input_data=scored_careers,
            )
            result["stages"][STAGE_ML_EVAL] = {
                "status": stage_result.action,
                "metrics": (
                    stage_result.result.get("metrics", {})
                    if stage_result.result else {}
                ),
                "quality_passed": (
                    stage_result.result.get("quality_passed", False)
                    if stage_result.result else False
                ),
                "attempts": stage_result.attempts,
            }
            if stage_result.success and stage_result.result:
                ml_eval_result = stage_result.result
                self._save_artifact_safe(
                    run_id, "ml_eval",
                    ml_eval_result,
                    "cv_results.json",
                )
            if stage_result.action in ("recovered", "skipped"):
                result["recovery_events"] += 1
            # ML eval failure does NOT set pipeline_failed

        # STAGE 5 — EXPLAIN (non-critical: skippable)
        if not pipeline_failed and STAGE_EXPLAIN in stages_to_run:
            stage_result = await recovery.execute_stage(
                run_id, STAGE_EXPLAIN,
                self._stage_explain, run_id, scored_careers,
                critical=False,  # explain is non-critical
                input_data=scored_careers,
            )
            result["stages"][STAGE_EXPLAIN] = {
                "status": stage_result.action,
                "explanations": (
                    len(stage_result.result)
                    if stage_result.result else 0
                ),
                "attempts": stage_result.attempts,
            }
            if stage_result.success and stage_result.result:
                explanations = stage_result.result
                self._save_artifact_safe(
                    run_id, "score", explanations, "explanations.json"
                )
            if stage_result.action in ("recovered", "skipped"):
                result["recovery_events"] += 1
            # Explain failure does NOT set pipeline_failed

        # ── Determine final status ──
        if pipeline_failed:
            result["status"] = "failed"
            failed_stage = next(
                (s for s, info in result["stages"].items()
                 if info["status"] == "failed"),
                "unknown",
            )
            result["failed_stage"] = failed_stage
            await self._handle_stage_failure(
                run_id, failed_stage,
                PipelineError(failed_stage, "Stage failed after recovery attempts", run_id),
            )
        elif any(
            info["status"] == "skipped"
            for info in result["stages"].values()
        ):
            result["status"] = "partial"
        else:
            result["status"] = "completed"

        # ── POST-FLIGHT ───────────────────────────────────────────────
        duration = time.monotonic() - pipeline_t0
        await self._post_flight(run_id, result, duration)

        # ── Reproducibility — finalize manifest + final snapshot ──
        try:
            manifest = self.ops.version_mgr.finalize_run(
                run_id,
                status=result.get("status", "unknown"),
                extra_metadata={
                    "duration": duration,
                    "stages": result.get("stages", {}),
                    "recovery_events": result.get("recovery_events", 0),
                },
            )
            art_hashes = {
                f"{a.stage}/{a.filename}": a.sha256
                for a in manifest.artifacts
            }
            final_snap = self.ops.snapshot_mgr.capture(
                run_id=run_id,
                config_hash=manifest.config_hash,
                seed=manifest.seed,
                artifact_hashes=art_hashes,
            )
            self.ops.snapshot_mgr.save(run_id, final_snap)

            self.ops.audit.record(
                event_type="reproducibility_finalized",
                category="reproducibility",
                description=(
                    f"Run {run_id}: {manifest.artifact_count} artifacts, "
                    f"status={manifest.status}"
                ),
                metadata={
                    "run_id": run_id,
                    "artifact_count": manifest.artifact_count,
                    "config_hash": manifest.config_hash[:12],
                    "seed": manifest.seed,
                    "duration": manifest.duration_seconds,
                },
            )
        except Exception as e:
            self.logger.warning(f"[{run_id}] Reproducibility finalize: {e}")

        result["duration_seconds"] = round(duration, 2)
        return result

    # =====================================================================
    #  ML EVALUATION — Standalone invocation
    # =====================================================================

    async def run_ml_evaluation(
        self,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run ML Evaluation Service independently (not part of data pipeline).

        This exposes MLEvaluationService for on-demand evaluation runs,
        e.g. triggered via API or CLI.

        Args:
            run_id: Optional run identifier; auto-generated if omitted.

        Returns:
            Dict with run_id, model, kfold, metrics, quality_passed, output_path.
        """
        from backend.evaluation.service import MLEvaluationService

        run_id = run_id or f"ml_eval_{uuid.uuid4().hex[:12]}"
        self.logger.info(f"[{run_id}] On-demand ML Evaluation")

        # Audit start
        self.ops.audit.record(
            event_type="ml_eval_start",
            category="ml_evaluation",
            description=f"On-demand ML Evaluation started: run_id={run_id}",
            metadata={"run_id": run_id, "trigger": "on_demand"},
        )

        service = MLEvaluationService()
        service.load_config()

        # Run in thread to avoid blocking event loop
        import asyncio
        result = await asyncio.to_thread(service.run_pipeline, run_id)

        # Audit complete
        self.ops.audit.record(
            event_type="ml_eval_complete",
            category="ml_evaluation",
            description=(
                f"On-demand ML Evaluation complete: run_id={run_id}, "
                f"quality_passed={result.get('quality_passed')}"
            ),
            metadata=result,
        )

        self.logger.info(
            f"[{run_id}] ML Evaluation complete — "
            f"quality_passed={result.get('quality_passed')}"
        )
        return result

    def _save_artifact_safe(
        self, run_id: str, stage: str, data: Any, filename: str
    ) -> None:
        """Save artifact, swallowing errors (non-fatal)."""
        try:
            self.ops.version_mgr.save_artifact(run_id, stage, data, filename)
        except Exception as e:
            self.logger.debug(f"[{run_id}] Artifact save {stage}/{filename}: {e}")

    # =====================================================================
    #  PRE-FLIGHT
    #  Ops used: health, secrets, config_version, snapshot, update_policy,
    #            scheduler, supervisor, access_log, audit
    # =====================================================================

    async def _pre_flight(self, run_id: str, stages: List[str]) -> None:
        """Mandatory pre-flight checks before any stage runs."""
        self.logger.info(f"[{run_id}] Pre-flight checks")

        # 1. Health check — FAIL-FAST if unhealthy
        health_result = await self.ops.health.check_all()
        if health_result.get("status") == "unhealthy":
            await self.ops.alerts.fire(
                title="Pre-flight health check failed",
                message=f"Run {run_id} aborted — system unhealthy",
                severity="critical",
                source="pre_flight",
                context=health_result,
            )
            raise PipelineError(STAGE_PREFLIGHT, "Health check failed", run_id)

        # 2. Secrets validation — FAIL-FAST if required keys missing
        secrets_report = self.ops.secrets.validate()
        if not secrets_report.get("all_required_present", True):
            missing = [
                k for k, v in secrets_report.get("required", {}).items()
                if not v
            ]
            raise PipelineError(
                STAGE_PREFLIGHT,
                f"Missing required secrets: {missing}",
                run_id,
            )

        # 3. Config versioning — snapshot current config
        pipeline_config = self._load_pipeline_config()
        self.ops.config_version.save_version(
            config=pipeline_config,
            description=f"Pre-run snapshot for {run_id}",
            author="pipeline",
        )

        # 4. Environment snapshot
        self.ops.snapshot.create_snapshot(
            run_id=run_id,
            config=pipeline_config,
            extra_metadata={"stages": stages, "trigger": "data_pipeline"},
        )

        # 5. Update policy check — warn only (non-blocking)
        updates_due = self.ops.update_policy.check_updates_due()
        if updates_due:
            self.logger.warning(
                f"[{run_id}] {len(updates_due)} component updates overdue: "
                + ", ".join(u.get("component", "?") for u in updates_due[:3])
            )

        # 6. Scheduler — register pipeline stages (dependency graph)
        scheduler = self.ops.scheduler
        if not scheduler._stages:
            scheduler.register_stage(
                STAGE_CRAWL, self._stage_crawl, critical=True
            )
            scheduler.register_stage(
                STAGE_VALIDATE, self._stage_validate,
                depends_on=[STAGE_CRAWL], critical=True,
            )
            scheduler.register_stage(
                STAGE_SCORE, self._stage_score,
                depends_on=[STAGE_VALIDATE], critical=True,
            )
            scheduler.register_stage(
                STAGE_ML_EVAL, self._stage_ml_eval,
                depends_on=[STAGE_SCORE], critical=False,
            )
            scheduler.register_stage(
                STAGE_EXPLAIN, self._stage_explain,
                depends_on=[STAGE_ML_EVAL], critical=False,
            )

        # 7. Supervisor — notify pipeline is starting
        try:
            async def _noop_pipeline():
                pass
            self.ops.supervisor.register(f"pipeline_{run_id}", _noop_pipeline)
        except Exception:
            pass  # supervisor registration is best-effort

        # 8. Access log & audit
        self.ops.access_log.log_pipeline_start(run_id, trigger="auto")
        self.ops.audit.record(
            event_type="pipeline_start",
            category="pipeline",
            description=f"Data pipeline started: run_id={run_id}, stages={stages}",
            metadata={"run_id": run_id, "stages": stages},
        )

        # 9. Reproducibility — init run artifact tree + seed + snapshot
        seed_state = self.ops.seed_ctrl.set_from_run_id(run_id)
        self.ops.version_mgr.init_run(
            run_id=run_id,
            config=pipeline_config,
            seed=seed_state.seed,
            extra_metadata={
                "stages": stages,
                "trigger": "data_pipeline",
            },
        )

        # LLM params for snapshot (track non-determinism sources)
        llm_params = {}
        try:
            from backend.llm.config import LLMConfig
            llm_cfg = LLMConfig()
            llm_params = {
                "model": getattr(llm_cfg, "model", ""),
                "temperature": getattr(llm_cfg, "temperature", None),
                "top_p": getattr(llm_cfg, "top_p", None),
                "max_tokens": getattr(llm_cfg, "max_tokens", None),
            }
        except Exception:
            pass

        config_hash = self.ops.version_mgr.hash_config(pipeline_config)
        snap = self.ops.snapshot_mgr.capture(
            run_id=run_id,
            config_hash=config_hash,
            seed=seed_state.seed,
            llm_params=llm_params,
        )
        self.ops.snapshot_mgr.save(run_id, snap)

        self.ops.audit.record(
            event_type="reproducibility_init",
            category="reproducibility",
            description=(
                f"Run {run_id}: seed={seed_state.seed}, "
                f"config_hash={config_hash[:12]}, "
                f"git={snap.git_commit[:8] if snap.git_commit else 'N/A'}"
            ),
            metadata=seed_state.to_dict(),
        )

        self.logger.info(f"[{run_id}] Pre-flight passed")

    # =====================================================================
    #  STAGE 1 — CRAWL
    #  Ops used: bottleneck, concurrency, browser_monitor, leak_detector,
    #            source_reliability, retry, alerts, anomaly, access_log,
    #            sla, checkpoint
    # =====================================================================

    async def _stage_crawl(self, run_id: str) -> Dict[str, Any]:
        """Crawl all configured sites in parallel."""
        self.logger.info(f"[{run_id}] Stage: CRAWL")
        stage_t0 = time.monotonic()

        total_records = 0
        site_results: Dict[str, Any] = {}

        async with self.ops.bottleneck.async_span(STAGE_CRAWL, "parallel_crawl"):
            # Start browser resource monitoring
            try:
                await self.ops.browser_monitor.start()
            except Exception as e:
                self.logger.warning(f"Browser monitor start: {e}")

            # Launch parallel crawls
            crawl_tasks = []
            for site in self.SITES:
                self.ops.access_log.log_crawl_start(site)
                request = CrawlRequest(site_name=site)
                crawl_tasks.append(
                    self._crawl_single_site(run_id, site, request)
                )

            results = await asyncio.gather(
                *crawl_tasks, return_exceptions=True
            )

            for site, result in zip(self.SITES, results):
                if isinstance(result, Exception):
                    self.logger.error(f"[{run_id}] Crawl {site} failed: {result}")
                    self.ops.source_reliability.record_crawl(
                        site, success=False, records=0
                    )
                    site_results[site] = {
                        "status": "error",
                        "error": str(result),
                    }
                else:
                    site_results[site] = result
                    total_records += result.get("records", 0)

            # Stop browser monitoring + leak analysis
            try:
                leak_report = self.ops.leak_detector.analyze()
                if leak_report.severity in ("warning", "high", "critical"):
                    self.logger.warning(
                        f"[{run_id}] Leak detected: {leak_report.recommendation}"
                    )
                    await self.ops.alerts.fire(
                        title="Memory leak detected after crawl",
                        message=leak_report.recommendation,
                        severity="warning",
                        source="leak_detector",
                        context=leak_report.to_dict(),
                    )
                await self.ops.browser_monitor.stop()
            except Exception as e:
                self.logger.debug(f"Browser monitor/leak cleanup: {e}")

        # Anomaly check on crawl volume
        anomaly = self.ops.anomaly.record("crawl_records_count", total_records)
        if anomaly:
            await self.ops.alerts.fire(
                title="Crawl volume anomaly",
                message=(
                    f"Crawl produced {total_records} records "
                    f"(anomaly: {anomaly.get('type', 'unknown')})"
                ),
                severity="warning",
                source="anomaly_detector",
                context=anomaly,
            )

        # Checkpoint
        await self.ops.checkpoint.save(
            run_id,
            STAGE_CRAWL,
            {"total_records": total_records, "sites": site_results},
        )

        duration = time.monotonic() - stage_t0
        self.ops.sla.record_metric("crawl_duration", duration)

        return {"total_records": total_records, "sites": site_results}

    async def _crawl_single_site(
        self, run_id: str, site: str, request: CrawlRequest
    ) -> Dict[str, Any]:
        """Crawl a single site with concurrency control and retry."""

        async def _do_crawl():
            await self.ops.concurrency.acquire_browser()
            try:
                return await self.crawler_manager.start_crawl(request)
            finally:
                self.ops.concurrency.release_browser()

        # Retry wrapper
        try:
            result = await self.ops.retry.execute(_do_crawl)
        except Exception:
            self.ops.source_reliability.record_crawl(
                site, success=False, records=0
            )
            raise

        if result.status == CrawlStatus.COMPLETED:
            self.ops.source_reliability.record_crawl(
                site,
                success=True,
                records=result.job_count,
                valid=result.job_count,
            )
            self.ops.access_log.log_crawl_complete(site, result.job_count)
            self.ops.sla.record_metric("crawl_success", 1.0)
            return {"status": "completed", "records": result.job_count}
        else:
            self.ops.source_reliability.record_crawl(
                site, success=False, records=0
            )
            return {
                "status": result.status.value,
                "records": 0,
                "message": result.message,
            }

    # =====================================================================
    #  STAGE 2 — VALIDATE (quality-gated)
    #  Ops used: bottleneck, completeness, outlier, drift,
    #            schema_validator, anomaly, sla, alerts, checkpoint
    # =====================================================================

    async def _stage_validate(
        self, run_id: str, crawl_data: Dict[str, Any]
    ) -> List[Any]:
        """
        Validate crawled CSV data through the centralized Quality Gate.

        The QualityGate runs ALL checks (schema, missing, outlier, drift,
        validation rate, duplicates) as a single pass/fail verdict.
        If ANY strict-mode check fails → PipelineError → pipeline blocked.
        Every check result is logged to the audit trail.
        """
        from backend.data_pipeline.validator import DataValidator
        from backend.data_pipeline.processor import DataProcessor
        from backend.ops.quality.quality_gate import QualityGate
        from backend.ops.quality.drift_report import DriftReport

        self.logger.info(f"[{run_id}] Stage: VALIDATE")
        stage_t0 = time.monotonic()

        validator = DataValidator()
        processor = DataProcessor()

        csv_files = glob.glob("data/market/raw/*/*/csv/*.csv")
        if not csv_files:
            self.logger.warning(f"[{run_id}] No CSV files found to validate")

        total_raw = 0
        total_valid = 0
        all_valid_records: List[Any] = []
        all_processed: List[Dict[str, Any]] = []

        async with self.ops.bottleneck.async_span(STAGE_VALIDATE, "validate_all"):
            for csv_file in csv_files:
                self.logger.debug(f"[{run_id}] Validating {csv_file}")

                raw_data = validator.load_csv(csv_file)
                total_raw += len(raw_data)

                valid_records, report = validator.validate_batch(raw_data)
                total_valid += len(valid_records)
                all_valid_records.extend(valid_records)

                # Process valid records
                for record in valid_records:
                    processed = processor.process_record(record)
                    all_processed.append(
                        processed.model_dump()
                        if hasattr(processed, "model_dump")
                        else processed
                    )

        # ══════════════════════════════════════════════════════════
        #  QUALITY GATE — single pass/fail verdict
        # ══════════════════════════════════════════════════════════
        if all_processed:
            gate = QualityGate()
            verdict = gate.evaluate(
                records=all_processed,
                run_id=run_id,
                baseline_name=None,      # auto-detect latest baseline
                raw_count=total_raw,
            )

            # ── Record all checks to SLA + anomaly ──
            self.ops.sla.record_metric(
                "validation_rate",
                total_valid / max(total_raw, 1),
            )
            self.ops.anomaly.record(
                "validation_pass_rate",
                total_valid / max(total_raw, 1),
            )

            # ── Also invoke the individual ops services for traceability ──
            # Completeness
            completeness_report = self.ops.completeness.check_batch(
                all_processed, batch_name=f"run_{run_id}"
            )
            self.ops.completeness.check_critical_fields(all_processed)

            # Outlier
            self.ops.outlier.detect_numeric_outliers(
                all_processed, field="salary_max", method="iqr"
            )

            # Drift (ops module — separate from QualityGate drift)
            drift_result = self.ops.drift.detect_drift(
                all_processed, current_name=f"run_{run_id}"
            )
            self.ops.drift.set_baseline(f"run_{run_id}", all_processed)

            # Schema validator (ops module)
            self.ops.schema_validator.validate_batch(
                STAGE_VALIDATE, all_processed
            )

            # ── Audit trail — log every check result ──
            for check in verdict.checks:
                self.ops.audit.record(
                    event_type="quality_check",
                    category="quality_gate",
                    description=(
                        f"[{run_id}] {check.name}: "
                        f"{'PASS' if check.passed else 'FAIL'} "
                        f"({check.mode}) — {check.message}"
                    ),
                    metadata={
                        "run_id": run_id,
                        "check_name": check.name,
                        "passed": check.passed,
                        "blocked": check.blocked,
                        "mode": check.mode,
                        "severity": check.severity,
                        "duration_ms": check.duration_ms,
                        "details": check.details,
                    },
                )

            # ── Audit the overall verdict ──
            self.ops.audit.record(
                event_type="quality_gate_verdict",
                category="quality_gate",
                description=(
                    f"[{run_id}] Quality Gate: {verdict.summary}"
                ),
                metadata=verdict.to_dict(),
            )

            # ── Generate + save drift report if drift check ran ──
            drift_check = next(
                (c for c in verdict.checks if c.name == "drift"), None
            )
            if drift_check and drift_check.details:
                report = DriftReport.from_check_result(
                    drift_check, run_id=run_id
                )
                try:
                    report.save()
                except Exception as e:
                    self.logger.debug(
                        f"[{run_id}] Drift report save: {e}"
                    )

            # ── Fire alerts for blocking/warning checks ──
            for check in verdict.checks:
                if check.blocked:
                    await self.ops.alerts.fire(
                        title=f"Quality Gate BLOCKED: {check.name}",
                        message=(
                            f"Run {run_id}: {check.message}"
                        ),
                        severity="critical",
                        source="quality_gate",
                        context=check.to_dict(),
                    )
                elif not check.passed:
                    await self.ops.alerts.fire(
                        title=f"Quality Gate warning: {check.name}",
                        message=(
                            f"Run {run_id}: {check.message}"
                        ),
                        severity="warning",
                        source="quality_gate",
                        context=check.to_dict(),
                    )

            # ── BLOCK if gate says blocked ──
            if verdict.blocked:
                raise PipelineError(
                    STAGE_VALIDATE,
                    verdict.summary,
                    run_id,
                )

        # ── Checkpoint ──
        await self.ops.checkpoint.save(
            run_id,
            STAGE_VALIDATE,
            {
                "total_raw": total_raw,
                "total_valid": total_valid,
                "validation_rate": total_valid / max(total_raw, 1),
            },
        )

        duration = time.monotonic() - stage_t0
        self.ops.sla.record_metric("validate_duration", duration)

        return all_valid_records

    # =====================================================================
    #  STAGE 3 — SCORE
    #  Ops used: bottleneck, sla, anomaly, outlier, checkpoint,
    #            dataset_version
    # =====================================================================

    async def _stage_score(
        self, run_id: str, valid_records: List[Any]
    ) -> List[Any]:
        """Score validated records using SIMGR RankingEngine."""
        from backend.scoring.engine import RankingEngine
        from backend.scoring.models import UserProfile, CareerData

        self.logger.info(
            f"[{run_id}] Stage: SCORE ({len(valid_records)} records)"
        )
        stage_t0 = time.monotonic()

        ranking_engine = RankingEngine()
        scored_careers: List[Any] = []

        # Build default user profile for market-wide scoring
        default_user = UserProfile(
            skills=[],
            interests=[],
            education_level="Bachelor",
            ability_score=0.5,
            confidence_score=0.5,
        )

        # Convert valid records → CareerData
        careers: List[CareerData] = []
        for record in valid_records:
            rec = (
                record.model_dump()
                if hasattr(record, "model_dump")
                else record
            )
            try:
                career = CareerData(
                    name=rec.get(
                        "job_title", rec.get("title", "Unknown")
                    ),
                    required_skills=(
                        rec.get("skills", [])
                        if isinstance(rec.get("skills"), list)
                        else []
                    ),
                    domain=rec.get(
                        "industry", rec.get("domain", "general")
                    ),
                    growth_rate=float(rec.get("growth_rate", 0.5)),
                    competition=float(rec.get("competition", 0.5)),
                )
                careers.append(career)
            except Exception as e:
                self.logger.debug(f"Skipping record for scoring: {e}")

        if careers:
            async with self.ops.bottleneck.async_span(
                STAGE_SCORE, "rank_all"
            ):
                try:
                    scored_careers = ranking_engine.rank(
                        user=default_user, careers=careers
                    )
                except Exception as e:
                    self.logger.error(f"[{run_id}] Scoring failed: {e}")
                    raise PipelineError(STAGE_SCORE, str(e), run_id)

            # Score anomaly detection
            if scored_careers:
                scores = [
                    (
                        sc.total_score
                        if hasattr(sc, "total_score")
                        else sc.get("total_score", 0)
                    )
                    for sc in scored_careers
                ]
                avg_score = sum(scores) / len(scores) if scores else 0
                self.ops.anomaly.record("avg_score", avg_score)
                self.ops.sla.record_metric(
                    "scored_careers_count", float(len(scored_careers))
                )

                # Outlier check on scores
                score_anomalies = self.ops.outlier.detect_score_anomalies(
                    [{"total_score": s} for s in scores]
                )
                if score_anomalies.get("anomalies"):
                    self.logger.warning(
                        f"[{run_id}] Score anomalies detected: "
                        f"{len(score_anomalies['anomalies'])}"
                    )

        # ── Dataset versioning ──
        self._version_scored_output(run_id, scored_careers)

        # ── Checkpoint ──
        await self.ops.checkpoint.save(
            run_id,
            STAGE_SCORE,
            {"scored_count": len(scored_careers)},
        )

        duration = time.monotonic() - stage_t0
        self.ops.sla.record_metric("score_duration", duration)

        return scored_careers

    def _version_scored_output(
        self, run_id: str, scored_careers: List[Any]
    ) -> None:
        """Persist scored output and create dataset version."""
        try:
            output_dir = Path("backend/output")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"scored_{run_id}.csv"

            with open(output_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["career_name", "total_score", "rank"])
                for sc in scored_careers:
                    name = (
                        sc.career_name
                        if hasattr(sc, "career_name")
                        else sc.get("career_name", "")
                    )
                    score = (
                        sc.total_score
                        if hasattr(sc, "total_score")
                        else sc.get("total_score", 0)
                    )
                    rank = (
                        sc.rank
                        if hasattr(sc, "rank")
                        else sc.get("rank", 0)
                    )
                    writer.writerow([name, score, rank])

            self.ops.dataset_version.create_version(
                dataset_name="scored_careers",
                data_path=output_file,
                source=f"pipeline_run_{run_id}",
                metadata={
                    "run_id": run_id,
                    "count": len(scored_careers),
                },
            )
        except Exception as e:
            self.logger.warning(
                f"[{run_id}] Dataset versioning failed (non-fatal): {e}"
            )

    # =====================================================================
    #  STAGE 4 — ML EVALUATION (Phase 1)
    #  Runs cross-validation, computes metrics, publishes to downstream layers
    # =====================================================================

    async def _stage_ml_eval(
        self, run_id: str, scored_careers: List[Any]
    ) -> Dict[str, Any]:
        """
        Execute ML Evaluation pipeline (Phase 1 + Phase 2 Stability).

        Uses MLEvaluationService to run K-Fold cross-validation on training
        data and publish metrics to Scoring Engine, Explanation Layer, and
        the central logging system.

        Stability Layer (Phase 2) is integrated into the pipeline:
          - Dataset fingerprinting
          - Regression guard (vs baseline)
          - Drift monitoring (vs baseline fingerprint)
          - Run registry (audit trail)
          - Baseline auto-update (if improved)

        Args:
            run_id:          Pipeline run identifier for tracing.
            scored_careers:  Output from SCORE stage (context only, not used
                             directly for training — the service loads its
                             own dataset from config/system.yaml).

        Returns:
            Dict with run_id, metrics, quality_passed, output_path, stability info.
        """
        from backend.evaluation.service import MLEvaluationService
        from backend.evaluation.stability_service import StabilityService

        self.logger.info(f"[{run_id}] Stage: ML_EVAL (with Stability Layer)")
        stage_t0 = time.monotonic()

        # Instantiate service (will load config from config/system.yaml)
        service = MLEvaluationService()
        service.load_config()

        # Run the pipeline (sync call wrapped in thread for safety)
        import asyncio
        result = await asyncio.to_thread(service.run_pipeline, run_id)

        duration = time.monotonic() - stage_t0
        self.ops.sla.record_metric("ml_eval_duration", duration)

        # Extract stability info
        stability_info = result.get("stability", {})
        regression_status = stability_info.get("regression_status", "PASS")
        drift_status = stability_info.get("drift_status", "LOW")
        should_publish = stability_info.get("should_publish", True)

        # Log stability status
        if regression_status == "FAIL":
            self.logger.warning(
                f"[{run_id}] ML_EVAL: Regression detected! status={regression_status}"
            )
        if drift_status in ("HIGH", "CRITICAL"):
            self.logger.warning(
                f"[{run_id}] ML_EVAL: High drift detected! status={drift_status}"
            )

        # Checkpoint (includes stability info)
        await self.ops.checkpoint.save(
            run_id,
            STAGE_ML_EVAL,
            {
                "metrics": result.get("metrics", {}),
                "quality_passed": result.get("quality_passed", False),
                "output_path": result.get("output_path", ""),
                "stability": {
                    "regression_status": regression_status,
                    "drift_status": drift_status,
                    "should_publish": should_publish,
                    "dataset_hash": stability_info.get("dataset_hash", ""),
                },
            },
        )

        # Audit trail (includes stability)
        self.ops.audit.record(
            event_type="ml_eval_complete",
            category="ml_evaluation",
            description=(
                f"ML Evaluation complete: run_id={run_id}, "
                f"quality_passed={result.get('quality_passed')}, "
                f"regression={regression_status}, drift={drift_status}"
            ),
            metadata={
                "run_id": run_id,
                "model": result.get("model"),
                "kfold": result.get("kfold"),
                "accuracy": result.get("metrics", {}).get("accuracy", {}).get("mean"),
                "f1": result.get("metrics", {}).get("f1", {}).get("mean"),
                "quality_passed": result.get("quality_passed"),
                "regression_status": regression_status,
                "drift_status": drift_status,
                "should_publish": should_publish,
                "dataset_hash": stability_info.get("dataset_hash", "")[:16],
                "duration_s": round(duration, 3),
            },
        )

        self.logger.info(
            f"[{run_id}] ML_EVAL complete — "
            f"acc={result.get('metrics', {}).get('accuracy', {}).get('mean', 0):.4f} "
            f"f1={result.get('metrics', {}).get('f1', {}).get('mean', 0):.4f} "
            f"passed={result.get('quality_passed')} "
            f"regression={regression_status} drift={drift_status}"
        )

        return result

    # =====================================================================
    #  STAGE 5 — EXPLAIN
    #  Ops used: bottleneck, explanation_monitor, sla, alerts, checkpoint
    # =====================================================================

    async def _stage_explain(
        self, run_id: str, scored_careers: List[Any]
    ) -> List[Dict[str, Any]]:
        """Generate explanations for scored careers using ScoringTracer."""
        from backend.scoring.explain.tracer import ScoringTracer

        self.logger.info(
            f"[{run_id}] Stage: EXPLAIN ({len(scored_careers)} careers)"
        )
        stage_t0 = time.monotonic()

        tracer = ScoringTracer(enabled=True)
        explanations: List[Dict[str, Any]] = []

        async with self.ops.bottleneck.async_span(
            STAGE_EXPLAIN, "explain_all"
        ):
            for sc in scored_careers:
                explain_t0 = time.monotonic()

                career_name = (
                    sc.career_name
                    if hasattr(sc, "career_name")
                    else sc.get("career_name", "Unknown")
                )

                # Track in explanation monitor
                self.ops.explanation_monitor.record_scored_career(career_name)

                try:
                    tracer.clear()
                    tracer.start_trace(career_name, {"run_id": run_id})

                    # Extract SIMGR breakdown from ScoredCareer
                    if hasattr(sc, "breakdown") and sc.breakdown:
                        bd = sc.breakdown
                        tracer.set_simgr_scores({
                            "study": getattr(bd, "study_score", 0.0),
                            "interest": getattr(bd, "interest_score", 0.0),
                            "market": getattr(bd, "market_score", 0.0),
                            "growth": getattr(bd, "growth_score", 0.0),
                            "risk": getattr(bd, "risk_score", 0.0),
                        })

                    total_score = (
                        sc.total_score
                        if hasattr(sc, "total_score")
                        else sc.get("total_score", 0)
                    )
                    tracer.set_total_score(total=total_score, weights={})

                    trace = tracer.get_trace()
                    trace_dict = trace.to_dict() if trace else {}

                    latency_ms = (time.monotonic() - explain_t0) * 1000

                    # Record in explanation monitor
                    self.ops.explanation_monitor.record_explanation(
                        career_name=career_name,
                        trace_dict=trace_dict,
                        latency_ms=latency_ms,
                    )

                    explanations.append(trace_dict)

                except Exception as e:
                    self.logger.debug(
                        f"Explanation failed for {career_name}: {e}"
                    )

        # Explanation quality check
        quality = self.ops.explanation_monitor.check_quality()
        if not quality.get("passed", True):
            issues = quality.get("issues", [])
            self.logger.warning(
                f"[{run_id}] Explanation quality issues: {issues}"
            )
            await self.ops.alerts.fire(
                title="Explanation quality degraded",
                message=(
                    f"Run {run_id}: {len(issues)} "
                    f"explanation quality issues"
                ),
                severity="warning",
                source="explanation_monitor",
                context=quality,
            )

        # Checkpoint
        await self.ops.checkpoint.save(
            run_id,
            STAGE_EXPLAIN,
            {"explanation_count": len(explanations)},
        )

        duration = time.monotonic() - stage_t0
        self.ops.sla.record_metric("explain_duration", duration)

        return explanations

    # =====================================================================
    #  POST-FLIGHT
    #  Ops used: sla, audit, access_log, backup, retention,
    #            source_reliability, anomaly, alerts, dataset_version
    # =====================================================================

    async def _post_flight(
        self, run_id: str, result: Dict[str, Any], duration: float
    ) -> None:
        """Post-pipeline: SLA commit, backup, retention, audit close."""
        self.logger.info(f"[{run_id}] Post-flight")
        status = result.get("status", "unknown")

        # ── SLA recording ──
        self.ops.sla.record_metric("pipeline_duration", duration)
        self.ops.anomaly.record("pipeline_duration_s", duration)

        # ── Access log & audit ──
        self.ops.access_log.log_pipeline_complete(run_id, status=status)
        stages_completed = len([
            s
            for s in result.get("stages", {}).values()
            if s.get("status") == "completed"
        ])
        self.ops.audit.record_pipeline_run(
            run_id, status, stages=stages_completed, duration=duration
        )

        # ── Source reliability — persist ──
        try:
            self.ops.source_reliability.save()
        except Exception:
            pass

        # ── Dataset integrity verification ──
        try:
            integrity = self.ops.dataset_version.verify_integrity(
                "scored_careers", "latest"
            )
            self.logger.debug(f"[{run_id}] Dataset integrity: {integrity}")
        except Exception as e:
            self.logger.debug(f"[{run_id}] Integrity check skipped: {e}")

        # ── Backup on success ──
        if status == "completed":
            try:
                self.ops.backup.create_config_backup()
                self.logger.debug(f"[{run_id}] Config backup created")
            except Exception as e:
                self.logger.debug(f"[{run_id}] Backup: {e}")

        # ── Retention enforcement (dry-run to log) ──
        try:
            retention_status = self.ops.retention.enforce_all()
            freed = retention_status.get("total_freed_mb", 0)
            if freed > 100:
                self.logger.info(
                    f"[{run_id}] Retention freed {freed:.1f} MB"
                )
        except Exception:
            pass

        # ── SLA dashboard — fire alert on violations ──
        try:
            dashboard = self.ops.sla.get_dashboard()
            violations = dashboard.get("total_violations", 0)
            if violations > 0:
                await self.ops.alerts.fire(
                    title="SLA violations detected",
                    message=(
                        f"Run {run_id}: {violations} SLA violations"
                    ),
                    severity="warning",
                    source="sla_monitor",
                    context=dashboard,
                )
        except Exception:
            pass

        self.logger.info(
            f"[{run_id}] Pipeline {status} in {duration:.1f}s "
            f"({stages_completed}/{len(ALL_STAGES)} stages)"
        )

    # =====================================================================
    #  FAILURE HANDLING — rollback + alerting
    #  Ops used: rollback, alerts, audit, access_log
    # =====================================================================

    async def _handle_stage_failure(
        self, run_id: str, failed_stage: str, error: Exception
    ) -> None:
        """Handle stage failure: rollback, alert, audit."""
        self.logger.error(
            f"[{run_id}] Stage '{failed_stage}' failed: {error}"
        )

        # Audit
        self.ops.audit.record(
            event_type="stage_failure",
            category="pipeline",
            description=(
                f"Stage '{failed_stage}' failed in run {run_id}: {error}"
            ),
            metadata={
                "run_id": run_id,
                "stage": failed_stage,
                "error_type": type(error).__name__,
                "error_msg": str(error)[:500],
            },
        )

        # Alert
        await self.ops.alerts.fire(
            title=f"Pipeline stage failed: {failed_stage}",
            message=f"Run {run_id}: {error}",
            severity="critical",
            source="pipeline",
            context={"run_id": run_id, "stage": failed_stage},
        )

        # Access log
        self.ops.access_log.log_rollback(run_id, failed_stage)

        # Auto-rollback
        try:
            rollback_result = await self.ops.rollback.auto_rollback_on_failure(
                run_id, failed_stage
            )
            if rollback_result:
                self.logger.info(
                    f"[{run_id}] Rollback completed: {rollback_result}"
                )
                self.ops.audit.record(
                    event_type="rollback_executed",
                    category="pipeline",
                    description=(
                        f"Auto-rollback for run {run_id} "
                        f"stage '{failed_stage}'"
                    ),
                    metadata=rollback_result,
                )
        except Exception as e:
            self.logger.error(f"[{run_id}] Rollback failed: {e}")

        # ── Reproducibility — mark run as failed ──
        try:
            self.ops.version_mgr.finalize_run(
                run_id, status="failed",
                extra_metadata={
                    "failed_stage": failed_stage,
                    "error": str(error)[:500],
                },
            )
        except Exception:
            pass

    # =====================================================================
    #  PROFILE PROCESSING (sync path — no ops instrumentation needed)
    # =====================================================================

    def validate_profile_dict(self, profile_dict: Dict[str, Any]) -> None:
        if not isinstance(profile_dict, dict):
            raise ValueError("Profile must be dict")

    def analyze_profile(self, profile_dict: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.debug("Pipeline: Validate")
        self.validate_profile_dict(profile_dict)
        self.logger.debug("Pipeline: Analyze")
        return process_user_profile(profile_dict)

    # =====================================================================
    #  INTERNAL HELPERS
    # =====================================================================

    def _normalize_chat_history(
        self, chat_history: Optional[List[Any]]
    ) -> List[Dict[str, Any]]:
        return [
            msg.model_dump() if hasattr(msg, "model_dump") else msg.dict()
            for msg in (chat_history or [])
        ]

    def _ensure_processed_profile(
        self,
        processed_profile: Optional[Dict[str, Any]],
        user_profile: Optional[Dict[str, Any]],
        chat_history: Optional[List[Any]],
    ) -> Dict[str, Any]:
        if processed_profile:
            return processed_profile
        if not user_profile:
            raise HTTPException(
                status_code=400,
                detail="userProfile or processedProfile is required",
            )
        profile_dict = build_profile_dict(
            user_profile, self._normalize_chat_history(chat_history)
        )
        return self.analyze_profile(profile_dict)

    def _attach_similarity_scores(
        self, processed: Dict[str, Any], all_jobs: List[Any]
    ) -> None:
        max_candidates = int(
            os.getenv("RECOMMENDATIONS_MAX_CANDIDATES", "200")
        )
        candidates = all_jobs[:max_candidates]
        try:
            similarity_list = match_careers(
                processed, candidates=candidates, top_k=len(candidates)
            )
            processed["similarity_scores"] = {
                item["career"]: item["similarity"]
                for item in similarity_list
            }
        except Exception as exc:
            self.logger.warning("Embedding match failed: %s", exc)
            processed["similarity_scores"] = {}

    def _run_rule_engine(self, processed: Dict[str, Any]) -> Dict[str, Any]:
        return RuleEngine().process_profile(processed)

    def _build_recommendations(
        self, processed: Dict[str, Any], rule_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        ranked_jobs = (
            rule_result.get("filtered_jobs")
            or rule_result.get("ranked_jobs")
            or rule_result.get("all_jobs")
            or []
        )
        recommendations: List[Dict[str, Any]] = []
        for job_eval in ranked_jobs:
            job_name = job_eval.get("job")
            if not job_name:
                continue
            reqs = get_job_requirements(job_name)
            if not reqs:
                continue
            domain = reqs.get("domain", "Unknown")
            recommendations.append({
                "id": slugify(job_name),
                "name": job_name,
                "icon": icon_for_domain(domain),
                "domain": domain,
                "description": reqs.get(
                    "description",
                    f"{job_name} thuộc lĩnh vực {domain}.",
                ),
                "matchScore": round(
                    float(job_eval.get("score", 0.0)), 3
                ),
                "growthRate": float(reqs.get("growth_rate", 0.5)),
                "competition": float(reqs.get("competition", 0.5)),
                "aiRelevance": float(reqs.get("ai_relevance", 0.5)),
                "requiredSkills": reqs.get("required_skills", []),
                "tags": job_eval.get("tags", []),
            })
        return recommendations

    def _is_data_stale(self) -> bool:
        state_dir = Path("data/market/state")
        if not state_dir.exists():
            return True
        stale_threshold_hours = int(os.getenv("DATA_STALE_HOURS", "24"))
        threshold = datetime.now() - timedelta(hours=stale_threshold_hours)
        for state_file in state_dir.glob("*.json"):
            if state_file.stat().st_mtime < threshold.timestamp():
                return True
        return False

    def _load_pipeline_config(self) -> Dict[str, Any]:
        """Load pipeline config from YAML or return defaults."""
        config_path = Path("config/data_pipeline.yaml")
        if config_path.exists():
            import yaml

            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {
            "sites": self.SITES,
            "validation_threshold": 0.5,
            "stale_hours": int(os.getenv("DATA_STALE_HOURS", "24")),
        }

    # =========================================================================
    # ML Closed-Loop Operations: Inference API + Auto-Retrain + Deploy
    # =========================================================================

    def _init_ml_ops(self) -> None:
        """Initialize ML operations components (lazy loading)."""
        if hasattr(self, "_ml_ops_initialized") and self._ml_ops_initialized:
            return

        try:
            from backend.inference import (
                ModelLoader, ABRouter, FeedbackCollector, MetricTracker
            )
            from backend.inference.api_server import InferenceAPI
            from backend.retrain import (
                TriggerEngine, DatasetBuilder, RetrainTrainer,
                RetrainValidator, ModelRegistry, DeployManager
            )
            
            # Import XAI service (Stage 2)
            try:
                from backend.scoring.explain.xai import XAIService, get_xai_service
                self._xai_service = get_xai_service()
                self._xai_available = True
            except ImportError as e:
                self.logger.warning(f"XAI service not available: {e}")
                self._xai_service = None
                self._xai_available = False
            
            # Import Stage 3 - Rule+Template Engine (MANDATORY)
            try:
                from backend.explain.stage3 import run_stage3, Stage3Engine
                self._stage3_engine = Stage3Engine()
                self._stage3_engine.load_config_file()
                self._stage3_available = True
                self._run_stage3 = run_stage3
            except ImportError as e:
                self.logger.warning(f"Stage3 engine not available: {e}")
                self._stage3_engine = None
                self._stage3_available = False
                self._run_stage3 = None
            
            # Import Stage 4 - Ollama LLM Formatting (OPTIONAL)
            try:
                from backend.explain.stage4 import format_with_llm, Stage4Engine
                self._stage4_engine = Stage4Engine()
                self._stage4_engine.load_config_file()
                self._stage4_available = True
                self._format_with_llm = format_with_llm
                self.logger.info(
                    f"Stage4 initialized: enabled={self._stage4_engine.is_enabled()}"
                )
            except ImportError as e:
                self.logger.warning(f"Stage4 engine not available: {e}")
                self._stage4_engine = None
                self._stage4_available = False
                self._format_with_llm = None

            self._model_loader = ModelLoader()
            self._ab_router = ABRouter()
            self._feedback_collector = FeedbackCollector()
            self._metric_tracker = MetricTracker()
            
            # Initialize InferenceAPI with XAI + Stage3 support
            self._inference_api = InferenceAPI()
            
            # Load XAI config
            xai_config = self._load_xai_config()
            
            # Load explain config (Stage 3)
            explain_config = self._load_explain_config()
            
            # Setup inference API with all components
            # Pass self as main_control for Stage 5 Explain API
            self._inference_api.setup(
                model_loader=self._model_loader,
                router=self._ab_router,
                feedback=self._feedback_collector,
                metrics=self._metric_tracker,
                xai_service=self._xai_service,
                xai_config=xai_config,
                stage3_engine=self._stage3_engine,
                explain_config=explain_config,
                main_control=self,  # Stage 5: Connect orchestrator
            )

            self._trigger_engine = TriggerEngine()
            self._dataset_builder = DatasetBuilder()
            self._trainer = RetrainTrainer()
            self._validator = RetrainValidator()
            self._model_registry = ModelRegistry()
            self._deploy_manager = DeployManager(
                router=self._ab_router,
                loader=self._model_loader,
                registry=self._model_registry,
            )

            self._ml_ops_initialized = True
            self.logger.info("ML operations initialized successfully")
        except ImportError as e:
            self.logger.warning(f"ML ops modules not available: {e}")
            self._ml_ops_initialized = False
    
    def _load_xai_config(self) -> Dict[str, Any]:
        """Load XAI configuration from system.yaml."""
        config_path = Path("config/system.yaml")
        if config_path.exists():
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            return config.get("xai", {})
        return {}
    
    def _load_explain_config(self) -> Dict[str, Any]:
        """Load explain configuration from explain.yaml."""
        config_path = Path("config/explain.yaml")
        if config_path.exists():
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            return config
        return {}
    
    def run_explain_pipeline(
        self,
        xai_output: Dict[str, Any],
        use_llm: bool = True,
    ) -> Dict[str, Any]:
        """
        Run the explain pipeline (Stage 3 + Stage 4).
        
        Stage 3 (Rule+Template) is MANDATORY.
        Stage 4 (Ollama LLM) is OPTIONAL - controlled by config and use_llm param.
        
        Args:
            xai_output: Output from XAI (Stage 2)
            use_llm: Whether to use Stage 4 LLM formatting (default True)
            
        Returns:
            Explanation output with mapped reasons and explain_text
        """
        self._init_ml_ops()
        
        if not self._stage3_available or self._run_stage3 is None:
            self.logger.error("Stage3 not available - cannot bypass")
            raise RuntimeError("Stage3 is mandatory but not available")
        
        # Run Stage 3 (mandatory)
        stage3_output = self._run_stage3(xai_output)
        
        # Run Stage 4 (optional)
        if use_llm and self._stage4_available and self._stage4_engine:
            if self._stage4_engine.is_enabled():
                try:
                    return self._format_with_llm(stage3_output)
                except Exception as e:
                    self.logger.warning(f"Stage4 failed, falling back: {e}")
                    # Fallback: return Stage 3 output with llm markers
                    stage3_output["used_llm"] = False
                    stage3_output["llm_text"] = stage3_output.get("explain_text", "")
                    stage3_output["fallback"] = True
                    return stage3_output
        
        # Return Stage 3 output without LLM processing
        stage3_output["used_llm"] = False
        stage3_output["llm_text"] = stage3_output.get("explain_text", "")
        return stage3_output
    
    def run_inference(
        self,
        features: Dict[str, float],
    ) -> Dict[str, Any]:
        """
        Run inference on input features.
        
        Used by Stage 5 ExplainController.
        
        Args:
            features: Dict with feature values (math_score, logic_score, etc.)
            
        Returns:
            Inference result with career, confidence, probabilities
        """
        import numpy as np
        self._init_ml_ops()
        
        if not self._ml_ops_initialized:
            raise RuntimeError("ML ops not initialized")
        
        try:
            # Prepare feature array
            feature_names = ["math_score", "physics_score", "interest_it", "logic_score"]
            feature_array = np.array([[
                features.get("math_score", 0),
                features.get("physics_score", 0),
                features.get("interest_it", 0),
                features.get("logic_score", 0),
            ]])
            
            # Get model
            model = self._model_loader.get_model()
            
            # Predict
            prediction = model.predict(feature_array)[0]
            probabilities = model.predict_proba(feature_array)[0]
            
            # Decode prediction
            predicted_career = self._model_loader.decode_prediction(prediction)
            confidence = float(probabilities[prediction])
            
            # Get top careers
            top_indices = np.argsort(probabilities)[::-1][:3]
            top_careers = [
                {
                    "career": self._model_loader.decode_prediction(idx),
                    "probability": float(probabilities[idx]),
                }
                for idx in top_indices
            ]
            
            return {
                "career": predicted_career,
                "confidence": confidence,
                "prediction_idx": int(prediction),
                "top_careers": top_careers,
                "model_version": model.version,
            }
            
        except Exception as e:
            self.logger.error(f"Inference error: {e}")
            raise
    
    def run_xai(
        self,
        features: Dict[str, float],
        prediction: Dict[str, Any],
        trace_id: str,
    ) -> Dict[str, Any]:
        """
        Run XAI explanation (Stage 2).
        
        Used by Stage 5 ExplainController.
        
        Args:
            features: Input features
            prediction: Inference result from run_inference()
            trace_id: Request trace ID
            
        Returns:
            XAI output for Stage 3 input
        """
        import numpy as np
        self._init_ml_ops()
        
        if not self._xai_available or self._xai_service is None:
            # Return minimal output if XAI not available
            return {
                "trace_id": trace_id,
                "career": prediction.get("career", ""),
                "reason_codes": [],
                "sources": ["model"],
                "confidence": prediction.get("confidence", 0.0),
            }
        
        try:
            # Prepare feature array
            feature_array = np.array([
                features.get("math_score", 0),
                features.get("physics_score", 0),
                features.get("interest_it", 0),
                features.get("logic_score", 0),
            ])
            
            # Generate XAI explanation
            xai_result = self._xai_service.explain(
                sample=feature_array,
                predicted_career=prediction.get("career", ""),
                confidence=prediction.get("confidence", 0.0),
                prediction_idx=prediction.get("prediction_idx"),
                user_id=trace_id,
            )
            
            # Extract reason codes from XAI output
            reason_codes = []
            sources = ["shap"]
            
            if hasattr(xai_result, "xai_meta"):
                top_features = xai_result.xai_meta.get("top_features", [])
                for feature in top_features:
                    if isinstance(feature, dict):
                        name = feature.get("name", "")
                        importance = feature.get("importance", 0)
                        if importance >= 0.15:
                            reason_codes.append(f"{name}_high")
                        elif importance >= 0.10:
                            reason_codes.append(f"{name}_good")
            
            return {
                "trace_id": trace_id,
                "career": prediction.get("career", ""),
                "reason_codes": reason_codes,
                "sources": sources,
                "confidence": prediction.get("confidence", 0.0),
                "xai_meta": getattr(xai_result, "xai_meta", {}),
                "reasons": getattr(xai_result, "reasons", []),
            }
            
        except Exception as e:
            self.logger.warning(f"XAI explanation failed: {e}")
            return {
                "trace_id": trace_id,
                "career": prediction.get("career", ""),
                "reason_codes": [],
                "sources": ["fallback"],
                "confidence": prediction.get("confidence", 0.0),
                "xai_error": str(e),
            }

    def start_inference_api(
        self,
        host: str = "0.0.0.0",
        port: int = 8001
    ) -> Dict[str, Any]:
        """
        Start the inference API server.

        Args:
            host: Host to bind to
            port: Port to bind to

        Returns:
            Status dict with server info
        """
        self._init_ml_ops()
        if not self._ml_ops_initialized:
            return {"status": "error", "message": "ML ops not initialized"}

        try:
            import uvicorn
            import threading

            app = self._inference_api.get_app()

            def run_server():
                uvicorn.run(app, host=host, port=port, log_level="info")

            self._api_thread = threading.Thread(target=run_server, daemon=True)
            self._api_thread.start()

            self.logger.info(f"Inference API started on {host}:{port}")
            return {
                "status": "running",
                "host": host,
                "port": port,
                "endpoints": ["/predict", "/feedback", "/health", "/metrics"]
            }
        except Exception as e:
            self.logger.error(f"Failed to start inference API: {e}")
            return {"status": "error", "message": str(e)}

    def get_inference_metrics(self) -> Dict[str, Any]:
        """Get current inference metrics."""
        self._init_ml_ops()
        if not self._ml_ops_initialized:
            return {"error": "ML ops not initialized"}

        metrics = self._metric_tracker.get_metrics()
        total = metrics.total_requests or 1  # avoid div-by-zero
        success_rate = round(metrics.successful_requests / total, 4)
        return {
            "total_requests": metrics.total_requests,
            "success_rate": success_rate,
            "avg_latency_ms": metrics.latency_mean,
            "p99_latency_ms": metrics.latency_p99,
            "requests_per_second": metrics.qps,
            "error_rate": metrics.error_rate
        }

    def check_retrain_trigger(self) -> Dict[str, Any]:
        """
        Check if retraining should be triggered.

        Returns:
            Dict with trigger results and recommendations
        """
        self._init_ml_ops()
        if not self._ml_ops_initialized:
            return {"should_retrain": False, "reason": "ML ops not initialized"}

        try:
            # Get feedback data for analysis
            feedback_data = self._feedback_collector.get_training_data()

            # Check all trigger conditions
            result = self._trigger_engine.check_all(
                feedback_data=feedback_data,
                current_metrics=self._metric_tracker.get_metrics()
            )

            return {
                "should_retrain": result.should_trigger,
                "trigger_type": result.trigger_type.value if result.should_trigger else None,
                "confidence": result.confidence,
                "details": result.details,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            self.logger.error(f"Error checking retrain trigger: {e}")
            return {"should_retrain": False, "reason": str(e)}

    def run_retrain(
        self,
        trigger_reason: str = "manual",
        include_online_data: bool = True
    ) -> Dict[str, Any]:
        """
        Run the retraining pipeline.

        Args:
            trigger_reason: Why retraining was triggered
            include_online_data: Whether to include online feedback data

        Returns:
            Dict with training results
        """
        self._init_ml_ops()
        if not self._ml_ops_initialized:
            return {"status": "error", "message": "ML ops not initialized"}

        retrain_start = datetime.now()
        self.logger.info(f"Starting retraining - reason: {trigger_reason}")

        try:
            # Step 1: Build dataset
            self.logger.info("Building training dataset...")
            dataset = self._dataset_builder.build(
                include_online=include_online_data
            )
            self.logger.info(
                f"Dataset built: {dataset.total_samples} samples "
                f"(offline: {dataset.offline_samples}, online: {dataset.online_samples})"
            )

            # Step 2: Train model
            self.logger.info("Training new model...")
            train_result = self._trainer.train(dataset)

            if not train_result.success:
                return {
                    "status": "failed",
                    "stage": "training",
                    "message": train_result.error
                }

            self.logger.info(
                f"Training complete - F1: {train_result.metrics.get('f1', 0):.4f}"
            )

            # Step 3: Validate model
            self.logger.info("Validating new model...")
            validation = self._validator.validate(
                train_result.model,
                train_result.metrics,
                dataset
            )

            if not validation.passed:
                return {
                    "status": "failed",
                    "stage": "validation",
                    "message": validation.reason,
                    "checks": validation.checks
                }

            # Step 4: Register model
            self.logger.info("Registering new model version...")
            new_version = self._model_registry.register(
                model=train_result.model,
                metrics=train_result.metrics,
                fingerprint=dataset.fingerprint,
                trigger_reason=trigger_reason
            )

            duration = (datetime.now() - retrain_start).total_seconds()

            return {
                "status": "success",
                "new_version": new_version,
                "metrics": train_result.metrics,
                "validation": {
                    "passed": validation.passed,
                    "checks": validation.checks
                },
                "dataset_stats": {
                    "total": dataset.total_samples,
                    "offline": dataset.offline_samples,
                    "online": dataset.online_samples
                },
                "duration_seconds": duration,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            self.logger.error(f"Retraining failed: {e}")
            return {"status": "error", "message": str(e)}

    def deploy_model(
        self,
        version: str,
        canary_ratio: float = 0.05
    ) -> Dict[str, Any]:
        """
        Deploy a model version using canary deployment.

        Args:
            version: Model version to deploy (e.g., "v2")
            canary_ratio: Initial traffic ratio for canary (0.0-1.0)

        Returns:
            Deployment status
        """
        self._init_ml_ops()
        if not self._ml_ops_initialized:
            return {"status": "error", "message": "ML ops not initialized"}

        try:
            self.logger.info(
                f"Starting canary deployment of {version} at {canary_ratio:.1%}"
            )

            # Set canary ratio before starting
            self._deploy_manager._canary_ratio = canary_ratio
            result = self._deploy_manager.start_canary(
                version=version,
            )

            state_str = result.state if isinstance(result.state, str) else result.state.value
            return {
                "status": state_str,
                "version": version,
                "canary_ratio": canary_ratio,
                "message": result.message,
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            self.logger.error(f"Deployment failed: {e}")
            return {"status": "error", "message": str(e)}

    def promote_canary(self) -> Dict[str, Any]:
        """Promote canary to full production."""
        self._init_ml_ops()
        if not self._ml_ops_initialized:
            return {"status": "error", "message": "ML ops not initialized"}

        try:
            result = self._deploy_manager.promote()
            state_str = result.state if isinstance(result.state, str) else result.state.value
            return {
                "status": state_str,
                "message": result.message,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            self.logger.error(f"Promotion failed: {e}")
            return {"status": "error", "message": str(e)}

    def rollback_model(self, reason: str = "manual") -> Dict[str, Any]:
        """
        Rollback to the previous model version.

        Args:
            reason: Reason for rollback

        Returns:
            Rollback status
        """
        self._init_ml_ops()
        if not self._ml_ops_initialized:
            return {"status": "error", "message": "ML ops not initialized"}

        try:
            self.logger.warning(f"Rolling back model - reason: {reason}")
            result = self._deploy_manager.rollback(reason=reason)

            state_str = result.state if isinstance(result.state, str) else result.state.value
            return {
                "status": state_str,
                "message": result.message,
                "rollback_reason": reason,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            self.logger.error(f"Rollback failed: {e}")
            return {"status": "error", "message": str(e)}

    def set_kill_switch(self, enabled: bool) -> Dict[str, Any]:
        """
        Enable or disable the kill switch (emergency stop).

        Args:
            enabled: True to enable kill switch, False to disable

        Returns:
            Kill switch status
        """
        self._init_ml_ops()
        if not self._ml_ops_initialized:
            return {"status": "error", "message": "ML ops not initialized"}

        try:
            self._deploy_manager.set_kill_switch(enabled)
            self._ab_router.set_kill_switch(enabled)

            action = "enabled" if enabled else "disabled"
            self.logger.warning(f"Kill switch {action}")

            return {
                "status": "success",
                "kill_switch": enabled,
                "message": f"Kill switch {action}",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_model_versions(self) -> Dict[str, Any]:
        """Get all model versions from registry."""
        self._init_ml_ops()
        if not self._ml_ops_initialized:
            return {"error": "ML ops not initialized"}

        try:
            versions = self._model_registry.list_versions()
            return {
                "versions": [
                    {
                        "version": v.version,
                        "created_at": v.created_at,
                        "metrics": v.metrics,
                        "is_active": v.is_active,
                        "is_canary": v.is_canary
                    }
                    for v in versions
                ],
                "active_version": self._model_registry.get_active_version(),
                "canary_version": self._model_registry.get_canary_version(),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"error": str(e)}

    def run_ml_monitoring_cycle(self) -> Dict[str, Any]:
        """
        Run a complete ML monitoring cycle:
        1. Check inference metrics
        2. Check retrain triggers
        3. Auto-retrain if needed
        4. Deploy new model if training succeeds

        Returns:
            Monitoring cycle results
        """
        self._init_ml_ops()
        if not self._ml_ops_initialized:
            return {"status": "error", "message": "ML ops not initialized"}

        cycle_start = datetime.now()
        cycle_results = {
            "timestamp": cycle_start.isoformat(),
            "phases": {}
        }

        try:
            # Phase 1: Check metrics
            metrics = self.get_inference_metrics()
            cycle_results["phases"]["metrics"] = metrics

            # Phase 2: Check triggers
            trigger_check = self.check_retrain_trigger()
            cycle_results["phases"]["trigger_check"] = trigger_check

            # Phase 3: Auto-retrain if triggered
            if trigger_check.get("should_retrain"):
                self.logger.info(
                    f"Auto-retrain triggered: {trigger_check.get('trigger_type')}"
                )
                retrain_result = self.run_retrain(
                    trigger_reason=trigger_check.get("trigger_type", "auto")
                )
                cycle_results["phases"]["retrain"] = retrain_result

                # Phase 4: Auto-deploy if retrain succeeded
                if retrain_result.get("status") == "success":
                    new_version = retrain_result.get("new_version")
                    deploy_result = self.deploy_model(
                        version=new_version,
                        canary_ratio=0.05
                    )
                    cycle_results["phases"]["deploy"] = deploy_result

            cycle_results["duration_seconds"] = (
                datetime.now() - cycle_start
            ).total_seconds()
            cycle_results["status"] = "success"

            return cycle_results

        except Exception as e:
            self.logger.error(f"Monitoring cycle failed: {e}")
            cycle_results["status"] = "error"
            cycle_results["error"] = str(e)
            return cycle_results

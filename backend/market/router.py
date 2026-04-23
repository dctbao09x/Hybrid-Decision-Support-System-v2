# -*- coding: utf-8 -*-
"""
Market Intelligence - Unified API Router
Stage 7 (I): System Architecture & Integration
FastAPI router exposing all market intelligence capabilities
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field

# Import all submodules
from .signal import (
    MarketSignalCollector,
    CrawlScheduler,
    MarketSnapshot,
    DataSource,
)
from .taxonomy import (
    TaxonomyEngine,
    SkillNode,
    TaxonomyVersion,
)
from .trends import (
    TrendDetector,
    DriftAnalyzer,
    TrendDirection,
)
from .forecast import (
    ForecastEngine,
    ForecastHorizon,
)
from .gap import (
    GapAnalyzer,
    PathOptimizer,
    UserProfile,
    CareerTarget,
    SkillLevel,
)
from .scoring import (
    ScoringAdapter,
    ScoringConfig,
)
from .evolution import (
    EvolutionOrchestrator,
    EvolutionStage,
)
from .governance import (
    GovernanceEngine,
    get_governance_engine,
    ApprovalStatus,
    ApprovalDecision,
    AuditEventType,
)

logger = logging.getLogger(__name__)

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

# --- Signal Models ---
class CrawlRequest(BaseModel):
    """Request to trigger a market data crawl."""
    sources: List[str] = Field(default_factory=lambda: ["vietnamworks", "topcv"])
    keywords: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default_factory=list)
    max_pages: int = Field(default=5, ge=1, le=50)


class SnapshotResponse(BaseModel):
    """Market snapshot response."""
    snapshot_id: str
    captured_at: str
    total_jobs: int
    sources_count: int
    top_skills: List[Dict[str, Any]]
    salary_stats: Dict[str, Any]


# --- Taxonomy Models ---
class SkillDetectionRequest(BaseModel):
    """Request to detect skills from text."""
    text: str
    context: Optional[str] = None
    threshold: float = Field(default=0.6, ge=0.0, le=1.0)


class TaxonomyUpdateRequest(BaseModel):
    """Request to update taxonomy."""
    skills_to_add: List[Dict[str, Any]] = Field(default_factory=list)
    skills_to_merge: List[Dict[str, str]] = Field(default_factory=list)
    skills_to_deprecate: List[str] = Field(default_factory=list)
    reason: str = ""


# --- Trend Models ---
class TrendQueryRequest(BaseModel):
    """Request to query skill trends."""
    skills: List[str] = Field(default_factory=list)
    time_range_days: int = Field(default=90, ge=7, le=365)


class DriftAnalysisRequest(BaseModel):
    """Request to analyze skill drift."""
    skill: str
    baseline_period_days: int = Field(default=30)
    comparison_period_days: int = Field(default=30)


# --- Forecast Models ---
class ForecastRequest(BaseModel):
    """Request to forecast skill demand."""
    skills: List[str]
    horizon: str = Field(default="6_months")  # 3_months, 6_months, 12_months
    include_confidence_bands: bool = True


# --- Gap Models ---
class GapAnalysisRequest(BaseModel):
    """Request for career gap analysis."""
    user_id: str
    current_skills: List[Dict[str, Any]]  # [{name, level, years}]
    target_role: str
    target_seniority: str = "mid"
    constraints: Dict[str, Any] = Field(default_factory=dict)


class LearningPathRequest(BaseModel):
    """Request to generate learning path."""
    user_id: str
    target_skills: List[str]
    available_hours_per_week: int = Field(default=10, ge=1, le=40)
    deadline_months: Optional[int] = None


# --- Scoring Models ---
class ScoreRequest(BaseModel):
    """Request to calculate market-adaptive score."""
    user_id: str
    skills: List[Dict[str, Any]]
    role: Optional[str] = None
    include_explanation: bool = True


class ScoringConfigUpdate(BaseModel):
    """Request to update scoring configuration."""
    base_weights: Optional[Dict[str, float]] = None
    trend_bonus_factor: float = Field(default=0.1, ge=0.0, le=0.5)
    demand_weight_factor: float = Field(default=0.2, ge=0.0, le=0.5)
    reason: str = ""


# --- Evolution Models ---
class EvolutionTriggerRequest(BaseModel):
    """Request to trigger evolution cycle."""
    force: bool = False
    skip_validation: bool = False
    stages_to_run: List[str] = Field(default_factory=list)


# --- Governance Models ---
class ApprovalDecisionRequest(BaseModel):
    """Request to submit approval decision."""
    decision: str  # approve, reject, defer, escalate
    comment: str = ""


class EmergencyOverrideRequest(BaseModel):
    """Request to create emergency override."""
    reason: str
    justification: str
    override_type: str
    duration_hours: int = Field(default=4, ge=1, le=24)
    affected_gates: List[str] = Field(default_factory=list)
    secondary_authorization: Optional[str] = None


# =============================================================================
# API ROUTER
# =============================================================================

# Note: Prefix is set in router_registry.py as /api/v1/market
router = APIRouter(tags=["market-intelligence"])

# Singleton instances (lazy initialization)
_signal_collector: Optional[MarketSignalCollector] = None
_crawl_scheduler: Optional[CrawlScheduler] = None
_taxonomy_engine: Optional[TaxonomyEngine] = None
_trend_detector: Optional[TrendDetector] = None
_drift_analyzer: Optional[DriftAnalyzer] = None
_forecast_engine: Optional[ForecastEngine] = None
_gap_analyzer: Optional[GapAnalyzer] = None
_path_optimizer: Optional[PathOptimizer] = None
_scoring_adapter: Optional[ScoringAdapter] = None
_evolution_orchestrator: Optional[EvolutionOrchestrator] = None


def get_signal_collector() -> MarketSignalCollector:
    global _signal_collector
    if _signal_collector is None:
        _signal_collector = MarketSignalCollector()
    return _signal_collector


def get_crawl_scheduler() -> CrawlScheduler:
    global _crawl_scheduler
    if _crawl_scheduler is None:
        _crawl_scheduler = CrawlScheduler(get_signal_collector())
    return _crawl_scheduler


def get_taxonomy_engine() -> TaxonomyEngine:
    global _taxonomy_engine
    if _taxonomy_engine is None:
        _taxonomy_engine = TaxonomyEngine()
    return _taxonomy_engine


def get_trend_detector() -> TrendDetector:
    global _trend_detector
    if _trend_detector is None:
        _trend_detector = TrendDetector()
    return _trend_detector


def get_drift_analyzer() -> DriftAnalyzer:
    global _drift_analyzer
    if _drift_analyzer is None:
        _drift_analyzer = DriftAnalyzer()
    return _drift_analyzer


def get_forecast_engine() -> ForecastEngine:
    global _forecast_engine
    if _forecast_engine is None:
        _forecast_engine = ForecastEngine()
    return _forecast_engine


def get_gap_analyzer() -> GapAnalyzer:
    global _gap_analyzer
    if _gap_analyzer is None:
        _gap_analyzer = GapAnalyzer()
    return _gap_analyzer


def get_path_optimizer() -> PathOptimizer:
    global _path_optimizer
    if _path_optimizer is None:
        _path_optimizer = PathOptimizer()
    return _path_optimizer


def get_scoring_adapter() -> ScoringAdapter:
    global _scoring_adapter
    if _scoring_adapter is None:
        _scoring_adapter = ScoringAdapter()
    return _scoring_adapter


def get_evolution_orchestrator() -> EvolutionOrchestrator:
    global _evolution_orchestrator
    if _evolution_orchestrator is None:
        _evolution_orchestrator = EvolutionOrchestrator()
    return _evolution_orchestrator


# =============================================================================
# HEALTH & STATUS ENDPOINTS
# =============================================================================

@router.get("/health")
async def health_check():
    """Check health of market intelligence system."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "components": {
            "signal_collector": "available",
            "taxonomy_engine": "available",
            "trend_detector": "available",
            "forecast_engine": "available",
            "gap_analyzer": "available",
            "scoring_adapter": "available",
            "evolution_orchestrator": "available",
            "governance_engine": "available",
        }
    }


@router.get("/status")
async def system_status():
    """Get detailed system status."""
    governance = get_governance_engine()
    governance_status = governance.get_governance_status()
    
    evolution = get_evolution_orchestrator()
    evolution_status = {
        "running": evolution._running,
        "total_cycles": len(evolution._cycle_history),
        "last_cycle": evolution._cycle_history[-1].to_dict() if evolution._cycle_history else None,
    }
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "governance": governance_status,
        "evolution": evolution_status,
        "uptime_seconds": 0,  # Would need to track start time
    }


# =============================================================================
# SIGNAL ENDPOINTS
# =============================================================================

@router.post("/signal/crawl")
async def trigger_crawl(request: CrawlRequest, background_tasks: BackgroundTasks):
    """Trigger a market data crawl."""
    collector = get_signal_collector()
    
    # Parse sources
    sources = []
    for source_name in request.sources:
        try:
            sources.append(DataSource(source_name.lower()))
        except ValueError:
            raise HTTPException(400, f"Unknown source: {source_name}")
    
    # Schedule in background
    async def run_crawl():
        for source in sources:
            await collector.crawl_source(
                source=source,
                keywords=request.keywords or None,
                locations=request.locations or None,
                max_pages=request.max_pages,
            )
    
    background_tasks.add_task(run_crawl)
    
    return {
        "status": "crawl_scheduled",
        "sources": request.sources,
        "keywords": request.keywords,
    }


@router.get("/signal/snapshot")
async def get_latest_snapshot():
    """Get the latest market snapshot."""
    collector = get_signal_collector()
    snapshot = collector.create_snapshot()
    
    if not snapshot:
        raise HTTPException(404, "No snapshot available")
    
    return {
        "snapshot_id": snapshot.snapshot_id,
        "captured_at": snapshot.captured_at.isoformat(),
        "total_jobs": snapshot.total_jobs,
        "sources_count": snapshot.sources_count,
        "top_skills": snapshot.top_skills[:20],
        "salary_stats": snapshot.salary_stats,
    }


@router.get("/signal/scheduler/status")
async def get_scheduler_status():
    """Get crawl scheduler status."""
    scheduler = get_crawl_scheduler()
    return {
        "running": scheduler._running,
        "pending_tasks": len(scheduler._task_queue),
        "completed_tasks": scheduler._completed_count,
    }


# =============================================================================
# TAXONOMY ENDPOINTS
# =============================================================================

@router.post("/taxonomy/detect-skills")
async def detect_skills(request: SkillDetectionRequest):
    """Detect skills from text."""
    engine = get_taxonomy_engine()
    skills = engine.detect_skills(request.text, threshold=request.threshold)
    
    return {
        "detected_skills": [
            {"name": s.name, "category": s.category, "confidence": s.confidence}
            for s in skills
        ],
        "input_length": len(request.text),
    }


@router.get("/taxonomy/skills")
async def list_skills(
    category: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
):
    """List skills in taxonomy."""
    engine = get_taxonomy_engine()
    skills = engine.get_all_skills()
    
    if category:
        skills = [s for s in skills if s.category == category]
    if status:
        skills = [s for s in skills if s.status.value == status]
    
    return {
        "skills": [s.to_dict() for s in skills[:limit]],
        "total": len(skills),
    }


@router.get("/taxonomy/version")
async def get_taxonomy_version():
    """Get current taxonomy version."""
    engine = get_taxonomy_engine()
    version = engine.get_current_version()
    
    if not version:
        return {"version": None}
    
    return version.to_dict()


@router.post("/taxonomy/merge-candidates")
async def get_merge_candidates(threshold: float = Query(default=0.85, ge=0.5, le=1.0)):
    """Get skill merge candidates based on similarity."""
    engine = get_taxonomy_engine()
    candidates = engine.find_merge_candidates(threshold=threshold)
    
    return {
        "candidates": [c.to_dict() for c in candidates],
        "total": len(candidates),
    }


@router.get("/taxonomy/clusters")
async def get_skill_clusters(min_cluster_size: int = Query(default=3, ge=2)):
    """Get skill clusters."""
    engine = get_taxonomy_engine()
    clusters = engine.cluster_skills(min_cluster_size=min_cluster_size)
    
    return {
        "clusters": [c.to_dict() for c in clusters],
        "total": len(clusters),
    }


# =============================================================================
# TREND ENDPOINTS
# =============================================================================

@router.post("/trends/analyze")
async def analyze_trends(request: TrendQueryRequest):
    """Analyze skill trends."""
    detector = get_trend_detector()
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=request.time_range_days)
    
    results = []
    for skill in request.skills:
        trend = detector.detect_trend(skill, start_date, end_date)
        results.append(trend.to_dict())
    
    return {
        "trends": results,
        "time_range": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        }
    }


@router.get("/trends/snapshot")
async def get_trend_snapshot():
    """Get current trend snapshot."""
    detector = get_trend_detector()
    snapshot = detector.create_snapshot()
    
    return snapshot.to_dict()


@router.post("/trends/drift")
async def analyze_drift(request: DriftAnalysisRequest):
    """Analyze skill drift."""
    analyzer = get_drift_analyzer()
    drift = analyzer.analyze_drift(
        skill=request.skill,
        baseline_days=request.baseline_period_days,
        comparison_days=request.comparison_period_days,
    )
    
    return drift.to_dict()


@router.get("/trends/emerging")
async def get_emerging_skills(limit: int = Query(default=20, ge=1, le=100)):
    """Get emerging skills."""
    detector = get_trend_detector()
    emerging = detector.get_emerging_skills(limit=limit)
    
    return {
        "emerging_skills": [e.to_dict() for e in emerging],
        "as_of": datetime.utcnow().isoformat(),
    }


@router.get("/trends/declining")
async def get_declining_skills(limit: int = Query(default=20, ge=1, le=100)):
    """Get declining skills."""
    detector = get_trend_detector()
    declining = detector.get_declining_skills(limit=limit)
    
    return {
        "declining_skills": [d.to_dict() for d in declining],
        "as_of": datetime.utcnow().isoformat(),
    }


# =============================================================================
# FORECAST ENDPOINTS
# =============================================================================

@router.post("/forecast/demand")
async def forecast_demand(request: ForecastRequest):
    """Forecast skill demand."""
    engine = get_forecast_engine()
    
    # Parse horizon
    horizon_map = {
        "3_months": ForecastHorizon.THREE_MONTHS,
        "6_months": ForecastHorizon.SIX_MONTHS,
        "12_months": ForecastHorizon.TWELVE_MONTHS,
    }
    horizon = horizon_map.get(request.horizon, ForecastHorizon.SIX_MONTHS)
    
    forecasts = []
    for skill in request.skills:
        forecast = engine.forecast_skill_demand(
            skill=skill,
            horizon=horizon,
            include_confidence_bands=request.include_confidence_bands,
        )
        forecasts.append(forecast.to_dict())
    
    return {
        "forecasts": forecasts,
        "horizon": request.horizon,
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/forecast/snapshot")
async def get_forecast_snapshot():
    """Get current forecast snapshot."""
    engine = get_forecast_engine()
    snapshot = engine.create_snapshot()
    
    return snapshot.to_dict()


@router.get("/forecast/top-growth")
async def get_top_growth_skills(
    horizon: str = Query(default="6_months"),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Get skills with highest forecasted growth."""
    engine = get_forecast_engine()
    
    horizon_map = {
        "3_months": ForecastHorizon.THREE_MONTHS,
        "6_months": ForecastHorizon.SIX_MONTHS,
        "12_months": ForecastHorizon.TWELVE_MONTHS,
    }
    h = horizon_map.get(horizon, ForecastHorizon.SIX_MONTHS)
    
    top_growth = engine.get_top_growth_skills(horizon=h, limit=limit)
    
    return {
        "top_growth_skills": [s.to_dict() for s in top_growth],
        "horizon": horizon,
    }


# =============================================================================
# GAP ANALYSIS ENDPOINTS
# =============================================================================

@router.post("/gap/analyze")
async def analyze_gap(request: GapAnalysisRequest):
    """Perform career gap analysis."""
    analyzer = get_gap_analyzer()
    
    # Build user profile
    user_skills = {}
    for skill_data in request.current_skills:
        level_map = {
            "none": SkillLevel.NONE,
            "beginner": SkillLevel.BEGINNER,
            "intermediate": SkillLevel.INTERMEDIATE,
            "advanced": SkillLevel.ADVANCED,
            "expert": SkillLevel.EXPERT,
        }
        level = level_map.get(skill_data.get("level", "beginner").lower(), SkillLevel.BEGINNER)
        user_skills[skill_data["name"]] = level
    
    profile = UserProfile(
        user_id=request.user_id,
        current_skills=user_skills,
        years_experience={s["name"]: s.get("years", 1) for s in request.current_skills},
    )
    
    target = CareerTarget(
        role=request.target_role,
        seniority=request.target_seniority,
    )
    
    result = analyzer.analyze(profile, target)
    
    return result.to_dict()


@router.post("/gap/learning-path")
async def generate_learning_path(request: LearningPathRequest):
    """Generate optimized learning path."""
    optimizer = get_path_optimizer()
    
    path = optimizer.optimize_path(
        user_id=request.user_id,
        target_skills=request.target_skills,
        hours_per_week=request.available_hours_per_week,
        deadline_months=request.deadline_months,
    )
    
    return path.to_dict()


@router.get("/gap/readiness/{user_id}/{target_role}")
async def check_readiness(user_id: str, target_role: str):
    """Check user readiness for target role."""
    analyzer = get_gap_analyzer()
    readiness = analyzer.check_readiness(user_id, target_role)
    
    return readiness


# =============================================================================
# SCORING ENDPOINTS
# =============================================================================

@router.post("/scoring/calculate")
async def calculate_score(request: ScoreRequest):
    """Calculate market-adaptive score."""
    adapter = get_scoring_adapter()
    
    skills_dict = {s["name"]: s.get("level", 1) for s in request.skills}
    
    score, explanation = adapter.calculate_score(
        user_id=request.user_id,
        skills=skills_dict,
        role=request.role,
        include_explanation=request.include_explanation,
    )
    
    return {
        "score": score,
        "explanation": explanation.to_dict() if explanation else None,
    }


@router.get("/scoring/config")
async def get_scoring_config():
    """Get current scoring configuration."""
    adapter = get_scoring_adapter()
    version = adapter.get_current_version()
    
    return version.to_dict() if version else {"version": None}


@router.post("/scoring/config")
async def update_scoring_config(request: ScoringConfigUpdate):
    """Update scoring configuration (requires approval)."""
    adapter = get_scoring_adapter()
    governance = get_governance_engine()
    
    # Evaluate through governance
    evaluation = governance.evaluate_change(
        change_type="scoring_update",
        change_id=f"scoring_config_{datetime.utcnow().timestamp()}",
        change_summary=f"Scoring config update: {request.reason}",
        change_details=request.dict(),
        context={
            "confidence": 0.9,
            "affected_users": 1000,
            "rollback_possible": True,
        },
    )
    
    if evaluation["decision"] == "auto_approved":
        # Apply change
        adapter.update_config(
            base_weights=request.base_weights,
            trend_bonus_factor=request.trend_bonus_factor,
            demand_weight_factor=request.demand_weight_factor,
            reason=request.reason,
        )
        
        return {
            "status": "applied",
            "governance": evaluation,
        }
    
    return {
        "status": evaluation["decision"],
        "governance": evaluation,
    }


@router.get("/scoring/versions")
async def list_scoring_versions(limit: int = Query(default=10, ge=1, le=50)):
    """List scoring config versions."""
    adapter = get_scoring_adapter()
    versions = adapter.get_version_history(limit=limit)
    
    return {
        "versions": [v.to_dict() for v in versions],
        "total": len(versions),
    }


@router.post("/scoring/rollback/{version_id}")
async def rollback_scoring(version_id: str):
    """Rollback to a previous scoring version."""
    adapter = get_scoring_adapter()
    governance = get_governance_engine()
    
    # Evaluate through governance
    evaluation = governance.evaluate_change(
        change_type="scoring_rollback",
        change_id=f"scoring_rollback_{version_id}",
        change_summary=f"Rollback scoring to version {version_id}",
        change_details={"target_version": version_id},
        context={
            "confidence": 1.0,
            "affected_users": 1000,
            "rollback_possible": True,
        },
    )
    
    if evaluation["decision"] == "auto_approved":
        adapter.rollback_to_version(version_id)
        return {"status": "rolled_back", "version": version_id}
    
    return {
        "status": evaluation["decision"],
        "governance": evaluation,
    }


# =============================================================================
# EVOLUTION ENDPOINTS
# =============================================================================

@router.post("/evolution/trigger")
async def trigger_evolution(request: EvolutionTriggerRequest, background_tasks: BackgroundTasks):
    """Trigger an evolution cycle."""
    orchestrator = get_evolution_orchestrator()
    governance = get_governance_engine()
    
    # Evaluate through governance
    evaluation = governance.evaluate_change(
        change_type="evolution_cycle",
        change_id=f"evolution_{datetime.utcnow().timestamp()}",
        change_summary="Trigger evolution cycle",
        change_details=request.dict(),
        context={
            "confidence": 0.95,
            "rollback_possible": True,
            "affected_components": ["taxonomy", "trends", "scoring"],
        },
    )
    
    if evaluation["decision"] == "auto_approved":
        # Trigger in background
        async def run_cycle():
            await orchestrator.trigger_cycle(
                force=request.force,
                skip_validation=request.skip_validation,
            )
        
        background_tasks.add_task(run_cycle)
        
        return {
            "status": "cycle_triggered",
            "governance": evaluation,
        }
    
    return {
        "status": evaluation["decision"],
        "governance": evaluation,
    }


@router.get("/evolution/status")
async def get_evolution_status():
    """Get evolution orchestrator status."""
    orchestrator = get_evolution_orchestrator()
    
    return {
        "running": orchestrator._running,
        "current_cycle": orchestrator._current_cycle.to_dict() if orchestrator._current_cycle else None,
        "total_cycles": len(orchestrator._cycle_history),
        "state": orchestrator.get_state().to_dict() if orchestrator.get_state() else None,
    }


@router.get("/evolution/history")
async def get_evolution_history(limit: int = Query(default=10, ge=1, le=50)):
    """Get evolution cycle history."""
    orchestrator = get_evolution_orchestrator()
    history = orchestrator._cycle_history[-limit:]
    
    return {
        "cycles": [c.to_dict() for c in history],
        "total": len(orchestrator._cycle_history),
    }


@router.post("/evolution/start")
async def start_evolution_scheduler(background_tasks: BackgroundTasks):
    """Start the evolution scheduler."""
    orchestrator = get_evolution_orchestrator()
    
    if orchestrator._running:
        raise HTTPException(400, "Evolution scheduler already running")
    
    background_tasks.add_task(orchestrator.start)
    
    return {"status": "scheduler_starting"}


@router.post("/evolution/stop")
async def stop_evolution_scheduler():
    """Stop the evolution scheduler."""
    orchestrator = get_evolution_orchestrator()
    orchestrator.stop()
    
    return {"status": "scheduler_stopped"}


# =============================================================================
# GOVERNANCE ENDPOINTS
# =============================================================================

@router.get("/governance/status")
async def get_governance_status():
    """Get governance status."""
    governance = get_governance_engine()
    return governance.get_governance_status()


@router.get("/governance/approvals/pending")
async def get_pending_approvals():
    """Get pending approval requests."""
    governance = get_governance_engine()
    pending = governance.approval_workflow.get_pending_requests()
    
    return {
        "pending": [p.to_dict() for p in pending],
        "total": len(pending),
    }


@router.post("/governance/approvals/{request_id}/decide")
async def submit_approval_decision(
    request_id: str,
    decision_request: ApprovalDecisionRequest,
    user_id: str = Query(...),
    user_role: str = Query(default="admin"),
):
    """Submit approval decision."""
    governance = get_governance_engine()
    
    decision_map = {
        "approve": ApprovalDecision.APPROVE,
        "reject": ApprovalDecision.REJECT,
        "defer": ApprovalDecision.DEFER,
        "escalate": ApprovalDecision.ESCALATE,
    }
    
    decision = decision_map.get(decision_request.decision.lower())
    if not decision:
        raise HTTPException(400, f"Invalid decision: {decision_request.decision}")
    
    updated_request = governance.approval_workflow.submit_decision(
        request_id=request_id,
        decision=decision,
        user_id=user_id,
        user_role=user_role,
        comment=decision_request.comment,
    )
    
    return updated_request.to_dict()


@router.post("/governance/override")
async def create_emergency_override(
    request: EmergencyOverrideRequest,
    authorized_by: str = Query(...),
    authorizer_role: str = Query(default="admin"),
):
    """Create emergency override."""
    governance = get_governance_engine()
    
    override = governance.create_emergency_override(
        reason=request.reason,
        justification=request.justification,
        override_type=request.override_type,
        authorized_by=authorized_by,
        authorizer_role=authorizer_role,
        duration_hours=request.duration_hours,
        affected_gates=request.affected_gates,
        secondary_authorization=request.secondary_authorization,
    )
    
    return override.to_dict()


@router.delete("/governance/override/{override_id}")
async def revoke_emergency_override(
    override_id: str,
    revoked_by: str = Query(...),
    reason: str = Query(default=""),
):
    """Revoke emergency override."""
    governance = get_governance_engine()
    governance.revoke_override(override_id, revoked_by, reason)
    
    return {"status": "revoked", "override_id": override_id}


@router.get("/governance/audit")
async def query_audit_log(
    event_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    component: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
):
    """Query audit log."""
    governance = get_governance_engine()
    
    event_types = None
    if event_type:
        try:
            event_types = [AuditEventType(event_type)]
        except ValueError:
            raise HTTPException(400, f"Invalid event type: {event_type}")
    
    start = datetime.fromisoformat(start_time) if start_time else None
    end = datetime.fromisoformat(end_time) if end_time else None
    
    entries = governance.audit_logger.query(
        event_types=event_types,
        actor_id=actor_id,
        component=component,
        start_time=start,
        end_time=end,
        limit=limit,
    )
    
    return {
        "entries": [e.to_dict() for e in entries],
        "total": len(entries),
    }


@router.get("/governance/audit/integrity")
async def verify_audit_integrity():
    """Verify audit log integrity."""
    governance = get_governance_engine()
    is_valid, errors = governance.audit_logger.verify_integrity()
    
    return {
        "is_valid": is_valid,
        "errors": errors,
        "checked_at": datetime.utcnow().isoformat(),
    }


@router.get("/governance/compliance/violations")
async def get_compliance_violations():
    """Get open compliance violations."""
    governance = get_governance_engine()
    violations = governance.compliance_engine.get_open_violations()
    
    return {
        "violations": [v.to_dict() for v in violations],
        "total": len(violations),
    }

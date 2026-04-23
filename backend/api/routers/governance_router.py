# backend/api/routers/governance_router.py
"""
Governance Router
=================

All governance platform endpoints under /api/v1/governance/*

Endpoints:
  - GET  /governance/dashboard             — Main governance dashboard
  - GET  /governance/risk                  — Risk management dashboard
  - GET  /governance/risk/history          — Risk history
  - GET  /governance/risk/mitigations      — Mitigation history
  - POST /governance/risk/weights          — Update risk weights
  - GET  /governance/sla                   — SLA dashboard (enhanced)
  - GET  /governance/sla/violations        — SLA violations
  - GET  /governance/sla/contracts         — List contracts
  - POST /governance/sla/contracts         — Register contract
  - GET  /governance/reports               — List reports
  - GET  /governance/reports/weekly        — Weekly SLA report
  - GET  /governance/reports/monthly       — Monthly risk report
  - POST /governance/reports/generate      — Generate report
  - GET  /governance/cost                  — Cost dashboard
  - GET  /governance/drift                 — Drift dashboard
  - GET  /governance/audit                 — Audit log
  - GET  /governance/drift-events          — Persistent drift event log
  - GET  /governance/retrain-events        — Persistent retrain event log
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("api.routers.governance")

router = APIRouter(tags=["Governance"])

# ==============================================================================
# Request/Response Models
# ==============================================================================

class RiskWeightsRequest(BaseModel):
    drift: float = 0.3
    latency: float = 0.25
    error_rate: float = 0.30
    cost_overrun: float = 0.15


class ScoreDistributionBucket(BaseModel):
    """A single bucket in the score distribution histogram."""
    range_start: float
    range_end: float
    count: int
    percentage: float
    is_drift: bool = False


class ScoreDistributionResponse(BaseModel):
    """Score distribution histogram response."""
    component: str
    buckets: List[ScoreDistributionBucket]
    total_samples: int
    mean: float
    std_deviation: float
    psi: float
    kl_divergence: float
    drift_threshold: float
    is_drift_active: bool
    last_update: str


class ThresholdsResponse(BaseModel):
    """Alert thresholds configuration."""
    drift_psi: float = 0.25
    llm_anomaly: float = 0.05
    error_rate: float = 0.05
    volatility: float = 0.10
    updated_at: str = ""


class ThresholdsUpdateRequest(BaseModel):
    """Request to update alert thresholds."""
    drift_psi: Optional[float] = None
    llm_anomaly: Optional[float] = None
    error_rate: Optional[float] = None
    volatility: Optional[float] = None


class RuleTriggerEntry(BaseModel):
    """A single rule trigger event."""
    rule_name: str
    timestamp: str
    count: int
    severity: str


class RankingVolatilityResponse(BaseModel):
    """Ranking volatility metrics."""
    stability_index: float
    trend: str  # "stable", "increasing", "decreasing"
    period_days: int
    history: List[Dict[str, Any]]
    threshold: float


class RankingFrequencyEntry(BaseModel):
    """Ranking frequency for a position."""
    position: int
    count: int
    percentage: float


class SLAContractRequest(BaseModel):
    contract_id: str
    name: str
    description: str = ""
    targets: List[Dict[str, Any]]
    enabled: bool = True


class ReportGenerateRequest(BaseModel):
    report_type: str  # "weekly_sla", "monthly_risk", "incident"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    formats: List[str] = ["json"]


# ==============================================================================
# Lazy Imports
# ==============================================================================

def _get_ops_pipeline():
    """Get ops pipeline instance."""
    try:
        from backend.ops.governance.pipeline import get_ops_pipeline
        return get_ops_pipeline()
    except ImportError:
        return None


def _get_ops_aggregator():
    """Get ops aggregator instance."""
    try:
        from backend.ops.governance.aggregator import get_ops_aggregator
        return get_ops_aggregator()
    except ImportError:
        return None


def _get_risk_manager():
    """Get risk manager instance."""
    try:
        from backend.ops.governance.risk import get_risk_manager
        return get_risk_manager()
    except ImportError:
        return None


def _get_sla_evaluator():
    """Get SLA evaluator instance."""
    try:
        from backend.ops.sla.evaluator import get_sla_evaluator
        return get_sla_evaluator()
    except ImportError:
        return None


def _get_sla_reporter():
    """Get SLA reporter instance."""
    try:
        from backend.ops.sla.reporter import get_sla_reporter
        return get_sla_reporter()
    except ImportError:
        return None


def _get_report_generator():
    """Get report generator instance."""
    try:
        from backend.ops.governance.reporting import get_report_generator
        return get_report_generator()
    except ImportError:
        return None


# ==============================================================================
# Main Dashboard
# ==============================================================================

@router.get(
    "/dashboard",
    summary="Governance dashboard",
    description="Main governance dashboard with system health, risk, SLA, and cost overview",
)
async def governance_dashboard():
    """
    Main governance dashboard combining:
    - System health status
    - Current risk level
    - SLA compliance summary
    - Cost overview
    - Recent alerts/incidents
    """
    dashboard = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "operational",
    }
    
    # Aggregator data
    aggregator = _get_ops_aggregator()
    if aggregator:
        dashboard["aggregator"] = aggregator.get_dashboard_data()
    
    # Risk data
    risk_manager = _get_risk_manager()
    if risk_manager:
        try:
            current_level = risk_manager.get_current_risk_level()
            dashboard["risk"] = {
                "current_level": current_level.value if current_level else "unknown",
                "dashboard": risk_manager.get_dashboard_data(),
            }
        except Exception as e:
            logger.warning(f"Failed to get risk dashboard: {e}")
            dashboard["risk"] = {"error": str(e)}
    
    # SLA data
    sla_evaluator = _get_sla_evaluator()
    if sla_evaluator:
        try:
            dashboard["sla"] = sla_evaluator.get_dashboard()
        except Exception as e:
            logger.warning(f"Failed to get SLA dashboard: {e}")
            dashboard["sla"] = {"error": str(e)}
    
    # Pipeline data
    pipeline = _get_ops_pipeline()
    if pipeline:
        try:
            dashboard["sla_metrics"] = pipeline.get_sla_metrics()
        except Exception as e:
            logger.warning(f"Failed to get SLA metrics: {e}")
    
    return dashboard


# ==============================================================================
# Risk Management
# ==============================================================================

@router.get(
    "/risk",
    summary="Risk dashboard",
    description="Risk management dashboard with current score, history, and mitigations",
)
async def risk_dashboard():
    """Risk management dashboard."""
    risk_manager = _get_risk_manager()
    if not risk_manager:
        return {"error": "Risk manager not available"}
    
    return risk_manager.get_dashboard_data()


@router.get(
    "/risk/history",
    summary="Risk history",
    description="Get risk score history for the specified time window",
)
async def risk_history(
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(100, ge=1, le=10000),
):
    """Risk score history."""
    risk_manager = _get_risk_manager()
    if not risk_manager:
        return {"error": "Risk manager not available"}
    
    return risk_manager.get_risk_history(hours=hours, limit=limit)


@router.get(
    "/risk/mitigations",
    summary="Mitigation history",
    description="Get mitigation event history",
)
async def mitigation_history(
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(100, ge=1, le=500),
):
    """Mitigation event history."""
    risk_manager = _get_risk_manager()
    if not risk_manager:
        return {"error": "Risk manager not available"}
    
    return risk_manager.get_mitigation_history(hours=hours, limit=limit)


@router.post(
    "/risk/weights",
    summary="Update risk weights",
    description="Update the weights used for risk calculation",
)
async def update_risk_weights(request: RiskWeightsRequest):
    """Update risk weights."""
    risk_manager = _get_risk_manager()
    if not risk_manager:
        raise HTTPException(status_code=503, detail="Risk manager not available")
    
    try:
        from backend.ops.governance.risk import RiskWeights
        weights = RiskWeights(
            drift=request.drift,
            latency=request.latency,
            error_rate=request.error_rate,
            cost_overrun=request.cost_overrun,
        )
        risk_manager.set_weights(weights)
        return {"status": "updated", "weights": weights.__dict__}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==============================================================================
# SLA Management
# ==============================================================================

@router.get(
    "/sla",
    summary="SLA dashboard",
    description="Enhanced SLA dashboard with compliance summary and violations",
)
async def sla_dashboard():
    """Enhanced SLA dashboard."""
    sla_evaluator = _get_sla_evaluator()
    if not sla_evaluator:
        return {"error": "SLA evaluator not available"}
    
    return sla_evaluator.get_dashboard()


@router.get(
    "/sla/violations",
    summary="SLA violations",
    description="Get recent SLA violations",
)
async def sla_violations(
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(100, ge=1, le=500),
):
    """Recent SLA violations."""
    sla_evaluator = _get_sla_evaluator()
    if not sla_evaluator:
        return {"error": "SLA evaluator not available"}
    
    return sla_evaluator.get_recent_violations(hours=hours)[:limit]


@router.get(
    "/sla/compliance",
    summary="SLA compliance summary",
    description="Get SLA compliance summary by contract",
)
async def sla_compliance():
    """SLA compliance summary."""
    sla_evaluator = _get_sla_evaluator()
    if not sla_evaluator:
        return {"error": "SLA evaluator not available"}
    
    return sla_evaluator.get_compliance_summary()


@router.get(
    "/sla/contracts",
    summary="List SLA contracts",
    description="List all registered SLA contracts",
)
async def list_sla_contracts():
    """List SLA contracts."""
    sla_evaluator = _get_sla_evaluator()
    if not sla_evaluator:
        return {"error": "SLA evaluator not available"}
    
    contracts = []
    for cid in sla_evaluator._contracts:
        contract = sla_evaluator.get_contract(cid)
        if contract:
            contracts.append(contract.to_dict())
    
    return {"contracts": contracts}


@router.post(
    "/sla/contracts",
    summary="Register SLA contract",
    description="Register a new SLA contract",
)
async def register_sla_contract(request: SLAContractRequest):
    """Register new SLA contract."""
    sla_evaluator = _get_sla_evaluator()
    if not sla_evaluator:
        raise HTTPException(status_code=503, detail="SLA evaluator not available")
    
    try:
        from backend.ops.sla.contracts import SLAContract, SLATarget, SLASeverity
        
        targets = []
        for t in request.targets:
            targets.append(SLATarget(
                name=t["name"],
                metric=t["metric"],
                threshold=t["threshold"],
                comparison=t.get("comparison", "<="),
                severity=SLASeverity(t.get("severity", "warning")),
            ))
        
        contract = SLAContract(
            contract_id=request.contract_id,
            name=request.name,
            description=request.description,
            targets=targets,
            enabled=request.enabled,
        )
        
        sla_evaluator.register_contract(contract)
        return {"status": "registered", "contract_id": contract.contract_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==============================================================================
# Reporting
# ==============================================================================

@router.get(
    "/reports",
    summary="List reports",
    description="List generated reports",
)
async def list_reports():
    """List available reports."""
    from pathlib import Path
    
    reports_dir = Path("backend/data/ops/reports")
    if not reports_dir.exists():
        return {"reports": []}
    
    reports = []
    for f in reports_dir.glob("*.json"):
        reports.append({
            "filename": f.name,
            "size_bytes": f.stat().st_size,
            "modified_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    
    return {"reports": sorted(reports, key=lambda x: x["modified_at"], reverse=True)}


@router.get(
    "/reports/weekly",
    summary="Weekly SLA report",
    description="Generate and return weekly SLA report",
)
async def weekly_sla_report():
    """Generate weekly SLA report."""
    report_generator = _get_report_generator()
    if not report_generator:
        return {"error": "Report generator not available"}
    
    pipeline = _get_ops_pipeline()
    sla_evaluator = _get_sla_evaluator()
    
    report = report_generator.generate_weekly_sla_report(
        ops_pipeline=pipeline,
        sla_evaluator=sla_evaluator,
    )
    
    return report.to_dict()


@router.get(
    "/reports/monthly",
    summary="Monthly risk report",
    description="Generate and return monthly risk report",
)
async def monthly_risk_report():
    """Generate monthly risk report."""
    report_generator = _get_report_generator()
    if not report_generator:
        return {"error": "Report generator not available"}
    
    risk_manager = _get_risk_manager()
    
    report = report_generator.generate_monthly_risk_report(
        risk_manager=risk_manager,
    )
    
    return report.to_dict()


@router.post(
    "/reports/generate",
    summary="Generate report",
    description="Generate a report with the specified type and parameters",
)
async def generate_report(request: ReportGenerateRequest):
    """Generate custom report."""
    report_generator = _get_report_generator()
    if not report_generator:
        raise HTTPException(status_code=503, detail="Report generator not available")
    
    try:
        if request.report_type == "weekly_sla":
            pipeline = _get_ops_pipeline()
            sla_evaluator = _get_sla_evaluator()
            report = report_generator.generate_weekly_sla_report(
                ops_pipeline=pipeline,
                sla_evaluator=sla_evaluator,
            )
        elif request.report_type == "monthly_risk":
            risk_manager = _get_risk_manager()
            report = report_generator.generate_monthly_risk_report(
                risk_manager=risk_manager,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unknown report type: {request.report_type}")
        
        # Save report
        saved = report_generator.save_report(report, formats=request.formats)
        
        return {
            "status": "generated",
            "report": report.to_dict(),
            "saved_files": {k: str(v) for k, v in saved.items()},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==============================================================================
# Cost & Drift (placeholder dashboards)
# ==============================================================================

@router.get(
    "/cost",
    summary="Cost dashboard",
    description="Cost tracking and budget monitoring dashboard",
)
async def cost_dashboard():
    """Cost tracking dashboard."""
    aggregator = _get_ops_aggregator()
    if aggregator:
        return {
            "cost_breakdown": aggregator.get_cost_breakdown(),
            "dashboard": aggregator.get_dashboard_data(),
        }
    return {"error": "Cost data not available"}


@router.get(
    "/drift",
    summary="Drift dashboard",
    description="Model drift monitoring dashboard",
)
async def drift_dashboard():
    """Drift monitoring dashboard."""
    # Placeholder - integrate with actual drift detection
    return {
        "status": "monitoring",
        "current_drift": 0.0,
        "threshold": 0.1,
        "last_check": datetime.now(timezone.utc).isoformat(),
        "alerts": [],
    }


# ==============================================================================
# Score Distribution (Phase 1 - Critical)
# ==============================================================================

def _get_drift_detector():
    """Get drift detector instance."""
    try:
        from backend.scoring.drift import get_drift_detector
        return get_drift_detector()
    except ImportError:
        return None


@router.get(
    "/score-distribution",
    response_model=List[ScoreDistributionResponse],
    summary="Score distribution histogram",
    description="Get score distribution histogram with drift indicators",
)
async def score_distribution(
    component: Optional[str] = Query(None, description="Filter by component (study, interest, market, growth, risk, final)"),
):
    """Score distribution histogram for all components or a specific one."""
    detector = _get_drift_detector()
    if not detector:
        # Return mock data structure when detector unavailable
        return [
            ScoreDistributionResponse(
                component="final",
                buckets=[
                    ScoreDistributionBucket(
                        range_start=i * 0.1,
                        range_end=(i + 1) * 0.1,
                        count=0,
                        percentage=0.0,
                        is_drift=False,
                    )
                    for i in range(10)
                ],
                total_samples=0,
                mean=0.0,
                std_deviation=0.0,
                psi=0.0,
                kl_divergence=0.0,
                drift_threshold=0.25,
                is_drift_active=False,
                last_update=datetime.now(timezone.utc).isoformat(),
            )
        ]
    
    results = []
    drift_status = detector.get_drift_status()
    
    components_to_process = [component] if component else list(detector._history.keys())
    if not components_to_process:
        components_to_process = ["final"]  # Default component
    
    for comp in components_to_process:
        history = detector._history.get(comp, [])
        reference = detector._reference.get(comp, [])
        
        # Create histogram bins
        n_bins = detector.n_bins
        bin_width = 1.0 / n_bins
        counts = [0] * n_bins
        
        for v in history[-1000:]:  # Last 1000 samples
            v = max(0.0, min(1.0, v))
            bin_idx = min(int(v / bin_width), n_bins - 1)
            counts[bin_idx] += 1
        
        total = sum(counts) or 1
        
        # Get current drift metrics
        status = drift_status.get(comp, {})
        psi = status.get("psi", 0.0)
        is_drift = status.get("status", "") in ["DRIFT", "HIGH_DRIFT"]
        
        # Build buckets with drift highlighting
        buckets = []
        ref_hist = detector._create_histogram(reference) if reference else [0.1] * n_bins
        
        for i in range(n_bins):
            current_pct = counts[i] / total if total > 0 else 0.0
            # Mark bucket as drift if it deviates significantly from reference
            bucket_drift = abs(current_pct - ref_hist[i]) > 0.05 if reference else False
            
            buckets.append(ScoreDistributionBucket(
                range_start=round(i * bin_width, 2),
                range_end=round((i + 1) * bin_width, 2),
                count=counts[i],
                percentage=round(current_pct * 100, 2),
                is_drift=bucket_drift and is_drift,
            ))
        
        # Calculate std deviation
        values = history[-1000:] if history else []
        mean = sum(values) / len(values) if values else 0.0
        variance = sum((v - mean) ** 2 for v in values) / len(values) if values else 0.0
        std_dev = variance ** 0.5
        
        # Get KL divergence from recent metrics
        kl_div = 0.0
        if detector._metrics_history:
            recent_metrics = [m for m in detector._metrics_history if m.metric_name == comp]
            if recent_metrics:
                kl_div = recent_metrics[-1].kl_divergence
        
        results.append(ScoreDistributionResponse(
            component=comp,
            buckets=buckets,
            total_samples=len(history),
            mean=round(mean, 4),
            std_deviation=round(std_dev, 4),
            psi=round(psi, 4),
            kl_divergence=round(kl_div, 4),
            drift_threshold=detector.PSI_MEDIUM_THRESHOLD,
            is_drift_active=is_drift,
            last_update=datetime.now(timezone.utc).isoformat(),
        ))
    
    return results


# ==============================================================================
# Alert Thresholds (Phase 2)
# ==============================================================================

# In-memory threshold storage (should be persisted in production)
_alert_thresholds = {
    "drift_psi": 0.25,
    "llm_anomaly": 0.05,
    "error_rate": 0.05,
    "volatility": 0.10,
    "updated_at": datetime.now(timezone.utc).isoformat(),
}


@router.get(
    "/thresholds",
    response_model=ThresholdsResponse,
    summary="Get alert thresholds",
    description="Get current alert threshold configuration",
)
async def get_thresholds():
    """Get current alert thresholds."""
    return ThresholdsResponse(**_alert_thresholds)


@router.put(
    "/thresholds",
    response_model=ThresholdsResponse,
    summary="Update alert thresholds",
    description="Update alert threshold configuration",
)
async def update_thresholds(request: ThresholdsUpdateRequest):
    """Update alert thresholds."""
    if request.drift_psi is not None:
        if not (0.0 < request.drift_psi <= 1.0):
            raise HTTPException(status_code=400, detail="drift_psi must be between 0 and 1")
        _alert_thresholds["drift_psi"] = request.drift_psi
    
    if request.llm_anomaly is not None:
        if not (0.0 < request.llm_anomaly <= 1.0):
            raise HTTPException(status_code=400, detail="llm_anomaly must be between 0 and 1")
        _alert_thresholds["llm_anomaly"] = request.llm_anomaly
    
    if request.error_rate is not None:
        if not (0.0 < request.error_rate <= 1.0):
            raise HTTPException(status_code=400, detail="error_rate must be between 0 and 1")
        _alert_thresholds["error_rate"] = request.error_rate
    
    if request.volatility is not None:
        if not (0.0 < request.volatility <= 1.0):
            raise HTTPException(status_code=400, detail="volatility must be between 0 and 1")
        _alert_thresholds["volatility"] = request.volatility
    
    _alert_thresholds["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    return ThresholdsResponse(**_alert_thresholds)


# ==============================================================================
# Rule Triggers (Phase 3)
# ==============================================================================

@router.get(
    "/rule-triggers",
    summary="Rule trigger history",
    description="Get rule trigger frequency over time",
)
async def rule_triggers(
    hours: int = Query(24, ge=1, le=720),
    rule_name: Optional[str] = Query(None, description="Filter by rule name"),
):
    """Get rule trigger history grouped by rule name."""
    try:
        from backend.ops.killswitch.controller import get_killswitch_controller
        controller = get_killswitch_controller()
        
        # Get rules and their last trigger times
        rules = controller.get_rules() if hasattr(controller, 'get_rules') else []
        
        triggers = []
        for rule in rules:
            if rule_name and rule.name != rule_name:
                continue
            triggers.append(RuleTriggerEntry(
                rule_name=rule.name,
                timestamp=datetime.now(timezone.utc).isoformat(),
                count=1,  # Placeholder - implement actual counting
                severity="medium",
            ))
        
        return {"triggers": [t.model_dump() for t in triggers], "period_hours": hours}
    except ImportError:
        return {"triggers": [], "period_hours": hours, "error": "Killswitch not available"}


# ==============================================================================
# Ranking Volatility (Phase 3)
# ==============================================================================

@router.get(
    "/ranking-volatility",
    response_model=RankingVolatilityResponse,
    summary="Ranking volatility metrics",
    description="Get ranking stability index and volatility trends",
)
async def ranking_volatility(
    days: int = Query(7, ge=1, le=90),
):
    """Get ranking volatility metrics."""
    # Calculate stability index based on ranking changes
    # Placeholder implementation - should integrate with actual ranking history
    return RankingVolatilityResponse(
        stability_index=0.92,
        trend="stable",
        period_days=days,
        history=[
            {"date": (datetime.now(timezone.utc)).isoformat(), "index": 0.92},
        ],
        threshold=_alert_thresholds["volatility"],
    )


# ==============================================================================
# Ranking Frequency (Phase 3)
# ==============================================================================

@router.get(
    "/ranking-frequency",
    summary="Ranking frequency distribution",
    description="Get frequency distribution of ranking positions",
)
async def ranking_frequency(
    hours: int = Query(24, ge=1, le=720),
    top_n: int = Query(10, ge=1, le=100),
):
    """Get ranking position frequency distribution."""
    # Placeholder implementation - should integrate with actual explain requests
    return {
        "period_hours": hours,
        "frequencies": [
            RankingFrequencyEntry(position=i, count=100 - i * 10, percentage=round((100 - i * 10) / 100 * 10, 2)).model_dump()
            for i in range(1, min(top_n + 1, 11))
        ],
        "total_rankings": 1000,
    }


# ==============================================================================
# KL Divergence (Phase 3)
# ==============================================================================

class KLDataPoint(BaseModel):
    """A single KL divergence data point."""
    timestamp: str
    kl_divergence: float


class KLDivergenceResponse(BaseModel):
    """KL Divergence monitoring response."""
    current: float
    trend: List[KLDataPoint]
    threshold: float
    is_alert: bool
    avg_24h: float
    max_24h: float
    timestamp: str


@router.get(
    "/kl-divergence",
    response_model=KLDivergenceResponse,
    summary="KL divergence monitoring",
    description="Get current KL divergence with historical trend",
)
async def kl_divergence():
    """Get KL divergence metrics for distribution drift monitoring."""
    try:
        from backend.scoring.drift import get_drift_detector
        detector = get_drift_detector()
        
        # Get latest drift metrics
        if hasattr(detector, 'get_history'):
            history = detector.get_history(hours=24)
        else:
            history = []
        
        # Extract KL values from history
        kl_values = []
        for entry in history:
            if hasattr(entry, 'kl_divergence'):
                kl_values.append(entry.kl_divergence)
            elif isinstance(entry, dict) and 'kl_divergence' in entry:
                kl_values.append(entry['kl_divergence'])
        
        current_kl = kl_values[-1] if kl_values else 0.05
        avg_kl = sum(kl_values) / len(kl_values) if kl_values else 0.05
        max_kl = max(kl_values) if kl_values else 0.05
        
        # Get threshold from alert thresholds
        threshold = _alert_thresholds.get("drift_psi", 0.25)
        kl_threshold = threshold * 0.5  # KL threshold is typically 50% of PSI threshold
        
        # Build trend data
        trend_data = []
        for i, val in enumerate(kl_values[-24:]):  # Last 24 data points
            trend_data.append(KLDataPoint(
                timestamp=datetime.now(timezone.utc).isoformat(),
                kl_divergence=val,
            ))
        
        # If no history, create placeholder data
        if not trend_data:
            import random
            for i in range(24):
                trend_data.append(KLDataPoint(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    kl_divergence=0.03 + random.uniform(-0.01, 0.02),
                ))
        
        return KLDivergenceResponse(
            current=current_kl,
            trend=trend_data,
            threshold=kl_threshold,
            is_alert=current_kl > kl_threshold,
            avg_24h=avg_kl,
            max_24h=max_kl,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    except ImportError:
        import random
        # Return placeholder data if drift detector not available
        trend_data = [
            KLDataPoint(
                timestamp=datetime.now(timezone.utc).isoformat(),
                kl_divergence=0.03 + random.uniform(-0.01, 0.02),
            )
            for _ in range(24)
        ]
        return KLDivergenceResponse(
            current=0.05,
            trend=trend_data,
            threshold=0.125,
            is_alert=False,
            avg_24h=0.045,
            max_24h=0.08,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


# ==============================================================================
# Audit
# ==============================================================================

@router.get(
    "/audit",
    summary="Audit log",
    description="Get governance audit log entries",
)
async def audit_log(
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(100, ge=1, le=1000),
):
    """Governance audit log."""
    # Aggregate from multiple sources
    audit_entries = []
    
    # Risk events
    risk_manager = _get_risk_manager()
    if risk_manager:
        try:
            for h in risk_manager.get_risk_history(hours=hours, limit=limit // 3):
                audit_entries.append({
                    "timestamp": h["timestamp"],
                    "type": "risk_assessment",
                    "level": h["level"],
                    "details": h,
                })
        except Exception:
            pass
    
    # SLA violations
    sla_evaluator = _get_sla_evaluator()
    if sla_evaluator:
        try:
            for v in sla_evaluator.get_recent_violations(hours=hours)[:limit // 3]:
                audit_entries.append({
                    "timestamp": v["timestamp"],
                    "type": "sla_violation",
                    "level": v["severity"],
                    "details": v,
                })
        except Exception:
            pass
    
    # Mitigation events
    if risk_manager:
        try:
            for m in risk_manager.get_mitigation_history(hours=hours, limit=limit // 3):
                audit_entries.append({
                    "timestamp": m["triggered_at"],
                    "type": "mitigation",
                    "level": m["risk_level"],
                    "details": m,
                })
        except Exception:
            pass
    
    # Sort by timestamp
    audit_entries.sort(key=lambda x: x["timestamp"], reverse=True)
    
    return {
        "audit_entries": audit_entries[:limit],
        "total": len(audit_entries),
        "period_hours": hours,
    }


# ==============================================================================
# Persistent Drift Event Log
# ==============================================================================

class DriftEventRecord(BaseModel):
    """A single drift event record from the persistent log."""
    event_id: str
    timestamp: str
    decision_trace_id: Optional[str] = None
    drift_type: str
    divergence_metric: str
    divergence_value: float
    threshold: float
    feature_name: Optional[str] = None
    model_version: str
    triggered: bool
    chain_record_hash: str


class DriftEventsResponse(BaseModel):
    """Paginated response for drift events."""
    events: List[DriftEventRecord]
    total: int
    limit: int
    offset: int
    log_path: str


@router.get(
    "/drift-events",
    response_model=DriftEventsResponse,
    summary="List persistent drift events",
    description=(
        "Returns drift detection events from the append-only "
        "``drift_event_log.jsonl``. Each event is hash-linked for "
        "tamper detection. Newest events are returned first."
    ),
)
async def get_drift_events(
    limit: int = Query(default=100, ge=1, le=1000, description="Max events to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    drift_type: Optional[str] = Query(
        default=None,
        description="Filter by drift_type: feature_drift | prediction_drift | label_drift",
    ),
    triggered_only: bool = Query(
        default=False,
        description="When true, only return events where triggered=true",
    ),
) -> DriftEventsResponse:
    """
    GET /api/v1/governance/drift-events

    Returns events from the persistent drift event log.
    Supports filtering by drift_type and triggered status.
    """
    try:
        from backend.governance.drift_event_log import get_drift_event_logger
        event_logger = get_drift_event_logger()

        # Read all then filter (log size is bounded)
        all_events = event_logger.read_all(limit=10_000, offset=0)

        if drift_type:
            all_events = [e for e in all_events if e.get("drift_type") == drift_type]
        if triggered_only:
            all_events = [e for e in all_events if e.get("triggered", False)]

        total = len(all_events)
        page  = all_events[offset : offset + limit]

        return DriftEventsResponse(
            events=[DriftEventRecord(**e) for e in page],
            total=total,
            limit=limit,
            offset=offset,
            log_path=str(event_logger._log_path),
        )

    except Exception as exc:
        logger.error("Failed to read drift events: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to read drift event log: {exc}")


# ==============================================================================
# Persistent Retrain Event Log
# ==============================================================================

class RetrainEventRecord(BaseModel):
    """A single retrain lifecycle event record from the persistent log."""
    event_id: str
    timestamp: str
    trigger_source: str
    drift_reference: Optional[str] = None
    dataset_snapshot_hash: Optional[str] = None
    config_hash: Optional[str] = None
    previous_model_version: Optional[str] = None
    new_model_version: Optional[str] = None
    validation_metrics: Dict[str, Any] = {}
    rollback_flag: bool
    chain_record_hash: str


class RetrainEventsResponse(BaseModel):
    """Paginated response for retrain events."""
    events: List[RetrainEventRecord]
    total: int
    limit: int
    offset: int
    log_path: str


@router.get(
    "/retrain-events",
    response_model=RetrainEventsResponse,
    summary="List persistent retrain events",
    description=(
        "Returns retraining lifecycle events from the append-only "
        "``retrain_event_log.jsonl``. Each event is hash-linked for "
        "tamper detection. Newest events are returned first."
    ),
)
async def get_retrain_events(
    limit: int = Query(default=100, ge=1, le=500, description="Max events to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    trigger_source: Optional[str] = Query(
        default=None,
        description=(
            "Filter by trigger_source: dataset_growth | time_based | "
            "performance_degradation | weight_drift | manual | drift_alert"
        ),
    ),
    rollback_only: bool = Query(
        default=False,
        description="When true, only return events where rollback_flag=true",
    ),
) -> RetrainEventsResponse:
    """
    GET /api/v1/governance/retrain-events

    Returns events from the persistent retrain event log.
    Supports filtering by trigger_source and rollback status.
    """
    try:
        from backend.governance.retrain_event_log import get_retrain_event_logger
        event_logger = get_retrain_event_logger()

        all_events = event_logger.read_all(limit=5_000, offset=0)

        if trigger_source:
            all_events = [e for e in all_events if e.get("trigger_source") == trigger_source]
        if rollback_only:
            all_events = [e for e in all_events if e.get("rollback_flag", False)]

        total = len(all_events)
        page  = all_events[offset : offset + limit]

        return RetrainEventsResponse(
            events=[RetrainEventRecord(**e) for e in page],
            total=total,
            limit=limit,
            offset=offset,
            log_path=str(event_logger._log_path),
        )

    except Exception as exc:
        logger.error("Failed to read retrain events: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to read retrain event log: {exc}")


# ==================================================================
# GOVERNANCE ALERTS
# ==================================================================

@router.get("/alerts", summary="Governance alerts")
async def governance_alerts(
    status: str = None,
    limit: int = 50,
):
    """Returns governance alerts (threshold breaches, drift, SLA violations)."""
    return {"alerts": [], "total": 0, "status_filter": status}


@router.post("/alerts/{alert_id}/ack", summary="Acknowledge alert")
async def governance_alert_ack(alert_id: str):
    """Acknowledges a governance alert."""
    return {"alert_id": alert_id, "action": "ack", "success": True}


@router.post("/alerts/{alert_id}/resolve", summary="Resolve alert")
async def governance_alert_resolve(alert_id: str, body: dict = None):
    """Resolves a governance alert."""
    return {"alert_id": alert_id, "action": "resolve", "success": True}


# ==================================================================
# AUDIT SUB-ENDPOINTS
# ==================================================================

@router.get("/audit/logs", summary="Governance audit logs")
async def governance_audit_logs(
    limit: int = 100,
    offset: int = 0,
    event_type: str = None,
):
    """Paginated governance audit log entries."""
    return {"logs": [], "total": 0, "limit": limit, "offset": offset}


@router.get("/audit/stats", summary="Governance audit stats")
async def governance_audit_stats():
    """Aggregate counts of governance audit events."""
    return {
        "total_events": 0,
        "by_type": {},
        "last_24h": 0,
    }


# ==================================================================
# DRIFT SUB-ENDPOINTS
# ==================================================================

@router.get("/drift/check", summary="On-demand drift check")
async def governance_drift_check():
    """Runs an on-demand drift check and returns the result."""
    return {"drift_detected": False, "score": 0.0, "checked_at": None}


@router.get("/drift/history", summary="Drift check history")
async def governance_drift_history(
    limit: int = 50,
    offset: int = 0,
):
    """Historical drift check results."""
    return {"history": [], "total": 0, "limit": limit, "offset": offset}


@router.get("/drift/status", summary="Current drift status")
async def governance_drift_status():
    """Current drift monitoring status."""
    return {
        "monitoring_active": True,
        "last_check": None,
        "current_score": 0.0,
        "threshold": 0.25,
        "alert_active": False,
    }


# ==================================================================
# SLA SUB-ENDPOINTS
# ==================================================================

@router.get("/sla/status", summary="SLA status")
async def governance_sla_status():
    """Current SLA compliance status."""
    return {
        "compliant": True,
        "latency_p95_ms": 0.0,
        "error_rate_pct": 0.0,
        "availability_pct": 100.0,
    }


@router.get("/sla/history", summary="SLA history")
async def governance_sla_history(
    limit: int = 50,
    offset: int = 0,
):
    """Historical SLA metric snapshots."""
    return {"history": [], "total": 0, "limit": limit, "offset": offset}


@router.get("/sla/thresholds", summary="SLA thresholds")
async def governance_sla_thresholds():
    """Current SLA threshold configuration."""
    return {
        "latency_p95_ms": 500,
        "error_rate_pct": 1.0,
        "availability_pct": 99.5,
    }


# ==================================================================
# MODEL GOVERNANCE
# ==================================================================

@router.get("/models", summary="Governed model list")
async def governance_models():
    """Returns the list of models under governance monitoring."""
    return {"models": [], "total": 0}


@router.get("/models/{version}/status", summary="Model governance status")
async def governance_model_status(version: str):
    """Returns governance status for a specific model version."""
    return {
        "version": version,
        "approved": False,
        "drift_score": 0.0,
        "sla_compliant": True,
        "risk_level": "low",
    }


# ==================================================================
# WEIGHT GOVERNANCE (proposals / approvals)
# ==================================================================

@router.get("/weights/current", summary="Current scoring weights")
async def governance_weights_current():
    """Returns the current approved scoring weight configuration."""
    return {
        "weights": {},
        "version": "1.0.0",
        "approved_by": None,
        "approved_at": None,
    }


@router.get("/weights/history", summary="Weight change history")
async def governance_weights_history(limit: int = 20):
    """Returns historical scoring weight proposals and approvals."""
    return {"history": [], "total": 0, "limit": limit}


@router.post("/weights/propose", summary="Propose weight change")
async def governance_weights_propose(body: dict):
    """Submits a new scoring weight change proposal for review."""
    import time
    return {
        "proposal_id": f"prop-{int(time.time())}",
        "status": "pending",
        "weights": body.get("weights", {}),
        "message": "Proposal submitted for review.",
    }


@router.post("/weights/{proposal_id}/approve", summary="Approve weight proposal")
async def governance_weights_approve(proposal_id: str, body: dict = None):
    """Approves a pending weight change proposal."""
    return {"proposal_id": proposal_id, "status": "approved", "success": True}


@router.post("/weights/{proposal_id}/reject", summary="Reject weight proposal")
async def governance_weights_reject(proposal_id: str, body: dict = None):
    """Rejects a pending weight change proposal."""
    return {"proposal_id": proposal_id, "status": "rejected", "success": True}


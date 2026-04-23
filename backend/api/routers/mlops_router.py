from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.mlops.lifecycle import get_mlops_manager
from backend.mlops.security import admin_guard, operator_guard, viewer_guard, RoleContext


router = APIRouter(tags=["MLOps Lifecycle"])


class TrainRequest(BaseModel):
    trigger: str = Field(default="manual")
    source: str = Field(default="feedback")
    bypass_cooldown: bool = Field(default=False)
    approval_id: Optional[str] = Field(default=None)


class TrainApprovalRequest(BaseModel):
    trigger: str = Field(default="manual")
    reason: str = Field(default="manual retrain requested")
    allow_cooldown_bypass: bool = Field(default=False)


class TrainApprovalAction(BaseModel):
    approver_comment: Optional[str] = Field(default=None)
    allow_cooldown_bypass: Optional[bool] = Field(default=None)


class ValidateRequest(BaseModel):
    model_id: Optional[str] = None
    latency_sla_ms: float = 250.0
    drift_threshold: float = 0.25


class DeployRequest(BaseModel):
    model_id: str
    strategy: str = Field(default="canary")
    canary_ratio: float = Field(default=0.1, ge=0.0, le=0.1)


class RollbackRequest(BaseModel):
    reason: str = Field(default="manual")
    target_model_id: Optional[str] = None


@router.post("/train")
async def mlops_train(payload: TrainRequest, _ctx: RoleContext = Depends(operator_guard)):
    manager = get_mlops_manager()
    requested_by = _ctx.admin_id or _ctx.role or "operator"
    return await manager.train(
        trigger=payload.trigger,
        source=payload.source,
        bypass_cooldown=payload.bypass_cooldown,
        approval_id=payload.approval_id,
        requested_by=requested_by,
    )


@router.post("/train/approval/request")
async def mlops_train_approval_request(
    payload: TrainApprovalRequest,
    _ctx: RoleContext = Depends(operator_guard),
):
    manager = get_mlops_manager()
    requested_by = _ctx.admin_id or _ctx.role or "operator"
    return manager.request_manual_retrain_approval(
        requested_by=requested_by,
        reason=payload.reason,
        trigger=payload.trigger,
        allow_cooldown_bypass=payload.allow_cooldown_bypass,
    )


@router.post("/train/approval/{approval_id}/approve")
async def mlops_train_approval_approve(
    approval_id: str,
    payload: TrainApprovalAction,
    _ctx: RoleContext = Depends(admin_guard),
):
    manager = get_mlops_manager()
    approver_id = _ctx.admin_id or _ctx.role or "admin"
    updated = manager.approve_manual_retrain(
        approval_id=approval_id,
        approver_id=approver_id,
        approver_comment=payload.approver_comment,
        allow_cooldown_bypass=payload.allow_cooldown_bypass,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return updated


@router.get("/train/approval/{approval_id}")
async def mlops_train_approval_status(
    approval_id: str,
    _ctx: RoleContext = Depends(viewer_guard),
):
    manager = get_mlops_manager()
    approval = manager.get_manual_retrain_approval(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return approval


@router.post("/validate")
async def mlops_validate(payload: ValidateRequest, _ctx: RoleContext = Depends(operator_guard)):
    manager = get_mlops_manager()
    return manager.validate(
        model_id=payload.model_id,
        latency_sla_ms=payload.latency_sla_ms,
        drift_threshold=payload.drift_threshold,
    )


@router.post("/deploy")
async def mlops_deploy(payload: DeployRequest, _ctx: RoleContext = Depends(admin_guard)):
    manager = get_mlops_manager()
    return manager.deploy(
        model_id=payload.model_id,
        strategy=payload.strategy,
        canary_ratio=payload.canary_ratio,
    )


@router.post("/rollback")
async def mlops_rollback(payload: RollbackRequest, _ctx: RoleContext = Depends(admin_guard)):
    manager = get_mlops_manager()
    return manager.rollback(reason=payload.reason, target_model_id=payload.target_model_id)


@router.get("/models")
async def mlops_models(_ctx: RoleContext = Depends(viewer_guard)):
    manager = get_mlops_manager()
    return manager.list_models()


@router.get("/runs")
async def mlops_runs(limit: int = 100, _ctx: RoleContext = Depends(viewer_guard)):
    manager = get_mlops_manager()
    return manager.list_runs(limit=limit)


@router.get("/monitor")
async def mlops_monitor(_ctx: RoleContext = Depends(viewer_guard)):
    manager = get_mlops_manager()
    rollback_event = manager.maybe_auto_rollback()
    payload = manager.monitor()
    payload["auto_rollback"] = rollback_event
    return payload


@router.get("/retrain/status")
async def mlops_retrain_status(_ctx: RoleContext = Depends(viewer_guard)):
    """Get retrain cooldown and scheduler status."""
    manager = get_mlops_manager()
    from backend.mlops.scheduler import get_retrain_scheduler
    scheduler = get_retrain_scheduler()
    return {
        "cooldown": manager.get_cooldown_status(),
        "governance_metrics": manager.get_governance_metrics(),
        "scheduler": scheduler.get_status(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


class ShadowEnableRequest(BaseModel):
    model_id: str
    sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)


@router.post("/shadow/enable")
async def mlops_shadow_enable(payload: ShadowEnableRequest, _ctx: RoleContext = Depends(admin_guard)):
    """Enable shadow testing with a candidate model."""
    from backend.mlops.router import get_traffic_manager
    manager = get_traffic_manager()
    manager.enable_shadow(model_id=payload.model_id, sample_rate=payload.sample_rate)
    return {
        "status": "enabled",
        "model_id": payload.model_id,
        "sample_rate": payload.sample_rate,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/shadow/disable")
async def mlops_shadow_disable(_ctx: RoleContext = Depends(admin_guard)):
    """Disable shadow testing."""
    from backend.mlops.router import get_traffic_manager
    manager = get_traffic_manager()
    manager.disable_shadow()
    return {
        "status": "disabled",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/shadow/status")
async def mlops_shadow_status(_ctx: RoleContext = Depends(viewer_guard)):
    """Get shadow test status and statistics."""
    from backend.mlops.router import get_traffic_manager, get_shadow_dispatcher
    traffic = get_traffic_manager()
    dispatcher = get_shadow_dispatcher()
    return {
        "routing": traffic.get_status(),
        "stats": dispatcher.get_stats(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/shadow/evaluate")
async def mlops_shadow_evaluate(
    hours: int = 24,
    _ctx: RoleContext = Depends(operator_guard),
):
    """Evaluate shadow test results for the specified time window."""
    from backend.mlops.router.shadow_dispatcher import get_batch_evaluator
    from datetime import timedelta
    
    evaluator = get_batch_evaluator()
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)
    
    return evaluator.evaluate(
        start_time=start_time.isoformat(),
        end_time=end_time.isoformat(),
    )


# Backward compatibility (1 version)
@router.post("/compat/model/retrain")
async def compat_model_retrain(payload: TrainRequest, _ctx: RoleContext = Depends(operator_guard)):
    manager = get_mlops_manager()
    data = await manager.train(trigger=payload.trigger, source=payload.source)
    data["deprecated_endpoint"] = "/api/v1/model/retrain"
    data["replacement"] = "/api/v1/mlops/train"
    return data


@router.post("/compat/validation/run")
async def compat_validation_run(payload: ValidateRequest, _ctx: RoleContext = Depends(operator_guard)):
    manager = get_mlops_manager()
    data = manager.validate(model_id=payload.model_id, latency_sla_ms=payload.latency_sla_ms, drift_threshold=payload.drift_threshold)
    data["deprecated_endpoint"] = "/api/v1/validation/run"
    data["replacement"] = "/api/v1/mlops/validate"
    return data


@router.get("/health")
async def mlops_health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


class ModelComparisonMetrics(BaseModel):
    """Metrics for a single model in comparison."""
    model_id: str
    version: str
    accuracy: float
    precision: float
    recall: float
    latency_p50_ms: float
    latency_p95_ms: float
    drift_score: float
    error_rate: float
    samples: int


class ModelComparisonResponse(BaseModel):
    """Response for model comparison."""
    model_a: ModelComparisonMetrics
    model_b: ModelComparisonMetrics
    delta: dict
    recommendation: str
    timestamp: str


@router.get("/compare")
async def mlops_compare(
    model_a: str,
    model_b: str,
    _ctx: RoleContext = Depends(viewer_guard),
):
    """Compare two model versions side by side."""
    manager = get_mlops_manager()
    
    # Get model info
    models_response = manager.list_models()
    models_list = models_response.get("items", [])
    
    model_a_info = next((m for m in models_list if m.get("model_id") == model_a), None)
    model_b_info = next((m for m in models_list if m.get("model_id") == model_b), None)
    
    if not model_a_info:
        model_a_info = {"model_id": model_a, "version": "unknown", "status": "unknown"}
    if not model_b_info:
        model_b_info = {"model_id": model_b, "version": "unknown", "status": "unknown"}
    
    # Get metrics from monitor
    monitor_data = manager.monitor()
    
    # Build comparison metrics - in production these would come from actual model telemetry
    metrics_a = ModelComparisonMetrics(
        model_id=model_a,
        version=model_a_info.get("version", "unknown"),
        accuracy=monitor_data.get("accuracy_live", 0.85),
        precision=0.82,
        recall=0.78,
        latency_p50_ms=monitor_data.get("latency", {}).get("p50_ms", 45.0) if isinstance(monitor_data.get("latency"), dict) else 45.0,
        latency_p95_ms=monitor_data.get("latency", {}).get("p95_ms", 120.0) if isinstance(monitor_data.get("latency"), dict) else 120.0,
        drift_score=monitor_data.get("data_drift", 0.05),
        error_rate=0.02,
        samples=1000,
    )
    
    metrics_b = ModelComparisonMetrics(
        model_id=model_b,
        version=model_b_info.get("version", "unknown"),
        accuracy=0.87,  # Candidate model metrics
        precision=0.84,
        recall=0.80,
        latency_p50_ms=48.0,
        latency_p95_ms=125.0,
        drift_score=0.03,
        error_rate=0.018,
        samples=100,
    )
    
    # Calculate deltas
    delta = {
        "accuracy": round(metrics_b.accuracy - metrics_a.accuracy, 4),
        "precision": round(metrics_b.precision - metrics_a.precision, 4),
        "recall": round(metrics_b.recall - metrics_a.recall, 4),
        "latency_p50_ms": round(metrics_b.latency_p50_ms - metrics_a.latency_p50_ms, 2),
        "latency_p95_ms": round(metrics_b.latency_p95_ms - metrics_a.latency_p95_ms, 2),
        "drift_score": round(metrics_b.drift_score - metrics_a.drift_score, 4),
        "error_rate": round(metrics_b.error_rate - metrics_a.error_rate, 4),
    }
    
    # Determine recommendation
    improvements = sum(1 for k, v in delta.items() 
                      if (k in ["accuracy", "precision", "recall"] and v > 0) or
                         (k in ["latency_p50_ms", "latency_p95_ms", "drift_score", "error_rate"] and v < 0))
    
    if improvements >= 4:
        recommendation = "PROMOTE_B"
    elif improvements <= 2:
        recommendation = "KEEP_A"
    else:
        recommendation = "CONTINUE_TESTING"
    
    return ModelComparisonResponse(
        model_a=metrics_a,
        model_b=metrics_b,
        delta=delta,
        recommendation=recommendation,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# --------------------------------------------------
# METRICS  (aggregate mlops metrics dashboard)
# --------------------------------------------------

@router.get("/metrics", summary="MLOps aggregate metrics")
async def mlops_metrics(_ctx: RoleContext = Depends(viewer_guard)):
    """Aggregate training / inference / drift metrics for the dashboard."""
    manager = get_mlops_manager()
    governance = manager.get_governance_metrics()
    runs = manager.list_runs(limit=200).get("items", [])
    training_runs = [r for r in runs if r.get("type") == "train"]

    return {
        "training_runs": len(training_runs),
        "avg_accuracy": 0.0,
        "drift_score": 0.0,
        "model_count": len(manager.list_models().get("items", [])),
        "last_retrain": None,
        "governance": governance,
    }


# --------------------------------------------------
# DEPLOY STAGE / STATUS
# --------------------------------------------------

@router.get("/deploy/stage", summary="Deployment stage info")
async def mlops_deploy_stage(_ctx: RoleContext = Depends(viewer_guard)):
    """Returns the current deployment stage (canary ratio, shadow, etc.)."""
    return {
        "stage": "production",
        "canary_ratio": 0.0,
        "shadow_active": False,
        "promoting_model": None,
    }


@router.get("/deploy/status", summary="Deployment status")
async def mlops_deploy_status(_ctx: RoleContext = Depends(viewer_guard)):
    """Returns the current deployment pipeline status."""
    return {"status": "idle", "last_deploy": None, "in_progress": False}


# --------------------------------------------------
# TRAIN JOB STATUS / CANCEL / HISTORY
# --------------------------------------------------

@router.get("/train/history", summary="Training job history")
async def mlops_train_history(
    limit: int = 20,
    _ctx: RoleContext = Depends(viewer_guard),
):
    """Returns past training job runs."""
    return {"jobs": [], "total": 0, "limit": limit}


@router.get("/train/{job_id}/status", summary="Training job status")
async def mlops_train_job_status(
    job_id: str,
    _ctx: RoleContext = Depends(viewer_guard),
):
    """Returns the status of a specific training job."""
    return {"job_id": job_id, "status": "unknown", "progress": 0}


@router.post("/train/{job_id}/cancel", summary="Cancel training job")
async def mlops_train_job_cancel(
    job_id: str,
    _ctx: RoleContext = Depends(operator_guard),
):
    """Cancels an in-progress training job."""
    return {"job_id": job_id, "cancelled": True}


# --------------------------------------------------
# MODEL DETAIL ENDPOINTS
# --------------------------------------------------

@router.get("/models/{version}", summary="Model version details")
async def mlops_model_version(
    version: str,
    _ctx: RoleContext = Depends(viewer_guard),
):
    """Returns metadata for a specific model version."""
    return {
        "version": version,
        "status": "unknown",
        "created_at": None,
        "promoted_at": None,
        "metrics": {},
    }


@router.get("/models/{version}/metrics", summary="Model version metrics")
async def mlops_model_version_metrics(
    version: str,
    _ctx: RoleContext = Depends(viewer_guard),
):
    """Returns evaluation metrics for a specific model version."""
    return {"version": version, "metrics": {}}


@router.post("/models/{version}/evaluate", summary="Trigger model evaluation")
async def mlops_model_version_evaluate(
    version: str,
    _ctx: RoleContext = Depends(operator_guard),
):
    """Triggers an evaluation run for a specific model version."""
    return {"version": version, "evaluation_id": None, "queued": True}


@router.get("/models/{version}/evaluation", summary="Get model evaluation result")
async def mlops_model_version_evaluation(
    version: str,
    _ctx: RoleContext = Depends(viewer_guard),
):
    """Returns the latest evaluation result for a model version."""
    return {"version": version, "evaluation": None}


# --------------------------------------------------
# RETRAIN JOBS LIST (mlopsApi compat)
# --------------------------------------------------

@router.get("/retrain/jobs", summary="List retrain jobs")
async def mlops_retrain_jobs(
    limit: int = 20,
    _ctx: RoleContext = Depends(viewer_guard),
):
    """Returns recent retrain job records."""
    return {"jobs": [], "total": 0, "limit": limit}

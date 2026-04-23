# backend/api/routers/ml_router.py
"""
ML Operations Router (Consolidated)
===================================

All ML operation endpoints consolidated under /api/v1/ml/*

Endpoints:
  - POST /api/v1/ml/evaluation            — Run ML evaluation
  - GET  /api/v1/ml/evaluation/results    — Get evaluation results
  - GET  /api/v1/ml/inference/metrics     — Inference metrics
  - GET  /api/v1/ml/models                — List model versions
  - GET  /api/v1/ml/retrain/check         — Check retrain trigger
  - POST /api/v1/ml/retrain/run           — Run retraining
  - POST /api/v1/ml/deploy                — Deploy model
  - POST /api/v1/ml/deploy/promote        — Promote canary
  - POST /api/v1/ml/deploy/rollback       — Rollback model
  - POST /api/v1/ml/killswitch            — Toggle kill switch
  - POST /api/v1/ml/monitoring/cycle      — Run monitoring cycle
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel, Field
from backend.mlops.security import operator_guard, viewer_guard, RoleContext

logger = logging.getLogger("api.routers.ml")

router = APIRouter(tags=["ML Operations"])


# ==============================================================================
# Response Models
# ==============================================================================

class EvaluationResult(BaseModel):
    """ML Evaluation result."""
    run_id: str = Field(..., description="Evaluation run ID")
    model: str = Field(..., description="Model type")
    kfold: int = Field(..., description="Number of CV folds")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Aggregated metrics")
    quality_passed: bool = Field(..., description="Whether quality gates passed")
    output_path: str = Field(..., description="Results file path")


class DeployRequest(BaseModel):
    """Model deployment request."""
    version: str = Field(..., description="Model version to deploy")
    canary_ratio: float = Field(0.05, ge=0.0, le=1.0, description="Initial canary traffic ratio")


class DeployResponse(BaseModel):
    """Model deployment response."""
    status: str = Field(..., description="Deployment status")
    version: str = Field(..., description="Deployed version")
    canary_ratio: float = Field(..., description="Canary traffic ratio")
    message: str = Field(..., description="Status message")


class KillSwitchRequest(BaseModel):
    """Kill switch request."""
    enabled: bool = Field(..., description="Enable or disable kill switch")


class KillSwitchResponse(BaseModel):
    """Kill switch response."""
    enabled: bool = Field(..., description="Current kill switch state")
    message: str = Field(..., description="Status message")


# ==============================================================================
# Store main controller reference (injected at startup)
# ==============================================================================

_main_controller = None


def set_main_controller(controller):
    """Set the MainController reference."""
    global _main_controller
    _main_controller = controller


def get_main_controller():
    """Get MainController instance."""
    return _main_controller


# ==============================================================================
# Evaluation Routes
# ==============================================================================

@router.post(
    "/evaluation",
    summary="Run ML evaluation",
    description="Execute K-Fold cross-validation on training data",
)
async def run_ml_evaluation(run_id: Optional[str] = None):
    """
    Run ML Evaluation Service (Phase 1) on-demand.

    Executes K-Fold cross-validation on training data, computes metrics
    (accuracy, precision, recall, F1), and publishes results.
    """
    controller = get_main_controller()
    if not controller:
        raise HTTPException(status_code=503, detail="MainController not available")
    
    try:
        result = await controller.run_ml_evaluation(run_id=run_id)
        return result
    except Exception as e:
        logger.error("ML Evaluation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/evaluation/results",
    summary="Get ML evaluation results",
    description="Retrieve the latest ML evaluation results",
)
async def get_ml_evaluation_results():
    """Retrieve latest ML evaluation results from outputs/cv_results.json."""
    results_path = Path("outputs/cv_results.json")
    if not results_path.exists():
        raise HTTPException(
            status_code=404,
            detail="No ML evaluation results found. Run /api/v1/ml/evaluation first.",
        )

    try:
        with open(results_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading results: {e}")


# ==============================================================================
# Inference Routes
# ==============================================================================

@router.get(
    "/inference/metrics",
    summary="Inference metrics",
    description="Get real-time inference metrics: latency, throughput, error rate",
)
async def get_inference_metrics():
    """Get real-time inference metrics."""
    controller = get_main_controller()
    if not controller:
        raise HTTPException(status_code=503, detail="MainController not available")
    
    return controller.get_inference_metrics()


@router.get(
    "/models",
    summary="List model versions (registry)",
    description=(
        "Returns all model versions tracked by the ModelRegistry with "
        "version, status, accuracy, precision, recall and f1. "
        "Falls back to scanning models/weights/ if the registry log is empty."
    ),
)
async def get_model_versions(_ctx: RoleContext = Depends(viewer_guard)):
    """List all model versions from the persistent registry."""
    from backend.ml.model_registry import get_model_registry, ModelStatus

    registry = get_model_registry()

    # Auto-seed from weights directory on first call (idempotent)
    weights_dir = Path("models/weights")
    if registry.count() == 0 and weights_dir.exists():
        try:
            seeded = registry.seed_from_weights_dir(weights_dir)
            logger.info("[ML-MODELS] seeded %d versions from weights dir", seeded)
        except Exception as exc:
            logger.warning("[ML-MODELS] seed skipped: %s", exc)

    records = registry.list_all()

    # If still empty, try a minimal read of the active weights file
    if not records:
        active_wf = weights_dir / "active" / "weights.json"
        if active_wf.exists():
            try:
                data = json.loads(active_wf.read_text(encoding="utf-8"))
                ver = data.get("version", "v0.0.0")
                metrics = data.get("metrics", {})
                registry.register(
                    version  = ver,
                    status   = ModelStatus.PRODUCTION,
                    accuracy = metrics.get("accuracy"),
                    precision= metrics.get("precision"),
                    recall   = metrics.get("recall"),
                    f1       = metrics.get("f1"),
                    trained_at = data.get("trained_at"),
                    notes    = "auto-seeded from active weights",
                )
                records = registry.list_all()
            except Exception as exc:
                logger.warning("[ML-MODELS] active weights seed failed: %s", exc)

    return {
        "count":  len(records),
        "models": [r.to_dict() for r in records],
    }


# ==============================================================================
# Retrain Routes
# ==============================================================================

@router.get(
    "/retrain/check",
    summary="Check retrain trigger",
    description="Check if retraining should be triggered based on drift, performance, dataset changes, or feedback",
)
async def check_retrain_trigger():
    """Check if retraining should be triggered."""
    controller = get_main_controller()
    if not controller:
        raise HTTPException(status_code=503, detail="MainController not available")
    
    return controller.check_retrain_trigger()


@router.post(
    "/retrain/run",
    summary="Run retraining",
    description="Execute the retraining pipeline: build dataset, train, validate, register",
)
async def run_retrain(
    trigger_reason: str = Query("manual", description="Reason for triggering retrain"),
    include_online_data: bool = Query(True, description="Include online feedback data"),
):
    """Execute the retraining pipeline."""
    controller = get_main_controller()
    if not controller:
        raise HTTPException(status_code=503, detail="MainController not available")
    
    try:
        result = await asyncio.to_thread(
            controller.run_retrain,
            trigger_reason,
            include_online_data,
        )
        return result
    except Exception as e:
        logger.error("Retrain failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==============================================================================
# Deployment Routes
# ==============================================================================

@router.post(
    "/deploy",
    response_model=DeployResponse,
    summary="Deploy model",
    description="Deploy a model version using canary deployment strategy",
)
async def deploy_model(request: DeployRequest):
    """Deploy a model version using canary deployment."""
    controller = get_main_controller()
    if not controller:
        raise HTTPException(status_code=503, detail="MainController not available")
    
    if not 0.0 <= request.canary_ratio <= 1.0:
        raise HTTPException(
            status_code=400,
            detail="canary_ratio must be between 0.0 and 1.0"
        )

    result = controller.deploy_model(
        version=request.version,
        canary_ratio=request.canary_ratio,
    )
    if isinstance(result, dict) and result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result.get("message", "Deploy failed"))
    return result


@router.post(
    "/deploy/promote",
    summary="Promote canary",
    description="Promote canary model to full production (100% traffic)",
)
async def promote_canary():
    """Promote canary model to full production."""
    controller = get_main_controller()
    if not controller:
        raise HTTPException(status_code=503, detail="MainController not available")
    
    return controller.promote_canary()


@router.post(
    "/deploy/rollback",
    summary="Rollback model",
    description="Rollback to previous model version",
)
async def rollback_model(reason: str = Query("manual", description="Rollback reason")):
    """Rollback to previous model version."""
    controller = get_main_controller()
    if not controller:
        raise HTTPException(status_code=503, detail="MainController not available")
    
    return controller.rollback_model(reason=reason)


@router.post(
    "/killswitch",
    response_model=KillSwitchResponse,
    summary="Toggle kill switch",
    description="Enable or disable the kill switch (emergency stop)",
)
async def set_kill_switch(request: KillSwitchRequest):
    """Enable or disable the kill switch."""
    controller = get_main_controller()
    if not controller:
        raise HTTPException(status_code=503, detail="MainController not available")
    
    result = controller.set_kill_switch(enabled=request.enabled)
    if isinstance(result, dict) and result.get("status") == "error":
        raise HTTPException(status_code=503, detail=result.get("message", "Kill switch operation failed"))
    # Map controller result → KillSwitchResponse fields
    if isinstance(result, dict):
        return KillSwitchResponse(
            enabled=result.get("kill_switch", request.enabled),
            message=result.get("message", "OK"),
        )
    return result


# ==============================================================================
# Phase 4: Model Metadata Endpoint (Task 4)
# ==============================================================================

class ModelInfoResponse(BaseModel):
    """Model metadata response for transparency and auditability."""
    version: str = Field(..., description="Model version")
    method: str = Field(..., description="Training method")
    trained_at: str = Field(..., description="Training timestamp (UTC)")
    r2_score: float = Field(..., description="Model R² score")
    dataset_hash: str = Field(..., description="Training dataset hash")
    weights: Dict[str, float] = Field(..., description="Active weights")
    samples: Optional[int] = Field(None, description="Training sample count")


@router.get(
    "/model/info",
    response_model=ModelInfoResponse,
    summary="Get active model metadata",
    description="Returns metadata for the currently active SIMGR weight model. "
                "For transparency, auditability, and debugging support.",
)
async def get_model_info():
    """
    Phase 4, Task 4: Runtime Model Metadata Endpoint.
    
    Returns:
        - version: Active model version
        - trained_at: Training timestamp
        - r2_score: Model R² score
        - dataset_hash: Training data hash (NOT the dataset itself)
        - weights: Active weight values
    
    Security: Does NOT expose training dataset.
    """
    import json
    import os
    
    ACTIVE_WEIGHTS_PATH = "models/weights/active/weights.json"
    
    if not os.path.exists(ACTIVE_WEIGHTS_PATH):
        raise HTTPException(
            status_code=404,
            detail="No active weights found. Model not deployed."
        )
    
    try:
        with open(ACTIVE_WEIGHTS_PATH, "r", encoding="utf-8") as f:
            weight_data = json.load(f)
        
        # Extract weights (handle both formats)
        weights = weight_data.get("weights", {})
        normalized_weights = {}
        for key, value in weights.items():
            # Remove _score suffix for display
            norm_key = key.replace("_score", "")
            normalized_weights[norm_key] = value
        
        return ModelInfoResponse(
            version=weight_data.get("version", "unknown"),
            method=weight_data.get("method", "unknown"),
            trained_at=weight_data.get("trained_at", ""),
            r2_score=weight_data.get("r2_score", 0.0),
            dataset_hash=weight_data.get("dataset_hash", ""),
            weights=normalized_weights,
            samples=weight_data.get("metrics", {}).get("samples")
        )
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse weight file: {e}"
        )
    except Exception as e:
        logger.error("Failed to get model info: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/monitoring/cycle",
    summary="Run monitoring cycle",
    description="Run a complete ML monitoring cycle: metrics, triggers, auto-retrain, deploy",
)
async def run_monitoring_cycle():
    """
    Run a complete ML monitoring cycle:
    1. Check inference metrics
    2. Check retrain triggers
    3. Auto-retrain if needed
    4. Deploy new model if training succeeds
    """
    controller = get_main_controller()
    if not controller:
        raise HTTPException(status_code=503, detail="MainController not available")
    
    try:
        result = await asyncio.to_thread(controller.run_ml_monitoring_cycle)
        return result
    except Exception as e:
        logger.error("Monitoring cycle failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# Governance-Grade ML Registry + Retrain + Eval  (Prompt-12 additions)
#
# These three endpoints satisfy ML governance: every model version is
# registered, every retrain is logged, and ML never runs uncontrolled
# in the background (RetrainJobLog enforces single-job concurrency).
# ══════════════════════════════════════════════════════════════════════════════

class RetrainRequest(BaseModel):
    """Request body for POST /ml/retrain."""
    triggered_by: str = Field(
        default="manual",
        description="Who/what triggered this retrain: 'manual', 'drift', 'schedule', etc.",
    )
    dry_run: bool = Field(
        default=False,
        description="If true, validate trigger eligibility but do NOT start training.",
    )


class RetrainResponse(BaseModel):
    """Response schema for POST /ml/retrain."""
    job_id:       str
    status:       str
    triggered_by: str
    started_at:   str
    message:      str
    dry_run:      bool = False


class EvalMetricsResponse(BaseModel):
    """Latest evaluation metrics snapshot."""
    model_version:               str
    sample_size:                 int
    labelled_size:               int
    rolling_accuracy:            Optional[float]
    rolling_precision:           Optional[float]
    rolling_recall:              Optional[float]
    rolling_f1:                  Optional[float]
    calibration_error:           Optional[float]  # Brier Score
    ece:                         Optional[float]
    model_performance_confidence: Optional[float]
    explanation_confidence_mean:  Optional[float]
    active_alert_count:          int
    timestamp:                   str
    source:                      str              # "live" | "log"


@router.post(
    "/retrain",
    response_model=RetrainResponse,
    status_code=202,
    summary="Trigger model retraining (governed)",
    description=(
        "Start a new retrain job.  The job is recorded in retrain_jobs.jsonl "
        "before any training begins.  If a job is already RUNNING, returns "
        "HTTP 409 Conflict — ML never runs uncontrolled in the background. "
        "Pass ``dry_run=true`` to check eligibility without starting training."
    ),
)
async def trigger_retrain(body: RetrainRequest = None, _ctx: RoleContext = Depends(operator_guard)):
    """
    Governed retrain trigger.

    Concurrency guard
    -----------------
    Only one retrain job may be RUNNING at a time.  If another is already
    running, HTTP 409 is returned with the active job ID.
    """
    from backend.ml.retrain_job_log import get_retrain_job_log, RetrainConflictError
    from backend.ml.model_registry import get_model_registry, ModelStatus

    if body is None:
        body = RetrainRequest()

    job_log  = get_retrain_job_log()
    registry = get_model_registry()

    # ── dry run – check and return without starting ──────────────────
    if body.dry_run:
        active = job_log.get_active_job()
        if active:
            return RetrainResponse(
                job_id       = active.job_id,
                status       = "conflict",
                triggered_by = active.triggered_by,
                started_at   = active.started_at,
                message      = f"Job {active.job_id} is already running.",
                dry_run      = True,
            )
        return RetrainResponse(
            job_id       = "dry-run",
            status       = "eligible",
            triggered_by = body.triggered_by,
            started_at   = datetime.now(timezone.utc).isoformat(),
            message      = "No active job; retrain can proceed.",
            dry_run      = True,
        )

    # ── start job (concurrency guard) ────────────────────────────────
    try:
        job = job_log.start_job(triggered_by=body.triggered_by)
    except RetrainConflictError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    # ── register a TRAINING model version ────────────────────────────
    ts      = datetime.now(timezone.utc)
    new_ver = f"v{ts.strftime('%Y%m%d.%H%M%S')}"
    registry.register(
        version         = new_ver,
        status          = ModelStatus.TRAINING,
        retrain_trigger = body.triggered_by,
        notes           = f"retrain job {job.job_id}",
    )

    # ── background training task ──────────────────────────────────────
    async def _run_training():
        """Run training in a background thread; update registry+job on finish."""
        import traceback

        def _train_sync():
            ctrl = get_main_controller()
            if ctrl is None:
                return None
            try:
                return ctrl.run_retrain(body.triggered_by, True)
            except Exception:
                return None

        try:
            result = await asyncio.to_thread(_train_sync)
            # Extract metrics if returned
            metrics: Optional[Dict] = None
            if isinstance(result, dict):
                m = result.get("metrics", result)
                metrics = {
                    "accuracy":  m.get("accuracy"),
                    "precision": m.get("precision"),
                    "recall":    m.get("recall"),
                    "f1":        m.get("f1"),
                }
                registry.update_status(
                    new_ver,
                    ModelStatus.STAGED,
                    notes="training completed",
                )
            job_log.complete_job(job.job_id, metrics=metrics)
            logger.info("[RETRAIN] job %s completed", job.job_id)
        except Exception as exc:
            err = traceback.format_exc()
            job_log.fail_job(job.job_id, error=str(exc))
            registry.update_status(new_ver, ModelStatus.ARCHIVED, notes=f"training failed: {exc}")
            logger.error("[RETRAIN] job %s failed: %s", job.job_id, err)

    asyncio.create_task(_run_training())

    return RetrainResponse(
        job_id       = job.job_id,
        status       = job.status,
        triggered_by = job.triggered_by,
        started_at   = job.started_at,
        message      = f"Training started for model {new_ver}.",
    )


@router.get(
    "/eval",
    response_model=EvalMetricsResponse,
    summary="Latest evaluation metrics snapshot",
    description=(
        "Returns the most recent evaluation snapshot combining rolling live "
        "metrics (accuracy, precision, recall, F1, calibration) from the "
        "in-memory RollingEvaluator.  Falls back to the newest persisted "
        "record in evaluation_metrics.jsonl when the live window is empty."
    ),
)
async def get_eval_metrics(_ctx: RoleContext = Depends(viewer_guard)):
    """
    Get latest evaluation metrics.

    Tries the live rolling evaluator first; falls back to the persisted log.
    Returns the standardised accuracy/precision/recall/f1 fields the frontend
    needs to render a metrics chart.
    """
    try:
        from backend.evaluation.rolling_evaluator import get_rolling_evaluator
        ev   = get_rolling_evaluator()
        snap = ev.snapshot()
        if snap.rolling_accuracy is not None or snap.sample_size > 0:
            return EvalMetricsResponse(
                model_version               = snap.model_version,
                sample_size                 = snap.sample_size,
                labelled_size               = snap.labelled_size,
                rolling_accuracy            = snap.rolling_accuracy,
                rolling_precision           = snap.rolling_precision,
                rolling_recall              = snap.rolling_recall,
                rolling_f1                  = snap.rolling_f1,
                calibration_error           = snap.brier_score,
                ece                         = snap.ece,
                model_performance_confidence= snap.model_performance_confidence,
                explanation_confidence_mean = snap.explanation_confidence_mean,
                active_alert_count          = len(snap.active_alerts),
                timestamp                   = snap.timestamp,
                source                      = "live",
            )
    except Exception as exc:
        logger.warning("[ML-EVAL] live evaluator unavailable: %s", exc)

    # Fall back to the JSONL log
    try:
        from backend.evaluation.eval_metrics_log import get_eval_metrics_logger
        log_inst = get_eval_metrics_logger()
        rec = log_inst.latest()
        if rec:
            return EvalMetricsResponse(
                model_version               = rec.get("model_version", "unknown"),
                sample_size                 = rec.get("sample_size", 0),
                labelled_size               = rec.get("labelled_size", 0),
                rolling_accuracy            = rec.get("rolling_accuracy"),
                rolling_precision           = rec.get("rolling_precision"),
                rolling_recall              = rec.get("rolling_recall"),
                rolling_f1                  = rec.get("rolling_f1"),
                calibration_error           = rec.get("calibration_error"),
                ece                         = rec.get("ece"),
                model_performance_confidence= rec.get("model_performance_confidence"),
                explanation_confidence_mean = rec.get("explanation_confidence_mean"),
                active_alert_count          = rec.get("active_alert_count", 0),
                timestamp                   = rec.get("timestamp", ""),
                source                      = "log",
            )
    except Exception as exc:
        logger.warning("[ML-EVAL] log fallback failed: %s", exc)

    # Nothing available — return empty snapshot
    now = datetime.now(timezone.utc).isoformat()
    return EvalMetricsResponse(
        model_version               = "unknown",
        sample_size                 = 0,
        labelled_size               = 0,
        rolling_accuracy            = None,
        rolling_precision           = None,
        rolling_recall              = None,
        rolling_f1                  = None,
        calibration_error           = None,
        ece                         = None,
        model_performance_confidence= None,
        explanation_confidence_mean = None,
        active_alert_count          = 0,
        timestamp                   = now,
        source                      = "empty",
    )


@router.get(
    "/retrain/jobs",
    summary="List recent retrain jobs",
    description="Returns the most recent retrain jobs from retrain_jobs.jsonl.",
)
async def list_retrain_jobs(limit: int = Query(default=20, ge=1, le=200), _ctx: RoleContext = Depends(viewer_guard)):
    """List recent retrain jobs for the admin UI."""
    from backend.ml.retrain_job_log import get_retrain_job_log
    log_inst = get_retrain_job_log()
    return {
        "count": log_inst.count(),
        "jobs":  log_inst.list_recent(limit=limit),
    }


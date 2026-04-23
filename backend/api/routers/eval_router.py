# backend/api/routers/eval_router.py
"""
Evaluation API Router
=====================

REST API for ML Evaluation operations.

Endpoints:
    GET  /api/v1/eval                  - List evaluation runs
    GET  /api/v1/eval/{run_id}         - Get evaluation run details
    POST /api/v1/eval                  - Create/trigger new evaluation
    GET  /api/v1/eval/{run_id}/metrics - Get metrics for a run
    GET  /api/v1/eval/health           - Eval service health
    GET  /api/v1/eval/baselines        - Get current baselines

RBAC:
    - Read: Admin, Ops, Auditor, Analyst
    - Write/Execute: Admin, Ops
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.response_contract import (
    success_response,
    paginated_response,
    health_response,
    error_response,
    APIError,
    ErrorCode,
)
from backend.api.middleware.rbac import (
    require_any_role,
    require_permission,
    Permission,
    READ_ROLES,
    WRITE_ROLES,
)
from backend.api.middleware.auth import AuthResult

logger = logging.getLogger("api.routers.eval")

# Router instance
router = APIRouter(tags=["Evaluation"])

# Service reference (injected at startup)
_eval_service = None
_main_controller = None
_start_time = time.time()


# ═══════════════════════════════════════════════════════════════════════════
#  Dependency Injection
# ═══════════════════════════════════════════════════════════════════════════

def set_eval_service(service) -> None:
    """Inject evaluation service."""
    global _eval_service
    _eval_service = service
    logger.info("Eval service injected")


def set_main_controller(controller) -> None:
    """Inject main controller (for triggering evals)."""
    global _main_controller
    _main_controller = controller
    logger.info("Main controller injected for eval")


def get_eval_service():
    """Get evaluation service, creating if needed."""
    global _eval_service
    if _eval_service is None:
        try:
            from backend.evaluation.service import MLEvaluationService
            _eval_service = MLEvaluationService()
            _eval_service.load_config()
        except Exception as e:
            logger.error(f"Failed to initialize eval service: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Evaluation service not available"
            )
    return _eval_service


# ═══════════════════════════════════════════════════════════════════════════
#  Request/Response Models
# ═══════════════════════════════════════════════════════════════════════════

class EvalRunRequest(BaseModel):
    """Request to trigger a new evaluation run."""
    config_override: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional config overrides"
    )
    run_id: Optional[str] = Field(
        default=None,
        description="Custom run ID (auto-generated if not provided)"
    )


class EvalRunSummary(BaseModel):
    """Summary of an evaluation run."""
    run_id: str = Field(..., description="Unique run identifier")
    timestamp: str = Field(..., description="Run timestamp")
    model: str = Field(..., description="Model type used")
    kfold: int = Field(..., description="K-fold cross-validation count")
    quality_passed: bool = Field(..., description="Whether quality gate passed")
    regression_status: str = Field(default="UNKNOWN", description="Regression check status")
    drift_status: str = Field(default="UNKNOWN", description="Drift detection status")


class EvalMetrics(BaseModel):
    """Evaluation metrics."""
    accuracy: float = Field(..., description="Overall accuracy")
    precision_macro: float = Field(..., description="Macro-averaged precision")
    recall_macro: float = Field(..., description="Macro-averaged recall")
    f1_macro: float = Field(..., description="Macro-averaged F1 score")
    confusion_matrix: Optional[List[List[int]]] = Field(
        default=None,
        description="Confusion matrix"
    )


class EvalRunDetail(BaseModel):
    """Detailed evaluation run information."""
    run_id: str
    timestamp: str
    model: str
    kfold: int
    metrics: EvalMetrics
    quality_passed: bool
    output_path: str
    stability: Dict[str, Any]


class BaselineInfo(BaseModel):
    """Baseline metrics information."""
    accuracy: float
    f1_macro: float
    dataset_hash: str
    updated_at: str
    model_type: str


# ═══════════════════════════════════════════════════════════════════════════
#  Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/health")
async def eval_health():
    """
    Evaluation service health check.
    
    Returns service status and uptime.
    """
    try:
        service = get_eval_service()
        service_ok = service is not None
    except Exception:
        service_ok = False
    
    return health_response(
        service="eval",
        healthy=service_ok,
        uptime_seconds=time.time() - _start_time,
        dependencies={
            "eval_service": service_ok,
        }
    )


@router.get("")
async def list_eval_runs(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status_filter: Optional[str] = Query(default=None, description="Filter by status"),
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """
    List all evaluation runs.
    
    Supports pagination and filtering.
    """
    try:
        # Get runs from registry
        runs_dir = Path(__file__).resolve().parents[2] / "runs"
        runs = []
        
        if runs_dir.exists():
            import json
            for run_file in sorted(runs_dir.glob("eval_*.json"), reverse=True):
                try:
                    with open(run_file, "r", encoding="utf-8") as f:
                        run_data = json.load(f)
                        
                    # Apply status filter
                    if status_filter:
                        stability = run_data.get("stability", {})
                        reg_status = stability.get("regression_status", "UNKNOWN")
                        if status_filter.upper() not in reg_status:
                            continue
                    
                    runs.append(EvalRunSummary(
                        run_id=run_data.get("run_id", run_file.stem),
                        timestamp=run_data.get("timestamp", ""),
                        model=run_data.get("model", "unknown"),
                        kfold=run_data.get("kfold", 0),
                        quality_passed=run_data.get("quality_passed", False),
                        regression_status=run_data.get("stability", {}).get("regression_status", "UNKNOWN"),
                        drift_status=run_data.get("stability", {}).get("drift_status", "UNKNOWN"),
                    ).model_dump())
                except Exception as e:
                    logger.warning(f"Failed to load run {run_file}: {e}")
        
        # Paginate
        total = len(runs)
        start = (page - 1) * page_size
        end = start + page_size
        page_runs = runs[start:end]
        
        return paginated_response(
            items=page_runs,
            page=page,
            page_size=page_size,
            total_items=total,
            item_key="runs",
        )
    except Exception as e:
        logger.error(f"List runs error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/baselines")
async def get_baselines(
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """
    Get current baseline metrics.
    
    Returns the baseline metrics used for regression detection.
    """
    try:
        baseline_path = Path(__file__).resolve().parents[2] / "baseline" / "baseline_metrics.json"
        fingerprint_path = Path(__file__).resolve().parents[2] / "baseline" / "dataset_fingerprint.json"
        
        baseline = {}
        fingerprint = {}
        
        if baseline_path.exists():
            import json
            with open(baseline_path, "r", encoding="utf-8") as f:
                baseline = json.load(f)
        
        if fingerprint_path.exists():
            import json
            with open(fingerprint_path, "r", encoding="utf-8") as f:
                fingerprint = json.load(f)
        
        return success_response(data={
            "baseline": baseline,
            "fingerprint": fingerprint,
        })
    except Exception as e:
        logger.error(f"Get baselines error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ═══════════════════════════════════════════════════════════════════════════
# ROLLING METRICS — REAL-TIME EVALUATION (Prompt-4 additions)
# Must be placed BEFORE /{run_id} to avoid wildcard shadowing.
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/rolling-metrics",
    summary="Real-Time Rolling Evaluation Metrics",
    description=(
        "Returns the live rolling evaluation snapshot: accuracy, F1, "
        "precision, recall, Brier Score, ECE, confidence axes, and active alerts. "
        "Metrics are computed over the in-memory rolling window of recent decisions."
    ),
)
async def get_rolling_metrics(
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """Real-time rolling metrics snapshot from the inference evaluator."""
    from backend.evaluation.rolling_evaluator import get_rolling_evaluator
    evaluator = get_rolling_evaluator()
    snap = evaluator.snapshot()
    return success_response(data=snap.to_dict())


@router.post(
    "/ground-truth",
    summary="Submit Ground Truth for a Decision",
    description=(
        "Attaches a verified ground-truth label to a previously logged decision. "
        "Once attached, this sample is included in rolling accuracy/F1/calibration "
        "computations on the next snapshot."
    ),
)
async def submit_ground_truth(
    trace_id: str = Query(..., description="The decision trace ID to label"),
    true_label: str = Query(..., description="Verified career outcome / ground truth label"),
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """Attach ground truth to a previously logged prediction."""
    from backend.evaluation.rolling_evaluator import get_rolling_evaluator
    evaluator = get_rolling_evaluator()
    sample = evaluator.update_ground_truth(
        trace_id=trace_id,
        true_label=true_label,
    )
    if sample is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"trace_id='{trace_id}' not found in the rolling window. "
                "It may have been evicted (window size: 500)."
            ),
        )
    return success_response(data={
        "trace_id": trace_id,
        "predicted_label": sample.predicted_label,
        "true_label": sample.true_label,
        "correct": sample.predicted_label == sample.true_label,
        "message": "Ground truth attached; sample will be included in next metrics snapshot.",
    })


@router.get(
    "/metrics-log",
    summary="Persisted Evaluation Metric Snapshots",
    description=(
        "Returns historical evaluation metric snapshots from "
        "backend/data/logs/evaluation_metrics.jsonl."
    ),
)
async def list_metrics_log(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    model_version: str = Query(default=None, description="Filter by model version"),
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """List persisted evaluation metric snapshots (newest first)."""
    from backend.evaluation.eval_metrics_log import get_eval_metrics_logger
    logger_inst = get_eval_metrics_logger()
    records = logger_inst.read_recent(
        limit=limit,
        offset=offset,
        model_version=model_version or None,
    )
    return success_response(data={
        "count": len(records),
        "total": logger_inst.count(),
        "records": records,
        "log_path": str(logger_inst._log_path),
    })


@router.get("/{run_id}")
async def get_eval_run(
    run_id: str,
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """
    Get details of a specific evaluation run.
    """
    try:
        import json
        
        # Try multiple locations
        runs_dir = Path(__file__).resolve().parents[2] / "runs"
        output_dir = Path(__file__).resolve().parents[2] / "outputs"
        
        # Look for the run file
        run_data = None
        for search_dir in [runs_dir, output_dir]:
            if not search_dir.exists():
                continue
            for pattern in [f"{run_id}.json", f"*{run_id}*.json"]:
                for run_file in search_dir.glob(pattern):
                    try:
                        with open(run_file, "r", encoding="utf-8") as f:
                            run_data = json.load(f)
                        break
                    except Exception:
                        continue
                if run_data:
                    break
            if run_data:
                break
        
        if not run_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Evaluation run '{run_id}' not found"
            )
        
        return success_response(data={"run": run_data})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get run error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/{run_id}/metrics")
async def get_eval_metrics(
    run_id: str,
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """
    Get metrics for a specific evaluation run.
    """
    try:
        import json
        
        runs_dir = Path(__file__).resolve().parents[2] / "runs"
        
        run_data = None
        if runs_dir.exists():
            for run_file in runs_dir.glob(f"*{run_id}*.json"):
                try:
                    with open(run_file, "r", encoding="utf-8") as f:
                        run_data = json.load(f)
                    break
                except Exception:
                    continue
        
        if not run_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Evaluation run '{run_id}' not found"
            )
        
        metrics = run_data.get("metrics", {})
        
        return success_response(data={
            "run_id": run_id,
            "metrics": metrics,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get metrics error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("")
async def create_eval_run(
    request: EvalRunRequest,
    auth: AuthResult = Depends(require_permission(Permission.EVAL_EXECUTE)),
):
    """
    Trigger a new evaluation run.
    
    This starts an ML evaluation pipeline with optional config overrides.
    """
    try:
        service = get_eval_service()
        
        # Load config with overrides if provided
        if request.config_override:
            current_config = service.config.copy()
            current_config.update(request.config_override)
            service._config = current_config
        
        # Run pipeline
        result = service.run_pipeline(run_id=request.run_id)
        
        return success_response(data={
            "run": {
                "run_id": result.get("run_id"),
                "timestamp": result.get("timestamp"),
                "model": result.get("model"),
                "kfold": result.get("kfold"),
                "metrics": result.get("metrics"),
                "quality_passed": result.get("quality_passed"),
                "stability": result.get("stability"),
            },
            "message": "Evaluation run completed successfully"
        })
    except Exception as e:
        logger.error(f"Create eval run error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/{run_id}")
async def delete_eval_run(
    run_id: str,
    auth: AuthResult = Depends(require_permission(Permission.EVAL_WRITE)),
):
    """
    Delete an evaluation run record.
    
    This removes the run from the registry (does not affect models).
    """
    try:
        import os
        
        runs_dir = Path(__file__).resolve().parents[2] / "runs"
        deleted = False
        
        if runs_dir.exists():
            for run_file in runs_dir.glob(f"*{run_id}*.json"):
                os.remove(run_file)
                deleted = True
                logger.info(f"Deleted eval run file: {run_file}")
        
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Evaluation run '{run_id}' not found"
            )
        
        return success_response(data={
            "deleted": run_id,
            "message": "Evaluation run deleted successfully"
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete run error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


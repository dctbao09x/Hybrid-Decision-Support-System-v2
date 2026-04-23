from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.explain.storage import get_explanation_storage
from backend.explain.calibration import get_calibration_dataset, ConfidenceCalibrator
from backend.mlops.security import viewer_guard, admin_guard

import io


router = APIRouter(prefix="/explain", tags=["explain-audit"])


# ==============================================================================
# History & Stats Endpoints
# ==============================================================================

@router.get("/history")
async def explain_history(
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=2000),
    _: object = Depends(viewer_guard),
):
    """Get explanation history within date range."""
    storage = get_explanation_storage()
    rows = await storage.get_history(from_date=from_date, to_date=to_date, limit=limit)
    return {
        "items": rows,
        "count": len(rows),
        "from": from_date,
        "to": to_date,
    }


@router.get("/stats")
async def explain_stats(_: object = Depends(viewer_guard)):
    """Get explanation storage statistics."""
    storage = get_explanation_storage()
    stats = await storage.get_stats()
    stats["retention_days_min"] = 180
    return stats


# ==============================================================================
# Trace Graph Endpoints
# ==============================================================================

@router.get("/graph/{trace_id}")
async def explain_trace_graph(trace_id: str, _: object = Depends(viewer_guard)):
    """Get trace graph for a specific trace."""
    storage = get_explanation_storage()
    graph = await storage.get_trace_graph(trace_id)
    if not graph.nodes:
        raise HTTPException(status_code=404, detail=f"Trace graph not found: {trace_id}")
    return graph.to_dict()


@router.get("/graph/{trace_id}/backtrack")
async def explain_backtrack(
    trace_id: str,
    target: str = Query(..., description="Target node id for backtracking"),
    _: object = Depends(viewer_guard),
):
    """Backtrack trace path to target node."""
    storage = get_explanation_storage()
    path = await storage.backtrack(trace_id=trace_id, target_node=target)
    if not path:
        raise HTTPException(status_code=404, detail="Backtrack path not found")
    return {
        "trace_id": trace_id,
        "target": target,
        "path": path,
    }


# ==============================================================================
# Calibration Endpoints
# ==============================================================================

@router.get("/calibration/report")
async def calibration_report(
    n_bins: int = Query(default=10, ge=2, le=50),
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    _: object = Depends(viewer_guard),
):
    """
    Get confidence calibration report with Brier Score and ECE.

    Returns:
        - brier_score: Mean squared error of probability predictions (lower is better)
        - expected_calibration_error: Measure of miscalibration (< 0.1 is good)
        - max_calibration_error: Maximum bin calibration error
        - bins: Reliability diagram data for each bin
        - is_well_calibrated: Boolean indicating if ECE < 0.1
    """
    dataset = get_calibration_dataset()
    report = dataset.generate_report(n_bins=n_bins, from_date=from_date, to_date=to_date)
    return report.to_dict()


@router.get("/calibration/diagram")
async def calibration_diagram(
    n_bins: int = Query(default=10, ge=2, le=50),
    _: object = Depends(viewer_guard),
):
    """
    Get reliability diagram data for visualization.

    Returns chart-ready data:
        - diagonal: Perfect calibration reference line
        - calibration_curve: Actual calibration points
        - histogram: Sample distribution across bins
    """
    dataset = get_calibration_dataset()
    samples = dataset.load_samples()

    calibrator = ConfidenceCalibrator(n_bins=n_bins)
    calibrator.add_samples_from_list(samples)

    return calibrator.generate_reliability_diagram_data()


@router.post("/calibration/outcome")
async def record_calibration_outcome(
    trace_id: str,
    predicted_confidence: float,
    predicted_class: str,
    actual_class: str,
    _: object = Depends(viewer_guard),
):
    """
    Record a prediction outcome for calibration analysis.

    This endpoint should be called when ground truth becomes available.
    """
    dataset = get_calibration_dataset()
    dataset.add_outcome(
        trace_id=trace_id,
        predicted_confidence=predicted_confidence,
        predicted_class=predicted_class,
        actual_class=actual_class,
    )
    return {
        "status": "recorded",
        "trace_id": trace_id,
        "correct": predicted_class == actual_class,
    }


# ==============================================================================
# Legal Hold Endpoints (Admin Only)
# ==============================================================================

@router.post("/legal-hold/{trace_id}")
async def set_legal_hold(
    trace_id: str,
    ctx: object = Depends(admin_guard),
):
    """
    Set legal hold on a trace to prevent deletion during retention cleanup.

    Requires admin role.
    """
    storage = get_explanation_storage()

    # Verify trace exists
    record = await storage.get_by_trace_id(trace_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")

    user = getattr(ctx, "role", "admin")
    result = await storage.set_legal_hold(trace_id, hold=True, user=user)

    return {
        "status": "legal_hold_set",
        **result,
    }


@router.delete("/legal-hold/{trace_id}")
async def clear_legal_hold(
    trace_id: str,
    ctx: object = Depends(admin_guard),
):
    """
    Remove legal hold from a trace, allowing normal retention cleanup.

    Requires admin role.
    """
    storage = get_explanation_storage()

    # Verify trace exists
    record = await storage.get_by_trace_id(trace_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")

    user = getattr(ctx, "role", "admin")
    result = await storage.set_legal_hold(trace_id, hold=False, user=user)

    return {
        "status": "legal_hold_cleared",
        **result,
    }


@router.get("/legal-hold/{trace_id}")
async def get_legal_hold_status(
    trace_id: str,
    _: object = Depends(viewer_guard),
):
    """Get legal hold status for a trace."""
    storage = get_explanation_storage()
    status = await storage.get_legal_hold_status(trace_id)

    if not status:
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")

    return status


@router.get("/legal-holds")
async def list_legal_holds(_: object = Depends(viewer_guard)):
    """List all traces with active legal holds."""
    storage = get_explanation_storage()
    holds = await storage.list_legal_holds()
    return {
        "items": holds,
        "count": len(holds),
    }


# ==============================================================================
# PDF Export Endpoints
# ==============================================================================

@router.get("/{trace_id}/pdf")
async def export_trace_pdf(
    trace_id: str,
    include_graph: bool = Query(default=True),
    _: object = Depends(viewer_guard),
):
    """
    Export explanation trace as PDF.

    Returns a downloadable PDF file with:
        - Summary information
        - Rule path
        - Evidence
        - Feature snapshot
        - Trace graph (optional)
        - Integrity verification
    """
    try:
        from backend.explain.export.pdf_generator import ExplainPdfGenerator
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail="PDF generation not available. Install reportlab: pip install reportlab"
        ) from e

    storage = get_explanation_storage()
    record = await storage.get_by_trace_id(trace_id)

    if not record:
        raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")

    # Get graph data if requested
    if include_graph:
        graph = await storage.get_trace_graph(trace_id)
        if graph.nodes:
            record["graph"] = graph.to_dict()

    # Generate PDF
    generator = ExplainPdfGenerator()
    pdf_bytes = generator.generate(record, include_graph=include_graph)

    # Return as downloadable file
    filename = f"explanation_{trace_id}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


# NOTE: The /{trace_id} GET endpoint is now in explain_router.py (get_explain)
# to avoid duplicate route registration. Keeping it there for centralized auth handling.


# Legacy alias - redirect to new location (for backward compat)
# @router.get("/{trace_id}") - REMOVED: Duplicate of /api/v1/explain/{trace_id} in explain_router.py

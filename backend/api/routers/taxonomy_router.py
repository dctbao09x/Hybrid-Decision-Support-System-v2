# backend/api/routers/taxonomy_router.py
"""
Taxonomy API Router
===================

REST API for Taxonomy operations.

Endpoints:
    GET  /api/v1/taxonomy                      - List all datasets
    GET  /api/v1/taxonomy/{dataset}            - List entries in a dataset
    GET  /api/v1/taxonomy/{dataset}/{entry_id} - Get entry details
    POST /api/v1/taxonomy/resolve              - Resolve text to taxonomy entry
    POST /api/v1/taxonomy/resolve-many         - Resolve multiple texts
    POST /api/v1/taxonomy/detect-intent        - Detect intent from text
    GET  /api/v1/taxonomy/health               - Taxonomy service health
    GET  /api/v1/taxonomy/coverage             - Get coverage report

Datasets:
    - skills: Technical and soft skills
    - interests: Career interests
    - education: Education levels
    - intents: Career intents/goals

RBAC:
    - Read: Admin, Ops, Auditor, Analyst
    - Write: Admin, Ops
"""

from __future__ import annotations

import logging
import time
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

logger = logging.getLogger("api.routers.taxonomy")

# Router instance
router = APIRouter(tags=["Taxonomy"])

# Service reference
_taxonomy_manager = None
_start_time = time.time()


# ═══════════════════════════════════════════════════════════════════════════
#  Dependency Injection
# ═══════════════════════════════════════════════════════════════════════════

def set_taxonomy_manager(manager) -> None:
    """Inject taxonomy manager."""
    global _taxonomy_manager
    _taxonomy_manager = manager
    logger.info("Taxonomy manager injected")


def get_taxonomy_manager():
    """Get taxonomy manager, creating if needed."""
    global _taxonomy_manager
    if _taxonomy_manager is None:
        try:
            from backend.taxonomy.manager import TaxonomyManager
            base_dir = Path(__file__).resolve().parents[2] / "taxonomy" / "data"
            _taxonomy_manager = TaxonomyManager(base_dir)
        except Exception as e:
            logger.error(f"Failed to initialize taxonomy manager: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Taxonomy service not available"
            )
    return _taxonomy_manager


# ═══════════════════════════════════════════════════════════════════════════
#  Request/Response Models
# ═══════════════════════════════════════════════════════════════════════════

class ResolveRequest(BaseModel):
    """Request to resolve text to taxonomy entry."""
    dataset: str = Field(..., description="Dataset name (skills, interests, education, intents)")
    text: str = Field(..., description="Text to resolve")


class ResolveManyRequest(BaseModel):
    """Request to resolve multiple texts."""
    dataset: str = Field(..., description="Dataset name")
    texts: List[str] = Field(..., description="Texts to resolve")


class DetectIntentRequest(BaseModel):
    """Request to detect intent from text."""
    text: str = Field(..., description="Text to analyze for intent")


class TaxonomyEntryResponse(BaseModel):
    """Taxonomy entry response."""
    id: str = Field(..., description="Entry ID")
    canonical_label: str = Field(..., description="Canonical/official name")
    priority: int = Field(default=0, description="Priority/rank")
    deprecated: bool = Field(default=False, description="Whether entry is deprecated")
    aliases: Dict[str, List[str]] = Field(default_factory=dict, description="Language aliases")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class DatasetSummary(BaseModel):
    """Summary of a taxonomy dataset."""
    name: str = Field(..., description="Dataset name")
    entries_count: int = Field(..., description="Number of entries")
    aliases_count: int = Field(default=0, description="Total number of aliases")
    deprecated_count: int = Field(default=0, description="Number of deprecated entries")


class CoverageReport(BaseModel):
    """Coverage report for all datasets."""
    datasets: Dict[str, Dict[str, int]] = Field(
        default_factory=dict,
        description="Per-dataset coverage stats"
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Dataset Names
# ═══════════════════════════════════════════════════════════════════════════

DATASET_NAMES = ["skills", "interests", "education", "intents"]


# ═══════════════════════════════════════════════════════════════════════════
#  Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/health")
async def taxonomy_health():
    """
    Taxonomy service health check.
    
    Returns service status and loaded datasets info.
    """
    try:
        manager = get_taxonomy_manager()
        counts = manager.self_check() if manager else {}
        service_ok = len(counts) > 0
    except Exception:
        service_ok = False
        counts = {}
    
    return health_response(
        service="taxonomy",
        healthy=service_ok,
        uptime_seconds=time.time() - _start_time,
        dependencies={
            "taxonomy_manager": service_ok,
            **{f"{k}_loaded": v > 0 for k, v in counts.items()}
        }
    )


@router.get("/coverage")
async def get_coverage(
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """
    Get coverage report for all datasets.
    
    Returns statistics about entries, aliases, and deprecated items.
    """
    try:
        manager = get_taxonomy_manager()
        coverage = manager.coverage_report()
        
        return success_response(data={
            "coverage": coverage,
        })
    except Exception as e:
        logger.error(f"Coverage report error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("")
async def list_datasets(
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """
    List all available taxonomy datasets.
    
    Returns summary of each dataset.
    """
    try:
        manager = get_taxonomy_manager()
        coverage = manager.coverage_report()
        
        datasets = []
        for name in DATASET_NAMES:
            stats = coverage.get(name, {})
            datasets.append(DatasetSummary(
                name=name,
                entries_count=stats.get("entries", 0),
                aliases_count=stats.get("aliases", 0),
                deprecated_count=stats.get("deprecated", 0),
            ).model_dump())
        
        return success_response(data={"datasets": datasets})
    except Exception as e:
        logger.error(f"List datasets error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/list")
async def list_taxonomy_for_frontend():
    """
    Public endpoint — returns canonical labels for skills, interests, and education.

    No auth required (used by the frontend form before login).
    Deprecated entries are excluded. Results sorted by priority desc.
    """
    try:
        manager = get_taxonomy_manager()
        result: Dict[str, List[Dict[str, str]]] = {}
        for dataset_name in ["skills", "interests", "education"]:
            ds = manager.get_dataset(dataset_name)
            entries = sorted(
                [e for e in ds.entries if not e.deprecated],
                key=lambda e: e.priority,
                reverse=True,
            )
            result[dataset_name] = [
                {"id": e.id, "label": e.canonical_label}
                for e in entries
            ]
        return success_response(data=result)
    except Exception as e:
        logger.error(f"Taxonomy list error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get("/{dataset}")
async def list_entries(
    dataset: str,
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=50, ge=1, le=200, description="Items per page"),
    include_deprecated: bool = Query(default=False, description="Include deprecated entries"),
    search: Optional[str] = Query(default=None, description="Search by label"),
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """
    List entries in a taxonomy dataset.
    
    Supports pagination and filtering.
    """
    if dataset not in DATASET_NAMES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset '{dataset}' not found. Available: {DATASET_NAMES}"
        )
    
    try:
        manager = get_taxonomy_manager()
        ds = manager.get_dataset(dataset)
        
        entries = []
        for entry in ds.entries:
            # Apply deprecated filter
            if not include_deprecated and entry.deprecated:
                continue
            
            # Apply search filter
            if search:
                search_lower = search.lower()
                match = search_lower in entry.canonical_label.lower()
                if not match:
                    for aliases in entry.aliases.values():
                        if any(search_lower in a.lower() for a in aliases):
                            match = True
                            break
                if not match:
                    continue
            
            entries.append(TaxonomyEntryResponse(
                id=entry.id,
                canonical_label=entry.canonical_label,
                priority=entry.priority,
                deprecated=entry.deprecated,
                aliases=entry.aliases,
                metadata=entry.metadata or {},
            ).model_dump())
        
        # Sort by priority
        entries.sort(key=lambda x: x.get("priority", 0), reverse=True)
        
        # Paginate
        total = len(entries)
        start = (page - 1) * page_size
        end = start + page_size
        page_entries = entries[start:end]
        
        return paginated_response(
            items=page_entries,
            page=page,
            page_size=page_size,
            total_items=total,
            item_key="entries",
        )
    except Exception as e:
        logger.error(f"List entries error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/{dataset}/{entry_id}")
async def get_entry(
    dataset: str,
    entry_id: str,
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """
    Get a specific taxonomy entry by ID.
    """
    if dataset not in DATASET_NAMES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset '{dataset}' not found. Available: {DATASET_NAMES}"
        )
    
    try:
        manager = get_taxonomy_manager()
        entry = manager.get_entry(dataset, entry_id)
        
        if not entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Entry '{entry_id}' not found in dataset '{dataset}'"
            )
        
        return success_response(data={
            "entry": TaxonomyEntryResponse(
                id=entry.id,
                canonical_label=entry.canonical_label,
                priority=entry.priority,
                deprecated=entry.deprecated,
                aliases=entry.aliases,
                metadata=entry.metadata or {},
            ).model_dump()
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get entry error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/resolve")
async def resolve_text(
    request: ResolveRequest,
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """
    Resolve text to best matching taxonomy entry.
    
    Uses fuzzy matching to find the best match.
    """
    if request.dataset not in DATASET_NAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dataset '{request.dataset}' not found. Available: {DATASET_NAMES}"
        )
    
    try:
        manager = get_taxonomy_manager()
        entry = manager.resolve_best(request.dataset, request.text)
        
        if not entry:
            return success_response(data={
                "match": None,
                "input_text": request.text,
                "message": "No match found"
            })
        
        return success_response(data={
            "match": TaxonomyEntryResponse(
                id=entry.id,
                canonical_label=entry.canonical_label,
                priority=entry.priority,
                deprecated=entry.deprecated,
                aliases=entry.aliases,
                metadata=entry.metadata or {},
            ).model_dump(),
            "input_text": request.text,
        })
    except Exception as e:
        logger.error(f"Resolve text error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/resolve-many")
async def resolve_many(
    request: ResolveManyRequest,
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """
    Resolve multiple texts to taxonomy entries.
    
    Returns unique matched entries.
    """
    if request.dataset not in DATASET_NAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dataset '{request.dataset}' not found. Available: {DATASET_NAMES}"
        )
    
    try:
        manager = get_taxonomy_manager()
        entries = manager.resolve_many(request.dataset, request.texts)
        
        matches = [
            TaxonomyEntryResponse(
                id=entry.id,
                canonical_label=entry.canonical_label,
                priority=entry.priority,
                deprecated=entry.deprecated,
                aliases=entry.aliases,
                metadata=entry.metadata or {},
            ).model_dump()
            for entry in entries
        ]
        
        return success_response(data={
            "matches": matches,
            "input_count": len(request.texts),
            "match_count": len(matches),
        })
    except Exception as e:
        logger.error(f"Resolve many error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/detect-intent")
async def detect_intent(
    request: DetectIntentRequest,
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """
    Detect career intent from text.
    
    Analyzes text to determine user's career intention.
    """
    try:
        manager = get_taxonomy_manager()
        entry = manager.detect_intent(request.text)
        
        return success_response(data={
            "intent": TaxonomyEntryResponse(
                id=entry.id,
                canonical_label=entry.canonical_label,
                priority=entry.priority,
                deprecated=entry.deprecated,
                aliases=entry.aliases,
                metadata=entry.metadata or {},
            ).model_dump(),
            "input_text": request.text,
        })
    except Exception as e:
        logger.error(f"Detect intent error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/reload")
async def reload_taxonomy(
    auth: AuthResult = Depends(require_permission(Permission.TAXONOMY_WRITE)),
):
    """
    Reload all taxonomy datasets.
    
    Re-reads data from disk and rebuilds indexes.
    """
    global _taxonomy_manager
    try:
        if _taxonomy_manager:
            _taxonomy_manager.reload()
        else:
            from backend.taxonomy.manager import TaxonomyManager
            base_dir = Path(__file__).resolve().parents[2] / "taxonomy" / "data"
            _taxonomy_manager = TaxonomyManager(base_dir)
        
        counts = _taxonomy_manager.self_check()
        
        return success_response(data={
            "reloaded": True,
            "datasets": counts,
            "message": "Taxonomy reloaded successfully"
        })
    except Exception as e:
        logger.error(f"Reload taxonomy error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

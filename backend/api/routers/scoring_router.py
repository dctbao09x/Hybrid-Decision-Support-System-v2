# backend/api/routers/scoring_router.py
"""
Scoring Engine API Router (REFACTORED)
======================================

REST API for Career Scoring operations.
ALL operations go through MainController.dispatch() — NO direct imports.

Endpoints:
    GET  /api/v1/scoring                  - Get scoring configuration
    POST /api/v1/scoring/rank             - Rank careers for user profile
    POST /api/v1/scoring/score            - Score specific careers
    GET  /api/v1/scoring/strategies       - List available scoring strategies
    GET  /api/v1/scoring/weights          - Get current weights
    PUT  /api/v1/scoring/weights          - [REMOVED 2026-02-21] Returns 410 Gone; weights are immutable
    POST /api/v1/scoring/reset            - Reset to defaults
    GET  /api/v1/scoring/health           - Scoring service health

ARCHITECTURE COMPLIANCE:
    - NO direct imports from backend.scoring.*
    - ALL operations via MainController.dispatch()
    - Follows 8-step pipeline (Validate → Auth → Authorize → Context → Service → Result → Explain → Log)

RBAC:
    - Read: Admin, Ops, Auditor, Analyst
    - Write: Admin, Ops
    - Execute: Admin, Ops, API_User
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator

from backend.api.response_contract import (
    success_response,
    health_response,
)
from backend.api.middleware.rbac import (
    require_any_role,
    require_permission,
    Permission,
    READ_ROLES,
)
from backend.api.middleware.auth import AuthResult

logger = logging.getLogger("api.routers.scoring")
security_logger = logging.getLogger("security.scoring.weights")

# Router instance
router = APIRouter(tags=["Scoring"])

# Controller reference — ONLY dependency allowed
_main_controller = None
_start_time = time.time()

# ═══════════════════════════════════════════════════════════════════════════
#  Weight Modification Hardening — Audit, Archive, Version Control
# ═══════════════════════════════════════════════════════════════════════════

WEIGHTS_ARCHIVE_DIR = Path("backend/data/weights_archive")
WEIGHTS_VERSION_FILE = Path("backend/data/weights_version.json")


def _compute_weights_checksum(weights: Dict[str, Any]) -> str:
    """Compute SHA256 checksum of weights payload."""
    canonical = json.dumps(weights, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _get_current_weight_version() -> int:
    """Get current weight version from persistent storage."""
    try:
        if WEIGHTS_VERSION_FILE.exists():
            with open(WEIGHTS_VERSION_FILE, "r") as f:
                data = json.load(f)
                return data.get("version", 0)
    except Exception:
        pass
    return 0


def _increment_weight_version() -> int:
    """Increment and persist weight version."""
    WEIGHTS_VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    current = _get_current_weight_version()
    new_version = current + 1
    with open(WEIGHTS_VERSION_FILE, "w") as f:
        json.dump({"version": new_version, "updated_at": datetime.now(timezone.utc).isoformat()}, f)
    return new_version


def _archive_weights_snapshot(
    weights: Dict[str, Any],
    checksum: str,
    version: int,
    user_id: str,
    correlation_id: str,
) -> Path:
    """
    Store current weights in immutable archive before modification.
    
    Archive format:
        weights_archive/v{version}_{timestamp}_{checksum[:8]}.json
    """
    WEIGHTS_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"v{version}_{timestamp}_{checksum[:8]}.json"
    archive_path = WEIGHTS_ARCHIVE_DIR / filename
    
    archive_data = {
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checksum": checksum,
        "weights": weights,
        "archived_by": user_id,
        "correlation_id": correlation_id,
        "immutable": True,
    }
    
    with open(archive_path, "w") as f:
        json.dump(archive_data, f, indent=2)
    
    return archive_path


# ═══════════════════════════════════════════════════════════════════════════
#  Dependency Injection — Controller Only
# ═══════════════════════════════════════════════════════════════════════════

def set_main_controller(controller) -> None:
    """
    Inject main controller for dispatch pattern.
    This is the ONLY dependency injection allowed.
    """
    global _main_controller
    _main_controller = controller
    logger.info("MainController injected into scoring router")


def get_main_controller():
    """Get main controller. Raises if not configured."""
    if _main_controller is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scoring service not initialized. MainController not injected."
        )
    return _main_controller


def _require_controller():
    """Dependency that ensures controller is available."""
    return get_main_controller()


# ═══════════════════════════════════════════════════════════════════════════
#  Request/Response Models — Data structures only, no service logic
# ═══════════════════════════════════════════════════════════════════════════

class UserProfileInput(BaseModel):
    """User profile input for scoring."""
    skills: List[str] = Field(default_factory=list, description="User skills")
    interests: List[str] = Field(default_factory=list, description="User interests")
    education_level: str = Field(default="Bachelor", description="Education level")
    ability_score: float = Field(default=0.5, ge=0.0, le=1.0, description="Self-assessed ability")
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0, description="Self-assessed confidence")


class CareerInput(BaseModel):
    """Career input for scoring."""
    name: str = Field(..., description="Career title")
    required_skills: List[str] = Field(default_factory=list, description="Required skills")
    preferred_skills: List[str] = Field(default_factory=list, description="Preferred skills")
    domain: str = Field(default="general", description="Career domain")
    domain_interests: List[str] = Field(default_factory=list, description="Domain interests")
    ai_relevance: float = Field(default=0.5, ge=0.0, le=1.0, description="AI relevance")
    growth_rate: float = Field(default=0.5, ge=0.0, le=1.0, description="Growth rate")
    competition: float = Field(default=0.5, ge=0.0, le=1.0, description="Competition level")


class RankRequest(BaseModel):
    """Request to rank careers for a user."""
    user_profile: UserProfileInput = Field(..., description="User profile")
    careers: List[CareerInput] = Field(..., description="Careers to rank")
    strategy: Optional[str] = Field(default=None, description="Scoring strategy (weighted/personalized)")
    top_n: Optional[int] = Field(default=None, ge=1, le=100, description="Return top N results")


class ScoreRequest(BaseModel):
    """Request to score specific careers."""
    user_profile: UserProfileInput = Field(..., description="User profile")
    career_names: List[str] = Field(..., description="Career names to score")
    strategy: Optional[str] = Field(default=None, description="Scoring strategy")


class WeightsInput(BaseModel):
    """Scoring weights configuration (SIMGR standard — all 5 components required non-zero)."""
    study_score: float = Field(default=0.25, ge=0.05, le=1.0)
    interest_score: float = Field(default=0.25, ge=0.05, le=1.0)
    market_score: float = Field(default=0.25, ge=0.05, le=1.0)
    growth_score: float = Field(default=0.15, ge=0.05, le=1.0)
    risk_score: float = Field(default=0.10, ge=0.05, le=1.0)

    @model_validator(mode="after")
    def _validate_5component_simgr(self) -> "WeightsInput":
        """Enforce 5-component SIMGR: no zero weights, sum approximately 1."""
        weights = {
            "study": self.study_score,
            "interest": self.interest_score,
            "market": self.market_score,
            "growth": self.growth_score,
            "risk": self.risk_score,
        }
        zero_comps = [k for k, v in weights.items() if v < 0.05]
        if zero_comps:
            raise ValueError(
                f"5-Component SIMGR violation (v2.0_full_SIMGR): "
                f"components below minimum (0.05): {zero_comps}. "
                "All 5 weights must be >= 0.05 to maintain full SIMGR model."
            )
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Weights must sum to approximately 1.0 (got {total:.4f}). "
                "Normalize weights before submitting."
            )
        return self


class StrategyInfo(BaseModel):
    """Scoring strategy information."""
    name: str
    description: str
    default: bool = False


class SimulateWeights(BaseModel):
    """SIMGR weights for simulation — all 5 components required, minimum 0.05 each."""
    study_score: float = Field(default=0.3, ge=0.05, le=0.5, description="Study/Skills weight (0.05-0.5)")
    interest_score: float = Field(default=0.25, ge=0.05, le=0.5, description="Interest weight (0.05-0.5)")
    market_score: float = Field(default=0.25, ge=0.05, le=0.5, description="Market weight (0.05-0.5)")
    growth_score: float = Field(default=0.1, ge=0.05, le=0.3, description="Growth weight (0.05-0.3)")
    risk_score: float = Field(default=0.1, ge=0.05, le=0.3, description="Risk weight (0.05-0.3)")

    @model_validator(mode="after")
    def _validate_5component_simgr(self) -> "SimulateWeights":
        """Enforce 5-component SIMGR: no zero weights, sum approximately 1."""
        weights = {
            "study": self.study_score,
            "interest": self.interest_score,
            "market": self.market_score,
            "growth": self.growth_score,
            "risk": self.risk_score,
        }
        zero_comps = [k for k, v in weights.items() if v < 0.05]
        if zero_comps:
            raise ValueError(
                f"5-Component SIMGR violation (v2.0_full_SIMGR): "
                f"components below minimum (0.05): {zero_comps}. "
                "All 5 weights must be >= 0.05 to maintain full SIMGR model."
            )
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Weights must sum to approximately 1.0 (got {total:.4f}). "
                "Normalize weights before submitting."
            )
        return self


class SimulateRequest(BaseModel):
    """Request to simulate ranking with custom weights."""
    weights: SimulateWeights = Field(default_factory=SimulateWeights, description="Custom SIMGR weights")
    career_ids: List[str] = Field(default_factory=list, description="Career IDs to include in simulation")


# ═══════════════════════════════════════════════════════════════════════════
#  Available Strategies — Static data only
# ═══════════════════════════════════════════════════════════════════════════

AVAILABLE_STRATEGIES = [
    StrategyInfo(
        name="weighted",
        description="Standard weighted scoring using configurable weights",
        default=True,
    ),
    StrategyInfo(
        name="personalized",
        description="Personalized scoring adapting to user profile characteristics",
        default=False,
    ),
]


# ═══════════════════════════════════════════════════════════════════════════
#  Endpoints — ALL use controller.dispatch()
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/health")
async def scoring_health():
    """
    Scoring service health check.
    Returns service status based on controller availability.
    """
    controller_available = _main_controller is not None
    
    return health_response(
        service="scoring",
        healthy=controller_available,
        uptime_seconds=time.time() - _start_time,
        dependencies={
            "main_controller": controller_available,
            "dispatch_ready": controller_available,
        }
    )


@router.get("")
async def get_config(
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
    controller = Depends(_require_controller),
):
    """
    Get current scoring configuration via controller dispatch.
    """
    try:
        result = await controller.dispatch(
            service="scoring",
            action="config",
            payload={},
            context={"source": "api", "user_id": getattr(auth, "user_id", "anonymous")}
        )
        
        return success_response(data={
            "config": result.get("config", {
                "default_strategy": "weighted",
                "available_strategies": [s.name for s in AVAILABLE_STRATEGIES],
            })
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get config error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/strategies")
async def list_strategies(
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
):
    """
    List available scoring strategies.
    Static data — no controller dispatch needed.
    """
    return success_response(data={
        "strategies": [s.model_dump() for s in AVAILABLE_STRATEGIES]
    })


@router.get("/weights")
async def get_weights(
    auth: AuthResult = Depends(require_any_role(READ_ROLES)),
    controller = Depends(_require_controller),
):
    """
    Get current scoring weights via controller dispatch.
    """
    try:
        result = await controller.dispatch(
            service="scoring",
            action="weights",
            payload={"operation": "get"},
            context={"source": "api", "user_id": getattr(auth, "user_id", "anonymous")}
        )
        
        return success_response(data={"weights": result.get("weights", {})})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get weights error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/weights")
async def update_weights(
    weights: WeightsInput,
    request: Request,
    auth: AuthResult = Depends(require_permission(Permission.SCORING_WRITE)),
    controller = Depends(_require_controller),
):
    """
    [REMOVED — PRODUCTION HARDENING 2026-02-21]

    Runtime weight update via API is permanently disabled.

    Weights are immutable after training:
      - Version pinned in backend/scoring/weights/manifest.json (locked=true)
      - Files are filesystem read-only (attrib +R)
      - Any weight change requires:
          1. Re-running the training pipeline
          2. Updating manifest.json via offline process
          3. Deploying a new build through CI/CD

    This endpoint returns HTTP 410 Gone in all environments.
    """
    correlation_id = getattr(request.state, "correlation_id", None) or str(uuid.uuid4())
    user_id = getattr(auth, "user_id", "anonymous")
    security_logger.critical(
        f"[WEIGHT_MOD_BLOCKED] "
        f"user_id={user_id} "
        f"correlation_id={correlation_id} "
        f"reason=endpoint_permanently_removed "
        f"timestamp={datetime.now(timezone.utc).isoformat()}"
    )
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Runtime weight updates are permanently disabled. "
            "weights/manifest.json is locked and filesystem read-only. "
            "Weight changes require a new training pipeline run and CI deployment."
        ),
    )


@router.post("/rank")
async def rank_careers(
    request: RankRequest,
    auth: AuthResult = Depends(require_permission(Permission.SCORING_EXECUTE)),
    controller = Depends(_require_controller),
):
    """
    Rank careers for a user profile via controller dispatch.
    
    Flow: Router → Controller.dispatch() → ScoringService → RankingEngine → Response
    """
    try:
        # Build payload for controller
        payload = {
            "user_profile": request.user_profile.model_dump(),
            "careers": [c.model_dump() for c in request.careers],
            "strategy": request.strategy,
            "top_n": request.top_n,
        }
        
        # Dispatch through controller — 8-step pipeline
        result = await controller.dispatch(
            service="scoring",
            action="rank",
            payload=payload,
            context={
                "source": "api",
                "user_id": getattr(auth, "user_id", "anonymous"),
            }
        )
        
        return success_response(data={
            "ranked_careers": result.get("ranked_careers", []),
            "total_evaluated": len(request.careers),
            "returned": len(result.get("ranked_careers", [])),
            "strategy": request.strategy or "weighted",
            "_meta": result.get("_meta", {}),
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Rank careers error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/score")
async def score_careers(
    request: ScoreRequest,
    auth: AuthResult = Depends(require_permission(Permission.SCORING_EXECUTE)),
    controller = Depends(_require_controller),
):
    """
    Score specific careers by name via controller dispatch.
    
    Flow: Router → Controller.dispatch() → ScoringService → Response
    """
    try:
        # Build payload for controller
        payload = {
            "user_profile": request.user_profile.model_dump(),
            "career_names": request.career_names,
            "strategy": request.strategy,
        }
        
        # Dispatch through controller — 8-step pipeline
        result = await controller.dispatch(
            service="scoring",
            action="score",
            payload=payload,
            context={
                "source": "api",
                "user_id": getattr(auth, "user_id", "anonymous"),
            }
        )
        
        return success_response(data={
            "scored_careers": result.get("scored_careers", []),
            "requested": len(request.career_names),
            "scored": len(result.get("scored_careers", [])),
            "not_found": result.get("not_found", []),
            "strategy": request.strategy or "weighted",
            "_meta": result.get("_meta", {}),
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Score careers error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/reset")
async def reset_config(
    auth: AuthResult = Depends(require_permission(Permission.SCORING_WRITE)),
    controller = Depends(_require_controller),
):
    """
    Reset scoring configuration to defaults via controller dispatch.
    """
    try:
        result = await controller.dispatch(
            service="scoring",
            action="reset",
            payload={},
            context={
                "source": "api",
                "user_id": getattr(auth, "user_id", "anonymous"),
            }
        )
        
        return success_response(data={
            "reset": True,
            "message": result.get("message", "Scoring configuration reset to defaults"),
            "_meta": result.get("_meta", {}),
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reset config error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/simulate")
async def simulate_ranking(
    request: SimulateRequest,
    controller = Depends(_require_controller),
):
    """
    Simulate career ranking with custom SIMGR weights.
    
    EXPLORATION ONLY - Results are NOT stored for training.
    This endpoint allows users to explore what-if scenarios
    without affecting the production scoring or training data.
    
    Weight Constraints (enforced by Pydantic):
    - study_score: 0-0.5
    - interest_score: 0-0.5  
    - market_score: 0-0.5
    - growth_score: 0-0.3
    - risk_score: 0-0.3
    
    Returns simulated rankings based on custom weights.
    """
    try:
        # Log simulation request (for monitoring, NOT training)
        logger.info(f"Simulation request: careers={len(request.career_ids)}, weights={request.weights.model_dump()}")
        
        # Build payload for controller
        payload = {
            "operation": "simulate",
            "weights": request.weights.model_dump(),
            "career_ids": request.career_ids,
            # Explicit flag: this is exploration, NOT for training
            "_exploration": True,
        }
        
        # Dispatch through controller
        result = await controller.dispatch(
            service="scoring",
            action="simulate",
            payload=payload,
            context={
                "source": "api_simulation",
                "user_id": "anonymous",  # No auth required for simulation
                "is_exploration": True,
            }
        )
        
        return success_response(data={
            "ranked_careers": result.get("ranked_careers", []),
            "weights_used": request.weights.model_dump(),
            "career_count": len(result.get("ranked_careers", [])),
            # Explicit warning that this is simulation only
            "_warning": "SIMULATION_ONLY: Results are NOT stored and do NOT affect training data.",
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Simulate ranking error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

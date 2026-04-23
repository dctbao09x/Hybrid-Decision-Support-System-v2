# backend/api/routers/pipeline_router.py
"""
Pipeline Router (Consolidated)
==============================

All data pipeline endpoints consolidated under /api/v1/pipeline/*

Endpoints:
  - POST /api/v1/pipeline/run              — Run full data pipeline
  - GET  /api/v1/pipeline/status           — Pipeline status
  - POST /api/v1/pipeline/recommendations  — Get recommendations via pipeline
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("api.routers.pipeline")

router = APIRouter(tags=["Pipeline"])


# ==============================================================================
# Request/Response Models
# ==============================================================================

class ChatMessage(BaseModel):
    """Chat message."""
    role: str
    text: str


class RecommendationsRequest(BaseModel):
    """Recommendations request."""
    processedProfile: Optional[Dict[str, Any]] = Field(None, description="Pre-processed profile")
    userProfile: Optional[Dict[str, Any]] = Field(None, description="Raw user profile")
    assessmentAnswers: Optional[Dict[str, Any]] = Field(None, description="Assessment answers")
    chatHistory: Optional[List[ChatMessage]] = Field(None, description="Chat history")


class PipelineRunRequest(BaseModel):
    """Pipeline run request."""
    run_id: Optional[str] = Field(None, description="Custom run ID")
    resume_from: Optional[str] = Field(None, description="Resume from previous run")


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
# Routes
# ==============================================================================

@router.post(
    "/run",
    summary="Run data pipeline",
    description="Execute the full data pipeline: Crawl → Validate → Score → ML Eval → Explain",
)
async def run_pipeline(
    run_id: Optional[str] = Query(None, description="Custom run ID"),
    resume_from: Optional[str] = Query(None, description="Resume from previous run ID"),
):
    """
    Execute the full data pipeline.
    
    Steps:
    1. Crawl data sources
    2. Validate data
    3. Score and rank
    4. ML Evaluation
    5. Generate explanations
    """
    controller = get_main_controller()
    if not controller:
        raise HTTPException(status_code=503, detail="MainController not available")
    
    try:
        result = await controller.run_data_pipeline(
            run_id=run_id,
            resume_from_run=resume_from,
        )
        return result
    except Exception as e:
        logger.error("Pipeline run failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail=str(e))


@router.post(
    "/recommendations",
    summary="Get recommendations",
    description="Full pipeline: Crawl → Validate → Score → Recommend",
)
async def get_recommendations(
    request: RecommendationsRequest,
    force_refresh: bool = Query(False, description="Force cache refresh"),
):
    """
    Get career recommendations via full pipeline.
    
    Steps:
    1. Process profile (if raw)
    2. Crawl fresh data (if needed)
    3. Validate and score
    4. Return ranked recommendations
    """
    controller = get_main_controller()
    if not controller:
        raise HTTPException(status_code=503, detail="MainController not available")
    
    try:
        result = await controller.recommend(
            processed_profile=request.processedProfile,
            user_profile=request.userProfile,
            assessment_answers=request.assessmentAnswers,
            chat_history=request.chatHistory,
            force_refresh=force_refresh,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Recommendation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail=str(e))

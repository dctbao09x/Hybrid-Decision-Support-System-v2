# backend/api/routers/infer_router.py
"""
Inference Router (Consolidated)
===============================

All inference endpoints consolidated under /api/v1/infer/*

Endpoints:
  - POST /api/v1/infer/predict        — Get career prediction
  - POST /api/v1/infer/feedback       — Submit feedback
  - GET  /api/v1/infer/models         — List model versions
  - GET  /api/v1/infer/metrics        — Inference metrics
  - POST /api/v1/infer/killswitch     — Toggle kill switch
  - GET  /api/v1/infer/router/stats   — A/B router statistics
  - POST /api/v1/infer/analyze        — Analyze user profile
  - POST /api/v1/infer/recommendations — Get recommendations
  - GET  /api/v1/infer/career-library — Get career library
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.explain.models import ExplanationRecord
from backend.explain.formatter import (
    RuleJustificationEngine,
    EvidenceCollector,
    ConfidenceEstimator,
    build_trace_edges,
    format_summary_text,
)
from backend.explain.storage import get_explanation_storage
from backend.feedback.models import TraceRecord
from backend.feedback.storage import get_feedback_storage

logger = logging.getLogger("api.routers.infer")

router = APIRouter(tags=["Inference"])


# ==============================================================================
# Request/Response Models
# ==============================================================================

class PredictRequest(BaseModel):
    """Career prediction request."""
    user_id: str = Field(..., description="Unique user identifier")
    math_score: float = Field(..., ge=0, le=100, description="Math aptitude score")
    physics_score: float = Field(..., ge=0, le=100, description="Physics aptitude score")
    interest_it: float = Field(..., ge=0, le=100, description="IT interest level")
    logic_score: float = Field(..., ge=0, le=100, description="Logical reasoning score")


class PredictResponse(BaseModel):
    """Career prediction response with XAI explanation."""
    prediction_id: str
    user_id: str
    career: str = Field(..., description="Predicted career")
    confidence: float
    reason: List[str] = Field(default_factory=list, description="Explanation reasons")
    explain_text: str = Field(default="", description="Full explanation text from Stage 3")
    xai_meta: Dict[str, Any] = Field(default_factory=dict, description="XAI metadata")
    top_careers: List[Dict[str, Any]] = Field(default_factory=list)
    model_version: str
    latency_ms: float
    timestamp: str
    trace_id: str = Field(default="", description="Unified trace identifier")
    explanation_id: str = Field(default="", description="Persistent explanation record id")


class FeedbackRequest(BaseModel):
    """Feedback submission request."""
    prediction_id: str = Field(..., description="ID from predict response")
    actual_career: str = Field(..., description="Actual career outcome")


class FeedbackResponse(BaseModel):
    """Feedback submission response."""
    prediction_id: str
    matched: bool
    message: str


class KillSwitchRequest(BaseModel):
    """Kill switch request."""
    enabled: bool


class KillSwitchResponse(BaseModel):
    """Kill switch response."""
    kill_switch: bool = Field(..., description="Current kill switch state")
    message: str = Field(..., description="Status message")
    timestamp: str = Field(..., description="Response timestamp")


class ModelInfo(BaseModel):
    """Model version information."""
    version: str = Field(..., description="Model version identifier")
    type: str = Field(default="unknown", description="Model type (e.g., random_forest)")
    path: str = Field(default="", description="Model file path")
    created_at: Optional[str] = Field(default=None, description="Creation timestamp")
    is_active: bool = Field(default=False, description="Whether this is the active model")


class RouterStats(BaseModel):
    """A/B router statistics."""
    active_version: str = Field(default="unknown", description="Active model version")
    canary_version: Optional[str] = Field(default=None, description="Canary model version")
    canary_ratio: float = Field(default=0.0, description="Canary traffic ratio")
    total_requests: int = Field(default=0, description="Total routed requests")
    active_requests: int = Field(default=0, description="Requests to active model")
    canary_requests: int = Field(default=0, description="Requests to canary model")
    kill_switch_enabled: bool = Field(default=False, description="Kill switch state")


class MetricsResponse(BaseModel):
    """Metrics response."""
    latency: Dict[str, float]
    requests: Dict[str, int]
    error_rate: float
    qps: float
    model_counts: Dict[str, int]
    feedback: Dict[str, Any]
    timestamp: str


# --- Analyze Profile Models ---

class PersonalInfo(BaseModel):
    """User personal information."""
    fullName: str = Field(default="", description="User's full name")
    age: str = Field(default="", description="User's age")
    education: str = Field(default="", description="Education level")


class ChatMessage(BaseModel):
    """Chat message."""
    role: str = Field(..., description="Message role (user/assistant)")
    text: str = Field(..., description="Message text")


class AnalyzeRequest(BaseModel):
    """Profile analysis request."""
    personalInfo: Optional[PersonalInfo] = Field(default=None, description="Personal info")
    interests: List[str] = Field(default_factory=list, description="User interests")
    skills: str = Field(default="", description="User skills (comma-separated)")
    careerGoal: str = Field(default="", description="Career goal")
    chatHistory: Optional[List[ChatMessage]] = Field(default=None, description="Chat history")


class AnalyzeResponse(BaseModel):
    """Profile analysis response."""
    age: int = Field(default=0, description="Parsed age")
    education_level: str = Field(default="", description="Education level")
    interest_tags: List[str] = Field(default_factory=list, description="Interest tags")
    skill_tags: List[str] = Field(default_factory=list, description="Skill tags")
    goal_cleaned: str = Field(default="", description="Cleaned career goal")
    intent: str = Field(default="", description="Detected intent")
    chat_summary: str = Field(default="", description="Chat summary")
    confidence_score: float = Field(default=0.0, description="Confidence score")


# --- Recommendations Models ---

class RecommendationsRequest(BaseModel):
    """Career recommendations request."""
    processedProfile: Optional[Dict[str, Any]] = Field(default=None, description="Pre-processed profile")
    userProfile: Optional[Dict[str, Any]] = Field(default=None, description="Raw user profile")
    assessmentAnswers: Optional[Dict[str, Any]] = Field(default=None, description="Assessment answers")
    chatHistory: Optional[List[Dict[str, str]]] = Field(default=None, description="Chat history")


class CareerRecommendation(BaseModel):
    """Single career recommendation."""
    id: str = Field(..., description="Career ID")
    name: str = Field(..., description="Career name")
    rank: int = Field(..., description="Ranking position (1-indexed, lower is better)")
    domain: str = Field(default="General", description="Career domain")
    description: str = Field(default="", description="Career description")
    icon: str = Field(default="💼", description="Career icon emoji")
    matchScore: float = Field(default=0.0, description="Match score 0-1")
    growthRate: float = Field(default=0.0, description="Growth rate 0-1")
    requiredSkills: List[str] = Field(default_factory=list, description="Required skills")
    education: str = Field(default="", description="Required education")
    salary_range: str = Field(default="", description="Salary range")


class RecommendationsResponse(BaseModel):
    """Career recommendations response."""
    recommendations: List[CareerRecommendation] = Field(default_factory=list)
    total_count: int = Field(default=0, description="Total recommendations")
    processing_time_ms: float = Field(default=0.0)
    timestamp: str = Field(default="")


class CareerLibraryItem(BaseModel):
    """Career library entry."""
    id: str = Field(..., description="Career ID")
    name: str = Field(..., description="Career name")
    domain: str = Field(default="General", description="Career domain")
    description: str = Field(default="", description="Career description")
    icon: str = Field(default="💼", description="Career icon emoji")
    aiRelevance: float = Field(default=0.0, description="AI relevance score 0-1")
    growthRate: float = Field(default=0.0, description="Growth rate 0-1")
    competition: float = Field(default=0.0, description="Competition level 0-1")
    requiredSkills: List[str] = Field(default_factory=list, description="Required skills")
    education: str = Field(default="")
    salary_range: str = Field(default="")


class CareerLibraryResponse(BaseModel):
    """Career library response."""
    careers: List[CareerLibraryItem] = Field(default_factory=list)
    total_count: int = Field(default=0)
    timestamp: str = Field(default="")


# ==============================================================================
# Store inference API reference (injected at startup)
# ==============================================================================

_inference_api = None


def set_inference_api(api):
    """Set the InferenceAPI reference."""
    global _inference_api
    _inference_api = api


def get_inference_api():
    """Get InferenceAPI instance."""
    return _inference_api


# ==============================================================================
# Routes
# ==============================================================================

@router.post(
    "/predict",
    response_model=PredictResponse,
    summary="Get career prediction",
    description="Get career prediction with XAI explanation",
)
async def predict(request: PredictRequest):
    """Get career prediction for a user."""
    api = get_inference_api()
    if not api:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inference API not initialized",
        )
    
    # Delegate to InferenceAPI internal handler
    # The actual logic is in api_server.py InferenceAPI._register_routes
    start_time = time.time()
    
    if not api._model_loader:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model not loaded",
        )
    
    try:
        from backend.inference.ab_router import RouteTarget
        
        # Route to appropriate model
        routing = api._router.route(request.user_id)
        use_canary = routing.target == RouteTarget.CANARY
        
        # Get model
        model = api._model_loader.get_model(use_canary=use_canary)
        
        # Prepare features
        features = np.array([[
            request.math_score,
            request.physics_score,
            request.interest_it,
            request.logic_score,
        ]])
        
        # Predict
        prediction = model.predict(features)[0]
        probabilities = model.predict_proba(features)[0]
        
        # Decode prediction
        predicted_career = api._model_loader.decode_prediction(prediction)
        confidence = float(probabilities[prediction])
        
        # Get top careers
        top_indices = np.argsort(probabilities)[::-1][:3]
        top_careers = [
            {
                "career": api._model_loader.decode_prediction(idx),
                "probability": float(probabilities[idx]),
            }
            for idx in top_indices
        ]
        
        latency_ms = (time.time() - start_time) * 1000
        
        features_payload = {
            "math_score": request.math_score,
            "physics_score": request.physics_score,
            "interest_it": request.interest_it,
            "logic_score": request.logic_score,
        }

        # Log prediction
        prediction_id = api._feedback.log_prediction(
            user_id=request.user_id,
            features=features_payload,
            predicted_career=predicted_career,
            predicted_proba=confidence,
            model_version=model.version,
            latency_ms=latency_ms,
            routing_target=routing.target.value,
        )

        trace_id = prediction_id
        
        # Record metrics
        api._metrics.record_success(
            latency_ms=latency_ms,
            model_version=model.version,
        )
        
        # Generate deterministic explanation and persist audit graph
        rule_engine = RuleJustificationEngine()
        fired_rules = rule_engine.evaluate(
            features=features_payload,
            predicted_career=predicted_career,
            predicted_confidence=confidence,
        )

        feedback_storage = get_feedback_storage()
        await feedback_storage.initialize()
        feedback_stats = await feedback_storage.get_feedback_stats()
        feedback_agreement = float(feedback_stats.get("feedback_rate", 0.5))

        probabilities_list = [float(prob) for prob in probabilities.tolist()]
        estimator = ConfidenceEstimator()
        explanation_confidence = estimator.estimate(
            probabilities=probabilities_list,
            fired_rules=len(fired_rules),
            total_rules=4,
            features=features_payload,
            feedback_agreement=feedback_agreement,
        )

        evidence = EvidenceCollector().collect(features_payload, top_careers=top_careers)
        weights = {rule.rule_id: float(rule.weight) for rule in fired_rules}
        explain_text = format_summary_text(
            career=predicted_career,
            confidence=explanation_confidence,
            fired_rules=fired_rules,
        )
        reasons = [
            f"{rule.rule_id} ({rule.condition})"
            for rule in fired_rules
        ]

        kb_version = os.getenv("MLOPS_KB_VERSION", "kb-v1")
        model_id = str(getattr(model, "version", "unknown"))
        explanation_store = get_explanation_storage()
        await explanation_store.initialize()

        explanation_record = ExplanationRecord(
            trace_id=trace_id,
            model_id=model_id,
            kb_version=kb_version,
            rule_path=fired_rules,
            weights=weights,
            evidence=evidence,
            confidence=explanation_confidence,
            feature_snapshot=features_payload,
            prediction={
                "career": predicted_career,
                "confidence": confidence,
                "top_careers": top_careers,
            },
        )
        explanation_record = await explanation_store.append_record(explanation_record)

        trace_edges = build_trace_edges(
            trace_id=trace_id,
            user_id=request.user_id,
            features=features_payload,
            fired_rules=fired_rules,
            score=confidence,
            decision=predicted_career,
        )
        await explanation_store.append_graph_edges(trace_id=trace_id, edges=trace_edges)

        await feedback_storage.store_trace(
            TraceRecord(
                trace_id=trace_id,
                user_id=request.user_id,
                input_profile=features_payload,
                kb_snapshot_version=kb_version,
                model_version=model_id,
                rule_path=[rule.rule_id for rule in fired_rules],
                score_vector=weights,
                timestamp=datetime.now(timezone.utc).isoformat(),
                predicted_career=predicted_career,
                predicted_confidence=confidence,
                top_careers=top_careers,
                reasons=reasons,
                xai_meta={
                    "explanation_id": explanation_record.explanation_id,
                    "deterministic": True,
                },
                latency_ms=latency_ms,
            )
        )

        xai_meta = {
            "explanation_id": explanation_record.explanation_id,
            "deterministic": True,
            "rule_count": len(fired_rules),
        }
        
        return PredictResponse(
            prediction_id=prediction_id,
            user_id=request.user_id,
            career=predicted_career,
            confidence=confidence,
            reason=reasons,
            explain_text=explain_text,
            xai_meta=xai_meta,
            top_careers=top_careers,
            model_version=model.version,
            latency_ms=latency_ms,
            timestamp=datetime.now(timezone.utc).isoformat(),
            trace_id=trace_id,
            explanation_id=explanation_record.explanation_id,
        )
        
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        if api._metrics:
            api._metrics.record_error(
                latency_ms=latency_ms,
                model_version="unknown",
                error_type=type(e).__name__,
            )
        logger.error("Prediction error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    summary="Submit feedback",
    description="Submit outcome feedback for a prediction",
)
async def feedback(request: FeedbackRequest):
    """Submit feedback for a prediction."""
    api = get_inference_api()
    if not api or not api._feedback:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Feedback collector not initialized",
        )
    
    matched = api._feedback.log_feedback(
        prediction_id=request.prediction_id,
        actual_career=request.actual_career,
    )
    
    return FeedbackResponse(
        prediction_id=request.prediction_id,
        matched=matched,
        message="Feedback recorded" if matched else "Prediction not found",
    )


@router.get(
    "/models",
    response_model=List[ModelInfo],
    summary="List models",
    description="List all available model versions",
)
async def list_models():
    """List available model versions."""
    api = get_inference_api()
    if not api or not api._model_loader:
        return []
    versions = api._model_loader.list_versions()
    return [
        ModelInfo(
            version=v.get("version", "unknown"),
            type=v.get("type", "unknown"),
            path=v.get("path", ""),
            created_at=v.get("created_at"),
            is_active=v.get("is_active", False),
        )
        for v in versions
    ]


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Inference metrics",
    description="Get inference metrics (latency, requests, error rate)",
)
async def get_metrics():
    """Get inference metrics."""
    api = get_inference_api()
    if not api or not api._metrics:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Metrics not initialized",
        )
    
    m = api._metrics.get_metrics()
    return MetricsResponse(
        latency=m.to_dict()["latency"],
        requests=m.to_dict()["requests"],
        error_rate=m.error_rate,
        qps=m.qps,
        model_counts=m.model_counts,
        feedback=m.to_dict()["feedback"],
        timestamp=m.timestamp,
    )


@router.post(
    "/killswitch",
    response_model=KillSwitchResponse,
    summary="Toggle kill switch",
    description="Enable or disable the kill switch to stop routing to canary model",
)
async def killswitch(request: KillSwitchRequest):
    """Enable or disable kill switch."""
    api = get_inference_api()
    if not api or not api._router:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Router not initialized",
        )
    
    api._router.set_kill_switch(request.enabled)
    return KillSwitchResponse(
        kill_switch=request.enabled,
        message="Kill switch " + ("enabled" if request.enabled else "disabled"),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/router/stats",
    response_model=RouterStats,
    summary="Router statistics",
    description="Get A/B router statistics including traffic split",
)
async def router_stats():
    """Get A/B router statistics."""
    api = get_inference_api()
    if not api or not api._router:
        return RouterStats()
    stats = api._router.get_stats()
    return RouterStats(
        active_version=stats.get("active_version", "unknown"),
        canary_version=stats.get("canary_version"),
        canary_ratio=stats.get("canary_ratio", 0.0),
        total_requests=stats.get("total_requests", 0),
        active_requests=stats.get("active_requests", 0),
        canary_requests=stats.get("canary_requests", 0),
        kill_switch_enabled=stats.get("kill_switch_enabled", False),
    )


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="Analyze profile",
    description="Analyze user profile and extract features",
)
async def analyze_profile(request: AnalyzeRequest):
    """Analyze user profile and return processed data."""
    try:
        from backend.processor import process_user_profile
        
        profile_dict = {
            "personalInfo": {
                "fullName": request.personalInfo.fullName if request.personalInfo else "",
                "age": request.personalInfo.age if request.personalInfo else "",
                "education": request.personalInfo.education if request.personalInfo else "",
            },
            "interests": request.interests,
            "skills": request.skills,
            "careerGoal": request.careerGoal,
            "chatHistory": [
                {"role": msg.role, "text": msg.text}
                for msg in (request.chatHistory or [])
            ],
        }
        
        result = process_user_profile(profile_dict)
        
        return AnalyzeResponse(
            age=result.get("age", 0),
            education_level=result.get("education_level", ""),
            interest_tags=result.get("interest_tags", []),
            skill_tags=result.get("skill_tags", []),
            goal_cleaned=result.get("goal_cleaned", ""),
            intent=result.get("intent", ""),
            chat_summary=result.get("chat_summary", ""),
            confidence_score=result.get("confidence_score", 0.0),
        )
    except ImportError:
        # Fallback mock response
        return AnalyzeResponse(
            age=25,
            education_level="Bachelor's",
            interest_tags=request.interests[:5] if request.interests else ["technology", "data"],
            skill_tags=[s.strip() for s in request.skills.split(",")][:5] if request.skills else ["python", "sql"],
            goal_cleaned=request.careerGoal or "career growth",
            intent="explore_careers",
            chat_summary="User exploring career options",
            confidence_score=0.75,
        )
    except Exception as e:
        logger.error(f"Profile analysis error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing profile: {str(e)}",
        )


@router.post(
    "/recommendations",
    response_model=RecommendationsResponse,
    summary="Get recommendations",
    description="Get personalized career recommendations",
)
async def get_recommendations(request: RecommendationsRequest):
    """Get career recommendations for user profile."""
    start_time = time.time()
    
    # Mock recommendations matching frontend expectations
    mock_careers = [
        CareerRecommendation(
            id="sw-dev",
            name="Software Developer",
            rank=1,
            domain="IT",
            icon="💻",
            matchScore=0.925,
            description="Design and develop software applications",
            requiredSkills=["Python", "JavaScript", "SQL", "Git", "React"],
            education="Bachelor's in Computer Science",
            salary_range="$70,000 - $120,000",
            growthRate=0.92,
        ),
        CareerRecommendation(
            id="data-sci",
            name="Data Scientist",
            rank=2,
            domain="IT",
            icon="📊",
            matchScore=0.88,
            description="Analyze complex data to help organizations make decisions",
            requiredSkills=["Python", "Machine Learning", "Statistics", "SQL", "TensorFlow"],
            education="Master's in Data Science or related",
            salary_range="$90,000 - $150,000",
            growthRate=0.88,
        ),
        CareerRecommendation(
            id="ml-eng",
            name="Machine Learning Engineer",
            rank=3,
            domain="IT",
            icon="🤖",
            matchScore=0.85,
            description="Build and deploy ML models at scale",
            requiredSkills=["Python", "TensorFlow", "PyTorch", "MLOps", "Docker"],
            education="Master's in CS or related",
            salary_range="$100,000 - $180,000",
            growthRate=0.95,
        ),
        CareerRecommendation(
            id="product-mgr",
            name="Product Manager",
            rank=4,
            domain="Business",
            icon="📈",
            matchScore=0.825,
            description="Lead product development and strategy",
            requiredSkills=["Communication", "Analytics", "Leadership", "Agile", "Strategy"],
            education="Bachelor's in Business or Engineering",
            salary_range="$80,000 - $140,000",
            growthRate=0.75,
        ),
        CareerRecommendation(
            id="ux-designer",
            name="UX Designer",
            rank=5,
            domain="Design",
            icon="🎨",
            matchScore=0.78,
            description="Design user experiences for digital products",
            requiredSkills=["UI/UX", "Figma", "User Research", "Prototyping", "Design Systems"],
            education="Bachelor's in Design or HCI",
            salary_range="$65,000 - $110,000",
            growthRate=0.70,
        ),
        CareerRecommendation(
            id="fin-analyst",
            name="Financial Analyst",
            rank=6,
            domain="Finance",
            icon="💰",
            matchScore=0.75,
            description="Analyze financial data and create forecasts",
            requiredSkills=["Excel", "Financial Modeling", "SQL", "Analysis", "Bloomberg"],
            education="Bachelor's in Finance or Accounting",
            salary_range="$60,000 - $100,000",
            growthRate=0.55,
        ),
    ]
    
    processing_time = (time.time() - start_time) * 1000
    return RecommendationsResponse(
        recommendations=mock_careers,
        total_count=len(mock_careers),
        processing_time_ms=processing_time,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/career-library",
    response_model=CareerLibraryResponse,
    summary="Get career library",
    description="Get the full career library with all available careers",
)
async def get_career_library():
    """Get full career library."""
    careers = [
        CareerLibraryItem(
            id="sw-dev", name="Software Developer", domain="IT",
            description="Design and develop software applications",
            icon="💻", aiRelevance=0.85, growthRate=0.92, competition=0.75,
            requiredSkills=["Python", "JavaScript", "SQL", "Git", "React"],
            education="Bachelor's", salary_range="$70K-$120K"
        ),
        CareerLibraryItem(
            id="data-sci", name="Data Scientist", domain="IT",
            description="Analyze data for business insights",
            icon="📊", aiRelevance=0.95, growthRate=0.88, competition=0.70,
            requiredSkills=["Python", "Machine Learning", "Statistics", "SQL", "TensorFlow"],
            education="Master's", salary_range="$90K-$150K"
        ),
        CareerLibraryItem(
            id="ml-engineer", name="Machine Learning Engineer", domain="IT",
            description="Build and deploy ML models at scale",
            icon="🤖", aiRelevance=0.98, growthRate=0.95, competition=0.65,
            requiredSkills=["Python", "TensorFlow", "PyTorch", "MLOps", "Docker"],
            education="Master's", salary_range="$100K-$180K"
        ),
        CareerLibraryItem(
            id="product-mgr", name="Product Manager", domain="Business",
            description="Lead product strategy and development",
            icon="📈", aiRelevance=0.60, growthRate=0.75, competition=0.80,
            requiredSkills=["Communication", "Analytics", "Leadership", "Agile", "Strategy"],
            education="Bachelor's", salary_range="$80K-$140K"
        ),
        CareerLibraryItem(
            id="ux-designer", name="UX Designer", domain="Design",
            description="Design user experiences for digital products",
            icon="🎨", aiRelevance=0.55, growthRate=0.70, competition=0.65,
            requiredSkills=["UI/UX", "Figma", "User Research", "Prototyping", "Design Systems"],
            education="Bachelor's", salary_range="$65K-$110K"
        ),
        CareerLibraryItem(
            id="fin-analyst", name="Financial Analyst", domain="Finance",
            description="Analyze financial data and create forecasts",
            icon="💰", aiRelevance=0.50, growthRate=0.55, competition=0.70,
            requiredSkills=["Excel", "Financial Modeling", "SQL", "Analysis", "Bloomberg"],
            education="Bachelor's", salary_range="$60K-$100K"
        ),
        CareerLibraryItem(
            id="marketing-mgr", name="Marketing Manager", domain="Marketing",
            description="Lead marketing campaigns and strategy",
            icon="📣", aiRelevance=0.65, growthRate=0.60, competition=0.72,
            requiredSkills=["Digital Marketing", "Analytics", "Communication", "SEO", "Social Media"],
            education="Bachelor's", salary_range="$60K-$120K"
        ),
        CareerLibraryItem(
            id="teacher", name="Teacher", domain="Education",
            description="Educate and mentor students",
            icon="🎓", aiRelevance=0.35, growthRate=0.40, competition=0.50,
            requiredSkills=["Communication", "Patience", "Subject Expertise", "Curriculum Design"],
            education="Bachelor's + Certification", salary_range="$40K-$70K"
        ),
        CareerLibraryItem(
            id="devops-eng", name="DevOps Engineer", domain="IT",
            description="Automate and optimize deployment pipelines",
            icon="⚙️", aiRelevance=0.80, growthRate=0.85, competition=0.60,
            requiredSkills=["Docker", "Kubernetes", "CI/CD", "AWS", "Linux"],
            education="Bachelor's", salary_range="$85K-$140K"
        ),
        CareerLibraryItem(
            id="cyber-sec", name="Cybersecurity Analyst", domain="IT",
            description="Protect systems and data from threats",
            icon="🛡️", aiRelevance=0.75, growthRate=0.90, competition=0.55,
            requiredSkills=["Network Security", "Penetration Testing", "SIEM", "Risk Analysis"],
            education="Bachelor's", salary_range="$75K-$130K"
        ),
    ]
    
    return CareerLibraryResponse(
        careers=careers,
        total_count=len(careers),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

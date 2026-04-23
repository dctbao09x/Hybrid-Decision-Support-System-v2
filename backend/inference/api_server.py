# backend/inference/api_server.py
"""
Inference API Server
====================

FastAPI-based REST API for online career prediction.

Endpoints:
  - POST /predict      — Get career prediction
  - POST /feedback     — Submit outcome feedback
  - GET  /health       — Health check
  - GET  /metrics      — Inference metrics
  - GET  /models       — List model versions
  - POST /killswitch   — Enable/disable kill switch
  
Stage 5 Explain API:
  - POST /api/v1/explain       — Run explanation pipeline
  - GET  /api/v1/explain/{id}  — Get stored explanation
  - GET  /api/v1/health        — Explain API health
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import numpy as np
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.inference.model_loader import ModelLoader
from backend.inference.ab_router import ABRouter, RouteTarget
from backend.inference.feedback_collector import FeedbackCollector
from backend.inference.metric_tracker import MetricTracker

# Type-only imports (for type hints)
if TYPE_CHECKING:
    from backend.scoring.explain.xai import XAIService
    from backend.explain.stage3 import Stage3Engine
    from backend.api.controllers.explain_controller import ExplainController
    from backend.storage.explain_history import ExplainHistoryStorage

# XAI Integration (runtime)
try:
    from backend.scoring.explain.xai import XAIService as _XAIService, get_xai_service
    XAI_AVAILABLE = True
except ImportError:
    XAI_AVAILABLE = False
    _XAIService = None
    get_xai_service = None

# Stage 3 Integration (runtime)
try:
    from backend.explain.stage3 import run_stage3, Stage3Engine as _Stage3Engine
    STAGE3_AVAILABLE = True
except ImportError:
    STAGE3_AVAILABLE = False
    run_stage3 = None
    _Stage3Engine = None

# Stage 5 Explain API Integration (runtime)
try:
    from backend.api.routers.explain_router import router as explain_router
    from backend.api.routers.explain_router import router_v2 as explain_router_v2
    from backend.api.routers.explain_router import set_controller
    from backend.api.controllers.explain_controller import ExplainController as _ExplainController
    from backend.storage.explain_history import ExplainHistoryStorage as _ExplainHistoryStorage
    STAGE5_AVAILABLE = True
except ImportError as e:
    STAGE5_AVAILABLE = False
    explain_router = None
    explain_router_v2 = None
    set_controller = None
    _ExplainController = None
    _ExplainHistoryStorage = None

logger = logging.getLogger("ml_inference.api")


# ═══════════════════════════════════════════════════════════════════════════
#  Request/Response Models
# ═══════════════════════════════════════════════════════════════════════════

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
    
    # Backward compatibility alias
    @property
    def predicted_career(self) -> str:
        return self.career


class FeedbackRequest(BaseModel):
    """Feedback submission request."""
    prediction_id: str = Field(..., description="ID from predict response")
    actual_career: str = Field(..., description="Actual career outcome")


class FeedbackResponse(BaseModel):
    """Feedback submission response."""
    prediction_id: str
    matched: bool
    message: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    active_model: str
    canary_model: Optional[str]
    uptime_seconds: float
    timestamp: str


class MetricsResponse(BaseModel):
    """Metrics response."""
    latency: Dict[str, float]
    requests: Dict[str, int]
    error_rate: float
    qps: float
    model_counts: Dict[str, int]
    feedback: Dict[str, Any]
    timestamp: str


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


class WarmupResponse(BaseModel):
    """LLM warmup response."""
    status: str = Field(..., description="Warmup status")
    llm_ready: bool = Field(default=False, description="Whether LLM is ready")
    model: str = Field(default="", description="LLM model name")
    warmup_time_ms: float = Field(default=0.0, description="Warmup duration")
    message: str = Field(default="", description="Status message")


# --- Recommendation Models ---

class UserProfile(BaseModel):
    """User profile for recommendations."""
    name: str = Field(default="", description="User name")
    age: Optional[int] = Field(default=None, description="User age")
    location: str = Field(default="", description="User location")
    skills: List[str] = Field(default_factory=list, description="User skills")
    interests: List[str] = Field(default_factory=list, description="User interests")
    education: str = Field(default="", description="Education level")
    experience: str = Field(default="", description="Work experience")


class ProcessedProfile(BaseModel):
    """Processed user profile."""
    skills: List[str] = Field(default_factory=list)
    interests: List[str] = Field(default_factory=list)
    education_level: str = Field(default="")
    experience_years: int = Field(default=0)
    domain_preferences: List[str] = Field(default_factory=list)
    aptitude_scores: Dict[str, float] = Field(default_factory=dict)


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


# ═══════════════════════════════════════════════════════════════════════════
#  Inference API
# ═══════════════════════════════════════════════════════════════════════════

class InferenceAPI:
    """
    Inference API with model loading, A/B routing, and feedback collection.
    
    Usage::
    
        api = InferenceAPI()
        api.setup()
        
        # Get FastAPI app
        app = api.get_app()
        
        # Run with uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8000)
    """
    
    def __init__(self):
        self.app = FastAPI(
            title="Career Prediction API",
            description="Online inference for career guidance ML model with Stage 5 Explain API",
            version="1.0.0",
        )
        
        # CORS middleware - allow frontend access
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # In production, specify exact origins
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Components
        self._model_loader: Optional[ModelLoader] = None
        self._router: Optional[ABRouter] = None
        self._feedback: Optional[FeedbackCollector] = None
        self._metrics: Optional[MetricTracker] = None
        self._xai_service: Optional["XAIService"] = None
        self._stage3_engine: Optional["Stage3Engine"] = None
        
        # Stage 5 components
        self._explain_controller: Optional["ExplainController"] = None
        self._history_storage: Optional["ExplainHistoryStorage"] = None
        self._main_control: Optional[Any] = None
        
        # State
        self._start_time = time.time()
        self._classes: List[str] = []
        self._feature_names: List[str] = [
            "math_score", "physics_score", "interest_it", "logic_score"
        ]
        
        # Register routes
        self._register_routes()
        
        # Register Stage 5 explain routes
        if STAGE5_AVAILABLE and explain_router:
            self.app.include_router(explain_router)
            self.app.include_router(explain_router_v2)
            logger.info("Stage 5 Explain API routes registered")
    
    def setup(
        self,
        model_loader: Optional[ModelLoader] = None,
        router: Optional[ABRouter] = None,
        feedback: Optional[FeedbackCollector] = None,
        metrics: Optional[MetricTracker] = None,
        xai_service: Optional["XAIService"] = None,
        xai_config: Optional[Dict[str, Any]] = None,
        stage3_engine: Optional["Stage3Engine"] = None,
        explain_config: Optional[Dict[str, Any]] = None,
        main_control: Optional[Any] = None,
    ) -> None:
        """Initialize components."""
        self._model_loader = model_loader or ModelLoader()
        self._router = router or ABRouter()
        self._feedback = feedback or FeedbackCollector()
        
        # Store main control reference for Stage 5
        self._main_control = main_control
        
        # Initialize XAI Service (Stage 2)
        if XAI_AVAILABLE:
            self._xai_service = xai_service or get_xai_service()
            if xai_config:
                self._xai_service.load_config(xai_config)
        
        # Initialize Stage 3 Engine (MANDATORY)
        if STAGE3_AVAILABLE and _Stage3Engine:
            self._stage3_engine = stage3_engine or _Stage3Engine()
            if explain_config:
                self._stage3_engine.load_config(explain_config)
        
        self._metrics = metrics or MetricTracker()
        
        # Load active model
        model_version = "unknown"
        try:
            model = self._model_loader.load_active()
            self._classes = self._model_loader.get_classes()
            self._router.configure(active_version=model.version)
            model_version = model.version
            
            # Initialize XAI with model
            if self._xai_service:
                self._xai_service.load_model(
                    model=model.model,
                    feature_names=self._feature_names,
                    classes=self._classes,
                    model_version=model.version,
                )
            
            logger.info("Inference API initialized with model %s", model.version)
        except FileNotFoundError:
            logger.warning("No active model found - API will return errors until model is deployed")
        
        # Initialize Stage 5 Explain API
        self._setup_stage5(main_control=main_control, model_version=model_version)
    
    def _setup_stage5(
        self,
        main_control: Optional[Any] = None,
        model_version: str = "unknown",
    ) -> None:
        """Initialize Stage 5 Explain API components."""
        if not STAGE5_AVAILABLE:
            logger.warning("Stage 5 not available - explain routes disabled")
            return
        
        try:
            # Initialize history storage
            self._history_storage = _ExplainHistoryStorage()
            
            # Initialize explain controller
            self._explain_controller = _ExplainController()
            self._explain_controller.load_config_file()
            
            # Connect main control
            if main_control:
                self._explain_controller.set_main_control(main_control)
                logger.info("Stage 5: main_control connected")
            else:
                logger.warning("Stage 5: main_control not provided - explain API will fail")
            
            # Connect history storage
            self._explain_controller.set_history_storage(self._history_storage)
            
            # Set version info
            self._explain_controller.set_versions(
                model_version=model_version,
                xai_version="1.0.0",
                stage3_version="1.0.0",
                stage4_version="1.0.0",
            )
            
            # Register controller with router
            set_controller(self._explain_controller)
            
            logger.info("Stage 5 Explain API initialized successfully")
            
        except Exception as e:
            logger.error(f"Stage 5 initialization failed: {e}")
            self._explain_controller = None
            self._history_storage = None
    
    def get_app(self) -> FastAPI:
        """Get the FastAPI application."""
        return self.app
    
    def _register_routes(self) -> None:
        """Register API routes."""
        
        @self.app.post("/predict", response_model=PredictResponse)
        async def predict(request: PredictRequest) -> PredictResponse:
            """Get career prediction for a user."""
            start_time = time.time()
            
            if not self._model_loader:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Model not loaded",
                )
            
            try:
                # Route to appropriate model
                routing = self._router.route(request.user_id)
                use_canary = routing.target == RouteTarget.CANARY
                
                # Get model
                model = self._model_loader.get_model(use_canary=use_canary)
                
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
                predicted_career = self._model_loader.decode_prediction(prediction)
                confidence = float(probabilities[prediction])
                
                # Get top careers
                top_indices = np.argsort(probabilities)[::-1][:3]
                top_careers = [
                    {
                        "career": self._model_loader.decode_prediction(idx),
                        "probability": float(probabilities[idx]),
                    }
                    for idx in top_indices
                ]
                
                latency_ms = (time.time() - start_time) * 1000
                
                # Log prediction
                prediction_id = self._feedback.log_prediction(
                    user_id=request.user_id,
                    features={
                        "math_score": request.math_score,
                        "physics_score": request.physics_score,
                        "interest_it": request.interest_it,
                        "logic_score": request.logic_score,
                    },
                    predicted_career=predicted_career,
                    predicted_proba=confidence,
                    model_version=model.version,
                    latency_ms=latency_ms,
                    routing_target=routing.target.value,
                )
                
                # Record metrics
                self._metrics.record_success(
                    latency_ms=latency_ms,
                    model_version=model.version,
                )
                
                # Generate XAI explanation
                reasons = []
                xai_meta = {}
                
                if self._xai_service and self._xai_service.is_ready():
                    try:
                        # Get class index for SHAP
                        pred_idx = None
                        if hasattr(model.model, "classes_"):
                            try:
                                pred_idx = list(model.model.classes_).index(prediction)
                            except (ValueError, TypeError):
                                pred_idx = int(prediction) if isinstance(prediction, (int, np.integer)) else None
                        
                        # Generate explanation
                        xai_result = self._xai_service.explain(
                            sample=features[0],
                            predicted_career=predicted_career,
                            confidence=confidence,
                            prediction_idx=pred_idx,
                            user_id=request.user_id,
                        )
                        
                        reasons = xai_result.reasons
                        xai_meta = xai_result.xai_meta
                        
                    except Exception as xai_err:
                        logger.warning(f"XAI explanation failed: {xai_err}")
                        reasons = []
                        xai_meta = {"error": str(xai_err)}
                
                # Run Stage 3: Rule+Template Engine (MANDATORY)
                explain_text = ""
                if self._stage3_engine and self._stage3_engine.is_enabled():
                    try:
                        # Build Stage 3 input from XAI output
                        stage2_output = {
                            "trace_id": prediction_id,
                            "career": predicted_career,
                            "reason_codes": self._extract_reason_codes(xai_meta),
                            "sources": self._extract_sources(xai_meta),
                            "confidence": confidence,
                        }
                        
                        # Run Stage 3
                        stage3_result = self._stage3_engine.run(stage2_output)
                        
                        # Use Stage 3 reasons if available (overrides XAI raw reasons)
                        if stage3_result.reasons:
                            reasons = stage3_result.reasons
                        explain_text = stage3_result.explain_text
                        
                        # Add Stage 3 metadata
                        xai_meta["stage3"] = {
                            "used_codes": stage3_result.used_codes,
                            "skipped_codes": stage3_result.skipped_codes,
                        }
                        
                    except Exception as stage3_err:
                        logger.error(f"Stage 3 processing failed: {stage3_err}")
                        xai_meta["stage3_error"] = str(stage3_err)
                
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
                )
                
            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                self._metrics.record_error(
                    latency_ms=latency_ms,
                    model_version="unknown",
                    error_type=type(e).__name__,
                )
                logger.error("Prediction error: %s", e)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=str(e),
                )
        
        @self.app.post("/feedback", response_model=FeedbackResponse)
        async def feedback(request: FeedbackRequest) -> FeedbackResponse:
            """Submit feedback for a prediction."""
            if not self._feedback:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Feedback collector not initialized",
                )
            
            matched = self._feedback.log_feedback(
                prediction_id=request.prediction_id,
                actual_career=request.actual_career,
            )
            
            # Record for metrics
            if matched:
                # We don't know if it's correct here, but feedback was logged
                pass
            
            return FeedbackResponse(
                prediction_id=request.prediction_id,
                matched=matched,
                message="Feedback recorded" if matched else "Prediction not found",
            )
        
        @self.app.get("/health", response_model=HealthResponse)
        async def health() -> HealthResponse:
            """Health check endpoint."""
            active_model = "none"
            canary_model = None
            
            if self._model_loader:
                try:
                    active = self._model_loader.get_model()
                    active_model = active.version
                except Exception:
                    pass
                
                if self._model_loader._canary_model:
                    canary_model = self._model_loader._canary_model.version
            
            return HealthResponse(
                status="healthy" if active_model != "none" else "degraded",
                active_model=active_model,
                canary_model=canary_model,
                uptime_seconds=time.time() - self._start_time,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        
        @self.app.get("/metrics", response_model=MetricsResponse)
        async def metrics() -> MetricsResponse:
            """Get inference metrics."""
            if not self._metrics:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Metrics not initialized",
                )
            
            m = self._metrics.get_metrics()
            return MetricsResponse(
                latency=m.to_dict()["latency"],
                requests=m.to_dict()["requests"],
                error_rate=m.error_rate,
                qps=m.qps,
                model_counts=m.model_counts,
                feedback=m.to_dict()["feedback"],
                timestamp=m.timestamp,
            )
        
        @self.app.get(
            "/models",
            response_model=List[ModelInfo],
            summary="List models",
            description="List all available model versions with their metadata",
            tags=["models"],
        )
        async def list_models() -> List[ModelInfo]:
            """List available model versions."""
            if not self._model_loader:
                return []
            versions = self._model_loader.list_versions()
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
        
        @self.app.post(
            "/killswitch",
            response_model=KillSwitchResponse,
            summary="Toggle kill switch",
            description="Enable or disable the kill switch to stop routing to canary model",
            tags=["routing"],
        )
        async def killswitch(request: KillSwitchRequest) -> KillSwitchResponse:
            """Enable or disable kill switch."""
            if not self._router:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Router not initialized",
                )
            
            self._router.set_kill_switch(request.enabled)
            return KillSwitchResponse(
                kill_switch=request.enabled,
                message="Kill switch " + ("enabled" if request.enabled else "disabled"),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        
        @self.app.get(
            "/router/stats",
            response_model=RouterStats,
            summary="Router statistics",
            description="Get A/B router statistics including traffic split and request counts",
            tags=["routing"],
        )
        async def router_stats() -> RouterStats:
            """Get A/B router statistics."""
            if not self._router:
                return RouterStats()
            stats = self._router.get_stats()
            return RouterStats(
                active_version=stats.get("active_version", "unknown"),
                canary_version=stats.get("canary_version"),
                canary_ratio=stats.get("canary_ratio", 0.0),
                total_requests=stats.get("total_requests", 0),
                active_requests=stats.get("active_requests", 0),
                canary_requests=stats.get("canary_requests", 0),
                kill_switch_enabled=stats.get("kill_switch_enabled", False),
            )
        
        @self.app.post(
            "/api/v1/health/warmup",
            response_model=WarmupResponse,
            summary="Warmup LLM",
            description="Warm up the LLM model for faster first response",
            tags=["explain"],
        )
        async def warmup_llm() -> WarmupResponse:
            """Warm up LLM for faster responses."""
            import httpx
            
            start_time = time.time()
            try:
                # Send a simple warmup request to Ollama
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        "http://127.0.0.1:11434/api/generate",
                        json={
                            "model": "llama3.2:1b",
                            "prompt": "Hello",
                            "stream": False,
                        },
                    )
                    warmup_time = (time.time() - start_time) * 1000
                    
                    if resp.status_code == 200:
                        return WarmupResponse(
                            status="success",
                            llm_ready=True,
                            model="llama3.2:1b",
                            warmup_time_ms=warmup_time,
                            message="LLM warmed up successfully",
                        )
                    else:
                        return WarmupResponse(
                            status="error",
                            llm_ready=False,
                            model="llama3.2:1b",
                            warmup_time_ms=warmup_time,
                            message=f"Ollama returned {resp.status_code}",
                        )
            except Exception as e:
                warmup_time = (time.time() - start_time) * 1000
                return WarmupResponse(
                    status="error",
                    llm_ready=False,
                    model="llama3.2:1b",
                    warmup_time_ms=warmup_time,
                    message=str(e),
                )
        
        # --- Recommendations Endpoints ---
        
        @self.app.post(
            "/recommendations",
            response_model=RecommendationsResponse,
            summary="Get career recommendations",
            description="Get personalized career recommendations based on user profile",
            tags=["recommendations"],
        )
        async def get_recommendations(request: RecommendationsRequest) -> RecommendationsResponse:
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
        
        @self.app.get(
            "/career-library",
            response_model=CareerLibraryResponse,
            summary="Get career library",
            description="Get the full career library with all available careers",
            tags=["recommendations"],
        )
        async def get_career_library() -> CareerLibraryResponse:
            """Get full career library."""
            # Mock career library matching frontend expected format
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
        
        # --- Analyze Profile Endpoint ---
        
        @self.app.post(
            "/analyze",
            response_model=AnalyzeResponse,
            summary="Analyze user profile",
            description="Analyze user profile and extract features for recommendations",
            tags=["recommendations"],
        )
        async def analyze_profile(request: AnalyzeRequest) -> AnalyzeResponse:
            """Analyze user profile and return processed data."""
            try:
                # Try to use processor if available
                from backend.processor import process_user_profile
                
                # Build profile dict
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
                
                # Process profile
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
    
    def _extract_reason_codes(self, xai_meta: Dict[str, Any]) -> List[str]:
        """Extract reason codes from XAI metadata for Stage 3."""
        codes = []
        
        # Extract from top_features
        top_features = xai_meta.get("top_features", [])
        for feature in top_features:
            if isinstance(feature, dict):
                name = feature.get("name", "")
                importance = feature.get("importance", 0)
                
                # Convert feature name to reason code
                if importance >= 0.15:  # High importance
                    codes.append(f"{name}_high")
                elif importance >= 0.10:  # Good importance
                    codes.append(f"{name}_good")
        
        return codes
    
    def _extract_sources(self, xai_meta: Dict[str, Any]) -> List[str]:
        """Extract evidence sources from XAI metadata."""
        method = xai_meta.get("method", "")
        
        sources = []
        if "shap" in method.lower():
            sources.append("shap")
        if "fi" in method.lower() or "importance" in method.lower():
            sources.append("importance")
        if "coef" in method.lower():
            sources.append("coef")
        if "perm" in method.lower():
            sources.append("perm")
        
        # Return at least one source
        if not sources:
            sources = ["importance"]
        
        return sources


# ═══════════════════════════════════════════════════════════════════════════
#  Factory Function
# ═══════════════════════════════════════════════════════════════════════════

def create_inference_api(
    model_loader: Optional[ModelLoader] = None,
    router: Optional[ABRouter] = None,
    feedback: Optional[FeedbackCollector] = None,
    metrics: Optional[MetricTracker] = None,
) -> InferenceAPI:
    """Create and configure inference API."""
    api = InferenceAPI()
    api.setup(model_loader, router, feedback, metrics)
    return api

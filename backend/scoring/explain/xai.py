# backend/scoring/explain/xai.py
"""
XAI Service
===========

Core Explainable AI service that integrates feature importance, SHAP,
and reason generation for explainable predictions.

Position in architecture:
    User → Inference API → Scoring Engine → XAI Service → Response

Every prediction must pass through XAI for explanation before returning.
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from backend.scoring.explain.feature_importance import (
    FeatureImportance,
    FeatureImportanceResult,
)
from backend.scoring.explain.shap_engine import SHAPEngine, SHAPResult
from backend.scoring.explain.reason_generator import ReasonGenerator, ReasonResult

logger = logging.getLogger("xai.service")


@dataclass
class ExplanationResult:
    """Complete explanation result for a prediction."""
    
    # Core prediction
    predicted_career: str
    confidence: float
    
    # Explanations
    reasons: List[str]
    
    # Metadata
    xai_meta: Dict[str, Any] = field(default_factory=dict)
    
    # Full details (for audit)
    feature_importance: Optional[FeatureImportanceResult] = None
    shap_result: Optional[SHAPResult] = None
    reason_result: Optional[ReasonResult] = None
    
    # Tracing
    trace_id: str = ""
    model_version: str = ""
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.trace_id:
            self.trace_id = str(uuid.uuid4())[:12]
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_response(self) -> Dict[str, Any]:
        """Convert to API response format."""
        return {
            "career": self.predicted_career,
            "confidence": round(self.confidence, 4),
            "reason": self.reasons,
            "xai_meta": self.xai_meta,
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to full dictionary (for logging)."""
        return {
            "predicted_career": self.predicted_career,
            "confidence": round(self.confidence, 4),
            "reasons": self.reasons,
            "xai_meta": self.xai_meta,
            "trace_id": self.trace_id,
            "model_version": self.model_version,
            "timestamp": self.timestamp,
            "details": {
                "feature_importance": (
                    self.feature_importance.to_dict()
                    if self.feature_importance else None
                ),
                "shap": (
                    self.shap_result.compress()
                    if self.shap_result else None
                ),
                "reasons": (
                    self.reason_result.to_dict()
                    if self.reason_result else None
                ),
            },
        }


class XAIService:
    """
    Core XAI service for explainable predictions.
    
    Usage::
    
        xai = XAIService()
        xai.load_config(config)
        xai.load_model()
        
        # Explain a prediction
        result = xai.explain(
            sample=features,
            predicted_career="Data Scientist",
            confidence=0.91,
        )
        
        # Get API response
        response = result.to_response()
        # {
        #     "career": "Data Scientist",
        #     "confidence": 0.91,
        #     "reason": ["Toán cao (8.9)", "Logic mạnh (7.8)"],
        #     "xai_meta": {...}
        # }
    """
    
    def __init__(self):
        self._project_root = Path(__file__).resolve().parents[3]
        
        # Components
        self._feature_importance = FeatureImportance()
        self._shap_engine = SHAPEngine()
        self._reason_generator = ReasonGenerator()
        
        # Model state
        self._model = None
        self._model_version = ""
        self._feature_names: List[str] = []
        self._classes: List[str] = []
        self._background_data: Optional[np.ndarray] = None
        
        # Configuration
        self._top_k = 3
        self._min_importance = 0.15
        self._enable_shap = True
        self._language = "vi"
        self._log_enabled = True
        
        # Logging
        self._xai_logs_dir = self._project_root / "outputs" / "xai_logs"
        self._xai_logs_dir.mkdir(parents=True, exist_ok=True)
        
        self._lock = threading.RLock()
    
    def load_config(self, config: Dict[str, Any]) -> None:
        """
        Load configuration from system.yaml xai section.
        
        Args:
            config: System configuration dict (or xai section)
        """
        xai_config = config.get("xai", config)
        
        self._top_k = xai_config.get("top_k", 3)
        self._min_importance = xai_config.get("min_importance", 0.15)
        self._enable_shap = xai_config.get("enable_shap", True)
        self._language = xai_config.get("language", "vi")
        self._log_enabled = xai_config.get("enable_logging", True)
        
        # Configure components
        self._shap_engine = SHAPEngine(enable_shap=self._enable_shap)
        self._reason_generator.load_config(xai_config)
        
        logger.info(
            f"XAI config: top_k={self._top_k}, min_importance={self._min_importance}, "
            f"shap={self._enable_shap}, lang={self._language}"
        )
    
    def load_model(
        self,
        model_path: Optional[str] = None,
        model: Optional[Any] = None,
        feature_names: Optional[List[str]] = None,
        classes: Optional[List[str]] = None,
        background_data: Optional[np.ndarray] = None,
        model_version: str = "",
    ) -> bool:
        """
        Load model for explanation.
        
        Args:
            model_path: Path to model pickle file
            model: Pre-loaded model object
            feature_names: List of feature names
            classes: List of class labels
            background_data: Background data for SHAP
            model_version: Version string
            
        Returns:
            True if model loaded successfully
        """
        with self._lock:
            try:
                # Load model from path or use provided
                if model is not None:
                    self._model = model
                elif model_path:
                    full_path = self._project_root / model_path
                    with open(full_path, "rb") as f:
                        self._model = pickle.load(f)
                else:
                    # Try default active model path
                    default_path = self._project_root / "models" / "active" / "model.pkl"
                    if default_path.exists():
                        with open(default_path, "rb") as f:
                            self._model = pickle.load(f)
                    else:
                        logger.warning("No model found to load")
                        return False
                
                # Set feature names
                if feature_names:
                    self._feature_names = feature_names
                else:
                    # Try to get from model
                    if hasattr(self._model, "feature_names_in_"):
                        self._feature_names = list(self._model.feature_names_in_)
                    else:
                        # Load from classes.json
                        self._feature_names = self._load_feature_names()
                
                # Set classes
                if classes:
                    self._classes = classes
                else:
                    # Try to get from model
                    if hasattr(self._model, "classes_"):
                        self._classes = list(self._model.classes_)
                    else:
                        self._classes = self._load_classes()
                
                # Set background data
                self._background_data = background_data
                
                # Set version
                self._model_version = model_version or self._load_model_version()
                
                # Initialize SHAP engine with model
                self._shap_engine.set_model(
                    self._model,
                    self._feature_names,
                    self._background_data,
                    self._classes,
                )
                
                logger.info(
                    f"Model loaded: version={self._model_version}, "
                    f"features={len(self._feature_names)}, classes={len(self._classes)}"
                )
                return True
                
            except Exception as e:
                logger.error(f"Failed to load model: {e}")
                return False
    
    def _load_feature_names(self) -> List[str]:
        """Load feature names from config or model directory."""
        # Try classes.json in active model
        classes_path = self._project_root / "models" / "active" / "classes.json"
        if classes_path.exists():
            try:
                with open(classes_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "feature_names" in data:
                        return data["feature_names"]
            except Exception:
                pass
        
        # Default feature names for career guidance
        return [
            "math_score", "physics_score", "chemistry_score",
            "literature_score", "english_score", "logic_score",
            "creativity_score", "communication_score", "analytical_score",
            "interest_it", "interest_ai", "interest_business",
            "interest_design", "interest_science",
        ]
    
    def _load_classes(self) -> List[str]:
        """Load class labels from model directory."""
        classes_path = self._project_root / "models" / "active" / "classes.json"
        if classes_path.exists():
            try:
                with open(classes_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    if "classes" in data:
                        return data["classes"]
            except Exception:
                pass
        return []
    
    def _load_model_version(self) -> str:
        """Load model version from .version file."""
        version_path = self._project_root / "models" / "active" / ".version"
        if version_path.exists():
            try:
                return version_path.read_text().strip()
            except Exception:
                pass
        return "unknown"
    
    def explain(
        self,
        sample: np.ndarray,
        predicted_career: str,
        confidence: float,
        prediction_idx: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> ExplanationResult:
        """
        Generate explanation for a prediction.
        
        Args:
            sample: Feature values (1D array)
            predicted_career: Predicted career label
            confidence: Prediction confidence/probability
            prediction_idx: Index of predicted class
            user_id: Optional user ID for logging
            
        Returns:
            ExplanationResult with reasons and metadata
            
        Raises:
            ValueError: If model not loaded or sample invalid
        """
        if self._model is None:
            raise ValueError("Model not loaded. Call load_model() first.")
        
        trace_id = str(uuid.uuid4())[:12]
        
        # Ensure 1D array
        if sample.ndim > 1:
            sample = sample.flatten()
        
        # Validate sample length
        if len(sample) != len(self._feature_names):
            logger.warning(
                f"Sample length mismatch: {len(sample)} vs {len(self._feature_names)}"
            )
            # Pad or truncate
            if len(sample) < len(self._feature_names):
                sample = np.pad(
                    sample,
                    (0, len(self._feature_names) - len(sample)),
                )
            else:
                sample = sample[:len(self._feature_names)]
        
        # Extract features
        features_dict = self.extract_features(sample)
        
        # Compute feature importance
        fi_result = self._feature_importance.compute(
            self._model,
            self._feature_names,
        )
        
        # Compute SHAP values
        shap_result = None
        if self._enable_shap:
            try:
                shap_result = self._shap_engine.explain(
                    sample,
                    predicted_career,
                    prediction_idx,
                )
            except Exception as e:
                logger.warning(f"SHAP failed: {e}")
        
        # Select top features
        top_features = self._select_top_features(
            fi_result, shap_result, sample
        )
        
        # Generate reasons
        reason_result = self._reason_generator.generate(
            top_features,
            predicted_career,
            min_importance=self._min_importance,
            max_reasons=self._top_k,
        )
        
        # Quality check
        if not reason_result.quality_passed:
            logger.warning(
                f"Reason quality issues: {reason_result.quality_issues}"
            )
        
        # Build XAI metadata
        xai_meta = self._build_xai_meta(
            fi_result, shap_result, reason_result
        )
        
        # Create result
        result = ExplanationResult(
            predicted_career=predicted_career,
            confidence=confidence,
            reasons=reason_result.reasons,
            xai_meta=xai_meta,
            feature_importance=fi_result,
            shap_result=shap_result,
            reason_result=reason_result,
            trace_id=trace_id,
            model_version=self._model_version,
        )
        
        # Audit log
        if self._log_enabled:
            self.log_explanation(result, sample, user_id)
        
        return result
    
    def extract_features(
        self,
        sample: np.ndarray,
    ) -> Dict[str, float]:
        """
        Extract named features from sample array.
        
        Args:
            sample: 1D feature array
            
        Returns:
            Dict mapping feature names to values
        """
        return {
            name: float(sample[i])
            for i, name in enumerate(self._feature_names)
            if i < len(sample)
        }
    
    def _select_top_features(
        self,
        fi_result: FeatureImportanceResult,
        shap_result: Optional[SHAPResult],
        sample: np.ndarray,
    ) -> List[Tuple[str, float, float]]:
        """
        Select top features using SHAP (preferred) or feature importance.
        
        Returns:
            List of (feature_name, importance/shap, value) tuples
        """
        # Prefer SHAP if available
        if shap_result is not None:
            return shap_result.top_k_features(self._top_k * 2)
        
        # Fallback to feature importance
        top_fi = fi_result.top_k(self._top_k * 2)
        
        # Add feature values
        result = []
        for name, importance in top_fi:
            try:
                idx = self._feature_names.index(name)
                value = float(sample[idx])
            except (ValueError, IndexError):
                value = 0.0
            
            result.append((name, importance, value))
        
        return result
    
    def _build_xai_meta(
        self,
        fi_result: FeatureImportanceResult,
        shap_result: Optional[SHAPResult],
        reason_result: ReasonResult,
    ) -> Dict[str, Any]:
        """Build XAI metadata for API response."""
        # Determine method used
        if shap_result is not None:
            method = f"shap({shap_result.method})+fi"
        else:
            method = f"fi({fi_result.method})"
        
        # Top features
        top_features = [
            {
                "name": name,
                "value": round(value, 4),
                "importance": round(imp, 4),
            }
            for name, value, imp in zip(
                reason_result.features_used,
                reason_result.feature_values,
                reason_result.importance_scores,
            )
        ]
        
        return {
            "method": method,
            "top_features": top_features,
            "model_version": self._model_version,
            "quality_passed": reason_result.quality_passed,
        }
    
    def generate_reasons(
        self,
        top_features: List[Tuple[str, float, float]],
        predicted_career: str,
    ) -> List[str]:
        """
        Generate reasons from top features (standalone method).
        
        Args:
            top_features: List of (name, importance, value) tuples
            predicted_career: Predicted career
            
        Returns:
            List of reason strings
        """
        result = self._reason_generator.generate(
            top_features,
            predicted_career,
            min_importance=self._min_importance,
            max_reasons=self._top_k,
        )
        return result.reasons
    
    def log_explanation(
        self,
        result: ExplanationResult,
        sample: np.ndarray,
        user_id: Optional[str] = None,
    ) -> None:
        """
        Log explanation for audit trail.
        
        Writes to outputs/xai_logs/YYYY-MM-DD.jsonl
        """
        try:
            # Build log entry
            log_entry = {
                "trace_id": result.trace_id,
                "timestamp": result.timestamp,
                "user_id": user_id,
                "model_version": result.model_version,
                "predicted_career": result.predicted_career,
                "confidence": result.confidence,
                "reasons": result.reasons,
                "features": self.extract_features(sample),
                "shap_compressed": (
                    result.shap_result.compress()
                    if result.shap_result else None
                ),
                "quality_passed": (
                    result.reason_result.quality_passed
                    if result.reason_result else True
                ),
            }
            
            # Write to daily log file
            date_str = datetime.now().strftime("%Y-%m-%d")
            log_file = self._xai_logs_dir / f"{date_str}.jsonl"
            
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            
            logger.debug(f"Logged explanation: {result.trace_id}")
            
        except Exception as e:
            logger.error(f"Failed to log explanation: {e}")
    
    def get_feature_names(self) -> List[str]:
        """Get loaded feature names."""
        return self._feature_names.copy()
    
    def get_classes(self) -> List[str]:
        """Get loaded class labels."""
        return self._classes.copy()
    
    def is_ready(self) -> bool:
        """Check if service is ready to explain."""
        return self._model is not None and len(self._feature_names) > 0


# Singleton instance
_xai_service: Optional[XAIService] = None


def get_xai_service() -> XAIService:
    """Get or create singleton XAI service."""
    global _xai_service
    if _xai_service is None:
        _xai_service = XAIService()
    return _xai_service

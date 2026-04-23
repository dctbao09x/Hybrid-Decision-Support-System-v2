# backend/scoring/explain/feature_importance.py
"""
Feature Importance Calculator
=============================

Extracts and normalizes feature importances from various ML model types.

Supported models:
  - RandomForest: feature_importances_
  - LogisticRegression: coef_
  - GradientBoosting: feature_importances_
  - XGBoost: feature_importances_

Output is always normalized to [0, 1].
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("xai.feature_importance")


@dataclass
class FeatureImportanceResult:
    """Result of feature importance computation."""
    
    feature_names: List[str]
    importances: List[float]  # Normalized to [0, 1]
    raw_importances: List[float]  # Original values
    method: str  # "tree" | "coef" | "permutation"
    model_type: str
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature_names": self.feature_names,
            "importances": [round(x, 6) for x in self.importances],
            "raw_importances": [round(x, 6) for x in self.raw_importances],
            "method": self.method,
            "model_type": self.model_type,
            "timestamp": self.timestamp,
        }
    
    def top_k(self, k: int = 5) -> List[Tuple[str, float]]:
        """Get top k most important features."""
        pairs = list(zip(self.feature_names, self.importances))
        pairs.sort(key=lambda x: x[1], reverse=True)
        return pairs[:k]
    
    def get_importance(self, feature_name: str) -> float:
        """Get importance of a specific feature."""
        try:
            idx = self.feature_names.index(feature_name)
            return self.importances[idx]
        except ValueError:
            return 0.0


class FeatureImportance:
    """
    Feature importance extractor for various model types.
    
    Usage::
    
        fi = FeatureImportance()
        result = fi.compute(model, feature_names)
        
        top_features = result.top_k(5)
        for name, importance in top_features:
            print(f"{name}: {importance:.4f}")
    """
    
    # Model type detection patterns
    TREE_MODELS = (
        "RandomForestClassifier",
        "RandomForestRegressor", 
        "GradientBoostingClassifier",
        "GradientBoostingRegressor",
        "ExtraTreesClassifier",
        "ExtraTreesRegressor",
        "XGBClassifier",
        "XGBRegressor",
        "LGBMClassifier",
        "LGBMRegressor",
        "DecisionTreeClassifier",
        "DecisionTreeRegressor",
    )
    
    LINEAR_MODELS = (
        "LogisticRegression",
        "LinearRegression",
        "Ridge",
        "Lasso",
        "ElasticNet",
        "SGDClassifier",
        "SGDRegressor",
    )
    
    def __init__(self):
        self._cache: Dict[str, FeatureImportanceResult] = {}
    
    def compute(
        self,
        model: Any,
        feature_names: List[str],
        X: Optional[np.ndarray] = None,
        y: Optional[np.ndarray] = None,
    ) -> FeatureImportanceResult:
        """
        Compute feature importances for the given model.
        
        Args:
            model: Trained sklearn-compatible model
            feature_names: List of feature names
            X: Optional feature matrix for permutation importance
            y: Optional target array for permutation importance
            
        Returns:
            FeatureImportanceResult with normalized importances
        """
        model_type = type(model).__name__
        
        # Try tree-based importance
        if self._is_tree_model(model):
            return self._compute_tree_importance(model, feature_names, model_type)
        
        # Try linear model coefficients
        if self._is_linear_model(model):
            return self._compute_linear_importance(model, feature_names, model_type)
        
        # Fallback to permutation importance
        if X is not None and y is not None:
            return self._compute_permutation_importance(
                model, feature_names, X, y, model_type
            )
        
        # Last resort: uniform importance
        logger.warning(
            f"Cannot compute importance for {model_type}, using uniform"
        )
        return self._uniform_importance(feature_names, model_type)
    
    def _is_tree_model(self, model: Any) -> bool:
        """Check if model is tree-based."""
        model_type = type(model).__name__
        return (
            model_type in self.TREE_MODELS
            or hasattr(model, "feature_importances_")
        )
    
    def _is_linear_model(self, model: Any) -> bool:
        """Check if model is linear."""
        model_type = type(model).__name__
        return (
            model_type in self.LINEAR_MODELS
            or hasattr(model, "coef_")
        )
    
    def _compute_tree_importance(
        self,
        model: Any,
        feature_names: List[str],
        model_type: str,
    ) -> FeatureImportanceResult:
        """Extract feature importances from tree-based models."""
        try:
            raw_importances = model.feature_importances_
            
            # Normalize to [0, 1]
            importances = self._normalize(raw_importances)
            
            logger.debug(
                f"Tree importance computed for {model_type}: "
                f"max={max(importances):.4f}, min={min(importances):.4f}"
            )
            
            return FeatureImportanceResult(
                feature_names=feature_names,
                importances=importances.tolist(),
                raw_importances=raw_importances.tolist(),
                method="tree",
                model_type=model_type,
            )
            
        except Exception as e:
            logger.error(f"Tree importance failed: {e}")
            return self._uniform_importance(feature_names, model_type)
    
    def _compute_linear_importance(
        self,
        model: Any,
        feature_names: List[str],
        model_type: str,
    ) -> FeatureImportanceResult:
        """Extract feature importances from linear model coefficients."""
        try:
            coef = model.coef_
            
            # Handle multi-class (take mean of absolute values)
            if coef.ndim > 1:
                raw_importances = np.mean(np.abs(coef), axis=0)
            else:
                raw_importances = np.abs(coef)
            
            # Normalize to [0, 1]
            importances = self._normalize(raw_importances)
            
            logger.debug(
                f"Linear importance computed for {model_type}: "
                f"max={max(importances):.4f}, min={min(importances):.4f}"
            )
            
            return FeatureImportanceResult(
                feature_names=feature_names,
                importances=importances.tolist(),
                raw_importances=raw_importances.tolist(),
                method="coef",
                model_type=model_type,
            )
            
        except Exception as e:
            logger.error(f"Linear importance failed: {e}")
            return self._uniform_importance(feature_names, model_type)
    
    def _compute_permutation_importance(
        self,
        model: Any,
        feature_names: List[str],
        X: np.ndarray,
        y: np.ndarray,
        model_type: str,
        n_repeats: int = 10,
    ) -> FeatureImportanceResult:
        """Compute permutation importance (model-agnostic)."""
        try:
            from sklearn.inspection import permutation_importance
            
            result = permutation_importance(
                model, X, y,
                n_repeats=n_repeats,
                random_state=42,
                n_jobs=-1,
            )
            
            raw_importances = result.importances_mean
            
            # Clip negative values (can happen with permutation)
            raw_importances = np.clip(raw_importances, 0, None)
            
            # Normalize to [0, 1]
            importances = self._normalize(raw_importances)
            
            logger.debug(
                f"Permutation importance computed for {model_type}: "
                f"max={max(importances):.4f}"
            )
            
            return FeatureImportanceResult(
                feature_names=feature_names,
                importances=importances.tolist(),
                raw_importances=raw_importances.tolist(),
                method="permutation",
                model_type=model_type,
            )
            
        except Exception as e:
            logger.error(f"Permutation importance failed: {e}")
            return self._uniform_importance(feature_names, model_type)
    
    def _normalize(self, values: np.ndarray) -> np.ndarray:
        """Normalize values to [0, 1] range."""
        values = np.array(values, dtype=float)
        
        total = np.sum(np.abs(values))
        if total > 0:
            normalized = np.abs(values) / total
        else:
            normalized = np.ones_like(values) / len(values)
        
        return normalized
    
    def _uniform_importance(
        self,
        feature_names: List[str],
        model_type: str,
    ) -> FeatureImportanceResult:
        """Return uniform importance (fallback)."""
        n = len(feature_names)
        uniform = [1.0 / n] * n
        
        return FeatureImportanceResult(
            feature_names=feature_names,
            importances=uniform,
            raw_importances=uniform,
            method="uniform",
            model_type=model_type,
        )
    
    def compare(
        self,
        result1: FeatureImportanceResult,
        result2: FeatureImportanceResult,
    ) -> Dict[str, Any]:
        """Compare two importance results."""
        if result1.feature_names != result2.feature_names:
            raise ValueError("Feature names must match for comparison")
        
        diff = {}
        for i, name in enumerate(result1.feature_names):
            diff[name] = {
                "importance_1": result1.importances[i],
                "importance_2": result2.importances[i],
                "delta": result2.importances[i] - result1.importances[i],
            }
        
        return {
            "method_1": result1.method,
            "method_2": result2.method,
            "features": diff,
        }

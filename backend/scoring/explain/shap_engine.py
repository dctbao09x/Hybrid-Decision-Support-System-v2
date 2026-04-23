# backend/scoring/explain/shap_engine.py
"""
SHAP Explanation Engine
=======================

Computes SHAP (SHapley Additive exPlanations) values for model predictions.

Supported explainers:
  - TreeExplainer: For tree-based models (RF, XGBoost, LightGBM)
  - LinearExplainer: For linear models (LogisticRegression, Ridge)
  - KernelExplainer: Universal fallback (slow but works for any model)

Fallback:
  - Permutation Importance if SHAP fails
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

logger = logging.getLogger("xai.shap_engine")


@dataclass
class SHAPResult:
    """Result of SHAP computation."""
    
    feature_names: List[str]
    shap_values: List[float]  # SHAP values for the predicted class
    base_value: float  # Expected value (base prediction)
    feature_values: List[float]  # Actual feature values for the sample
    predicted_class: Optional[str] = None
    prediction_proba: float = 0.0
    method: str = "tree"  # "tree" | "linear" | "kernel" | "permutation"
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature_names": self.feature_names,
            "shap_values": [round(x, 6) for x in self.shap_values],
            "base_value": round(self.base_value, 6),
            "feature_values": [round(x, 4) for x in self.feature_values],
            "predicted_class": self.predicted_class,
            "prediction_proba": round(self.prediction_proba, 4),
            "method": self.method,
            "timestamp": self.timestamp,
        }
    
    def mean_abs_shap(self) -> float:
        """Compute mean absolute SHAP value."""
        return float(np.mean(np.abs(self.shap_values)))
    
    def top_k_features(self, k: int = 5) -> List[Tuple[str, float, float]]:
        """
        Get top k features by absolute SHAP value.
        
        Returns:
            List of (feature_name, shap_value, feature_value) tuples
        """
        # Create (name, shap, value) tuples
        data = list(zip(
            self.feature_names,
            self.shap_values,
            self.feature_values,
        ))
        
        # Sort by absolute SHAP value
        data.sort(key=lambda x: abs(x[1]), reverse=True)
        
        return data[:k]
    
    def get_contribution(self, feature_name: str) -> Tuple[float, float]:
        """
        Get SHAP contribution for a specific feature.
        
        Returns:
            (shap_value, feature_value) tuple
        """
        try:
            idx = self.feature_names.index(feature_name)
            return self.shap_values[idx], self.feature_values[idx]
        except ValueError:
            return 0.0, 0.0
    
    def compress(self) -> Dict[str, Any]:
        """Compress SHAP result for logging (only top features)."""
        top = self.top_k_features(10)
        return {
            "top_features": [
                {"name": n, "shap": round(s, 4), "value": round(v, 4)}
                for n, s, v in top
            ],
            "base_value": round(self.base_value, 4),
            "mean_abs_shap": round(self.mean_abs_shap(), 4),
            "method": self.method,
        }


class SHAPEngine:
    """
    SHAP explanation engine with automatic explainer selection.
    
    Usage::
    
        engine = SHAPEngine()
        engine.set_model(model, feature_names)
        
        # Explain single sample
        result = engine.explain(sample)
        
        # Get top contributing features
        top_features = result.top_k_features(5)
    """
    
    # Model type patterns for explainer selection
    TREE_MODELS = {
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
    }
    
    LINEAR_MODELS = {
        "LogisticRegression",
        "LinearRegression",
        "Ridge",
        "Lasso",
        "ElasticNet",
    }
    
    def __init__(self, enable_shap: bool = True):
        self._model = None
        self._feature_names: List[str] = []
        self._explainer = None
        self._explainer_type: str = ""
        self._background_data: Optional[np.ndarray] = None
        self._classes: Optional[List[str]] = None
        self._enable_shap = enable_shap
        self._shap_available = self._check_shap_available()
    
    def _check_shap_available(self) -> bool:
        """Check if SHAP library is available."""
        try:
            import shap
            return True
        except ImportError:
            logger.warning("SHAP not installed, using permutation fallback")
            return False
    
    def set_model(
        self,
        model: Any,
        feature_names: List[str],
        background_data: Optional[np.ndarray] = None,
        classes: Optional[List[str]] = None,
    ) -> None:
        """
        Set the model to explain.
        
        Args:
            model: Trained sklearn-compatible model
            feature_names: List of feature names
            background_data: Background data for KernelExplainer
            classes: Class labels for classification
        """
        self._model = model
        self._feature_names = feature_names
        self._background_data = background_data
        self._classes = classes
        self._explainer = None  # Reset explainer
        self._explainer_type = ""
        
        if self._enable_shap and self._shap_available:
            self._init_explainer()
    
    def _init_explainer(self) -> None:
        """Initialize appropriate SHAP explainer based on model type."""
        import shap
        
        model_type = type(self._model).__name__
        
        # Try TreeExplainer first
        if model_type in self.TREE_MODELS:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    self._explainer = shap.TreeExplainer(self._model)
                self._explainer_type = "tree"
                logger.info(f"Using TreeExplainer for {model_type}")
                return
            except Exception as e:
                logger.warning(f"TreeExplainer failed: {e}")
        
        # Try LinearExplainer
        if model_type in self.LINEAR_MODELS:
            try:
                if self._background_data is not None:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        self._explainer = shap.LinearExplainer(
                            self._model,
                            self._background_data,
                        )
                    self._explainer_type = "linear"
                    logger.info(f"Using LinearExplainer for {model_type}")
                    return
            except Exception as e:
                logger.warning(f"LinearExplainer failed: {e}")
        
        # Fallback to KernelExplainer (slow but universal)
        if self._background_data is not None:
            try:
                # Use smaller background for kernel
                bg_sample = self._background_data
                if len(bg_sample) > 100:
                    indices = np.random.choice(
                        len(bg_sample), 100, replace=False
                    )
                    bg_sample = bg_sample[indices]
                
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    
                    # Use predict_proba if available
                    if hasattr(self._model, "predict_proba"):
                        def model_predict(X):
                            return self._model.predict_proba(X)
                    else:
                        def model_predict(X):
                            return self._model.predict(X)
                    
                    self._explainer = shap.KernelExplainer(
                        model_predict,
                        bg_sample,
                    )
                self._explainer_type = "kernel"
                logger.info(f"Using KernelExplainer for {model_type}")
                return
            except Exception as e:
                logger.warning(f"KernelExplainer failed: {e}")
        
        logger.warning(f"No SHAP explainer available for {model_type}")
    
    def explain(
        self,
        sample: np.ndarray,
        predicted_class: Optional[str] = None,
        prediction_idx: Optional[int] = None,
    ) -> SHAPResult:
        """
        Explain a single prediction using SHAP.
        
        Args:
            sample: Feature values for the sample (1D or 2D array)
            predicted_class: Name of predicted class
            prediction_idx: Index of predicted class (for multi-class)
            
        Returns:
            SHAPResult with SHAP values and metadata
        """
        if self._model is None:
            raise ValueError("Model not set. Call set_model() first.")
        
        # Ensure 2D shape
        if sample.ndim == 1:
            sample = sample.reshape(1, -1)
        
        feature_values = sample[0].tolist()
        
        # Get prediction probability
        prediction_proba = 0.0
        if hasattr(self._model, "predict_proba"):
            proba = self._model.predict_proba(sample)[0]
            if prediction_idx is not None:
                prediction_proba = proba[prediction_idx]
            else:
                prediction_proba = float(np.max(proba))
        
        # Try SHAP if available
        if self._enable_shap and self._explainer is not None:
            try:
                return self._compute_shap(
                    sample,
                    feature_values,
                    predicted_class,
                    prediction_proba,
                    prediction_idx,
                )
            except Exception as e:
                logger.warning(f"SHAP computation failed: {e}")
        
        # Fallback to permutation importance
        return self._compute_permutation(
            sample,
            feature_values,
            predicted_class,
            prediction_proba,
        )
    
    def _compute_shap(
        self,
        sample: np.ndarray,
        feature_values: List[float],
        predicted_class: Optional[str],
        prediction_proba: float,
        prediction_idx: Optional[int],
    ) -> SHAPResult:
        """Compute SHAP values using the initialized explainer."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            shap_values = self._explainer.shap_values(sample)
        
        # Handle different SHAP output formats
        if isinstance(shap_values, list):
            # Multi-class: pick the predicted class
            if prediction_idx is not None and prediction_idx < len(shap_values):
                shap_values = shap_values[prediction_idx]
            else:
                # Use the class with highest SHAP magnitude
                shap_values = shap_values[-1]  # Last class by default
        
        # Flatten if needed
        shap_values = np.array(shap_values).flatten()
        
        # Get base value
        base_value = 0.0
        if hasattr(self._explainer, "expected_value"):
            ev = self._explainer.expected_value
            if isinstance(ev, np.ndarray):
                if prediction_idx is not None and prediction_idx < len(ev):
                    base_value = float(ev[prediction_idx])
                else:
                    base_value = float(ev[-1])
            else:
                base_value = float(ev)
        
        return SHAPResult(
            feature_names=self._feature_names,
            shap_values=shap_values.tolist(),
            base_value=base_value,
            feature_values=feature_values,
            predicted_class=predicted_class,
            prediction_proba=prediction_proba,
            method=self._explainer_type,
        )
    
    def _compute_permutation(
        self,
        sample: np.ndarray,
        feature_values: List[float],
        predicted_class: Optional[str],
        prediction_proba: float,
        n_repeats: int = 20,
    ) -> SHAPResult:
        """
        Compute permutation-based feature importance for single sample.
        
        This is a local approximation using prediction differences.
        """
        logger.debug("Using permutation fallback for explanation")
        
        # Get base prediction
        if hasattr(self._model, "predict_proba"):
            base_pred = self._model.predict_proba(sample)[0]
            base_value = float(np.max(base_pred))
        else:
            base_pred = self._model.predict(sample)
            base_value = float(base_pred[0])
        
        # Compute feature contributions by perturbation
        shap_values = []
        
        for i in range(len(self._feature_names)):
            diffs = []
            
            for _ in range(n_repeats):
                # Create perturbed sample
                perturbed = sample.copy()
                
                # Randomly perturb the feature
                if self._background_data is not None:
                    # Use background value
                    bg_idx = np.random.randint(len(self._background_data))
                    perturbed[0, i] = self._background_data[bg_idx, i]
                else:
                    # Add noise
                    std = abs(perturbed[0, i]) * 0.1 + 0.1
                    perturbed[0, i] += np.random.normal(0, std)
                
                # Get perturbed prediction
                if hasattr(self._model, "predict_proba"):
                    pert_pred = self._model.predict_proba(perturbed)[0]
                    pert_value = float(np.max(pert_pred))
                else:
                    pert_pred = self._model.predict(perturbed)
                    pert_value = float(pert_pred[0])
                
                diffs.append(base_value - pert_value)
            
            # Average contribution
            shap_values.append(float(np.mean(diffs)))
        
        return SHAPResult(
            feature_names=self._feature_names,
            shap_values=shap_values,
            base_value=base_value,
            feature_values=feature_values,
            predicted_class=predicted_class,
            prediction_proba=prediction_proba,
            method="permutation",
        )
    
    def explain_batch(
        self,
        samples: np.ndarray,
        max_samples: int = 100,
    ) -> List[SHAPResult]:
        """
        Explain multiple samples.
        
        Args:
            samples: 2D array of samples
            max_samples: Maximum samples to explain
            
        Returns:
            List of SHAPResult
        """
        if len(samples) > max_samples:
            logger.warning(
                f"Limiting explanation to {max_samples} samples"
            )
            samples = samples[:max_samples]
        
        results = []
        for i, sample in enumerate(samples):
            try:
                result = self.explain(sample)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to explain sample {i}: {e}")
        
        return results
    
    def global_importance(
        self,
        samples: np.ndarray,
    ) -> Dict[str, float]:
        """
        Compute global feature importance from SHAP values.
        
        Args:
            samples: 2D array of samples
            
        Returns:
            Dict mapping feature names to mean absolute SHAP values
        """
        results = self.explain_batch(samples)
        
        # Aggregate SHAP values
        all_shap = np.array([r.shap_values for r in results])
        mean_abs_shap = np.mean(np.abs(all_shap), axis=0)
        
        # Normalize
        total = np.sum(mean_abs_shap)
        if total > 0:
            mean_abs_shap = mean_abs_shap / total
        
        return {
            name: float(value)
            for name, value in zip(self._feature_names, mean_abs_shap)
        }

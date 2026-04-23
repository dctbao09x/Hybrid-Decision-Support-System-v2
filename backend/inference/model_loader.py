# backend/inference/model_loader.py
"""
Model Loader
============

Manages loading and switching between model versions for online inference.

Responsibilities:
  - Load model from models/active/ or specific version
  - Hot-swap models without restart
  - Fallback to rollback model on failure
  - Track loaded model metadata
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from backend.mlops.registry import ModelRegistryStore

logger = logging.getLogger("ml_inference.model_loader")


@dataclass
class LoadedModel:
    """Represents a loaded model with metadata."""
    version: str
    model: Any  # sklearn model
    metrics: Dict[str, Any]
    fingerprint: Dict[str, Any]
    loaded_at: str = ""
    model_type: str = ""
    
    def __post_init__(self):
        if not self.loaded_at:
            self.loaded_at = datetime.now(timezone.utc).isoformat()
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict using the loaded model."""
        return self.model.predict(X)
    
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Predict probabilities if supported."""
        if hasattr(self.model, "predict_proba"):
            return self.model.predict_proba(X)
        raise NotImplementedError("Model does not support predict_proba")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "model_type": self.model_type,
            "metrics": self.metrics,
            "fingerprint_hash": self.fingerprint.get("hash", "")[:16],
            "loaded_at": self.loaded_at,
        }


class ModelLoader:
    """
    Thread-safe model loader with hot-swap and fallback support.
    
    Usage::
    
        loader = ModelLoader()
        loader.load_active()
        
        # Get current model
        model = loader.get_model()
        predictions = model.predict(X)
        
        # Hot-swap to new version
        loader.load_version("v2")
    """
    
    def __init__(
        self,
        models_dir: str = "models",
        active_link: str = "active",
        rollback_link: str = "rollback",
    ):
        self._project_root = Path(__file__).resolve().parents[2]
        self._models_dir = self._project_root / models_dir
        self._active_link = active_link
        self._rollback_link = rollback_link
        
        # Thread-safe model storage
        self._lock = threading.RLock()
        self._active_model: Optional[LoadedModel] = None
        self._fallback_model: Optional[LoadedModel] = None
        self._canary_model: Optional[LoadedModel] = None
        
        # Label encoder for decoding predictions
        self._label_encoder: Optional[Any] = None
        self._classes: List[str] = []
        
        # Ensure models directory exists
        self._models_dir.mkdir(parents=True, exist_ok=True)
        self._mlops_registry = ModelRegistryStore()
    
    # ──────────────────────────────────────────────────────────────
    #  Public API
    # ──────────────────────────────────────────────────────────────
    
    def load_active(self) -> LoadedModel:
        """Load the active model (from models/active/)."""
        with self._lock:
            active_path = self._models_dir / self._active_link
            
            if not active_path.exists():
                # Try to load v1 as default
                v1_path = self._models_dir / "v1"
                if v1_path.exists():
                    self._create_link(v1_path, active_path)
                else:
                    raise FileNotFoundError(
                        f"No active model found at {active_path} and no v1 fallback"
                    )
            
            self._active_model = self._load_from_path(active_path)
            logger.info(
                "Loaded active model: version=%s type=%s",
                self._active_model.version,
                self._active_model.model_type,
            )
            return self._active_model
    
    def load_rollback(self) -> Optional[LoadedModel]:
        """Load the rollback model (from models/rollback/)."""
        with self._lock:
            rollback_path = self._models_dir / self._rollback_link
            
            if not rollback_path.exists():
                logger.warning("No rollback model available")
                return None
            
            self._fallback_model = self._load_from_path(rollback_path)
            logger.info(
                "Loaded rollback model: version=%s",
                self._fallback_model.version,
            )
            return self._fallback_model
    
    def load_version(self, version: str) -> LoadedModel:
        """Load a specific model version."""
        with self._lock:
            version_path = self._models_dir / version
            
            if not version_path.exists():
                raise FileNotFoundError(f"Model version not found: {version}")

            if not self._mlops_registry.is_registered_artifact(version_path):
                raise PermissionError(
                    f"Inference blocked: model version {version} is not registered in MLOps registry"
                )
            
            model = self._load_from_path(version_path)
            logger.info("Loaded model version: %s", version)
            return model
    
    def load_canary(self, version: str) -> LoadedModel:
        """Load a model as canary (for A/B testing)."""
        with self._lock:
            self._canary_model = self.load_version(version)
            logger.info("Loaded canary model: %s", version)
            return self._canary_model
    
    def get_model(self, use_canary: bool = False) -> LoadedModel:
        """Get the current active or canary model."""
        with self._lock:
            if use_canary and self._canary_model:
                return self._canary_model
            
            if self._active_model:
                return self._active_model
            
            # Try to load active
            return self.load_active()
    
    def get_fallback(self) -> Optional[LoadedModel]:
        """Get the fallback model."""
        with self._lock:
            if self._fallback_model:
                return self._fallback_model
            return self.load_rollback()
    
    def hot_swap(self, new_version: str) -> Tuple[bool, str]:
        """
        Hot-swap the active model to a new version.
        
        Returns:
            (success, message)
        """
        with self._lock:
            try:
                # Save current as rollback
                if self._active_model:
                    current_version = self._active_model.version
                    self._save_as_rollback(current_version)
                
                # Load new version
                new_model = self.load_version(new_version)
                
                # Update active link
                self._update_active_link(new_version)
                
                # Swap
                self._active_model = new_model
                self._canary_model = None  # Clear canary after promotion
                
                logger.info("Hot-swapped to version %s", new_version)
                return True, f"Swapped to {new_version}"
                
            except Exception as e:
                logger.error("Hot-swap failed: %s", e)
                return False, str(e)
    
    def rollback(self) -> Tuple[bool, str]:
        """Rollback to the previous model version."""
        with self._lock:
            try:
                rollback_path = self._models_dir / self._rollback_link
                
                if not rollback_path.exists():
                    return False, "No rollback model available"
                
                # Load rollback model
                rollback_model = self._load_from_path(rollback_path)
                
                # Get version from rollback
                rollback_version = rollback_model.version
                
                # Swap active to rollback
                active_path = self._models_dir / self._active_link
                if active_path.exists():
                    # Remove or rename current active
                    if active_path.is_symlink() or active_path.is_dir():
                        if active_path.is_symlink():
                            active_path.unlink()
                        else:
                            shutil.rmtree(active_path)
                
                # Copy rollback to active
                self._create_link(
                    self._models_dir / rollback_version,
                    active_path,
                )
                
                # Update in memory
                self._active_model = rollback_model
                self._canary_model = None
                
                logger.info("Rolled back to version %s", rollback_version)
                return True, f"Rolled back to {rollback_version}"
                
            except Exception as e:
                logger.error("Rollback failed: %s", e)
                return False, str(e)
    
    def list_versions(self) -> List[Dict[str, Any]]:
        """List all available model versions."""
        versions = []
        
        for item in self._models_dir.iterdir():
            if item.is_dir() and item.name.startswith("v"):
                metrics_path = item / "metrics.json"
                if metrics_path.exists():
                    with open(metrics_path, "r", encoding="utf-8") as f:
                        metrics = json.load(f)
                    versions.append({
                        "version": item.name,
                        "accuracy": metrics.get("accuracy", 0),
                        "f1": metrics.get("f1", 0),
                        "created_at": metrics.get("timestamp", ""),
                    })
        
        return sorted(versions, key=lambda x: x["version"], reverse=True)
    
    def decode_prediction(self, encoded: int) -> str:
        """Decode numeric prediction to career label."""
        if self._classes and 0 <= encoded < len(self._classes):
            return self._classes[encoded]
        return f"class_{encoded}"
    
    def get_classes(self) -> List[str]:
        """Get list of career classes."""
        return self._classes.copy()
    
    # ──────────────────────────────────────────────────────────────
    #  Internal Methods
    # ──────────────────────────────────────────────────────────────
    
    def _load_from_path(self, path: Path) -> LoadedModel:
        """Load model from a directory path."""
        # Resolve symlinks
        if path.is_symlink():
            path = path.resolve()
        
        model_file = path / "model.pkl"
        metrics_file = path / "metrics.json"
        fingerprint_file = path / "fingerprint.json"
        classes_file = path / "classes.json"
        
        if not model_file.exists():
            raise FileNotFoundError(f"Model file not found: {model_file}")
        
        # Load model
        with open(model_file, "rb") as f:
            model = pickle.load(f)
        
        # Load metrics
        metrics = {}
        if metrics_file.exists():
            with open(metrics_file, "r", encoding="utf-8") as f:
                metrics = json.load(f)
        
        # Load fingerprint
        fingerprint = {}
        if fingerprint_file.exists():
            with open(fingerprint_file, "r", encoding="utf-8") as f:
                fingerprint = json.load(f)
        
        # Load classes
        if classes_file.exists():
            with open(classes_file, "r", encoding="utf-8") as f:
                self._classes = json.load(f)
        
        # Determine version from path
        version = path.name
        
        return LoadedModel(
            version=version,
            model=model,
            metrics=metrics,
            fingerprint=fingerprint,
            model_type=metrics.get("model_type", "unknown"),
        )
    
    def _create_link(self, source: Path, target: Path) -> None:
        """Create a directory copy (Windows-compatible, no symlink)."""
        if target.exists():
            if target.is_symlink():
                target.unlink()
            else:
                shutil.rmtree(target)
        
        # Copy instead of symlink for Windows compatibility
        shutil.copytree(source, target)
    
    def _update_active_link(self, version: str) -> None:
        """Update the active link to point to a new version."""
        active_path = self._models_dir / self._active_link
        version_path = self._models_dir / version
        
        self._create_link(version_path, active_path)
    
    def _save_as_rollback(self, version: str) -> None:
        """Save a version as rollback."""
        version_path = self._models_dir / version
        rollback_path = self._models_dir / self._rollback_link
        
        if version_path.exists():
            self._create_link(version_path, rollback_path)
            logger.info("Saved %s as rollback", version)

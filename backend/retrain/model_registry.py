# backend/retrain/model_registry.py
"""
Model Registry
==============

Manages versioned model storage.

Structure:
  models/
    v1/
      model.pkl
      metrics.json
      fingerprint.json
      classes.json
    v2/
      ...
    active/   → copy of current active version
    rollback/ → copy of previous version
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ml_retrain.registry")


@dataclass
class ModelVersion:
    """Metadata for a model version."""
    version: str
    accuracy: float
    f1: float
    precision: float
    recall: float
    model_type: str
    run_id: str
    dataset_hash: str
    created_at: str
    is_active: bool = False
    is_rollback: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "metrics": {
                "accuracy": self.accuracy,
                "f1": self.f1,
                "precision": self.precision,
                "recall": self.recall,
            },
            "model_type": self.model_type,
            "run_id": self.run_id,
            "dataset_hash": self.dataset_hash,
            "created_at": self.created_at,
            "is_active": self.is_active,
            "is_rollback": self.is_rollback,
        }


class ModelRegistry:
    """
    Registry for versioned models.
    
    Usage::
    
        registry = ModelRegistry()
        
        # List versions
        versions = registry.list_versions()
        
        # Get active version
        active = registry.get_active()
        
        # Activate a version
        registry.activate("v2")
        
        # Rollback
        registry.rollback()
    """
    
    def __init__(self, models_dir: str = "models"):
        self._project_root = Path(__file__).resolve().parents[2]
        self._models_dir = self._project_root / models_dir
        
        # Ensure directories exist
        self._models_dir.mkdir(parents=True, exist_ok=True)
    
    def list_versions(self) -> List[ModelVersion]:
        """List all model versions."""
        versions = []
        
        active_version = self._get_active_version_name()
        rollback_version = self._get_rollback_version_name()
        
        for item in self._models_dir.iterdir():
            if item.is_dir() and item.name.startswith("v"):
                version_info = self._load_version_info(item)
                if version_info:
                    version_info.is_active = (item.name == active_version)
                    version_info.is_rollback = (item.name == rollback_version)
                    versions.append(version_info)
        
        # Sort by version number (descending)
        versions.sort(key=lambda v: int(v.version[1:]) if v.version[1:].isdigit() else 0, reverse=True)
        
        return versions
    
    def get_version(self, version: str) -> Optional[ModelVersion]:
        """Get info for a specific version."""
        version_dir = self._models_dir / version
        
        if not version_dir.exists():
            return None
        
        return self._load_version_info(version_dir)
    
    def get_active(self) -> Optional[ModelVersion]:
        """Get the active model version."""
        active_name = self._get_active_version_name()
        if active_name:
            return self.get_version(active_name)
        return None
    
    def get_rollback(self) -> Optional[ModelVersion]:
        """Get the rollback model version."""
        rollback_name = self._get_rollback_version_name()
        if rollback_name:
            return self.get_version(rollback_name)
        return None
    
    def activate(self, version: str) -> bool:
        """
        Activate a model version.
        
        - Saves current active as rollback
        - Copies version to active/
        
        Returns:
            True if activation successful
        """
        version_dir = self._models_dir / version
        
        if not version_dir.exists():
            logger.error("Version not found: %s", version)
            return False
        
        active_dir = self._models_dir / "active"
        rollback_dir = self._models_dir / "rollback"
        
        try:
            # Save current active as rollback (if exists)
            if active_dir.exists():
                if rollback_dir.exists():
                    shutil.rmtree(rollback_dir)
                shutil.copytree(active_dir, rollback_dir)
                logger.info("Saved current active as rollback")
            
            # Copy version to active
            if active_dir.exists():
                shutil.rmtree(active_dir)
            shutil.copytree(version_dir, active_dir)
            
            # Update active marker
            self._write_version_marker(active_dir, version)
            
            logger.info("Activated version %s", version)
            return True
            
        except Exception as e:
            logger.error("Failed to activate %s: %s", version, e)
            return False
    
    def rollback(self) -> Optional[str]:
        """
        Rollback to previous version.
        
        Returns:
            Version that was rolled back to, or None if failed
        """
        rollback_dir = self._models_dir / "rollback"
        
        if not rollback_dir.exists():
            logger.error("No rollback version available")
            return None
        
        # Get rollback version name
        rollback_name = self._get_rollback_version_name()
        
        active_dir = self._models_dir / "active"
        
        try:
            # Swap active and rollback
            if active_dir.exists():
                shutil.rmtree(active_dir)
            shutil.copytree(rollback_dir, active_dir)
            
            logger.info("Rolled back to %s", rollback_name)
            return rollback_name
            
        except Exception as e:
            logger.error("Rollback failed: %s", e)
            return None
    
    def register(
        self,
        version: str,
        model_path: str,
    ) -> bool:
        """
        Register a new model version.
        
        Copies model files from model_path to models/vX/
        """
        source_path = Path(model_path)
        
        if not source_path.exists():
            logger.error("Source path not found: %s", model_path)
            return False
        
        version_dir = self._models_dir / version
        
        try:
            if version_dir.exists():
                shutil.rmtree(version_dir)
            
            shutil.copytree(source_path, version_dir)
            logger.info("Registered version %s", version)
            return True
            
        except Exception as e:
            logger.error("Failed to register %s: %s", version, e)
            return False
    
    def delete_version(self, version: str) -> bool:
        """Delete a model version (not active or rollback)."""
        if version in ("active", "rollback"):
            logger.error("Cannot delete %s", version)
            return False
        
        version_dir = self._models_dir / version
        
        if not version_dir.exists():
            logger.warning("Version not found: %s", version)
            return False
        
        # Check if it's the active version
        if version == self._get_active_version_name():
            logger.error("Cannot delete active version")
            return False
        
        try:
            shutil.rmtree(version_dir)
            logger.info("Deleted version %s", version)
            return True
        except Exception as e:
            logger.error("Failed to delete %s: %s", version, e)
            return False
    
    def compare_versions(
        self,
        version_a: str,
        version_b: str,
    ) -> Dict[str, Any]:
        """Compare two model versions."""
        a = self.get_version(version_a)
        b = self.get_version(version_b)
        
        if not a or not b:
            return {"error": "Version not found"}
        
        return {
            "version_a": version_a,
            "version_b": version_b,
            "accuracy_delta": a.accuracy - b.accuracy,
            "f1_delta": a.f1 - b.f1,
            "winner": version_a if a.f1 >= b.f1 else version_b,
            "details": {
                version_a: a.to_dict(),
                version_b: b.to_dict(),
            },
        }
    
    def _load_version_info(self, version_dir: Path) -> Optional[ModelVersion]:
        """Load version info from directory."""
        metrics_path = version_dir / "metrics.json"
        fingerprint_path = version_dir / "fingerprint.json"
        
        if not metrics_path.exists():
            return None
        
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                metrics = json.load(f)
            
            fingerprint_hash = ""
            if fingerprint_path.exists():
                with open(fingerprint_path, "r", encoding="utf-8") as f:
                    fingerprint = json.load(f)
                    fingerprint_hash = fingerprint.get("hash", "")
            
            return ModelVersion(
                version=version_dir.name,
                accuracy=metrics.get("accuracy", 0),
                f1=metrics.get("f1", 0),
                precision=metrics.get("precision", 0),
                recall=metrics.get("recall", 0),
                model_type=metrics.get("model_type", "unknown"),
                run_id=metrics.get("run_id", ""),
                dataset_hash=fingerprint_hash,
                created_at=metrics.get("timestamp", ""),
            )
        except Exception as e:
            logger.warning("Failed to load version info from %s: %s", version_dir, e)
            return None
    
    def _get_active_version_name(self) -> Optional[str]:
        """Get the name of the active version."""
        marker_path = self._models_dir / "active" / ".version"
        
        if marker_path.exists():
            return marker_path.read_text().strip()
        
        # Fallback: check metrics
        metrics_path = self._models_dir / "active" / "metrics.json"
        if metrics_path.exists():
            try:
                with open(metrics_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("version", "active")
            except Exception:
                pass
        
        return None
    
    def _get_rollback_version_name(self) -> Optional[str]:
        """Get the name of the rollback version."""
        marker_path = self._models_dir / "rollback" / ".version"
        
        if marker_path.exists():
            return marker_path.read_text().strip()
        
        return None
    
    def _write_version_marker(self, dir_path: Path, version: str) -> None:
        """Write version marker file."""
        marker_path = dir_path / ".version"
        marker_path.write_text(version)

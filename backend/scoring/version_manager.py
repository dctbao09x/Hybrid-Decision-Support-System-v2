# backend/scoring/version_manager.py
"""
Config Version Manager

Manages versioned configurations for SIMGR scoring system.
Supports:
- Version tracking
- Rollback capability
- Audit trail
- A/B testing configurations
"""

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ConfigVersion:
    """Represents a versioned configuration."""
    version: str
    created_at: str
    weights: Dict[str, float]
    metrics: Dict[str, float]
    source: str
    description: str = ""


class ConfigVersionManager:
    """Manages versioned SIMGR configurations."""
    
    def __init__(self, base_dir: str = "models/weights"):
        self.base_dir = Path(base_dir)
        self.active_dir = self.base_dir / "active"
        self._ensure_dirs()
    
    def _ensure_dirs(self) -> None:
        """Ensure required directories exist."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.active_dir.mkdir(parents=True, exist_ok=True)
    
    def list_versions(self) -> List[str]:
        """List all available config versions."""
        versions = []
        for item in self.base_dir.iterdir():
            if item.is_dir() and item.name != "active":
                weights_file = item / "weights.json"
                if weights_file.exists():
                    versions.append(item.name)
        return sorted(versions)
    
    def get_version(self, version: str) -> Optional[ConfigVersion]:
        """Get a specific config version."""
        version_dir = self.base_dir / version
        weights_file = version_dir / "weights.json"
        
        if not weights_file.exists():
            return None
        
        try:
            with open(weights_file, "r") as f:
                data = json.load(f)
            
            return ConfigVersion(
                version=data.get("version", version),
                created_at=data.get("created_at", ""),
                weights=data.get("weights", {}),
                metrics=data.get("metrics", {}),
                source=data.get("config", {}).get("method", "unknown"),
                description=data.get("description", ""),
            )
        except Exception as e:
            logger.error(f"Failed to load version {version}: {e}")
            return None
    
    def get_active(self) -> Optional[ConfigVersion]:
        """Get current active configuration."""
        weights_file = self.active_dir / "weights.json"
        
        if not weights_file.exists():
            return None
        
        try:
            with open(weights_file, "r") as f:
                data = json.load(f)
            
            return ConfigVersion(
                version=data.get("version", "active"),
                created_at=data.get("created_at", ""),
                weights=data.get("weights", {}),
                metrics=data.get("metrics", {}),
                source=data.get("config", {}).get("method", "unknown"),
                description=data.get("description", ""),
            )
        except Exception as e:
            logger.error(f"Failed to load active config: {e}")
            return None
    
    def activate(self, version: str) -> bool:
        """Activate a specific version.
        
        Copies version weights to active directory.
        """
        version_dir = self.base_dir / version
        weights_file = version_dir / "weights.json"
        
        if not weights_file.exists():
            logger.error(f"Version {version} not found")
            return False
        
        try:
            # Backup current active
            self._backup_active()
            
            # Copy to active
            active_file = self.active_dir / "weights.json"
            shutil.copy(weights_file, active_file)
            
            logger.info(f"Activated version {version}")
            return True
        except Exception as e:
            logger.error(f"Failed to activate version {version}: {e}")
            return False
    
    def _backup_active(self) -> None:
        """Backup current active config before replacement."""
        active_file = self.active_dir / "weights.json"
        if active_file.exists():
            backup_name = f"weights.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            backup_file = self.active_dir / backup_name
            shutil.copy(active_file, backup_file)
            logger.info(f"Backed up active config to {backup_name}")
    
    def create_version(
        self,
        version: str,
        weights: Dict[str, float],
        metrics: Dict[str, float] = None,
        source: str = "manual",
        description: str = "",
    ) -> bool:
        """Create a new version."""
        version_dir = self.base_dir / version
        version_dir.mkdir(parents=True, exist_ok=True)
        
        payload = {
            "version": version,
            "created_at": datetime.utcnow().isoformat(),
            "weights": weights,
            "metrics": metrics or {},
            "config": {
                "method": source,
            },
            "description": description,
        }
        
        try:
            weights_file = version_dir / "weights.json"
            with open(weights_file, "w") as f:
                json.dump(payload, f, indent=2)
            
            logger.info(f"Created version {version}")
            return True
        except Exception as e:
            logger.error(f"Failed to create version {version}: {e}")
            return False
    
    def rollback(self) -> bool:
        """Rollback to most recent backup."""
        backups = sorted([
            f.name for f in self.active_dir.iterdir()
            if f.name.startswith("weights.backup.")
        ], reverse=True)
        
        if not backups:
            logger.warning("No backups available for rollback")
            return False
        
        latest_backup = self.active_dir / backups[0]
        active_file = self.active_dir / "weights.json"
        
        try:
            shutil.copy(latest_backup, active_file)
            logger.info(f"Rolled back to {backups[0]}")
            return True
        except Exception as e:
            logger.error(f"Failed to rollback: {e}")
            return False
    
    def compare_versions(
        self, v1: str, v2: str
    ) -> Optional[Dict[str, Dict[str, float]]]:
        """Compare two versions."""
        cfg1 = self.get_version(v1)
        cfg2 = self.get_version(v2)
        
        if not cfg1 or not cfg2:
            return None
        
        comparison = {}
        all_keys = set(cfg1.weights.keys()) | set(cfg2.weights.keys())
        
        for key in all_keys:
            w1 = cfg1.weights.get(key, 0)
            w2 = cfg2.weights.get(key, 0)
            comparison[key] = {
                v1: w1,
                v2: w2,
                "diff": round(w2 - w1, 4),
            }
        
        return comparison


# Singleton instance
_version_manager: Optional[ConfigVersionManager] = None


def get_version_manager() -> ConfigVersionManager:
    """Get singleton version manager instance."""
    global _version_manager
    if _version_manager is None:
        _version_manager = ConfigVersionManager()
    return _version_manager

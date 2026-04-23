# backend/ops/versioning/config_version.py
"""
Configuration Versioning.

Tracks changes to pipeline configuration with:
- Git-like history
- Diff between versions
- Rollback capability
- Environment-specific overrides
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.versioning.config")


class ConfigVersionManager:
    """
    Manages versioned pipeline configurations.

    Storage layout:
        versions/
          configs/
            history.json
            v001.json
            v002.json
            ...
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path("backend/data/versions/configs")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_version(
        self,
        config: Dict[str, Any],
        description: str = "",
        author: str = "system",
    ) -> str:
        """Save a new config version."""
        content = json.dumps(config, sort_keys=True, indent=2)
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]

        # Check if identical to latest
        latest = self.get_latest()
        if latest and latest.get("content_hash") == content_hash:
            logger.info("Config unchanged, skipping version creation")
            return latest["version_id"]

        # Determine version
        history = self._load_history()
        next_num = len(history) + 1
        version_id = f"v{next_num:03d}"

        # Save config file
        config_path = self.base_dir / f"{version_id}.json"
        config_path.write_text(content)

        # Update history
        entry = {
            "version_id": version_id,
            "content_hash": content_hash,
            "description": description,
            "author": author,
            "created_at": datetime.now().isoformat(),
        }
        history.append(entry)
        self._save_history(history)

        logger.info(f"Config version saved: {version_id} ({description})")
        return version_id

    def get_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        """Load a specific config version."""
        config_path = self.base_dir / f"{version_id}.json"
        if not config_path.exists():
            return None
        return json.loads(config_path.read_text())

    def get_latest(self) -> Optional[Dict[str, Any]]:
        """Get the latest config version metadata."""
        history = self._load_history()
        return history[-1] if history else None

    def get_latest_config(self) -> Optional[Dict[str, Any]]:
        """Get the latest config content."""
        latest = self.get_latest()
        if not latest:
            return None
        return self.get_version(latest["version_id"])

    def diff(
        self, version_a: str, version_b: str
    ) -> Dict[str, Any]:
        """Diff two config versions."""
        config_a = self.get_version(version_a) or {}
        config_b = self.get_version(version_b) or {}

        added = {k: config_b[k] for k in config_b if k not in config_a}
        removed = {k: config_a[k] for k in config_a if k not in config_b}
        changed = {
            k: {"old": config_a[k], "new": config_b[k]}
            for k in config_a
            if k in config_b and config_a[k] != config_b[k]
        }

        return {
            "version_a": version_a,
            "version_b": version_b,
            "added": added,
            "removed": removed,
            "changed": changed,
            "is_different": bool(added or removed or changed),
        }

    def list_versions(self) -> List[Dict[str, Any]]:
        """List all config versions."""
        return self._load_history()

    def rollback_to(self, version_id: str) -> Optional[Dict[str, Any]]:
        """Create a new version that is a copy of a previous version."""
        config = self.get_version(version_id)
        if not config:
            return None

        new_id = self.save_version(
            config, description=f"Rollback to {version_id}"
        )
        return {"new_version": new_id, "rolled_back_to": version_id}

    def _load_history(self) -> List[Dict[str, Any]]:
        path = self.base_dir / "history.json"
        if not path.exists():
            return []
        return json.loads(path.read_text())

    def _save_history(self, history: List[Dict[str, Any]]) -> None:
        path = self.base_dir / "history.json"
        path.write_text(json.dumps(history, indent=2))

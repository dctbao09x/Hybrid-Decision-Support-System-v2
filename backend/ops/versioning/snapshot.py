# backend/ops/versioning/snapshot.py
"""
Pipeline Snapshot Manager.

Creates complete snapshots of pipeline state including:
- Dataset versions
- Config versions
- Code version (git hash)
- Environment info
- Dependency versions
"""

from __future__ import annotations

import json
import logging
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.versioning.snapshot")


class PipelineSnapshotManager:
    """
    Creates and manages pipeline state snapshots for reproducibility.

    A snapshot captures:
    - Git commit hash
    - Python version and dependencies
    - Pipeline config
    - Dataset version references
    - System info
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path("backend/data/versions/snapshots")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_snapshot(
        self,
        run_id: str,
        config: Optional[Dict[str, Any]] = None,
        dataset_versions: Optional[Dict[str, str]] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a complete pipeline snapshot."""
        snapshot = {
            "snapshot_id": f"snap_{run_id}",
            "run_id": run_id,
            "created_at": datetime.now().isoformat(),
            "git": self._get_git_info(),
            "python": {
                "version": sys.version,
                "executable": sys.executable,
                "platform": platform.platform(),
            },
            "dependencies": self._get_dependencies(),
            "config": config or {},
            "dataset_versions": dataset_versions or {},
            "system": {
                "os": platform.system(),
                "arch": platform.machine(),
                "hostname": platform.node(),
            },
            "metadata": extra_metadata or {},
        }

        # Save snapshot
        snap_path = self.base_dir / f"{snapshot['snapshot_id']}.json"
        snap_path.write_text(json.dumps(snapshot, indent=2, default=str))

        logger.info(f"Pipeline snapshot created: {snapshot['snapshot_id']}")
        return snapshot

    def load_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        """Load a pipeline snapshot."""
        snap_path = self.base_dir / f"{snapshot_id}.json"
        if not snap_path.exists():
            # Try with prefix
            snap_path = self.base_dir / f"snap_{snapshot_id}.json"
        if not snap_path.exists():
            return None
        return json.loads(snap_path.read_text())

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """List all snapshots (summary only)."""
        snapshots = []
        for f in sorted(self.base_dir.glob("snap_*.json"), reverse=True):
            try:
                data = json.loads(f.read_text())
                snapshots.append({
                    "snapshot_id": data.get("snapshot_id"),
                    "run_id": data.get("run_id"),
                    "created_at": data.get("created_at"),
                    "git_hash": data.get("git", {}).get("commit_hash", "unknown"),
                })
            except Exception:
                continue
        return snapshots

    def compare_snapshots(
        self, snap_a: str, snap_b: str
    ) -> Dict[str, Any]:
        """Compare two snapshots to identify differences."""
        a = self.load_snapshot(snap_a) or {}
        b = self.load_snapshot(snap_b) or {}

        diff = {}

        # Git diff
        git_a = a.get("git", {}).get("commit_hash", "")
        git_b = b.get("git", {}).get("commit_hash", "")
        if git_a != git_b:
            diff["git"] = {"a": git_a[:8], "b": git_b[:8]}

        # Python version diff
        py_a = a.get("python", {}).get("version", "")
        py_b = b.get("python", {}).get("version", "")
        if py_a != py_b:
            diff["python_version"] = {"a": py_a, "b": py_b}

        # Config diff
        conf_a = a.get("config", {})
        conf_b = b.get("config", {})
        config_changes = {
            k: {"a": conf_a.get(k), "b": conf_b.get(k)}
            for k in set(list(conf_a.keys()) + list(conf_b.keys()))
            if conf_a.get(k) != conf_b.get(k)
        }
        if config_changes:
            diff["config"] = config_changes

        # Dependency diff
        deps_a = a.get("dependencies", {})
        deps_b = b.get("dependencies", {})
        dep_changes = {
            k: {"a": deps_a.get(k), "b": deps_b.get(k)}
            for k in set(list(deps_a.keys()) + list(deps_b.keys()))
            if deps_a.get(k) != deps_b.get(k)
        }
        if dep_changes:
            diff["dependencies"] = dep_changes

        return {
            "snapshot_a": snap_a,
            "snapshot_b": snap_b,
            "differences": diff,
            "identical": len(diff) == 0,
        }

    def _get_git_info(self) -> Dict[str, str]:
        """Get current git commit info."""
        try:
            commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                stderr=subprocess.DEVNULL, timeout=5,
            ).decode().strip()
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL, timeout=5
            ).decode().strip()
            dirty = subprocess.call(
                ["git", "diff", "--quiet"],
                stderr=subprocess.DEVNULL, timeout=5,
            ) != 0
            return {
                "commit_hash": commit,
                "branch": branch,
                "dirty": dirty,
            }
        except Exception:
            return {"commit_hash": "unknown", "branch": "unknown", "dirty": False}

    def _get_dependencies(self) -> Dict[str, str]:
        """Get installed Python packages."""
        try:
            result = subprocess.check_output(
                [sys.executable, "-m", "pip", "list", "--format=json"],
                stderr=subprocess.DEVNULL, timeout=30,
            ).decode()
            packages = json.loads(result)
            return {p["name"]: p["version"] for p in packages}
        except Exception:
            return {}

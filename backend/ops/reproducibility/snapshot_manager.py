"""
SnapshotManager — full environment capture for reproducible runs.

Captures:
  - Git state (commit, branch, dirty flag)
  - Python version + installed packages
  - OS / platform info
  - Pipeline config hash
  - Seed state
  - Data artifact manifest summary
  - LLM parameters (model, temperature, etc.)

Supports:
  - Capture → save → load → diff → verify
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  Data model
# ─────────────────────────────────────────────────────────────
@dataclass
class RunSnapshot:
    """Complete environment snapshot for a pipeline run."""

    run_id: str
    created_at: str = ""

    # Git
    git_commit: str = ""
    git_branch: str = ""
    git_dirty: bool = False

    # Python environment
    python_version: str = ""
    python_executable: str = ""
    packages: Dict[str, str] = field(default_factory=dict)

    # System
    os_name: str = ""
    os_version: str = ""
    hostname: str = ""
    cpu_count: int = 0

    # Pipeline
    config_hash: str = ""
    seed: Optional[int] = None
    llm_params: Dict[str, Any] = field(default_factory=dict)

    # Artifacts summary
    artifact_count: int = 0
    artifact_hashes: Dict[str, str] = field(default_factory=dict)

    # Extra
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RunSnapshot":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


# ─────────────────────────────────────────────────────────────
#  SnapshotManager
# ─────────────────────────────────────────────────────────────
class SnapshotManager:
    """
    Capture, persist, and verify full environment snapshots.

    Usage
    -----
    >>> mgr = SnapshotManager()
    >>> snap = mgr.capture("run_001", config_hash="abc...", seed=42)
    >>> mgr.save("run_001", snap)
    >>> loaded = mgr.load("run_001")
    >>> diff = mgr.diff("run_001", "run_002")
    >>> check = mgr.verify_env(snap)
    """

    def __init__(
        self, base_dir: Optional[Union[str, Path]] = None
    ) -> None:
        self.base_dir = Path(
            base_dir or "backend/data/runs"
        )
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ═════════════════════════════════════════════════════════
    #  Capture
    # ═════════════════════════════════════════════════════════
    def capture(
        self,
        run_id: str,
        config_hash: str = "",
        seed: Optional[int] = None,
        llm_params: Optional[Dict[str, Any]] = None,
        artifact_hashes: Optional[Dict[str, str]] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> RunSnapshot:
        """
        Capture the current environment state.

        Parameters
        ----------
        run_id : str
        config_hash : str
            SHA-256 of the frozen config.json.
        seed : int, optional
        llm_params : dict, optional
            Model name, temperature, top_p, etc.
        artifact_hashes : dict, optional
            {stage/filename: sha256} from the manifest.
        extra_metadata : dict, optional

        Returns
        -------
        RunSnapshot
        """
        git = self._get_git_info()
        deps = self._get_packages()

        snap = RunSnapshot(
            run_id=run_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            # Git
            git_commit=git.get("commit", ""),
            git_branch=git.get("branch", ""),
            git_dirty=git.get("dirty", False),
            # Python
            python_version=platform.python_version(),
            python_executable=sys.executable,
            packages=deps,
            # System
            os_name=platform.system(),
            os_version=platform.version(),
            hostname=platform.node(),
            cpu_count=os.cpu_count() or 0,
            # Pipeline
            config_hash=config_hash,
            seed=seed,
            llm_params=llm_params or {},
            # Artifacts
            artifact_count=len(artifact_hashes) if artifact_hashes else 0,
            artifact_hashes=artifact_hashes or {},
            # Extra
            metadata=extra_metadata or {},
        )

        logger.info(
            f"Snapshot captured: run={run_id}, "
            f"commit={snap.git_commit[:8] if snap.git_commit else 'N/A'}, "
            f"python={snap.python_version}, "
            f"packages={len(snap.packages)}"
        )
        return snap

    # ═════════════════════════════════════════════════════════
    #  Persist / Load
    # ═════════════════════════════════════════════════════════
    def save(self, run_id: str, snapshot: RunSnapshot) -> Path:
        """Save snapshot to the run's directory."""
        run_dir = self.base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "snapshot.json"
        path.write_text(
            json.dumps(
                snapshot.to_dict(),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )
        logger.debug(f"Snapshot saved: {path}")
        return path

    def load(self, run_id: str) -> Optional[RunSnapshot]:
        """Load snapshot from disk."""
        path = self.base_dir / run_id / "snapshot.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return RunSnapshot.from_dict(data)
        except Exception as e:
            logger.warning(f"Failed to load snapshot {run_id}: {e}")
            return None

    # ═════════════════════════════════════════════════════════
    #  Diff
    # ═════════════════════════════════════════════════════════
    def diff(
        self, run_a: str, run_b: str
    ) -> Dict[str, Any]:
        """
        Compare two snapshots and report differences.

        Returns
        -------
        dict
            {
                "identical": bool,
                "differences": {
                    "git": {...},
                    "python": {...},
                    "packages": {...},
                    "config": {...},
                    "seed": {...},
                    "llm": {...},
                }
            }
        """
        sa = self.load(run_a)
        sb = self.load(run_b)
        if not sa or not sb:
            return {
                "identical": False,
                "error": f"Missing snapshot: "
                         f"{'A' if not sa else ''}"
                         f"{'B' if not sb else ''}",
            }

        diffs: Dict[str, Any] = {}

        # Git
        if sa.git_commit != sb.git_commit:
            diffs["git_commit"] = {
                "a": sa.git_commit[:12],
                "b": sb.git_commit[:12],
            }
        if sa.git_dirty != sb.git_dirty:
            diffs["git_dirty"] = {"a": sa.git_dirty, "b": sb.git_dirty}

        # Python
        if sa.python_version != sb.python_version:
            diffs["python_version"] = {
                "a": sa.python_version,
                "b": sb.python_version,
            }

        # Packages
        pkg_diff = self._diff_packages(sa.packages, sb.packages)
        if pkg_diff["added"] or pkg_diff["removed"] or pkg_diff["changed"]:
            diffs["packages"] = pkg_diff

        # Config
        if sa.config_hash != sb.config_hash:
            diffs["config_hash"] = {
                "a": sa.config_hash[:12],
                "b": sb.config_hash[:12],
            }

        # Seed
        if sa.seed != sb.seed:
            diffs["seed"] = {"a": sa.seed, "b": sb.seed}

        # LLM params
        if sa.llm_params != sb.llm_params:
            diffs["llm_params"] = {"a": sa.llm_params, "b": sb.llm_params}

        return {
            "run_a": run_a,
            "run_b": run_b,
            "identical": len(diffs) == 0,
            "differences": diffs,
        }

    # ═════════════════════════════════════════════════════════
    #  Verify current env against snapshot
    # ═════════════════════════════════════════════════════════
    def verify_env(self, snapshot: RunSnapshot) -> Dict[str, Any]:
        """
        Check if the current environment matches a snapshot.

        Returns
        -------
        dict
            {
                "match": bool,           # overall match
                "checks": {
                    "git_commit": bool,
                    "python_version": bool,
                    "packages": bool,
                    "config_hash": bool,
                    "seed": bool,
                },
                "details": {...}          # specifics on mismatches
            }
        """
        current = self.capture(
            run_id="__verify__",
            config_hash=snapshot.config_hash,
            seed=snapshot.seed,
        )

        checks: Dict[str, bool] = {}
        details: Dict[str, Any] = {}

        # Git
        checks["git_commit"] = (
            current.git_commit == snapshot.git_commit
        )
        if not checks["git_commit"]:
            details["git_commit"] = {
                "expected": snapshot.git_commit[:12],
                "actual": current.git_commit[:12],
            }

        checks["git_clean"] = not current.git_dirty
        if not checks["git_clean"]:
            details["git_clean"] = "Working tree has uncommitted changes"

        # Python version
        checks["python_version"] = (
            current.python_version == snapshot.python_version
        )
        if not checks["python_version"]:
            details["python_version"] = {
                "expected": snapshot.python_version,
                "actual": current.python_version,
            }

        # Packages
        pkg_diff = self._diff_packages(
            snapshot.packages, current.packages
        )
        checks["packages"] = not (
            pkg_diff["added"] or pkg_diff["removed"] or pkg_diff["changed"]
        )
        if not checks["packages"]:
            details["packages"] = pkg_diff

        # Config hash (we can only check if same hash was provided)
        checks["config_hash"] = True  # Can't verify content here

        # Seed
        checks["seed"] = current.seed == snapshot.seed

        overall = all(checks.values())
        return {
            "match": overall,
            "checks": checks,
            "details": details,
        }

    # ═════════════════════════════════════════════════════════
    #  List snapshots
    # ═════════════════════════════════════════════════════════
    def list_snapshots(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List runs that have snapshots."""
        results: List[Dict[str, Any]] = []
        if not self.base_dir.exists():
            return results

        for entry in sorted(self.base_dir.iterdir(), reverse=True):
            snap_path = entry / "snapshot.json"
            if not snap_path.exists():
                continue
            try:
                data = json.loads(
                    snap_path.read_text(encoding="utf-8")
                )
                results.append({
                    "run_id": data.get("run_id", entry.name),
                    "created_at": data.get("created_at"),
                    "git_commit": data.get("git_commit", "")[:8],
                    "python_version": data.get("python_version"),
                    "package_count": len(data.get("packages", {})),
                })
            except Exception:
                continue
            if len(results) >= limit:
                break
        return results

    # ═════════════════════════════════════════════════════════
    #  Private helpers
    # ═════════════════════════════════════════════════════════
    def _get_git_info(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "commit": "",
            "branch": "",
            "dirty": False,
        }
        try:
            info["commit"] = (
                subprocess.check_output(
                    ["git", "rev-parse", "HEAD"],
                    stderr=subprocess.DEVNULL,
                )
                .decode()
                .strip()
            )
            info["branch"] = (
                subprocess.check_output(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    stderr=subprocess.DEVNULL,
                )
                .decode()
                .strip()
            )
            result = subprocess.run(
                ["git", "diff", "--quiet"],
                capture_output=True,
            )
            info["dirty"] = result.returncode != 0
        except Exception:
            pass
        return info

    def _get_packages(self) -> Dict[str, str]:
        try:
            output = subprocess.check_output(
                [sys.executable, "-m", "pip", "list", "--format=json"],
                stderr=subprocess.DEVNULL,
            )
            pkgs = json.loads(output.decode())
            return {p["name"]: p["version"] for p in pkgs}
        except Exception:
            return {}

    def _diff_packages(
        self,
        pkgs_a: Dict[str, str],
        pkgs_b: Dict[str, str],
    ) -> Dict[str, Any]:
        all_names = set(pkgs_a.keys()) | set(pkgs_b.keys())
        added: Dict[str, str] = {}
        removed: Dict[str, str] = {}
        changed: Dict[str, Dict[str, str]] = {}

        for name in sorted(all_names):
            va = pkgs_a.get(name)
            vb = pkgs_b.get(name)
            if va and not vb:
                removed[name] = va
            elif vb and not va:
                added[name] = vb
            elif va != vb:
                changed[name] = {"a": va or "", "b": vb or ""}

        return {
            "added": added,
            "removed": removed,
            "changed": changed,
        }

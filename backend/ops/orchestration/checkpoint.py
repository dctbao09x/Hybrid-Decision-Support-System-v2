# backend/ops/orchestration/checkpoint.py
"""
Checkpoint Manager for pipeline state persistence and recovery.

Saves intermediate state between pipeline stages so that:
- Failed runs can resume from last successful stage
- Partial rollback is possible
- Reproducibility is guaranteed
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.checkpoint")

CHECKPOINT_DIR = Path("backend/data/checkpoints")


class CheckpointManager:
    """
    Manages pipeline checkpoints for recovery and rollback.

    Directory layout:
        checkpoints/
          {run_id}/
            manifest.json          # Run metadata
            crawl.json             # Stage checkpoint
            crawl_data/            # Stage artifact directory
            validate.json
            score.json
            explain.json
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or CHECKPOINT_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ── Save / Load ─────────────────────────────────────────

    async def save(
        self,
        run_id: str,
        stage_name: str,
        stage_result: Any,
        artifacts: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """Save checkpoint for a pipeline stage."""
        run_dir = self.base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        checkpoint = {
            "run_id": run_id,
            "stage": stage_name,
            "timestamp": datetime.now().isoformat(),
            "status": getattr(stage_result, "status", "unknown"),
            "records_in": getattr(stage_result, "records_in", 0),
            "records_out": getattr(stage_result, "records_out", 0),
            "duration_seconds": getattr(stage_result, "duration_seconds", 0),
            "error": getattr(stage_result, "error", None),
        }

        # Serialize status enum
        if hasattr(checkpoint["status"], "value"):
            checkpoint["status"] = checkpoint["status"].value

        cp_path = run_dir / f"{stage_name}.json"
        cp_path.write_text(json.dumps(checkpoint, indent=2, default=str))

        # Save artifacts
        if artifacts:
            art_dir = run_dir / f"{stage_name}_data"
            art_dir.mkdir(parents=True, exist_ok=True)
            for name, data in artifacts.items():
                art_path = art_dir / name
                if isinstance(data, (dict, list)):
                    art_path.with_suffix(".json").write_text(
                        json.dumps(data, indent=2, default=str)
                    )
                elif isinstance(data, bytes):
                    art_path.write_bytes(data)
                else:
                    art_path.write_text(str(data))

        # Update manifest
        await self._update_manifest(run_id, stage_name, checkpoint)
        logger.info(f"Checkpoint saved: {run_id}/{stage_name}")
        return cp_path

    async def load(
        self, run_id: str, stage_name: str
    ) -> Optional[Dict[str, Any]]:
        """Load checkpoint for a stage."""
        cp_path = self.base_dir / run_id / f"{stage_name}.json"
        if not cp_path.exists():
            return None
        return json.loads(cp_path.read_text())

    async def get_last_successful_stage(self, run_id: str) -> Optional[str]:
        """Find the last successful stage for a run."""
        manifest = await self._load_manifest(run_id)
        if not manifest:
            return None

        for stage in reversed(["crawl", "validate", "score", "explain"]):
            stage_info = manifest.get("stages", {}).get(stage)
            if stage_info and stage_info.get("status") == "success":
                return stage
        return None

    async def get_resume_point(self, run_id: str) -> Optional[str]:
        """Get the stage to resume from after a failure."""
        last_ok = await self.get_last_successful_stage(run_id)
        if not last_ok:
            return "crawl"

        stages = ["crawl", "validate", "score", "explain"]
        idx = stages.index(last_ok)
        if idx < len(stages) - 1:
            return stages[idx + 1]
        return None  # All stages completed

    # ── Manifest ────────────────────────────────────────────

    async def _update_manifest(
        self, run_id: str, stage_name: str, checkpoint: Dict
    ) -> None:
        manifest = await self._load_manifest(run_id) or {
            "run_id": run_id,
            "created_at": datetime.now().isoformat(),
            "stages": {},
        }
        manifest["stages"][stage_name] = {
            "status": checkpoint.get("status"),
            "timestamp": checkpoint.get("timestamp"),
            "records_out": checkpoint.get("records_out", 0),
        }
        manifest["updated_at"] = datetime.now().isoformat()

        manifest_path = self.base_dir / run_id / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))

    async def _load_manifest(self, run_id: str) -> Optional[Dict]:
        manifest_path = self.base_dir / run_id / "manifest.json"
        if not manifest_path.exists():
            return None
        return json.loads(manifest_path.read_text())

    # ── Cleanup ─────────────────────────────────────────────

    async def cleanup_old_checkpoints(self, keep_last: int = 20) -> int:
        """Remove old checkpoint directories, keeping the most recent N."""
        if not self.base_dir.exists():
            return 0

        runs = sorted(
            [d for d in self.base_dir.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
        )

        removed = 0
        while len(runs) > keep_last:
            old = runs.pop(0)
            shutil.rmtree(old, ignore_errors=True)
            removed += 1
            logger.info(f"Removed old checkpoint: {old.name}")

        return removed

    # ── Listing ─────────────────────────────────────────────

    async def list_runs(self) -> List[Dict[str, Any]]:
        """List all checkpoint runs."""
        runs = []
        if not self.base_dir.exists():
            return runs

        for d in sorted(self.base_dir.iterdir(), reverse=True):
            if d.is_dir():
                manifest = await self._load_manifest(d.name)
                if manifest:
                    runs.append(manifest)
        return runs

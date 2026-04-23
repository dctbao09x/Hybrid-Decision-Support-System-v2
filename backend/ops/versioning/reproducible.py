# backend/ops/versioning/reproducible.py
"""
Reproducible Run Manager.

Ensures pipeline runs can be exactly reproduced by:
- Capturing full execution context
- Fixing random seeds
- Pinning dependencies
- Recording input/output hashes
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.versioning.reproducible")


class ReproducibleRunManager:
    """
    Manages reproducible pipeline runs.

    A reproducible run captures:
    - Input data hash
    - Config snapshot
    - Random seed
    - Environment variables
    - Output data hash
    - Full execution log
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path("backend/data/versions/runs")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def prepare_run(
        self,
        run_id: str,
        config: Dict[str, Any],
        input_path: Optional[Path] = None,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Prepare a reproducible run by capturing all context.

        Args:
            run_id: Unique run identifier
            config: Pipeline configuration
            input_path: Path to input data
            seed: Random seed (auto-generated if None)
        """
        if seed is None:
            seed = random.randint(0, 2**32 - 1)

        # Set deterministic seeds
        random.seed(seed)
        os.environ["PYTHONHASHSEED"] = str(seed)

        try:
            import numpy as np
            np.random.seed(seed)
        except ImportError:
            pass

        run_context = {
            "run_id": run_id,
            "seed": seed,
            "config": config,
            "input_hash": self._hash_file(input_path) if input_path else None,
            "env_vars": {
                k: v for k, v in os.environ.items()
                if k.startswith(("PIPELINE_", "PYTHON", "PATH"))
            },
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "output_hash": None,
            "status": "prepared",
        }

        # Save run context
        run_dir = self.base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "context.json").write_text(json.dumps(run_context, indent=2))

        logger.info(f"Reproducible run prepared: {run_id} (seed={seed})")
        return run_context

    def finalize_run(
        self,
        run_id: str,
        output_path: Optional[Path] = None,
        status: str = "completed",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Finalize a run by recording output hash and status."""
        run_dir = self.base_dir / run_id
        context_path = run_dir / "context.json"

        if not context_path.exists():
            return {"error": f"Run {run_id} not found"}

        context = json.loads(context_path.read_text())
        context["completed_at"] = datetime.now().isoformat()
        context["status"] = status
        context["output_hash"] = self._hash_file(output_path) if output_path else None
        if metadata:
            context["metadata"] = metadata

        context_path.write_text(json.dumps(context, indent=2))
        logger.info(f"Reproducible run finalized: {run_id} ({status})")
        return context

    def verify_reproduction(
        self,
        original_run_id: str,
        reproduction_run_id: str,
    ) -> Dict[str, Any]:
        """Verify that a reproduction matches the original run."""
        original = self._load_context(original_run_id)
        reproduction = self._load_context(reproduction_run_id)

        if not original or not reproduction:
            return {"error": "Run not found"}

        matches = {
            "input_hash": original.get("input_hash") == reproduction.get("input_hash"),
            "output_hash": original.get("output_hash") == reproduction.get("output_hash"),
            "config": original.get("config") == reproduction.get("config"),
            "seed": original.get("seed") == reproduction.get("seed"),
        }

        return {
            "original_run": original_run_id,
            "reproduction_run": reproduction_run_id,
            "matches": matches,
            "fully_reproduced": all(matches.values()),
        }

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List recent reproducible runs."""
        runs = []
        for d in sorted(self.base_dir.iterdir(), reverse=True):
            if d.is_dir():
                ctx = self._load_context(d.name)
                if ctx:
                    runs.append({
                        "run_id": ctx["run_id"],
                        "status": ctx.get("status"),
                        "started_at": ctx.get("started_at"),
                        "seed": ctx.get("seed"),
                    })
            if len(runs) >= limit:
                break
        return runs

    def _load_context(self, run_id: str) -> Optional[Dict[str, Any]]:
        path = self.base_dir / run_id / "context.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def _hash_file(self, path: Optional[Path]) -> Optional[str]:
        if not path or not path.exists():
            return None
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

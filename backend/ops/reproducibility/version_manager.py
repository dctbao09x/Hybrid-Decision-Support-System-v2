"""
VersionManager — content-addressed artifact tree for reproducible runs.

Creates the canonical run artifact structure:

    backend/data/runs/{run_id}/
        ├── raw/              ← crawled data snapshots
        ├── clean/            ← validated + cleaned records
        ├── feature/          ← feature-engineered data
        ├── score/            ← scored output + explanations
        ├── config.json       ← frozen pipeline config (deterministic hash)
        ├── manifest.json     ← content-addressed index of ALL artifacts
        └── seed.json         ← seed state for replay

Every artifact is SHA-256 hashed.  Re-run + verify → ≥95% match.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

logger = logging.getLogger(__name__)

# Canonical stage sub-directories
STAGE_DIRS = ("raw", "clean", "feature", "score")


# ─────────────────────────────────────────────────────────────
#  Data models
# ─────────────────────────────────────────────────────────────
@dataclass
class Artifact:
    """A single versioned file within a run."""

    stage: str                     # raw | clean | feature | score
    filename: str                  # e.g. "jobs.csv"
    sha256: str                    # content hash
    size_bytes: int                # file size
    record_count: Optional[int]    # rows if tabular, else None
    created_at: str = ""           # ISO-8601 timestamp
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RunManifest:
    """
    Content-addressed index of every artifact produced in a pipeline run.

    The manifest is the *single source of truth* for reproducibility
    verification — if all artifact hashes match, the run is reproduced.
    """

    run_id: str
    config_hash: str                    # SHA-256 of frozen config.json
    seed: Optional[int] = None
    artifacts: List[Artifact] = field(default_factory=list)
    status: str = "running"             # running | completed | failed
    created_at: str = ""
    finalized_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ── Convenience ──────────────────────────────────────────

    @property
    def artifact_count(self) -> int:
        return len(self.artifacts)

    @property
    def total_size_bytes(self) -> int:
        return sum(a.size_bytes for a in self.artifacts)

    def artifacts_for_stage(self, stage: str) -> List[Artifact]:
        return [a for a in self.artifacts if a.stage == stage]

    # ── Serialization ────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["artifact_count"] = self.artifact_count
        d["total_size_bytes"] = self.total_size_bytes
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RunManifest":
        arts = [Artifact(**a) for a in d.get("artifacts", [])]
        return cls(
            run_id=d["run_id"],
            config_hash=d["config_hash"],
            seed=d.get("seed"),
            artifacts=arts,
            status=d.get("status", "unknown"),
            created_at=d.get("created_at", ""),
            finalized_at=d.get("finalized_at"),
            duration_seconds=d.get("duration_seconds"),
            metadata=d.get("metadata", {}),
        )


# ─────────────────────────────────────────────────────────────
#  VersionManager
# ─────────────────────────────────────────────────────────────
class VersionManager:
    """
    Manages a content-addressed artifact tree per pipeline run.

    Lifecycle
    ---------
    1. ``init_run(run_id, config)``  — create dirs, freeze config, set seed
    2. ``save_artifact(run_id, stage, data)``  — per-stage, returns Artifact
    3. ``finalize_run(run_id)``  — seal manifest
    4. ``verify_run(run_id)``  — re-hash everything, report mismatches
    5. ``compare_runs(a, b)``  — artifact-level diff
    """

    HASH_CHUNK = 8192  # bytes per read for streaming hash

    def __init__(
        self, base_dir: Optional[Union[str, Path]] = None
    ) -> None:
        self.base_dir = Path(
            base_dir or "backend/data/runs"
        )
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._manifests: Dict[str, RunManifest] = {}  # in-memory cache
        logger.debug(f"VersionManager base_dir={self.base_dir}")

    # ═════════════════════════════════════════════════════════
    #  1. Init run
    # ═════════════════════════════════════════════════════════
    def init_run(
        self,
        run_id: str,
        config: Dict[str, Any],
        seed: Optional[int] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> RunManifest:
        """
        Create the run directory tree and freeze configuration.

        Parameters
        ----------
        run_id : str
            Unique run identifier.
        config : dict
            Pipeline configuration (will be frozen as config.json).
        seed : int, optional
            Random seed used for this run.
        extra_metadata : dict, optional
            Additional context to attach to the manifest.

        Returns
        -------
        RunManifest
            Initial manifest with no artifacts yet.
        """
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        # Create stage sub-directories
        for stage in STAGE_DIRS:
            (run_dir / stage).mkdir(exist_ok=True)

        # Freeze config.json  (deterministic serialization)
        config_json = self._deterministic_json(config)
        config_hash = self._hash_bytes(config_json.encode("utf-8"))
        config_path = run_dir / "config.json"
        config_path.write_text(config_json, encoding="utf-8")

        # Save seed state
        if seed is not None:
            seed_path = run_dir / "seed.json"
            seed_path.write_text(
                json.dumps({"seed": seed, "run_id": run_id}, indent=2),
                encoding="utf-8",
            )

        now = datetime.now(timezone.utc).isoformat()
        manifest = RunManifest(
            run_id=run_id,
            config_hash=config_hash,
            seed=seed,
            status="running",
            created_at=now,
            metadata=extra_metadata or {},
        )
        self._manifests[run_id] = manifest
        self._save_manifest(run_id, manifest)

        logger.info(
            f"Run {run_id} initialized: "
            f"config_hash={config_hash[:12]}, seed={seed}"
        )
        return manifest

    # ═════════════════════════════════════════════════════════
    #  2. Save artifact
    # ═════════════════════════════════════════════════════════
    def save_artifact(
        self,
        run_id: str,
        stage: str,
        data: Any,
        filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Artifact:
        """
        Persist data to the run's stage directory and add to manifest.

        Parameters
        ----------
        run_id : str
        stage : str
            One of "raw", "clean", "feature", "score".
        data : Any
            - List[dict] → saved as CSV
            - dict        → saved as JSON
            - str / bytes → saved as-is
            - Path        → copied into the artifact tree
        filename : str, optional
            Override the default filename.
        metadata : dict, optional
            Extra info to attach to this artifact.

        Returns
        -------
        Artifact
            With sha256 hash, size, record count.
        """
        stage_dir = self._run_dir(run_id) / stage
        stage_dir.mkdir(parents=True, exist_ok=True)

        # ── Determine filename and write ──
        written_path, record_count = self._write_data(
            stage_dir, data, filename, stage
        )

        # ── Hash + size ──
        sha = self._hash_file(written_path)
        size = written_path.stat().st_size

        artifact = Artifact(
            stage=stage,
            filename=written_path.name,
            sha256=sha,
            size_bytes=size,
            record_count=record_count,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata or {},
        )

        # ── Append to manifest ──
        manifest = self._get_or_load_manifest(run_id)
        manifest.artifacts.append(artifact)
        self._save_manifest(run_id, manifest)

        logger.debug(
            f"Artifact saved: {run_id}/{stage}/{written_path.name} "
            f"sha256={sha[:12]} size={size}"
        )
        return artifact

    # ═════════════════════════════════════════════════════════
    #  3. Finalize run
    # ═════════════════════════════════════════════════════════
    def finalize_run(
        self,
        run_id: str,
        status: str = "completed",
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> RunManifest:
        """
        Seal the manifest — no more artifacts should be added.

        Parameters
        ----------
        run_id : str
        status : str
            "completed" or "failed".
        extra_metadata : dict, optional

        Returns
        -------
        RunManifest
            Finalized manifest with duration and status.
        """
        manifest = self._get_or_load_manifest(run_id)
        now = datetime.now(timezone.utc).isoformat()
        manifest.status = status
        manifest.finalized_at = now

        # Compute duration
        try:
            t0 = datetime.fromisoformat(manifest.created_at)
            t1 = datetime.fromisoformat(now)
            manifest.duration_seconds = round(
                (t1 - t0).total_seconds(), 3
            )
        except (ValueError, TypeError):
            manifest.duration_seconds = None

        if extra_metadata:
            manifest.metadata.update(extra_metadata)

        self._save_manifest(run_id, manifest)
        logger.info(
            f"Run {run_id} finalized: status={status}, "
            f"artifacts={manifest.artifact_count}, "
            f"duration={manifest.duration_seconds}s"
        )
        return manifest

    # ═════════════════════════════════════════════════════════
    #  4. Verify run  (re-hash everything)
    # ═════════════════════════════════════════════════════════
    def verify_run(self, run_id: str) -> Dict[str, Any]:
        """
        Re-hash every artifact and compare to manifest.

        Returns
        -------
        dict
            {
                "run_id": str,
                "verified": bool,
                "total_artifacts": int,
                "matched": int,
                "mismatched": int,
                "missing": int,
                "details": [...]
            }
        """
        manifest = self._get_or_load_manifest(run_id)
        run_dir = self._run_dir(run_id)

        matched = 0
        mismatched = 0
        missing = 0
        details: List[Dict[str, Any]] = []

        for art in manifest.artifacts:
            fpath = run_dir / art.stage / art.filename
            if not fpath.exists():
                missing += 1
                details.append({
                    "artifact": f"{art.stage}/{art.filename}",
                    "status": "missing",
                    "expected_hash": art.sha256,
                })
                continue

            current_hash = self._hash_file(fpath)
            if current_hash == art.sha256:
                matched += 1
                details.append({
                    "artifact": f"{art.stage}/{art.filename}",
                    "status": "ok",
                    "hash": current_hash[:12],
                })
            else:
                mismatched += 1
                details.append({
                    "artifact": f"{art.stage}/{art.filename}",
                    "status": "hash_mismatch",
                    "expected": art.sha256[:12],
                    "actual": current_hash[:12],
                })

        total = len(manifest.artifacts)
        verified = mismatched == 0 and missing == 0 and total > 0

        # Config hash verification
        config_path = run_dir / "config.json"
        config_ok = False
        if config_path.exists():
            cfg_hash = self._hash_file(config_path)
            config_ok = cfg_hash == manifest.config_hash

        result = {
            "run_id": run_id,
            "verified": verified and config_ok,
            "config_hash_ok": config_ok,
            "total_artifacts": total,
            "matched": matched,
            "mismatched": mismatched,
            "missing": missing,
            "match_rate": matched / max(total, 1),
            "details": details,
        }
        logger.info(
            f"Verify {run_id}: verified={result['verified']}, "
            f"matched={matched}/{total}"
        )
        return result

    # ═════════════════════════════════════════════════════════
    #  5. Compare runs
    # ═════════════════════════════════════════════════════════
    def compare_runs(
        self, run_a: str, run_b: str
    ) -> Dict[str, Any]:
        """
        Compare two runs artifact-by-artifact.

        Returns
        -------
        dict
            {
                "reproduced": bool,     # True if ≥95% match
                "match_rate": float,
                "config_match": bool,
                "seed_match": bool,
                "artifact_comparison": [...]
            }
        """
        ma = self._get_or_load_manifest(run_a)
        mb = self._get_or_load_manifest(run_b)

        config_match = ma.config_hash == mb.config_hash
        seed_match = ma.seed == mb.seed

        # Index artifacts by (stage, filename)
        idx_a = {(a.stage, a.filename): a for a in ma.artifacts}
        idx_b = {(a.stage, a.filename): a for a in mb.artifacts}

        all_keys = sorted(set(idx_a.keys()) | set(idx_b.keys()))
        comparisons: List[Dict[str, Any]] = []
        matched = 0

        for key in all_keys:
            art_a = idx_a.get(key)
            art_b = idx_b.get(key)

            if art_a and art_b:
                hash_match = art_a.sha256 == art_b.sha256
                if hash_match:
                    matched += 1
                comparisons.append({
                    "artifact": f"{key[0]}/{key[1]}",
                    "hash_match": hash_match,
                    "hash_a": art_a.sha256[:12],
                    "hash_b": art_b.sha256[:12],
                    "size_a": art_a.size_bytes,
                    "size_b": art_b.size_bytes,
                })
            elif art_a:
                comparisons.append({
                    "artifact": f"{key[0]}/{key[1]}",
                    "hash_match": False,
                    "reason": f"only in {run_a}",
                })
            else:
                comparisons.append({
                    "artifact": f"{key[0]}/{key[1]}",
                    "hash_match": False,
                    "reason": f"only in {run_b}",
                })

        total = max(len(all_keys), 1)
        match_rate = matched / total

        return {
            "run_a": run_a,
            "run_b": run_b,
            "reproduced": match_rate >= 0.95,
            "match_rate": round(match_rate, 4),
            "config_match": config_match,
            "seed_match": seed_match,
            "total_artifacts": len(all_keys),
            "matched": matched,
            "artifact_comparison": comparisons,
        }

    # ═════════════════════════════════════════════════════════
    #  6. Query API
    # ═════════════════════════════════════════════════════════
    def get_manifest(self, run_id: str) -> Optional[RunManifest]:
        """Load manifest for a run, or None if not found."""
        return self._get_or_load_manifest(run_id)

    def list_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List recent runs (summary only)."""
        runs: List[Dict[str, Any]] = []
        if not self.base_dir.exists():
            return runs

        for entry in sorted(
            self.base_dir.iterdir(), reverse=True
        ):
            if not entry.is_dir():
                continue
            manifest_path = entry / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                data = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
                runs.append({
                    "run_id": data.get("run_id", entry.name),
                    "status": data.get("status"),
                    "created_at": data.get("created_at"),
                    "artifact_count": len(data.get("artifacts", [])),
                    "config_hash": data.get("config_hash", "")[:12],
                })
            except Exception:
                continue
            if len(runs) >= limit:
                break

        return runs

    def get_run_dir(self, run_id: str) -> Path:
        """Return the Path to a run's artifact directory."""
        return self._run_dir(run_id)

    # ═════════════════════════════════════════════════════════
    #  Hashing utilities  (public — usable by other modules)
    # ═════════════════════════════════════════════════════════
    def hash_file(self, path: Union[str, Path]) -> str:
        """SHA-256 of a file (streaming, memory-safe)."""
        return self._hash_file(Path(path))

    def hash_data(
        self, data: Union[List[Dict], Dict, str, bytes]
    ) -> str:
        """
        Content-addressable hash of in-memory data.

        - List[dict] → sorted CSV bytes
        - dict       → deterministic JSON
        - str        → UTF-8 encoded
        - bytes      → raw
        """
        if isinstance(data, bytes):
            return self._hash_bytes(data)
        if isinstance(data, str):
            return self._hash_bytes(data.encode("utf-8"))
        if isinstance(data, dict):
            return self._hash_bytes(
                self._deterministic_json(data).encode("utf-8")
            )
        if isinstance(data, list):
            return self._hash_bytes(
                self._records_to_csv_bytes(data)
            )
        return self._hash_bytes(str(data).encode("utf-8"))

    def hash_config(self, config: Dict[str, Any]) -> str:
        """Deterministic SHA-256 of a config dict."""
        return self._hash_bytes(
            self._deterministic_json(config).encode("utf-8")
        )

    # ═════════════════════════════════════════════════════════
    #  Private helpers
    # ═════════════════════════════════════════════════════════
    def _run_dir(self, run_id: str) -> Path:
        return self.base_dir / run_id

    def _hash_file(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(self.HASH_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def _hash_bytes(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _deterministic_json(self, obj: Any) -> str:
        """
        Serialize to JSON with sorted keys and consistent formatting.

        This ensures identical configs always produce the same hash,
        regardless of dict insertion order or whitespace.
        """
        return json.dumps(
            obj,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            default=str,          # handle datetime, Path, etc.
        )

    def _records_to_csv_bytes(self, records: List[Dict]) -> bytes:
        """
        Convert records to deterministic CSV bytes.

        Sorts columns alphabetically so column order doesn't
        affect the hash.
        """
        if not records:
            return b""

        # Collect all keys, sorted
        all_keys = sorted(
            set().union(*(r.keys() for r in records))
        )

        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=all_keys, extrasaction="ignore"
        )
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)

        return buf.getvalue().encode("utf-8")

    def _write_data(
        self,
        stage_dir: Path,
        data: Any,
        filename: Optional[str],
        stage: str,
    ) -> tuple:
        """
        Write data to disk.  Returns (path, record_count).
        """
        record_count: Optional[int] = None

        # ── Path (copy existing file) ──
        if isinstance(data, Path) or (
            isinstance(data, str) and os.path.isfile(data)
        ):
            src = Path(data)
            dst_name = filename or src.name
            dst = stage_dir / dst_name
            shutil.copy2(src, dst)
            # Try to count CSV rows
            if dst.suffix.lower() == ".csv":
                record_count = self._count_csv(dst)
            return dst, record_count

        # ── List[dict] → CSV ──
        if isinstance(data, list) and data and isinstance(data[0], dict):
            fname = filename or f"{stage}_data.csv"
            dst = stage_dir / fname
            all_keys = sorted(
                set().union(*(r.keys() for r in data))
            )
            with open(dst, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=all_keys, extrasaction="ignore"
                )
                writer.writeheader()
                for rec in data:
                    writer.writerow(rec)
            return dst, len(data)

        # ── Dict → JSON ──
        if isinstance(data, dict):
            fname = filename or f"{stage}_data.json"
            dst = stage_dir / fname
            dst.write_text(
                self._deterministic_json(data), encoding="utf-8"
            )
            return dst, None

        # ── str ──
        if isinstance(data, str):
            fname = filename or f"{stage}_data.txt"
            dst = stage_dir / fname
            dst.write_text(data, encoding="utf-8")
            return dst, None

        # ── bytes ──
        if isinstance(data, bytes):
            fname = filename or f"{stage}_data.bin"
            dst = stage_dir / fname
            dst.write_bytes(data)
            return dst, None

        # Fallback: serialize as JSON string
        fname = filename or f"{stage}_data.json"
        dst = stage_dir / fname
        dst.write_text(
            self._deterministic_json({"data": data}), encoding="utf-8"
        )
        return dst, None

    def _count_csv(self, path: Path) -> int:
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                return sum(1 for _ in reader)
        except Exception:
            return 0

    def _save_manifest(
        self, run_id: str, manifest: RunManifest
    ) -> None:
        path = self._run_dir(run_id) / "manifest.json"
        path.write_text(
            self._deterministic_json(manifest.to_dict()),
            encoding="utf-8",
        )

    def _get_or_load_manifest(
        self, run_id: str
    ) -> RunManifest:
        # In-memory cache
        if run_id in self._manifests:
            return self._manifests[run_id]

        # Load from disk
        path = self._run_dir(run_id) / "manifest.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            manifest = RunManifest.from_dict(data)
            self._manifests[run_id] = manifest
            return manifest

        # Not found — create empty
        manifest = RunManifest(
            run_id=run_id,
            config_hash="",
            status="unknown",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._manifests[run_id] = manifest
        return manifest

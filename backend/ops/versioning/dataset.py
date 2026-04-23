# backend/ops/versioning/dataset.py
"""
Dataset Versioning Manager.

Tracks versions of crawled and processed datasets with:
- Semantic versioning
- Content hashing (integrity verification)
- Lineage tracking (source → processed → scored)
- Diff generation between versions
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.versioning.dataset")


class DatasetVersion:
    """Represents a single dataset version."""

    def __init__(
        self,
        version_id: str,
        dataset_name: str,
        record_count: int,
        content_hash: str,
        source: str = "",
        parent_version: Optional[str] = None,
    ):
        self.version_id = version_id
        self.dataset_name = dataset_name
        self.record_count = record_count
        self.content_hash = content_hash
        self.source = source
        self.parent_version = parent_version
        self.created_at = datetime.now().isoformat()
        self.metadata: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_id": self.version_id,
            "dataset_name": self.dataset_name,
            "record_count": self.record_count,
            "content_hash": self.content_hash,
            "source": self.source,
            "parent_version": self.parent_version,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


class DatasetVersionManager:
    """
    Manages dataset versions with content-addressable storage.

    Storage layout:
        versions/
          datasets/
            {dataset_name}/
              manifest.json       # Version history
              v001/
                data.csv
                meta.json
                checksum.sha256
              v002/
                ...
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path("backend/data/versions/datasets")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_version(
        self,
        dataset_name: str,
        data_path: Path,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DatasetVersion:
        """
        Create a new version of a dataset.

        Args:
            dataset_name: Name of the dataset (e.g., "topcv_jobs")
            data_path: Path to the data file (CSV)
            source: Source identifier
            metadata: Additional metadata
        """
        ds_dir = self.base_dir / dataset_name
        ds_dir.mkdir(parents=True, exist_ok=True)

        # Determine version number
        existing = self._list_version_dirs(dataset_name)
        next_num = len(existing) + 1
        version_id = f"v{next_num:03d}"

        # Create version directory
        ver_dir = ds_dir / version_id
        ver_dir.mkdir(parents=True, exist_ok=True)

        # Copy data
        dest = ver_dir / data_path.name
        shutil.copy2(data_path, dest)

        # Compute hash
        content_hash = self._hash_file(dest)

        # Count records
        record_count = self._count_csv_records(dest)

        # Get parent version
        parent = f"v{next_num-1:03d}" if next_num > 1 else None

        version = DatasetVersion(
            version_id=version_id,
            dataset_name=dataset_name,
            record_count=record_count,
            content_hash=content_hash,
            source=source,
            parent_version=parent,
        )
        if metadata:
            version.metadata = metadata

        # Save metadata
        meta_path = ver_dir / "meta.json"
        meta_path.write_text(json.dumps(version.to_dict(), indent=2))

        # Save checksum
        checksum_path = ver_dir / "checksum.sha256"
        checksum_path.write_text(content_hash)

        # Update manifest
        self._update_manifest(dataset_name, version)

        logger.info(
            f"Dataset version created: {dataset_name}/{version_id} "
            f"({record_count} records, hash={content_hash[:12]})"
        )
        return version

    def get_version(
        self, dataset_name: str, version_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific version."""
        meta_path = self.base_dir / dataset_name / version_id / "meta.json"
        if not meta_path.exists():
            return None
        return json.loads(meta_path.read_text())

    def get_latest_version(self, dataset_name: str) -> Optional[Dict[str, Any]]:
        """Get the latest version of a dataset."""
        versions = self._list_version_dirs(dataset_name)
        if not versions:
            return None
        return self.get_version(dataset_name, versions[-1])

    def list_versions(self, dataset_name: str) -> List[Dict[str, Any]]:
        """List all versions of a dataset."""
        manifest_path = self.base_dir / dataset_name / "manifest.json"
        if not manifest_path.exists():
            return []
        manifest = json.loads(manifest_path.read_text())
        return manifest.get("versions", [])

    def verify_integrity(
        self, dataset_name: str, version_id: str
    ) -> Dict[str, Any]:
        """Verify data integrity of a version using stored hash."""
        ver_dir = self.base_dir / dataset_name / version_id
        checksum_path = ver_dir / "checksum.sha256"

        if not checksum_path.exists():
            return {"status": "no_checksum", "valid": False}

        stored_hash = checksum_path.read_text().strip()

        # Find data file
        data_files = list(ver_dir.glob("*.csv")) + list(ver_dir.glob("*.json"))
        if not data_files:
            return {"status": "no_data_file", "valid": False}

        actual_hash = self._hash_file(data_files[0])
        valid = stored_hash == actual_hash

        return {
            "status": "verified" if valid else "integrity_error",
            "valid": valid,
            "stored_hash": stored_hash[:16],
            "actual_hash": actual_hash[:16],
        }

    def diff_versions(
        self,
        dataset_name: str,
        version_a: str,
        version_b: str,
    ) -> Dict[str, Any]:
        """Compare two versions of a dataset."""
        meta_a = self.get_version(dataset_name, version_a)
        meta_b = self.get_version(dataset_name, version_b)

        if not meta_a or not meta_b:
            return {"error": "Version not found"}

        return {
            "version_a": version_a,
            "version_b": version_b,
            "record_count_a": meta_a.get("record_count", 0),
            "record_count_b": meta_b.get("record_count", 0),
            "record_diff": meta_b.get("record_count", 0) - meta_a.get("record_count", 0),
            "hash_a": meta_a.get("content_hash", "")[:16],
            "hash_b": meta_b.get("content_hash", "")[:16],
            "same_content": meta_a.get("content_hash") == meta_b.get("content_hash"),
        }

    # ── Private Methods ─────────────────────────────────────

    def _list_version_dirs(self, dataset_name: str) -> List[str]:
        ds_dir = self.base_dir / dataset_name
        if not ds_dir.exists():
            return []
        return sorted(
            d.name for d in ds_dir.iterdir()
            if d.is_dir() and d.name.startswith("v")
        )

    def _hash_file(self, path: Path) -> str:
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _count_csv_records(self, path: Path) -> int:
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # Skip header
                return sum(1 for _ in reader)
        except Exception:
            return 0

    def _update_manifest(
        self, dataset_name: str, version: DatasetVersion
    ) -> None:
        manifest_path = self.base_dir / dataset_name / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
        else:
            manifest = {"dataset_name": dataset_name, "versions": []}

        manifest["versions"].append(version.to_dict())
        manifest["latest_version"] = version.version_id
        manifest["updated_at"] = datetime.now().isoformat()
        manifest_path.write_text(json.dumps(manifest, indent=2))

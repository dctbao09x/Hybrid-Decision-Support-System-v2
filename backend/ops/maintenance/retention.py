# backend/ops/maintenance/retention.py
"""
Data Retention Policy Manager.

Manages:
- Log rotation
- Old data cleanup
- Checkpoint pruning
- Backup lifecycle
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ops.maintenance.retention")


class RetentionPolicy:
    """A single retention policy."""

    def __init__(
        self,
        name: str,
        path: Path,
        max_age_days: int,
        max_size_mb: float = 0,
        pattern: str = "*",
        keep_minimum: int = 1,
    ):
        self.name = name
        self.path = path
        self.max_age_days = max_age_days
        self.max_size_mb = max_size_mb
        self.pattern = pattern
        self.keep_minimum = keep_minimum


class RetentionManager:
    """
    Enforces data retention policies across the pipeline.

    Manages lifecycle of:
    - Raw crawl data
    - Processed outputs
    - Log files
    - Checkpoints
    - Backups
    - Temporary files
    """

    DEFAULT_POLICIES = [
        RetentionPolicy("crawl_logs", Path("backend/crawlers/logs"), max_age_days=30, pattern="*.log"),
        RetentionPolicy("data_logs", Path("backend/data/logs"), max_age_days=14, pattern="*.log"),
        RetentionPolicy("session_data", Path("backend/data/sessions"), max_age_days=7, pattern="*"),
        RetentionPolicy("checkpoints", Path("backend/data/checkpoints"), max_age_days=14, pattern="*.json"),
        RetentionPolicy("backups", Path("backend/data/backups"), max_age_days=90, max_size_mb=5000, pattern="*.tar.gz", keep_minimum=3),
        RetentionPolicy("market_data", Path("backend/data/market"), max_age_days=60, pattern="*"),
        RetentionPolicy("output_csvs", Path("backend/output"), max_age_days=30, pattern="*.csv", keep_minimum=5),
        RetentionPolicy("tmp_files", Path("."), max_age_days=1, pattern="tmpclaude-*"),
    ]

    def __init__(
        self,
        policies: Optional[List[RetentionPolicy]] = None,
        dry_run: bool = False,
    ):
        self.policies = policies or self.DEFAULT_POLICIES
        self.dry_run = dry_run

    def enforce_all(self) -> Dict[str, Any]:
        """Enforce all retention policies."""
        results = {}
        total_freed = 0

        for policy in self.policies:
            result = self.enforce(policy)
            results[policy.name] = result
            total_freed += result.get("freed_bytes", 0)

        return {
            "policies_enforced": len(results),
            "total_freed_bytes": total_freed,
            "total_freed_mb": round(total_freed / 1024 / 1024, 2),
            "details": results,
            "dry_run": self.dry_run,
            "timestamp": datetime.now().isoformat(),
        }

    def enforce(self, policy: RetentionPolicy) -> Dict[str, Any]:
        """Enforce a single retention policy."""
        if not policy.path.exists():
            return {"status": "skipped", "reason": "path not found"}

        expired_files = []
        kept_files = []
        freed_bytes = 0
        now = datetime.now()

        # Collect files matching pattern
        all_files = sorted(
            policy.path.glob(policy.pattern),
            key=lambda f: f.stat().st_mtime if f.is_file() else 0,
        )
        files = [f for f in all_files if f.is_file()]

        for f in files:
            age = now - datetime.fromtimestamp(f.stat().st_mtime)
            if age > timedelta(days=policy.max_age_days):
                expired_files.append(f)
            else:
                kept_files.append(f)

        # Ensure we keep minimum files
        while len(kept_files) < policy.keep_minimum and expired_files:
            kept_files.insert(0, expired_files.pop())

        # Check size limit
        if policy.max_size_mb > 0:
            total_size = sum(f.stat().st_size for f in kept_files if f.is_file())
            max_bytes = policy.max_size_mb * 1024 * 1024
            while total_size > max_bytes and len(kept_files) > policy.keep_minimum:
                oldest = kept_files.pop(0)
                expired_files.append(oldest)
                total_size -= oldest.stat().st_size if oldest.is_file() else 0

        # Delete expired files
        for f in expired_files:
            size = f.stat().st_size if f.is_file() else 0
            freed_bytes += size
            if not self.dry_run:
                try:
                    if f.is_dir():
                        shutil.rmtree(f, ignore_errors=True)
                    else:
                        f.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete {f}: {e}")

        if expired_files:
            logger.info(
                f"Retention[{policy.name}]: Removed {len(expired_files)} items, "
                f"freed {freed_bytes / 1024 / 1024:.1f} MB"
            )

        return {
            "status": "enforced",
            "deleted_count": len(expired_files),
            "kept_count": len(kept_files),
            "freed_bytes": freed_bytes,
            "dry_run": self.dry_run,
        }

    def get_status(self) -> Dict[str, Any]:
        """Get current data retention status."""
        status = {}
        for policy in self.policies:
            if not policy.path.exists():
                status[policy.name] = {"status": "path_missing"}
                continue

            files = list(policy.path.glob(policy.pattern))
            file_list = [f for f in files if f.is_file()]
            total_size = sum(f.stat().st_size for f in file_list)

            now = datetime.now()
            expired = [
                f for f in file_list
                if (now - datetime.fromtimestamp(f.stat().st_mtime)) > timedelta(days=policy.max_age_days)
            ]

            status[policy.name] = {
                "path": str(policy.path),
                "total_files": len(file_list),
                "total_size_mb": round(total_size / 1024 / 1024, 2),
                "expired_files": len(expired),
                "max_age_days": policy.max_age_days,
            }
        return status

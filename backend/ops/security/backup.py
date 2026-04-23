# backend/ops/security/backup.py
"""
Backup and Restore Manager.

Handles:
- Scheduled backups of datasets and configs
- Incremental and full backup strategies
- Compressed archive creation
- Restore from backup
"""

from __future__ import annotations

import json
import logging
import shutil
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.security.backup")


class BackupManager:
    """
    Manages backups of pipeline data and configuration.

    Backup types:
    - Full: Complete snapshot of all data
    - Incremental: Only changed files since last backup
    - Config-only: Just configuration files
    """

    def __init__(
        self,
        backup_dir: Optional[Path] = None,
        data_dirs: Optional[List[Path]] = None,
        config_dirs: Optional[List[Path]] = None,
        max_backups: int = 30,
    ):
        self.backup_dir = backup_dir or Path("backend/data/backups")
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        self.data_dirs = data_dirs or [
            Path("backend/data/market"),
            Path("backend/data/versions"),
            Path("backend/data/checkpoints"),
        ]
        self.config_dirs = config_dirs or [
            Path("config"),
            Path("backend/crawlers"),
        ]
        self.max_backups = max_backups

    def create_full_backup(
        self,
        label: str = "",
        compress: bool = True,
    ) -> Dict[str, Any]:
        """
        Create a full backup of all data and config.

        Returns backup metadata.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"full_{label}_{timestamp}" if label else f"full_{timestamp}"

        backup_path = self.backup_dir / f"{name}.tar.gz" if compress else self.backup_dir / name

        files_backed_up = 0
        total_size = 0

        try:
            if compress:
                with tarfile.open(backup_path, "w:gz") as tar:
                    for src_dir in self.data_dirs + self.config_dirs:
                        if src_dir.exists():
                            for f in src_dir.rglob("*"):
                                if f.is_file() and not f.name.startswith("."):
                                    tar.add(f, arcname=str(f.relative_to(src_dir.parent)))
                                    files_backed_up += 1
                                    total_size += f.stat().st_size

                backup_size = backup_path.stat().st_size
            else:
                backup_path.mkdir(parents=True, exist_ok=True)
                for src_dir in self.data_dirs + self.config_dirs:
                    if src_dir.exists():
                        dest = backup_path / src_dir.name
                        shutil.copytree(src_dir, dest, dirs_exist_ok=True)
                        for f in dest.rglob("*"):
                            if f.is_file():
                                files_backed_up += 1
                                total_size += f.stat().st_size
                backup_size = total_size

            metadata = {
                "name": name,
                "type": "full",
                "path": str(backup_path),
                "files": files_backed_up,
                "original_size_bytes": total_size,
                "backup_size_bytes": backup_size,
                "compressed": compress,
                "created_at": datetime.now().isoformat(),
            }

            # Save backup manifest
            manifest_path = self.backup_dir / "manifest.json"
            manifests = self._load_manifests()
            manifests.append(metadata)
            manifest_path.write_text(json.dumps(manifests, indent=2))

            self._cleanup_old_backups()

            logger.info(
                f"Full backup created: {name} "
                f"({files_backed_up} files, {backup_size / 1024 / 1024:.1f} MB)"
            )
            return metadata

        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return {"error": str(e)}

    def create_config_backup(self) -> Dict[str, Any]:
        """Create a backup of configuration files only."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"config_{timestamp}"

        backup_path = self.backup_dir / f"{name}.tar.gz"
        files_backed_up = 0

        try:
            with tarfile.open(backup_path, "w:gz") as tar:
                for src_dir in self.config_dirs:
                    if src_dir.exists():
                        for f in src_dir.rglob("*"):
                            if f.is_file() and f.suffix in (".yaml", ".yml", ".json", ".env"):
                                tar.add(f, arcname=str(f.relative_to(src_dir.parent)))
                                files_backed_up += 1

            metadata = {
                "name": name,
                "type": "config",
                "path": str(backup_path),
                "files": files_backed_up,
                "created_at": datetime.now().isoformat(),
            }

            logger.info(f"Config backup created: {name} ({files_backed_up} files)")
            return metadata

        except Exception as e:
            logger.error(f"Config backup failed: {e}")
            return {"error": str(e)}

    def restore(
        self,
        backup_name: str,
        target_dir: Optional[Path] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Restore from a backup.

        Args:
            backup_name: Name of the backup to restore
            target_dir: Where to extract (None = original locations)
            dry_run: If True, list files without extracting
        """
        backup_path = self.backup_dir / f"{backup_name}.tar.gz"
        if not backup_path.exists():
            backup_path = self.backup_dir / backup_name
        if not backup_path.exists():
            return {"error": f"Backup '{backup_name}' not found"}

        try:
            if backup_path.suffix == ".gz":
                with tarfile.open(backup_path, "r:gz") as tar:
                    members = tar.getmembers()
                    if dry_run:
                        return {
                            "backup": backup_name,
                            "files": [m.name for m in members],
                            "total_files": len(members),
                            "dry_run": True,
                        }

                    extract_to = target_dir or Path(".")
                    tar.extractall(path=extract_to, filter="data")

                    return {
                        "backup": backup_name,
                        "restored_to": str(extract_to),
                        "files_restored": len(members),
                        "dry_run": False,
                    }
            else:
                # Directory backup
                return {"error": "Directory restore not implemented — use tar.gz backups"}

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return {"error": str(e)}

    def list_backups(self) -> List[Dict[str, Any]]:
        """List all available backups."""
        return self._load_manifests()

    def _load_manifests(self) -> List[Dict[str, Any]]:
        manifest_path = self.backup_dir / "manifest.json"
        if not manifest_path.exists():
            return []
        try:
            return json.loads(manifest_path.read_text())
        except Exception:
            return []

    def _cleanup_old_backups(self) -> None:
        """Remove oldest backups if exceeding max_backups."""
        manifests = self._load_manifests()
        while len(manifests) > self.max_backups:
            oldest = manifests.pop(0)
            old_path = Path(oldest.get("path", ""))
            if old_path.exists():
                if old_path.is_file():
                    old_path.unlink()
                else:
                    shutil.rmtree(old_path, ignore_errors=True)
                logger.info(f"Removed old backup: {oldest.get('name')}")

        manifest_path = self.backup_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifests, indent=2))

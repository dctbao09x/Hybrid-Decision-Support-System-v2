# backend/training/rollback_weights.py
"""
Phase 4: Weight Rollback Mechanism.

Enables safe rollback to previous weight versions.

Usage:
    python -m backend.training.rollback_weights --list
    python -m backend.training.rollback_weights --version v2_linear_regression_20260219_145802
    
    # Or programmatically:
    from backend.training.rollback_weights import rollback_to_version
    rollback_to_version("v2_linear_regression_20260219_145802")
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


# =====================================================
# CONSTANTS
# =====================================================

WEIGHTS_DIR = "models/weights"
ARCHIVE_DIR = "models/weights/archive"
ACTIVE_DIR = "models/weights/active"
ACTIVE_WEIGHTS_PATH = "models/weights/active/weights.json"
DEPLOYMENT_LOG_FILE = "models/weights/deployment_log.json"
ROLLBACK_LOG_FILE = "models/weights/rollback_log.json"


# =====================================================
# EXCEPTIONS
# =====================================================

class RollbackError(Exception):
    """Base exception for rollback failures."""
    pass


class VersionNotFoundError(RollbackError):
    """Raised when rollback version not found."""
    pass


class NoBackupAvailableError(RollbackError):
    """Raised when no backup is available for rollback."""
    pass


# =====================================================
# ROLLBACK LOGGING
# =====================================================

def load_rollback_log() -> List[Dict[str, Any]]:
    """Load rollback log entries."""
    if not os.path.exists(ROLLBACK_LOG_FILE):
        return []
    
    try:
        with open(ROLLBACK_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def append_rollback_log(entry: Dict[str, Any]) -> None:
    """Append entry to rollback log."""
    log = load_rollback_log()
    log.append(entry)
    
    os.makedirs(os.path.dirname(ROLLBACK_LOG_FILE), exist_ok=True)
    with open(ROLLBACK_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
    
    logger.warning(f"[ROLLBACK] Logged rollback: {entry['rolled_back_to']}")


def load_deployment_log() -> List[Dict[str, Any]]:
    """Load deployment log to find previous versions."""
    if not os.path.exists(DEPLOYMENT_LOG_FILE):
        return []
    
    try:
        with open(DEPLOYMENT_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


# =====================================================
# VERSION LISTING
# =====================================================

def list_archived_versions() -> List[Dict[str, Any]]:
    """List all archived versions available for rollback.
    
    Returns:
        List of version info dicts, sorted newest first
    """
    archive_dir = Path(ARCHIVE_DIR)
    if not archive_dir.exists():
        return []
    
    versions = []
    for weight_file in sorted(archive_dir.glob("*.json"), reverse=True):
        try:
            with open(weight_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            versions.append({
                "file": str(weight_file),
                "version": data.get("version", "unknown"),
                "r2_score": data.get("r2_score", 0),
                "trained_at": data.get("trained_at", ""),
                "method": data.get("method", "unknown"),
            })
        except (json.JSONDecodeError, IOError):
            continue
    
    return versions


def list_backup_versions() -> List[Dict[str, Any]]:
    """List all backup versions in active directory.
    
    Returns:
        List of backup file info
    """
    active_dir = Path(ACTIVE_DIR)
    if not active_dir.exists():
        return []
    
    backups = []
    for backup_file in sorted(active_dir.glob("weights_backup_*.json"), reverse=True):
        try:
            with open(backup_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            backups.append({
                "file": str(backup_file),
                "version": data.get("version", "unknown"),
                "r2_score": data.get("r2_score", 0),
                "backup_time": backup_file.stem.replace("weights_backup_", ""),
            })
        except (json.JSONDecodeError, IOError):
            continue
    
    return backups


def get_current_version() -> Optional[Dict[str, Any]]:
    """Get currently active weight version info."""
    if not os.path.exists(ACTIVE_WEIGHTS_PATH):
        return None
    
    try:
        with open(ACTIVE_WEIGHTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "version": data.get("version", "unknown"),
            "r2_score": data.get("r2_score", 0),
            "trained_at": data.get("trained_at", ""),
        }
    except (json.JSONDecodeError, IOError):
        return None


def get_previous_version() -> Optional[str]:
    """Get the previously activated version from deployment log."""
    log = load_deployment_log()
    if len(log) < 2:
        return None
    
    # Get second-to-last entry
    return log[-2].get("activated_version")


# =====================================================
# ROLLBACK FUNCTIONS
# =====================================================

def find_version_file(version: str) -> Optional[str]:
    """Find the weight file for a version.
    
    Searches:
    1. Archive directory
    2. Backup files in active directory
    
    Args:
        version: Version string to find
        
    Returns:
        Path to weight file or None
    """
    # Search archive
    archive_dir = Path(ARCHIVE_DIR)
    if archive_dir.exists():
        for weight_file in archive_dir.glob("*.json"):
            try:
                with open(weight_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("version") == version:
                    return str(weight_file)
            except (json.JSONDecodeError, IOError):
                continue
    
    # Search backups
    active_dir = Path(ACTIVE_DIR)
    if active_dir.exists():
        for backup_file in active_dir.glob("weights_backup_*.json"):
            try:
                with open(backup_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("version") == version:
                    return str(backup_file)
            except (json.JSONDecodeError, IOError):
                continue
    
    return None


def rollback_to_version(
    version: str,
    reason: str = "",
    rolled_back_by: str = "system"
) -> str:
    """Rollback to a specific archived version.
    
    Args:
        version: Version string to rollback to
        reason: Reason for rollback
        rolled_back_by: Who initiated rollback
        
    Returns:
        Path to activated weights
        
    Raises:
        VersionNotFoundError: If version not found
    """
    logger.warning("=" * 60)
    logger.warning("[ROLLBACK] Initiating weight rollback")
    logger.warning("=" * 60)
    
    # Find version file
    version_file = find_version_file(version)
    if not version_file:
        raise VersionNotFoundError(f"Version not found: {version}")
    
    logger.warning(f"[ROLLBACK] Target version: {version}")
    logger.warning(f"[ROLLBACK] Source file: {version_file}")
    
    # Get current version
    current = get_current_version()
    current_version = current["version"] if current else "none"
    
    logger.warning(f"[ROLLBACK] Current version: {current_version}")
    
    # Backup current active (even on rollback)
    active_path = Path(ACTIVE_WEIGHTS_PATH)
    if active_path.exists():
        backup_name = f"weights_pre_rollback_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        backup_path = active_path.parent / backup_name
        shutil.copy2(active_path, backup_path)
        logger.warning(f"[ROLLBACK] Backed up current weights to: {backup_path}")
    
    # Copy version to active
    shutil.copy2(version_file, ACTIVE_WEIGHTS_PATH)
    
    logger.warning(f"[ROLLBACK] Activated weights version={version}")
    
    # Load version data for logging
    with open(version_file, "r", encoding="utf-8") as f:
        version_data = json.load(f)
    
    # Log rollback event
    rollback_entry = {
        "rolled_back_to": version,
        "rolled_back_from": current_version,
        "rolled_back_at": datetime.utcnow().isoformat() + "Z",
        "rolled_back_by": rolled_back_by,
        "reason": reason,
        "r2_score": version_data.get("r2_score", 0),
        "source_file": version_file
    }
    append_rollback_log(rollback_entry)
    
    logger.warning("=" * 60)
    logger.warning("[ROLLBACK] Rollback COMPLETE")
    logger.warning(f"[ROLLBACK] Now active: {version}")
    logger.warning(f"[ROLLBACK] R²: {version_data.get('r2_score', 0):.4f}")
    logger.warning("=" * 60)
    
    return ACTIVE_WEIGHTS_PATH


def rollback_to_previous() -> str:
    """Rollback to the previous activated version.
    
    Uses deployment log to find previous version.
    
    Returns:
        Path to activated weights
        
    Raises:
        NoBackupAvailableError: If no previous version available
    """
    previous = get_previous_version()
    if not previous:
        raise NoBackupAvailableError("No previous version found in deployment log")
    
    return rollback_to_version(
        previous,
        reason="Automatic rollback to previous version",
        rolled_back_by="auto_rollback"
    )


def rollback_to_latest_backup() -> str:
    """Rollback to the most recent backup file.
    
    Used for emergency recovery.
    
    Returns:
        Path to activated weights
        
    Raises:
        NoBackupAvailableError: If no backups available
    """
    backups = list_backup_versions()
    if not backups:
        raise NoBackupAvailableError("No backup files found")
    
    latest_backup = backups[0]
    version = latest_backup["version"]
    
    return rollback_to_version(
        version,
        reason="Emergency rollback to latest backup",
        rolled_back_by="emergency_recovery"
    )


# =====================================================
# CLI INTERFACE
# =====================================================

def main():
    """CLI entry point for weight rollback."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Phase 4: Weight Rollback Mechanism"
    )
    parser.add_argument(
        "--version",
        help="Version to rollback to"
    )
    parser.add_argument(
        "--previous",
        action="store_true",
        help="Rollback to previous activated version"
    )
    parser.add_argument(
        "--latest-backup",
        action="store_true",
        help="Rollback to latest backup (emergency)"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available versions"
    )
    parser.add_argument(
        "--list-backups",
        action="store_true",
        help="List backup files"
    )
    parser.add_argument(
        "--current",
        action="store_true",
        help="Show current active version"
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Reason for rollback"
    )
    parser.add_argument(
        "--by",
        default="cli",
        help="Who initiated rollback"
    )
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    
    if args.list:
        versions = list_archived_versions()
        print("\nArchived Versions (newest first):")
        print("=" * 80)
        for v in versions:
            print(f"  {v['version']:<45} R²={v['r2_score']:.4f}")
        print("=" * 80)
        return
    
    if args.list_backups:
        backups = list_backup_versions()
        print("\nBackup Files (newest first):")
        print("=" * 80)
        for b in backups:
            print(f"  {b['version']:<45} R²={b['r2_score']:.4f}  [{b['backup_time']}]")
        print("=" * 80)
        return
    
    if args.current:
        current = get_current_version()
        if current:
            print(f"\nCurrent Active Version:")
            print(f"  Version: {current['version']}")
            print(f"  R²: {current['r2_score']:.4f}")
            print(f"  Trained at: {current['trained_at']}")
        else:
            print("\nNo active weights found")
        return
    
    try:
        if args.version:
            result = rollback_to_version(
                args.version,
                reason=args.reason,
                rolled_back_by=args.by
            )
        elif args.previous:
            result = rollback_to_previous()
        elif args.latest_backup:
            result = rollback_to_latest_backup()
        else:
            parser.print_help()
            return
        
        print(f"\n✓ Rollback successful: {result}")
    except RollbackError as e:
        print(f"\n✗ Rollback FAILED: {e}")
        exit(1)


if __name__ == "__main__":
    main()

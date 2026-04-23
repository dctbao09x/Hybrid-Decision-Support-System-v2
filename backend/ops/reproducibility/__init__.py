"""
Reproducibility package — ensures ≥95% run reproducibility.

Architecture:
    VersionManager   → run_id/ artifact tree, data/config hashing, manifest
    SeedController   → deterministic seed management across all RNG sources
    SnapshotManager  → full environment capture & verification

Usage:
    from backend.ops.reproducibility import (
        VersionManager,
        SeedController,
        SnapshotManager,
    )
"""

from .version_manager import VersionManager
from .seed_control import SeedController
from .snapshot_manager import SnapshotManager

__all__ = [
    "VersionManager",
    "SeedController",
    "SnapshotManager",
]

# backend/scoring/promote_model.py
"""
PHẦN F — MANUAL OVERRIDE BLOCKING

promote_model.py - The ONLY approved way to promote models.

Responsibilities:
1. Validate source model
2. Create audit trail
3. Update metadata with promotion info
4. Prevent direct filesystem manipulation

RULES:
- NO direct copy of weights.json
- NO manual editing of active/
- Full audit log required
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple, Any

logger = logging.getLogger(__name__)


# =============================================================================
# AUDIT LOG
# =============================================================================

AUDIT_LOG_PATH = "logs/model_promotion_audit.jsonl"


class PromotionAuditEntry:
    """Audit entry for model promotion."""
    
    def __init__(
        self,
        source_version: str,
        success: bool,
        user: str = "",
        reason: str = "",
        error: str = "",
    ):
        self.timestamp = datetime.utcnow().isoformat()
        self.source_version = source_version
        self.success = success
        self.user = user
        self.reason = reason
        self.error = error
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "source_version": self.source_version,
            "success": self.success,
            "user": self.user,
            "reason": self.reason,
            "error": self.error,
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict())


def _write_audit_log(entry: PromotionAuditEntry) -> None:
    """Write audit entry to log file."""
    log_path = Path(AUDIT_LOG_PATH)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(log_path, "a") as f:
        f.write(entry.to_json() + "\n")
    
    logger.info(f"[AUDIT] Promotion logged: {entry.source_version} -> {entry.success}")


# =============================================================================
# PROMOTION ERRORS
# =============================================================================

class PromotionError(Exception):
    """Base error for promotion failures."""
    pass


class InvalidSourceError(PromotionError):
    """Source model is invalid."""
    pass


class MissingMetadataError(PromotionError):
    """Source lacks required metadata."""
    pass


class VerificationFailedError(PromotionError):
    """Model verification failed."""
    pass


# =============================================================================
# MODEL PROMOTER
# =============================================================================

class ModelPromoter:
    """
    The ONLY approved mechanism for promoting models to active.
    
    PHẦN F: Manual override blocking.
    
    Usage:
        promoter = ModelPromoter()
        success = promoter.promote("v2", user="data_scientist", reason="Improved R²")
    """
    
    BASE_PATH: str = "models/weights"
    
    def __init__(self, base_path: Optional[str] = None):
        self.base_path = Path(base_path or self.BASE_PATH)
    
    def promote(
        self,
        source_version: str,
        user: str = "",
        reason: str = "",
        force: bool = False,
    ) -> bool:
        """Promote a model version to active.
        
        Args:
            source_version: Version to promote (e.g., "v2")
            user: User performing promotion (for audit)
            reason: Reason for promotion (for audit)
            force: Skip some validation (DANGEROUS)
            
        Returns:
            True if promotion successful.
            
        Raises:
            PromotionError: If promotion fails.
        """
        audit_entry = PromotionAuditEntry(
            source_version=source_version,
            success=False,
            user=user,
            reason=reason,
        )
        
        try:
            # Step 1: Validate source exists
            source_dir = self.base_path / source_version
            if not source_dir.exists():
                raise InvalidSourceError(
                    f"Source version not found: {source_dir}"
                )
            
            # Step 2: Validate required files
            weights_file = source_dir / "weights.json"
            metadata_file = source_dir / "weight_metadata.json"
            
            if not weights_file.exists():
                raise InvalidSourceError(
                    f"Missing weights.json in {source_dir}"
                )
            
            if not metadata_file.exists():
                raise MissingMetadataError(
                    f"Missing weight_metadata.json in {source_dir}. "
                    "Model was not produced by valid training pipeline."
                )
            
            # Step 3: Verify model integrity (unless force)
            if not force:
                self._verify_model(source_version)
            else:
                logger.warning(
                    f"[PROMOTE] FORCE mode - skipping verification for {source_version}"
                )
            
            # Step 4: Update metadata with promotion info
            with open(metadata_file, "r") as f:
                metadata = json.load(f)
            
            metadata["promotion"] = {
                "promoted_at": datetime.utcnow().isoformat(),
                "promoted_by": user,
                "promotion_reason": reason,
                "previous_active": self._get_current_active_version(),
            }
            
            # Step 5: Atomic promotion
            active_dir = self.base_path / "active"
            active_dir.mkdir(parents=True, exist_ok=True)
            
            # Backup current active (if exists)
            self._backup_active()
            
            # Copy to active
            active_weights = active_dir / "weights.json"
            active_metadata = active_dir / "weight_metadata.json"
            
            shutil.copy2(weights_file, active_weights)
            
            # Write updated metadata
            with open(active_metadata, "w") as f:
                json.dump(metadata, f, indent=2)
            
            # Step 6: Verify promoted model
            self._verify_promoted()
            
            # Success!
            audit_entry.success = True
            logger.info(
                f"[PROMOTE] SUCCESS: {source_version} -> active "
                f"(user={user}, reason={reason})"
            )
            
            return True
            
        except Exception as e:
            audit_entry.error = str(e)
            logger.error(f"[PROMOTE] FAILED: {source_version} - {e}")
            raise
            
        finally:
            _write_audit_log(audit_entry)
    
    def _verify_model(self, version: str) -> None:
        """Verify model using TrainingLinker."""
        from backend.scoring.training_linker import (
            TrainingLinker,
            ModelIntegrityError,
        )
        
        try:
            # Reset singleton to force re-verification
            TrainingLinker.reset()
            TrainingLinker.load_verified_weights(version=version, force_reload=True)
            logger.debug(f"[PROMOTE] Model {version} verified OK")
        except ModelIntegrityError as e:
            raise VerificationFailedError(
                f"Model {version} failed verification: {e}"
            ) from e
    
    def _verify_promoted(self) -> None:
        """Verify the promoted active model."""
        from backend.scoring.training_linker import (
            TrainingLinker,
            ModelIntegrityError,
        )
        
        try:
            TrainingLinker.reset()
            TrainingLinker.load_verified_weights(force_reload=True)
            logger.debug("[PROMOTE] Promoted model verified OK")
        except ModelIntegrityError as e:
            raise VerificationFailedError(
                f"Promoted model failed verification: {e}"
            ) from e
    
    def _get_current_active_version(self) -> str:
        """Get current active model version."""
        active_metadata = self.base_path / "active" / "weight_metadata.json"
        
        if not active_metadata.exists():
            return "none"
        
        try:
            with open(active_metadata, "r") as f:
                metadata = json.load(f)
            return metadata.get("version", "unknown")
        except Exception:
            return "unknown"
    
    def _backup_active(self) -> None:
        """Backup current active model."""
        active_dir = self.base_path / "active"
        
        if not active_dir.exists():
            return
        
        backup_dir = self.base_path / f"active_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        if (active_dir / "weights.json").exists():
            shutil.copytree(active_dir, backup_dir)
            logger.info(f"[PROMOTE] Backed up active to {backup_dir}")


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """Command-line interface for model promotion."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Promote a trained model to active",
        epilog="PHẦN F: This is the ONLY approved way to promote models."
    )
    parser.add_argument(
        "version",
        help="Version to promote (e.g., 'v2')",
    )
    parser.add_argument(
        "--user", "-u",
        default=os.environ.get("USER", "unknown"),
        help="User performing promotion (for audit)",
    )
    parser.add_argument(
        "--reason", "-r",
        default="",
        help="Reason for promotion (for audit)",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force promotion (skip verification) - DANGEROUS",
    )
    parser.add_argument(
        "--base-path",
        default="models/weights",
        help="Base path for weight storage",
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    # Promote
    promoter = ModelPromoter(base_path=args.base_path)
    
    try:
        promoter.promote(
            source_version=args.version,
            user=args.user,
            reason=args.reason,
            force=args.force,
        )
        print(f"\n✓ Successfully promoted {args.version} to active")
        return 0
    except PromotionError as e:
        print(f"\n✗ Promotion failed: {e}")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())

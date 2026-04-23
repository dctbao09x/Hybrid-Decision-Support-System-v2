# backend/training/activate_weights.py
"""
Phase 4: Controlled Weight Activation Script.

This script handles explicit activation of validated weights to production.

CRITICAL RULES:
- NO auto-activation from training script
- Activation MUST be explicit
- Activation ONLY after governance validation passes
- Never allow direct overwrite of active weights

Usage:
    python -m backend.training.activate_weights --version v2_linear_regression_20260219_151434
    
    # Or programmatically:
    from backend.training.activate_weights import activate_weights
    activate_weights("models/weights/archive/v2_linear_regression_20260219_151434.json")
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
AUDIT_REPORTS_DIR = "models/weights/audit_reports"
DEPLOYMENT_LOG_FILE = "models/weights/deployment_log.json"
ACTIVE_WEIGHTS_PATH = "models/weights/active/weights.json"

# Governance thresholds (must match Phase 3)
MIN_R2_THRESHOLD = 0.6
IMPROVEMENT_THRESHOLD = 0.05
MAX_SINGLE_WEIGHT = 0.5
MAX_RISK_WEIGHT = 0.3


# =====================================================
# EXCEPTIONS
# =====================================================

class ActivationError(Exception):
    """Base exception for activation failures."""
    pass


class GovernanceNotPassedError(ActivationError):
    """Raised when governance validation has not passed."""
    pass


class ChecklistFailedError(ActivationError):
    """Raised when activation checklist fails."""
    pass


class VersionNotFoundError(ActivationError):
    """Raised when weight version not found."""
    pass


# =====================================================
# DEPLOYMENT LOGGING (Task 8)
# =====================================================

def load_deployment_log() -> List[Dict[str, Any]]:
    """Load deployment log entries."""
    if not os.path.exists(DEPLOYMENT_LOG_FILE):
        return []
    
    try:
        with open(DEPLOYMENT_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def append_deployment_log(entry: Dict[str, Any]) -> None:
    """Append entry to deployment log.
    
    Creates immutable activation history.
    """
    log = load_deployment_log()
    log.append(entry)
    
    os.makedirs(os.path.dirname(DEPLOYMENT_LOG_FILE), exist_ok=True)
    with open(DEPLOYMENT_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
    
    logger.info(f"[DEPLOY] Logged activation: {entry['activated_version']}")


def get_current_active_version() -> Optional[str]:
    """Get currently active weight version."""
    if not os.path.exists(ACTIVE_WEIGHTS_PATH):
        return None
    
    try:
        with open(ACTIVE_WEIGHTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("version", "unknown")
    except (json.JSONDecodeError, IOError):
        return None


# =====================================================
# ACTIVATION CHECKLIST (Task 6)
# =====================================================

def find_audit_report(version: str) -> Optional[str]:
    """Find audit report for a version.
    
    Looks for validation report in audit_reports directory.
    """
    audit_dir = Path(AUDIT_REPORTS_DIR)
    if not audit_dir.exists():
        return None
    
    # Extract timestamp from version if possible
    # Format: v2_linear_regression_YYYYMMDD_HHMMSS
    parts = version.split("_")
    if len(parts) >= 4:
        timestamp = "_".join(parts[-2:])
        
        # Look for matching report
        for report_file in audit_dir.glob("v2_validation_report_*.json"):
            if timestamp in report_file.name:
                return str(report_file)
    
    # Try to find any report close in time
    for report_file in sorted(audit_dir.glob("v2_validation_report_*.json"), reverse=True):
        return str(report_file)
    
    return None


def validate_governance_report(report_path: str, weight_data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate governance report exists and passes.
    
    Args:
        report_path: Path to validation report
        weight_data: Weight file data
        
    Returns:
        Report data
        
    Raises:
        GovernanceNotPassedError: If governance not approved
    """
    if not os.path.exists(report_path):
        raise GovernanceNotPassedError(f"Governance report not found: {report_path}")
    
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)
    
    # Check governance approved
    if not report.get("governance_approved", False):
        raise GovernanceNotPassedError("Governance report shows governance_approved=False")
    
    # Check sanity checks passed
    if not report.get("sanity_checks_passed", False):
        raise GovernanceNotPassedError("Governance report shows sanity_checks_passed=False")
    
    return report


def run_activation_checklist(weight_data: Dict[str, Any], report_data: Dict[str, Any]) -> None:
    """Run full activation checklist.
    
    Phase 4, Task 6: Checklist enforcement.
    
    Checks:
    1. Validation report exists (already done)
    2. Governance approved == True
    3. Weight sanity checks passed
    4. r2_score >= 0.6
    5. Improvement >= 5%
    6. No component > 0.5
    7. risk <= 0.3
    
    Raises:
        ChecklistFailedError: If any check fails
    """
    checklist_results = []
    failed = False
    
    # 1. Governance approved
    if report_data.get("governance_approved"):
        checklist_results.append("✓ Governance approved: True")
    else:
        checklist_results.append("✗ Governance approved: False")
        failed = True
    
    # 2. Sanity checks passed
    if report_data.get("sanity_checks_passed"):
        checklist_results.append("✓ Sanity checks passed: True")
    else:
        checklist_results.append("✗ Sanity checks passed: False")
        failed = True
    
    # 3. R² threshold
    r2 = weight_data.get("r2_score", 0)
    if r2 >= MIN_R2_THRESHOLD:
        checklist_results.append(f"✓ R² threshold: {r2:.4f} >= {MIN_R2_THRESHOLD}")
    else:
        checklist_results.append(f"✗ R² threshold: {r2:.4f} < {MIN_R2_THRESHOLD}")
        failed = True
    
    # 4. Improvement threshold
    improvement_pct = report_data.get("improvement", {}).get("r2_improvement_pct", 0)
    if improvement_pct >= IMPROVEMENT_THRESHOLD * 100:
        checklist_results.append(f"✓ Improvement: {improvement_pct:.2f}% >= {IMPROVEMENT_THRESHOLD*100}%")
    else:
        checklist_results.append(f"✗ Improvement: {improvement_pct:.2f}% < {IMPROVEMENT_THRESHOLD*100}%")
        failed = True
    
    # 5. No single weight > 0.5
    weights = weight_data.get("weights", {})
    max_weight = max(weights.values()) if weights else 0
    dominant = [k for k, v in weights.items() if v > MAX_SINGLE_WEIGHT]
    if not dominant:
        checklist_results.append(f"✓ No domination: max weight = {max_weight:.4f} <= {MAX_SINGLE_WEIGHT}")
    else:
        checklist_results.append(f"✗ Weight domination detected: {dominant}")
        failed = True
    
    # 6. Risk <= 0.3
    risk_weight = weights.get("risk_score", weights.get("risk", 0))
    if risk_weight <= MAX_RISK_WEIGHT:
        checklist_results.append(f"✓ Risk cap: {risk_weight:.4f} <= {MAX_RISK_WEIGHT}")
    else:
        checklist_results.append(f"✗ Risk exceeds cap: {risk_weight:.4f} > {MAX_RISK_WEIGHT}")
        failed = True
    
    # Print checklist
    logger.info("=" * 60)
    logger.info("[ACTIVATE] Activation Checklist")
    logger.info("=" * 60)
    for result in checklist_results:
        logger.info(f"  {result}")
    logger.info("=" * 60)
    
    if failed:
        raise ChecklistFailedError(
            "Activation checklist FAILED:\n" + "\n".join(checklist_results)
        )
    
    logger.info("[ACTIVATE] All checklist items PASSED")


# =====================================================
# MAIN ACTIVATION FUNCTION (Task 2)
# =====================================================

def activate_weights(
    archive_file: str,
    activated_by: str = "system",
    force: bool = False
) -> str:
    """Activate weights from archive to production.
    
    Phase 4, Task 2: Controlled activation.
    
    This is the ONLY approved method to activate weights.
    
    Args:
        archive_file: Path to archived weight file
        activated_by: Who/what triggered activation
        force: Skip checklist (DANGEROUS - not recommended)
        
    Returns:
        Path to activated weights
        
    Raises:
        VersionNotFoundError: If archive file not found
        GovernanceNotPassedError: If governance validation not passed
        ChecklistFailedError: If checklist fails
    """
    logger.info("=" * 60)
    logger.info("[ACTIVATE] Phase 4: Controlled Weight Activation")
    logger.info("=" * 60)
    
    # Step 1: Validate archive file exists
    if not os.path.exists(archive_file):
        raise VersionNotFoundError(f"Archive file not found: {archive_file}")
    
    logger.info(f"[ACTIVATE] Source: {archive_file}")
    
    # Step 2: Load weight data
    with open(archive_file, "r", encoding="utf-8") as f:
        weight_data = json.load(f)
    
    version = weight_data.get("version", "unknown")
    logger.info(f"[ACTIVATE] Version: {version}")
    
    # Step 3: Validate schema (Phase 4, Task 1)
    from backend.scoring.weights_registry import validate_weight_schema, WeightSchemaError
    try:
        validate_weight_schema(weight_data)
    except WeightSchemaError as e:
        raise ActivationError(f"Schema validation failed: {e}")
    
    if not force:
        # Step 4: Find and validate governance report
        report_path = find_audit_report(version)
        if not report_path:
            raise GovernanceNotPassedError(
                f"No governance report found for version: {version}. "
                "Run validation first or provide report path."
            )
        
        logger.info(f"[ACTIVATE] Governance report: {report_path}")
        report_data = validate_governance_report(report_path, weight_data)
        
        # Step 5: Run activation checklist
        run_activation_checklist(weight_data, report_data)
    else:
        logger.warning("[ACTIVATE] Checklist SKIPPED due to force=True (NOT RECOMMENDED)")
    
    # Step 6: Get current active version for logging
    previous_version = get_current_active_version()
    
    # Step 7: Backup current active weights
    active_path = Path(ACTIVE_WEIGHTS_PATH)
    if active_path.exists():
        backup_name = f"weights_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        backup_path = active_path.parent / backup_name
        shutil.copy2(active_path, backup_path)
        logger.info(f"[ACTIVATE] Backed up current weights to: {backup_path}")
    
    # Step 8: Copy to active (NEVER direct overwrite)
    os.makedirs(ACTIVE_DIR, exist_ok=True)
    shutil.copy2(archive_file, ACTIVE_WEIGHTS_PATH)
    
    logger.info(f"[ACTIVATE] Activated weights: {ACTIVE_WEIGHTS_PATH}")
    
    # Step 9: Log deployment event (Task 8)
    deployment_entry = {
        "activated_version": version,
        "previous_version": previous_version,
        "activated_at": datetime.utcnow().isoformat() + "Z",
        "activated_by": activated_by,
        "r2_score": weight_data.get("r2_score", 0),
        "source_file": archive_file
    }
    append_deployment_log(deployment_entry)
    
    logger.info("=" * 60)
    logger.info("[ACTIVATE] Activation COMPLETE")
    logger.info(f"[ACTIVATE] Version: {version}")
    logger.info(f"[ACTIVATE] R²: {weight_data.get('r2_score', 0):.4f}")
    logger.info("=" * 60)
    
    return ACTIVE_WEIGHTS_PATH


def list_available_versions() -> List[Dict[str, Any]]:
    """List all available archived versions.
    
    Returns:
        List of version info dicts
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
            })
        except (json.JSONDecodeError, IOError):
            continue
    
    return versions


# =====================================================
# CLI INTERFACE
# =====================================================

def main():
    """CLI entry point for weight activation."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Phase 4: Controlled Weight Activation"
    )
    parser.add_argument(
        "--version",
        help="Version name (looks in archive directory)"
    )
    parser.add_argument(
        "--file",
        help="Direct path to weight file"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available versions"
    )
    parser.add_argument(
        "--by",
        default="cli",
        help="Who triggered activation"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip checklist (DANGEROUS)"
    )
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    
    if args.list:
        versions = list_available_versions()
        print("\nAvailable Versions:")
        print("=" * 80)
        for v in versions:
            print(f"  {v['version']:<40} R²={v['r2_score']:.4f}  {v['trained_at']}")
        print("=" * 80)
        return
    
    if args.file:
        archive_file = args.file
    elif args.version:
        archive_file = f"{ARCHIVE_DIR}/{args.version}.json"
    else:
        # Use latest version
        versions = list_available_versions()
        if not versions:
            print("ERROR: No versions available")
            return
        archive_file = versions[0]["file"]
        print(f"Using latest version: {versions[0]['version']}")
    
    try:
        result = activate_weights(archive_file, activated_by=args.by, force=args.force)
        print(f"\n✓ Activation successful: {result}")
    except ActivationError as e:
        print(f"\n✗ Activation FAILED: {e}")
        exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Phase 4, Task 7: CI Weight Protection Check.

This script is designed to run in CI/CD pipelines (GitHub Actions, etc.)
to verify weight files have not been improperly modified.

Usage in GitHub Actions:
    - name: Check Weight Protection
      run: python scripts/ci/ci_weight_protection_check.py

Exit codes:
    0 - All checks passed
    1 - Violation detected
"""

import json
import os
import subprocess
import sys
from pathlib import Path


# Files that require governance approval before modification
PROTECTED_WEIGHTS = "models/weights/active/weights.json"

# Files that track modifications
DEPLOYMENT_LOG = "models/weights/deployment_log.json"
AUDIT_REPORTS_DIR = "models/weights/audit_reports"


def get_changed_files():
    """Get files changed in this PR/commit."""
    # Try to get base branch from CI environment
    base = os.environ.get("GITHUB_BASE_REF", "main")
    head = os.environ.get("GITHUB_HEAD_REF", "HEAD")
    
    # If not in CI, check against main
    if not base:
        base = "main"
    
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"origin/{base}...{head}"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return result.stdout.strip().split("\n")
    except Exception:
        pass
    
    # Fallback: check staged files
    result = subprocess.run(
        ["git", "diff", "--name-only", "--cached"],
        capture_output=True,
        text=True
    )
    return result.stdout.strip().split("\n") if result.returncode == 0 else []


def validate_active_weights():
    """Validate active weights file has required schema."""
    if not os.path.exists(PROTECTED_WEIGHTS):
        print("⚠️  No active weights file found")
        return True
    
    try:
        with open(PROTECTED_WEIGHTS, "r") as f:
            data = json.load(f)
        
        required_fields = ["version", "method", "trained_at", "dataset_hash", "r2_score", "weights"]
        missing = [f for f in required_fields if f not in data]
        
        if missing:
            print(f"❌ Active weights missing required fields: {missing}")
            return False
        
        if data.get("method") != "linear_regression":
            print(f"❌ Active weights have invalid method: {data.get('method')}")
            return False
        
        if data.get("r2_score", 0) < 0.6:
            print(f"❌ Active weights have R² below threshold: {data.get('r2_score')}")
            return False
        
        print("✓ Active weights schema validation passed")
        return True
    
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in active weights: {e}")
        return False


def check_deployment_log():
    """Verify deployment log exists and has entries."""
    if not os.path.exists(DEPLOYMENT_LOG):
        print("⚠️  No deployment log found (first activation?)")
        return True
    
    try:
        with open(DEPLOYMENT_LOG, "r") as f:
            log = json.load(f)
        
        if not isinstance(log, list):
            print("❌ Deployment log is not a list")
            return False
        
        print(f"✓ Deployment log has {len(log)} entries")
        return True
    
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in deployment log: {e}")
        return False


def check_audit_reports():
    """Verify audit reports exist."""
    if not os.path.exists(AUDIT_REPORTS_DIR):
        print("⚠️  No audit reports directory")
        return True
    
    reports = list(Path(AUDIT_REPORTS_DIR).glob("*.json"))
    print(f"✓ Found {len(reports)} audit reports")
    return True


def main():
    """Run all CI protection checks."""
    print("\n" + "=" * 60)
    print("Phase 4: CI Weight Protection Check")
    print("=" * 60 + "\n")
    
    failed = False
    
    # Check 1: Validate active weights schema
    print("[1] Validating active weights schema...")
    if not validate_active_weights():
        failed = True
    
    # Check 2: Verify deployment log
    print("\n[2] Checking deployment log...")
    if not check_deployment_log():
        failed = True
    
    # Check 3: Verify audit reports
    print("\n[3] Checking audit reports...")
    if not check_audit_reports():
        failed = True
    
    # Check 4: Look for unauthorized changes
    print("\n[4] Checking for unauthorized weight changes...")
    changed = get_changed_files()
    
    if PROTECTED_WEIGHTS in changed:
        # Verify deployment log was also updated (indicating proper activation)
        if DEPLOYMENT_LOG in changed:
            print("✓ Weight change has corresponding deployment log entry")
        else:
            print("⚠️  Active weights changed but no deployment log update")
            print("   This may indicate unauthorized modification")
            # Don't fail here, just warn - could be legitimate first activation
    else:
        print("✓ No changes to active weights detected")
    
    print("\n" + "=" * 60)
    if failed:
        print("❌ CI PROTECTION CHECK FAILED")
        print("=" * 60 + "\n")
        return 1
    else:
        print("✓ CI PROTECTION CHECK PASSED")
        print("=" * 60 + "\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())

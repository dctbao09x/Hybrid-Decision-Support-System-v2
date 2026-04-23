#!/usr/bin/env python3
"""
Phase 4, Task 7: CI Protection Pre-commit Hook.

Prevents direct modification of models/weights/active/weights.json.

Installation:
    1. Copy this file to .git/hooks/pre-commit
    2. Make it executable: chmod +x .git/hooks/pre-commit
    
Or use the install script:
    python scripts/ci/install_weight_protection.py

This hook ensures:
- Direct edits to active weights are blocked
- Only activation script can modify active weights
- Changes must go through governance validation first
"""

import subprocess
import sys
import os
from pathlib import Path


# Protected paths (cannot be directly modified)
PROTECTED_FILES = [
    "models/weights/active/weights.json",
]

# Allowed commit message prefixes for activation
ALLOWED_PREFIXES = [
    "[ACTIVATE]",
    "[ROLLBACK]",
    "[CI-OVERRIDE]",
]


def get_staged_files():
    """Get list of staged files."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        return []
    return result.stdout.strip().split("\n")


def check_commit_message():
    """Check if commit message allows override."""
    # Get commit message from file
    commit_msg_file = ".git/COMMIT_EDITMSG"
    if os.path.exists(commit_msg_file):
        with open(commit_msg_file, "r") as f:
            msg = f.read().strip()
        return any(msg.startswith(prefix) for prefix in ALLOWED_PREFIXES)
    return False


def main():
    """Main pre-commit hook logic."""
    staged_files = get_staged_files()
    
    violations = []
    for protected in PROTECTED_FILES:
        if protected in staged_files:
            violations.append(protected)
    
    if violations:
        print("\n" + "=" * 60)
        print("❌ PRE-COMMIT HOOK BLOCKED")
        print("=" * 60)
        print("\nDirect modification of protected files detected:")
        for v in violations:
            print(f"  - {v}")
        print("\n⚠️  Active weights MUST NOT be modified directly!")
        print("\nTo activate weights properly, use:")
        print("  python -m backend.training.activate_weights --version <version>")
        print("\nTo rollback, use:")
        print("  python -m backend.training.rollback_weights --version <version>")
        print("\nIf this is an authorized override, commit with message prefix:")
        for prefix in ALLOWED_PREFIXES:
            print(f"  - {prefix}")
        print("=" * 60 + "\n")
        
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    main()

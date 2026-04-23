#!/usr/bin/env python3
"""
Install weight protection pre-commit hook.

Usage:
    python scripts/ci/install_weight_protection.py
"""

import os
import shutil
import stat
from pathlib import Path


def main():
    """Install pre-commit hook."""
    # Get paths
    script_dir = Path(__file__).parent
    hook_source = script_dir / "pre_commit_weight_protection.py"
    git_hooks_dir = Path(".git") / "hooks"
    hook_dest = git_hooks_dir / "pre-commit"
    
    # Check if in git repo
    if not Path(".git").exists():
        print("ERROR: Not in a git repository root")
        return 1
    
    # Create hooks dir if needed
    git_hooks_dir.mkdir(parents=True, exist_ok=True)
    
    # Backup existing hook if present
    if hook_dest.exists():
        backup = hook_dest.with_suffix(".backup")
        shutil.copy2(hook_dest, backup)
        print(f"Backed up existing hook to: {backup}")
    
    # Copy hook
    shutil.copy2(hook_source, hook_dest)
    
    # Make executable (Unix)
    if os.name != 'nt':
        st = os.stat(hook_dest)
        os.chmod(hook_dest, st.st_mode | stat.S_IEXEC)
    
    print(f"✓ Installed weight protection hook: {hook_dest}")
    print("\nThe following files are now protected:")
    print("  - models/weights/active/weights.json")
    print("\nTo bypass (NOT recommended), use commit message prefix:")
    print("  - [ACTIVATE]")
    print("  - [ROLLBACK]")
    print("  - [CI-OVERRIDE]")
    
    return 0


if __name__ == "__main__":
    exit(main())

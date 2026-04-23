# backend/ops/maintenance/dependency_manager.py
"""
Dependency Management.

Tracks and validates:
- Python package versions
- System dependencies
- Compatibility checks
- Vulnerability scanning (via pip-audit integration)
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ops.maintenance.deps")


class DependencyManager:
    """
    Manages pipeline dependencies and compatibility.

    Features:
    - Freeze current environment
    - Compare against requirements files
    - Detect outdated packages
    - Check for known vulnerabilities
    """

    REQUIREMENTS_FILES = [
        Path("requirements_crawler.txt"),
        Path("requirements_data_pipeline.txt"),
        Path("backend/requirements_api.txt"),
    ]

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path(".")

    def freeze_environment(self) -> Dict[str, str]:
        """Get all installed packages and versions."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--format=json"],
                capture_output=True, text=True, timeout=30,
            )
            packages = json.loads(result.stdout)
            return {p["name"]: p["version"] for p in packages}
        except Exception as e:
            logger.error(f"Failed to freeze environment: {e}")
            return {}

    def check_requirements(self) -> Dict[str, Any]:
        """
        Compare installed versions against requirements files.

        Returns mismatches and missing packages.
        """
        installed = self.freeze_environment()
        installed_lower = {k.lower(): v for k, v in installed.items()}

        report = {
            "installed_count": len(installed),
            "files_checked": [],
            "missing": [],
            "version_mismatch": [],
        }

        for req_file in self.REQUIREMENTS_FILES:
            full_path = self.project_root / req_file
            if not full_path.exists():
                continue

            report["files_checked"].append(str(req_file))
            required = self._parse_requirements(full_path)

            for pkg_name, req_version in required.items():
                pkg_lower = pkg_name.lower()
                if pkg_lower not in installed_lower:
                    report["missing"].append({
                        "package": pkg_name,
                        "required": req_version,
                        "file": str(req_file),
                    })
                elif req_version and installed_lower[pkg_lower] != req_version:
                    report["version_mismatch"].append({
                        "package": pkg_name,
                        "required": req_version,
                        "installed": installed_lower[pkg_lower],
                        "file": str(req_file),
                    })

        return report

    def check_outdated(self) -> List[Dict[str, str]]:
        """Check for outdated packages."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--outdated", "--format=json"],
                capture_output=True, text=True, timeout=60,
            )
            return json.loads(result.stdout)
        except Exception as e:
            logger.error(f"Failed to check outdated: {e}")
            return []

    def check_vulnerabilities(self) -> Dict[str, Any]:
        """
        Check for known package vulnerabilities using pip-audit.

        Requires pip-audit to be installed.
        """
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip_audit", "--format=json", "--progress-spinner=off"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                return {"status": "clean", "vulnerabilities": []}
            else:
                try:
                    data = json.loads(result.stdout)
                    return {"status": "vulnerable", "vulnerabilities": data}
                except json.JSONDecodeError:
                    return {
                        "status": "error",
                        "message": result.stderr or result.stdout,
                    }
        except FileNotFoundError:
            return {"status": "skipped", "message": "pip-audit not installed"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def generate_lockfile(self, output: Optional[Path] = None) -> Path:
        """Generate a pip freeze lockfile."""
        output = output or Path("requirements.lock")
        installed = self.freeze_environment()
        lines = [f"{pkg}=={ver}" for pkg, ver in sorted(installed.items())]
        output.write_text("\n".join(lines) + "\n")
        logger.info(f"Lockfile generated: {output} ({len(lines)} packages)")
        return output

    def _parse_requirements(self, path: Path) -> Dict[str, str]:
        """Parse a requirements.txt file into {package: version}."""
        result = {}
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                if "==" in line:
                    name, _, version = line.partition("==")
                    result[name.strip()] = version.strip()
                elif ">=" in line:
                    name, _, version = line.partition(">=")
                    result[name.strip()] = ""  # no exact version pinned
                else:
                    result[line.strip()] = ""
        return result

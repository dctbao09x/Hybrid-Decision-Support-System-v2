"""
test_env_scan_gate.py
───────────────────────────────────────────────────────────────────────────────
CI Gate: ENV isolation scan.

GUARANTEE: no file in the scoring code path reads any of the five forbidden
environment variables at the AST level (os.environ.get / os.getenv /
os.environ[]).

Why:
  Forbidden ENV vars make scoring non-deterministic: the same model weights
  produce different outputs depending on deployment variables, test flags, or
  version overrides.  Any ENV read in the scoring path is a determinism
  regression.

Reference architectural decision: GD8 / production-hardening-2026-02-21
───────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

# ─── Ensure project root is importable ───────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ─── Configuration ────────────────────────────────────────────────────────────

#: Directories that belong to the scoring code path.
SCORING_SCAN_ROOTS: list[str] = [
    "backend/scoring",
    "backend/api/routers",       # scoring_router.py lives here
    "backend/api/controllers",   # decision_controller.py
    "backend/api",               # hash_chain_logger.py, artifacts.py
]

#: ENV variable names that must NOT appear in any scoring-path file.
FORBIDDEN_ENV_VARS: list[str] = [
    "SCORING_ENV",
    "SCORING_TEST_MODE",
    "SIMGR_ENVIRONMENT",
    "SIMGR_WEIGHTS_VERSION",
    "SIMGR_WEIGHT_VALIDATION_MODE",
]

# ─── AST helpers ─────────────────────────────────────────────────────────────


class EnvRead(NamedTuple):
    file: Path
    line: int
    column: int
    call_form: str
    env_var_name: str


def _extract_string_value(node: ast.expr | None) -> str | None:
    """Return the string value if *node* is a string literal, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _scan_file(path: Path, forbidden: set[str]) -> list[EnvRead]:
    """
    Walk the AST of *path* looking for forbidden ENV var reads.

    Detected patterns:
      os.environ.get("KEY", ...)
      os.environ["KEY"]
      os.getenv("KEY", ...)
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    hits: list[EnvRead] = []

    for node in ast.walk(tree):
        # ── os.environ.get("KEY") ──────────────────────────────────────────
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "environ"
            and node.args
        ):
            key = _extract_string_value(node.args[0])
            if key and key in forbidden:
                hits.append(EnvRead(path, node.lineno, node.col_offset, "os.environ.get", key))

        # ── os.environ["KEY"] ─────────────────────────────────────────────
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "environ"
        ):
            slice_node = node.slice
            key = _extract_string_value(slice_node)
            if key and key in forbidden:
                hits.append(EnvRead(path, node.lineno, node.col_offset, "os.environ[...]", key))

        # ── os.getenv("KEY") ──────────────────────────────────────────────
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "getenv"
            and node.args
        ):
            key = _extract_string_value(node.args[0])
            if key and key in forbidden:
                hits.append(EnvRead(path, node.lineno, node.col_offset, "os.getenv", key))

    return hits


def _collect_python_files(workspace_root: Path, scan_roots: list[str]) -> list[Path]:
    files: list[Path] = []
    for root in scan_roots:
        scan_dir = workspace_root / root
        if scan_dir.exists():
            files.extend(scan_dir.rglob("*.py"))
    return sorted(set(files))


# ─── Tests ───────────────────────────────────────────────────────────────────

_WORKSPACE_ROOT = Path(__file__).parent.parent.resolve()


class TestEnvScanGate:
    """No scoring-path file may read any of the five forbidden ENV variables."""

    def test_no_forbidden_env_reads_in_scoring_path(self) -> None:
        """
        AST scan of all scoring-path Python files.
        Fails immediately if any forbidden ENV read is found.
        """
        python_files = _collect_python_files(_WORKSPACE_ROOT, SCORING_SCAN_ROOTS)
        assert python_files, (
            f"No Python files found in scan roots {SCORING_SCAN_ROOTS}. "
            f"Workspace root: {_WORKSPACE_ROOT}"
        )

        forbidden_set = set(FORBIDDEN_ENV_VARS)
        all_hits: list[EnvRead] = []

        for py_file in python_files:
            hits = _scan_file(py_file, forbidden_set)
            all_hits.extend(hits)

        if all_hits:
            report_lines = [
                f"\nForbidden ENV reads found in scoring path ({len(all_hits)} violation(s)):\n"
            ]
            for hit in all_hits:
                rel = hit.file.relative_to(_WORKSPACE_ROOT)
                report_lines.append(
                    f"  {rel}:{hit.line}:{hit.column}  "
                    f"{hit.call_form}({hit.env_var_name!r})"
                )
            report_lines.append(
                "\nFix: remove ENV reads from scoring path. "
                "All configuration must be baked into the weight manifest at training time."
            )
            pytest.fail("\n".join(report_lines))

    def test_scan_roots_all_exist(self) -> None:
        """All declared scan root directories must exist in the workspace."""
        missing = [r for r in SCORING_SCAN_ROOTS if not (_WORKSPACE_ROOT / r).exists()]
        assert not missing, (
            f"Scan root directories not found: {missing}. "
            f"Update SCORING_SCAN_ROOTS in test_env_scan_gate.py"
        )

    def test_forbidden_list_is_complete(self) -> None:
        """The forbidden list must contain all 5 known ENV vars (regression guard)."""
        assert len(FORBIDDEN_ENV_VARS) == 5, (
            f"FORBIDDEN_ENV_VARS has {len(FORBIDDEN_ENV_VARS)} entries — expected 5. "
            f"A variable may have been removed. Verify the list is intentional."
        )
        for name in FORBIDDEN_ENV_VARS:
            assert name, "Empty entry in FORBIDDEN_ENV_VARS"

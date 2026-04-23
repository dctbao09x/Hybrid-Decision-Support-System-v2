# tests/test_manifest_enforcement.py
"""
Weight Manifest Enforcement Tests
==================================

Verifies that all manifest invariants are enforced at load time for BOTH
manifest systems:

  - weight_loader.load_weight_manifest()  (reads manifest.json directly)
  - weight_manifest.get_manifest()        (reads manifest.json via _load_manifest_from_files)

Test matrix:
    [A] locked=false          → hard error (not warning)
    [B] missing required field→ hard error on each of the 5 required fields
    [C] tampered content      → checksum_manifest_file mismatch → hard error
    [D] valid manifest        → loads cleanly, all invariants satisfied

Canonical hash algorithm:
    canonical = {k: v for k in CANONICAL_FIELDS if k in data}
    sha256(json.dumps(canonical, indent=2) + "\\n")

CANONICAL_FIELDS (ordered, no checksum_manifest_file):
    active_version, weights_path, sha256, internal_checksum,
    locked, created_at, _comment
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Canonical hash helper (mirrors production implementation)
# ─────────────────────────────────────────────────────────────────────────────

_CANONICAL_FIELDS = (
    "active_version",
    "weights_path",
    "sha256",
    "internal_checksum",
    "locked",
    "created_at",
    "_comment",
)


def _make_canonical_hash(data: Dict[str, Any]) -> str:
    canonical = {k: data[k] for k in _CANONICAL_FIELDS if k in data}
    raw = (json.dumps(canonical, indent=2) + "\n").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Valid baseline manifest (all invariants satisfied)
# ─────────────────────────────────────────────────────────────────────────────

def _valid_manifest() -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "active_version": "v2_linear_regression_20260219_145802",
        "weights_path": "models/weights/active/weights.json",
        "sha256": "59f0f3adcfd16e025739b4f50bb3691d55950f4d9091662df5a8040026d1d2ed",
        "internal_checksum": "7995c0683b509015177137cc4ea295c81d43bfef23660965e4c34c19997683da",
        "locked": True,
        "created_at": "2026-02-21T14:05:05.937796+00:00",
        "_comment": "IMMUTABLE MANIFEST - DO NOT MODIFY AT RUNTIME",
    }
    base["checksum_manifest_file"] = _make_canonical_hash(base)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Helper: write manifest to a temp file and patch _MANIFEST_PATH
# ─────────────────────────────────────────────────────────────────────────────

def _write_temp_manifest(data: Dict[str, Any]) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(data, tmp, indent=2)
    tmp.flush()
    tmp.close()
    return Path(tmp.name)


# ─────────────────────────────────────────────────────────────────────────────
# Tests for weight_loader.load_weight_manifest()
# ─────────────────────────────────────────────────────────────────────────────

class TestWeightLoaderManifest:
    """Tests for backend.scoring.weight_loader.load_weight_manifest()."""

    def _call_with(self, data: Dict[str, Any]):
        """Write data to a temp file, then call load_weight_manifest()."""
        from backend.scoring import weight_loader
        from backend.scoring.weight_loader import WeightManifestIntegrityError, WeightRegistryError

        tmp_path = _write_temp_manifest(data)
        try:
            with patch.object(weight_loader, "_MANIFEST_PATH", tmp_path.relative_to(tmp_path.parent)):
                # Patch CWD so Path.cwd() / relative_path == tmp_path
                with patch("pathlib.Path.cwd", return_value=tmp_path.parent):
                    return weight_loader.load_weight_manifest()
        finally:
            os.unlink(tmp_path)

    # ── [A] locked=false ──────────────────────────────────────────────────────

    def test_locked_false_raises_integrity_error(self):
        """locked=false must raise WeightManifestIntegrityError (not a warning)."""
        from backend.scoring.weight_loader import WeightManifestIntegrityError

        data = _valid_manifest()
        data["locked"] = False
        # Update checksum so we hit the locked check, not the checksum mismatch
        data["checksum_manifest_file"] = _make_canonical_hash(data)

        with pytest.raises(WeightManifestIntegrityError, match="locked"):
            self._call_with(data)

    def test_locked_none_raises_integrity_error(self):
        """locked=null (None in Python) must also raise."""
        from backend.scoring.weight_loader import WeightManifestIntegrityError

        data = _valid_manifest()
        data["locked"] = None
        data["checksum_manifest_file"] = _make_canonical_hash(data)

        with pytest.raises(WeightManifestIntegrityError, match="locked"):
            self._call_with(data)

    # ── [B] missing required fields ───────────────────────────────────────────

    @pytest.mark.parametrize("field", [
        "active_version",
        "weights_path",
        "sha256",
        "locked",
        "checksum_manifest_file",
    ])
    def test_missing_required_field_raises(self, field: str):
        """Any missing required field must abort loading."""
        from backend.scoring.weight_loader import WeightRegistryError

        data = _valid_manifest()
        del data[field]

        with pytest.raises(WeightRegistryError, match=r"missing|Missing"):
            self._call_with(data)

    # ── [C] tampered content ──────────────────────────────────────────────────

    def test_tampered_active_version_raises(self):
        """Changing active_version without updating checksum_manifest_file must fail."""
        from backend.scoring.weight_loader import WeightManifestIntegrityError

        data = _valid_manifest()
        data["active_version"] = "TAMPERED_VERSION"
        # checksum_manifest_file is now stale — do NOT update it

        with pytest.raises(WeightManifestIntegrityError, match="tampered"):
            self._call_with(data)

    def test_tampered_sha256_raises(self):
        """Changing sha256 (weights file hash) without updating checksum raises."""
        from backend.scoring.weight_loader import WeightManifestIntegrityError

        data = _valid_manifest()
        data["sha256"] = "a" * 64  # Fake replacement hash
        # Do NOT recompute checksum_manifest_file

        with pytest.raises(WeightManifestIntegrityError, match="tampered"):
            self._call_with(data)

    def test_tampered_checksum_field_itself_raises(self):
        """Storing wrong checksum_manifest_file value raises."""
        from backend.scoring.weight_loader import WeightManifestIntegrityError

        data = _valid_manifest()
        data["checksum_manifest_file"] = "b" * 64  # Bad checksum

        with pytest.raises(WeightManifestIntegrityError, match="tampered"):
            self._call_with(data)

    # ── [D] valid manifest ────────────────────────────────────────────────────

    def test_valid_manifest_loads_cleanly(self):
        """A correctly-formed manifest must load without error."""
        result = self._call_with(_valid_manifest())
        assert result["active_version"] == "v2_linear_regression_20260219_145802"
        assert result["locked"] is True
        assert "checksum_manifest_file" in result


# ─────────────────────────────────────────────────────────────────────────────
# Tests for weight_manifest.get_manifest() / _load_manifest_from_files()
# ─────────────────────────────────────────────────────────────────────────────

class TestWeightManifestSingleton:
    """Tests for backend.scoring.weight_manifest._load_manifest_from_files()."""

    def _call_with(self, data: Dict[str, Any]):
        """Write data to a temp file, then call _load_manifest_from_files()."""
        import backend.scoring.weight_manifest as wm

        tmp_path = _write_temp_manifest(data)
        try:
            with patch.object(wm, "_MANIFEST_PATH", tmp_path.relative_to(tmp_path.parent)):
                with patch("pathlib.Path.cwd", return_value=tmp_path.parent):
                    return wm._load_manifest_from_files()
        finally:
            os.unlink(tmp_path)

    # ── [A] locked=false ──────────────────────────────────────────────────────

    def test_locked_false_raises_runtime_error(self):
        """locked=false must raise RuntimeError (hard abort)."""
        data = _valid_manifest()
        data["locked"] = False
        data["checksum_manifest_file"] = _make_canonical_hash(data)

        with pytest.raises(RuntimeError, match="locked"):
            self._call_with(data)

    # ── [B] missing required fields ───────────────────────────────────────────

    @pytest.mark.parametrize("field", [
        "active_version",
        "weights_path",
        "sha256",
        "locked",
        "checksum_manifest_file",
    ])
    def test_missing_required_field_raises(self, field: str):
        """Any missing required field must abort startup."""
        data = _valid_manifest()
        del data[field]

        with pytest.raises(RuntimeError, match=r"missing|Missing|ABORTED"):
            self._call_with(data)

    # ── [C] tampered content ──────────────────────────────────────────────────

    def test_tampered_content_raises_runtime_error(self):
        """Changing any canonical field without updating checksum raises."""
        data = _valid_manifest()
        data["active_version"] = "EVIL_VERSION"
        # Do NOT update checksum_manifest_file

        with pytest.raises(RuntimeError, match="tampered"):
            self._call_with(data)

    def test_tampered_locked_false_in_tampered_manifest(self):
        """Even with correct checksum after tampering locked, locked check fires."""
        data = _valid_manifest()
        data["locked"] = False
        # Recompute checksum so it matches the tampered content
        data["checksum_manifest_file"] = _make_canonical_hash(data)

        with pytest.raises(RuntimeError, match="locked"):
            self._call_with(data)

    # ── [D] valid manifest ────────────────────────────────────────────────────

    def test_valid_manifest_builds_frozen_dataclass(self):
        """A valid manifest must produce an immutable WeightManifest."""
        from backend.scoring.weight_manifest import WeightManifest

        result = self._call_with(_valid_manifest())
        assert isinstance(result, WeightManifest)
        assert result.active_version == "v2_linear_regression_20260219_145802"
        assert result.locked is True
        assert result.validation_mode == "STRICT"
        assert len(result.checksum_manifest_file) == 64  # full hex SHA256

    def test_frozen_dataclass_cannot_be_mutated(self):
        """WeightManifest is frozen=True — mutation must raise FrozenInstanceError."""
        from dataclasses import FrozenInstanceError

        result = self._call_with(_valid_manifest())
        with pytest.raises(FrozenInstanceError):
            result.locked = False  # type: ignore[misc]

    def test_locked_invariant_in_post_init(self):
        """WeightManifest.__post_init__ enforces locked=True even if bypassing loader."""
        from backend.scoring.weight_manifest import WeightManifest

        with pytest.raises(RuntimeError, match="locked"):
            WeightManifest(
                active_version="v1",
                validation_mode="STRICT",
                weights_path="models/weights/active/weights.json",
                checksum="a" * 64,
                locked=False,  # ← must reject
                checksum_manifest_file="c" * 64,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Canonical hash algorithm correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestCanonicalHash:
    """Verify that the canonical hash algorithm is deterministic and correct."""

    def test_known_hash_matches(self):
        """
        The canonical hash of the production manifest.json content must equal the
        value embedded in checksum_manifest_file of the live manifest file.
        """
        live_manifest_path = (
            Path(__file__).parent.parent
            / "backend" / "scoring" / "weights" / "manifest.json"
        )
        if not live_manifest_path.exists():
            pytest.skip("manifest.json not found; skipping live-file hash test")

        with open(live_manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        stored_cmf = data.get("checksum_manifest_file", "")
        computed_cmf = _make_canonical_hash(data)

        assert computed_cmf == stored_cmf, (
            f"manifest.json checksum_manifest_file is incorrect!\n"
            f"  stored  : {stored_cmf}\n"
            f"  computed: {computed_cmf}\n"
            f"The manifest file may have been modified after locking."
        )

    def test_hash_is_stable_across_calls(self):
        """Same input → same hash (no random salt)."""
        data = _valid_manifest()
        h1 = _make_canonical_hash(data)
        h2 = _make_canonical_hash(data)
        assert h1 == h2

    def test_hash_length_is_64_hex_chars(self):
        """SHA256 hexdigest is always exactly 64 characters."""
        data = _valid_manifest()
        assert len(_make_canonical_hash(data)) == 64

    def test_any_field_change_produces_different_hash(self):
        """Any modification to a canonical field must change the hash."""
        data = _valid_manifest()
        original_hash = _make_canonical_hash(data)

        for field in _CANONICAL_FIELDS:
            mutated = copy.deepcopy(data)
            mutated[field] = "MUTATED"
            assert _make_canonical_hash(mutated) != original_hash, (
                f"Field {field!r} change did not affect canonical hash"
            )

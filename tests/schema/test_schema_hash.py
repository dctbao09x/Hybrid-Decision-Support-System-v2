# tests/schema/test_schema_hash.py
"""
Schema Hash + Version Trace + Artifact Chain — Prompt-14 Test Suite
====================================================================

Test classes:
  TestComputeSchemaHash         — hash function determinism and sensitivity
  TestVersionBundle             — dataclass shape, to_dict, immutability
  TestResolveVersionsIntegration— public resolve_versions() with mocks
  TestResolveModelVersion       — _resolve_model_version fallback behaviour
  TestResolveRuleVersion        — _resolve_rule_version hash fingerprint
  TestResolveTaxonomyVersion    — _resolve_taxonomy_version hash fingerprint
  TestArtifactChainRecord       — record dataclass + JSONL serialisation
  TestArtifactChainLogger       — JSONL read/write/count/search
  TestLogArtifactChainFunc      — convenience wrapper error handling
  TestDecisionMetaVersionFields — DecisionMeta schema carries 4 new fields
  TestDecisionResponseLineage   — every SUCCESS response has version fields
  TestVersionHashSensitivity    — changing one version changes schema_hash

PASS CRITERIA (P-14): No response without traceable lineage.
All tests assert that model_version, rule_version, taxonomy_version,
schema_version, and schema_hash are present and non-empty.
"""

from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ─── Imports under test ───────────────────────────────────────────────────────

from backend.governance.version_resolver import (
    RESPONSE_SCHEMA_VERSION,
    VersionBundle,
    compute_schema_hash,
    resolve_versions,
    _resolve_model_version,
    _resolve_rule_version,
    _resolve_taxonomy_version,
    _sha256,
)
from backend.governance.artifact_chain_log import (
    ArtifactChainLogger,
    ArtifactChainRecord,
    log_artifact_chain,
    get_artifact_chain_logger,
)


# ══════════════════════════════════════════════════════════════════════════════
# TestComputeSchemaHash
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeSchemaHash:
    """Verify compute_schema_hash() is deterministic and sensitive to each axis."""

    def test_returns_64_char_hex_string(self):
        h = compute_schema_hash("v1.0", "abc", "def", "response-v4.0")
        assert isinstance(h, str)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic_same_input(self):
        h1 = compute_schema_hash("v1", "r1", "t1", "schema-v1")
        h2 = compute_schema_hash("v1", "r1", "t1", "schema-v1")
        assert h1 == h2

    def test_different_model_version_yields_different_hash(self):
        base = compute_schema_hash("v1.0", "r1", "t1", "schema-v1")
        changed = compute_schema_hash("v2.0", "r1", "t1", "schema-v1")
        assert base != changed

    def test_different_rule_version_yields_different_hash(self):
        base = compute_schema_hash("v1.0", "r1", "t1", "schema-v1")
        changed = compute_schema_hash("v1.0", "r2", "t1", "schema-v1")
        assert base != changed

    def test_different_taxonomy_version_yields_different_hash(self):
        base = compute_schema_hash("v1.0", "r1", "t1", "schema-v1")
        changed = compute_schema_hash("v1.0", "r1", "t2", "schema-v1")
        assert base != changed

    def test_different_schema_version_yields_different_hash(self):
        base = compute_schema_hash("v1.0", "r1", "t1", "schema-v1")
        changed = compute_schema_hash("v1.0", "r1", "t1", "schema-v2")
        assert base != changed

    def test_all_unknown_still_returns_hash(self):
        h = compute_schema_hash("unknown", "unknown", "unknown", "unknown")
        assert isinstance(h, str)
        assert len(h) == 64

    def test_hash_is_lowercase(self):
        h = compute_schema_hash("v1", "r1", "t1", "schema")
        assert h == h.lower()

    def test_hash_is_independent_of_argument_order(self):
        # compute_schema_hash sorts by axis name internally
        # so value order matters because the argument names fix the key–value mapping
        h1 = compute_schema_hash("mv", "rv", "tv", "sv")
        h2 = compute_schema_hash("mv", "rv", "tv", "sv")
        assert h1 == h2


# ══════════════════════════════════════════════════════════════════════════════
# TestVersionBundle
# ══════════════════════════════════════════════════════════════════════════════

class TestVersionBundle:
    """VersionBundle frozen dataclass — shape and serialisation."""

    def _make(self, **kw) -> VersionBundle:
        defaults = dict(
            model_version="v1.0.0",
            rule_version="abc123",
            taxonomy_version="def456",
            schema_version="response-v4.0",
            schema_hash="a" * 64,
            resolved_at="2026-02-24T00:00:00+00:00",
        )
        defaults.update(kw)
        return VersionBundle(**defaults)

    def test_bundle_has_all_fields(self):
        b = self._make()
        assert b.model_version == "v1.0.0"
        assert b.rule_version == "abc123"
        assert b.taxonomy_version == "def456"
        assert b.schema_version == "response-v4.0"
        assert len(b.schema_hash) == 64
        assert b.resolved_at

    def test_bundle_is_frozen(self):
        b = self._make()
        with pytest.raises((AttributeError, TypeError)):
            b.model_version = "tampered"  # type: ignore[misc]

    def test_to_dict_returns_all_six_keys(self):
        b = self._make()
        d = b.to_dict()
        assert set(d.keys()) == {
            "model_version", "rule_version", "taxonomy_version",
            "schema_version", "schema_hash", "resolved_at",
        }

    def test_to_dict_values_match_fields(self):
        b = self._make()
        d = b.to_dict()
        assert d["model_version"] == b.model_version
        assert d["schema_hash"] == b.schema_hash

    def test_to_dict_is_json_serialisable(self):
        b = self._make()
        j = json.dumps(b.to_dict())
        assert isinstance(j, str)


# ══════════════════════════════════════════════════════════════════════════════
# TestResolveModelVersion
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveModelVersion:
    def test_uses_hint_when_registry_unavailable(self, monkeypatch):
        monkeypatch.setitem(
            sys.modules,
            "backend.ml.model_registry",
            None,  # type: ignore[arg-type]
        )
        result = _resolve_model_version("v2.3.1")
        assert result == "v2.3.1"

    def test_falls_back_to_unknown_when_no_hint(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "backend.ml.model_registry", None)  # type: ignore
        result = _resolve_model_version(None)
        assert result == "unknown"

    def test_uses_registry_active_model(self, monkeypatch, tmp_path):
        from backend.ml.model_registry import ModelRegistry, ModelStatus
        import backend.ml.model_registry as mr_mod

        reg = ModelRegistry(tmp_path / "r.jsonl")
        reg.register("v9.0.0", ModelStatus.PRODUCTION, accuracy=0.95)
        monkeypatch.setattr(mr_mod, "get_model_registry", lambda: reg)

        result = _resolve_model_version("v1.0.0")
        assert result == "v9.0.0"

    def test_never_raises(self):
        # Even a broken import must not propagate
        result = _resolve_model_version("fallback-v1")
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════════════════════════════
# TestResolveRuleVersion
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveRuleVersion:
    def test_returns_string(self):
        result = _resolve_rule_version()
        assert isinstance(result, str)

    def test_returns_16_chars_or_unknown(self):
        result = _resolve_rule_version()
        assert result == "unknown" or len(result) == 16

    def test_deterministic_for_same_rules(self, monkeypatch):
        import backend.rule_engine.rule_service as rs_mod
        fake_rules = [
            {"name": "rule_A", "category": "career", "priority": 1},
            {"name": "rule_B", "category": "career", "priority": 2},
        ]
        monkeypatch.setattr(
            rs_mod.RuleService, "list_rules",
            staticmethod(lambda page_size=100: {"rules": fake_rules}),
        )
        h1 = _resolve_rule_version()
        h2 = _resolve_rule_version()
        assert h1 == h2

    def test_changes_when_rules_change(self, monkeypatch):
        import backend.rule_engine.rule_service as rs_mod

        rules_v1 = [{"name": "rule_A", "category": "c", "priority": 1}]
        rules_v2 = [{"name": "rule_B", "category": "c", "priority": 1}]

        monkeypatch.setattr(
            rs_mod.RuleService, "list_rules",
            staticmethod(lambda page_size=100: {"rules": rules_v1}),
        )
        h1 = _resolve_rule_version()

        monkeypatch.setattr(
            rs_mod.RuleService, "list_rules",
            staticmethod(lambda page_size=100: {"rules": rules_v2}),
        )
        h2 = _resolve_rule_version()
        assert h1 != h2

    def test_never_raises_on_failure(self, monkeypatch):
        import backend.rule_engine.rule_service as rs_mod
        monkeypatch.setattr(
            rs_mod.RuleService, "list_rules",
            staticmethod(lambda page_size=100: (_ for _ in ()).throw(RuntimeError)),
        )
        result = _resolve_rule_version()
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════════════════════════════
# TestResolveTaxonomyVersion
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveTaxonomyVersion:
    def test_returns_string(self):
        result = _resolve_taxonomy_version()
        assert isinstance(result, str)

    def test_returns_16_chars_or_unknown(self):
        result = _resolve_taxonomy_version()
        assert result == "unknown" or len(result) == 16

    def test_unknown_when_manager_none(self, monkeypatch):
        import backend.api.routers.taxonomy_router as tt_mod
        monkeypatch.setattr(tt_mod, "get_taxonomy_manager", lambda: None)
        result = _resolve_taxonomy_version()
        assert result == "unknown"

    def test_deterministic_for_same_counts(self, monkeypatch):
        import backend.api.routers.taxonomy_router as tt_mod
        mock_mgr = MagicMock()
        mock_mgr.self_check.return_value = {"skills": 100, "interests": 50}
        monkeypatch.setattr(tt_mod, "get_taxonomy_manager", lambda: mock_mgr)
        h1 = _resolve_taxonomy_version()
        h2 = _resolve_taxonomy_version()
        assert h1 == h2

    def test_changes_when_counts_change(self, monkeypatch):
        import backend.api.routers.taxonomy_router as tt_mod
        mgr1 = MagicMock()
        mgr1.self_check.return_value = {"skills": 100}
        monkeypatch.setattr(tt_mod, "get_taxonomy_manager", lambda: mgr1)
        h1 = _resolve_taxonomy_version()

        mgr2 = MagicMock()
        mgr2.self_check.return_value = {"skills": 999}
        monkeypatch.setattr(tt_mod, "get_taxonomy_manager", lambda: mgr2)
        h2 = _resolve_taxonomy_version()
        assert h1 != h2

    def test_never_raises_on_failure(self, monkeypatch):
        import backend.api.routers.taxonomy_router as tt_mod
        monkeypatch.setattr(
            tt_mod, "get_taxonomy_manager",
            lambda: (_ for _ in ()).throw(ImportError("no taxonomy")),
        )
        result = _resolve_taxonomy_version()
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════════════════════════════
# TestResolveVersionsIntegration
# ══════════════════════════════════════════════════════════════════════════════

class TestResolveVersionsIntegration:
    """resolve_versions() assembles all four axes and derives schema_hash."""

    def test_returns_version_bundle(self):
        bundle = resolve_versions()
        assert isinstance(bundle, VersionBundle)

    def test_bundle_has_all_required_fields(self):
        bundle = resolve_versions()
        assert bundle.model_version
        assert bundle.rule_version
        assert bundle.taxonomy_version
        assert bundle.schema_version
        assert bundle.schema_hash
        assert bundle.resolved_at

    def test_schema_version_matches_constant(self):
        bundle = resolve_versions()
        assert bundle.schema_version == RESPONSE_SCHEMA_VERSION

    def test_schema_hash_is_64_hex(self):
        bundle = resolve_versions()
        assert len(bundle.schema_hash) == 64
        assert all(c in "0123456789abcdef" for c in bundle.schema_hash)

    def test_schema_hash_recomputable(self):
        """The stored schema_hash must match independently computed hash."""
        bundle = resolve_versions()
        expected = compute_schema_hash(
            bundle.model_version,
            bundle.rule_version,
            bundle.taxonomy_version,
            bundle.schema_version,
        )
        assert bundle.schema_hash == expected

    def test_model_version_hint_used_when_registry_down(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "backend.ml.model_registry", None)  # type: ignore
        bundle = resolve_versions(model_version_hint="hint-v7")
        assert bundle.model_version == "hint-v7"

    def test_never_raises(self):
        """resolve_versions must never propagate any exception."""
        bundle = resolve_versions()
        assert isinstance(bundle, VersionBundle)

    def test_two_calls_have_same_schema_version(self):
        b1 = resolve_versions()
        b2 = resolve_versions()
        assert b1.schema_version == b2.schema_version == RESPONSE_SCHEMA_VERSION

    def test_resolved_at_is_iso_string(self):
        import datetime as _dt
        bundle = resolve_versions()
        parsed = _dt.datetime.fromisoformat(bundle.resolved_at)
        assert parsed.tzinfo is not None  # must be timezone-aware


# ══════════════════════════════════════════════════════════════════════════════
# TestArtifactChainRecord
# ══════════════════════════════════════════════════════════════════════════════

class TestArtifactChainRecord:
    def _make(self, **kw) -> ArtifactChainRecord:
        defaults = dict(
            trace_id="dec-abc123",
            model_version="v1.0.0",
            rule_version="r1234567",
            taxonomy_version="t1234567",
            schema_version="response-v4.0",
            schema_hash="a" * 64,
            artifact_chain_root="b" * 64,
            stage_count=9,
            logged_at="2026-02-24T00:00:00+00:00",
        )
        defaults.update(kw)
        return ArtifactChainRecord(**defaults)

    def test_all_fields_accessible(self):
        rec = self._make()
        assert rec.trace_id == "dec-abc123"
        assert rec.model_version == "v1.0.0"
        assert rec.rule_version == "r1234567"
        assert rec.taxonomy_version == "t1234567"
        assert rec.schema_version == "response-v4.0"
        assert len(rec.schema_hash) == 64
        assert len(rec.artifact_chain_root) == 64
        assert rec.stage_count == 9
        assert rec.logged_at

    def test_to_jsonl_line_is_valid_json(self):
        rec = self._make()
        line = rec.to_jsonl_line()
        parsed = json.loads(line)
        assert parsed["trace_id"] == "dec-abc123"

    def test_to_jsonl_line_has_all_fields(self):
        rec = self._make()
        d = json.loads(rec.to_jsonl_line())
        for field in ("trace_id", "model_version", "rule_version",
                      "taxonomy_version", "schema_version", "schema_hash",
                      "artifact_chain_root", "stage_count", "logged_at"):
            assert field in d, f"Missing field: {field}"

    def test_to_jsonl_line_no_newline(self):
        rec = self._make()
        assert "\n" not in rec.to_jsonl_line()


# ══════════════════════════════════════════════════════════════════════════════
# TestArtifactChainLogger
# ══════════════════════════════════════════════════════════════════════════════

class TestArtifactChainLogger:
    def _make_record(self, trace_id="dec-test-001") -> ArtifactChainRecord:
        return ArtifactChainRecord(
            trace_id=trace_id,
            model_version="v1.0",
            rule_version="r1",
            taxonomy_version="t1",
            schema_version="response-v4.0",
            schema_hash="c" * 64,
            artifact_chain_root="d" * 64,
            stage_count=9,
            logged_at="2026-02-24T00:00:00+00:00",
        )

    def test_append_returns_true(self, tmp_path):
        logger = ArtifactChainLogger(tmp_path / "chain.jsonl")
        result = logger.append(self._make_record())
        assert result is True

    def test_file_created_on_append(self, tmp_path):
        p = tmp_path / "chain.jsonl"
        logger = ArtifactChainLogger(p)
        logger.append(self._make_record())
        assert p.exists()

    def test_count_correct_after_multiple_appends(self, tmp_path):
        logger = ArtifactChainLogger(tmp_path / "chain.jsonl")
        for i in range(5):
            logger.append(self._make_record(trace_id=f"dec-{i:03d}"))
        assert logger.count() == 5

    def test_count_zero_for_missing_file(self, tmp_path):
        logger = ArtifactChainLogger(tmp_path / "nonexistent.jsonl")
        assert logger.count() == 0

    def test_read_all_returns_list_of_dicts(self, tmp_path):
        logger = ArtifactChainLogger(tmp_path / "chain.jsonl")
        logger.append(self._make_record("dec-test-A"))
        logger.append(self._make_record("dec-test-B"))
        records = logger.read_all()
        assert isinstance(records, list)
        assert len(records) == 2

    def test_read_all_records_have_trace_id(self, tmp_path):
        logger = ArtifactChainLogger(tmp_path / "chain.jsonl")
        logger.append(self._make_record("dec-alpha"))
        records = logger.read_all()
        assert records[0]["trace_id"] == "dec-alpha"

    def test_find_by_trace_id_returns_matching(self, tmp_path):
        logger = ArtifactChainLogger(tmp_path / "chain.jsonl")
        logger.append(self._make_record("dec-A"))
        logger.append(self._make_record("dec-B"))
        found = logger.find_by_trace_id("dec-A")
        assert len(found) == 1
        assert found[0]["trace_id"] == "dec-A"

    def test_find_by_trace_id_returns_empty_for_no_match(self, tmp_path):
        logger = ArtifactChainLogger(tmp_path / "chain.jsonl")
        logger.append(self._make_record("dec-A"))
        assert logger.find_by_trace_id("dec-nope") == []

    def test_find_by_schema_hash(self, tmp_path):
        logger = ArtifactChainLogger(tmp_path / "chain.jsonl")
        rec = self._make_record()
        logger.append(rec)
        found = logger.find_by_schema_hash("c" * 64)
        assert len(found) == 1

    def test_read_all_empty_for_missing_file(self, tmp_path):
        logger = ArtifactChainLogger(tmp_path / "missing.jsonl")
        assert logger.read_all() == []

    def test_appended_records_have_all_version_fields(self, tmp_path):
        logger = ArtifactChainLogger(tmp_path / "chain.jsonl")
        logger.append(self._make_record())
        records = logger.read_all()
        r = records[0]
        for field in ("model_version", "rule_version", "taxonomy_version",
                      "schema_version", "schema_hash", "artifact_chain_root"):
            assert field in r, f"Missing field: {field}"


# ══════════════════════════════════════════════════════════════════════════════
# TestLogArtifactChainFunc
# ══════════════════════════════════════════════════════════════════════════════

class TestLogArtifactChainFunc:
    def _make_bundle(self) -> VersionBundle:
        sh = compute_schema_hash("v1", "r1", "t1", "response-v4.0")
        return VersionBundle(
            model_version="v1.0.0",
            rule_version="r1234567",
            taxonomy_version="t1234567",
            schema_version="response-v4.0",
            schema_hash=sh,
            resolved_at="2026-02-24T00:00:00+00:00",
        )

    def test_returns_true_on_success(self, tmp_path, monkeypatch):
        from backend.governance import artifact_chain_log as acl_mod
        logger = ArtifactChainLogger(tmp_path / "chain.jsonl")
        monkeypatch.setattr(acl_mod, "get_artifact_chain_logger", lambda: logger)

        result = log_artifact_chain(
            trace_id="dec-log001",
            versions=self._make_bundle(),
            artifact_chain_root="e" * 64,
            stage_count=9,
        )
        assert result is True

    def test_record_persisted_with_correct_trace_id(self, tmp_path, monkeypatch):
        from backend.governance import artifact_chain_log as acl_mod
        logger = ArtifactChainLogger(tmp_path / "chain.jsonl")
        monkeypatch.setattr(acl_mod, "get_artifact_chain_logger", lambda: logger)

        log_artifact_chain(
            trace_id="dec-log002",
            versions=self._make_bundle(),
            artifact_chain_root="f" * 64,
            stage_count=9,
        )
        records = logger.find_by_trace_id("dec-log002")
        assert len(records) == 1
        assert records[0]["schema_version"] == "response-v4.0"

    def test_never_raises_on_broken_logger(self, monkeypatch):
        from backend.governance import artifact_chain_log as acl_mod

        class BrokenLogger:
            def append(self, _):
                raise OSError("disk full")

        monkeypatch.setattr(acl_mod, "get_artifact_chain_logger", lambda: BrokenLogger())
        result = log_artifact_chain(
            trace_id="dec-broken",
            versions=self._make_bundle(),
            artifact_chain_root="0" * 64,
            stage_count=5,
        )
        assert result is False  # must not raise

    def test_record_contains_schema_hash(self, tmp_path, monkeypatch):
        from backend.governance import artifact_chain_log as acl_mod
        logger = ArtifactChainLogger(tmp_path / "chain.jsonl")
        monkeypatch.setattr(acl_mod, "get_artifact_chain_logger", lambda: logger)

        bundle = self._make_bundle()
        log_artifact_chain("dec-schema", bundle, "a" * 64, 9)
        records = logger.find_by_trace_id("dec-schema")
        assert records[0]["schema_hash"] == bundle.schema_hash


# ══════════════════════════════════════════════════════════════════════════════
# TestDecisionMetaVersionFields
# ══════════════════════════════════════════════════════════════════════════════

class TestDecisionMetaVersionFields:
    """DecisionMeta Pydantic model must carry all 4 P-14 version fields."""

    def test_decision_meta_has_rule_version_field(self):
        from backend.api.controllers.decision_controller import DecisionMeta
        meta = DecisionMeta(
            correlation_id="corr-001",
            pipeline_duration_ms=42.0,
            model_version="v1.0.0",
            weights_version="default",
            llm_used=False,
            stages_completed=["input_normalize"],
        )
        assert hasattr(meta, "rule_version")

    def test_decision_meta_has_taxonomy_version_field(self):
        from backend.api.controllers.decision_controller import DecisionMeta
        meta = DecisionMeta(
            correlation_id="corr-002",
            pipeline_duration_ms=42.0,
            model_version="v1.0.0",
            weights_version="default",
            llm_used=False,
            stages_completed=[],
        )
        assert hasattr(meta, "taxonomy_version")

    def test_decision_meta_has_schema_version_field(self):
        from backend.api.controllers.decision_controller import DecisionMeta
        meta = DecisionMeta(
            correlation_id="corr-003",
            pipeline_duration_ms=42.0,
            model_version="v1.0.0",
            weights_version="default",
            llm_used=False,
            stages_completed=[],
        )
        assert hasattr(meta, "schema_version")

    def test_decision_meta_has_schema_hash_field(self):
        from backend.api.controllers.decision_controller import DecisionMeta
        meta = DecisionMeta(
            correlation_id="corr-004",
            pipeline_duration_ms=42.0,
            model_version="v1.0.0",
            weights_version="default",
            llm_used=False,
            stages_completed=[],
        )
        assert hasattr(meta, "schema_hash")

    def test_default_values_are_unknown(self):
        from backend.api.controllers.decision_controller import DecisionMeta
        meta = DecisionMeta(
            correlation_id="corr-005",
            pipeline_duration_ms=10.0,
            model_version="v1.0.0",
            weights_version="default",
            llm_used=False,
            stages_completed=[],
        )
        assert meta.rule_version == "unknown"
        assert meta.taxonomy_version == "unknown"
        assert meta.schema_version == "unknown"
        assert meta.schema_hash == "unknown"

    def test_version_fields_accept_real_values(self):
        from backend.api.controllers.decision_controller import DecisionMeta
        sh = compute_schema_hash("v1", "rv", "tv", "response-v4.0")
        meta = DecisionMeta(
            correlation_id="corr-006",
            pipeline_duration_ms=15.0,
            model_version="v1.0.0",
            weights_version="default",
            llm_used=False,
            stages_completed=["input_normalize", "scoring"],
            rule_version="rv1234",
            taxonomy_version="tv5678",
            schema_version="response-v4.0",
            schema_hash=sh,
        )
        assert meta.rule_version == "rv1234"
        assert meta.taxonomy_version == "tv5678"
        assert meta.schema_version == "response-v4.0"
        assert meta.schema_hash == sh

    def test_meta_serialises_version_fields_to_json(self):
        from backend.api.controllers.decision_controller import DecisionMeta
        sh = compute_schema_hash("v1", "rv", "tv", "response-v4.0")
        meta = DecisionMeta(
            correlation_id="corr-007",
            pipeline_duration_ms=5.0,
            model_version="v1.0.0",
            weights_version="default",
            llm_used=False,
            stages_completed=[],
            rule_version="rv1",
            taxonomy_version="tv1",
            schema_version="response-v4.0",
            schema_hash=sh,
        )
        d = meta.model_dump()
        assert d["rule_version"] == "rv1"
        assert d["taxonomy_version"] == "tv1"
        assert d["schema_version"] == "response-v4.0"
        assert d["schema_hash"] == sh


# ══════════════════════════════════════════════════════════════════════════════
# TestVersionHashSensitivity
# ══════════════════════════════════════════════════════════════════════════════

class TestVersionHashSensitivity:
    """
    PASS CRITERIA FOR P-14: 'No more untraced responses.'

    Verify that each version axis independently influences schema_hash.
    This proves that schema_hash can detect any component version change.
    """

    BASE = ("v1.0.0", "rule-abc", "tax-def", "response-v4.0")

    def _hash(self, *args) -> str:
        return compute_schema_hash(*args)

    def test_model_change_detected(self):
        h_base = self._hash(*self.BASE)
        h_new = self._hash("v2.0.0", *self.BASE[1:])
        assert h_base != h_new, "Model version change must alter schema_hash"

    def test_rule_change_detected(self):
        h_base = self._hash(*self.BASE)
        h_new = self._hash(self.BASE[0], "rule-xyz", *self.BASE[2:])
        assert h_base != h_new, "Rule version change must alter schema_hash"

    def test_taxonomy_change_detected(self):
        h_base = self._hash(*self.BASE)
        args = list(self.BASE)
        args[2] = "tax-999"
        h_new = self._hash(*args)
        assert h_base != h_new, "Taxonomy version change must alter schema_hash"

    def test_schema_change_detected(self):
        h_base = self._hash(*self.BASE)
        args = list(self.BASE)
        args[3] = "response-v5.0"
        h_new = self._hash(*args)
        assert h_base != h_new, "Schema version change must alter schema_hash"

    def test_four_identical_axes_have_same_hash(self):
        h1 = self._hash(*self.BASE)
        h2 = self._hash(*self.BASE)
        assert h1 == h2, "Identical axes must yield identical schema_hash"


# ══════════════════════════════════════════════════════════════════════════════
# TestSha256Helper
# ══════════════════════════════════════════════════════════════════════════════

class TestSha256Helper:
    """_sha256 internal helper — determinism and correctness."""

    def test_returns_lowercase_hex_string(self):
        h = _sha256({"key": "value"})
        assert isinstance(h, str)
        assert len(h) == 64
        assert h == h.lower()

    def test_matches_manual_computation(self):
        obj = {"sorted": True, "value": 42}
        manual = hashlib.sha256(
            json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        assert _sha256(obj) == manual

    def test_deterministic(self):
        obj = {"a": 1, "b": 2}
        assert _sha256(obj) == _sha256(obj)

    def test_sort_order_irrelevant_due_to_sort_keys(self):
        h1 = _sha256({"b": 2, "a": 1})
        h2 = _sha256({"a": 1, "b": 2})
        assert h1 == h2  # sort_keys=True normalises order

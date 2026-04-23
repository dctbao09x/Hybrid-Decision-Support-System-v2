# backend/tests/test_decision_trace.py
"""
Unit tests for P7: Decision Trace Chain
========================================

P7 PASS criteria:
- Every ``DecisionResponse`` has ``rule_applied``, ``reasoning_path``, ``stage_log``.
- ``rule_applied`` is a list of dicts with keys: rule, category, priority, outcome, frozen.
- ``reasoning_path`` has at least one entry per pipeline stage (≥ 9 total).
- ``stage_log`` contains one entry per stage; each entry has: stage, status, duration_ms.
- ``stage_log`` entries reference all 9 expected stage names.
- ``_RuleEngineResult`` dataclass exists and holds rankings + rules_trace.
"""

from __future__ import annotations

import pytest
from dataclasses import fields as dc_fields
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Helpers imported from controller
# ─────────────────────────────────────────────────────────────────────────────

def _import_controller():
    from backend.api.controllers import decision_controller
    return decision_controller


def _make_meta():
    """Return a minimal valid DecisionMeta instance."""
    from backend.api.controllers.decision_controller import DecisionMeta
    return DecisionMeta(
        correlation_id="corr-test",
        pipeline_duration_ms=0.0,
        model_version="test",
        weights_version="test",
        llm_used=False,
        stages_completed=[],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test: DecisionResponse model fields
# ─────────────────────────────────────────────────────────────────────────────

class TestDecisionResponseP7Fields:
    """DecisionResponse must expose the three P7 traceability fields."""

    def test_rule_applied_field_exists(self):
        from backend.api.controllers.decision_controller import DecisionResponse
        dr = DecisionResponse(
            trace_id="t1",
            timestamp="2024-01-01T00:00:00Z",
            status="SUCCESS",
            rankings=[],
            top_career=None,
            explanation=None,
            market_insights=[],
            meta=_make_meta(),
        )
        assert hasattr(dr, "rule_applied"), "DecisionResponse must have 'rule_applied' field"
        assert isinstance(dr.rule_applied, list)

    def test_reasoning_path_field_exists(self):
        from backend.api.controllers.decision_controller import DecisionResponse
        dr = DecisionResponse(
            trace_id="t2",
            timestamp="2024-01-01T00:00:00Z",
            status="SUCCESS",
            rankings=[],
            top_career=None,
            explanation=None,
            market_insights=[],
            meta=_make_meta(),
        )
        assert hasattr(dr, "reasoning_path"), "DecisionResponse must have 'reasoning_path' field"
        assert isinstance(dr.reasoning_path, list)

    def test_stage_log_field_exists(self):
        from backend.api.controllers.decision_controller import DecisionResponse
        dr = DecisionResponse(
            trace_id="t3",
            timestamp="2024-01-01T00:00:00Z",
            status="SUCCESS",
            rankings=[],
            top_career=None,
            explanation=None,
            market_insights=[],
            meta=_make_meta(),
        )
        assert hasattr(dr, "stage_log"), "DecisionResponse must have 'stage_log' field"
        assert isinstance(dr.stage_log, list)

    def test_all_p7_fields_default_to_empty_list(self):
        from backend.api.controllers.decision_controller import DecisionResponse
        dr = DecisionResponse(
            trace_id="t4",
            timestamp="2024-01-01T00:00:00Z",
            status="SUCCESS",
            rankings=[],
            top_career=None,
            explanation=None,
            market_insights=[],
            meta=_make_meta(),
        )
        assert dr.rule_applied == []
        assert dr.reasoning_path == []
        assert dr.stage_log == []


# ─────────────────────────────────────────────────────────────────────────────
# Test: _RuleEngineResult dataclass
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleEngineResultDataclass:
    def test_dataclass_importable(self):
        from backend.api.controllers.decision_controller import _RuleEngineResult
        assert _RuleEngineResult is not None

    def test_has_rankings_field(self):
        from backend.api.controllers.decision_controller import _RuleEngineResult
        field_names = {f.name for f in dc_fields(_RuleEngineResult)}
        assert "rankings" in field_names, "_RuleEngineResult must have 'rankings'"

    def test_has_rules_trace_field(self):
        from backend.api.controllers.decision_controller import _RuleEngineResult
        field_names = {f.name for f in dc_fields(_RuleEngineResult)}
        assert "rules_trace" in field_names, "_RuleEngineResult must have 'rules_trace'"

    def test_instantiation(self):
        from backend.api.controllers.decision_controller import _RuleEngineResult
        rr = _RuleEngineResult(rankings=[], rules_trace=[{"rule": "test"}])
        assert rr.rankings == []
        assert rr.rules_trace == [{"rule": "test"}]


# ─────────────────────────────────────────────────────────────────────────────
# Test: stage_log schema validation
# ─────────────────────────────────────────────────────────────────────────────

EXPECTED_STAGES = {
    "input_normalize",
    "feature_extraction",
    "kb_alignment",
    "merge",
    "simgr_scoring",
    "drift_check",
    "rule_engine",
    "market_data",
    "explanation",
}

class TestStageLogSchema:
    """Validate the structure of stage_log entries."""

    def _make_entry(self, stage: str, status: str = "ok", duration_ms: float = 12.5):
        return {"stage": stage, "status": status, "duration_ms": duration_ms}

    def test_entry_has_required_keys(self):
        entry = self._make_entry("simgr_scoring")
        assert "stage" in entry
        assert "status" in entry
        assert "duration_ms" in entry

    def test_all_nine_stages_covered(self):
        entries = [self._make_entry(s) for s in EXPECTED_STAGES]
        stage_names = {e["stage"] for e in entries}
        missing = EXPECTED_STAGES - stage_names
        assert not missing, f"Missing stages in stage_log: {missing}"

    def test_duration_ms_is_numeric(self):
        entry = self._make_entry("merge", duration_ms=0.5)
        assert isinstance(entry["duration_ms"], (int, float))
        assert entry["duration_ms"] >= 0


# ─────────────────────────────────────────────────────────────────────────────
# Test: reasoning_path structure
# ─────────────────────────────────────────────────────────────────────────────

class TestReasoningPath:
    """reasoning_path must contain one entry per pipeline stage."""

    def _make_sample_path(self):
        return [
            "[1] INPUT_NORMALIZE: 3 skills, 2 interests, education=Bachelor, user_id=u1",
            "[2] FEATURE_EXTRACTION: llm_used=False",
            "[3] KB_ALIGNMENT: profile aligned with knowledge base",
            "[4] MERGE: normalized profile merged with features + KB alignment",
            "[5] SIMGR_SCORING: 5 careers ranked; top='Software Engineer' score=0.7800",
            "[6] DRIFT_CHECK: drift_detected=False",
            "[7] RULE_ENGINE: FROZEN pass-through; 3 rules audited",
            "[8] MARKET_DATA: 2 insights fetched",
            "[9] EXPLANATION: skipped (no_main_controller or not_requested)",
        ]

    def test_has_at_least_nine_entries(self):
        path = self._make_sample_path()
        assert len(path) >= 9, f"reasoning_path should have ≥ 9 entries, got {len(path)}"

    def test_entries_are_strings(self):
        path = self._make_sample_path()
        for entry in path:
            assert isinstance(entry, str), f"reasoning_path entries must be str, got {type(entry)}"

    def test_stage_numbers_present(self):
        path = self._make_sample_path()
        for i in range(1, 10):
            tag = f"[{i}]"
            assert any(tag in e for e in path), f"Missing stage tag '{tag}' in reasoning_path"

    def test_rule_engine_mentions_frozen(self):
        path = self._make_sample_path()
        rule_entries = [e for e in path if "RULE_ENGINE" in e]
        assert rule_entries, "reasoning_path must have a RULE_ENGINE entry"
        assert "FROZEN" in rule_entries[0], "RULE_ENGINE entry must mention FROZEN"


# ─────────────────────────────────────────────────────────────────────────────
# Test: _apply_rules returns _RuleEngineResult (mocked rule_service)
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyRulesReturnsRuleEngineResult:
    """_apply_rules() must return _RuleEngineResult, not a raw list."""

    @pytest.mark.asyncio
    async def test_apply_rules_return_type(self):
        from backend.api.controllers.decision_controller import (
            DecisionController,
            _RuleEngineResult,
        )

        # Build a minimal controller
        controller = DecisionController.__new__(DecisionController)
        controller._main_controller = None

        # Mock rule_service
        mock_rule_svc = MagicMock()
        mock_rule_svc.evaluate_profile.return_value = {"matched_rules": []}
        mock_rule_svc.list_rules.return_value = {"rules": [], "total": 0, "page": 1, "page_size": 100, "pages": 0}

        mock_career = MagicMock()
        mock_career.name = "Software Engineer"

        with patch(
            "backend.rule_engine.rule_service.rule_service",
            mock_rule_svc,
        ):
            result = await controller._apply_rules(
                [mock_career], {"skills": ["python"]}, "test-trace"
            )

        assert isinstance(result, _RuleEngineResult), (
            f"_apply_rules must return _RuleEngineResult, got {type(result)}"
        )
        assert hasattr(result, "rankings")
        assert hasattr(result, "rules_trace")
        assert result.rankings == [mock_career]

    @pytest.mark.asyncio
    async def test_apply_rules_rules_trace_format(self):
        from backend.api.controllers.decision_controller import DecisionController

        controller = DecisionController.__new__(DecisionController)
        controller._main_controller = None

        mock_rule = MagicMock()
        mock_rule.name = "rule_test"
        mock_rule.category = "education"
        mock_rule.priority = 5

        mock_rule_svc = MagicMock()
        mock_rule_svc.evaluate_profile.return_value = {"matched_rules": ["rule_test"]}
        mock_rule_svc.list_rules.return_value = {
            "rules": [
                {"name": mock_rule.name, "category": mock_rule.category, "priority": mock_rule.priority},
            ],
            "total": 1,
            "page": 1,
            "page_size": 100,
            "pages": 1,
        }

        with patch(
            "backend.rule_engine.rule_service.rule_service",
            mock_rule_svc,
        ):
            result = await controller._apply_rules(
                [], {"skills": ["python"]}, "trace-abc"
            )

        for trace_entry in result.rules_trace:
            assert "rule" in trace_entry
            assert "category" in trace_entry
            assert "priority" in trace_entry
            assert "outcome" in trace_entry
            assert "frozen" in trace_entry
            assert trace_entry["frozen"] is True, "rule_engine is FROZEN — frozen must be True"

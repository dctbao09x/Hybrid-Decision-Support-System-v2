# backend/tests/test_one_button_run.py
"""
P11 Tests — One-Button Full Orchestration Endpoint
====================================================

PASS criteria:
  • POST /api/v1/one-button/run exists and returns 200 on valid input.
  • All 8 mandatory stage names appear in the response ``stages`` dict.
  • No stage has status == "skipped".
  • ``stage_trace`` is an ordered list covering all internal stages.
  • ``diagnostics`` block is present and well-formed.
  • ``entrypoint`` == "/api/v1/one-button/run" and ``entrypoint_enforced`` == True.
  • TaxonomyValidationError → HTTP 400.
  • Pipeline ERROR → HTTP 500 (not swallowed as SUCCESS).
  • ``_validate_required_stages`` raises HTTP 500 for missing stages.
  • ``_validate_required_stages`` raises HTTP 500 for skipped stages.
  • ``_build_stage_result`` correctly maps internal log dicts.
  • ``_derive_taxonomy_validate_stage`` derives status from taxonomy_applied.
  • ``_assemble_response`` maps all 8 canonical stages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from backend.api.controllers.decision_controller import DecisionResponse


# ─────────────────────────────────────────────────────────────────────────────
# Helper factories
# ─────────────────────────────────────────────────────────────────────────────

def _make_stage_log() -> list:
    """Minimal stage_log covering all internal stages to trigger all 8 canonical stages."""
    return [
        {
            "stage": "input_normalize",
            "status": "ok",
            "duration_ms": 5.0,
            "input": {"user_id": "u1"},
            "output": {
                "skills_resolved": ["python"],
                "interests_resolved": ["technology"],
                "education_level": "Bachelor",
                "ability_score": 0.7,
                "taxonomy_applied": True,
            },
        },
        {
            "stage": "feature_extraction",
            "status": "ok",
            "duration_ms": 2.0,
            "input": {},
            "output": {"llm_extracted": False},
        },
        {
            "stage": "kb_alignment",
            "status": "ok",
            "duration_ms": 1.0,
            "input": {},
            "output": {},
        },
        {
            "stage": "merge",
            "status": "ok",
            "duration_ms": 1.0,
            "input": {},
            "output": {},
        },
        {
            "stage": "simgr_scoring",
            "status": "ok",
            "duration_ms": 20.0,
            "input": {},
            "output": {"careers_ranked": 3, "top_career": "Software Engineer"},
        },
        {
            "stage": "drift_check",
            "status": "ok",
            "duration_ms": 3.0,
            "input": {},
            "output": {"drift_detected": False},
        },
        {
            "stage": "rule_engine",
            "status": "frozen_pass_through",
            "duration_ms": 4.0,
            "input": {},
            "output": {"rules_audited": 2, "frozen": True},
        },
        {
            "stage": "market_data",
            "status": "ok",
            "duration_ms": 10.0,
            "input": {},
            "output": {"insights_count": 3},
        },
        {
            "stage": "explanation",
            "status": "ok",
            "duration_ms": 15.0,
            "input": {},
            "output": {"confidence": 0.85, "llm_used": True},
        },
    ]


def _make_meta():
    from backend.api.controllers.decision_controller import DecisionMeta
    return DecisionMeta(
        correlation_id="corr-test",
        pipeline_duration_ms=61.0,
        model_version="v1",
        weights_version="default",
        llm_used=True,
        stages_completed=[
            "input_normalize", "feature_extraction", "kb_alignment",
            "merge", "simgr_scoring", "drift_check", "rule_engine",
            "market_data", "explanation",
        ],
    )


def _make_inner_response(*, explanation_skipped: bool = False) -> "DecisionResponse":
    """Build a minimal valid DecisionResponse from the controller."""
    from backend.api.controllers.decision_controller import (
        DecisionResponse, CareerResult,
    )
    stage_log = _make_stage_log()
    if explanation_skipped:
        for s in stage_log:
            if s["stage"] == "explanation":
                s["status"] = "skipped"

    career = CareerResult(
        name="Software Engineer",
        domain="technology",
        total_score=0.85,
        skill_score=0.9,
        interest_score=0.8,
        market_score=0.85,
        growth_potential=0.75,
        ai_relevance=0.9,
    )
    return DecisionResponse(
        trace_id="dec-test000001",
        timestamp="2026-02-23T00:00:00+00:00",
        status="SUCCESS",
        rankings=[career],
        top_career=career,
        explanation=None,
        market_insights=[],
        meta=_make_meta(),
        stage_log=stage_log,
        rule_applied=[{"rule": "r1", "category": "c1", "priority": 1, "outcome": "pass", "frozen": True}],
        reasoning_path=["[1] INPUT: ok", "[2] SCORING: ok"],
        diagnostics={
            "total_latency_ms": 61.0,
            "stage_count": 9,
            "stage_passed": 8,
            "stage_skipped": 0,
            "stage_failed": 0,
            "slowest_stage": "simgr_scoring",
            "errors": [],
            "llm_used": True,
            "rules_audited": 2,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests — router helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildStageResult:
    def test_maps_fields_correctly(self):
        from backend.api.routers.one_button_router import _build_stage_result
        raw = {
            "stage": "simgr_scoring",
            "status": "ok",
            "duration_ms": 22.5,
            "input": {"key": "v"},
            "output": {"top": "SE"},
            "error": None,
        }
        result = _build_stage_result(raw)
        assert result.stage == "simgr_scoring"
        assert result.status == "ok"
        assert result.duration_ms == 22.5
        assert result.input == {"key": "v"}
        assert result.output == {"top": "SE"}

    def test_override_name(self):
        from backend.api.routers.one_button_router import _build_stage_result
        raw = {"stage": "simgr_scoring", "status": "ok", "duration_ms": 10.0}
        result = _build_stage_result(raw, override_name="scoring")
        assert result.stage == "scoring"

    def test_missing_fields_default(self):
        from backend.api.routers.one_button_router import _build_stage_result
        result = _build_stage_result({})
        assert result.stage == "unknown"
        assert result.status == "unknown"
        assert result.duration_ms == 0.0


class TestDeriveTaxonomyValidateStage:
    def test_taxonomy_ok_when_applied(self):
        from backend.api.routers.one_button_router import _derive_taxonomy_validate_stage
        raw = {
            "output": {
                "taxonomy_applied": True,
                "skills_resolved": ["python"],
                "interests_resolved": ["tech"],
                "education_level": "Bachelor",
            }
        }
        result = _derive_taxonomy_validate_stage(raw)
        assert result.stage == "taxonomy_validate"
        assert result.status == "ok"
        assert result.output["validation_passed"] is True
        assert result.error is None

    def test_taxonomy_error_when_not_applied(self):
        from backend.api.routers.one_button_router import _derive_taxonomy_validate_stage
        raw = {"output": {"taxonomy_applied": False}}
        result = _derive_taxonomy_validate_stage(raw)
        assert result.status == "error"
        assert result.output["validation_passed"] is False

    def test_empty_raw_is_error(self):
        from backend.api.routers.one_button_router import _derive_taxonomy_validate_stage
        result = _derive_taxonomy_validate_stage({})
        assert result.status == "error"


class TestValidateRequiredStages:
    def test_passes_when_all_present(self):
        from backend.api.routers.one_button_router import (
            _validate_required_stages, REQUIRED_STAGES, StageResult,
        )
        stages = {
            name: StageResult(stage=name, status="ok", duration_ms=1.0)
            for name in REQUIRED_STAGES
        }
        _validate_required_stages(stages)  # must not raise

    def test_raises_500_on_missing_stage(self):
        from fastapi import HTTPException
        from backend.api.routers.one_button_router import (
            _validate_required_stages, REQUIRED_STAGES, StageResult,
        )
        stages = {
            name: StageResult(stage=name, status="ok", duration_ms=1.0)
            for name in REQUIRED_STAGES
            if name != "explain"
        }
        with pytest.raises(HTTPException) as exc_info:
            _validate_required_stages(stages)
        assert exc_info.value.status_code == 500
        assert "explain" in exc_info.value.detail["missing_stages"]

    def test_raises_500_on_skipped_stage(self):
        from fastapi import HTTPException
        from backend.api.routers.one_button_router import (
            _validate_required_stages, REQUIRED_STAGES, StageResult,
        )
        stages = {
            name: StageResult(stage=name, status="ok", duration_ms=1.0)
            for name in REQUIRED_STAGES
        }
        stages["scoring"] = StageResult(stage="scoring", status="skipped", duration_ms=0.0)
        with pytest.raises(HTTPException) as exc_info:
            _validate_required_stages(stages)
        assert exc_info.value.status_code == 500
        assert "scoring" in exc_info.value.detail["skipped_stages"]


class TestAssembleResponse:
    def test_all_8_stages_present(self):
        from backend.api.routers.one_button_router import (
            _assemble_response, REQUIRED_STAGES,
        )
        inner = _make_inner_response()
        result = _assemble_response(inner)
        for stage_name in REQUIRED_STAGES:
            assert stage_name in result.stages, f"Stage '{stage_name}' missing from response"

    def test_no_stage_is_skipped(self):
        from backend.api.routers.one_button_router import _assemble_response
        inner = _make_inner_response()
        result = _assemble_response(inner)
        for name, stage in result.stages.items():
            assert stage.status != "skipped", f"Stage '{name}' must not be skipped"

    def test_explain_forced_ok_even_if_inner_skipped(self):
        """explanation=skipped in inner response → reclassified to ok in one-button."""
        from backend.api.routers.one_button_router import _assemble_response
        inner = _make_inner_response(explanation_skipped=True)
        result = _assemble_response(inner)
        assert result.stages["explain"].status != "skipped"

    def test_entrypoint_fields(self):
        from backend.api.routers.one_button_router import _assemble_response
        inner = _make_inner_response()
        result = _assemble_response(inner)
        assert result.entrypoint == "/api/v1/one-button/run"
        assert result.entrypoint_enforced is True

    def test_stage_trace_is_ordered_list(self):
        from backend.api.routers.one_button_router import _assemble_response
        inner = _make_inner_response()
        result = _assemble_response(inner)
        assert isinstance(result.stage_trace, list)
        assert len(result.stage_trace) > 0
        stage_names = [s.stage for s in result.stage_trace]
        assert "input_normalize" in stage_names

    def test_diagnostics_block_present(self):
        from backend.api.routers.one_button_router import _assemble_response
        inner = _make_inner_response()
        result = _assemble_response(inner)
        assert isinstance(result.diagnostics, dict)
        assert "total_latency_ms" in result.diagnostics
        assert "stage_passed" in result.diagnostics

    def test_rankings_serialised(self):
        from backend.api.routers.one_button_router import _assemble_response
        inner = _make_inner_response()
        result = _assemble_response(inner)
        assert isinstance(result.rankings, list)
        assert len(result.rankings) == 1
        assert result.rankings[0]["name"] == "Software Engineer"

    def test_top_career_serialised(self):
        from backend.api.routers.one_button_router import _assemble_response
        inner = _make_inner_response()
        result = _assemble_response(inner)
        assert result.top_career is not None
        assert result.top_career["name"] == "Software Engineer"

    def test_contract_fields_present(self):
        from backend.api.routers.one_button_router import _assemble_response
        inner = _make_inner_response()
        result = _assemble_response(inner)
        assert result.contract_version == "2026-04-02.v1"
        assert result.response_schema_version == "one_button.response.v1"
        assert result.stage_manifest == [
            "taxonomy_normalize",
            "taxonomy_validate",
            "rule_engine",
            "ml_predict",
            "scoring",
            "explain",
            "diagnostics",
            "stage_trace",
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests — HTTP layer
# ─────────────────────────────────────────────────────────────────────────────

def _make_app_with_mock_controller(inner_response) -> FastAPI:
    """Build a minimal FastAPI app with a mocked DecisionController."""
    from fastapi import FastAPI
    from backend.api.routers.one_button_router import (
        router as ob_router,
        set_controller,
    )

    mock_ctrl = MagicMock()
    mock_ctrl.run_pipeline = AsyncMock(return_value=inner_response)
    set_controller(mock_ctrl)

    app = FastAPI()
    app.include_router(ob_router)
    return app


def _make_app_with_mock_controller_and_legacy(inner_response) -> FastAPI:
    """Build app with canonical one-button + legacy /decision/run alias."""
    from backend.api.routers.one_button_router import (
        router as ob_router,
        set_controller,
    )
    from backend.api.routers.decision_legacy_router import router as legacy_router

    mock_ctrl = MagicMock()
    mock_ctrl.run_pipeline = AsyncMock(return_value=inner_response)
    set_controller(mock_ctrl)

    app = FastAPI()
    app.include_router(ob_router)
    app.include_router(legacy_router)
    return app


def _minimal_request_body() -> dict:
    return {
        "user_id": "test_user_p11",
        "scoring_input": {
            "personal_profile": {
                "ability_score": 0.7,
                "confidence_score": 0.65,
                "interests": ["technology", "science"],
            },
            "experience": {"years": 3, "domains": ["software development"]},
            "goals": {"career_aspirations": ["software engineer"], "timeline_years": 5},
            "skills": ["python", "sql"],
            "education": {"level": "Bachelor", "field_of_study": "Computer Science"},
            "preferences": {"preferred_domains": ["technology"], "work_style": "remote"},
        },
    }


class TestOneButtonEndpointHTTP:
    """HTTP-level integration tests for POST /api/v1/one-button/run."""

    def test_200_on_valid_request(self):
        inner = _make_inner_response()
        app = _make_app_with_mock_controller(inner)
        client = TestClient(app)
        resp = client.post("/api/v1/one-button/run", json=_minimal_request_body())
        assert resp.status_code == 200, resp.text

    def test_response_contains_all_8_stages(self):
        inner = _make_inner_response()
        app = _make_app_with_mock_controller(inner)
        client = TestClient(app)
        resp = client.post("/api/v1/one-button/run", json=_minimal_request_body())
        data = resp.json()
        from backend.api.routers.one_button_router import REQUIRED_STAGES
        for stage_name in REQUIRED_STAGES:
            assert stage_name in data["stages"], f"'{stage_name}' missing from response stages"

    def test_no_stage_skipped_in_response(self):
        inner = _make_inner_response()
        app = _make_app_with_mock_controller(inner)
        client = TestClient(app)
        resp = client.post("/api/v1/one-button/run", json=_minimal_request_body())
        data = resp.json()
        for name, stage in data["stages"].items():
            assert stage["status"] != "skipped", (
                f"Stage '{name}' must not be skipped in one-button response"
            )

    def test_entrypoint_enforced_in_response(self):
        inner = _make_inner_response()
        app = _make_app_with_mock_controller(inner)
        client = TestClient(app)
        data = client.post("/api/v1/one-button/run", json=_minimal_request_body()).json()
        assert data["entrypoint"] == "/api/v1/one-button/run"
        assert data["entrypoint_enforced"] is True

    def test_stage_trace_present_and_non_empty(self):
        inner = _make_inner_response()
        app = _make_app_with_mock_controller(inner)
        client = TestClient(app)
        data = client.post("/api/v1/one-button/run", json=_minimal_request_body()).json()
        assert isinstance(data["stage_trace"], list)
        assert len(data["stage_trace"]) > 0

    def test_diagnostics_present(self):
        inner = _make_inner_response()
        app = _make_app_with_mock_controller(inner)
        client = TestClient(app)
        data = client.post("/api/v1/one-button/run", json=_minimal_request_body()).json()
        assert data["diagnostics"] is not None
        assert "total_latency_ms" in data["diagnostics"]

    def test_contract_versions_and_manifest_present(self):
        inner = _make_inner_response()
        app = _make_app_with_mock_controller(inner)
        client = TestClient(app)
        data = client.post("/api/v1/one-button/run", json=_minimal_request_body()).json()
        assert data["contract_version"] == "2026-04-02.v1"
        assert data["response_schema_version"] == "one_button.response.v1"
        assert isinstance(data["stage_manifest"], list)
        assert len(data["stage_manifest"]) == 8

    def test_idempotency_replay_returns_cached_response(self):
        inner = _make_inner_response()
        app = _make_app_with_mock_controller(inner)
        client = TestClient(app)

        headers = {"Idempotency-Key": "idem-test-key-1"}
        first = client.post("/api/v1/one-button/run", json=_minimal_request_body(), headers=headers)
        second = client.post("/api/v1/one-button/run", json=_minimal_request_body(), headers=headers)

        assert first.status_code == 200
        assert second.status_code == 200
        first_body = first.json()
        second_body = second.json()
        assert first_body["trace_id"] == second_body["trace_id"]
        assert second_body["idempotency"]["status"] == "replayed"
        assert second_body["idempotency"]["replayed"] is True

    def test_400_on_contract_version_mismatch(self):
        inner = _make_inner_response()
        app = _make_app_with_mock_controller(inner)
        client = TestClient(app)

        payload = _minimal_request_body()
        payload["contract_version"] = "legacy-v0"
        resp = client.post("/api/v1/one-button/run", json=payload)
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "ONE_BUTTON_CONTRACT_VERSION_MISMATCH"

    def test_400_on_taxonomy_validation_error(self):
        from backend.api.taxonomy_gate import TaxonomyValidationError
        from backend.api.routers.one_button_router import set_controller
        from fastapi import FastAPI
        from backend.api.routers.one_button_router import router as ob_router

        mock_ctrl = MagicMock()
        mock_ctrl.run_pipeline = AsyncMock(
            side_effect=TaxonomyValidationError(
                "No skills resolved",
                detail={"field": "skills", "raw_values": [], "trace_id": "t1"},
            )
        )
        set_controller(mock_ctrl)
        app = FastAPI()
        app.include_router(ob_router)
        client = TestClient(app)

        resp = client.post("/api/v1/one-button/run", json=_minimal_request_body())
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "TAXONOMY_VALIDATION_FAILED"

    def test_500_on_pipeline_error_status(self):
        """Controller returns status=ERROR → endpoint must return HTTP 500."""
        from backend.api.controllers.decision_controller import DecisionResponse
        inner_error = DecisionResponse(
            trace_id="dec-err001",
            timestamp="2026-02-23T00:00:00+00:00",
            status="ERROR",
            rankings=[],
            top_career=None,
            explanation=None,
            market_insights=[],
            meta=_make_meta(),
            stage_log=[],
            rule_applied=[],
            reasoning_path=["[ERROR] Pipeline failed"],
        )
        app = _make_app_with_mock_controller(inner_error)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/one-button/run", json=_minimal_request_body())
        assert resp.status_code == 500

    def test_422_on_missing_required_field(self):
        """Omitting scoring_input → FastAPI returns 422 validation error."""
        inner = _make_inner_response()
        app = _make_app_with_mock_controller(inner)
        client = TestClient(app)
        resp = client.post("/api/v1/one-button/run", json={"user_id": "u1"})
        assert resp.status_code == 422

    def test_422_on_extra_forbidden_field(self):
        inner = _make_inner_response()
        app = _make_app_with_mock_controller(inner)
        client = TestClient(app)
        payload = _minimal_request_body()
        payload["options"] = {"include_explanation": True}
        resp = client.post("/api/v1/one-button/run", json=payload)
        assert resp.status_code == 422

    def test_legacy_endpoint_has_deprecation_headers(self):
        inner = _make_inner_response()
        app = _make_app_with_mock_controller_and_legacy(inner)
        client = TestClient(app)

        resp = client.post("/api/v1/decision/run", json=_minimal_request_body())
        assert resp.status_code == 200
        assert resp.headers.get("Deprecation") == "true"
        assert resp.headers.get("Sunset") is not None
        assert "/api/v1/one-button/run" in (resp.headers.get("Link") or "")

    def test_health_endpoint(self):
        inner = _make_inner_response()
        app = _make_app_with_mock_controller(inner)
        client = TestClient(app)
        resp = client.get("/api/v1/one-button/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "one-button"
        assert data["entrypoint"] == "/api/v1/one-button/run"
        assert data["required_stages"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# Structural invariants
# ─────────────────────────────────────────────────────────────────────────────

class TestOneButtonInvariants:
    """Verify structural guarantees of the one-button module itself."""

    def test_required_stages_has_8_entries(self):
        from backend.api.routers.one_button_router import REQUIRED_STAGES
        assert len(REQUIRED_STAGES) == 8, (
            f"Expected 8 required stages, got {len(REQUIRED_STAGES)}: {REQUIRED_STAGES}"
        )

    def test_required_stages_contains_all_canonical_names(self):
        from backend.api.routers.one_button_router import REQUIRED_STAGES
        expected = {
            "taxonomy_normalize", "taxonomy_validate",
            "rule_engine", "ml_predict", "scoring",
            "explain", "diagnostics", "stage_trace",
        }
        assert set(REQUIRED_STAGES) == expected

    def test_router_has_post_run_route(self):
        from backend.api.routers.one_button_router import router
        routes = {r.path: r for r in router.routes}  # type: ignore[attr-defined]
        assert "/api/v1/one-button/run" in routes, (
            "POST /api/v1/one-button/run route not found in router"
        )

    def test_router_prefix(self):
        from backend.api.routers.one_button_router import router
        assert router.prefix == "/api/v1/one-button"

    def test_stage_map_covers_controller_stages(self):
        from backend.api.routers.one_button_router import _STAGE_MAP
        required_internal = {
            "input_normalize", "feature_extraction", "simgr_scoring",
            "rule_engine", "explanation",
        }
        assert required_internal.issubset(set(_STAGE_MAP.keys()))

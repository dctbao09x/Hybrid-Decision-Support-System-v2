from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.taxonomy_gate import TaxonomyValidationError


CONTRACT_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "one_button_consumer_contract_v1.json"
)


@pytest.fixture(scope="module")
def contract_fixture() -> Dict[str, Any]:
    return json.loads(CONTRACT_FIXTURE_PATH.read_text(encoding="utf-8"))


def _build_stage_log(*, explanation_status: str = "ok") -> list[dict[str, Any]]:
    return [
        {
            "stage": "input_normalize",
            "status": "ok",
            "duration_ms": 4.0,
            "input": {"raw": True},
            "output": {
                "skills_resolved": ["python"],
                "interests_resolved": ["technology"],
                "education_level": "Bachelor",
                "taxonomy_applied": True,
            },
        },
        {
            "stage": "feature_extraction",
            "status": "ok",
            "duration_ms": 3.0,
            "input": {},
            "output": {"llm_extracted": True},
        },
        {
            "stage": "simgr_scoring",
            "status": "ok",
            "duration_ms": 12.0,
            "input": {},
            "output": {"careers_ranked": 2},
        },
        {
            "stage": "rule_engine",
            "status": "frozen_pass_through",
            "duration_ms": 5.0,
            "input": {},
            "output": {"rules_audited": 1},
        },
        {
            "stage": "explanation",
            "status": explanation_status,
            "duration_ms": 7.0,
            "input": {},
            "output": {"confidence": 0.8, "llm_used": False},
        },
    ]


def _build_inner_response(*, explanation_status: str = "ok"):
    from backend.api.controllers.decision_controller import (
        CareerResult,
        DecisionMeta,
        DecisionResponse,
    )

    top = CareerResult(
        name="Software Engineer",
        domain="technology",
        total_score=0.84,
        skill_score=0.88,
        interest_score=0.79,
        market_score=0.82,
        growth_potential=0.76,
        ai_relevance=0.9,
    )

    meta = DecisionMeta(
        correlation_id="contract-corr-001",
        pipeline_duration_ms=42.0,
        model_version="v1",
        weights_version="default",
        llm_used=False,
        stages_completed=[
            "input_normalize",
            "feature_extraction",
            "simgr_scoring",
            "rule_engine",
            "explanation",
        ],
    )

    return DecisionResponse(
        trace_id="contract-trace-001",
        timestamp="2026-04-02T00:00:00+00:00",
        status="SUCCESS",
        rankings=[top],
        top_career=top,
        scoring_breakdown={
            "ml_score": 0.85,
            "rule_score": 0.8,
            "penalty": 0.01,
            "final_score": 0.84,
            "result_hash": "hash-001",
        },
        explanation={
            "summary": "Ban co nen tang ky nang Python va SQL de tang do phu hop.",
            "factors": [
                {
                    "name": "skills",
                    "contribution": 0.4,
                    "description": "Python va SQL phu hop voi nhom nghe cong nghe",
                }
            ],
            "confidence": 0.8,
            "reasoning_chain": ["skills -> scoring -> explanation"],
        },
        market_insights=[],
        meta=meta,
        stage_log=_build_stage_log(explanation_status=explanation_status),
        rule_applied=[{"rule": "r1", "category": "core", "priority": 1, "outcome": "pass", "frozen": True}],
        reasoning_path=["[1] taxonomy", "[2] scoring", "[3] explain"],
        diagnostics={
            "total_latency_ms": 42.0,
            "stage_count": 5,
            "stage_passed": 5,
            "stage_skipped": 0,
            "stage_failed": 0,
            "slowest_stage": "simgr_scoring",
            "errors": [],
            "llm_used": False,
            "rules_audited": 1,
        },
    )


def _build_one_button_app(*, inner_response=None, side_effect=None) -> FastAPI:
    from backend.api.routers.one_button_router import router as one_button_router
    from backend.api.routers.one_button_router import set_controller

    app = FastAPI()
    mock_controller = MagicMock()

    if side_effect is not None:
        mock_controller.run_pipeline = AsyncMock(side_effect=side_effect)
    else:
        mock_controller.run_pipeline = AsyncMock(return_value=inner_response or _build_inner_response())

    set_controller(mock_controller)
    app.include_router(one_button_router)
    return app


@pytest.mark.contract
@pytest.mark.schema_regression
@pytest.mark.regression
def test_frontend_payload_e2e_backend_response_schema(contract_fixture: Dict[str, Any]) -> None:
    from backend.api.routers.one_button_router import OneButtonResponse

    app = _build_one_button_app(inner_response=_build_inner_response())
    client = TestClient(app)

    response = client.post(
        contract_fixture["canonical_endpoint"],
        json=contract_fixture["frontend_request_sample"],
    )

    assert response.status_code == 200, response.text
    payload = response.json()

    # Strict schema validation via backend response model.
    parsed = OneButtonResponse.model_validate(payload)
    assert parsed.contract_version == contract_fixture["contract_version"]
    assert parsed.response_schema_version == contract_fixture["response_schema_version"]
    assert parsed.stage_manifest == contract_fixture["required_stage_manifest"]

    for key in contract_fixture["required_response_fields"]:
        assert key in payload, f"Missing response field: {key}"


@pytest.mark.contract
def test_error_semantics_contract_version_mismatch(contract_fixture: Dict[str, Any]) -> None:
    app = _build_one_button_app(inner_response=_build_inner_response())
    client = TestClient(app)

    bad_payload = dict(contract_fixture["frontend_request_sample"])
    bad_payload["contract_version"] = "legacy-v0"

    response = client.post(contract_fixture["canonical_endpoint"], json=bad_payload)
    body = response.json()

    expected = contract_fixture["error_semantics"]["contract_version_mismatch"]
    assert response.status_code == expected["status_code"]
    assert body["detail"]["error"] == expected["error"]
    assert body["detail"]["retryable"] == expected["retryable"]


@pytest.mark.contract
def test_error_semantics_taxonomy_validation_failure(contract_fixture: Dict[str, Any]) -> None:
    app = _build_one_button_app(
        side_effect=TaxonomyValidationError(
            "No skills resolved",
            detail={"field": "skills", "raw_values": [], "trace_id": "tx-1"},
        )
    )
    client = TestClient(app)

    response = client.post(
        contract_fixture["canonical_endpoint"],
        json=contract_fixture["frontend_request_sample"],
    )
    body = response.json()

    expected = contract_fixture["error_semantics"]["taxonomy_validation_failed"]
    assert response.status_code == expected["status_code"]
    assert body["detail"]["error"] == expected["error"]
    assert body["detail"]["retryable"] == expected["retryable"]


@pytest.mark.contract
@pytest.mark.schema_regression
@pytest.mark.regression
def test_stage_manifest_and_fallback_behavior(contract_fixture: Dict[str, Any]) -> None:
    app = _build_one_button_app(inner_response=_build_inner_response(explanation_status="skipped"))
    client = TestClient(app)

    response = client.post(
        contract_fixture["canonical_endpoint"],
        json=contract_fixture["frontend_request_sample"],
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["stage_manifest"] == contract_fixture["required_stage_manifest"]
    for stage_name in contract_fixture["required_stage_manifest"]:
        assert payload["stages"][stage_name]["status"] != "skipped"


@pytest.mark.contract
def test_router_registry_alignment_with_one_button_contract(contract_fixture: Dict[str, Any]) -> None:
    from backend.api.router_registry import AuthLevel, get_all_routers
    from backend.api.routers.one_button_router import REQUIRED_STAGES

    routers = get_all_routers()
    one_button = [r for r in routers if r.name == "one_button"]
    assert len(one_button) == 1
    assert one_button[0].auth == AuthLevel.USER

    assert list(REQUIRED_STAGES) == contract_fixture["required_stage_manifest"]


@pytest.mark.contract
@pytest.mark.schema_regression
@pytest.mark.regression
def test_consumer_driven_frontend_backend_constant_compatibility(contract_fixture: Dict[str, Any]) -> None:
    from backend.api.routers.one_button_router import (
        CANONICAL_ONE_BUTTON_ENDPOINT,
        ONE_BUTTON_CONTRACT_VERSION,
        ONE_BUTTON_REQUEST_SCHEMA_VERSION,
        ONE_BUTTON_RESPONSE_SCHEMA_VERSION,
    )

    frontend_path = Path(__file__).resolve().parents[2] / "ui-vite" / "src" / "services" / "decisionApi.ts"
    source = frontend_path.read_text(encoding="utf-8")

    endpoint_match = re.search(r"DECISION_ENDPOINT\s*=\s*`\$\{API_BASE_URL\}(/api/v1/one-button/run)`", source)
    contract_match = re.search(r"CONTRACT_VERSION\s*=\s*'([^']+)'", source)
    request_schema_match = re.search(r"REQUEST_SCHEMA_VERSION\s*=\s*'([^']+)'", source)

    assert endpoint_match is not None
    assert contract_match is not None
    assert request_schema_match is not None

    assert endpoint_match.group(1) == CANONICAL_ONE_BUTTON_ENDPOINT
    assert contract_match.group(1) == ONE_BUTTON_CONTRACT_VERSION
    assert request_schema_match.group(1) == ONE_BUTTON_REQUEST_SCHEMA_VERSION

    assert contract_fixture["canonical_endpoint"] == CANONICAL_ONE_BUTTON_ENDPOINT
    assert contract_fixture["contract_version"] == ONE_BUTTON_CONTRACT_VERSION
    assert contract_fixture["request_schema_version"] == ONE_BUTTON_REQUEST_SCHEMA_VERSION
    assert contract_fixture["response_schema_version"] == ONE_BUTTON_RESPONSE_SCHEMA_VERSION

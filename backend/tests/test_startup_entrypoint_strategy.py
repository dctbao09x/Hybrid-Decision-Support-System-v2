"""Startup entrypoint strategy validation tests.

These tests enforce the production startup contract:
1. Canonical process entrypoint is backend.run_api:app
2. run_api route table remains a superset of gateway factory routes
3. Startup health/contract routes are mounted and introspectable
"""

from __future__ import annotations

from typing import Set

from fastapi.testclient import TestClient

from backend import run_api
from backend.inference.api_server_v2 import (
    CANONICAL_STARTUP_ENTRYPOINT,
    REQUIRED_STARTUP_ROUTES,
    create_inference_api,
)


def _route_paths(app) -> Set[str]:
    return {
        route.path
        for route in app.routes
        if hasattr(route, "methods")
    }


def test_canonical_entrypoint_is_run_api() -> None:
    assert run_api.CANONICAL_ENTRYPOINT == CANONICAL_STARTUP_ENTRYPOINT
    assert run_api.CANONICAL_ENTRYPOINT == "backend.run_api:app"


def test_run_api_registers_startup_health_routes() -> None:
    paths = _route_paths(run_api.app)
    assert "/api/v1/health/startup" in paths
    assert "/api/v1/health/startup/contract" in paths


def test_route_parity_run_api_is_superset_of_gateway_factory() -> None:
    gateway_api = create_inference_api(strict_startup_validation=False)

    gateway_paths = _route_paths(gateway_api.app)
    run_api_paths = _route_paths(run_api.app)

    missing_from_run_api = sorted(gateway_paths.difference(run_api_paths))
    assert not missing_from_run_api, (
        "run_api is missing routes from create_inference_api: "
        f"{missing_from_run_api[:20]}"
    )

    for required_path in REQUIRED_STARTUP_ROUTES:
        assert required_path in run_api_paths


def test_startup_contract_report_contains_validation() -> None:
    contract = run_api._api.get_startup_contract()

    assert contract.get("canonical_entrypoint") == CANONICAL_STARTUP_ENTRYPOINT
    assert "dependency_loading_order" in contract
    assert "router_registration_order" in contract
    assert "validation" in contract
    assert isinstance(contract["validation"], dict)


def test_startup_contract_endpoint_smoke() -> None:
    client = TestClient(run_api.app)
    response = client.get("/api/v1/health/startup/contract")

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("canonical_entrypoint") == CANONICAL_STARTUP_ENTRYPOINT
    assert payload.get("strict_startup_validation") is True
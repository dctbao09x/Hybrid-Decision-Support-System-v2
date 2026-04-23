from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Set

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend import run_api
from backend.api.routers.health_router import router as health_router
from backend.api.routers.one_button_router import router as one_button_router


CONTRACT_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "one_button_consumer_contract_v1.json"
)
MAIN_MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"

_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


@pytest.fixture(scope="module")
def contract_fixture() -> Dict[str, Any]:
    return json.loads(CONTRACT_FIXTURE_PATH.read_text(encoding="utf-8"))


def _normalize_path(prefix: str, route_path: str) -> str:
    if not prefix:
        return route_path
    return f"{prefix.rstrip('/')}/{route_path.lstrip('/')}"


def _route_methods_from_fastapi_router(*, prefix: str, routes: Iterable[Any]) -> Dict[str, Set[str]]:
    route_map: Dict[str, Set[str]] = {}
    for route in routes:
        if not isinstance(route, APIRoute):
            continue
        full_path = _normalize_path(prefix, route.path)
        route_map.setdefault(full_path, set()).update(m for m in (route.methods or set()) if m in _HTTP_METHODS)
    return route_map


def _extract_main_include_router_prefixes() -> Dict[str, str]:
    source = MAIN_MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    include_map: Dict[str, str] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "include_router":
            continue
        if not node.args:
            continue

        first_arg = node.args[0]
        if not isinstance(first_arg, ast.Name):
            continue

        prefix = ""
        for keyword in node.keywords:
            if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                prefix = keyword.value.value
                break

        include_map[first_arg.id] = prefix

    return include_map


def _main_declared_routes() -> Dict[str, Set[str]]:
    include_prefixes = _extract_main_include_router_prefixes()
    known_routers: Mapping[str, Any] = {
        "one_button_router": one_button_router,
        "health_router": health_router,
    }

    route_map: Dict[str, Set[str]] = {}
    for router_name, router in known_routers.items():
        if router_name not in include_prefixes:
            continue
        merged = _route_methods_from_fastapi_router(prefix=include_prefixes[router_name], routes=router.routes)
        for path, methods in merged.items():
            route_map.setdefault(path, set()).update(methods)

    return route_map


def _run_api_routes() -> Dict[str, Set[str]]:
    return _route_methods_from_fastapi_router(prefix="", routes=run_api.app.routes)


@pytest.mark.contract
@pytest.mark.startup_parity
def test_required_startup_routes_exist_in_main_and_run_api(contract_fixture: Dict[str, Any]) -> None:
    required_routes = set(contract_fixture["startup_parity_required_routes"])

    main_routes = _main_declared_routes()
    run_api_routes = _run_api_routes()

    missing_in_main = sorted(required_routes.difference(main_routes.keys()))
    missing_in_run_api = sorted(required_routes.difference(run_api_routes.keys()))

    assert not missing_in_main, f"Required startup-parity routes missing in backend.main: {missing_in_main}"
    assert not missing_in_run_api, f"Required startup-parity routes missing in backend.run_api: {missing_in_run_api}"


@pytest.mark.contract
@pytest.mark.startup_parity
def test_required_startup_route_methods_are_parity_aligned(contract_fixture: Dict[str, Any]) -> None:
    main_routes = _main_declared_routes()
    run_api_routes = _run_api_routes()

    required_routes = contract_fixture["startup_parity_required_routes"]
    for path in required_routes:
        assert path in main_routes
        assert path in run_api_routes
        assert main_routes[path] == run_api_routes[path], (
            f"Method mismatch for {path}: main={sorted(main_routes[path])}, "
            f"run_api={sorted(run_api_routes[path])}"
        )


@pytest.mark.contract
@pytest.mark.startup_parity
def test_run_api_startup_contract_endpoint_reports_canonical_metadata() -> None:
    client = TestClient(run_api.app)

    response = client.get("/api/v1/health/startup/contract")
    assert response.status_code == 200

    payload = response.json()
    assert payload.get("canonical_entrypoint") == run_api.CANONICAL_ENTRYPOINT
    assert payload.get("strict_startup_validation") is True
    assert isinstance(payload.get("validation"), dict)


@pytest.mark.contract
@pytest.mark.startup_parity
def test_startup_probe_contract_shape_is_backward_compatible() -> None:
    client = TestClient(run_api.app)

    response = client.get("/api/v1/health/startup")
    assert response.status_code in {200, 503}

    payload = response.json()
    assert "startup_complete" in payload
    assert "status" in payload
    if "canonical_entrypoint" in payload:
        assert payload["canonical_entrypoint"] == run_api.CANONICAL_ENTRYPOINT

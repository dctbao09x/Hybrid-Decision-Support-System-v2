# backend/tests/test_taxonomy_list.py
"""
P9 Tests — GET /api/v1/taxonomy/list
=====================================

PASS criteria:
- /taxonomy/list returns 200 with correct structure
- Response contains skills, interests, education arrays
- Each item has {id, label} shape
- Deprecated entries are excluded
- No hardcoded taxonomy values required in test expectations
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routers.taxonomy_router import router as taxonomy_router


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """Minimal app with just the taxonomy router mounted."""
    app = FastAPI()
    app.include_router(taxonomy_router, prefix="/api/v1/taxonomy")
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# Tests: /list endpoint
# ─────────────────────────────────────────────────────────────────────────────

class TestTaxonomyListEndpoint:

    def test_returns_200(self, client: TestClient):
        resp = client.get("/api/v1/taxonomy/list")
        assert resp.status_code == 200

    def test_response_has_success_flag(self, client: TestClient):
        data = client.get("/api/v1/taxonomy/list").json()
        assert data.get("status") == "ok"

    def test_response_contains_three_datasets(self, client: TestClient):
        body = client.get("/api/v1/taxonomy/list").json()
        payload = body["data"]
        for key in ("skills", "interests", "education"):
            assert key in payload, f"Missing key: {key}"

    def test_each_entry_has_id_and_label(self, client: TestClient):
        body = client.get("/api/v1/taxonomy/list").json()
        payload = body["data"]
        for dataset_name in ("skills", "interests", "education"):
            entries = payload[dataset_name]
            assert isinstance(entries, list), f"{dataset_name} should be a list"
            for item in entries:
                assert "id" in item, f"{dataset_name} item missing 'id': {item}"
                assert "label" in item, f"{dataset_name} item missing 'label': {item}"
                assert isinstance(item["id"], str), f"id must be string"
                assert isinstance(item["label"], str), f"label must be string"

    def test_skills_non_empty(self, client: TestClient):
        body = client.get("/api/v1/taxonomy/list").json()
        assert len(body["data"]["skills"]) > 0

    def test_interests_non_empty(self, client: TestClient):
        body = client.get("/api/v1/taxonomy/list").json()
        assert len(body["data"]["interests"]) > 0

    def test_education_non_empty(self, client: TestClient):
        body = client.get("/api/v1/taxonomy/list").json()
        assert len(body["data"]["education"]) > 0

    def test_no_deprecated_entries_in_skills(self, client: TestClient):
        """Deprecated entries must not appear in the list."""
        from backend.api.routers.taxonomy_router import get_taxonomy_manager
        manager = get_taxonomy_manager()
        ds = manager.get_dataset("skills")
        deprecated_ids = {e.id for e in ds.entries if e.deprecated}

        body = client.get("/api/v1/taxonomy/list").json()
        returned_ids = {item["id"] for item in body["data"]["skills"]}
        overlap = deprecated_ids & returned_ids
        assert len(overlap) == 0, f"Deprecated skill IDs returned: {overlap}"

    def test_no_deprecated_entries_in_education(self, client: TestClient):
        from backend.api.routers.taxonomy_router import get_taxonomy_manager
        manager = get_taxonomy_manager()
        ds = manager.get_dataset("education")
        deprecated_ids = {e.id for e in ds.entries if e.deprecated}

        body = client.get("/api/v1/taxonomy/list").json()
        returned_ids = {item["id"] for item in body["data"]["education"]}
        overlap = deprecated_ids & returned_ids
        assert len(overlap) == 0, f"Deprecated education IDs returned: {overlap}"

    def test_no_auth_required(self, client: TestClient):
        """Public endpoint — no Authorization header needed."""
        resp = client.get("/api/v1/taxonomy/list")
        # Must not return 401 or 403
        assert resp.status_code not in (401, 403)

    def test_endpoint_distinct_from_dataset_route(self, client: TestClient):
        """Ensure /list is not handled by /{dataset} — it returns the multi-dataset shape."""
        body = client.get("/api/v1/taxonomy/list").json()
        # Multi-dataset response has 'data' with multiple keys
        assert isinstance(body.get("data"), dict)
        assert len(body["data"]) == 3

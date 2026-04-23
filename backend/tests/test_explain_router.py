# backend/tests/test_explain_router.py
"""
Comprehensive tests for Explain Router API endpoints.

Tests:
    - History endpoint
    - Stats endpoint
    - Graph endpoints
    - Calibration endpoints
    - Legal hold endpoints
    - PDF export endpoint
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.explain.router import router
from backend.explain.storage import ExplanationStorage


# Create test app
app = FastAPI()
app.include_router(router, prefix="/api/v1")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_storage(tmp_path):
    """Create mock storage for testing."""
    storage = ExplanationStorage(db_path=tmp_path / "test_router.db")
    
    async def init():
        await storage.initialize()
    asyncio.run(init())
    
    return storage


class TestHistoryEndpoint:
    """Tests for /explain/history endpoint."""

    def test_history_default_params(self, client):
        """GET /history with default params should return 200."""
        with patch("backend.explain.router.get_explanation_storage") as mock:
            mock_storage = MagicMock()
            mock_storage.get_history = AsyncMock(return_value=[])
            mock.return_value = mock_storage

            response = client.get(
                "/api/v1/explain/history",
                headers={"X-Role": "viewer"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert "count" in data

    def test_history_with_date_range(self, client):
        """GET /history with date range should filter results."""
        with patch("backend.explain.router.get_explanation_storage") as mock:
            mock_storage = MagicMock()
            mock_storage.get_history = AsyncMock(return_value=[
                {"trace_id": "t1", "created_at": "2026-02-01T00:00:00"},
            ])
            mock.return_value = mock_storage

            response = client.get(
                "/api/v1/explain/history?from=2026-01-01&to=2026-03-01",
                headers={"X-Role": "viewer"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["from"] == "2026-01-01"
            assert data["to"] == "2026-03-01"

    def test_history_with_limit(self, client):
        """GET /history with limit should respect limit."""
        with patch("backend.explain.router.get_explanation_storage") as mock:
            mock_storage = MagicMock()
            mock_storage.get_history = AsyncMock(return_value=[])
            mock.return_value = mock_storage

            response = client.get(
                "/api/v1/explain/history?limit=100",
                headers={"X-Role": "viewer"},
            )

            assert response.status_code == 200
            mock_storage.get_history.assert_called_once()
            call_args = mock_storage.get_history.call_args
            assert call_args.kwargs.get("limit") == 100


class TestStatsEndpoint:
    """Tests for /explain/stats endpoint."""

    def test_stats_returns_metrics(self, client):
        """GET /stats should return storage metrics."""
        with patch("backend.explain.router.get_explanation_storage") as mock:
            mock_storage = MagicMock()
            mock_storage.get_stats = AsyncMock(return_value={
                "total_records": 1000,
                "unique_traces": 500,
                "tamper_ok": True,
            })
            mock.return_value = mock_storage

            response = client.get(
                "/api/v1/explain/stats",
                headers={"X-Role": "viewer"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "total_records" in data
            assert "retention_days_min" in data
            assert data["retention_days_min"] == 180


class TestGraphEndpoints:
    """Tests for trace graph endpoints."""

    def test_graph_returns_data(self, client):
        """GET /graph/{trace_id} should return graph data."""
        with patch("backend.explain.router.get_explanation_storage") as mock:
            mock_storage = MagicMock()
            mock_graph = MagicMock()
            mock_graph.nodes = [{"id": "node1"}]
            mock_graph.to_dict.return_value = {
                "trace_id": "test_trace",
                "nodes": [{"id": "node1"}],
                "edges": [],
                "adjacency": {},
            }
            mock_storage.get_trace_graph = AsyncMock(return_value=mock_graph)
            mock.return_value = mock_storage

            response = client.get(
                "/api/v1/explain/graph/test_trace",
                headers={"X-Role": "viewer"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["trace_id"] == "test_trace"

    def test_graph_not_found(self, client):
        """GET /graph/{trace_id} should return 404 if not found."""
        with patch("backend.explain.router.get_explanation_storage") as mock:
            mock_storage = MagicMock()
            mock_graph = MagicMock()
            mock_graph.nodes = []  # Empty = not found
            mock_storage.get_trace_graph = AsyncMock(return_value=mock_graph)
            mock.return_value = mock_storage

            response = client.get(
                "/api/v1/explain/graph/nonexistent",
                headers={"X-Role": "viewer"},
            )

            assert response.status_code == 404

    def test_backtrack_returns_path(self, client):
        """GET /graph/{trace_id}/backtrack should return path."""
        with patch("backend.explain.router.get_explanation_storage") as mock:
            mock_storage = MagicMock()
            mock_storage.backtrack = AsyncMock(return_value=["node1", "node2", "node3"])
            mock.return_value = mock_storage

            response = client.get(
                "/api/v1/explain/graph/test_trace/backtrack?target=node3",
                headers={"X-Role": "viewer"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["path"] == ["node1", "node2", "node3"]


class TestCalibrationEndpoints:
    """Tests for calibration endpoints."""

    def test_calibration_report(self, client):
        """GET /calibration/report should return metrics."""
        with patch("backend.explain.router.get_calibration_dataset") as mock:
            mock_dataset = MagicMock()
            mock_report = MagicMock()
            mock_report.to_dict.return_value = {
                "brier_score": 0.15,
                "expected_calibration_error": 0.08,
                "is_well_calibrated": True,
            }
            mock_dataset.generate_report.return_value = mock_report
            mock.return_value = mock_dataset

            response = client.get(
                "/api/v1/explain/calibration/report",
                headers={"X-Role": "viewer"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "brier_score" in data
            assert "expected_calibration_error" in data

    def test_calibration_diagram(self, client):
        """GET /calibration/diagram should return chart data."""
        with patch("backend.explain.router.get_calibration_dataset") as mock_ds, \
             patch("backend.explain.router.ConfidenceCalibrator") as mock_cal:
            
            mock_ds.return_value.load_samples.return_value = []
            mock_calibrator_instance = MagicMock()
            mock_calibrator_instance.generate_reliability_diagram_data.return_value = {
                "diagonal": [[0, 0], [1, 1]],
                "calibration_curve": [],
                "histogram": [],
            }
            mock_cal.return_value = mock_calibrator_instance

            response = client.get(
                "/api/v1/explain/calibration/diagram",
                headers={"X-Role": "viewer"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "diagonal" in data
            assert "calibration_curve" in data

    def test_record_outcome(self, client):
        """POST /calibration/outcome should record data."""
        with patch("backend.explain.router.get_calibration_dataset") as mock:
            mock_dataset = MagicMock()
            mock.return_value = mock_dataset

            response = client.post(
                "/api/v1/explain/calibration/outcome",
                params={
                    "trace_id": "trace_001",
                    "predicted_confidence": 0.85,
                    "predicted_class": "Data Scientist",
                    "actual_class": "Data Scientist",
                },
                headers={"X-Role": "viewer"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "recorded"
            assert data["correct"] is True


class TestLegalHoldEndpoints:
    """Tests for legal hold endpoints."""

    def test_set_legal_hold_requires_admin(self, client):
        """POST /legal-hold/{trace_id} should require admin role."""
        with patch("backend.explain.router.get_explanation_storage") as mock:
            mock_storage = MagicMock()
            mock_storage.get_by_trace_id = AsyncMock(return_value={"trace_id": "test"})
            mock_storage.set_legal_hold = AsyncMock(return_value={
                "trace_id": "test",
                "legal_hold": True,
                "affected_rows": 1,
            })
            mock.return_value = mock_storage

            # With admin role - should succeed
            response = client.post(
                "/api/v1/explain/legal-hold/test_trace",
                headers={"X-Role": "admin"},
            )
            assert response.status_code == 200

    def test_set_legal_hold_forbidden_for_viewer(self, client):
        """POST /legal-hold should fail for viewer role."""
        response = client.post(
            "/api/v1/explain/legal-hold/test_trace",
            headers={"X-Role": "viewer"},
        )
        assert response.status_code == 403

    def test_clear_legal_hold(self, client):
        """DELETE /legal-hold/{trace_id} should clear hold."""
        with patch("backend.explain.router.get_explanation_storage") as mock:
            mock_storage = MagicMock()
            mock_storage.get_by_trace_id = AsyncMock(return_value={"trace_id": "test"})
            mock_storage.set_legal_hold = AsyncMock(return_value={
                "trace_id": "test",
                "legal_hold": False,
                "affected_rows": 1,
            })
            mock.return_value = mock_storage

            response = client.delete(
                "/api/v1/explain/legal-hold/test_trace",
                headers={"X-Role": "admin"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "legal_hold_cleared"

    def test_get_legal_hold_status(self, client):
        """GET /legal-hold/{trace_id} should return status."""
        with patch("backend.explain.router.get_explanation_storage") as mock:
            mock_storage = MagicMock()
            mock_storage.get_legal_hold_status = AsyncMock(return_value={
                "trace_id": "test",
                "legal_hold": True,
                "created_at": "2026-02-14T00:00:00",
            })
            mock.return_value = mock_storage

            response = client.get(
                "/api/v1/explain/legal-hold/test_trace",
                headers={"X-Role": "viewer"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["legal_hold"] is True

    def test_list_legal_holds(self, client):
        """GET /legal-holds should return all held traces."""
        with patch("backend.explain.router.get_explanation_storage") as mock:
            mock_storage = MagicMock()
            mock_storage.list_legal_holds = AsyncMock(return_value=[
                {"trace_id": "hold1", "created_at": "2026-01-01"},
                {"trace_id": "hold2", "created_at": "2026-01-15"},
            ])
            mock.return_value = mock_storage

            response = client.get(
                "/api/v1/explain/legal-holds",
                headers={"X-Role": "viewer"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 2


class TestPdfExportEndpoint:
    """Tests for PDF export endpoint."""

    def test_pdf_export_success(self, client):
        """GET /{trace_id}/pdf should return PDF."""
        with patch("backend.explain.router.get_explanation_storage") as mock_storage, \
             patch("backend.explain.export.pdf_generator.ExplainPdfGenerator") as mock_gen:
            
            storage = MagicMock()
            storage.get_by_trace_id = AsyncMock(return_value={
                "trace_id": "test",
                "confidence": 0.85,
            })
            mock_graph = MagicMock()
            mock_graph.nodes = []
            storage.get_trace_graph = AsyncMock(return_value=mock_graph)
            mock_storage.return_value = storage

            generator_instance = MagicMock()
            generator_instance.generate.return_value = b"%PDF-1.4 test content"
            mock_gen.return_value = generator_instance

            response = client.get(
                "/api/v1/explain/test_trace/pdf",
                headers={"X-Role": "viewer"},
            )

            assert response.status_code == 200
            assert response.headers["content-type"] == "application/pdf"

    def test_pdf_export_not_found(self, client):
        """GET /{trace_id}/pdf should return 404 if trace not found."""
        with patch("backend.explain.router.get_explanation_storage") as mock:
            mock_storage = MagicMock()
            mock_storage.get_by_trace_id = AsyncMock(return_value=None)
            mock.return_value = mock_storage

            response = client.get(
                "/api/v1/explain/nonexistent/pdf",
                headers={"X-Role": "viewer"},
            )

            assert response.status_code == 404


class TestTraceDetailEndpoint:
    """Tests for trace detail endpoint."""

    def test_get_trace_detail(self, client):
        """GET /{trace_id} should return full record."""
        with patch("backend.explain.router.get_explanation_storage") as mock:
            mock_storage = MagicMock()
            mock_storage.get_by_trace_id = AsyncMock(return_value={
                "trace_id": "test",
                "explanation_id": "exp-001",
                "confidence": 0.85,
                "rule_path": [],
                "evidence": [],
            })
            mock.return_value = mock_storage

            response = client.get(
                "/api/v1/explain/test_trace",
                headers={"X-Role": "viewer"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["trace_id"] == "test"

    def test_get_trace_detail_not_found(self, client):
        """GET /{trace_id} should return 404 if not found."""
        with patch("backend.explain.router.get_explanation_storage") as mock:
            mock_storage = MagicMock()
            mock_storage.get_by_trace_id = AsyncMock(return_value=None)
            mock.return_value = mock_storage

            response = client.get(
                "/api/v1/explain/nonexistent",
                headers={"X-Role": "viewer"},
            )

            assert response.status_code == 404

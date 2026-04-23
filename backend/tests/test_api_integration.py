# backend/tests/test_api_integration.py
"""
Integration tests — FastAPI TestClient hitting all major API routes.
No external services required (mocked where needed).
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport

# We need to patch heavy dependencies BEFORE importing the app
# to avoid startup-time DB connections, background tasks, etc.


@pytest.fixture
def app():
    """Create a test-safe FastAPI app instance."""
    from backend.main import app as real_app
    return real_app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Health & Root
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestHealthRoutes:
    @pytest.mark.asyncio
    async def test_root(self, client):
        r = await client.get("/")
        assert r.status_code == 200
        assert "message" in r.json()

    @pytest.mark.asyncio
    async def test_health_live(self, client):
        r = await client.get("/health/live")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_health_full(self, client):
        r = await client.get("/health/full")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_health_alias(self, client):
        r = await client.get("/health")
        assert r.status_code == 200


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Observability & Metrics
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestObservabilityRoutes:
    @pytest.mark.asyncio
    async def test_metrics_prometheus(self, client):
        r = await client.get("/metrics")
        assert r.status_code == 200
        assert "text/plain" in r.headers["content-type"]

    @pytest.mark.asyncio
    async def test_metrics_json(self, client):
        r = await client.get("/metrics/json")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_ops_sla(self, client):
        r = await client.get("/ops/sla")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_alerts(self, client):
        r = await client.get("/ops/alerts")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_status(self, client):
        r = await client.get("/ops/status")
        assert r.status_code == 200
        data = r.json()
        assert "supervisor" in data or "sla" in data

    @pytest.mark.asyncio
    async def test_ops_explanation(self, client):
        r = await client.get("/ops/explanation")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_correlation_id_header(self, client):
        r = await client.get("/")
        assert "x-correlation-id" in r.headers


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Recovery Routes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestRecoveryRoutes:
    @pytest.mark.asyncio
    async def test_recovery_status(self, client):
        r = await client.get("/ops/recovery/status")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_recovery_report(self, client):
        r = await client.get("/ops/recovery/report")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_recovery_catalog(self, client):
        r = await client.get("/ops/recovery/catalog")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_recovery_history(self, client):
        r = await client.get("/ops/recovery/history")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_recovery_log(self, client):
        r = await client.get("/ops/recovery/log")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_recovery_retry_stats(self, client):
        r = await client.get("/ops/recovery/retry-stats")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_recovery_rollback_history(self, client):
        r = await client.get("/ops/recovery/rollback-history")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_recovery_checkpoint_404(self, client):
        r = await client.get("/ops/recovery/checkpoint/nonexistent_run_xyz")
        assert r.status_code == 404


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Profile Processing
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestProfileProcessingRoute:
    @pytest.mark.asyncio
    async def test_process_profile(self, client):
        """Full profile processing via API."""
        payload = {
            "personalInfo": {
                "fullName": "Nguyen Van Test",
                "age": "22",
                "education": "Bachelor",
            },
            "interests": ["AI", "Machine Learning"],
            "skills": "Python, SQL, TensorFlow",
            "careerGoal": "Trở thành AI Engineer",
            "chatHistory": [
                {"role": "user", "text": "Tôi muốn làm AI"},
            ],
        }
        with patch("backend.main.process_user_profile") as mock_pup:
            mock_pup.return_value = {
                "age": 22,
                "education_level": "Bachelor",
                "interest_tags": ["ai", "machine learning"],
                "skill_tags": ["python", "sql", "tensorflow"],
                "goal_cleaned": "tro thanh AI Engineer",
                "intent": "career_intent",
                "chat_summary": "toi muon lam ai",
                "confidence_score": 0.75,
            }
            r = await client.post("/api/v1/profile/process", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert data["age"] == 22
            assert data["confidence_score"] == 0.75


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Crawler Routes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestCrawlerRoutes:
    @pytest.mark.asyncio
    async def test_get_all_crawler_status(self, client):
        r = await client.get("/api/v1/crawlers/status")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_get_single_crawler_status(self, client):
        r = await client.get("/api/v1/crawlers/status/topcv")
        assert r.status_code == 200

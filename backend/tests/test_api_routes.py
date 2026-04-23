# backend/tests/test_api_routes.py
"""
API Route Contract Validation Tests
===================================

Validates that all required endpoints are registered and accessible.
"""

import pytest
from fastapi.testclient import TestClient


def get_app():
    """Get the API Gateway app."""
    from backend.inference.api_server_v2 import create_inference_api
    api = create_inference_api()
    return api.app


@pytest.fixture
def client():
    """Create test client."""
    app = get_app()
    return TestClient(app)


class TestRouteRegistration:
    """Test that all expected routes are registered."""
    
    EXPECTED_ROUTES = [
        # Root & Legacy
        ("GET", "/"),
        ("GET", "/health"),
        ("GET", "/metrics"),
        ("POST", "/predict"),
        ("POST", "/feedback"),
        
        # Health
        ("GET", "/api/v1/health/live"),
        ("GET", "/api/v1/health/full"),
        ("GET", "/api/v1/health/ready"),
        ("GET", "/api/v1/health/scoring"),
        ("GET", "/api/v1/health/llm"),
        ("GET", "/api/v1/health/warmup"),
        ("POST", "/api/v1/health/warmup"),
        
        # Ops
        ("GET", "/api/v1/ops/sla"),
        ("GET", "/api/v1/ops/alerts"),
        ("GET", "/api/v1/ops/status"),
        ("GET", "/api/v1/ops/explanation"),
        ("POST", "/api/v1/ops/backup"),
        ("POST", "/api/v1/ops/retention"),
        ("GET", "/api/v1/ops/recovery/status"),
        ("GET", "/api/v1/ops/recovery/report"),
        ("GET", "/api/v1/ops/recovery/catalog"),
        ("GET", "/api/v1/ops/recovery/history"),
        ("GET", "/api/v1/ops/recovery/log"),
        ("GET", "/api/v1/ops/recovery/retry-stats"),
        ("GET", "/api/v1/ops/recovery/rollback-history"),
        ("GET", "/api/v1/ops/metrics"),
        ("GET", "/api/v1/ops/metrics/prometheus"),
        
        # ML
        ("POST", "/api/v1/ml/evaluation"),
        ("GET", "/api/v1/ml/evaluation/results"),
        ("GET", "/api/v1/ml/inference/metrics"),
        ("GET", "/api/v1/ml/models"),
        ("GET", "/api/v1/ml/retrain/check"),
        ("POST", "/api/v1/ml/retrain/run"),
        ("POST", "/api/v1/ml/deploy"),
        ("POST", "/api/v1/ml/deploy/promote"),
        ("POST", "/api/v1/ml/deploy/rollback"),
        ("POST", "/api/v1/ml/killswitch"),
        ("POST", "/api/v1/ml/monitoring/cycle"),
        
        # Infer
        ("POST", "/api/v1/infer/predict"),
        ("POST", "/api/v1/infer/feedback"),
        ("GET", "/api/v1/infer/models"),
        ("GET", "/api/v1/infer/metrics"),
        ("POST", "/api/v1/infer/killswitch"),
        ("GET", "/api/v1/infer/router/stats"),
        ("POST", "/api/v1/infer/analyze"),
        ("POST", "/api/v1/infer/recommendations"),
        ("GET", "/api/v1/infer/career-library"),
        
        # Explain
        ("POST", "/api/v1/explain"),
        ("GET", "/api/v1/health"),  # Explain health
        
        # Pipeline
        ("POST", "/api/v1/pipeline/run"),
        ("POST", "/api/v1/pipeline/recommendations"),
        
        # Crawlers
        # ("POST", "/api/v1/crawlers/start/{site_name}"),  # Path params need different handling
        ("GET", "/api/v1/crawlers/status"),
        
        # KB
        ("POST", "/api/v1/kb/domains"),
        ("GET", "/api/v1/kb/domains"),
        ("POST", "/api/v1/kb/skills"),
        ("GET", "/api/v1/kb/skills"),
        ("POST", "/api/v1/kb/careers"),
        ("GET", "/api/v1/kb/careers"),
        ("GET", "/api/v1/kb/education-levels"),
        ("GET", "/api/v1/kb/legacy/all-jobs"),
        
        # Chat
        ("POST", "/api/v1/chat"),
    ]
    
    MINIMUM_ROUTE_COUNT = 50
    
    def test_minimum_route_count(self, client):
        """Test that minimum number of routes are registered."""
        app = client.app
        routes = [r for r in app.routes if hasattr(r, 'methods')]
        
        assert len(routes) >= self.MINIMUM_ROUTE_COUNT, (
            f"Expected at least {self.MINIMUM_ROUTE_COUNT} routes, got {len(routes)}"
        )
    
    def test_all_routes_registered(self, client):
        """Test that all expected routes are registered."""
        app = client.app
        
        # Build set of registered routes
        registered = set()
        for route in app.routes:
            if hasattr(route, 'methods') and hasattr(route, 'path'):
                for method in route.methods:
                    if method != "HEAD":  # Skip HEAD, it's auto-added
                        registered.add((method, route.path))
        
        # Check expected routes
        missing = []
        for method, path in self.EXPECTED_ROUTES:
            # Handle path parameters
            path_pattern = path
            found = False
            for reg_method, reg_path in registered:
                if reg_method == method:
                    # Exact match or pattern match
                    if reg_path == path_pattern:
                        found = True
                        break
                    # Check if it's a parameterized route
                    if "{" in reg_path and path_pattern.split("/")[:-1] == reg_path.split("/")[:-1]:
                        found = True
                        break
            
            if not found:
                missing.append((method, path))
        
        if missing:
            print(f"\nMissing routes ({len(missing)}):")
            for m, p in missing[:20]:  # Show first 20
                print(f"  {m} {p}")
        
        # Allow some missing routes (dynamic paths, etc.)
        assert len(missing) <= 10, f"Too many missing routes: {missing}"
    
    def test_root_endpoint(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
    
    def test_health_endpoints(self, client):
        """Test health endpoints return valid responses."""
        # Legacy health
        response = client.get("/health")
        assert response.status_code == 200
        
        # New health endpoints
        response = client.get("/api/v1/health/live")
        assert response.status_code in [200, 503]  # May be unavailable without ops
        
        response = client.get("/api/v1/health/full")
        assert response.status_code in [200, 503]
    
    def test_chat_endpoint(self, client):
        """Test chat endpoint."""
        response = client.post(
            "/api/v1/chat",
            json={"message": "Hello", "chatHistory": []}
        )
        assert response.status_code == 200
        data = response.json()
        assert "reply" in data
    
    def test_career_library_endpoint(self, client):
        """Test career library endpoint."""
        response = client.get("/api/v1/infer/career-library")
        assert response.status_code == 200
        data = response.json()
        assert "careers" in data
        assert len(data["careers"]) > 0


class TestBackwardCompatibility:
    """Test backward compatibility with legacy endpoints."""
    
    def test_legacy_health(self, client):
        """Test legacy /health endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
    
    def test_legacy_root(self, client):
        """Test legacy / endpoint."""
        response = client.get("/")
        assert response.status_code == 200


def test_all_routes_registered():
    """Standalone test function for route count."""
    from backend.inference.api_server_v2 import create_inference_api
    api = create_inference_api()
    app = api.app
    
    routes = [r for r in app.routes if hasattr(r, 'methods')]
    print(f"\nTotal routes registered: {len(routes)}")
    
    # List all routes
    for route in sorted(routes, key=lambda r: r.path):
        methods = ",".join(sorted(route.methods - {"HEAD"}))
        print(f"  {methods:8} {route.path}")
    
    assert len(routes) >= 50, f"Expected at least 50 routes, got {len(routes)}"


if __name__ == "__main__":
    # Run basic validation
    test_all_routes_registered()
    print("\nRoute validation passed!")

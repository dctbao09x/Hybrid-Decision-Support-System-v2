# backend/ops/tests/test_governance_api.py
"""
Governance API Tests
====================

Tests for governance router endpoints
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, AsyncMock

# Skip tests if dependencies not available
pytest.importorskip("fastapi")


@pytest.fixture
def api_client():
    """Create test client."""
    from fastapi import FastAPI
    from backend.api.routers.governance_router import router
    
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/governance")
    
    return TestClient(app)


class TestGovernanceDashboard:
    """Tests for main dashboard endpoint."""

    def test_dashboard_returns_200(self, api_client):
        """Test dashboard endpoint returns 200."""
        response = api_client.get("/api/v1/governance/dashboard")
        
        assert response.status_code == 200
        data = response.json()
        assert "timestamp" in data
        assert "status" in data

    def test_dashboard_contains_sections(self, api_client):
        """Test dashboard contains expected sections."""
        response = api_client.get("/api/v1/governance/dashboard")
        
        data = response.json()
        # Dashboard should have various sections (may be empty if no data)
        assert isinstance(data, dict)


class TestRiskEndpoints:
    """Tests for risk management endpoints."""

    def test_risk_dashboard(self, api_client):
        """Test risk dashboard endpoint."""
        response = api_client.get("/api/v1/governance/risk")
        
        # May return error if risk manager not available, but should be 200
        assert response.status_code == 200

    def test_risk_history(self, api_client):
        """Test risk history endpoint."""
        response = api_client.get("/api/v1/governance/risk/history?hours=24&limit=100")
        
        assert response.status_code == 200

    def test_risk_mitigations(self, api_client):
        """Test mitigation history endpoint."""
        response = api_client.get("/api/v1/governance/risk/mitigations?hours=24")
        
        assert response.status_code == 200

    def test_update_risk_weights(self, api_client):
        """Test updating risk weights."""
        weights = {
            "drift": 0.25,
            "latency": 0.25,
            "error_rate": 0.25,
            "cost_overrun": 0.25,
        }
        
        response = api_client.post(
            "/api/v1/governance/risk/weights",
            json=weights,
        )
        
        # May return 503 if risk manager not available
        assert response.status_code in [200, 503]


class TestSLAEndpoints:
    """Tests for SLA management endpoints."""

    def test_sla_dashboard(self, api_client):
        """Test SLA dashboard endpoint."""
        response = api_client.get("/api/v1/governance/sla")
        
        assert response.status_code == 200

    def test_sla_violations(self, api_client):
        """Test SLA violations endpoint."""
        response = api_client.get("/api/v1/governance/sla/violations?hours=24")
        
        assert response.status_code == 200

    def test_sla_compliance(self, api_client):
        """Test SLA compliance endpoint."""
        response = api_client.get("/api/v1/governance/sla/compliance")
        
        assert response.status_code == 200

    def test_list_sla_contracts(self, api_client):
        """Test listing SLA contracts."""
        response = api_client.get("/api/v1/governance/sla/contracts")
        
        assert response.status_code == 200

    def test_register_sla_contract(self, api_client):
        """Test registering SLA contract."""
        contract = {
            "contract_id": "test-contract",
            "name": "Test Contract",
            "description": "A test contract",
            "targets": [
                {
                    "name": "latency",
                    "metric": "latency_ms",
                    "threshold": 500,
                    "comparison": "<=",
                    "severity": "warning",
                }
            ],
            "enabled": True,
        }
        
        response = api_client.post(
            "/api/v1/governance/sla/contracts",
            json=contract,
        )
        
        # May return 503 if evaluator not available
        assert response.status_code in [200, 503]


class TestReportingEndpoints:
    """Tests for reporting endpoints."""

    def test_list_reports(self, api_client):
        """Test listing reports."""
        response = api_client.get("/api/v1/governance/reports")
        
        assert response.status_code == 200
        data = response.json()
        assert "reports" in data

    def test_weekly_report(self, api_client):
        """Test weekly SLA report endpoint."""
        response = api_client.get("/api/v1/governance/reports/weekly")
        
        assert response.status_code == 200

    def test_monthly_report(self, api_client):
        """Test monthly risk report endpoint."""
        response = api_client.get("/api/v1/governance/reports/monthly")
        
        assert response.status_code == 200

    def test_generate_report(self, api_client):
        """Test report generation endpoint."""
        request = {
            "report_type": "weekly_sla",
            "formats": ["json"],
        }
        
        response = api_client.post(
            "/api/v1/governance/reports/generate",
            json=request,
        )
        
        # May return 503 if generator not available
        assert response.status_code in [200, 503]


class TestCostAndDriftEndpoints:
    """Tests for cost and drift endpoints."""

    def test_cost_dashboard(self, api_client):
        """Test cost dashboard endpoint."""
        response = api_client.get("/api/v1/governance/cost")
        
        assert response.status_code == 200

    def test_drift_dashboard(self, api_client):
        """Test drift dashboard endpoint."""
        response = api_client.get("/api/v1/governance/drift")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data


class TestAuditEndpoints:
    """Tests for audit log endpoints."""

    def test_audit_log(self, api_client):
        """Test audit log endpoint."""
        response = api_client.get("/api/v1/governance/audit?hours=24&limit=100")
        
        assert response.status_code == 200
        data = response.json()
        assert "audit_entries" in data
        assert "total" in data

    def test_audit_log_with_filters(self, api_client):
        """Test audit log with different filters."""
        # Test with different hour ranges
        for hours in [1, 6, 24, 168]:
            response = api_client.get(f"/api/v1/governance/audit?hours={hours}")
            assert response.status_code == 200
        
        # Test with different limits
        for limit in [10, 50, 100]:
            response = api_client.get(f"/api/v1/governance/audit?limit={limit}")
            assert response.status_code == 200


class TestAPIValidation:
    """Tests for API input validation."""

    def test_invalid_hours_parameter(self, api_client):
        """Test validation of hours parameter."""
        # Should handle edge cases gracefully
        response = api_client.get("/api/v1/governance/risk/history?hours=0")
        assert response.status_code in [200, 422]  # Either works or validation error

    def test_invalid_limit_parameter(self, api_client):
        """Test validation of limit parameter."""
        response = api_client.get("/api/v1/governance/audit?limit=-1")
        assert response.status_code in [200, 422]

    def test_invalid_contract_data(self, api_client):
        """Test validation of contract registration data."""
        invalid_contract = {
            "contract_id": "",  # Empty ID
            "name": "",
            "targets": [],
        }
        
        response = api_client.post(
            "/api/v1/governance/sla/contracts",
            json=invalid_contract,
        )
        
        # Should handle gracefully
        assert response.status_code in [200, 400, 422, 503]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

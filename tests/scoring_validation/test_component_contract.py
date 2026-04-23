# tests/scoring_validation/test_component_contract.py
"""
Component Contract Tests for SIMGR Scoring Pipeline.

GĐ3 - COMPONENT VALIDATION HARDENING - PHẦN G

Tests:
- test_contract_missing_fail
- test_healthcheck_fail_abort
- test_missing_method_fail
"""

import pytest
from unittest.mock import MagicMock

import sys
sys.path.insert(0, "F:/Hybrid Decision Support System")

from backend.scoring.validation.component_contract import (
    BaseComponentContract,
    ContractValidator,
    ComponentRegistry,
    get_component_registry,
    HealthStatus,
    DatasetStatus,
    create_healthcheck_response,
    create_metadata_response,
)
from backend.scoring.errors import (
    ComponentContractError,
    MissingMethodError,
    HealthcheckFailError,
)


# =====================================================
# TEST COMPONENTS
# =====================================================

class ValidComponent(BaseComponentContract):
    """A valid component implementing full contract."""
    
    COMPONENT_NAME = "valid_test"
    COMPONENT_VERSION = "1.0"
    
    def validate(self, input_dict):
        if not input_dict:
            raise ComponentContractError("Empty input")
        return True
    
    def healthcheck(self):
        return create_healthcheck_response(
            status=HealthStatus.OK,
            dataset=DatasetStatus.READY,
            last_update="2026-02-16T12:00:00Z",
            schema_version="1.0",
            coverage=1.0,
        )
    
    def metadata(self):
        return create_metadata_response(
            name=self.COMPONENT_NAME,
            version=self.COMPONENT_VERSION,
            dependencies=[],
            required_fields=["user_id"],
        )


class MissingValidateComponent:
    """Component missing validate method."""
    COMPONENT_NAME = "missing_validate"
    
    def healthcheck(self):
        return {}
    
    def metadata(self):
        return {}


class MissingHealthcheckComponent:
    """Component missing healthcheck method."""
    COMPONENT_NAME = "missing_healthcheck"
    
    def validate(self, input_dict):
        return True
    
    def metadata(self):
        return {}


class MissingMetadataComponent:
    """Component missing metadata method."""
    COMPONENT_NAME = "missing_metadata"
    
    def validate(self, input_dict):
        return True
    
    def healthcheck(self):
        return {}


class NonCallableMethod:
    """Component with non-callable method."""
    COMPONENT_NAME = "non_callable"
    
    validate = "not a method"  # Not callable
    
    def healthcheck(self):
        return {}
    
    def metadata(self):
        return {}


class FailingHealthcheckComponent(BaseComponentContract):
    """Component with failing healthcheck."""
    
    COMPONENT_NAME = "failing_health"
    COMPONENT_VERSION = "1.0"
    
    def validate(self, input_dict):
        return True
    
    def healthcheck(self):
        return create_healthcheck_response(
            status=HealthStatus.FAIL,
            dataset=DatasetStatus.MISSING,
            last_update="2026-02-16T12:00:00Z",
            schema_version="1.0",
            coverage=0.0,
        )
    
    def metadata(self):
        return create_metadata_response(
            name=self.COMPONENT_NAME,
            version=self.COMPONENT_VERSION,
            dependencies=[],
            required_fields=[],
        )


# =====================================================
# CONTRACT MISSING TESTS
# =====================================================

class TestContractMissingFail:
    """Tests for missing contract methods."""
    
    def test_missing_validate_method_fails(self):
        """Missing validate method should fail."""
        component = MissingValidateComponent()
        
        with pytest.raises(MissingMethodError) as exc:
            ContractValidator.check_contract(component)
        
        assert exc.value.code == "COMP_002"
        assert "validate" in str(exc.value)
    
    def test_missing_healthcheck_method_fails(self):
        """Missing healthcheck method should fail."""
        component = MissingHealthcheckComponent()
        
        with pytest.raises(MissingMethodError) as exc:
            ContractValidator.check_contract(component)
        
        assert "healthcheck" in str(exc.value)
    
    def test_missing_metadata_method_fails(self):
        """Missing metadata method should fail."""
        component = MissingMetadataComponent()
        
        with pytest.raises(MissingMethodError) as exc:
            ContractValidator.check_contract(component)
        
        assert "metadata" in str(exc.value)
    
    def test_non_callable_method_fails(self):
        """Non-callable method should fail."""
        component = NonCallableMethod()
        
        with pytest.raises(MissingMethodError) as exc:
            ContractValidator.check_contract(component)
        
        assert "validate" in str(exc.value)
        assert "not callable" in str(exc.value)
    
    def test_valid_component_passes(self):
        """Valid component should pass contract check."""
        component = ValidComponent()
        
        result = ContractValidator.check_contract(component)
        assert result is True


# =====================================================
# HEALTHCHECK RESPONSE TESTS
# =====================================================

class TestHealthcheckResponseValidation:
    """Tests for healthcheck response validation."""
    
    def test_missing_status_fails(self):
        """Response missing status should fail."""
        response = {
            "dataset": "ready",
            "last_update": "2026-02-16T12:00:00Z",
            "schema_version": "1.0",
            "coverage": 1.0,
        }
        
        with pytest.raises(ComponentContractError) as exc:
            ContractValidator.validate_healthcheck_response(response)
        
        assert "status" in str(exc.value)
    
    def test_missing_dataset_fails(self):
        """Response missing dataset should fail."""
        response = {
            "status": "OK",
            "last_update": "2026-02-16T12:00:00Z",
            "schema_version": "1.0",
            "coverage": 1.0,
        }
        
        with pytest.raises(ComponentContractError):
            ContractValidator.validate_healthcheck_response(response)
    
    def test_invalid_status_value_fails(self):
        """Invalid status value should fail."""
        response = {
            "status": "INVALID_STATUS",
            "dataset": "ready",
            "last_update": "2026-02-16T12:00:00Z",
            "schema_version": "1.0",
            "coverage": 1.0,
        }
        
        with pytest.raises(ComponentContractError) as exc:
            ContractValidator.validate_healthcheck_response(response)
        
        assert "Invalid status" in str(exc.value)
    
    def test_invalid_coverage_type_fails(self):
        """Invalid coverage type should fail."""
        response = {
            "status": "OK",
            "dataset": "ready",
            "last_update": "2026-02-16T12:00:00Z",
            "schema_version": "1.0",
            "coverage": "high",  # Should be float
        }
        
        with pytest.raises(ComponentContractError) as exc:
            ContractValidator.validate_healthcheck_response(response)
        
        assert "coverage" in str(exc.value).lower()
    
    def test_coverage_out_of_range_fails(self):
        """Coverage out of [0, 1] range should fail."""
        response = {
            "status": "OK",
            "dataset": "ready",
            "last_update": "2026-02-16T12:00:00Z",
            "schema_version": "1.0",
            "coverage": 1.5,  # Out of range
        }
        
        with pytest.raises(ComponentContractError):
            ContractValidator.validate_healthcheck_response(response)
    
    def test_valid_response_passes(self):
        """Valid response should pass."""
        response = {
            "status": "OK",
            "dataset": "ready",
            "last_update": "2026-02-16T12:00:00Z",
            "schema_version": "1.0",
            "coverage": 0.95,
        }
        
        result = ContractValidator.validate_healthcheck_response(response)
        assert result is True


# =====================================================
# HEALTHCHECK FAIL ABORT TESTS
# =====================================================

class TestHealthcheckFailAbort:
    """Tests for healthcheck fail abortion."""
    
    def test_failing_component_aborts_registry(self):
        """Failing component should abort registry healthcheck."""
        registry = ComponentRegistry()
        registry.clear()
        
        # Register a failing component
        failing = FailingHealthcheckComponent()
        registry.register(failing)
        
        with pytest.raises(HealthcheckFailError) as exc:
            registry.run_all_healthchecks()
        
        assert exc.value.code == "HEALTH_001"
        assert "failing_health" in str(exc.value)
    
    def test_valid_component_passes_registry(self):
        """Valid component should pass registry healthcheck."""
        registry = ComponentRegistry()
        registry.clear()
        
        valid = ValidComponent()
        registry.register(valid)
        
        results = registry.run_all_healthchecks()
        
        assert "valid_test" in results
        assert results["valid_test"]["status"] == HealthStatus.OK


# =====================================================
# REGISTRY TESTS
# =====================================================

class TestComponentRegistry:
    """Tests for component registry."""
    
    def test_register_invalid_component_fails(self):
        """Registering invalid component should fail."""
        registry = ComponentRegistry()
        registry.clear()
        
        invalid = MissingValidateComponent()
        
        with pytest.raises(MissingMethodError):
            registry.register(invalid)
    
    def test_register_valid_component_succeeds(self):
        """Registering valid component should succeed."""
        registry = ComponentRegistry()
        registry.clear()
        
        valid = ValidComponent()
        registry.register(valid)
        
        assert registry.get("valid_test") is valid
    
    def test_get_nonexistent_returns_none(self):
        """Getting nonexistent component should return None."""
        registry = ComponentRegistry()
        registry.clear()
        
        result = registry.get("nonexistent")
        assert result is None
    
    def test_all_components_returns_copy(self):
        """all_components should return a copy."""
        registry = ComponentRegistry()
        registry.clear()
        
        valid = ValidComponent()
        registry.register(valid)
        
        components = registry.all_components()
        components["new"] = "value"  # Modify copy
        
        # Original should be unchanged
        assert "new" not in registry.all_components()


# =====================================================
# HELPER FUNCTION TESTS
# =====================================================

class TestHelperFunctions:
    """Tests for helper functions."""
    
    def test_create_healthcheck_response_validates(self):
        """create_healthcheck_response should validate output."""
        # Valid params
        response = create_healthcheck_response(
            status=HealthStatus.OK,
            dataset=DatasetStatus.READY,
            last_update="2026-02-16T12:00:00Z",
            schema_version="1.0",
            coverage=0.95,
        )
        
        assert response["status"] == "OK"
        assert response["coverage"] == 0.95
    
    def test_create_healthcheck_invalid_fails(self):
        """create_healthcheck_response with invalid params should fail."""
        with pytest.raises(ComponentContractError):
            create_healthcheck_response(
                status="INVALID",
                dataset="ready",
                last_update="2026-02-16T12:00:00Z",
                schema_version="1.0",
                coverage=0.95,
            )
    
    def test_create_metadata_response(self):
        """create_metadata_response should include all fields."""
        response = create_metadata_response(
            name="test",
            version="1.0",
            dependencies=["dep1"],
            required_fields=["field1", "field2"],
        )
        
        assert response["name"] == "test"
        assert response["version"] == "1.0"
        assert "contract_version" in response
        assert "dep1" in response["dependencies"]


# =====================================================
# STATUS SUMMARY TESTS
# =====================================================

class TestStatusSummary:
    """Tests for get_status_summary method."""
    
    def test_status_summary_includes_all_fields(self):
        """Status summary should include all required fields."""
        component = ValidComponent()
        summary = component.get_status_summary()
        
        required = [
            "component", "version", "health_status", 
            "dataset_status", "contract_compliant", "checked_at"
        ]
        
        for field in required:
            assert field in summary
    
    def test_status_summary_reflects_health(self):
        """Status summary should reflect component health."""
        component = ValidComponent()
        summary = component.get_status_summary()
        
        assert summary["health_status"] == HealthStatus.OK
        assert summary["contract_compliant"] is True


# =====================================================
# RUN IF MAIN
# =====================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

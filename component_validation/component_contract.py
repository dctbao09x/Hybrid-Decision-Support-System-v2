# backend/scoring/validation/component_contract.py
"""
Component Contract System for SIMGR Scoring Pipeline.

GĐ3 - COMPONENT VALIDATION HARDENING - PHẦN B

Defines abstract base contract that ALL scoring components must implement:
- validate(input_dict) → bool | raise
- healthcheck() → dict
- metadata() → dict

Components without these methods will FAIL at import/runtime.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

from backend.scoring.errors import (
    ComponentContractError,
    MissingMethodError,
    HealthcheckFailError,
)


# =====================================================
# CONTRACT VERSION
# =====================================================

CONTRACT_VERSION = "1.0"


# =====================================================
# HEALTHCHECK STATUS
# =====================================================

class HealthStatus:
    """Healthcheck status constants."""
    OK = "OK"
    DEGRADED = "DEGRADED"
    FAIL = "FAIL"


class DatasetStatus:
    """Dataset status constants."""
    READY = "ready"
    MISSING = "missing"
    STALE = "stale"


# =====================================================
# BASE CONTRACT
# =====================================================

class BaseComponentContract(ABC):
    """
    Abstract base class for all SIMGR scoring components.
    
    ALL components MUST implement:
    - validate(input_dict) → bool
    - healthcheck() → dict
    - metadata() → dict
    
    Failure to implement any method will raise MissingMethodError.
    """
    
    # Component identification (override in subclass)
    COMPONENT_NAME: str = "unknown"
    COMPONENT_VERSION: str = "1.0"
    
    @abstractmethod
    def validate(self, input_dict: Dict[str, Any]) -> bool:
        """
        Validate input data for this component.
        
        Args:
            input_dict: Input data dictionary
            
        Returns:
            True if validation passes
            
        Raises:
            ComponentContractError: If validation fails
        """
        pass
    
    @abstractmethod
    def healthcheck(self) -> Dict[str, Any]:
        """
        Perform component health check.
        
        Returns:
            Dict with structure:
            {
                "status": "OK" | "DEGRADED" | "FAIL",
                "dataset": "ready" | "missing" | "stale",
                "last_update": "ISO8601 timestamp",
                "schema_version": "version string",
                "coverage": float (0.0 to 1.0)
            }
            
        Raises:
            HealthcheckFailError: If healthcheck cannot complete
        """
        pass
    
    @abstractmethod
    def metadata(self) -> Dict[str, Any]:
        """
        Return component metadata.
        
        Returns:
            Dict with structure:
            {
                "name": "component name",
                "version": "component version",
                "contract_version": "contract version",
                "dependencies": ["list", "of", "deps"],
                "required_fields": ["list", "of", "required", "fields"]
            }
        """
        pass
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Get summary of component status."""
        health = self.healthcheck()
        meta = self.metadata()
        return {
            "component": self.COMPONENT_NAME,
            "version": self.COMPONENT_VERSION,
            "health_status": health.get("status", HealthStatus.FAIL),
            "dataset_status": health.get("dataset", DatasetStatus.MISSING),
            "last_update": health.get("last_update"),
            "contract_compliant": True,
            "checked_at": datetime.utcnow().isoformat(),
        }


# =====================================================
# CONTRACT VALIDATOR
# =====================================================

class ContractValidator:
    """
    Validates that components implement required contract methods.
    """
    
    REQUIRED_METHODS = ["validate", "healthcheck", "metadata"]
    
    @classmethod
    def check_contract(cls, component: Any) -> bool:
        """
        Check if component implements full contract.
        
        Args:
            component: Component instance to check
            
        Returns:
            True if contract is satisfied
            
        Raises:
            MissingMethodError: If any required method is missing
        """
        missing = []
        
        for method_name in cls.REQUIRED_METHODS:
            if not hasattr(component, method_name):
                missing.append(method_name)
            elif not callable(getattr(component, method_name)):
                missing.append(f"{method_name} (not callable)")
        
        if missing:
            raise MissingMethodError(
                f"Component missing required methods: {', '.join(missing)}",
                component=getattr(component, "COMPONENT_NAME", "unknown"),
                details={"missing_methods": missing}
            )
        
        return True
    
    @classmethod
    def validate_healthcheck_response(cls, response: Dict[str, Any]) -> bool:
        """
        Validate healthcheck response structure.
        
        Args:
            response: Healthcheck response dict
            
        Returns:
            True if valid
            
        Raises:
            ComponentContractError: If response is invalid
        """
        required_keys = ["status", "dataset", "last_update", "schema_version", "coverage"]
        
        for key in required_keys:
            if key not in response:
                raise ComponentContractError(
                    f"Healthcheck response missing required key: '{key}'",
                    component="healthcheck",
                    field=key
                )
        
        # Validate status value
        if response["status"] not in [HealthStatus.OK, HealthStatus.DEGRADED, HealthStatus.FAIL]:
            raise ComponentContractError(
                f"Invalid status value: '{response['status']}'",
                component="healthcheck",
                field="status",
                details={"valid_values": ["OK", "DEGRADED", "FAIL"]}
            )
        
        # Validate coverage is float
        coverage = response["coverage"]
        if not isinstance(coverage, (int, float)) or not (0.0 <= coverage <= 1.0):
            raise ComponentContractError(
                f"Coverage must be float in [0, 1], got {coverage}",
                component="healthcheck",
                field="coverage"
            )
        
        return True


# =====================================================
# COMPONENT REGISTRY
# =====================================================

class ComponentRegistry:
    """
    Registry for tracking validated components.
    """
    
    _instance: Optional["ComponentRegistry"] = None
    _components: Dict[str, BaseComponentContract]
    
    def __new__(cls) -> "ComponentRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._components = {}
        return cls._instance
    
    def register(self, component: BaseComponentContract) -> None:
        """Register a component after contract validation."""
        ContractValidator.check_contract(component)
        self._components[component.COMPONENT_NAME] = component
    
    def get(self, name: str) -> Optional[BaseComponentContract]:
        """Get component by name."""
        return self._components.get(name)
    
    def all_components(self) -> Dict[str, BaseComponentContract]:
        """Get all registered components."""
        return self._components.copy()
    
    def run_all_healthchecks(self) -> Dict[str, Dict[str, Any]]:
        """
        Run healthcheck on all registered components.
        
        Returns:
            Dict mapping component names to healthcheck results
            
        Raises:
            HealthcheckFailError: If any component fails healthcheck
        """
        results = {}
        failures = []
        
        for name, component in self._components.items():
            try:
                health = component.healthcheck()
                ContractValidator.validate_healthcheck_response(health)
                results[name] = health
                
                if health["status"] == HealthStatus.FAIL:
                    failures.append(name)
                    
            except Exception as e:
                results[name] = {
                    "status": HealthStatus.FAIL,
                    "error": str(e)
                }
                failures.append(name)
        
        if failures:
            raise HealthcheckFailError(
                f"Healthcheck failed for components: {', '.join(failures)}",
                component="registry",
                details={"failed_components": failures, "results": results}
            )
        
        return results
    
    def clear(self) -> None:
        """Clear all registered components (for testing)."""
        self._components.clear()


def get_component_registry() -> ComponentRegistry:
    """Get the global component registry."""
    return ComponentRegistry()


# =====================================================
# HELPER FUNCTIONS
# =====================================================

def create_healthcheck_response(
    status: str,
    dataset: str,
    last_update: str,
    schema_version: str,
    coverage: float,
    **extra
) -> Dict[str, Any]:
    """
    Create a properly structured healthcheck response.
    
    Args:
        status: HealthStatus value (OK, DEGRADED, FAIL)
        dataset: DatasetStatus value (ready, missing, stale)
        last_update: ISO8601 timestamp
        schema_version: Schema version string
        coverage: Coverage ratio (0.0 to 1.0)
        **extra: Additional fields
        
    Returns:
        Structured healthcheck response dict
    """
    response = {
        "status": status,
        "dataset": dataset,
        "last_update": last_update,
        "schema_version": schema_version,
        "coverage": float(coverage),
        **extra
    }
    
    # Validate before returning
    ContractValidator.validate_healthcheck_response(response)
    return response


def create_metadata_response(
    name: str,
    version: str,
    dependencies: List[str],
    required_fields: List[str],
    **extra
) -> Dict[str, Any]:
    """
    Create a properly structured metadata response.
    
    Args:
        name: Component name
        version: Component version
        dependencies: List of dependencies
        required_fields: List of required input fields
        **extra: Additional fields
        
    Returns:
        Structured metadata response dict
    """
    return {
        "name": name,
        "version": version,
        "contract_version": CONTRACT_VERSION,
        "dependencies": dependencies,
        "required_fields": required_fields,
        **extra
    }


# =====================================================
# EXPORTS
# =====================================================

__all__ = [
    "CONTRACT_VERSION",
    "HealthStatus",
    "DatasetStatus",
    "BaseComponentContract",
    "ContractValidator",
    "ComponentRegistry",
    "get_component_registry",
    "create_healthcheck_response",
    "create_metadata_response",
]

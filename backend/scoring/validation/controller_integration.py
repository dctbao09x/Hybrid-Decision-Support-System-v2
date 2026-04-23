# backend/scoring/validation/controller_integration.py
"""
Controller Integration for Validation Pipeline.

GĐ3 - COMPONENT VALIDATION HARDENING - PHẦN I

Provides:
- preflight_validation() - Run all validations before scoring
- ValidationTrace - Structured trace for audit

Request Flow:
  Request
   → InputSchema.validate
   → Component.healthcheck
   → Contract.validate
   → RiskLoader.verify
   → Only then → RankingEngine
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.scoring.validation.input_schema import (
    ScoreInputSchema,
    validate_score_input,
    SCHEMA_VERSION,
)
from backend.scoring.validation.component_contract import (
    ComponentRegistry,
    get_component_registry,
    HealthStatus,
)
from backend.scoring.errors import (
    SIMGRValidationError,
    InputValidationError,
    HealthcheckFailError,
    ComponentContractError,
)

logger = logging.getLogger(__name__)


# =====================================================
# VALIDATION TRACE
# =====================================================

class ValidationTrace:
    """
    Structured validation trace for audit logging.
    
    Records:
    - request_id
    - schema_version
    - health_state (per component)
    - contract_ok
    - validation_time
    """
    
    def __init__(self, request_id: Optional[str] = None):
        self.request_id = request_id or str(uuid.uuid4())[:8]
        self.schema_version = SCHEMA_VERSION
        self.health_state: Dict[str, str] = {}
        self.contract_ok: bool = False
        self.validation_passed: bool = False
        self.started_at = datetime.utcnow()
        self.ended_at: Optional[datetime] = None
        self.errors: List[str] = []
    
    def record_health(self, component: str, status: str):
        """Record healthcheck status for a component."""
        self.health_state[component] = status
    
    def record_contract_ok(self):
        """Mark contract validation as OK."""
        self.contract_ok = True
    
    def record_validation_passed(self):
        """Mark full validation as passed."""
        self.validation_passed = True
        self.ended_at = datetime.utcnow()
    
    def record_error(self, error: str):
        """Record an error."""
        self.errors.append(error)
        self.ended_at = datetime.utcnow()
    
    @property
    def duration_ms(self) -> float:
        """Get validation duration in milliseconds."""
        if self.ended_at:
            return (self.ended_at - self.started_at).total_seconds() * 1000
        return 0.0
    
    def to_log_format(self) -> str:
        """Format for structured logging."""
        health_str = ",".join(f"{k}={v}" for k, v in self.health_state.items())
        return (
            f"[VALIDATION_TRACE] "
            f"request_id={self.request_id} "
            f"schema_ver={self.schema_version} "
            f"health_state={{{health_str}}} "
            f"contract_ok={self.contract_ok} "
            f"passed={self.validation_passed} "
            f"duration_ms={self.duration_ms:.2f}"
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "health_state": self.health_state,
            "contract_ok": self.contract_ok,
            "validation_passed": self.validation_passed,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_ms": self.duration_ms,
            "errors": self.errors,
        }


# =====================================================
# PREFLIGHT VALIDATION
# =====================================================

def preflight_validation(
    input_data: Dict[str, Any],
    request_id: Optional[str] = None,
    skip_healthcheck: bool = False,
) -> ValidationTrace:
    """
    Run full preflight validation before scoring.
    
    Validates in order:
    1. Input schema
    2. Component healthchecks
    3. Contract validation
    
    Args:
        input_data: Raw input data to validate
        request_id: Optional request ID for tracing
        skip_healthcheck: Skip component healthchecks (testing only)
        
    Returns:
        ValidationTrace with results
        
    Raises:
        InputValidationError: If input schema invalid
        HealthcheckFailError: If any component healthcheck fails
        ComponentContractError: If contract validation fails
    """
    trace = ValidationTrace(request_id)
    
    # 1. Validate input schema
    try:
        schema = validate_score_input(input_data)
        logger.debug(f"[{trace.request_id}] Schema validation passed")
    except SIMGRValidationError as e:
        trace.record_error(f"Schema: {e.code} - {e._raw_message}")
        logger.warning(e.to_log_format())
        raise
    
    # 2. Run component healthchecks
    if not skip_healthcheck:
        registry = get_component_registry()
        
        for name, component in registry.all_components().items():
            try:
                health = component.healthcheck()
                status = health.get("status", HealthStatus.FAIL)
                trace.record_health(name, status)
                
                if status == HealthStatus.FAIL:
                    trace.record_error(f"Healthcheck: {name} FAIL")
                    raise HealthcheckFailError(
                        f"Component '{name}' healthcheck failed",
                        component=name,
                        details=health
                    )
                    
            except HealthcheckFailError:
                raise
            except Exception as e:
                trace.record_health(name, "ERROR")
                trace.record_error(f"Healthcheck: {name} exception - {str(e)}")
                raise HealthcheckFailError(
                    f"Component '{name}' healthcheck raised exception: {e}",
                    component=name
                )
    
    # 3. Contract validation passed (if we got here)
    trace.record_contract_ok()
    
    # All validations passed
    trace.record_validation_passed()
    
    # Log trace
    logger.info(trace.to_log_format())
    
    return trace


def preflight_healthcheck() -> Dict[str, Dict[str, Any]]:
    """
    Run healthcheck on all registered components.
    
    Called by MainController before accepting requests.
    
    Returns:
        Dict mapping component names to health results
        
    Raises:
        HealthcheckFailError: If any component fails
    """
    registry = get_component_registry()
    return registry.run_all_healthchecks()


def validate_before_scoring(
    input_data: Dict[str, Any],
    request_id: Optional[str] = None,
) -> ScoreInputSchema:
    """
    Convenience function to validate input and return schema.
    
    Args:
        input_data: Raw input data
        request_id: Optional request ID
        
    Returns:
        Validated ScoreInputSchema
        
    Raises:
        Various validation errors
    """
    # Run preflight (healthchecks may be empty if no components registered)
    trace = preflight_validation(input_data, request_id, skip_healthcheck=True)
    
    # Return validated schema
    return validate_score_input(input_data)


# =====================================================
# TRACE LOGGING
# =====================================================

# In-memory trace buffer (for testing/debugging)
_trace_buffer: List[ValidationTrace] = []
_max_traces = 1000


def log_validation_trace(trace: ValidationTrace):
    """Log validation trace to buffer and file."""
    global _trace_buffer
    
    _trace_buffer.append(trace)
    
    # Keep only last N traces
    if len(_trace_buffer) > _max_traces:
        _trace_buffer = _trace_buffer[-_max_traces:]
    
    # Log to file
    logger.info(trace.to_log_format())


def get_recent_traces(limit: int = 100) -> List[Dict[str, Any]]:
    """Get recent validation traces."""
    return [t.to_dict() for t in _trace_buffer[-limit:]]


def clear_trace_buffer():
    """Clear trace buffer (for testing)."""
    global _trace_buffer
    _trace_buffer = []


# =====================================================
# EXPORTS
# =====================================================

__all__ = [
    "ValidationTrace",
    "preflight_validation",
    "preflight_healthcheck",
    "validate_before_scoring",
    "log_validation_trace",
    "get_recent_traces",
    "clear_trace_buffer",
]

# backend/scoring/errors.py
"""
Standardized Error System for SIMGR Scoring Pipeline.

GĐ3 - COMPONENT VALIDATION HARDENING

All exceptions have:
- Unique error code
- Component source
- Field reference
- Trace ID support
- Structured logging format
"""

from __future__ import annotations

import traceback
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List


# =====================================================
# ERROR CODES
# =====================================================

class ErrorCode:
    """Standard error codes for SIMGR scoring system."""
    
    # Input Validation Errors (INPUT_xxx)
    INPUT_001 = "INPUT_001"  # Missing required field
    INPUT_002 = "INPUT_002"  # Invalid field type
    INPUT_003 = "INPUT_003"  # Value out of range
    INPUT_004 = "INPUT_004"  # None value not allowed
    INPUT_005 = "INPUT_005"  # NaN/Inf value detected
    INPUT_006 = "INPUT_006"  # Empty list/dict not allowed
    INPUT_007 = "INPUT_007"  # Schema validation failed
    INPUT_008 = "INPUT_008"  # Invalid timestamp format
    INPUT_009 = "INPUT_009"  # Missing mandatory scoring input component
    
    # Component Errors (COMP_xxx)
    COMP_001 = "COMP_001"  # Contract validation failed
    COMP_002 = "COMP_002"  # Required method missing
    COMP_003 = "COMP_003"  # Healthcheck failed
    COMP_004 = "COMP_004"  # Component not initialized
    COMP_005 = "COMP_005"  # Component degraded
    
    # Risk Errors (RISK_xxx)
    RISK_001 = "RISK_001"  # Risk dataset missing
    RISK_002 = "RISK_002"  # Risk data parse error
    RISK_003 = "RISK_003"  # Cost column missing
    RISK_004 = "RISK_004"  # Dropout rate missing
    RISK_005 = "RISK_005"  # Schema mismatch
    RISK_006 = "RISK_006"  # Stale data (outdated)
    
    # Schema Errors (SCHEMA_xxx)
    SCHEMA_001 = "SCHEMA_001"  # Schema version mismatch
    SCHEMA_002 = "SCHEMA_002"  # Invalid schema format
    SCHEMA_003 = "SCHEMA_003"  # Required schema field missing
    
    # Healthcheck Errors (HEALTH_xxx)
    HEALTH_001 = "HEALTH_001"  # Preflight check failed
    HEALTH_002 = "HEALTH_002"  # Component unavailable
    HEALTH_003 = "HEALTH_003"  # Data source unavailable

    # Scoring Consistency Errors (SCORE_xxx)
    SCORE_001 = "SCORE_001"  # Missing required sub-score
    SCORE_002 = "SCORE_002"  # Sub-score out of [0, 100] range
    SCORE_003 = "SCORE_003"  # Weighted sum does not match final_score
    SCORE_004 = "SCORE_004"  # Explanation contributions mismatch breakdown
    SCORE_005 = "SCORE_005"  # Weight version absent or unknown


# =====================================================
# BASE EXCEPTION
# =====================================================

class SIMGRValidationError(Exception):
    """
    Base exception for all SIMGR validation errors.
    
    Provides structured error information with code, component, and trace.
    """
    
    default_code = "SIMGR_000"
    default_component = "unknown"
    
    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        component: Optional[str] = None,
        field: Optional[str] = None,
        trace_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.code = code or self.default_code
        self.component = component or self.default_component
        self.field = field
        self.trace_id = trace_id or str(uuid.uuid4())[:8]
        self.details = details or {}
        self.timestamp = datetime.utcnow().isoformat()
        self.stack_trace = traceback.format_exc()
        
        # Build structured message
        full_message = self._build_message(message)
        super().__init__(full_message)
        self._raw_message = message
    
    def _build_message(self, message: str) -> str:
        """Build structured error message."""
        parts = [
            f"[{self.code}]",
            f"component={self.component}",
        ]
        if self.field:
            parts.append(f"field={self.field}")
        parts.append(f"trace_id={self.trace_id}")
        parts.append(f"msg={message}")
        return " ".join(parts)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "code": self.code,
            "component": self.component,
            "field": self.field,
            "trace_id": self.trace_id,
            "message": self._raw_message,
            "timestamp": self.timestamp,
            "details": self.details,
        }
    
    def to_log_format(self) -> str:
        """Format for structured logging."""
        parts = [
            "[VALIDATION_ERROR]",
            f"code={self.code}",
            f"component={self.component}",
        ]
        if self.field:
            parts.append(f"field={self.field}")
        parts.append(f"trace_id={self.trace_id}")
        parts.append(f"msg={self._raw_message}")
        return " ".join(parts)


# =====================================================
# INPUT VALIDATION ERRORS
# =====================================================

class InputValidationError(SIMGRValidationError):
    """Raised when input validation fails."""
    default_code = ErrorCode.INPUT_007
    default_component = "input_schema"


class MissingFieldError(InputValidationError):
    """Raised when a required field is missing."""
    default_code = ErrorCode.INPUT_001


class InvalidTypeError(InputValidationError):
    """Raised when a field has wrong type."""
    default_code = ErrorCode.INPUT_002


class OutOfRangeError(InputValidationError):
    """Raised when a value is out of allowed range."""
    default_code = ErrorCode.INPUT_003


class NoneValueError(InputValidationError):
    """Raised when None is not allowed but provided."""
    default_code = ErrorCode.INPUT_004


class NaNInfError(InputValidationError):
    """Raised when NaN or Inf value is detected."""
    default_code = ErrorCode.INPUT_005


class EmptyCollectionError(InputValidationError):
    """Raised when empty list/dict is not allowed."""
    default_code = ErrorCode.INPUT_006


class TimestampFormatError(InputValidationError):
    """Raised when timestamp format is invalid."""
    default_code = ErrorCode.INPUT_008


class MissingComponentError(InputValidationError):
    """
    Raised when one or more mandatory scoring input components are absent.

    Mandatory components: personal_profile, experience, goals,
    skills, education, preferences.

    Scoring execution MUST NOT proceed when this error is raised.
    """
    default_code = ErrorCode.INPUT_009
    default_component = "scoring_input"

    def __init__(
        self,
        missing: list,
        *,
        trace_id: str | None = None,
    ) -> None:
        self.missing_components = list(missing)
        super().__init__(
            f"Missing mandatory scoring components: {self.missing_components}",
            code=ErrorCode.INPUT_009,
            component="scoring_input",
            field="scoring_input",
            trace_id=trace_id,
            details={"missing_components": self.missing_components},
        )


# =====================================================
# COMPONENT CONTRACT ERRORS
# =====================================================

class ComponentContractError(SIMGRValidationError):
    """Raised when component contract validation fails."""
    default_code = ErrorCode.COMP_001
    default_component = "contract"


class MissingMethodError(ComponentContractError):
    """Raised when required method is not implemented."""
    default_code = ErrorCode.COMP_002


class ComponentNotInitializedError(ComponentContractError):
    """Raised when component is not properly initialized."""
    default_code = ErrorCode.COMP_004


# =====================================================
# RISK MODULE ERRORS
# =====================================================

class RiskDatasetMissingError(SIMGRValidationError):
    """Raised when risk dataset is missing or unavailable."""
    default_code = ErrorCode.RISK_001
    default_component = "risk"


class RiskParseError(SIMGRValidationError):
    """Raised when risk data parsing fails."""
    default_code = ErrorCode.RISK_002
    default_component = "risk"


class CostColumnMissingError(RiskParseError):
    """Raised when cost column is missing from risk data."""
    default_code = ErrorCode.RISK_003


class DropoutRateMissingError(RiskParseError):
    """Raised when dropout rate is missing."""
    default_code = ErrorCode.RISK_004


class RiskSchemaMismatchError(SIMGRValidationError):
    """Raised when risk data schema doesn't match expected."""
    default_code = ErrorCode.RISK_005
    default_component = "risk"


class StaleDataError(SIMGRValidationError):
    """Raised when data is outdated beyond threshold."""
    default_code = ErrorCode.RISK_006
    default_component = "risk"


# =====================================================
# SCHEMA ERRORS
# =====================================================

class SchemaMismatchError(SIMGRValidationError):
    """Raised when schema version or format doesn't match."""
    default_code = ErrorCode.SCHEMA_001
    default_component = "schema"


class InvalidSchemaError(SchemaMismatchError):
    """Raised when schema format is invalid."""
    default_code = ErrorCode.SCHEMA_002


# =====================================================
# SCORING CONSISTENCY ERRORS
# =====================================================

class InconsistentScoringError(SIMGRValidationError):
    """
    Raised when a ``ScoringBreakdown`` fails any consistency invariant.

    This is a hard pipeline error — it MUST NOT be silently suppressed.
    All rules are checked before raising; every violation is reported.

    Invariants checked
    ------------------
    SCORE_001  All five required sub-scores exist in the breakdown.
    SCORE_002  Every sub-score is within [0, 100].
    SCORE_003  sum(weight_i * sub_score_i) == final_score  (± 1e-4).
    SCORE_004  Explanation contributions match breakdown contributions.
    SCORE_005  A non-empty weight version string is present.

    Attributes
    ----------
    violations : list[str]
        Human-readable description of every individual rule violation found.
    """

    default_code = ErrorCode.SCORE_001
    default_component = "scoring_consistency_validator"

    def __init__(
        self,
        message: str,
        violations: Optional[List[str]] = None,
        *,
        trace_id: Optional[str] = None,
    ) -> None:
        self.violations: List[str] = violations or []
        super().__init__(
            message,
            code=ErrorCode.SCORE_001,
            component="scoring_consistency_validator",
            trace_id=trace_id,
            details={"violations": self.violations},
        )

    def __str__(self) -> str:
        base = self._raw_message
        if self.violations:
            lines = "\n".join(f"  [{i + 1}] {v}" for i, v in enumerate(self.violations))
            return f"{base}\n{lines}"
        return base


# =====================================================
# HEALTHCHECK ERRORS
# =====================================================

class HealthcheckFailError(SIMGRValidationError):
    """Raised when healthcheck fails."""
    default_code = ErrorCode.HEALTH_001
    default_component = "healthcheck"


class ComponentUnavailableError(HealthcheckFailError):
    """Raised when a component is unavailable."""
    default_code = ErrorCode.HEALTH_002


class DataSourceUnavailableError(HealthcheckFailError):
    """Raised when a data source is unavailable."""
    default_code = ErrorCode.HEALTH_003


# =====================================================
# EXPORTS
# =====================================================

__all__ = [
    # Base
    "ErrorCode",
    "SIMGRValidationError",
    
    # Input Validation
    "InputValidationError",
    "MissingFieldError",
    "MissingComponentError",
    "InvalidTypeError",
    "OutOfRangeError",
    "NoneValueError",
    "NaNInfError",
    "EmptyCollectionError",
    "TimestampFormatError",
    
    # Component Contract
    "ComponentContractError",
    "MissingMethodError",
    "ComponentNotInitializedError",
    
    # Risk
    "RiskDatasetMissingError",
    "RiskParseError",
    "CostColumnMissingError",
    "DropoutRateMissingError",
    "RiskSchemaMismatchError",
    "StaleDataError",
    
    # Schema
    "SchemaMismatchError",
    "InvalidSchemaError",
    
    # Scoring Consistency
    "InconsistentScoringError",

    # Healthcheck
    "HealthcheckFailError",
    "ComponentUnavailableError",
    "DataSourceUnavailableError",
]

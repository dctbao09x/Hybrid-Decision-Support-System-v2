# backend/scoring/validation/__init__.py
"""
Validation Module for SIMGR Scoring Pipeline.

GĐ3 - COMPONENT VALIDATION HARDENING

Provides:
- Input schema enforcement
- Component contracts
- Type safety guards
- Healthcheck system
- Controller integration

All imports are re-exported for convenience.
"""

from backend.scoring.validation.input_schema import (
    SCHEMA_VERSION,
    MANDATORY_SCORING_COMPONENTS,
    validate_scoring_components,
    ScoreInputSchema,
    ScoresDict,
    FeaturesDict,
    validate_score_input,
    validate_score_value,
    is_valid_timestamp,
)

from backend.scoring.validation.component_contract import (
    CONTRACT_VERSION,
    HealthStatus,
    DatasetStatus,
    BaseComponentContract,
    ContractValidator,
    ComponentRegistry,
    get_component_registry,
    create_healthcheck_response,
    create_metadata_response,
)

from backend.scoring.validation.validation_guard import (
    check_not_none,
    check_type,
    check_not_nan_inf,
    check_not_empty,
    check_dict_keys,
    check_valid_json,
    validate_all_inputs,
    type_guard,
    reject_none,
    require_keys,
    validate_scoring_input,
)

from backend.scoring.validation.controller_integration import (
    ValidationTrace,
    preflight_validation,
    preflight_healthcheck,
    validate_before_scoring,
    log_validation_trace,
    get_recent_traces,
    clear_trace_buffer,
)


__all__ = [
    # Schema
    "SCHEMA_VERSION",
    "MANDATORY_SCORING_COMPONENTS",
    "validate_scoring_components",
    "ScoreInputSchema",
    "ScoresDict",
    "FeaturesDict",
    "validate_score_input",
    "validate_score_value",
    "is_valid_timestamp",
    
    # Contract
    "CONTRACT_VERSION",
    "HealthStatus",
    "DatasetStatus",
    "BaseComponentContract",
    "ContractValidator",
    "ComponentRegistry",
    "get_component_registry",
    "create_healthcheck_response",
    "create_metadata_response",
    
    # Guards
    "check_not_none",
    "check_type",
    "check_not_nan_inf",
    "check_not_empty",
    "check_dict_keys",
    "check_valid_json",
    "validate_all_inputs",
    "type_guard",
    "reject_none",
    "require_keys",
    "validate_scoring_input",
    
    # Controller integration
    "ValidationTrace",
    "preflight_validation",
    "preflight_healthcheck",
    "validate_before_scoring",
    "log_validation_trace",
    "get_recent_traces",
    "clear_trace_buffer",
]

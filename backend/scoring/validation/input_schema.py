# backend/scoring/validation/input_schema.py
"""
Input Schema Enforcement for SIMGR Scoring Pipeline.

GĐ3 - COMPONENT VALIDATION HARDENING - PHẦN A
GĐ4 - Uses ScoringFormula.COMPONENTS for canonical component list.

Enforces:
- All required fields present
- No None values
- No NaN/Inf values
- All values in valid range
- Proper timestamp format
- Valid control token

NO FALLBACKS. NO DEFAULTS. FAIL FAST.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

from backend.scoring.errors import (
    InputValidationError,
    MissingFieldError,
    MissingComponentError,
    InvalidTypeError,
    OutOfRangeError,
    NoneValueError,
    NaNInfError,
    TimestampFormatError,
)
from backend.scoring.scoring_formula import ScoringFormula


# =====================================================
# SCHEMA VERSION
# =====================================================

SCHEMA_VERSION = "3.0"
ISO8601_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$"
)


# =====================================================
# MANDATORY SCORING COMPONENTS
# =====================================================

#: The exact set of top-level components that MUST be present in every
#: ScoringInput before any scoring execution is allowed.  This list is the
#: single source of truth — update here if the contract changes.
MANDATORY_SCORING_COMPONENTS: tuple[str, ...] = (
    "personal_profile",
    "experience",
    "goals",
    "skills",
    "education",
    "preferences",
)


def validate_scoring_components(
    scoring_input: Any,
    *,
    trace_id: str = "-",
) -> None:
    """
    Gate: verify all mandatory scoring components are present and non-null.

    This function is the SINGLE enforcement point that must be called before
    any scoring execution path.  It:

    1. Builds a component-presence matrix and emits it to the structured log.
    2. Raises ``MissingComponentError`` immediately if ANY component is absent
       or ``None``; scoring execution is BLOCKED.

    Parameters
    ----------
    scoring_input:
        A ``ScoringInput`` Pydantic model instance **or** a plain ``dict``
        that must contain all six mandatory component keys.
    trace_id:
        Decision trace ID propagated from the controller for log correlation.

    Raises
    ------
    MissingComponentError
        Deterministically raised when one or more mandatory components are
        absent.  The ``missing_components`` attribute lists every absent key.

    Notes
    -----
    - NO try/except should wrap this call in the controller — let it propagate.
    - A ``dict`` input is accepted to allow validation before Pydantic
      construction (e.g. in raw-payload middleware paths).
    """
    import logging as _logging
    _log = _logging.getLogger("scoring.validation.input_schema")

    # Normalise to dict for uniform key access
    if hasattr(scoring_input, "model_dump"):
        raw: Dict[str, Any] = scoring_input.model_dump()
    elif hasattr(scoring_input, "dict"):
        raw = scoring_input.dict()
    elif isinstance(scoring_input, dict):
        raw = scoring_input
    else:
        raise InvalidTypeError(
            f"scoring_input must be ScoringInput or dict, got {type(scoring_input).__name__}",
            field="scoring_input",
            component="scoring_input",
        )

    # ── Component presence matrix ────────────────────────────────────────────
    matrix: Dict[str, str] = {}
    missing: List[str] = []
    for component in MANDATORY_SCORING_COMPONENTS:
        value = raw.get(component)
        if value is None:
            matrix[component] = "MISSING"
            missing.append(component)
        elif isinstance(value, (list, dict)) and len(value) == 0:
            # Empty list/dict treated as effectively absent for skills/domains
            matrix[component] = "EMPTY"
            missing.append(component)
        else:
            matrix[component] = "PRESENT"

    # ── Structured log — always emitted ─────────────────────────────────────
    # NOTE: keep symbols ASCII-only — Windows cp1252 console cannot encode
    # Unicode check marks and will crash the logging StreamHandler (UnicodeEncodeError).
    matrix_lines = "  ".join(
        f"{c}={'[OK]' if s == 'PRESENT' else '[' + s + ']'}" for c, s in matrix.items()
    )
    _log.info(
        "[%s] COMPONENT_PRESENCE_MATRIX  %s",
        trace_id,
        matrix_lines,
    )

    # ── Hard gate — no bypass ────────────────────────────────────────────────
    if missing:
        _log.error(
            "[%s] SCORING_BLOCKED: missing mandatory components %s",
            trace_id,
            missing,
        )
        raise MissingComponentError(missing, trace_id=trace_id)


# =====================================================
# TYPE DEFINITIONS
# =====================================================

class ScoresDict(TypedDict):
    """Required scores structure."""
    study: float
    interest: float
    market: float
    growth: float
    risk: float


class FeaturesDict(TypedDict, total=False):
    """Optional features structure."""
    career_id: str
    skills: List[str]
    education: str
    experience: int


# =====================================================
# INPUT SCHEMA
# =====================================================

@dataclass
class ScoreInputSchema:
    """
    Validated score input schema.
    
    All fields are REQUIRED. No defaults. No None allowed.
    
    Raises InputValidationError on any validation failure.
    """
    
    user_id: str
    session_id: str
    features: Dict[str, Any]
    scores: ScoresDict
    timestamp: str  # ISO8601
    weight_version: str
    control_token: str
    
    # Optional metadata (can be empty dict but must exist)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate after initialization."""
        self._validate_all()
    
    def _validate_all(self):
        """Run all validations."""
        self._validate_strings()
        self._validate_scores()
        self._validate_timestamp()
        self._validate_features()
    
    def _validate_strings(self):
        """Validate required string fields."""
        string_fields = [
            ("user_id", self.user_id),
            ("session_id", self.session_id),
            ("weight_version", self.weight_version),
            ("control_token", self.control_token),
        ]
        
        for field_name, value in string_fields:
            if value is None:
                raise NoneValueError(
                    f"Field '{field_name}' cannot be None",
                    field=field_name,
                    component="input_schema"
                )
            if not isinstance(value, str):
                raise InvalidTypeError(
                    f"Field '{field_name}' must be string, got {type(value).__name__}",
                    field=field_name,
                    component="input_schema"
                )
            if not value.strip():
                raise MissingFieldError(
                    f"Field '{field_name}' cannot be empty",
                    field=field_name,
                    component="input_schema"
                )
    
    def _validate_scores(self):
        """Validate scores dict with all required components."""
        if self.scores is None:
            raise NoneValueError(
                "Field 'scores' cannot be None",
                field="scores",
                component="input_schema"
            )
        
        if not isinstance(self.scores, dict):
            raise InvalidTypeError(
                f"Field 'scores' must be dict, got {type(self.scores).__name__}",
                field="scores",
                component="input_schema"
            )
        
        # GĐ4: Use canonical component list from ScoringFormula
        required_score_keys = ScoringFormula.COMPONENTS
        
        for key in required_score_keys:
            # Check key exists
            if key not in self.scores:
                raise MissingFieldError(
                    f"Missing required score: '{key}'",
                    field=f"scores.{key}",
                    component="input_schema"
                )
            
            value = self.scores[key]
            
            # Check not None
            if value is None:
                raise NoneValueError(
                    f"Score '{key}' cannot be None",
                    field=f"scores.{key}",
                    component="input_schema"
                )
            
            # Check type
            if not isinstance(value, (int, float)):
                raise InvalidTypeError(
                    f"Score '{key}' must be numeric, got {type(value).__name__}",
                    field=f"scores.{key}",
                    component="input_schema"
                )
            
            # Check NaN/Inf
            if math.isnan(value) or math.isinf(value):
                raise NaNInfError(
                    f"Score '{key}' contains NaN or Inf",
                    field=f"scores.{key}",
                    component="input_schema"
                )
            
            # Check range [0, 1]
            if not (0.0 <= value <= 1.0):
                raise OutOfRangeError(
                    f"Score '{key}' must be in [0, 1], got {value}",
                    field=f"scores.{key}",
                    component="input_schema",
                    details={"value": value, "min": 0.0, "max": 1.0}
                )
    
    def _validate_timestamp(self):
        """Validate ISO8601 timestamp format."""
        if self.timestamp is None:
            raise NoneValueError(
                "Field 'timestamp' cannot be None",
                field="timestamp",
                component="input_schema"
            )
        
        if not isinstance(self.timestamp, str):
            raise InvalidTypeError(
                f"Field 'timestamp' must be string, got {type(self.timestamp).__name__}",
                field="timestamp",
                component="input_schema"
            )
        
        if not ISO8601_PATTERN.match(self.timestamp):
            raise TimestampFormatError(
                f"Timestamp must be ISO8601 format, got '{self.timestamp}'",
                field="timestamp",
                component="input_schema"
            )
    
    def _validate_features(self):
        """Validate features dict."""
        if self.features is None:
            raise NoneValueError(
                "Field 'features' cannot be None",
                field="features",
                component="input_schema"
            )
        
        if not isinstance(self.features, dict):
            raise InvalidTypeError(
                f"Field 'features' must be dict, got {type(self.features).__name__}",
                field="features",
                component="input_schema"
            )
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScoreInputSchema":
        """
        Create schema from dictionary with validation.
        
        Raises InputValidationError if any field is missing or invalid.
        """
        if data is None:
            raise NoneValueError(
                "Input data cannot be None",
                field="data",
                component="input_schema"
            )
        
        if not isinstance(data, dict):
            raise InvalidTypeError(
                f"Input must be dict, got {type(data).__name__}",
                field="data",
                component="input_schema"
            )
        
        required_keys = [
            "user_id", "session_id", "features", "scores",
            "timestamp", "weight_version", "control_token"
        ]
        
        for key in required_keys:
            if key not in data:
                raise MissingFieldError(
                    f"Missing required field: '{key}'",
                    field=key,
                    component="input_schema"
                )
        
        return cls(
            user_id=data["user_id"],
            session_id=data["session_id"],
            features=data["features"],
            scores=data["scores"],
            timestamp=data["timestamp"],
            weight_version=data["weight_version"],
            control_token=data["control_token"],
            metadata=data.get("metadata", {}),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "features": self.features,
            "scores": self.scores,
            "timestamp": self.timestamp,
            "weight_version": self.weight_version,
            "control_token": self.control_token,
            "metadata": self.metadata,
            "schema_version": SCHEMA_VERSION,
        }


# =====================================================
# VALIDATION FUNCTIONS
# =====================================================

def validate_score_input(data: Dict[str, Any]) -> ScoreInputSchema:
    """
    Validate score input and return schema object.
    
    Args:
        data: Input dictionary to validate
        
    Returns:
        Validated ScoreInputSchema
        
    Raises:
        InputValidationError: If any validation fails
    """
    return ScoreInputSchema.from_dict(data)


def validate_score_value(value: Any, field_name: str) -> float:
    """
    Validate a single score value.
    
    Args:
        value: Score value to validate
        field_name: Field name for error messages
        
    Returns:
        Validated float value
        
    Raises:
        NoneValueError: If value is None
        InvalidTypeError: If not numeric
        NaNInfError: If NaN or Inf
        OutOfRangeError: If not in [0, 1]
    """
    if value is None:
        raise NoneValueError(
            f"Score '{field_name}' cannot be None",
            field=field_name,
            component="input_schema"
        )
    
    if not isinstance(value, (int, float)):
        raise InvalidTypeError(
            f"Score '{field_name}' must be numeric, got {type(value).__name__}",
            field=field_name,
            component="input_schema"
        )
    
    if math.isnan(value) or math.isinf(value):
        raise NaNInfError(
            f"Score '{field_name}' contains NaN or Inf",
            field=field_name,
            component="input_schema"
        )
    
    if not (0.0 <= value <= 1.0):
        raise OutOfRangeError(
            f"Score '{field_name}' must be in [0, 1], got {value}",
            field=field_name,
            component="input_schema",
            details={"value": value, "min": 0.0, "max": 1.0}
        )
    
    return float(value)


def is_valid_timestamp(ts: str) -> bool:
    """Check if timestamp is valid ISO8601 format."""
    if not isinstance(ts, str):
        return False
    return bool(ISO8601_PATTERN.match(ts))


# =====================================================
# EXPORTS
# =====================================================

__all__ = [
    "SCHEMA_VERSION",
    "MANDATORY_SCORING_COMPONENTS",
    "validate_scoring_components",
    "ScoreInputSchema",
    "ScoresDict",
    "FeaturesDict",
    "validate_score_input",
    "validate_score_value",
    "is_valid_timestamp",
]

# tests/scoring_validation/test_input_validation.py
"""
Input Validation Tests for SIMGR Scoring Pipeline.

GĐ3 - COMPONENT VALIDATION HARDENING - PHẦN G

Tests:
- test_none_input_rejected
- test_nan_input_rejected
- test_schema_violation_blocked
- test_missing_field_rejected
- test_out_of_range_rejected
- test_invalid_timestamp_rejected
"""

import math
import pytest
from unittest.mock import patch

# Import from scoring module
import sys
sys.path.insert(0, "F:/Hybrid Decision Support System")

from backend.scoring.validation.input_schema import (
    ScoreInputSchema,
    validate_score_input,
    validate_score_value,
    SCHEMA_VERSION,
)
from backend.scoring.errors import (
    InputValidationError,
    NoneValueError,
    InvalidTypeError,
    OutOfRangeError,
    NaNInfError,
    MissingFieldError,
    TimestampFormatError,
)


# =====================================================
# VALID TEST DATA
# =====================================================

def make_valid_input():
    """Create valid test input."""
    return {
        "user_id": "user_123",
        "session_id": "session_456",
        "features": {"career_id": "software_engineer", "skills": ["python", "java"]},
        "scores": {
            "study": 0.75,
            "interest": 0.80,
            "market": 0.65,
            "growth": 0.70,
            "risk": 0.30,
        },
        "timestamp": "2026-02-16T12:00:00Z",
        "weight_version": "v1",
        "control_token": "token_abc123",
    }


# =====================================================
# NONE INPUT TESTS
# =====================================================

class TestNoneInputRejected:
    """Tests for None value rejection."""
    
    def test_none_user_id_rejected(self):
        """None user_id should be rejected."""
        data = make_valid_input()
        data["user_id"] = None
        
        with pytest.raises(NoneValueError) as exc:
            validate_score_input(data)
        
        assert "user_id" in str(exc.value)
        assert exc.value.code == "INPUT_004"
    
    def test_none_session_id_rejected(self):
        """None session_id should be rejected."""
        data = make_valid_input()
        data["session_id"] = None
        
        with pytest.raises(NoneValueError) as exc:
            validate_score_input(data)
        
        assert "session_id" in str(exc.value)
    
    def test_none_scores_rejected(self):
        """None scores dict should be rejected."""
        data = make_valid_input()
        data["scores"] = None
        
        with pytest.raises(NoneValueError) as exc:
            validate_score_input(data)
        
        assert "scores" in str(exc.value)
    
    def test_none_score_value_rejected(self):
        """None individual score should be rejected."""
        data = make_valid_input()
        data["scores"]["study"] = None
        
        with pytest.raises(NoneValueError) as exc:
            validate_score_input(data)
        
        assert "study" in str(exc.value)
    
    def test_none_timestamp_rejected(self):
        """None timestamp should be rejected."""
        data = make_valid_input()
        data["timestamp"] = None
        
        with pytest.raises(NoneValueError) as exc:
            validate_score_input(data)
        
        assert "timestamp" in str(exc.value)
    
    def test_none_control_token_rejected(self):
        """None control_token should be rejected."""
        data = make_valid_input()
        data["control_token"] = None
        
        with pytest.raises(NoneValueError) as exc:
            validate_score_input(data)
        
        assert "control_token" in str(exc.value)
    
    def test_entire_input_none_rejected(self):
        """Entire input being None should be rejected."""
        with pytest.raises(NoneValueError) as exc:
            validate_score_input(None)
        
        assert exc.value.code == "INPUT_004"


# =====================================================
# NAN/INF INPUT TESTS
# =====================================================

class TestNaNInputRejected:
    """Tests for NaN/Inf value rejection."""
    
    def test_nan_score_rejected(self):
        """NaN score should be rejected."""
        data = make_valid_input()
        data["scores"]["study"] = float('nan')
        
        with pytest.raises(NaNInfError) as exc:
            validate_score_input(data)
        
        assert "study" in str(exc.value)
        assert exc.value.code == "INPUT_005"
    
    def test_inf_score_rejected(self):
        """Inf score should be rejected."""
        data = make_valid_input()
        data["scores"]["market"] = float('inf')
        
        with pytest.raises(NaNInfError) as exc:
            validate_score_input(data)
        
        assert "market" in str(exc.value)
    
    def test_negative_inf_score_rejected(self):
        """Negative Inf score should be rejected."""
        data = make_valid_input()
        data["scores"]["growth"] = float('-inf')
        
        with pytest.raises(NaNInfError) as exc:
            validate_score_input(data)
        
        assert "growth" in str(exc.value)
    
    def test_validate_score_value_rejects_nan(self):
        """validate_score_value should reject NaN."""
        with pytest.raises(NaNInfError):
            validate_score_value(float('nan'), "test_field")
    
    def test_validate_score_value_rejects_inf(self):
        """validate_score_value should reject Inf."""
        with pytest.raises(NaNInfError):
            validate_score_value(float('inf'), "test_field")


# =====================================================
# SCHEMA VIOLATION TESTS
# =====================================================

class TestSchemaViolationBlocked:
    """Tests for schema violation blocking."""
    
    def test_wrong_type_user_id_blocked(self):
        """Non-string user_id should be blocked."""
        data = make_valid_input()
        data["user_id"] = 12345  # Should be string
        
        with pytest.raises(InvalidTypeError) as exc:
            validate_score_input(data)
        
        assert "user_id" in str(exc.value)
        assert exc.value.code == "INPUT_002"
    
    def test_wrong_type_scores_blocked(self):
        """Non-dict scores should be blocked."""
        data = make_valid_input()
        data["scores"] = [0.5, 0.6, 0.7]  # Should be dict
        
        with pytest.raises(InvalidTypeError) as exc:
            validate_score_input(data)
        
        assert "scores" in str(exc.value)
    
    def test_wrong_type_score_value_blocked(self):
        """Non-numeric score value should be blocked."""
        data = make_valid_input()
        data["scores"]["study"] = "high"  # Should be float
        
        with pytest.raises(InvalidTypeError) as exc:
            validate_score_input(data)
        
        assert "study" in str(exc.value)
    
    def test_wrong_type_features_blocked(self):
        """Non-dict features should be blocked."""
        data = make_valid_input()
        data["features"] = "skills=python"  # Should be dict
        
        with pytest.raises(InvalidTypeError) as exc:
            validate_score_input(data)
        
        assert "features" in str(exc.value)


# =====================================================
# MISSING FIELD TESTS
# =====================================================

class TestMissingFieldRejected:
    """Tests for missing field rejection."""
    
    def test_missing_user_id_rejected(self):
        """Missing user_id should be rejected."""
        data = make_valid_input()
        del data["user_id"]
        
        with pytest.raises(MissingFieldError) as exc:
            validate_score_input(data)
        
        assert "user_id" in str(exc.value)
        assert exc.value.code == "INPUT_001"
    
    def test_missing_scores_rejected(self):
        """Missing scores should be rejected."""
        data = make_valid_input()
        del data["scores"]
        
        with pytest.raises(MissingFieldError) as exc:
            validate_score_input(data)
        
        assert "scores" in str(exc.value)
    
    def test_missing_score_key_rejected(self):
        """Missing score key should be rejected."""
        data = make_valid_input()
        del data["scores"]["risk"]  # Remove required score
        
        with pytest.raises(MissingFieldError) as exc:
            validate_score_input(data)
        
        assert "risk" in str(exc.value)
    
    def test_missing_timestamp_rejected(self):
        """Missing timestamp should be rejected."""
        data = make_valid_input()
        del data["timestamp"]
        
        with pytest.raises(MissingFieldError) as exc:
            validate_score_input(data)
        
        assert "timestamp" in str(exc.value)
    
    def test_missing_weight_version_rejected(self):
        """Missing weight_version should be rejected."""
        data = make_valid_input()
        del data["weight_version"]
        
        with pytest.raises(MissingFieldError) as exc:
            validate_score_input(data)
        
        assert "weight_version" in str(exc.value)
    
    def test_missing_control_token_rejected(self):
        """Missing control_token should be rejected."""
        data = make_valid_input()
        del data["control_token"]
        
        with pytest.raises(MissingFieldError) as exc:
            validate_score_input(data)
        
        assert "control_token" in str(exc.value)
    
    def test_empty_string_user_id_rejected(self):
        """Empty string user_id should be rejected."""
        data = make_valid_input()
        data["user_id"] = ""
        
        with pytest.raises(MissingFieldError) as exc:
            validate_score_input(data)
        
        assert "user_id" in str(exc.value)
    
    def test_whitespace_only_rejected(self):
        """Whitespace-only string should be rejected."""
        data = make_valid_input()
        data["session_id"] = "   "
        
        with pytest.raises(MissingFieldError) as exc:
            validate_score_input(data)
        
        assert "session_id" in str(exc.value)


# =====================================================
# OUT OF RANGE TESTS
# =====================================================

class TestOutOfRangeRejected:
    """Tests for out-of-range value rejection."""
    
    def test_score_above_1_rejected(self):
        """Score above 1.0 should be rejected."""
        data = make_valid_input()
        data["scores"]["study"] = 1.5
        
        with pytest.raises(OutOfRangeError) as exc:
            validate_score_input(data)
        
        assert "study" in str(exc.value)
        assert exc.value.code == "INPUT_003"
    
    def test_score_below_0_rejected(self):
        """Score below 0.0 should be rejected."""
        data = make_valid_input()
        data["scores"]["interest"] = -0.1
        
        with pytest.raises(OutOfRangeError) as exc:
            validate_score_input(data)
        
        assert "interest" in str(exc.value)
    
    def test_large_positive_score_rejected(self):
        """Large positive score should be rejected."""
        data = make_valid_input()
        data["scores"]["market"] = 100.0
        
        with pytest.raises(OutOfRangeError) as exc:
            validate_score_input(data)
        
        assert "market" in str(exc.value)
    
    def test_large_negative_score_rejected(self):
        """Large negative score should be rejected."""
        data = make_valid_input()
        data["scores"]["growth"] = -50.0
        
        with pytest.raises(OutOfRangeError) as exc:
            validate_score_input(data)
        
        assert "growth" in str(exc.value)
    
    def test_boundary_0_accepted(self):
        """Score of exactly 0.0 should be accepted."""
        data = make_valid_input()
        data["scores"]["risk"] = 0.0
        
        schema = validate_score_input(data)
        assert schema.scores["risk"] == 0.0
    
    def test_boundary_1_accepted(self):
        """Score of exactly 1.0 should be accepted."""
        data = make_valid_input()
        data["scores"]["risk"] = 1.0
        
        schema = validate_score_input(data)
        assert schema.scores["risk"] == 1.0


# =====================================================
# TIMESTAMP TESTS
# =====================================================

class TestTimestampValidation:
    """Tests for timestamp format validation."""
    
    def test_invalid_timestamp_format_rejected(self):
        """Invalid timestamp format should be rejected."""
        data = make_valid_input()
        data["timestamp"] = "2026/02/16"  # Wrong format
        
        with pytest.raises(TimestampFormatError) as exc:
            validate_score_input(data)
        
        assert "timestamp" in str(exc.value)
        assert exc.value.code == "INPUT_008"
    
    def test_unix_timestamp_rejected(self):
        """Unix timestamp should be rejected."""
        data = make_valid_input()
        data["timestamp"] = "1708099200"  # Unix timestamp
        
        with pytest.raises(TimestampFormatError):
            validate_score_input(data)
    
    def test_valid_iso8601_z_accepted(self):
        """Valid ISO8601 with Z suffix should be accepted."""
        data = make_valid_input()
        data["timestamp"] = "2026-02-16T12:00:00Z"
        
        schema = validate_score_input(data)
        assert schema.timestamp == "2026-02-16T12:00:00Z"
    
    def test_valid_iso8601_offset_accepted(self):
        """Valid ISO8601 with offset should be accepted."""
        data = make_valid_input()
        data["timestamp"] = "2026-02-16T12:00:00+07:00"
        
        schema = validate_score_input(data)
        assert "2026-02-16" in schema.timestamp
    
    def test_valid_iso8601_millis_accepted(self):
        """Valid ISO8601 with milliseconds should be accepted."""
        data = make_valid_input()
        data["timestamp"] = "2026-02-16T12:00:00.123456Z"
        
        schema = validate_score_input(data)
        assert "2026-02-16" in schema.timestamp


# =====================================================
# VALID INPUT TESTS
# =====================================================

class TestValidInputAccepted:
    """Tests for valid input acceptance."""
    
    def test_valid_input_accepted(self):
        """Valid input should be accepted."""
        data = make_valid_input()
        schema = validate_score_input(data)
        
        assert schema.user_id == "user_123"
        assert schema.session_id == "session_456"
        assert schema.scores["study"] == 0.75
        assert schema.weight_version == "v1"
    
    def test_integer_scores_accepted(self):
        """Integer scores (0 or 1) should be accepted."""
        data = make_valid_input()
        data["scores"]["study"] = 1
        data["scores"]["interest"] = 0
        
        schema = validate_score_input(data)
        assert schema.scores["study"] == 1
        assert schema.scores["interest"] == 0
    
    def test_schema_version_included(self):
        """Schema version should be in output."""
        data = make_valid_input()
        schema = validate_score_input(data)
        
        output = schema.to_dict()
        assert output["schema_version"] == SCHEMA_VERSION


# =====================================================
# ERROR FORMAT TESTS
# =====================================================

class TestErrorFormat:
    """Tests for error format compliance."""
    
    def test_error_has_code(self):
        """Errors should have error code."""
        data = make_valid_input()
        data["user_id"] = None
        
        with pytest.raises(NoneValueError) as exc:
            validate_score_input(data)
        
        assert exc.value.code is not None
        assert exc.value.code.startswith("INPUT_")
    
    def test_error_has_component(self):
        """Errors should have component name."""
        data = make_valid_input()
        data["scores"]["study"] = "invalid"
        
        with pytest.raises(InvalidTypeError) as exc:
            validate_score_input(data)
        
        assert exc.value.component == "input_schema"
    
    def test_error_has_field(self):
        """Errors should have field name."""
        data = make_valid_input()
        data["scores"]["market"] = float('nan')
        
        with pytest.raises(NaNInfError) as exc:
            validate_score_input(data)
        
        assert exc.value.field is not None
        assert "market" in exc.value.field
    
    def test_error_has_trace_id(self):
        """Errors should have trace ID."""
        data = make_valid_input()
        data["user_id"] = None
        
        with pytest.raises(NoneValueError) as exc:
            validate_score_input(data)
        
        assert exc.value.trace_id is not None
        assert len(exc.value.trace_id) > 0
    
    def test_error_to_log_format(self):
        """Errors should produce proper log format."""
        data = make_valid_input()
        data["scores"]["risk"] = 2.0  # Out of range
        
        with pytest.raises(OutOfRangeError) as exc:
            validate_score_input(data)
        
        log_str = exc.value.to_log_format()
        assert "[VALIDATION_ERROR]" in log_str
        assert "code=" in log_str
        assert "component=" in log_str


# =====================================================
# RUN IF MAIN
# =====================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

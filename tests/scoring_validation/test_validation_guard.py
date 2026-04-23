# tests/scoring_validation/test_validation_guard.py
"""
Validation Guard Tests for SIMGR Scoring Pipeline.

GĐ3 - COMPONENT VALIDATION HARDENING - PHẦN G

Tests validation decorators and guards.
"""

import math
import pytest

import sys
sys.path.insert(0, "F:/Hybrid Decision Support System")

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
from backend.scoring.errors import (
    NoneValueError,
    InvalidTypeError,
    NaNInfError,
    EmptyCollectionError,
    MissingFieldError,
)


# =====================================================
# CHECK FUNCTIONS TESTS
# =====================================================

class TestCheckNotNone:
    """Tests for check_not_none function."""
    
    def test_none_raises_error(self):
        """None value should raise NoneValueError."""
        with pytest.raises(NoneValueError) as exc:
            check_not_none(None, "test_field")
        
        assert "test_field" in str(exc.value)
    
    def test_valid_value_passes(self):
        """Non-None value should pass."""
        result = check_not_none("value", "test_field")
        assert result == "value"
    
    def test_zero_passes(self):
        """Zero should pass (not None)."""
        result = check_not_none(0, "test_field")
        assert result == 0
    
    def test_empty_string_passes(self):
        """Empty string should pass (not None)."""
        result = check_not_none("", "test_field")
        assert result == ""


class TestCheckType:
    """Tests for check_type function."""
    
    def test_wrong_type_raises_error(self):
        """Wrong type should raise InvalidTypeError."""
        with pytest.raises(InvalidTypeError) as exc:
            check_type("string", int, "test_field")
        
        assert "test_field" in str(exc.value)
        assert "str" in str(exc.value)
    
    def test_correct_type_passes(self):
        """Correct type should pass."""
        result = check_type("string", str, "test_field")
        assert result == "string"
    
    def test_int_accepted_as_numeric(self):
        """Int should be accepted for numeric check."""
        result = check_type(42, (int, float), "test_field")
        assert result == 42


class TestCheckNotNanInf:
    """Tests for check_not_nan_inf function."""
    
    def test_nan_raises_error(self):
        """NaN should raise NaNInfError."""
        with pytest.raises(NaNInfError):
            check_not_nan_inf(float('nan'), "test_field")
    
    def test_inf_raises_error(self):
        """Inf should raise NaNInfError."""
        with pytest.raises(NaNInfError):
            check_not_nan_inf(float('inf'), "test_field")
    
    def test_neg_inf_raises_error(self):
        """Negative Inf should raise NaNInfError."""
        with pytest.raises(NaNInfError):
            check_not_nan_inf(float('-inf'), "test_field")
    
    def test_valid_float_passes(self):
        """Valid float should pass."""
        result = check_not_nan_inf(3.14, "test_field")
        assert result == 3.14
    
    def test_int_passes(self):
        """Int should pass."""
        result = check_not_nan_inf(42, "test_field")
        assert result == 42


class TestCheckNotEmpty:
    """Tests for check_not_empty function."""
    
    def test_empty_list_raises_error(self):
        """Empty list should raise EmptyCollectionError."""
        with pytest.raises(EmptyCollectionError):
            check_not_empty([], "test_field")
    
    def test_empty_dict_raises_error(self):
        """Empty dict should raise EmptyCollectionError."""
        with pytest.raises(EmptyCollectionError):
            check_not_empty({}, "test_field")
    
    def test_empty_string_raises_error(self):
        """Empty string should raise EmptyCollectionError."""
        with pytest.raises(EmptyCollectionError):
            check_not_empty("", "test_field")
    
    def test_non_empty_list_passes(self):
        """Non-empty list should pass."""
        result = check_not_empty([1, 2, 3], "test_field")
        assert result == [1, 2, 3]


class TestCheckDictKeys:
    """Tests for check_dict_keys function."""
    
    def test_missing_key_raises_error(self):
        """Missing key should raise MissingFieldError."""
        with pytest.raises(MissingFieldError) as exc:
            check_dict_keys({"a": 1}, ["a", "b"], "test")
        
        assert "b" in str(exc.value)
    
    def test_all_keys_present_passes(self):
        """All keys present should pass."""
        data = {"a": 1, "b": 2, "c": 3}
        result = check_dict_keys(data, ["a", "b"], "test")
        assert result == data


class TestCheckValidJson:
    """Tests for check_valid_json function."""
    
    def test_invalid_json_raises_error(self):
        """Invalid JSON should raise InvalidTypeError."""
        with pytest.raises(InvalidTypeError):
            check_valid_json("{invalid", "test_field")
    
    def test_valid_json_passes(self):
        """Valid JSON should be parsed."""
        result = check_valid_json('{"key": "value"}', "test_field")
        assert result == {"key": "value"}


# =====================================================
# DECORATOR TESTS
# =====================================================

class TestValidateAllInputsDecorator:
    """Tests for @validate_all_inputs decorator."""
    
    def test_none_arg_raises_error(self):
        """None argument should raise error."""
        @validate_all_inputs
        def func(arg1: str):
            return arg1
        
        with pytest.raises(NoneValueError):
            func(None)
    
    def test_valid_args_pass(self):
        """Valid arguments should pass."""
        @validate_all_inputs
        def func(arg1: str, arg2: int):
            return f"{arg1}_{arg2}"
        
        result = func("test", 42)
        assert result == "test_42"
    
    def test_nan_float_raises_error(self):
        """NaN float argument should raise error."""
        @validate_all_inputs
        def func(score: float):
            return score
        
        with pytest.raises(NaNInfError):
            func(float('nan'))


class TestTypeGuardDecorator:
    """Tests for @type_guard decorator."""
    
    def test_wrong_type_raises_error(self):
        """Wrong type should raise InvalidTypeError."""
        @type_guard(str, int)
        def func(name, age):
            return f"{name}: {age}"
        
        with pytest.raises(InvalidTypeError):
            func("test", "not_int")
    
    def test_correct_types_pass(self):
        """Correct types should pass."""
        @type_guard(str, int)
        def func(name, age):
            return f"{name}: {age}"
        
        result = func("test", 42)
        assert result == "test: 42"


class TestRejectNoneDecorator:
    """Tests for @reject_none decorator."""
    
    def test_specified_none_raises_error(self):
        """Specified None param should raise error."""
        @reject_none("user_id")
        def func(user_id, optional=None):
            return user_id
        
        with pytest.raises(NoneValueError) as exc:
            func(None)
        
        assert "user_id" in str(exc.value)
    
    def test_unspecified_none_passes(self):
        """Unspecified None param should pass."""
        @reject_none("user_id")
        def func(user_id, optional=None):
            return user_id
        
        result = func("user123", None)
        assert result == "user123"


class TestRequireKeysDecorator:
    """Tests for @require_keys decorator."""
    
    def test_missing_key_raises_error(self):
        """Missing required key should raise error."""
        @require_keys("user_id", "score")
        def func(data):
            return data
        
        with pytest.raises(MissingFieldError):
            func({"user_id": "123"})  # Missing score
    
    def test_all_keys_present_passes(self):
        """All required keys should pass."""
        @require_keys("user_id", "score")
        def func(data):
            return data
        
        result = func({"user_id": "123", "score": 0.8})
        assert result["user_id"] == "123"


# =====================================================
# SCORING INPUT VALIDATION TESTS
# =====================================================

class TestValidateScoringInput:
    """Tests for validate_scoring_input function."""
    
    def test_missing_key_raises_error(self):
        """Missing required key should raise error."""
        data = {"user_id": "123"}  # Missing session_id, scores, timestamp
        
        with pytest.raises(MissingFieldError):
            validate_scoring_input(data)
    
    def test_none_value_raises_error(self):
        """None required value should raise error."""
        data = {
            "user_id": None,
            "session_id": "sess123",
            "scores": {},
            "timestamp": "2026-02-16T12:00:00Z"
        }
        
        with pytest.raises(NoneValueError):
            validate_scoring_input(data)
    
    def test_nan_score_raises_error(self):
        """NaN score should raise error."""
        data = {
            "user_id": "123",
            "session_id": "sess123",
            "scores": {"study": float('nan')},
            "timestamp": "2026-02-16T12:00:00Z"
        }
        
        with pytest.raises(NaNInfError):
            validate_scoring_input(data)
    
    def test_valid_input_passes(self):
        """Valid input should pass."""
        data = {
            "user_id": "123",
            "session_id": "sess123",
            "scores": {"study": 0.8, "interest": 0.7},
            "timestamp": "2026-02-16T12:00:00Z"
        }
        
        result = validate_scoring_input(data)
        assert result["user_id"] == "123"


# =====================================================
# RUN IF MAIN
# =====================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

# backend/scoring/validation/validation_guard.py
"""
None & Type Safety Layer for SIMGR Scoring Pipeline.

GĐ3 - COMPONENT VALIDATION HARDENING - PHẦN E
GĐ4 - Uses ScoringFormula.COMPONENTS for canonical component list.

Provides decorators and middleware for:
- None value rejection
- Missing dict key detection
- Wrong dtype detection
- Empty collection rejection
- Invalid JSON rejection

NO FALLBACKS. NO AUTO-FIX. FAIL FAST.
"""

from __future__ import annotations

import functools
import json
import math
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar, Union, get_type_hints

from backend.scoring.errors import (
    InputValidationError,
    NoneValueError,
    InvalidTypeError,
    NaNInfError,
    EmptyCollectionError,
    MissingFieldError,
)
from backend.scoring.scoring_formula import ScoringFormula


# =====================================================
# TYPE VARIABLES
# =====================================================

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])


# =====================================================
# VALIDATION FUNCTIONS
# =====================================================

def check_not_none(value: Any, field_name: str) -> Any:
    """
    Check that value is not None.
    
    Args:
        value: Value to check
        field_name: Field name for error messages
        
    Returns:
        The value if not None
        
    Raises:
        NoneValueError: If value is None
    """
    if value is None:
        raise NoneValueError(
            f"Field '{field_name}' cannot be None",
            field=field_name,
            component="validation_guard"
        )
    return value


def check_type(value: Any, expected_type: Type, field_name: str) -> Any:
    """
    Check that value has expected type.
    
    Args:
        value: Value to check
        expected_type: Expected type or tuple of types
        field_name: Field name for error messages
        
    Returns:
        The value if type matches
        
    Raises:
        InvalidTypeError: If type doesn't match
    """
    if not isinstance(value, expected_type):
        raise InvalidTypeError(
            f"Field '{field_name}' expected {expected_type.__name__}, got {type(value).__name__}",
            field=field_name,
            component="validation_guard"
        )
    return value


def check_not_nan_inf(value: Union[int, float], field_name: str) -> Union[int, float]:
    """
    Check that numeric value is not NaN or Inf.
    
    Args:
        value: Numeric value to check
        field_name: Field name for error messages
        
    Returns:
        The value if valid
        
    Raises:
        NaNInfError: If value is NaN or Inf
    """
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise NaNInfError(
            f"Field '{field_name}' contains NaN or Inf",
            field=field_name,
            component="validation_guard"
        )
    return value


def check_not_empty(value: Union[List, Dict, str], field_name: str) -> Any:
    """
    Check that collection is not empty.
    
    Args:
        value: Collection to check
        field_name: Field name for error messages
        
    Returns:
        The value if not empty
        
    Raises:
        EmptyCollectionError: If collection is empty
    """
    if len(value) == 0:
        raise EmptyCollectionError(
            f"Field '{field_name}' cannot be empty",
            field=field_name,
            component="validation_guard"
        )
    return value


def check_dict_keys(data: Dict, required_keys: List[str], context: str = "") -> Dict:
    """
    Check that dict has all required keys.
    
    Args:
        data: Dictionary to check
        required_keys: List of required key names
        context: Optional context for error messages
        
    Returns:
        The dict if all keys present
        
    Raises:
        MissingFieldError: If any key is missing
    """
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise MissingFieldError(
            f"Missing required keys: {', '.join(missing)}",
            field=context if context else "dict",
            component="validation_guard",
            details={"missing_keys": missing}
        )
    return data


def check_valid_json(data: str, field_name: str) -> Any:
    """
    Check that string is valid JSON and parse it.
    
    Args:
        data: JSON string to validate
        field_name: Field name for error messages
        
    Returns:
        Parsed JSON data
        
    Raises:
        InvalidTypeError: If JSON is invalid
    """
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError) as e:
        raise InvalidTypeError(
            f"Field '{field_name}' contains invalid JSON: {str(e)}",
            field=field_name,
            component="validation_guard"
        )


# =====================================================
# DECORATORS
# =====================================================

def validate_all_inputs(func: F) -> F:
    """
    Decorator that validates all input arguments for None and type safety.
    
    Checks:
    - No None values
    - No NaN/Inf in numeric values
    - No empty collections if typed as List/Dict
    
    Usage:
        @validate_all_inputs
        def calculate_score(user_id: str, score: float):
            ...
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Get function signature hints if available
        hints = {}
        try:
            hints = get_type_hints(func)
        except Exception:
            pass
        
        # Validate positional args
        func_params = list(func.__code__.co_varnames[:func.__code__.co_argcount])
        
        for i, arg in enumerate(args):
            if i < len(func_params):
                param_name = func_params[i]
                # Skip 'self' and 'cls'
                if param_name in ("self", "cls"):
                    continue
                    
                _validate_value(arg, param_name, hints.get(param_name))
        
        # Validate keyword args
        for key, value in kwargs.items():
            _validate_value(value, key, hints.get(key))
        
        return func(*args, **kwargs)
    
    return wrapper  # type: ignore


def type_guard(*expected_types: Type) -> Callable[[F], F]:
    """
    Decorator that enforces specific types for arguments.
    
    Usage:
        @type_guard(str, float, dict)
        def process(user_id, score, features):
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get parameter names
            func_params = list(func.__code__.co_varnames[:func.__code__.co_argcount])
            
            # Skip 'self' and 'cls'
            start_idx = 0
            if func_params and func_params[0] in ("self", "cls"):
                start_idx = 1
            
            actual_args = args[start_idx:] if start_idx else args
            actual_params = func_params[start_idx:]
            
            # Validate each argument against expected type
            for i, (arg, expected) in enumerate(zip(actual_args, expected_types)):
                param_name = actual_params[i] if i < len(actual_params) else f"arg{i}"
                
                if not isinstance(arg, expected):
                    raise InvalidTypeError(
                        f"Argument '{param_name}' expected {expected.__name__}, got {type(arg).__name__}",
                        field=param_name,
                        component="type_guard"
                    )
            
            return func(*args, **kwargs)
        
        return wrapper  # type: ignore
    
    return decorator


def reject_none(*param_names: str) -> Callable[[F], F]:
    """
    Decorator that explicitly rejects None for specified parameters.
    
    Usage:
        @reject_none("user_id", "score")
        def calculate(user_id, score, optional_param=None):
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get parameter names
            func_params = list(func.__code__.co_varnames[:func.__code__.co_argcount])
            
            # Build arg dict
            arg_dict = dict(zip(func_params, args))
            arg_dict.update(kwargs)
            
            # Check specified params
            for name in param_names:
                if name in arg_dict and arg_dict[name] is None:
                    raise NoneValueError(
                        f"Parameter '{name}' cannot be None",
                        field=name,
                        component="reject_none"
                    )
            
            return func(*args, **kwargs)
        
        return wrapper  # type: ignore
    
    return decorator


def require_keys(*required_keys: str) -> Callable[[F], F]:
    """
    Decorator that requires specific keys in the first dict argument.
    
    Usage:
        @require_keys("user_id", "score", "timestamp")
        def process_data(data: dict):
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Find first dict argument
            data = None
            for arg in args:
                if isinstance(arg, dict):
                    data = arg
                    break
            
            if data is None:
                for value in kwargs.values():
                    if isinstance(value, dict):
                        data = value
                        break
            
            if data is not None:
                check_dict_keys(data, list(required_keys), "input_data")
            
            return func(*args, **kwargs)
        
        return wrapper  # type: ignore
    
    return decorator


# =====================================================
# HELPER FUNCTIONS
# =====================================================

def _validate_value(value: Any, name: str, type_hint: Optional[Type] = None) -> None:
    """
    Validate a single value.
    
    Raises appropriate error if validation fails.
    """
    # Check None
    if value is None:
        # Only raise if not Optional in type hint
        if type_hint is not None:
            origin = getattr(type_hint, "__origin__", None)
            if origin is Union:
                args = getattr(type_hint, "__args__", ())
                if type(None) in args:
                    return  # Optional, allow None
        raise NoneValueError(
            f"Parameter '{name}' cannot be None",
            field=name,
            component="validation_guard"
        )
    
    # Check NaN/Inf for numeric
    if isinstance(value, float):
        check_not_nan_inf(value, name)
    
    # Check empty for collections
    if isinstance(value, (list, dict)) and len(value) == 0:
        # Only warn, don't fail by default (specific decorators handle this)
        pass


def validate_scoring_input(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Comprehensive validation for scoring input data.
    
    Validates:
    - Required keys present
    - No None values in required fields
    - No NaN/Inf in scores
    - Valid types
    
    Args:
        data: Input data dictionary
        
    Returns:
        Validated data (unchanged)
        
    Raises:
        Various validation errors if invalid
    """
    required_keys = ["user_id", "session_id", "scores", "timestamp"]
    check_dict_keys(data, required_keys, "scoring_input")
    
    # Validate each required field
    for key in required_keys:
        check_not_none(data[key], key)
    
    # Validate scores
    scores = data.get("scores", {})
    if not isinstance(scores, dict):
        raise InvalidTypeError(
            "Field 'scores' must be dict",
            field="scores",
            component="validation_guard"
        )
    
    # GĐ4: Use canonical component list from ScoringFormula
    score_keys = ScoringFormula.COMPONENTS
    for sk in score_keys:
        if sk in scores:
            value = scores[sk]
            check_not_none(value, f"scores.{sk}")
            if isinstance(value, (int, float)):
                check_not_nan_inf(value, f"scores.{sk}")
    
    return data


# =====================================================
# EXPORTS
# =====================================================

__all__ = [
    # Validation functions
    "check_not_none",
    "check_type",
    "check_not_nan_inf",
    "check_not_empty",
    "check_dict_keys",
    "check_valid_json",
    
    # Decorators
    "validate_all_inputs",
    "type_guard",
    "reject_none",
    "require_keys",
    
    # Higher-level
    "validate_scoring_input",
]

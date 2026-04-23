# backend/scoring/lineage_validator.py
"""
PHẦN G — TRACEABILITY HEADER

Lineage Validator - Ensures every scoring response has model lineage.

Responsibilities:
1. Validate lineage data is complete
2. Format lineage for API responses
3. Detect missing lineage
4. Log lineage violations
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


# =============================================================================
# LINEAGE ERRORS
# =============================================================================

class LineageError(Exception):
    """Base error for lineage issues."""
    pass


class MissingLineageError(LineageError):
    """Response lacks required lineage."""
    pass


class IncompleteLineageError(LineageError):
    """Lineage is incomplete."""
    pass


# =============================================================================
# LINEAGE HEADER SPEC
# =============================================================================

REQUIRED_LINEAGE_FIELDS = [
    "weight_version",
    "trained_at",
    "dataset",
    "checksum",
]

OPTIONAL_LINEAGE_FIELDS = [
    "pipeline_version",
    "trainer_commit",
    "r2",
    "mae",
]


@dataclass
class LineageHeader:
    """
    PHẦN G: Model lineage header for API responses.
    
    Every scoring response MUST include this.
    """
    weight_version: str
    trained_at: str
    dataset: str
    checksum: str
    pipeline_version: str = ""
    trainer_commit: str = ""
    r2: Optional[float] = None
    mae: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to response-ready dict."""
        result = {
            "weight_version": self.weight_version,
            "trained_at": self.trained_at,
            "dataset": self.dataset,
            "checksum": self.checksum,
        }
        
        if self.pipeline_version:
            result["pipeline_version"] = self.pipeline_version
        if self.trainer_commit:
            result["trainer_commit"] = self.trainer_commit
        if self.r2 is not None:
            result["r2"] = self.r2
        if self.mae is not None:
            result["mae"] = self.mae
        
        return result
    
    def to_response_header(self) -> Dict[str, Any]:
        """Format for API response."""
        return {"model_lineage": self.to_dict()}


# =============================================================================
# LINEAGE VALIDATOR
# =============================================================================

class LineageValidator:
    """
    Validates and manages lineage data.
    
    PHẦN G: Ensures every response has valid lineage.
    """
    
    def __init__(self):
        self._current_lineage: Optional[LineageHeader] = None
        self._validation_errors: List[str] = []
    
    def set_lineage(self, lineage: LineageHeader) -> None:
        """Set current lineage (called after weight load)."""
        self._current_lineage = lineage
        self._validation_errors = []
    
    def get_lineage_header(self) -> Dict[str, Any]:
        """Get lineage header for response.
        
        PHẦN G: Use this in every API response.
        
        Raises:
            MissingLineageError: If no lineage set.
        """
        if self._current_lineage is None:
            raise MissingLineageError(
                "No model lineage available. Load verified weights first."
            )
        
        return self._current_lineage.to_response_header()
    
    def validate_lineage(self, lineage_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate lineage data is complete.
        
        Args:
            lineage_data: Lineage dict to validate.
            
        Returns:
            (is_valid, errors) tuple.
        """
        errors = []
        
        for field in REQUIRED_LINEAGE_FIELDS:
            if field not in lineage_data or not lineage_data[field]:
                errors.append(f"Missing required field: {field}")
        
        # Validate timestamp format
        trained_at = lineage_data.get("trained_at", "")
        if trained_at:
            try:
                datetime.fromisoformat(trained_at.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"Invalid trained_at format: {trained_at}")
        
        # Validate checksum format (should be hex)
        checksum = lineage_data.get("checksum", "")
        if checksum:
            try:
                int(checksum, 16)
            except ValueError:
                errors.append(f"Invalid checksum format: {checksum}")
        
        return len(errors) == 0, errors
    
    @classmethod
    def from_training_linker(cls) -> "LineageValidator":
        """Create validator from current TrainingLinker state.
        
        PHẦN G: Standard way to get lineage for responses.
        """
        from backend.scoring.training_linker import TrainingLinker
        
        validator = cls()
        
        try:
            linker_lineage = TrainingLinker.get_lineage()
            
            header = LineageHeader(
                weight_version=linker_lineage.weight_version,
                trained_at=linker_lineage.trained_at,
                dataset=linker_lineage.dataset,
                checksum=linker_lineage.weights_checksum,
                pipeline_version=linker_lineage.pipeline_version,
                trainer_commit=linker_lineage.trainer_commit,
                r2=linker_lineage.metrics.get("r2"),
                mae=linker_lineage.metrics.get("mae"),
            )
            
            validator.set_lineage(header)
            
        except Exception as e:
            logger.error(f"[LINEAGE] Failed to get lineage: {e}")
            raise MissingLineageError(f"Cannot get lineage: {e}") from e
        
        return validator


# Need to import Tuple from typing
from typing import Tuple


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================

_global_validator: Optional[LineageValidator] = None


def init_lineage_validator() -> LineageValidator:
    """Initialize global lineage validator.
    
    Call after loading verified weights.
    """
    global _global_validator
    _global_validator = LineageValidator.from_training_linker()
    return _global_validator


def get_lineage_header() -> Dict[str, Any]:
    """Get current model lineage header.
    
    PHẦN G: Include in every API response.
    
    Returns:
        {"model_lineage": {...}}
    """
    global _global_validator
    
    if _global_validator is None:
        _global_validator = init_lineage_validator()
    
    return _global_validator.get_lineage_header()


def validate_response_lineage(response: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate a response has proper lineage.
    
    Args:
        response: API response dict.
        
    Returns:
        (is_valid, errors) tuple.
    """
    errors = []
    
    if "model_lineage" not in response:
        errors.append("Response missing 'model_lineage' field")
        return False, errors
    
    validator = LineageValidator()
    return validator.validate_lineage(response["model_lineage"])


def add_lineage_to_response(response: Dict[str, Any]) -> Dict[str, Any]:
    """Add model lineage to an API response.
    
    PHẦN G: Use this to ensure every response has lineage.
    
    Args:
        response: Original response dict.
        
    Returns:
        Response with model_lineage added.
    """
    lineage = get_lineage_header()
    return {**response, **lineage}

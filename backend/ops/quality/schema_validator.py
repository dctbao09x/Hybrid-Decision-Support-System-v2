# backend/ops/quality/schema_validator.py
"""
Pipeline-level Schema Validation.

Validates data schemas at every pipeline boundary:
  crawl output → validate input
  validate output → score input
  score output → explain input

Catches schema drift between pipeline stages.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError

logger = logging.getLogger("ops.quality.schema")


class SchemaValidationResult:
    """Result of schema validation."""

    def __init__(self):
        self.valid_count = 0
        self.invalid_count = 0
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[str] = []
        self.timestamp = datetime.now().isoformat()

    @property
    def pass_rate(self) -> float:
        total = self.valid_count + self.invalid_count
        return self.valid_count / total if total > 0 else 0.0

    @property
    def passed(self) -> bool:
        return self.invalid_count == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid_count,
            "invalid": self.invalid_count,
            "pass_rate": round(self.pass_rate, 4),
            "passed": self.passed,
            "errors": self.errors[:50],  # Limit to 50
            "warnings": self.warnings,
            "timestamp": self.timestamp,
        }


class PipelineSchemaValidator:
    """
    Validates data contracts at pipeline stage boundaries.

    Registered schemas:
    - crawl_output: Raw crawled data
    - validate_output: Validated records
    - score_input: Data entering scoring
    - score_output: Scored careers
    - explain_output: Explanation traces
    """

    def __init__(self):
        self._schemas: Dict[str, Type[BaseModel]] = {}
        self._custom_rules: Dict[str, List] = {}

    def register_schema(
        self,
        stage_name: str,
        schema: Type[BaseModel],
    ) -> None:
        """Register a Pydantic schema for a pipeline stage."""
        self._schemas[stage_name] = schema
        logger.info(f"Schema registered: {stage_name} → {schema.__name__}")

    def add_custom_rule(
        self,
        stage_name: str,
        rule_name: str,
        check_fn,
        error_msg: str,
    ) -> None:
        """Add a custom validation rule for a stage."""
        if stage_name not in self._custom_rules:
            self._custom_rules[stage_name] = []
        self._custom_rules[stage_name].append({
            "name": rule_name,
            "check": check_fn,
            "error_msg": error_msg,
        })

    def validate_batch(
        self,
        stage_name: str,
        records: List[Dict[str, Any]],
        strict: bool = False,
    ) -> SchemaValidationResult:
        """
        Validate a batch of records against the registered schema.

        Args:
            stage_name: Pipeline stage name
            records: List of data records
            strict: If True, extra fields cause errors
        """
        result = SchemaValidationResult()
        schema = self._schemas.get(stage_name)

        if not schema:
            result.warnings.append(f"No schema registered for '{stage_name}'")
            result.valid_count = len(records)
            return result

        for i, record in enumerate(records):
            try:
                schema.model_validate(record, strict=strict)
                result.valid_count += 1
            except ValidationError as e:
                result.invalid_count += 1
                result.errors.append({
                    "record_index": i,
                    "record_id": record.get("job_id", record.get("id", f"idx_{i}")),
                    "errors": [
                        {
                            "field": ".".join(str(x) for x in err["loc"]),
                            "message": err["msg"],
                            "type": err["type"],
                        }
                        for err in e.errors()
                    ],
                })

        # Run custom rules
        for rule in self._custom_rules.get(stage_name, []):
            for i, record in enumerate(records):
                try:
                    if not rule["check"](record):
                        result.warnings.append(
                            f"Rule '{rule['name']}' failed for record {i}: {rule['error_msg']}"
                        )
                except Exception:
                    pass

        logger.info(
            f"Schema validation [{stage_name}]: "
            f"{result.valid_count}/{result.valid_count + result.invalid_count} passed "
            f"({result.pass_rate:.1%})"
        )
        return result

    def validate_stage_transition(
        self,
        from_stage: str,
        to_stage: str,
        records: List[Dict[str, Any]],
    ) -> Dict[str, SchemaValidationResult]:
        """Validate records against both source and target schemas."""
        return {
            from_stage: self.validate_batch(from_stage, records),
            to_stage: self.validate_batch(to_stage, records),
        }

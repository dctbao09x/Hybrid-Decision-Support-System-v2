import json
import re
from enum import Enum
from typing import List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

VERSION_PATTERN = re.compile(r"^v1\.\d+\.\d+$")

class CareerFieldEnum(str, Enum):
    IT = "INFORMATION_TECHNOLOGY"
    BUSINESS = "BUSINESS_ADMINISTRATION"
    MEDICAL = "HEALTHCARE_MEDICINE"
    ART = "ART_DESIGN"
    UNKNOWN = "UNKNOWN"

class SkillLevelEnum(str, Enum):
    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"

class ExtractedSkill(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    skill_name: str = Field(min_length=1, max_length=60)
    category: Optional[str] = Field(default=None, max_length=30)
    level: Optional[SkillLevelEnum] = None
    confidence_score: float = Field(ge=0.0, le=1.0)

class UserTraits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    extraversion_level: int = Field(ge=1, le=10)
    stress_tolerance: int = Field(ge=1, le=10)

class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: str = Field(min_length=1, max_length=20)
    inferred_interests: List[CareerFieldEnum] = Field(default_factory=list)
    skills: List[ExtractedSkill] = Field(default_factory=list)
    traits: UserTraits
    has_financial_constraints: Optional[bool] = False
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    missing_info_flags: List[str] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        if not VERSION_PATTERN.match(v):
            raise ValueError("unsupported_schema_version")
        return v

    @field_validator("missing_info_flags")
    @classmethod
    def validate_flags(cls, v: List[str]) -> List[str]:
        for item in v:
            if not isinstance(item, str) or len(item) > 80:
                raise ValueError("invalid_flag")
        return v


def parse_extraction_output(raw: str) -> Tuple[Optional[ExtractionOutput], str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, "invalid_json"

    try:
        model = ExtractionOutput.model_validate(data)
    except ValidationError as exc:
        return None, "schema_error:" + str(exc.errors()[0].get("type", "validation_error"))

    return model, ""

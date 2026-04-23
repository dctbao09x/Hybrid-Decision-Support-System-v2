from enum import Enum
from typing import Any, Annotated, List, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
MAX_LIST_ITEMS = 50


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


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


class EducationLevelEnum(str, Enum):
    MIDDLE_SCHOOL = "MIDDLE_SCHOOL"
    HIGH_SCHOOL = "HIGH_SCHOOL"
    COLLEGE = "COLLEGE"
    UNIVERSITY = "UNIVERSITY"
    MASTER = "MASTER"
    DOCTORATE = "DOCTORATE"
    OTHER = "OTHER"


class ExtractedSkill(StrictBaseModel):
    skill_name: ShortText = Field(description="Skill name extracted from user input.")
    category: Optional[ShortText] = Field(None, description="Soft skill or hard skill.")
    level: Optional[SkillLevelEnum] = Field(None, description="Estimated proficiency.")
    confidence_score: float = Field(0.0, ge=0.0, le=1.0, description="Confidence from 0 to 1.")

    @field_validator("confidence_score", mode="before")
    @classmethod
    def coerce_confidence(cls, v: Any) -> float:
        if v is None:
            return 0.0
        if isinstance(v, str):
            try:
                v = float(v)
            except ValueError:
                return 0.0
        return max(0.0, min(float(v), 1.0))


class UserTraits(StrictBaseModel):
    extraversion_level: int = Field(default=5, ge=1, le=10, description="Extraversion level (1-10).")
    stress_tolerance: int = Field(default=5, ge=1, le=10, description="Stress tolerance (1-10).")

    @field_validator("extraversion_level", "stress_tolerance", mode="before")
    @classmethod
    def coerce_int(cls, v: Any) -> int:
        if v is None:
            return 5
        if isinstance(v, str) and v.isdigit():
            return int(v)
        return int(v)


class UserProfile(StrictBaseModel):
    age: Optional[int] = Field(default=None, ge=12, le=80)
    education_level: Optional[EducationLevelEnum] = None
    location: Optional[ShortText] = None
    school: Optional[ShortText] = None
    major: Optional[ShortText] = None
    years_experience: Optional[float] = Field(default=None, ge=0.0, le=60.0)
    extraversion_level: Optional[int] = Field(default=None, ge=1, le=10)
    stress_tolerance: Optional[int] = Field(default=None, ge=1, le=10)
    financial_constraints: Optional[bool] = None
    notes: Optional[LongText] = None

    @field_validator("age", "years_experience", mode="before")
    @classmethod
    def coerce_numeric(cls, v: Any) -> Optional[float]:
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return None
        return v


class InterestItem(StrictBaseModel):
    label: CareerFieldEnum = CareerFieldEnum.UNKNOWN
    confidence: float = Field(0.0, ge=0.0, le=1.0)

    @field_validator("label", mode="before")
    @classmethod
    def coerce_interest(cls, v: Any) -> CareerFieldEnum:
        if isinstance(v, CareerFieldEnum):
            return v
        if isinstance(v, str):
            try:
                return CareerFieldEnum(v)
            except ValueError:
                return CareerFieldEnum.UNKNOWN
        return CareerFieldEnum.UNKNOWN

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_interest_confidence(cls, v: Any) -> float:
        if v is None:
            return 0.0
        if isinstance(v, str):
            try:
                v = float(v)
            except ValueError:
                return 0.0
        return max(0.0, min(float(v), 1.0))


class StrengthItem(StrictBaseModel):
    title: ShortText
    evidence: Optional[LongText] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_strength_confidence(cls, v: Any) -> float:
        if v is None:
            return 0.0
        if isinstance(v, str):
            try:
                v = float(v)
            except ValueError:
                return 0.0
        return max(0.0, min(float(v), 1.0))


class WeaknessItem(StrictBaseModel):
    title: ShortText
    evidence: Optional[LongText] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_weakness_confidence(cls, v: Any) -> float:
        if v is None:
            return 0.0
        if isinstance(v, str):
            try:
                v = float(v)
            except ValueError:
                return 0.0
        return max(0.0, min(float(v), 1.0))


class CareerMatch(StrictBaseModel):
    career_code: ShortText
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reasons: List[ShortText] = Field(default_factory=list)
    score: Optional[float] = Field(default=None, ge=0.0, le=100.0)

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_match_confidence(cls, v: Any) -> float:
        if v is None:
            return 0.0
        if isinstance(v, str):
            try:
                v = float(v)
            except ValueError:
                return 0.0
        return max(0.0, min(float(v), 1.0))


class ScoreComponent(StrictBaseModel):
    name: ShortText
    value: float = Field(..., ge=0.0, le=100.0)
    weight: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class ScoreBreakdown(StrictBaseModel):
    final_score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    components: List[ScoreComponent] = Field(default_factory=list)

    @field_validator("components", mode="before")
    @classmethod
    def cap_components(cls, v: Any):
        if v is None:
            return []
        if not isinstance(v, list):
            return [v]
        return v[:MAX_LIST_ITEMS]


class ExplanationMetadata(StrictBaseModel):
    prompt_version: Optional[ShortText] = None
    model: Optional[ShortText] = None
    token_count: Optional[int] = Field(default=None, ge=0)
    latency_ms: Optional[int] = Field(default=None, ge=0)
    generated_at: Optional[ShortText] = None


class ConfidenceRiskFlags(StrictBaseModel):
    extraction_confidence: float = Field(0.0, ge=0.0, le=1.0)
    hallucination_risk: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    pii_detected: Optional[bool] = None
    injection_detected: Optional[bool] = None
    warnings: List[ShortText] = Field(default_factory=list)

    @field_validator("extraction_confidence", mode="before")
    @classmethod
    def coerce_extraction_confidence(cls, v: Any) -> float:
        if v is None:
            return 0.0
        if isinstance(v, str):
            try:
                v = float(v)
            except ValueError:
                return 0.0
        return max(0.0, min(float(v), 1.0))

    @field_validator("warnings", mode="before")
    @classmethod
    def cap_warnings(cls, v: Any):
        if v is None:
            return []
        if not isinstance(v, list):
            return [v]
        return v[:MAX_LIST_ITEMS]


class LLMExtractionEnvelopeV1(StrictBaseModel):
    schema_version: Literal["v1.0.0"] = "v1.0.0"
    user_profile: UserProfile = Field(default_factory=UserProfile)
    interests: List[InterestItem] = Field(default_factory=list)
    strengths: List[StrengthItem] = Field(default_factory=list)
    weaknesses: List[WeaknessItem] = Field(default_factory=list)
    career_matches: List[CareerMatch] = Field(default_factory=list)
    score_breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    explanation_metadata: ExplanationMetadata = Field(default_factory=ExplanationMetadata)
    risk_flags: ConfidenceRiskFlags = Field(default_factory=ConfidenceRiskFlags)

    @field_validator("interests", "strengths", "weaknesses", "career_matches", mode="before")
    @classmethod
    def cap_list_sizes(cls, v: Any):
        if v is None:
            return []
        if not isinstance(v, list):
            return [v]
        return v[:MAX_LIST_ITEMS]


class CareerFeatureExtractionV1(StrictBaseModel):
    schema_version: Literal["v1.0.0"] = "v1.0.0"
    inferred_interests: List[CareerFieldEnum] = Field(default_factory=list, description="Các nhóm ngành user có vẻ hứng thú.")
    skills: List[ExtractedSkill] = Field(default_factory=list, description="Danh sách kỹ năng user tự nhận hoặc ngụ ý.")
    traits: UserTraits = Field(default_factory=UserTraits, description="Thông tin tính cách, tâm lý.")
    has_financial_constraints: bool = Field(default=False, description="True nếu user đề cập đến khó khăn tài chính hoặc nhắc đến học phí rẻ.")
    extraction_confidence: float = Field(..., ge=0.0, le=1.0, description="Độ tự tin tổng thể của toàn bộ phiên trích xuất.")
    missing_info_flags: List[ShortText] = Field(default_factory=list, description="Liệt kê những thông tin quan trọng mà user bị thiếu cần hỏi thêm.")

    @field_validator("skills")
    @classmethod
    def check_min_confidence(cls, v: Any):
        if not isinstance(v, list):
            return []
        return [skill for skill in v if skill.confidence_score > 0.4]

    @field_validator("inferred_interests", mode="before")
    @classmethod
    def coerce_interests(cls, v: Any):
        if v is None:
            return []
        if not isinstance(v, list):
            v = [v]
        normalized = []
        for item in v:
            if isinstance(item, CareerFieldEnum):
                normalized.append(item)
            elif isinstance(item, str):
                try:
                    normalized.append(CareerFieldEnum(item))
                except ValueError:
                    normalized.append(CareerFieldEnum.UNKNOWN)
            else:
                normalized.append(CareerFieldEnum.UNKNOWN)
        return normalized

    @field_validator("missing_info_flags", mode="before")
    @classmethod
    def cap_missing_info(cls, v: Any):
        if v is None:
            return []
        if not isinstance(v, list):
            return [v]
        return v[:MAX_LIST_ITEMS]

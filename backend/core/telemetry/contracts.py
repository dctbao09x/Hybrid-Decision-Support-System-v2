from typing import Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class TelemetryBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class TokenUsage(TelemetryBaseModel):
    prompt_tokens: int = Field(0, ge=0)
    completion_tokens: int = Field(0, ge=0)
    total_tokens: int = Field(0, ge=0)


class PromptInfo(TelemetryBaseModel):
    prompt_id: Optional[str] = None
    prompt_version: Optional[str] = None
    prompt_hash: Optional[str] = None


class ModelInfo(TelemetryBaseModel):
    model_id: Optional[str] = None
    model_version: Optional[str] = None


class CostBreakdown(TelemetryBaseModel):
    token_cost_usd: float = Field(0.0, ge=0)
    redis_cost_usd: float = Field(0.0, ge=0)
    queue_cost_usd: float = Field(0.0, ge=0)
    storage_cost_usd: float = Field(0.0, ge=0)
    market_crawl_cost_usd: float = Field(0.0, ge=0)
    total_cost_usd: float = Field(0.0, ge=0)


class TelemetryError(TelemetryBaseModel):
    error_type: str
    error_code: Optional[str] = None
    message: Optional[str] = None


class TelemetryKpi(TelemetryBaseModel):
    name: str
    value: float
    segment: Optional[str] = None
    window: Optional[str] = None


class TelemetryLogEvent(TelemetryBaseModel):
    timestamp: str
    event_type: str
    severity: str
    component: str
    status: str
    endpoint: Optional[str] = None
    endpoint_version: Optional[str] = None
    tenant_id: Optional[str] = None
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None
    span_name: Optional[str] = None
    pipeline_stage: Optional[str] = None
    duration_ms: Optional[float] = None
    payload_bytes: Optional[int] = None
    payload_snippet: Optional[str] = None
    error: Optional[TelemetryError] = None
    error_code: Optional[str] = None
    prompt_version: Optional[str] = None
    model_version: Optional[str] = None
    prompt: Optional[PromptInfo] = None
    model: Optional[ModelInfo] = None
    schema_version: Optional[str] = None
    ruleset_version: Optional[str] = None
    scoring_version: Optional[str] = None
    dataset_version: Optional[str] = None
    token_usage: Optional[TokenUsage] = None
    cost_usd: Optional[float] = None
    cost_breakdown: Optional[CostBreakdown] = None
    explanation_status: Optional[str] = None
    unit_cost_per_decision_usd: Optional[float] = None
    unit_cost_per_successful_explanation_usd: Optional[float] = None
    confidence: Optional[float] = None
    drift_type: Optional[str] = None
    drift_score: Optional[float] = None
    rollback_id: Optional[str] = None
    rollback_action: Optional[str] = None
    rollback_trigger: Optional[str] = None
    baseline_version: Optional[str] = None
    kpi: Optional[TelemetryKpi] = None


class TelemetryPipelineEvent(TelemetryBaseModel):
    request_id: str
    trace_id: str
    correlation_id: str
    endpoint: Optional[str] = None
    endpoint_version: Optional[str] = None
    tenant_id: Optional[str] = None
    pipeline_stage: str
    status: str
    duration_ms: float
    error_code: Optional[str] = None
    explanation_status: Optional[str] = None
    confidence: Optional[float] = None
    model_version: Optional[str] = None
    prompt_version: Optional[str] = None
    schema_version: Optional[str] = None
    scoring_version: Optional[str] = None
    dataset_version: Optional[str] = None
    cost_usd: Optional[float] = None
    cost_breakdown: Optional[CostBreakdown] = None
    unit_cost_per_decision_usd: Optional[float] = None
    unit_cost_per_successful_explanation_usd: Optional[float] = None
    drift_type: Optional[str] = None
    drift_score: Optional[float] = None
    rollback_id: Optional[str] = None
    rollback_action: Optional[str] = None
    rollback_trigger: Optional[str] = None


class TelemetryMetricSample(TelemetryBaseModel):
    name: str
    value: float
    labels: Dict[str, str] = Field(default_factory=dict)
    timestamp: Optional[str] = None

import asyncio
import json
import logging
import os
import time
from functools import wraps
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any, Dict, Optional

from pydantic import ValidationError

from backend.core.telemetry.attributes import TelemetryAttributes
from backend.core.telemetry.context import get_prompt_context, set_prompt_context
from backend.core.telemetry.span_naming import SpanNames
from backend.llm.client import build_default_client
from backend.llm.providers import LLMProviderError
from backend.models.llm_schemas import (
    CareerFeatureExtractionV1,
    CareerFieldEnum,
    ExtractedSkill,
    LLMExtractionEnvelopeV1,
    UserTraits,
)


class _NoOpMetric:
    def inc(self, value: float = 1.0) -> None:
        _ = value

    def labels(self, **kwargs):
        _ = kwargs
        return self

    def observe(self, value: float) -> None:
        _ = value


try:
    from backend.core.telemetry.custom_metrics import (
        LLM_ERROR_COUNTER,
        LLM_EXTRACTION_TIME,
        TOTAL_COST_USD,
    )
except Exception:  # pragma: no cover
    LLM_ERROR_COUNTER = _NoOpMetric()  # type: ignore[assignment]
    LLM_EXTRACTION_TIME = _NoOpMetric()  # type: ignore[assignment]
    TOTAL_COST_USD = _NoOpMetric()  # type: ignore[assignment]


class _NoOpSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        _ = (key, value)


class _NoOpSpanContext:
    def __enter__(self) -> "_NoOpSpan":
        return _NoOpSpan()

    def __exit__(self, exc_type, exc, tb) -> bool:
        _ = (exc_type, exc, tb)
        return False

    def __call__(self, func):
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def _async_wrapper(*args, **kwargs):
                return await func(*args, **kwargs)

            return _async_wrapper

        @wraps(func)
        def _wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return _wrapper


class _NoOpTracer:
    def start_as_current_span(self, name: str) -> _NoOpSpanContext:
        _ = name
        return _NoOpSpanContext()


class _NoOpTraceModule:
    @staticmethod
    def get_current_span() -> _NoOpSpan:
        return _NoOpSpan()


try:
    from opentelemetry import trace  # type: ignore
    from backend.core.telemetry.otel_setup import tracer  # type: ignore
except Exception:  # pragma: no cover
    trace = _NoOpTraceModule()  # type: ignore[assignment]
    tracer = _NoOpTracer()  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


MAX_VALIDATION_RETRIES = max(_env_int("LLM_EXTRACTION_MAX_RETRIES", 2), 0)
MAX_RAW_CHARS = max(_env_int("LLM_EXTRACTION_MAX_RAW_CHARS", 20000), 1024)
MIN_EXTRACTION_CONFIDENCE = max(
    0.0,
    min(_env_float("LLM_EXTRACTION_MIN_CONFIDENCE", 0.55), 1.0),
)
MODEL_METRIC_LABEL = os.getenv("LLM_EXTRACTION_MODEL_LABEL", "provider_default")
LLM_FALLBACK_SPAN = getattr(SpanNames, "LLM_FALLBACK", SpanNames.LLM_EXTRACT)


@dataclass(frozen=True)
class LLMExtractionAttempt:
    feature: CareerFeatureExtractionV1
    success: bool
    used_fallback: bool
    schema_validation_failures: int
    attempts: int
    confidence: float
    fallback_reason: Optional[str] = None


INTEREST_TO_FEATURES: Dict[CareerFieldEnum, Dict[str, float]] = {
    CareerFieldEnum.IT: {"interest_tech": 1.0, "logic_score": 0.8},
    CareerFieldEnum.BUSINESS: {"interest_social": 0.9, "economics_score": 0.8},
    CareerFieldEnum.MEDICAL: {"interest_science": 1.0, "biology_score": 0.9},
    CareerFieldEnum.ART: {"interest_arts": 1.0, "creativity_score": 0.9},
}


def _build_extraction_prompt(anonymized_text: str) -> str:
    schema_shape = {
        "schema_version": "v1.0.0",
        "user_profile": {
            "extraversion_level": 5,
            "stress_tolerance": 5,
            "financial_constraints": False,
        },
        "interests": [{"label": "UNKNOWN", "confidence": 0.0}],
        "strengths": [{"title": "skill_name", "confidence": 0.0}],
        "weaknesses": [],
        "career_matches": [],
        "score_breakdown": {"final_score": 0.0, "components": []},
        "explanation_metadata": {"model": "string"},
        "risk_flags": {
            "extraction_confidence": 0.0,
            "warnings": ["missing_information"],
        },
    }
    return (
        "You are a strict extraction engine for career guidance.\n"
        "Return ONLY valid JSON. Do not add commentary or markdown.\n"
        "The output must follow this shape exactly:\n"
        f"{json.dumps(schema_shape, ensure_ascii=True)}\n\n"
        "User input:\n"
        f"{anonymized_text}\n"
    )


def _coerce_raw_output(provider_output: Any) -> str:
    if provider_output is None:
        raise ValueError("Empty LLM output")
    if isinstance(provider_output, str):
        return provider_output.strip()
    if isinstance(provider_output, (dict, list)):
        return json.dumps(provider_output, ensure_ascii=True)
    raise ValueError("Unsupported LLM output type")


async def _invoke_llm_raw_output(prompt: str) -> str:
    client = build_default_client()
    provider_output = await asyncio.to_thread(client.analyze, prompt)
    return _coerce_raw_output(provider_output)


def _parse_llm_output(raw_text: str) -> LLMExtractionEnvelopeV1:
    if not raw_text:
        raise ValueError("Empty LLM output")
    if len(raw_text) > MAX_RAW_CHARS:
        raise ValueError("LLM output too large")
    try:
        data = json.loads(raw_text)
    except JSONDecodeError as exc:
        raise ValueError("Malformed JSON from LLM") from exc
    return LLMExtractionEnvelopeV1.model_validate(data)


def _map_envelope_to_feature(envelope: LLMExtractionEnvelopeV1) -> CareerFeatureExtractionV1:
    inferred_interests = [item.label for item in envelope.interests]
    if not inferred_interests:
        inferred_interests = [CareerFieldEnum.UNKNOWN]

    skills = [
        ExtractedSkill(
            skill_name=item.title,
            confidence_score=item.confidence,
            category="Strength",
        )
        for item in envelope.strengths
    ]

    traits = UserTraits(
        extraversion_level=envelope.user_profile.extraversion_level or 5,
        stress_tolerance=envelope.user_profile.stress_tolerance or 5,
    )

    confidence = max(
        0.0,
        min(float(envelope.risk_flags.extraction_confidence or 0.0), 1.0),
    )

    return CareerFeatureExtractionV1(
        inferred_interests=inferred_interests,
        skills=skills,
        traits=traits,
        has_financial_constraints=bool(envelope.user_profile.financial_constraints),
        extraction_confidence=confidence,
        missing_info_flags=list(envelope.risk_flags.warnings or []),
    )


def _skill_keyword_to_feature(skill_name: str) -> Optional[str]:
    lowered = skill_name.lower()
    if any(token in lowered for token in ("math", "statistics", "algebra", "calculus", "quant")):
        return "math_score"
    if any(token in lowered for token in ("logic", "algorithm", "python", "coding", "software")):
        return "logic_score"
    if any(token in lowered for token in ("physics", "electrical", "mechanical")):
        return "physics_score"
    if any(token in lowered for token in ("biology", "medical", "nursing", "chemistry")):
        return "biology_score"
    if any(token in lowered for token in ("design", "art", "creative", "drawing")):
        return "creativity_score"
    if any(token in lowered for token in ("economics", "finance", "business", "marketing")):
        return "economics_score"
    return None


def to_feature_signals(extraction: CareerFeatureExtractionV1) -> Dict[str, float]:
    """Project extraction output into the numeric feature space used downstream."""
    confidence_10 = max(0.0, min(float(extraction.extraction_confidence), 1.0)) * 10.0
    projected: Dict[str, float] = {}

    for interest in extraction.inferred_interests:
        for feature_name, weight in INTEREST_TO_FEATURES.get(interest, {}).items():
            candidate = round(confidence_10 * weight, 2)
            projected[feature_name] = max(projected.get(feature_name, 0.0), candidate)

    for skill in extraction.skills:
        feature_name = _skill_keyword_to_feature(skill.skill_name)
        if feature_name is None:
            continue
        candidate = round(max(0.0, min(skill.confidence_score, 1.0)) * 10.0, 2)
        projected[feature_name] = max(projected.get(feature_name, 0.0), candidate)

    return {k: v for k, v in projected.items() if v > 0.0}


@tracer.start_as_current_span(SpanNames.LLM_EXTRACT)
async def extract_features_with_retry(anonymized_text: str) -> LLMExtractionAttempt:
    """Run LLM extraction with strict schema validation and retry budget."""
    start_time = time.time()
    prompt = _build_extraction_prompt(anonymized_text)

    span = trace.get_current_span()
    prompt_context = get_prompt_context()
    if prompt_context.prompt_id:
        span.set_attribute(TelemetryAttributes.PROMPT_ID, prompt_context.prompt_id)
    if prompt_context.prompt_version:
        span.set_attribute(TelemetryAttributes.PROMPT_VERSION, prompt_context.prompt_version)
    if prompt_context.prompt_hash:
        span.set_attribute(TelemetryAttributes.PROMPT_HASH, prompt_context.prompt_hash)
    if prompt_context.model_id:
        span.set_attribute(TelemetryAttributes.MODEL_ID, prompt_context.model_id)
    if prompt_context.model_version:
        span.set_attribute(TelemetryAttributes.MODEL_VERSION, prompt_context.model_version)

    schema_validation_failures = 0
    attempts = 0
    provider_failed = False

    for attempt in range(MAX_VALIDATION_RETRIES + 1):
        attempts = attempt + 1
        try:
            raw_text = await _invoke_llm_raw_output(prompt)
            TOTAL_COST_USD.inc(0.0001)

            with tracer.start_as_current_span(SpanNames.SCHEMA_VALIDATE):
                envelope = _parse_llm_output(raw_text)

            span.set_attribute(TelemetryAttributes.SCHEMA_VERSION, envelope.schema_version)
            set_prompt_context(schema_version=envelope.schema_version)

            feature = _map_envelope_to_feature(envelope)
            confidence = float(feature.extraction_confidence)
            latency = time.time() - start_time
            LLM_EXTRACTION_TIME.labels(model=MODEL_METRIC_LABEL).observe(latency)

            if confidence < MIN_EXTRACTION_CONFIDENCE:
                span.set_attribute(TelemetryAttributes.LOW_CONFIDENCE, True)
                return LLMExtractionAttempt(
                    feature=feature,
                    success=False,
                    used_fallback=True,
                    schema_validation_failures=schema_validation_failures,
                    attempts=attempts,
                    confidence=confidence,
                    fallback_reason="low_confidence",
                )

            return LLMExtractionAttempt(
                feature=feature,
                success=True,
                used_fallback=False,
                schema_validation_failures=schema_validation_failures,
                attempts=attempts,
                confidence=confidence,
            )

        except (ValueError, ValidationError) as exc:
            schema_validation_failures += 1
            LLM_ERROR_COUNTER.inc()
            logger.warning(
                "LLM schema validation failed",
                extra={"attempt": attempts, "error": str(exc)},
            )
            span.set_attribute(TelemetryAttributes.ERROR_TYPE, "schema_validation")
            continue
        except (LLMProviderError, RuntimeError, Exception) as exc:
            provider_failed = True
            LLM_ERROR_COUNTER.inc()
            logger.warning(
                "LLM provider invocation failed",
                extra={"attempt": attempts, "error": str(exc)},
            )
            span.set_attribute(TelemetryAttributes.ERROR_TYPE, "provider_error")
            break

    fallback_feature = await fallback_heuristic_extractor(anonymized_text)
    latency = time.time() - start_time
    LLM_EXTRACTION_TIME.labels(model=MODEL_METRIC_LABEL).observe(latency)

    fallback_reason = "schema_validation" if schema_validation_failures > 0 else "provider_error"
    if not provider_failed and schema_validation_failures == 0:
        fallback_reason = "unknown_error"

    return LLMExtractionAttempt(
        feature=fallback_feature,
        success=False,
        used_fallback=True,
        schema_validation_failures=schema_validation_failures,
        attempts=max(attempts, 1),
        confidence=float(fallback_feature.extraction_confidence),
        fallback_reason=fallback_reason,
    )


@tracer.start_as_current_span(LLM_FALLBACK_SPAN)
async def fallback_heuristic_extractor(text: str) -> CareerFeatureExtractionV1:
    """Deterministic minimal fallback when structured extraction cannot be trusted."""
    _ = text
    return CareerFeatureExtractionV1(
        inferred_interests=[CareerFieldEnum.UNKNOWN],
        extraction_confidence=0.0,
        missing_info_flags=["fallback_extraction_used"],
    )

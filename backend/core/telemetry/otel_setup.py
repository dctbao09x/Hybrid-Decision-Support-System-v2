import os
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.sampling import (
    AlwaysOnSampler,
    Sampler,
    SamplingResult,
    Decision,
    ParentBased,
    TraceIdRatioBased,
)

try:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
except ImportError:  # pragma: no cover - optional dependency
    OTLPSpanExporter = None

from backend.core.telemetry.attributes import TelemetryAttributes
from backend.core.telemetry.tail_sampler import TailSamplingConfig, TailSamplingSpanProcessor


class DynamicSampler(Sampler):
    def __init__(self, default_rate: float, high_rate: float):
        self._default_sampler = TraceIdRatioBased(default_rate)
        self._high_sampler = TraceIdRatioBased(high_rate)

    def should_sample(
        self,
        parent_context,
        trace_id,
        name,
        kind,
        attributes=None,
        links=None,
    ) -> SamplingResult:
        attributes = attributes or {}
        priority = attributes.get(TelemetryAttributes.TRACE_PRIORITY)
        sampler = self._high_sampler if priority == "high" else self._default_sampler
        return sampler.should_sample(parent_context, trace_id, name, kind, attributes, links)

    def get_description(self) -> str:
        return "DynamicSampler(default|high)"


_tracer_initialized = False


def setup_telemetry(service_name: Optional[str] = None) -> trace.Tracer:
    global _tracer_initialized
    if _tracer_initialized:
        return trace.get_tracer(__name__)

    name = service_name or os.getenv("SERVICE_NAME", "hdss-backend")
    default_rate = float(os.getenv("OTEL_SAMPLER_BASE_RATE", "0.05"))
    high_rate = float(os.getenv("OTEL_SAMPLER_HIGH_RATE", "1.0"))
    tail_enabled = os.getenv("OTEL_TAIL_SAMPLING", "true").lower() == "true"

    if tail_enabled:
        sampler = AlwaysOnSampler()
    else:
        sampler = ParentBased(DynamicSampler(default_rate, high_rate))
    resource = Resource.create({"service.name": name})

    provider = TracerProvider(resource=resource, sampler=sampler)

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint and OTLPSpanExporter is not None:
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
    else:
        exporter = ConsoleSpanExporter()

    if tail_enabled:
        config = TailSamplingConfig(
            success_rate=float(os.getenv("OTEL_SAMPLER_SUCCESS_RATE", "0.05")),
            slow_ms=float(os.getenv("OTEL_SAMPLER_SLOW_MS", "2000")),
            max_traces=int(os.getenv("OTEL_TAIL_MAX_TRACES", "1000")),
            max_spans_per_trace=int(os.getenv("OTEL_TAIL_MAX_SPANS", "200")),
            trace_ttl_seconds=float(os.getenv("OTEL_TAIL_TTL_SECONDS", "60")),
        )
        provider.add_span_processor(TailSamplingSpanProcessor(exporter, config))
    else:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _tracer_initialized = True
    return trace.get_tracer(__name__)


tracer = setup_telemetry()

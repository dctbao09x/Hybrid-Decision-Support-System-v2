import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanProcessor

from backend.core.telemetry.attributes import TelemetryAttributes
from backend.core.telemetry.span_naming import SpanNames


@dataclass
class TailSamplingConfig:
    success_rate: float = 0.05
    slow_ms: float = 2000.0
    max_traces: int = 1000
    max_spans_per_trace: int = 200
    trace_ttl_seconds: float = 60.0


class TailSamplingSpanProcessor(SpanProcessor):
    def __init__(self, exporter: SpanExporter, config: TailSamplingConfig) -> None:
        self._exporter = exporter
        self._config = config
        self._buffer: Dict[int, Dict[str, object]] = {}

    def on_start(self, span: ReadableSpan, parent_context) -> None:
        pass

    def on_end(self, span: ReadableSpan) -> None:
        trace_id = span.context.trace_id
        now = time.monotonic()
        entry = self._buffer.get(trace_id)
        if entry is None:
            entry = {"spans": [], "last_seen": now, "decision": None}
            self._buffer[trace_id] = entry
        entry["last_seen"] = now

        spans: List[ReadableSpan] = entry["spans"]  # type: ignore[assignment]
        if len(spans) < self._config.max_spans_per_trace:
            spans.append(span)

        # Pre-mark trace for export on critical signals
        if self._has_critical_signal(span):
            entry["decision"] = True

        if self._is_root_span(span):
            decision = entry["decision"]
            if decision is None:
                decision = self._decide(span)
            entry["decision"] = decision
            if decision:
                self._exporter.export(list(spans))
            self._buffer.pop(trace_id, None)

        self._cleanup_expired(now)

    def shutdown(self) -> None:
        for entry in self._buffer.values():
            spans: List[ReadableSpan] = entry["spans"]  # type: ignore[assignment]
            self._exporter.export(list(spans))
        self._buffer.clear()
        self._exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._exporter.force_flush(timeout_millis)

    def _is_root_span(self, span: ReadableSpan) -> bool:
        if span.parent is None:
            return True
        stage = span.attributes.get(TelemetryAttributes.PIPELINE_STAGE)
        return span.name == SpanNames.REQUEST_RECEIVE or stage == SpanNames.REQUEST_RECEIVE

    def _decide(self, span: ReadableSpan) -> bool:
        attributes = span.attributes or {}
        status_code = attributes.get("http.status_code", 0)
        duration_ms = attributes.get(TelemetryAttributes.REQUEST_DURATION_MS, 0.0)
        low_confidence = bool(attributes.get(TelemetryAttributes.LOW_CONFIDENCE))
        hitl_escalated = bool(attributes.get(TelemetryAttributes.HITL_ESCALATED))

        if status_code and int(status_code) >= 400:
            return True
        if duration_ms and float(duration_ms) >= self._config.slow_ms:
            return True
        if low_confidence or hitl_escalated:
            return True

        return random.random() < self._config.success_rate

    def _has_critical_signal(self, span: ReadableSpan) -> bool:
        attributes = span.attributes or {}
        if attributes.get(TelemetryAttributes.LOW_CONFIDENCE):
            return True
        if attributes.get(TelemetryAttributes.HITL_ESCALATED):
            return True
        return False

    def _cleanup_expired(self, now: float) -> None:
        ttl = self._config.trace_ttl_seconds
        if len(self._buffer) <= self._config.max_traces and ttl <= 0:
            return

        expired = [
            trace_id
            for trace_id, entry in self._buffer.items()
            if ttl > 0 and (now - float(entry["last_seen"])) >= ttl
        ]
        for trace_id in expired:
            self._buffer.pop(trace_id, None)

        if len(self._buffer) > self._config.max_traces:
            # Drop oldest traces first
            sorted_items = sorted(self._buffer.items(), key=lambda item: item[1]["last_seen"])
            for trace_id, _ in sorted_items[: len(self._buffer) - self._config.max_traces]:
                self._buffer.pop(trace_id, None)

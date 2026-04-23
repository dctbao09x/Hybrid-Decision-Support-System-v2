from __future__ import annotations

import asyncio
from functools import wraps
from typing import Any, Optional


class _NoOpSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        _ = (key, value)


class _NoOpSpanContext:
    def __enter__(self) -> _NoOpSpan:
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


try:
    from .otel_setup import tracer, setup_telemetry
except Exception:  # pragma: no cover
    tracer = _NoOpTracer()

    def setup_telemetry(service_name: Optional[str] = None):
        _ = service_name
        return tracer

from .span_naming import SpanNames
from .attributes import TelemetryAttributes
from .context import (
    correlation_id_var,
    request_id_var,
    set_request_context,
    get_request_context,
    set_prompt_context,
    get_prompt_context,
)

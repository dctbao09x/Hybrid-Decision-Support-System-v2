# backend/ops/resource/bottleneck.py
"""
Bottleneck Tracer for pipeline performance analysis.

Traces execution time across pipeline stages and sub-operations
to identify performance bottlenecks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ops.resource.bottleneck")


@dataclass
class SpanRecord:
    """A single timed span."""
    name: str
    stage: str
    start_time: float
    end_time: float = 0.0
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent: Optional[str] = None
    children: List[str] = field(default_factory=list)

    def finish(self) -> None:
        self.end_time = time.monotonic()
        self.duration_ms = (self.end_time - self.start_time) * 1000


class BottleneckTracer:
    """
    Traces pipeline execution to identify bottlenecks.

    Usage:
        tracer = BottleneckTracer()
        with tracer.span("crawl", "navigate_page"):
            await page.goto(url)
        with tracer.span("crawl", "extract_data"):
            data = await extract()
        report = tracer.analyze()
    """

    def __init__(self):
        self._spans: List[SpanRecord] = []
        self._active_spans: Dict[str, SpanRecord] = {}
        self._stage_totals: Dict[str, float] = defaultdict(float)
        self._lock = asyncio.Lock()

    @contextmanager
    def span(self, stage: str, name: str, **metadata):
        """Synchronous span context manager."""
        record = SpanRecord(
            name=name,
            stage=stage,
            start_time=time.monotonic(),
            metadata=metadata,
        )
        span_key = f"{stage}.{name}"
        self._active_spans[span_key] = record

        try:
            yield record
        finally:
            record.finish()
            self._spans.append(record)
            self._stage_totals[stage] += record.duration_ms
            self._active_spans.pop(span_key, None)

    @asynccontextmanager
    async def async_span(self, stage: str, name: str, **metadata):
        """Async span context manager."""
        record = SpanRecord(
            name=name,
            stage=stage,
            start_time=time.monotonic(),
            metadata=metadata,
        )
        span_key = f"{stage}.{name}"
        self._active_spans[span_key] = record

        try:
            yield record
        finally:
            record.finish()
            async with self._lock:
                self._spans.append(record)
                self._stage_totals[stage] += record.duration_ms
            self._active_spans.pop(span_key, None)

    def analyze(self, top_n: int = 10) -> Dict[str, Any]:
        """
        Analyze collected spans for bottlenecks.

        Returns:
            - Per-stage breakdown
            - Top N slowest operations
            - Bottleneck identification
        """
        if not self._spans:
            return {"status": "no_data"}

        # Per-stage analysis
        stage_stats: Dict[str, Dict[str, Any]] = {}
        stage_spans: Dict[str, List[SpanRecord]] = defaultdict(list)

        for span in self._spans:
            stage_spans[span.stage].append(span)

        total_time = sum(s.duration_ms for s in self._spans)

        for stage, spans in stage_spans.items():
            durations = [s.duration_ms for s in spans]
            stage_total = sum(durations)
            stage_stats[stage] = {
                "total_ms": round(stage_total, 2),
                "count": len(spans),
                "avg_ms": round(stage_total / len(spans), 2),
                "max_ms": round(max(durations), 2),
                "min_ms": round(min(durations), 2),
                "pct_of_total": round(stage_total / total_time * 100, 1) if total_time else 0,
            }

        # Top slowest
        sorted_spans = sorted(self._spans, key=lambda s: s.duration_ms, reverse=True)
        top_slow = [
            {
                "stage": s.stage,
                "name": s.name,
                "duration_ms": round(s.duration_ms, 2),
                "metadata": s.metadata,
            }
            for s in sorted_spans[:top_n]
        ]

        # Identify bottleneck stage
        bottleneck_stage = max(stage_stats, key=lambda k: stage_stats[k]["total_ms"]) if stage_stats else None

        return {
            "total_spans": len(self._spans),
            "total_time_ms": round(total_time, 2),
            "per_stage": stage_stats,
            "top_slowest": top_slow,
            "bottleneck_stage": bottleneck_stage,
            "bottleneck_pct": round(
                stage_stats[bottleneck_stage]["pct_of_total"], 1
            ) if bottleneck_stage else 0,
        }

    def reset(self) -> None:
        """Clear all collected spans."""
        self._spans.clear()
        self._active_spans.clear()
        self._stage_totals.clear()

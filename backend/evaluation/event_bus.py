# backend/evaluation/event_bus.py
"""
Event / Publish Layer
=====================
Lightweight dispatcher to publish ML evaluation results to downstream layers:
  • Scoring Engine
  • Explanation Layer
  • Logging / Audit System

Implementations can be:
  • In-process callbacks (default — sync)
  • Message queue (Redis, RabbitMQ — async stub)
  • HTTP webhooks (external integrations)

The interface is intentionally simple so it can be swapped out.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("ml_evaluation.event_bus")


# ═══════════════════════════════════════════════════════════════════════════
#  Event Types
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class EvaluationEvent:
    """Payload published after an ML evaluation run."""
    run_id: str
    model_type: str
    kfold: int
    metrics: Dict[str, Any]
    output_path: str
    timestamp: str
    quality_passed: bool


# ═══════════════════════════════════════════════════════════════════════════
#  Abstract Interface
# ═══════════════════════════════════════════════════════════════════════════

class EventPublisher(ABC):
    """Base class for event publishers."""

    @abstractmethod
    def publish(self, event: EvaluationEvent) -> bool:
        """Publish an event. Returns True on success."""

    @abstractmethod
    def name(self) -> str:
        """Human-readable name for logging."""


# ═══════════════════════════════════════════════════════════════════════════
#  Concrete Publishers
# ═══════════════════════════════════════════════════════════════════════════

class ScoringEnginePublisher(EventPublisher):
    """Notify the Scoring Engine of updated model metrics."""

    def __init__(self, callback: Optional[Callable[[EvaluationEvent], None]] = None):
        self._callback = callback

    def name(self) -> str:
        return "ScoringEngine"

    def publish(self, event: EvaluationEvent) -> bool:
        logger.info(
            "[%s] Publishing metrics for run %s (acc=%.4f)",
            self.name(), event.run_id,
            event.metrics.get("accuracy", {}).get("mean", 0),
        )
        if self._callback:
            try:
                self._callback(event)
            except Exception as exc:
                logger.warning("[%s] Callback error: %s", self.name(), exc)
                return False
        return True


class ExplanationLayerPublisher(EventPublisher):
    """Notify the Explanation Layer so it can update feature-importance views."""

    def __init__(self, callback: Optional[Callable[[EvaluationEvent], None]] = None):
        self._callback = callback

    def name(self) -> str:
        return "ExplanationLayer"

    def publish(self, event: EvaluationEvent) -> bool:
        logger.info("[%s] Publishing event for run %s", self.name(), event.run_id)
        if self._callback:
            try:
                self._callback(event)
            except Exception as exc:
                logger.warning("[%s] Callback error: %s", self.name(), exc)
                return False
        return True


class LoggingSystemPublisher(EventPublisher):
    """Write evaluation events to the central audit log."""

    def __init__(self, callback: Optional[Callable[[EvaluationEvent], None]] = None):
        self._callback = callback

    def name(self) -> str:
        return "LoggingSystem"

    def publish(self, event: EvaluationEvent) -> bool:
        logger.info(
            "[%s] Audit log — run_id=%s  model=%s  f1=%.4f  passed=%s",
            self.name(),
            event.run_id,
            event.model_type,
            event.metrics.get("f1", {}).get("mean", 0),
            event.quality_passed,
        )
        if self._callback:
            try:
                self._callback(event)
            except Exception as exc:
                logger.warning("[%s] Callback error: %s", self.name(), exc)
                return False
        return True


# ═══════════════════════════════════════════════════════════════════════════
#  Event Bus (Coordinator)
# ═══════════════════════════════════════════════════════════════════════════

class EventBus:
    """
    Central dispatcher that fans-out events to all registered publishers.

    Usage::

        bus = EventBus()
        bus.register(ScoringEnginePublisher())
        bus.register(ExplanationLayerPublisher())
        bus.publish(event)
    """

    def __init__(self) -> None:
        self._publishers: List[EventPublisher] = []

    def register(self, publisher: EventPublisher) -> None:
        """Add a publisher to the bus."""
        self._publishers.append(publisher)
        logger.info("Registered publisher: %s", publisher.name())

    def unregister(self, name: str) -> bool:
        """Remove a publisher by name."""
        before = len(self._publishers)
        self._publishers = [p for p in self._publishers if p.name() != name]
        return len(self._publishers) < before

    def publish(self, event: EvaluationEvent) -> Dict[str, bool]:
        """
        Publish event to all registered publishers.

        Returns:
            Dict mapping publisher name → success boolean.
        """
        results: Dict[str, bool] = {}
        for pub in self._publishers:
            try:
                results[pub.name()] = pub.publish(event)
            except Exception as exc:
                logger.error("Publisher %s raised: %s", pub.name(), exc)
                results[pub.name()] = False
        return results

    @property
    def publisher_count(self) -> int:
        return len(self._publishers)


# ═══════════════════════════════════════════════════════════════════════════
#  Factory helper — default bus with all layers
# ═══════════════════════════════════════════════════════════════════════════

def create_default_event_bus() -> EventBus:
    """Create an EventBus pre-wired with default publishers."""
    bus = EventBus()
    bus.register(ScoringEnginePublisher())
    bus.register(ExplanationLayerPublisher())
    bus.register(LoggingSystemPublisher())
    return bus

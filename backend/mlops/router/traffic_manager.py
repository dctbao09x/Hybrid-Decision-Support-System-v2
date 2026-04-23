"""Traffic Manager - Routes requests to production with async shadow mirroring."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class RoutingDecision:
    """Represents a routing decision for a request."""
    trace_id: str
    timestamp: str
    route_to_prod: bool
    mirror_to_shadow: bool
    shadow_model_id: Optional[str]
    prod_model_id: Optional[str]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "route_to_prod": self.route_to_prod,
            "mirror_to_shadow": self.mirror_to_shadow,
            "shadow_model_id": self.shadow_model_id,
            "prod_model_id": self.prod_model_id,
            "reason": self.reason,
        }


@dataclass
class TrafficConfig:
    """Configuration for traffic routing."""
    shadow_enabled: bool = False
    shadow_sample_rate: float = 1.0  # Percentage of traffic to mirror (0.0-1.0)
    shadow_timeout_seconds: float = 5.0
    shadow_model_id: Optional[str] = None
    prod_model_id: Optional[str] = None

    @classmethod
    def from_env(cls) -> "TrafficConfig":
        """Load configuration from environment variables."""
        return cls(
            shadow_enabled=os.getenv("MLOPS_SHADOW_ENABLED", "false").lower() in ("true", "1", "yes"),
            shadow_sample_rate=float(os.getenv("MLOPS_SHADOW_SAMPLE_RATE", "1.0")),
            shadow_timeout_seconds=float(os.getenv("MLOPS_SHADOW_TIMEOUT", "5.0")),
        )


class TrafficManager:
    """Manages traffic routing between production and shadow models.
    
    The traffic manager ensures:
    1. Production always serves the request (synchronously)
    2. Shadow inference runs asynchronously (fire-and-forget)
    3. Shadow results are compared and logged
    
    Example usage:
        manager = TrafficManager()
        
        # Set up models
        manager.set_prod_model("model_v1")
        manager.enable_shadow("model_v2_candidate")
        
        # Route a request
        decision = manager.route(trace_id="req_123")
        prod_result = await serve_prod(request)
        
        # Shadow runs async in background
        asyncio.create_task(manager.mirror_to_shadow(trace_id, request, prod_result))
    """

    def __init__(self, config: Optional[TrafficConfig] = None):
        """Initialize the traffic manager.
        
        Args:
            config: Traffic configuration. If None, loads from env.
        """
        self._config = config or TrafficConfig.from_env()
        self._prod_model_id: Optional[str] = self._config.prod_model_id
        self._shadow_model_id: Optional[str] = self._config.shadow_model_id
        self._shadow_enabled = self._config.shadow_enabled
        
        # Callbacks for inference
        self._prod_inference: Optional[Callable[[str, Any], Any]] = None
        self._shadow_inference: Optional[Callable[[str, Any], Any]] = None
        self._shadow_dispatcher: Optional[Any] = None  # Lazy import to avoid circular
        
        # Statistics
        self._stats = {
            "total_requests": 0,
            "shadow_mirrors": 0,
            "shadow_errors": 0,
        }

    def configure(
        self,
        prod_inference: Callable[[str, Any], Any],
        shadow_inference: Optional[Callable[[str, Any], Any]] = None,
    ) -> None:
        """Configure inference callbacks.
        
        Args:
            prod_inference: Function to run production inference (model_id, request) -> result
            shadow_inference: Function to run shadow inference (model_id, request) -> result
        """
        self._prod_inference = prod_inference
        self._shadow_inference = shadow_inference or prod_inference

    def set_prod_model(self, model_id: str) -> None:
        """Set the production model ID."""
        logger.info("Setting prod model: %s", model_id)
        self._prod_model_id = model_id

    def enable_shadow(self, model_id: str, sample_rate: float = 1.0) -> None:
        """Enable shadow testing with a candidate model.
        
        Args:
            model_id: Model ID to use for shadow testing
            sample_rate: Fraction of traffic to mirror (0.0-1.0)
        """
        logger.info("Enabling shadow: model=%s, sample_rate=%.2f", model_id, sample_rate)
        self._shadow_model_id = model_id
        self._shadow_enabled = True
        self._config.shadow_sample_rate = sample_rate

    def disable_shadow(self) -> None:
        """Disable shadow testing."""
        logger.info("Disabling shadow testing")
        self._shadow_enabled = False

    @property
    def shadow_enabled(self) -> bool:
        """Check if shadow testing is enabled."""
        return self._shadow_enabled and self._shadow_model_id is not None

    def get_status(self) -> Dict[str, Any]:
        """Get current traffic manager status."""
        return {
            "shadow_enabled": self._shadow_enabled,
            "shadow_model_id": self._shadow_model_id,
            "prod_model_id": self._prod_model_id,
            "sample_rate": self._config.shadow_sample_rate,
            "timeout_seconds": self._config.shadow_timeout_seconds,
            "stats": self._stats.copy(),
        }

    def _should_mirror(self) -> bool:
        """Determine if this request should be mirrored to shadow."""
        if not self._shadow_enabled or not self._shadow_model_id:
            return False
        
        # Sample based on configured rate
        import random
        return random.random() < self._config.shadow_sample_rate

    def route(self, trace_id: Optional[str] = None) -> RoutingDecision:
        """Make a routing decision for a request.
        
        Args:
            trace_id: Optional trace ID. If None, generates one.
            
        Returns:
            RoutingDecision with routing instructions
        """
        if trace_id is None:
            trace_id = f"trace_{uuid.uuid4().hex[:16]}"
        
        self._stats["total_requests"] += 1
        
        mirror = self._should_mirror()
        if mirror:
            self._stats["shadow_mirrors"] += 1
        
        reason = "normal"
        if mirror:
            reason = "shadow_test"
        
        return RoutingDecision(
            trace_id=trace_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            route_to_prod=True,  # Always serve from prod
            mirror_to_shadow=mirror,
            shadow_model_id=self._shadow_model_id if mirror else None,
            prod_model_id=self._prod_model_id,
            reason=reason,
        )

    async def serve_prod(
        self,
        trace_id: str,
        request: Any,
    ) -> Any:
        """Synchronously serve from production model.
        
        Args:
            trace_id: Request trace ID
            request: The request payload
            
        Returns:
            Production inference result
        """
        if self._prod_inference is None:
            raise RuntimeError("Production inference not configured")
        
        if self._prod_model_id is None:
            raise RuntimeError("Production model ID not set")
        
        return await self._prod_inference(self._prod_model_id, request)

    async def mirror_to_shadow(
        self,
        trace_id: str,
        request: Any,
        prod_result: Any,
    ) -> None:
        """Asynchronously mirror request to shadow model.
        
        This is fire-and-forget - errors are logged but don't affect the response.
        
        Args:
            trace_id: Request trace ID
            request: The original request payload
            prod_result: The production result for comparison
        """
        if not self._shadow_enabled or not self._shadow_model_id:
            return
        
        if self._shadow_inference is None:
            logger.warning("Shadow inference not configured")
            return
        
        try:
            # Get or create shadow dispatcher
            if self._shadow_dispatcher is None:
                from backend.mlops.router.shadow_dispatcher import get_shadow_dispatcher
                self._shadow_dispatcher = get_shadow_dispatcher()
            
            # Run shadow inference with timeout
            shadow_result = await asyncio.wait_for(
                self._shadow_inference(self._shadow_model_id, request),
                timeout=self._config.shadow_timeout_seconds,
            )
            
            # Log comparison
            await self._shadow_dispatcher.dispatch(
                trace_id=trace_id,
                request=request,
                prod_model_id=self._prod_model_id,
                shadow_model_id=self._shadow_model_id,
                prod_result=prod_result,
                shadow_result=shadow_result,
            )
            
        except asyncio.TimeoutError:
            self._stats["shadow_errors"] += 1
            logger.warning("Shadow inference timed out: trace=%s", trace_id)
        except Exception as e:
            self._stats["shadow_errors"] += 1
            logger.error("Shadow inference error: trace=%s, error=%s", trace_id, e)


# Singleton instance
_traffic_manager: Optional[TrafficManager] = None


def get_traffic_manager() -> TrafficManager:
    """Get the singleton TrafficManager instance."""
    global _traffic_manager
    if _traffic_manager is None:
        _traffic_manager = TrafficManager()
    return _traffic_manager

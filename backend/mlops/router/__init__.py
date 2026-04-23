"""MLOps Router Module - Shadow Test Traffic Routing and Dispatch."""

from backend.mlops.router.traffic_manager import (
    TrafficManager,
    RoutingDecision,
    get_traffic_manager,
)
from backend.mlops.router.shadow_dispatcher import (
    ShadowDispatcher,
    ShadowResult,
    ShadowComparison,
    get_shadow_dispatcher,
)

__all__ = [
    "TrafficManager",
    "RoutingDecision",
    "get_traffic_manager",
    "ShadowDispatcher",
    "ShadowResult",
    "ShadowComparison",
    "get_shadow_dispatcher",
]

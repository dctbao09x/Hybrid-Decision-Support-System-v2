# backend/inference/ab_router.py
"""
A/B Router
==========

Handles traffic splitting between active and canary models for A/B testing.

Features:
  - Config-driven traffic split
  - Sticky routing by user_id (consistent experience)
  - Gradual rollout support (canary deployment)
  - Kill switch for immediate rollback
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger("ml_inference.ab_router")


class RouteTarget(Enum):
    """Target model for routing."""
    ACTIVE = "active"
    CANARY = "canary"
    FALLBACK = "fallback"


@dataclass
class RoutingDecision:
    """Result of routing decision."""
    target: RouteTarget
    model_version: str
    user_id: str
    bucket: int  # 0-99 bucket for traffic split
    reason: str
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target.value,
            "model_version": self.model_version,
            "user_id": self.user_id,
            "bucket": self.bucket,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class ABRouter:
    """
    A/B testing router with sticky user routing.
    
    Usage::
    
        router = ABRouter()
        router.configure(canary_ratio=0.05)  # 5% to canary
        
        decision = router.route(user_id="user123")
        if decision.target == RouteTarget.CANARY:
            # Use canary model
        else:
            # Use active model
    """
    
    def __init__(self):
        self._lock = threading.RLock()
        
        # Configuration
        self._canary_ratio: float = 0.0  # 0-1, percentage to canary
        self._canary_version: str = ""
        self._active_version: str = "v1"
        self._fallback_version: str = ""
        
        # Kill switch
        self._kill_switch: bool = False  # If True, all traffic to active
        
        # Metrics
        self._route_counts: Dict[str, int] = {
            "active": 0,
            "canary": 0,
            "fallback": 0,
        }
    
    def configure(
        self,
        canary_ratio: float = 0.0,
        canary_version: str = "",
        active_version: str = "",
        fallback_version: str = "",
    ) -> None:
        """
        Configure routing parameters.
        
        Args:
            canary_ratio: Fraction of traffic to canary (0.0 - 1.0)
            canary_version: Version string for canary model
            active_version: Version string for active model
            fallback_version: Version string for fallback model
        """
        with self._lock:
            if canary_ratio < 0 or canary_ratio > 1:
                raise ValueError("canary_ratio must be between 0 and 1")
            
            self._canary_ratio = canary_ratio
            
            if canary_version:
                self._canary_version = canary_version
            if active_version:
                self._active_version = active_version
            if fallback_version:
                self._fallback_version = fallback_version
            
            logger.info(
                "Router configured: canary_ratio=%.2f active=%s canary=%s",
                self._canary_ratio,
                self._active_version,
                self._canary_version,
            )
    
    def set_kill_switch(self, enabled: bool) -> None:
        """
        Enable/disable kill switch.
        
        When enabled, all traffic routes to active model (bypasses canary).
        """
        with self._lock:
            self._kill_switch = enabled
            logger.warning("Kill switch %s", "ENABLED" if enabled else "DISABLED")
    
    def route(self, user_id: str) -> RoutingDecision:
        """
        Route a request based on user_id.
        
        Uses consistent hashing for sticky routing.
        
        Args:
            user_id: Unique user identifier
            
        Returns:
            RoutingDecision with target model
        """
        with self._lock:
            # Compute bucket (0-99) from user_id hash
            bucket = self._compute_bucket(user_id)
            
            # Check kill switch
            if self._kill_switch:
                self._route_counts["active"] += 1
                return RoutingDecision(
                    target=RouteTarget.ACTIVE,
                    model_version=self._active_version,
                    user_id=user_id,
                    bucket=bucket,
                    reason="kill_switch_enabled",
                )
            
            # Check if canary is configured
            if self._canary_ratio > 0 and self._canary_version:
                # Route to canary if in canary bucket
                threshold = int(self._canary_ratio * 100)
                if bucket < threshold:
                    self._route_counts["canary"] += 1
                    return RoutingDecision(
                        target=RouteTarget.CANARY,
                        model_version=self._canary_version,
                        user_id=user_id,
                        bucket=bucket,
                        reason=f"canary_bucket (threshold={threshold})",
                    )
            
            # Default to active
            self._route_counts["active"] += 1
            return RoutingDecision(
                target=RouteTarget.ACTIVE,
                model_version=self._active_version,
                user_id=user_id,
                bucket=bucket,
                reason="default_active",
            )
    
    def route_to_fallback(self, user_id: str, error: str) -> RoutingDecision:
        """Route to fallback model due to error."""
        with self._lock:
            bucket = self._compute_bucket(user_id)
            self._route_counts["fallback"] += 1
            
            return RoutingDecision(
                target=RouteTarget.FALLBACK,
                model_version=self._fallback_version or self._active_version,
                user_id=user_id,
                bucket=bucket,
                reason=f"fallback_due_to: {error}",
            )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get routing statistics."""
        with self._lock:
            total = sum(self._route_counts.values())
            return {
                "canary_ratio": self._canary_ratio,
                "active_version": self._active_version,
                "canary_version": self._canary_version,
                "kill_switch": self._kill_switch,
                "route_counts": self._route_counts.copy(),
                "total_requests": total,
                "actual_canary_ratio": (
                    self._route_counts["canary"] / total if total > 0 else 0
                ),
            }
    
    def reset_stats(self) -> None:
        """Reset routing statistics."""
        with self._lock:
            self._route_counts = {"active": 0, "canary": 0, "fallback": 0}
    
    def promote_canary(self) -> bool:
        """
        Promote canary to active.
        
        Returns:
            True if promotion successful
        """
        with self._lock:
            if not self._canary_version:
                logger.warning("No canary to promote")
                return False
            
            # Save current active as fallback
            self._fallback_version = self._active_version
            
            # Promote canary to active
            old_active = self._active_version
            self._active_version = self._canary_version
            self._canary_version = ""
            self._canary_ratio = 0.0
            
            logger.info(
                "Promoted canary: %s -> active (old active %s -> fallback)",
                self._active_version, old_active,
            )
            return True
    
    def rollback_canary(self) -> bool:
        """
        Abort canary deployment, route all to active.
        
        Returns:
            True if rollback successful
        """
        with self._lock:
            if not self._canary_version:
                logger.info("No canary to rollback")
                return False
            
            rolled_back = self._canary_version
            self._canary_version = ""
            self._canary_ratio = 0.0
            
            logger.info("Rolled back canary: %s", rolled_back)
            return True
    
    def _compute_bucket(self, user_id: str) -> int:
        """
        Compute consistent bucket (0-99) from user_id.
        
        Same user_id always maps to same bucket (sticky routing).
        """
        # Use MD5 for fast, consistent hashing
        hash_bytes = hashlib.md5(user_id.encode()).digest()
        # Take first 4 bytes as integer
        hash_int = int.from_bytes(hash_bytes[:4], byteorder="big")
        # Map to 0-99
        return hash_int % 100

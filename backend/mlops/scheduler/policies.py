"""Policies - Cooldown, Anti-Storm, and Retry policies for automated retraining."""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CooldownViolation(Exception):
    """Raised when a retrain attempt violates the cooldown policy."""

    def __init__(
        self,
        message: str,
        last_retrain_at: Optional[datetime] = None,
        cooldown_remaining_hours: float = 0.0,
    ):
        super().__init__(message)
        self.last_retrain_at = last_retrain_at
        self.cooldown_remaining_hours = cooldown_remaining_hours


@dataclass
class CooldownStatus:
    """Status of the current cooldown state."""
    active: bool
    remaining_hours: float
    last_retrain_at: Optional[str]
    next_eligible_at: Optional[str]
    min_interval_hours: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "active": self.active,
            "remaining_hours": round(self.remaining_hours, 2),
            "last_retrain_at": self.last_retrain_at,
            "next_eligible_at": self.next_eligible_at,
            "min_interval_hours": self.min_interval_hours,
        }


class CooldownPolicy:
    """Enforces minimum interval between retrain operations.
    
    Configurable via environment variables:
    - MLOPS_COOLDOWN_HOURS: Minimum hours between retrains (default: 24)
    - MLOPS_COOLDOWN_ENABLED: Enable/disable cooldown (default: true)
    """

    def __init__(
        self,
        min_interval_hours: Optional[float] = None,
        enabled: Optional[bool] = None,
    ):
        """Initialize the cooldown policy.
        
        Args:
            min_interval_hours: Minimum hours between retrains. If None, reads from env.
            enabled: Whether cooldown is enabled. If None, reads from env.
        """
        self._min_interval_hours = min_interval_hours
        self._enabled = enabled

    @property
    def min_interval_hours(self) -> float:
        """Get the minimum interval in hours."""
        if self._min_interval_hours is not None:
            return self._min_interval_hours
        return float(os.getenv("MLOPS_COOLDOWN_HOURS", "24"))

    @property
    def enabled(self) -> bool:
        """Check if cooldown is enabled."""
        if self._enabled is not None:
            return self._enabled
        return os.getenv("MLOPS_COOLDOWN_ENABLED", "true").lower() in ("true", "1", "yes")

    def check(
        self,
        last_retrain_at: Optional[datetime],
        trigger: str = "auto",
    ) -> CooldownStatus:
        """Check cooldown status without raising.
        
        Args:
            last_retrain_at: Timestamp of the last retrain
            trigger: Type of trigger ('auto', 'manual')
            
        Returns:
            CooldownStatus with current state
        """
        if not self.enabled:
            return CooldownStatus(
                active=False,
                remaining_hours=0.0,
                last_retrain_at=last_retrain_at.isoformat() if last_retrain_at else None,
                next_eligible_at=None,
                min_interval_hours=self.min_interval_hours,
            )

        if last_retrain_at is None:
            return CooldownStatus(
                active=False,
                remaining_hours=0.0,
                last_retrain_at=None,
                next_eligible_at=None,
                min_interval_hours=self.min_interval_hours,
            )

        now = datetime.now(timezone.utc)
        elapsed_hours = (now - last_retrain_at).total_seconds() / 3600
        remaining = max(0.0, self.min_interval_hours - elapsed_hours)
        active = remaining > 0

        from datetime import timedelta
        next_eligible = last_retrain_at + timedelta(hours=self.min_interval_hours)

        return CooldownStatus(
            active=active,
            remaining_hours=remaining,
            last_retrain_at=last_retrain_at.isoformat(),
            next_eligible_at=next_eligible.isoformat() if active else None,
            min_interval_hours=self.min_interval_hours,
        )

    def enforce(
        self,
        last_retrain_at: Optional[datetime],
        trigger: str = "auto",
        bypass_manual: bool = True,
    ) -> CooldownStatus:
        """Enforce cooldown policy, raising if violated.
        
        Args:
            last_retrain_at: Timestamp of the last retrain
            trigger: Type of trigger ('auto', 'manual')
            bypass_manual: Allow manual triggers to bypass cooldown
            
        Returns:
            CooldownStatus if allowed
            
        Raises:
            CooldownViolation: If cooldown is active and cannot be bypassed
        """
        status = self.check(last_retrain_at, trigger)
        
        # Manual triggers can bypass if configured
        if trigger == "manual" and bypass_manual:
            if status.active:
                logger.warning(
                    "Manual trigger bypassing cooldown. Remaining: %.2f hours",
                    status.remaining_hours,
                )
            return status
        
        if status.active:
            msg = (
                f"Cooldown active. Last retrain: {status.last_retrain_at}. "
                f"Remaining: {status.remaining_hours:.2f} hours. "
                f"Next eligible: {status.next_eligible_at}"
            )
            logger.warning("Cooldown violation: %s", msg)
            raise CooldownViolation(
                message=msg,
                last_retrain_at=last_retrain_at,
                cooldown_remaining_hours=status.remaining_hours,
            )
        
        return status


@dataclass
class AntiStormStatus:
    """Status of the anti-storm protection."""
    blocked: bool
    reason: Optional[str]
    recent_attempts: int
    threshold: int
    window_hours: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "blocked": self.blocked,
            "reason": self.reason,
            "recent_attempts": self.recent_attempts,
            "threshold": self.threshold,
            "window_hours": self.window_hours,
        }


class AntiStormPolicy:
    """Prevents retrain storms by limiting attempts within a time window.
    
    Configurable via environment variables:
    - MLOPS_STORM_MAX_ATTEMPTS: Max attempts per window (default: 5)
    - MLOPS_STORM_WINDOW_HOURS: Window size in hours (default: 6)
    - MLOPS_STORM_ENABLED: Enable/disable protection (default: true)
    """

    def __init__(
        self,
        max_attempts: Optional[int] = None,
        window_hours: Optional[int] = None,
        enabled: Optional[bool] = None,
    ):
        """Initialize the anti-storm policy.
        
        Args:
            max_attempts: Max retrain attempts per window. If None, reads from env.
            window_hours: Time window in hours. If None, reads from env.
            enabled: Whether protection is enabled. If None, reads from env.
        """
        self._max_attempts = max_attempts
        self._window_hours = window_hours
        self._enabled = enabled

    @property
    def max_attempts(self) -> int:
        """Get the maximum attempts allowed."""
        if self._max_attempts is not None:
            return self._max_attempts
        return int(os.getenv("MLOPS_STORM_MAX_ATTEMPTS", "5"))

    @property
    def window_hours(self) -> int:
        """Get the time window in hours."""
        if self._window_hours is not None:
            return self._window_hours
        return int(os.getenv("MLOPS_STORM_WINDOW_HOURS", "6"))

    @property
    def enabled(self) -> bool:
        """Check if protection is enabled."""
        if self._enabled is not None:
            return self._enabled
        return os.getenv("MLOPS_STORM_ENABLED", "true").lower() in ("true", "1", "yes")

    def check(self, recent_runs: List[Dict[str, Any]]) -> AntiStormStatus:
        """Check if retrain is allowed under anti-storm policy.
        
        Args:
            recent_runs: List of recent run entries with timestamps
            
        Returns:
            AntiStormStatus with current state
        """
        if not self.enabled:
            return AntiStormStatus(
                blocked=False,
                reason=None,
                recent_attempts=0,
                threshold=self.max_attempts,
                window_hours=self.window_hours,
            )

        # Count actual retrain attempts (not just blocks)
        attempt_count = sum(
            1 for r in recent_runs
            if r.get("trigger") in ("auto", "manual", "alarm")
            and r.get("status") in ("success", "failed")
        )

        blocked = attempt_count >= self.max_attempts
        reason = None
        if blocked:
            reason = (
                f"Storm protection: {attempt_count} attempts in last "
                f"{self.window_hours} hours (max: {self.max_attempts})"
            )
            logger.warning("Anti-storm block: %s", reason)

        return AntiStormStatus(
            blocked=blocked,
            reason=reason,
            recent_attempts=attempt_count,
            threshold=self.max_attempts,
            window_hours=self.window_hours,
        )


@dataclass
class RetryPolicy:
    """Retry policy with exponential backoff for failed retrains."""
    max_retries: int = 3
    base_delay_seconds: float = 60.0
    max_delay_seconds: float = 3600.0
    exponential_base: float = 2.0

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for a given attempt number.
        
        Args:
            attempt: Current attempt number (0-indexed)
            
        Returns:
            Delay in seconds before next retry
        """
        if attempt >= self.max_retries:
            return self.max_delay_seconds
        
        delay = self.base_delay_seconds * (self.exponential_base ** attempt)
        return min(delay, self.max_delay_seconds)

    def should_retry(self, attempt: int) -> bool:
        """Check if another retry is allowed.
        
        Args:
            attempt: Current attempt number (0-indexed)
            
        Returns:
            True if retry is allowed, False otherwise
        """
        return attempt < self.max_retries


# Default policy instances
def get_cooldown_policy() -> CooldownPolicy:
    """Get the default cooldown policy."""
    return CooldownPolicy()


def get_anti_storm_policy() -> AntiStormPolicy:
    """Get the default anti-storm policy."""
    return AntiStormPolicy()

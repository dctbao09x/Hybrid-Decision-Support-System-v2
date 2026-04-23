# backend/ops/testing/chaos.py
"""
Chaos Testing Engine
====================

Provides chaos testing capabilities for validating system resilience.

Scenarios:
- Network failures
- Service outages
- Resource exhaustion
- Latency injection
- Data corruption (simulated)
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger("ops.testing.chaos")


class ChaosType(str, Enum):
    """Types of chaos to inject."""
    LATENCY = "latency"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    NETWORK_PARTITION = "network_partition"
    DATA_CORRUPTION = "data_corruption"
    CASCADE_FAILURE = "cascade_failure"


@dataclass
class ChaosScenario:
    """Definition of a chaos scenario."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    chaos_type: ChaosType = ChaosType.FAILURE
    
    # Targeting
    target_services: List[str] = field(default_factory=list)
    target_percentage: float = 100.0  # Percentage of requests affected
    
    # Duration
    duration_seconds: int = 60
    gradual_rollout: bool = False
    rollout_seconds: int = 10
    
    # Parameters
    latency_ms: int = 1000  # For latency injection
    failure_rate: float = 1.0  # 0.0-1.0
    error_code: str = "CHAOS_INJECTED"
    
    # Safety
    abort_on_critical: bool = True
    max_affected_requests: int = 1000


@dataclass
class ChaosResult:
    """Result of a chaos test."""
    scenario_id: str
    success: bool
    started_at: datetime
    ended_at: datetime
    duration_ms: int
    
    # Metrics
    requests_affected: int = 0
    requests_failed: int = 0
    requests_succeeded: int = 0
    
    # System response
    recovery_detected: bool = False
    recovery_time_ms: int = 0
    circuit_breakers_triggered: int = 0
    alerts_generated: int = 0
    
    # Errors
    errors: List[str] = field(default_factory=list)
    
    # Observations
    observations: List[str] = field(default_factory=list)


@dataclass
class ChaosState:
    """Current state of chaos engine."""
    active: bool = False
    current_scenario: Optional[str] = None
    affected_services: List[str] = field(default_factory=list)
    requests_intercepted: int = 0
    start_time: Optional[datetime] = None


class ChaosEngine:
    """
    Chaos testing engine for validating system resilience.
    
    Features:
    - Multiple chaos types
    - Gradual rollout
    - Safety controls
    - Automatic recovery detection
    """
    
    def __init__(self):
        self._scenarios: Dict[str, ChaosScenario] = {}
        self._results: List[ChaosResult] = []
        self._state = ChaosState()
        
        # Interceptors
        self._interceptors: List[Callable[[str, Dict], Coroutine[Any, Any, bool]]] = []
        
        # Recovery detectors
        self._recovery_callbacks: List[Callable[[], Coroutine[Any, Any, bool]]] = []
        
        # Running task
        self._chaos_task: Optional[asyncio.Task] = None
        
        # Register built-in scenarios
        self._register_builtin_scenarios()
    
    def add_scenario(self, scenario: ChaosScenario):
        """Add a chaos scenario."""
        self._scenarios[scenario.id] = scenario
        logger.info(f"Added chaos scenario: {scenario.name}")
    
    def remove_scenario(self, scenario_id: str):
        """Remove a chaos scenario."""
        self._scenarios.pop(scenario_id, None)
    
    def get_scenario(self, scenario_id: str) -> Optional[ChaosScenario]:
        """Get a scenario by ID."""
        return self._scenarios.get(scenario_id)
    
    def list_scenarios(self) -> List[ChaosScenario]:
        """List all registered scenarios."""
        return list(self._scenarios.values())
    
    async def run(self, scenario_id: str) -> ChaosResult:
        """
        Run a chaos scenario.
        
        Args:
            scenario_id: ID of scenario to run
            
        Returns:
            ChaosResult with test outcomes
        """
        scenario = self._scenarios.get(scenario_id)
        if not scenario:
            raise ValueError(f"Scenario {scenario_id} not found")
        
        if self._state.active:
            raise RuntimeError("Another chaos scenario is already running")
        
        logger.warning(f"Starting chaos scenario: {scenario.name}")
        
        # Initialize state
        self._state = ChaosState(
            active=True,
            current_scenario=scenario_id,
            affected_services=scenario.target_services.copy(),
            start_time=datetime.utcnow(),
        )
        
        started_at = datetime.utcnow()
        errors = []
        observations = []
        requests_affected = 0
        requests_failed = 0
        
        try:
            # Run chaos for duration
            if scenario.gradual_rollout:
                # Gradually increase chaos
                for i in range(scenario.rollout_seconds):
                    if not self._state.active:
                        break
                    progress = (i + 1) / scenario.rollout_seconds
                    observations.append(f"Rollout progress: {progress * 100:.0f}%")
                    await asyncio.sleep(1)
            
            # Full chaos
            remaining = scenario.duration_seconds
            if scenario.gradual_rollout:
                remaining -= scenario.rollout_seconds
            
            while remaining > 0 and self._state.active:
                # Inject chaos
                affected, failed = await self._inject_chaos(scenario)
                requests_affected += affected
                requests_failed += failed
                
                # Check safety limits
                if requests_affected >= scenario.max_affected_requests:
                    observations.append("Safety limit reached - stopping")
                    break
                
                await asyncio.sleep(1)
                remaining -= 1
            
            # Check for recovery
            recovery_detected = False
            recovery_time_ms = 0
            
            for callback in self._recovery_callbacks:
                if await callback():
                    recovery_detected = True
                    recovery_time = datetime.utcnow() - started_at
                    recovery_time_ms = int(recovery_time.total_seconds() * 1000)
                    observations.append(f"Recovery detected after {recovery_time_ms}ms")
                    break
            
        except Exception as e:
            errors.append(str(e))
            logger.error(f"Chaos scenario error: {e}")
            
        finally:
            self._state.active = False
        
        ended_at = datetime.utcnow()
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)
        
        result = ChaosResult(
            scenario_id=scenario_id,
            success=len(errors) == 0,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            requests_affected=requests_affected,
            requests_failed=requests_failed,
            requests_succeeded=requests_affected - requests_failed,
            recovery_detected=recovery_detected,
            recovery_time_ms=recovery_time_ms,
            errors=errors,
            observations=observations,
        )
        
        self._results.append(result)
        logger.info(f"Chaos scenario completed: {scenario.name}")
        
        return result
    
    async def stop(self):
        """Stop the currently running chaos scenario."""
        if self._state.active:
            logger.info("Stopping chaos scenario")
            self._state.active = False
            
            if self._chaos_task:
                self._chaos_task.cancel()
                try:
                    await self._chaos_task
                except asyncio.CancelledError:
                    pass
    
    def add_interceptor(
        self,
        interceptor: Callable[[str, Dict], Coroutine[Any, Any, bool]],
    ):
        """Add a request interceptor for chaos injection."""
        self._interceptors.append(interceptor)
    
    def add_recovery_detector(
        self,
        detector: Callable[[], Coroutine[Any, Any, bool]],
    ):
        """Add a recovery detection callback."""
        self._recovery_callbacks.append(detector)
    
    async def intercept(self, service: str, request: Dict) -> Optional[Exception]:
        """
        Intercept a request and potentially inject chaos.
        
        Args:
            service: Target service name
            request: Request data
            
        Returns:
            Exception if chaos should be injected, None otherwise
        """
        if not self._state.active:
            return None
        
        scenario = self._scenarios.get(self._state.current_scenario or "")
        if not scenario:
            return None
        
        # Check if service is targeted
        if scenario.target_services and service not in scenario.target_services:
            return None
        
        # Check percentage
        if random.random() * 100 > scenario.target_percentage:
            return None
        
        self._state.requests_intercepted += 1
        
        # Inject chaos based on type
        if scenario.chaos_type == ChaosType.LATENCY:
            await asyncio.sleep(scenario.latency_ms / 1000)
            return None
            
        elif scenario.chaos_type == ChaosType.FAILURE:
            if random.random() <= scenario.failure_rate:
                return Exception(f"Chaos failure: {scenario.error_code}")
            
        elif scenario.chaos_type == ChaosType.TIMEOUT:
            await asyncio.sleep(scenario.latency_ms / 1000)
            raise asyncio.TimeoutError("Chaos timeout")
        
        return None
    
    def get_state(self) -> ChaosState:
        """Get current chaos state."""
        return self._state
    
    def get_results(self, limit: int = 10) -> List[ChaosResult]:
        """Get recent chaos test results."""
        return self._results[-limit:]
    
    async def _inject_chaos(
        self,
        scenario: ChaosScenario,
    ) -> tuple[int, int]:
        """Inject chaos and return (affected, failed) counts."""
        affected = 0
        failed = 0
        
        # Call interceptors
        for interceptor in self._interceptors:
            try:
                if await interceptor(scenario.target_services[0] if scenario.target_services else "all", {}):
                    affected += 1
                    if random.random() <= scenario.failure_rate:
                        failed += 1
            except Exception:
                failed += 1
                affected += 1
        
        return affected, failed
    
    def _register_builtin_scenarios(self):
        """Register built-in chaos scenarios."""
        # Network latency
        self.add_scenario(ChaosScenario(
            id="builtin_latency",
            name="Network Latency",
            description="Inject 500ms latency to all services",
            chaos_type=ChaosType.LATENCY,
            latency_ms=500,
            duration_seconds=30,
            target_percentage=50.0,
        ))
        
        # Service failure
        self.add_scenario(ChaosScenario(
            id="builtin_failure",
            name="Random Failures",
            description="Inject random failures at 10% rate",
            chaos_type=ChaosType.FAILURE,
            failure_rate=0.1,
            duration_seconds=60,
            target_percentage=100.0,
        ))
        
        # Timeout
        self.add_scenario(ChaosScenario(
            id="builtin_timeout",
            name="Timeout Storm",
            description="Cause request timeouts",
            chaos_type=ChaosType.TIMEOUT,
            latency_ms=10000,
            duration_seconds=30,
            target_percentage=25.0,
        ))

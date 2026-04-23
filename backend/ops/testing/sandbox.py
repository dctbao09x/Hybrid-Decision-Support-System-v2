# backend/ops/testing/sandbox.py
"""
Ops Sandbox
===========

Provides an isolated environment for testing operations.

Features:
- Isolated execution
- State snapshotting
- Automatic cleanup
- Resource limits
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger("ops.testing.sandbox")


@dataclass
class SandboxConfig:
    """Configuration for sandbox environment."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "default"
    
    # Resource limits
    max_execution_time: int = 300  # seconds
    max_memory_mb: int = 512
    max_concurrent_commands: int = 5
    
    # Isolation
    isolated_storage: bool = True
    mock_external_services: bool = True
    capture_side_effects: bool = True
    
    # Cleanup
    auto_cleanup: bool = True
    cleanup_delay: int = 60  # seconds after completion


@dataclass
class SandboxState:
    """State snapshot of sandbox."""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    resources: Dict[str, Any] = field(default_factory=dict)
    executed_commands: List[str] = field(default_factory=list)
    side_effects: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class SandboxResult:
    """Result of sandbox execution."""
    success: bool
    duration_ms: int
    commands_executed: int
    side_effects: List[Dict[str, Any]]
    errors: List[str]
    final_state: SandboxState


class OpsSandbox:
    """
    Isolated environment for testing operations.
    
    Features:
    - Execute commands without affecting production
    - Capture and inspect side effects
    - Automatic state restoration
    """
    
    def __init__(self, config: Optional[SandboxConfig] = None):
        self._config = config or SandboxConfig()
        self._state = SandboxState()
        self._active = False
        self._start_time: Optional[datetime] = None
        
        # Mock handlers
        self._mock_handlers: Dict[str, Callable] = {}
        
        # Side effect capture
        self._captured_effects: List[Dict[str, Any]] = []
        
        # Resource tracking
        self._resources: Dict[str, Any] = {}
        
        logger.info(f"Sandbox {self._config.id} initialized")
    
    async def __aenter__(self):
        """Enter sandbox context."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit sandbox context."""
        await self.stop()
    
    async def start(self):
        """Start the sandbox environment."""
        if self._active:
            return
        
        self._active = True
        self._start_time = datetime.utcnow()
        self._state = SandboxState()
        self._captured_effects = []
        
        logger.info(f"Sandbox {self._config.id} started")
    
    async def stop(self) -> SandboxResult:
        """Stop the sandbox and return results."""
        if not self._active:
            return self._create_result()
        
        self._active = False
        
        # Cleanup if enabled
        if self._config.auto_cleanup:
            await self._cleanup()
        
        result = self._create_result()
        logger.info(
            f"Sandbox {self._config.id} stopped: "
            f"{result.commands_executed} commands, "
            f"{len(result.side_effects)} effects"
        )
        
        return result
    
    def register_mock(
        self,
        command_type: str,
        handler: Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]],
    ):
        """Register a mock handler for a command type."""
        self._mock_handlers[command_type] = handler
    
    async def execute(
        self,
        command_type: str,
        target: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a command in the sandbox.
        
        Args:
            command_type: Type of command
            target: Target resource
            params: Command parameters
            
        Returns:
            Execution result
        """
        if not self._active:
            raise RuntimeError("Sandbox is not active")
        
        # Check resource limits
        if len(self._state.executed_commands) >= self._config.max_concurrent_commands:
            raise RuntimeError("Max concurrent commands exceeded")
        
        # Check execution time
        if self._start_time:
            elapsed = (datetime.utcnow() - self._start_time).total_seconds()
            if elapsed > self._config.max_execution_time:
                raise RuntimeError("Max execution time exceeded")
        
        # Execute with mock or simulated handler
        handler = self._mock_handlers.get(command_type)
        
        try:
            if handler:
                result = await handler({"type": command_type, "target": target, **params})
            else:
                result = await self._simulate_command(command_type, target, params)
            
            # Record execution
            self._state.executed_commands.append(command_type)
            
            # Capture side effects
            if self._config.capture_side_effects:
                effect = {
                    "command": command_type,
                    "target": target,
                    "result": result,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                self._captured_effects.append(effect)
                self._state.side_effects.append(effect)
            
            return result
            
        except Exception as e:
            self._state.errors.append(str(e))
            raise
    
    async def execute_sequence(
        self,
        commands: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Execute a sequence of commands.
        
        Args:
            commands: List of command specifications
            
        Returns:
            List of results
        """
        results = []
        
        for cmd in commands:
            result = await self.execute(
                command_type=cmd.get("type", "unknown"),
                target=cmd.get("target", ""),
                params=cmd.get("params", {}),
            )
            results.append(result)
        
        return results
    
    def get_state(self) -> SandboxState:
        """Get current sandbox state."""
        return self._state
    
    def get_side_effects(self) -> List[Dict[str, Any]]:
        """Get captured side effects."""
        return self._captured_effects.copy()
    
    def set_resource(self, key: str, value: Any):
        """Set a resource value in the sandbox."""
        self._resources[key] = value
        self._state.resources[key] = value
    
    def get_resource(self, key: str) -> Optional[Any]:
        """Get a resource value from the sandbox."""
        return self._resources.get(key)
    
    async def _simulate_command(
        self,
        command_type: str,
        target: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Simulate a command execution."""
        # Basic simulation - returns success with simulated data
        await asyncio.sleep(0.1)  # Simulate processing time
        
        return {
            "success": True,
            "simulated": True,
            "command_type": command_type,
            "target": target,
            "params": params,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    async def _cleanup(self):
        """Cleanup sandbox resources."""
        logger.info(f"Cleaning up sandbox {self._config.id}")
        
        # Clear captured data
        self._captured_effects.clear()
        self._resources.clear()
        
        # Reset state
        self._state = SandboxState()
    
    def _create_result(self) -> SandboxResult:
        """Create execution result."""
        duration_ms = 0
        if self._start_time:
            duration = datetime.utcnow() - self._start_time
            duration_ms = int(duration.total_seconds() * 1000)
        
        return SandboxResult(
            success=len(self._state.errors) == 0,
            duration_ms=duration_ms,
            commands_executed=len(self._state.executed_commands),
            side_effects=self._captured_effects.copy(),
            errors=self._state.errors.copy(),
            final_state=self._state,
        )

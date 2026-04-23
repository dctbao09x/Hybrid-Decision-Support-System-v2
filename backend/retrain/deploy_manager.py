# backend/retrain/deploy_manager.py
"""
Deploy Manager
==============

Manages canary deployment and automatic rollback.

Deployment flow:
  1. Start canary (5% traffic to new model)
  2. Monitor metrics for observation period
  3. If metrics OK → promote to active
  4. If metrics FAIL → rollback canary
  5. Kill switch for emergency rollback
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from backend.inference.ab_router import ABRouter
from backend.inference.model_loader import ModelLoader
from backend.retrain.model_registry import ModelRegistry
from backend.state import StatePolicy, get_operational_state_store

logger = logging.getLogger("ml_retrain.deploy")


class DeployState(Enum):
    """Deployment state."""
    IDLE = "idle"
    CANARY = "canary"
    PROMOTING = "promoting"
    ROLLING_BACK = "rolling_back"


@dataclass
class DeployResult:
    """Result of a deployment operation."""
    success: bool
    action: str
    version: str
    state: str
    message: str
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "action": self.action,
            "version": self.version,
            "state": self.state,
            "message": self.message,
            "timestamp": self.timestamp,
        }


class DeployManager:
    """
    Manages canary deployment with automatic rollback.
    
    Usage::
    
        deploy = DeployManager(router, loader, registry)
        deploy.load_config(config)
        
        # Start canary
        result = deploy.start_canary("v2")
        
        # Monitor and auto-promote/rollback
        deploy.observe()
        
        # Or manual promotion
        deploy.promote()
        
        # Emergency rollback
        deploy.rollback()
    """
    
    def __init__(
        self,
        router: Optional[ABRouter] = None,
        loader: Optional[ModelLoader] = None,
        registry: Optional[ModelRegistry] = None,
    ):
        self._project_root = Path(__file__).resolve().parents[2]
        
        self._router = router or ABRouter()
        self._loader = loader or ModelLoader()
        self._registry = registry or ModelRegistry()
        self._state_store = get_operational_state_store()
        self._state_policy = StatePolicy(ttl_seconds=None, persistent=True, stale_after_seconds=1800)
        self._state_namespace = "deploy_manager"
        self._runtime_state_key = "runtime"
        
        # Config (config-driven)
        self._canary_ratio = 0.05  # 5%
        self._observation_minutes = 30
        self._auto_rollback = True
        self._f1_threshold = 0.01  # F1_new >= F1_old - 0.01
        
        # Monitoring
        self._observer_thread: Optional[threading.Thread] = None
        self._stop_observer = threading.Event()
        
        # Logs
        self._deploy_logs_dir = self._project_root / "deploy_logs"
        self._deploy_logs_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_runtime_state()

    def _state_lock(self, name: str = "runtime"):
        return self._state_store.lock(
            name=f"deploy_manager:{name}",
            ttl_seconds=20.0,
            wait_timeout_seconds=5.0,
            retry_interval_seconds=0.05,
        )

    def _default_runtime_state(self) -> Dict[str, Any]:
        return {
            "state": DeployState.IDLE.value,
            "canary_version": None,
            "canary_start_time": None,
            "kill_switch": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _ensure_runtime_state(self) -> None:
        state = self._state_store.get_json(
            namespace=self._state_namespace,
            state_key=self._runtime_state_key,
            default=None,
            policy=self._state_policy,
        )
        if not isinstance(state, dict):
            self._state_store.set_json(
                namespace=self._state_namespace,
                state_key=self._runtime_state_key,
                value=self._default_runtime_state(),
                policy=self._state_policy,
            )

    def _get_runtime_state(self) -> Dict[str, Any]:
        state = self._state_store.get_json(
            namespace=self._state_namespace,
            state_key=self._runtime_state_key,
            default=self._default_runtime_state(),
            policy=self._state_policy,
        )
        if isinstance(state, dict):
            return state
        return self._default_runtime_state()

    def _save_runtime_state(self, state: Dict[str, Any]) -> None:
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._state_store.set_json(
            namespace=self._state_namespace,
            state_key=self._runtime_state_key,
            value=state,
            policy=self._state_policy,
        )

    @staticmethod
    def _state_enum(state_doc: Dict[str, Any]) -> DeployState:
        raw = str(state_doc.get("state", DeployState.IDLE.value)).strip().lower()
        try:
            return DeployState(raw)
        except Exception:
            return DeployState.IDLE
    
    def load_config(self, config: Dict[str, Any]) -> None:
        """Load deployment configuration."""
        deploy_cfg = config.get("deploy", {})
        
        self._canary_ratio = deploy_cfg.get("canary_ratio", 0.05)
        self._observation_minutes = deploy_cfg.get("observation_minutes", 30)
        self._auto_rollback = deploy_cfg.get("auto_rollback", True)
        self._f1_threshold = deploy_cfg.get("f1_threshold", 0.01)
        
        logger.info(
            "Deploy config: canary=%.1f%% obs=%dmin auto_rollback=%s",
            self._canary_ratio * 100,
            self._observation_minutes,
            self._auto_rollback,
        )
    
    def get_state(self) -> Dict[str, Any]:
        """Get current deployment state."""
        state = self._get_runtime_state()
        return {
            "state": self._state_enum(state).value,
            "canary_version": state.get("canary_version"),
            "canary_start_time": state.get("canary_start_time"),
            "canary_ratio": self._canary_ratio,
            "kill_switch": bool(state.get("kill_switch", False)),
            "auto_rollback": self._auto_rollback,
        }
    
    def start_canary(self, version: str) -> DeployResult:
        """
        Start canary deployment for a new version.
        
        Routes canary_ratio traffic to new model.
        """
        with self._state_lock("start_canary"):
            runtime = self._get_runtime_state()
            current_state = self._state_enum(runtime)

            if current_state != DeployState.IDLE:
                return DeployResult(
                    success=False,
                    action="start_canary",
                    version=version,
                    state=current_state.value,
                    message=f"Cannot start canary: already in {current_state.value} state",
                )

            if bool(runtime.get("kill_switch", False)):
                return DeployResult(
                    success=False,
                    action="start_canary",
                    version=version,
                    state=current_state.value,
                    message="Cannot start canary: kill switch is enabled",
                )
        
        # Verify version exists
        version_info = self._registry.get_version(version)
        if not version_info:
            state = self._state_enum(self._get_runtime_state())
            return DeployResult(
                success=False,
                action="start_canary",
                version=version,
                state=state.value,
                message=f"Version not found: {version}",
            )
        
        try:
            # Load canary model
            self._loader.load_canary(version)
            
            # Configure router
            active = self._registry.get_active()
            active_version = active.version if active else "unknown"
            
            self._router.configure(
                canary_ratio=self._canary_ratio,
                canary_version=version,
                active_version=active_version,
            )
            
            # Update state
            with self._state_lock("start_canary_update"):
                runtime = self._get_runtime_state()
                runtime["state"] = DeployState.CANARY.value
                runtime["canary_version"] = version
                runtime["canary_start_time"] = time.time()
                self._save_runtime_state(runtime)
            
            # Log
            self._log_deploy_event("canary_started", version, {
                "canary_ratio": self._canary_ratio,
                "active_version": active_version,
            })
            
            logger.info(
                "Started canary: %s with %.1f%% traffic",
                version, self._canary_ratio * 100,
            )
            
            return DeployResult(
                success=True,
                action="start_canary",
                version=version,
                state=DeployState.CANARY.value,
                message=f"Canary started with {self._canary_ratio*100:.1f}% traffic",
            )
            
        except Exception as e:
            logger.error("Failed to start canary: %s", e)
            state = self._state_enum(self._get_runtime_state())
            return DeployResult(
                success=False,
                action="start_canary",
                version=version,
                state=state.value,
                message=str(e),
            )
    
    def promote(self) -> DeployResult:
        """Promote canary to active."""
        with self._state_lock("promote"):
            runtime = self._get_runtime_state()
            current_state = self._state_enum(runtime)
            if current_state != DeployState.CANARY:
                return DeployResult(
                    success=False,
                    action="promote",
                    version=str(runtime.get("canary_version") or ""),
                    state=current_state.value,
                    message=f"Cannot promote: not in canary state (current: {current_state.value})",
                )

            version = str(runtime.get("canary_version") or "")
            runtime["state"] = DeployState.PROMOTING.value
            self._save_runtime_state(runtime)
        
        try:
            # Activate in registry
            self._registry.activate(version)
            
            # Hot-swap in loader
            self._loader.hot_swap(version)
            
            # Update router (100% to new active)
            self._router.configure(
                canary_ratio=0.0,
                canary_version="",
                active_version=version,
            )
            self._router.promote_canary()
            
            # Reset state
            with self._state_lock("promote_finalize"):
                runtime = self._get_runtime_state()
                runtime["state"] = DeployState.IDLE.value
                runtime["canary_version"] = None
                runtime["canary_start_time"] = None
                self._save_runtime_state(runtime)
            
            # Log
            self._log_deploy_event("canary_promoted", version, {})
            
            logger.info("Promoted canary %s to active", version)
            
            return DeployResult(
                success=True,
                action="promote",
                version=version,
                state=DeployState.IDLE.value,
                message=f"Promoted {version} to active",
            )
            
        except Exception as e:
            logger.error("Failed to promote: %s", e)
            with self._state_lock("promote_revert"):
                runtime = self._get_runtime_state()
                runtime["state"] = DeployState.CANARY.value
                self._save_runtime_state(runtime)
            return DeployResult(
                success=False,
                action="promote",
                version=version,
                state=DeployState.CANARY.value,
                message=str(e),
            )
    
    def rollback(self, reason: str = "manual") -> DeployResult:
        """
        Rollback canary or active deployment.
        
        If in canary state: abort canary
        If in idle state: rollback to previous version
        """
        with self._state_lock("rollback"):
            runtime = self._get_runtime_state()
            version = str(runtime.get("canary_version") or "active")
            runtime["state"] = DeployState.ROLLING_BACK.value
            self._save_runtime_state(runtime)
        
        try:
            runtime = self._get_runtime_state()
            canary_version = runtime.get("canary_version")

            if canary_version:
                # Abort canary
                self._router.rollback_canary()
                self._router.configure(
                    canary_ratio=0.0,
                    canary_version="",
                )
                
                old_canary = str(canary_version)

                with self._state_lock("rollback_finalize_canary"):
                    runtime = self._get_runtime_state()
                    runtime["canary_version"] = None
                    runtime["canary_start_time"] = None
                    runtime["state"] = DeployState.IDLE.value
                    self._save_runtime_state(runtime)
                
                self._log_deploy_event("canary_rolled_back", old_canary, {
                    "reason": reason,
                })
                
                logger.info("Rolled back canary %s: %s", old_canary, reason)
                
            else:
                # Rollback active to previous
                rolled_to = self._registry.rollback()
                
                if rolled_to:
                    self._loader.rollback()
                    self._router.configure(active_version=rolled_to)
                    
                    self._log_deploy_event("active_rolled_back", rolled_to, {
                        "reason": reason,
                    })
                    
                    logger.info("Rolled back active to %s: %s", rolled_to, reason)
                else:
                    logger.warning("No rollback version available")
                with self._state_lock("rollback_finalize_active"):
                    runtime = self._get_runtime_state()
                    runtime["state"] = DeployState.IDLE.value
                    self._save_runtime_state(runtime)
            
            return DeployResult(
                success=True,
                action="rollback",
                version=version,
                state=DeployState.IDLE.value,
                message=f"Rolled back: {reason}",
            )
            
        except Exception as e:
            logger.error("Rollback failed: %s", e)
            with self._state_lock("rollback_error"):
                runtime = self._get_runtime_state()
                runtime["state"] = DeployState.IDLE.value
                self._save_runtime_state(runtime)
            return DeployResult(
                success=False,
                action="rollback",
                version=version,
                state=DeployState.IDLE.value,
                message=str(e),
            )
    
    def set_kill_switch(self, enabled: bool) -> DeployResult:
        """Enable or disable kill switch."""
        with self._state_lock("kill_switch"):
            runtime = self._get_runtime_state()
            runtime["kill_switch"] = bool(enabled)
            canary_active = self._state_enum(runtime) == DeployState.CANARY
            self._save_runtime_state(runtime)

        self._router.set_kill_switch(enabled)
        
        if enabled and canary_active:
            # Abort canary deployment
            self.rollback("kill_switch_enabled")
        
        self._log_deploy_event(
            "kill_switch_changed",
            "",
            {"enabled": enabled},
        )
        
        return DeployResult(
            success=True,
            action="kill_switch",
            version="",
            state=self._state_enum(self._get_runtime_state()).value,
            message=f"Kill switch {'enabled' if enabled else 'disabled'}",
        )
    
    def start_observer(self) -> None:
        """Start background observer for auto-promote/rollback."""
        if self._observer_thread and self._observer_thread.is_alive():
            return
        
        self._stop_observer.clear()
        self._observer_thread = threading.Thread(
            target=self._observe_loop,
            daemon=True,
        )
        self._observer_thread.start()
        logger.info("Started deployment observer")
    
    def stop_observer(self) -> None:
        """Stop background observer."""
        self._stop_observer.set()
        if self._observer_thread:
            self._observer_thread.join(timeout=5)
        logger.info("Stopped deployment observer")
    
    def _observe_loop(self) -> None:
        """Background observation loop."""
        while not self._stop_observer.is_set():
            runtime = self._get_runtime_state()
            canary_start = runtime.get("canary_start_time")
            if self._state_enum(runtime) == DeployState.CANARY and isinstance(canary_start, (int, float)):
                elapsed_minutes = (time.time() - float(canary_start)) / 60
                
                if elapsed_minutes >= self._observation_minutes:
                    # Check if we should promote or rollback
                    decision = self._evaluate_canary()
                    
                    if decision == "promote":
                        self.promote()
                    elif decision == "rollback":
                        if self._auto_rollback:
                            self.rollback("auto_rollback_metrics_failed")
            
            # Check every 30 seconds
            self._stop_observer.wait(30)
    
    def _evaluate_canary(self) -> str:
        """
        Evaluate whether canary should be promoted or rolled back.
        
        Returns: "promote", "rollback", or "continue"
        """
        # Get canary metrics
        runtime = self._get_runtime_state()
        canary_version = runtime.get("canary_version")
        canary_info = self._registry.get_version(str(canary_version)) if canary_version else None
        active_info = self._registry.get_active()
        
        if not canary_info or not active_info:
            return "continue"
        
        # Compare F1 scores
        canary_f1 = canary_info.f1
        active_f1 = active_info.f1
        
        # Promotion rule: F1_new >= F1_old - threshold
        if canary_f1 >= active_f1 - self._f1_threshold:
            logger.info(
                "Canary evaluation: PROMOTE (f1=%.4f >= %.4f - %.4f)",
                canary_f1, active_f1, self._f1_threshold,
            )
            return "promote"
        else:
            logger.warning(
                "Canary evaluation: ROLLBACK (f1=%.4f < %.4f - %.4f)",
                canary_f1, active_f1, self._f1_threshold,
            )
            return "rollback"
    
    def _log_deploy_event(
        self,
        event: str,
        version: str,
        details: Dict[str, Any],
    ) -> None:
        """Log deployment event."""
        log_entry = {
            "event": event,
            "version": version,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": details,
            "state": self.get_state(),
        }

        self._state_store.append_event(
            namespace=self._state_namespace,
            event_type=event,
            payload=log_entry,
            state_key=self._runtime_state_key,
        )
        
        log_file = self._deploy_logs_dir / f"deploy_{datetime.now().strftime('%Y%m%d')}.jsonl"
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")

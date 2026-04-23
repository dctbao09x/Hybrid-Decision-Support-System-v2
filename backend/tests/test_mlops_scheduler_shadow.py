"""Comprehensive tests for MLOps Scheduler, Cooldown, and Shadow Testing.

Coverage targets: ≥85% for mlops/ module

Tests:
- M1: Automated retrain scheduler
- M2: Cooldown policy enforcement
- M3: Shadow test routing
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def run_async(coro):
    """Helper to run async functions in sync tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ============================================================================
# M1: Scheduler Tests
# ============================================================================

class TestSchedulerTrigger:
    """Test automated retrain scheduler triggers."""

    def test_scheduler_config_from_env(self, monkeypatch):
        """Test scheduler loads config from environment variables."""
        monkeypatch.setenv("MLOPS_SCHEDULER_ENABLED", "true")
        monkeypatch.setenv("MLOPS_SCHEDULER_POLL_INTERVAL", "60")
        monkeypatch.setenv("MLOPS_SCHEDULER_MIN_FEEDBACK", "50")
        
        from backend.mlops.scheduler.retrain_scheduler import SchedulerConfig
        
        config = SchedulerConfig.from_env()
        assert config.enabled is True
        assert config.poll_interval_seconds == 60
        assert config.min_feedback_count == 50

    def test_scheduler_disabled_by_default_env(self, monkeypatch):
        """Test scheduler respects disabled setting."""
        monkeypatch.setenv("MLOPS_SCHEDULER_ENABLED", "false")
        
        from backend.mlops.scheduler.retrain_scheduler import SchedulerConfig
        
        config = SchedulerConfig.from_env()
        assert config.enabled is False

    def test_scheduler_trigger_on_drift(self, monkeypatch, tmp_path):
        """Test scheduler triggers retrain when drift exceeds threshold."""
        from backend.mlops.scheduler.retrain_scheduler import RetrainScheduler, SchedulerConfig
        from backend.mlops.scheduler.state_store import StateStore
        from backend.mlops.scheduler.policies import CooldownPolicy
        
        # Setup
        state_store = StateStore(storage_path=str(tmp_path / "state.json"))
        cooldown = CooldownPolicy(min_interval_hours=0, enabled=False)  # Disable for test
        config = SchedulerConfig(enabled=True)
        
        scheduler = RetrainScheduler(
            config=config,
            state_store=state_store,
            cooldown_policy=cooldown,
        )
        
        # Mock providers
        train_called = {"count": 0}
        
        async def mock_train(trigger: str):
            train_called["count"] += 1
            return {"run_id": "test_run", "status": "success", "trigger": trigger}
        
        scheduler.configure(
            metric_provider=lambda: {"drift_score": 0.5, "accuracy_drop": 0.1},  # Exceeds thresholds
            feedback_provider=lambda: {},
            train_callback=mock_train,
        )
        
        # Trigger check
        result = run_async(scheduler.check_and_trigger())
        
        assert result["triggered"] is True
        assert train_called["count"] == 1
        assert "drift_score" in str(result.get("trigger_reasons", []))

    def test_scheduler_no_trigger_below_threshold(self, tmp_path):
        """Test scheduler does NOT trigger when metrics are healthy."""
        from backend.mlops.scheduler.retrain_scheduler import RetrainScheduler, SchedulerConfig
        from backend.mlops.scheduler.state_store import StateStore
        from backend.mlops.scheduler.policies import CooldownPolicy
        
        state_store = StateStore(storage_path=str(tmp_path / "state.json"))
        cooldown = CooldownPolicy(min_interval_hours=0, enabled=False)
        config = SchedulerConfig(enabled=True)
        
        scheduler = RetrainScheduler(
            config=config,
            state_store=state_store,
            cooldown_policy=cooldown,
        )
        
        train_called = {"count": 0}
        
        async def mock_train(trigger: str):
            train_called["count"] += 1
            return {"status": "success"}
        
        # Healthy metrics - below thresholds
        scheduler.configure(
            metric_provider=lambda: {"drift_score": 0.01, "accuracy_drop": 0.01, "error_rate": 0.001},
            feedback_provider=lambda: {"negative_feedback_rate": 0.01},
            train_callback=mock_train,
        )
        
        result = run_async(scheduler.check_and_trigger())
        
        assert result["triggered"] is False
        assert train_called["count"] == 0

    def test_scheduler_force_trigger(self, tmp_path):
        """Test scheduler force trigger bypasses condition checks."""
        from backend.mlops.scheduler.retrain_scheduler import RetrainScheduler, SchedulerConfig
        from backend.mlops.scheduler.state_store import StateStore
        from backend.mlops.scheduler.policies import CooldownPolicy
        
        state_store = StateStore(storage_path=str(tmp_path / "state.json"))
        cooldown = CooldownPolicy(min_interval_hours=0, enabled=False)
        config = SchedulerConfig(enabled=True)
        
        scheduler = RetrainScheduler(
            config=config,
            state_store=state_store,
            cooldown_policy=cooldown,
        )
        
        train_called = {"count": 0}
        
        async def mock_train(trigger: str):
            train_called["count"] += 1
            return {"run_id": "forced_run", "status": "success"}
        
        # Healthy metrics - would not normally trigger
        scheduler.configure(
            metric_provider=lambda: {"drift_score": 0.01},
            feedback_provider=lambda: {},
            train_callback=mock_train,
        )
        
        result = run_async(scheduler.check_and_trigger(force=True))
        
        assert result["triggered"] is True
        assert train_called["count"] == 1
        assert "forced" in result.get("trigger_reasons", [])


# ============================================================================
# M2: Cooldown Policy Tests
# ============================================================================

class TestCooldownPolicy:
    """Test cooldown policy enforcement."""

    def test_cooldown_check_no_previous_retrain(self):
        """Test cooldown allows when no previous retrain exists."""
        from backend.mlops.scheduler.policies import CooldownPolicy
        
        policy = CooldownPolicy(min_interval_hours=24, enabled=True)
        status = policy.check(last_retrain_at=None)
        
        assert status.active is False
        assert status.remaining_hours == 0.0

    def test_cooldown_check_within_window(self):
        """Test cooldown is active within the cooldown window."""
        from backend.mlops.scheduler.policies import CooldownPolicy
        
        policy = CooldownPolicy(min_interval_hours=24, enabled=True)
        
        # Last retrain was 12 hours ago
        last_retrain = datetime.now(timezone.utc) - timedelta(hours=12)
        status = policy.check(last_retrain_at=last_retrain)
        
        assert status.active is True
        assert 11 < status.remaining_hours < 13  # ~12 hours remaining

    def test_cooldown_check_after_window(self):
        """Test cooldown is inactive after window expires."""
        from backend.mlops.scheduler.policies import CooldownPolicy
        
        policy = CooldownPolicy(min_interval_hours=24, enabled=True)
        
        # Last retrain was 30 hours ago
        last_retrain = datetime.now(timezone.utc) - timedelta(hours=30)
        status = policy.check(last_retrain_at=last_retrain)
        
        assert status.active is False
        assert status.remaining_hours == 0.0

    def test_cooldown_enforce_raises_for_auto_trigger(self):
        """Test cooldown raises CooldownViolation for auto triggers."""
        from backend.mlops.scheduler.policies import CooldownPolicy, CooldownViolation
        
        policy = CooldownPolicy(min_interval_hours=24, enabled=True)
        
        last_retrain = datetime.now(timezone.utc) - timedelta(hours=12)
        
        with pytest.raises(CooldownViolation) as exc_info:
            policy.enforce(last_retrain_at=last_retrain, trigger="auto")
        
        assert exc_info.value.cooldown_remaining_hours > 0

    def test_cooldown_enforce_allows_manual_bypass(self):
        """Test manual triggers can bypass cooldown by default."""
        from backend.mlops.scheduler.policies import CooldownPolicy
        
        policy = CooldownPolicy(min_interval_hours=24, enabled=True)
        
        last_retrain = datetime.now(timezone.utc) - timedelta(hours=12)
        
        # Should not raise for manual trigger
        status = policy.enforce(last_retrain_at=last_retrain, trigger="manual", bypass_manual=True)
        
        assert status.active is True  # Still shows as active
        # But no exception raised

    def test_cooldown_disabled(self):
        """Test cooldown can be disabled."""
        from backend.mlops.scheduler.policies import CooldownPolicy
        
        policy = CooldownPolicy(min_interval_hours=24, enabled=False)
        
        last_retrain = datetime.now(timezone.utc) - timedelta(hours=1)
        status = policy.check(last_retrain_at=last_retrain)
        
        assert status.active is False

    def test_cooldown_env_config(self, monkeypatch):
        """Test cooldown reads from environment variables."""
        monkeypatch.setenv("MLOPS_COOLDOWN_HOURS", "48")
        monkeypatch.setenv("MLOPS_COOLDOWN_ENABLED", "true")
        
        from backend.mlops.scheduler.policies import CooldownPolicy
        
        policy = CooldownPolicy()  # Should read from env
        
        assert policy.min_interval_hours == 48
        assert policy.enabled is True


class TestCooldownInLifecycle:
    """Test cooldown integration in MLOpsManager lifecycle."""

    def test_train_blocked_by_cooldown(self, monkeypatch, tmp_path):
        """Test lifecycle.train() is blocked by cooldown for auto triggers."""
        from backend.mlops.scheduler.policies import CooldownViolation
        from backend.mlops.scheduler.state_store import StateStore
        from backend.mlops.lifecycle import MLOpsManager
        
        # Create a manager with mocked state store that has recent retrain
        manager = MLOpsManager()
        
        # Mock the state store to return a recent retrain
        state_store = StateStore(storage_path=str(tmp_path / "state.json"))
        
        # Record a recent retrain
        state_store.record_retrain(
            run_id="prev_run",
            trigger="manual",
            status="success",
        )
        
        manager._state_store = state_store
        
        # Now try auto retrain - should be blocked
        with pytest.raises(CooldownViolation):
            run_async(manager.train(trigger="auto", source="feedback"))

    def test_train_status_includes_cooldown(self, monkeypatch, tmp_path):
        """Test training results include cooldown status."""
        from backend.mlops.lifecycle import MLOpsManager
        from backend.mlops.scheduler.state_store import StateStore
        
        manager = MLOpsManager()
        state_store = StateStore(storage_path=str(tmp_path / "state.json"))
        manager._state_store = state_store
        
        # Mock the dataset build to fail early (avoid full training)
        async def mock_build(*args, **kwargs):
            raise ValueError("Test skip training")
        
        manager._datasets.build_immutable_from_training_candidates = mock_build
        
        result = run_async(manager.train(trigger="manual", source="feedback"))
        
        assert "cooldown_status" in result
        assert result["cooldown_status"]["min_interval_hours"] > 0


class TestAntiStormPolicy:
    """Test anti-storm protection against retrain storms."""

    def test_anti_storm_allows_under_threshold(self):
        """Test anti-storm allows when under attempt threshold."""
        from backend.mlops.scheduler.policies import AntiStormPolicy
        
        policy = AntiStormPolicy(max_attempts=5, window_hours=6, enabled=True)
        
        recent_runs = [
            {"trigger": "auto", "status": "success", "timestamp": datetime.now(timezone.utc).isoformat()},
            {"trigger": "auto", "status": "success", "timestamp": datetime.now(timezone.utc).isoformat()},
        ]
        
        status = policy.check(recent_runs)
        
        assert status.blocked is False
        assert status.recent_attempts == 2

    def test_anti_storm_blocks_at_threshold(self):
        """Test anti-storm blocks when threshold is reached."""
        from backend.mlops.scheduler.policies import AntiStormPolicy
        
        policy = AntiStormPolicy(max_attempts=3, window_hours=6, enabled=True)
        
        recent_runs = [
            {"trigger": "auto", "status": "success", "timestamp": datetime.now(timezone.utc).isoformat()},
            {"trigger": "auto", "status": "failed", "timestamp": datetime.now(timezone.utc).isoformat()},
            {"trigger": "manual", "status": "success", "timestamp": datetime.now(timezone.utc).isoformat()},
        ]
        
        status = policy.check(recent_runs)
        
        assert status.blocked is True
        assert "Storm protection" in (status.reason or "")


# ============================================================================
# M3: Shadow Test Routing Tests
# ============================================================================

class TestTrafficManager:
    """Test traffic manager routing decisions."""

    def test_route_without_shadow(self):
        """Test routing without shadow enabled returns prod-only decision."""
        from backend.mlops.router.traffic_manager import TrafficManager, TrafficConfig
        
        config = TrafficConfig(shadow_enabled=False)
        manager = TrafficManager(config=config)
        manager.set_prod_model("model_v1")
        
        decision = manager.route()
        
        assert decision.route_to_prod is True
        assert decision.mirror_to_shadow is False
        assert decision.shadow_model_id is None

    def test_route_with_shadow_enabled(self):
        """Test routing with shadow enabled includes mirror decision."""
        from backend.mlops.router.traffic_manager import TrafficManager, TrafficConfig
        
        config = TrafficConfig(shadow_enabled=False)  # Start disabled
        manager = TrafficManager(config=config)
        manager.set_prod_model("model_v1")
        manager.enable_shadow("model_v2_candidate", sample_rate=1.0)
        
        decision = manager.route()
        
        assert decision.route_to_prod is True
        assert decision.mirror_to_shadow is True
        assert decision.shadow_model_id == "model_v2_candidate"

    def test_route_sample_rate(self):
        """Test shadow sampling respects sample rate."""
        from backend.mlops.router.traffic_manager import TrafficManager, TrafficConfig
        
        config = TrafficConfig(shadow_enabled=False)
        manager = TrafficManager(config=config)
        manager.set_prod_model("model_v1")
        manager.enable_shadow("model_v2", sample_rate=0.5)
        
        # Run many samples
        mirror_count = sum(1 for _ in range(1000) if manager.route().mirror_to_shadow)
        
        # Should be roughly 50% (allow some variance)
        assert 400 < mirror_count < 600

    def test_disable_shadow(self):
        """Test disabling shadow stops mirroring."""
        from backend.mlops.router.traffic_manager import TrafficManager, TrafficConfig
        
        manager = TrafficManager()
        manager.enable_shadow("model_v2", sample_rate=1.0)
        manager.disable_shadow()
        
        decision = manager.route()
        
        assert decision.mirror_to_shadow is False

    def test_get_status(self):
        """Test status reporting includes all fields."""
        from backend.mlops.router.traffic_manager import TrafficManager
        
        manager = TrafficManager()
        manager.set_prod_model("model_v1")
        manager.enable_shadow("model_v2", sample_rate=0.8)
        
        status = manager.get_status()
        
        assert status["shadow_enabled"] is True
        assert status["shadow_model_id"] == "model_v2"
        assert status["prod_model_id"] == "model_v1"
        assert status["sample_rate"] == 0.8


class TestShadowDispatcher:
    """Test shadow result dispatcher and comparison."""

    def test_dispatch_logs_comparison(self, tmp_path):
        """Test dispatch creates comparison log entry."""
        from backend.mlops.router.shadow_dispatcher import ShadowDispatcher
        
        dispatcher = ShadowDispatcher(
            log_path=str(tmp_path / "shadow.jsonl"),
            batch_size=1,  # Flush immediately
        )
        
        comparison = run_async(dispatcher.dispatch(
            trace_id="trace_001",
            request={"text": "test input"},
            prod_model_id="model_v1",
            shadow_model_id="model_v2",
            prod_result={"score": 0.85, "label": "A"},
            shadow_result={"score": 0.87, "label": "A"},
        ))
        
        assert comparison.trace_id == "trace_001"
        assert comparison.match is True  # Same label, small score diff
        assert "score_diff" in comparison.delta

    def test_dispatch_detects_mismatch(self, tmp_path):
        """Test dispatch correctly identifies mismatches."""
        from backend.mlops.router.shadow_dispatcher import ShadowDispatcher
        
        dispatcher = ShadowDispatcher(log_path=str(tmp_path / "shadow.jsonl"))
        
        comparison = run_async(dispatcher.dispatch(
            trace_id="trace_002",
            request={},
            prod_model_id="v1",
            shadow_model_id="v2",
            prod_result={"score": 0.9, "label": "A"},
            shadow_result={"score": 0.3, "label": "B"},  # Different label and big score diff
        ))
        
        assert comparison.match is False
        assert comparison.delta.get("label_match") is False
        assert comparison.delta.get("score_diff") > 0.5

    def test_stats_accumulation(self, tmp_path):
        """Test statistics are accumulated correctly."""
        from backend.mlops.router.shadow_dispatcher import ShadowDispatcher
        
        dispatcher = ShadowDispatcher(log_path=str(tmp_path / "shadow.jsonl"))
        
        # Dispatch several comparisons
        run_async(dispatcher.dispatch("t1", {}, "v1", "v2", {"label": "A"}, {"label": "A"}))
        run_async(dispatcher.dispatch("t2", {}, "v1", "v2", {"label": "A"}, {"label": "B"}))
        run_async(dispatcher.dispatch("t3", {}, "v1", "v2", {"label": "B"}, {"label": "B"}))
        
        stats = dispatcher.get_stats()
        
        assert stats["total_comparisons"] == 3
        assert stats["matches"] == 2
        assert stats["mismatches"] == 1
        assert 0.6 < stats["match_rate"] < 0.7

    def test_batch_evaluator(self, tmp_path):
        """Test batch evaluator processes log file correctly."""
        from backend.mlops.router.shadow_dispatcher import BatchEvaluator
        
        log_path = tmp_path / "shadow.jsonl"
        
        # Write test entries
        entries = [
            {"timestamp": datetime.now(timezone.utc).isoformat(), "match": True, "delta": {"score_diff": 0.01}},
            {"timestamp": datetime.now(timezone.utc).isoformat(), "match": True, "delta": {"score_diff": 0.02}},
            {"timestamp": datetime.now(timezone.utc).isoformat(), "match": False, "delta": {"score_diff": 0.1, "label_match": False}},
        ]
        
        with log_path.open("w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
        
        evaluator = BatchEvaluator(log_path=str(log_path))
        result = evaluator.evaluate()
        
        assert result["status"] == "success"
        assert result["entries"] == 3
        assert result["metrics"]["matches"] == 2
        assert result["metrics"]["mismatches"] == 1
        assert "recommendation" in result


class TestShadowLogPersistence:
    """Test shadow log persistence and recovery."""

    def test_log_persisted_to_file(self, tmp_path):
        """Test shadow results are persisted to log file."""
        from backend.mlops.router.shadow_dispatcher import ShadowDispatcher
        
        log_path = tmp_path / "shadow.jsonl"
        dispatcher = ShadowDispatcher(log_path=str(log_path), batch_size=1)
        
        run_async(dispatcher.dispatch(
            trace_id="persist_test",
            request={"id": 123},
            prod_model_id="v1",
            shadow_model_id="v2",
            prod_result={"score": 0.5},
            shadow_result={"score": 0.5},
        ))
        
        # Force flush
        run_async(dispatcher._flush())
        
        # Verify file exists and has content
        assert log_path.exists()
        content = log_path.read_text()
        assert "persist_test" in content

    def test_recent_comparisons_readable(self, tmp_path):
        """Test recent comparisons can be read back."""
        from backend.mlops.router.shadow_dispatcher import ShadowDispatcher
        
        log_path = tmp_path / "shadow.jsonl"
        dispatcher = ShadowDispatcher(log_path=str(log_path), batch_size=1)
        
        for i in range(5):
            run_async(dispatcher.dispatch(
                trace_id=f"read_test_{i}",
                request={},
                prod_model_id="v1",
                shadow_model_id="v2",
                prod_result={"n": i},
                shadow_result={"n": i},
            ))
        
        run_async(dispatcher._flush())
        
        recent = dispatcher.get_recent_comparisons(limit=3)
        
        assert len(recent) == 3
        # Most recent first
        assert "read_test_4" in recent[0].get("trace_id", "")


# ============================================================================
# State Store Tests
# ============================================================================

class TestStateStore:
    """Test scheduler state persistence."""

    def test_state_initialized(self, tmp_path):
        """Test state store initializes correctly."""
        from backend.mlops.scheduler.state_store import StateStore
        
        store = StateStore(storage_path=str(tmp_path / "state.json"))
        state = store.get_state()
        
        assert state.total_auto_retrains == 0
        assert state.last_retrain_at is None

    def test_record_retrain_updates_state(self, tmp_path):
        """Test recording retrain updates state correctly."""
        from backend.mlops.scheduler.state_store import StateStore
        
        store = StateStore(storage_path=str(tmp_path / "state.json"))
        
        store.record_retrain(
            run_id="run_001",
            trigger="auto",
            status="success",
        )
        
        state = store.get_state()
        
        assert state.total_auto_retrains == 1
        assert state.last_run_id == "run_001"
        assert state.last_status == "success"
        assert state.last_retrain_at is not None

    def test_state_persisted_across_instances(self, tmp_path):
        """Test state survives instance recreation."""
        from backend.mlops.scheduler.state_store import StateStore
        
        path = str(tmp_path / "state.json")
        
        # First instance
        store1 = StateStore(storage_path=path)
        store1.record_retrain("r1", "auto", "success")
        
        # Second instance - should load persisted state
        store2 = StateStore(storage_path=path)
        state = store2.get_state()
        
        assert state.total_auto_retrains == 1
        assert state.last_run_id == "r1"

    def test_record_block_updates_counts(self, tmp_path):
        """Test blocking records update counters."""
        from backend.mlops.scheduler.state_store import StateStore
        
        store = StateStore(storage_path=str(tmp_path / "state.json"))
        
        store.record_block("cooldown", "12h remaining")
        store.record_block("storm", "5 attempts in 6h")
        store.record_block("cooldown", "6h remaining")
        
        state = store.get_state()
        
        assert state.total_blocked_by_cooldown == 2
        assert state.total_blocked_by_storm == 1

    def test_recent_runs_filtered_by_time(self, tmp_path):
        """Test get_recent_runs filters by time window."""
        from backend.mlops.scheduler.state_store import StateStore
        
        store = StateStore(storage_path=str(tmp_path / "state.json"))
        
        # Record some runs
        for i in range(5):
            store.record_retrain(f"r{i}", "auto", "success")
        
        recent = store.get_recent_runs(hours=24)
        
        assert len(recent) == 5  # All within window


# ============================================================================
# Integration Tests
# ============================================================================

class TestEndToEndSchedulerCooldown:
    """End-to-end tests for scheduler with cooldown."""

    def test_scheduler_respects_cooldown(self, tmp_path, monkeypatch):
        """Test scheduler poll respects cooldown policy."""
        from backend.mlops.scheduler.retrain_scheduler import RetrainScheduler, SchedulerConfig
        from backend.mlops.scheduler.state_store import StateStore
        from backend.mlops.scheduler.policies import CooldownPolicy
        
        state_store = StateStore(storage_path=str(tmp_path / "state.json"))
        
        # Record a recent retrain
        state_store.record_retrain("prev", "auto", "success")
        
        cooldown = CooldownPolicy(min_interval_hours=24, enabled=True)
        config = SchedulerConfig(enabled=True)
        
        scheduler = RetrainScheduler(
            config=config,
            state_store=state_store,
            cooldown_policy=cooldown,
        )
        
        train_called = {"count": 0}
        
        async def mock_train(trigger):
            train_called["count"] += 1
            return {"status": "success"}
        
        scheduler.configure(
            metric_provider=lambda: {"drift_score": 0.9},  # Would trigger
            feedback_provider=lambda: {},
            train_callback=mock_train,
        )
        
        result = run_async(scheduler.check_and_trigger())
        
        # Should be blocked by cooldown
        assert result["blocked"] is True
        assert train_called["count"] == 0
        assert "cooldown" in result.get("reason", "").lower()


class TestEndToEndShadowRouting:
    """End-to-end tests for shadow routing."""

    def test_full_shadow_flow(self, tmp_path):
        """Test complete shadow routing flow from request to log."""
        from backend.mlops.router.traffic_manager import TrafficManager
        from backend.mlops.router.shadow_dispatcher import ShadowDispatcher
        
        log_path = tmp_path / "shadow.jsonl"
        
        # Setup
        dispatcher = ShadowDispatcher(log_path=str(log_path), batch_size=1)
        manager = TrafficManager()
        manager._shadow_dispatcher = dispatcher
        
        manager.set_prod_model("prod_v1")
        manager.enable_shadow("candidate_v2", sample_rate=1.0)
        
        # Mock inference functions
        async def mock_inference(model_id: str, request: dict):
            if model_id == "prod_v1":
                return {"score": 0.8, "label": "good"}
            else:
                return {"score": 0.75, "label": "good"}
        
        manager.configure(
            prod_inference=mock_inference,
            shadow_inference=mock_inference,
        )
        
        # Route request
        decision = manager.route(trace_id="e2e_test")
        
        assert decision.mirror_to_shadow is True
        
        # Simulate serving prod and mirroring to shadow
        prod_result = run_async(manager.serve_prod("e2e_test", {"text": "test"}))
        run_async(manager.mirror_to_shadow("e2e_test", {"text": "test"}, prod_result))
        
        # Flush and check log
        run_async(dispatcher._flush())
        
        content = log_path.read_text()
        assert "e2e_test" in content
        assert "score_diff" in content


# ============================================================================
# API Endpoint Tests
# ============================================================================

class TestMLOpsAPIEndpoints:
    """Test MLOps API endpoints."""

    def test_retrain_status_endpoint_exists(self):
        """Test /retrain/status endpoint is defined."""
        from backend.api.routers.mlops_router import router
        
        routes = [r.path for r in router.routes]
        assert "/retrain/status" in routes

    def test_shadow_endpoints_exist(self):
        """Test shadow management endpoints are defined."""
        from backend.api.routers.mlops_router import router
        
        routes = [r.path for r in router.routes]
        assert "/shadow/enable" in routes
        assert "/shadow/disable" in routes
        assert "/shadow/status" in routes
        assert "/shadow/evaluate" in routes


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

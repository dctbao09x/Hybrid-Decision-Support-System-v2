"""
Tests for the Failure Recovery & Rollback system.
==================================================
Covers: FailureCatalog, StageRetryExecutor, StageRollbackManager,
        RecoveryCheckpointManager, RecoveryManager.

Target: Stage fail ≠ kill whole run.  Recovery < 15 min.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════
#  1. FailureCatalog
# ═══════════════════════════════════════════════════════════════════════

class TestFailureCatalog:
    """Test failure classification taxonomy."""

    def setup_method(self):
        from backend.ops.recovery.failure_catalog import FailureCatalog
        self.catalog = FailureCatalog()

    def test_builtin_patterns_loaded(self):
        entries = self.catalog.list_entries()
        assert len(entries) >= 20, f"Expected ≥20 builtin patterns, got {len(entries)}"

    def test_classify_timeout(self):
        err = TimeoutError("Connection timed out after 30s")
        result = self.catalog.classify(err, stage="crawl", run_id="r1")
        assert result.category.value == "transient"
        assert result.retryable is True

    def test_classify_memory_error(self):
        err = MemoryError("Cannot allocate 2GB")
        result = self.catalog.classify(err, stage="score", run_id="r2")
        assert result.category.value == "resource"
        assert result.severity == "critical"

    def test_classify_type_error(self):
        err = TypeError("'NoneType' object is not subscriptable")
        result = self.catalog.classify(err, stage="validate", run_id="r3")
        assert result.category.value == "internal"
        assert result.retryable is False

    def test_classify_rate_limit(self):
        err = Exception("HTTP 429 Too Many Requests")
        result = self.catalog.classify(err, stage="crawl", run_id="r4")
        assert result.category.value == "external"
        assert result.retryable is True
        assert result.max_retries >= 3

    def test_classify_schema_mismatch(self):
        err = ValueError("pydantic validation error: field 'title' required")
        result = self.catalog.classify(err, stage="validate", run_id="r5")
        assert result.category.value == "data"
        assert result.recovery_strategy.value == "rollback_retry"

    def test_classify_unknown(self):
        err = RuntimeError("some completely unknown error XYZ123")
        result = self.catalog.classify(err, stage="crawl", run_id="r6")
        assert result.category.value == "unknown"
        assert result.retryable is False

    def test_classify_missing_secret(self):
        err = KeyError("missing secret API_KEY not found")
        result = self.catalog.classify(err, stage="crawl", run_id="r7")
        # KeyError matches "KeyError" pattern (internal)
        assert result.category.value in ("config", "internal")
        assert result.retryable is False

    def test_classify_captcha(self):
        err = Exception("Cloudflare challenge detected, access denied")
        result = self.catalog.classify(err, stage="crawl", run_id="r8")
        assert result.category.value == "external"
        assert result.retryable is False
        assert result.recovery_strategy.value == "skip_stage"

    def test_classify_disk_full(self):
        err = OSError("No space left on device")
        result = self.catalog.classify(err, stage="validate", run_id="r9")
        assert result.category.value == "resource"
        assert result.recovery_strategy.value == "abort"

    def test_custom_pattern_registration(self):
        from backend.ops.recovery.failure_catalog import (
            FailureCategory,
            RecoveryStrategy,
        )
        self.catalog.register_pattern(
            name="custom_api_error",
            category=FailureCategory.EXTERNAL,
            pattern=r"CustomAPIError",
            retryable=True,
            max_retries=2,
            recovery_strategy=RecoveryStrategy.RETRY,
            severity="high",
        )
        err = Exception("CustomAPIError: service unavailable")
        result = self.catalog.classify(err, stage="crawl", run_id="r10")
        assert result.entry.name == "custom_api_error"
        assert result.category.value == "external"

    def test_classify_to_dict(self):
        err = TimeoutError("timed out")
        result = self.catalog.classify(err, stage="crawl", run_id="r11")
        d = result.to_dict()
        assert "error_type" in d
        assert d["stage"] == "crawl"
        assert d["run_id"] == "r11"

    def test_record_failure_history(self):
        err = TimeoutError("timed out")
        classified = self.catalog.classify(err, stage="crawl", run_id="r12")
        record = self.catalog.record_failure(
            "r12", "crawl", classified, recovered=True, recovery_duration=5.0
        )
        assert record.recovered is True
        history = self.catalog.get_history()
        assert len(history) >= 1

    def test_get_stats(self):
        stats = self.catalog.get_stats()
        assert "total_failures" in stats
        assert "recovery_rate" in stats

    def test_import_error_classified(self):
        err = ImportError("No module named 'nonexistent'")
        result = self.catalog.classify(err, stage="score", run_id="r13")
        assert result.category.value == "config"
        assert result.retryable is False
        assert result.recovery_strategy.value == "abort"

    def test_quality_gate_classified(self):
        err = Exception("quality gate BLOCKED pipeline: drift block")
        result = self.catalog.classify(err, stage="validate", run_id="r14")
        assert result.category.value == "data"
        assert result.recovery_strategy.value == "rollback_retry"

    def test_browser_crash_classified(self):
        err = Exception("Target closed: browser crash detected")
        result = self.catalog.classify(err, stage="crawl", run_id="r15")
        assert result.category.value == "resource"
        assert result.retryable is True


# ═══════════════════════════════════════════════════════════════════════
#  2. RecoveryCheckpointManager
# ═══════════════════════════════════════════════════════════════════════

class TestRecoveryCheckpoint:
    """Test checkpoint lifecycle and safe-rerun detection."""

    def setup_method(self):
        from backend.ops.recovery.stage_checkpoint import RecoveryCheckpointManager
        self.tmp_dir = Path("backend/data/_test_recovery_cp")
        self.mgr = RecoveryCheckpointManager(base_dir=self.tmp_dir)

    def teardown_method(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_begin_stage(self):
        cp = self.mgr.begin_stage("run1", "crawl", input_data=["a", "b"])
        assert cp.status == "running"
        assert cp.records_in == 2
        assert cp.input_hash != ""

    def test_complete_stage(self):
        self.mgr.begin_stage("run1", "crawl")
        cp = self.mgr.complete_stage("run1", "crawl", output_data=[1, 2, 3])
        assert cp.status == "completed"
        assert cp.records_out == 3
        assert cp.output_hash != ""

    def test_fail_stage(self):
        self.mgr.begin_stage("run1", "validate")
        cp = self.mgr.fail_stage("run1", "validate", ValueError("bad data"))
        assert cp.status == "failed"
        assert "ValueError" in cp.error

    def test_skip_stage(self):
        cp = self.mgr.skip_stage("run1", "explain", reason="non-critical")
        assert cp.status == "skipped"
        assert cp.metadata["skip_reason"] == "non-critical"

    def test_resume_point(self):
        self.mgr.begin_stage("run1", "crawl")
        self.mgr.complete_stage("run1", "crawl")
        self.mgr.begin_stage("run1", "validate")
        self.mgr.fail_stage("run1", "validate", Exception("err"))
        resume = self.mgr.get_resume_point("run1")
        assert resume == "validate"

    def test_resume_point_all_complete(self):
        for stage in ["crawl", "validate", "score", "explain"]:
            self.mgr.begin_stage("run2", stage)
            self.mgr.complete_stage("run2", stage)
        assert self.mgr.get_resume_point("run2") is None

    def test_safe_rerun_same_input(self):
        data = {"a": 1, "b": 2}
        self.mgr.begin_stage("run1", "crawl", input_data=data)
        self.mgr.complete_stage("run1", "crawl")
        # Same input → NOT safe to rerun (already done)
        assert self.mgr.is_safe_rerun("run1", "crawl", input_data=data) is False

    def test_safe_rerun_changed_input(self):
        self.mgr.begin_stage("run1", "crawl", input_data={"a": 1})
        self.mgr.complete_stage("run1", "crawl")
        # Different input → safe to rerun
        assert self.mgr.is_safe_rerun("run1", "crawl", input_data={"a": 2}) is True

    def test_safe_rerun_never_ran(self):
        assert self.mgr.is_safe_rerun("newrun", "crawl") is True

    def test_persistence_and_reload(self):
        self.mgr.begin_stage("run1", "crawl")
        self.mgr.complete_stage("run1", "crawl", output_data=[1])
        # Create new manager pointing to same dir
        from backend.ops.recovery.stage_checkpoint import RecoveryCheckpointManager
        mgr2 = RecoveryCheckpointManager(base_dir=self.tmp_dir)
        status = mgr2.get_run_status("run1")
        assert status is not None
        assert status["stages"]["crawl"]["status"] == "completed"

    def test_get_stage_attempt(self):
        self.mgr.begin_stage("run1", "crawl", attempt=1)
        self.mgr.fail_stage("run1", "crawl", Exception("err"))
        self.mgr.begin_stage("run1", "crawl", attempt=2)
        assert self.mgr.get_stage_attempt("run1", "crawl") == 2

    def test_finalize_run(self):
        self.mgr.begin_stage("run1", "crawl")
        self.mgr.complete_stage("run1", "crawl")
        self.mgr.finalize_run("run1", status="completed")
        status = self.mgr.get_run_status("run1")
        assert status["status"] == "completed"


# ═══════════════════════════════════════════════════════════════════════
#  3. StageRetryExecutor
# ═══════════════════════════════════════════════════════════════════════

class TestStageRetry:
    """Test failure-aware retry with backoff."""

    def setup_method(self):
        from backend.ops.recovery.failure_catalog import FailureCatalog
        from backend.ops.recovery.stage_retry import StageRetryExecutor
        self.catalog = FailureCatalog()
        self.executor = StageRetryExecutor(catalog=self.catalog)

    @pytest.mark.asyncio
    async def test_success_first_try(self):
        async def ok():
            return {"data": 42}

        result = await self.executor.execute("crawl", ok, run_id="r1")
        assert result.success is True
        assert result.attempts == 1
        assert result.result["data"] == 42

    @pytest.mark.asyncio
    async def test_retry_on_transient(self):
        call_count = 0
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TimeoutError("timed out")
            return {"ok": True}

        result = await self.executor.execute(
            "crawl", flaky, run_id="r2", max_retries_override=3
        )
        assert result.success is True
        assert result.attempts == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_internal(self):
        async def buggy():
            raise TypeError("'NoneType' object is not subscriptable")

        result = await self.executor.execute("score", buggy, run_id="r3")
        assert result.success is False
        assert result.attempts == 1  # no retry for internal errors
        assert result.classified.category.value == "internal"

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        async def always_fail():
            raise TimeoutError("timed out")

        result = await self.executor.execute(
            "crawl", always_fail, run_id="r4", max_retries_override=1
        )
        assert result.success is False
        assert result.attempts == 2  # 1 initial + 1 retry
        assert result.total_delay > 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens(self):
        from backend.ops.recovery.stage_retry import StageRetryPolicy
        self.executor.set_policy("test_stage", StageRetryPolicy(
            stage="test_stage",
            max_retries=0,
            circuit_threshold=2,
            circuit_recovery=999,  # won't recover during test
        ))

        async def fail():
            raise TimeoutError("t")

        # Trip the circuit
        await self.executor.execute("test_stage", fail, run_id="r5a")
        await self.executor.execute("test_stage", fail, run_id="r5b")

        # Now circuit should be open
        result = await self.executor.execute("test_stage", fail, run_id="r5c")
        assert result.success is False
        assert result.circuit_opened is True

    @pytest.mark.asyncio
    async def test_budget_exhaustion(self):
        from backend.ops.recovery.stage_retry import StageRetryPolicy
        self.executor.set_policy("budget_stage", StageRetryPolicy(
            stage="budget_stage",
            max_retries=1,
            budget_max_retries=2,
            budget_window=900,
            base_delay=0.01,
        ))

        async def fail():
            raise TimeoutError("t")

        # Exhaust budget
        await self.executor.execute("budget_stage", fail, run_id="r6a")
        await self.executor.execute("budget_stage", fail, run_id="r6b")
        result = await self.executor.execute("budget_stage", fail, run_id="r6c")
        # Should hit budget at some point
        assert result.success is False

    def test_retry_stats(self):
        stats = self.executor.get_retry_stats()
        assert "total_executions" in stats
        assert "by_stage" in stats

    def test_telemetry(self):
        telemetry = self.executor.get_telemetry()
        assert isinstance(telemetry, list)


# ═══════════════════════════════════════════════════════════════════════
#  4. StageRollbackManager
# ═══════════════════════════════════════════════════════════════════════

class TestStageRollback:
    """Test failure-aware rollback with validation."""

    def setup_method(self):
        from backend.ops.recovery.stage_rollback import StageRollbackManager
        self.tmp_dir = Path("backend/data/_test_rollback")
        self.mgr = StageRollbackManager(
            checkpoint_dir=self.tmp_dir / "checkpoints",
            data_dir=self.tmp_dir / "market",
            log_dir=self.tmp_dir / "logs",
        )
        (self.tmp_dir / "market").mkdir(parents=True, exist_ok=True)

    def teardown_method(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_create_plan_transient(self):
        from backend.ops.recovery.failure_catalog import (
            ClassifiedFailure, FailureCategory, FailureEntry, RecoveryStrategy,
        )
        classified = ClassifiedFailure(
            error=TimeoutError("timeout"),
            category=FailureCategory.TRANSIENT,
            entry=FailureEntry(
                name="timeout", category=FailureCategory.TRANSIENT,
                pattern="timeout", retryable=True,
                recovery_strategy=RecoveryStrategy.RETRY,
            ),
            stage="crawl", run_id="r1",
        )
        plan = self.mgr.create_plan("r1", "crawl", classified)
        # Transient → no rollback steps
        assert len(plan.steps) == 0

    def test_create_plan_data_error(self):
        from backend.ops.recovery.failure_catalog import (
            ClassifiedFailure, FailureCategory, FailureEntry, RecoveryStrategy,
        )
        classified = ClassifiedFailure(
            error=ValueError("schema mismatch"),
            category=FailureCategory.DATA,
            entry=FailureEntry(
                name="schema", category=FailureCategory.DATA,
                pattern="schema", retryable=False,
                recovery_strategy=RecoveryStrategy.ROLLBACK_AND_RETRY,
            ),
            stage="validate", run_id="r2",
        )
        plan = self.mgr.create_plan("r2", "validate", classified)
        # Should have rollback steps for validate, score, explain
        assert len(plan.steps) >= 4  # revert + clear for each affected stage
        assert plan.failure_category == "data"

    def test_create_plan_resource_error(self):
        from backend.ops.recovery.failure_catalog import (
            ClassifiedFailure, FailureCategory, FailureEntry, RecoveryStrategy,
        )
        classified = ClassifiedFailure(
            error=MemoryError("OOM"),
            category=FailureCategory.RESOURCE,
            entry=FailureEntry(
                name="oom", category=FailureCategory.RESOURCE,
                pattern="OOM", retryable=True,
                recovery_strategy=RecoveryStrategy.ROLLBACK_AND_RETRY,
            ),
            stage="score", run_id="r3",
        )
        plan = self.mgr.create_plan("r3", "score", classified)
        # Should have cleanup steps + rollback
        cleanup_steps = [s for s in plan.steps if s.action_type == "cleanup_resource"]
        assert len(cleanup_steps) >= 1
        assert plan.failure_category == "resource"

    @pytest.mark.asyncio
    async def test_execute_plan(self):
        from backend.ops.recovery.failure_catalog import (
            ClassifiedFailure, FailureCategory, FailureEntry, RecoveryStrategy,
        )
        classified = ClassifiedFailure(
            error=ValueError("schema"),
            category=FailureCategory.DATA,
            entry=FailureEntry(
                name="schema", category=FailureCategory.DATA,
                pattern="schema", retryable=False,
                recovery_strategy=RecoveryStrategy.ROLLBACK_AND_RETRY,
            ),
            stage="validate", run_id="r4",
        )
        plan = self.mgr.create_plan("r4", "validate", classified)
        result = await self.mgr.execute_plan(plan, validate_after=True)
        assert "steps_executed" in result
        assert "validation" in result

    @pytest.mark.asyncio
    async def test_execute_empty_plan(self):
        from backend.ops.recovery.stage_rollback import RollbackPlan
        plan = RollbackPlan(
            run_id="r5", failed_stage="crawl",
            reason="transient", failure_category="transient",
            recovery_strategy="retry",
        )
        result = await self.mgr.execute_plan(plan, validate_after=False)
        assert result["success"] is True
        assert result["steps_executed"] == 0

    def test_rollback_stats(self):
        stats = self.mgr.get_stats()
        assert "total_rollbacks" in stats

    def test_plan_to_dict(self):
        from backend.ops.recovery.stage_rollback import RollbackPlan, RollbackStep
        plan = RollbackPlan(
            run_id="r6", failed_stage="score",
            reason="test", failure_category="data",
            recovery_strategy="rollback_retry",
        )
        plan.add_step(RollbackStep(
            name="test_step", action_type="revert_data",
            target="score", description="Test step",
        ))
        d = plan.to_dict()
        assert d["steps_total"] == 1
        assert d["failed_stage"] == "score"


# ═══════════════════════════════════════════════════════════════════════
#  5. RecoveryManager (integration)
# ═══════════════════════════════════════════════════════════════════════

class TestRecoveryManager:
    """Test the central recovery orchestrator."""

    def setup_method(self):
        from backend.ops.recovery.recovery_manager import RecoveryManager
        from backend.ops.recovery.failure_catalog import FailureCatalog
        from backend.ops.recovery.stage_retry import StageRetryExecutor, StageRetryPolicy
        from backend.ops.recovery.stage_rollback import StageRollbackManager
        from backend.ops.recovery.stage_checkpoint import RecoveryCheckpointManager

        self.tmp_dir = Path("backend/data/_test_recovery_mgr")
        self.catalog = FailureCatalog()
        self.retry = StageRetryExecutor(catalog=self.catalog)
        # Shorten delays for testing
        for stage in ["crawl", "validate", "score", "explain"]:
            self.retry.set_policy(stage, StageRetryPolicy(
                stage=stage, max_retries=2, base_delay=0.01, max_delay=0.05,
                jitter=False,
            ))
        self.rollback = StageRollbackManager(
            checkpoint_dir=self.tmp_dir / "cp",
            data_dir=self.tmp_dir / "data",
            log_dir=self.tmp_dir / "logs",
        )
        (self.tmp_dir / "data").mkdir(parents=True, exist_ok=True)
        self.checkpoint = RecoveryCheckpointManager(
            base_dir=self.tmp_dir / "rcp",
        )
        self.mgr = RecoveryManager(
            catalog=self.catalog,
            retry_executor=self.retry,
            rollback_manager=self.rollback,
            checkpoint_manager=self.checkpoint,
        )

    def teardown_method(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_execute_stage_success(self):
        async def ok(run_id):
            return {"records": 10}

        result = await self.mgr.execute_stage(
            "run1", "crawl", ok, "run1", critical=True,
        )
        assert result.success is True
        assert result.action == "completed"
        assert result.result["records"] == 10

    @pytest.mark.asyncio
    async def test_execute_stage_recover_after_retry(self):
        call_count = 0
        async def flaky(run_id):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise TimeoutError("network timeout")
            return {"ok": True}

        result = await self.mgr.execute_stage(
            "run2", "crawl", flaky, "run2", critical=True,
        )
        assert result.success is True
        assert result.action == "recovered"
        assert result.attempts >= 2

    @pytest.mark.asyncio
    async def test_execute_stage_skip_noncritical(self):
        async def fail(run_id):
            raise Exception("Cloudflare challenge detected")

        result = await self.mgr.execute_stage(
            "run3", "explain", fail, "run3",
            critical=False,
        )
        assert result.success is True
        assert result.action == "skipped"

    @pytest.mark.asyncio
    async def test_execute_stage_abort_critical(self):
        async def fail(run_id):
            raise TypeError("'NoneType' not iterable")

        result = await self.mgr.execute_stage(
            "run4", "crawl", fail, "run4", critical=True,
        )
        assert result.success is False
        assert result.action == "failed"

    @pytest.mark.asyncio
    async def test_stage_fail_does_not_kill_run(self):
        """Core acceptance: stage fail ≠ kill whole run."""
        call_log = []

        async def crawl_ok(*args, **kwargs):
            call_log.append("crawl")
            return {"total_records": 5}

        async def validate_ok(*args, **kwargs):
            call_log.append("validate")
            return [{"job": "dev"}]

        async def score_ok(*args, **kwargs):
            call_log.append("score")
            return [{"career": "dev", "score": 0.8}]

        async def explain_fail(*args, **kwargs):
            call_log.append("explain_attempt")
            raise Exception("Cloudflare challenge detected — cannot explain")

        # Execute pipeline where explain (non-critical) fails
        result = await self.mgr.execute_pipeline(
            "run_skip",
            stage_funcs={
                "crawl": crawl_ok,
                "validate": validate_ok,
                "score": score_ok,
                "explain": explain_fail,
            },
        )
        # Pipeline should complete (partial) — not crash
        assert result.status in ("completed", "partial")
        # All critical stages ran
        assert "crawl" in result.completed_stages
        assert "validate" in result.completed_stages
        assert "score" in result.completed_stages

    @pytest.mark.asyncio
    async def test_critical_stage_fail_stops_pipeline(self):
        """Critical stage failure stops subsequent stages."""
        async def crawl_ok(*args, **kwargs):
            return {"total_records": 5}

        async def validate_fail(*args, **kwargs):
            raise TypeError("bug in validate")

        async def score_ok(*args, **kwargs):
            return [{"score": 1}]

        result = await self.mgr.execute_pipeline(
            "run_fail",
            stage_funcs={
                "crawl": crawl_ok,
                "validate": validate_fail,
                "score": score_ok,
            },
            stage_order=["crawl", "validate", "score"],
        )
        assert result.status in ("partial", "failed")
        assert "crawl" in result.completed_stages
        assert "validate" in result.failed_stages
        # Score should NOT have run
        assert "score" not in result.completed_stages

    @pytest.mark.asyncio
    async def test_idempotent_rerun(self):
        """Safe rerun: stage with same input is skipped."""
        input_data = {"sites": ["a"]}

        async def stage_func(run_id):
            return {"done": True}

        # First run — should complete
        r1 = await self.mgr.execute_stage(
            "run_idem", "crawl", stage_func, "run_idem",
            input_data=input_data,
        )
        assert r1.action == "completed"

        # Second run with same input — should skip
        r2 = await self.mgr.execute_stage(
            "run_idem", "crawl", stage_func, "run_idem",
            input_data=input_data,
        )
        assert r2.action == "skipped"

    @pytest.mark.asyncio
    async def test_time_budget_enforcement(self):
        """Recovery budget: execute_stage checks time."""
        from backend.ops.recovery import recovery_manager
        old_max = recovery_manager.MAX_RUN_RECOVERY_SECONDS
        recovery_manager.MAX_RUN_RECOVERY_SECONDS = 0.001

        # Record a start time in the past
        self.mgr._run_start_times["run_budget"] = time.time() - 1000

        async def ok(run_id):
            return {}

        result = await self.mgr.execute_stage(
            "run_budget", "crawl", ok, "run_budget",
        )
        assert result.action == "aborted"
        assert "budget" in result.skip_reason.lower()

        recovery_manager.MAX_RUN_RECOVERY_SECONDS = old_max

    def test_get_stats(self):
        stats = self.mgr.get_stats()
        assert "catalog" in stats
        assert "retry" in stats
        assert "rollback" in stats

    def test_get_failure_report(self):
        report = self.mgr.get_failure_report()
        assert "catalog_entries" in report
        assert report["catalog_entries"] >= 20
        assert "stage_criticality" in report

    def test_recovery_log(self):
        log = self.mgr.get_recovery_log()
        assert isinstance(log, list)


# ═══════════════════════════════════════════════════════════════════════
#  6. OpsHub Integration
# ═══════════════════════════════════════════════════════════════════════

class TestOpsHubRecovery:
    """Test OpsHub wiring for recovery subsystem."""

    def test_opshub_has_recovery(self):
        from backend.ops.integration import OpsHub
        hub = OpsHub()
        assert hub.recovery is not None
        from backend.ops.recovery.recovery_manager import RecoveryManager
        assert isinstance(hub.recovery, RecoveryManager)

    def test_opshub_has_failure_catalog(self):
        from backend.ops.integration import OpsHub
        hub = OpsHub()
        assert hub.failure_catalog is not None
        from backend.ops.recovery.failure_catalog import FailureCatalog
        assert isinstance(hub.failure_catalog, FailureCatalog)

    def test_opshub_recovery_singleton(self):
        from backend.ops.integration import OpsHub
        hub = OpsHub()
        r1 = hub.recovery
        r2 = hub.recovery
        assert r1 is r2

    def test_opshub_recovery_has_catalog(self):
        from backend.ops.integration import OpsHub
        hub = OpsHub()
        # Recovery's catalog should be the same as hub's catalog
        assert hub.recovery.catalog is hub.failure_catalog


# ═══════════════════════════════════════════════════════════════════════
#  7. StageRetryPolicy
# ═══════════════════════════════════════════════════════════════════════

class TestStageRetryPolicy:
    """Test per-stage retry policy configuration."""

    def test_exponential_backoff(self):
        from backend.ops.recovery.stage_retry import StageRetryPolicy
        from backend.ops.recovery.failure_catalog import FailureCategory
        policy = StageRetryPolicy(
            stage="test", base_delay=1.0, max_delay=100.0, jitter=False
        )
        d0 = policy.get_delay(0)
        d1 = policy.get_delay(1)
        d2 = policy.get_delay(2)
        assert d0 == 1.0   # 1 * 2^0
        assert d1 == 2.0   # 1 * 2^1
        assert d2 == 4.0   # 1 * 2^2

    def test_max_delay_cap(self):
        from backend.ops.recovery.stage_retry import StageRetryPolicy
        policy = StageRetryPolicy(
            stage="test", base_delay=10.0, max_delay=20.0, jitter=False
        )
        d5 = policy.get_delay(5)
        assert d5 <= 20.0

    def test_resource_cooldown(self):
        from backend.ops.recovery.stage_retry import StageRetryPolicy
        from backend.ops.recovery.failure_catalog import FailureCategory
        policy = StageRetryPolicy(
            stage="test", base_delay=1.0, resource_cooldown=30.0, jitter=False
        )
        d = policy.get_delay(0, FailureCategory.RESOURCE)
        assert d >= 30.0

    def test_external_minimum(self):
        from backend.ops.recovery.stage_retry import StageRetryPolicy
        from backend.ops.recovery.failure_catalog import FailureCategory
        policy = StageRetryPolicy(
            stage="test", base_delay=1.0, jitter=False
        )
        d = policy.get_delay(0, FailureCategory.EXTERNAL)
        assert d >= 10.0

    def test_default_stage_policies_exist(self):
        from backend.ops.recovery.stage_retry import DEFAULT_STAGE_POLICIES
        assert "crawl" in DEFAULT_STAGE_POLICIES
        assert "validate" in DEFAULT_STAGE_POLICIES
        assert "score" in DEFAULT_STAGE_POLICIES
        assert "explain" in DEFAULT_STAGE_POLICIES
        # Crawl gets more retries
        assert DEFAULT_STAGE_POLICIES["crawl"].max_retries >= DEFAULT_STAGE_POLICIES["explain"].max_retries


# ═══════════════════════════════════════════════════════════════════════
#  8. RetryBudget
# ═══════════════════════════════════════════════════════════════════════

class TestRetryBudget:
    """Test retry budget tracking."""

    def test_consume_within_budget(self):
        from backend.ops.recovery.stage_retry import RetryBudget
        budget = RetryBudget(max_retries=3, window_seconds=60)
        assert budget.consume() is True
        assert budget.consume() is True
        assert budget.consume() is True
        assert budget.consume() is False  # exhausted
        assert budget.remaining == 0

    def test_budget_window_expiry(self):
        from backend.ops.recovery.stage_retry import RetryBudget
        budget = RetryBudget(max_retries=1, window_seconds=0.01)
        assert budget.consume() is True
        time.sleep(0.02)  # wait for window to expire
        assert budget.consume() is True  # budget refreshed

    def test_budget_to_dict(self):
        from backend.ops.recovery.stage_retry import RetryBudget
        budget = RetryBudget(max_retries=5)
        d = budget.to_dict()
        assert d["remaining"] == 5
        assert d["max"] == 5

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.mlops.governance import RetrainApprovalStore, RetrainAuditLogger
from backend.mlops.lifecycle import MLOpsManager
from backend.mlops.scheduler.policies import CooldownPolicy
from backend.mlops.scheduler.retrain_scheduler import RetrainScheduler, SchedulerConfig
from backend.mlops.scheduler.state_store import StateStore


def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _isolated_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MLOpsManager:
    monkeypatch.setenv("MLOPS_SCHEDULER_STATE_BACKEND", "json")
    manager = MLOpsManager()

    manager._runs_path = tmp_path / "runs.jsonl"
    manager._runs_path.parent.mkdir(parents=True, exist_ok=True)
    manager._state_store = StateStore(storage_path=str(tmp_path / "scheduler_state.json"))
    manager._approvals = RetrainApprovalStore(path=str(tmp_path / "approvals.json"))
    manager._audit = RetrainAuditLogger(path=str(tmp_path / "audit.jsonl"))
    return manager


def test_manual_train_requires_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MLOPS_MANUAL_RETRAIN_APPROVAL_REQUIRED", "true")
    manager = _isolated_manager(tmp_path=tmp_path, monkeypatch=monkeypatch)

    result = run_async(manager.train(trigger="manual", source="feedback", requested_by="operator_a"))

    assert result["status"] == "blocked"
    assert result["stage"] == "approval"
    assert "approval" in result["reason"].lower()


def test_manual_train_with_approval_reaches_dataset_quality_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MLOPS_MANUAL_RETRAIN_APPROVAL_REQUIRED", "true")
    monkeypatch.setenv("MLOPS_RETRAIN_MIN_DATASET_ROWS", "10")
    monkeypatch.setenv("MLOPS_RETRAIN_MIN_AVG_QUALITY", "0.8")
    monkeypatch.setenv("MLOPS_RETRAIN_MIN_LABEL_CLASSES", "2")

    manager = _isolated_manager(tmp_path=tmp_path, monkeypatch=monkeypatch)

    approval = manager.request_manual_retrain_approval(
        requested_by="operator_a",
        reason="Need manual retrain for incident",
        trigger="manual",
        allow_cooldown_bypass=False,
    )
    manager.approve_manual_retrain(
        approval_id=approval["approval_id"],
        approver_id="admin_b",
        approver_comment="approved",
    )

    async def _fake_build(*args, **kwargs):
        return SimpleNamespace(
            dataset_id="ds_low_quality",
            source="feedback",
            hash="hash-low",
            kb_version="kb1",
            created_at="2026-01-01T00:00:00+00:00",
            size=2,
            path=str(tmp_path / "dataset.csv"),
            avg_quality_score=0.3,
            min_quality_score=0.2,
            label_classes=1,
            to_dict=lambda: {
                "dataset_id": "ds_low_quality",
                "size": 2,
                "avg_quality_score": 0.3,
                "label_classes": 1,
            },
        )

    monkeypatch.setattr(manager._datasets, "build_immutable_from_training_candidates", _fake_build)

    result = run_async(
        manager.train(
            trigger="manual",
            source="feedback",
            approval_id=approval["approval_id"],
            requested_by="operator_a",
        )
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "dataset_quality"
    assert "dataset quality" in result["reason"].lower()


def test_static_fallback_removed_from_retraining_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MLOPS_MANUAL_RETRAIN_APPROVAL_REQUIRED", "false")
    manager = _isolated_manager(tmp_path=tmp_path, monkeypatch=monkeypatch)

    async def _no_candidates(*args, **kwargs):
        raise ValueError("No eligible training candidates")

    monkeypatch.setattr(manager._datasets, "build_immutable_from_training_candidates", _no_candidates)

    result = run_async(manager.train(trigger="auto", source="feedback", requested_by="scheduler"))

    assert result["status"] == "failed"
    assert "No eligible training candidates" in result["error"]
    assert "static fallback" not in result["error"].lower()


def test_scheduler_validation_failure_updates_failure_rate(tmp_path: Path) -> None:
    state_store = StateStore(storage_path=str(tmp_path / "scheduler.json"))
    scheduler = RetrainScheduler(
        config=SchedulerConfig(enabled=True, max_consecutive_failures=3),
        state_store=state_store,
        cooldown_policy=CooldownPolicy(min_interval_hours=0, enabled=False),
    )

    async def _train_ok(trigger: str):
        return {"status": "success", "trigger": trigger}

    def _bad_metrics():
        raise RuntimeError("metrics unavailable")

    scheduler.configure(
        metric_provider=_bad_metrics,
        feedback_provider=lambda: {"negative_feedback_rate": 0.05},
        train_callback=_train_ok,
    )

    result = run_async(scheduler.check_and_trigger())
    status = scheduler.get_status()

    assert result["blocked"] is True
    assert "validation failed" in (result.get("reason") or "").lower()
    assert status["total_scheduler_failures"] >= 1
    assert status["scheduler_failure_rate"] > 0.0


def test_bypass_attempt_metric_is_tracked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MLOPS_MANUAL_RETRAIN_APPROVAL_REQUIRED", "true")
    monkeypatch.setenv("MLOPS_COOLDOWN_BYPASS_REQUIRES_APPROVAL", "true")
    manager = _isolated_manager(tmp_path=tmp_path, monkeypatch=monkeypatch)

    result = run_async(
        manager.train(
            trigger="manual",
            source="feedback",
            bypass_cooldown=True,
            requested_by="operator_a",
        )
    )
    metrics = manager.get_governance_metrics()

    assert result["status"] == "blocked"
    assert metrics["retrain_trigger_count"] >= 1.0
    assert metrics["bypass_attempt_rate"] > 0.0

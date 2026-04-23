from __future__ import annotations

from backend.mlops.lifecycle import MLOpsManager


def test_train_fail(monkeypatch):
    manager = MLOpsManager()

    async def _boom(*args, **kwargs):
        raise ValueError("dataset unavailable")

    monkeypatch.setattr(manager._datasets, "build_immutable_from_training_candidates", _boom)

    import asyncio
    result = asyncio.run(manager.train(trigger="test", source="feedback"))
    assert result["status"] == "failed"


def test_validate_block(monkeypatch):
    manager = MLOpsManager()

    def _staging():
        return {
            "model_id": "m1",
            "version": "v999",
            "metrics": {"accuracy": {"mean": 0.1}, "f1": {"mean": 0.1}},
            "validation": {"passed": False},
            "status": "staging",
        }

    monkeypatch.setattr(manager._registry, "current_staging", _staging)
    result = manager.validate()
    assert result["status"] == "failed"


def test_canary_abort(monkeypatch):
    manager = MLOpsManager()

    def _get(model_id):
        return {
            "model_id": model_id,
            "version": "v10",
            "validation": {"passed": True},
            "status": "staging",
        }

    monkeypatch.setattr(manager._registry, "get", _get)
    result = manager.deploy(model_id="m10", strategy="canary", canary_ratio=0.2)
    assert result["status"] == "failed"


def test_auto_rollback(monkeypatch):
    manager = MLOpsManager()

    def _monitor_alert():
        return {
            "accuracy_live": 0.8,
            "data_drift": 0.9,
            "concept_drift": 0.8,
            "latency": 999,
            "cost": 1.0,
            "error_rate": 0.2,
            "accuracy_drop": 0.2,
            "drift_score": 0.8,
            "thresholds": {"error_rate": 0.03, "accuracy_drop": 0.05, "drift_score": 0.25},
            "alert": True,
            "timestamp": "now",
        }

    called = {"n": 0}

    def _rollback(reason="auto", target_model_id=None):
        called["n"] += 1
        return {"status": "success", "reason": reason}

    monkeypatch.setattr(manager, "monitor", _monitor_alert)
    monkeypatch.setattr(manager, "rollback", _rollback)

    result = manager.maybe_auto_rollback()
    assert result["status"] == "success"
    assert called["n"] == 1

# backend/retrain/__init__.py
"""
Auto-Retrain Module
===================

Phase 3B: Auto-Retraining (A)

Components:
  - trigger_engine.py    — Detect when retraining is needed
  - dataset_builder.py   — Merge online + offline data
  - trainer.py           — Reuse evaluation pipeline
  - validator.py         — Phase 1 + 2 validation
  - model_registry.py    — Version management
  - deploy_manager.py    — Canary deployment + rollback

Triggers:
  - Drift ≥ threshold
  - Regression FAIL
  - Dataset change > X%
  - Scheduled (optional)
"""

from importlib import import_module

__all__ = [
    "TriggerEngine",
    "TriggerResult",
    "TriggerType",
    "DatasetBuilder",
    "RetrainTrainer",
    "TrainResult",
    "RetrainValidator",
    "ValidationResult",
    "ModelRegistry",
    "DeployManager",
    "DeployResult",
]

_SYMBOL_TO_MODULE = {
    "TriggerEngine": "backend.retrain.trigger_engine",
    "TriggerResult": "backend.retrain.trigger_engine",
    "TriggerType": "backend.retrain.trigger_engine",
    "DatasetBuilder": "backend.retrain.dataset_builder",
    "RetrainTrainer": "backend.retrain.trainer",
    "TrainResult": "backend.retrain.trainer",
    "RetrainValidator": "backend.retrain.validator",
    "ValidationResult": "backend.retrain.validator",
    "ModelRegistry": "backend.retrain.model_registry",
    "DeployManager": "backend.retrain.deploy_manager",
    "DeployResult": "backend.retrain.deploy_manager",
}

def __getattr__(name: str):
    module_path = _SYMBOL_TO_MODULE.get(name)
    if not module_path:
        raise AttributeError(f"module 'backend.retrain' has no attribute {name!r}")
    module = import_module(module_path)
    return getattr(module, name)

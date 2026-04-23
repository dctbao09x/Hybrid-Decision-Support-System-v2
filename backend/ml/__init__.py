# backend/ml/__init__.py
"""
ML Model Governance Package
============================

Provides controlled model registry and retrain job tracking so that
ML operations are no longer uncontrolled background processes.

Exports:
  ModelRegistry   – JSONL-backed versioned model store
  ModelRecord     – Per-model snapshot (version, status, metrics)
  ModelStatus     – Enum of model lifecycle states
  RetrainJobLog   – Persistent retrain job tracker
  RetrainJob      – Single retrain job record
"""

from backend.ml.model_registry import (
    ModelRegistry,
    ModelRecord,
    ModelStatus,
    get_model_registry,
)
from backend.ml.retrain_job_log import (
    RetrainJobLog,
    RetrainJob,
    get_retrain_job_log,
)

__all__ = [
    "ModelRegistry",
    "ModelRecord",
    "ModelStatus",
    "get_model_registry",
    "RetrainJobLog",
    "RetrainJob",
    "get_retrain_job_log",
]

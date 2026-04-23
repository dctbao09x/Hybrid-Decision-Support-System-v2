# backend/inference/__init__.py
"""
Online Inference Module
=======================

Phase 3A: Online Inference (C)

Components:
  - model_loader.py      — Load/manage active model
  - ab_router.py         — A/B testing traffic routing
  - feedback_collector.py — Capture prediction + outcome
  - metric_tracker.py    — Latency, error rate, accuracy
  - api_server.py        — FastAPI endpoints

Endpoints:
  - POST /predict        — Get career prediction
  - POST /feedback       — Submit outcome feedback
  - GET  /health         — Health check
  - GET  /metrics        — Inference metrics
"""

from importlib import import_module

__all__ = [
    "ModelLoader",
    "LoadedModel",
    "ABRouter",
    "RoutingDecision",
    "FeedbackCollector",
    "FeedbackRecord",
    "MetricTracker",
]

_SYMBOL_TO_MODULE = {
    "ModelLoader": "backend.inference.model_loader",
    "LoadedModel": "backend.inference.model_loader",
    "ABRouter": "backend.inference.ab_router",
    "RoutingDecision": "backend.inference.ab_router",
    "FeedbackCollector": "backend.inference.feedback_collector",
    "FeedbackRecord": "backend.inference.feedback_collector",
    "MetricTracker": "backend.inference.metric_tracker",
}

def __getattr__(name: str):
    module_path = _SYMBOL_TO_MODULE.get(name)
    if not module_path:
        raise AttributeError(f"module 'backend.inference' has no attribute {name!r}")
    module = import_module(module_path)
    return getattr(module, name)

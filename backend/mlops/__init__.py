"""MLOps lifecycle package.

Avoid eager imports at package import time to prevent circular import chains.
"""

from importlib import import_module

__all__ = ["get_mlops_manager", "MLOpsManager"]


def __getattr__(name: str):
    if name in {"get_mlops_manager", "MLOpsManager"}:
        module = import_module("backend.mlops.lifecycle")
        return getattr(module, name)
    raise AttributeError(f"module 'backend.mlops' has no attribute {name!r}")

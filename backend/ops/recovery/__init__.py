"""backend/ops/recovery — Failure Recovery & Rollback subsystem.

Ops Recovery Module
===================

Provides failure handling and recovery capabilities.
"""

from .failure_handler import (
    FailureHandler,
    FailureContext,
    FailureType,
    RecoveryState,
    RecoveryAction,
    IncidentReport,
)

__all__ = [
    "FailureHandler",
    "FailureContext",
    "FailureType",
    "RecoveryState",
    "RecoveryAction",
    "IncidentReport",
]
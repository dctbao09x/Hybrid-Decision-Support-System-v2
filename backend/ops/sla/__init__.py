# backend/ops/sla/__init__.py
"""
SLA Engine Module
=================

Provides:
- SLA Contracts (contracts.py)
- SLA Evaluator (evaluator.py)
- SLA Reporter (reporter.py)
"""

from backend.ops.sla.contracts import (
    SLAContract,
    SLATarget,
    SLAViolation,
    SLAStatus,
    SLASeverity,
    DEFAULT_CONTRACT,
    CRITICAL_CONTRACT,
    BATCH_CONTRACT,
)
from backend.ops.sla.evaluator import SLAEvaluator, get_sla_evaluator
from backend.ops.sla.reporter import SLAReporter, SLAReport, SLAReportPeriod, get_sla_reporter

__all__ = [
    # Contracts
    "SLAContract",
    "SLATarget",
    "SLAViolation",
    "SLAStatus",
    "SLASeverity",
    "DEFAULT_CONTRACT",
    "CRITICAL_CONTRACT",
    "BATCH_CONTRACT",
    # Evaluator
    "SLAEvaluator",
    "get_sla_evaluator",
    # Reporter
    "SLAReporter",
    "SLAReport",
    "SLAReportPeriod",
    "get_sla_reporter",
]

# backend/rule_engine/job_database.py
"""
DEPRECATED MODULE: Legacy Compatibility Layer

This module is kept ONLY for backward compatibility.

All career data is now served via:
    rule_engine.adapters.kb_adapter

DO NOT:
- Add new data here
- Add business logic here
- Access JOB_DATABASE directly

This file will be removed in future versions.
"""

import warnings
import logging
from typing import Dict

# ==================== LOGGING ====================

logger = logging.getLogger(__name__)


# ==================== DEPRECATION WARNING ====================

warnings.warn(
    "rule_engine.job_database is deprecated and will be removed. "
    "Use rule_engine.adapters.kb_adapter instead.",
    DeprecationWarning,
    stacklevel=2
)


# ==================== IMPORT ADAPTER API ====================

from .adapters.kb_adapter import (  # noqa: E402
    get_job_requirements,
    get_all_jobs,
    get_jobs_by_domain,
    get_job_domain,
    get_relevant_interests,
    EDUCATION_HIERARCHY,
    DOMAIN_INTEREST_MAP,
    kb_adapter,
)


# ==================== BLOCK LEGACY DICT ACCESS ====================

class _DeprecatedJobDatabase(dict):
    """
    Prevent usage of old dict-style JOB_DATABASE.

    Forces migration to KB Adapter.
    """

    def __getitem__(self, key):
        logger.error(
            "Deprecated JOB_DATABASE access: %s",
            key
        )
        raise RuntimeError(
            "JOB_DATABASE is deprecated. "
            "Use kb_adapter instead."
        )

    def get(self, key, default=None):
        logger.error(
            "Deprecated JOB_DATABASE.get() called: %s",
            key
        )
        return default


# Public legacy symbol (placeholder only)
JOB_DATABASE: Dict = _DeprecatedJobDatabase()


# ==================== DIAGNOSTIC API ====================

def legacy_status() -> dict:
    """
    Return legacy compatibility status.
    For debugging and migration checks.
    """
    return {
        "deprecated": True,
        "adapter_connected": kb_adapter is not None,
        "education_loaded": bool(EDUCATION_HIERARCHY),
        "domain_loaded": bool(DOMAIN_INTEREST_MAP),
    }


# ==================== EXPORT ====================

__all__ = [
    # Adapter API
    "get_job_requirements",
    "get_all_jobs",
    "get_jobs_by_domain",
    "get_job_domain",
    "get_relevant_interests",

    # Constants
    "EDUCATION_HIERARCHY",
    "DOMAIN_INTEREST_MAP",

    # Legacy
    "JOB_DATABASE",
    "legacy_status",
]

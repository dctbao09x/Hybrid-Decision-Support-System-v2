"""
taxonomy_gate.py — P8: Taxonomy Normalize + Validate + Enforce
==============================================================

Every input category (skills, interests, education) is passed through the
taxonomy facade before reaching the rule engine or scoring stages.

Rules
-----
* If skill list is empty after normalization  → ``TaxonomyValidationError``
* If interest list is empty after normalization → ``TaxonomyValidationError``
* Invalid / unknown education resolves to the taxonomy's UNKNOWN_EDUCATION_ID
  (this is *allowed* — the downstream guard decides whether to block on it).
* Gate MUST be called before rule_engine. Scoring is blocked on failure.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from backend.taxonomy.facade import TaxonomyFacade  # module-level import (patchable)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class TaxonomyValidationError(Exception):
    """Raised when input cannot be mapped to any recognized taxonomy entry.

    Attributes
    ----------
    message : str
        Human-readable reason.
    detail : Dict[str, Any]
        Structured payload (field, raw_values, trace_id) for the API 400 body.
    """

    def __init__(self, message: str, *, detail: Dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail: Dict[str, Any] = detail or {}

    def as_dict(self) -> Dict[str, Any]:
        return {
            "error": "TAXONOMY_VALIDATION_FAILED",
            "message": str(self),
            **self.detail,
        }


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

class TaxonomyGate:
    """Static gate that normalizes + validates all input taxonomy fields.

    Usage
    -----
    Call :py:meth:`normalize_and_validate` inside ``_normalize_input()``
    **after** the raw skill / interest non-empty guards have run, so that
    the lists are guaranteed non-empty before taxonomy resolution begins.

    Returns
    -------
    Dict with keys:
        ``skills``           – deduplicated, canonical-cased skill labels.
        ``interests``        – deduplicated, canonical-cased interest labels.
        ``education_level``  – normalized education id/label.
        ``taxonomy_applied`` – True (signals gate ran for audit).
    """

    @staticmethod
    def normalize_and_validate(
        skills: List[str],
        interests: List[str],
        education_level: str,
        *,
        trace_id: str = "-",
    ) -> Dict[str, Any]:
        """Run taxonomy normalization on all three input categories.

        Parameters
        ----------
        skills:
            Pre-cleaned skill strings (already lowercased, stripped).
        interests:
            Pre-cleaned interest strings.
        education_level:
            Raw education level string from the user's form.
        trace_id:
            Pipeline trace id for logging.

        Raises
        ------
        TaxonomyValidationError
            If resolved skills list becomes empty, or if resolved interests
            list becomes empty after taxonomy lookup.
        """
        facade = TaxonomyFacade()

        # ── Skills ────────────────────────────────────────────────────────────
        resolved_skills: List[str] = facade.resolve_skill_list(
            skills, include_unmatched=True
        )
        logger.debug(
            "[%s] TaxonomyGate skills: raw=%d → resolved=%d",
            trace_id, len(skills), len(resolved_skills),
        )
        if not resolved_skills:
            raise TaxonomyValidationError(
                "No skills could be resolved to a recognized taxonomy entry.",
                detail={
                    "field": "skills",
                    "raw_values": skills,
                    "trace_id": trace_id,
                },
            )

        # ── Interests ─────────────────────────────────────────────────────────
        resolved_interests: List[str] = facade.resolve_interest_list(
            interests, include_unmatched=True
        )
        logger.debug(
            "[%s] TaxonomyGate interests: raw=%d → resolved=%d",
            trace_id, len(interests), len(resolved_interests),
        )
        if not resolved_interests:
            raise TaxonomyValidationError(
                "No interests could be resolved to a recognized taxonomy entry.",
                detail={
                    "field": "interests",
                    "raw_values": interests,
                    "trace_id": trace_id,
                },
            )

        # ── Education ─────────────────────────────────────────────────────────
        resolved_education: str = facade.resolve_education(
            education_level, return_id=False
        )
        logger.debug(
            "[%s] TaxonomyGate education: raw=%r → resolved=%r",
            trace_id, education_level, resolved_education,
        )

        result: Dict[str, Any] = {
            "skills": resolved_skills,
            "interests": resolved_interests,
            "education_level": resolved_education,
            "taxonomy_applied": True,
        }
        logger.info(
            "[%s] TaxonomyGate passed: skills=%d interests=%d education=%r",
            trace_id, len(resolved_skills), len(resolved_interests), resolved_education,
        )
        return result

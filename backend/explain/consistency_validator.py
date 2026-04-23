# backend/explain/consistency_validator.py
"""
Strict Mathematical Validation — Explanation ↔ ScoringBreakdown
================================================================

Guarantees that every ``UnifiedExplanation`` produced by the pipeline is
arithmetically consistent with the authoritative ``ScoringBreakdown`` that
produced it.

CONTRACT
--------
1. ``explanation.per_component_contributions == breakdown.contributions``
   (key-for-key, value-for-value, within EPSILON = 1e-6)

2. ``sum(explanation.per_component_contributions.values()) == breakdown.final_score``
   (within EPSILON = 1e-6)

3. ``explanation.weight_version == expected_weight_version``
   (exact string match)

4. No extra components in explanation that are absent from breakdown.
   No missing components in explanation that are present in breakdown.

INTEGRATION POINTS (Stage 9)
-----------------------------
Call ``validate_explanation_consistency()`` in ``_generate_explanation()``:
  ① After ``UnifiedExplanation.build()`` (explanation assembly complete)
  ② Before ``storage.append_unified()``  (before artifact creation)
  ③ Before ``return ExplanationResult()`` (before response return)

If any invariant is violated, ``ExplanationInconsistencyError`` is raised
immediately and the pipeline MUST NOT proceed silently.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from backend.explain.unified_schema import UnifiedExplanation
    from backend.scoring.sub_scorer import ScoringBreakdown

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_EPSILON: float = 1e-6  # Tolerance for floating-point comparisons


# ─────────────────────────────────────────────────────────────────────────────
# Exception
# ─────────────────────────────────────────────────────────────────────────────

class ExplanationInconsistencyError(Exception):
    """
    Raised when a ``UnifiedExplanation`` does not match its ``ScoringBreakdown``.

    This is a hard pipeline error — it must never be silently suppressed.

    Attributes
    ----------
    mismatches : list[str]
        Human-readable descriptions of each individual inconsistency found.
    """

    def __init__(self, message: str, mismatches: Optional[list] = None) -> None:
        super().__init__(message)
        self.mismatches: list = mismatches or []

    def __str__(self) -> str:
        base = super().__str__()
        if self.mismatches:
            lines = "\n".join(f"  [{i + 1}] {m}" for i, m in enumerate(self.mismatches))
            return f"{base}\n{lines}"
        return base


# ─────────────────────────────────────────────────────────────────────────────
# Validator
# ─────────────────────────────────────────────────────────────────────────────

def validate_explanation_consistency(
    explanation: "UnifiedExplanation",
    breakdown: "ScoringBreakdown",
    expected_weight_version: str,
) -> None:
    """
    Validate that ``explanation`` is arithmetically consistent with ``breakdown``.

    This function is a PURE GUARD — it either returns ``None`` silently
    or raises ``ExplanationInconsistencyError`` with a full list of mismatches.

    Parameters
    ----------
    explanation:
        The assembled ``UnifiedExplanation`` from Stage 9.
    breakdown:
        The authoritative ``ScoringBreakdown`` from Stage 5 (SIMGR scoring).
    expected_weight_version:
        The weight artifact version string that ``explanation.weight_version``
        must match exactly (e.g. ``self._weights_version`` in the controller).

    Raises
    ------
    ExplanationInconsistencyError
        If any of the four invariants are violated.  All violations are
        collected before raising so the caller gets a complete diagnostic.
    """
    mismatches: list[str] = []

    exp_contribs: dict[str, float] = dict(explanation.per_component_contributions)
    bd_contribs: dict[str, float] = dict(breakdown.contributions)

    exp_keys = set(exp_contribs)
    bd_keys = set(bd_contribs)

    # ── Invariant 4a: No missing components ──────────────────────────────────
    missing = bd_keys - exp_keys
    if missing:
        mismatches.append(
            f"Components present in ScoringBreakdown but absent from explanation: "
            f"{sorted(missing)}"
        )

    # ── Invariant 4b: No extra components ────────────────────────────────────
    extra = exp_keys - bd_keys
    if extra:
        mismatches.append(
            f"Components present in explanation but absent from ScoringBreakdown: "
            f"{sorted(extra)}"
        )

    # ── Invariant 1: per_component_contributions values match exactly ─────────
    for component in sorted(exp_keys & bd_keys):
        exp_val = float(exp_contribs[component])
        bd_val = float(bd_contribs[component])
        delta = abs(exp_val - bd_val)
        if delta > _EPSILON:
            mismatches.append(
                f"Contribution mismatch for component '{component}': "
                f"explanation={exp_val!r}, breakdown={bd_val!r}, "
                f"delta={delta:.2e} (threshold={_EPSILON:.0e})"
            )

    # ── Invariant 2: sum(contributions) == final_score ───────────────────────
    contribution_sum = sum(exp_contribs.get(c, 0.0) for c in exp_keys)
    final_score = float(breakdown.final_score)
    sum_delta = abs(contribution_sum - final_score)
    if sum_delta > _EPSILON:
        mismatches.append(
            f"sum(per_component_contributions)={contribution_sum!r} != "
            f"ScoringBreakdown.final_score={final_score!r}, "
            f"delta={sum_delta:.2e} (threshold={_EPSILON:.0e})"
        )

    # ── Invariant 3: weight_version matches expected ──────────────────────────
    if explanation.weight_version != expected_weight_version:
        mismatches.append(
            f"weight_version mismatch: "
            f"explanation.weight_version={explanation.weight_version!r}, "
            f"expected={expected_weight_version!r}"
        )

    # ── Outcome ───────────────────────────────────────────────────────────────
    if mismatches:
        logger.error(
            "ExplanationInconsistencyError: %d mismatch(es) detected — "
            "explanation does not match ScoringBreakdown. "
            "trace_id=%r  weight_version=%r",
            len(mismatches),
            getattr(explanation, "trace_id", "<unknown>"),
            getattr(explanation, "weight_version", "<unknown>"),
        )
        raise ExplanationInconsistencyError(
            f"Explanation ↔ ScoringBreakdown inconsistency: "
            f"{len(mismatches)} violation(s) detected",
            mismatches=mismatches,
        )

    logger.debug(
        "[%s] validate_explanation_consistency: PASS "
        "(contributions=%d components, sum=%.6f, final_score=%.6f)",
        getattr(explanation, "trace_id", "-"),
        len(exp_keys),
        contribution_sum,
        final_score,
    )


__all__ = [
    "ExplanationInconsistencyError",
    "validate_explanation_consistency",
]

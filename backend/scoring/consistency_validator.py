# backend/scoring/consistency_validator.py
"""
Scoring Consistency Validator
==============================

Enforces strict five-rule invariant over every ``ScoringBreakdown`` before
it is embedded in a ``DecisionResponse``.  If any rule is violated the
validator raises ``InconsistentScoringError`` immediately so inconsistent
scores can NEVER be returned to callers silently.

RULES
-----
SCORE_001  All five required sub-scores are present.
SCORE_002  Every sub-score is within [0, 100].
SCORE_003  sum(weight_i * sub_score_i) == final_score  (± FLOAT_TOLERANCE).
SCORE_004  Explanation contributions (when provided) match breakdown.contributions.
SCORE_005  A non-empty weight version string is present.

INTEGRATION POINT
-----------------
Call ``validate_scoring_consistency()`` in ``run_pipeline()`` immediately
BEFORE the ``DecisionResponse`` object is constructed:

    validate_scoring_consistency(
        breakdown,
        weight_version=self._weights_version,
        explanation_contributions=explanation.per_component_contributions
            if explanation else None,
        trace_id=trace_id,
    )

Any ``InconsistentScoringError`` raised here will be caught by the
pipeline's outer ``except`` block and returned as a status=ERROR response
(or propagated, depending on policy).  It will NEVER be swallowed silently.

TOLERANCES
----------
FLOAT_TOLERANCE = 1e-4   — used for weighted-sum cross-check (Rule 3).
CONTRIBUTION_TOLERANCE = 1e-4  — used for explanation mismatch check (Rule 4).
"""

from __future__ import annotations

import logging
import math
from typing import Dict, Optional, TYPE_CHECKING

from backend.scoring.errors import InconsistentScoringError

if TYPE_CHECKING:
    from backend.scoring.sub_scorer import ScoringBreakdown

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

#: Floating-point tolerance for weighted-sum cross-check (Rule 3).
FLOAT_TOLERANCE: float = 1e-4

#: Floating-point tolerance for explanation contribution mismatch (Rule 4).
CONTRIBUTION_TOLERANCE: float = 1e-4

#: The five canonical sub-score component names (matches SubScoreWeights).
REQUIRED_COMPONENTS: tuple[str, ...] = (
    "skill",
    "experience",
    "education",
    "goal_alignment",
    "preference",
)

#: Corresponding attribute names on ScoringBreakdown, in the same order.
_SCORE_ATTRS: tuple[str, ...] = (
    "skill_score",
    "experience_score",
    "education_score",
    "goal_alignment_score",
    "preference_score",
)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def validate_scoring_consistency(
    breakdown: "ScoringBreakdown",
    *,
    weight_version: Optional[str] = None,
    explanation_contributions: Optional[Dict[str, float]] = None,
    trace_id: str = "-",
) -> None:
    """
    Validate a ``ScoringBreakdown`` against all five consistency rules.

    All rules are evaluated before raising so that every violation is
    reported in a single ``InconsistentScoringError``.

    Parameters
    ----------
    breakdown:
        The ``ScoringBreakdown`` produced by ``assemble_breakdown()``.
    weight_version:
        The active weight-manifest version string (e.g. ``"v1.2.0"``).
        Must be a non-empty string for Rule 5 to pass.
    explanation_contributions:
        Optional ``per_component_contributions`` dict from the
        ``UnifiedExplanation`` (or ``ExplanationResult``).  When provided,
        Rule 4 checks that every key/value matches ``breakdown.contributions``
        within ``CONTRIBUTION_TOLERANCE``.
    trace_id:
        Pipeline trace identifier threaded into log messages and the error.

    Raises
    ------
    InconsistentScoringError
        If one or more rules are violated.  The ``violations`` attribute
        contains a human-readable description of every individual failure.
    """
    violations: list[str] = []

    # ── Rule 1: All required sub-scores exist ────────────────────────────────
    violations.extend(_check_required_subscores(breakdown))

    # ── Rule 2: All sub-scores within [0, 100] ───────────────────────────────
    violations.extend(_check_subscores_in_range(breakdown))

    # ── Rule 3: Weighted sum == final_score ──────────────────────────────────
    violations.extend(_check_weighted_sum(breakdown))

    # ── Rule 4: Explanation contributions match breakdown ────────────────────
    if explanation_contributions is not None:
        violations.extend(
            _check_explanation_contributions(breakdown, explanation_contributions)
        )

    # ── Rule 5: Weight version present ───────────────────────────────────────
    violations.extend(_check_weight_version(weight_version))

    if violations:
        msg = (
            f"[{trace_id}] ScoringConsistencyValidator: "
            f"{len(violations)} invariant(s) violated — "
            "inconsistent scoring result blocked."
        )
        logger.error("%s  violations=%r", msg, violations)
        raise InconsistentScoringError(msg, violations, trace_id=trace_id)

    logger.debug(
        "[%s] ScoringConsistencyValidator: all rules passed  "
        "final_score=%.4f  weight_version=%s",
        trace_id,
        breakdown.final_score,
        weight_version or "<none>",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Internal rule checks  (each returns a list of violation strings)
# ─────────────────────────────────────────────────────────────────────────────

def _check_required_subscores(breakdown: "ScoringBreakdown") -> list[str]:
    """
    RULE 1 — All required sub-scores exist.

    Verifies that ``breakdown.weights`` contains every component in
    ``REQUIRED_COMPONENTS`` and that every corresponding score attribute is
    reachable (not missing as an attribute).
    """
    violations: list[str] = []

    # Check weights dict has all components
    for comp in REQUIRED_COMPONENTS:
        if comp not in breakdown.weights:
            violations.append(
                f"SCORE_001: required component '{comp}' missing from "
                f"breakdown.weights — cannot verify weighted sum."
            )

    # Check score attributes exist on the breakdown object
    for attr in _SCORE_ATTRS:
        if not hasattr(breakdown, attr):
            violations.append(
                f"SCORE_001: attribute '{attr}' missing from ScoringBreakdown."
            )
        elif getattr(breakdown, attr) is None:
            violations.append(
                f"SCORE_001: '{attr}' is None — sub-score must be a float."
            )

    return violations


def _check_subscores_in_range(breakdown: "ScoringBreakdown") -> list[str]:
    """RULE 2 — Every sub-score is within [0, 100]."""
    violations: list[str] = []

    subscores: dict[str, float] = {
        "skill_score":          getattr(breakdown, "skill_score",          None),
        "experience_score":     getattr(breakdown, "experience_score",     None),
        "education_score":      getattr(breakdown, "education_score",      None),
        "goal_alignment_score": getattr(breakdown, "goal_alignment_score", None),
        "preference_score":     getattr(breakdown, "preference_score",     None),
    }

    for name, value in subscores.items():
        if value is None:
            continue  # Already reported by Rule 1
        if math.isnan(value) or math.isinf(value):
            violations.append(
                f"SCORE_002: '{name}' = {value!r} is NaN/Inf — must be finite."
            )
        elif not (0.0 <= value <= 100.0):
            violations.append(
                f"SCORE_002: '{name}' = {value:.6f} is outside [0, 100]."
            )

    # Also check final_score
    fs = breakdown.final_score
    if math.isnan(fs) or math.isinf(fs):
        violations.append(
            f"SCORE_002: 'final_score' = {fs!r} is NaN/Inf — must be finite."
        )
    elif not (0.0 <= fs <= 100.0):
        violations.append(
            f"SCORE_002: 'final_score' = {fs:.6f} is outside [0, 100]."
        )

    return violations


def _check_weighted_sum(breakdown: "ScoringBreakdown") -> list[str]:
    """
    RULE 3 — sum(weight_i * sub_score_i) equals final_score within tolerance.

    Uses the ``contributions`` dict if it is populated; falls back to
    recomputing directly from ``weights`` and sub-scores.
    """
    violations: list[str] = []

    # Use contributions dict as the authoritative source when available
    if breakdown.contributions:
        recomputed = sum(breakdown.contributions.values())
    else:
        # Recompute manually from weights and sub-scores
        recomputed = 0.0
        score_map = {
            "skill":          getattr(breakdown, "skill_score",          0.0),
            "experience":     getattr(breakdown, "experience_score",     0.0),
            "education":      getattr(breakdown, "education_score",      0.0),
            "goal_alignment": getattr(breakdown, "goal_alignment_score", 0.0),
            "preference":     getattr(breakdown, "preference_score",     0.0),
        }
        for comp, weight in breakdown.weights.items():
            score = score_map.get(comp, 0.0)
            recomputed += weight * score

    delta = abs(recomputed - breakdown.final_score)
    if delta > FLOAT_TOLERANCE:
        violations.append(
            f"SCORE_003: weighted sum recomputed={recomputed:.6f} differs from "
            f"final_score={breakdown.final_score:.6f}  "
            f"delta={delta:.2e} (tolerance={FLOAT_TOLERANCE:.0e})."
        )

    return violations


def _check_explanation_contributions(
    breakdown: "ScoringBreakdown",
    explanation_contributions: Dict[str, float],
) -> list[str]:
    """
    RULE 4 — Explanation contributions match ScoringBreakdown.contributions.

    Checks:
    - No extra keys in explanation absent from breakdown.
    - No keys in breakdown absent from explanation.
    - Per-key value diff within CONTRIBUTION_TOLERANCE.
    """
    violations: list[str] = []
    bd_contribs = breakdown.contributions or {}

    extra_keys = set(explanation_contributions) - set(bd_contribs)
    for k in sorted(extra_keys):
        violations.append(
            f"SCORE_004: explanation.contributions has extra key '{k}' "
            "not present in breakdown.contributions."
        )

    missing_keys = set(bd_contribs) - set(explanation_contributions)
    for k in sorted(missing_keys):
        violations.append(
            f"SCORE_004: explanation.contributions missing key '{k}' "
            "present in breakdown.contributions."
        )

    for key in sorted(set(bd_contribs) & set(explanation_contributions)):
        bd_val  = bd_contribs[key]
        exp_val = explanation_contributions[key]
        delta   = abs(bd_val - exp_val)
        if delta > CONTRIBUTION_TOLERANCE:
            violations.append(
                f"SCORE_004: contribution['{key}'] mismatch — "
                f"breakdown={bd_val:.6f}, explanation={exp_val:.6f}, "
                f"delta={delta:.2e} (tolerance={CONTRIBUTION_TOLERANCE:.0e})."
            )

    return violations


def _check_weight_version(weight_version: Optional[str]) -> list[str]:
    """RULE 5 — Weight version string is present and non-empty."""
    if not weight_version or not weight_version.strip():
        return [
            "SCORE_005: weight_version is absent or empty — "
            "scoring provenance cannot be established."
        ]
    return []

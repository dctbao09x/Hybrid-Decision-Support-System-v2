# backend/scoring/sub_scorer.py
"""
Sub-Score Decomposition Engine
================================

Single source of truth for the five mandatory sub-score components and the
`ScoringBreakdown` data structure.

MANDATORY SUB-SCORES
--------------------
  skill_score          — breadth and depth of declared skills
  experience_score     — years of experience × domain spread
  education_score      — ordinal mapping of highest education level
  goal_alignment_score — aspiration count × timeline reasonableness
  preference_score     — preferred-domain breadth × work-style clarity

FORMULA CONTRACT
----------------
  final_score = Σ  weight_i * component_score_i     for i in {skill, experience,
                                                      education, goal_alignment,
                                                      preference}
  where:
    - every component_score_i ∈ [0, 100]
    - Σ weight_i == 1.0  (enforced at runtime)
    - final_score ∈ [0, 100]  (clamped after summation)

INVARIANTS
----------
  * Each sub-score function is a PURE, DETERMINISTIC function of its arguments.
  * NO hidden multipliers, bonuses, or implicit modifiers.
  * All intermediate values are surfaced in `ScoringBreakdown.contributions`.
  * `final_score` is NEVER set directly — it is always computed by
    `_weighted_sum()` from the five components and their weights.

BOUNDS
------
  All sub-scores are clamped to [0.0, 100.0] before aggregation.
  `final_score` is subsequently clamped to [0.0, 100.0].
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# BOUNDS
# ──────────────────────────────────────────────────────────────────────────────

_MIN: float = 0.0
_MAX: float = 100.0


def _clamp(value: float) -> float:
    """Clamp a value to [0, 100].  No NaN/Inf allowed."""
    if math.isnan(value) or math.isinf(value):
        return _MIN
    return max(_MIN, min(_MAX, value))


# ──────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SubScoreWeights:
    """
    Weights for the five sub-score components.

    Invariants
    ----------
    * All weights are non-negative.
    * ``skill + experience + education + goal_alignment + preference == 1.0``
      (verified by ``validate()`` and enforced by ``assemble_breakdown``).

    Default distribution
    --------------------
    skill          0.30
    experience     0.25
    education      0.20
    goal_alignment 0.15
    preference     0.10
    ──────────────────
    total          1.00
    """

    skill: float = 0.30
    experience: float = 0.25
    education: float = 0.20
    goal_alignment: float = 0.15
    preference: float = 0.10

    # ── component order (canonical — never change) ──────────────────────────
    COMPONENTS: tuple[str, ...] = field(
        default=("skill", "experience", "education", "goal_alignment", "preference"),
        init=False,
        repr=False,
        compare=False,
    )

    def as_dict(self) -> Dict[str, float]:
        """Return ``{component: weight}`` dict in canonical order."""
        return {c: getattr(self, c) for c in self.COMPONENTS}

    def validate(self) -> None:
        """
        Assert weights are valid.

        Raises
        ------
        ValueError
            If any weight is negative or total deviates from 1.0 by > 1e-6.
        """
        total = 0.0
        for c in self.COMPONENTS:
            w = getattr(self, c)
            if w < 0.0:
                raise ValueError(
                    f"SubScoreWeights.{c} = {w} is negative; all weights must be >= 0."
                )
            total += w
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"SubScoreWeights must sum to 1.0, got {total:.8f}."
            )


DEFAULT_WEIGHTS: SubScoreWeights = SubScoreWeights()  # populated below


def _init_default_weights() -> SubScoreWeights:
    """
    Load SubScoreWeights from ``config/scoring.yaml`` (sub_score_weights block).

    Falls back to hardcoded field defaults when the config file is absent (e.g.
    in lightweight unit-test environments).  Production deployments MUST have
    a valid ``sub_score_weights`` block in scoring.yaml.

    The fallback values are identical to ``SubScoreWeights`` field defaults,
    so test results remain deterministic regardless of which path is taken.
    """
    try:
        from backend.scoring.weight_config import load_sub_score_weight_dict
        d = load_sub_score_weight_dict()
        weights = SubScoreWeights(**d)
        weights.validate()  # belt-and-suspenders: validate again after construction
        logger.debug(
            "DEFAULT_WEIGHTS loaded from config/scoring.yaml: %s",
            {k: round(v, 6) for k, v in weights.as_dict().items()},
        )
        return weights
    except FileNotFoundError:
        logger.debug(
            "scoring.yaml not found; DEFAULT_WEIGHTS using hardcoded SubScoreWeights defaults."
        )
    except KeyError as exc:
        logger.warning(
            "scoring.yaml missing sub_score_weights block (%s); "
            "using hardcoded defaults.", exc
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Unexpected error loading weight config (%s); "
            "using hardcoded defaults.", exc
        )
    return SubScoreWeights()


DEFAULT_WEIGHTS: SubScoreWeights = _init_default_weights()


@dataclass(frozen=True)
class ScoringBreakdown:
    """
    Fully-decomposed scoring result.

    All five sub-scores are in **[0, 100]**.
    ``final_score`` is the weighted sum of the five sub-scores,
    also in **[0, 100]**.

    The ``contributions`` dict surfaces every term of the weighted sum so that
    any external party can verify the arithmetic without access to internal code:

        contributions[c] == weights[c] * score_for_c
        final_score      == sum(contributions.values())   # ± float rounding

    No field may be set independently — use ``assemble_breakdown()`` to
    produce a valid instance.
    """

    # ── Sub-scores ───────────────────────────────────────────────────────────
    skill_score: float
    experience_score: float
    education_score: float
    goal_alignment_score: float
    preference_score: float

    # ── Final aggregation ────────────────────────────────────────────────────
    final_score: float

    # ── Audit fields (always populated) ─────────────────────────────────────
    weights: Dict[str, float]
    """Weights used to compute ``final_score``."""

    contributions: Dict[str, float]
    """Per-component contribution to ``final_score``: ``weight_i * score_i``."""

    formula: str
    """Human-readable formula string for auditability."""

    sub_score_meta: Dict[str, Any]
    """Intermediate diagnostic values from each sub-score function."""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to plain dict for JSON responses."""
        return {
            "skill_score": round(self.skill_score, 4),
            "experience_score": round(self.experience_score, 4),
            "education_score": round(self.education_score, 4),
            "goal_alignment_score": round(self.goal_alignment_score, 4),
            "preference_score": round(self.preference_score, 4),
            "final_score": round(self.final_score, 4),
            "weights": {k: round(v, 6) for k, v in self.weights.items()},
            "contributions": {k: round(v, 4) for k, v in self.contributions.items()},
            "formula": self.formula,
        }


# ──────────────────────────────────────────────────────────────────────────────
# EDUCATION LEVEL LOOKUP
# ──────────────────────────────────────────────────────────────────────────────

_EDUCATION_MAP: Dict[str, float] = {
    # Doctoral
    "phd": 100.0,
    "ph.d": 100.0,
    "ph.d.": 100.0,
    "doctorate": 100.0,
    "doctoral": 100.0,
    # Master's
    "master": 85.0,
    "master's": 85.0,
    "masters": 85.0,
    "m.sc": 85.0,
    "m.sc.": 85.0,
    "msc": 85.0,
    "mba": 85.0,
    "postgraduate": 80.0,
    # Bachelor's
    "bachelor": 70.0,
    "bachelor's": 70.0,
    "bachelors": 70.0,
    "b.sc": 70.0,
    "b.sc.": 70.0,
    "bsc": 70.0,
    "undergraduate": 65.0,
    # Associate / Diploma
    "associate": 52.0,
    "associate's": 52.0,
    "diploma": 45.0,
    "diploma (advanced)": 50.0,
    "certificate": 40.0,
    # Secondary
    "high school": 30.0,
    "secondary": 30.0,
    "a-level": 35.0,
    "gcse": 25.0,
}

_RECOGNIZED_WORK_STYLES: frozenset[str] = frozenset({
    "remote", "in-office", "on-site", "onsite", "hybrid",
    "flexible", "freelance", "contract", "full-time", "part-time",
})


# ──────────────────────────────────────────────────────────────────────────────
# PURE SUB-SCORE FUNCTIONS
# ──────────────────────────────────────────────────────────────────────────────

def compute_skill_score(skills: List[str]) -> tuple[float, Dict[str, Any]]:
    """
    Compute ``skill_score`` from the list of declared skills.

    Algorithm
    ---------
    * Each non-empty, unique skill contributes **10 points** (after dedup).
    * Score is capped at **100**.
    * No hidden bonuses; no career-context dependency.

    Parameters
    ----------
    skills:
        List of skill strings from ``ScoringInput.skills``.

    Returns
    -------
    score : float
        Clamped to [0, 100].
    meta : dict
        Diagnostic values.
    """
    deduped = list({s.strip().lower() for s in skills if s and s.strip()})
    count = len(deduped)
    raw = count * 10.0
    score = _clamp(raw)
    meta = {
        "unique_skill_count": count,
        "points_per_skill": 10.0,
        "raw_before_clamp": raw,
    }
    logger.debug("compute_skill_score: count=%d raw=%.1f score=%.1f", count, raw, score)
    return score, meta


def compute_experience_score(years: int, domains: List[str]) -> tuple[float, Dict[str, Any]]:
    """
    Compute ``experience_score`` from years of experience and domain breadth.

    Algorithm
    ---------
    * **Years component** (max 60 pts): ``min(60, years * 6)``
      — 10 years of experience → full 60 pts.
    * **Domain breadth component** (max 40 pts): ``min(40, unique_domains * 10)``
      — 4 or more distinct domains → full 40 pts.
    * ``experience_score = years_pts + domain_pts``, clamped to [0, 100].
    * No hidden multipliers.

    Parameters
    ----------
    years : int
        Years of experience (``ScoringInput.experience.years``).
    domains : list[str]
        Experience domains (``ScoringInput.experience.domains``).

    Returns
    -------
    score : float
        Clamped to [0, 100].
    meta : dict
        Diagnostic values.
    """
    years_pts = min(60.0, max(0.0, years) * 6.0)
    deduped_domains = list({d.strip().lower() for d in domains if d and d.strip()})
    domain_pts = min(40.0, len(deduped_domains) * 10.0)
    raw = years_pts + domain_pts
    score = _clamp(raw)
    meta = {
        "years": years,
        "years_pts": years_pts,
        "unique_domains": len(deduped_domains),
        "domain_pts": domain_pts,
        "raw_before_clamp": raw,
    }
    logger.debug(
        "compute_experience_score: years=%d years_pts=%.1f domains=%d domain_pts=%.1f score=%.1f",
        years, years_pts, len(deduped_domains), domain_pts, score,
    )
    return score, meta


def compute_education_score(level: str) -> tuple[float, Dict[str, Any]]:
    """
    Compute ``education_score`` from a declared education level string.

    Algorithm
    ---------
    * Perform case-insensitive lookup in ``_EDUCATION_MAP``.
    * If not found, try a partial-match scan (level is a substring of a key).
    * Default to **50.0** (neutral) if no match found.
    * Result is clamped to [0, 100] (already guaranteed by ``_EDUCATION_MAP``).

    Parameters
    ----------
    level : str
        Education level string (``ScoringInput.education.level``).

    Returns
    -------
    score : float
        Clamped to [0, 100].
    meta : dict
        Diagnostic values.
    """
    norm = level.strip().lower() if level else ""
    score: float = 50.0  # neutral default
    match_type = "default"

    if not norm:
        # Empty / missing level → neutral default (skip partial scan; empty string
        # would match every key via `"" in key`, which is a Python string gotcha).
        match_type = "empty"
    elif norm in _EDUCATION_MAP:
        score = _EDUCATION_MAP[norm]
        match_type = "exact"
    else:
        # Partial scan: check if any map key is contained in the input or vice-versa.
        # Guard: both sides must be non-empty to avoid spurious empty-string matches.
        for key, val in _EDUCATION_MAP.items():
            if key and (key in norm or norm in key):
                score = val
                match_type = f"partial:{key}"
                break

    score = _clamp(score)
    meta = {
        "input_level": level,
        "normalised": norm,
        "match_type": match_type,
        "raw_before_clamp": score,
    }
    logger.debug(
        "compute_education_score: level=%r match=%s score=%.1f", level, match_type, score
    )
    return score, meta


def compute_goal_alignment_score(
    career_aspirations: List[str], timeline_years: int
) -> tuple[float, Dict[str, Any]]:
    """
    Compute ``goal_alignment_score`` from career aspirations and timeline.

    Algorithm
    ---------
    * **Aspirations component** (max 70 pts): ``min(70, unique_aspirations * 15)``
      — 5 or more distinct aspirations → full 70 pts.
    * **Timeline component** (max 30 pts):

      =================  ==========
      ``timeline_years``  Points
      =================  ==========
      0                  0
      1 – 10              30  (realistic planning horizon)
      11 – 20             20  (longer-term, still structured)
      > 20                10  (very long-range, lower certainty)
      =================  ==========

    * ``goal_alignment_score = aspiration_pts + timeline_pts``, clamped to [0, 100].

    Parameters
    ----------
    career_aspirations : list[str]
        List of career goals (``ScoringInput.goals.career_aspirations``).
    timeline_years : int
        Goal completion horizon (``ScoringInput.goals.timeline_years``).

    Returns
    -------
    score : float
        Clamped to [0, 100].
    meta : dict
        Diagnostic values.
    """
    deduped = list({a.strip().lower() for a in career_aspirations if a and a.strip()})
    aspiration_pts = min(70.0, len(deduped) * 15.0)

    tl = max(0, timeline_years)
    if tl == 0:
        timeline_pts = 0.0
    elif tl <= 10:
        timeline_pts = 30.0
    elif tl <= 20:
        timeline_pts = 20.0
    else:
        timeline_pts = 10.0

    raw = aspiration_pts + timeline_pts
    score = _clamp(raw)
    meta = {
        "unique_aspirations": len(deduped),
        "aspiration_pts": aspiration_pts,
        "timeline_years": tl,
        "timeline_pts": timeline_pts,
        "raw_before_clamp": raw,
    }
    logger.debug(
        "compute_goal_alignment_score: aspirations=%d aspiration_pts=%.1f "
        "timeline=%d timeline_pts=%.1f score=%.1f",
        len(deduped), aspiration_pts, tl, timeline_pts, score,
    )
    return score, meta


def compute_preference_score(
    preferred_domains: List[str], work_style: str
) -> tuple[float, Dict[str, Any]]:
    """
    Compute ``preference_score`` from preferred domains and work style.

    Algorithm
    ---------
    * **Domain breadth component** (max 60 pts): ``min(60, unique_domains * 12)``
      — 5 or more distinct preferred domains → full 60 pts.
    * **Work-style component** (max 40 pts):

      ==========================  ==========
      Condition                   Points
      ==========================  ==========
      recognised style keyword    40
      non-empty but unrecognised  20
      empty / missing             0
      ==========================  ==========

    * ``preference_score = domain_pts + style_pts``, clamped to [0, 100].

    Parameters
    ----------
    preferred_domains : list[str]
        Preferred career domains (``ScoringInput.preferences.preferred_domains``).
    work_style : str
        Preferred work arrangement (``ScoringInput.preferences.work_style``).

    Returns
    -------
    score : float
        Clamped to [0, 100].
    meta : dict
        Diagnostic values.
    """
    deduped = list({d.strip().lower() for d in preferred_domains if d and d.strip()})
    domain_pts = min(60.0, len(deduped) * 12.0)

    style_norm = work_style.strip().lower() if work_style else ""
    if style_norm in _RECOGNIZED_WORK_STYLES:
        style_pts = 40.0
        style_matched = True
    elif style_norm:
        style_pts = 20.0
        style_matched = False
    else:
        style_pts = 0.0
        style_matched = False

    raw = domain_pts + style_pts
    score = _clamp(raw)
    meta = {
        "unique_domains": len(deduped),
        "domain_pts": domain_pts,
        "work_style_input": work_style,
        "work_style_normalised": style_norm,
        "style_recognised": style_matched,
        "style_pts": style_pts,
        "raw_before_clamp": raw,
    }
    logger.debug(
        "compute_preference_score: domains=%d domain_pts=%.1f "
        "work_style=%r recognised=%s style_pts=%.1f score=%.1f",
        len(deduped), domain_pts, work_style, style_matched, style_pts, score,
    )
    return score, meta


# ──────────────────────────────────────────────────────────────────────────────
# WEIGHTED SUM (internal — no caller should replicate this)
# ──────────────────────────────────────────────────────────────────────────────

def _weighted_sum(scores: Dict[str, float], weights: SubScoreWeights) -> float:
    """
    Compute ``final_score`` as the strict weighted sum of sub-scores.

    This is the ONLY place the aggregation formula executes.

    Parameters
    ----------
    scores:
        ``{component: sub_score}`` with sub_scores in [0, 100].
    weights:
        ``SubScoreWeights`` instance (already validated).

    Returns
    -------
    float
        Clamped to [0, 100].
    """
    total = 0.0
    for component in weights.COMPONENTS:
        total += weights.as_dict()[component] * scores[component]
    return _clamp(total)


def _build_contributions(
    scores: Dict[str, float], weights: SubScoreWeights
) -> Dict[str, float]:
    """
    Return per-component contribution dict.

    Each value equals ``weight_i * score_i``.  The sum of contributions
    equals ``final_score`` (before clamp — see ``_weighted_sum``).
    """
    return {
        c: round(weights.as_dict()[c] * scores[c], 6)
        for c in weights.COMPONENTS
    }


def _build_formula_string(weights: SubScoreWeights) -> str:
    """Produce a human-readable formula string for the current weights."""
    terms = [
        f"{weights.as_dict()[c]:.4f}*{c}_score"
        for c in weights.COMPONENTS
    ]
    return "final_score = " + " + ".join(terms)


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC ASSEMBLER
# ──────────────────────────────────────────────────────────────────────────────

def assemble_breakdown(
    scoring_input: Any,
    *,
    weights: Optional[SubScoreWeights] = None,
    trace_id: str = "-",
) -> ScoringBreakdown:
    """
    Compute and assemble a fully-decomposed ``ScoringBreakdown``.

    This is the **single public entry point** for the sub-score decomposition.
    It accepts either a ``ScoringInput`` Pydantic model or a plain ``dict``
    (for use in middleware or pre-Pydantic validation paths).

    Algorithm
    ---------
    1. Extract component fields from ``scoring_input``.
    2. Call each pure sub-score function independently.
    3. Clamp all five sub-scores to [0, 100].
    4. Validate weights (sum-to-1 check).
    5. Compute ``final_score = _weighted_sum(sub_scores, weights)``.
    6. Build ``contributions`` for auditability.
    7. Return immutable ``ScoringBreakdown``.

    Parameters
    ----------
    scoring_input:
        ``ScoringInput`` instance or plain dict with keys matching the model.
    weights:
        Custom ``SubScoreWeights``.  Defaults to ``DEFAULT_WEIGHTS``.
    trace_id:
        Trace ID for log correlation.

    Returns
    -------
    ScoringBreakdown
        Immutable, fully-populated breakdown instance.

    Raises
    ------
    ValueError
        If ``weights`` fail validation (non-negative + sum-to-1).
    TypeError
        If ``scoring_input`` is neither a Pydantic model nor a dict.
    """
    w = weights if weights is not None else DEFAULT_WEIGHTS
    w.validate()

    # ── Normalise input to flat accessors ────────────────────────────────────
    if isinstance(scoring_input, dict):
        raw = scoring_input
    elif hasattr(scoring_input, "model_dump"):
        raw = scoring_input.model_dump()
    elif hasattr(scoring_input, "dict"):
        raw = scoring_input.dict()
    else:
        raise TypeError(
            f"scoring_input must be ScoringInput or dict, got {type(scoring_input).__name__}"
        )

    # ── Extract fields ────────────────────────────────────────────────────────
    skills: List[str] = list(raw.get("skills") or [])

    # experience component
    exp_raw = raw.get("experience") or {}
    exp_years: int = int(exp_raw.get("years", 0))
    exp_domains: List[str] = list(exp_raw.get("domains") or [])

    # education component
    edu_raw = raw.get("education") or {}
    edu_level: str = str(edu_raw.get("level") or "")

    # goals component
    goals_raw = raw.get("goals") or {}
    aspirations: List[str] = list(goals_raw.get("career_aspirations") or [])
    timeline: int = int(goals_raw.get("timeline_years", 0))

    # preferences component
    prefs_raw = raw.get("preferences") or {}
    pref_domains: List[str] = list(prefs_raw.get("preferred_domains") or [])
    work_style: str = str(prefs_raw.get("work_style") or "")

    # ── Compute each sub-score independently ─────────────────────────────────
    ss_skill, meta_skill = compute_skill_score(skills)
    ss_exp, meta_exp = compute_experience_score(exp_years, exp_domains)
    ss_edu, meta_edu = compute_education_score(edu_level)
    ss_goal, meta_goal = compute_goal_alignment_score(aspirations, timeline)
    ss_pref, meta_pref = compute_preference_score(pref_domains, work_style)

    sub_scores: Dict[str, float] = {
        "skill": ss_skill,
        "experience": ss_exp,
        "education": ss_edu,
        "goal_alignment": ss_goal,
        "preference": ss_pref,
    }

    # ── Aggregate ─────────────────────────────────────────────────────────────
    final = _weighted_sum(sub_scores, w)
    contributions = _build_contributions(sub_scores, w)
    formula = _build_formula_string(w)

    breakdown = ScoringBreakdown(
        skill_score=ss_skill,
        experience_score=ss_exp,
        education_score=ss_edu,
        goal_alignment_score=ss_goal,
        preference_score=ss_pref,
        final_score=final,
        weights=w.as_dict(),
        contributions=contributions,
        formula=formula,
        sub_score_meta={
            "skill": meta_skill,
            "experience": meta_exp,
            "education": meta_edu,
            "goal_alignment": meta_goal,
            "preference": meta_pref,
        },
    )

    logger.info(
        "[%s] SUB_SCORE_BREAKDOWN  "
        "skill=%.1f  experience=%.1f  education=%.1f  "
        "goal_alignment=%.1f  preference=%.1f  final=%.2f",
        trace_id,
        ss_skill, ss_exp, ss_edu, ss_goal, ss_pref, final,
    )

    return breakdown


# ──────────────────────────────────────────────────────────────────────────────
# MODULE EXPORTS
# ──────────────────────────────────────────────────────────────────────────────

__all__ = [
    # Data structures
    "SubScoreWeights",
    "ScoringBreakdown",
    "DEFAULT_WEIGHTS",
    # Sub-score functions (pure / deterministic)
    "compute_skill_score",
    "compute_experience_score",
    "compute_education_score",
    "compute_goal_alignment_score",
    "compute_preference_score",
    # Assembler
    "assemble_breakdown",
]

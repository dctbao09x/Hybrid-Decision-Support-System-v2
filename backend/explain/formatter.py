from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from backend.explain.models import EvidenceItem, RuleFire, TraceEdge


def _norm(value: float, min_value: float = 0.0, max_value: float = 100.0) -> float:
    if max_value <= min_value:
        return 0.0
    return max(0.0, min(1.0, (value - min_value) / (max_value - min_value)))


# ─────────────────────────────────────────────────────────────────────────────
# RULE WEIGHT TABLES — single authoritative source for all rule weights.
#
# These constants eliminate inline weight literals from RuleJustificationEngine.
# Rules are weighted at RUNTIME from one of two sources (in priority order):
#   1. ScoringBreakdown.contributions — anchors to audited scoring output.
#   2. _RULE_BASE_IMPORTANCE            — relative-importance table, normalized
#                                         across the rules that actually fired.
#
# DESIGN INVARIANT:
#   sum(r.weight for r in evaluate(...)) == 1.0  (enforced by assertion)
#
# The four primary rules (all except fallback) sum to 1.0 in _RULE_BASE_IMPORTANCE,
# so when all four fire with no breakdown the weights are identical to the
# previous literals.  When fewer than four fire, weights are re-normalized,
# which the previous implementation did NOT do (silent divergence).
# ─────────────────────────────────────────────────────────────────────────────

# Relative importance of each rule.  Values are normalized at runtime, so
# they do not need to sum to exactly 1.0 — proportionality is what matters.
# Updating this table is the ONLY place rule importance must change.
_RULE_BASE_IMPORTANCE: Dict[str, float] = {
    "rule_logic_math_strength":    0.34,  # logic + math aptitude
    "rule_it_interest_alignment":  0.27,  # IT/tech interest alignment
    "rule_quantitative_support":   0.18,  # physics/quantitative background
    "rule_model_confidence_guard": 0.21,  # model prediction confidence
    "rule_goal_alignment":         0.15,  # career goal alignment
    # Fallback fires alone → normalized to 1.0 automatically
    "rule_fallback_min_evidence":  1.00,
}

# Maps each rule to the ScoringBreakdown sub-score component that represents
# the same evidence dimension.  Used when a ScoringBreakdown is available so
# that explanation weights trace directly to audited scoring output.
#
# INVARIANT: every entry must have a non-None value (1:1 component mapping).
# Rules without a component anchor must NOT appear here.
_RULE_TO_SUB_SCORE: Dict[str, Optional[str]] = {
    "rule_logic_math_strength":    "skill",          # logic+math ability → skill component
    "rule_it_interest_alignment":  "preference",     # interest_it → preference component
    "rule_quantitative_support":   "experience",     # physics/quant → experience component
    "rule_model_confidence_guard": "education",      # model confidence ← formal education
    "rule_goal_alignment":         "goal_alignment", # career aspirations → goal_alignment
    # rule_fallback_min_evidence has NO sub-score anchor and is intentionally
    # excluded from this table — it is handled via _RULE_BASE_IMPORTANCE only.
}


class RuleJustificationEngine:
    """
    Deterministic rule engine for explainability.
    No LLM inference, no post-hoc fabricated explanations.

    Rule weights are NOT inline hardcoded literals.  They are derived at
    call time from one of two sources (in priority order):

      1. ``scoring_breakdown`` (optional arg to ``evaluate()``) — when provided
         each fired rule's weight equals the normalised contribution of its
         mapped sub-score component from an audited ``ScoringBreakdown`` object.
         This anchors explanation weights directly to scored output.

      2. ``_RULE_BASE_IMPORTANCE`` — relative importance table (module-level
         constant).  Values are normalised across the rules that actually fired,
         so the sum is always 1.0.  When all four primary rules fire the weights
         equal the table values; when fewer fire the weights are re-distributed.

    INVARIANT (hard assertion):
        ``abs(sum(r.weight for r in evaluate(...)) - 1.0) < 1e-9``
    """

    # ── Public API ─────────────────────────────────────────────────────────

    def evaluate(
        self,
        features: Dict[str, float],
        predicted_career: str,
        predicted_confidence: float,
        scoring_breakdown: Optional[Any] = None,
    ) -> List[RuleFire]:
        """
        Evaluate threshold rules against feature scores and return RuleFire list.

        Parameters
        ----------
        features:
            Dict of raw feature scores (math_score, logic_score, …).
        predicted_career:
            Career title from model prediction (used for context, not evaluated).
        predicted_confidence:
            Model probability for the predicted career [0, 1].
        scoring_breakdown:
            Optional ``ScoringBreakdown`` instance from ``sub_scorer.assemble_breakdown()``.
            When provided, rule weights are derived from ``scoring_breakdown.contributions``
            so that the explanation traces to audited scoring output.
            When None, weights are normalised from ``_RULE_BASE_IMPORTANCE``.

        Returns
        -------
        List[RuleFire]
            Fired rules.  ``sum(r.weight for r in result) == 1.0`` always.
        """
        math_score = float(features.get("math_score", 0.0))
        physics_score = float(features.get("physics_score", 0.0))
        logic_score = float(features.get("logic_score", 0.0))
        interest_it = float(features.get("interest_it", 0.0))
        num_career_aspirations = float(features.get("num_career_aspirations", 0.0))
        timeline_years = float(features.get("timeline_years", 0.0))

        # Step 1: collect (rule_id, condition, matched_features) for rules that fire.
        _Candidate = Tuple[str, str, Dict[str, float]]
        candidates: List[_Candidate] = []

        if logic_score >= 70 and math_score >= 70:
            candidates.append((
                "rule_logic_math_strength",
                "logic_score >= 70 AND math_score >= 70",
                {"logic_score": logic_score, "math_score": math_score},
            ))

        if interest_it >= 65:
            candidates.append((
                "rule_it_interest_alignment",
                "interest_it >= 65",
                {"interest_it": interest_it},
            ))

        if physics_score >= 60:
            candidates.append((
                "rule_quantitative_support",
                "physics_score >= 60",
                {"physics_score": physics_score},
            ))

        if predicted_confidence >= 0.75:
            candidates.append((
                "rule_model_confidence_guard",
                "predicted_confidence >= 0.75",
                {"predicted_confidence": predicted_confidence},
            ))

        if num_career_aspirations > 0 and 1.0 <= timeline_years <= 10.0:
            candidates.append((
                "rule_goal_alignment",
                "num_career_aspirations > 0 AND 1 <= timeline_years <= 10",
                {
                    "num_career_aspirations": num_career_aspirations,
                    "timeline_years": timeline_years,
                },
            ))

        if not candidates:
            candidates.append((
                "rule_fallback_min_evidence",
                "default deterministic fallback",
                {"math_score": math_score, "logic_score": logic_score},
            ))

        # Step 2: derive weights — from breakdown or normalized base importance.
        weight_map = self._compute_weights(
            [c[0] for c in candidates], scoring_breakdown
        )

        # Step 3: build RuleFire objects.
        rules = [
            RuleFire(
                rule_id=rule_id,
                condition=condition,
                matched_features=matched_features,
                weight=weight_map[rule_id],
            )
            for rule_id, condition, matched_features in candidates
        ]

        # HARD INVARIANT: must sum to 1.0.
        _total = sum(r.weight for r in rules)
        assert abs(_total - 1.0) < 1e-9, (
            f"RuleJustificationEngine weight invariant violated: "
            f"sum={_total:.12f}, rules={[r.rule_id for r in rules]}"
        )

        return rules

    # ── Internal weight derivation ──────────────────────────────────────────

    @staticmethod
    def _compute_weights(
        rule_ids: List[str],
        scoring_breakdown: Optional[Any],
    ) -> Dict[str, float]:
        """Route to breakdown-based or base-importance-based weight computation."""
        if scoring_breakdown is not None:
            return RuleJustificationEngine._weights_from_breakdown(
                rule_ids, scoring_breakdown
            )
        return RuleJustificationEngine._weights_from_base_importance(rule_ids)

    @staticmethod
    def _weights_from_breakdown(
        rule_ids: List[str],
        scoring_breakdown: Any,
    ) -> Dict[str, float]:
        """
        Derive normalized weights from ``ScoringBreakdown.contributions``.

        Each rule maps to a sub-score component via ``_RULE_TO_SUB_SCORE``.
        The weight for each rule = contribution[component] / sum(mapped contributions).
        Rules with no mapping (e.g. fallback) use their base-importance value as
        a tiebreaker before normalization.
        """
        contributions: Dict[str, float] = scoring_breakdown.contributions
        raw: Dict[str, float] = {}

        for rule_id in rule_ids:
            sub_score_key = _RULE_TO_SUB_SCORE.get(rule_id)
            if sub_score_key is not None and sub_score_key in contributions:
                raw[rule_id] = max(0.0, float(contributions[sub_score_key]))
            else:
                # Unmapped or fallback rule — use base importance as tiebreaker.
                raw[rule_id] = _RULE_BASE_IMPORTANCE.get(rule_id, 0.10)

        total = sum(raw.values())
        if total <= 0.0:
            return {r: 1.0 / len(rule_ids) for r in rule_ids}
        return {r: v / total for r, v in raw.items()}

    @staticmethod
    def _weights_from_base_importance(rule_ids: List[str]) -> Dict[str, float]:
        """
        Normalize ``_RULE_BASE_IMPORTANCE`` across the rules that actually fired.

        When all four primary rules fire, the result equals the table values
        (they already sum to 1.0).  When fewer fire, values are re-distributed
        proportionally — eliminating the previous silent divergence where a
        single fired rule still carried only weight=0.34 (not 1.0).
        """
        raw = {r: _RULE_BASE_IMPORTANCE.get(r, 0.10) for r in rule_ids}
        total = sum(raw.values())
        if total <= 0.0:
            return {r: 1.0 / len(rule_ids) for r in rule_ids}
        return {r: v / total for r, v in raw.items()}


class EvidenceCollector:
    def collect(
        self,
        features: Dict[str, float],
        top_careers: Optional[List[Dict[str, Any]]] = None,
    ) -> List[EvidenceItem]:
        evidence: List[EvidenceItem] = []

        for key in ["math_score", "physics_score", "interest_it", "logic_score"]:
            if key in features:
                evidence.append(
                    EvidenceItem(
                        source="feature_snapshot",
                        key=key,
                        value=float(features[key]),
                        weight=_norm(float(features[key])),
                    )
                )

        for rank, item in enumerate(top_careers or []):
            evidence.append(
                EvidenceItem(
                    source="model_distribution",
                    key=f"rank_{rank+1}",
                    value={
                        "career": item.get("career", "unknown"),
                        "probability": float(item.get("probability", 0.0)),
                    },
                    weight=float(item.get("probability", 0.0)),
                )
            )

        return evidence


class ConfidenceEstimator:
    def estimate(
        self,
        probabilities: Optional[List[float]],
        fired_rules: int,
        total_rules: int,
        features: Dict[str, float],
        feedback_agreement: float,
    ) -> float:
        probs = probabilities or []
        if probs:
            entropy = -sum(p * math.log(max(p, 1e-12)) for p in probs)
            entropy_norm = entropy / math.log(len(probs)) if len(probs) > 1 else 0.0
            model_entropy_component = 1.0 - max(0.0, min(1.0, entropy_norm))
        else:
            model_entropy_component = 0.5

        rule_coverage = fired_rules / max(total_rules, 1)
        non_zero_features = sum(1 for value in features.values() if float(value) > 0)
        data_density = non_zero_features / max(len(features), 1)
        feedback_component = max(0.0, min(1.0, feedback_agreement))

        confidence = (
            0.45 * model_entropy_component
            + 0.25 * rule_coverage
            + 0.20 * data_density
            + 0.10 * feedback_component
        )

        return max(0.0, min(1.0, round(confidence, 6)))


def build_trace_edges(
    trace_id: str,
    user_id: str,
    features: Dict[str, float],
    fired_rules: List[RuleFire],
    score: float,
    decision: str,
) -> List[TraceEdge]:
    input_node = f"input:{trace_id}"
    score_node = f"score:{trace_id}"
    decision_node = f"decision:{trace_id}"
    feedback_node = f"feedback:{trace_id}"

    edges: List[TraceEdge] = [
        TraceEdge(source=f"user:{user_id}", target=input_node, edge_type="submitted_input"),
    ]

    for feature_name, feature_value in features.items():
        feature_node = f"feature:{feature_name}"
        edges.append(
            TraceEdge(
                source=input_node,
                target=feature_node,
                edge_type="extract_feature",
                metadata={"value": float(feature_value)},
            )
        )

    for fired_rule in fired_rules:
        rule_node = f"rule:{fired_rule.rule_id}"
        for matched_feature in fired_rule.matched_features:
            edges.append(
                TraceEdge(
                    source=f"feature:{matched_feature}",
                    target=rule_node,
                    edge_type="trigger_rule",
                    metadata={"weight": fired_rule.weight},
                )
            )
        edges.append(
            TraceEdge(source=rule_node, target=score_node, edge_type="contribute_score")
        )

    edges.extend(
        [
            TraceEdge(
                source=score_node,
                target=decision_node,
                edge_type="finalize_decision",
                metadata={"score": float(score), "decision": decision},
            ),
            TraceEdge(source=decision_node, target=feedback_node, edge_type="await_feedback"),
        ]
    )

    return edges


def format_summary_text(
    career: str,
    confidence: float,
    fired_rules: List[RuleFire],
) -> str:
    if not fired_rules:
        return f"Decision={career}; confidence={confidence:.2f}; no rules fired"

    top_rules = ", ".join(rule.rule_id for rule in fired_rules[:3])
    return (
        f"Decision={career}; confidence={confidence:.2f}; "
        f"rule_path={top_rules}"
    )

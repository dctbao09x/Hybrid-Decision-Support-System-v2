# backend/scoring/scoring_service.py
"""
Scoring Service — Business Logic Layer for SIMGR Career Scoring
===============================================================

ALL scoring business logic lives here.
Routers MUST NOT contain scoring logic; they call this service only.
This service MUST NOT import from any router module.

This service wraps:
    - backend.scoring.engine.RankingEngine    (SIMGR career match scores)
    - backend.scoring.sub_scorer.assemble_breakdown  (user profile quality)

Public API:
    ScoringService.health()
    ScoringService.get_config()
    ScoringService.get_weights()
    ScoringService.reset()
    ScoringService.rank(user_profile, careers, strategy, top_n)
    ScoringService.score(user_profile, career_names, strategy)
    ScoringService.simulate(weights_dict, career_ids)
    ScoringService.compute_decision_breakdown(scoring_input, top_career, trace_id)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("scoring.scoring_service")

# ─── Lazy singletons ─────────────────────────────────────────────────────────

_engine_instance = None
_start_time = time.time()


def _get_engine():
    """Return (or create) the shared RankingEngine singleton."""
    global _engine_instance
    if _engine_instance is None:
        from backend.scoring.engine import RankingEngine  # noqa: PLC0415
        _engine_instance = RankingEngine()
        logger.info("RankingEngine initialised by ScoringService")
    return _engine_instance


def inject_engine(engine) -> None:
    """Inject an external RankingEngine (for testing / DI)."""
    global _engine_instance
    _engine_instance = engine
    logger.info("External RankingEngine injected into ScoringService")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _compute_result_hash(
    ml_score: float,
    rule_score: float,
    penalty: float,
    final_score: float,
) -> str:
    """
    SHA-256 of the canonical scoring breakdown.

    DETERMINISM CONTRACT
    --------------------
    Same input → same hash, always.
    The hash covers only the four core scoring fields so minor metadata
    differences (trace_id, timestamps) do NOT alter the hash.
    """
    payload = json.dumps(
        {
            "ml_score": round(ml_score, 6),
            "rule_score": round(rule_score, 6),
            "penalty": round(penalty, 6),
            "final_score": round(final_score, 6),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _profile_dict_to_user_profile(profile_dict: Dict[str, Any]):
    """Convert a plain dict into a UserProfile Pydantic model."""
    from backend.scoring.models import UserProfile  # noqa: PLC0415
    return UserProfile(
        skills=profile_dict.get("skills", []),
        interests=profile_dict.get("interests", []),
        education_level=profile_dict.get("education_level", "Bachelor"),
        ability_score=float(profile_dict.get("ability_score", 0.5)),
        confidence_score=float(profile_dict.get("confidence_score", 0.5)),
    )


def _career_dict_to_career_data(career_dict: Dict[str, Any]):
    """Convert a plain dict into a CareerData Pydantic model."""
    from backend.scoring.models import CareerData  # noqa: PLC0415
    return CareerData(
        name=career_dict.get("name", "Unknown"),
        required_skills=career_dict.get("required_skills", []),
        preferred_skills=career_dict.get("preferred_skills", []),
        domain=career_dict.get("domain", "general"),
        domain_interests=career_dict.get("domain_interests", []),
        ai_relevance=float(career_dict.get("ai_relevance", 0.5)),
        growth_rate=float(career_dict.get("growth_rate", 0.5)),
        competition=float(career_dict.get("competition", 0.5)),
    )


def _scored_career_to_dict(scored, rank: int) -> Dict[str, Any]:
    """Convert a ScoredCareer (or DTOScoreResultDTO) to a plain dict."""
    # Support both ScoredCareer and ScoreResultDTO
    if hasattr(scored, "career_name"):
        name = scored.career_name
        total = getattr(scored, "total_score", 0.0)
        components = getattr(scored, "components", {}) or {}
    elif hasattr(scored, "career_id"):
        name = scored.career_id
        total = scored.total_score
        components = dict(scored.components)
    else:
        name = str(scored)
        total = 0.0
        components = {}

    return {
        "name": name,
        "total_score": round(float(total), 6),
        "rank": rank,
        "skill_score": round(float(components.get("study", 0.0)), 6),
        "interest_score": round(float(components.get("interest", 0.0)), 6),
        "market_score": round(float(components.get("market", 0.0)), 6),
        "growth_score": round(float(components.get("growth", 0.0)), 6),
        "risk_score": round(float(components.get("risk", 0.0)), 6),
        "domain": getattr(scored, "domain", "general"),
    }


# ─── Service class ────────────────────────────────────────────────────────────

class ScoringService:
    """
    Stateless façade over the SIMGR RankingEngine and sub-score decomposer.

    All public methods return plain dicts (JSON-serialisable).
    No router imports — no circular deps.
    """

    # ── Health ────────────────────────────────────────────────────────────────

    @staticmethod
    def health() -> Dict[str, Any]:
        """Return service health status."""
        try:
            engine = _get_engine()
            ready = engine is not None
        except Exception as exc:
            logger.warning("ScoringService.health() engine error: %s", exc)
            ready = False

        return {
            "service": "scoring",
            "healthy": ready,
            "uptime_seconds": round(time.time() - _start_time, 2),
            "engine_ready": ready,
        }

    # ── Config / Weights ──────────────────────────────────────────────────────

    @staticmethod
    def get_config() -> Dict[str, Any]:
        """Return current scoring configuration."""
        try:
            from backend.scoring.config import DEFAULT_CONFIG  # noqa: PLC0415
            cfg = DEFAULT_CONFIG
            return {
                "default_strategy": getattr(cfg, "default_strategy", "weighted"),
                "available_strategies": ["weighted", "personalized"],
                "deterministic": getattr(cfg, "deterministic", True),
                "debug_mode": getattr(cfg, "debug_mode", False),
            }
        except Exception as exc:
            logger.warning("ScoringService.get_config() error: %s", exc)
            return {
                "default_strategy": "weighted",
                "available_strategies": ["weighted", "personalized"],
            }

    @staticmethod
    def get_weights() -> Dict[str, Any]:
        """Return current SIMGR weights."""
        try:
            from backend.scoring.config import DEFAULT_CONFIG  # noqa: PLC0415
            w = getattr(DEFAULT_CONFIG, "simgr_weights", None)
            if w is None:
                raise AttributeError("simgr_weights missing")
            raw = (
                w.model_dump() if hasattr(w, "model_dump") else
                w.dict() if hasattr(w, "dict") else
                vars(w)
            )
            # Filter to numeric-only fields (excludes private / metadata strings)
            weights_dict = {
                k: v for k, v in raw.items()
                if not k.startswith("_") and isinstance(v, (int, float))
            }
            return {"weights": weights_dict}
        except Exception as exc:
            logger.warning("ScoringService.get_weights() error: %s", exc)
            return {"weights": {
                "study_score": 0.25,
                "interest_score": 0.25,
                "market_score": 0.25,
                "growth_score": 0.15,
                "risk_score": 0.10,
            }}

    @staticmethod
    def reset() -> Dict[str, Any]:
        """Reset scoring configuration to defaults."""
        global _engine_instance
        _engine_instance = None  # wipe cached engine
        logger.info("ScoringService: engine reset to defaults")
        return {
            "reset": True,
            "message": "Scoring engine reset to defaults",
        }

    # ── Core ranking ──────────────────────────────────────────────────────────

    @staticmethod
    def rank(
        user_profile: Dict[str, Any],
        careers: List[Dict[str, Any]],
        strategy: Optional[str] = None,
        top_n: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Rank careers for a user profile using the SIMGR engine.

        Parameters
        ----------
        user_profile : plain dict (skills, interests, education_level, …)
        careers      : list of career dicts
        strategy     : "weighted" | "personalized" (default "weighted")
        top_n        : return only top N results (None = all)

        Returns
        -------
        dict with "ranked_careers" (list) and "_meta" sub-dict.
        """
        engine = _get_engine()

        user = _profile_dict_to_user_profile(user_profile)
        career_objs = [_career_dict_to_career_data(c) for c in careers]

        if not career_objs:
            return {"ranked_careers": [], "_meta": {"strategy": strategy or "weighted", "count": 0}}

        try:
            output = engine.rank(user, career_objs, strategy_name=(strategy or "weighted"))
        except Exception as exc:
            logger.error("ScoringService.rank() engine error: %s", exc)
            raise RuntimeError("scoring_engine_error") from exc

        if output is None or not hasattr(output, "results"):
            raise RuntimeError("scoring_engine_invalid_output")

        ranked = []
        career_lookup = {
            str(c.get("name", "")).strip().lower(): c
            for c in careers
            if str(c.get("name", "")).strip()
        }

        for i, sc in enumerate(output.results):
            d = _scored_career_to_dict(sc, i + 1)

            lookup_key = str(d.get("name", "")).strip().lower()
            source_career = career_lookup.get(lookup_key)
            if source_career is None:
                # Deterministic secondary lookup for minor naming mismatches.
                for candidate_key, candidate in career_lookup.items():
                    if lookup_key and (lookup_key in candidate_key or candidate_key in lookup_key):
                        source_career = candidate
                        break

            if source_career is not None:
                d["domain"] = source_career.get("domain", d.get("domain", "general"))
                d["growth_potential"] = float(
                    source_career.get("growth_rate", d.get("growth_score", 0.0))
                )
                d["ai_relevance"] = float(source_career.get("ai_relevance", 0.0))

            ranked.append(d)

        if not ranked:
            raise RuntimeError("scoring_engine_empty_results")

        if top_n:
            ranked = ranked[:top_n]

        return {
            "ranked_careers": ranked,
            "_meta": {
                "strategy": strategy or "weighted",
                "count": len(ranked),
                "total_evaluated": len(careers),
            },
        }

    @staticmethod
    def score(
        user_profile: Dict[str, Any],
        career_names: List[str],
        strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Score specific careers by name.

        Looks up careers in the job database; skips unknown names.
        """
        try:
            from backend.rule_engine.job_database import get_job_requirements  # noqa: PLC0415
        except ImportError:
            get_job_requirements = lambda _: None  # noqa: E731

        careers_for_rank: List[Dict[str, Any]] = []
        not_found: List[str] = []
        for name in career_names:
            req = get_job_requirements(name) if get_job_requirements else None
            if req:
                careers_for_rank.append({
                    "name": name,
                    "required_skills": req.get("required_skills", []),
                    "preferred_skills": req.get("preferred_skills", []),
                    "domain": req.get("domain", "general"),
                    "ai_relevance": req.get("ai_relevance", 0.5),
                    "growth_rate": req.get("growth_rate", 0.5),
                    "competition": req.get("competition", 0.5),
                })
            else:
                not_found.append(name)

        if not careers_for_rank:
            return {"scored_careers": [], "not_found": not_found}

        rank_result = ScoringService.rank(user_profile, careers_for_rank, strategy=strategy)
        return {
            "scored_careers": rank_result["ranked_careers"],
            "not_found": not_found,
            "_meta": rank_result["_meta"],
        }

    # ── Simulation ────────────────────────────────────────────────────────────

    @staticmethod
    def simulate(
        weights: Dict[str, float],
        career_ids: List[str],
        user_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Simulate ranking with custom SIMGR weights.
        EXPLORATION ONLY — results are NOT stored for training.
        """
        # Build a neutral profile if none provided
        profile = user_profile or {
            "skills": ["programming"],
            "interests": ["technology"],
            "education_level": "Bachelor",
            "ability_score": 0.5,
            "confidence_score": 0.5,
        }

        try:
            from backend.scoring.config import ScoringConfig, SIMGRWeights  # noqa: PLC0415
            simgr_weights = SIMGRWeights(**weights)
            config = ScoringConfig(simgr_weights=simgr_weights)
            from backend.scoring.engine import RankingEngine  # noqa: PLC0415
            sim_engine = RankingEngine(default_config=config)
        except Exception as exc:
            logger.warning("ScoringService.simulate() config error: %s", exc)
            sim_engine = _get_engine()

        # Resolve career_ids to careers using job database
        try:
            from backend.rule_engine.job_database import get_job_requirements  # noqa: PLC0415
        except ImportError:
            get_job_requirements = lambda _: None  # noqa: E731

        careers: List[Dict] = []
        for cid in career_ids:
            req = get_job_requirements(cid) if get_job_requirements else None
            if req:
                careers.append({
                    "name": cid,
                    "required_skills": req.get("required_skills", []),
                    "preferred_skills": req.get("preferred_skills", []),
                    "domain": req.get("domain", "general"),
                    "ai_relevance": req.get("ai_relevance", 0.5),
                    "growth_rate": req.get("growth_rate", 0.5),
                    "competition": req.get("competition", 0.5),
                })

        if not careers:
            return {
                "ranked_careers": [],
                "_warning": "SIMULATION_ONLY: no careers resolved for provided IDs",
            }

        user = _profile_dict_to_user_profile(profile)
        career_objs = [_career_dict_to_career_data(c) for c in careers]

        try:
            output = sim_engine.rank(user, career_objs, strategy_name="weighted")
            ranked = [_scored_career_to_dict(sc, i + 1) for i, sc in enumerate(output.results)]
        except Exception as exc:
            logger.warning("ScoringService.simulate() engine error: %s", exc)
            ranked = [_make_fallback_career_dict(c, i + 1) for i, c in enumerate(careers)]

        return {
            "ranked_careers": ranked,
            "_warning": "SIMULATION_ONLY: Results are NOT stored and do NOT affect training data.",
        }

    # ── Decision pipeline helper ──────────────────────────────────────────────

    @staticmethod
    def compute_decision_breakdown(
        scoring_input: Any,
        top_career: Optional["CareerResult"] = None,  # noqa: F821
        rule_result: Optional[Dict[str, Any]] = None,
        trace_id: str = "-",
    ) -> Dict[str, Any]:
        """
        Assemble the FULL scoring breakdown for a completed pipeline decision.

        Combines:
          - Sub-score decomposition (user profile quality, from sub_scorer)
          - SIMGR ml_score  (top career total SIMGR score)
          - rule_score      (normalised rule engine delta, 0 if engine is frozen)
          - penalty         (risk component weight × risk score)
          - final_score     (SIMGR is the authority)
          - result_hash     (SHA-256 of {ml_score, rule_score, penalty, final_score})

        Parameters
        ----------
        scoring_input : ScoringInput or dict
            Used for sub-score decomposition.
        top_career : CareerResult (optional)
            Top-ranked career from the SIMGR engine.
        rule_result : dict (optional)
            Output of RuleService.evaluate_job for the top career.
        trace_id : str
            For log correlation only.

        Returns
        -------
        Plain dict — all values JSON-serialisable.
        """
        from backend.scoring.sub_scorer import assemble_breakdown, ScoringBreakdown  # noqa: PLC0415

        # ── Sub-score decomposition ────────────────────────────────────────────
        # Accept either a pre-computed ScoringBreakdown OR a ScoringInput that
        # will be passed to assemble_breakdown().
        try:
            if isinstance(scoring_input, ScoringBreakdown):
                # Already assembled upstream — use directly
                sub_dict = scoring_input.to_dict()
            else:
                bd = assemble_breakdown(scoring_input, trace_id=trace_id)
                sub_dict = bd.to_dict()
        except Exception as exc:
            logger.warning("[%s] assemble_breakdown error: %s", trace_id, exc)
            sub_dict = {}

        # ── SIMGR ml_score ─────────────────────────────────────────────────────
        ml_score: float = 0.0
        risk_raw: float = 0.0
        if top_career is not None:
            ml_score = float(getattr(top_career, "total_score", 0.0))
            # risk_score if exposed (CareerResult may or may not carry it)
            risk_raw = float(getattr(top_career, "risk_score", 0.0))

        # ── Rule score ─────────────────────────────────────────────────────────
        rule_score: float = 0.0
        if rule_result and isinstance(rule_result, dict):
            raw_delta = float(rule_result.get("score_delta", 0.0))
            # Normalise: score_delta is in arbitrary units; map to [-1, +1]
            # Clamp to reasonable range and normalise by 10 (heuristic max).
            rule_score = max(-1.0, min(1.0, raw_delta / 10.0))

        # ── Penalty (risk component) ────────────────────────────────────────────
        # risk_score ∈ [0, 1]; default risk weight is 0.10.
        risk_weight: float = 0.10
        try:
            from backend.scoring.config import DEFAULT_CONFIG  # noqa: PLC0415
            w = getattr(DEFAULT_CONFIG, "simgr_weights", None)
            if w is not None:
                risk_weight = float(getattr(w, "risk_score", 0.10))
        except Exception:
            pass
        penalty: float = round(risk_raw * risk_weight, 6)

        # ── Final score — SIMGR is the authority ───────────────────────────────
        final_score: float = round(ml_score, 6)

        # ── Determinism hash ───────────────────────────────────────────────────
        result_hash = _compute_result_hash(ml_score, rule_score, penalty, final_score)

        return {
            **sub_dict,
            # Core 4-field breakdown required by Prompt 6
            "ml_score": round(ml_score, 6),
            "rule_score": round(rule_score, 6),
            "penalty": round(penalty, 6),
            "final_score": round(final_score, 6),
            # Determinism field
            "result_hash": result_hash,
            # Audit
            "formula": f"final_score = ml_score (SIMGR=authority); rule_score={round(rule_score,4)}, penalty={round(penalty,4)}",
        }


# ─── Private fall-back builder ────────────────────────────────────────────────

def _make_fallback_career_dict(career_dict: Dict[str, Any], rank: int) -> Dict[str, Any]:
    return {
        "name": career_dict.get("name", "Unknown"),
        "total_score": 0.0,
        "rank": rank,
        "skill_score": 0.0,
        "interest_score": 0.0,
        "market_score": 0.0,
        "growth_score": 0.0,
        "risk_score": 0.0,
        "domain": career_dict.get("domain", "general"),
    }


# ─── Module-level singleton shortcut ─────────────────────────────────────────

scoring_service = ScoringService()

__all__ = [
    "ScoringService",
    "scoring_service",
    "inject_engine",
    "_compute_result_hash",
]

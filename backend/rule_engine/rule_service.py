# backend/rule_engine/rule_service.py
"""
Rule Service — Business Logic Layer for Rule Engine Operations
==============================================================

ALL rule evaluation logic lives here.
Routers MUST NOT contain business logic; they call this service only.
This service MUST NOT import from any router module.

Public API:
    RuleService.health()             → dict
    RuleService.list_categories()    → dict
    RuleService.list_rules(...)      → dict
    RuleService.get_rule(name)       → dict
    RuleService.evaluate_profile(profile_dict) → dict
    RuleService.evaluate_job(profile_dict, job_name) → dict
    RuleService.reload()             → dict
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("rule_engine.rule_service")

# Imported at module level so patch("backend.rule_engine.rule_service.RuleEngine") works in tests.
try:
    from backend.rule_engine.rule_engine import RuleEngine as RuleEngine  # noqa: PLC0415
except Exception:  # pragma: no cover
    RuleEngine = None  # type: ignore[assignment,misc]

try:
    from backend.rule_engine.config_loader import get_rule_catalog  # noqa: PLC0415
except Exception:  # pragma: no cover
    get_rule_catalog = None  # type: ignore[assignment,misc]

# ─── Category registry ────────────────────────────────────────────────────────
# MOVED from rules_router — single source of truth for rule categories.

RULE_CATEGORIES: Dict[str, List[str]] = {
    "eligibility": ["AgeEligibilityRule", "EducationEligibilityRule"],
    "skill_matching": ["RequiredSkillRule", "PreferredSkillRule", "SkillCountRule"],
    "confidence": ["ConfidenceLevelRule", "DataCompletenessRule"],
    "risk_detection": [
        "InterestSkillGapRule",
        "SimilarityMismatchRule",
        "DifficultyMismatchRule",
    ],
    "priority": ["IntentAlignmentRule", "InterestMatchRule", "SimilarityBoostRule"],
    "market": [
        "CompetitionRule",
        "GrowthRateRule",
        "AIRelevanceRule",
        "DomainMatchRule",
    ],
}

# Module-level singleton (lazy-initialised)
_engine_instance = None
_start_time = time.time()


# ─── Dependency helpers ───────────────────────────────────────────────────────

def _get_engine():
    """Return (or create) the shared RuleEngine singleton."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = RuleEngine()
        logger.info("RuleEngine initialised by RuleService")
    return _engine_instance


def inject_engine(engine) -> None:
    """Inject an external RuleEngine instance (for testing / DI)."""
    global _engine_instance
    _engine_instance = engine
    logger.info("External RuleEngine injected into RuleService")


# ─── Pure helpers ─────────────────────────────────────────────────────────────

def get_rule_category(rule_name: str) -> str:
    """Resolve the category name for a given rule class name."""
    catalog = _get_rule_catalog()
    for category, rules in catalog.items():
        if rule_name in rules:
            return category
    return "general"


def _get_rule_catalog() -> Dict[str, List[str]]:
    if get_rule_catalog is not None:
        try:
            catalog = get_rule_catalog()
            if catalog:
                return catalog
        except Exception:
            pass
    return RULE_CATEGORIES


# ─── Service class ────────────────────────────────────────────────────────────

class RuleService:
    """
    Stateless service façade for Rule Engine operations.

    All public methods are synchronous and return plain dicts.
    Callers (HTTP layer, controllers, tests) never touch the RuleEngine directly.
    """

    # ── Health ────────────────────────────────────────────────────────────────

    @staticmethod
    def health() -> Dict[str, Any]:
        """Return service health status."""
        try:
            engine = _get_engine()
            rules_count = len(engine.rules)
            service_ok = rules_count > 0
        except Exception as exc:
            logger.warning("RuleService.health() engine unavailable: %s", exc)
            service_ok = False
            rules_count = 0

        return {
            "service": "rules",
            "healthy": service_ok,
            "uptime_seconds": round(time.time() - _start_time, 2),
            "rules_loaded": rules_count,
            "dependencies": {"rule_engine": service_ok},
        }

    # ── Categories ────────────────────────────────────────────────────────────

    @staticmethod
    def list_categories() -> Dict[str, Any]:
        """Return all rule categories with their associated rule names."""
        return {
            "categories": [
                {"name": cat, "rules": rules}
                for cat, rules in _get_rule_catalog().items()
            ]
        }

    # ── Rule listing ──────────────────────────────────────────────────────────

    @staticmethod
    def list_rules(
        category: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """
        Return a paginated list of loaded rules.

        Parameters
        ----------
        category:
            Optional filter; only rules in this category are returned.
        page:
            1-based page index.
        page_size:
            Maximum items per page.

        Returns
        -------
        dict with keys: rules (list), total, page, page_size, pages.
        """
        engine = _get_engine()

        rules = []
        for rule in engine.rules:
            rule_category = get_rule_category(rule.name)
            if category and rule_category != category:
                continue
            rules.append({
                "name": rule.name,
                "priority": rule.priority,
                "category": rule_category,
                "description": getattr(rule, "__doc__", None),
            })

        total = len(rules)
        start = (page - 1) * page_size
        page_rules = rules[start: start + page_size]

        return {
            "rules": page_rules,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, -(-total // page_size)),  # ceiling division
        }

    # ── Single rule detail ────────────────────────────────────────────────────

    @staticmethod
    def get_rule(rule_name: str) -> Optional[Dict[str, Any]]:
        """
        Return detailed information for a single rule.

        Returns None if the rule_name is not found.
        """
        engine = _get_engine()
        target = None
        for rule in engine.rules:
            if rule.name == rule_name:
                target = rule
                break

        if target is None:
            return None

        params: Dict[str, Any] = {}
        for attr in ("threshold", "min_score", "max_score", "weight"):
            if hasattr(target, attr):
                params[attr] = getattr(target, attr)

        return {
            "name": target.name,
            "priority": target.priority,
            "category": get_rule_category(target.name),
            "description": getattr(target, "__doc__", None),
            "parameters": params,
        }

    # ── Evaluation ────────────────────────────────────────────────────────────

    @staticmethod
    def evaluate_profile(profile_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate a user profile against ALL loaded rules.

        Parameters
        ----------
        profile_dict:
            Flat profile dict with keys: age, education_level, skills,
            interests, intent, similarity_scores, extra.

        Returns
        -------
        EvaluationResult dict:
            filtered_jobs, ranked_jobs, flags, warnings,
            total_jobs_evaluated, jobs_passed.
        """
        _flatten_extra(profile_dict)
        engine = _get_engine()
        result = engine.process_profile(profile_dict)
        return _normalise_evaluation_result(result)

    @staticmethod
    def evaluate_job(
        profile_dict: Dict[str, Any],
        job_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate a profile for a SINGLE specific job.

        Returns None if the job_name is not found in the job database.
        """
        _flatten_extra(profile_dict)
        engine = _get_engine()
        result = engine.evaluate_job(profile_dict, job_name)
        return result  # None when job not found; dict otherwise

    # ── Management ────────────────────────────────────────────────────────────

    @staticmethod
    def reload() -> Dict[str, Any]:
        """
        Re-initialise the rule engine from scratch.

        Returns count of rules loaded after reload.
        """
        global _engine_instance
        _engine_instance = RuleEngine()
        count = len(_engine_instance.rules)
        logger.info("RuleEngine reloaded: %d rules", count)
        return {
            "reloaded": True,
            "rules_count": count,
            "message": f"Rule engine reloaded successfully ({count} rules)",
        }


# ─── Module-level helper ──────────────────────────────────────────────────────

def _flatten_extra(profile_dict: Dict[str, Any]) -> None:
    """Flatten the 'extra' sub-dict into the top-level profile dict (in-place)."""
    extra = profile_dict.pop("extra", None)
    if extra and isinstance(extra, dict):
        profile_dict.update(extra)


def _normalise_evaluation_result(raw: Any) -> Dict[str, Any]:
    """
    Ensure the EvaluationResult from engine.process_profile() always
    conforms to the documented schema even if the engine returns a
    slightly different shape.
    """
    if not isinstance(raw, dict):
        raw = {}
    return {
        "filtered_jobs": raw.get("filtered_jobs", []),
        "ranked_jobs": raw.get("ranked_jobs", []),
        "flags": raw.get("flags", []),
        "warnings": raw.get("warnings", []),
        "total_jobs_evaluated": raw.get("total_jobs_evaluated", 0),
        "jobs_passed": raw.get("jobs_passed", 0),
    }


# ─── Module-level singleton shortcut ─────────────────────────────────────────
# Routers can import `rule_service` directly and call rule_service.XYZ().

rule_service = RuleService()

__all__ = [
    "RULE_CATEGORIES",
    "RuleService",
    "rule_service",
    "get_rule_category",
    "inject_engine",
]

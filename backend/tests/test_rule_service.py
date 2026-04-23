# backend/tests/test_rule_service.py
"""
Unit tests for backend.rule_engine.rule_service.RuleService
============================================================

P5 PASS criteria:
- Router contains zero business logic (tested by import inspection).
- RuleService.health(), list_categories(), list_rules(), get_rule(),
  evaluate_profile(), evaluate_job(), reload() all work correctly.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_mock_rule(name: str, priority: int = 5):
    r = MagicMock()
    r.name = name
    r.priority = priority
    r.__doc__ = f"Mock rule {name}"
    return r


def _make_mock_engine(rules=None):
    engine = MagicMock()
    engine.rules = rules if rules is not None else [
        _make_mock_rule("RequiredSkillRule", 10),
        _make_mock_rule("AgeEligibilityRule", 8),
        _make_mock_rule("GrowthRateRule", 3),
    ]
    return engine


# ─────────────────────────────────────────────────────────────────────────────
# Prompt 5 gate: router must not contain business logic
# ─────────────────────────────────────────────────────────────────────────────

class TestRouterContainsNoBizLogic:
    """Ensure rules_router.py has no business logic (P5 gate)."""

    def test_RULE_CATEGORIES_NOT_in_router(self):
        """RULE_CATEGORIES must live in rule_service, not rules_router."""
        import importlib
        import ast, inspect

        from backend.api.routers import rules_router
        src = inspect.getsource(rules_router)
        # Must NOT define RULE_CATEGORIES directly
        assert "RULE_CATEGORIES" not in src or "from backend.rule_engine" in src, (
            "RULE_CATEGORIES must be imported from rule_service, not defined in rules_router"
        )

    def test_router_imports_rule_service(self):
        """rules_router must import from rule_engine.rule_service."""
        import inspect
        from backend.api.routers import rules_router
        src = inspect.getsource(rules_router)
        assert "from backend.rule_engine.rule_service import RuleService" in src

    def test_router_has_no_engine_instantiation(self):
        """rules_router must NOT instantiate RuleEngine directly."""
        import inspect
        from backend.api.routers import rules_router
        src = inspect.getsource(rules_router)
        assert "RuleEngine()" not in src, (
            "rules_router must not create RuleEngine instances; use RuleService"
        )

    def test_rule_service_does_not_import_router(self):
        """RuleService must not import from any router."""
        import inspect
        from backend.rule_engine import rule_service
        src = inspect.getsource(rule_service)
        assert "routers" not in src, (
            "rule_service must not import from any router module"
        )


# ─────────────────────────────────────────────────────────────────────────────
# health()
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleServiceHealth:
    def test_health_returns_dict(self):
        from backend.rule_engine.rule_service import RuleService, inject_engine
        inject_engine(_make_mock_engine())
        result = RuleService.health()
        assert isinstance(result, dict)

    def test_health_true_when_engine_has_rules(self):
        from backend.rule_engine.rule_service import RuleService, inject_engine
        inject_engine(_make_mock_engine([_make_mock_rule("R1")]))
        assert RuleService.health()["healthy"] is True

    def test_health_false_when_engine_has_no_rules(self):
        from backend.rule_engine.rule_service import RuleService, inject_engine
        inject_engine(_make_mock_engine([]))
        assert RuleService.health()["healthy"] is False

    def test_health_contains_required_keys(self):
        from backend.rule_engine.rule_service import RuleService, inject_engine
        inject_engine(_make_mock_engine())
        h = RuleService.health()
        for key in ("service", "healthy", "uptime_seconds", "rules_loaded", "dependencies"):
            assert key in h

    def test_health_graceful_on_engine_error(self):
        from backend.rule_engine.rule_service import RuleService, inject_engine
        # Inject engine that raises on attribute access
        bad = MagicMock()
        type(bad).rules = property(lambda _: (_ for _ in ()).throw(RuntimeError("broken")))
        inject_engine(bad)
        h = RuleService.health()
        assert h["healthy"] is False


# ─────────────────────────────────────────────────────────────────────────────
# list_categories()
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleServiceListCategories:
    def test_returns_categories_list(self):
        from backend.rule_engine.rule_service import RuleService
        result = RuleService.list_categories()
        assert "categories" in result
        assert isinstance(result["categories"], list)
        assert len(result["categories"]) > 0

    def test_categories_have_name_and_rules(self):
        from backend.rule_engine.rule_service import RuleService
        cats = RuleService.list_categories()["categories"]
        for cat in cats:
            assert "name" in cat
            assert "rules" in cat

    def test_eligibility_category_present(self):
        from backend.rule_engine.rule_service import RuleService
        cats = RuleService.list_categories()["categories"]
        names = {c["name"] for c in cats}
        assert "eligibility" in names


# ─────────────────────────────────────────────────────────────────────────────
# list_rules()
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleServiceListRules:
    def setup_method(self):
        from backend.rule_engine.rule_service import inject_engine
        inject_engine(_make_mock_engine([
            _make_mock_rule("RequiredSkillRule", 10),
            _make_mock_rule("AgeEligibilityRule", 8),
            _make_mock_rule("GrowthRateRule", 3),
        ]))

    def test_returns_rules_key(self):
        from backend.rule_engine.rule_service import RuleService
        result = RuleService.list_rules()
        assert "rules" in result

    def test_pagination_metadata(self):
        from backend.rule_engine.rule_service import RuleService
        result = RuleService.list_rules(page=1, page_size=20)
        assert "total" in result
        assert "page" in result
        assert "page_size" in result
        assert "pages" in result

    def test_page_size_limits_results(self):
        from backend.rule_engine.rule_service import RuleService
        result = RuleService.list_rules(page=1, page_size=1)
        assert len(result["rules"]) == 1

    def test_category_filter_skill_matching(self):
        from backend.rule_engine.rule_service import RuleService
        result = RuleService.list_rules(category="skill_matching")
        rule_names = [r["name"] for r in result["rules"]]
        assert "RequiredSkillRule" in rule_names
        # AgeEligibilityRule is eligibility, not skill_matching
        assert "AgeEligibilityRule" not in rule_names

    def test_each_rule_has_required_fields(self):
        from backend.rule_engine.rule_service import RuleService
        result = RuleService.list_rules()
        for rule in result["rules"]:
            assert "name" in rule
            assert "priority" in rule
            assert "category" in rule


# ─────────────────────────────────────────────────────────────────────────────
# get_rule()
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleServiceGetRule:
    def setup_method(self):
        from backend.rule_engine.rule_service import inject_engine
        inject_engine(_make_mock_engine([
            _make_mock_rule("RequiredSkillRule", 10),
        ]))

    def test_find_existing_rule(self):
        from backend.rule_engine.rule_service import RuleService
        rule = RuleService.get_rule("RequiredSkillRule")
        assert rule is not None
        assert rule["name"] == "RequiredSkillRule"

    def test_returns_none_for_unknown(self):
        from backend.rule_engine.rule_service import RuleService
        assert RuleService.get_rule("NonExistentRule_XYZ") is None

    def test_rule_detail_has_required_keys(self):
        from backend.rule_engine.rule_service import RuleService
        rule = RuleService.get_rule("RequiredSkillRule")
        assert rule is not None
        for key in ("name", "priority", "category", "description", "parameters"):
            assert key in rule

    def test_category_resolved_correctly(self):
        from backend.rule_engine.rule_service import RuleService
        rule = RuleService.get_rule("RequiredSkillRule")
        assert rule is not None
        assert rule["category"] == "skill_matching"


# ─────────────────────────────────────────────────────────────────────────────
# get_rule_category()
# ─────────────────────────────────────────────────────────────────────────────

class TestGetRuleCategory:
    def test_known_rule_returns_correct_category(self):
        from backend.rule_engine.rule_service import get_rule_category
        assert get_rule_category("AgeEligibilityRule") == "eligibility"
        assert get_rule_category("RequiredSkillRule") == "skill_matching"
        assert get_rule_category("GrowthRateRule") == "market"

    def test_unknown_rule_returns_general(self):
        from backend.rule_engine.rule_service import get_rule_category
        assert get_rule_category("FooBarUnknown") == "general"


# ─────────────────────────────────────────────────────────────────────────────
# evaluate_profile()
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleServiceEvaluateProfile:
    def setup_method(self):
        engine = _make_mock_engine()
        engine.process_profile.return_value = {
            "filtered_jobs": ["Job A"],
            "ranked_jobs": [{"name": "Job A", "score": 0.8}],
            "flags": [],
            "warnings": [],
            "total_jobs_evaluated": 5,
            "jobs_passed": 1,
        }
        from backend.rule_engine.rule_service import inject_engine
        inject_engine(engine)

    def test_returns_evaluation_dict(self):
        from backend.rule_engine.rule_service import RuleService
        profile = {"skills": ["python"], "interests": ["technology"]}
        result = RuleService.evaluate_profile(profile)
        assert "filtered_jobs" in result
        assert "ranked_jobs" in result

    def test_flattens_extra_dict(self):
        """extra key must be merged into profile before engine call."""
        from backend.rule_engine.rule_service import RuleService, inject_engine
        engine = _make_mock_engine()
        engine.process_profile.return_value = {
            "filtered_jobs": [], "ranked_jobs": [], "flags": [],
            "warnings": [], "total_jobs_evaluated": 0, "jobs_passed": 0,
        }
        inject_engine(engine)
        profile = {"skills": ["coding"], "extra": {"intent": "STEM"}}
        RuleService.evaluate_profile(profile)
        call_args = engine.process_profile.call_args[0][0]
        # extra should have been merged
        assert "intent" in call_args
        assert "extra" not in call_args

    def test_result_has_mandatory_keys(self):
        from backend.rule_engine.rule_service import RuleService
        result = RuleService.evaluate_profile({"skills": ["python"]})
        for key in ("filtered_jobs", "ranked_jobs", "flags", "warnings",
                    "total_jobs_evaluated", "jobs_passed"):
            assert key in result


# ─────────────────────────────────────────────────────────────────────────────
# evaluate_job()
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleServiceEvaluateJob:
    def setup_method(self):
        engine = _make_mock_engine()
        engine.evaluate_job.return_value = {
            "job": "Software Engineer",
            "passed": True,
            "score_delta": 0.3,
            "flags": [],
            "warnings": [],
        }
        from backend.rule_engine.rule_service import inject_engine
        inject_engine(engine)

    def test_returns_dict_for_known_job(self):
        from backend.rule_engine.rule_service import RuleService
        result = RuleService.evaluate_job({"skills": ["python"]}, "Software Engineer")
        assert result is not None
        assert result["job"] == "Software Engineer"

    def test_returns_none_for_unknown_job(self):
        from backend.rule_engine.rule_service import RuleService, inject_engine
        engine = _make_mock_engine()
        engine.evaluate_job.return_value = None
        inject_engine(engine)
        assert RuleService.evaluate_job({"skills": ["python"]}, "GHOST_JOB_XYZ") is None

    def test_score_delta_float(self):
        from backend.rule_engine.rule_service import RuleService
        result = RuleService.evaluate_job({"skills": ["python"]}, "Software Engineer")
        assert isinstance(result["score_delta"], float)


# ─────────────────────────────────────────────────────────────────────────────
# reload()
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleServiceReload:
    def test_reload_reinitialises_engine(self):
        """After reload, the engine count comes from a fresh RuleEngine."""
        from backend.rule_engine.rule_service import RuleService, inject_engine
        # Inject a stale engine with 0 rules
        inject_engine(_make_mock_engine([]))
        # After reload, it should create a new real engine
        with patch("backend.rule_engine.rule_service.RuleEngine") as MockEngine:
            mock_instance = MagicMock()
            mock_instance.rules = [_make_mock_rule("R1"), _make_mock_rule("R2")]
            MockEngine.return_value = mock_instance
            result = RuleService.reload()

        assert result["reloaded"] is True
        assert result["rules_count"] == 2

    def test_reload_returns_message(self):
        with patch("backend.rule_engine.rule_service.RuleEngine") as MockEngine:
            m = MagicMock()
            m.rules = []
            MockEngine.return_value = m
            from backend.rule_engine.rule_service import RuleService
            result = RuleService.reload()
        assert "message" in result

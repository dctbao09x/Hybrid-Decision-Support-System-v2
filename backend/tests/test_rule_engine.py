# backend/tests/test_rule_engine.py
"""Unit tests for backend.rule_engine — rules, engine, prototype_jobs."""

import pytest
from unittest.mock import patch, MagicMock


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# rule_base
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestRuleBase:
    def test_rule_result_init(self):
        from backend.rule_engine.rule_base import RuleResult
        r = RuleResult()
        assert r.passed is True
        assert r.score_delta == 0.0
        assert r.flags == []
        assert r.warnings == []

    def test_merge_passed_false(self):
        from backend.rule_engine.rule_base import RuleResult
        r = RuleResult()
        r.merge({"passed": False, "score_delta": -0.3, "flags": ["fail"], "warnings": ["warn"]})
        assert r.passed is False
        assert r.score_delta == -0.3
        assert "fail" in r.flags

    def test_merge_accumulates_delta(self):
        from backend.rule_engine.rule_base import RuleResult
        r = RuleResult()
        r.merge({"passed": True, "score_delta": 0.1, "flags": ["a"], "warnings": []})
        r.merge({"passed": True, "score_delta": 0.2, "flags": ["b"], "warnings": []})
        assert abs(r.score_delta - 0.3) < 0.001

    def test_to_dict_dedupes(self):
        from backend.rule_engine.rule_base import RuleResult
        r = RuleResult()
        r.merge({"passed": True, "score_delta": 0, "flags": ["a", "a"], "warnings": ["w", "w"]})
        d = r.to_dict()
        # flags & warnings passed through set()
        assert isinstance(d["flags"], list)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# prototype_jobs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestPrototypeJobs:
    def test_database_validates_at_import(self):
        from backend.rule_engine.prototype_jobs import JOB_DATABASE
        assert len(JOB_DATABASE) >= 40

    def test_get_job_exists(self):
        from backend.rule_engine.prototype_jobs import get_job, get_all_jobs
        jobs = get_all_jobs()
        first = jobs[0]
        j = get_job(first)
        assert j is not None
        assert "domain" in j
        assert "required_skills" in j

    def test_get_job_not_found(self):
        from backend.rule_engine.prototype_jobs import get_job
        assert get_job("NonExistentJob_XYZ_999") is None

    def test_get_all_jobs_sorted(self):
        from backend.rule_engine.prototype_jobs import get_all_jobs
        jobs = get_all_jobs()
        assert jobs == sorted(jobs)

    def test_get_jobs_by_domain(self):
        from backend.rule_engine.prototype_jobs import get_jobs_by_domain
        ai_jobs = get_jobs_by_domain("AI")
        assert len(ai_jobs) >= 1
        assert all(isinstance(j, str) for j in ai_jobs)

    def test_get_required_skills(self):
        from backend.rule_engine.prototype_jobs import get_required_skills, get_all_jobs
        job = get_all_jobs()[0]
        skills = get_required_skills(job)
        assert isinstance(skills, list)

    def test_get_required_skills_missing(self):
        from backend.rule_engine.prototype_jobs import get_required_skills
        assert get_required_skills("GHOST_JOB") == []

    def test_get_relevant_interests(self):
        from backend.rule_engine.prototype_jobs import get_relevant_interests, get_all_jobs
        job = get_all_jobs()[0]
        interests = get_relevant_interests(job)
        assert isinstance(interests, list)

    def test_education_hierarchy(self):
        from backend.rule_engine.prototype_jobs import EDUCATION_HIERARCHY
        assert EDUCATION_HIERARCHY["HighSchool"] < EDUCATION_HIERARCHY["Bachelor"]
        assert EDUCATION_HIERARCHY["Bachelor"] < EDUCATION_HIERARCHY["PhD"]

    def test_domain_interest_map(self):
        from backend.rule_engine.prototype_jobs import DOMAIN_INTEREST_MAP
        assert "AI" in DOMAIN_INTEREST_MAP
        assert len(DOMAIN_INTEREST_MAP) >= 10

    def test_all_jobs_have_valid_ranges(self):
        from backend.rule_engine.prototype_jobs import JOB_DATABASE
        for name, spec in JOB_DATABASE.items():
            assert 0 <= spec["ai_relevance"] <= 1, f"{name}.ai_relevance"
            assert 0 <= spec["competition"] <= 1, f"{name}.competition"
            assert 0 <= spec["growth_rate"] <= 1, f"{name}.growth_rate"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Individual rules — eligibility
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestEligibilityRules:
    def test_age_pass(self):
        from backend.rule_engine.rules.eligibility import AgeEligibilityRule
        r = AgeEligibilityRule()
        result = r.evaluate({"age": 22}, {"min_age": 18})
        assert result["passed"] is True

    def test_age_fail(self):
        from backend.rule_engine.rules.eligibility import AgeEligibilityRule
        r = AgeEligibilityRule()
        result = r.evaluate({"age": 15}, {"min_age": 18})
        assert result["passed"] is False
        assert "age_ineligible" in result["flags"]

    def test_age_missing_default(self):
        from backend.rule_engine.rules.eligibility import AgeEligibilityRule
        r = AgeEligibilityRule()
        result = r.evaluate({"age": 20}, {})  # no min_age → default 18
        assert result["passed"] is True


class TestConfidenceRules:
    def test_high_confidence(self):
        from backend.rule_engine.rules.confidence import ConfidenceLevelRule
        r = ConfidenceLevelRule()
        result = r.evaluate({"confidence_score": 0.9}, {})
        assert result["score_delta"] > 0
        assert "high_confidence" in result["flags"]

    def test_low_confidence(self):
        from backend.rule_engine.rules.confidence import ConfidenceLevelRule
        r = ConfidenceLevelRule()
        result = r.evaluate({"confidence_score": 0.3}, {})
        assert result["score_delta"] < 0

    def test_data_completeness_full(self):
        from backend.rule_engine.rules.confidence import DataCompletenessRule
        r = DataCompletenessRule()
        profile = {
            "age": 25, "education_level": "Bachelor",
            "interest_tags": ["ai"], "skill_tags": ["python"],
            "goal_cleaned": "AI Engineer",
        }
        result = r.evaluate(profile, {})
        assert "complete_profile" in result["flags"]

    def test_data_completeness_empty(self):
        from backend.rule_engine.rules.confidence import DataCompletenessRule
        r = DataCompletenessRule()
        result = r.evaluate({}, {})
        assert "incomplete_profile" in result["flags"]


class TestSkillMatchingRules:
    def test_required_all_present(self):
        from backend.rule_engine.rules.skill_matching import RequiredSkillRule
        r = RequiredSkillRule()
        profile = {"skill_tags": ["python", "sql", "django"]}
        job = {"required_skills": ["Python", "SQL"]}
        result = r.evaluate(profile, job)
        assert result["passed"] is True
        assert result["score_delta"] > 0

    def test_required_missing_some(self):
        from backend.rule_engine.rules.skill_matching import RequiredSkillRule
        r = RequiredSkillRule()
        profile = {"skill_tags": ["python"]}
        job = {"required_skills": ["Python", "SQL", "React"]}
        result = r.evaluate(profile, job)
        assert "missing_required_skills" in result["flags"]

    def test_skill_count_zero(self):
        from backend.rule_engine.rules.skill_matching import SkillCountRule
        r = SkillCountRule()
        result = r.evaluate({"skill_tags": []}, {})
        assert "no_skills_listed" in result["flags"]

    def test_skill_count_rich(self):
        from backend.rule_engine.rules.skill_matching import SkillCountRule
        r = SkillCountRule()
        result = r.evaluate({"skill_tags": ["a", "b", "c", "d", "e"]}, {})
        assert "skill_rich" in result["flags"]


class TestPriorityRules:
    def test_similarity_boost_high(self):
        from backend.rule_engine.rules.priority import SimilarityBoostRule
        r = SimilarityBoostRule()
        profile = {"similarity_scores": {"AI Engineer": 0.85}}
        result = r.evaluate(profile, {"name": "AI Engineer"})
        assert result["score_delta"] > 0

    def test_similarity_boost_low(self):
        from backend.rule_engine.rules.priority import SimilarityBoostRule
        r = SimilarityBoostRule()
        profile = {"similarity_scores": {"AI Engineer": 0.2}}
        result = r.evaluate(profile, {"name": "AI Engineer"})
        assert result["score_delta"] < 0

    def test_interest_match(self):
        from backend.rule_engine.rules.priority import InterestMatchRule
        r = InterestMatchRule()
        profile = {"interest_tags": ["machine learning", "deep learning"]}
        job = {"name": "AI Engineer", "domain": "AI"}
        result = r.evaluate(profile, job)
        assert isinstance(result["score_delta"], float)


class TestMarketRules:
    def test_high_competition_risk(self):
        from backend.rule_engine.rules.market_rules import CompetitionRule
        r = CompetitionRule()
        profile = {"skill_tags": ["python"], "confidence_score": 0.3}
        job = {"competition": 0.9}
        result = r.evaluate(profile, job)
        assert "high_competition_risk" in result["flags"]

    def test_low_competition(self):
        from backend.rule_engine.rules.market_rules import CompetitionRule
        r = CompetitionRule()
        profile = {"skill_tags": [], "confidence_score": 0.5}
        job = {"competition": 0.5}
        result = r.evaluate(profile, job)
        assert "low_competition" in result["flags"]

    def test_high_growth(self):
        from backend.rule_engine.rules.market_rules import GrowthRateRule
        r = GrowthRateRule()
        result = r.evaluate({"intent": "career_intent"}, {"growth_rate": 0.9})
        assert "high_growth" in result["flags"]

    def test_ai_relevance_mismatch(self):
        from backend.rule_engine.rules.market_rules import AIRelevanceRule
        r = AIRelevanceRule()
        profile = {"interest_tags": [], "skill_tags": []}
        job = {"ai_relevance": 0.9}
        result = r.evaluate(profile, job)
        assert "ai_mismatch" in result["flags"]


class TestRiskDetection:
    def test_difficulty_too_high(self):
        from backend.rule_engine.rules.risk_detection import DifficultyMismatchRule
        r = DifficultyMismatchRule()
        profile = {"education_level": "unknown", "skill_tags": ["python"]}
        job = {"competition": 0.85}
        result = r.evaluate(profile, job)
        assert "difficulty_too_high" in result["flags"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RuleEngine
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestRuleEngine:
    @pytest.fixture
    def engine(self):
        from backend.rule_engine.rule_engine import RuleEngine
        return RuleEngine()

    def test_init_loads_rules(self, engine):
        assert len(engine.rules) >= 10

    def test_rules_sorted_by_priority(self, engine):
        priorities = [r.priority for r in engine.rules]
        assert priorities == sorted(priorities, reverse=True)

    def test_add_rule(self, engine):
        from backend.rule_engine.rule_base import Rule
        class DummyRule(Rule):
            def evaluate(self, profile, job):
                return {"passed": True, "score_delta": 0, "flags": [], "warnings": []}
        before = len(engine.rules)
        engine.add_rule(DummyRule("dummy", priority=99))
        assert len(engine.rules) == before + 1

    def test_remove_rule(self, engine):
        name = engine.rules[-1].name
        engine.remove_rule(name)
        assert name not in [r.name for r in engine.rules]

    def test_evaluate_job_not_found(self, engine):
        result = engine.evaluate_job({}, "NonExistentJob_XYZ")
        assert result is None

    def test_evaluate_job_success(self, engine):
        # The engine's evaluate_job uses job_database.get_job_requirements
        # which goes through kb_adapter (needs DB). Mock it to return
        # a known job requirement dict.
        from unittest.mock import patch
        job_name = "AI Engineer"
        mock_reqs = {
            "name": job_name,
            "domain": "AI",
            "required_skills": ["python", "tensorflow"],
            "preferred_skills": ["pytorch", "sql"],
            "min_education": "Bachelor",
            "age_max": 35,
            "competition": 0.6,
            "growth_rate": 0.2,
            "difficulty": "medium",
            "interests": ["ai", "machine learning"],
        }
        with patch("backend.rule_engine.rule_engine.get_job_requirements", return_value=mock_reqs):
            profile = {
                "age": 22, "education_level": "Bachelor",
                "interest_tags": ["ai"], "skill_tags": ["python", "sql"],
                "goal_cleaned": "AI Engineer", "intent": "career_intent",
                "confidence_score": 0.8, "similarity_scores": {job_name: 0.7},
            }
            result = engine.evaluate_job(profile, job_name)
            assert result is not None
            assert "passed" in result
            assert "score_delta" in result

    def test_process_profile(self, engine):
        from unittest.mock import patch
        # Provide a small set of mock jobs
        mock_jobs = ["AI Engineer", "Data Analyst"]
        mock_reqs = {
            "AI Engineer": {
                "domain": "AI", "required_skills": ["python"],
                "preferred_skills": ["tensorflow"], "min_education": "Bachelor",
                "age_max": 35, "competition": 0.6, "growth_rate": 0.2,
                "difficulty": "medium", "interests": ["ai"],
            },
            "Data Analyst": {
                "domain": "Data", "required_skills": ["sql"],
                "preferred_skills": ["python"], "min_education": "Bachelor",
                "age_max": 40, "competition": 0.5, "growth_rate": 0.15,
                "difficulty": "easy", "interests": ["data"],
            },
        }
        def mock_get_reqs(name):
            r = mock_reqs.get(name)
            if r:
                r["name"] = name
            return r

        with patch("backend.rule_engine.rule_engine.get_all_jobs", return_value=mock_jobs), \
             patch("backend.rule_engine.rule_engine.get_job_requirements", side_effect=mock_get_reqs):
            profile = {
                "age": 22, "education_level": "Bachelor",
                "interest_tags": ["ai", "data"],
                "skill_tags": ["python", "sql", "tensorflow"],
                "goal_cleaned": "AI Engineer", "intent": "career_intent",
                "confidence_score": 0.8,
                "similarity_scores": {j: 0.5 for j in mock_jobs},
            }
            result = engine.process_profile(profile)
            assert "ranked_jobs" in result
            assert "total_jobs_evaluated" in result
            assert result["total_jobs_evaluated"] == len(mock_jobs)

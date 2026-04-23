from pathlib import Path

from backend.rule_engine.config_loader import load_ruleset_config
from backend.rule_engine.rule_engine import RuleEngine


def test_ruleset_config_loads():
    ruleset = load_ruleset_config()
    assert ruleset.version
    assert ruleset.groups


def test_rule_engine_audit_trail(monkeypatch):
    from backend.rule_engine import rule_engine as engine_module

    def _job_requirements(_name: str):
        return {
            "min_age": 18,
            "min_education": "high school",
            "required_skills": [],
            "preferred_skills": [],
            "competition": 0.5,
            "growth_rate": 0.5,
            "ai_relevance": 0.5,
            "domain": "general",
        }

    monkeypatch.setattr(engine_module, "get_job_requirements", _job_requirements)
    monkeypatch.setattr(engine_module, "get_all_jobs", lambda: ["TestJob"])

    engine = RuleEngine(config_path=Path("backend/rule_engine/configs/ruleset_v1.yaml"))
    profile = {
        "age": 20,
        "education_level": "high school",
        "skill_tags": [],
        "interest_tags": [],
        "confidence_score": 0.6,
    }

    result = engine.evaluate_job(profile, "TestJob")
    assert result["job"] == "TestJob"
    assert "audit_trail" in result
    assert result["ruleset_version"] is not None

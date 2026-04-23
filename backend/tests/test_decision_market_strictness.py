from __future__ import annotations

from typing import Any, Dict

import pytest

from backend.api.controllers.decision_controller import (
    CareerResult,
    DecisionOptions,
    DecisionRequest,
    DecisionController,
    InputValidationError,
)
from backend.scoring.sub_scorer import ScoringBreakdown


class _MockMainController:
    def __init__(self, response: Dict[str, Any]):
        self._response = response

    async def dispatch(self, service: str, action: str, payload: Dict[str, Any], context: Dict[str, Any]):
        return dict(self._response)


def _sample_top_career() -> CareerResult:
    return CareerResult(
        name="Data Scientist",
        domain="technology",
        total_score=0.8,
        skill_score=0.7,
        interest_score=0.8,
        market_score=0.6,
        growth_potential=0.7,
        ai_relevance=0.8,
    )


def test_market_fallback_event_includes_reason_code() -> None:
    event = DecisionController._build_market_signal_fallback_event(
        [_sample_top_career()],
        "Market salary range missing for career 'Data Scientist'",
    )

    assert event["taxonomy"] == "missing_market_signal"
    assert event["reason_code"] == "salary_range_missing"
    assert event["career_name"] == "Data Scientist"


@pytest.mark.asyncio
async def test_market_data_missing_signal_raises_strict_error() -> None:
    controller = DecisionController()
    controller.set_main_controller(
        _MockMainController(
            {
                "status": "missing_market_signal",
                "career_name": "Data Scientist",
            }
        )
    )

    with pytest.raises(InputValidationError, match="Missing market signal"):
        await controller._get_market_data([_sample_top_career()], trace_id="trace-1")

    assert controller._fallback_metric_state["missing_market_signal_events"] == 1


@pytest.mark.asyncio
async def test_market_data_emits_stale_and_low_confidence_taxonomy() -> None:
    controller = DecisionController()
    controller.set_main_controller(
        _MockMainController(
            {
                "status": "ok",
                "career_name": "Data Scientist",
                "demand": "HIGH",
                "salary_range": {"min": 20000000, "max": 40000000, "currency": "VND"},
                "growth_rate": 0.12,
                "competition": "MEDIUM",
                "stale": True,
                "trust_ok": False,
                "source_trust_score": 0.22,
                "age_hours": 97,
            }
        )
    )

    insights, events = await controller._get_market_data(
        [_sample_top_career()], trace_id="trace-2"
    )

    assert len(insights) == 1
    taxonomy = {event["taxonomy"] for event in events}
    assert "stale_data_fallback" in taxonomy
    assert "low_confidence_fallback" in taxonomy


@pytest.mark.asyncio
async def test_run_scoring_records_zero_score_occurrence(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = DecisionController()
    controller.set_main_controller(
        _MockMainController(
            {
                "ranked_careers": [
                    {
                        "name": "Data Scientist",
                        "domain": "technology",
                        "total_score": 0.0,
                        "skill_score": 0.0,
                        "interest_score": 0.0,
                        "market_score": 0.0,
                        "growth_potential": 0.0,
                        "ai_relevance": 0.0,
                    }
                ]
            }
        )
    )

    monkeypatch.setattr(
        controller,
        "_get_career_database",
        lambda: [
            {
                "name": "Data Scientist",
                "required_skills": ["python"],
                "preferred_skills": ["statistics"],
                "domain": "technology",
                "domain_interests": ["technology"],
                "ai_relevance": 0.8,
                "growth_rate": 0.6,
                "competition": 0.5,
            }
        ],
    )

    rankings = await controller._run_scoring(
        profile={
            "skills": ["python"],
            "interests": ["technology"],
            "education_level": "bachelor",
            "ability_score": 0.7,
            "confidence_score": 0.6,
        },
        trace_id="trace-3",
    )

    assert len(rankings) == 1
    assert controller._fallback_metric_state["zero_score_occurrences"] == 1


@pytest.mark.asyncio
async def test_run_pipeline_degrades_on_missing_market_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = DecisionController()

    breakdown = ScoringBreakdown(
        skill_score=80.0,
        experience_score=75.0,
        education_score=70.0,
        goal_alignment_score=85.0,
        preference_score=65.0,
        final_score=76.5,
        weights={
            "skill_score": 0.3,
            "experience_score": 0.2,
            "education_score": 0.2,
            "goal_alignment_score": 0.2,
            "preference_score": 0.1,
        },
        contributions={
            "skill_score": 24.0,
            "experience_score": 15.0,
            "education_score": 14.0,
            "goal_alignment_score": 17.0,
            "preference_score": 6.5,
        },
        formula="final = weighted_sum(sub_scores)",
        sub_score_meta={},
    )

    monkeypatch.setattr(
        controller,
        "_normalize_input",
        lambda request, trace_id="-": {
            "user_id": request.user_id,
            "skills": ["python"],
            "interests": ["technology"],
            "education_level": "Bachelor",
            "ability_score": 0.7,
            "confidence_score": 0.6,
            "taxonomy_applied": True,
            "_scoring_breakdown": breakdown,
        },
    )

    async def _stub_extract_features(request, trace_id):
        _ = (request, trace_id)
        return ({"llm_extracted": False}, {"llm_attempted": False, "mode": "deterministic_input_only"})

    monkeypatch.setattr(controller, "_extract_features", _stub_extract_features)
    monkeypatch.setattr(controller, "_align_with_knowledge_base", lambda normalized, features, trace_id: {})
    monkeypatch.setattr(controller, "_merge_data", lambda normalized, features, kb: dict(normalized))
    monkeypatch.setattr(
        controller,
        "_run_drift_check",
        lambda profile, rankings_payload, trace_id: {"drift_detected": False, "drift_score": 0.0},
    )

    ranked = [
        CareerResult(
            name="Data Scientist",
            domain="technology",
            total_score=82.0,
            skill_score=80.0,
            interest_score=79.0,
            market_score=76.0,
            growth_potential=81.0,
            ai_relevance=88.0,
        )
    ]

    async def _stub_run_scoring(profile, trace_id, scoring_breakdown=None):
        _ = (profile, trace_id, scoring_breakdown)
        return ranked

    async def _stub_apply_rules(rankings, profile, trace_id):
        _ = (profile, trace_id)
        return type("_RuleEngineStub", (), {"rankings": rankings, "rules_trace": []})()

    async def _stub_get_market_data(top_careers, trace_id):
        _ = (top_careers, trace_id)
        raise InputValidationError("Missing market signal for career 'Data Scientist'")

    monkeypatch.setattr(controller, "_run_scoring", _stub_run_scoring)
    monkeypatch.setattr(controller, "_apply_rules", _stub_apply_rules)
    monkeypatch.setattr(controller, "_get_market_data", _stub_get_market_data)
    monkeypatch.setattr(controller, "_log_snapshot", lambda trace_id, request, response: None)
    monkeypatch.setattr(
        "backend.api.controllers.decision_controller.validate_scoring_consistency",
        lambda *args, **kwargs: None,
    )

    request = DecisionRequest(
        user_id="test-user",
        scoring_input={
            "personal_profile": {
                "ability_score": 0.7,
                "confidence_score": 0.6,
                "interests": ["technology"],
            },
            "experience": {"years": 2, "domains": ["software"]},
            "goals": {"career_aspirations": ["data scientist"], "timeline_years": 3},
            "skills": ["python"],
            "education": {"level": "Bachelor", "field_of_study": "Computer Science"},
            "preferences": {"preferred_domains": ["technology"], "work_style": "hybrid"},
        },
        options=DecisionOptions(include_explanation=False, include_market_data=True),
    )

    response = await controller.run_pipeline(request)
    assert response.status == "SUCCESS"

    market_stage = next(s for s in response.stage_log if s["stage"] == "market_data")
    assert market_stage["status"] == "degraded"

    fallback_events = response.diagnostics.get("fallback_taxonomy_events", [])
    assert any(evt.get("taxonomy") == "missing_market_signal" for evt in fallback_events)

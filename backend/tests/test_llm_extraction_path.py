from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.api.controllers.decision_controller import DecisionController, UserFeatures
from backend.models.llm_schemas import (
    CareerFeatureExtractionV1,
    CareerFieldEnum,
    UserTraits,
)
from backend.scoring.models import ScoringInput
from backend.services import llm_extractor
from backend.services.llm_extractor import LLMExtractionAttempt


def _sample_scoring_input() -> ScoringInput:
    return ScoringInput(
        personal_profile={
            "ability_score": 0.72,
            "confidence_score": 0.68,
            "interests": ["technology", "science"],
        },
        experience={
            "years": 3,
            "domains": ["software engineering"],
        },
        goals={
            "career_aspirations": ["machine learning engineer"],
            "timeline_years": 4,
        },
        skills=["python", "data analysis"],
        education={
            "level": "Bachelor",
            "field_of_study": "Computer Science",
        },
        preferences={
            "preferred_domains": ["technology"],
            "work_style": "hybrid",
        },
    )


def _sample_feature(confidence: float = 0.9) -> CareerFeatureExtractionV1:
    return CareerFeatureExtractionV1(
        inferred_interests=[CareerFieldEnum.IT],
        skills=[],
        traits=UserTraits(extraversion_level=5, stress_tolerance=6),
        has_financial_constraints=False,
        extraction_confidence=confidence,
        missing_info_flags=[],
    )


@pytest.mark.asyncio
async def test_llm_extractor_success_path(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "schema_version": "v1.0.0",
        "user_profile": {
            "extraversion_level": 6,
            "stress_tolerance": 7,
            "financial_constraints": False,
        },
        "interests": [{"label": "INFORMATION_TECHNOLOGY", "confidence": 0.9}],
        "strengths": [{"title": "Python", "confidence": 0.88}],
        "weaknesses": [],
        "career_matches": [],
        "score_breakdown": {"final_score": 0.0, "components": []},
        "explanation_metadata": {"model": "unit-test"},
        "risk_flags": {"extraction_confidence": 0.86, "warnings": []},
    }

    async def _fake_invoke(prompt: str) -> str:
        assert "User input" in prompt
        return json.dumps(payload)

    monkeypatch.setattr(llm_extractor, "_invoke_llm_raw_output", _fake_invoke)

    attempt = await llm_extractor.extract_features_with_retry("skills: python")

    assert attempt.success is True
    assert attempt.used_fallback is False
    assert attempt.schema_validation_failures == 0
    assert attempt.confidence >= 0.8
    assert attempt.feature.inferred_interests[0] == CareerFieldEnum.IT


@pytest.mark.asyncio
async def test_llm_extractor_schema_validation_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_invoke(prompt: str) -> str:
        _ = prompt
        return "{not_valid_json"

    monkeypatch.setattr(llm_extractor, "_invoke_llm_raw_output", _fake_invoke)

    attempt = await llm_extractor.extract_features_with_retry("skills: python")

    assert attempt.success is False
    assert attempt.used_fallback is True
    assert attempt.fallback_reason == "schema_validation"
    assert attempt.schema_validation_failures == llm_extractor.MAX_VALIDATION_RETRIES + 1
    assert attempt.feature.inferred_interests == [CareerFieldEnum.UNKNOWN]


@pytest.mark.asyncio
async def test_controller_deterministic_mode_uses_manual_features(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECISION_EXTRACTION_MODE", "deterministic_input_only")

    controller = DecisionController()
    request = SimpleNamespace(
        scoring_input=_sample_scoring_input(),
        features=UserFeatures(math_score=8.0, logic_score=7.5),
    )

    features, diagnostics = await controller._extract_features(request, trace_id="trace-det")

    assert diagnostics["mode"] == "deterministic_input_only"
    assert diagnostics["llm_attempted"] is False
    assert features["llm_extracted"] is False
    assert features["math_score"] == 8.0
    assert features["logic_score"] == 7.5


@pytest.mark.asyncio
async def test_controller_hybrid_mode_enriches_with_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECISION_EXTRACTION_MODE", "hybrid")

    async def _fake_extract(text: str) -> LLMExtractionAttempt:
        assert "skills:" in text
        return LLMExtractionAttempt(
            feature=_sample_feature(confidence=0.91),
            success=True,
            used_fallback=False,
            schema_validation_failures=0,
            attempts=1,
            confidence=0.91,
            fallback_reason=None,
        )

    monkeypatch.setattr(
        "backend.api.controllers.decision_controller.extract_features_with_retry",
        _fake_extract,
    )
    monkeypatch.setattr(
        "backend.api.controllers.decision_controller.to_feature_signals",
        lambda extraction: {"interest_tech": 9.1},
    )

    controller = DecisionController()
    request = SimpleNamespace(scoring_input=_sample_scoring_input(), features=None)

    features, diagnostics = await controller._extract_features(request, trace_id="trace-hybrid")

    assert diagnostics["mode"] == "hybrid"
    assert diagnostics["llm_attempted"] is True
    assert diagnostics["llm_extracted"] is True
    assert features["llm_extracted"] is True
    assert features["interest_tech"] == 9.1


@pytest.mark.asyncio
async def test_controller_llm_low_confidence_falls_back_to_manual(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECISION_EXTRACTION_MODE", "llm_only")

    async def _fake_extract(text: str) -> LLMExtractionAttempt:
        _ = text
        return LLMExtractionAttempt(
            feature=_sample_feature(confidence=0.31),
            success=False,
            used_fallback=True,
            schema_validation_failures=1,
            attempts=2,
            confidence=0.31,
            fallback_reason="low_confidence",
        )

    monkeypatch.setattr(
        "backend.api.controllers.decision_controller.extract_features_with_retry",
        _fake_extract,
    )
    monkeypatch.setattr(
        "backend.api.controllers.decision_controller.to_feature_signals",
        lambda extraction: {"interest_tech": 3.1},
    )

    controller = DecisionController()
    request = SimpleNamespace(
        scoring_input=_sample_scoring_input(),
        features=UserFeatures(math_score=7.2),
    )

    features, diagnostics = await controller._extract_features(request, trace_id="trace-fallback")

    assert diagnostics["llm_attempted"] is True
    assert diagnostics["fallback_reason"] == "low_confidence"
    assert features["llm_extracted"] is False
    assert features["math_score"] == 7.2
    assert controller._fallback_metric_state["manual_feature_fallbacks"] >= 1

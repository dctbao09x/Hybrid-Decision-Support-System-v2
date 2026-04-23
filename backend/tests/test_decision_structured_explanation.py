from __future__ import annotations

from backend.api.controllers.decision_controller import (
    CareerResult,
    DecisionController,
    ExplanationFactor,
    MarketInsight,
)


def test_structured_fallback_contains_required_sections() -> None:
    factors = [
        ExplanationFactor(name="skill_match", contribution=0.31, description="Strong skill fit"),
        ExplanationFactor(name="goal_alignment", contribution=0.24, description="Goals align"),
        ExplanationFactor(name="experience", contribution=-0.08, description="Limited practical experience"),
    ]
    careers = [
        CareerResult(
            name="Fintech Engineer",
            domain="technology",
            total_score=0.72,
            skill_score=0.75,
            interest_score=0.7,
            market_score=0.71,
            growth_potential=0.68,
            ai_relevance=0.77,
        ),
        CareerResult(
            name="Data Analyst",
            domain="data",
            total_score=0.69,
            skill_score=0.7,
            interest_score=0.68,
            market_score=0.69,
            growth_potential=0.66,
            ai_relevance=0.72,
        ),
    ]
    market = [
        MarketInsight(
            career_name="Fintech Engineer",
            demand_level="HIGH",
            salary_range={"min": 1000, "max": 2000, "currency": "USD"},
            growth_rate=0.12,
            competition_level="MEDIUM",
        )
    ]

    structured = DecisionController._build_structured_explanation_fallback(
        summary="Candidate has promising alignment for fintech roles.",
        factors=factors,
        confidence=0.74,
        top_careers=careers,
        rule_path=[{"rule": "goal_match", "outcome": "pass"}],
        market_insights=market,
        scoring_breakdown=None,
    )

    assert structured["summary"]
    assert structured["confidence_explanation"]
    assert len(structured["main_reasons"]) > 0
    assert len(structured["strengths"]) > 0
    assert len(structured["risks_or_gaps"]) > 0
    assert len(structured["market_context"]) > 0
    assert len(structured["next_actions"]) > 0


def test_merge_structured_explanation_falls_back_when_fields_are_empty() -> None:
    fallback = {
        "summary": "Fallback summary",
        "main_reasons": ["Fallback reason"],
        "strengths": ["Fallback strength"],
        "risks_or_gaps": ["Fallback risk"],
        "market_context": ["Fallback market"],
        "next_actions": ["Fallback action"],
        "confidence_explanation": "Fallback confidence",
    }
    generated = {
        "summary": "Generated summary",
        "main_reasons": [],
        "strengths": ["Generated strength"],
        "risks_or_gaps": [],
        "market_context": [],
        "next_actions": [],
        "confidence_explanation": "",
    }

    merged = DecisionController._merge_structured_explanation(
        generated=generated,
        fallback=fallback,
    )

    assert merged["summary"] == "Generated summary"
    assert merged["main_reasons"] == fallback["main_reasons"]
    assert merged["strengths"] == ["Generated strength"]
    assert merged["risks_or_gaps"] == fallback["risks_or_gaps"]
    assert merged["market_context"] == fallback["market_context"]
    assert merged["next_actions"] == fallback["next_actions"]
    assert merged["confidence_explanation"] == fallback["confidence_explanation"]

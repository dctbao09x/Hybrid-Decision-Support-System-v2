# backend/tests/test_taxonomy_gate.py
"""
Unit tests for P8: Taxonomy Gate (Normalize + Validate + Enforce)
=================================================================

P8 PASS criteria:
- All input categories (skills, interests, education) go through normalize()
  then validate().
- If invalid: block scoring, return clear TaxonomyValidationError.
- Rule engine MUST NOT run when taxonomy gate fails.
- No scoring bypasses taxonomy.
- TaxonomyValidationError carries structured detail payload.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _mock_facade(
    *,
    skills_result=None,
    interests_result=None,
    education_result="Bachelor",
):
    """Return a mocked TaxonomyFacade."""
    facade = MagicMock()
    facade.resolve_skill_list.return_value = (
        skills_result if skills_result is not None else ["Python", "Machine Learning"]
    )
    facade.resolve_interest_list.return_value = (
        interests_result if interests_result is not None else ["Technology", "Science"]
    )
    facade.resolve_education.return_value = education_result
    return facade


PATCH_FACADE = "backend.api.taxonomy_gate.TaxonomyFacade"


# ─────────────────────────────────────────────────────────────────────────────
# Test: TaxonomyValidationError class
# ─────────────────────────────────────────────────────────────────────────────

class TestTaxonomyValidationError:
    def test_importable(self):
        from backend.api.taxonomy_gate import TaxonomyValidationError
        assert TaxonomyValidationError is not None

    def test_is_exception(self):
        from backend.api.taxonomy_gate import TaxonomyValidationError
        err = TaxonomyValidationError("bad input", detail={"field": "skills"})
        assert isinstance(err, Exception)

    def test_message_stored(self):
        from backend.api.taxonomy_gate import TaxonomyValidationError
        err = TaxonomyValidationError("skills empty", detail={})
        assert "skills empty" in str(err)

    def test_detail_dict_stored(self):
        from backend.api.taxonomy_gate import TaxonomyValidationError
        err = TaxonomyValidationError("fail", detail={"field": "interests", "trace_id": "abc"})
        assert err.detail["field"] == "interests"
        assert err.detail["trace_id"] == "abc"

    def test_as_dict_contains_error_key(self):
        from backend.api.taxonomy_gate import TaxonomyValidationError
        err = TaxonomyValidationError("fail", detail={"field": "skills"})
        d = err.as_dict()
        assert d["error"] == "TAXONOMY_VALIDATION_FAILED"
        assert "message" in d
        assert "field" in d


# ─────────────────────────────────────────────────────────────────────────────
# Test: TaxonomyGate.normalize_and_validate — happy path
# ─────────────────────────────────────────────────────────────────────────────

class TestTaxonomyGateHappyPath:
    """Valid inputs should pass through and return canonical forms."""

    def test_returns_dict_with_required_keys(self):
        from backend.api.taxonomy_gate import TaxonomyGate

        mock_facade = _mock_facade()
        with patch(PATCH_FACADE, return_value=mock_facade):
            result = TaxonomyGate.normalize_and_validate(
                skills=["python"],
                interests=["technology"],
                education_level="Bachelor",
                trace_id="t-ok",
            )

        assert "skills" in result
        assert "interests" in result
        assert "education_level" in result
        assert "taxonomy_applied" in result

    def test_taxonomy_applied_is_true(self):
        from backend.api.taxonomy_gate import TaxonomyGate

        mock_facade = _mock_facade()
        with patch(PATCH_FACADE, return_value=mock_facade):
            result = TaxonomyGate.normalize_and_validate(
                skills=["python"],
                interests=["reading"],
                education_level="Bachelor",
            )
        assert result["taxonomy_applied"] is True

    def test_resolved_skills_returned(self):
        from backend.api.taxonomy_gate import TaxonomyGate

        mock_facade = _mock_facade(skills_result=["Python", "ML"])
        with patch(PATCH_FACADE, return_value=mock_facade):
            result = TaxonomyGate.normalize_and_validate(
                skills=["python", "ml"],
                interests=["tech"],
                education_level="Bachelor",
            )
        assert result["skills"] == ["Python", "ML"]

    def test_resolved_interests_returned(self):
        from backend.api.taxonomy_gate import TaxonomyGate

        mock_facade = _mock_facade(interests_result=["Technology"])
        with patch(PATCH_FACADE, return_value=mock_facade):
            result = TaxonomyGate.normalize_and_validate(
                skills=["python"],
                interests=["tech"],
                education_level="Bachelor",
            )
        assert result["interests"] == ["Technology"]

    def test_facade_called_for_all_three_categories(self):
        from backend.api.taxonomy_gate import TaxonomyGate

        mock_facade = _mock_facade()
        with patch(PATCH_FACADE, return_value=mock_facade):
            TaxonomyGate.normalize_and_validate(
                skills=["python"],
                interests=["tech"],
                education_level="Bachelor",
            )

        mock_facade.resolve_skill_list.assert_called_once()
        mock_facade.resolve_interest_list.assert_called_once()
        mock_facade.resolve_education.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# Test: TaxonomyGate.normalize_and_validate — failure cases
# ─────────────────────────────────────────────────────────────────────────────

class TestTaxonomyGateFailureCases:
    """Invalid inputs must raise TaxonomyValidationError, blocking scoring."""

    def test_empty_skills_after_resolution_raises(self):
        from backend.api.taxonomy_gate import TaxonomyGate, TaxonomyValidationError

        mock_facade = _mock_facade(skills_result=[])  # resolved to nothing
        with patch(PATCH_FACADE, return_value=mock_facade):
            with pytest.raises(TaxonomyValidationError) as exc_info:
                TaxonomyGate.normalize_and_validate(
                    skills=["gibberish_skill_xyz"],
                    interests=["tech"],
                    education_level="Bachelor",
                    trace_id="t-fail-skills",
                )
        assert exc_info.value.detail["field"] == "skills"

    def test_empty_interests_after_resolution_raises(self):
        from backend.api.taxonomy_gate import TaxonomyGate, TaxonomyValidationError

        mock_facade = _mock_facade(interests_result=[])  # resolved to nothing
        with patch(PATCH_FACADE, return_value=mock_facade):
            with pytest.raises(TaxonomyValidationError) as exc_info:
                TaxonomyGate.normalize_and_validate(
                    skills=["python"],
                    interests=["gibberish_interest_xyz"],
                    education_level="Bachelor",
                    trace_id="t-fail-interests",
                )
        assert exc_info.value.detail["field"] == "interests"

    def test_skills_error_detail_has_trace_id(self):
        from backend.api.taxonomy_gate import TaxonomyGate, TaxonomyValidationError

        mock_facade = _mock_facade(skills_result=[])
        with patch(PATCH_FACADE, return_value=mock_facade):
            with pytest.raises(TaxonomyValidationError) as exc_info:
                TaxonomyGate.normalize_and_validate(
                    skills=["unknown"],
                    interests=["tech"],
                    education_level="Bachelor",
                    trace_id="trace-xyz",
                )
        assert exc_info.value.detail.get("trace_id") == "trace-xyz"

    def test_skills_error_detail_has_raw_values(self):
        from backend.api.taxonomy_gate import TaxonomyGate, TaxonomyValidationError

        mock_facade = _mock_facade(skills_result=[])
        raw = ["unknown_skill_1", "unknown_skill_2"]
        with patch(PATCH_FACADE, return_value=mock_facade):
            with pytest.raises(TaxonomyValidationError) as exc_info:
                TaxonomyGate.normalize_and_validate(
                    skills=raw,
                    interests=["tech"],
                    education_level="Bachelor",
                )
        assert exc_info.value.detail.get("raw_values") == raw

    def test_as_dict_from_gate_error(self):
        from backend.api.taxonomy_gate import TaxonomyGate, TaxonomyValidationError

        mock_facade = _mock_facade(skills_result=[])
        with patch(PATCH_FACADE, return_value=mock_facade):
            with pytest.raises(TaxonomyValidationError) as exc_info:
                TaxonomyGate.normalize_and_validate(
                    skills=["unknown"],
                    interests=["tech"],
                    education_level="Bachelor",
                    trace_id="t-dict",
                )
        d = exc_info.value.as_dict()
        assert d["error"] == "TAXONOMY_VALIDATION_FAILED"
        assert "field" in d

    def test_error_type_is_taxonomy_validation_error(self):
        from backend.api.taxonomy_gate import TaxonomyGate, TaxonomyValidationError

        mock_facade = _mock_facade(skills_result=[])
        with patch(PATCH_FACADE, return_value=mock_facade):
            with pytest.raises(TaxonomyValidationError):
                TaxonomyGate.normalize_and_validate(
                    skills=[],
                    interests=["tech"],
                    education_level="Bachelor",
                )


# ─────────────────────────────────────────────────────────────────────────────
# Test: P8 enforcement — gate runs before rule engine
# ─────────────────────────────────────────────────────────────────────────────

class TestP8Enforcement:
    """TaxonomyValidationError must block rule engine + scoring from running."""

    @pytest.mark.asyncio
    async def test_taxonomy_error_re_raised_from_run_pipeline(self):
        """run_pipeline() must re-raise TaxonomyValidationError, not swallow it."""
        from unittest.mock import patch, AsyncMock
        from backend.api.controllers.decision_controller import (
            DecisionController,
            TaxonomyValidationError,
        )
        from backend.api.taxonomy_gate import TaxonomyGate

        controller = DecisionController.__new__(DecisionController)
        controller._main_controller = None

        # Patch _normalize_input to raise TaxonomyValidationError
        with patch.object(
            controller,
            "_normalize_input",
            side_effect=TaxonomyValidationError("no skills", detail={"field": "skills"}),
        ):
            with pytest.raises(TaxonomyValidationError):
                await controller.run_pipeline(MagicMock())

    @pytest.mark.asyncio
    async def test_scoring_not_called_on_taxonomy_failure(self):
        """_run_scoring must NOT be called when taxonomy gate raises."""
        from unittest.mock import patch, AsyncMock
        from backend.api.controllers.decision_controller import (
            DecisionController,
            TaxonomyValidationError,
        )

        controller = DecisionController.__new__(DecisionController)
        controller._main_controller = None

        run_scoring_mock = AsyncMock()

        with patch.object(
            controller,
            "_normalize_input",
            side_effect=TaxonomyValidationError("no skills", detail={"field": "skills"}),
        ), patch.object(controller, "_run_scoring", run_scoring_mock):
            with pytest.raises(TaxonomyValidationError):
                await controller.run_pipeline(MagicMock())

        run_scoring_mock.assert_not_called()

    def test_taxonomy_gate_called_inside_normalize_input(self):
        """TaxonomyGate.normalize_and_validate is called during _normalize_input."""
        from backend.api.taxonomy_gate import TaxonomyGate
        import inspect
        from backend.api.controllers import decision_controller

        src = inspect.getsource(decision_controller.DecisionController._normalize_input)
        assert "TaxonomyGate" in src, (
            "_normalize_input must call TaxonomyGate.normalize_and_validate"
        )
        assert "normalize_and_validate" in src, (
            "_normalize_input must call TaxonomyGate.normalize_and_validate"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test: Route-level HTTP 400 for TaxonomyValidationError
# ─────────────────────────────────────────────────────────────────────────────

class TestRouterHandlesTaxonomyError:
    """decision_router must catch TaxonomyValidationError and return HTTP 400."""

    def test_router_imports_taxonomy_validation_error(self):
        import inspect
        from backend.api.routers import decision_router
        src = inspect.getsource(decision_router)
        assert "TaxonomyValidationError" in src, (
            "decision_router must import and handle TaxonomyValidationError"
        )

    @pytest.mark.asyncio
    async def test_router_returns_http_400_on_taxonomy_failure(self):
        """TaxonomyValidationError → HTTPException(status_code=400)."""
        from unittest.mock import patch, AsyncMock
        from fastapi import HTTPException
        from backend.api.routers.decision_router import run_decision_pipeline
        from backend.api.taxonomy_gate import TaxonomyValidationError
        # Use a real but minimal ScoringInput
        from backend.scoring.models import (
            ScoringInput, PersonalProfileComponent, ExperienceComponent,
            GoalsComponent, PreferencesComponent, EducationComponent,
        )

        si = ScoringInput(
            personal_profile=PersonalProfileComponent(
                ability_score=0.7,
                confidence_score=0.6,
                interests=["technology"],
            ),
            experience=ExperienceComponent(years=2, domains=["software"]),
            goals=GoalsComponent(career_aspirations=["engineer"], timeline_years=3),
            skills=["python"],
            education=EducationComponent(level="Bachelor", field_of_study="Computer Science"),
            preferences=PreferencesComponent(work_style="remote", preferred_domains=["tech"]),
        )

        from fastapi import Request as FastAPIRequest
        fake_request = MagicMock(spec=FastAPIRequest)
        fake_body = MagicMock()
        fake_body.user_id = "user-test"
        fake_body.scoring_input = si
        fake_body.features = None
        fake_body.options = None

        with patch(
            "backend.api.routers.decision_router._get_controller"
        ) as mock_get_ctrl:
            mock_ctrl = MagicMock()
            mock_ctrl.run_pipeline = AsyncMock(
                side_effect=TaxonomyValidationError(
                    "no skills", detail={"field": "skills"}
                )
            )
            mock_get_ctrl.return_value = mock_ctrl

            with pytest.raises(HTTPException) as exc_info:
                await run_decision_pipeline(fake_request, fake_body)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["error"] == "TAXONOMY_VALIDATION_FAILED"


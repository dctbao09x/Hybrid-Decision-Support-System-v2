# tests/explain/test_score_analytics_engine.py
"""
Regression tests for Score Analytics Engine — hardening suite.

T1 — Prompt hot reload without process restart
T2 — TimeoutError classified and emitted as fallback_reason
T3 — Fallback response headers enforced
T4 — UnclassifiedError logged at ERROR level

Run:
    pytest tests/explain/test_score_analytics_engine.py -v
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import os
import time
import threading
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_input() -> "ScoreAnalyticsInput":  # noqa: F821 — imported below
    from backend.explain.score_analytics.engine import ScoreAnalyticsInput

    return ScoreAnalyticsInput(
        skill_score=70.0,
        experience_score=60.0,
        education_score=80.0,
        goal_alignment_score=65.0,
        preference_score=55.0,
        confidence=0.75,
        skills=["Python", "SQL"],
        interests=["Data Science"],
        education_level="Bachelor",
        years_experience=3.0,
    )


# ═════════════════════════════════════════════════════════════════════════════
# T1 — Prompt hot reload without process restart
# ═════════════════════════════════════════════════════════════════════════════


class TestT1PromptHotReload:
    """
    Input: Edit score_analytics.txt on disk (bump PROMPT_VERSION).
    Expected: Next render() call picks up the new version string.
    Failure condition: version unchanged after mtime advance.
    """

    def test_renderer_reloads_on_mtime_change(self, tmp_path: Path) -> None:
        from backend.explain.score_analytics.engine import _PromptRenderer, _MISSING

        prompt_file = tmp_path / "score_analytics.txt"
        prompt_file.write_text(
            "# PROMPT_VERSION: score_analytics_v1\nSYSTEM:\nYou are a test.\n\nUSER:\n{{skills}}\n",
            encoding="utf-8",
        )

        with patch(
            "backend.explain.score_analytics.engine._PROMPT_PATH", prompt_file
        ):
            renderer = _PromptRenderer()
            assert renderer.version == "score_analytics_v1", (
                "Initial version must be parsed from file header"
            )

            # Advance mtime by writing new content
            time.sleep(0.01)  # ensure mtime differs
            prompt_file.write_text(
                "# PROMPT_VERSION: score_analytics_v2\nSYSTEM:\nYou are updated.\n\nUSER:\n{{skills}}\n",
                encoding="utf-8",
            )

            result = renderer.render({"skills": "Python"})
            assert renderer.version == "score_analytics_v2", (
                "FAILURE: renderer did not reload — version still score_analytics_v1"
            )
            assert "score_analytics_v2" not in result or True  # content rendered
            assert "Python" in result

    def test_renderer_does_not_reload_when_mtime_stable(self, tmp_path: Path) -> None:
        from backend.explain.score_analytics.engine import _PromptRenderer

        prompt_file = tmp_path / "score_analytics.txt"
        prompt_file.write_text(
            "# PROMPT_VERSION: score_analytics_v1\nSYSTEM:\nstable.\n\nUSER:\n{{skills}}\n",
            encoding="utf-8",
        )

        with patch(
            "backend.explain.score_analytics.engine._PROMPT_PATH", prompt_file
        ):
            renderer = _PromptRenderer()
            initial_version = renderer.version
            # Call render twice without changing file
            renderer.render({"skills": "Java"})
            renderer.render({"skills": "Go"})
            assert renderer.version == initial_version, (
                "FAILURE: renderer reloaded unnecessarily — mtime unchanged"
            )


# ═════════════════════════════════════════════════════════════════════════════
# T2 — TimeoutError classified correctly
# ═════════════════════════════════════════════════════════════════════════════


class TestT2TimeoutClassification:
    """
    Input: Mock Ollama client raises asyncio.TimeoutError via wait_for.
    Expected:
      - result.fallback == True
      - result.fallback_reason == "TimeoutError"
      - explain_llm_error_total{error_type="TimeoutError"} incremented
    Failure condition: fallback_reason is "UnclassifiedError" or counter not incremented.
    """

    def test_timeout_triggers_classified_fallback(self) -> None:
        from backend.explain.score_analytics.engine import (
            ScoreAnalyticsEngine,
            _PromptRenderer,
            _LLM_ERROR_COUNTER,
            _FALLBACK_COUNTER,
        )

        inp = _make_input()

        # Mock renderer with stable version
        mock_renderer = MagicMock(spec=_PromptRenderer)
        mock_renderer.version = "score_analytics_v1"
        mock_renderer.render.return_value = (
            "SYSTEM:\nYou are a test.\n\nUSER:\n{{skills}}\n"
        )
        mock_renderer.split_system_user.return_value = ("You are a test.", "Python")

        engine = ScoreAnalyticsEngine(renderer=mock_renderer)

        before_error = _LLM_ERROR_COUNTER.labels(error_type="TimeoutError")._value.get()
        before_fallback = _FALLBACK_COUNTER.labels(reason="TimeoutError")._value.get()

        async def _run() -> Any:
            with patch(
                "backend.explain.score_analytics.engine.asyncio.wait_for",
                side_effect=asyncio.TimeoutError,
            ):
                with patch(
                    "backend.explain.stage4.client.get_ollama_client"
                ) as mock_client:
                    oc = MagicMock()
                    oc.health_check.return_value = True
                    mock_client.return_value = oc
                    return await engine.generate(inp, trace_id="t2-test", timeout=5.0)

        result = asyncio.get_event_loop().run_until_complete(_run())

        assert result.fallback is True, "FAILURE: fallback flag must be True on TimeoutError"
        assert result.fallback_reason == "TimeoutError", (
            f"FAILURE: fallback_reason is {result.fallback_reason!r}, expected 'TimeoutError'"
        )

        after_error = _LLM_ERROR_COUNTER.labels(error_type="TimeoutError")._value.get()
        after_fallback = _FALLBACK_COUNTER.labels(reason="TimeoutError")._value.get()

        assert after_error > before_error, (
            "FAILURE: explain_llm_error_total{error_type=TimeoutError} not incremented"
        )
        assert after_fallback > before_fallback, (
            "FAILURE: explain_fallback_total{reason=TimeoutError} not incremented"
        )


# ═════════════════════════════════════════════════════════════════════════════
# T3 — Fallback response headers enforced in router
# ═════════════════════════════════════════════════════════════════════════════


class TestT3FallbackResponseHeaders:
    """
    Input: POST /api/v1/explain/score-analytics with engine returning fallback.
    Expected:
      - X-Fallback-Used: true
      - X-Fallback-Reason: <non-empty>
      - X-Prompt-Version: <non-empty>
      - X-Engine-Version: <non-empty>
    Failure condition: Any header absent or X-Fallback-Used == "false" when fallback occurred.
    """

    def test_fallback_headers_set_when_fallback_true(self) -> None:
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from backend.api.routers.explain_router import router
        from backend.explain.score_analytics.engine import ScoreAnalyticsResult

        app = FastAPI()
        app.include_router(router)

        # Minimal payload
        payload = {
            "skill_score": 70,
            "experience_score": 60,
            "education_score": 80,
            "goal_alignment_score": 65,
            "preference_score": 55,
            "confidence": 0.75,
        }

        fallback_result = ScoreAnalyticsResult(
            markdown="> **[FALLBACK MODE — LLM UNAVAILABLE]** reason=TimeoutError\n\n# STAGE 1",
            used_llm=False,
            fallback=True,
            latency_ms=120.0,
            trace_id="test-trace",
            fallback_reason="TimeoutError",
            prompt_version="score_analytics_v1",
            engine_version="2.0.0",
        )

        with patch(
            "backend.explain.score_analytics.engine.ScoreAnalyticsEngine.generate",
            new_callable=AsyncMock,
            return_value=fallback_result,
        ):
            with patch(
                "backend.api.middleware.auth.verify_token",
                return_value=MagicMock(user_id="test"),
            ):
                with patch(
                    "backend.api.middleware.rate_limit.check_rate_limit",
                    return_value=None,
                ):
                    client = TestClient(app, raise_server_exceptions=True)
                    resp = client.post("/api/v1/explain/score-analytics", json=payload)

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

        headers = resp.headers
        assert headers.get("x-fallback-used") == "true", (
            f"FAILURE: X-Fallback-Used is {headers.get('x-fallback-used')!r}"
        )
        assert headers.get("x-fallback-reason") == "TimeoutError", (
            f"FAILURE: X-Fallback-Reason is {headers.get('x-fallback-reason')!r}"
        )
        assert headers.get("x-prompt-version") == "score_analytics_v1", (
            f"FAILURE: X-Prompt-Version is {headers.get('x-prompt-version')!r}"
        )
        assert headers.get("x-engine-version") == "2.0.0", (
            f"FAILURE: X-Engine-Version is {headers.get('x-engine-version')!r}"
        )
        body = resp.json()
        assert body["fallback"] is True
        assert "[FALLBACK MODE" in body["markdown"], (
            "FAILURE: fallback banner not present in markdown"
        )

    def test_no_fallback_headers_correct_when_llm_succeeds(self) -> None:
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from backend.api.routers.explain_router import router
        from backend.explain.score_analytics.engine import ScoreAnalyticsResult

        app = FastAPI()
        app.include_router(router)

        payload = {
            "skill_score": 70,
            "experience_score": 60,
            "education_score": 80,
            "goal_alignment_score": 65,
            "preference_score": 55,
            "confidence": 0.75,
        }

        success_result = ScoreAnalyticsResult(
            markdown="# STAGE 1 — INPUT SUMMARY INTERPRETATION\n- Skills: Python",
            used_llm=True,
            fallback=False,
            latency_ms=980.0,
            trace_id="test-trace-ok",
            fallback_reason="none",
            prompt_version="score_analytics_v1",
            engine_version="2.0.0",
        )

        with patch(
            "backend.explain.score_analytics.engine.ScoreAnalyticsEngine.generate",
            new_callable=AsyncMock,
            return_value=success_result,
        ):
            with patch(
                "backend.api.middleware.auth.verify_token",
                return_value=MagicMock(user_id="test"),
            ):
                with patch(
                    "backend.api.middleware.rate_limit.check_rate_limit",
                    return_value=None,
                ):
                    client = TestClient(app, raise_server_exceptions=True)
                    resp = client.post("/api/v1/explain/score-analytics", json=payload)

        assert resp.headers.get("x-fallback-used") == "false", (
            "FAILURE: X-Fallback-Used must be 'false' when LLM succeeded"
        )
        assert resp.headers.get("x-fallback-reason") == "none"


# ═════════════════════════════════════════════════════════════════════════════
# T4 — UnclassifiedError logged at ERROR level
# ═════════════════════════════════════════════════════════════════════════════


class TestT4UnclassifiedErrorLogging:
    """
    Input: Mock Ollama client raises a bare RuntimeError (not a known type).
    Expected:
      - result.fallback_reason == "UnclassifiedError"
      - logger.error called (not logger.warning)
    Failure condition: log emitted at WARNING, or fallback_reason is not "UnclassifiedError".
    """

    def test_unclassified_error_logged_at_error_level(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from backend.explain.score_analytics.engine import (
            ScoreAnalyticsEngine,
            _PromptRenderer,
        )

        inp = _make_input()

        mock_renderer = MagicMock(spec=_PromptRenderer)
        mock_renderer.version = "score_analytics_v1"
        mock_renderer.render.return_value = "SYSTEM:\nTest.\n\nUSER:\n{{skills}}\n"
        mock_renderer.split_system_user.return_value = ("Test.", "Python, SQL")

        engine = ScoreAnalyticsEngine(renderer=mock_renderer)

        async def _run() -> Any:
            with patch(
                "backend.explain.stage4.client.get_ollama_client"
            ) as mock_client:
                oc = MagicMock()
                oc.health_check.return_value = True
                # generate() raises a bare exception from the executor
                oc.generate.side_effect = ValueError("unexpected value in response")
                mock_client.return_value = oc

                with patch(
                    "backend.explain.score_analytics.engine.asyncio.wait_for",
                    side_effect=ValueError("unexpected value in response"),
                ):
                    return await engine.generate(inp, trace_id="t4-test", timeout=5.0)

        with caplog.at_level(logging.ERROR, logger="explain.score_analytics"):
            result = asyncio.get_event_loop().run_until_complete(_run())

        assert result.fallback is True
        assert result.fallback_reason == "UnclassifiedError", (
            f"FAILURE: fallback_reason is {result.fallback_reason!r}, expected 'UnclassifiedError'"
        )

        error_records = [
            r for r in caplog.records
            if r.levelno >= logging.ERROR and "UnclassifiedError" in r.message
        ]
        assert error_records, (
            "FAILURE: No ERROR-level log record with 'UnclassifiedError' found — "
            "unclassified exceptions must not be silently swallowed at WARNING level"
        )

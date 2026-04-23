# backend/explain/score_analytics/engine.py
"""
Score Analytics Engine
======================

Fills the deterministic career analytics prompt template with real scoring
data, dispatches to Ollama, and returns structured markdown.

Data mapping
------------
ScoringBreakdown field      Template placeholder        Scale
─────────────────────────   ─────────────────────────  ─────────────────
skill_score                 {{skill_score}}             [0,100] → /10 → [0,10]
experience_score            {{experience_score}}        same
education_score             {{education_score}}         same
goal_alignment_score        {{goal_alignment_score}}    same
preference_score            {{preference_score}}        same
confidence (float 0-1)      {{confidence_percent}}      *100 → %
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from prometheus_client import Counter

logger = logging.getLogger("explain.score_analytics")

# ── Package version ───────────────────────────────────────────────────────────
_ENGINE_VERSION: str = os.getenv("EXPLAIN_ENGINE_VERSION", "2.0.0")

# ── Sentinel for unavailable fields ──────────────────────────────────────────
_MISSING = "Insufficient data provided."

# ── Prompt template path ─────────────────────────────────────────────────────
_PROMPT_PATH = Path(__file__).parent / "prompts" / "score_analytics.txt"

# ── Prometheus counters ───────────────────────────────────────────────────────
_PROMPT_RELOAD_COUNTER: Counter = Counter(
    "explain_prompt_reload_total",
    "Number of times the prompt template was reloaded from disk",
    ["version"],
)
_LLM_ERROR_COUNTER: Counter = Counter(
    "explain_llm_error_total",
    "Number of LLM call failures by error type",
    ["error_type"],
)
_LLM_CALL_COUNTER: Counter = Counter(
    "explain_llm_call_total",
    "Number of LLM call attempts by status",
    ["status"],
)
_FALLBACK_COUNTER: Counter = Counter(
    "explain_fallback_total",
    "Number of fallback activations by reason",
    ["reason"],
)

# ── 0-100 → 1-10 conversion (clamp to [1, 10]) ───────────────────────────────
def _to_1_10(value: float) -> float:
    return round(max(1.0, min(10.0, value / 10.0)), 2)


# ══════════════════════════════════════════════════════════════════════════════
# Custom exception hierarchy
# ══════════════════════════════════════════════════════════════════════════════

class ScoreAnalyticsError(Exception):
    """Base for all score analytics engine errors."""


class TemplateRenderError(ScoreAnalyticsError):
    """Raised when the prompt template cannot be loaded or rendered."""


class ModelResponseError(ScoreAnalyticsError):
    """Raised when Ollama returns a non-success response or empty text."""


# ══════════════════════════════════════════════════════════════════════════════
# Input / Output models
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ScoreAnalyticsInput:
    """
    Aggregated inputs required to render the analytics prompt.

    All fields that cannot be sourced from the current DecisionInput /
    ScoringBreakdown schema are optional and default to ``None``, which
    renders as ``_MISSING`` in the prompt.
    """

    # ── From ScoringBreakdown (required) ─────────────────────────────────────
    skill_score: float           # [0, 100]
    experience_score: float      # [0, 100]
    education_score: float       # [0, 100]
    goal_alignment_score: float  # [0, 100]
    preference_score: float      # [0, 100]

    # ── Confidence (required) ─────────────────────────────────────────────────
    confidence: float            # [0.0, 1.0]

    # ── Profile fields ───────────────────────────────────────────────────────
    skills: List[str] = field(default_factory=list)
    interests: List[str] = field(default_factory=list)
    education_level: str = _MISSING
    years_experience: Optional[float] = None

    # ── Preference / goal fields ──────────────────────────────────────────────
    preferred_industry: Optional[List[str]] = None
    work_style: Optional[str] = None
    # Extended fields — not yet in DecisionInput schema
    excluded_industry: Optional[str] = None          # future
    mobility: Optional[str] = None                   # future
    languages: Optional[List[str]] = None            # future
    expected_salary: Optional[str] = None            # future (suppressed in UI)
    priority_weight: Optional[str] = None            # future
    training_horizon_months: Optional[int] = None    # derived from timeline_years if available

    # ── Convenience factory ───────────────────────────────────────────────────
    @classmethod
    def from_scoring_artifacts(
        cls,
        scoring_breakdown: Any,   # backend.scoring.sub_scorer.ScoringBreakdown
        profile: Dict[str, Any],
        confidence: float = 0.0,
        experience_years: float = 0.0,
    ) -> "ScoreAnalyticsInput":
        """
        Build from a ``ScoringBreakdown`` + normalised profile dict.

        Parameters
        ----------
        scoring_breakdown:
            Instance of ``ScoringBreakdown`` (all sub-scores in [0, 100]).
        profile:
            Merged profile dict as produced by the decision pipeline
            (keys: skills, interests, education_level, …).
        confidence:
            Explanation confidence as a float in [0.0, 1.0].
        experience_years:
            Years from ``ScoringInput.experience.years``.
        """
        prefs: Dict[str, Any] = profile.get("preferences", {}) or {}
        goals: Dict[str, Any] = profile.get("goals", {}) or {}
        timeline_y: Optional[int] = (
            int(goals.get("timeline_years", 0)) or None
        )

        return cls(
            skill_score=float(getattr(scoring_breakdown, "skill_score", 0.0)),
            experience_score=float(getattr(scoring_breakdown, "experience_score", 0.0)),
            education_score=float(getattr(scoring_breakdown, "education_score", 0.0)),
            goal_alignment_score=float(getattr(scoring_breakdown, "goal_alignment_score", 0.0)),
            preference_score=float(getattr(scoring_breakdown, "preference_score", 0.0)),
            confidence=float(confidence),
            skills=list(profile.get("skills", [])),
            interests=list(profile.get("interests", [])),
            education_level=str(profile.get("education_level", _MISSING) or _MISSING),
            years_experience=float(experience_years) if experience_years else None,
            preferred_industry=list(prefs.get("preferred_domains", [])) or None,
            work_style=str(prefs.get("work_style", "") or "") or None,
            training_horizon_months=timeline_y * 12 if timeline_y else None,
        )


@dataclass
class ScoreAnalyticsResult:
    """Result of a score analytics generation call."""

    markdown: str          # Raw LLM / fallback output
    used_llm: bool
    fallback: bool
    latency_ms: float
    trace_id: str = ""
    fallback_reason: str = "none"          # e.g. "none" | "TimeoutError" | "NetworkError" | ...
    prompt_version: str = "unknown"        # parsed from # PROMPT_VERSION header
    engine_version: str = _ENGINE_VERSION  # from _ENGINE_VERSION constant

    def to_dict(self) -> Dict[str, Any]:
        return {
            "markdown": self.markdown,
            "used_llm": self.used_llm,
            "fallback": self.fallback,
            "fallback_reason": self.fallback_reason,
            "prompt_version": self.prompt_version,
            "engine_version": self.engine_version,
            "latency_ms": round(self.latency_ms, 2),
            "trace_id": self.trace_id,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Prompt renderer
# ══════════════════════════════════════════════════════════════════════════════

_INLINE_STUB = (
    "# PROMPT_VERSION: score_analytics_stub\n"
    "SYSTEM:\nYou are a deterministic career analytics engine.\n\n"
    "USER:\nSkills: {{skills}}\nSkill Score: {{skill_score}}\n"
    "Confidence: {{confidence_percent}}%\n"
)
_VERSION_RE = re.compile(r"^#\s*PROMPT_VERSION:\s*(\S+)", re.MULTILINE)


class _PromptRenderer:
    """
    Fills ``{{variable}}`` placeholders in the analytics prompt template.

    Hot-reload contract
    -------------------
    On every call to ``render()`` the file mtime is stat-checked.  If the
    mtime has advanced the template is re-read from disk, the version string
    is re-parsed, and ``explain_prompt_reload_total`` is incremented.
    Thread-safe via a reentrant lock.
    """

    _PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._template: str = ""
        self._mtime: float = -1.0
        self.version: str = "unknown"
        self._load()  # initial load

    # ── Internal load ─────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Read template from disk, parse version header, update state."""
        if not _PROMPT_PATH.exists():
            logger.warning(
                "score_analytics prompt not found at %s; using inline stub", _PROMPT_PATH
            )
            self._template = _INLINE_STUB
            self._mtime = -1.0
            self.version = "score_analytics_stub"
            return
        try:
            text = _PROMPT_PATH.read_text(encoding="utf-8")
            mtime = _PROMPT_PATH.stat().st_mtime
        except OSError as exc:
            raise TemplateRenderError(
                f"Cannot read prompt template at {_PROMPT_PATH}: {exc}"
            ) from exc
        m = _VERSION_RE.search(text)
        new_version = m.group(1) if m else "unversioned"
        old_version = self.version
        self._template = text
        self._mtime = mtime
        self.version = new_version
        if old_version not in ("unknown", new_version, "score_analytics_stub"):
            # Version changed mid-run — count as reload
            _PROMPT_RELOAD_COUNTER.labels(version=new_version).inc()
            logger.info(
                "Prompt template reloaded: %s → %s", old_version, new_version
            )

    def _reload_if_stale(self) -> None:
        """Stat the file; reload only if mtime has advanced."""
        if not _PROMPT_PATH.exists():
            return
        try:
            current_mtime = _PROMPT_PATH.stat().st_mtime
        except OSError:
            return
        if current_mtime != self._mtime:
            with self._lock:
                # Second check inside the lock
                try:
                    current_mtime = _PROMPT_PATH.stat().st_mtime
                except OSError:
                    return
                if current_mtime != self._mtime:
                    prev_version = self.version
                    self._load()
                    _PROMPT_RELOAD_COUNTER.labels(version=self.version).inc()
                    logger.info(
                        "[hot-reload] Prompt template reloaded from disk "
                        "(mtime changed): %s → %s",
                        prev_version,
                        self.version,
                    )

    # ── Public API ────────────────────────────────────────────────────────────

    def render(self, data: Dict[str, str]) -> str:
        """Stat-check for stale template, then replace every ``{{key}}``."""
        self._reload_if_stale()
        def _replace(m: re.Match) -> str:
            return data.get(m.group(1), _MISSING)
        with self._lock:
            try:
                return self._PLACEHOLDER.sub(_replace, self._template)
            except Exception as exc:
                raise TemplateRenderError(f"Placeholder substitution failed: {exc}") from exc

    def split_system_user(self, filled: str) -> tuple[str, str]:
        """Return (system_prompt, user_prompt) extracted from filled text."""
        lines = filled.splitlines()
        system_lines: List[str] = []
        user_lines: List[str] = []
        section = "none"
        for line in lines:
            stripped = line.strip()
            if stripped == "SYSTEM:":
                section = "system"
                continue
            if stripped == "USER:":
                section = "user"
                continue
            if stripped.startswith("#"):
                continue  # skip version/comment lines
            if section == "system":
                system_lines.append(line)
            elif section == "user":
                user_lines.append(line)
        return "\n".join(system_lines).strip(), "\n".join(user_lines).strip()


def _build_substitutions(inp: ScoreAnalyticsInput) -> Dict[str, str]:
    """Map ``ScoreAnalyticsInput`` fields → template substitution dict."""

    def _list(v: Optional[List[str]]) -> str:
        return ", ".join(v) if v else _MISSING

    def _opt(v: Any) -> str:
        if v is None:
            return _MISSING
        return str(v)

    return {
        # Profile
        "skills":                   _list(inp.skills) if inp.skills else _MISSING,
        "years_experience":         _opt(inp.years_experience),
        "education_level":          inp.education_level or _MISSING,
        "interests":                _list(inp.interests) if inp.interests else _MISSING,
        "preferred_industry":       _list(inp.preferred_industry),
        "excluded_industry":        _opt(inp.excluded_industry),
        "work_style":               _opt(inp.work_style),
        "mobility":                 _opt(inp.mobility),
        "languages":                _list(inp.languages),
        "expected_salary":          _opt(inp.expected_salary),
        "priority_weight":          _opt(inp.priority_weight),
        "training_horizon_months":  _opt(inp.training_horizon_months),
        # Scores (0-100 → 1-10)
        "skill_score":              str(_to_1_10(inp.skill_score)),
        "experience_score":         str(_to_1_10(inp.experience_score)),
        "education_score":          str(_to_1_10(inp.education_score)),
        "goal_alignment_score":     str(_to_1_10(inp.goal_alignment_score)),
        "preference_score":         str(_to_1_10(inp.preference_score)),
        # Confidence (0.0-1.0 → %)
        "confidence_percent":       str(round(min(100.0, max(0.0, inp.confidence * 100)), 1)),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Engine
# ══════════════════════════════════════════════════════════════════════════════

class ScoreAnalyticsEngine:
    """
    Generates a structured analytics explanation from scoring results.

    Workflow
    --------
    1. ``ScoreAnalyticsInput.from_scoring_artifacts()`` to build the input.
    2. Call ``await engine.generate(input, trace_id)`` to get a
       ``ScoreAnalyticsResult`` containing the markdown text.

    LLM is used via the existing Ollama adapter.  If Ollama is unavailable, a
    deterministic fallback is produced directly from the filled-in prompt.
    """

    # Maximum LLM output length accepted (chars)
    MAX_OUTPUT_LEN = 6000

    def __init__(self, renderer: Optional[_PromptRenderer] = None) -> None:
        # Accept an injected renderer so callers can share the hot-reloading
        # instance without keeping state in this class.
        self._renderer: _PromptRenderer = renderer if renderer is not None else _PromptRenderer()

    # ── Public entry point ────────────────────────────────────────────────────

    async def generate(
        self,
        inp: ScoreAnalyticsInput,
        trace_id: str = "",
        timeout: float = 30.0,
    ) -> ScoreAnalyticsResult:
        """
        Generate a score analytics markdown document.

        Falls back to the deterministic template output (no LLM) if Ollama
        is unavailable or the call exceeds *timeout* seconds.
        Each failure branch emits a typed Prometheus counter and logs at ERROR.
        """
        start = time.monotonic()

        # ── Render prompt (may raise TemplateRenderError) ─────────────────────
        try:
            subs = _build_substitutions(inp)
            filled = self._renderer.render(subs)
            system_prompt, user_prompt = self._renderer.split_system_user(filled)
        except TemplateRenderError as exc:
            latency_ms = (time.monotonic() - start) * 1000
            _LLM_ERROR_COUNTER.labels(error_type="TemplateRenderError").inc()
            _FALLBACK_COUNTER.labels(reason="TemplateRenderError").inc()
            logger.error(
                "[%s] TemplateRenderError — falling back: %s",
                trace_id, exc, exc_info=True,
            )
            subs = _build_substitutions(inp)  # re-build without renderer
            return ScoreAnalyticsResult(
                markdown=self._deterministic_fallback(subs, "TemplateRenderError"),
                used_llm=False,
                fallback=True,
                latency_ms=latency_ms,
                trace_id=trace_id,
                fallback_reason="TemplateRenderError",
                prompt_version=self._renderer.version,
                engine_version=_ENGINE_VERSION,
            )

        prompt_version = self._renderer.version

        # ── LLM call ──────────────────────────────────────────────────────────
        _client_ref = None
        _original_timeout = None
        try:
            from backend.explain.stage4.client import get_ollama_client  # lazy import

            _client_ref = get_ollama_client()
            if not _client_ref.health_check():
                raise OSError("Ollama health_check() returned False")

            # Give each HTTP attempt a fair share of the outer timeout budget.
            # With DEFAULT_MAX_RETRIES=2 (3 attempts total) we reserve a small
            # fraction for backoff sleeps; floor at 5s so we never go below the
            # original hard-coded default.
            _per_attempt = max(5.0, (timeout * 0.9) / (_client_ref._max_retries + 1))
            _original_timeout = _client_ref._timeout
            _client_ref.configure(timeout=_per_attempt)

            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: _client_ref.generate(
                        prompt=user_prompt,
                        system_prompt=system_prompt,
                        temperature=0.1,
                        max_tokens=900,
                    ),
                ),
                timeout=timeout,
            )

            if not (response.success and response.text):
                raise ModelResponseError(
                    f"Ollama returned non-success response: {response.error!r}"
                )

            latency_ms = (time.monotonic() - start) * 1000
            text = response.text[: self.MAX_OUTPUT_LEN]
            _LLM_CALL_COUNTER.labels(status="success").inc()
            logger.info(
                "[%s] ScoreAnalytics LLM ok — %d chars in %.0f ms (prompt=%s)",
                trace_id, len(text), latency_ms, prompt_version,
            )
            return ScoreAnalyticsResult(
                markdown=text,
                used_llm=True,
                fallback=False,
                latency_ms=latency_ms,
                trace_id=trace_id,
                fallback_reason="none",
                prompt_version=prompt_version,
                engine_version=_ENGINE_VERSION,
            )

        except asyncio.TimeoutError as exc:
            error_type = "TimeoutError"
            log_msg = f"LLM call timed out after {timeout}s"
        except OSError as exc:
            error_type = "NetworkError"
            log_msg = f"Network/socket error reaching Ollama: {exc}"
        except TemplateRenderError as exc:
            error_type = "TemplateRenderError"
            log_msg = f"Template render failed inside LLM path: {exc}"
        except ModelResponseError as exc:
            error_type = "ModelResponseError"
            log_msg = f"Ollama returned invalid response: {exc}"
        except Exception as exc:
            error_type = "UnclassifiedError"
            log_msg = f"Unexpected engine failure: {exc}"
        finally:
            # Always restore the singleton client's original timeout
            if _client_ref is not None and _original_timeout is not None:
                try:
                    _client_ref.configure(timeout=_original_timeout)
                except Exception:
                    pass

        latency_ms = (time.monotonic() - start) * 1000
        _LLM_ERROR_COUNTER.labels(error_type=error_type).inc()
        _LLM_CALL_COUNTER.labels(status="error").inc()
        _FALLBACK_COUNTER.labels(reason=error_type).inc()
        logger.error(
            "[%s] ScoreAnalytics %s — activating deterministic fallback (%.0f ms): %s",
            trace_id, error_type, latency_ms, log_msg,
            exc_info=(error_type == "UnclassifiedError"),
        )
        return ScoreAnalyticsResult(
            markdown=self._deterministic_fallback(subs, error_type),
            used_llm=False,
            fallback=True,
            latency_ms=latency_ms,
            trace_id=trace_id,
            fallback_reason=error_type,
            prompt_version=prompt_version,
            engine_version=_ENGINE_VERSION,
        )

    # ── Deterministic fallback ────────────────────────────────────────────────

    @staticmethod
    def _deterministic_fallback(subs: Dict[str, str], reason: str = "none") -> str:
        """
        Return a minimal but spec-compliant analytics markdown when the LLM
        is not available.  Always prepends a visible fallback banner.
        """
        banner = f"> **[FALLBACK MODE — LLM UNAVAILABLE]** reason={reason}\n\n"
        return banner + f"""\
# STAGE 1 — INPUT SUMMARY INTERPRETATION
- **Skills**: {subs['skills']}
- **Experience**: {subs['years_experience']} years
- **Education**: {subs['education_level']}
- **Interests**: {subs['interests']}
- **Preferred Industry**: {subs['preferred_industry']}
- **Excluded Industry**: {subs['excluded_industry']}
- **Work Style**: {subs['work_style']}
- **Mobility**: {subs['mobility']}
- **Languages**: {subs['languages']}
- **Expected Salary**: {subs['expected_salary']}
- **Priority Weight**: {subs['priority_weight']}
- **Training Horizon (months)**: {subs['training_horizon_months']}

# STAGE 2 — SCORE ANALYSIS

## 1. Skill Score: {subs['skill_score']} / 10
Derived from declared skill breadth and alignment to target domain. \
Score reflects number and relevance of listed skills relative to the scoring threshold.

## 2. Experience Score: {subs['experience_score']} / 10
Based on {subs['years_experience']} years of documented experience. \
Scaling applies a logarithmic curve; early years contribute more per unit than later years.

## 3. Education Score: {subs['education_score']} / 10
Mapped from education level enum ({subs['education_level']}). \
Score reflects the standard education-to-score mapping table.

## 4. Goal Alignment Score: {subs['goal_alignment_score']} / 10
Derived from overlap between declared interests ({subs['interests']}) \
and preferred industry ({subs['preferred_industry']}). \
Excluded industry constraints: {subs['excluded_industry']}.

## 5. Preference Score: {subs['preference_score']} / 10
Composed of work style ({subs['work_style']}), mobility ({subs['mobility']}), \
language compatibility ({subs['languages']}), and salary alignment \
({subs['expected_salary']}).

# STAGE 3 — STRENGTHS
- Education level ({subs['education_level']}) meets standard scoring threshold.
- Declared interests align with preferred industry selection.

# STAGE 4 — LIMITATIONS
- Excluded Industry: {subs['excluded_industry']}
- Mobility data: {subs['mobility']}
- Language data: {subs['languages']}
- Expected salary data: {subs['expected_salary']}
- Priority weight data: {subs['priority_weight']}

# STAGE 5 — IMPROVEMENT LEVERS
- **Skill Score**: Add more domain-relevant skills to increase breadth coverage.
- **Experience Score**: Accumulate additional years in primary domain.
- **Goal Alignment Score**: Narrow preferred industries to reduce misalignment penalty.
- **Preference Score**: Provide mobility, language, and salary data to reduce missing-field penalty.

# STAGE 6 — CONFIDENCE JUSTIFICATION
Confidence is {subs['confidence_percent']}%.
Fields with missing data: \
{', '.join(k for k, v in subs.items() if v == _MISSING) or 'none'}.
Internal consistency: scores derived from deterministic SIMGR algorithm with no LLM override.
"""


# ══════════════════════════════════════════════════════════════════════════════
# Engine factory — NO MODULE-LEVEL SINGLETON
# ══════════════════════════════════════════════════════════════════════════════

# _PromptRenderer is shared across request-scoped engines so file-stat
# overhead is paid once per mtime change, not once per request.
_shared_renderer: Optional[_PromptRenderer] = None
_renderer_lock = threading.Lock()


def _get_shared_renderer() -> _PromptRenderer:
    """Return a process-wide _PromptRenderer (hot-reload capable)."""
    global _shared_renderer
    if _shared_renderer is None:
        with _renderer_lock:
            if _shared_renderer is None:
                _shared_renderer = _PromptRenderer()
    return _shared_renderer


def get_score_analytics_engine() -> ScoreAnalyticsEngine:
    """
    Return a new ``ScoreAnalyticsEngine`` instance backed by the shared
    hot-reloading renderer.  No module-level engine state is cached.
    Safe to call from FastAPI ``Depends``.
    """
    return ScoreAnalyticsEngine(renderer=_get_shared_renderer())


async def render_score_analytics(
    scoring_breakdown: Any,
    profile: Dict[str, Any],
    confidence: float = 0.0,
    experience_years: float = 0.0,
    trace_id: str = "",
    timeout: float = 5.0,
) -> str:
    """
    Convenience wrapper: build input, generate, return markdown string.

    Parameters
    ----------
    scoring_breakdown:
        ``ScoringBreakdown`` instance from the SIMGR scoring step.
    profile:
        Merged profile dict (skills, interests, education_level, …).
    confidence:
        Explanation confidence in [0.0, 1.0].
    experience_years:
        From ``ScoringInput.experience.years``.
    trace_id:
        Pipeline trace identifier for logging.
    timeout:
        Maximum seconds to wait for the LLM response (default 5s for fast fallback).

    Returns
    -------
    str
        Structured markdown document per the analytics prompt spec.
    """
    inp = ScoreAnalyticsInput.from_scoring_artifacts(
        scoring_breakdown=scoring_breakdown,
        profile=profile,
        confidence=confidence,
        experience_years=experience_years,
    )
    result = await get_score_analytics_engine().generate(inp, trace_id=trace_id, timeout=timeout)
    return result.markdown

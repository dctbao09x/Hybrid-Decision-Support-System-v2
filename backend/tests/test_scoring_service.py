# backend/tests/test_scoring_service.py
"""
Unit tests for backend.scoring.scoring_service.ScoringService
==============================================================

P5 PASS criteria:
- ScoringService contains all scoring business logic.
- ScoringService does NOT import from any router.
- health(), get_config(), get_weights(), reset(), rank(), score(),
  simulate(), compute_decision_breakdown() all work correctly.

P6 PASS criteria:
- compute_decision_breakdown() returns ml_score, rule_score, penalty,
  final_score, result_hash.
- Determinism: same inputs → same result_hash.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_engine_output(scored_careers):
    out = MagicMock()
    out.results = scored_careers
    return out


def _make_scored_career(name: str, total: float = 0.7, components: dict = None):
    sc = MagicMock()
    sc.career_name = name
    sc.total_score = total
    sc.components = components or {
        "study": 0.75, "interest": 0.65, "market": 0.70,
        "growth": 0.60, "risk": 0.20,
    }
    sc.domain = "technology"
    return sc


def _sample_profile() -> dict:
    return {
        "skills": ["python", "machine learning"],
        "interests": ["technology", "science"],
        "education_level": "Bachelor",
        "ability_score": 0.7,
        "confidence_score": 0.65,
    }


def _sample_career_list():
    return [
        {"name": "Software Engineer", "domain": "technology",
         "required_skills": ["python"], "preferred_skills": ["git"],
         "ai_relevance": 0.8, "growth_rate": 0.7, "competition": 0.5},
        {"name": "Data Scientist", "domain": "data",
         "required_skills": ["statistics"], "preferred_skills": ["python"],
         "ai_relevance": 0.9, "growth_rate": 0.8, "competition": 0.6},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Prompt 5 gate: no router import inside scoring_service
# ─────────────────────────────────────────────────────────────────────────────

class TestScoringServiceNoBizLogicInRouter:
    def test_scoring_service_does_not_import_router(self):
        import inspect
        from backend.scoring import scoring_service
        src = inspect.getsource(scoring_service)
        assert "routers" not in src, (
            "scoring_service must not import from any router module"
        )

    def test_scoring_service_module_importable(self):
        from backend.scoring.scoring_service import ScoringService
        assert ScoringService is not None


# ─────────────────────────────────────────────────────────────────────────────
# health()
# ─────────────────────────────────────────────────────────────────────────────

class TestScoringServiceHealth:
    def test_health_returns_dict(self):
        from backend.scoring.scoring_service import ScoringService, inject_engine
        inject_engine(MagicMock())
        result = ScoringService.health()
        assert isinstance(result, dict)

    def test_health_keys_present(self):
        from backend.scoring.scoring_service import ScoringService, inject_engine
        inject_engine(MagicMock())
        h = ScoringService.health()
        for key in ("service", "healthy", "uptime_seconds", "engine_ready"):
            assert key in h

    def test_health_true_when_engine_ready(self):
        from backend.scoring.scoring_service import ScoringService, inject_engine
        inject_engine(MagicMock())
        assert ScoringService.health()["healthy"] is True

    def test_health_graceful_on_error(self):
        """Injecting None-like engine should still return a response."""
        from backend.scoring.scoring_service import ScoringService
        with patch("backend.scoring.scoring_service._get_engine", side_effect=RuntimeError("broken")):
            result = ScoringService.health()
        assert result["healthy"] is False


# ─────────────────────────────────────────────────────────────────────────────
# get_config()
# ─────────────────────────────────────────────────────────────────────────────

class TestScoringServiceGetConfig:
    def test_returns_dict(self):
        from backend.scoring.scoring_service import ScoringService
        result = ScoringService.get_config()
        assert isinstance(result, dict)

    def test_has_default_strategy(self):
        from backend.scoring.scoring_service import ScoringService
        result = ScoringService.get_config()
        assert "default_strategy" in result

    def test_has_available_strategies(self):
        from backend.scoring.scoring_service import ScoringService
        result = ScoringService.get_config()
        assert "available_strategies" in result
        assert isinstance(result["available_strategies"], list)


# ─────────────────────────────────────────────────────────────────────────────
# get_weights()
# ─────────────────────────────────────────────────────────────────────────────

class TestScoringServiceGetWeights:
    def test_returns_weights_key(self):
        from backend.scoring.scoring_service import ScoringService
        result = ScoringService.get_weights()
        assert "weights" in result

    def test_weights_are_dict(self):
        from backend.scoring.scoring_service import ScoringService
        w = ScoringService.get_weights()["weights"]
        assert isinstance(w, dict)

    def test_weights_sum_close_to_one(self):
        from backend.scoring.scoring_service import ScoringService
        w = ScoringService.get_weights()["weights"]
        total = sum(w.values())
        assert abs(total - 1.0) < 0.01, f"Weights sum = {total}, expected ~1.0"


# ─────────────────────────────────────────────────────────────────────────────
# reset()
# ─────────────────────────────────────────────────────────────────────────────

class TestScoringServiceReset:
    def test_reset_returns_true(self):
        from backend.scoring.scoring_service import ScoringService
        result = ScoringService.reset()
        assert result["reset"] is True

    def test_reset_clears_engine_cache(self):
        from backend.scoring.scoring_service import ScoringService, inject_engine
        inject_engine(MagicMock())
        ScoringService.reset()
        import backend.scoring.scoring_service as svc_mod
        assert svc_mod._engine_instance is None


# ─────────────────────────────────────────────────────────────────────────────
# rank()
# ─────────────────────────────────────────────────────────────────────────────

class TestScoringServiceRank:
    def test_empty_careers_returns_empty(self):
        from backend.scoring.scoring_service import ScoringService, inject_engine
        inject_engine(MagicMock())
        result = ScoringService.rank(_sample_profile(), [])
        assert result["ranked_careers"] == []

    def test_ranked_careers_present(self):
        from backend.scoring.scoring_service import ScoringService, inject_engine
        mock_engine = MagicMock()
        mock_engine.rank.return_value = _make_engine_output([
            _make_scored_career("Software Engineer", 0.8),
            _make_scored_career("Data Scientist", 0.6),
        ])
        inject_engine(mock_engine)
        result = ScoringService.rank(_sample_profile(), _sample_career_list())
        assert len(result["ranked_careers"]) == 2

    def test_top_n_limits_results(self):
        from backend.scoring.scoring_service import ScoringService, inject_engine
        mock_engine = MagicMock()
        mock_engine.rank.return_value = _make_engine_output([
            _make_scored_career("A", 0.9),
            _make_scored_career("B", 0.7),
            _make_scored_career("C", 0.5),
        ])
        inject_engine(mock_engine)
        result = ScoringService.rank(_sample_profile(), _sample_career_list() * 3, top_n=1)
        assert len(result["ranked_careers"]) == 1

    def test_each_career_has_required_fields(self):
        from backend.scoring.scoring_service import ScoringService, inject_engine
        mock_engine = MagicMock()
        mock_engine.rank.return_value = _make_engine_output([
            _make_scored_career("Software Engineer", 0.8),
        ])
        inject_engine(mock_engine)
        result = ScoringService.rank(_sample_profile(), _sample_career_list())
        career = result["ranked_careers"][0]
        for key in ("name", "total_score", "rank", "skill_score", "interest_score",
                    "market_score", "growth_score", "risk_score"):
            assert key in career, f"Missing key: {key}"

    def test_raises_on_engine_error(self):
        """If engine raises, rank() must surface a controlled runtime error."""
        from backend.scoring.scoring_service import ScoringService, inject_engine
        bad_engine = MagicMock()
        bad_engine.rank.side_effect = RuntimeError("engine broken")
        inject_engine(bad_engine)
        with pytest.raises(RuntimeError, match="scoring_engine_error"):
            ScoringService.rank(_sample_profile(), _sample_career_list())


# ─────────────────────────────────────────────────────────────────────────────
# _compute_result_hash() — determinism
# ─────────────────────────────────────────────────────────────────────────────

class TestDeterminism:
    def test_same_inputs_same_hash(self):
        from backend.scoring.scoring_service import _compute_result_hash
        h1 = _compute_result_hash(0.75, 0.0, 0.02, 0.75)
        h2 = _compute_result_hash(0.75, 0.0, 0.02, 0.75)
        assert h1 == h2

    def test_different_ml_score_different_hash(self):
        from backend.scoring.scoring_service import _compute_result_hash
        h1 = _compute_result_hash(0.75, 0.0, 0.02, 0.75)
        h2 = _compute_result_hash(0.80, 0.0, 0.02, 0.80)
        assert h1 != h2

    def test_hash_is_64_char_hex(self):
        """SHA-256 hex digest is always 64 chars."""
        from backend.scoring.scoring_service import _compute_result_hash
        h = _compute_result_hash(0.5, 0.1, 0.05, 0.5)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_float_precision_does_not_break_determinism(self):
        """Rounding to 6 dp must ensure stability across equivalent floats."""
        from backend.scoring.scoring_service import _compute_result_hash
        h1 = _compute_result_hash(0.750000000001, 0.0, 0.02, 0.750000000001)
        h2 = _compute_result_hash(0.750000000002, 0.0, 0.02, 0.750000000002)
        # Both round to 0.75 at 6 dp → same hash
        assert h1 == h2


# ─────────────────────────────────────────────────────────────────────────────
# compute_decision_breakdown() — P6
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeDecisionBreakdown:
    """Prompt 6: breakdown must expose ml_score, rule_score, penalty,
    final_score, result_hash.  All scores must be numeric."""

    def _make_top_career(self, total_score=0.75, risk_score=0.2):
        career = MagicMock()
        career.total_score = total_score
        career.risk_score = risk_score
        return career

    def _make_scoring_input(self):
        """Return a minimal ScoringInput-compatible dict."""
        return {
            "skills": ["python", "ml"],
            "experience": {"years": 3, "domains": ["software"]},
            "education": {"level": "Bachelor"},
            "goals": {"career_aspirations": ["engineer"], "timeline_years": 5},
            "preferences": {"preferred_domains": ["tech"], "work_style": "remote"},
            "personal_profile": {
                "ability_score": 0.7,
                "confidence_score": 0.65,
                "interests": ["technology"],
            },
        }

    def test_breakdown_has_required_p6_fields(self):
        from backend.scoring.scoring_service import ScoringService
        bd = ScoringService.compute_decision_breakdown(
            self._make_scoring_input(),
            top_career=self._make_top_career(0.75),
        )
        for key in ("ml_score", "rule_score", "penalty", "final_score", "result_hash"):
            assert key in bd, f"Breakdown missing required field: {key}"

    def test_ml_score_matches_top_career_total(self):
        from backend.scoring.scoring_service import ScoringService
        top = self._make_top_career(total_score=0.82)
        bd = ScoringService.compute_decision_breakdown(self._make_scoring_input(), top_career=top)
        assert abs(bd["ml_score"] - 0.82) < 1e-4

    def test_rule_score_zero_when_no_rule_result(self):
        from backend.scoring.scoring_service import ScoringService
        bd = ScoringService.compute_decision_breakdown(
            self._make_scoring_input(),
            top_career=self._make_top_career(),
            rule_result=None,
        )
        assert bd["rule_score"] == 0.0

    def test_rule_score_nonzero_when_rule_result_provided(self):
        from backend.scoring.scoring_service import ScoringService
        bd = ScoringService.compute_decision_breakdown(
            self._make_scoring_input(),
            top_career=self._make_top_career(),
            rule_result={"score_delta": 5.0},
        )
        # 5.0 / 10.0 = 0.5
        assert bd["rule_score"] == pytest.approx(0.5, abs=1e-4)

    def test_penalty_is_nonnegative(self):
        from backend.scoring.scoring_service import ScoringService
        bd = ScoringService.compute_decision_breakdown(
            self._make_scoring_input(),
            top_career=self._make_top_career(0.75, risk_score=0.3),
        )
        assert bd["penalty"] >= 0.0

    def test_final_score_equals_ml_score(self):
        """SIMGR is the authority — final_score = ml_score."""
        from backend.scoring.scoring_service import ScoringService
        top = self._make_top_career(total_score=0.65)
        bd = ScoringService.compute_decision_breakdown(self._make_scoring_input(), top_career=top)
        assert abs(bd["final_score"] - 0.65) < 1e-4

    def test_result_hash_is_64_hex_chars(self):
        from backend.scoring.scoring_service import ScoringService
        bd = ScoringService.compute_decision_breakdown(
            self._make_scoring_input(),
            top_career=self._make_top_career(),
        )
        assert len(bd["result_hash"]) == 64

    def test_result_hash_deterministic(self):
        """Same scoring_input + same top_career → same result_hash."""
        from backend.scoring.scoring_service import ScoringService
        si = self._make_scoring_input()
        top = self._make_top_career(0.75, 0.2)
        bd1 = ScoringService.compute_decision_breakdown(si, top_career=top)
        bd2 = ScoringService.compute_decision_breakdown(si, top_career=top)
        assert bd1["result_hash"] == bd2["result_hash"]

    def test_breakdown_includes_sub_scores(self):
        """P5: sub-score decomposition fields must still be present."""
        from backend.scoring.scoring_service import ScoringService
        bd = ScoringService.compute_decision_breakdown(
            self._make_scoring_input(),
            top_career=self._make_top_career(),
        )
        for key in ("skill_score", "experience_score", "education_score",
                    "goal_alignment_score", "preference_score"):
            assert key in bd, f"Sub-score field missing: {key}"

    def test_breakdown_without_top_career(self):
        """No top_career → ml_score=0, final_score=0, hash still valid."""
        from backend.scoring.scoring_service import ScoringService
        bd = ScoringService.compute_decision_breakdown(self._make_scoring_input())
        assert bd["ml_score"] == 0.0
        assert bd["final_score"] == 0.0
        assert len(bd["result_hash"]) == 64

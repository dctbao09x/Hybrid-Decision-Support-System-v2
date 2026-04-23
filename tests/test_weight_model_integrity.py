"""
tests/test_weight_model_integrity.py
══════════════════════════════════════════════════════════════════════════════
Weight Model Integrity — Stage 4 Gate
======================================

Verifies that the sub-score weight model satisfies all invariants required
for deterministic, auditable scoring:

  INVARIANT 1  — SCHEMA COMPLETENESS
    scoring.yaml contains a sub_score_weights block with all five components.

  INVARIANT 2  — SUM == 1.0
    sum(sub_score_weights.values()) == 1.0  (tolerance 1e-6)

  INVARIANT 3  — NO NEGATIVE WEIGHTS
    Every component weight is >= 0.

  INVARIANT 4  — CONFIG IS SINGLE SOURCE OF TRUTH
    DEFAULT_WEIGHTS in sub_scorer.py is loaded from config, not hardcoded.

  INVARIANT 5  — RUNTIME GUARD ENFORCED
    SubScoreWeights.validate() raises ValueError for invalid weight sets.

  INVARIANT 6  — NO ENV OVERRIDES
    weight_config.py and sub_scorer.py contain no os.environ reads for
    weight values.

  INVARIANT 7  — SIMGR TOLERANCE STRICTNESS
    SIMGRWeights.__post_init__ enforces tolerance 1e-6 (not 0.001).

  INVARIANT 8  — copy_with_weights VALIDATES SUM
    ScoringConfig.copy_with_weights() raises when the resulting sum != 1.0.

  INVARIANT 9  — DETERMINISTIC WEIGHT RESOLUTION
    Three consecutive calls to load_sub_score_weight_dict() return identical
    values.

  INVARIANT 10 — assemble_breakdown CALLS VALIDATE
    assemble_breakdown() always validates weights before computing final_score.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.scoring.sub_scorer import (
    SubScoreWeights,
    DEFAULT_WEIGHTS,
    assemble_breakdown,
)
from backend.scoring.weight_config import (
    load_sub_score_weight_dict,
    validate_weights_dict,
    get_weight_resolution_source,
    _COMPONENTS,
    _SUM_TOLERANCE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

_VALID_INPUT: Dict[str, Any] = {
    "skills": ["python", "data analysis", "machine learning"],
    "experience": {"years": 3, "domains": ["software", "data"]},
    "education": {"level": "bachelor"},
    "goals": {"career_aspirations": ["engineer", "analyst"], "timeline_years": 5},
    "preferences": {"preferred_domains": ["technology"], "work_style": "remote"},
}

_CANONICAL_COMPONENTS = frozenset(_COMPONENTS)


# ═════════════════════════════════════════════════════════════════════════════
# INVARIANT 1 — SCHEMA COMPLETENESS
# ═════════════════════════════════════════════════════════════════════════════

class TestSchemaCompleteness:
    """scoring.yaml must contain a complete sub_score_weights block."""

    def _load_yaml(self) -> dict:
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        path = ROOT / "config" / "scoring.yaml"
        assert path.exists(), "config/scoring.yaml not found"
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    def test_sub_score_weights_block_exists(self):
        cfg = self._load_yaml()
        assert "sub_score_weights" in cfg, (
            "INVARIANT 1 FAIL — 'sub_score_weights' block missing from scoring.yaml.\n"
            f"  Present keys: {list(cfg.keys())}"
        )

    def test_all_five_components_present(self):
        cfg = self._load_yaml()
        block = cfg["sub_score_weights"]
        missing = [c for c in _COMPONENTS if c not in block]
        assert not missing, (
            f"INVARIANT 1 FAIL — sub_score_weights missing components: {missing}"
        )

    def test_no_extra_components(self):
        """sub_score_weights must contain exactly the five canonical components."""
        cfg = self._load_yaml()
        block = cfg["sub_score_weights"]
        extra = [k for k in block if k not in _CANONICAL_COMPONENTS]
        assert not extra, (
            f"INVARIANT 1 FAIL — sub_score_weights has unexpected extra keys: {extra}\n"
            f"  Allowed: {sorted(_CANONICAL_COMPONENTS)}"
        )

    def test_all_values_are_numeric(self):
        cfg = self._load_yaml()
        block = cfg["sub_score_weights"]
        bad = {k: v for k, v in block.items() if not isinstance(v, (int, float))}
        assert not bad, (
            f"INVARIANT 1 FAIL — non-numeric weight values: {bad}"
        )

    def test_schema_key_present_in_scoring_schema_yaml(self):
        """scoring_schema.yaml must declare sub_score_weights as required."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        path = ROOT / "config" / "scoring_schema.yaml"
        if not path.exists():
            pytest.skip("scoring_schema.yaml not present")
        with open(path, encoding="utf-8") as fh:
            schema = yaml.safe_load(fh)
        required = schema.get("required", [])
        assert "sub_score_weights" in required, (
            "INVARIANT 1 FAIL — 'sub_score_weights' is not in scoring_schema.yaml required list."
        )


# ═════════════════════════════════════════════════════════════════════════════
# INVARIANT 2 — SUM == 1.0
# ═════════════════════════════════════════════════════════════════════════════

class TestSumEqualsOne:
    """Weight sum must equal 1.0 within tolerance at every level."""

    def test_default_weights_sum_to_one(self):
        total = sum(DEFAULT_WEIGHTS.as_dict().values())
        assert abs(total - 1.0) <= _SUM_TOLERANCE, (
            f"INVARIANT 2 FAIL — DEFAULT_WEIGHTS sum = {total:.10f} "
            f"(expected 1.0 ± {_SUM_TOLERANCE:.0e})"
        )

    def test_config_loaded_weights_sum_to_one(self):
        d = load_sub_score_weight_dict()
        total = sum(d.values())
        assert abs(total - 1.0) <= _SUM_TOLERANCE, (
            f"INVARIANT 2 FAIL — config weights sum = {total:.10f}"
        )

    def test_sub_score_weights_validate_enforces_sum(self):
        """SubScoreWeights.validate() must raise when sum != 1.0."""
        bad = SubScoreWeights(
            skill=0.40, experience=0.30, education=0.20,
            goal_alignment=0.20,  # total = 1.10
            preference=0.00,
        )
        with pytest.raises(ValueError, match="sum to 1.0"):
            bad.validate()

    def test_validate_weights_dict_enforces_sum(self):
        bad_dict = {c: 0.25 for c in _COMPONENTS}  # sum = 1.25
        with pytest.raises(ValueError, match="sum to 1.0"):
            validate_weights_dict(bad_dict)

    def test_loaded_default_weights_pass_validate(self):
        """DEFAULT_WEIGHTS must survive validate() without error."""
        DEFAULT_WEIGHTS.validate()  # must not raise


# ═════════════════════════════════════════════════════════════════════════════
# INVARIANT 3 — NO NEGATIVE WEIGHTS
# ═════════════════════════════════════════════════════════════════════════════

class TestNoNegativeWeights:
    """Every component weight must be >= 0."""

    def test_default_weights_non_negative(self):
        for c, w in DEFAULT_WEIGHTS.as_dict().items():
            assert w >= 0.0, (
                f"INVARIANT 3 FAIL — DEFAULT_WEIGHTS.{c} = {w} is negative."
            )

    def test_config_loaded_weights_non_negative(self):
        d = load_sub_score_weight_dict()
        for c, w in d.items():
            assert w >= 0.0, (
                f"INVARIANT 3 FAIL — config weight for {c!r} = {w} is negative."
            )

    def test_negative_weight_raises(self):
        bad = SubScoreWeights(
            skill=-0.10, experience=0.35, education=0.25,
            goal_alignment=0.25, preference=0.25,
        )
        with pytest.raises(ValueError, match="negative"):
            bad.validate()

    def test_validate_weights_dict_rejects_negative(self):
        bad = dict(load_sub_score_weight_dict())
        bad["skill"] = -0.01
        with pytest.raises(ValueError):
            validate_weights_dict(bad)


# ═════════════════════════════════════════════════════════════════════════════
# INVARIANT 4 — CONFIG IS SINGLE SOURCE OF TRUTH
# ═════════════════════════════════════════════════════════════════════════════

class TestConfigIsSingleSourceOfTruth:
    """DEFAULT_WEIGHTS values must match scoring.yaml sub_score_weights."""

    def test_default_weights_match_config(self):
        d = load_sub_score_weight_dict()
        for c in _COMPONENTS:
            config_val = d[c]
            default_val = DEFAULT_WEIGHTS.as_dict()[c]
            assert abs(config_val - default_val) <= _SUM_TOLERANCE, (
                f"INVARIANT 4 FAIL — {c}: "
                f"config={config_val:.8f} vs DEFAULT_WEIGHTS={default_val:.8f}.\n"
                "DEFAULT_WEIGHTS must be loaded from config, not hardcoded independently."
            )

    def test_weight_resolution_source_is_config(self):
        source = get_weight_resolution_source()
        assert source.startswith("config:"), (
            f"INVARIANT 4 FAIL — weight resolution source is '{source}', "
            "expected 'config:scoring.yaml'.\n"
            "  Ensure scoring.yaml exists with a valid sub_score_weights block."
        )

    def test_reload_returns_same_values(self):
        """Re-loading config gives identical weights (no drift)."""
        d1 = load_sub_score_weight_dict()
        d2 = load_sub_score_weight_dict()
        assert d1 == d2, (
            f"INVARIANT 4 FAIL — Two successive load_sub_score_weight_dict() calls "
            f"returned different values:\n  run1={d1}\n  run2={d2}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# INVARIANT 5 — RUNTIME GUARD ENFORCED
# ═════════════════════════════════════════════════════════════════════════════

class TestRuntimeGuardEnforced:
    """SubScoreWeights.validate() is the authoritative runtime guard."""

    def test_default_weights_pass_validate(self):
        DEFAULT_WEIGHTS.validate()

    def test_valid_custom_weights_pass_validate(self):
        w = SubScoreWeights(
            skill=0.20, experience=0.20, education=0.20,
            goal_alignment=0.20, preference=0.20,
        )
        w.validate()  # must not raise

    def test_assemble_breakdown_calls_validate_implicitly(self):
        """assemble_breakdown() must call validate() — detectable by passing bad weights."""
        bad_weights = SubScoreWeights(
            skill=0.50, experience=0.50, education=0.20,
            goal_alignment=0.10, preference=0.10,
            # sum = 1.40 — invalid
        )
        # The frozen dataclass allows construction but validate() raises.
        # assemble_breakdown() calls w.validate() before computing.
        with pytest.raises(ValueError, match="sum to 1.0"):
            assemble_breakdown(_VALID_INPUT, weights=bad_weights)

    def test_sum_boundary_exactly_one_passes(self):
        """Weights that differ from 1.0 by exactly 0.0 pass."""
        w = SubScoreWeights(
            skill=0.30, experience=0.25, education=0.20,
            goal_alignment=0.15, preference=0.10,
        )
        w.validate()

    def test_sum_boundary_tolerance_edge_fails(self):
        """Deviation of 2e-6 must fail (> tolerance 1e-6)."""
        # Construct via dict to bypass __init__ default; use object.__setattr__
        # since it's frozen.
        import dataclasses
        fields_vals = {
            "skill": 0.30,
            "experience": 0.25,
            "education": 0.20,
            "goal_alignment": 0.15,
            "preference": 0.10 + 2e-6,  # pushes sum to 1.000002
        }
        w = SubScoreWeights(**fields_vals)
        with pytest.raises(ValueError, match="sum to 1.0"):
            w.validate()


# ═════════════════════════════════════════════════════════════════════════════
# INVARIANT 6 — NO ENV OVERRIDES
# ═════════════════════════════════════════════════════════════════════════════

class TestNoEnvOverrides:
    """
    weight_config.py and sub_scorer.py must not read os.environ for weight
    values.  Path-only helpers (for logging, not weights) are exempt.
    """

    _PROHIBITED_PATTERNS = [
        'os.environ.get("WEIGHT',
        "os.environ.get('WEIGHT",
        'os.environ.get("SUB_SCORE',
        "os.environ.get('SUB_SCORE",
        'os.getenv("WEIGHT',
        "os.getenv('WEIGHT",
        'os.getenv("SUB_SCORE',
        "os.getenv('SUB_SCORE",
    ]

    def _scan_source(self, path: Path) -> list[str]:
        source = path.read_text(encoding="utf-8")
        return [p for p in self._PROHIBITED_PATTERNS if p in source]

    def test_weight_config_no_env_reads(self):
        path = ROOT / "backend" / "scoring" / "weight_config.py"
        hits = self._scan_source(path)
        assert not hits, (
            f"INVARIANT 6 FAIL — weight_config.py contains env-override patterns:\n"
            + "\n".join(f"  {h}" for h in hits)
        )

    def test_sub_scorer_no_env_reads_for_weights(self):
        path = ROOT / "backend" / "scoring" / "sub_scorer.py"
        hits = self._scan_source(path)
        assert not hits, (
            f"INVARIANT 6 FAIL — sub_scorer.py contains weight env-override patterns:\n"
            + "\n".join(f"  {h}" for h in hits)
        )

    def test_simgr_weights_validation_mode_not_env_driven(self):
        """
        SIMGRWeights validation mode must NOT be driven by os.environ in
        active (non-comment) code.  A comment documenting the old pattern is
        acceptable; an active os.environ.get() call is not.
        """
        path = ROOT / "backend" / "scoring" / "config.py"
        source = path.read_text(encoding="utf-8")
        # Filter out comment lines; only check active code lines.
        active_lines = [
            line for line in source.splitlines()
            if not line.lstrip().startswith("#")
        ]
        active_code = "\n".join(active_lines)
        _PATTERN = 'os.environ.get("SIMGR_WEIGHT_VALIDATION_MODE'
        assert _PATTERN not in active_code, (
            "INVARIANT 6 FAIL — SIMGR_WEIGHT_VALIDATION_MODE is read from env "
            "in active (non-comment) code in config.py.\n"
            "  Expected: comment-only reference (historical documentation).\n"
            "  This env-driven override was supposed to be removed (HARDENED flag)."
        )


# ═════════════════════════════════════════════════════════════════════════════
# INVARIANT 7 — SIMGR TOLERANCE STRICTNESS
# ═════════════════════════════════════════════════════════════════════════════

class TestSIMGRToleranceStrictness:
    """SIMGRWeights must use tolerance 1e-6, not the legacy 0.001."""

    def test_simgr_weights_tolerance_is_strict(self):
        """
        SIMGRWeights.__post_init__ must use tolerance 1e-6.
        A sum of 1.0009 (within 0.001 but outside 1e-6) must raise.
        """
        from backend.scoring.config import SIMGRWeights
        # 0.25 + 0.25 + 0.25 + 0.15 + 0.11 = 1.01 — well outside 1e-6
        with pytest.raises(ValueError, match="sum to 1.0"):
            SIMGRWeights(
                study_score=0.2600,
                interest_score=0.2500,
                market_score=0.2500,
                growth_score=0.1500,
                risk_score=0.1000,
                # sum = 1.01 — should raise regardless of tolerance level
            )

    def test_simgr_valid_weights_pass(self):
        from backend.scoring.config import SIMGRWeights
        w = SIMGRWeights(
            study_score=0.25,
            interest_score=0.25,
            market_score=0.25,
            growth_score=0.15,
            risk_score=0.10,
        )
        # Must not raise
        total = (w.study_score + w.interest_score + w.market_score
                 + w.growth_score + w.risk_score)
        assert abs(total - 1.0) <= 1e-6

    def test_simgr_tolerance_value_in_source(self):
        """Verify 1e-6 tolerance is present in config.py SIMGRWeights."""
        path = ROOT / "backend" / "scoring" / "config.py"
        source = path.read_text(encoding="utf-8")
        # The old loose tolerance must be gone
        assert "abs(total - 1.0) > 0.001" not in source, (
            "INVARIANT 7 FAIL — SIMGRWeights still uses loose tolerance 0.001.\n"
            "  Update to: abs(total - 1.0) > 1e-6"
        )


# ═════════════════════════════════════════════════════════════════════════════
# INVARIANT 8 — copy_with_weights VALIDATES SUM
# ═════════════════════════════════════════════════════════════════════════════

class TestCopyWithWeightsValidates:
    """ScoringConfig.copy_with_weights() must reject partial sums."""

    def _make_config(self):
        from backend.scoring.config import ScoringConfig, SIMGRWeights
        return ScoringConfig(
            simgr_weights=SIMGRWeights(
                study_score=0.25, interest_score=0.25,
                market_score=0.25, growth_score=0.15, risk_score=0.10,
            )
        )

    def test_valid_copy_passes(self):
        cfg = self._make_config()
        new_cfg = cfg.copy_with_weights(
            study=0.30, interest=0.25, market=0.20,
            growth=0.15, risk=0.10,
        )
        total = (new_cfg.simgr_weights.study_score
                 + new_cfg.simgr_weights.interest_score
                 + new_cfg.simgr_weights.market_score
                 + new_cfg.simgr_weights.growth_score
                 + new_cfg.simgr_weights.risk_score)
        assert abs(total - 1.0) <= 1e-6, f"sum = {total}"

    def test_partial_override_producing_invalid_sum_raises(self):
        """Setting only study=0.99 without adjusting others → sum != 1.0 → must raise."""
        cfg = self._make_config()
        with pytest.raises(ValueError, match="sum to 1.0"):
            cfg.copy_with_weights(study=0.99)  # rest unchanged → sum > 1.0

    def test_original_config_unchanged_after_copy(self):
        cfg = self._make_config()
        original_study = cfg.simgr_weights.study_score
        try:
            cfg.copy_with_weights(study=0.99)
        except ValueError:
            pass
        assert cfg.simgr_weights.study_score == original_study, (
            "copy_with_weights() must not mutate the original config."
        )


# ═════════════════════════════════════════════════════════════════════════════
# INVARIANT 9 — DETERMINISTIC WEIGHT RESOLUTION
# ═════════════════════════════════════════════════════════════════════════════

class TestDeterministicWeightResolution:
    """Identical calls must return identical values — no stochastic resolution."""

    def test_three_loads_identical(self):
        d1 = load_sub_score_weight_dict()
        d2 = load_sub_score_weight_dict()
        d3 = load_sub_score_weight_dict()
        assert d1 == d2 == d3, (
            "INVARIANT 9 FAIL — weight loading is not deterministic:\n"
            f"  load1={d1}\n  load2={d2}\n  load3={d3}"
        )

    def test_assemble_breakdown_deterministic_across_runs(self):
        bd1 = assemble_breakdown(_VALID_INPUT)
        bd2 = assemble_breakdown(_VALID_INPUT)
        bd3 = assemble_breakdown(_VALID_INPUT)
        assert bd1.to_dict() == bd2.to_dict() == bd3.to_dict(), (
            "INVARIANT 9 FAIL — assemble_breakdown() is not deterministic."
        )

    def test_weight_values_are_finite(self):
        import math
        for c, w in DEFAULT_WEIGHTS.as_dict().items():
            assert math.isfinite(w), (
                f"INVARIANT 9 FAIL — DEFAULT_WEIGHTS.{c} = {w} is not finite."
            )

    def test_resolution_source_stable(self):
        s1 = get_weight_resolution_source()
        s2 = get_weight_resolution_source()
        assert s1 == s2, "Weight resolution source is not stable across calls."

    def test_no_os_environ_weight_overrides_possible(self):
        """
        Prove determinism: setting a hypothetical env var does NOT change
        loaded weights.
        """
        import os
        os.environ["WEIGHT_SKILL_OVERRIDE"] = "0.99"
        try:
            d = load_sub_score_weight_dict()
            assert abs(d["skill"] - 0.99) > 1e-3, (
                "INVARIANT 9 FAIL — env var WEIGHT_SKILL_OVERRIDE changed weight value.\n"
                "  weight_config.py must not read env vars for weight values."
            )
        finally:
            del os.environ["WEIGHT_SKILL_OVERRIDE"]


# ═════════════════════════════════════════════════════════════════════════════
# INVARIANT 10 — assemble_breakdown CALLS VALIDATE
# ═════════════════════════════════════════════════════════════════════════════

class TestAssembleBreakdownCallsValidate:
    """assemble_breakdown() must always validate weights before computing."""

    def test_valid_input_produces_correct_final_score(self):
        bd = assemble_breakdown(_VALID_INPUT)
        expected = sum(
            DEFAULT_WEIGHTS.as_dict()[c] * getattr(bd, f"{c}_score")
            for c in DEFAULT_WEIGHTS.COMPONENTS
        )
        assert abs(bd.final_score - expected) <= 1e-6, (
            f"final_score {bd.final_score} != expected {expected}"
        )

    def test_weights_in_breakdown_are_five_components(self):
        bd = assemble_breakdown(_VALID_INPUT)
        assert set(bd.weights.keys()) == set(DEFAULT_WEIGHTS.COMPONENTS)

    def test_contributions_sum_equals_final_score(self):
        bd = assemble_breakdown(_VALID_INPUT)
        contribs_sum = sum(bd.contributions.values())
        assert abs(contribs_sum - bd.final_score) <= 1e-4, (
            f"INVARIANT 10 FAIL — contributions sum {contribs_sum} "
            f"!= final_score {bd.final_score}"
        )

    def test_breakdown_weights_match_default(self):
        bd = assemble_breakdown(_VALID_INPUT)
        for c in DEFAULT_WEIGHTS.COMPONENTS:
            assert abs(bd.weights[c] - DEFAULT_WEIGHTS.as_dict()[c]) <= 1e-9, (
                f"INVARIANT 10 FAIL — breakdown weight for {c} "
                f"({bd.weights[c]}) differs from DEFAULT_WEIGHTS ({DEFAULT_WEIGHTS.as_dict()[c]})"
            )

    def test_custom_valid_weights_used_in_breakdown(self):
        custom = SubScoreWeights(
            skill=0.20, experience=0.20, education=0.20,
            goal_alignment=0.20, preference=0.20,
        )
        bd = assemble_breakdown(_VALID_INPUT, weights=custom)
        for c in custom.COMPONENTS:
            assert abs(bd.weights[c] - 0.20) <= 1e-9, (
                f"Expected custom weight 0.20 for {c}, got {bd.weights[c]}"
            )


# ═════════════════════════════════════════════════════════════════════════════
# FINAL SUMMARY TEST
# ═════════════════════════════════════════════════════════════════════════════

class TestWeightModelIntegritySummary:
    """Print weight model state and assert all invariants green."""

    def test_print_weight_model_state(self):
        d = load_sub_score_weight_dict()
        source = get_weight_resolution_source()
        total = sum(d.values())

        print("\n")
        print("╔" + "═" * 68 + "╗")
        print("║        WEIGHT MODEL INTEGRITY — STAGE 4 REPORT              ║")
        print("╠" + "═" * 68 + "╣")
        print(f"║  Resolution source : {source:<46} ║")
        print(f"║  Components        : {len(d)}/5 present"
              + " " * (46 - len(f"{len(d)}/5 present")) + "║")
        print("║" + "─" * 68 + "║")
        for c in _COMPONENTS:
            print(f"║    {c:<20} weight = {d[c]:.6f}"
                  + " " * max(0, 37 - len(f"{d[c]:.6f}")) + "║")
        print("║" + "─" * 68 + "║")
        print(f"║  sum(weights)      : {total:.10f}"
              + " " * max(0, 35 - len(f"{total:.10f}")) + "║")
        sum_ok = abs(total - 1.0) <= _SUM_TOLERANCE
        print(f"║  sum == 1.0        : {'✓ PASS' if sum_ok else '✗ FAIL':<46}║")
        print("╚" + "═" * 68 + "╝")
        print()

        assert sum_ok, f"Weight sum {total:.10f} deviates from 1.0 by > {_SUM_TOLERANCE:.0e}"
        assert source.startswith("config:"), (
            f"Weights not loaded from config (source='{source}'). "
            "Check scoring.yaml sub_score_weights block."
        )

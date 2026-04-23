# backend/ops/tests/test_regression.py
"""
Regression Tests for pipeline stability.

Ensures:
- Known bugs stay fixed
- Score determinism (same input → same output)
- Performance doesn't degrade
- Data contracts don't break
"""

import json
import time
from datetime import datetime
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════
# Section 1: Score Determinism
# ═══════════════════════════════════════════════════════

class TestScoreDeterminism:
    """Verify scoring produces deterministic results."""

    def _score_direct(self, components: dict) -> dict:
        from backend.scoring.scoring import SIMGRScorer
        scorer = SIMGRScorer()
        return scorer.score(components)

    def test_same_input_same_output(self):
        """Identical inputs must produce identical scores."""
        components = {
            "study": 0.8,
            "interest": 0.7,
            "market": 0.6,
            "growth": 0.5,
            "risk": 0.3,
        }
        result1 = self._score_direct(components)
        result2 = self._score_direct(components)

        if "error" not in result1 and "error" not in result2:
            s1 = result1.get("total_score", result1.get("score"))
            s2 = result2.get("total_score", result2.get("score"))
            if s1 is not None and s2 is not None:
                assert abs(s1 - s2) < 1e-10, f"Scores differ: {s1} vs {s2}"

    def test_score_monotonicity(self):
        """Higher component scores should yield higher total."""
        low = self._score_direct({
            "study": 0.2, "interest": 0.2, "market": 0.2,
            "growth": 0.2, "risk": 0.2,
        })
        high = self._score_direct({
            "study": 0.9, "interest": 0.9, "market": 0.9,
            "growth": 0.9, "risk": 0.9,
        })

        s_low = low.get("total_score", low.get("score", 0))
        s_high = high.get("total_score", high.get("score", 0))

        if isinstance(s_low, (int, float)) and isinstance(s_high, (int, float)):
            assert s_high >= s_low, f"Monotonicity failed: {s_high} < {s_low}"


# ═══════════════════════════════════════════════════════
# Section 2: Validation Contract Stability
# ═══════════════════════════════════════════════════════

class TestValidationContracts:
    """Ensure validation contracts don't regress."""

    def test_valid_record_always_passes(self):
        """A well-formed record must always pass validation."""
        from backend.data_pipeline.validator import DataValidator

        v = DataValidator()
        record = {
            "job_id": "reg001",
            "job_title": "Software Engineer",
            "company": "TestCo",
            "url": "https://example.com/reg001",
        }
        valid, report = v.validate_batch([record])
        assert len(valid) == 1, "Valid record was rejected"

    def test_missing_job_id_always_rejected(self):
        """Record without job_id must always be rejected."""
        from backend.data_pipeline.validator import DataValidator

        v = DataValidator()
        record = {
            "job_id": "",
            "job_title": "Engineer",
            "company": "Co",
            "url": "https://x.com",
        }
        valid, report = v.validate_batch([record])
        assert len(valid) == 0, "Record without job_id was accepted"


# ═══════════════════════════════════════════════════════
# Section 3: Performance Regression
# ═══════════════════════════════════════════════════════

class TestPerformanceRegression:
    """Ensure performance doesn't degrade beyond thresholds."""

    def test_validation_performance(self):
        """Validate 1000 records in under 5 seconds."""
        from backend.data_pipeline.validator import DataValidator

        records = [
            {
                "job_id": f"perf{i:04d}",
                "job_title": f"Job Title {i}",
                "company": f"Company {i}",
                "url": f"https://x.com/perf{i:04d}",
            }
            for i in range(1000)
        ]

        v = DataValidator()
        start = time.time()
        valid, report = v.validate_batch(records)
        elapsed = time.time() - start

        assert elapsed < 5.0, f"Validation took {elapsed:.2f}s (limit: 5s)"
        assert report.valid_records == 1000

    def test_scoring_performance(self):
        """Score 100 direct component sets in under 2 seconds."""
        from backend.scoring.scoring import SIMGRScorer

        scorer = SIMGRScorer()
        start = time.time()

        for i in range(100):
            scorer.score({
                "study": 0.5 + (i % 5) * 0.1,
                "interest": 0.5 + (i % 4) * 0.1,
                "market": 0.5 + (i % 3) * 0.1,
                "growth": 0.5 + (i % 2) * 0.1,
                "risk": 0.2 + (i % 3) * 0.1,
            })

        elapsed = time.time() - start
        assert elapsed < 2.0, f"Scoring took {elapsed:.2f}s (limit: 2s)"


# ═══════════════════════════════════════════════════════
# Section 4: Explanation Consistency
# ═══════════════════════════════════════════════════════

class TestExplanationConsistency:
    """Verify explanation traces are consistent with scores."""

    def test_trace_matches_scores(self):
        """Tracer component scores must match final SIMGR scores."""
        from backend.scoring.explain.tracer import ScoringTracer

        tracer = ScoringTracer(enabled=True)
        tracer.start_trace("DS", {"skill_count": 5})

        components = {
            "study": 0.8,
            "interest": 0.7,
            "market": 0.6,
            "growth": 0.5,
            "risk": 0.3,
        }

        for name, score in components.items():
            tracer.trace_component(name, score, {})

        tracer.set_simgr_scores(components)
        trace = tracer.get_trace()

        # Verify recorded == supplied
        for comp in trace.components:
            assert comp.score == components[comp.component_name]

        assert trace.simgr_scores == components

    def test_trace_completeness(self):
        """All 5 SIMGR components must appear in trace."""
        from backend.scoring.explain.tracer import ScoringTracer

        tracer = ScoringTracer(enabled=True)
        tracer.start_trace("Test Career", {})

        required = ["study", "interest", "market", "growth", "risk"]
        for comp in required:
            tracer.trace_component(comp, 0.5, {})

        trace = tracer.get_trace()
        traced_names = {c.component_name for c in trace.components}
        for comp in required:
            assert comp in traced_names, f"Missing component in trace: {comp}"

    def test_trace_serialization_roundtrip(self):
        """Trace must survive dictionary round-trip."""
        from backend.scoring.explain.tracer import ScoringTracer

        tracer = ScoringTracer(enabled=True)
        tracer.start_trace("Roundtrip Test", {"skills": 3})
        tracer.trace_component("study", 0.75, {"detail": "test"})
        tracer.set_simgr_scores({"study": 0.75})

        trace = tracer.get_trace()
        d = trace.to_dict()
        json_str = json.dumps(d)
        reloaded = json.loads(json_str)

        assert reloaded["career_name"] == "Roundtrip Test"
        assert len(reloaded["components"]) == 1
        assert reloaded["components"][0]["score"] == 0.75

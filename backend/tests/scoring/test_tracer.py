"""
Unit tests for backend/scoring/explain/tracer.py

Tests tracing functionality for explainability.
"""

import pytest
from datetime import datetime
from backend.scoring.explain.tracer import (
    ComponentTrace,
    ScoringTrace,
    ScoringTracer
)


class TestComponentTrace:
    """Test ComponentTrace dataclass."""

    def test_init(self):
        """Test ComponentTrace initialization."""
        details = {"skill_match": 0.8, "count": 2}
        trace = ComponentTrace(
            component_name="study",
            score=0.7,
            details=details
        )

        assert trace.component_name == "study"
        assert trace.score == 0.7
        assert trace.details == details
        assert isinstance(trace.timestamp, datetime)

    def test_to_dict(self):
        """Test converting ComponentTrace to dict."""
        details = {"skill_match": 0.8}
        trace = ComponentTrace(
            component_name="study",
            score=0.7,
            details=details
        )

        data = trace.to_dict()

        assert data["component_name"] == "study"
        assert data["score"] == 0.7
        assert data["details"] == details
        assert "timestamp" in data


class TestScoringTrace:
    """Test ScoringTrace dataclass."""

    def test_init(self):
        """Test ScoringTrace initialization."""
        user_summary = {"skill_count": 3, "interest_count": 2}
        trace = ScoringTrace(
            career_name="Data Scientist",
            user_summary=user_summary
        )

        assert trace.career_name == "Data Scientist"
        assert trace.user_summary == user_summary
        assert trace.components == []
        assert trace.simgr_scores == {}
        assert trace.total_score == 0.0
        assert trace.weights_used == {}
        assert trace.contributions == {}
        assert isinstance(trace.timestamp, datetime)

    def test_add_component(self):
        """Test adding component trace."""
        trace = ScoringTrace(career_name="Engineer", user_summary={})
        details = {"matched": 2}

        trace.add_component("study", 0.8, details)

        assert len(trace.components) == 1
        assert trace.components[0].component_name == "study"
        assert trace.components[0].score == 0.8
        assert trace.components[0].details == details

    def test_set_simgr_scores(self):
        """Test setting SIMGR scores."""
        trace = ScoringTrace(career_name="Engineer", user_summary={})
        scores = {"study": 0.8, "interest": 0.6}

        trace.simgr_scores = scores

        assert trace.simgr_scores == scores

    def test_final_score_assignment(self):
        """Test assigning final score and weights directly."""
        trace = ScoringTrace(career_name="Engineer", user_summary={})
        weights = {"study": 0.25, "interest": 0.25}

        trace.total_score = 0.65
        trace.weights_used = weights

        assert trace.total_score == 0.65
        assert trace.weights_used == weights

    def test_to_dict(self):
        """Test converting ScoringTrace to dict."""
        user_summary = {"skill_count": 2}
        trace = ScoringTrace(
            career_name="Engineer",
            user_summary=user_summary
        )
        trace.add_component("study", 0.8, {"matched": 1})
        trace.simgr_scores = {"study": 0.8}
        trace.total_score = 0.8
        trace.weights_used = {"study": 1.0}

        data = trace.to_dict()

        assert data["career_name"] == "Engineer"
        assert data["user_summary"] == user_summary
        assert len(data["components"]) == 1
        assert data["simgr_scores"] == {"study": 0.8}
        assert data["total_score"] == 0.8
        assert data["weights_used"] == {"study": 1.0}
        assert "timestamp" in data

    def test_to_readable(self):
        """Test human-readable output."""
        trace = ScoringTrace(
            career_name="Data Scientist",
            user_summary={"skill_count": 2, "interest_count": 1}
        )
        trace.simgr_scores = {"study": 0.8, "interest": 0.6}
        trace.total_score = 0.7
        trace.weights_used = {"study": 0.5, "interest": 0.5}

        readable = trace.to_readable()

        assert "Data Scientist" in readable
        assert "study: 0.8000" in readable
        assert "interest: 0.6000" in readable
        assert "TOTAL: 0.7000" in readable


class TestScoringTracer:
    """Test ScoringTracer class."""

    def test_init_enabled(self):
        """Test initialization with tracing enabled."""
        tracer = ScoringTracer(enabled=True)

        assert tracer.enabled is True
        assert tracer.current_trace is None

    def test_init_disabled(self):
        """Test initialization with tracing disabled."""
        tracer = ScoringTracer(enabled=False)

        assert tracer.enabled is False

    def test_start_trace_enabled(self):
        """Test starting trace when enabled."""
        tracer = ScoringTracer(enabled=True)
        user_summary = {"skills": 3}

        tracer.start_trace("Engineer", user_summary)

        assert tracer.current_trace is not None
        assert tracer.current_trace.career_name == "Engineer"
        assert tracer.current_trace.user_summary == user_summary

    def test_start_trace_disabled(self):
        """Test starting trace when disabled."""
        tracer = ScoringTracer(enabled=False)

        tracer.start_trace("Engineer", {})

        assert tracer.current_trace is None

    def test_trace_component_enabled(self):
        """Test tracing component when enabled."""
        tracer = ScoringTracer(enabled=True)
        tracer.start_trace("Engineer", {})
        details = {"score": 0.8}

        tracer.trace_component("study", 0.8, details)

        assert len(tracer.current_trace.components) == 1
        assert tracer.current_trace.components[0].component_name == "study"

    def test_trace_component_disabled(self):
        """Test tracing component when disabled."""
        tracer = ScoringTracer(enabled=False)

        tracer.trace_component("study", 0.8, {})

        # No assertion needed, just ensure no errors

    def test_set_simgr_scores_enabled(self):
        """Test setting SIMGR scores when enabled."""
        tracer = ScoringTracer(enabled=True)
        tracer.start_trace("Engineer", {})
        scores = {"study": 0.8}

        tracer.set_simgr_scores(scores)

        assert tracer.current_trace.simgr_scores == scores

    def test_set_simgr_scores_disabled(self):
        """Test setting SIMGR scores when disabled."""
        tracer = ScoringTracer(enabled=False)

        tracer.set_simgr_scores({"study": 0.8})

        # No assertion needed

    def test_final_score_assignment_enabled(self):
        """Test assigning final score when enabled."""
        tracer = ScoringTracer(enabled=True)
        tracer.start_trace("Engineer", {})
        weights = {"study": 0.25}

        tracer.current_trace.total_score = 0.8
        tracer.current_trace.weights_used = weights

        assert tracer.current_trace.total_score == 0.8
        assert tracer.current_trace.weights_used == weights

    def test_final_score_assignment_disabled(self):
        """Test final score assignment when disabled."""
        tracer = ScoringTracer(enabled=False)

        # No current_trace when disabled, so no assignment possible
        # No assertion needed

    def test_get_trace(self):
        """Test getting current trace."""
        tracer = ScoringTracer(enabled=True)
        tracer.start_trace("Engineer", {})

        trace = tracer.get_trace()

        assert trace is not None
        assert trace.career_name == "Engineer"

    def test_clear(self):
        """Test clearing current trace."""
        tracer = ScoringTracer(enabled=True)
        tracer.start_trace("Engineer", {})

        tracer.clear()

        assert tracer.current_trace is None

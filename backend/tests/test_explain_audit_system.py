import asyncio
from datetime import datetime, timezone, timedelta

from backend.explain.formatter import (
    RuleJustificationEngine,
    ConfidenceEstimator,
    EvidenceCollector,
    build_trace_edges,
)
from backend.explain.models import ExplanationRecord
from backend.explain.retention import ExplainRetentionManager
from backend.explain.storage import ExplanationStorage
from backend.feedback.models import TraceRecord
from backend.feedback.storage import FeedbackStorage


def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            new_loop = asyncio.new_event_loop()
            try:
                return new_loop.run_until_complete(coro)
            finally:
                new_loop.close()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def make_record(trace_id: str = "trace_test_001") -> ExplanationRecord:
    # Compute fired rules (and their normalized weights) from the engine.
    # Do NOT hardcode weights — they must always come from the engine so that
    # they reflect the current _RULE_BASE_IMPORTANCE table (or a ScoringBreakdown
    # when one is available).  sum(weights.values()) == 1.0 is enforced.
    _fired_rules = RuleJustificationEngine().evaluate(
        features={"math_score": 90, "physics_score": 85, "interest_it": 88, "logic_score": 92},
        predicted_career="Data Scientist",
        predicted_confidence=0.91,
    )
    return ExplanationRecord(
        trace_id=trace_id,
        model_id="model-v1",
        kb_version="kb-v1",
        rule_path=_fired_rules,
        weights={rule.rule_id: rule.weight for rule in _fired_rules},
        evidence=EvidenceCollector().collect(
            {"math_score": 90, "physics_score": 85, "interest_it": 88, "logic_score": 92},
            top_careers=[{"career": "Data Scientist", "probability": 0.91}],
        ),
        confidence=0.89,
        feature_snapshot={"math_score": 90, "physics_score": 85, "interest_it": 88, "logic_score": 92},
        prediction={"career": "Data Scientist", "confidence": 0.91},
    )


def test_rule_justification_is_deterministic():
    engine = RuleJustificationEngine()
    features = {"math_score": 82, "physics_score": 71, "interest_it": 73, "logic_score": 88}

    first = engine.evaluate(features, "AI Engineer", 0.86)
    second = engine.evaluate(features, "AI Engineer", 0.86)

    assert [rule.to_dict() for rule in first] == [rule.to_dict() for rule in second]


def test_confidence_normalized_range():
    estimator = ConfidenceEstimator()
    value = estimator.estimate(
        probabilities=[0.85, 0.10, 0.05],
        fired_rules=3,
        total_rules=4,
        features={"math_score": 90, "physics_score": 70, "interest_it": 80, "logic_score": 85},
        feedback_agreement=0.65,
    )
    assert 0.0 <= value <= 1.0


def test_storage_append_and_trace_fetch(tmp_path):
    storage = ExplanationStorage(db_path=tmp_path / "explanations.db")
    record = make_record("trace_append_001")

    run_async(storage.initialize())
    stored = run_async(storage.append_record(record))
    fetched = run_async(storage.get_by_trace_id("trace_append_001"))

    assert stored.explanation_id.startswith("exp-")
    assert fetched is not None
    assert fetched["trace_id"] == "trace_append_001"
    assert fetched["explanation_id"] == stored.explanation_id


def test_trace_graph_reconstructable(tmp_path):
    storage = ExplanationStorage(db_path=tmp_path / "graph.db")
    record = make_record("trace_graph_001")

    run_async(storage.initialize())
    run_async(storage.append_record(record))

    edges = build_trace_edges(
        trace_id="trace_graph_001",
        user_id="user_abc",
        features=record.feature_snapshot,
        fired_rules=record.rule_path,
        score=0.91,
        decision="Data Scientist",
    )
    run_async(storage.append_graph_edges("trace_graph_001", edges))

    graph = run_async(storage.get_trace_graph("trace_graph_001"))
    path = run_async(storage.backtrack("trace_graph_001", "feedback:trace_graph_001"))

    assert len(graph.nodes) >= 6
    assert len(graph.edges) >= 6
    assert path[0].startswith("user:")
    assert path[-1] == "feedback:trace_graph_001"


def test_history_respects_default_180_days(tmp_path):
    storage = ExplanationStorage(db_path=tmp_path / "history.db")

    run_async(storage.initialize())
    recent = run_async(storage.append_record(make_record("trace_recent")))
    old = run_async(storage.append_record(make_record("trace_old")))

    old_date = (datetime.now(timezone.utc) - timedelta(days=220)).isoformat()
    storage._conn.execute(
        "UPDATE explanations SET created_at = ? WHERE explanation_id = ?",
        (old_date, old.explanation_id),
    )
    storage._conn.commit()

    history = run_async(storage.get_history(from_date=None, to_date=None, limit=200))
    trace_ids = {item["trace_id"] for item in history}

    assert recent.trace_id in trace_ids
    assert old.trace_id not in trace_ids


def test_retention_cleanup_expiry(tmp_path):
    storage = ExplanationStorage(db_path=tmp_path / "retention.db")
    run_async(storage.initialize())

    expired = run_async(storage.append_record(make_record("trace_expired")))
    old_date = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    storage._conn.execute(
        "UPDATE explanations SET created_at = ? WHERE explanation_id = ?",
        (old_date, expired.explanation_id),
    )
    storage._conn.commit()

    manager = ExplainRetentionManager(storage=storage, retention_days=180)
    result = run_async(manager.run_cleanup())
    fetched = run_async(storage.get_by_trace_id("trace_expired"))

    assert result["deleted"] >= 1
    assert fetched is None


def test_tamper_detection(tmp_path):
    storage = ExplanationStorage(db_path=tmp_path / "tamper.db")
    run_async(storage.initialize())

    stored = run_async(storage.append_record(make_record("trace_tamper")))
    assert run_async(storage.verify_integrity("trace_tamper")) is True

    storage._conn.execute(
        "UPDATE explanations SET confidence = ? WHERE explanation_id = ?",
        (0.01, stored.explanation_id),
    )
    storage._conn.commit()

    assert run_async(storage.verify_integrity("trace_tamper")) is False


def test_trace_contract_no_orphan_trace(tmp_path):
    feedback_storage = FeedbackStorage(db_path=tmp_path / "feedback.db")
    run_async(feedback_storage.initialize())

    trace = TraceRecord(
        trace_id="trace_contract_001",
        user_id="user_123",
        input_profile={"math_score": 80},
        model_version="model-v1",
        kb_snapshot_version="kb-v1",
        rule_path=["rule_logic_math_strength"],
        score_vector={"rule_logic_math_strength": 0.34},
        timestamp=datetime.now(timezone.utc).isoformat(),
        predicted_career="Data Scientist",
        predicted_confidence=0.82,
    )

    run_async(feedback_storage.store_trace(trace))
    exists = run_async(feedback_storage.trace_exists("trace_contract_001"))

    assert exists is True

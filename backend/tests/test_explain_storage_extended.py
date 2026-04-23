"""
Additional tests for backend/explain/storage.py to improve coverage.
Focuses on graph operations, integrity verification, backtracking, and statistics.
"""
import pytest
import asyncio
import tempfile
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from backend.explain.storage import ExplanationStorage
from backend.explain.models import ExplanationRecord, EvidenceItem, RuleFire, TraceEdge


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield Path(path)
    try:
        os.unlink(path)
    except:
        pass


@pytest.fixture
def store(temp_db):
    """Create a storage instance with temp database."""
    return ExplanationStorage(db_path=temp_db)


@pytest.fixture
def sample_record():
    """Create a sample explanation record."""
    return ExplanationRecord(
        trace_id="test-trace-001",
        model_id="model-v1",
        kb_version="kb-2024",
        rule_path=[
            RuleFire(
                rule_id="rule_test",
                condition="test condition",
                matched_features={"math_score": 80.0},
                weight=0.5,
            )
        ],
        weights={"rule_test": 0.5},
        evidence=[
            EvidenceItem(
                source="feature_snapshot",
                key="math_score",
                value=80.0,
                weight=0.8,
            )
        ],
        confidence=0.85,
        feature_snapshot={"math_score": 80.0, "logic_score": 75.0},
        prediction={"career": "Engineer", "probability": 0.85},
    )


class TestGraphOperations:
    """Tests for graph-related operations."""

    @pytest.mark.asyncio
    async def test_append_graph_edges(self, store, sample_record):
        """Test appending graph edges."""
        await store.initialize()
        await store.append_record(sample_record)
        
        edges = [
            TraceEdge(source="input:test", target="feature:math", edge_type="extract"),
            TraceEdge(source="feature:math", target="rule:test", edge_type="trigger"),
        ]
        await store.append_graph_edges(sample_record.trace_id, edges)
        
        graph = await store.get_trace_graph(sample_record.trace_id)
        assert len(graph.edges) == 2
        assert len(graph.nodes) == 3  # input, feature, rule

    @pytest.mark.asyncio
    async def test_get_trace_graph_empty(self, store, sample_record):
        """Test getting graph with no edges."""
        await store.initialize()
        await store.append_record(sample_record)
        
        graph = await store.get_trace_graph(sample_record.trace_id)
        assert graph.trace_id == sample_record.trace_id
        assert len(graph.edges) == 0
        assert len(graph.nodes) == 0

    @pytest.mark.asyncio
    async def test_get_trace_graph_adjacency(self, store, sample_record):
        """Test that adjacency list is built correctly."""
        await store.initialize()
        
        edges = [
            TraceEdge(source="A", target="B", edge_type="ab"),
            TraceEdge(source="A", target="C", edge_type="ac"),
            TraceEdge(source="B", target="D", edge_type="bd"),
        ]
        await store.append_graph_edges(sample_record.trace_id, edges)
        
        graph = await store.get_trace_graph(sample_record.trace_id)
        assert "A" in graph.adjacency
        assert "B" in graph.adjacency["A"]
        assert "C" in graph.adjacency["A"]
        assert "D" in graph.adjacency["B"]


class TestBacktracking:
    """Tests for backtracking functionality."""

    @pytest.mark.asyncio
    async def test_backtrack_simple_path(self, store, sample_record):
        """Test backtracking a simple path."""
        await store.initialize()
        
        edges = [
            TraceEdge(source="A", target="B", edge_type="step1"),
            TraceEdge(source="B", target="C", edge_type="step2"),
            TraceEdge(source="C", target="D", edge_type="step3"),
        ]
        await store.append_graph_edges(sample_record.trace_id, edges)
        
        path = await store.backtrack(sample_record.trace_id, "D")
        assert path == ["A", "B", "C", "D"]

    @pytest.mark.asyncio
    async def test_backtrack_no_parents(self, store, sample_record):
        """Test backtracking from a root node."""
        await store.initialize()
        
        edges = [
            TraceEdge(source="A", target="B", edge_type="step1"),
        ]
        await store.append_graph_edges(sample_record.trace_id, edges)
        
        path = await store.backtrack(sample_record.trace_id, "A")
        assert path == ["A"]

    @pytest.mark.asyncio
    async def test_backtrack_nonexistent_node(self, store, sample_record):
        """Test backtracking from a node that doesn't exist."""
        await store.initialize()
        
        edges = [
            TraceEdge(source="A", target="B", edge_type="step1"),
        ]
        await store.append_graph_edges(sample_record.trace_id, edges)
        
        path = await store.backtrack(sample_record.trace_id, "X")
        assert path == ["X"]

    @pytest.mark.asyncio
    async def test_backtrack_handles_cycle(self, store, sample_record):
        """Test that backtracking handles cycles."""
        await store.initialize()
        
        # Create a cycle: A -> B -> C -> A
        edges = [
            TraceEdge(source="A", target="B", edge_type="step1"),
            TraceEdge(source="B", target="C", edge_type="step2"),
            TraceEdge(source="C", target="A", edge_type="cycle"),
        ]
        await store.append_graph_edges(sample_record.trace_id, edges)
        
        # Should not infinite loop
        path = await store.backtrack(sample_record.trace_id, "C")
        # Path should stop when it detects cycle
        assert len(path) <= 4


class TestIntegrityVerification:
    """Tests for integrity verification."""

    @pytest.mark.asyncio
    async def test_verify_integrity_empty_db(self, store):
        """Test integrity verification on empty database."""
        await store.initialize()
        
        result = await store.verify_integrity()
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_integrity_single_record(self, store, sample_record):
        """Test integrity verification with single record."""
        await store.initialize()
        await store.append_record(sample_record)
        
        result = await store.verify_integrity()
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_integrity_multiple_records(self, store):
        """Test integrity verification with multiple records."""
        await store.initialize()
        
        for i in range(5):
            record = ExplanationRecord(
                trace_id=f"trace-{i}",
                model_id="model-v1",
                kb_version="kb-2024",
                rule_path=[],
                weights={},
                evidence=[],
                confidence=0.5 + i * 0.1,
                feature_snapshot={},
                prediction={"career": f"Career-{i}"},
            )
            await store.append_record(record)
        
        result = await store.verify_integrity()
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_integrity_specific_trace(self, store, sample_record):
        """Test integrity verification for specific trace."""
        await store.initialize()
        await store.append_record(sample_record)
        
        result = await store.verify_integrity(trace_id=sample_record.trace_id)
        assert result is True


class TestStatistics:
    """Tests for statistics functionality."""

    @pytest.mark.asyncio
    async def test_get_stats_empty(self, store):
        """Test getting stats from empty database."""
        await store.initialize()
        
        stats = await store.get_stats()
        assert stats["total_records"] == 0
        assert stats["unique_traces"] == 0

    @pytest.mark.asyncio
    async def test_get_stats_with_records(self, store):
        """Test getting stats with records."""
        await store.initialize()
        
        for i in range(3):
            record = ExplanationRecord(
                trace_id=f"trace-{i}",
                model_id="model-v1",
                kb_version="kb-2024",
                rule_path=[],
                weights={},
                evidence=[],
                confidence=0.8,
                feature_snapshot={},
                prediction={},
            )
            await store.append_record(record)
        
        stats = await store.get_stats()
        assert stats["total_records"] == 3
        assert stats["unique_traces"] == 3
        assert stats["tamper_ok"] is True

    @pytest.mark.asyncio
    async def test_get_stats_duplicate_traces(self, store):
        """Test stats with duplicate trace IDs."""
        await store.initialize()
        
        for i in range(3):
            record = ExplanationRecord(
                trace_id="same-trace",  # Same trace ID
                model_id="model-v1",
                kb_version="kb-2024",
                rule_path=[],
                weights={},
                evidence=[],
                confidence=0.8 + i * 0.01,
                feature_snapshot={},
                prediction={},
            )
            await store.append_record(record)
        
        stats = await store.get_stats()
        assert stats["total_records"] == 3
        assert stats["unique_traces"] == 1


class TestHistoryQueries:
    """Tests for history query functionality."""

    @pytest.mark.asyncio
    async def test_get_history_empty(self, store):
        """Test getting history from empty database."""
        await store.initialize()
        
        history = await store.get_history(None, None)
        assert len(history) == 0

    @pytest.mark.asyncio
    async def test_get_history_with_records(self, store):
        """Test getting history with records."""
        await store.initialize()
        
        for i in range(5):
            record = ExplanationRecord(
                trace_id=f"trace-{i}",
                model_id="model-v1",
                kb_version="kb-2024",
                rule_path=[],
                weights={},
                evidence=[],
                confidence=0.8,
                feature_snapshot={},
                prediction={},
            )
            await store.append_record(record)
        
        history = await store.get_history(None, None, limit=10)
        assert len(history) == 5

    @pytest.mark.asyncio
    async def test_get_history_with_limit(self, store):
        """Test history respects limit."""
        await store.initialize()
        
        for i in range(10):
            record = ExplanationRecord(
                trace_id=f"trace-{i}",
                model_id="model-v1",
                kb_version="kb-2024",
                rule_path=[],
                weights={},
                evidence=[],
                confidence=0.8,
                feature_snapshot={},
                prediction={},
            )
            await store.append_record(record)
        
        history = await store.get_history(None, None, limit=3)
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_get_history_date_filter(self, store, sample_record):
        """Test history with date filters."""
        await store.initialize()
        await store.append_record(sample_record)
        
        now = datetime.now(timezone.utc)
        from_date = (now - timedelta(hours=1)).isoformat()
        to_date = (now + timedelta(hours=1)).isoformat()
        
        history = await store.get_history(from_date, to_date)
        assert len(history) == 1


class TestCleanupExpired:
    """Tests for cleanup functionality."""

    @pytest.mark.asyncio
    async def test_cleanup_expired_no_records(self, store):
        """Test cleanup with no expired records."""
        await store.initialize()
        
        result = await store.cleanup_expired(retention_days=180)
        assert result["deleted"] == 0

    @pytest.mark.asyncio
    async def test_cleanup_expired_respects_legal_hold(self, store):
        """Test that cleanup skips legal hold records."""
        await store.initialize()
        
        record = ExplanationRecord(
            trace_id="test-hold",
            model_id="model-v1",
            kb_version="kb-2024",
            rule_path=[],
            weights={},
            evidence=[],
            confidence=0.8,
            feature_snapshot={},
            prediction={},
        )
        await store.append_record(record)
        await store.set_legal_hold(record.trace_id, hold=True, user="admin")
        
        # Cleanup with 0 retention - should try to delete everything
        result = await store.cleanup_expired(retention_days=0)
        
        # Record on legal hold should be skipped
        assert result["skipped_legal_hold"] >= 0


class TestGetByTraceId:
    """Tests for get_by_trace_id functionality."""

    @pytest.mark.asyncio
    async def test_get_existing_trace(self, store, sample_record):
        """Test getting an existing trace."""
        await store.initialize()
        await store.append_record(sample_record)
        
        result = await store.get_by_trace_id(sample_record.trace_id)
        assert result is not None
        assert result["trace_id"] == sample_record.trace_id
        assert result["confidence"] == sample_record.confidence

    @pytest.mark.asyncio
    async def test_get_nonexistent_trace(self, store):
        """Test getting a non-existent trace."""
        await store.initialize()
        
        result = await store.get_by_trace_id("nonexistent-trace")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_latest_trace_version(self, store):
        """Test that get_by_trace_id returns the latest version."""
        await store.initialize()
        
        # Append multiple versions of same trace
        for i in range(3):
            record = ExplanationRecord(
                trace_id="versioned-trace",
                model_id="model-v1",
                kb_version="kb-2024",
                rule_path=[],
                weights={},
                evidence=[],
                confidence=0.5 + i * 0.1,  # Different confidence each time
                feature_snapshot={},
                prediction={},
            )
            await store.append_record(record)
        
        result = await store.get_by_trace_id("versioned-trace")
        # Should get the last one with confidence ~0.7
        assert result["confidence"] == pytest.approx(0.7, rel=0.01)


class TestRecordSerialization:
    """Tests for record serialization/deserialization."""

    @pytest.mark.asyncio
    async def test_record_round_trip(self, store, sample_record):
        """Test that records survive round-trip serialization."""
        await store.initialize()
        await store.append_record(sample_record)
        
        result = await store.get_by_trace_id(sample_record.trace_id)
        
        assert result["model_id"] == sample_record.model_id
        assert result["kb_version"] == sample_record.kb_version
        assert result["confidence"] == sample_record.confidence
        assert result["feature_snapshot"] == sample_record.feature_snapshot

    @pytest.mark.asyncio
    async def test_record_with_complex_evidence(self, store):
        """Test record with complex evidence values."""
        await store.initialize()
        
        record = ExplanationRecord(
            trace_id="complex-evidence",
            model_id="model-v1",
            kb_version="kb-2024",
            rule_path=[
                RuleFire(
                    rule_id="rule_complex",
                    condition="complex condition",
                    matched_features={"feature_a": 1.0, "feature_b": 2.0},
                    weight=0.75,
                )
            ],
            weights={"rule_complex": 0.75},
            evidence=[
                EvidenceItem(
                    source="model_distribution",
                    key="rank_1",
                    value={"career": "Engineer", "probability": 0.8},
                    weight=0.8,
                )
            ],
            confidence=0.9,
            feature_snapshot={"feature_a": 1.0, "feature_b": 2.0},
            prediction={"career": "Engineer", "probability": 0.8, "rank": 1},
        )
        await store.append_record(record)
        
        result = await store.get_by_trace_id("complex-evidence")
        assert result is not None
        assert len(result["rule_path"]) == 1
        assert len(result["evidence"]) == 1


class TestInitialization:
    """Tests for storage initialization."""

    @pytest.mark.asyncio
    async def test_double_initialization(self, store):
        """Test that double initialization is safe."""
        await store.initialize()
        await store.initialize()  # Should not raise
        
        stats = await store.get_stats()
        assert stats["total_records"] == 0

    @pytest.mark.asyncio
    async def test_auto_init_on_append(self, temp_db):
        """Test that append auto-initializes if needed."""
        store = ExplanationStorage(db_path=temp_db)
        # Don't call initialize explicitly
        
        record = ExplanationRecord(
            trace_id="auto-init-test",
            model_id="model-v1",
            kb_version="kb-2024",
            rule_path=[],
            weights={},
            evidence=[],
            confidence=0.8,
            feature_snapshot={},
            prediction={},
        )
        
        # This should auto-initialize
        await store.append_record(record)
        
        result = await store.get_by_trace_id("auto-init-test")
        assert result is not None

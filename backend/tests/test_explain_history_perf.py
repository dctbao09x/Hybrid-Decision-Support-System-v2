# backend/tests/test_explain_history_perf.py
"""
Performance tests for explain history queries.

Requirements:
    - Query 6 months of data
    - SLA: < 2 seconds

Tests:
    - Large dataset query performance
    - Index effectiveness
    - Pagination performance
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List

import pytest

from backend.explain.models import ExplanationRecord, RuleFire, EvidenceItem
from backend.explain.storage import ExplanationStorage


def run_async(coro):
    """Helper to run async code in tests."""
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


def make_record(trace_id: str, created_at: str = "") -> ExplanationRecord:
    """Create test explanation record with optional timestamp."""
    record = ExplanationRecord(
        trace_id=trace_id,
        model_id="model-perf-test",
        kb_version="kb-v1",
        rule_path=[
            RuleFire(
                rule_id="rule_perf",
                condition="score >= 70",
                matched_features={"score": 85},
                weight=0.5,
            ),
        ],
        weights={"rule_perf": 0.5},
        evidence=[
            EvidenceItem(
                source="feature",
                key="score",
                value=85,
                weight=0.85,
            ),
        ],
        confidence=0.85,
        feature_snapshot={"score": 85},
        prediction={"career": "Engineer", "confidence": 0.85},
    )
    if created_at:
        record.created_at = created_at
    return record


class TestHistoryPerformance:
    """Performance tests for history queries."""

    @pytest.fixture
    def large_dataset(self, tmp_path) -> ExplanationStorage:
        """Create storage with 6 months of data (~1000 records)."""
        storage = ExplanationStorage(db_path=tmp_path / "perf_test.db")
        run_async(storage.initialize())

        # Generate 1000 records spread over 6 months (approximately 180 days)
        base_date = datetime.now(timezone.utc)
        records_to_insert: List[tuple] = []

        for i in range(1000):
            days_ago = i % 180  # Spread across 6 months
            timestamp = (base_date - timedelta(days=days_ago)).isoformat()
            trace_id = f"trace_perf_{i:04d}"

            # Batch insert for speed
            records_to_insert.append((
                f"exp-{i:010d}",
                trace_id,
                "model-perf-test",
                "kb-v1",
                '{"rule_path": []}',
                '{}',
                '{"evidence": []}',
                0.85,
                '{"score": 85}',
                '{"career": "Engineer"}',
                timestamp,
                f"hash_{i}",
                f"prev_hash_{i-1}" if i > 0 else "",
                0,  # is_deleted
                0,  # legal_hold
            ))

        # Batch insert
        storage._conn.executemany(
            """
            INSERT INTO explanations
            (explanation_id, trace_id, model_id, kb_version, rule_path, weights,
             evidence, confidence, feature_snapshot, prediction, created_at,
             record_hash, prev_hash, is_deleted, legal_hold)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records_to_insert,
        )
        storage._conn.commit()

        return storage

    def test_query_6_months_under_2_seconds(self, large_dataset):
        """
        Query 6 months of history data should complete under 2 seconds.
        
        SLA: < 2 seconds for 6 months data query
        """
        storage = large_dataset
        
        # Define 6-month date range
        end_date = datetime.now(timezone.utc).isoformat()
        start_date = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()

        # Measure query time
        start_time = time.perf_counter()
        
        history = run_async(storage.get_history(
            from_date=start_date,
            to_date=end_date,
            limit=2000,  # Allow up to 2000 results
        ))
        
        elapsed = time.perf_counter() - start_time

        # Assertions
        assert elapsed < 2.0, f"Query took {elapsed:.2f}s, exceeds 2s SLA"
        assert len(history) > 0, "Should return some results"

        print(f"\n=== Performance Test Results ===")
        print(f"Records returned: {len(history)}")
        print(f"Query time: {elapsed:.4f} seconds")
        print(f"SLA Status: {'PASS' if elapsed < 2.0 else 'FAIL'}")

    def test_query_with_default_limit_under_500ms(self, large_dataset):
        """Query with default limit (500) should be fast."""
        storage = large_dataset

        start_time = time.perf_counter()
        
        history = run_async(storage.get_history(
            from_date=None,
            to_date=None,
            limit=500,
        ))
        
        elapsed = time.perf_counter() - start_time

        assert elapsed < 0.5, f"Default query took {elapsed:.2f}s, should be < 0.5s"
        assert len(history) <= 500

    def test_paginated_queries_consistent(self, large_dataset):
        """Multiple paginated queries should return consistent results."""
        storage = large_dataset

        # Query page 1 (first 100)
        page1 = run_async(storage.get_history(limit=100))
        
        # Query page 2 (next 100 - simulated by getting 200 and taking second half)
        page1_2 = run_async(storage.get_history(limit=200))

        # First 100 from both should match
        assert len(page1) == 100
        assert len(page1_2) == 200
        
        # First 100 items should be same
        for i in range(100):
            assert page1[i]["trace_id"] == page1_2[i]["trace_id"]

    def test_stats_query_performance(self, large_dataset):
        """Stats query should be fast."""
        storage = large_dataset

        start_time = time.perf_counter()
        stats = run_async(storage.get_stats())
        elapsed = time.perf_counter() - start_time

        assert elapsed < 0.5, f"Stats query took {elapsed:.2f}s, should be < 0.5s"
        assert stats["total_records"] == 1000

    def test_integrity_check_performance(self, large_dataset):
        """
        Integrity verification should complete in reasonable time.
        Note: This can be slower as it verifies hash chain.
        """
        storage = large_dataset

        start_time = time.perf_counter()
        # Note: Due to batch insert not maintaining proper hash chain,
        # this will fail integrity check, but we're testing performance
        try:
            is_valid = run_async(storage.verify_integrity())
        except Exception:
            is_valid = False
        elapsed = time.perf_counter() - start_time

        # Even full chain verification should be under 10 seconds
        assert elapsed < 10.0, f"Integrity check took {elapsed:.2f}s"
        
        print(f"\nIntegrity check: {elapsed:.4f}s")


class TestQueryOptimization:
    """Tests for query optimization effectiveness."""

    def test_date_filter_reduces_scan(self, tmp_path):
        """Date filtering should use index effectively."""
        storage = ExplanationStorage(db_path=tmp_path / "filter_test.db")
        run_async(storage.initialize())

        # Insert records with various dates
        for i in range(100):
            record = make_record(
                trace_id=f"trace_filter_{i}",
                created_at=(datetime.now(timezone.utc) - timedelta(days=i * 3)).isoformat(),
            )
            run_async(storage.append_record(record))

        # Query recent 30 days only
        recent_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        
        start_time = time.perf_counter()
        history = run_async(storage.get_history(
            from_date=recent_date,
            to_date=datetime.now(timezone.utc).isoformat(),
            limit=500,
        ))
        elapsed = time.perf_counter() - start_time

        # Should be very fast with date filter
        assert elapsed < 0.1, f"Filtered query took {elapsed:.2f}s"
        assert len(history) <= 11  # ~10 records in 30 days

    def test_trace_id_lookup_fast(self, tmp_path):
        """Single trace lookup should be very fast."""
        storage = ExplanationStorage(db_path=tmp_path / "lookup_test.db")
        run_async(storage.initialize())

        # Insert sample records
        for i in range(100):
            run_async(storage.append_record(make_record(f"trace_lookup_{i}")))

        # Lookup single trace
        start_time = time.perf_counter()
        record = run_async(storage.get_by_trace_id("trace_lookup_50"))
        elapsed = time.perf_counter() - start_time

        assert record is not None
        assert elapsed < 0.05, f"Trace lookup took {elapsed:.4f}s, should be < 50ms"


class TestConcurrentAccess:
    """Tests for concurrent access performance."""

    def test_concurrent_queries(self, tmp_path):
        """Multiple concurrent queries should complete efficiently."""
        storage = ExplanationStorage(db_path=tmp_path / "concurrent_test.db")
        run_async(storage.initialize())

        # Insert records
        for i in range(200):
            run_async(storage.append_record(make_record(f"trace_concurrent_{i}")))

        async def run_concurrent():
            tasks = [
                storage.get_history(limit=50),
                storage.get_history(limit=50),
                storage.get_stats(),
                storage.get_by_trace_id("trace_concurrent_100"),
            ]
            return await asyncio.gather(*tasks)

        start_time = time.perf_counter()
        results = run_async(run_concurrent())
        elapsed = time.perf_counter() - start_time

        assert len(results) == 4
        assert elapsed < 1.0, f"Concurrent queries took {elapsed:.2f}s"


class TestMemoryEfficiency:
    """Tests for memory efficient querying."""

    def test_streaming_large_result(self, tmp_path):
        """Large results should not cause memory issues."""
        storage = ExplanationStorage(db_path=tmp_path / "memory_test.db")
        run_async(storage.initialize())

        # Insert 500 records
        for i in range(500):
            run_async(storage.append_record(make_record(f"trace_memory_{i}")))

        # Query all
        start_time = time.perf_counter()
        history = run_async(storage.get_history(limit=500))
        elapsed = time.perf_counter() - start_time

        assert len(history) == 500
        assert elapsed < 2.0

        # Check each record has expected fields
        for record in history[:10]:
            assert "trace_id" in record
            assert "confidence" in record
            assert "created_at" in record

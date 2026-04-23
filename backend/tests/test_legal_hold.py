# backend/tests/test_legal_hold.py
"""
Comprehensive tests for Legal Hold functionality.

Tests:
    - Setting legal hold
    - Clearing legal hold
    - Legal hold prevents retention cleanup
    - Audit logging of legal hold actions
"""

import asyncio
from datetime import datetime, timezone, timedelta

import pytest

from backend.explain.models import ExplanationRecord, RuleFire, EvidenceItem
from backend.explain.storage import ExplanationStorage
from backend.explain.retention import ExplainRetentionManager


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


def make_record(trace_id: str = "trace_test_001") -> ExplanationRecord:
    """Create test explanation record."""
    return ExplanationRecord(
        trace_id=trace_id,
        model_id="model-v1",
        kb_version="kb-v1",
        rule_path=[
            RuleFire(
                rule_id="rule_test",
                condition="test >= 70",
                matched_features={"test": 80},
                weight=0.5,
            ),
        ],
        weights={"rule_test": 0.5},
        evidence=[
            EvidenceItem(
                source="test_source",
                key="test_key",
                value=100,
                weight=0.8,
            ),
        ],
        confidence=0.85,
        feature_snapshot={"test_feature": 80},
        prediction={"career": "Test Career", "confidence": 0.85},
    )


class TestLegalHoldBasic:
    """Basic legal hold functionality tests."""

    def test_set_legal_hold(self, tmp_path):
        """Test setting legal hold on a trace."""
        storage = ExplanationStorage(db_path=tmp_path / "legal_hold.db")
        record = make_record("trace_hold_001")

        run_async(storage.initialize())
        run_async(storage.append_record(record))

        result = run_async(storage.set_legal_hold("trace_hold_001", hold=True, user="admin"))

        assert result["trace_id"] == "trace_hold_001"
        assert result["legal_hold"] is True
        assert result["affected_rows"] >= 1

    def test_clear_legal_hold(self, tmp_path):
        """Test clearing legal hold on a trace."""
        storage = ExplanationStorage(db_path=tmp_path / "clear_hold.db")
        record = make_record("trace_clear_001")

        run_async(storage.initialize())
        run_async(storage.append_record(record))
        run_async(storage.set_legal_hold("trace_clear_001", hold=True))

        result = run_async(storage.set_legal_hold("trace_clear_001", hold=False, user="admin"))

        assert result["trace_id"] == "trace_clear_001"
        assert result["legal_hold"] is False

    def test_get_legal_hold_status(self, tmp_path):
        """Test getting legal hold status."""
        storage = ExplanationStorage(db_path=tmp_path / "status_hold.db")
        record = make_record("trace_status_001")

        run_async(storage.initialize())
        run_async(storage.append_record(record))
        run_async(storage.set_legal_hold("trace_status_001", hold=True))

        status = run_async(storage.get_legal_hold_status("trace_status_001"))

        assert status is not None
        assert status["trace_id"] == "trace_status_001"
        assert status["legal_hold"] is True

    def test_get_legal_hold_status_not_found(self, tmp_path):
        """Test getting status for non-existent trace."""
        storage = ExplanationStorage(db_path=tmp_path / "notfound.db")
        run_async(storage.initialize())

        status = run_async(storage.get_legal_hold_status("nonexistent_trace"))
        assert status is None

    def test_list_legal_holds(self, tmp_path):
        """Test listing all traces with legal holds."""
        storage = ExplanationStorage(db_path=tmp_path / "list_holds.db")

        run_async(storage.initialize())

        # Create multiple traces
        for i in range(5):
            run_async(storage.append_record(make_record(f"trace_list_{i}")))

        # Set legal hold on some
        run_async(storage.set_legal_hold("trace_list_0", hold=True))
        run_async(storage.set_legal_hold("trace_list_2", hold=True))
        run_async(storage.set_legal_hold("trace_list_4", hold=True))

        holds = run_async(storage.list_legal_holds())

        assert len(holds) == 3
        trace_ids = {h["trace_id"] for h in holds}
        assert "trace_list_0" in trace_ids
        assert "trace_list_2" in trace_ids
        assert "trace_list_4" in trace_ids


class TestLegalHoldRetention:
    """Tests that legal hold prevents retention cleanup."""

    def test_legal_hold_prevents_deletion(self, tmp_path):
        """Records with legal hold should not be deleted by retention cleanup."""
        storage = ExplanationStorage(db_path=tmp_path / "retention_hold.db")

        run_async(storage.initialize())

        # Create two old records
        record_protected = run_async(storage.append_record(make_record("trace_protected")))
        record_unprotected = run_async(storage.append_record(make_record("trace_unprotected")))

        # Set both records to old dates (beyond retention)
        old_date = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        storage._conn.execute(
            "UPDATE explanations SET created_at = ?",
            (old_date,),
        )
        storage._conn.commit()

        # Set legal hold on one
        run_async(storage.set_legal_hold("trace_protected", hold=True))

        # Run retention cleanup
        manager = ExplainRetentionManager(storage=storage, retention_days=180)
        result = run_async(manager.run_cleanup())

        # Check results
        assert result["deleted"] >= 1  # At least the unprotected one deleted
        assert result.get("skipped_legal_hold", 0) >= 1  # At least one skipped

        # Verify protected record still exists
        protected = run_async(storage.get_by_trace_id("trace_protected"))
        assert protected is not None

        # Verify unprotected record is deleted
        unprotected = run_async(storage.get_by_trace_id("trace_unprotected"))
        assert unprotected is None

    def test_released_hold_allows_deletion(self, tmp_path):
        """After releasing legal hold, record can be deleted."""
        storage = ExplanationStorage(db_path=tmp_path / "release_hold.db")

        run_async(storage.initialize())

        # Create old record with legal hold
        run_async(storage.append_record(make_record("trace_release")))
        old_date = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        storage._conn.execute(
            "UPDATE explanations SET created_at = ? WHERE trace_id = ?",
            (old_date, "trace_release"),
        )
        storage._conn.commit()

        # Set then clear legal hold
        run_async(storage.set_legal_hold("trace_release", hold=True))
        run_async(storage.set_legal_hold("trace_release", hold=False))

        # Run cleanup
        manager = ExplainRetentionManager(storage=storage, retention_days=180)
        result = run_async(manager.run_cleanup())

        assert result["deleted"] >= 1

        # Record should be deleted
        record = run_async(storage.get_by_trace_id("trace_release"))
        assert record is None


class TestLegalHoldAudit:
    """Tests for audit logging of legal hold operations."""

    def test_set_legal_hold_logged(self, tmp_path):
        """Setting legal hold should be logged to audit table."""
        storage = ExplanationStorage(db_path=tmp_path / "audit_set.db")
        record = make_record("trace_audit_set")

        run_async(storage.initialize())
        run_async(storage.append_record(record))
        run_async(storage.set_legal_hold("trace_audit_set", hold=True, user="admin_user"))

        # Check audit log
        cursor = storage._conn.execute(
            "SELECT * FROM explanation_audit WHERE action = 'set_legal_hold' AND trace_id = ?",
            ("trace_audit_set",),
        )
        audit_row = cursor.fetchone()

        assert audit_row is not None
        assert "admin_user" in audit_row["details"]

    def test_clear_legal_hold_logged(self, tmp_path):
        """Clearing legal hold should be logged to audit table."""
        storage = ExplanationStorage(db_path=tmp_path / "audit_clear.db")
        record = make_record("trace_audit_clear")

        run_async(storage.initialize())
        run_async(storage.append_record(record))
        run_async(storage.set_legal_hold("trace_audit_clear", hold=True))
        run_async(storage.set_legal_hold("trace_audit_clear", hold=False, user="compliance_team"))

        # Check audit log
        cursor = storage._conn.execute(
            "SELECT * FROM explanation_audit WHERE action = 'clear_legal_hold' AND trace_id = ?",
            ("trace_audit_clear",),
        )
        audit_row = cursor.fetchone()

        assert audit_row is not None
        assert "compliance_team" in audit_row["details"]


class TestLegalHoldRecordIncluded:
    """Tests that legal_hold status is included in record data."""

    def test_record_includes_legal_hold_status(self, tmp_path):
        """Retrieved records should include legal_hold field."""
        storage = ExplanationStorage(db_path=tmp_path / "include_hold.db")
        record = make_record("trace_include")

        run_async(storage.initialize())
        run_async(storage.append_record(record))
        run_async(storage.set_legal_hold("trace_include", hold=True))

        fetched = run_async(storage.get_by_trace_id("trace_include"))

        assert "legal_hold" in fetched
        assert fetched["legal_hold"] is True

    def test_record_legal_hold_default_false(self, tmp_path):
        """New records should have legal_hold = False by default."""
        storage = ExplanationStorage(db_path=tmp_path / "default_hold.db")
        record = make_record("trace_default")

        run_async(storage.initialize())
        run_async(storage.append_record(record))

        fetched = run_async(storage.get_by_trace_id("trace_default"))

        assert "legal_hold" in fetched
        assert fetched["legal_hold"] is False

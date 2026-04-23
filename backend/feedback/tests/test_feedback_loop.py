# backend/feedback/tests/test_feedback_loop.py
"""
Feedback Loop System Test Suite
===============================

Tests for:
  - Models and schemas
  - Storage operations
  - Validation layer
  - API endpoints
  - Linker service
  - Analytics
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.feedback.models import (
    TraceRecord,
    FeedbackEntry,
    FeedbackStatus,
    FeedbackSource,
    TrainingCandidate,
    TrainingStatus,
    FeedbackAuditLog,
)
from backend.feedback.schemas import (
    FeedbackSubmitRequest,
    FeedbackSubmitResponse,
    FeedbackReviewRequest,
    FeedbackStatsResponse,
)
from backend.feedback.storage import FeedbackStorage
from backend.feedback.validation import FeedbackValidator, ValidationError
from backend.feedback.linker import FeedbackLinker, QualityFilter
from backend.feedback.analytics import FeedbackAnalytics


def async_test(coro):
    """Decorator for async test methods."""
    def wrapper(*args, **kwargs):
        return asyncio.get_event_loop().run_until_complete(coro(*args, **kwargs))
    return wrapper


# ==============================================================================
# MODEL TESTS
# ==============================================================================

class TestTraceRecord(unittest.TestCase):
    """Test TraceRecord model."""
    
    def test_create_trace(self):
        trace = TraceRecord(
            trace_id="trace-123",
            user_id="user-456",
            input_profile={"skills": ["Python"], "interests": ["AI"]},
            kb_snapshot_version="kb-v1.0",
            model_version="model-v2.0",
            rule_path=["rule1", "rule2"],
            score_vector={"career1": 0.8, "career2": 0.2},
            timestamp=datetime.now(timezone.utc).isoformat(),
            predicted_career="career1",
            predicted_confidence=0.8,
        )
        
        self.assertEqual(trace.trace_id, "trace-123")
        self.assertEqual(trace.predicted_career, "career1")
        self.assertEqual(trace.predicted_confidence, 0.8)
    
    def test_generate_trace_id(self):
        trace_id = TraceRecord.generate_trace_id()
        self.assertTrue(trace_id.startswith("trace_"))
        parts = trace_id.split("_")
        self.assertEqual(len(parts), 3)  # trace, timestamp, suffix


class TestFeedbackEntry(unittest.TestCase):
    """Test FeedbackEntry model."""
    
    def test_create_feedback(self):
        fb = FeedbackEntry(
            id="fb-123",
            trace_id="trace-456",
            rating=4,
            correction={"correct_career": "Data Scientist"},
            reason="Better fit",
            source=FeedbackSource.WEB_UI,
            created_at=datetime.now(timezone.utc).isoformat(),
            status=FeedbackStatus.PENDING,
        )
        
        self.assertEqual(fb.rating, 4)
        self.assertEqual(fb.status, FeedbackStatus.PENDING)
        self.assertEqual(fb.correction["correct_career"], "Data Scientist")
    
    def test_status_enum(self):
        self.assertEqual(FeedbackStatus.PENDING.value, "pending")
        self.assertEqual(FeedbackStatus.APPROVED.value, "approved")
        self.assertEqual(FeedbackStatus.REJECTED.value, "rejected")
        self.assertEqual(FeedbackStatus.FLAGGED.value, "flagged")


class TestTrainingCandidate(unittest.TestCase):
    """Test TrainingCandidate model."""
    
    def test_create_candidate(self):
        candidate = TrainingCandidate(
            train_id="train-123",
            trace_id="trace-456",
            feedback_id="fb-789",
            input_features={"skills": ["Python"]},
            target_label="Data Scientist",
            original_prediction="Software Engineer",
            kb_version="kb-v1.0",
            model_version="model-v2.0",
            quality_score=0.85,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        
        self.assertEqual(candidate.target_label, "Data Scientist")
        self.assertEqual(candidate.quality_score, 0.85)
        self.assertFalse(candidate.used_in_training)


# ==============================================================================
# SCHEMA TESTS
# ==============================================================================

class TestFeedbackSchemas(unittest.TestCase):
    """Test Pydantic schemas."""
    
    def test_submit_request_valid(self):
        req = FeedbackSubmitRequest(
            trace_id="trace-123",
            rating=4,
            correction={"correct_career": "Engineer"},
            reason="Good match",
        )
        
        self.assertEqual(req.trace_id, "trace-123")
        self.assertEqual(req.rating, 4)
    
    def test_submit_request_invalid_rating(self):
        with self.assertRaises(ValueError):
            FeedbackSubmitRequest(
                trace_id="trace-123",
                rating=6,  # Invalid
                reason="Test",
            )
    
    def test_submit_request_empty_trace_id(self):
        with self.assertRaises(ValueError):
            FeedbackSubmitRequest(
                trace_id="",  # Empty - should fail
                rating=4,
                reason="Test",
            )


# ==============================================================================
# STORAGE TESTS
# ==============================================================================

class TestFeedbackStorage(unittest.TestCase):
    """Test FeedbackStorage operations."""
    
    def setUp(self):
        # Use temp database for tests
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_feedback.db"
        self.storage = FeedbackStorage(db_path=self.db_path)
    
    def tearDown(self):
        asyncio.get_event_loop().run_until_complete(self.storage.close())
        if self.db_path.exists():
            os.unlink(self.db_path)
        os.rmdir(self.temp_dir)
    
    @async_test
    async def test_store_and_get_trace(self):
        trace = TraceRecord(
            trace_id="test-trace-1",
            user_id="user-1",
            input_profile={"skills": ["Python"]},
            kb_snapshot_version="kb-v1",
            model_version="model-v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
            predicted_career="Engineer",
        )
        
        await self.storage.store_trace(trace)
        
        retrieved = await self.storage.get_trace("test-trace-1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.trace_id, "test-trace-1")
        self.assertEqual(retrieved.predicted_career, "Engineer")
    
    @async_test
    async def test_trace_exists(self):
        trace = TraceRecord(
            trace_id="exists-test",
            user_id="user-1",
            input_profile={},
            model_version="v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        
        await self.storage.store_trace(trace)
        
        exists = await self.storage.trace_exists("exists-test")
        self.assertTrue(exists)
        
        not_exists = await self.storage.trace_exists("nonexistent")
        self.assertFalse(not_exists)
    
    @async_test
    async def test_store_and_get_feedback(self):
        # First store a trace
        trace = TraceRecord(
            trace_id="trace-for-feedback",
            user_id="user-1",
            input_profile={},
            model_version="v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await self.storage.store_trace(trace)
        
        # Now store feedback
        feedback = FeedbackEntry(
            id="fb-test-1",
            trace_id="trace-for-feedback",
            rating=4,
            correction={"correct_career": "Scientist"},
            reason="Good fit",
            source=FeedbackSource.WEB_UI,
            created_at=datetime.now(timezone.utc).isoformat(),
            status=FeedbackStatus.PENDING,
        )
        
        await self.storage.store_feedback(feedback)
        
        retrieved = await self.storage.get_feedback("fb-test-1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.rating, 4)
        self.assertEqual(retrieved.status, FeedbackStatus.PENDING)
    
    @async_test
    async def test_update_feedback_status(self):
        # Setup trace and feedback
        trace = TraceRecord(
            trace_id="trace-status-test",
            user_id="user-1",
            input_profile={},
            model_version="v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await self.storage.store_trace(trace)
        
        feedback = FeedbackEntry(
            id="fb-status-test",
            trace_id="trace-status-test",
            rating=3,
            correction={},
            reason="Test",
            created_at=datetime.now(timezone.utc).isoformat(),
            status=FeedbackStatus.PENDING,
        )
        await self.storage.store_feedback(feedback)
        
        # Update status
        success = await self.storage.update_feedback_status(
            feedback_id="fb-status-test",
            status=FeedbackStatus.APPROVED,
            reviewer_id="reviewer-1",
            notes="Approved for training",
        )
        
        self.assertTrue(success)
        
        updated = await self.storage.get_feedback("fb-status-test")
        self.assertEqual(updated.status, FeedbackStatus.APPROVED)
        self.assertEqual(updated.reviewer_id, "reviewer-1")
    
    @async_test
    async def test_list_feedback_with_filters(self):
        # Setup traces and feedback
        for i in range(5):
            trace = TraceRecord(
                trace_id=f"trace-list-{i}",
                user_id="user-1",
                input_profile={},
                model_version="v1",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            await self.storage.store_trace(trace)
            
            fb = FeedbackEntry(
                id=f"fb-list-{i}",
                trace_id=f"trace-list-{i}",
                rating=i + 1,
                correction={},
                reason=f"Reason {i}",
                created_at=datetime.now(timezone.utc).isoformat(),
                status=FeedbackStatus.APPROVED if i % 2 == 0 else FeedbackStatus.PENDING,
            )
            await self.storage.store_feedback(fb)
        
        # List all
        items, total = await self.storage.list_feedback(limit=10)
        self.assertEqual(total, 5)
        
        # Filter by status
        approved, approved_total = await self.storage.list_feedback(
            status=FeedbackStatus.APPROVED,
            limit=10
        )
        self.assertEqual(approved_total, 3)
    
    @async_test
    async def test_feedback_stats(self):
        # Setup some data
        trace = TraceRecord(
            trace_id="trace-stats",
            user_id="user-1",
            input_profile={},
            model_version="v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await self.storage.store_trace(trace)
        
        fb1 = FeedbackEntry(
            id="fb-stats-1",
            trace_id="trace-stats",
            rating=4,
            correction={},
            reason="Test",
            created_at=datetime.now(timezone.utc).isoformat(),
            status=FeedbackStatus.APPROVED,
        )
        await self.storage.store_feedback(fb1)
        
        stats = await self.storage.get_feedback_stats()
        
        self.assertIn("total_feedback", stats)
        self.assertIn("approval_rate", stats)
        self.assertIn("avg_rating", stats)


# ==============================================================================
# VALIDATION TESTS
# ==============================================================================

class TestFeedbackValidator(unittest.TestCase):
    """Test FeedbackValidator."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_validation.db"
        self.storage = FeedbackStorage(db_path=self.db_path)
        self.validator = FeedbackValidator(self.storage)
    
    def tearDown(self):
        asyncio.get_event_loop().run_until_complete(self.storage.close())
        if self.db_path.exists():
            os.unlink(self.db_path)
        os.rmdir(self.temp_dir)
    
    @async_test
    async def test_validate_missing_trace_id(self):
        """trace_id is MANDATORY - no NULL allowed."""
        req = MagicMock()
        req.trace_id = ""
        req.rating = 4
        req.reason = "Test"
        req.correction = None
        
        is_valid, errors = await self.validator.validate(req)
        
        self.assertFalse(is_valid)
        self.assertTrue(any(e.code == "TRACE_ID_REQUIRED" for e in errors))
    
    @async_test
    async def test_validate_nonexistent_trace(self):
        """Feedback must link to existing trace."""
        req = MagicMock()
        req.trace_id = "nonexistent-trace-xyz"
        req.rating = 4
        req.reason = "Test reason"
        req.correction = None
        
        is_valid, errors = await self.validator.validate(req)
        
        self.assertFalse(is_valid)
        self.assertTrue(any(e.code == "TRACE_NOT_FOUND" for e in errors))
    
    @async_test
    async def test_validate_valid_feedback(self):
        """Valid feedback should pass."""
        # Create trace first
        trace = TraceRecord(
            trace_id="valid-trace-123",
            user_id="user-1",
            input_profile={},
            model_version="v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await self.storage.store_trace(trace)
        
        req = MagicMock()
        req.trace_id = "valid-trace-123"
        req.rating = 4
        req.reason = "Good recommendation"
        req.correction = {"correct_career": "Data Engineer"}
        
        is_valid, errors = await self.validator.validate(req)
        
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
    
    @async_test
    async def test_validate_rating_out_of_range(self):
        """Rating must be 1-5."""
        trace = TraceRecord(
            trace_id="rating-test-trace",
            user_id="user-1",
            input_profile={},
            model_version="v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await self.storage.store_trace(trace)
        
        req = MagicMock()
        req.trace_id = "rating-test-trace"
        req.rating = 10  # Invalid
        req.reason = "Test"
        req.correction = None
        
        is_valid, errors = await self.validator.validate(req)
        
        self.assertFalse(is_valid)
        self.assertTrue(any(e.code == "RATING_OUT_OF_RANGE" for e in errors))
    
    @async_test
    async def test_spam_detection(self):
        """Detect spam patterns."""
        trace = TraceRecord(
            trace_id="spam-test-trace",
            user_id="user-1",
            input_profile={},
            model_version="v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await self.storage.store_trace(trace)
        
        req = MagicMock()
        req.trace_id = "spam-test-trace"
        req.rating = 4
        req.reason = "aaaaaaaaaaaaaaaaaaaaa"  # Repeated chars
        req.correction = None
        
        is_valid, errors = await self.validator.validate(req)
        
        self.assertFalse(is_valid)
        self.assertTrue(any(e.code == "SPAM_DETECTED" for e in errors))


# ==============================================================================
# LINKER TESTS
# ==============================================================================

class TestFeedbackLinker(unittest.TestCase):
    """Test FeedbackLinker service."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_linker.db"
        self.storage = FeedbackStorage(db_path=self.db_path)
        self.linker = FeedbackLinker(self.storage)
    
    def tearDown(self):
        asyncio.get_event_loop().run_until_complete(self.storage.close())
        if self.db_path.exists():
            os.unlink(self.db_path)
        os.rmdir(self.temp_dir)
    
    @async_test
    async def test_generate_training_candidates(self):
        """Generate candidates from approved feedback."""
        # Setup trace
        trace = TraceRecord(
            trace_id="linker-test-trace",
            user_id="user-1",
            input_profile={"skills": ["Python", "ML"]},
            kb_snapshot_version="kb-v1",
            model_version="model-v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
            predicted_career="Data Analyst",
        )
        await self.storage.store_trace(trace)
        
        # Setup approved feedback
        fb = FeedbackEntry(
            id="linker-test-fb",
            trace_id="linker-test-trace",
            rating=4,
            correction={"correct_career": "Data Scientist"},
            reason="User has PhD - better fit for scientist role",
            created_at=datetime.now(timezone.utc).isoformat(),
            status=FeedbackStatus.APPROVED,
        )
        await self.storage.store_feedback(fb)
        
        # Generate candidates
        result = await self.linker.generate_training_candidates(
            min_quality=0.0,  # Low threshold for test
            max_samples=10,
        )
        
        self.assertEqual(result["created"], 1)
        self.assertIn("batch_id", result)
        
        # Verify candidate created
        candidates = await self.storage.get_training_candidates(
            min_quality=0.0,
            unused_only=True,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].target_label, "Data Scientist")
    
    @async_test
    async def test_link_trace(self):
        """Get full linkage for a trace."""
        trace = TraceRecord(
            trace_id="link-test-trace",
            user_id="user-1",
            input_profile={"skills": ["Java"]},
            model_version="v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
            predicted_career="Backend Dev",
        )
        await self.storage.store_trace(trace)
        
        result = await self.linker.link_trace("link-test-trace")
        
        self.assertIn("trace", result)
        self.assertEqual(result["trace"]["trace_id"], "link-test-trace")
        self.assertIn("feedback", result)
        self.assertIn("training_candidates", result)


# ==============================================================================
# ANALYTICS TESTS
# ==============================================================================

class TestFeedbackAnalytics(unittest.TestCase):
    """Test FeedbackAnalytics service."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_analytics.db"
        self.storage = FeedbackStorage(db_path=self.db_path)
        self.analytics = FeedbackAnalytics(self.storage)
    
    def tearDown(self):
        asyncio.get_event_loop().run_until_complete(self.storage.close())
        if self.db_path.exists():
            os.unlink(self.db_path)
        os.rmdir(self.temp_dir)
    
    @async_test
    async def test_dashboard_metrics_empty(self):
        """Dashboard works with no data."""
        metrics = await self.analytics.get_dashboard_metrics()
        
        self.assertIn("summary", metrics)
        self.assertEqual(metrics["summary"]["total_feedback"], 0)
    
    @async_test
    async def test_dashboard_metrics_with_data(self):
        """Dashboard calculates correct metrics."""
        # Setup data
        for i in range(10):
            trace = TraceRecord(
                trace_id=f"analytics-trace-{i}",
                user_id="user-1",
                input_profile={},
                model_version="v1",
                timestamp=datetime.now(timezone.utc).isoformat(),
                predicted_career="Engineer",
            )
            await self.storage.store_trace(trace)
            
            fb = FeedbackEntry(
                id=f"analytics-fb-{i}",
                trace_id=f"analytics-trace-{i}",
                rating=4 if i % 2 == 0 else 3,
                correction={"correct_career": "Scientist"} if i < 3 else {},
                reason="Test reason",
                created_at=datetime.now(timezone.utc).isoformat(),
                status=FeedbackStatus.APPROVED if i < 7 else FeedbackStatus.PENDING,
            )
            await self.storage.store_feedback(fb)
        
        metrics = await self.analytics.get_dashboard_metrics()
        
        self.assertEqual(metrics["summary"]["total_feedback"], 10)
        self.assertEqual(metrics["status_breakdown"]["approved"], 7)
        self.assertEqual(metrics["status_breakdown"]["pending"], 3)


# ==============================================================================
# INTEGRATION TESTS
# ==============================================================================

class TestFeedbackLoopIntegration(unittest.TestCase):
    """End-to-end integration tests."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_integration.db"
        self.storage = FeedbackStorage(db_path=self.db_path)
    
    def tearDown(self):
        asyncio.get_event_loop().run_until_complete(self.storage.close())
        if self.db_path.exists():
            os.unlink(self.db_path)
        os.rmdir(self.temp_dir)
    
    @async_test
    async def test_complete_feedback_workflow(self):
        """Test complete feedback → training workflow."""
        # 1. Store inference trace
        trace = TraceRecord(
            trace_id="workflow-trace",
            user_id="user-123",
            input_profile={"skills": ["Python", "SQL"], "experience": 5},
            kb_snapshot_version="kb-v1.5",
            model_version="model-v2.1",
            timestamp=datetime.now(timezone.utc).isoformat(),
            predicted_career="Data Analyst",
            predicted_confidence=0.75,
        )
        await self.storage.store_trace(trace)
        
        # 2. Validate trace exists
        validator = FeedbackValidator(self.storage)
        req = MagicMock()
        req.trace_id = "workflow-trace"
        req.rating = 3
        req.reason = "Prediction is okay but I think Data Engineer is better"
        req.correction = {"correct_career": "Data Engineer", "confidence": 0.9}
        
        is_valid, errors = await validator.validate(req)
        self.assertTrue(is_valid)
        
        # 3. Store feedback
        feedback = FeedbackEntry(
            id="workflow-fb",
            trace_id="workflow-trace",
            rating=3,
            correction={"correct_career": "Data Engineer", "confidence": 0.9},
            reason="Prediction is okay but I think Data Engineer is better",
            created_at=datetime.now(timezone.utc).isoformat(),
            status=FeedbackStatus.PENDING,
        )
        await self.storage.store_feedback(feedback)
        
        # 4. Review and approve
        await self.storage.update_feedback_status(
            feedback_id="workflow-fb",
            status=FeedbackStatus.APPROVED,
            reviewer_id="curator-1",
            notes="Valid correction - user has strong SQL skills",
        )
        
        # 5. Generate training candidate
        linker = FeedbackLinker(self.storage)
        result = await linker.generate_training_candidates(
            min_quality=0.0,
            max_samples=10,
        )
        
        self.assertEqual(result["created"], 1)
        
        # 6. Verify training candidate
        candidates = await self.storage.get_training_candidates()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].target_label, "Data Engineer")
        self.assertEqual(candidates[0].input_features, trace.input_profile)
        
        # 7. Check analytics
        analytics = FeedbackAnalytics(self.storage)
        metrics = await analytics.get_dashboard_metrics()
        
        self.assertEqual(metrics["summary"]["total_feedback"], 1)
        self.assertEqual(metrics["training"]["samples_generated"], 1)


# ==============================================================================
# RUN TESTS
# ==============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)

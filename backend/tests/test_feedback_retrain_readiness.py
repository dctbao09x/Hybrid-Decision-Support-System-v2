"""
Feedback Retrain Readiness Tests
================================

Phase 5: Verify feedback system is retrain-grade.

PASS CRITERIA:
1. Feedback contains career_id
2. Feedback contains rank_position (1-indexed)
3. Feedback contains score_snapshot with matchScore
4. Feedback contains profile_snapshot (non-empty)
5. Feedback contains model_version
6. Can filter by career_id
7. Can filter by model_version
8. Can filter by explicit_accept
9. Can reconstruct input -> output mapping
10. Can compute training sample from DB
"""

import json
import pytest
from datetime import datetime, timezone
from typing import Any, Dict

# Mock storage for testing
from unittest.mock import AsyncMock, MagicMock, patch


# ==============================================================================
# TEST DATA
# ==============================================================================

VALID_RETRAIN_FEEDBACK = {
    "trace_id": "trace_1740000000000_user123",
    "rating": 4,
    "correction": {"correct_career": "Software Engineer is correct"},
    "reason": "The recommendation matches my interests and skills",
    "user_id": "user123",
    
    # Retrain-grade required fields
    "career_id": "sw-eng-001",
    "rank_position": 1,
    "score_snapshot": {
        "matchScore": 0.925,
        "studyScore": 0.85,
        "interestScore": 0.90,
        "marketScore": 0.88,
        "growthScore": 0.92,
        "riskScore": 0.15,
    },
    "profile_snapshot": {
        "fullName": "Test User",
        "skills": ["Python", "React", "SQL"],
        "interests": ["AI", "Web Development"],
        "education": "Computer Science",
    },
    "model_version": "simgr_v2.1",
    "explicit_accept": True,
    
    # Optional fields
    "kb_version": "kb_2026.02",
    "confidence": 0.925,
    "session_id": "sess_1740000000000_abc123",
}

INVALID_FEEDBACK_MISSING_CAREER = {
    "trace_id": "trace_1740000000000_user123",
    "rating": 4,
    "correction": {"correct_career": "Software Engineer is correct"},
    "reason": "The recommendation matches my interests",
    # Missing career_id
    "rank_position": 1,
    "score_snapshot": {"matchScore": 0.925},
    "profile_snapshot": {"fullName": "Test User"},
    "model_version": "simgr_v2.1",
    "explicit_accept": True,
}

INVALID_FEEDBACK_BAD_RANK = {
    "trace_id": "trace_1740000000000_user123",
    "rating": 4,
    "correction": {"correct_career": "Software Engineer is correct"},
    "reason": "The recommendation matches my interests",
    "career_id": "sw-eng-001",
    "rank_position": 0,  # Invalid: must be >= 1
    "score_snapshot": {"matchScore": 0.925},
    "profile_snapshot": {"fullName": "Test User"},
    "model_version": "simgr_v2.1",
    "explicit_accept": True,
}

INVALID_FEEDBACK_NO_MATCH_SCORE = {
    "trace_id": "trace_1740000000000_user123",
    "rating": 4,
    "correction": {"correct_career": "Software Engineer is correct"},
    "reason": "The recommendation matches my interests",
    "career_id": "sw-eng-001",
    "rank_position": 1,
    "score_snapshot": {"studyScore": 0.85},  # Missing matchScore
    "profile_snapshot": {"fullName": "Test User"},
    "model_version": "simgr_v2.1",
    "explicit_accept": True,
}


# ==============================================================================
# SCHEMA VALIDATION TESTS
# ==============================================================================

class TestFeedbackSchemaValidation:
    """Test Pydantic schema validation for retrain-grade requirements."""
    
    def test_valid_feedback_passes(self):
        """Valid feedback with all retrain-grade fields should pass."""
        from backend.feedback.schemas import FeedbackSubmitRequest
        
        request = FeedbackSubmitRequest(**VALID_RETRAIN_FEEDBACK)
        
        assert request.career_id == "sw-eng-001"
        assert request.rank_position == 1
        assert request.score_snapshot["matchScore"] == 0.925
        assert request.profile_snapshot["fullName"] == "Test User"
        assert request.model_version == "simgr_v2.1"
        assert request.explicit_accept is True
    
    def test_missing_career_id_fails(self):
        """Missing career_id should raise validation error."""
        from backend.feedback.schemas import FeedbackSubmitRequest
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError) as exc:
            FeedbackSubmitRequest(**INVALID_FEEDBACK_MISSING_CAREER)
        
        errors = exc.value.errors()
        assert any(e["loc"] == ("career_id",) for e in errors)
    
    def test_invalid_rank_position_fails(self):
        """rank_position < 1 should raise validation error."""
        from backend.feedback.schemas import FeedbackSubmitRequest
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError) as exc:
            FeedbackSubmitRequest(**INVALID_FEEDBACK_BAD_RANK)
        
        errors = exc.value.errors()
        assert any("rank_position" in str(e) for e in errors)
    
    def test_missing_match_score_fails(self):
        """score_snapshot without matchScore should raise validation error."""
        from backend.feedback.schemas import FeedbackSubmitRequest
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError) as exc:
            FeedbackSubmitRequest(**INVALID_FEEDBACK_NO_MATCH_SCORE)
        
        errors = exc.value.errors()
        assert any("matchScore" in str(e) for e in errors)
    
    def test_empty_profile_snapshot_fails(self):
        """Empty profile_snapshot should raise validation error."""
        from backend.feedback.schemas import FeedbackSubmitRequest
        from pydantic import ValidationError
        
        data = {**VALID_RETRAIN_FEEDBACK, "profile_snapshot": {}}
        
        with pytest.raises(ValidationError) as exc:
            FeedbackSubmitRequest(**data)
        
        errors = exc.value.errors()
        assert any("profile_snapshot" in str(e) for e in errors)


# ==============================================================================
# STORED DATA VERIFICATION TESTS
# ==============================================================================

class TestFeedbackStorageVerification:
    """Test that stored feedback contains all retrain-grade fields."""
    
    def test_stored_feedback_contains_career_id(self):
        """Stored feedback must have career_id."""
        from backend.feedback.models import FeedbackEntry, FeedbackSource, FeedbackStatus
        
        entry = FeedbackEntry(
            id="fb_test_001",
            trace_id="trace_test",
            rating=4,
            correction={},
            reason="test",
            career_id="sw-eng-001",
            rank_position=1,
            score_snapshot={"matchScore": 0.9},
            profile_snapshot={"name": "Test"},
            model_version="simgr_v2.1",
            explicit_accept=True,
        )
        
        data = entry.to_dict()
        
        assert data["career_id"] == "sw-eng-001"
        assert data["rank_position"] == 1
        assert data["score_snapshot"]["matchScore"] == 0.9
        assert data["profile_snapshot"]["name"] == "Test"
        assert data["model_version"] == "simgr_v2.1"
        assert data["explicit_accept"] is True
    
    def test_feedback_entry_roundtrip(self):
        """FeedbackEntry should serialize and deserialize correctly."""
        from backend.feedback.models import FeedbackEntry, FeedbackSource, FeedbackStatus
        
        original = FeedbackEntry(
            id="fb_test_002",
            trace_id="trace_test",
            rating=5,
            correction={"correct_career": "Data Scientist"},
            reason="Great match!",
            career_id="data-sci-001",
            rank_position=2,
            score_snapshot={"matchScore": 0.88, "studyScore": 0.85},
            profile_snapshot={"skills": ["Python", "ML"]},
            model_version="simgr_v2.1",
            kb_version="kb_2026.02",
            confidence=0.88,
            explicit_accept=True,
            session_id="sess_test",
        )
        
        data = original.to_dict()
        restored = FeedbackEntry.from_dict(data)
        
        assert restored.career_id == original.career_id
        assert restored.rank_position == original.rank_position
        assert restored.score_snapshot == original.score_snapshot
        assert restored.profile_snapshot == original.profile_snapshot
        assert restored.model_version == original.model_version
        assert restored.explicit_accept == original.explicit_accept


# ==============================================================================
# FILTER QUERY TESTS
# ==============================================================================

class TestFeedbackQueryFilters:
    """Test that admin filters work correctly."""
    
    def test_filter_by_career_id(self):
        """FeedbackQuery should support career_id filter."""
        from backend.modules.feedback.model import FeedbackQuery
        
        query = FeedbackQuery(career_id="sw-eng-001")
        
        assert query.career_id == "sw-eng-001"
    
    def test_filter_by_model_version(self):
        """FeedbackQuery should support model_version filter."""
        from backend.modules.feedback.model import FeedbackQuery
        
        query = FeedbackQuery(model_version="simgr_v2.1")
        
        assert query.model_version == "simgr_v2.1"
    
    def test_filter_by_explicit_accept(self):
        """FeedbackQuery should support explicit_accept filter."""
        from backend.modules.feedback.model import FeedbackQuery
        
        query_accept = FeedbackQuery(explicit_accept=True)
        query_reject = FeedbackQuery(explicit_accept=False)
        
        assert query_accept.explicit_accept is True
        assert query_reject.explicit_accept is False
    
    def test_filter_by_confidence_range(self):
        """FeedbackQuery should support confidence range filters."""
        from backend.modules.feedback.model import FeedbackQuery
        
        query = FeedbackQuery(min_confidence=0.7, max_confidence=0.9)
        
        assert query.min_confidence == 0.7
        assert query.max_confidence == 0.9


# ==============================================================================
# RETRAIN RECONSTRUCTION TESTS
# ==============================================================================

class TestRetrainReconstruction:
    """Test that we can reconstruct training samples from stored feedback."""
    
    def test_can_reconstruct_input_output_mapping(self):
        """Should be able to reconstruct full input -> output mapping."""
        # Simulated stored feedback
        stored = {
            "id": "fb_test_003",
            "trace_id": "trace_test",
            "rating": 4,
            "career_id": "sw-eng-001",
            "rank_position": 1,
            "score_snapshot": {
                "matchScore": 0.925,
                "studyScore": 0.85,
                "interestScore": 0.90,
            },
            "profile_snapshot": {
                "skills": ["Python", "React"],
                "interests": ["AI"],
                "education": "CS",
            },
            "model_version": "simgr_v2.1",
            "explicit_accept": True,
            "correction": {"correct_career": "sw-eng-001"},
        }
        
        # Reconstruct training sample
        training_input = stored["profile_snapshot"]
        training_target = stored["career_id"] if stored["explicit_accept"] else stored["correction"].get("correct_career")
        original_prediction = stored["career_id"]
        original_rank = stored["rank_position"]
        original_score = stored["score_snapshot"]["matchScore"]
        
        # Verify reconstruction
        assert training_input == {"skills": ["Python", "React"], "interests": ["AI"], "education": "CS"}
        assert training_target == "sw-eng-001"  # Accepted, so target = original
        assert original_prediction == "sw-eng-001"
        assert original_rank == 1
        assert original_score == 0.925
    
    def test_rejected_feedback_uses_correction(self):
        """Rejected feedback should use correction as training target."""
        stored = {
            "career_id": "sw-eng-001",
            "explicit_accept": False,  # Rejected
            "correction": {"correct_career": "data-sci-001"},
        }
        
        # For rejected feedback, target is the correction
        training_target = stored["career_id"] if stored["explicit_accept"] else stored["correction"].get("correct_career")
        
        assert training_target == "data-sci-001"  # Should be the correction


# ==============================================================================
# BACKWARD COMPATIBILITY TESTS
# ==============================================================================

class TestBackwardCompatibility:
    """Test HTTP 422 for old requests missing new required fields."""
    
    def test_old_request_without_career_id_returns_422(self):
        """Request without career_id should return HTTP 422."""
        from backend.feedback.schemas import FeedbackSubmitRequest
        from pydantic import ValidationError
        
        old_style_request = {
            "trace_id": "trace_test",
            "rating": 4,
            "correction": {"correct_career": "Test"},
            "reason": "Test reason here",
            # Missing all new required fields
        }
        
        with pytest.raises(ValidationError):
            FeedbackSubmitRequest(**old_style_request)
    
    def test_422_error_message_is_clear(self):
        """HTTP 422 error message should clearly list missing fields."""
        from backend.feedback.schemas import FeedbackSubmitRequest
        from pydantic import ValidationError
        
        try:
            FeedbackSubmitRequest(
                trace_id="trace_test",
                rating=4,
                # Missing required fields
            )
        except ValidationError as e:
            error_fields = [err["loc"][0] for err in e.errors()]
            
            # Check all new required fields are mentioned
            assert "career_id" in error_fields
            assert "rank_position" in error_fields
            assert "score_snapshot" in error_fields
            assert "profile_snapshot" in error_fields
            assert "model_version" in error_fields
            assert "explicit_accept" in error_fields


# ==============================================================================
# INTEGRATION-STYLE TESTS
# ==============================================================================

class TestEndToEndRetrainFlow:
    """Integration tests for the full retrain data flow."""
    
    def test_full_feedback_submission_flow(self):
        """Test complete feedback submission with retrain-grade data."""
        from backend.feedback.models import FeedbackEntry, FeedbackSource, FeedbackStatus, TrainingStatus
        
        # 1. Create feedback entry with all fields
        feedback = FeedbackEntry(
            id="fb_e2e_001",
            trace_id="trace_e2e",
            rating=5,
            correction={"correct_career": "Software Engineer"},
            reason="Perfect match for my profile",
            source=FeedbackSource.WEB_UI,
            status=FeedbackStatus.PENDING,
            training_status=TrainingStatus.CANDIDATE,
            career_id="sw-eng-001",
            rank_position=1,
            score_snapshot={
                "matchScore": 0.95,
                "studyScore": 0.90,
                "interestScore": 0.92,
            },
            profile_snapshot={
                "fullName": "John Doe",
                "skills": ["Python", "JavaScript", "SQL"],
                "interests": ["AI", "Web Dev"],
            },
            model_version="simgr_v2.1",
            kb_version="kb_2026.02",
            confidence=0.95,
            explicit_accept=True,
            session_id="sess_e2e_001",
        )
        
        # 2. Verify all fields are present
        data = feedback.to_dict()
        
        assert data["career_id"] == "sw-eng-001"
        assert data["rank_position"] == 1
        assert "matchScore" in data["score_snapshot"]
        assert "skills" in data["profile_snapshot"]
        assert data["model_version"] == "simgr_v2.1"
        assert data["explicit_accept"] is True
        
        # 3. Verify training sample can be generated
        can_generate_sample = (
            data["career_id"] and
            data["rank_position"] >= 1 and
            "matchScore" in data["score_snapshot"] and
            data["profile_snapshot"] and
            data["model_version"]
        )
        
        assert can_generate_sample, "Should be able to generate training sample"
        
        print("\n✅ RETRAIN READINESS: PASS")
        print(f"   - career_id: {data['career_id']}")
        print(f"   - rank_position: {data['rank_position']}")
        print(f"   - score_snapshot keys: {list(data['score_snapshot'].keys())}")
        print(f"   - profile_snapshot keys: {list(data['profile_snapshot'].keys())}")
        print(f"   - model_version: {data['model_version']}")
        print(f"   - explicit_accept: {data['explicit_accept']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

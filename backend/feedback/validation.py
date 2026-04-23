# backend/feedback/validation.py
"""
Feedback Validation Layer
=========================

Validates feedback submissions before storage.
Implements constraint checking, schema validation, and spam detection.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from backend.feedback.models import FeedbackEntry
from backend.feedback.schemas import FeedbackSubmitRequest
from backend.feedback.storage import FeedbackStorage

logger = logging.getLogger("feedback.validation")


class ValidationError(Exception):
    """Validation failed."""
    
    def __init__(self, code: str, message: str, field: Optional[str] = None):
        self.code = code
        self.message = message
        self.field = field
        super().__init__(message)


class FeedbackValidator:
    """
    Validates feedback submissions.
    
    Checks:
      1. trace_id exists (MANDATORY - no NULL trace_id)
      2. Rating in valid range (1-5)
      3. Schema compliance
      4. Content quality
      5. Rate limiting (spam detection)
    """
    
    def __init__(self, storage: FeedbackStorage):
        self._storage = storage
        self._rate_limit_window = 60  # seconds
        self._rate_limit_max = 10  # max submissions per window
        self._recent_submissions: Dict[str, List[datetime]] = {}
    
    async def validate(
        self,
        request: FeedbackSubmitRequest,
        client_ip: Optional[str] = None,
    ) -> Tuple[bool, List[ValidationError]]:
        """
        Validate feedback submission.
        
        Returns:
            (is_valid, list of errors)
        """
        errors = []
        
        # 1. Trace ID validation (CRITICAL)
        trace_error = await self._validate_trace_id(request.trace_id)
        if trace_error:
            errors.append(trace_error)
        
        # 2. Rating validation
        rating_error = self._validate_rating(request.rating)
        if rating_error:
            errors.append(rating_error)
        
        # 3. Content validation
        content_errors = self._validate_content(request)
        errors.extend(content_errors)
        
        # 4. Rate limiting
        if client_ip:
            rate_error = self._check_rate_limit(client_ip)
            if rate_error:
                errors.append(rate_error)
        
        # 5. Spam detection
        spam_error = self._check_spam(request)
        if spam_error:
            errors.append(spam_error)
        
        return len(errors) == 0, errors
    
    async def _validate_trace_id(self, trace_id: str) -> Optional[ValidationError]:
        """Validate trace_id exists. NO NULL TRACE_ID ALLOWED."""
        if not trace_id:
            return ValidationError(
                code="TRACE_ID_REQUIRED",
                message="trace_id is required. Feedback must be linked to an inference trace.",
                field="trace_id",
            )
        
        if not trace_id.strip():
            return ValidationError(
                code="TRACE_ID_EMPTY",
                message="trace_id cannot be empty.",
                field="trace_id",
            )
        
        # Check format
        if not re.match(r"^[a-zA-Z0-9\-_]+$", trace_id):
            return ValidationError(
                code="TRACE_ID_INVALID_FORMAT",
                message="trace_id contains invalid characters.",
                field="trace_id",
            )
        
        # Verify trace exists
        await self._storage.initialize()
        exists = await self._storage.trace_exists(trace_id)
        
        if not exists:
            return ValidationError(
                code="TRACE_NOT_FOUND",
                message=f"Trace not found: {trace_id}. Cannot submit orphan feedback.",
                field="trace_id",
            )
        
        return None
    
    def _validate_rating(self, rating: int) -> Optional[ValidationError]:
        """Validate rating is in range 1-5."""
        if rating < 1 or rating > 5:
            return ValidationError(
                code="RATING_OUT_OF_RANGE",
                message="Rating must be between 1 and 5.",
                field="rating",
            )
        return None
    
    def _validate_content(self, request: FeedbackSubmitRequest) -> List[ValidationError]:
        """Validate content quality."""
        errors = []
        
        # Reason length check
        if request.reason:
            reason = request.reason.strip()
            if len(reason) < 3:
                errors.append(ValidationError(
                    code="REASON_TOO_SHORT",
                    message="Reason is too short. Please provide meaningful feedback.",
                    field="reason",
                ))
            if len(reason) > 5000:
                errors.append(ValidationError(
                    code="REASON_TOO_LONG",
                    message="Reason exceeds maximum length of 5000 characters.",
                    field="reason",
                ))
        
        # Correction validation
        if request.correction:
            correction = request.correction
            
            # Check career name format
            if "correct_career" in correction:
                career = correction["correct_career"]
                if career and (len(career) < 2 or len(career) > 200):
                    errors.append(ValidationError(
                        code="CAREER_NAME_INVALID",
                        message="Career name must be 2-200 characters.",
                        field="correction.correct_career",
                    ))
            
            # Check confidence
            if "confidence" in correction:
                conf = correction.get("confidence")
                if conf is not None and (not isinstance(conf, (int, float)) or conf < 0 or conf > 1):
                    errors.append(ValidationError(
                        code="CONFIDENCE_INVALID",
                        message="Confidence must be a number between 0 and 1.",
                        field="correction.confidence",
                    ))
        
        return errors
    
    def _check_rate_limit(self, client_ip: str) -> Optional[ValidationError]:
        """Check rate limiting."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=self._rate_limit_window)
        
        # Clean old entries
        if client_ip in self._recent_submissions:
            self._recent_submissions[client_ip] = [
                t for t in self._recent_submissions[client_ip] if t > cutoff
            ]
        else:
            self._recent_submissions[client_ip] = []
        
        # Check limit
        if len(self._recent_submissions[client_ip]) >= self._rate_limit_max:
            return ValidationError(
                code="RATE_LIMIT_EXCEEDED",
                message=f"Too many submissions. Please wait before submitting more feedback.",
                field=None,
            )
        
        # Record submission
        self._recent_submissions[client_ip].append(now)
        return None
    
    def _check_spam(self, request: FeedbackSubmitRequest) -> Optional[ValidationError]:
        """Check for spam patterns."""
        reason = (request.reason or "").lower()
        
        # Common spam patterns
        spam_patterns = [
            r"(.)\1{10,}",  # Repeated characters
            r"(test){3,}",  # Repeated "test"
            r"(asdf){2,}",  # Keyboard mashing
            r"http[s]?://",  # URLs (might be legitimate, flag for review)
        ]
        
        for pattern in spam_patterns[:3]:  # Skip URL pattern
            if re.search(pattern, reason):
                return ValidationError(
                    code="SPAM_DETECTED",
                    message="Feedback appears to be spam or invalid.",
                    field="reason",
                )
        
        return None
    
    async def validate_review(
        self,
        feedback_id: str,
        reviewer_id: str,
        action: str,
    ) -> Tuple[bool, List[ValidationError]]:
        """Validate review action."""
        errors = []
        
        # Check feedback exists
        await self._storage.initialize()
        feedback = await self._storage.get_feedback(feedback_id)
        
        if not feedback:
            errors.append(ValidationError(
                code="FEEDBACK_NOT_FOUND",
                message=f"Feedback not found: {feedback_id}",
                field="feedback_id",
            ))
            return False, errors
        
        # Check valid action
        valid_actions = {"approve", "reject", "flag"}
        if action not in valid_actions:
            errors.append(ValidationError(
                code="INVALID_ACTION",
                message=f"Invalid action: {action}. Must be one of: {valid_actions}",
                field="action",
            ))
        
        # Check reviewer_id
        if not reviewer_id or not reviewer_id.strip():
            errors.append(ValidationError(
                code="REVIEWER_REQUIRED",
                message="Reviewer ID is required for audit trail.",
                field="reviewer_id",
            ))
        
        return len(errors) == 0, errors


# ==============================================================================
# CONSISTENCY CHECKER
# ==============================================================================

class ConsistencyChecker:
    """
    Checks feedback consistency and flags outliers.
    
    Used to detect:
      - Inconsistent corrections for similar inputs
      - Systematic bias in reviewer
      - Training data quality issues
    """
    
    def __init__(self, storage: FeedbackStorage):
        self._storage = storage
    
    async def check_consistency(
        self,
        feedback: FeedbackEntry,
    ) -> Tuple[float, List[str]]:
        """
        Calculate consistency score for feedback.
        
        Returns:
            (score 0-1, list of warnings)
        """
        warnings = []
        score = 1.0
        
        # Get trace context
        trace = await self._storage.get_trace(feedback.trace_id)
        if not trace:
            return 0.5, ["Trace not found - cannot verify consistency"]
        
        # Check if correction contradicts high-confidence prediction
        correction = feedback.correction or {}
        correct_career = correction.get("correct_career")
        
        if correct_career and trace.predicted_career:
            if (correct_career != trace.predicted_career and 
                trace.predicted_confidence > 0.9):
                warnings.append(
                    f"Correction contradicts high-confidence prediction "
                    f"({trace.predicted_confidence:.0%})"
                )
                score -= 0.2
        
        # Check rating vs correction consistency
        if feedback.rating <= 2 and not correction:
            warnings.append("Low rating without correction suggestion")
            score -= 0.1
        
        if feedback.rating >= 4 and correct_career and correct_career != trace.predicted_career:
            warnings.append("High rating but correction differs from prediction")
            score -= 0.15
        
        return max(0.0, score), warnings
    
    async def calculate_reviewer_bias(self, reviewer_id: str) -> Dict[str, Any]:
        """Calculate bias statistics for a reviewer."""
        items, _ = await self._storage.list_feedback(limit=10000)
        
        reviewer_items = [fb for fb in items if fb.reviewer_id == reviewer_id]
        
        if not reviewer_items:
            return {"error": "No reviews found"}
        
        approved = sum(1 for fb in reviewer_items if fb.status.value == "approved")
        rejected = sum(1 for fb in reviewer_items if fb.status.value == "rejected")
        
        total = len(reviewer_items)
        
        return {
            "reviewer_id": reviewer_id,
            "total_reviews": total,
            "approval_rate": approved / total if total > 0 else 0,
            "rejection_rate": rejected / total if total > 0 else 0,
        }

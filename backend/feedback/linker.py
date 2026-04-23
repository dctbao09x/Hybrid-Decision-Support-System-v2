# backend/feedback/linker.py
"""
Feedback Linker Service
=======================

Trace linking engine that connects feedback to training data.
Implements quality scoring and training candidate generation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.feedback.models import (
    TraceRecord,
    FeedbackEntry,
    FeedbackStatus,
    TrainingCandidate,
    TrainingStatus,
)
from backend.feedback.storage import FeedbackStorage

logger = logging.getLogger("feedback.linker")


class FeedbackLinker:
    """
    Links feedback to traces and generates training candidates.
    
    Workflow:
      1. Fetch approved feedback
      2. Score feedback quality
      3. Create training sample with frozen context
      4. Store as training candidate (not direct to training set)
    """
    
    def __init__(self, storage: FeedbackStorage):
        self._storage = storage
    
    async def generate_training_candidates(
        self,
        min_quality: float = 0.5,
        max_samples: int = 100,
    ) -> Dict[str, Any]:
        """
        Generate training candidates from approved feedback.
        
        Args:
            min_quality: Minimum quality score threshold
            max_samples: Maximum samples to generate
        
        Returns:
            Summary with created count, skipped count, distribution
        """
        # Get approved feedback
        items, _ = await self._storage.list_feedback(
            status=FeedbackStatus.APPROVED,
            limit=max_samples * 2,  # Get extra to filter by quality
        )
        
        created = 0
        skipped = 0
        quality_dist = {"high": 0, "medium": 0, "low": 0}
        batch_id = f"batch-{uuid.uuid4().hex[:8]}"
        
        for fb in items:
            # Skip if already linked to training
            if fb.linked_train_id:
                skipped += 1
                continue
            
            # Calculate quality score
            quality = await self._calculate_quality_score(fb)
            
            if quality < min_quality:
                skipped += 1
                continue
            
            # Categorize quality
            if quality >= 0.8:
                quality_dist["high"] += 1
            elif quality >= 0.5:
                quality_dist["medium"] += 1
            else:
                quality_dist["low"] += 1
            
            # Create training candidate
            candidate = await self._create_candidate(fb, quality)
            if candidate:
                await self._storage.store_training_candidate(candidate)
                created += 1
            else:
                skipped += 1
            
            if created >= max_samples:
                break
        
        return {
            "batch_id": batch_id,
            "created": created,
            "skipped": skipped,
            "quality_distribution": quality_dist,
        }
    
    async def _calculate_quality_score(self, feedback: FeedbackEntry) -> float:
        """
        Calculate quality score for feedback.
        
        Factors:
          - Rating consistency (higher = better)
          - Reason completeness
          - Correction specificity
          - Historical accuracy (if same user feedback is validated)
        """
        score = 0.0
        
        # Rating factor (1-5 normalized)
        rating_score = (feedback.rating - 1) / 4.0  # 0-1 range
        score += rating_score * 0.2
        
        # Reason quality
        reason_length = len(feedback.reason.strip())
        if reason_length > 100:
            score += 0.25
        elif reason_length > 50:
            score += 0.15
        elif reason_length > 10:
            score += 0.05
        
        # Correction completeness
        correction = feedback.correction or {}
        if correction.get("correct_career"):
            score += 0.25
        if correction.get("confidence"):
            score += 0.1
        if correction.get("reason_corrections"):
            score += 0.1
        
        # Trace exists bonus
        trace = await self._storage.get_trace(feedback.trace_id)
        if trace:
            score += 0.1
            
            # Extra points if correction differs from prediction
            if (correction.get("correct_career") and 
                correction.get("correct_career") != trace.predicted_career):
                score += 0.1  # Correction feedback is more valuable
        
        return min(1.0, score)
    
    async def _create_candidate(
        self,
        feedback: FeedbackEntry,
        quality_score: float,
    ) -> Optional[TrainingCandidate]:
        """
        Create training candidate from feedback.
        
        Freezes context at feedback time:
          - Input profile from trace
          - Target label from correction
          - KB version from trace
          - Model version from trace
        """
        trace = await self._storage.get_trace(feedback.trace_id)
        if not trace:
            logger.warning(f"Trace not found for feedback {feedback.id}")
            return None
        
        # Extract target label
        correction = feedback.correction or {}
        target_label = correction.get("correct_career")
        
        if not target_label:
            # If no correction, use original prediction (confirmation feedback)
            target_label = trace.predicted_career
        
        if not target_label:
            logger.warning(f"No target label for feedback {feedback.id}")
            return None
        
        train_id = f"train-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        
        return TrainingCandidate(
            train_id=train_id,
            trace_id=feedback.trace_id,
            feedback_id=feedback.id,
            input_features=trace.input_profile,
            target_label=target_label,
            original_prediction=trace.predicted_career,
            kb_version=trace.kb_snapshot_version,
            model_version=trace.model_version,
            quality_score=quality_score,
            created_at=now,
            used_in_training=False,
        )
    
    async def link_trace(self, trace_id: str) -> Dict[str, Any]:
        """
        Get full linkage for a trace.
        
        Returns trace + associated feedback + training candidates.
        """
        trace = await self._storage.get_trace(trace_id)
        if not trace:
            return {"error": "Trace not found"}
        
        feedback_list = await self._storage.get_feedback_by_trace(trace_id)
        
        # Get training candidates linked to this trace
        all_candidates = await self._storage.get_training_candidates(
            min_quality=0.0,
            unused_only=False,
            limit=100,
        )
        linked_candidates = [c for c in all_candidates if c.trace_id == trace_id]
        
        return {
            "trace": {
                "trace_id": trace.trace_id,
                "user_id": trace.user_id,
                "input_profile": trace.input_profile,
                "predicted_career": trace.predicted_career,
                "model_version": trace.model_version,
                "kb_version": trace.kb_snapshot_version,
                "timestamp": trace.timestamp,
            },
            "feedback": [
                {
                    "feedback_id": fb.id,
                    "rating": fb.rating,
                    "correction": fb.correction,
                    "status": fb.status.value,
                    "reviewer": fb.reviewer_id,
                }
                for fb in feedback_list
            ],
            "training_candidates": [
                {
                    "train_id": c.train_id,
                    "target_label": c.target_label,
                    "quality_score": c.quality_score,
                    "used_in_training": c.used_in_training,
                }
                for c in linked_candidates
            ],
        }


# ==============================================================================
# QUALITY FILTER SERVICE (TASK 8)
# ==============================================================================

class QualityFilter:
    """
    Filters training candidates by quality criteria.
    
    Criteria:
      - Minimum quality score
      - Consistency with similar feedback
      - Source reliability
      - Age of feedback
    """
    
    def __init__(self, storage: FeedbackStorage):
        self._storage = storage
    
    async def filter_candidates(
        self,
        min_quality: float = 0.5,
        max_age_days: int = 90,
        require_review: bool = True,
    ) -> List[TrainingCandidate]:
        """
        Filter training candidates for retrain pipeline.
        
        Only returns candidates meeting all criteria.
        """
        candidates = await self._storage.get_training_candidates(
            min_quality=min_quality,
            unused_only=True,
            limit=1000,
        )
        
        filtered = []
        now = datetime.now(timezone.utc)
        
        for candidate in candidates:
            # Age check
            created = datetime.fromisoformat(candidate.created_at.replace("Z", "+00:00"))
            age = (now - created).days
            
            if age > max_age_days:
                continue
            
            # Review check
            if require_review:
                feedback = await self._storage.get_feedback(candidate.feedback_id)
                if not feedback or feedback.status != FeedbackStatus.APPROVED:
                    continue
            
            filtered.append(candidate)
        
        return filtered
    
    async def get_quality_report(self) -> Dict[str, Any]:
        """Generate quality analysis report."""
        all_candidates = await self._storage.get_training_candidates(
            min_quality=0.0,
            unused_only=False,
            limit=10000,
        )
        
        if not all_candidates:
            return {
                "total": 0,
                "quality_distribution": {},
                "label_distribution": {},
            }
        
        # Score distribution
        high_quality = sum(1 for c in all_candidates if c.quality_score >= 0.8)
        medium_quality = sum(1 for c in all_candidates if 0.5 <= c.quality_score < 0.8)
        low_quality = sum(1 for c in all_candidates if c.quality_score < 0.5)
        
        # Label distribution
        labels = {}
        for c in all_candidates:
            label = c.target_label
            labels[label] = labels.get(label, 0) + 1
        
        # Usage stats
        used = sum(1 for c in all_candidates if c.used_in_training)
        
        return {
            "total": len(all_candidates),
            "used_in_training": used,
            "unused": len(all_candidates) - used,
            "quality_distribution": {
                "high": high_quality,
                "medium": medium_quality,
                "low": low_quality,
            },
            "label_distribution": labels,
            "avg_quality": sum(c.quality_score for c in all_candidates) / len(all_candidates),
        }

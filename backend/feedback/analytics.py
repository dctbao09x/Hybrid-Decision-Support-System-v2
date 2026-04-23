# backend/feedback/analytics.py
"""
Feedback Analytics & KPI Service
================================

Calculates feedback metrics and KPIs for training loop monitoring.
Implements drift detection and retrain impact analysis.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from collections import defaultdict

from backend.feedback.models import FeedbackStatus
from backend.feedback.storage import FeedbackStorage

logger = logging.getLogger("feedback.analytics")


class FeedbackAnalytics:
    """
    Analytics service for feedback loop system.
    
    KPIs:
      - feedback_rate: % of inferences with feedback
      - approval_rate: % of feedback approved
      - correction_rate: % where correction != prediction
      - avg_rating: Average user rating
      - retrain_impact: Training samples used / generated
      - drift_signal: Distribution shift indicator
    """
    
    def __init__(self, storage: FeedbackStorage):
        self._storage = storage
    
    async def get_dashboard_metrics(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get full dashboard metrics."""
        await self._storage.initialize()
        
        stats = await self._storage.get_feedback_stats(from_date, to_date)
        
        # Calculate additional metrics
        correction_rate = await self._calculate_correction_rate(from_date, to_date)
        drift = await self._calculate_drift_signal(from_date, to_date)
        timeline = await self._get_timeline_data(from_date, to_date)
        
        return {
            "summary": {
                "total_feedback": stats["total_feedback"],
                "feedback_rate": round(stats["feedback_rate"] * 100, 2),
                "approval_rate": round(stats["approval_rate"] * 100, 2),
                "correction_rate": round(correction_rate * 100, 2),
                "avg_rating": round(stats["avg_rating"], 2),
            },
            "status_breakdown": {
                "pending": stats["pending_count"],
                "approved": stats["approved_count"],
                "rejected": stats["rejected_count"],
                "flagged": stats.get("flagged_count", 0),
            },
            "training": {
                "samples_generated": stats["training_samples_generated"],
                "samples_used": stats["training_samples_used"],
                "retrain_impact": round(
                    stats["training_samples_used"] / max(stats["training_samples_generated"], 1),
                    4
                ),
            },
            "drift": drift,
            "timeline": timeline,
            "career_distribution": stats.get("career_distribution", {}),
        }
    
    async def _calculate_correction_rate(
        self,
        from_date: Optional[str],
        to_date: Optional[str],
    ) -> float:
        """Calculate % of feedback with corrections differing from prediction."""
        items, _ = await self._storage.list_feedback(
            status=FeedbackStatus.APPROVED,
            from_date=from_date,
            to_date=to_date,
            limit=10000,
        )
        
        if not items:
            return 0.0
        
        correction_count = 0
        total_with_trace = 0
        
        for fb in items:
            trace = await self._storage.get_trace(fb.trace_id)
            if not trace:
                continue
            
            total_with_trace += 1
            correction = fb.correction or {}
            correct_career = correction.get("correct_career")
            
            if correct_career and correct_career != trace.predicted_career:
                correction_count += 1
        
        return correction_count / total_with_trace if total_with_trace > 0 else 0.0
    
    async def _calculate_drift_signal(
        self,
        from_date: Optional[str],
        to_date: Optional[str],
    ) -> Dict[str, Any]:
        """
        Calculate distribution drift indicator.
        
        Compares recent prediction distribution vs feedback correction distribution.
        High divergence suggests model drift.
        """
        items, _ = await self._storage.list_feedback(
            from_date=from_date,
            to_date=to_date,
            limit=5000,
        )
        
        if len(items) < 10:
            return {
                "signal": 0.0,
                "status": "insufficient_data",
                "sample_count": len(items),
            }
        
        # Get prediction distribution
        prediction_dist: Dict[str, int] = defaultdict(int)
        correction_dist: Dict[str, int] = defaultdict(int)
        
        for fb in items:
            trace = await self._storage.get_trace(fb.trace_id)
            if trace and trace.predicted_career:
                prediction_dist[trace.predicted_career] += 1
            
            correction = fb.correction or {}
            if correction.get("correct_career"):
                correction_dist[correction["correct_career"]] += 1
        
        # Calculate Jensen-Shannon divergence (simplified)
        all_careers = set(prediction_dist.keys()) | set(correction_dist.keys())
        
        if not all_careers:
            return {
                "signal": 0.0,
                "status": "no_data",
            }
        
        total_pred = sum(prediction_dist.values())
        total_corr = sum(correction_dist.values())
        
        if total_pred == 0 or total_corr == 0:
            return {
                "signal": 0.0,
                "status": "missing_distribution",
            }
        
        divergence = 0.0
        for career in all_careers:
            p = prediction_dist.get(career, 0) / total_pred
            q = correction_dist.get(career, 0) / total_corr
            
            if p > 0 and q > 0:
                divergence += abs(p - q)
        
        divergence /= 2  # Normalize to 0-1
        
        # Interpret signal
        if divergence < 0.1:
            status = "stable"
        elif divergence < 0.3:
            status = "minor_drift"
        else:
            status = "significant_drift"
        
        return {
            "signal": round(divergence, 4),
            "status": status,
            "sample_count": len(items),
            "prediction_distribution": dict(prediction_dist),
            "correction_distribution": dict(correction_dist),
        }
    
    async def _get_timeline_data(
        self,
        from_date: Optional[str],
        to_date: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Get daily feedback counts for timeline chart."""
        items, _ = await self._storage.list_feedback(
            from_date=from_date,
            to_date=to_date,
            limit=10000,
        )
        
        # Group by date
        daily_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: {
            "total": 0,
            "approved": 0,
            "rejected": 0,
            "pending": 0,
        })
        
        for fb in items:
            date = fb.created_at[:10]  # YYYY-MM-DD
            daily_counts[date]["total"] += 1
            daily_counts[date][fb.status.value] += 1
        
        # Sort by date
        return [
            {
                "date": date,
                **counts
            }
            for date, counts in sorted(daily_counts.items())
        ]
    
    async def get_reviewer_performance(self) -> List[Dict[str, Any]]:
        """Get reviewer performance metrics."""
        items, _ = await self._storage.list_feedback(limit=10000)
        
        # Group by reviewer
        reviewer_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {
            "reviews": 0,
            "approved": 0,
            "rejected": 0,
            "flagged": 0,
        })
        
        for fb in items:
            if fb.reviewer_id:
                reviewer_stats[fb.reviewer_id]["reviews"] += 1
                reviewer_stats[fb.reviewer_id][fb.status.value] += 1
        
        return [
            {
                "reviewer_id": reviewer_id,
                "total_reviews": stats["reviews"],
                "approval_rate": stats["approved"] / stats["reviews"] if stats["reviews"] > 0 else 0,
                "avg_review_time": 0,  # Would need reviewed_at - created_at
            }
            for reviewer_id, stats in reviewer_stats.items()
        ]
    
    async def get_quality_trends(self, window_days: int = 30) -> Dict[str, Any]:
        """Get quality score trends over time."""
        await self._storage.initialize()
        
        candidates = await self._storage.get_training_candidates(
            min_quality=0.0,
            unused_only=False,
            limit=10000,
        )
        
        if not candidates:
            return {"trend": "stable", "data": []}
        
        # Group by week
        weekly_quality: Dict[str, List[float]] = defaultdict(list)
        
        for c in candidates:
            week = c.created_at[:10]  # Simplify to date
            weekly_quality[week].append(c.quality_score)
        
        # Calculate weekly averages
        weekly_avg = [
            {
                "date": date,
                "avg_quality": sum(scores) / len(scores),
                "count": len(scores),
            }
            for date, scores in sorted(weekly_quality.items())
        ]
        
        # Determine trend
        if len(weekly_avg) < 2:
            trend = "stable"
        else:
            recent_avg = weekly_avg[-1]["avg_quality"]
            older_avg = weekly_avg[0]["avg_quality"]
            
            if recent_avg > older_avg + 0.1:
                trend = "improving"
            elif recent_avg < older_avg - 0.1:
                trend = "declining"
            else:
                trend = "stable"
        
        return {
            "trend": trend,
            "data": weekly_avg,
        }


# ==============================================================================
# RETRAIN IMPACT ANALYZER
# ==============================================================================

class RetrainImpactAnalyzer:
    """
    Analyzes the impact of feedback-derived training data on model performance.
    """
    
    def __init__(self, storage: FeedbackStorage):
        self._storage = storage
    
    async def estimate_impact(
        self,
        model_version: str,
    ) -> Dict[str, Any]:
        """
        Estimate impact of adding feedback samples to training.
        
        Returns estimate of expected improvement based on:
          - Volume of new samples
          - Quality distribution
          - Label coverage gaps
        """
        candidates = await self._storage.get_training_candidates(
            min_quality=0.5,
            unused_only=True,
            limit=10000,
        )
        
        if not candidates:
            return {
                "estimated_impact": 0.0,
                "reason": "No unused training candidates",
            }
        
        # Quality factor
        avg_quality = sum(c.quality_score for c in candidates) / len(candidates)
        quality_factor = avg_quality * 0.3
        
        # Volume factor (diminishing returns)
        volume = len(candidates)
        volume_factor = min(0.3, volume / 1000 * 0.3)
        
        # Diversity factor (unique labels)
        unique_labels = len(set(c.target_label for c in candidates))
        diversity_factor = min(0.2, unique_labels / 50 * 0.2)
        
        # Correction ratio (corrections more valuable than confirmations)
        corrections = sum(
            1 for c in candidates 
            if c.target_label != c.original_prediction
        )
        correction_factor = corrections / len(candidates) * 0.2
        
        total_impact = quality_factor + volume_factor + diversity_factor + correction_factor
        
        return {
            "estimated_impact": round(total_impact, 4),
            "factors": {
                "quality": round(quality_factor, 4),
                "volume": round(volume_factor, 4),
                "diversity": round(diversity_factor, 4),
                "corrections": round(correction_factor, 4),
            },
            "sample_count": len(candidates),
            "avg_quality": round(avg_quality, 4),
            "unique_labels": unique_labels,
            "correction_rate": round(corrections / len(candidates), 4),
        }

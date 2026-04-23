# backend/inference/feedback_collector.py
"""
Feedback Collector
==================

Captures prediction outcomes for model monitoring and retraining.

Features:
  - Append-only feedback log
  - Timestamped records
  - Links predictions to outcomes
  - Supports delayed feedback
  - Aggregates for drift detection
"""

from __future__ import annotations

import csv
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ml_inference.feedback")


@dataclass
class FeedbackRecord:
    """A single feedback record linking prediction to outcome."""
    prediction_id: str
    user_id: str
    timestamp: str
    
    # Input features
    features: Dict[str, float]
    
    # Prediction details
    predicted_career: str
    predicted_proba: float
    model_version: str
    
    # Outcome (may be None initially)
    actual_career: Optional[str] = None
    feedback_timestamp: Optional[str] = None
    is_correct: Optional[bool] = None
    
    # Metadata
    latency_ms: float = 0.0
    routing_target: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "prediction_id": self.prediction_id,
            "user_id": self.user_id,
            "timestamp": self.timestamp,
            "features": self.features,
            "predicted_career": self.predicted_career,
            "predicted_proba": self.predicted_proba,
            "model_version": self.model_version,
            "actual_career": self.actual_career,
            "feedback_timestamp": self.feedback_timestamp,
            "is_correct": self.is_correct,
            "latency_ms": self.latency_ms,
            "routing_target": self.routing_target,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FeedbackRecord":
        return cls(
            prediction_id=data["prediction_id"],
            user_id=data["user_id"],
            timestamp=data["timestamp"],
            features=data.get("features", {}),
            predicted_career=data["predicted_career"],
            predicted_proba=data.get("predicted_proba", 0.0),
            model_version=data["model_version"],
            actual_career=data.get("actual_career"),
            feedback_timestamp=data.get("feedback_timestamp"),
            is_correct=data.get("is_correct"),
            latency_ms=data.get("latency_ms", 0.0),
            routing_target=data.get("routing_target", ""),
        )


@dataclass
class FeedbackSummary:
    """Aggregated feedback statistics."""
    total_predictions: int = 0
    total_feedback: int = 0
    correct_predictions: int = 0
    
    by_model: Dict[str, Dict[str, int]] = field(default_factory=dict)
    by_career: Dict[str, Dict[str, int]] = field(default_factory=dict)
    
    def accuracy(self) -> float:
        if self.total_feedback == 0:
            return 0.0
        return self.correct_predictions / self.total_feedback
    
    def feedback_rate(self) -> float:
        if self.total_predictions == 0:
            return 0.0
        return self.total_feedback / self.total_predictions
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_predictions": self.total_predictions,
            "total_feedback": self.total_feedback,
            "correct_predictions": self.correct_predictions,
            "accuracy": self.accuracy(),
            "feedback_rate": self.feedback_rate(),
            "by_model": self.by_model,
            "by_career": self.by_career,
        }


class FeedbackCollector:
    """
    Append-only feedback collection with delayed outcome support.
    
    Usage::
    
        collector = FeedbackCollector()
        
        # Log prediction
        pred_id = collector.log_prediction(
            user_id="user123",
            features={"math": 85, "physics": 90},
            predicted_career="Software Engineer",
            model_version="v1",
        )
        
        # Later, log feedback
        collector.log_feedback(
            prediction_id=pred_id,
            actual_career="Software Engineer",
        )
    """
    
    def __init__(
        self,
        logs_dir: str = "feedback_logs",
        max_pending_hours: int = 168,  # 7 days
    ):
        self._project_root = Path(__file__).resolve().parents[2]
        self._logs_dir = self._project_root / logs_dir
        self._max_pending_hours = max_pending_hours
        
        self._lock = threading.RLock()
        
        # In-memory pending predictions (awaiting feedback)
        self._pending: Dict[str, FeedbackRecord] = {}
        
        # Ensure logs directory exists
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize log files
        self._init_logs()
    
    def _init_logs(self) -> None:
        """Initialize log files if they don't exist."""
        self._predictions_file = self._logs_dir / "predictions.jsonl"
        self._feedback_file = self._logs_dir / "feedback.jsonl"
        self._matched_file = self._logs_dir / "matched.jsonl"
    
    def log_prediction(
        self,
        user_id: str,
        features: Dict[str, float],
        predicted_career: str,
        predicted_proba: float,
        model_version: str,
        latency_ms: float = 0.0,
        routing_target: str = "",
    ) -> str:
        """
        Log a prediction (before outcome is known).
        
        Returns:
            prediction_id for later feedback matching
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        prediction_id = f"pred_{int(datetime.now().timestamp() * 1000)}_{user_id[:8]}"
        
        record = FeedbackRecord(
            prediction_id=prediction_id,
            user_id=user_id,
            timestamp=timestamp,
            features=features,
            predicted_career=predicted_career,
            predicted_proba=predicted_proba,
            model_version=model_version,
            latency_ms=latency_ms,
            routing_target=routing_target,
        )
        
        with self._lock:
            # Store in pending
            self._pending[prediction_id] = record
            
            # Append to predictions log
            self._append_log(self._predictions_file, record.to_dict())
        
        logger.debug("Logged prediction: %s -> %s", prediction_id, predicted_career)
        return prediction_id
    
    def log_feedback(
        self,
        prediction_id: str,
        actual_career: str,
    ) -> bool:
        """
        Log feedback (outcome) for a prediction.
        
        Returns:
            True if feedback was matched to a prediction
        """
        feedback_timestamp = datetime.now(timezone.utc).isoformat()
        
        with self._lock:
            # Try to find in pending
            record = self._pending.pop(prediction_id, None)
            
            if record:
                # Update record with feedback
                record.actual_career = actual_career
                record.feedback_timestamp = feedback_timestamp
                record.is_correct = (
                    record.predicted_career.lower() == actual_career.lower()
                )
                
                # Append to matched log
                self._append_log(self._matched_file, record.to_dict())
                
                logger.debug(
                    "Matched feedback: %s correct=%s",
                    prediction_id, record.is_correct,
                )
                return True
            else:
                # Log orphan feedback
                orphan = {
                    "prediction_id": prediction_id,
                    "actual_career": actual_career,
                    "feedback_timestamp": feedback_timestamp,
                    "status": "orphan",
                }
                self._append_log(self._feedback_file, orphan)
                
                logger.warning("Orphan feedback: %s", prediction_id)
                return False
    
    def get_summary(self, hours: int = 24) -> FeedbackSummary:
        """Get aggregated feedback summary for the last N hours."""
        summary = FeedbackSummary()
        
        with self._lock:
            # Count pending predictions
            summary.total_predictions = len(self._pending)
            
            # Read matched log
            if self._matched_file.exists():
                cutoff = datetime.now(timezone.utc).timestamp() - (hours * 3600)
                
                with open(self._matched_file, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            record = json.loads(line)
                            ts = datetime.fromisoformat(
                                record["timestamp"].replace("Z", "+00:00")
                            ).timestamp()
                            
                            if ts >= cutoff:
                                summary.total_predictions += 1
                                summary.total_feedback += 1
                                
                                if record.get("is_correct"):
                                    summary.correct_predictions += 1
                                
                                # By model
                                model = record.get("model_version", "unknown")
                                if model not in summary.by_model:
                                    summary.by_model[model] = {
                                        "total": 0, "correct": 0
                                    }
                                summary.by_model[model]["total"] += 1
                                if record.get("is_correct"):
                                    summary.by_model[model]["correct"] += 1
                                
                                # By career
                                career = record.get("predicted_career", "unknown")
                                if career not in summary.by_career:
                                    summary.by_career[career] = {
                                        "total": 0, "correct": 0
                                    }
                                summary.by_career[career]["total"] += 1
                                if record.get("is_correct"):
                                    summary.by_career[career]["correct"] += 1
                                    
                        except (json.JSONDecodeError, KeyError):
                            continue
        
        return summary
    
    def get_training_data(
        self,
        min_samples: int = 100,
        correct_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Extract training data from feedback logs.
        
        Returns list of (features, label) suitable for retraining.
        """
        data = []
        
        with self._lock:
            if self._matched_file.exists():
                with open(self._matched_file, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            record = json.loads(line)
                            
                            # Skip if we only want correct predictions
                            if correct_only and not record.get("is_correct"):
                                continue
                            
                            # Use actual career as label
                            if record.get("actual_career"):
                                data.append({
                                    "features": record.get("features", {}),
                                    "label": record["actual_career"],
                                    "source": "online_feedback",
                                    "timestamp": record.get("feedback_timestamp"),
                                })
                        except (json.JSONDecodeError, KeyError):
                            continue
        
        logger.info("Extracted %d training samples from feedback", len(data))
        return data
    
    def get_pending_count(self) -> int:
        """Get count of predictions awaiting feedback."""
        with self._lock:
            return len(self._pending)
    
    def cleanup_stale(self) -> int:
        """Remove stale pending predictions."""
        cutoff = datetime.now(timezone.utc).timestamp() - (
            self._max_pending_hours * 3600
        )
        removed = 0
        
        with self._lock:
            stale_ids = []
            for pred_id, record in self._pending.items():
                try:
                    ts = datetime.fromisoformat(
                        record.timestamp.replace("Z", "+00:00")
                    ).timestamp()
                    if ts < cutoff:
                        stale_ids.append(pred_id)
                except (ValueError, AttributeError):
                    stale_ids.append(pred_id)
            
            for pred_id in stale_ids:
                del self._pending[pred_id]
                removed += 1
        
        if removed:
            logger.info("Cleaned up %d stale pending predictions", removed)
        
        return removed
    
    def _append_log(self, path: Path, data: Dict[str, Any]) -> None:
        """Append a record to a JSONL log file."""
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, default=str) + "\n")

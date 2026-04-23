# backend/inference/metric_tracker.py
"""
Metric Tracker
==============

Tracks online inference metrics for monitoring and alerting.

Metrics tracked:
  - Latency (p50, p95, p99)
  - Error rate
  - Throughput (QPS)
  - Online accuracy (from feedback)
  - Model version distribution
"""

from __future__ import annotations

import json
import logging
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ml_inference.metrics")


@dataclass
class InferenceMetrics:
    """Aggregated inference metrics."""
    window_seconds: int = 300  # 5 minutes default
    
    # Latency (ms)
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0
    latency_mean: float = 0.0
    
    # Counts
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    
    # Rates
    error_rate: float = 0.0
    qps: float = 0.0
    
    # Model distribution
    model_counts: Dict[str, int] = field(default_factory=dict)
    
    # Feedback stats
    feedback_received: int = 0
    online_accuracy: float = 0.0
    
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_seconds": self.window_seconds,
            "latency": {
                "p50": round(self.latency_p50, 2),
                "p95": round(self.latency_p95, 2),
                "p99": round(self.latency_p99, 2),
                "mean": round(self.latency_mean, 2),
            },
            "requests": {
                "total": self.total_requests,
                "successful": self.successful_requests,
                "failed": self.failed_requests,
            },
            "error_rate": round(self.error_rate, 4),
            "qps": round(self.qps, 2),
            "model_counts": self.model_counts,
            "feedback": {
                "received": self.feedback_received,
                "online_accuracy": round(self.online_accuracy, 4),
            },
            "timestamp": self.timestamp,
        }


@dataclass
class RequestRecord:
    """Single request record for metrics computation."""
    timestamp: float  # Unix timestamp
    latency_ms: float
    success: bool
    model_version: str
    error_type: Optional[str] = None


class MetricTracker:
    """
    Real-time inference metrics tracker.
    
    Uses sliding window for computation.
    
    Usage::
    
        tracker = MetricTracker()
        
        # Record requests
        start = time.time()
        try:
            result = model.predict(X)
            tracker.record_success(
                latency_ms=(time.time() - start) * 1000,
                model_version="v1",
            )
        except Exception as e:
            tracker.record_error(
                latency_ms=(time.time() - start) * 1000,
                model_version="v1",
                error_type=type(e).__name__,
            )
        
        # Get metrics
        metrics = tracker.get_metrics()
    """
    
    def __init__(
        self,
        window_seconds: int = 300,
        max_records: int = 10000,
        logs_dir: str = "inference_logs",
    ):
        self._window_seconds = window_seconds
        self._max_records = max_records
        
        self._project_root = Path(__file__).resolve().parents[2]
        self._logs_dir = self._project_root / logs_dir
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        
        self._lock = threading.RLock()
        
        # Sliding window of records
        self._records: deque = deque(maxlen=max_records)
        
        # Feedback counters
        self._feedback_total = 0
        self._feedback_correct = 0
        
        # Alert thresholds
        self._alert_latency_p95 = 500.0  # ms
        self._alert_error_rate = 0.05  # 5%
        self._alert_callbacks: List = []
    
    def record_success(
        self,
        latency_ms: float,
        model_version: str,
    ) -> None:
        """Record a successful inference request."""
        record = RequestRecord(
            timestamp=time.time(),
            latency_ms=latency_ms,
            success=True,
            model_version=model_version,
        )
        
        with self._lock:
            self._records.append(record)
        
        self._check_alerts()
    
    def record_error(
        self,
        latency_ms: float,
        model_version: str,
        error_type: str,
    ) -> None:
        """Record a failed inference request."""
        record = RequestRecord(
            timestamp=time.time(),
            latency_ms=latency_ms,
            success=False,
            model_version=model_version,
            error_type=error_type,
        )
        
        with self._lock:
            self._records.append(record)
        
        self._check_alerts()
    
    def record_feedback(self, is_correct: bool) -> None:
        """Record feedback for online accuracy tracking."""
        with self._lock:
            self._feedback_total += 1
            if is_correct:
                self._feedback_correct += 1
    
    def get_metrics(self, window_seconds: Optional[int] = None) -> InferenceMetrics:
        """Compute metrics for the specified window."""
        window = window_seconds or self._window_seconds
        cutoff = time.time() - window
        
        with self._lock:
            # Filter records in window
            in_window = [r for r in self._records if r.timestamp >= cutoff]
            
            if not in_window:
                return InferenceMetrics(window_seconds=window)
            
            # Compute latencies
            latencies = [r.latency_ms for r in in_window]
            sorted_latencies = sorted(latencies)
            
            n = len(sorted_latencies)
            p50_idx = int(n * 0.50)
            p95_idx = int(n * 0.95)
            p99_idx = int(n * 0.99)
            
            # Counts
            total = len(in_window)
            successful = sum(1 for r in in_window if r.success)
            failed = total - successful
            
            # Model distribution
            model_counts: Dict[str, int] = {}
            for r in in_window:
                model_counts[r.model_version] = model_counts.get(
                    r.model_version, 0
                ) + 1
            
            # Online accuracy
            online_accuracy = 0.0
            if self._feedback_total > 0:
                online_accuracy = self._feedback_correct / self._feedback_total
            
            return InferenceMetrics(
                window_seconds=window,
                latency_p50=sorted_latencies[p50_idx] if n > 0 else 0,
                latency_p95=sorted_latencies[min(p95_idx, n - 1)] if n > 0 else 0,
                latency_p99=sorted_latencies[min(p99_idx, n - 1)] if n > 0 else 0,
                latency_mean=statistics.mean(latencies) if latencies else 0,
                total_requests=total,
                successful_requests=successful,
                failed_requests=failed,
                error_rate=failed / total if total > 0 else 0,
                qps=total / window if window > 0 else 0,
                model_counts=model_counts,
                feedback_received=self._feedback_total,
                online_accuracy=online_accuracy,
            )
    
    def set_alert_thresholds(
        self,
        latency_p95: Optional[float] = None,
        error_rate: Optional[float] = None,
    ) -> None:
        """Set alert thresholds."""
        with self._lock:
            if latency_p95 is not None:
                self._alert_latency_p95 = latency_p95
            if error_rate is not None:
                self._alert_error_rate = error_rate
    
    def add_alert_callback(self, callback) -> None:
        """Add callback for alerts."""
        self._alert_callbacks.append(callback)
    
    def _check_alerts(self) -> None:
        """Check if metrics exceed thresholds."""
        metrics = self.get_metrics(window_seconds=60)  # 1 minute window
        
        alerts = []
        
        if metrics.latency_p95 > self._alert_latency_p95:
            alerts.append({
                "type": "high_latency",
                "message": f"P95 latency {metrics.latency_p95:.0f}ms > {self._alert_latency_p95:.0f}ms",
                "value": metrics.latency_p95,
                "threshold": self._alert_latency_p95,
            })
        
        if metrics.error_rate > self._alert_error_rate:
            alerts.append({
                "type": "high_error_rate",
                "message": f"Error rate {metrics.error_rate:.2%} > {self._alert_error_rate:.2%}",
                "value": metrics.error_rate,
                "threshold": self._alert_error_rate,
            })
        
        for alert in alerts:
            logger.warning("[ALERT] %s", alert["message"])
            for callback in self._alert_callbacks:
                try:
                    callback(alert)
                except Exception as e:
                    logger.error("Alert callback failed: %s", e)
    
    def export_metrics(self) -> str:
        """Export current metrics to log file."""
        metrics = self.get_metrics()
        
        log_file = self._logs_dir / f"metrics_{datetime.now().strftime('%Y%m%d')}.jsonl"
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(metrics.to_dict()) + "\n")
        
        return str(log_file)
    
    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._records.clear()
            self._feedback_total = 0
            self._feedback_correct = 0

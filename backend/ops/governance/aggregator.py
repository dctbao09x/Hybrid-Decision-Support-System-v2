# backend/ops/governance/aggregator.py
"""
Ops Aggregator
==============

Aggregates operational metrics across time windows for:
- Dashboard displays
- SLA calculations
- Cost tracking
- Drift monitoring
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Deque, List, Optional, Tuple
from collections import deque

from backend.ops.governance.models import (
    OpsRecord,
    InferenceStatus,
    SLAMetrics,
    CostRecord,
)

logger = logging.getLogger("ops.governance.aggregator")


@dataclass
class TimeSeriesPoint:
    """Single point in a time series."""
    timestamp: float
    value: float
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class AggregateWindow:
    """Aggregated metrics for a time window."""
    window_start: str
    window_end: str
    window_minutes: int
    
    # Counts
    total_requests: int = 0
    success_count: int = 0
    error_count: int = 0
    timeout_count: int = 0
    
    # Latency
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    
    # Cost
    total_cost_usd: float = 0.0
    avg_cost_per_request: float = 0.0
    
    # Drift
    avg_drift_score: float = 0.0
    max_drift_score: float = 0.0
    
    # Derived
    availability: float = 1.0
    error_rate: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "window": {
                "start": self.window_start,
                "end": self.window_end,
                "minutes": self.window_minutes,
            },
            "counts": {
                "total": self.total_requests,
                "success": self.success_count,
                "error": self.error_count,
                "timeout": self.timeout_count,
            },
            "latency": {
                "avg": round(self.avg_latency_ms, 2),
                "p50": round(self.p50_latency_ms, 2),
                "p95": round(self.p95_latency_ms, 2),
                "p99": round(self.p99_latency_ms, 2),
                "max": round(self.max_latency_ms, 2),
            },
            "cost": {
                "total_usd": round(self.total_cost_usd, 6),
                "avg_per_request": round(self.avg_cost_per_request, 6),
            },
            "drift": {
                "avg": round(self.avg_drift_score, 4),
                "max": round(self.max_drift_score, 4),
            },
            "sla": {
                "availability": round(self.availability, 6),
                "error_rate": round(self.error_rate, 6),
            },
        }


class OpsAggregator:
    """
    Aggregates operational metrics across time windows.
    
    Maintains:
    - Per-minute aggregates (last hour)
    - Per-hour aggregates (last 24 hours)
    - Per-day aggregates (last 30 days)
    
    Thread-safe for concurrent metric recording.
    """
    
    def __init__(
        self,
        minute_retention: int = 60,  # Keep 60 minutes
        hour_retention: int = 24,    # Keep 24 hours
        day_retention: int = 30,     # Keep 30 days
    ):
        self._minute_retention = minute_retention
        self._hour_retention = hour_retention
        self._day_retention = day_retention
        
        # Time series data
        self._latency_samples: Deque[TimeSeriesPoint] = deque(maxlen=100000)
        self._cost_samples: Deque[TimeSeriesPoint] = deque(maxlen=100000)
        self._drift_samples: Deque[TimeSeriesPoint] = deque(maxlen=100000)
        
        # Status counts per time bucket
        self._minute_buckets: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._hour_buckets: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._day_buckets: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        
        # Cost aggregates
        self._cost_by_model: Dict[str, List[float]] = defaultdict(list)
        self._cost_by_user: Dict[str, List[float]] = defaultdict(list)
        self._cost_by_hour: Dict[str, float] = defaultdict(float)
        
        # Lock for thread safety
        self._lock = threading.RLock()
        
        logger.info("OpsAggregator initialized")
    
    def record(self, record: OpsRecord) -> None:
        """Record an ops event for aggregation."""
        ts = time.time()
        
        with self._lock:
            # Record latency
            self._latency_samples.append(TimeSeriesPoint(
                timestamp=ts,
                value=record.latency_ms,
                labels={"model_id": record.model_id, "status": record.status.value},
            ))
            
            # Record cost
            self._cost_samples.append(TimeSeriesPoint(
                timestamp=ts,
                value=record.cost_usd,
                labels={"model_id": record.model_id},
            ))
            
            # Record drift
            self._drift_samples.append(TimeSeriesPoint(
                timestamp=ts,
                value=record.drift_score,
                labels={"model_id": record.model_id},
            ))
            
            # Update time buckets
            now = datetime.fromtimestamp(ts, tz=timezone.utc)
            minute_key = now.strftime("%Y-%m-%d %H:%M")
            hour_key = now.strftime("%Y-%m-%d %H")
            day_key = now.strftime("%Y-%m-%d")
            
            status_key = record.status.value
            self._minute_buckets[minute_key][status_key] += 1
            self._minute_buckets[minute_key]["total"] += 1
            self._hour_buckets[hour_key][status_key] += 1
            self._hour_buckets[hour_key]["total"] += 1
            self._day_buckets[day_key][status_key] += 1
            self._day_buckets[day_key]["total"] += 1
            
            # Update cost aggregates
            self._cost_by_model[record.model_id].append(record.cost_usd)
            if record.user_id:
                self._cost_by_user[record.user_id].append(record.cost_usd)
            self._cost_by_hour[hour_key] += record.cost_usd
        
        # Cleanup old buckets periodically (every 100 records)
        if sum(b.get("total", 0) for b in self._minute_buckets.values()) % 100 == 0:
            self._cleanup_old_buckets()
    
    def _cleanup_old_buckets(self) -> None:
        """Remove old time buckets."""
        now = datetime.now(timezone.utc)
        
        with self._lock:
            # Clean minute buckets
            cutoff_minute = (now - timedelta(minutes=self._minute_retention)).strftime("%Y-%m-%d %H:%M")
            self._minute_buckets = defaultdict(
                lambda: defaultdict(int),
                {k: v for k, v in self._minute_buckets.items() if k >= cutoff_minute}
            )
            
            # Clean hour buckets
            cutoff_hour = (now - timedelta(hours=self._hour_retention)).strftime("%Y-%m-%d %H")
            self._hour_buckets = defaultdict(
                lambda: defaultdict(int),
                {k: v for k, v in self._hour_buckets.items() if k >= cutoff_hour}
            )
            
            # Clean day buckets
            cutoff_day = (now - timedelta(days=self._day_retention)).strftime("%Y-%m-%d")
            self._day_buckets = defaultdict(
                lambda: defaultdict(int),
                {k: v for k, v in self._day_buckets.items() if k >= cutoff_day}
            )
    
    def get_aggregate(self, window_minutes: int = 60) -> AggregateWindow:
        """Get aggregated metrics for the specified time window."""
        cutoff = time.time() - (window_minutes * 60)
        now = datetime.now(timezone.utc)
        
        with self._lock:
            # Filter samples
            latencies = [p.value for p in self._latency_samples if p.timestamp >= cutoff]
            costs = [p.value for p in self._cost_samples if p.timestamp >= cutoff]
            drifts = [p.value for p in self._drift_samples if p.timestamp >= cutoff]
            
            # Calculate status counts
            total = 0
            success = 0
            error = 0
            timeout = 0
            
            for p in self._latency_samples:
                if p.timestamp >= cutoff:
                    total += 1
                    status = p.labels.get("status", "")
                    if status == "success" or status == "cached":
                        success += 1
                    elif status == "error":
                        error += 1
                    elif status == "timeout":
                        timeout += 1
        
        if not latencies:
            return AggregateWindow(
                window_start=(now - timedelta(minutes=window_minutes)).isoformat(),
                window_end=now.isoformat(),
                window_minutes=window_minutes,
            )
        
        # Calculate percentiles
        latencies.sort()
        n = len(latencies)
        
        return AggregateWindow(
            window_start=(now - timedelta(minutes=window_minutes)).isoformat(),
            window_end=now.isoformat(),
            window_minutes=window_minutes,
            total_requests=total,
            success_count=success,
            error_count=error,
            timeout_count=timeout,
            avg_latency_ms=sum(latencies) / n,
            p50_latency_ms=latencies[int(n * 0.50)],
            p95_latency_ms=latencies[int(n * 0.95)] if n >= 20 else latencies[-1],
            p99_latency_ms=latencies[int(n * 0.99)] if n >= 100 else latencies[-1],
            max_latency_ms=max(latencies),
            total_cost_usd=sum(costs),
            avg_cost_per_request=sum(costs) / len(costs) if costs else 0.0,
            avg_drift_score=sum(drifts) / len(drifts) if drifts else 0.0,
            max_drift_score=max(drifts) if drifts else 0.0,
            availability=success / total if total > 0 else 1.0,
            error_rate=(error + timeout) / total if total > 0 else 0.0,
        )
    
    def get_latency_series(
        self,
        window_minutes: int = 60,
        resolution: str = "minute",  # "minute", "hour"
    ) -> List[Dict[str, Any]]:
        """Get latency time series data."""
        cutoff = time.time() - (window_minutes * 60)
        
        with self._lock:
            samples = [
                (p.timestamp, p.value)
                for p in self._latency_samples
                if p.timestamp >= cutoff
            ]
        
        if not samples:
            return []
        
        # Aggregate by resolution
        buckets: Dict[str, List[float]] = defaultdict(list)
        
        for ts, value in samples:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            if resolution == "minute":
                key = dt.strftime("%Y-%m-%d %H:%M")
            else:
                key = dt.strftime("%Y-%m-%d %H")
            buckets[key].append(value)
        
        series = []
        for bucket_key, values in sorted(buckets.items()):
            values.sort()
            n = len(values)
            series.append({
                "timestamp": bucket_key,
                "avg": round(sum(values) / n, 2),
                "min": round(min(values), 2),
                "max": round(max(values), 2),
                "p95": round(values[int(n * 0.95)] if n >= 20 else values[-1], 2),
                "count": n,
            })
        
        return series
    
    def get_cost_breakdown(self) -> Dict[str, Any]:
        """Get cost breakdown by model and user."""
        with self._lock:
            by_model = {
                model: {
                    "total": round(sum(costs), 6),
                    "count": len(costs),
                    "avg": round(sum(costs) / len(costs), 6) if costs else 0,
                }
                for model, costs in self._cost_by_model.items()
            }
            
            by_user = {
                user: {
                    "total": round(sum(costs), 6),
                    "count": len(costs),
                    "avg": round(sum(costs) / len(costs), 6) if costs else 0,
                }
                for user, costs in self._cost_by_user.items()
            }
            
            total_cost = sum(sum(costs) for costs in self._cost_by_model.values())
            
            # Hourly trend
            hourly = [
                {"hour": hour, "cost": round(cost, 6)}
                for hour, cost in sorted(self._cost_by_hour.items())[-24:]
            ]
        
        return {
            "total_cost_usd": round(total_cost, 6),
            "by_model": by_model,
            "by_user": by_user,
            "hourly_trend": hourly,
        }
    
    def get_error_analysis(self, window_minutes: int = 60) -> Dict[str, Any]:
        """Analyze errors in the time window."""
        cutoff = time.time() - (window_minutes * 60)
        
        with self._lock:
            errors = [
                p.labels
                for p in self._latency_samples
                if p.timestamp >= cutoff and p.labels.get("status") == "error"
            ]
            
            timeouts = [
                p.labels
                for p in self._latency_samples
                if p.timestamp >= cutoff and p.labels.get("status") == "timeout"
            ]
        
        # Group by model
        error_by_model: Dict[str, int] = defaultdict(int)
        for e in errors + timeouts:
            model = e.get("model_id", "unknown")
            error_by_model[model] += 1
        
        return {
            "total_errors": len(errors),
            "total_timeouts": len(timeouts),
            "errors_by_model": dict(error_by_model),
            "window_minutes": window_minutes,
        }
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get all data needed for the ops dashboard."""
        return {
            "realtime": self.get_aggregate(window_minutes=5).to_dict(),
            "hourly": self.get_aggregate(window_minutes=60).to_dict(),
            "daily": self.get_aggregate(window_minutes=1440).to_dict(),
            "latency_trend": self.get_latency_series(window_minutes=60),
            "cost_breakdown": self.get_cost_breakdown(),
            "error_analysis": self.get_error_analysis(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# Global aggregator instance
_aggregator: Optional[OpsAggregator] = None


def get_ops_aggregator() -> OpsAggregator:
    """Get or create the global ops aggregator instance."""
    global _aggregator
    if _aggregator is None:
        _aggregator = OpsAggregator()
    return _aggregator

"""Shadow Dispatcher - Handles shadow inference results, comparison, and logging."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ShadowResult:
    """Result from a shadow inference execution."""
    trace_id: str
    shadow_model_id: str
    result: Any
    latency_ms: float
    timestamp: str
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "shadow_model_id": self.shadow_model_id,
            "result": self.result,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp,
            "error": self.error,
        }


@dataclass
class ShadowComparison:
    """Comparison between production and shadow model results."""
    trace_id: str
    timestamp: str
    prod_model_id: Optional[str]
    shadow_model_id: Optional[str]
    prod_pred: Any
    shadow_pred: Any
    delta: Dict[str, Any]
    match: bool
    request_sample: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "prod_model_id": self.prod_model_id,
            "shadow_model_id": self.shadow_model_id,
            "prod_pred": self.prod_pred,
            "shadow_pred": self.shadow_pred,
            "delta": self.delta,
            "match": self.match,
            "request_sample": self.request_sample,
        }


@dataclass
class ShadowStats:
    """Aggregate statistics for shadow testing."""
    total_comparisons: int = 0
    matches: int = 0
    mismatches: int = 0
    errors: int = 0
    avg_delta: float = 0.0
    max_delta: float = 0.0
    window_start: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        match_rate = self.matches / max(1, self.total_comparisons)
        return {
            "total_comparisons": self.total_comparisons,
            "matches": self.matches,
            "mismatches": self.mismatches,
            "errors": self.errors,
            "match_rate": round(match_rate, 4),
            "avg_delta": round(self.avg_delta, 4),
            "max_delta": round(self.max_delta, 4),
            "window_start": self.window_start,
        }


class ShadowDispatcher:
    """Dispatches shadow inference and logs results for comparison.
    
    Log schema:
    {
        "trace_id": "trace_abc123",
        "prod_pred": {...},
        "shadow_pred": {...},
        "delta": {"score_diff": 0.05, "label_match": true},
        "timestamp": "2026-02-14T10:00:00Z"
    }
    
    Features:
    - Async logging to avoid blocking
    - Batch flushing for efficiency
    - Statistics aggregation
    - Nightly batch evaluation support
    """

    def __init__(
        self,
        log_path: Optional[str] = None,
        batch_size: int = 100,
        flush_interval_seconds: float = 60.0,
    ):
        """Initialize the shadow dispatcher.
        
        Args:
            log_path: Path to write shadow logs. Defaults to storage/mlops/shadow_results.jsonl
            batch_size: Number of results to buffer before flushing
            flush_interval_seconds: Max time between flushes
        """
        self._root = Path(__file__).resolve().parents[3]
        
        if log_path:
            self._log_path = Path(log_path)
        else:
            self._log_path = self._root / "storage" / "mlops" / "shadow_results.jsonl"
        
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._batch_size = batch_size
        self._flush_interval = flush_interval_seconds
        self._buffer: List[Dict[str, Any]] = []
        self._lock = RLock()
        
        # Statistics
        self._stats = ShadowStats(window_start=datetime.now(timezone.utc).isoformat())
        
        # Comparison function (can be customized)
        self._compare_fn: Optional[Callable[[Any, Any], Dict[str, Any]]] = None
        
        # Background flush task
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False

    def set_comparison_function(
        self,
        compare_fn: Callable[[Any, Any], Dict[str, Any]],
    ) -> None:
        """Set a custom comparison function.
        
        Args:
            compare_fn: Function that takes (prod_result, shadow_result) and returns
                       a dict with delta information and 'match' boolean.
        """
        self._compare_fn = compare_fn

    def _default_compare(
        self,
        prod_result: Any,
        shadow_result: Any,
    ) -> Dict[str, Any]:
        """Default comparison function for results.
        
        Handles common result formats:
        - Scalar values (numeric comparison)
        - Dicts with 'score', 'label', 'prediction' keys
        - Lists (element-wise comparison)
        """
        delta: Dict[str, Any] = {}
        match = True
        
        if prod_result is None or shadow_result is None:
            return {"delta": {"error": "null_result"}, "match": False}
        
        # Handle dict results
        if isinstance(prod_result, dict) and isinstance(shadow_result, dict):
            # Compare scores
            prod_score = prod_result.get("score", prod_result.get("confidence", prod_result.get("probability")))
            shadow_score = shadow_result.get("score", shadow_result.get("confidence", shadow_result.get("probability")))
            
            if prod_score is not None and shadow_score is not None:
                try:
                    score_diff = abs(float(shadow_score) - float(prod_score))
                    delta["score_diff"] = round(score_diff, 6)
                    if score_diff > 0.05:  # 5% threshold
                        match = False
                except (TypeError, ValueError):
                    pass
            
            # Compare labels
            prod_label = prod_result.get("label", prod_result.get("prediction", prod_result.get("class")))
            shadow_label = shadow_result.get("label", shadow_result.get("prediction", shadow_result.get("class")))
            
            if prod_label is not None and shadow_label is not None:
                label_match = prod_label == shadow_label
                delta["label_match"] = label_match
                if not label_match:
                    match = False
                    delta["prod_label"] = prod_label
                    delta["shadow_label"] = shadow_label
        
        # Handle scalar results
        elif isinstance(prod_result, (int, float)) and isinstance(shadow_result, (int, float)):
            diff = abs(float(shadow_result) - float(prod_result))
            delta["value_diff"] = round(diff, 6)
            if diff > 0.05:
                match = False
        
        # Handle string/categorical
        elif isinstance(prod_result, str) and isinstance(shadow_result, str):
            delta["string_match"] = prod_result == shadow_result
            match = prod_result == shadow_result
        
        else:
            # Generic equality check
            try:
                match = prod_result == shadow_result
                delta["type_mismatch"] = type(prod_result).__name__ != type(shadow_result).__name__
            except Exception:
                match = False
                delta["comparison_error"] = True
        
        return {"delta": delta, "match": match}

    def _compare(
        self,
        prod_result: Any,
        shadow_result: Any,
    ) -> Dict[str, Any]:
        """Compare production and shadow results."""
        if self._compare_fn:
            return self._compare_fn(prod_result, shadow_result)
        return self._default_compare(prod_result, shadow_result)

    async def dispatch(
        self,
        trace_id: str,
        request: Any,
        prod_model_id: Optional[str],
        shadow_model_id: Optional[str],
        prod_result: Any,
        shadow_result: Any,
    ) -> ShadowComparison:
        """Dispatch shadow result for comparison and logging.
        
        Args:
            trace_id: Unique trace ID for the request
            request: Original request (for sampling)
            prod_model_id: Production model ID
            shadow_model_id: Shadow model ID
            prod_result: Production inference result
            shadow_result: Shadow inference result
            
        Returns:
            ShadowComparison with comparison results
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Compare results
        comparison_result = self._compare(prod_result, shadow_result)
        delta = comparison_result.get("delta", {})
        match = comparison_result.get("match", False)
        
        # Create comparison object
        comparison = ShadowComparison(
            trace_id=trace_id,
            timestamp=timestamp,
            prod_model_id=prod_model_id,
            shadow_model_id=shadow_model_id,
            prod_pred=prod_result,
            shadow_pred=shadow_result,
            delta=delta,
            match=match,
            request_sample=self._sample_request(request),
        )
        
        # Update statistics
        self._update_stats(comparison)
        
        # Add to buffer
        await self._add_to_buffer(comparison.to_dict())
        
        if not match:
            logger.info(
                "Shadow mismatch: trace=%s, delta=%s",
                trace_id,
                delta,
            )
        
        return comparison

    def _sample_request(self, request: Any) -> Optional[Any]:
        """Sample request for logging (avoid storing full request)."""
        # Store a limited sample for debugging
        if request is None:
            return None
        
        if isinstance(request, dict):
            # Keep only essential fields
            sample = {}
            for key in ["id", "type", "category", "text"][:3]:
                if key in request:
                    val = request[key]
                    if isinstance(val, str) and len(val) > 100:
                        val = val[:100] + "..."
                    sample[key] = val
            return sample if sample else {"_type": type(request).__name__}
        
        if isinstance(request, str):
            return request[:100] + "..." if len(request) > 100 else request
        
        return {"_type": type(request).__name__}

    def _update_stats(self, comparison: ShadowComparison) -> None:
        """Update aggregate statistics."""
        with self._lock:
            self._stats.total_comparisons += 1
            
            if comparison.match:
                self._stats.matches += 1
            else:
                self._stats.mismatches += 1
            
            # Update delta stats
            delta = comparison.delta
            if "score_diff" in delta:
                diff = delta["score_diff"]
                # Running average
                n = self._stats.total_comparisons
                self._stats.avg_delta = (
                    (self._stats.avg_delta * (n - 1) + diff) / n
                )
                self._stats.max_delta = max(self._stats.max_delta, diff)

    async def _add_to_buffer(self, entry: Dict[str, Any]) -> None:
        """Add entry to buffer and flush if needed."""
        with self._lock:
            self._buffer.append(entry)
            
            if len(self._buffer) >= self._batch_size:
                await self._flush()

    async def _flush(self) -> None:
        """Flush buffer to log file."""
        with self._lock:
            if not self._buffer:
                return
            
            entries = self._buffer
            self._buffer = []
        
        try:
            with self._log_path.open("a", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            
            logger.debug("Flushed %d shadow results to log", len(entries))
        except Exception as e:
            logger.error("Failed to flush shadow log: %s", e)
            # Put entries back in buffer
            with self._lock:
                self._buffer = entries + self._buffer

    async def _flush_loop(self) -> None:
        """Background flush loop."""
        while self._running:
            await asyncio.sleep(self._flush_interval)
            await self._flush()

    async def start(self) -> None:
        """Start background flushing."""
        if self._running:
            return
        
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("Shadow dispatcher started")

    async def stop(self) -> None:
        """Stop background flushing and flush remaining entries."""
        if not self._running:
            return
        
        self._running = False
        
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        
        # Final flush
        await self._flush()
        logger.info("Shadow dispatcher stopped")

    def get_stats(self) -> Dict[str, Any]:
        """Get current shadow testing statistics."""
        return self._stats.to_dict()

    def reset_stats(self) -> None:
        """Reset statistics (e.g., for new evaluation window)."""
        with self._lock:
            self._stats = ShadowStats(window_start=datetime.now(timezone.utc).isoformat())

    def get_recent_comparisons(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Read recent comparisons from log file.
        
        Args:
            limit: Maximum number of entries to return
            
        Returns:
            List of recent comparison entries
        """
        if not self._log_path.exists():
            return []
        
        try:
            with self._log_path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
            
            entries = []
            for line in reversed(lines[-limit:]):
                if line.strip():
                    entries.append(json.loads(line))
            
            return entries
        except Exception as e:
            logger.error("Failed to read shadow log: %s", e)
            return []


class BatchEvaluator:
    """Evaluates shadow test results in batch (for nightly comparison jobs).
    
    Reads shadow logs and generates aggregate metrics comparing
    production and shadow model performance.
    """

    def __init__(self, log_path: Optional[str] = None):
        """Initialize the batch evaluator.
        
        Args:
            log_path: Path to shadow results log
        """
        self._root = Path(__file__).resolve().parents[3]
        
        if log_path:
            self._log_path = Path(log_path)
        else:
            self._log_path = self._root / "storage" / "mlops" / "shadow_results.jsonl"

    def evaluate(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Evaluate shadow results within a time window.
        
        Args:
            start_time: ISO format start time (default: 24h ago)
            end_time: ISO format end time (default: now)
            
        Returns:
            Evaluation results with metrics
        """
        from datetime import timedelta
        
        now = datetime.now(timezone.utc)
        if end_time is None:
            end_dt = now
        else:
            end_dt = datetime.fromisoformat(end_time)
        
        if start_time is None:
            start_dt = now - timedelta(hours=24)
        else:
            start_dt = datetime.fromisoformat(start_time)
        
        if not self._log_path.exists():
            return {
                "status": "no_data",
                "window": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
                "entries": 0,
            }
        
        # Read and filter entries
        entries = []
        try:
            with self._log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry.get("timestamp", ""))
                    if start_dt <= ts <= end_dt:
                        entries.append(entry)
        except Exception as e:
            logger.error("Failed to read shadow log: %s", e)
            return {"status": "error", "error": str(e)}
        
        if not entries:
            return {
                "status": "no_data",
                "window": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
                "entries": 0,
            }
        
        # Compute metrics
        total = len(entries)
        matches = sum(1 for e in entries if e.get("match", False))
        mismatches = total - matches
        
        score_diffs = [
            e.get("delta", {}).get("score_diff", 0)
            for e in entries
            if "score_diff" in e.get("delta", {})
        ]
        
        avg_score_diff = sum(score_diffs) / max(1, len(score_diffs)) if score_diffs else 0
        max_score_diff = max(score_diffs) if score_diffs else 0
        
        # Label agreement
        label_matches = sum(
            1 for e in entries
            if e.get("delta", {}).get("label_match", True)
        )
        
        return {
            "status": "success",
            "window": {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
            },
            "entries": total,
            "metrics": {
                "total_comparisons": total,
                "matches": matches,
                "mismatches": mismatches,
                "match_rate": round(matches / total, 4),
                "label_agreement_rate": round(label_matches / total, 4),
                "avg_score_diff": round(avg_score_diff, 6),
                "max_score_diff": round(max_score_diff, 6),
            },
            "recommendation": self._get_recommendation(matches / total, avg_score_diff),
        }

    def _get_recommendation(
        self,
        match_rate: float,
        avg_score_diff: float,
    ) -> str:
        """Generate a recommendation based on evaluation results."""
        if match_rate >= 0.99 and avg_score_diff < 0.01:
            return "PROMOTE: Shadow model performs identically to production"
        elif match_rate >= 0.95 and avg_score_diff < 0.03:
            return "REVIEW: Shadow model within acceptable variance, review mismatches"
        elif match_rate >= 0.90:
            return "CAUTION: Significant differences detected, investigate before promotion"
        else:
            return "REJECT: Shadow model shows substantial deviation from production"


# Singleton instance
_shadow_dispatcher: Optional[ShadowDispatcher] = None


def get_shadow_dispatcher() -> ShadowDispatcher:
    """Get the singleton ShadowDispatcher instance."""
    global _shadow_dispatcher
    if _shadow_dispatcher is None:
        _shadow_dispatcher = ShadowDispatcher()
    return _shadow_dispatcher


def get_batch_evaluator() -> BatchEvaluator:
    """Get a BatchEvaluator instance."""
    return BatchEvaluator()

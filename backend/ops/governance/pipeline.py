# backend/ops/governance/pipeline.py
"""
OPS Data Pipeline
=================

Central pipeline for collecting, processing, and routing operational data.

Architecture:
    Services → Metrics Collector → Ops Aggregator → SLA Engine → Alert Manager → Dashboard API

Each inference emits an OpsRecord that flows through this pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from backend.ops.governance.models import (
    OpsRecord,
    CostRecord,
    DriftRecord,
    InferenceStatus,
    SLAMetrics,
)

logger = logging.getLogger("ops.governance.pipeline")


class OpsPipeline:
    """
    Central operational data pipeline.
    
    Responsibilities:
    - Collect OpsRecords from all inference endpoints
    - Aggregate metrics for SLA evaluation
    - Persist records for audit/replay
    - Route data to alerting and dashboard systems
    
    Thread-safe for concurrent inference processing.
    """
    
    def __init__(
        self,
        db_path: Optional[Path] = None,
        buffer_size: int = 10000,
        flush_interval: int = 60,
        retention_months: int = 12,
    ):
        self._db_path = db_path or Path("backend/data/ops/governance.db")
        self._buffer_size = buffer_size
        self._flush_interval = flush_interval
        self._retention_months = retention_months
        
        # In-memory buffers
        self._record_buffer: Deque[OpsRecord] = deque(maxlen=buffer_size)
        self._lock = threading.RLock()
        
        # Aggregated metrics (rolling window)
        self._latency_samples: Deque[Tuple[float, float]] = deque(maxlen=10000)  # (timestamp, latency)
        self._status_counts: Dict[InferenceStatus, int] = defaultdict(int)
        self._cost_by_model: Dict[str, float] = defaultdict(float)
        self._cost_by_user: Dict[str, float] = defaultdict(float)
        self._drift_scores: Deque[Tuple[float, float]] = deque(maxlen=1000)  # (timestamp, drift)
        
        # Subscribers
        self._subscribers: List[Callable[[OpsRecord], None]] = []
        
        # Stats
        self._total_records = 0
        self._last_flush = time.time()
        
        # Initialize storage
        self._initialized = False
        self._conn: Optional[sqlite3.Connection] = None
    
    async def initialize(self) -> None:
        """Initialize storage and start background tasks."""
        if self._initialized:
            return
        
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        self._initialized = True
        
        logger.info(f"OpsPipeline initialized with db at {self._db_path}")
    
    def _create_tables(self) -> None:
        """Create database tables."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS ops_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id TEXT NOT NULL UNIQUE,
                trace_id TEXT NOT NULL,
                latency_ms REAL NOT NULL,
                cost_usd REAL NOT NULL,
                model_id TEXT NOT NULL,
                drift_score REAL NOT NULL,
                status TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                user_id TEXT,
                session_id TEXT,
                endpoint TEXT,
                input_size INTEGER,
                output_size INTEGER,
                confidence REAL,
                error_code TEXT,
                error_message TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_ops_records_trace ON ops_records(trace_id);
            CREATE INDEX IF NOT EXISTS idx_ops_records_timestamp ON ops_records(timestamp);
            CREATE INDEX IF NOT EXISTS idx_ops_records_model ON ops_records(model_id);
            CREATE INDEX IF NOT EXISTS idx_ops_records_status ON ops_records(status);
            CREATE INDEX IF NOT EXISTS idx_ops_records_user ON ops_records(user_id);
            
            CREATE TABLE IF NOT EXISTS cost_aggregates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL,
                model_id TEXT NOT NULL,
                user_id TEXT,
                total_cost REAL NOT NULL,
                call_count INTEGER NOT NULL,
                avg_cost_per_call REAL NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(period, model_id, user_id)
            );
            
            CREATE TABLE IF NOT EXISTS drift_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                drift_type TEXT NOT NULL,
                score REAL NOT NULL,
                model_id TEXT NOT NULL,
                feature_drifts TEXT,
                is_significant INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_drift_timestamp ON drift_snapshots(timestamp);
            CREATE INDEX IF NOT EXISTS idx_drift_model ON drift_snapshots(model_id);
            
            CREATE TABLE IF NOT EXISTS sla_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                availability REAL NOT NULL,
                p50_latency REAL NOT NULL,
                p95_latency REAL NOT NULL,
                p99_latency REAL NOT NULL,
                error_rate REAL NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                sample_count INTEGER NOT NULL,
                compliance INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_sla_timestamp ON sla_snapshots(timestamp);
        """)
        self._conn.commit()
    
    def emit(self, record: OpsRecord) -> None:
        """
        Emit an OpsRecord to the pipeline.
        
        Called by inference endpoints after each prediction.
        """
        with self._lock:
            # Add to buffer
            self._record_buffer.append(record)
            self._total_records += 1
            
            # Update aggregates
            ts = time.time()
            self._latency_samples.append((ts, record.latency_ms))
            self._status_counts[record.status] += 1
            self._cost_by_model[record.model_id] += record.cost_usd
            if record.user_id:
                self._cost_by_user[record.user_id] += record.cost_usd
            self._drift_scores.append((ts, record.drift_score))
        
        # Notify subscribers (async-safe)
        for subscriber in self._subscribers:
            try:
                subscriber(record)
            except Exception as e:
                logger.warning(f"Subscriber error: {e}")
    
    def subscribe(self, callback: Callable[[OpsRecord], None]) -> None:
        """Subscribe to receive OpsRecords."""
        self._subscribers.append(callback)
    
    async def flush(self) -> int:
        """Flush buffered records to storage."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            records = list(self._record_buffer)
            self._record_buffer.clear()
        
        if not records:
            return 0
        
        import json
        now = datetime.now(timezone.utc).isoformat()
        
        with self._lock:
            for record in records:
                try:
                    self._conn.execute(
                        """
                        INSERT OR IGNORE INTO ops_records
                        (record_id, trace_id, latency_ms, cost_usd, model_id, drift_score,
                         status, timestamp, user_id, session_id, endpoint, input_size,
                         output_size, confidence, error_code, error_message, metadata, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record.record_id,
                            record.trace_id,
                            record.latency_ms,
                            record.cost_usd,
                            record.model_id,
                            record.drift_score,
                            record.status.value,
                            record.timestamp,
                            record.user_id,
                            record.session_id,
                            record.endpoint,
                            record.input_size,
                            record.output_size,
                            record.confidence,
                            record.error_code,
                            record.error_message,
                            json.dumps(record.metadata),
                            now,
                        )
                    )
                except sqlite3.Error as e:
                    logger.warning(f"Failed to persist record {record.trace_id}: {e}")
            
            self._conn.commit()
        
        self._last_flush = time.time()
        logger.debug(f"Flushed {len(records)} ops records to storage")
        return len(records)
    
    def get_sla_metrics(self, window_minutes: int = 60) -> SLAMetrics:
        """Calculate SLA metrics for the given time window."""
        cutoff = time.time() - (window_minutes * 60)
        
        with self._lock:
            # Filter samples within window
            latencies = [lat for ts, lat in self._latency_samples if ts >= cutoff]
            
            if not latencies:
                return SLAMetrics(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    availability=1.0,
                    p50_latency_ms=0.0,
                    p95_latency_ms=0.0,
                    p99_latency_ms=0.0,
                    error_rate=0.0,
                )
            
            # Calculate percentiles
            latencies.sort()
            n = len(latencies)
            p50 = latencies[int(n * 0.50)] if n > 0 else 0
            p95 = latencies[int(n * 0.95)] if n > 0 else 0
            p99 = latencies[int(n * 0.99)] if n > 0 else 0
            
            # Calculate error rate
            total = sum(self._status_counts.values())
            errors = self._status_counts.get(InferenceStatus.ERROR, 0)
            timeouts = self._status_counts.get(InferenceStatus.TIMEOUT, 0)
            error_rate = (errors + timeouts) / total if total > 0 else 0.0
            
            # Calculate availability (success + cached + degraded / total)
            success = self._status_counts.get(InferenceStatus.SUCCESS, 0)
            cached = self._status_counts.get(InferenceStatus.CACHED, 0)
            degraded = self._status_counts.get(InferenceStatus.DEGRADED, 0)
            availability = (success + cached + degraded) / total if total > 0 else 1.0
            
            now = datetime.now(timezone.utc)
            
            return SLAMetrics(
                timestamp=now.isoformat(),
                availability=availability,
                p50_latency_ms=p50,
                p95_latency_ms=p95,
                p99_latency_ms=p99,
                error_rate=error_rate,
                period_start=(now - timedelta(minutes=window_minutes)).isoformat(),
                period_end=now.isoformat(),
                sample_count=n,
            )
    
    def get_cost_summary(self) -> Dict[str, Any]:
        """Get cost summary by model and user."""
        with self._lock:
            return {
                "by_model": dict(self._cost_by_model),
                "by_user": dict(self._cost_by_user),
                "total": sum(self._cost_by_model.values()),
            }
    
    def get_drift_summary(self, window_minutes: int = 60) -> Dict[str, Any]:
        """Get drift summary for the given time window."""
        cutoff = time.time() - (window_minutes * 60)
        
        with self._lock:
            scores = [score for ts, score in self._drift_scores if ts >= cutoff]
            
            if not scores:
                return {
                    "avg_drift": 0.0,
                    "max_drift": 0.0,
                    "sample_count": 0,
                }
            
            return {
                "avg_drift": sum(scores) / len(scores),
                "max_drift": max(scores),
                "min_drift": min(scores),
                "sample_count": len(scores),
            }
    
    def get_recent_records(
        self,
        limit: int = 100,
        status: Optional[InferenceStatus] = None,
        model_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent records from buffer."""
        with self._lock:
            records = list(self._record_buffer)
        
        # Filter
        if status:
            records = [r for r in records if r.status == status]
        if model_id:
            records = [r for r in records if r.model_id == model_id]
        
        # Sort by timestamp descending and limit
        records.sort(key=lambda r: r.timestamp, reverse=True)
        records = records[:limit]
        
        return [r.to_dict() for r in records]
    
    async def query_history(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        model_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """Query historical records from storage."""
        if not self._initialized:
            await self.initialize()
        
        import json
        
        query = "SELECT * FROM ops_records WHERE 1=1"
        params: List[Any] = []
        
        if from_date:
            query += " AND timestamp >= ?"
            params.append(from_date)
        if to_date:
            query += " AND timestamp <= ?"
            params.append(to_date)
        if model_id:
            query += " AND model_id = ?"
            params.append(model_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        with self._lock:
            cursor = self._conn.execute(query, params)
            rows = cursor.fetchall()
        
        results = []
        for row in rows:
            results.append({
                "record_id": row["record_id"],
                "trace_id": row["trace_id"],
                "latency_ms": row["latency_ms"],
                "cost_usd": row["cost_usd"],
                "model_id": row["model_id"],
                "drift_score": row["drift_score"],
                "status": row["status"],
                "timestamp": row["timestamp"],
                "user_id": row["user_id"],
                "endpoint": row["endpoint"],
                "confidence": row["confidence"],
                "error_code": row["error_code"],
                "metadata": json.loads(row["metadata"] or "{}"),
            })
        
        return results
    
    async def cleanup_old_records(self) -> Dict[str, Any]:
        """Remove records older than retention period."""
        if not self._initialized:
            await self.initialize()
        
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self._retention_months * 30)
        ).isoformat()
        
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM ops_records WHERE timestamp < ?",
                (cutoff,)
            )
            deleted = cursor.rowcount
            self._conn.commit()
        
        return {
            "deleted_records": deleted,
            "cutoff_date": cutoff,
            "retention_months": self._retention_months,
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        with self._lock:
            return {
                "total_records_processed": self._total_records,
                "buffer_size": len(self._record_buffer),
                "buffer_capacity": self._buffer_size,
                "status_distribution": {
                    k.value: v for k, v in self._status_counts.items()
                },
                "total_cost": sum(self._cost_by_model.values()),
                "models_tracked": len(self._cost_by_model),
                "users_tracked": len(self._cost_by_user),
                "last_flush": datetime.fromtimestamp(
                    self._last_flush, tz=timezone.utc
                ).isoformat(),
            }


# Global pipeline instance
_pipeline: Optional[OpsPipeline] = None


def get_ops_pipeline() -> OpsPipeline:
    """Get or create the global ops pipeline instance."""
    global _pipeline
    if _pipeline is None:
        _pipeline = OpsPipeline()
    return _pipeline


def emit_ops_record(record: OpsRecord) -> None:
    """Convenience function to emit an ops record."""
    get_ops_pipeline().emit(record)

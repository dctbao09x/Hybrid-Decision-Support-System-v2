# backend/feedback/storage.py
"""
Feedback Storage Layer
======================

SQLite-based persistence for feedback and trace data.
Implements audit logging and data retention policies.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.feedback.models import (
    TraceRecord,
    FeedbackEntry,
    FeedbackStatus,
    TrainingCandidate,
    FeedbackAuditLog,
    TrainingStatus,
)

logger = logging.getLogger("feedback.storage")


# ==============================================================================
# FEEDBACK STORAGE
# ==============================================================================

class FeedbackStorage:
    """
    SQLite storage for feedback loop system.
    
    Tables:
      - traces: Inference trace records
      - feedback: User feedback entries
      - training_candidates: Training samples from feedback
      - audit_log: All operations audit trail
    
    Data Retention Policy (TASK 10):
      - Raw feedback: 2 years
      - Approved training data: permanent
      - Rejected feedback: 6 months
    """
    
    def __init__(
        self,
        db_path: Optional[Path] = None,
    ):
        self._db_path = db_path or Path("storage/feedback_loop.db")
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize database and create tables."""
        with self._lock:
            if self._initialized:
                return
            
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            
            # Create tables
            self._create_tables()
            
            self._initialized = True
            logger.info(f"Feedback storage initialized: {self._db_path}")
    
    def _create_tables(self) -> None:
        """Create database tables."""
        
        # Traces table
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS traces (
                trace_id TEXT PRIMARY KEY,
                user_id TEXT,
                input_profile TEXT NOT NULL,
                kb_snapshot_version TEXT,
                model_version TEXT NOT NULL,
                rule_path TEXT,
                score_vector TEXT,
                timestamp TEXT NOT NULL,
                predicted_career TEXT,
                predicted_confidence REAL DEFAULT 0,
                top_careers TEXT,
                reasons TEXT,
                xai_meta TEXT,
                latency_ms REAL DEFAULT 0,
                stage_timings TEXT,
                request_hash TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Feedback table
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
                correction TEXT NOT NULL,
                reason TEXT NOT NULL,
                source TEXT DEFAULT 'web_ui',
                created_at TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                reviewer_id TEXT,
                reviewed_at TEXT,
                review_notes TEXT,
                linked_train_id TEXT,
                training_status TEXT DEFAULT 'candidate',
                quality_score REAL DEFAULT 0,
                consistency_score REAL DEFAULT 0,
                FOREIGN KEY (trace_id) REFERENCES traces(trace_id)
            )
        """)
        
        # Training candidates table
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS training_candidates (
                train_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                feedback_id TEXT NOT NULL,
                input_features TEXT NOT NULL,
                target_label TEXT NOT NULL,
                original_prediction TEXT,
                kb_version TEXT,
                model_version TEXT,
                quality_score REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                used_in_training INTEGER DEFAULT 0,
                training_batch_id TEXT,
                FOREIGN KEY (trace_id) REFERENCES traces(trace_id),
                FOREIGN KEY (feedback_id) REFERENCES feedback(id)
            )
        """)
        
        # Audit log table
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                user_id TEXT,
                details TEXT,
                ip_address TEXT
            )
        """)
        
        # Indexes
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_traces_timestamp ON traces(timestamp)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_traces_user ON traces(user_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_trace ON feedback(trace_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_training_feedback ON training_candidates(feedback_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id)")
        
        self._conn.commit()
    
    # ==========================================================================
    # TRACE OPERATIONS
    # ==========================================================================
    
    async def store_trace(self, trace: TraceRecord) -> TraceRecord:
        """Store a trace record."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            self._conn.execute("""
                INSERT OR REPLACE INTO traces
                (trace_id, user_id, input_profile, kb_snapshot_version, model_version,
                 rule_path, score_vector, timestamp, predicted_career, predicted_confidence,
                 top_careers, reasons, xai_meta, latency_ms, stage_timings, request_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trace.trace_id,
                trace.user_id,
                json.dumps(trace.input_profile, ensure_ascii=False),
                trace.kb_snapshot_version,
                trace.model_version,
                json.dumps(trace.rule_path, ensure_ascii=False),
                json.dumps(trace.score_vector, ensure_ascii=False),
                trace.timestamp,
                trace.predicted_career,
                trace.predicted_confidence,
                json.dumps(trace.top_careers, ensure_ascii=False),
                json.dumps(trace.reasons, ensure_ascii=False),
                json.dumps(trace.xai_meta, ensure_ascii=False),
                trace.latency_ms,
                json.dumps(trace.stage_timings, ensure_ascii=False),
                trace.request_hash,
            ))
            self._conn.commit()
            
            logger.debug(f"Stored trace: {trace.trace_id}")
            return trace
    
    async def get_trace(self, trace_id: str) -> Optional[TraceRecord]:
        """Get a trace by ID."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM traces WHERE trace_id = ?",
                (trace_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return TraceRecord(
                trace_id=row["trace_id"],
                user_id=row["user_id"],
                input_profile=json.loads(row["input_profile"]),
                kb_snapshot_version=row["kb_snapshot_version"],
                model_version=row["model_version"],
                rule_path=json.loads(row["rule_path"] or "[]"),
                score_vector=json.loads(row["score_vector"] or "{}"),
                timestamp=row["timestamp"],
                predicted_career=row["predicted_career"],
                predicted_confidence=row["predicted_confidence"] or 0.0,
                top_careers=json.loads(row["top_careers"] or "[]"),
                reasons=json.loads(row["reasons"] or "[]"),
                xai_meta=json.loads(row["xai_meta"] or "{}"),
                latency_ms=row["latency_ms"] or 0.0,
                stage_timings=json.loads(row["stage_timings"] or "{}"),
                request_hash=row["request_hash"] or "",
            )
    
    async def trace_exists(self, trace_id: str) -> bool:
        """Check if trace exists."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            cursor = self._conn.execute(
                "SELECT 1 FROM traces WHERE trace_id = ?",
                (trace_id,)
            )
            return cursor.fetchone() is not None
    
    async def get_trace_count(self) -> int:
        """Get total trace count."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            cursor = self._conn.execute("SELECT COUNT(*) FROM traces")
            return cursor.fetchone()[0]
    
    # ==========================================================================
    # FEEDBACK OPERATIONS
    # ==========================================================================
    
    async def store_feedback(self, feedback: FeedbackEntry) -> FeedbackEntry:
        """Store a feedback entry."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            self._conn.execute("""
                INSERT INTO feedback
                (id, trace_id, rating, correction, reason, source, created_at,
                 status, reviewer_id, reviewed_at, review_notes, linked_train_id,
                 training_status, quality_score, consistency_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                feedback.id,
                feedback.trace_id,
                feedback.rating,
                json.dumps(feedback.correction, ensure_ascii=False),
                feedback.reason,
                feedback.source.value,
                feedback.created_at,
                feedback.status.value,
                feedback.reviewer_id,
                feedback.reviewed_at,
                feedback.review_notes,
                feedback.linked_train_id,
                feedback.training_status.value,
                feedback.quality_score,
                feedback.consistency_score,
            ))
            self._conn.commit()
            
            logger.debug(f"Stored feedback: {feedback.id}")
            return feedback
    
    async def get_feedback(self, feedback_id: str) -> Optional[FeedbackEntry]:
        """Get feedback by ID."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM feedback WHERE id = ?",
                (feedback_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return self._row_to_feedback(row)
    
    async def get_feedback_by_trace(self, trace_id: str) -> List[FeedbackEntry]:
        """Get all feedback for a trace."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM feedback WHERE trace_id = ? ORDER BY created_at DESC",
                (trace_id,)
            )
            return [self._row_to_feedback(row) for row in cursor.fetchall()]
    
    async def update_feedback_status(
        self,
        feedback_id: str,
        status: FeedbackStatus,
        reviewer_id: str,
        notes: Optional[str] = None,
    ) -> bool:
        """Update feedback review status."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            self._conn.execute("""
                UPDATE feedback SET
                    status = ?,
                    reviewer_id = ?,
                    reviewed_at = ?,
                    review_notes = ?
                WHERE id = ?
            """, (
                status.value,
                reviewer_id,
                datetime.now(timezone.utc).isoformat(),
                notes,
                feedback_id,
            ))
            self._conn.commit()
            return self._conn.total_changes > 0
    
    async def list_feedback(
        self,
        status: Optional[FeedbackStatus] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[FeedbackEntry], int]:
        """List feedback with filters."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            conditions = []
            params = []
            
            if status:
                conditions.append("status = ?")
                params.append(status.value)
            
            if from_date:
                conditions.append("created_at >= ?")
                params.append(from_date)
            
            if to_date:
                conditions.append("created_at <= ?")
                params.append(to_date)
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            # Get total count
            count_cursor = self._conn.execute(
                f"SELECT COUNT(*) FROM feedback WHERE {where_clause}",
                params
            )
            total = count_cursor.fetchone()[0]
            
            # Get items
            cursor = self._conn.execute(
                f"""SELECT * FROM feedback WHERE {where_clause}
                    ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                params + [limit, offset]
            )
            
            items = [self._row_to_feedback(row) for row in cursor.fetchall()]
            return items, total
    
    async def feedback_exists_for_trace(self, trace_id: str) -> bool:
        """Check if feedback exists for a trace."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            cursor = self._conn.execute(
                "SELECT 1 FROM feedback WHERE trace_id = ? LIMIT 1",
                (trace_id,)
            )
            return cursor.fetchone() is not None
    
    def _row_to_feedback(self, row: sqlite3.Row) -> FeedbackEntry:
        """Convert row to FeedbackEntry."""
        return FeedbackEntry(
            id=row["id"],
            trace_id=row["trace_id"],
            rating=row["rating"],
            correction=json.loads(row["correction"]),
            reason=row["reason"],
            source=row["source"],
            created_at=row["created_at"],
            status=FeedbackStatus(row["status"]),
            reviewer_id=row["reviewer_id"],
            reviewed_at=row["reviewed_at"],
            review_notes=row["review_notes"],
            linked_train_id=row["linked_train_id"],
            training_status=TrainingStatus(row["training_status"]),
            quality_score=row["quality_score"] or 0.0,
            consistency_score=row["consistency_score"] or 0.0,
        )
    
    # ==========================================================================
    # TRAINING CANDIDATES
    # ==========================================================================
    
    async def store_training_candidate(self, candidate: TrainingCandidate) -> TrainingCandidate:
        """Store a training candidate."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            self._conn.execute("""
                INSERT INTO training_candidates
                (train_id, trace_id, feedback_id, input_features, target_label,
                 original_prediction, kb_version, model_version, quality_score,
                 created_at, used_in_training, training_batch_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                candidate.train_id,
                candidate.trace_id,
                candidate.feedback_id,
                json.dumps(candidate.input_features, ensure_ascii=False),
                candidate.target_label,
                candidate.original_prediction,
                candidate.kb_version,
                candidate.model_version,
                candidate.quality_score,
                candidate.created_at,
                1 if candidate.used_in_training else 0,
                candidate.training_batch_id,
            ))
            self._conn.commit()
            
            # Update feedback with linked train_id
            self._conn.execute(
                "UPDATE feedback SET linked_train_id = ? WHERE id = ?",
                (candidate.train_id, candidate.feedback_id)
            )
            self._conn.commit()
            
            return candidate
    
    async def get_training_candidates(
        self,
        min_quality: float = 0.0,
        unused_only: bool = True,
        limit: int = 1000,
    ) -> List[TrainingCandidate]:
        """Get training candidates."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            conditions = ["quality_score >= ?"]
            params = [min_quality]
            
            if unused_only:
                conditions.append("used_in_training = 0")
            
            where_clause = " AND ".join(conditions)
            
            cursor = self._conn.execute(
                f"""SELECT * FROM training_candidates WHERE {where_clause}
                    ORDER BY quality_score DESC LIMIT ?""",
                params + [limit]
            )
            
            return [self._row_to_candidate(row) for row in cursor.fetchall()]
    
    async def mark_candidates_used(
        self,
        train_ids: List[str],
        batch_id: str,
    ) -> int:
        """Mark training candidates as used."""
        if not self._initialized:
            await self.initialize()
        
        if not train_ids:
            return 0
        
        with self._lock:
            placeholders = ",".join("?" * len(train_ids))
            self._conn.execute(
                f"""UPDATE training_candidates SET
                    used_in_training = 1,
                    training_batch_id = ?
                WHERE train_id IN ({placeholders})""",
                [batch_id] + train_ids
            )
            self._conn.commit()
            return self._conn.total_changes
    
    def _row_to_candidate(self, row: sqlite3.Row) -> TrainingCandidate:
        """Convert row to TrainingCandidate."""
        return TrainingCandidate(
            train_id=row["train_id"],
            trace_id=row["trace_id"],
            feedback_id=row["feedback_id"],
            input_features=json.loads(row["input_features"]),
            target_label=row["target_label"],
            original_prediction=row["original_prediction"],
            kb_version=row["kb_version"],
            model_version=row["model_version"],
            quality_score=row["quality_score"] or 0.0,
            created_at=row["created_at"],
            used_in_training=bool(row["used_in_training"]),
            training_batch_id=row["training_batch_id"],
        )
    
    # ==========================================================================
    # AUDIT LOG
    # ==========================================================================
    
    async def log_audit(self, audit: FeedbackAuditLog) -> None:
        """Log an audit entry."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            self._conn.execute("""
                INSERT INTO audit_log
                (id, timestamp, action, entity_type, entity_id, user_id, details, ip_address)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                audit.id,
                audit.timestamp,
                audit.action,
                audit.entity_type,
                audit.entity_id,
                audit.user_id,
                json.dumps(audit.details, ensure_ascii=False),
                audit.ip_address,
            ))
            self._conn.commit()
    
    # ==========================================================================
    # STATISTICS
    # ==========================================================================
    
    async def get_feedback_stats(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get feedback statistics."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            params = []
            date_filter = ""
            
            if from_date:
                date_filter += " AND created_at >= ?"
                params.append(from_date)
            if to_date:
                date_filter += " AND created_at <= ?"
                params.append(to_date)
            
            # Feedback counts by status
            cursor = self._conn.execute(f"""
                SELECT status, COUNT(*) as cnt FROM feedback
                WHERE 1=1 {date_filter}
                GROUP BY status
            """, params)
            
            status_counts = {row["status"]: row["cnt"] for row in cursor.fetchall()}
            
            # Total traces
            cursor = self._conn.execute("SELECT COUNT(*) FROM traces")
            total_traces = cursor.fetchone()[0]
            
            # Average rating
            cursor = self._conn.execute(f"""
                SELECT AVG(rating), AVG(quality_score) FROM feedback
                WHERE 1=1 {date_filter}
            """, params)
            row = cursor.fetchone()
            avg_rating = row[0] or 0.0
            avg_quality = row[1] or 0.0
            
            # Training samples
            cursor = self._conn.execute("SELECT COUNT(*) FROM training_candidates")
            training_generated = cursor.fetchone()[0]
            
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM training_candidates WHERE used_in_training = 1"
            )
            training_used = cursor.fetchone()[0]
            
            # Career distribution
            cursor = self._conn.execute(f"""
                SELECT json_extract(correction, '$.correct_career') as career, COUNT(*) as cnt
                FROM feedback WHERE 1=1 {date_filter}
                GROUP BY career ORDER BY cnt DESC LIMIT 10
            """, params)
            career_dist = {row["career"]: row["cnt"] for row in cursor.fetchall() if row["career"]}
            
            total_feedback = sum(status_counts.values())
            approved = status_counts.get("approved", 0)
            
            return {
                "total_feedback": total_feedback,
                "pending_count": status_counts.get("pending", 0),
                "approved_count": approved,
                "rejected_count": status_counts.get("rejected", 0),
                "flagged_count": status_counts.get("flagged", 0),
                "feedback_rate": total_feedback / total_traces if total_traces > 0 else 0,
                "approval_rate": approved / total_feedback if total_feedback > 0 else 0,
                "avg_rating": avg_rating,
                "avg_quality_score": avg_quality,
                "training_samples_generated": training_generated,
                "training_samples_used": training_used,
                "career_distribution": career_dist,
            }
    
    # ==========================================================================
    # DATA RETENTION
    # ==========================================================================
    
    async def cleanup_old_data(self) -> Dict[str, int]:
        """Apply data retention policy."""
        if not self._initialized:
            await self.initialize()
        
        now = datetime.now(timezone.utc)
        
        # Rejected feedback: 6 months
        rejected_cutoff = (now - timedelta(days=180)).isoformat()
        
        # Raw feedback: 2 years
        raw_cutoff = (now - timedelta(days=730)).isoformat()
        
        with self._lock:
            # Delete old rejected feedback
            self._conn.execute(
                "DELETE FROM feedback WHERE status = 'rejected' AND created_at < ?",
                (rejected_cutoff,)
            )
            deleted_rejected = self._conn.total_changes
            
            # Delete very old pending feedback
            self._conn.execute(
                "DELETE FROM feedback WHERE status = 'pending' AND created_at < ?",
                (raw_cutoff,)
            )
            deleted_pending = self._conn.total_changes
            
            # Keep approved training data permanently
            # Delete orphan traces (no feedback, older than 1 year)
            year_ago = (now - timedelta(days=365)).isoformat()
            self._conn.execute("""
                DELETE FROM traces WHERE trace_id NOT IN (
                    SELECT DISTINCT trace_id FROM feedback
                ) AND timestamp < ?
            """, (year_ago,))
            deleted_traces = self._conn.total_changes
            
            self._conn.commit()
            
            return {
                "deleted_rejected": deleted_rejected,
                "deleted_pending": deleted_pending,
                "deleted_traces": deleted_traces,
            }
    
    async def close(self) -> None:
        """Close database connection."""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None
            self._initialized = False


# ==============================================================================
# SINGLETON INSTANCE
# ==============================================================================

_storage_instance: Optional[FeedbackStorage] = None


def get_feedback_storage() -> FeedbackStorage:
    """Get singleton storage instance."""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = FeedbackStorage()
    return _storage_instance

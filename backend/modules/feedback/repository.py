from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .model import FeedbackPriority, FeedbackQuery, FeedbackRecord, FeedbackStatus, FeedbackSubmitRequest


class FeedbackRepository:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or Path("storage/admin_feedback.db")
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()

    def initialize(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._create_tables()

    def _create_tables(self) -> None:
        assert self._conn is not None
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                email TEXT NOT NULL,
                rating INTEGER NOT NULL,
                category TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                priority TEXT NOT NULL DEFAULT 'medium',
                created_at TEXT NOT NULL,
                reviewed_by TEXT,
                screenshot TEXT,
                meta TEXT,
                archived INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_status_created ON feedback(status, created_at DESC)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_category ON feedback(category)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating)")
        self._conn.commit()

    def submit_feedback(self, payload: FeedbackSubmitRequest) -> FeedbackRecord:
        self.initialize()
        now = datetime.now(timezone.utc).isoformat()
        feedback_id = f"fb_{uuid.uuid4().hex[:16]}"
        priority = self._derive_priority(payload.rating)

        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                """
                INSERT INTO feedback (id, user_id, email, rating, category, message, status, priority, created_at, reviewed_by, screenshot, meta, archived)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    feedback_id,
                    payload.userId,
                    str(payload.email),
                    payload.rating,
                    payload.category,
                    payload.message,
                    FeedbackStatus.NEW.value,
                    priority.value,
                    now,
                    None,
                    payload.screenshot,
                    payload.meta.model_dump_json(),
                ),
            )
            self._conn.commit()

        return FeedbackRecord(
            id=feedback_id,
            user_id=payload.userId,
            email=str(payload.email),
            rating=payload.rating,
            category=payload.category,
            message=payload.message,
            status=FeedbackStatus.NEW,
            priority=priority,
            created_at=now,
            reviewed_by=None,
            screenshot=payload.screenshot,
            meta=payload.meta.model_dump(),
        )

    def list_feedback(self, query: FeedbackQuery) -> Tuple[List[FeedbackRecord], int]:
        self.initialize()
        where_clauses = ["archived = 0"]
        params: List[Any] = []

        if query.status:
            where_clauses.append("status = ?")
            params.append(query.status.value)
        if query.rating:
            where_clauses.append("rating = ?")
            params.append(query.rating)
        if query.category:
            where_clauses.append("category = ?")
            params.append(query.category)
        if query.from_date:
            where_clauses.append("created_at >= ?")
            params.append(query.from_date.isoformat())
        if query.to_date:
            where_clauses.append("created_at <= ?")
            params.append(query.to_date.isoformat())
        if query.search:
            where_clauses.append("(user_id LIKE ? OR email LIKE ? OR message LIKE ?)")
            wildcard = f"%{query.search}%"
            params.extend([wildcard, wildcard, wildcard])
        
        # === RETRAIN-GRADE FILTERS (2026-02-20) ===
        if query.career_id:
            where_clauses.append("career_id = ?")
            params.append(query.career_id)
        if query.model_version:
            where_clauses.append("model_version = ?")
            params.append(query.model_version)
        if query.explicit_accept is not None:
            where_clauses.append("explicit_accept = ?")
            params.append(1 if query.explicit_accept else 0)
        if query.min_confidence is not None:
            where_clauses.append("confidence >= ?")
            params.append(query.min_confidence)
        if query.max_confidence is not None:
            where_clauses.append("confidence <= ?")
            params.append(query.max_confidence)

        where_sql = " AND ".join(where_clauses)
        offset = (query.page - 1) * query.page_size

        with self._lock:
            assert self._conn is not None
            rows = self._conn.execute(
                f"SELECT * FROM feedback WHERE {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*params, query.page_size, offset],
            ).fetchall()
            total = self._conn.execute(
                f"SELECT COUNT(1) as total FROM feedback WHERE {where_sql}",
                params,
            ).fetchone()["total"]

        return [self._to_record(row) for row in rows], int(total)

    def update_status(self, feedback_id: str, status: FeedbackStatus, priority: Optional[FeedbackPriority]) -> Optional[FeedbackRecord]:
        self.initialize()
        with self._lock:
            assert self._conn is not None
            if priority:
                self._conn.execute(
                    "UPDATE feedback SET status = ?, priority = ? WHERE id = ? AND archived = 0",
                    (status.value, priority.value, feedback_id),
                )
            else:
                self._conn.execute(
                    "UPDATE feedback SET status = ? WHERE id = ? AND archived = 0",
                    (status.value, feedback_id),
                )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()

        return self._to_record(row) if row else None

    def assign_reviewer(self, feedback_id: str, reviewer: str) -> Optional[FeedbackRecord]:
        self.initialize()
        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                "UPDATE feedback SET reviewed_by = ? WHERE id = ? AND archived = 0",
                (reviewer, feedback_id),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
        return self._to_record(row) if row else None

    def archive_feedback(self, feedback_id: str) -> bool:
        self.initialize()
        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute("UPDATE feedback SET archived = 1, status = ? WHERE id = ?", (FeedbackStatus.ARCHIVED.value, feedback_id))
            self._conn.commit()
            return cur.rowcount > 0

    def delete_feedback(self, feedback_id: str) -> bool:
        self.initialize()
        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def export_feedback(self, query: FeedbackQuery) -> List[FeedbackRecord]:
        records, _ = self.list_feedback(query)
        return records

    @staticmethod
    def _derive_priority(rating: int) -> FeedbackPriority:
        if rating <= 2:
            return FeedbackPriority.HIGH
        if rating == 3:
            return FeedbackPriority.MEDIUM
        return FeedbackPriority.LOW

    @staticmethod
    def _to_record(row: sqlite3.Row) -> FeedbackRecord:
        meta = {}
        if row["meta"]:
            try:
                meta = json.loads(row["meta"])
            except json.JSONDecodeError:
                meta = {}
        return FeedbackRecord(
            id=row["id"],
            user_id=row["user_id"],
            email=row["email"],
            rating=row["rating"],
            category=row["category"],
            message=row["message"],
            status=FeedbackStatus(row["status"]),
            priority=FeedbackPriority(row["priority"]),
            created_at=row["created_at"],
            reviewed_by=row["reviewed_by"],
            screenshot=row["screenshot"],
            meta=meta,
        )

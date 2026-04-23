# backend/storage/explain_history.py
"""
Explain History Storage
=======================

Persistence layer for explanation API responses.

Supports:
  - SQLite (default)
  - S3/MinIO (future)

Enables:
  - Replay support (GET /explain/{id})
  - Audit trail
  - Debugging
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("storage.explain_history")


# ==============================================================================
# History Entry
# ==============================================================================

@dataclass
class HistoryEntry:
    """Stored explanation entry."""
    
    trace_id: str
    request: Dict[str, Any]
    response: Dict[str, Any]
    timestamp: str
    request_hash: str = ""
    response_hash: str = ""
    
    def __post_init__(self):
        if not self.request_hash:
            self.request_hash = self._compute_hash(self.request)
        if not self.response_hash:
            self.response_hash = self._compute_hash(self.response)
    
    @staticmethod
    def _compute_hash(data: Dict[str, Any]) -> str:
        """Compute SHA256 hash of data."""
        json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(json_str.encode()).hexdigest()[:32]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return {
            "trace_id": self.trace_id,
            "request": self.request,
            "response": self.response,
            "timestamp": self.timestamp,
            "request_hash": self.request_hash,
            "response_hash": self.response_hash,
        }


# ==============================================================================
# SQLite Storage
# ==============================================================================

class ExplainHistoryStorage:
    """
    SQLite-based history storage.
    
    Schema:
      - trace_id: TEXT PRIMARY KEY
      - request: TEXT (JSON)
      - response: TEXT (JSON)
      - timestamp: TEXT (ISO format)
      - request_hash: TEXT
      - response_hash: TEXT
    
    Usage::
    
        storage = ExplainHistoryStorage()
        await storage.initialize()
        
        await storage.store(trace_id, request, response)
        entry = await storage.get(trace_id)
    """
    
    def __init__(
        self,
        db_path: Optional[Path] = None,
        max_entries: int = 100000,
    ):
        self._db_path = db_path or Path("storage/explain_history.db")
        self._max_entries = max_entries
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize database and create tables."""
        with self._lock:
            if self._initialized:
                return
            
            # Ensure directory exists
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Connect
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            
            # Create table
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS explain_history (
                    trace_id TEXT PRIMARY KEY,
                    request TEXT NOT NULL,
                    response TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    request_hash TEXT,
                    response_hash TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON explain_history(timestamp)
            """)
            
            self._conn.commit()
            self._initialized = True
            
            logger.info(f"History storage initialized: {self._db_path}")
    
    async def store(
        self,
        trace_id: str,
        request: Dict[str, Any],
        response: Dict[str, Any],
    ) -> HistoryEntry:
        """
        Store request/response pair.
        
        Args:
            trace_id: Unique trace identifier
            request: Original request
            response: Generated response
            
        Returns:
            Created HistoryEntry
        """
        if not self._initialized:
            await self.initialize()
        
        entry = HistoryEntry(
            trace_id=trace_id,
            request=request,
            response=response,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        
        with self._lock:
            try:
                self._conn.execute("""
                    INSERT OR REPLACE INTO explain_history
                    (trace_id, request, response, timestamp, request_hash, response_hash)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    entry.trace_id,
                    json.dumps(entry.request, ensure_ascii=False),
                    json.dumps(entry.response, ensure_ascii=False),
                    entry.timestamp,
                    entry.request_hash,
                    entry.response_hash,
                ))
                self._conn.commit()
                
                # Cleanup old entries if needed
                await self._cleanup_if_needed()
                
                logger.debug(f"Stored history entry: {trace_id}")
                return entry
                
            except Exception as e:
                logger.error(f"Failed to store history: {e}")
                raise
    
    async def get(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """
        Get stored response by trace_id.
        
        Args:
            trace_id: Trace identifier to look up
            
        Returns:
            Stored response dict or None
        """
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            cursor = self._conn.execute(
                "SELECT response FROM explain_history WHERE trace_id = ?",
                (trace_id,)
            )
            row = cursor.fetchone()
            
            if row:
                return json.loads(row["response"])
            return None
    
    async def get_entry(self, trace_id: str) -> Optional[HistoryEntry]:
        """
        Get full history entry by trace_id.
        
        Args:
            trace_id: Trace identifier to look up
            
        Returns:
            HistoryEntry or None
        """
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            cursor = self._conn.execute(
                """SELECT trace_id, request, response, timestamp, 
                   request_hash, response_hash 
                   FROM explain_history WHERE trace_id = ?""",
                (trace_id,)
            )
            row = cursor.fetchone()
            
            if row:
                return HistoryEntry(
                    trace_id=row["trace_id"],
                    request=json.loads(row["request"]),
                    response=json.loads(row["response"]),
                    timestamp=row["timestamp"],
                    request_hash=row["request_hash"],
                    response_hash=row["response_hash"],
                )
            return None
    
    async def list_recent(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> List[HistoryEntry]:
        """
        List recent history entries.
        
        Args:
            limit: Max entries to return
            offset: Offset for pagination
            
        Returns:
            List of HistoryEntry
        """
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            cursor = self._conn.execute(
                """SELECT trace_id, request, response, timestamp, 
                   request_hash, response_hash 
                   FROM explain_history 
                   ORDER BY timestamp DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset)
            )
            
            entries = []
            for row in cursor.fetchall():
                entries.append(HistoryEntry(
                    trace_id=row["trace_id"],
                    request=json.loads(row["request"]),
                    response=json.loads(row["response"]),
                    timestamp=row["timestamp"],
                    request_hash=row["request_hash"],
                    response_hash=row["response_hash"],
                ))
            return entries
    
    async def count(self) -> int:
        """Get total entry count."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            cursor = self._conn.execute(
                "SELECT COUNT(*) as count FROM explain_history"
            )
            return cursor.fetchone()["count"]
    
    async def delete(self, trace_id: str) -> bool:
        """Delete entry by trace_id."""
        if not self._initialized:
            await self.initialize()
        
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM explain_history WHERE trace_id = ?",
                (trace_id,)
            )
            self._conn.commit()
            return cursor.rowcount > 0
    
    async def _cleanup_if_needed(self) -> None:
        """Remove old entries if over max limit."""
        count = await self.count()
        
        if count > self._max_entries:
            # Delete oldest 10%
            delete_count = int(self._max_entries * 0.1)
            
            self._conn.execute("""
                DELETE FROM explain_history 
                WHERE trace_id IN (
                    SELECT trace_id FROM explain_history 
                    ORDER BY timestamp ASC 
                    LIMIT ?
                )
            """, (delete_count,))
            self._conn.commit()
            
            logger.info(f"Cleaned up {delete_count} old history entries")
    
    async def close(self) -> None:
        """Close database connection."""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None
                self._initialized = False


# ==============================================================================
# S3/MinIO Storage (Future)
# ==============================================================================

class S3HistoryStorage:
    """
    S3/MinIO-based history storage.
    
    STUB: Not yet implemented.
    
    Future features:
      - Partitioned by date
      - Compressed JSON
      - Lifecycle policies
    """
    
    def __init__(
        self,
        bucket: str = "explain-history",
        endpoint: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ):
        self._bucket = bucket
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        raise NotImplementedError("S3 storage not yet implemented")


# ==============================================================================
# Singleton
# ==============================================================================

_history_storage: Optional[ExplainHistoryStorage] = None


def get_history_storage(
    db_path: Optional[Path] = None,
) -> ExplainHistoryStorage:
    """Get or create singleton history storage."""
    global _history_storage
    if _history_storage is None:
        _history_storage = ExplainHistoryStorage(db_path=db_path)
    return _history_storage

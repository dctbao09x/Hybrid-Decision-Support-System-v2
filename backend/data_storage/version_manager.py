"""
Version Manager - Handles data versioning and history tracking

Maintains version metadata and enables point-in-time data access
"""

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import json
import logging
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class VersionInfo:
    """Metadata for a data version"""
    version_id: str  # YYYYMM format
    created_at: str  # ISO timestamp
    data_path: str  # Path to versioned data
    record_count: int = 0
    source_count: int = 0
    status: str = "active"  # active, archived, deleted
    data_quality: float = 0.0  # 0-100
    processing_time_seconds: float = 0.0
    notes: str = ""
    parent_version: Optional[str] = None
    changelog: List[str] = None
    
    def __post_init__(self):
        if self.changelog is None:
            self.changelog = []


class VersionManager:
    """
    Manages data versioning and retention policies
    
    Creates monthly versions with full history tracking
    """
    
    def __init__(self, storage_path: str):
        """
        Initialize version manager
        
        Args:
            storage_path: Base path for data storage
        """
        self.storage_path = Path(storage_path)
        self.db_path = self.storage_path / "processed" / "versions.db"
        
        # Create database if needed
        self._init_database()
    
    def _init_database(self):
        """Initialize SQLite database for version tracking"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Create versions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS versions (
                    version_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    data_path TEXT NOT NULL,
                    record_count INTEGER,
                    source_count INTEGER,
                    status TEXT,
                    data_quality REAL,
                    processing_time_seconds REAL,
                    notes TEXT,
                    parent_version TEXT,
                    changelog TEXT,
                    created_timestamp REAL DEFAULT (julianday('now'))
                )
            """)
            
            # Create index for faster queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_version_created 
                ON versions(created_at DESC)
            """)
            
            conn.commit()
        
        logger.info(f"Version database initialized at {self.db_path}")
    
    def create_version(
        self,
        data_path: str,
        metadata: Dict[str, Any] = None
    ) -> str:
        """
        Create a new data version
        
        Args:
            data_path: Path containing the version data
            metadata: Additional metadata
            
        Returns:
            Version ID (YYYYMM format)
        """
        # Generate version ID
        version_id = datetime.now().strftime("%Y%m")
        
        # Check if version already exists for this month
        existing = self.get_version(version_id)
        if existing:
            logger.warning(f"Version {version_id} already exists, overwriting...")
            self.delete_version(version_id)
        
        # Create version info
        parent_version = self.get_latest_version()
        
        version_info = VersionInfo(
            version_id=version_id,
            created_at=datetime.now().isoformat(),
            data_path=data_path,
            parent_version=parent_version.version_id if parent_version else None,
            notes=metadata.get("notes", "") if metadata else "",
        )
        
        # Save to database
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO versions (
                    version_id, created_at, data_path, status,
                    record_count, source_count, data_quality,
                    processing_time_seconds, notes, parent_version,
                    changelog
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                version_info.version_id,
                version_info.created_at,
                version_info.data_path,
                "active",
                0,
                0,
                0.0,
                0.0,
                version_info.notes,
                version_info.parent_version,
                json.dumps(version_info.changelog),
            ))
            
            conn.commit()
        
        logger.info(f"Version created: {version_id}")
        return version_id
    
    def get_version(self, version_id: str) -> Optional[VersionInfo]:
        """
        Retrieve version information
        
        Args:
            version_id: Version identifier (YYYYMM format)
            
        Returns:
            VersionInfo or None if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    version_id, created_at, data_path, record_count,
                    source_count, status, data_quality, processing_time_seconds,
                    notes, parent_version, changelog
                FROM versions
                WHERE version_id = ?
            """, (version_id,))
            
            row = cursor.fetchone()
        
        if not row:
            return None
        
        changelog = json.loads(row[10]) if row[10] else []
        
        return VersionInfo(
            version_id=row[0],
            created_at=row[1],
            data_path=row[2],
            record_count=row[3],
            source_count=row[4],
            status=row[5],
            data_quality=row[6],
            processing_time_seconds=row[7],
            notes=row[8],
            parent_version=row[9],
            changelog=changelog,
        )
    
    def get_latest_version(self) -> Optional[VersionInfo]:
        """Get the most recent version"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    version_id, created_at, data_path, record_count,
                    source_count, status, data_quality, processing_time_seconds,
                    notes, parent_version, changelog
                FROM versions
                WHERE status = 'active'
                ORDER BY version_id DESC
                LIMIT 1
            """)
            
            row = cursor.fetchone()
        
        if not row:
            return None
        
        changelog = json.loads(row[10]) if row[10] else []
        
        return VersionInfo(
            version_id=row[0],
            created_at=row[1],
            data_path=row[2],
            record_count=row[3],
            source_count=row[4],
            status=row[5],
            data_quality=row[6],
            processing_time_seconds=row[7],
            notes=row[8],
            parent_version=row[9],
            changelog=changelog,
        )
    
    def list_versions(self, limit: int = 24) -> List[VersionInfo]:
        """
        List recent versions
        
        Args:
            limit: Max versions to return (default: 24 months)
            
        Returns:
            List of VersionInfo sorted by date descending
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    version_id, created_at, data_path, record_count,
                    source_count, status, data_quality, processing_time_seconds,
                    notes, parent_version, changelog
                FROM versions
                ORDER BY version_id DESC
                LIMIT ?
            """, (limit,))
            
            rows = cursor.fetchall()
        
        versions = []
        for row in rows:
            changelog = json.loads(row[10]) if row[10] else []
            versions.append(VersionInfo(
                version_id=row[0],
                created_at=row[1],
                data_path=row[2],
                record_count=row[3],
                source_count=row[4],
                status=row[5],
                data_quality=row[6],
                processing_time_seconds=row[7],
                notes=row[8],
                parent_version=row[9],
                changelog=changelog,
            ))
        
        return versions
    
    def update_version_status(self, version_id: str, status: str):
        """
        Update version status (active, archived, deleted)
        
        Args:
            version_id: Version to update
            status: New status
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE versions
                SET status = ?
                WHERE version_id = ?
            """, (status, version_id))
            
            conn.commit()
        
        logger.info(f"Version {version_id} status updated to {status}")
    
    def add_changelog_entry(self, version_id: str, entry: str):
        """
        Add changelog entry to version
        
        Args:
            version_id: Version to update
            entry: Changelog entry text
        """
        version = self.get_version(version_id)
        if not version:
            logger.error(f"Version {version_id} not found")
            return
        
        version.changelog.append({
            "timestamp": datetime.now().isoformat(),
            "message": entry,
        })
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE versions
                SET changelog = ?
                WHERE version_id = ?
            """, (json.dumps(version.changelog), version_id))
            
            conn.commit()
    
    def delete_version(self, version_id: str):
        """
        Delete a version (soft delete - marks as deleted)
        
        Args:
            version_id: Version to delete
        """
        self.update_version_status(version_id, "deleted")
        logger.info(f"Version {version_id} marked as deleted")
    
    def get_retention_policy_violations(self) -> List[str]:
        """
        Check for versions violating retention policy
        
        Returns:
            List of version IDs that should be archived/deleted
        """
        violations = []
        versions = self.list_versions(limit=999)
        
        for i, version in enumerate(versions):
            created = datetime.fromisoformat(version.created_at)
            age_days = (datetime.now() - created).days
            
            # If version is older than hot retention (12 months), archive it
            if age_days > 365 and version.status == "active":
                violations.append(version.version_id)
        
        return violations
    
    def export_version_info(self, version_id: str) -> Dict[str, Any]:
        """
        Export version information as dictionary
        
        Args:
            version_id: Version to export
            
        Returns:
            Dictionary with version metadata
        """
        version = self.get_version(version_id)
        if not version:
            return {}
        
        return asdict(version)

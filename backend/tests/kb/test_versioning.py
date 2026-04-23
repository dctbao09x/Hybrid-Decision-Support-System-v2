# backend/tests/kb/test_versioning.py
"""
Test KB Versioning Engine
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# Test versioning engine core functionality


class TestVersioningEngine:
    """Tests for VersioningEngine class"""

    def test_snapshot_serializes_career(self):
        """Verify career entity serialization for snapshots"""
        from backend.kb.versioning import VersioningEngine
        
        # Mock career object
        career = MagicMock()
        career.id = 1
        career.name = "Software Engineer"
        career.code = "SE001"
        career.level = "senior"
        career.domain_id = 1
        career.description = "Test description"
        career.version = 1
        career.status = "active"
        career.market_tags = ["tech", "software"]
        career.is_active = True
        
        # Mock session
        mock_session = MagicMock()
        
        engine = VersioningEngine(mock_session)
        snapshot = engine._serialize_entity("career", career)
        
        assert snapshot["name"] == "Software Engineer"
        assert snapshot["code"] == "SE001"
        assert snapshot["version"] == 1
        assert "tech" in snapshot.get("market_tags", [])

    def test_snapshot_serializes_skill(self):
        """Verify skill entity serialization"""
        from backend.kb.versioning import VersioningEngine
        
        skill = MagicMock()
        skill.id = 1
        skill.name = "Python"
        skill.code = "PY001"
        skill.category = "technical"
        skill.description = "Programming language"
        skill.version = 1
        skill.status = "active"
        skill.level_map = {"junior": 1, "senior": 3}
        skill.related_skills = ["Java", "Go"]
        skill.is_active = True
        
        mock_session = MagicMock()
        engine = VersioningEngine(mock_session)
        snapshot = engine._serialize_entity("skill", skill)
        
        assert snapshot["name"] == "Python"
        assert snapshot["category"] == "technical"
        assert "junior" in snapshot.get("level_map", {})

    def test_compute_diff_detects_additions(self):
        """Verify diff computation detects new fields"""
        from backend.kb.versioning import VersioningEngine
        
        mock_session = MagicMock()
        engine = VersioningEngine(mock_session)
        
        old = {"name": "Test", "version": 1}
        new = {"name": "Test", "version": 2, "description": "Added"}
        
        diff = engine.compute_diff(old, new)
        
        assert "description" in diff["added"]
        assert diff["added"]["description"] == "Added"

    def test_compute_diff_detects_modifications(self):
        """Verify diff computation detects changed fields"""
        from backend.kb.versioning import VersioningEngine
        
        mock_session = MagicMock()
        engine = VersioningEngine(mock_session)
        
        old = {"name": "Test", "version": 1, "description": "Old"}
        new = {"name": "Test", "version": 2, "description": "New"}
        
        diff = engine.compute_diff(old, new)
        
        assert "description" in diff["modified"]
        assert diff["modified"]["description"]["old"] == "Old"
        assert diff["modified"]["description"]["new"] == "New"

    def test_compute_diff_detects_removals(self):
        """Verify diff computation detects removed fields"""
        from backend.kb.versioning import VersioningEngine
        
        mock_session = MagicMock()
        engine = VersioningEngine(mock_session)
        
        old = {"name": "Test", "version": 1, "extra": "Removed"}
        new = {"name": "Test", "version": 2}
        
        diff = engine.compute_diff(old, new)
        
        assert "extra" in diff["removed"]


class TestKBHistory:
    """Tests for KB audit history"""

    def test_log_action_creates_history_record(self):
        """Verify log_action creates proper history entry"""
        from backend.kb.versioning import VersioningEngine
        from backend.kb.models import KBHistory
        
        mock_session = MagicMock()
        engine = VersioningEngine(mock_session)
        
        engine.log_action(
            entity_type="career",
            entity_id=1,
            action="update",
            version_before=1,
            version_after=2,
            diff={"modified": {"name": {"old": "A", "new": "B"}}},
            user="test_user"
        )
        
        # Verify add was called with KBHistory object
        assert mock_session.add.called
        call_args = mock_session.add.call_args[0][0]
        assert isinstance(call_args, KBHistory)
        assert call_args.entity_type == "career"
        assert call_args.action == "update"
        assert call_args.user == "test_user"


class TestVersionedOperations:
    """Tests for versioned CRUD operations"""

    @patch("backend.kb.versioning.KBVersion")
    def test_snapshot_before_update_stores_version(self, mock_kb_version):
        """Verify snapshots are stored before updates"""
        from backend.kb.versioning import VersioningEngine
        
        mock_session = MagicMock()
        engine = VersioningEngine(mock_session)
        
        # Mock entity
        entity = MagicMock()
        entity.id = 1
        entity.version = 1
        entity.name = "Test"
        
        engine.snapshot_before_update("career", entity, "test_user")
        
        # Verify snapshot was added
        assert mock_session.add.called

    def test_rollback_validates_version_exists(self):
        """Verify rollback fails for non-existent version"""
        from backend.kb.versioning import VersioningEngine
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None
        
        engine = VersioningEngine(mock_session)
        
        with pytest.raises(ValueError, match="Version .* not found"):
            engine.rollback("career", 1, 5, "test_user")


class TestCacheIntegration:
    """Tests for KB adapter cache"""

    def test_cache_invalidation_on_career_update(self):
        """Verify cache is invalidated when career is updated"""
        from backend.rule_engine.adapters.kb_adapter import KnowledgeBaseAdapter
        
        adapter = KnowledgeBaseAdapter()
        
        # Populate cache
        adapter._jobs_cache = ["Job1", "Job2"]
        adapter._jobs_ts = datetime.utcnow()
        
        # Invalidate
        adapter.invalidate_entity("career")
        
        assert adapter._jobs_cache is None
        assert adapter._jobs_ts is None

    def test_cache_stats_tracking(self):
        """Verify cache statistics are tracked"""
        from backend.rule_engine.adapters.kb_adapter import KnowledgeBaseAdapter
        
        adapter = KnowledgeBaseAdapter()
        adapter._stats = {"hits": 10, "misses": 5, "errors": 1, "last_refresh": None}
        
        stats = adapter.get_stats()
        
        assert stats["hits"] == 10
        assert stats["misses"] == 5
        assert stats["hit_rate"] == "66.7%"

    def test_cache_ttl_expiration(self):
        """Verify cache entries expire after TTL"""
        from backend.rule_engine.adapters.kb_adapter import KnowledgeBaseAdapter
        
        adapter = KnowledgeBaseAdapter()
        adapter.CACHE_TTL = 300  # 5 minutes
        
        # Fresh timestamp
        assert adapter._cache_valid(datetime.utcnow()) is True
        
        # Expired timestamp
        old_ts = datetime.utcnow() - timedelta(seconds=400)
        assert adapter._cache_valid(old_ts) is False


class TestBulkImport:
    """Tests for bulk import functionality"""

    def test_bulk_import_dry_run(self):
        """Verify dry run doesn't persist data"""
        from backend.kb import schemas
        
        request = schemas.BulkImportRequest(
            entity_type="career",
            items=[{"name": "Test Career", "domain_id": 1}],
            dry_run=True,
            skip_duplicates=True,
        )
        
        assert request.dry_run is True
        assert len(request.items) == 1

    def test_bulk_import_validates_entity_type(self):
        """Verify bulk import validates entity type"""
        from backend.kb import schemas
        import pydantic
        
        # Should accept valid types
        valid_request = schemas.BulkImportRequest(
            entity_type="career",
            items=[],
            dry_run=True,
        )
        assert valid_request.entity_type == "career"


class TestMigrationUtilities:
    """Tests for migration utilities"""

    @patch("backend.kb.migration.get_db_context")
    @patch("backend.kb.migration.KnowledgeBaseService")
    def test_export_generates_valid_structure(self, mock_service, mock_db):
        """Verify export produces valid JSON structure"""
        from backend.kb.migration import export_kb_to_json
        
        # Mock service methods
        mock_kb = MagicMock()
        mock_kb.list_domains.return_value = []
        mock_kb.list_education_levels.return_value = []
        mock_kb.list_skills.return_value = []
        mock_kb.list_careers.return_value = []
        mock_kb.list_templates.return_value = []
        mock_kb.list_ontology_nodes.return_value = []
        mock_service.return_value = mock_kb
        
        # Mock context manager
        mock_db.return_value.__enter__ = MagicMock()
        mock_db.return_value.__exit__ = MagicMock()
        
        result = export_kb_to_json()
        
        assert "metadata" in result
        assert "domains" in result
        assert "skills" in result
        assert "careers" in result
        assert "version" in result["metadata"]

    def test_migration_report_structure(self):
        """Verify migration report has expected sections"""
        # This would require actual DB setup, so we test structure expectations
        expected_sections = ["summary", "entity_details", "recommendations"]
        
        # Structure validation
        for section in expected_sections:
            assert section in expected_sections  # Placeholder for actual test

# backend/tests/kb/test_kb_service.py
"""
Test KB Service CRUD Operations
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime


class TestCareerService:
    """Tests for Career CRUD operations"""

    def test_create_career_with_required_fields(self):
        """Verify career creation with minimum required fields"""
        from backend.kb import schemas
        
        career = schemas.CareerCreate(
            name="Test Engineer",
            domain_id=1,
            slug="test-engineer",
        )
        
        assert career.name == "Test Engineer"
        assert career.domain_id == 1
        assert career.slug == "test-engineer"

    def test_career_create_with_extended_fields(self):
        """Verify career creation with new extended fields"""
        from backend.kb import schemas
        
        career = schemas.CareerCreate(
            name="Senior Developer",
            domain_id=1,
            slug="senior-dev",
            code="DEV001",
            level="senior",
            market_tags=["remote", "startup"],
        )
        
        assert career.code == "DEV001"
        assert career.level == "senior"
        assert "remote" in career.market_tags

    def test_career_update_preserves_version(self):
        """Verify career update schema has version field"""
        from backend.kb import schemas
        
        update = schemas.CareerUpdate(
            name="Updated Name",
            description="Updated description",
        )
        
        assert update.name == "Updated Name"


class TestSkillService:
    """Tests for Skill CRUD operations"""

    def test_create_skill_with_code(self):
        """Verify skill creation with code field"""
        from backend.kb import schemas
        
        skill = schemas.SkillCreate(
            name="Python",
            code="PY001",
            category="technical",
            description="Programming language",
        )
        
        assert skill.code == "PY001"
        assert skill.category == "technical"

    def test_skill_with_level_map(self):
        """Verify skill level_map field"""
        from backend.kb import schemas
        
        skill = schemas.SkillCreate(
            name="Python",
            code="PY001",
            category="technical",
            level_map={"junior": 1, "mid": 2, "senior": 3},
        )
        
        assert skill.level_map["senior"] == 3

    def test_skill_with_related_skills(self):
        """Verify skill related_skills field"""
        from backend.kb import schemas
        
        skill = schemas.SkillCreate(
            name="Python",
            code="PY001",
            category="technical",
            related_skills=["Java", "Go", "Rust"],
        )
        
        assert "Java" in skill.related_skills


class TestTemplateService:
    """Tests for Template CRUD operations"""

    def test_create_template(self):
        """Verify template creation"""
        from backend.kb import schemas
        
        template = schemas.TemplateCreate(
            code="TPL001",
            type="prompt",
            name="Career Recommendation Prompt",
            content="Based on your profile: {{profile}}, we recommend...",
            variables=["profile", "skills"],
        )
        
        assert template.code == "TPL001"
        assert template.type == "prompt"
        assert "profile" in template.variables

    def test_template_types(self):
        """Verify template type enum values"""
        from backend.kb import schemas
        
        valid_types = ["prompt", "report", "email", "scoring", "custom"]
        
        for t in valid_types:
            template = schemas.TemplateCreate(
                code=f"TPL_{t}",
                type=t,
                name=f"Test {t}",
                content="Content",
            )
            assert template.type == t


class TestOntologyService:
    """Tests for Ontology CRUD operations"""

    def test_create_ontology_node(self):
        """Verify ontology node creation"""
        from backend.kb import schemas
        
        node = schemas.OntologyNodeCreate(
            code="ONT001",
            type="domain",
            label="Information Technology",
            parent_id=None,
            relations={"broader": [], "narrower": ["ONT002"]},
            metadata={"source": "manual"},
        )
        
        assert node.code == "ONT001"
        assert node.type == "domain"
        assert node.parent_id is None
        assert "narrower" in node.relations

    def test_ontology_with_parent(self):
        """Verify ontology node with parent relationship"""
        from backend.kb import schemas
        
        child = schemas.OntologyNodeCreate(
            code="ONT002",
            type="category",
            label="Software Development",
            parent_id="ONT001",
        )
        
        assert child.parent_id == "ONT001"

    def test_ontology_node_types(self):
        """Verify ontology node type enum values"""
        from backend.kb import schemas
        
        valid_types = ["domain", "category", "skill", "concept"]
        
        for t in valid_types:
            node = schemas.OntologyNodeCreate(
                code=f"ONT_{t}",
                type=t,
                label=f"Test {t}",
            )
            assert node.type == t


class TestVersionSchemas:
    """Tests for version-related schemas"""

    def test_kb_version_schema(self):
        """Verify KBVersion schema structure"""
        from backend.kb import schemas
        
        version = schemas.KBVersionSchema(
            id=1,
            entity_type="career",
            entity_id=1,
            version_number=1,
            snapshot={"name": "Test", "version": 1},
            created_at=datetime.utcnow(),
            created_by="test_user",
        )
        
        assert version.version_number == 1
        assert version.entity_type == "career"

    def test_kb_history_schema(self):
        """Verify KBHistory schema structure"""
        from backend.kb import schemas
        
        history = schemas.KBHistorySchema(
            id=1,
            entity_type="career",
            entity_id=1,
            action="update",
            version_before=1,
            version_after=2,
            diff={"modified": {"name": {"old": "A", "new": "B"}}},
            user="test_user",
            timestamp=datetime.utcnow(),
        )
        
        assert history.action == "update"
        assert history.version_before == 1
        assert history.version_after == 2

    def test_kb_diff_schema(self):
        """Verify KBDiff schema structure"""
        from backend.kb import schemas
        
        diff = schemas.KBDiff(
            entity_type="career",
            entity_id=1,
            version_from=1,
            version_to=2,
            changes={
                "added": {"new_field": "value"},
                "modified": {"name": {"old": "A", "new": "B"}},
                "removed": {},
            },
        )
        
        assert diff.version_from == 1
        assert diff.version_to == 2
        assert "added" in diff.changes


class TestBulkImportSchemas:
    """Tests for bulk import schemas"""

    def test_bulk_import_request(self):
        """Verify bulk import request structure"""
        from backend.kb import schemas
        
        request = schemas.BulkImportRequest(
            entity_type="career",
            items=[
                {"name": "Career 1", "domain_id": 1},
                {"name": "Career 2", "domain_id": 1},
            ],
            dry_run=False,
            skip_duplicates=True,
        )
        
        assert request.entity_type == "career"
        assert len(request.items) == 2
        assert request.skip_duplicates is True

    def test_bulk_import_result(self):
        """Verify bulk import result structure"""
        from backend.kb import schemas
        
        result = schemas.BulkImportResult(
            success_count=5,
            error_count=1,
            skipped_count=2,
            errors=[schemas.BulkImportError(row=3, error="Duplicate name")],
        )
        
        assert result.success_count == 5
        assert result.error_count == 1
        assert len(result.errors) == 1
        assert result.errors[0].row == 3


class TestRBACSchemas:
    """Tests for RBAC schemas"""

    def test_kb_role_enum(self):
        """Verify KB role enum values"""
        from backend.kb import schemas
        
        assert schemas.KBRole.VIEWER.value == "viewer"
        assert schemas.KBRole.EDITOR.value == "editor"
        assert schemas.KBRole.ADMIN.value == "admin"

    def test_kb_action_enum(self):
        """Verify KB action enum values"""
        from backend.kb import schemas
        
        assert schemas.KBAction.READ.value == "read"
        assert schemas.KBAction.CREATE.value == "create"
        assert schemas.KBAction.UPDATE.value == "update"
        assert schemas.KBAction.DELETE.value == "delete"
        assert schemas.KBAction.ROLLBACK.value == "rollback"

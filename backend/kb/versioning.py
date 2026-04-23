# backend/kb/versioning.py
"""
Versioning Engine for Knowledge Base.
  - clone-on-update: snapshot old state before applying changes.
  - soft-delete: mark status='deleted', never hard-delete.
  - full audit trail via kb_history.
  - diff computation between any two versions.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from . import models
from .repository import transactional


# ==========================================
# ENTITY SERIALIZERS
# ==========================================

def _serialize_career(career: models.Career) -> Dict[str, Any]:
    return {
        "id": career.id,
        "code": career.code,
        "name": career.name,
        "slug": career.slug,
        "domain_id": career.domain_id,
        "description": career.description,
        "icon": career.icon,
        "level": career.level,
        "education_min": career.education_min,
        "ai_relevance": career.ai_relevance,
        "competition": career.competition,
        "growth_rate": career.growth_rate,
        "salary_range_min": career.salary_range_min,
        "salary_range_max": career.salary_range_max,
        "market_tags": career.market_tags or [],
        "is_active": career.is_active,
        "version": career.version,
        "status": career.status,
    }


def _serialize_skill(skill: models.Skill) -> Dict[str, Any]:
    return {
        "id": skill.id,
        "code": skill.code,
        "name": skill.name,
        "slug": skill.slug,
        "category": skill.category.value if skill.category else "technical",
        "description": skill.description,
        "level_map": skill.level_map or {},
        "related_skills": skill.related_skills or [],
        "is_active": skill.is_active,
        "version": skill.version,
        "status": skill.status,
    }


def _serialize_template(tmpl: models.Template) -> Dict[str, Any]:
    return {
        "id": tmpl.id,
        "code": tmpl.code,
        "name": tmpl.name,
        "type": tmpl.type.value if tmpl.type else "custom",
        "content": tmpl.content,
        "variables": tmpl.variables or [],
        "is_active": tmpl.is_active,
        "version": tmpl.version,
        "status": tmpl.status,
    }


def _serialize_ontology(node: models.OntologyNode) -> Dict[str, Any]:
    return {
        "node_id": node.node_id,
        "code": node.code,
        "type": node.type.value if node.type else "concept",
        "label": node.label,
        "parent_id": node.parent_id,
        "relations": node.relations or [],
        "metadata": node.metadata_ or {},
        "is_active": node.is_active,
        "version": node.version,
        "status": node.status,
    }


SERIALIZERS = {
    "career": _serialize_career,
    "skill": _serialize_skill,
    "template": _serialize_template,
    "ontology": _serialize_ontology,
}

ENTITY_MODELS = {
    "career": (models.Career, "id"),
    "skill": (models.Skill, "id"),
    "template": (models.Template, "id"),
    "ontology": (models.OntologyNode, "node_id"),
}


# ==========================================
# VERSIONING ENGINE
# ==========================================

class VersioningEngine:
    """
    Central versioning engine for all KB entities.
    """

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------
    # SNAPSHOT (clone old state before update)
    # ------------------------------------------

    def snapshot_before_update(
        self,
        entity_type: str,
        entity: Any,
        user: str = "system"
    ) -> models.KBVersion:
        """
        Clone current entity state into kb_versions BEFORE applying changes.
        Call this before any update/delete.
        """
        serializer = SERIALIZERS.get(entity_type)
        if not serializer:
            raise ValueError(f"Unknown entity type: {entity_type}")

        snapshot = serializer(entity)
        version_number = getattr(entity, "version", 1)

        version_record = models.KBVersion(
            entity_type=entity_type,
            entity_id=self._get_entity_id(entity_type, entity),
            version_number=version_number,
            snapshot=snapshot,
            created_by=user,
        )

        self.db.add(version_record)
        self.db.flush()

        return version_record

    # ------------------------------------------
    # LOG HISTORY
    # ------------------------------------------

    def log_action(
        self,
        entity_type: str,
        entity_id: int,
        action: str,
        version_before: Optional[int] = None,
        version_after: Optional[int] = None,
        diff: Optional[Dict[str, Any]] = None,
        user: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> models.KBHistory:
        """
        Log an action to kb_history.
        """
        record = models.KBHistory(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            version_before=version_before,
            version_after=version_after,
            diff=diff,
            user=user,
            metadata_=metadata or {},
        )

        self.db.add(record)
        self.db.flush()

        return record

    # ------------------------------------------
    # VERSIONED UPDATE
    # ------------------------------------------

    def versioned_update(
        self,
        entity_type: str,
        entity: Any,
        changes: Dict[str, Any],
        user: str = "system"
    ) -> int:
        """
        1. Snapshot old state
        2. Apply changes
        3. Bump version
        4. Log history
        Returns new version number.
        """
        old_version = getattr(entity, "version", 1) or 1
        entity_id = self._get_entity_id(entity_type, entity)

        # 1. Snapshot
        self.snapshot_before_update(entity_type, entity, user)

        # 2. Compute diff
        serializer = SERIALIZERS.get(entity_type)
        old_snapshot = serializer(entity) if serializer else {}
        diff = {}
        for field, new_val in changes.items():
            old_val = old_snapshot.get(field)
            if old_val != new_val:
                diff[field] = {"old": old_val, "new": new_val}

        # 3. Apply changes
        for field, value in changes.items():
            if hasattr(entity, field):
                setattr(entity, field, value)

        # 4. Bump version
        new_version = old_version + 1
        entity.version = new_version

        # 5. Log history
        self.log_action(
            entity_type=entity_type,
            entity_id=entity_id,
            action="update",
            version_before=old_version,
            version_after=new_version,
            diff=diff,
            user=user,
        )

        return new_version

    # ------------------------------------------
    # VERSIONED DELETE (soft)
    # ------------------------------------------

    def versioned_delete(
        self,
        entity_type: str,
        entity: Any,
        user: str = "system"
    ) -> None:
        """
        Soft delete: snapshot → mark as deleted → log.
        """
        old_version = getattr(entity, "version", 1) or 1
        entity_id = self._get_entity_id(entity_type, entity)

        # Snapshot before delete
        self.snapshot_before_update(entity_type, entity, user)

        # Soft delete
        entity.is_active = False
        if hasattr(entity, "status"):
            entity.status = "deleted"
        entity.version = old_version + 1

        # Log
        self.log_action(
            entity_type=entity_type,
            entity_id=entity_id,
            action="delete",
            version_before=old_version,
            version_after=old_version + 1,
            user=user,
        )

    # ------------------------------------------
    # VERSIONED CREATE
    # ------------------------------------------

    def log_create(
        self,
        entity_type: str,
        entity: Any,
        user: str = "system"
    ) -> None:
        """
        Log creation in history (no snapshot needed for v1).
        """
        entity_id = self._get_entity_id(entity_type, entity)

        self.log_action(
            entity_type=entity_type,
            entity_id=entity_id,
            action="create",
            version_before=None,
            version_after=1,
            user=user,
        )

    # ------------------------------------------
    # ROLLBACK
    # ------------------------------------------

    def rollback(
        self,
        entity_type: str,
        entity_id: int,
        target_version: int,
        user: str = "system"
    ) -> Any:
        """
        Rollback entity to a specific version.
        1. Find snapshot at target_version
        2. Snapshot current state
        3. Apply snapshot data
        4. Log rollback
        """
        model_cls, pk_field = ENTITY_MODELS.get(entity_type, (None, None))
        if not model_cls:
            raise ValueError(f"Unknown entity type: {entity_type}")

        # Find entity
        entity = self.db.query(model_cls).filter(
            getattr(model_cls, pk_field) == entity_id
        ).first()

        if not entity:
            raise ValueError(f"{entity_type} {entity_id} not found")

        # Find target version snapshot
        version_record = self.db.query(models.KBVersion).filter(
            models.KBVersion.entity_type == entity_type,
            models.KBVersion.entity_id == entity_id,
            models.KBVersion.version_number == target_version,
        ).first()

        if not version_record:
            raise ValueError(
                f"Version {target_version} not found for "
                f"{entity_type}:{entity_id}"
            )

        old_version = getattr(entity, "version", 1) or 1

        # Snapshot current state before rollback
        self.snapshot_before_update(entity_type, entity, user)

        # Apply snapshot data
        snapshot = version_record.snapshot
        skip_fields = {pk_field, "id", "node_id", "created_at", "updated_at"}

        for field, value in snapshot.items():
            if field in skip_fields:
                continue
            if hasattr(entity, field):
                setattr(entity, field, value)

        # Bump version
        new_version = old_version + 1
        entity.version = new_version
        entity.status = "active"
        entity.is_active = True

        # Log rollback
        self.log_action(
            entity_type=entity_type,
            entity_id=entity_id,
            action="rollback",
            version_before=old_version,
            version_after=new_version,
            diff={"rollback_to": target_version},
            user=user,
        )

        return entity

    # ------------------------------------------
    # VERSION QUERIES
    # ------------------------------------------

    def get_versions(
        self,
        entity_type: str,
        entity_id: int
    ) -> List[models.KBVersion]:
        """Get all version snapshots for an entity."""
        return (
            self.db.query(models.KBVersion)
            .filter(
                models.KBVersion.entity_type == entity_type,
                models.KBVersion.entity_id == entity_id,
            )
            .order_by(models.KBVersion.version_number.desc())
            .all()
        )

    def get_history(
        self,
        entity_type: str,
        entity_id: int
    ) -> List[models.KBHistory]:
        """Get full audit history for an entity."""
        return (
            self.db.query(models.KBHistory)
            .filter(
                models.KBHistory.entity_type == entity_type,
                models.KBHistory.entity_id == entity_id,
            )
            .order_by(models.KBHistory.timestamp.desc())
            .all()
        )

    def compute_diff(
        self,
        entity_type: str,
        entity_id: int,
        version_from: int,
        version_to: int
    ) -> Dict[str, Any]:
        """Compute diff between two versions."""
        v_from = self.db.query(models.KBVersion).filter(
            models.KBVersion.entity_type == entity_type,
            models.KBVersion.entity_id == entity_id,
            models.KBVersion.version_number == version_from,
        ).first()

        v_to = self.db.query(models.KBVersion).filter(
            models.KBVersion.entity_type == entity_type,
            models.KBVersion.entity_id == entity_id,
            models.KBVersion.version_number == version_to,
        ).first()

        if not v_from or not v_to:
            raise ValueError("Version not found")

        snap_from = v_from.snapshot or {}
        snap_to = v_to.snapshot or {}

        changes = {}
        all_keys = set(snap_from.keys()) | set(snap_to.keys())

        for key in all_keys:
            old = snap_from.get(key)
            new = snap_to.get(key)
            if old != new:
                changes[key] = {"old": old, "new": new}

        return changes

    # ------------------------------------------
    # HELPERS
    # ------------------------------------------

    @staticmethod
    def _get_entity_id(entity_type: str, entity: Any) -> int:
        _, pk_field = ENTITY_MODELS.get(entity_type, (None, "id"))
        return getattr(entity, pk_field or "id")

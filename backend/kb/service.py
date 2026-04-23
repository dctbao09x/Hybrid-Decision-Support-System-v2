"""
Service layer for Knowledge Base (Business Logic Layer)
"""

from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session

from . import models, schemas, repository
from .versioning import VersioningEngine
from backend.taxonomy.facade import taxonomy


class KnowledgeBaseService:
    """
    Main service for Knowledge Base operations
    (Orchestrates Repositories + Business Rules)
    """

    def __init__(self, db: Session):
        self.db = db
        self.versioning = VersioningEngine(db)

    # =====================================================
    # INTERNAL HELPERS
    # =====================================================

    def _require_domain(self, domain_id: int) -> models.Domain:
        domain = repository.DomainRepository.get_by_id(self.db, domain_id)

        if not domain:
            raise ValueError("Domain not found")

        return domain

    def _require_career(self, career_id: int) -> models.Career:
        career = repository.CareerRepository.get_by_id(self.db, career_id)

        if not career:
            raise ValueError("Career not found")

        return career

    def _require_skill(self, skill_id: int) -> models.Skill:
        skill = repository.SkillRepository.get_by_id(self.db, skill_id)

        if not skill:
            raise ValueError("Skill not found")

        return skill

    # =====================================================
    # DOMAIN
    # =====================================================

    def create_domain(
        self,
        domain: schemas.DomainCreate
    ) -> models.Domain:

        exists = repository.DomainRepository.get_by_name(
            self.db,
            domain.name
        )

        if exists:
            raise ValueError("Domain already exists")

        return repository.DomainRepository.create(self.db, domain)


    def get_domain(self, domain_id: int) -> Optional[models.Domain]:

        return repository.DomainRepository.get_by_id(self.db, domain_id)


    def get_domain_by_name(self, name: str) -> Optional[models.Domain]:

        return repository.DomainRepository.get_by_name(self.db, name)


    def list_domains(
        self,
        skip: int = 0,
        limit: int = 100
    ) -> List[models.Domain]:

        return repository.DomainRepository.get_all(
            self.db,
            skip,
            limit
        )


    def update_domain(
        self,
        domain_id: int,
        domain_update: schemas.DomainUpdate
    ) -> models.Domain:

        self._require_domain(domain_id)

        domain = repository.DomainRepository.update(
            self.db,
            domain_id,
            domain_update
        )

        return domain


    def delete_domain(self, domain_id: int) -> bool:

        self._require_domain(domain_id)

        return repository.DomainRepository.delete(
            self.db,
            domain_id
        )


    # =====================================================
    # SKILL
    # =====================================================

    def create_skill(
        self,
        skill: schemas.SkillCreate
    ) -> models.Skill:

        exists = repository.SkillRepository.get_by_name(
            self.db,
            skill.name
        )

        if exists:
            raise ValueError("Skill already exists")

        return repository.SkillRepository.create(self.db, skill)


    def get_skill(self, skill_id: int) -> Optional[models.Skill]:

        return repository.SkillRepository.get_by_id(self.db, skill_id)


    def get_skill_by_name(self, name: str) -> Optional[models.Skill]:

        return repository.SkillRepository.get_by_name(self.db, name)


    def list_skills(
        self,
        category: Optional[str] = None,
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 100
    ) -> List[models.Skill]:

        return repository.SkillRepository.get_all(
            self.db,
            category,
            is_active,
            skip,
            limit
        )


    def update_skill(
        self,
        skill_id: int,
        skill_update: schemas.SkillUpdate
    ) -> models.Skill:

        self._require_skill(skill_id)

        return repository.SkillRepository.update(
            self.db,
            skill_id,
            skill_update
        )


    def delete_skill(self, skill_id: int) -> bool:

        self._require_skill(skill_id)

        return repository.SkillRepository.delete(
            self.db,
            skill_id
        )


    def get_or_create_skill(
        self,
        skill_name: str,
        category: str = "technical"
    ) -> models.Skill:

        skill = repository.SkillRepository.get_by_name(
            self.db,
            skill_name
        )

        if skill:
            return skill

        create = schemas.SkillCreate(
            name=skill_name,
            category=category
        )

        return repository.SkillRepository.create(
            self.db,
            create
        )


    # =====================================================
    # CAREER
    # =====================================================

    def create_career(
        self,
        career: schemas.CareerCreate
    ) -> models.Career:

        exists = repository.CareerRepository.get_by_slug(
            self.db,
            career.slug
        ) if career.slug else None

        if exists:
            raise ValueError("Career slug already exists")

        return repository.CareerRepository.create(self.db, career)


    def get_career(
        self,
        career_id: int
    ) -> Optional[models.Career]:

        return repository.CareerRepository.get_by_id(
            self.db,
            career_id
        )


    def get_career_by_name(
        self,
        name: str
    ) -> Optional[models.Career]:

        return repository.CareerRepository.get_by_name(
            self.db,
            name
        )


    def get_career_by_slug(
        self,
        slug: str
    ) -> Optional[models.Career]:

        return repository.CareerRepository.get_by_slug(
            self.db,
            slug
        )


    def list_careers(
        self,
        filters: Optional[schemas.CareerFilter] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[models.Career]:

        return repository.CareerRepository.get_all(
            self.db,
            filters,
            skip,
            limit
        )


    def update_career(
        self,
        career_id: int,
        career_update: schemas.CareerUpdate
    ) -> models.Career:

        self._require_career(career_id)

        return repository.CareerRepository.update(
            self.db,
            career_id,
            career_update
        )


    def delete_career(self, career_id: int) -> bool:

        self._require_career(career_id)

        return repository.CareerRepository.delete(
            self.db,
            career_id
        )


    def add_career_skill(
        self,
        career_id: int,
        skill_id: int,
        requirement_type: str = "required",
        proficiency_level: str = "intermediate"
    ) -> models.CareerSkill:

        self._require_career(career_id)
        self._require_skill(skill_id)

        rel = repository.CareerRepository.add_skill(
            self.db,
            career_id,
            skill_id,
            requirement_type,
            proficiency_level
        )

        if not rel:
            raise ValueError("Relation already exists")

        return rel


    def remove_career_skill(
        self,
        career_id: int,
        skill_id: int
    ) -> bool:

        self._require_career(career_id)
        self._require_skill(skill_id)

        return repository.CareerRepository.remove_skill(
            self.db,
            career_id,
            skill_id
        )


    # =====================================================
    # EDUCATION
    # =====================================================

    def create_education_level(
        self,
        edu: schemas.EducationLevelCreate
    ) -> models.EducationLevel:

        exists = repository.EducationLevelRepository.get_by_name(
            self.db,
            edu.name
        )

        if exists:
            raise ValueError("Education level exists")

        return repository.EducationLevelRepository.create(
            self.db,
            edu
        )


    def list_education_levels(self) -> List[models.EducationLevel]:

        return repository.EducationLevelRepository.get_all(
            self.db
        )


    def get_education_hierarchy(self) -> Dict[str, int]:

        # Taxonomy is the single source of truth for education levels
        mapping: Dict[str, int] = {}
        for entry in taxonomy.manager.education.entries:
            if entry.deprecated:
                continue
            mapping[entry.canonical_label] = entry.priority
            for values in entry.aliases.values():
                for alias in values:
                    mapping[alias] = entry.priority
        return mapping


    # =====================================================
    # RULE ENGINE COMPATIBILITY
    # =====================================================

    def get_job_requirements(
        self,
        job_name: str
    ) -> Dict[str, Any]:

        career = self.get_career_by_name(job_name)

        if not career:
            return {}

        required = []
        preferred = []

        for cs in career.career_skills:

            if cs.requirement_type == models.RequirementType.REQUIRED:
                required.append(cs.skill.name)

            elif cs.requirement_type == models.RequirementType.PREFERRED:
                preferred.append(cs.skill.name)

        # Normalize skills via taxonomy
        required_norm = taxonomy.resolve_skill_list(required, return_ids=False)
        preferred_norm = taxonomy.resolve_skill_list(preferred, return_ids=False)

        return {
            "name": career.name,
            "domain": career.domain.name if career.domain else "Unknown",
            "required_skills": required_norm,
            "preferred_skills": preferred_norm,
            "min_education": taxonomy.resolve_education(
                career.education_min or "",
                return_id=False
            ),
            "ai_relevance": career.ai_relevance,
            "competition": career.competition,
            "growth_rate": career.growth_rate,
        }


    def get_all_jobs(self) -> List[str]:

        careers = self.list_careers(
            filters=schemas.CareerFilter(is_active=True),
            limit=1000
        )

        return [c.name for c in careers]


    def get_job_domain(self, job_name: str) -> str:

        career = self.get_career_by_name(job_name)

        if not career or not career.domain:
            return "Unknown"

        return career.domain.name


    def get_relevant_interests(
        self,
        job_name: str
    ) -> List[str]:

        career = self.get_career_by_name(job_name)

        if not career or not career.domain:
            return []

        return [
            i.interest_name
            for i in career.domain.interests
        ]


    def get_domain_interest_map(self) -> Dict[str, List[str]]:

        domains = self.list_domains(limit=100)

        return {
            d.name: taxonomy.resolve_interest_list(
                [i.interest_name for i in d.interests],
                return_ids=False
            )
            for d in domains
        }

    def get_education_by_name(
        self,
        name: str
    ) -> Optional[models.EducationLevel]:

        return repository.EducationLevelRepository.get_by_name(
            self.db,
            name
        )

    # =====================================================
    # TEMPLATE
    # =====================================================

    def create_template(
        self,
        tmpl: schemas.TemplateCreate,
        user: str = "system"
    ) -> models.Template:

        exists = repository.TemplateRepository.get_by_code(self.db, tmpl.code)
        if exists:
            raise ValueError("Template code already exists")

        db_tmpl = repository.TemplateRepository.create(self.db, tmpl)
        self.versioning.log_create("template", db_tmpl, user)
        return db_tmpl

    def get_template(self, tmpl_id: int) -> Optional[models.Template]:
        return repository.TemplateRepository.get_by_id(self.db, tmpl_id)

    def get_template_by_code(self, code: str) -> Optional[models.Template]:
        return repository.TemplateRepository.get_by_code(self.db, code)

    def list_templates(
        self,
        type_filter: Optional[str] = None,
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 100
    ) -> List[models.Template]:
        return repository.TemplateRepository.get_all(
            self.db, type_filter, is_active, skip, limit
        )

    def update_template(
        self,
        tmpl_id: int,
        update: schemas.TemplateUpdate,
        user: str = "system"
    ) -> models.Template:

        tmpl = repository.TemplateRepository.get_by_id(self.db, tmpl_id)
        if not tmpl:
            raise ValueError("Template not found")

        # Versioned update
        changes = update.model_dump(exclude_unset=True)
        self.versioning.versioned_update("template", tmpl, changes, user)
        self.db.commit()
        self.db.refresh(tmpl)
        return tmpl

    def delete_template(self, tmpl_id: int, user: str = "system") -> bool:
        tmpl = repository.TemplateRepository.get_by_id(self.db, tmpl_id)
        if not tmpl:
            raise ValueError("Template not found")

        self.versioning.versioned_delete("template", tmpl, user)
        self.db.commit()
        return True

    # =====================================================
    # ONTOLOGY
    # =====================================================

    def create_ontology_node(
        self,
        node: schemas.OntologyNodeCreate,
        user: str = "system"
    ) -> models.OntologyNode:

        exists = repository.OntologyRepository.get_by_code(self.db, node.code)
        if exists:
            raise ValueError("Ontology node code already exists")

        db_node = repository.OntologyRepository.create(self.db, node)
        self.versioning.log_create("ontology", db_node, user)
        return db_node

    def get_ontology_node(self, node_id: int) -> Optional[models.OntologyNode]:
        return repository.OntologyRepository.get_by_id(self.db, node_id)

    def get_ontology_node_by_code(self, code: str) -> Optional[models.OntologyNode]:
        return repository.OntologyRepository.get_by_code(self.db, code)

    def list_ontology_nodes(
        self,
        type_filter: Optional[str] = None,
        parent_id: Optional[int] = None,
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 100
    ) -> List[models.OntologyNode]:
        return repository.OntologyRepository.get_all(
            self.db, type_filter, parent_id, is_active, skip, limit
        )

    def get_ontology_roots(self) -> List[models.OntologyNode]:
        return repository.OntologyRepository.get_roots(self.db)

    def get_ontology_children(self, node_id: int) -> List[models.OntologyNode]:
        return repository.OntologyRepository.get_children(self.db, node_id)

    def update_ontology_node(
        self,
        node_id: int,
        update: schemas.OntologyNodeUpdate,
        user: str = "system"
    ) -> models.OntologyNode:

        node = repository.OntologyRepository.get_by_id(self.db, node_id)
        if not node:
            raise ValueError("Ontology node not found")

        changes = update.model_dump(exclude_unset=True)
        self.versioning.versioned_update("ontology", node, changes, user)
        self.db.commit()
        self.db.refresh(node)
        return node

    def delete_ontology_node(self, node_id: int, user: str = "system") -> bool:
        node = repository.OntologyRepository.get_by_id(self.db, node_id)
        if not node:
            raise ValueError("Ontology node not found")

        self.versioning.versioned_delete("ontology", node, user)
        self.db.commit()
        return True

    # =====================================================
    # VERSIONING QUERIES
    # =====================================================

    def get_entity_versions(
        self,
        entity_type: str,
        entity_id: int
    ) -> List[models.KBVersion]:
        return self.versioning.get_versions(entity_type, entity_id)

    def get_entity_history(
        self,
        entity_type: str,
        entity_id: int
    ) -> List[models.KBHistory]:
        return self.versioning.get_history(entity_type, entity_id)

    def compute_entity_diff(
        self,
        entity_type: str,
        entity_id: int,
        version_from: int,
        version_to: int
    ) -> Dict[str, Any]:
        return self.versioning.compute_diff(
            entity_type, entity_id, version_from, version_to
        )

    def rollback_entity(
        self,
        entity_type: str,
        entity_id: int,
        target_version: int,
        user: str = "system"
    ) -> Any:
        entity = self.versioning.rollback(
            entity_type, entity_id, target_version, user
        )
        self.db.commit()
        return entity

    # =====================================================
    # VERSIONED CAREER CRUD (override standard)
    # =====================================================

    def update_career_versioned(
        self,
        career_id: int,
        update: schemas.CareerUpdate,
        user: str = "system"
    ) -> models.Career:

        career = repository.CareerRepository.get_by_id(self.db, career_id)
        if not career:
            raise ValueError("Career not found")

        changes = update.model_dump(exclude_unset=True)
        self.versioning.versioned_update("career", career, changes, user)
        self.db.commit()
        self.db.refresh(career)
        return career

    def delete_career_versioned(
        self,
        career_id: int,
        user: str = "system"
    ) -> bool:

        career = repository.CareerRepository.get_by_id(self.db, career_id)
        if not career:
            raise ValueError("Career not found")

        self.versioning.versioned_delete("career", career, user)
        self.db.commit()
        return True

    # =====================================================
    # VERSIONED SKILL CRUD
    # =====================================================

    def update_skill_versioned(
        self,
        skill_id: int,
        update: schemas.SkillUpdate,
        user: str = "system"
    ) -> models.Skill:

        skill = repository.SkillRepository.get_by_id(self.db, skill_id)
        if not skill:
            raise ValueError("Skill not found")

        changes = update.model_dump(exclude_unset=True)
        self.versioning.versioned_update("skill", skill, changes, user)
        self.db.commit()
        self.db.refresh(skill)
        return skill

    def delete_skill_versioned(
        self,
        skill_id: int,
        user: str = "system"
    ) -> bool:

        skill = repository.SkillRepository.get_by_id(self.db, skill_id)
        if not skill:
            raise ValueError("Skill not found")

        self.versioning.versioned_delete("skill", skill, user)
        self.db.commit()
        return True

    # =====================================================
    # BULK IMPORT
    # =====================================================

    def bulk_import(
        self,
        request: schemas.BulkImportRequest,
        user: str = "system"
    ) -> schemas.BulkImportResult:

        result = schemas.BulkImportResult(
            total=len(request.items),
            created=0,
            skipped=0,
            errors=[],
            dry_run=request.dry_run,
        )

        for item in request.items:
            try:
                entity = self._import_single(
                    request.entity_type,
                    item.data,
                    request.skip_duplicates,
                    request.dry_run,
                    user,
                )
                if entity:
                    result.created += 1
                else:
                    result.skipped += 1

            except Exception as e:
                result.errors.append({
                    "row": item.row_number,
                    "error": str(e),
                    "data": item.data,
                })

        if not request.dry_run:
            self.db.commit()

        return result

    def _import_single(
        self,
        entity_type: str,
        data: Dict[str, Any],
        skip_duplicates: bool,
        dry_run: bool,
        user: str,
    ) -> Optional[Any]:

        if entity_type == "career":
            return self._import_career(data, skip_duplicates, dry_run, user)
        elif entity_type == "skill":
            return self._import_skill(data, skip_duplicates, dry_run, user)
        elif entity_type == "template":
            return self._import_template(data, skip_duplicates, dry_run, user)
        elif entity_type == "ontology":
            return self._import_ontology(data, skip_duplicates, dry_run, user)
        else:
            raise ValueError(f"Unknown entity type: {entity_type}")

    def _import_career(
        self,
        data: Dict[str, Any],
        skip_duplicates: bool,
        dry_run: bool,
        user: str,
    ) -> Optional[models.Career]:

        name = data.get("name")
        if not name:
            raise ValueError("Career name is required")

        exists = repository.CareerRepository.get_by_name(self.db, name)
        if exists and skip_duplicates:
            return None
        if exists:
            raise ValueError(f"Career '{name}' already exists")

        if dry_run:
            return True  # Validation passed

        create = schemas.CareerCreate(**data)
        career = repository.CareerRepository.create(self.db, create)
        self.versioning.log_create("career", career, user)
        return career

    def _import_skill(
        self,
        data: Dict[str, Any],
        skip_duplicates: bool,
        dry_run: bool,
        user: str,
    ) -> Optional[models.Skill]:

        name = data.get("name")
        if not name:
            raise ValueError("Skill name is required")

        exists = repository.SkillRepository.get_by_name(self.db, name)
        if exists and skip_duplicates:
            return None
        if exists:
            raise ValueError(f"Skill '{name}' already exists")

        if dry_run:
            return True

        create = schemas.SkillCreate(**data)
        skill = repository.SkillRepository.create(self.db, create)
        self.versioning.log_create("skill", skill, user)
        return skill

    def _import_template(
        self,
        data: Dict[str, Any],
        skip_duplicates: bool,
        dry_run: bool,
        user: str,
    ) -> Optional[models.Template]:

        code = data.get("code")
        if not code:
            raise ValueError("Template code is required")

        exists = repository.TemplateRepository.get_by_code(self.db, code)
        if exists and skip_duplicates:
            return None
        if exists:
            raise ValueError(f"Template '{code}' already exists")

        if dry_run:
            return True

        create = schemas.TemplateCreate(**data)
        tmpl = repository.TemplateRepository.create(self.db, create)
        self.versioning.log_create("template", tmpl, user)
        return tmpl

    def _import_ontology(
        self,
        data: Dict[str, Any],
        skip_duplicates: bool,
        dry_run: bool,
        user: str,
    ) -> Optional[models.OntologyNode]:

        code = data.get("code")
        if not code:
            raise ValueError("Ontology code is required")

        exists = repository.OntologyRepository.get_by_code(self.db, code)
        if exists and skip_duplicates:
            return None
        if exists:
            raise ValueError(f"Ontology node '{code}' already exists")

        if dry_run:
            return True

        create = schemas.OntologyNodeCreate(**data)
        node = repository.OntologyRepository.create(self.db, create)
        self.versioning.log_create("ontology", node, user)
        return node


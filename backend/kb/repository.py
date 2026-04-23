"""
Repository layer for Knowledge Base (Data Access Layer)
"""

from typing import List, Optional, Generator
from contextlib import contextmanager

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_

from . import models, schemas


# ======================================================
# UTILS
# ======================================================

def safe_enum(enum_cls, value: Optional[str], default):
    """
    Safe convert string to Enum
    """
    if not value:
        return default

    try:
        return enum_cls[value.upper()]
    except KeyError:
        return default


@contextmanager
def transactional(db: Session) -> Generator:
    """
    Transaction wrapper
    """
    try:
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise


# ======================================================
# DOMAIN REPOSITORY
# ======================================================

class DomainRepository:

    @staticmethod
    def create(db: Session, domain: schemas.DomainCreate) -> models.Domain:

        with transactional(db):

            db_domain = models.Domain(
                name=domain.name,
                description=domain.description,
                icon=domain.icon
            )

            db.add(db_domain)
            db.flush()

            for interest in domain.interests or []:
                db.add(
                    models.DomainInterest(
                        domain_id=db_domain.id,
                        interest_name=interest
                    )
                )

        db.refresh(db_domain)
        return db_domain


    @staticmethod
    def get_by_id(db: Session, domain_id: int) -> Optional[models.Domain]:

        return db.query(models.Domain).filter(
            models.Domain.id == domain_id
        ).options(
            joinedload(models.Domain.interests)
        ).first()


    @staticmethod
    def get_by_name(db: Session, name: str) -> Optional[models.Domain]:

        return db.query(models.Domain).filter(
            models.Domain.name == name
        ).options(
            joinedload(models.Domain.interests)
        ).first()


    @staticmethod
    def get_all(
        db: Session,
        skip: int = 0,
        limit: int = 100
    ) -> List[models.Domain]:

        return db.query(models.Domain).options(
            joinedload(models.Domain.interests)
        ).offset(skip).limit(limit).all()


    @staticmethod
    def update(
        db: Session,
        domain_id: int,
        domain_update: schemas.DomainUpdate
    ) -> Optional[models.Domain]:

        domain = db.query(models.Domain).get(domain_id)

        if not domain:
            return None

        data = domain_update.dict(exclude_unset=True)

        with transactional(db):

            for k, v in data.items():
                setattr(domain, k, v)

        db.refresh(domain)
        return domain


    @staticmethod
    def delete(db: Session, domain_id: int) -> bool:

        domain = db.query(models.Domain).get(domain_id)

        if not domain:
            return False

        with transactional(db):
            db.delete(domain)

        return True


# ======================================================
# SKILL REPOSITORY
# ======================================================

class SkillRepository:

    @staticmethod
    def create(db: Session, skill: schemas.SkillCreate) -> models.Skill:

        category = safe_enum(
            models.SkillCategory,
            skill.category,
            models.SkillCategory.TECHNICAL
        )

        slug = skill.slug or skill.name.lower().replace(" ", "-")

        with transactional(db):

            db_skill = models.Skill(
                name=skill.name,
                slug=slug,
                code=getattr(skill, 'code', None) or slug,
                category=category,
                description=skill.description,
                level_map=getattr(skill, 'level_map', None) or {},
                related_skills=getattr(skill, 'related_skills', None) or [],
            )

            db.add(db_skill)

        db.refresh(db_skill)
        return db_skill


    @staticmethod
    def get_by_id(db: Session, skill_id: int) -> Optional[models.Skill]:

        return db.query(models.Skill).get(skill_id)


    @staticmethod
    def get_by_name(db: Session, name: str) -> Optional[models.Skill]:

        return db.query(models.Skill).filter(
            models.Skill.name == name
        ).first()


    @staticmethod
    def get_by_slug(db: Session, slug: str) -> Optional[models.Skill]:

        return db.query(models.Skill).filter(
            models.Skill.slug == slug
        ).first()


    @staticmethod
    def get_all(
        db: Session,
        category: Optional[str] = None,
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 100
    ) -> List[models.Skill]:

        query = db.query(models.Skill)

        if is_active is not None:
            query = query.filter(models.Skill.is_active == is_active)

        if category:
            query = query.filter(
                models.Skill.category == safe_enum(
                    models.SkillCategory,
                    category,
                    models.SkillCategory.TECHNICAL
                )
            )

        return query.offset(skip).limit(limit).all()


    @staticmethod
    def update(
        db: Session,
        skill_id: int,
        skill_update: schemas.SkillUpdate
    ) -> Optional[models.Skill]:

        skill = db.query(models.Skill).get(skill_id)

        if not skill:
            return None

        data = skill_update.dict(exclude_unset=True)

        with transactional(db):

            for k, v in data.items():

                if k == "category":
                    v = safe_enum(
                        models.SkillCategory,
                        v,
                        skill.category
                    )

                setattr(skill, k, v)

        db.refresh(skill)
        return skill


    @staticmethod
    def delete(db: Session, skill_id: int) -> bool:

        skill = db.query(models.Skill).get(skill_id)

        if not skill:
            return False

        with transactional(db):
            skill.is_active = False

        return True


# ======================================================
# CAREER REPOSITORY
# ======================================================

class CareerRepository:


    @staticmethod
    def create(db: Session, career: schemas.CareerCreate) -> models.Career:

        # Validate domain
        if not db.query(models.Domain).get(career.domain_id):
            raise ValueError("Domain not found")

        slug = career.slug or career.name.lower().replace(" ", "-")

        with transactional(db):

            db_career = models.Career(
                name=career.name,
                slug=slug,
                code=getattr(career, 'code', None) or slug,
                domain_id=career.domain_id,
                description=career.description,
                icon=career.icon,
                level=getattr(career, 'level', None),
                education_min=career.education_min,
                ai_relevance=career.ai_relevance,
                competition=career.competition,
                growth_rate=career.growth_rate,
                salary_range_min=career.salary_range_min,
                salary_range_max=career.salary_range_max,
                market_tags=getattr(career, 'market_tags', None) or [],
            )

            db.add(db_career)
            db.flush()


            # Skills
            for s in career.skills or []:

                if not db.query(models.Skill).get(s.skill_id):
                    continue

                db.add(
                    models.CareerSkill(
                        career_id=db_career.id,
                        skill_id=s.skill_id,
                        requirement_type=safe_enum(
                            models.RequirementType,
                            s.requirement_type,
                            models.RequirementType.REQUIRED
                        ),
                        proficiency_level=safe_enum(
                            models.ProficiencyLevel,
                            s.proficiency_level,
                            models.ProficiencyLevel.INTERMEDIATE
                        )
                    )
                )


            # Roadmaps
            for r in career.roadmaps or []:

                db.add(
                    models.Roadmap(
                        career_id=db_career.id,
                        title=r.title,
                        description=r.description,
                        step_order=r.step_order,
                        level=r.level,
                        duration_months=r.duration_months
                    )
                )

        db.refresh(db_career)
        return db_career


    @staticmethod
    def get_by_id(db: Session, career_id: int) -> Optional[models.Career]:

        return db.query(models.Career).filter(
            models.Career.id == career_id
        ).options(
            joinedload(models.Career.domain).joinedload(models.Domain.interests),
            joinedload(models.Career.career_skills).joinedload(models.CareerSkill.skill),
            joinedload(models.Career.roadmaps)
        ).first()


    @staticmethod
    def get_by_slug(db: Session, slug: str) -> Optional[models.Career]:

        return db.query(models.Career).filter(
            models.Career.slug == slug
        ).options(
            joinedload(models.Career.domain),
            joinedload(models.Career.career_skills).joinedload(models.CareerSkill.skill),
            joinedload(models.Career.roadmaps)
        ).first()


    @staticmethod
    def get_by_name(db: Session, name: str) -> Optional[models.Career]:

        return db.query(models.Career).filter(
            models.Career.name == name
        ).options(
            joinedload(models.Career.domain),
            joinedload(models.Career.career_skills).joinedload(models.CareerSkill.skill),
            joinedload(models.Career.roadmaps)
        ).first()


    @staticmethod
    def get_all(
        db: Session,
        filters: Optional[schemas.CareerFilter] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[models.Career]:

        query = db.query(models.Career)

        if filters:

            if filters.domain_id:
                query = query.filter(
                    models.Career.domain_id == filters.domain_id
                )

            if filters.education_min:
                query = query.filter(
                    models.Career.education_min == filters.education_min
                )

            if filters.is_active is not None:
                query = query.filter(
                    models.Career.is_active == filters.is_active
                )

            if filters.min_ai_relevance:
                query = query.filter(
                    models.Career.ai_relevance >= filters.min_ai_relevance
                )

            if filters.max_competition:
                query = query.filter(
                    models.Career.competition <= filters.max_competition
                )

            if filters.search:

                term = f"%{filters.search}%"

                query = query.filter(
                    or_(
                        models.Career.name.ilike(term),
                        models.Career.description.ilike(term)
                    )
                )

        return query.options(
            joinedload(models.Career.domain),
            joinedload(models.Career.career_skills).joinedload(models.CareerSkill.skill)
        ).offset(skip).limit(limit).all()


    @staticmethod
    def update(
        db: Session,
        career_id: int,
        career_update: schemas.CareerUpdate
    ) -> Optional[models.Career]:

        career = db.query(models.Career).get(career_id)

        if not career:
            return None

        data = career_update.dict(exclude_unset=True)

        with transactional(db):

            for k, v in data.items():
                setattr(career, k, v)

        db.refresh(career)
        return career


    @staticmethod
    def delete(db: Session, career_id: int) -> bool:

        career = db.query(models.Career).get(career_id)

        if not career:
            return False

        with transactional(db):
            career.is_active = False

        return True


    @staticmethod
    def add_skill(
        db: Session,
        career_id: int,
        skill_id: int,
        requirement_type: str = "required",
        proficiency_level: str = "intermediate"
    ) -> Optional[models.CareerSkill]:

        if not db.query(models.Career).get(career_id):
            return None

        if not db.query(models.Skill).get(skill_id):
            return None

        exists = db.query(models.CareerSkill).filter(
            models.CareerSkill.career_id == career_id,
            models.CareerSkill.skill_id == skill_id
        ).first()

        if exists:
            return None

        with transactional(db):

            rel = models.CareerSkill(
                career_id=career_id,
                skill_id=skill_id,
                requirement_type=safe_enum(
                    models.RequirementType,
                    requirement_type,
                    models.RequirementType.REQUIRED
                ),
                proficiency_level=safe_enum(
                    models.ProficiencyLevel,
                    proficiency_level,
                    models.ProficiencyLevel.INTERMEDIATE
                )
            )

            db.add(rel)

        db.refresh(rel)
        return rel


    @staticmethod
    def remove_skill(db: Session, career_id: int, skill_id: int) -> bool:

        rel = db.query(models.CareerSkill).filter(
            models.CareerSkill.career_id == career_id,
            models.CareerSkill.skill_id == skill_id
        ).first()

        if not rel:
            return False

        with transactional(db):
            db.delete(rel)

        return True


# ======================================================
# EDUCATION LEVEL REPOSITORY
# ======================================================

class EducationLevelRepository:
    @staticmethod
    def create(
        db: Session,
        edu: schemas.EducationLevelCreate
    ) -> models.EducationLevel:

        with transactional(db):

            level = models.EducationLevel(
                name=edu.name,
                hierarchy_level=edu.hierarchy_level,
                description=edu.description
            )

            db.add(level)

        db.refresh(level)
        return level


    @staticmethod
    def get_all(db: Session) -> List[models.EducationLevel]:

        return db.query(models.EducationLevel).order_by(
            models.EducationLevel.hierarchy_level
        ).all()


    @staticmethod
    def get_by_name(
        db: Session,
        name: str
    ) -> Optional[models.EducationLevel]:

        return db.query(models.EducationLevel).filter(
            models.EducationLevel.name == name
        ).first()


    @staticmethod
    def get_hierarchy_map(db: Session) -> dict:

        levels = db.query(models.EducationLevel).all()

        return {
            l.name: l.hierarchy_level
            for l in levels
        }


# ======================================================
# TEMPLATE REPOSITORY
# ======================================================

class TemplateRepository:

    @staticmethod
    def create(db: Session, tmpl: schemas.TemplateCreate) -> models.Template:

        with transactional(db):
            db_tmpl = models.Template(
                code=tmpl.code,
                name=tmpl.name,
                type=safe_enum(models.TemplateType, tmpl.type, models.TemplateType.CUSTOM),
                content=tmpl.content,
                variables=tmpl.variables or [],
            )
            db.add(db_tmpl)

        db.refresh(db_tmpl)
        return db_tmpl

    @staticmethod
    def get_by_id(db: Session, tmpl_id: int) -> Optional[models.Template]:
        return db.query(models.Template).get(tmpl_id)

    @staticmethod
    def get_by_code(db: Session, code: str) -> Optional[models.Template]:
        return db.query(models.Template).filter(
            models.Template.code == code
        ).first()

    @staticmethod
    def get_all(
        db: Session,
        type_filter: Optional[str] = None,
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 100
    ) -> List[models.Template]:

        query = db.query(models.Template)

        if is_active is not None:
            query = query.filter(models.Template.is_active == is_active)

        if type_filter:
            query = query.filter(
                models.Template.type == safe_enum(
                    models.TemplateType, type_filter, models.TemplateType.CUSTOM
                )
            )

        return query.offset(skip).limit(limit).all()

    @staticmethod
    def update(
        db: Session,
        tmpl_id: int,
        update: schemas.TemplateUpdate
    ) -> Optional[models.Template]:

        tmpl = db.query(models.Template).get(tmpl_id)
        if not tmpl:
            return None

        data = update.model_dump(exclude_unset=True)

        with transactional(db):
            for k, v in data.items():
                if k == "type":
                    v = safe_enum(models.TemplateType, v, tmpl.type)
                setattr(tmpl, k, v)

        db.refresh(tmpl)
        return tmpl

    @staticmethod
    def delete(db: Session, tmpl_id: int) -> bool:
        tmpl = db.query(models.Template).get(tmpl_id)
        if not tmpl:
            return False

        with transactional(db):
            tmpl.is_active = False
            tmpl.status = "deleted"

        return True


# ======================================================
# ONTOLOGY REPOSITORY
# ======================================================

class OntologyRepository:

    @staticmethod
    def create(db: Session, node: schemas.OntologyNodeCreate) -> models.OntologyNode:

        with transactional(db):
            db_node = models.OntologyNode(
                code=node.code,
                type=safe_enum(models.OntologyNodeType, node.type, models.OntologyNodeType.CONCEPT),
                label=node.label,
                parent_id=node.parent_id,
                relations=[r.model_dump() for r in (node.relations or [])],
                metadata_=getattr(node, 'metadata_', {}) or {},
            )
            db.add(db_node)

        db.refresh(db_node)
        return db_node

    @staticmethod
    def get_by_id(db: Session, node_id: int) -> Optional[models.OntologyNode]:
        return db.query(models.OntologyNode).filter(
            models.OntologyNode.node_id == node_id
        ).first()

    @staticmethod
    def get_by_code(db: Session, code: str) -> Optional[models.OntologyNode]:
        return db.query(models.OntologyNode).filter(
            models.OntologyNode.code == code
        ).first()

    @staticmethod
    def get_all(
        db: Session,
        type_filter: Optional[str] = None,
        parent_id: Optional[int] = None,
        is_active: Optional[bool] = True,
        skip: int = 0,
        limit: int = 100
    ) -> List[models.OntologyNode]:

        query = db.query(models.OntologyNode)

        if is_active is not None:
            query = query.filter(models.OntologyNode.is_active == is_active)

        if type_filter:
            query = query.filter(
                models.OntologyNode.type == safe_enum(
                    models.OntologyNodeType, type_filter, models.OntologyNodeType.CONCEPT
                )
            )

        if parent_id is not None:
            query = query.filter(models.OntologyNode.parent_id == parent_id)

        return query.offset(skip).limit(limit).all()

    @staticmethod
    def get_roots(db: Session, is_active: bool = True) -> List[models.OntologyNode]:
        """Get root nodes (parent_id = None)"""
        query = db.query(models.OntologyNode).filter(
            models.OntologyNode.parent_id.is_(None)
        )
        if is_active is not None:
            query = query.filter(models.OntologyNode.is_active == is_active)
        return query.all()

    @staticmethod
    def get_children(db: Session, node_id: int, is_active: bool = True) -> List[models.OntologyNode]:
        """Get children of a node"""
        query = db.query(models.OntologyNode).filter(
            models.OntologyNode.parent_id == node_id
        )
        if is_active is not None:
            query = query.filter(models.OntologyNode.is_active == is_active)
        return query.all()

    @staticmethod
    def update(
        db: Session,
        node_id: int,
        update: schemas.OntologyNodeUpdate
    ) -> Optional[models.OntologyNode]:

        node = db.query(models.OntologyNode).filter(
            models.OntologyNode.node_id == node_id
        ).first()
        if not node:
            return None

        data = update.model_dump(exclude_unset=True)

        with transactional(db):
            for k, v in data.items():
                if k == "relations" and v:
                    v = [r if isinstance(r, dict) else r.model_dump() for r in v]
                setattr(node, k, v)

        db.refresh(node)
        return node

    @staticmethod
    def delete(db: Session, node_id: int) -> bool:
        node = db.query(models.OntologyNode).filter(
            models.OntologyNode.node_id == node_id
        ).first()
        if not node:
            return False

        with transactional(db):
            node.is_active = False
            node.status = "deleted"

        return True

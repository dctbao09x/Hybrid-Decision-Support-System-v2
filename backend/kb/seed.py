# backend/kb/seed.py
"""
Seed script to migrate data from old job_database.py to Knowledge Base
Improved: idempotent, validation, logging, normalization
"""

import sys
import re
import logging
from pathlib import Path
from typing import List


# ============================
# PATH CONFIG
# ============================

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))


# ============================
# LOGGING
# ============================

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(message)s"
)

logger = logging.getLogger("kb-seed")


# ============================
# IMPORTS
# ============================

from backend.kb.database import get_db_context, init_db
from kb import schemas, service

from backend.rule_engine.prototype_jobs import (
    JOB_DATABASE,
    DOMAIN_INTEREST_MAP,
    EDUCATION_HIERARCHY
)


# ============================
# HELPERS
# ============================

def normalize_slug(text: str) -> str:
    """Create safe slug"""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def safe_create(fn, name: str):
    """Wrapper for safe creation"""
    try:
        return fn()
    except Exception as e:
        logger.error("Failed %s: %s", name, e)
        return None


# ============================
# EDUCATION
# ============================

def seed_education_levels():
    logger.info("Seeding education levels...")

    with get_db_context() as db:
        kb = service.KnowledgeBaseService(db)

        for name, level in EDUCATION_HIERARCHY.items():

            if level < 1:
                logger.warning("Skip invalid education: %s", name)
                continue

            if kb.get_education_by_name(name):
                logger.info("Skip education: %s (exists)", name)
                continue

            data = schemas.EducationLevelCreate(
                name=name,
                hierarchy_level=level,
                description=f"{name} education level"
            )

            safe_create(
                lambda: kb.create_education_level(data),
                f"education {name}"
            )
# ============================
# DOMAINS
# ============================

DOMAIN_ICONS = {
    "AI": "🤖",
    "Data": "📊",
    "Software": "💻",
    "Cloud": "☁️",
    "Security": "🔒",
    "Business": "💼",
    "Design": "🎨",
    "Marketing": "📱",
    "Media": "📺",
    "Engineering": "⚙️",
    "Finance": "💰",
    "Education": "📚",
    "IT": "🖥️",
    "Entrepreneurship": "🚀",
    "Healthcare": "🏥",
    "Legal": "⚖️",
    "HR": "👥",
    "Logistics": "🚚",
    "Manufacturing": "🏭",
}


def seed_domains():
    logger.info("Seeding domains...")

    with get_db_context() as db:

        kb = service.KnowledgeBaseService(db)

        for name, interests in DOMAIN_INTEREST_MAP.items():

            if kb.get_domain_by_name(name):
                logger.info("Skip domain: %s (exists)", name)
                continue

            domain = schemas.DomainCreate(
                name=name,
                description=f"{name} domain",
                icon=DOMAIN_ICONS.get(name, "📁"),
                interests=interests
            )

            safe_create(
                lambda: kb.create_domain(domain),
                f"domain {name}"
            )


# ============================
# SKILLS
# ============================

def build_skills(
    kb: service.KnowledgeBaseService,
    skills: List[str],
    requirement_type
) -> List[schemas.CareerSkillCreate]:

    results = []

    for name in skills:

        skill = kb.get_or_create_skill(name, "technical")

        results.append(
            schemas.CareerSkillCreate(
                skill_id=skill.id,
                requirement_type=requirement_type,
                proficiency_level=schemas.ProficiencyLevelEnum.INTERMEDIATE
            )
        )

    return results


# ============================
# ROADMAP
# ============================

def default_roadmap():

    return [

        schemas.RoadmapCreate(
            title="Junior",
            description="Entry level",
            level="junior",
            step_order=1,
            duration_months=12,
        ),

        schemas.RoadmapCreate(
            title="Mid",
            description="Intermediate level",
            level="mid",
            duration_months=24,
            step_order=2,
        ),

        schemas.RoadmapCreate(
            title="Senior",
            description="Senior level",
            level="senior",
            duration_months=36,
            step_order=3,
        ),

        schemas.RoadmapCreate(
            title="Lead",
            description="Leadership / Expert",
            level="lead",
            duration_months=48,
            step_order=4,
        )
    ]


# ============================
# CAREERS
# ============================

CAREER_ICONS = {
    "AI Engineer": "🤖",
    "Machine Learning Engineer": "🧠",
    "Data Scientist": "📊",
    "Data Analyst": "📈",
    "AI Researcher": "🔬",
    "Software Engineer": "💻",
    "Backend Developer": "⚙️",
    "Frontend Developer": "🌐",
    "Mobile Developer": "📱",
    "Game Developer": "🎮",
    "DevOps Engineer": "🔧",
    "Cloud Architect": "☁️",
    "System Administrator": "🖥️",
    "Cybersecurity Analyst": "🔒",
    "Security Engineer": "🛡️",
    "Product Manager": "📋",
    "Business Analyst": "💼",
    "Project Manager": "📊",
    "UI/UX Designer": "🎨",
    "Graphic Designer": "🖌️",
    "Motion Designer": "🎬",
    "Digital Marketer": "📱",
    "Content Creator": "✍️",
    "Copywriter": "📝",
    "Robotics Engineer": "🤖",
    "Embedded Engineer": "🔌",
    "IoT Engineer": "📡",
    "Financial Analyst": "💰",
    "Quant Analyst": "📊",
    "AI Lecturer": "👨‍🏫",
    "STEM Teacher": "🧪",
    "IT Support": "🆘",
    "QA Engineer": "✅",
    "Technical Writer": "📖",
    "Startup Founder": "🚀",
    "Freelance Developer": "💼",
    "Data Engineer": "🏗️",
    "MLOps Engineer": "🔄",
    "Machine OPS Engineer": "🔄",
    "Strategy Analyst": "📈",
    "Operations Analyst": "⚡",
    # Software extended
    "Full Stack Developer": "🖥️",
    "Blockchain Developer": "⛓️",
    "Database Administrator": "🗄️",
    # Networking
    "Network Engineer": "🌐",
    # Engineering extended
    "Electrical Engineer": "⚡",
    "Mechanical Engineer": "🔩",
    "Civil Engineer": "🏗️",
    # Design extended
    "Product Designer": "🎯",
    "Architect": "🏛️",
    "3D Artist": "🎭",
    # Data extended
    "BI Developer": "📊",
    "Growth Analyst": "📈",
    # Marketing extended
    "PR Manager": "📣",
    "Brand Manager": "🏷️",
    "Social Media Manager": "📱",
    # Media extended
    "Journalist": "📰",
    "Video Editor": "🎬",
    # Business extended
    "Sales Manager": "💰",
    "Account Manager": "🤝",
    # Finance extended
    "Accountant": "📒",
    "Auditor": "🔍",
    "Investment Banker": "🏦",
    "Risk Manager": "⚠️",
    "Fintech Engineer": "💳",
    # Healthcare
    "Doctor": "👨‍⚕️",
    "Nurse": "👩‍⚕️",
    "Pharmacist": "💊",
    "Health Informatics Specialist": "🏥",
    # Legal
    "Lawyer": "⚖️",
    "Legal Counsel": "📜",
    "Compliance Officer": "✅",
    # HR
    "HR Manager": "👥",
    "Talent Acquisition Specialist": "🎯",
    "HR Data Analyst": "📊",
    # Logistics
    "Supply Chain Manager": "🚚",
    "Logistics Coordinator": "📦",
    # Manufacturing
    "Manufacturing Engineer": "🏭",
    "Quality Engineer": "🔬",
    "Production Manager": "⚙️",
    # Education extended
    "E-learning Designer": "💻",
    "Training Manager": "📚",
}


def seed_careers():

    logger.info("Seeding careers...")

    with get_db_context() as db:

        kb = service.KnowledgeBaseService(db)

        for name, data in JOB_DATABASE.items():

            # Skip exists
            if kb.get_career_by_name(name):
                logger.info("Skip career: %s (exists)", name)
                continue

            try:

                # Domain
                domain_name = data.get("domain", "IT")
                domain = kb.get_domain_by_name(domain_name)

                if not domain:
                    logger.error("Missing domain: %s → %s", name, domain_name)
                    continue

                # Skills
                required = data.get("required_skills", [])
                preferred = data.get("preferred_skills", [])

                skills = []

                skills += build_skills(
                    kb,
                    required,
                    schemas.RequirementTypeEnum.REQUIRED
                )

                skills += build_skills(
                    kb,
                    preferred,
                    schemas.RequirementTypeEnum.PREFERRED
                )

                # Slug
                slug = normalize_slug(name)

                # Career object
                career = schemas.CareerCreate(

                    name=name,
                    slug=slug,

                    domain_id=domain.id,

                    description=data.get(
                        "description",
                        f"{name} professional"
                    ),

                    icon=CAREER_ICONS.get(name, "💼"),

                    education_min=data.get(
                        "education_min",
                        "Bachelor"
                    ),

                    ai_relevance=float(
                        data.get("ai_relevance", 0.5)
                    ),

                    competition=float(
                        data.get("competition", 0.5)
                    ),

                    growth_rate=float(
                        data.get("growth_rate", 0.5)
                    ),

                    skills=skills,

                    roadmaps=default_roadmap()
                )

                kb.create_career(career)

                logger.info("Created career: %s", name)

            except Exception as e:

                logger.exception("Career failed: %s | %s", name, e)


# ============================
# MAIN
# ============================

def seed_all():

    logger.info("=" * 60)
    logger.info("START KB SEEDING")
    logger.info("=" * 60)

    init_db()

    seed_education_levels()
    seed_domains()
    seed_careers()

    with get_db_context() as db:

        kb = service.KnowledgeBaseService(db)

        logger.info("-" * 40)

        logger.info(
            "Education: %s",
            len(kb.list_education_levels())
        )

        logger.info(
            "Domains: %s",
            len(kb.list_domains(limit=1000))
        )

        logger.info(
            "Skills: %s",
            len(kb.list_skills(limit=2000))
        )

        logger.info(
            "Careers: %s",
            len(kb.list_careers(limit=1000))
        )

        logger.info("-" * 40)


# ============================
# RUN
# ============================

if __name__ == "__main__":
    seed_all()

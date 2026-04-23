"""
Career library router (for frontend library page).
"""

from typing import List, Dict, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.kb.database import get_db
from backend.kb.service import KnowledgeBaseService
from backend.kb import schemas
from .utils import slugify, icon_for_domain


router = APIRouter()


def get_kb_service(db: Session = Depends(get_db)) -> KnowledgeBaseService:
    return KnowledgeBaseService(db)


@router.get("/")
def get_career_library(kb: KnowledgeBaseService = Depends(get_kb_service)):
    filters = schemas.CareerFilter()
    careers = kb.list_careers(filters=filters, skip=0, limit=1000)
    items: List[Dict[str, Any]] = []

    for career in careers:
        domain = career.domain.name if career.domain else "Unknown"
        items.append({
            "id": slugify(career.name),
            "name": career.name,
            "icon": icon_for_domain(domain),
            "domain": domain,
            "description": career.description or f"{career.name} thuộc lĩnh vực {domain}.",
            "matchScore": 0.5,
            "growthRate": float(getattr(career, "growth_rate", 0.5) or 0.5),
            "competition": float(getattr(career, "competition", 0.5) or 0.5),
            "aiRelevance": float(getattr(career, "ai_relevance", 0.5) or 0.5),
            "requiredSkills": [],
            "tags": []
        })

    return {"careers": items}

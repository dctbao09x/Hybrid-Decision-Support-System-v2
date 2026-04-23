"""
Recommendations router.
"""

from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.processor import process_user_profile
from backend.rule_engine.rule_engine import RuleEngine
from backend.rule_engine.job_database import (
    get_job_requirements,
    get_all_jobs
)
from backend.embedding_engine import match_careers
from .utils import build_profile_dict, slugify, icon_for_domain


router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    text: str


class RecommendationsRequest(BaseModel):
    processedProfile: Optional[Dict[str, Any]] = None
    userProfile: Optional[Dict[str, Any]] = None
    assessmentAnswers: Optional[Dict[str, Any]] = None
    chatHistory: Optional[List[ChatMessage]] = None


@router.post("/")
def get_recommendations(request: RecommendationsRequest):

    processed = request.processedProfile

    if not processed:

        if not request.userProfile:
            raise HTTPException(
                status_code=400,
                detail="userProfile or processedProfile is required"
            )

        profile_dict = build_profile_dict(
            request.userProfile,
            [m.model_dump() if hasattr(m, 'model_dump') else m.dict() for m in (request.chatHistory or [])]
        )

        processed = process_user_profile(profile_dict)

    all_jobs = get_all_jobs()
    total_jobs = len(all_jobs)

    if total_jobs == 0:
        raise HTTPException(
            status_code=500,
            detail="Job database is empty"
        )

    # ------------------------
    # Embedding match with timeout / fallback
    # ------------------------

    timeout_s = float(os.getenv("RECOMMENDATIONS_TIMEOUT", "3.0"))
    max_candidates = int(os.getenv("RECOMMENDATIONS_MAX_CANDIDATES", "200"))

    candidates = all_jobs[:max_candidates]

    def _run_match():
        return match_careers(
            processed,
            candidates=candidates,
            top_k=len(candidates)
        )

    similarity_scores = {}
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_run_match)
            similarity_list = fut.result(timeout=timeout_s)
        similarity_scores = {
            item["career"]: item["similarity"]
            for item in similarity_list
        }
    except TimeoutError:
        # Fallback: no similarity scores
        similarity_scores = {}
    except Exception:
        similarity_scores = {}

    processed["similarity_scores"] = similarity_scores

    engine = RuleEngine()
    rule_result = engine.process_profile(processed)

    ranked_jobs = (
        rule_result.get("filtered_jobs")
        or rule_result.get("ranked_jobs")
        or rule_result.get("all_jobs")
        or []
    )

    recommendations = []

    for job_eval in ranked_jobs:

        job_name = job_eval.get("job")
        if not job_name:
            continue

        reqs = get_job_requirements(job_name)
        if not reqs:
            continue

        domain = reqs.get("domain", "Unknown")

        recommendations.append({
            "id": slugify(job_name),
            "name": job_name,
            "icon": icon_for_domain(domain),
            "domain": domain,
            "description": reqs.get(
                "description",
                f"{job_name} thuộc lĩnh vực {domain}."
            ),
            "matchScore": round(float(job_eval.get("score", 0.0)), 3),
            "growthRate": float(reqs.get("growth_rate", 0.5)),
            "competition": float(reqs.get("competition", 0.5)),
            "aiRelevance": float(reqs.get("ai_relevance", 0.5)),
            "requiredSkills": reqs.get("required_skills", []),
            "tags": job_eval.get("tags", [])
        })

    return {
        "total": len(recommendations),
        "processedProfile": processed,
        "recommendations": recommendations,
        "meta": {
            "flags": rule_result.get("flags", []),
            "warnings": rule_result.get("warnings", []),
            "total_jobs_in_db": total_jobs,
            "jobs_after_rule": len(ranked_jobs)
        }
    }

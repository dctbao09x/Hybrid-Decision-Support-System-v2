# backend/api_legacy.py
"""
DEPRECATED - Legacy API
=======================

This file is DEPRECATED. All functionality has been migrated to the unified
API Gateway at backend/inference/api_server_v2.py

Use the new unified API:
  - Entrypoint: backend/run_api.py
  - Gateway: backend/inference/api_server_v2.py
  
All endpoints now under /api/v1/*:
  - /api/v1/infer/analyze      — replaces /analyze
  - /api/v1/infer/recommendations — replaces /recommendations  
  - /api/v1/chat               — replaces /chat
  - /api/v1/health/full        — replaces /health

DO NOT USE THIS FILE IN PRODUCTION.
"""

import warnings

warnings.warn(
    "api_legacy.py is deprecated. Use backend.run_api instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Raise error if someone tries to run this
def _deprecated():
    raise RuntimeError(
        "api_legacy.py is deprecated and disabled. "
        "Use the unified API Gateway: python -m uvicorn backend.run_api:app --port 8000"
    )

# If this file is imported as a module, issue warning
_deprecated()

# Legacy code preserved below for reference only
# ================================================
#
# from backend.rule_engine.job_database import JOB_DATABASE
# from fastapi import FastAPI, HTTPException
# ... (rest of file preserved as comment)


def _build_profile_dict(
    user_profile: Dict[str, Any],
    chat_history: Optional[List[ChatMessage]] = None
) -> Dict[str, Any]:
    return {
        "personalInfo": {
            "fullName": user_profile.get("fullName", ""),
            "age": user_profile.get("age", ""),
            "education": user_profile.get("education", "")
        },
        "interests": user_profile.get("interests", []),
        "skills": user_profile.get("skills", ""),
        "careerGoal": user_profile.get("careerGoal", ""),
        "chatHistory": [
            {"role": msg.role, "text": msg.text}
            for msg in (chat_history or [])
        ]
    }


def _slugify(text: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in text).strip("-")


def _icon_for_domain(domain: str) -> str:
    mapping = {
        "AI": "🤖",
        "Data": "📊",
        "Software": "💻",
        "Cloud": "☁️",
        "Security": "🛡️",
        "Business": "📈",
        "Design": "🎨",
        "Marketing": "📣",
        "Media": "📝",
        "Engineering": "⚙️",
        "Finance": "💰",
        "Education": "🎓",
        "IT": "🖧",
        "Entrepreneurship": "🚀",
        "Healthcare": "🏥",
        "Legal": "⚖️",
        "HR": "👥",
        "Logistics": "🚚",
        "Manufacturing": "🏭",
    }
    return mapping.get(domain, "💼")


@app.post("/recommendations")
def get_recommendations(request: RecommendationsRequest):
    # Lazy imports to avoid startup failures if optional deps are missing
    from embedding_engine import match_careers
    from rule_engine.rule_engine import RuleEngine
    from rule_engine.job_database import get_job_requirements

    processed = request.processedProfile

    if not processed:
        if not request.userProfile:
            raise HTTPException(
                status_code=400,
                detail="userProfile or processedProfile is required"
            )
        profile_dict = _build_profile_dict(
            request.userProfile,
            request.chatHistory
        )
        processed = process_user_profile(profile_dict)

    similarity_list = match_careers(processed, top_k=50)
    similarity_scores = {
        item["career"]: item["similarity"]
        for item in similarity_list
    }

    processed_with_similarity = {
        **processed,
        "similarity_scores": similarity_scores
    }

    engine = RuleEngine()
    rule_result = engine.process_profile(processed_with_similarity)
    ranked_jobs = rule_result.get("filtered_jobs") or rule_result.get("ranked_jobs", [])

@app.post("/recommendations")
def get_recommendations(request: RecommendationsRequest):

    # Lazy imports
    from embedding_engine import match_careers
    from rule_engine.rule_engine import RuleEngine
    from rule_engine.job_database import (
        get_job_requirements,
        get_all_jobs
    )

    # ==================== BUILD PROFILE ====================

    processed = request.processedProfile

    if not processed:

        if not request.userProfile:
            raise HTTPException(
                status_code=400,
                detail="userProfile or processedProfile is required"
            )

        profile_dict = _build_profile_dict(
            request.userProfile,
            request.chatHistory
        )

        processed = process_user_profile(profile_dict)

    # ==================== LOAD ALL JOBS ====================

    all_jobs = get_all_jobs()
    total_jobs = len(all_jobs)

    if total_jobs == 0:
        raise HTTPException(
            status_code=500,
            detail="Job database is empty"
        )

    # ==================== EMBEDDING MATCH ====================

    similarity_list = match_careers(
        processed,
        candidates=all_jobs,
        top_k=total_jobs
    )

    similarity_scores = {
        item["career"]: item["similarity"]
        for item in similarity_list
    }

    processed["similarity_scores"] = similarity_scores

    # ==================== RULE ENGINE ====================

    engine = RuleEngine()
    rule_result = engine.process_profile(processed)

    ranked_jobs = (
        rule_result.get("filtered_jobs")
        or rule_result.get("ranked_jobs")
        or rule_result.get("all_jobs")
        or []
    )

    # ==================== DEBUG ====================

    print("TOTAL JOBS IN DB:", total_jobs)
    print("TOTAL AFTER RULE:", len(ranked_jobs))

    # ==================== BUILD RESPONSE ====================

    recommendations = []

    for job_eval in ranked_jobs:

        job_name = job_eval.get("job")

        if not job_name:
            continue

        reqs = get_job_requirements(job_name) or {}

        domain = reqs.get("domain", "Unknown")

        recommendations.append({

            "id": _slugify(job_name),

            "name": job_name,

            "icon": _icon_for_domain(domain),

            "domain": domain,

            "description": reqs.get(
                "description",
                f"{job_name} thuộc lĩnh vực {domain}."
            ),

            "matchScore": round(
                float(job_eval.get("score", 0.0)), 3
            ),

            "growthRate": float(
                reqs.get("growth_rate", 0.5)
            ),

            "competition": float(
                reqs.get("competition", 0.5)
            ),

            "aiRelevance": float(
                reqs.get("ai_relevance", 0.5)
            ),

            "requiredSkills": reqs.get(
                "required_skills", []
            ),

            "tags": job_eval.get("tags", [])
        })

    # ==================== FINAL RESPONSE ====================

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


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    text = request.message.strip().lower()

    if not text:
        return ChatResponse(reply="Bạn có thể chia sẻ thêm không?")

    if "AI" in text or "trí tuệ nhân tạo" in text or "machine learning" in text:
        reply = "AI/ML là mảng rất tiềm năng. Bạn đã có nền tảng lập trình nào chưa?"
    elif "thiết kế" in text or "design" in text or "ui" in text:
        reply = "Thiết kế là mảng sáng tạo. Bạn quan tâm UI/UX hay graphic?"
    elif "data" in text or "dữ liệu" in text:
        reply = "Data là mảng có nhiều cơ hội. Bạn thích phân tích hay xây hệ thống dữ liệu?"
    elif "backend" in text or "server" in text:
        reply = "Backend cần nền tảng về API và database. Bạn đã dùng ngôn ngữ nào?"
    else:
        reply = "Cảm ơn bạn đã chia sẻ. Bạn có thể nói rõ hơn về mục tiêu nghề nghiệp không?"

    return ChatResponse(reply=reply)


@app.get("/health")
def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "services": {
            "processor": "ok",
            "api": "ok"
        }
    }


# ==================== RUN ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0",reload=False,log_level="info",port=8000)
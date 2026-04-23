"""
Shared helpers for API routers.
"""

from typing import Dict, Any, Optional, List


def build_profile_dict(
    user_profile: Dict[str, Any],
    chat_history: Optional[List[Dict[str, Any]]] = None
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
            {
                "role": (
                    msg.get("role", "user")
                    if isinstance(msg, dict)
                    else "user"
                ),
                "text": (
                    msg.get("text", "")
                    if isinstance(msg, dict)
                    else ""
                )
            }
            for msg in (chat_history or [])
            if msg is not None
        ]
    }


def slugify(text: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in text).strip("-")


def icon_for_domain(domain: str) -> str:
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

"""
Input Processing Layer - Core processing logic
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

from backend.schema import ProcessedProfile
from backend.llm_adapter import analyze_with_llm
from backend.taxonomy.facade import taxonomy


# =====================================================
# Reliability Layer (3.3)
# =====================================================

def evaluate_input_quality(processed_dict: dict) -> dict:
    """
    Analyze input quality flags
    """

    flags = {}

    flags["empty_chat"] = not bool(processed_dict.get("chat_summary", "").strip())

    flags["no_skills"] = len(processed_dict.get("skill_tags", [])) == 0

    vague_goals = ["chưa biết", "không rõ", "mơ hồ", "unknown", "none"]
    goal = processed_dict.get("goal_cleaned", "").lower()

    flags["vague_goal"] = any(x in goal for x in vague_goals)

    flags["low_confidence"] = processed_dict.get("confidence_score", 0) < 0.4

    return flags


def assign_confidence_level(score: float) -> str:
    """
    Convert confidence score to level
    """

    if score < 0.4:
        return "LOW"
    elif score < 0.7:
        return "MEDIUM"
    else:
        return "HIGH"


def decide_next_route(confidence_level: str, quality_flags: dict) -> str:
    """
    Decide system route
    """

    if confidence_level == "LOW":
        return "ask_more"

    if quality_flags.get("vague_goal") or quality_flags.get("no_skills"):
        return "ask_more"

    if confidence_level == "MEDIUM":
        return "minimal"

    return "normal"


# =====================================================
# Main Processor
# =====================================================

class InputProcessor:
    """Main processor for user profile data"""

    def __init__(self):
        self.taxonomy = taxonomy


    def normalize_vietnamese(self, text: str) -> str:
        return self.taxonomy.normalize_text(text or "")


    def clean_text(self, text: str) -> str:
        return self.taxonomy.clean_text(text or "")


    def extract_tags(self, text: str, taxonomy: Dict[str, str]) -> List[str]:
        # Legacy wrapper (kept for backward compatibility)
        # Prefer taxonomy facade methods in new code.
        if not text or not taxonomy:
            return []

        resolved = []
        normalized = self.normalize_vietnamese(text)
        cleaned = self.clean_text(text)

        for key, value in taxonomy.items():
            norm_key = self.normalize_vietnamese(key)
            if norm_key and norm_key in normalized:
                resolved.append(value)
                continue
            if key in cleaned:
                resolved.append(value)

        return sorted(set(resolved))


    def detect_intent(self, text: str) -> str:
        # Legacy wrapper (kept for backward compatibility)
        return self.taxonomy.detect_intent(text or "", return_id=True)


    def summarize_chat(self, chat_history: List[Dict[str, str]]) -> str:

        if not chat_history:
            return ""

        user_msgs = [
            msg.get("text", msg.get("message", ""))
            for msg in chat_history
            if msg.get("role", msg.get("sender", "")) == "user"
        ]

        summary = " ".join(user_msgs)

        summary = self.clean_text(summary)

        if len(summary) > 500:
            summary = summary[:500] + "..."

        return summary


    def calculate_confidence(
        self,
        age: int,
        education_level: str,
        interest_tags: List[str],
        skill_tags: List[str],
        goal_cleaned: str,
        chat_summary: str
    ) -> float:

        score = 0.0

        if 0 < age < 100:
            score += 0.1

        if education_level and education_level != "unknown":
            score += 0.15

        if interest_tags:
            score += min(0.20, len(interest_tags) * 0.05)

        if skill_tags:
            score += min(0.25, len(skill_tags) * 0.05)

        if goal_cleaned and len(goal_cleaned) > 10:
            score += 0.20

        if chat_summary and len(chat_summary) > 20:
            score += 0.10

        return round(min(1.0, score), 2)


    def process(self, profile_dict: dict) -> ProcessedProfile:

        personal_info = profile_dict.get("personalInfo", {})

        # Age
        age_str = personal_info.get("age", "0")

        try:
            age = int(age_str)
        except (ValueError, TypeError) as e:
            logger.debug(f"Could not parse age '{age_str}': {e}")
            age = 0


        # Education
        edu_raw = personal_info.get("education", "").lower()
        education_level = self.taxonomy.resolve_education(
            edu_raw,
            return_id=False
        )
        if str(education_level).lower() == "unknown":
            education_level = "unknown"
            logger.warning(f"Unknown education level received: '{edu_raw}' - scoring accuracy may be reduced")


        # Interests
        interests = profile_dict.get("interests", [])
        if not interests:
            logger.warning("Empty interests list received - scoring accuracy may be reduced")

        interest_tags = sorted(self.taxonomy.resolve_interests(
            interests or [],
            return_ids=False
        ))


        # Skills
        skills_raw = profile_dict.get("skills", "")

        skill_tags = sorted(self.taxonomy.resolve_skills(
            skills_raw,
            return_ids=False
        ))


        # Goal
        goal_raw = profile_dict.get("careerGoal", "")

        goal_cleaned = self.clean_text(goal_raw)


        # Intent
        combined = f"{goal_cleaned} {skills_raw}"

        intent = self.taxonomy.detect_intent(combined, return_id=True)


        # Chat
        chat_history = profile_dict.get("chatHistory", [])

        chat_summary = self.summarize_chat(chat_history)


        # Confidence
        confidence = self.calculate_confidence(
            age,
            education_level,
            interest_tags,
            skill_tags,
            goal_cleaned,
            chat_summary
        )


        return ProcessedProfile(
            age=age,
            education_level=education_level,
            interest_tags=interest_tags,
            skill_tags=skill_tags,
            goal_cleaned=goal_cleaned,
            intent=intent,
            chat_summary=chat_summary,
            confidence_score=confidence
        )


# =====================================================
# Public API
# =====================================================

def process_user_profile(profile: dict) -> dict:

    if not isinstance(profile, dict):
        raise ValueError("Profile must be dict")

    processor = InputProcessor()
    processed = processor.process(profile)

    llm_text = (processed.chat_summary or "") + " " + (processed.goal_cleaned or "")

    try:
        llm_features = analyze_with_llm(llm_text) or {}
    except Exception:
        # LLM may be unavailable; fall back to rule-based features
        llm_features = {}

    result = processed.to_dict()

    result["intent"] = llm_features.get("intent") or result["intent"]
    result["main_domains"] = llm_features.get("main_domains", [])
    result["skill_level"] = llm_features.get("skill_level")
    result["motivation_score"] = llm_features.get("motivation_score")
    result["ai_relevance_score"] = llm_features.get("ai_relevance_score")
    result["llm_summary"] = llm_features.get("summary")

    # Quality check
    result["quality_flags"] = evaluate_input_quality(result)

    return result

"""
Data schemas for Input Processing Layer.
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class UserProfile:
    """Raw user profile from frontend"""
    personalInfo: Dict[str, str]
    interests: List[str]
    skills: str
    careerGoal: str
    chatHistory: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class ProcessedProfile:
    """Processed and normalized user profile"""
    age: int
    education_level: str
    interest_tags: List[str]
    skill_tags: List[str]
    goal_cleaned: str
    intent: str
    chat_summary: str
    confidence_score: float

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "age": self.age,
            "education_level": self.education_level,
            "interest_tags": self.interest_tags,
            "skill_tags": self.skill_tags,
            "goal_cleaned": self.goal_cleaned,
            "intent": self.intent,
            "chat_summary": self.chat_summary,
            "confidence_score": self.confidence_score
        }

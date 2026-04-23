"""
Analyze router (extracted from legacy api.py)
"""

from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.processor import process_user_profile


router = APIRouter()


class PersonalInfo(BaseModel):
    fullName: str
    age: str
    education: str


class ChatMessage(BaseModel):
    role: str
    text: str


class UserProfileRequest(BaseModel):
    personalInfo: PersonalInfo
    interests: List[str]
    skills: str
    careerGoal: str
    chatHistory: Optional[List[ChatMessage]] = []


class UserProfileResponse(BaseModel):
    age: int
    education_level: str
    interest_tags: List[str]
    skill_tags: List[str]
    goal_cleaned: str
    intent: str
    chat_summary: str
    confidence_score: float


@router.post("/", response_model=UserProfileResponse)
def analyze_profile(request: UserProfileRequest):
    """
    Analyze user profile and return processed data.
    """
    try:
        profile_dict = {
            "personalInfo": {
                "fullName": request.personalInfo.fullName,
                "age": request.personalInfo.age,
                "education": request.personalInfo.education
            },
            "interests": request.interests,
            "skills": request.skills,
            "careerGoal": request.careerGoal,
            "chatHistory": [
                {"role": msg.role, "text": msg.text}
                for msg in request.chatHistory
            ]
        }

        return process_user_profile(profile_dict)

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing profile: {str(exc)}"
        )

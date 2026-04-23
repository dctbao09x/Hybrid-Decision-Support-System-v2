from backend.processor import process_user_profile


def test_processor_basic_profile():
    profile = {
        "personalInfo": {"fullName": "Test", "age": "18", "education": "THPT"},
        "interests": ["CNTT", "Thiết kế"],
        "skills": "Lập trình Python, tư duy logic",
        "careerGoal": "Muốn làm kỹ sư AI",
        "chatHistory": []
    }
    result = process_user_profile(profile)
    assert result["education_level"] in ["High School", "unknown"]
    assert "Programming" in result["skill_tags"]
    assert result["intent"] in ["learning_intent", "career_intent", "switching_intent", "general"]

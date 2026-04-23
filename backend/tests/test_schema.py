# backend/tests/test_schema.py
"""Unit tests for backend.schema — dataclass models."""

from backend.schema import UserProfile, ProcessedProfile


class TestUserProfile:
    def test_default_chat_history(self):
        p = UserProfile(
            personalInfo={"age": "20"},
            interests=["AI"],
            skills="Python",
            careerGoal="AI Engineer",
        )
        assert p.chatHistory == []

    def test_fields_accessible(self):
        p = UserProfile(
            personalInfo={"age": "25", "education_level": "Master"},
            interests=["Data"],
            skills="SQL, Python",
            careerGoal="Data Scientist",
            chatHistory=[{"role": "user", "text": "hello"}],
        )
        assert p.personalInfo["age"] == "25"
        assert p.interests == ["Data"]
        assert p.skills == "SQL, Python"
        assert p.careerGoal == "Data Scientist"
        assert len(p.chatHistory) == 1

    def test_mutable_default_independent(self):
        a = UserProfile(personalInfo={}, interests=[], skills="", careerGoal="")
        b = UserProfile(personalInfo={}, interests=[], skills="", careerGoal="")
        a.chatHistory.append({"role": "user", "text": "X"})
        assert b.chatHistory == [], "Mutable default must not leak"


class TestProcessedProfile:
    def test_to_dict_returns_all_keys(self):
        pp = ProcessedProfile(
            age=22,
            education_level="Bachelor",
            interest_tags=["ai"],
            skill_tags=["python"],
            goal_cleaned="AI Engineer",
            intent="career_intent",
            chat_summary="toi muon lam ai",
            confidence_score=0.75,
        )
        d = pp.to_dict()
        expected_keys = {
            "age", "education_level", "interest_tags", "skill_tags",
            "goal_cleaned", "intent", "chat_summary", "confidence_score",
        }
        assert set(d.keys()) == expected_keys
        assert d["age"] == 22
        assert d["confidence_score"] == 0.75

    def test_to_dict_values_match(self):
        pp = ProcessedProfile(
            age=0,
            education_level="unknown",
            interest_tags=[],
            skill_tags=[],
            goal_cleaned="",
            intent="general",
            chat_summary="",
            confidence_score=0.0,
        )
        d = pp.to_dict()
        assert d["age"] == 0
        assert d["interest_tags"] == []
        assert d["confidence_score"] == 0.0

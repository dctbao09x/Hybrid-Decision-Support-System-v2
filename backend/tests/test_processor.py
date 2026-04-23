# backend/tests/test_processor.py
"""Unit tests for backend.processor — InputProcessor & helpers."""

from unittest.mock import patch, MagicMock
import pytest

from backend.schema import ProcessedProfile


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# evaluate_input_quality
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestEvaluateInputQuality:
    def _call(self, d):
        from backend.processor import evaluate_input_quality
        return evaluate_input_quality(d)

    def test_all_good(self, processed_profile):
        flags = self._call(processed_profile)
        assert flags["empty_chat"] is False
        assert flags["no_skills"] is False
        assert flags["vague_goal"] is False
        assert flags["low_confidence"] is False

    def test_empty_chat_detected(self, processed_profile):
        processed_profile["chat_summary"] = ""
        flags = self._call(processed_profile)
        assert flags["empty_chat"] is True

    def test_no_skills_detected(self, processed_profile):
        processed_profile["skill_tags"] = []
        flags = self._call(processed_profile)
        assert flags["no_skills"] is True

    def test_vague_goal_vietnamese(self, processed_profile):
        processed_profile["goal_cleaned"] = "chưa biết"
        flags = self._call(processed_profile)
        assert flags["vague_goal"] is True

    def test_vague_goal_partial(self, processed_profile):
        processed_profile["goal_cleaned"] = "tôi không rõ lắm"
        flags = self._call(processed_profile)
        assert flags["vague_goal"] is True

    def test_low_confidence(self, processed_profile):
        processed_profile["confidence_score"] = 0.2
        flags = self._call(processed_profile)
        assert flags["low_confidence"] is True

    def test_medium_confidence_not_low(self, processed_profile):
        processed_profile["confidence_score"] = 0.5
        flags = self._call(processed_profile)
        assert flags["low_confidence"] is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# assign_confidence_level
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestAssignConfidenceLevel:
    def _call(self, score):
        from backend.processor import assign_confidence_level
        return assign_confidence_level(score)

    def test_low(self):
        assert self._call(0.0) == "LOW"
        assert self._call(0.39) == "LOW"

    def test_medium(self):
        assert self._call(0.4) == "MEDIUM"
        assert self._call(0.69) == "MEDIUM"

    def test_high(self):
        assert self._call(0.7) == "HIGH"
        assert self._call(1.0) == "HIGH"

    def test_boundary_04(self):
        assert self._call(0.4) == "MEDIUM"

    def test_boundary_07(self):
        assert self._call(0.7) == "HIGH"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# decide_next_route
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestDecideNextRoute:
    def _call(self, level, flags):
        from backend.processor import decide_next_route
        return decide_next_route(level, flags)

    def test_low_confidence_ask_more(self):
        flags = {"empty_chat": False, "no_skills": False, "vague_goal": False}
        assert self._call("LOW", flags) == "ask_more"

    def test_medium_with_problems_ask_more(self):
        # vague_goal or no_skills => ask_more regardless of confidence
        flags = {"empty_chat": True, "no_skills": True, "vague_goal": True}
        assert self._call("MEDIUM", flags) == "ask_more"

    def test_medium_no_problems_minimal(self):
        flags = {"empty_chat": False, "no_skills": False, "vague_goal": False}
        assert self._call("MEDIUM", flags) == "minimal"

    def test_high_normal(self):
        flags = {"empty_chat": False, "no_skills": False, "vague_goal": False}
        assert self._call("HIGH", flags) == "normal"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# InputProcessor
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestInputProcessor:
    @pytest.fixture
    def proc(self):
        from backend.processor import InputProcessor
        return InputProcessor()

    def test_summarize_chat_user_messages_only(self, proc):
        history = [
            {"role": "user", "text": "Tôi muốn làm AI"},
            {"role": "assistant", "text": "Bạn có kinh nghiệm gì?"},
            {"role": "user", "text": "Python, TensorFlow"},
        ]
        summary = proc.summarize_chat(history)
        assert "toi muon lam ai" in summary.lower() or "python" in summary.lower()

    def test_summarize_chat_sender_key(self, proc):
        history = [
            {"sender": "user", "message": "Hello"},
            {"sender": "bot", "message": "Hi"},
        ]
        summary = proc.summarize_chat(history)
        assert "hello" in summary.lower()

    def test_summarize_chat_truncation(self, proc):
        history = [{"role": "user", "text": "x" * 1000}]
        summary = proc.summarize_chat(history)
        # truncation is summary[:500] + "..." = 503 chars
        assert len(summary) <= 503

    def test_summarize_chat_empty(self, proc):
        assert proc.summarize_chat([]) == ""

    def test_calculate_confidence_full(self, proc):
        score = proc.calculate_confidence(
            age=22,
            education_level="Bachelor",
            interest_tags=["ai", "ml", "dl"],
            skill_tags=["python", "sql", "tf", "pytorch", "numpy"],
            goal_cleaned="become AI Engineer",
            chat_summary="I want to work in AI",
        )
        assert 0.0 <= score <= 1.0
        assert score >= 0.7  # should be HIGH region

    def test_calculate_confidence_empty(self, proc):
        score = proc.calculate_confidence(
            age=0,
            education_level="",
            interest_tags=[],
            skill_tags=[],
            goal_cleaned="",
            chat_summary="",
        )
        assert score == 0.0

    def test_calculate_confidence_capped_at_1(self, proc):
        score = proc.calculate_confidence(
            age=25,
            education_level="PhD",
            interest_tags=["a", "b", "c", "d"],
            skill_tags=["s1", "s2", "s3", "s4", "s5"],
            goal_cleaned="detailed goal here",
            chat_summary="long chat summary with info",
        )
        assert score <= 1.0

    def test_process_returns_processed_profile(self, proc, raw_profile):
        result = proc.process(raw_profile)
        assert isinstance(result, ProcessedProfile)
        assert result.age == 22
        assert isinstance(result.confidence_score, float)

    def test_process_non_numeric_age(self, proc):
        profile = {
            "personalInfo": {"age": "abc"},
            "interests": [],
            "skills": "",
            "careerGoal": "",
            "chatHistory": [],
        }
        result = proc.process(profile)
        assert result.age == 0

    def test_process_missing_keys_graceful(self, proc):
        result = proc.process({})
        assert isinstance(result, ProcessedProfile)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# process_user_profile
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestProcessUserProfile:
    def test_non_dict_raises(self):
        from backend.processor import process_user_profile
        with pytest.raises(ValueError):
            process_user_profile("not a dict")

    def test_non_dict_list_raises(self):
        from backend.processor import process_user_profile
        with pytest.raises(ValueError):
            process_user_profile([1, 2, 3])

    def test_happy_path(self, raw_profile, mock_llm):
        from backend.processor import process_user_profile
        result = process_user_profile(raw_profile)
        assert isinstance(result, dict)
        assert "confidence_score" in result

    def test_llm_failure_graceful(self, raw_profile):
        with patch("backend.processor.analyze_with_llm", side_effect=Exception("LLM down")):
            from backend.processor import process_user_profile
            result = process_user_profile(raw_profile)
            assert isinstance(result, dict)

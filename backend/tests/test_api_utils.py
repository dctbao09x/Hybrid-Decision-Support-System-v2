# backend/tests/test_api_utils.py
"""Unit tests for backend.api.utils — helper functions."""

import pytest
from backend.api.utils import build_profile_dict, slugify, icon_for_domain


class TestBuildProfileDict:
    def test_basic(self):
        # build_profile_dict expects a flat dict with top-level keys
        profile = {"fullName": "Alice", "age": "22", "education": "CS",
                   "interests": ["AI"], "skills": "Python", "careerGoal": "ML"}
        result = build_profile_dict(profile)
        assert isinstance(result, dict)
        assert result["personalInfo"]["age"] == "22"
        assert result["personalInfo"]["fullName"] == "Alice"
        assert result["interests"] == ["AI"]

    def test_chat_history_none(self):
        profile = {"age": "20"}
        result = build_profile_dict(profile, chat_history=None)
        assert isinstance(result, dict)

    def test_chat_history_with_none_items(self):
        profile = {"personalInfo": {}}
        result = build_profile_dict(profile, chat_history=[None, {"role": "user", "text": "hi"}])
        assert isinstance(result, dict)

    def test_chat_history_non_dict_items(self):
        profile = {"personalInfo": {}}
        result = build_profile_dict(profile, chat_history=["bad", 42])
        assert isinstance(result, dict)


class TestSlugify:
    def test_basic(self):
        assert slugify("Hello World") == "hello-world"

    def test_special_chars(self):
        result = slugify("AI & Machine Learning!")
        assert "&" not in result
        assert "!" not in result

    def test_leading_trailing_dashes(self):
        result = slugify("--hello--")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_empty(self):
        assert slugify("") == ""

    def test_unicode(self):
        result = slugify("Trí tuệ nhân tạo")
        assert isinstance(result, str)


class TestIconForDomain:
    def test_known_domains(self):
        assert icon_for_domain("AI") != "💼"
        assert icon_for_domain("Data") != "💼"
        assert icon_for_domain("Software") != "💼"

    def test_unknown_domain_default(self):
        assert icon_for_domain("UnknownDomain123") == "💼"

    def test_case_sensitivity(self):
        # Verify behavior with different cases
        result = icon_for_domain("ai")
        assert isinstance(result, str)

# backend/tests/test_taxonomy_unit.py
"""Unit tests for backend.taxonomy — schema, normalizer, matcher, manager, facade."""

import pytest
from pathlib import Path


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# schema
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestTaxonomySchema:
    def test_taxonomy_entry_frozen(self):
        from backend.taxonomy.schema import TaxonomyEntry
        e = TaxonomyEntry(
            id="s01", canonical_label="Python",
            aliases={"en": ["Python"], "vi": ["Python"]},
            priority=10, deprecated=False,
        )
        with pytest.raises(AttributeError):
            e.id = "s02"

    def test_dataset_frozen(self):
        from backend.taxonomy.schema import TaxonomyEntry, Dataset
        entry = TaxonomyEntry("s01", "Python", {"en": ["Python"]}, 10)
        ds = Dataset(name="skills", entries=[entry])
        assert ds.name == "skills"
        assert len(ds.entries) == 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# normalizer
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestTextNormalizer:
    @pytest.fixture
    def normalizer(self):
        from backend.taxonomy.normalizer import TextNormalizer
        return TextNormalizer()

    def test_clean_text_lowercase(self, normalizer):
        assert normalizer.clean_text("HELLO") == "hello"

    def test_clean_text_strips_special(self, normalizer):
        result = normalizer.clean_text("hello! @world#")
        assert "!" not in result
        assert "@" not in result

    def test_clean_text_keeps_vietnamese(self, normalizer):
        result = normalizer.clean_text("Trí tuệ nhân tạo")
        assert len(result) > 0

    def test_strip_diacritics(self, normalizer):
        result = normalizer.strip_diacritics("Trí tuệ nhân tạo")
        assert "í" not in result.lower()

    def test_normalize(self, normalizer):
        result = normalizer.normalize("  Trí Tuệ  Nhân Tạo!  ")
        assert isinstance(result, str)
        assert result == result.lower()

    def test_normalize_empty(self, normalizer):
        assert normalizer.normalize("") == ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# matcher
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestTaxonomyMatcher:
    @pytest.fixture
    def matcher(self):
        from backend.taxonomy.normalizer import TextNormalizer
        from backend.taxonomy.matcher import TaxonomyMatcher
        return TaxonomyMatcher(TextNormalizer())

    @pytest.fixture
    def entries(self):
        from backend.taxonomy.schema import TaxonomyEntry
        return [
            TaxonomyEntry("py", "Python", {"en": ["Python", "python3"], "vi": ["Python"]}, 10),
            TaxonomyEntry("js", "JavaScript", {"en": ["JavaScript", "JS"], "vi": ["JavaScript"]}, 8),
            TaxonomyEntry("dep", "COBOL", {"en": ["COBOL"]}, 1, deprecated=True),
        ]

    def test_match_exact(self, matcher, entries):
        results = matcher.match_all("Python", entries)
        assert len(results) >= 1
        from backend.taxonomy.matcher import MatchType
        assert any(r.match_type == MatchType.EXACT for r in results)

    def test_deprecated_skipped(self, matcher, entries):
        results = matcher.match_all("COBOL", entries)
        assert len(results) == 0

    def test_select_best(self, matcher, entries):
        results = matcher.match_all("Python", entries)
        best = matcher.select_best(results)
        assert best is not None
        assert best.entry.id == "py"

    def test_select_best_empty(self, matcher):
        assert matcher.select_best([]) is None

    def test_select_unique_entries(self, matcher, entries):
        results = matcher.match_all("Python", entries)
        unique = matcher.select_unique_entries(results)
        ids = [e.id for e in unique]
        assert len(ids) == len(set(ids))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# facade (singleton)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestTaxonomyFacade:
    @pytest.fixture
    def facade(self):
        from backend.taxonomy.facade import taxonomy
        return taxonomy

    def test_self_check(self, facade):
        result = facade.self_check()
        assert isinstance(result, dict)
        assert "skills" in result
        assert "interests" in result
        assert "education" in result
        assert "intents" in result

    def test_coverage_report(self, facade):
        report = facade.coverage_report()
        assert isinstance(report, dict)
        for ds in ("skills", "interests", "education"):
            assert ds in report

    def test_normalize_text(self, facade):
        result = facade.normalize_text("Python Programming")
        assert result == result.lower()

    def test_clean_text(self, facade):
        result = facade.clean_text("Hello! World@")
        assert "!" not in result

    def test_resolve_skills(self, facade):
        result = facade.resolve_skills("python")
        assert isinstance(result, list)

    def test_resolve_skill_list(self, facade):
        result = facade.resolve_skill_list(["Python", "SQL"])
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_resolve_interest_list(self, facade):
        result = facade.resolve_interest_list(["AI", "Machine Learning"])
        assert isinstance(result, list)

    def test_resolve_education(self, facade):
        result = facade.resolve_education("Bachelor")
        assert isinstance(result, str)

    def test_resolve_education_unknown(self, facade):
        result = facade.resolve_education("xyzunknown123")
        assert isinstance(result, str)

    def test_detect_intent(self, facade):
        result = facade.detect_intent("Tôi muốn tìm việc")
        assert isinstance(result, str)

    def test_legacy_taxonomy_map(self, facade):
        result = facade.legacy_taxonomy_map("skills")
        assert isinstance(result, dict)

    def test_legacy_intent_keywords(self, facade):
        result = facade.legacy_intent_keywords()
        assert isinstance(result, dict)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# validate
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestTaxonomyValidate:
    def test_startup_check(self):
        from backend.taxonomy.validate import startup_check
        result = startup_check()
        assert isinstance(result, dict)
        assert all(v > 0 for v in result.values())

    def test_coverage_report(self):
        from backend.taxonomy.validate import coverage_report
        result = coverage_report()
        assert isinstance(result, dict)

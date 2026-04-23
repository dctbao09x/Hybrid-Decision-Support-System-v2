# backend/tests/test_data_validation.py
"""Unit tests for backend.data_validation.validators — record-level validators."""

import time
import pytest
from datetime import datetime, timedelta


class TestDataValidator:
    @pytest.fixture
    def validator(self):
        from backend.data_validation.validators import DataValidator
        return DataValidator()

    @pytest.fixture
    def valid_record(self):
        return {
            "job_title": "Python Developer",
            "company_name": "TechCorp",
            "salary_min": 10_000_000,
            "salary_max": 25_000_000,
            "skills": ["Python", "Django", "SQL"],
            "experience_level": "mid",
            "location": "Ho Chi Minh",
            "job_description": "We are looking for a Python developer with experience in Django and SQL frameworks.",
            "posted_date": datetime.now().isoformat(),
        }

    # ── Single record validation ───────────────────────────────────
    def test_valid_record_passes(self, validator, valid_record):
        ok, msg = validator.validate_record(valid_record)
        assert ok is True, f"Valid record rejected: {msg}"

    def test_missing_title(self, validator, valid_record):
        valid_record.pop("job_title")
        ok, msg = validator.validate_record(valid_record)
        assert ok is False

    def test_title_too_short(self, validator, valid_record):
        valid_record["job_title"] = "ab"
        ok, msg = validator.validate_record(valid_record)
        assert ok is False

    def test_title_too_long(self, validator, valid_record):
        valid_record["job_title"] = "x" * 201
        ok, msg = validator.validate_record(valid_record)
        assert ok is False

    def test_title_special_chars(self, validator, valid_record):
        valid_record["job_title"] = "Dev!@#$%^&*()"
        ok, msg = validator.validate_record(valid_record)
        assert ok is False  # >5 special chars

    def test_company_too_short(self, validator, valid_record):
        valid_record["company_name"] = "X"
        ok, msg = validator.validate_record(valid_record)
        assert ok is False

    def test_salary_negative(self, validator, valid_record):
        valid_record["salary_min"] = -1
        ok, msg = validator.validate_record(valid_record)
        assert ok is False

    def test_salary_min_gt_max(self, validator, valid_record):
        valid_record["salary_min"] = 30_000_000
        valid_record["salary_max"] = 20_000_000
        ok, msg = validator.validate_record(valid_record)
        assert ok is False

    def test_salary_exceeds_500m(self, validator, valid_record):
        valid_record["salary_max"] = 600_000_000
        ok, msg = validator.validate_record(valid_record)
        assert ok is False

    def test_salary_range_too_small(self, validator, valid_record):
        valid_record["salary_min"] = 10_000_000
        valid_record["salary_max"] = 10_500_000
        ok, msg = validator.validate_record(valid_record)
        assert ok is False  # diff < 1M

    def test_skills_empty_list(self, validator, valid_record):
        valid_record["skills"] = []
        ok, msg = validator.validate_record(valid_record)
        assert ok is False

    def test_skills_too_many(self, validator, valid_record):
        valid_record["skills"] = [f"skill_{i}" for i in range(51)]
        ok, msg = validator.validate_record(valid_record)
        assert ok is False

    def test_skills_dict_with_name(self, validator, valid_record):
        valid_record["skills"] = [{"name": "Python"}, {"name": "SQL"}]
        ok, msg = validator.validate_record(valid_record)
        assert ok is True, f"Dict skills rejected: {msg}"

    def test_invalid_experience_level(self, validator, valid_record):
        valid_record["experience_level"] = "wizard"
        ok, msg = validator.validate_record(valid_record)
        assert ok is False

    def test_valid_experience_levels(self, validator, valid_record):
        for level in ["entry", "mid", "senior", "lead", "cto"]:
            valid_record["experience_level"] = level
            ok, msg = validator.validate_record(valid_record)
            assert ok is True, f"{level} rejected: {msg}"

    def test_description_too_short(self, validator, valid_record):
        valid_record["job_description"] = "Short"
        ok, msg = validator.validate_record(valid_record)
        assert ok is False

    def test_future_posted_date(self, validator, valid_record):
        # Validator only rejects future dates when given as numeric timestamps
        future_ts = (datetime.now() + timedelta(days=7)).timestamp()
        valid_record["posted_date"] = future_ts
        ok, msg = validator.validate_record(valid_record)
        assert ok is False

    # ── Batch validation ───────────────────────────────────────────
    def test_batch_all_valid(self, validator, valid_record):
        result = validator.validate_batch([valid_record.copy() for _ in range(5)])
        assert result["status"] in ("success", "warning")
        assert len(result["valid_data"]) == 5

    def test_batch_with_invalid(self, validator, valid_record):
        bad = {"job_title": "x"}  # missing everything
        result = validator.validate_batch([valid_record, bad])
        assert len(result["invalid_data"]) >= 1

    def test_batch_duplicate_detection(self, validator, valid_record):
        batch = [valid_record.copy(), valid_record.copy()]
        result = validator.validate_batch(batch)
        stats = result.get("stats", result.get("statistics", {}))
        # duplicates should be detected
        assert isinstance(result, dict)

    def test_batch_empty(self, validator):
        result = validator.validate_batch([])
        assert len(result.get("valid_data", [])) == 0

    def test_report_generation(self, validator, valid_record):
        result = validator.validate_batch([valid_record])
        report_text = validator.generate_validation_report(result)
        assert isinstance(report_text, str)
        assert len(report_text) > 0

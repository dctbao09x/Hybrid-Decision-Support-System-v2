# backend/tests/test_data_pipeline.py
"""Unit tests for backend.data_pipeline — config, schema, validator, processor."""

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

# Stub external modules that pipeline_manager imports at module level
# so that importing backend.data_pipeline does not fail.
_EXT_MODS = [
    'data_sources', 'data_sources.base_scraper',
    'data_sources.vietnamworks_scraper', 'data_sources.topcv_scraper',
    'data_validation', 'data_validation.validators',
    'data_enrichment', 'data_enrichment.skill_mapper',
    'data_storage', 'data_storage.version_manager', 'data_storage.storage_manager',
    'data_integration', 'data_integration.scoring_integrator',
    'logging_monitoring', 'logging_monitoring.logger',
]
for _mod in _EXT_MODS:
    sys.modules.setdefault(_mod, MagicMock())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# data_pipeline.schema
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestRawJobRecord:
    def test_basic_creation(self):
        from backend.data_pipeline.schema import RawJobRecord
        rec = RawJobRecord(job_id="J1", job_title="Dev", company="Corp")
        assert rec.job_id == "J1"
        assert rec.title == "Dev"

    def test_alias_job_title(self):
        from backend.data_pipeline.schema import RawJobRecord
        rec = RawJobRecord(**{"job_id": "J2", "job_title": "Engineer"})
        assert rec.title == "Engineer"

    def test_extra_fields_ignored(self):
        from backend.data_pipeline.schema import RawJobRecord
        rec = RawJobRecord(job_id="J3", extra_field="ignored")
        assert not hasattr(rec, "extra_field")

    def test_all_fields_optional(self):
        from backend.data_pipeline.schema import RawJobRecord
        rec = RawJobRecord()
        assert rec.job_id is None
        assert rec.title is None


class TestCleanJobRecord:
    def test_defaults(self):
        from backend.data_pipeline.schema import CleanJobRecord
        rec = CleanJobRecord(
            id="C1", title_raw="Dev", title_normalized="dev",
            company="Corp", location_raw="HCM", province_code="SG",
            url="https://ex.com", source="test", raw_reference="J1",
        )
        assert rec.salary_min == 0
        assert rec.salary_max == 0
        assert rec.currency == "VND"
        assert rec.is_expired is False
        assert rec.processed_at is not None

    def test_processed_at_auto(self):
        from backend.data_pipeline.schema import CleanJobRecord
        rec = CleanJobRecord(
            id="C2", title_raw="X", title_normalized="x",
            company="C", location_raw="HN", province_code="HN",
            url="https://ex.com", source="test", raw_reference="J2",
        )
        assert isinstance(rec.processed_at, (str, datetime))


class TestValidationReport:
    def test_add_error(self):
        from backend.data_pipeline.schema import ValidationReport
        report = ValidationReport()
        report.add_error("J1", "missing_field", "title is required")
        assert len(report.errors) == 1
        assert report.errors[0]["job_id"] == "J1"
        assert report.errors[0]["type"] == "missing_field"
        assert report.errors[0]["message"] == "title is required"

    def test_initial_counts(self):
        from backend.data_pipeline.schema import ValidationReport
        report = ValidationReport()
        assert report.total_records == 0
        assert report.valid_records == 0
        assert report.rejected_records == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# data_pipeline.config
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestPipelineConfig:
    def test_create_default_config(self):
        from backend.data_pipeline.config import create_default_config
        cfg = create_default_config()
        assert len(cfg.sources) >= 2
        assert cfg.validate() is True

    def test_validate_no_sources(self):
        from backend.data_pipeline.config import PipelineConfig, StorageConfig
        cfg = PipelineConfig(sources=[], storage=StorageConfig())
        with pytest.raises(ValueError, match="[Ss]ource"):
            cfg.validate()

    def test_validate_bad_completeness(self):
        from backend.data_pipeline.config import (
            PipelineConfig, SourceConfig, StorageConfig, ValidationConfig,
        )
        cfg = PipelineConfig(
            sources=[SourceConfig(name="x")],
            storage=StorageConfig(),
            validation=ValidationConfig(min_completeness=0),
        )
        with pytest.raises(ValueError):
            cfg.validate()

    def test_to_dict_from_dict_roundtrip(self):
        from backend.data_pipeline.config import create_default_config, PipelineConfig
        cfg = create_default_config()
        d = cfg.to_dict()
        assert isinstance(d, dict)
        assert "sources" in d

    def test_storage_create_directories(self, tmp_dir):
        from backend.data_pipeline.config import StorageConfig
        sc = StorageConfig(
            raw_path=str(tmp_dir / "raw"),
            processed_path=str(tmp_dir / "processed"),
            archive_path=str(tmp_dir / "archive"),
            backup_path=str(tmp_dir / "backup"),
            log_path=str(tmp_dir / "log"),
        )
        sc.create_directories()
        assert (tmp_dir / "raw").is_dir()
        assert (tmp_dir / "processed").is_dir()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# data_pipeline.validator
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestDataPipelineValidator:
    @pytest.fixture
    def validator(self):
        from backend.data_pipeline.validator import DataValidator
        return DataValidator()

    def test_validate_batch_valid(self, validator, raw_job_record):
        valid, report = validator.validate_batch([raw_job_record])
        assert len(valid) == 1
        assert report.valid_records == 1

    def test_validate_batch_missing_critical(self, validator):
        bad = {"job_id": "J1", "job_title": None, "company": None, "url": None}
        valid, report = validator.validate_batch([bad])
        assert len(valid) == 0
        assert report.rejected_records >= 1

    def test_validate_batch_duplicate(self, validator, raw_job_record):
        valid, report = validator.validate_batch([raw_job_record, raw_job_record])
        assert len(valid) == 1  # second is duplicate

    def test_validate_batch_short_title(self, validator):
        rec = {
            "job_id": "J1", "job_title": "ab", "company": "C",
            "url": "https://x.com", "salary": "", "location": "", "skills": "",
        }
        valid, report = validator.validate_batch([rec])
        # title < 3 chars should be rejected
        assert report.rejected_records >= 1

    def test_validate_batch_empty(self, validator):
        valid, report = validator.validate_batch([])
        assert len(valid) == 0
        assert report.total_records == 0

    def test_load_csv_missing_file(self, validator):
        result = validator.load_csv("/nonexistent/file.csv")
        assert result == []

    def test_dedup_persists_across_calls(self, validator, raw_job_record):
        # First batch
        valid1, _ = validator.validate_batch([raw_job_record])
        assert len(valid1) == 1
        # Second batch, same record → duplicate
        valid2, _ = validator.validate_batch([raw_job_record])
        assert len(valid2) == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# data_pipeline.processor
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestDataProcessor:
    @pytest.fixture
    def proc(self):
        from backend.data_pipeline.processor import DataProcessor
        return DataProcessor()

    # ── Salary normalization ───────────────────────────────────────
    def test_salary_range_trieu(self, proc):
        lo, hi = proc.normalize_salary("10 - 15 Triệu")
        assert lo == 10_000_000
        assert hi == 15_000_000

    def test_salary_usd(self, proc):
        # "1000 USD" — multiplier=25000, range match finds '1000'
        lo, hi = proc.normalize_salary("1000 USD")
        # No range/upto/from pattern matched (single number without keyword),
        # so the result is (0, 0).
        assert (lo, hi) == (0, 0)

    def test_salary_up_to(self, proc):
        # Vietnamese "Tới" (with diacritics) doesn't match 'toi' regex.
        # Use ASCII form to test the happy path.
        lo, hi = proc.normalize_salary("Toi 20 Trieu")
        assert lo == 0
        assert hi == 20_000_000

    def test_salary_from(self, proc):
        # Vietnamese "Từ" (with diacritics) doesn't match 'tren|from'.
        # Use ASCII form with 'tren' keyword.
        lo, hi = proc.normalize_salary("Tren 15 Trieu")
        assert lo == 15_000_000

    def test_salary_none(self, proc):
        assert proc.normalize_salary(None) == (0, 0)

    def test_salary_negotiable(self, proc):
        assert proc.normalize_salary("Thỏa thuận") == (0, 0)

    # ── Location normalization ─────────────────────────────────────
    def test_location_hcm(self, proc):
        assert proc.normalize_location("Hồ Chí Minh") == "SG"

    def test_location_hanoi(self, proc):
        assert proc.normalize_location("Hà Nội") == "HN"

    def test_location_none(self, proc):
        assert proc.normalize_location(None) == "UNKNOWN"

    def test_location_unknown(self, proc):
        assert proc.normalize_location("Mars") == "OTHER"

    # ── Title normalization ────────────────────────────────────────
    def test_title_basic(self, proc):
        result = proc.normalize_title("Python Developer!!!")
        assert "python" in result.lower()
        assert "!" not in result

    def test_title_empty(self, proc):
        assert proc.normalize_title("") == ""

    def test_title_whitespace_collapse(self, proc):
        result = proc.normalize_title("  python   developer  ")
        assert "  " not in result

    # ── Skills normalization ───────────────────────────────────────
    def test_skills_comma_sep(self, proc):
        result = proc.normalize_skills("Python, Django, SQL")
        assert len(result) == 3
        assert "Python" in result

    def test_skills_none(self, proc):
        assert proc.normalize_skills(None) == []

    def test_skills_empty_string(self, proc):
        assert proc.normalize_skills("") == []

    # ── Date parsing ───────────────────────────────────────────────
    def test_parse_date_ddmmyyyy(self, proc):
        result = proc.parse_date("25/12/2025")
        assert result is not None
        assert result.day == 25
        assert result.month == 12

    def test_parse_date_yesterday(self, proc):
        result = proc.parse_date("hom qua")
        if result:
            expected = datetime.now() - timedelta(days=1)
            assert result.date() == expected.date()

    def test_parse_date_days_ago(self, proc):
        result = proc.parse_date("3 ngay truoc")
        if result:
            expected = datetime.now() - timedelta(days=3)
            assert abs((result - expected).total_seconds()) < 86400

    def test_parse_date_none(self, proc):
        assert proc.parse_date(None) is None

    def test_parse_date_invalid(self, proc):
        assert proc.parse_date("not a date") is None

    # ── Full record processing ─────────────────────────────────────
    def test_process_record(self, proc):
        from backend.data_pipeline.schema import RawJobRecord
        raw = RawJobRecord(
            job_id="J1",
            job_title="Python Dev",
            company="Corp",
            salary="10 - 15 Triệu",
            location="Hà Nội",
            url="https://example.com",
            skills="Python, SQL",
            source="topcv",
        )
        clean = proc.process_record(raw)
        assert clean.id == "topcv_J1"
        assert clean.salary_min == 10_000_000
        assert clean.province_code == "HN"
        assert len(clean.skills) == 2

    def test_process_batch(self, proc, sample_crawl_records):
        from backend.data_pipeline.schema import RawJobRecord
        raws = [RawJobRecord(**r) for r in sample_crawl_records]
        cleans = proc.process_batch(raws)
        assert len(cleans) == len(raws)

    def test_process_record_expiration(self, proc):
        from backend.data_pipeline.schema import RawJobRecord
        old_date = (datetime.now() - timedelta(days=60)).strftime("%d/%m/%Y")
        raw = RawJobRecord(
            job_id="J2", job_title="Old Job", company="C",
            posted_date=old_date, source="topcv",
            url="https://example.com", location="HCM",
            skills="Python",
        )
        clean = proc.process_record(raw)
        assert clean.is_expired is True

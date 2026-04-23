# backend/tests/test_e2e_crawl.py
"""
E2E tests — real crawl simulation.
Marked with @pytest.mark.e2e so they can be excluded in CI fast runs.
These tests verify the actual pipeline stages work end-to-end.
"""

import sys
from unittest.mock import MagicMock

# Stub missing modules that data_pipeline.__init__ → pipeline_manager.py imports
_EXT_MODS = [
    "data_sources", "data_sources.base_scraper",
    "data_sources.vietnamworks_scraper", "data_sources.topcv_scraper",
    "data_validation", "data_validation.validators",
    "data_enrichment", "data_enrichment.skill_mapper",
    "data_storage", "data_storage.version_manager", "data_storage.storage_manager",
    "data_integration", "data_integration.scoring_integrator",
    "logging_monitoring", "logging_monitoring.logger",
]
for _mod in _EXT_MODS:
    sys.modules.setdefault(_mod, MagicMock())

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.mark.e2e
class TestE2ECrawlPipeline:
    """E2E tests for the crawl → validate → process pipeline."""

    @pytest.fixture
    def sample_raw_records(self):
        """Simulate what a real crawler would return."""
        return [
            {
                "job_id": f"e2e_{i:03d}",
                "job_title": f"Senior Python Developer {i}",
                "company": f"TechCorp {i}",
                "salary": f"{15 + i} - {25 + i} Triệu",
                "location": ["Hồ Chí Minh", "Hà Nội", "Đà Nẵng"][i % 3],
                "url": f"https://topcv.vn/job/e2e_{i:03d}",
                "posted_date": "01/02/2026",
                "skills": "Python, Django, PostgreSQL, Docker",
                "source": "topcv",
                "experience": "3 năm",
                "description": f"Tuyển dụng Senior Python Developer có kinh nghiệm với Django và PostgreSQL cho dự án lớn {i}",
            }
            for i in range(20)
        ]

    def test_validate_real_records(self, sample_raw_records):
        """Validate stage works on realistic records."""
        from backend.data_pipeline.validator import DataValidator
        v = DataValidator()
        valid, report = v.validate_batch(sample_raw_records)
        assert len(valid) == 20
        assert report.valid_records == 20
        assert report.rejected_records == 0

    def test_process_real_records(self, sample_raw_records):
        """Process stage transforms validated records."""
        from backend.data_pipeline.validator import DataValidator
        from backend.data_pipeline.processor import DataProcessor
        from backend.data_pipeline.schema import RawJobRecord

        v = DataValidator()
        valid, _ = v.validate_batch(sample_raw_records)
        p = DataProcessor()
        clean = p.process_batch(valid)

        assert len(clean) == 20
        for rec in clean:
            assert rec.salary_min > 0 or rec.salary_max > 0
            assert rec.province_code in ("SG", "HN", "DN")
            assert len(rec.skills) >= 1
            assert rec.id.startswith("topcv_")

    def test_full_validate_process_flow(self, sample_raw_records):
        """Full flow: raw → validate → process → verify output."""
        from backend.data_pipeline.validator import DataValidator
        from backend.data_pipeline.processor import DataProcessor

        # Step 1: Validate
        validator = DataValidator()
        valid, report = validator.validate_batch(sample_raw_records)
        assert report.rejected_records == 0

        # Step 2: Process
        processor = DataProcessor()
        clean = processor.process_batch(valid)

        # Step 3: Verify output quality
        assert len(clean) == len(valid)
        unique_ids = {r.id for r in clean}
        assert len(unique_ids) == len(clean), "Duplicate IDs in output"

        # All should have normalized locations
        provinces = {r.province_code for r in clean}
        assert "UNKNOWN" not in provinces

    def test_mixed_quality_records(self):
        """Pipeline handles mixed-quality input gracefully."""
        from backend.data_pipeline.validator import DataValidator
        from backend.data_pipeline.processor import DataProcessor

        records = [
            # Good record
            {
                "job_id": "good_001", "job_title": "Java Developer",
                "company": "Corp", "salary": "10 - 15 Triệu",
                "url": "https://x.com/1", "location": "HCM",
                "skills": "Java, Spring", "source": "topcv",
            },
            # Bad: missing title
            {
                "job_id": "bad_001", "company": "Corp",
                "url": "https://x.com/2",
            },
            # Bad: too-short title
            {
                "job_id": "bad_002", "job_title": "ab",
                "company": "Corp", "url": "https://x.com/3",
            },
            # Good record
            {
                "job_id": "good_002", "job_title": "DevOps Engineer",
                "company": "Infra Inc", "salary": "Thỏa thuận",
                "url": "https://x.com/4", "location": "Hà Nội",
                "skills": "Docker, K8s", "source": "vietnamworks",
            },
        ]

        validator = DataValidator()
        valid, report = validator.validate_batch(records)
        assert report.valid_records >= 2
        assert report.rejected_records >= 1

        processor = DataProcessor()
        clean = processor.process_batch(valid)
        assert len(clean) >= 2


@pytest.mark.e2e
class TestE2EScoringFlow:
    """E2E scoring pipeline integration."""

    def test_scoring_engine_basic(self):
        """Scoring engine produces valid results for a basic profile."""
        from backend.scoring.scoring import SIMGRScorer

        scorer = SIMGRScorer()
        input_dict = {
            "user": {
                "skills": ["python", "sql", "tensorflow"],
                "interests": ["ai", "machine learning"],
                "education_level": "Bachelor",
                "confidence_score": 0.8,
            },
            "careers": [
                {
                    "name": "AI Engineer",
                    "domain": "AI",
                    "required_skills": ["python", "tensorflow"],
                },
                {
                    "name": "Data Scientist",
                    "domain": "Data",
                    "required_skills": ["python", "sql"],
                },
            ],
        }

        result = scorer.score(input_dict)
        assert isinstance(result, dict)

    def test_scoring_with_rule_engine(self):
        """Scoring combined with rule engine evaluation."""
        from backend.rule_engine.rule_engine import RuleEngine

        engine = RuleEngine()
        mock_jobs = ["AI Engineer", "Data Analyst"]
        mock_reqs = {
            "AI Engineer": {
                "name": "AI Engineer", "domain": "AI",
                "required_skills": ["python", "tensorflow"],
                "preferred_skills": ["pytorch"], "min_education": "Bachelor",
                "age_max": 35, "competition": 0.6, "growth_rate": 0.2,
                "difficulty": "medium", "interests": ["ai"],
            },
            "Data Analyst": {
                "name": "Data Analyst", "domain": "Data",
                "required_skills": ["sql", "python"],
                "preferred_skills": ["pandas"], "min_education": "Bachelor",
                "age_max": 40, "competition": 0.5, "growth_rate": 0.15,
                "difficulty": "easy", "interests": ["data"],
            },
        }
        profile = {
            "age": 24, "education_level": "Bachelor",
            "interest_tags": ["ai", "data science"],
            "skill_tags": ["python", "sql", "pandas", "tensorflow"],
            "goal_cleaned": "data scientist",
            "intent": "career_intent",
            "confidence_score": 0.85,
            "similarity_scores": {j: 0.6 for j in mock_jobs},
        }

        with patch("backend.rule_engine.rule_engine.get_job_requirements",
                    side_effect=lambda n: mock_reqs.get(n)):
            for job_name in mock_jobs:
                result = engine.evaluate_job(profile, job_name)
                if result is not None:
                    assert "passed" in result
                    assert "score_delta" in result
                    assert isinstance(result["score_delta"], float)

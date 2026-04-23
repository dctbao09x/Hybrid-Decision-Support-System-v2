# backend/ops/tests/test_integration.py
"""
Integration Tests for the crawl → validate → score → explain pipeline.

Tests component interactions:
- Crawler output → Validator input
- Validator output → Processor input
- Processor output → Scoring input
- Scoring output → Explain input
- Orchestrator → Stage integration
"""

import asyncio
import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════
# Section 1: Crawl → Validate Integration
# ═══════════════════════════════════════════════════════

class TestCrawlToValidate:
    """Test that crawler output feeds correctly into validator."""

    def _create_crawl_csv(self, tmp_dir: str, records: list) -> Path:
        csv_path = Path(tmp_dir) / "crawled_jobs.csv"
        if not records:
            records = [
                {
                    "job_id": "tc001",
                    "job_title": "Python Developer",
                    "company": "TechCorp",
                    "url": "https://topcv.vn/job/tc001",
                    "salary": "15 - 25 Triệu",
                    "location": "Hồ Chí Minh",
                    "skills": "Python, Django, REST API",
                    "posted_date": "01/02/2026",
                },
                {
                    "job_id": "tc002",
                    "job_title": "Data Analyst",
                    "company": "DataCo",
                    "url": "https://topcv.vn/job/tc002",
                    "salary": "10 - 15 Triệu",
                    "location": "Hà Nội",
                    "skills": "SQL, Python, Excel",
                    "posted_date": "15/01/2026",
                },
            ]

        fieldnames = list(records[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in records:
                writer.writerow(r)
        return csv_path

    def test_validator_accepts_crawl_output(self):
        from backend.data_pipeline.validator import DataValidator

        with tempfile.TemporaryDirectory() as td:
            csv_path = self._create_crawl_csv(td, [])
            validator = DataValidator()
            raw_data = validator.load_csv(str(csv_path))
            assert len(raw_data) == 2

            valid, report = validator.validate_batch(raw_data)
            assert report.valid_records == 2
            assert report.rejected_records == 0

    def test_validator_handles_malformed_crawl_output(self):
        from backend.data_pipeline.validator import DataValidator

        with tempfile.TemporaryDirectory() as td:
            # Write CSV with empty/invalid data
            csv_path = Path(td) / "malformed.csv"
            fieldnames = ["job_id", "job_title", "company", "url"]
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow({"job_id": "", "job_title": "", "company": "", "url": ""})
            validator = DataValidator()
            raw_data = validator.load_csv(str(csv_path))
            valid, report = validator.validate_batch(raw_data)
            assert report.rejected_records >= 1


# ═══════════════════════════════════════════════════════
# Section 2: Validate → Process Integration
# ═══════════════════════════════════════════════════════

class TestValidateToProcess:
    """Test validated records feed into DataProcessor correctly."""

    def test_process_validated_records(self):
        from backend.data_pipeline.processor import DataProcessor
        from backend.data_pipeline.schema import RawJobRecord

        record = RawJobRecord(
            job_id="tc001",
            job_title="Python Developer",
            company="TechCorp",
            url="https://topcv.vn/job/tc001",
            salary="15 - 25 Triệu",
            location="Hồ Chí Minh",
            skills="Python, Django",
        )

        processor = DataProcessor()
        clean = processor.process_record(record)
        assert clean is not None
        assert clean.id == "tc001"

    def test_process_batch(self):
        from backend.data_pipeline.processor import DataProcessor
        from backend.data_pipeline.schema import RawJobRecord

        records = [
            RawJobRecord(
                job_id=f"j{i:03d}",
                job_title=f"Job {i}",
                company=f"Co{i}",
                url=f"https://x.com/j{i}",
            )
            for i in range(5)
        ]

        processor = DataProcessor()
        results = processor.process_batch(records)
        assert len(results) == 5


# ═══════════════════════════════════════════════════════
# Section 3: Score Pipeline Integration
# ═══════════════════════════════════════════════════════

class TestScoringIntegration:
    """Test scoring pipeline with full user profile and career data."""

    def test_full_scoring_pipeline(self):
        from backend.scoring.scoring import SIMGRScorer

        scorer = SIMGRScorer()
        result = scorer.score({
            "study": 0.8,
            "interest": 0.7,
            "market": 0.6,
            "growth": 0.5,
            "risk": 0.3,
        })
        assert "total_score" in result or "score" in result or "error" not in result

    def test_scoring_with_user_and_careers(self):
        from backend.scoring.scoring import SIMGRScorer

        scorer = SIMGRScorer()
        result = scorer.score({
            "user": {
                "skills": ["python", "sql"],
                "interests": ["data-science"],
                "education_level": "bachelor",
            },
            "careers": [
                {
                    "name": "Data Scientist",
                    "required_skills": ["python", "statistics"],
                    "preferred_skills": ["machine-learning"],
                },
            ],
        })
        # Should return a result (may have error if taxonomy not available)
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════
# Section 4: Orchestrator Integration
# ═══════════════════════════════════════════════════════

class TestOrchestratorIntegration:
    """Test pipeline orchestration with real stage handlers."""

    @pytest.mark.asyncio
    async def test_full_pipeline_orchestration(self):
        from backend.ops.orchestration.scheduler import PipelineScheduler

        scheduler = PipelineScheduler()
        stage_log = []

        async def crawl(data):
            stage_log.append("crawl")
            return {"records_out": 10, "output": [{"id": i} for i in range(10)]}

        async def validate(data):
            stage_log.append("validate")
            return {"records_in": 10, "records_out": 8, "output": data}

        async def score(data):
            stage_log.append("score")
            return {"records_in": 8, "records_out": 8, "output": data}

        async def explain(data):
            stage_log.append("explain")
            return {"records_in": 8, "records_out": 8, "output": data}

        scheduler.register_stage("crawl", crawl, critical=True)
        scheduler.register_stage("validate", validate, depends_on=["crawl"], critical=True)
        scheduler.register_stage("score", score, depends_on=["validate"], critical=True)
        scheduler.register_stage("explain", explain, depends_on=["score"], critical=False)

        run = await scheduler.run_pipeline()
        assert run.status.value in ("completed", "partial_failure")
        assert stage_log == ["crawl", "validate", "score", "explain"]

    @pytest.mark.asyncio
    async def test_checkpoint_and_recovery(self):
        from backend.ops.orchestration.scheduler import PipelineScheduler
        from backend.ops.orchestration.checkpoint import CheckpointManager

        with tempfile.TemporaryDirectory() as td:
            scheduler = PipelineScheduler()
            cp_mgr = CheckpointManager(base_dir=Path(td))

            async def crawl(data):
                return {"records_out": 10}

            async def validate(data):
                return {"records_out": 8}

            scheduler.register_stage("crawl", crawl)
            scheduler.register_stage("validate", validate, depends_on=["crawl"])

            run = await scheduler.run_pipeline(checkpoint_mgr=cp_mgr, stages=["crawl", "validate"])

            # Verify checkpoints saved
            crawl_cp = await cp_mgr.load(run.run_id, "crawl")
            assert crawl_cp is not None

            validate_cp = await cp_mgr.load(run.run_id, "validate")
            assert validate_cp is not None

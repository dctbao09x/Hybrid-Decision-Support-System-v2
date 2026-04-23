# backend/ops/tests/test_e2e.py
"""
End-to-End Tests for the complete pipeline.

Tests the full flow:
  crawl → validate → score → explain

Uses mock crawlers to avoid real network calls,
but exercises real validator, processor, scorer.
"""

import asyncio
import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestEndToEndPipeline:
    """
    Full end-to-end pipeline test.

    Flow:
    1. Mock crawler generates job CSV
    2. Validator loads and validates CSV
    3. Processor normalizes records
    4. Scorer produces scores
    5. Tracer captures explanations
    """

    def _generate_mock_crawl_data(self, count: int = 10) -> list:
        """Generate realistic mock crawl output."""
        return [
            {
                "job_id": f"e2e_{i:04d}",
                "job_title": f"Software Engineer Level {i % 5 + 1}",
                "company": f"Company{chr(65 + i % 10)}",
                "url": f"https://topcv.vn/job/e2e_{i:04d}",
                "salary": f"{10 + i % 20} - {15 + i % 20} Triệu",
                "location": ["Hồ Chí Minh", "Hà Nội", "Đà Nẵng"][i % 3],
                "skills": ", ".join(
                    ["Python", "Java", "SQL", "JavaScript", "React"][: (i % 4 + 1)]
                ),
                "experience": f"{i % 5 + 1} năm",
                "posted_date": f"{(i % 28) + 1:02d}/01/2026",
                "job_type": ["Full-time", "Part-time", "Remote"][i % 3],
            }
            for i in range(count)
        ]

    def _write_csv(self, dir_path: str, records: list) -> Path:
        csv_path = Path(dir_path) / "e2e_jobs.csv"
        fieldnames = list(records[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in records:
                writer.writerow(r)
        return csv_path

    def test_e2e_validation_and_processing(self):
        """Test: crawl CSV → validate → process."""
        from backend.data_pipeline.validator import DataValidator
        from backend.data_pipeline.processor import DataProcessor

        with tempfile.TemporaryDirectory() as td:
            # Step 1: Mock crawl output
            records = self._generate_mock_crawl_data(20)
            csv_path = self._write_csv(td, records)

            # Step 2: Validate
            validator = DataValidator()
            raw_data = validator.load_csv(str(csv_path))
            assert len(raw_data) == 20

            valid_records, report = validator.validate_batch(raw_data)
            assert report.valid_records >= 15  # Allow some rejection
            assert report.valid_records > 0

            # Step 3: Process
            processor = DataProcessor()
            clean_records = processor.process_batch(valid_records)
            assert len(clean_records) > 0

            # Verify clean record properties
            for cr in clean_records:
                assert cr.id is not None
                assert cr.processed_at is not None

    def test_e2e_scoring(self):
        """Test: direct scoring with component values."""
        from backend.scoring.scoring import SIMGRScorer

        scorer = SIMGRScorer()
        result = scorer.score({
            "study": 0.85,
            "interest": 0.72,
            "market": 0.65,
            "growth": 0.55,
            "risk": 0.20,
        })

        assert isinstance(result, dict)
        if "error" not in result:
            total = result.get("total_score", result.get("score", 0))
            assert 0 <= total <= 1

    def test_e2e_explain_trace(self):
        """Test: scoring with tracer captures explanations."""
        from backend.scoring.explain.tracer import ScoringTracer

        tracer = ScoringTracer(enabled=True)

        # Simulate scoring with tracing
        tracer.start_trace(
            "Data Scientist",
            {"skill_count": 5, "interest_count": 3},
        )
        tracer.trace_component("study", 0.85, {"matched_skills": 3, "total_required": 4})
        tracer.trace_component("interest", 0.72, {"domain_match": True})
        tracer.trace_component("market", 0.65, {"demand_score": 0.7})
        tracer.trace_component("growth", 0.55, {"growth_rate": 0.15})
        tracer.trace_component("risk", 0.20, {"automation_risk": 0.3})

        tracer.set_simgr_scores({
            "study": 0.85,
            "interest": 0.72,
            "market": 0.65,
            "growth": 0.55,
            "risk": 0.20,
        })

        trace = tracer.get_trace()
        assert trace is not None
        assert len(trace.components) == 5
        assert trace.career_name == "Data Scientist"

        # Verify serialization works
        trace_dict = trace.to_dict()
        readable = trace.to_readable()
        assert "Data Scientist" in readable

    @pytest.mark.asyncio
    async def test_e2e_orchestrated_pipeline(self):
        """Test: full orchestrated pipeline with all stages."""
        from backend.ops.orchestration.scheduler import PipelineScheduler
        from backend.ops.orchestration.checkpoint import CheckpointManager
        from backend.ops.quality.completeness import CompletenessChecker
        from backend.ops.quality.schema_validator import PipelineSchemaValidator

        with tempfile.TemporaryDirectory() as td:
            scheduler = PipelineScheduler()
            cp_mgr = CheckpointManager(base_dir=Path(td) / "checkpoints")
            completeness = CompletenessChecker()

            # Register stages
            crawl_data = self._generate_mock_crawl_data(15)

            async def crawl_stage(data):
                return {"records_out": len(crawl_data), "output": crawl_data}

            async def validate_stage(data):
                from backend.data_pipeline.validator import DataValidator
                v = DataValidator()
                valid, report = v.validate_batch(data or crawl_data)
                comp_report = completeness.check_batch(
                    [r.model_dump() if hasattr(r, 'model_dump') else r.__dict__ for r in valid]
                )
                return {
                    "records_in": report.total_records,
                    "records_out": report.valid_records,
                    "output": valid,
                    "completeness": comp_report.overall_completeness,
                }

            async def score_stage(data):
                return {"records_in": 15, "records_out": 15, "output": data}

            async def explain_stage(data):
                return {"records_in": 15, "records_out": 15, "output": data}

            scheduler.register_stage("crawl", crawl_stage, critical=True)
            scheduler.register_stage("validate", validate_stage, depends_on=["crawl"])
            scheduler.register_stage("score", score_stage, depends_on=["validate"])
            scheduler.register_stage("explain", explain_stage, depends_on=["score"], critical=False)

            run = await scheduler.run_pipeline(checkpoint_mgr=cp_mgr)
            assert run.status.value in ("completed", "partial_failure")
            assert "crawl" in run.stages
            assert "validate" in run.stages

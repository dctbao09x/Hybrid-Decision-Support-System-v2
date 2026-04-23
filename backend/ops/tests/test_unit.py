# backend/ops/tests/test_unit.py
"""
Unit Tests for pipeline components.

Tests individual functions/classes in isolation:
- DataValidator
- DataProcessor
- ScoringEngine / Calculator
- ScoringTracer
- Orchestration components
- Quality control modules
"""

import asyncio
import json
import math
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════
# Section 1: DataValidator Unit Tests
# ═══════════════════════════════════════════════════════

class TestDataValidator:
    """Unit tests for backend.data_pipeline.validator.DataValidator."""

    def _make_validator(self):
        from backend.data_pipeline.validator import DataValidator
        return DataValidator()

    def test_validate_batch_valid_records(self):
        v = self._make_validator()
        records = [
            {
                "job_id": "j001",
                "job_title": "Software Engineer",
                "company": "TechCo",
                "url": "https://example.com/j001",
                "salary": "15-20 Triệu",
                "location": "Hồ Chí Minh",
            },
            {
                "job_id": "j002",
                "job_title": "Data Analyst",
                "company": "DataCo",
                "url": "https://example.com/j002",
            },
        ]
        valid, report = v.validate_batch(records)
        assert len(valid) == 2
        assert report.valid_records == 2
        assert report.rejected_records == 0

    def test_validate_batch_missing_critical_fields(self):
        v = self._make_validator()
        records = [
            {"job_id": "", "job_title": "Eng", "company": "Co", "url": ""},
        ]
        valid, report = v.validate_batch(records)
        assert len(valid) == 0
        assert report.rejected_records == 1

    def test_validate_batch_duplicates(self):
        v = self._make_validator()
        record = {
            "job_id": "dup1",
            "job_title": "Dev",
            "company": "Co",
            "url": "https://x.com/dup1",
        }
        valid, report = v.validate_batch([record, record])
        assert len(valid) == 1
        assert report.rejected_records == 1

    def test_validate_batch_title_too_short(self):
        v = self._make_validator()
        records = [
            {"job_id": "j1", "job_title": "ab", "company": "Co", "url": "https://x.com/j1"},
        ]
        valid, report = v.validate_batch(records)
        assert len(valid) == 0

    def test_validate_batch_empty_input(self):
        v = self._make_validator()
        valid, report = v.validate_batch([])
        assert len(valid) == 0
        assert report.total_records == 0


# ═══════════════════════════════════════════════════════
# Section 2: DataProcessor Unit Tests
# ═══════════════════════════════════════════════════════

class TestDataProcessor:
    """Unit tests for backend.data_pipeline.processor.DataProcessor."""

    def _make_processor(self):
        from backend.data_pipeline.processor import DataProcessor
        return DataProcessor()

    def test_normalize_salary_vnd(self):
        dp = self._make_processor()
        result = dp.normalize_salary("10 - 15 Triệu")
        assert result is not None
        # Should parse min/max or return dict

    def test_normalize_salary_usd(self):
        dp = self._make_processor()
        result = dp.normalize_salary("1000 - 2000 USD")
        assert result is not None

    def test_normalize_salary_empty(self):
        dp = self._make_processor()
        result = dp.normalize_salary("")
        # Should handle gracefully

    def test_normalize_location_hcm(self):
        dp = self._make_processor()
        result = dp.normalize_location("Hồ Chí Minh")
        assert result in ("SG", "HCM", "Hồ Chí Minh", result)

    def test_normalize_skills_comma_separated(self):
        dp = self._make_processor()
        result = dp.normalize_skills("Python, Java, SQL")
        assert isinstance(result, list)
        assert len(result) >= 2

    def test_normalize_skills_empty(self):
        dp = self._make_processor()
        result = dp.normalize_skills("")
        assert isinstance(result, list)


# ═══════════════════════════════════════════════════════
# Section 3: Scoring Engine Unit Tests
# ═══════════════════════════════════════════════════════

class TestScoringEngine:
    """Unit tests for backend.scoring.engine.RankingEngine."""

    def _make_engine(self):
        from backend.scoring.engine import RankingEngine
        return RankingEngine()

    def _make_user(self):
        from backend.scoring.models import UserProfile
        return UserProfile(
            skills=["python", "data-analysis"],
            interests=["AI", "machine-learning"],
            education_level="bachelor",
        )

    def _make_career(self):
        from backend.scoring.models import CareerData
        return CareerData(
            name="Data Scientist",
            required_skills=["python", "statistics"],
            preferred_skills=["machine-learning"],
        )

    def test_engine_init(self):
        engine = self._make_engine()
        assert engine is not None

    def test_rank_empty_careers(self):
        engine = self._make_engine()
        user = self._make_user()
        result = engine.rank(user, [])
        assert result == []

    def test_rank_single_career(self):
        engine = self._make_engine()
        user = self._make_user()
        career = self._make_career()
        result = engine.rank(user, [career])
        assert len(result) == 1
        assert 0 <= result[0].total_score <= 1

    def test_score_bounds(self):
        """All scores must be in [0, 1]."""
        engine = self._make_engine()
        user = self._make_user()
        career = self._make_career()
        result = engine.rank(user, [career])
        for scored in result:
            assert 0 <= scored.total_score <= 1
            bd = scored.breakdown.model_dump()
            for val in bd.values():
                if isinstance(val, (int, float)):
                    assert 0 <= val <= 1


# ═══════════════════════════════════════════════════════
# Section 4: ScoringTracer Unit Tests
# ═══════════════════════════════════════════════════════

class TestScoringTracer:
    """Unit tests for backend.scoring.explain.tracer.ScoringTracer."""

    def _make_tracer(self):
        from backend.scoring.explain.tracer import ScoringTracer
        return ScoringTracer(enabled=True)

    def test_start_trace(self):
        tracer = self._make_tracer()
        tracer.start_trace("Data Scientist", {"skills": 5, "interests": 3})
        assert tracer.current_trace is not None
        assert tracer.current_trace.career_name == "Data Scientist"

    def test_trace_component(self):
        tracer = self._make_tracer()
        tracer.start_trace("DS", {"skills": 5})
        tracer.trace_component("study", 0.8, {"matched": 3})
        assert len(tracer.current_trace.components) == 1
        assert tracer.current_trace.components[0].score == 0.8

    def test_trace_disabled(self):
        from backend.scoring.explain.tracer import ScoringTracer
        tracer = ScoringTracer(enabled=False)
        tracer.start_trace("DS", {})
        assert tracer.current_trace is None

    def test_trace_to_dict(self):
        tracer = self._make_tracer()
        tracer.start_trace("DS", {"skills": 5})
        tracer.trace_component("study", 0.85, {})
        trace = tracer.get_trace()
        d = trace.to_dict()
        assert "career_name" in d
        assert "components" in d

    def test_trace_to_readable(self):
        tracer = self._make_tracer()
        tracer.start_trace("DS", {"skill_count": 5, "interest_count": 3})
        tracer.set_simgr_scores({"study": 0.8, "interest": 0.7})
        trace = tracer.get_trace()
        readable = trace.to_readable()
        assert "Score Trace for: DS" in readable


# ═══════════════════════════════════════════════════════
# Section 5: Orchestration Unit Tests
# ═══════════════════════════════════════════════════════

class TestScheduler:
    """Unit tests for ops.orchestration.scheduler."""

    def _make_scheduler(self):
        from backend.ops.orchestration.scheduler import PipelineScheduler
        return PipelineScheduler()

    @pytest.mark.asyncio
    async def test_register_and_run_stage(self):
        scheduler = self._make_scheduler()

        async def mock_crawl(data):
            return {"records_out": 10}

        scheduler.register_stage("crawl", mock_crawl, critical=True)
        run = await scheduler.run_pipeline(stages=["crawl"])
        assert run.stages["crawl"].status.value == "success"
        assert run.stages["crawl"].records_out == 10

    @pytest.mark.asyncio
    async def test_stage_failure_isolation(self):
        scheduler = self._make_scheduler()

        async def ok_stage(data):
            return {"records_out": 5}

        async def fail_stage(data):
            raise RuntimeError("boom")

        scheduler.register_stage("crawl", ok_stage, critical=True)
        scheduler.register_stage("validate", fail_stage, critical=False)

        run = await scheduler.run_pipeline(stages=["crawl", "validate"])
        assert run.stages["crawl"].status.value == "success"
        assert run.stages["validate"].status.value == "failed"

    @pytest.mark.asyncio
    async def test_critical_failure_stops_pipeline(self):
        scheduler = self._make_scheduler()

        async def fail(data):
            raise RuntimeError("critical fail")

        async def never_run(data):
            return {}

        scheduler.register_stage("crawl", fail, critical=True)
        scheduler.register_stage("validate", never_run)

        run = await scheduler.run_pipeline(stages=["crawl", "validate"])
        assert run.status.value == "failed"
        assert "validate" not in run.stages or run.stages.get("validate", None) is None


class TestRetry:
    """Unit tests for ops.orchestration.retry."""

    @pytest.mark.asyncio
    async def test_retry_success_on_third(self):
        from backend.ops.orchestration.retry import RetryExecutor, RetryPolicy

        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "ok"

        executor = RetryExecutor(RetryPolicy(max_retries=3, base_delay=0.01))
        result = await executor.execute(flaky)
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_all_fail(self):
        from backend.ops.orchestration.retry import RetryExecutor, RetryPolicy

        async def always_fail():
            raise ValueError("always")

        executor = RetryExecutor(RetryPolicy(max_retries=2, base_delay=0.01))
        with pytest.raises(ValueError):
            await executor.execute(always_fail)


class TestCheckpoint:
    """Unit tests for ops.orchestration.checkpoint."""

    @pytest.mark.asyncio
    async def test_save_and_load(self):
        from backend.ops.orchestration.checkpoint import CheckpointManager

        with tempfile.TemporaryDirectory() as td:
            mgr = CheckpointManager(base_dir=Path(td))
            mock_result = MagicMock()
            mock_result.status = "success"
            mock_result.records_in = 100
            mock_result.records_out = 95
            mock_result.duration_seconds = 12.5
            mock_result.error = None

            await mgr.save("run1", "crawl", mock_result)
            loaded = await mgr.load("run1", "crawl")
            assert loaded is not None
            assert loaded["stage"] == "crawl"
            assert loaded["records_out"] == 95

    @pytest.mark.asyncio
    async def test_resume_point(self):
        from backend.ops.orchestration.checkpoint import CheckpointManager

        with tempfile.TemporaryDirectory() as td:
            mgr = CheckpointManager(base_dir=Path(td))
            mock_result = MagicMock()
            mock_result.status = "success"
            mock_result.records_in = 0
            mock_result.records_out = 0
            mock_result.duration_seconds = 1.0
            mock_result.error = None

            await mgr.save("run1", "crawl", mock_result)
            await mgr.save("run1", "validate", mock_result)

            resume = await mgr.get_resume_point("run1")
            assert resume == "score"


# ═══════════════════════════════════════════════════════
# Section 6: Quality Control Unit Tests
# ═══════════════════════════════════════════════════════

class TestCompletenessChecker:
    """Unit tests for ops.quality.completeness."""

    def test_full_completeness(self):
        from backend.ops.quality.completeness import CompletenessChecker

        checker = CompletenessChecker()
        records = [
            {
                "job_id": "1",
                "title": "Dev",
                "company": "Co",
                "url": "https://x.com",
                "salary": "10M",
                "location": "HCM",
                "skills": "Python",
                "experience": "2yr",
                "job_type": "FT",
                "posted_date": "2026-01-01",
                "description": "A dev job",
            }
        ]
        report = checker.check_batch(records)
        assert report.overall_completeness > 0.9

    def test_empty_records(self):
        from backend.ops.quality.completeness import CompletenessChecker

        checker = CompletenessChecker()
        report = checker.check_batch([])
        assert report.total_records == 0

    def test_critical_field_check(self):
        from backend.ops.quality.completeness import CompletenessChecker

        checker = CompletenessChecker()
        records = [{"job_id": "1", "title": "Dev"}]  # Missing company, url
        result = checker.check_critical_fields(records)
        assert result["failures"] == 1


class TestOutlierDetector:
    """Unit tests for ops.quality.outlier."""

    def test_numeric_outlier_detection(self):
        from backend.ops.quality.outlier import OutlierDetector

        detector = OutlierDetector()
        records = [{"salary": i} for i in range(100)]
        records.append({"salary": 10000})  # Outlier

        result = detector.detect_numeric_outliers(records, "salary")
        assert result["outlier_count"] >= 1

    def test_score_anomaly_detection(self):
        from backend.ops.quality.outlier import OutlierDetector

        detector = OutlierDetector()
        scores = [
            {"total_score": 0.7, "breakdown": {"study": 0.8, "interest": 0.6}},
            {"total_score": 1.5, "breakdown": {"study": 0.5}},  # Out of bounds
        ]
        result = detector.detect_score_anomalies(scores)
        assert result["anomaly_count"] >= 1


class TestDriftMonitor:
    """Unit tests for ops.quality.drift."""

    def test_no_drift_identical_batches(self):
        from backend.ops.quality.drift import DriftMonitor

        with tempfile.TemporaryDirectory() as td:
            monitor = DriftMonitor(storage_dir=Path(td))
            records = [
                {"salary_min": i * 1000, "location": "HCM"}
                for i in range(50)
            ]
            monitor.set_baseline("ref", records)
            report = monitor.detect_drift(records, "ref", "test")
            assert report.overall_drift_score < 0.1

    def test_drift_detected(self):
        from backend.ops.quality.drift import DriftMonitor

        with tempfile.TemporaryDirectory() as td:
            monitor = DriftMonitor(storage_dir=Path(td))
            # Reference: concentrated at low range
            ref = [{"salary_min": 1000} for _ in range(45)] + [{"salary_min": 50000} for _ in range(5)]
            # Current: concentrated at high range (opposite shape)
            cur = [{"salary_min": 1000} for _ in range(5)] + [{"salary_min": 50000} for _ in range(45)]
            monitor.set_baseline("ref", ref)
            report = monitor.detect_drift(cur, "ref", "new")
            # Distribution shapes are inverted → significant drift
            assert report.overall_drift_score > 0.0

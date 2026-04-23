# tests/scoring_validation/test_risk_validation.py
"""
Risk Data Validation Tests for SIMGR Scoring Pipeline.

GĐ3 - COMPONENT VALIDATION HARDENING - PHẦN G

Tests:
- test_missing_risk_data_abort
- test_risk_parse_error_abort
- test_cost_column_missing_abort
- test_dropout_rate_missing_abort
- test_stale_data_rejected
"""

import json
import os
import tempfile
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, "F:/Hybrid Decision Support System")

from backend.scoring.components.risk_loader import (
    RiskLoader,
    get_risk_loader,
    verify_risk_prerequisites,
    RISK_DATASET_PATHS,
    REQUIRED_SCHEMA,
    MAX_DATA_AGE_DAYS,
)
from backend.scoring.errors import (
    RiskDatasetMissingError,
    RiskParseError,
    CostColumnMissingError,
    DropoutRateMissingError,
    RiskSchemaMismatchError,
    StaleDataError,
    HealthcheckFailError,
)
from backend.scoring.validation.component_contract import HealthStatus


# =====================================================
# FIXTURES
# =====================================================

@pytest.fixture
def temp_project_root():
    """Create temporary project root with mock data directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        
        # Create data directories
        risk_dir = root / "backend" / "data" / "risk"
        risk_dir.mkdir(parents=True, exist_ok=True)
        
        yield root


@pytest.fixture
def valid_dropout_data():
    """Create valid dropout dataset."""
    return {
        "version": "1.0",
        "entries": [
            {"career": "software_engineer", "rate": 0.25, "confidence": 0.9, "last_updated": "2026-01-15"},
            {"career": "data_scientist", "rate": 0.28, "confidence": 0.85, "last_updated": "2026-01-15"},
        ]
    }


@pytest.fixture
def valid_cost_data():
    """Create valid cost dataset."""
    return {
        "version": "1.0",
        "entries": [
            {"career": "physician", "cost_usd": 250000, "barrier_level": 0.9, "education_years": 12},
            {"career": "software_engineer", "cost_usd": 40000, "barrier_level": 0.45, "education_years": 4},
        ]
    }


@pytest.fixture
def valid_unemployment_data():
    """Create valid unemployment dataset."""
    return {
        "version": "1.0",
        "entries": [
            {"sector": "technology", "rate": 0.03, "trend": "stable", "region": "national"},
            {"sector": "healthcare", "rate": 0.02, "trend": "declining", "region": "national"},
        ]
    }


@pytest.fixture
def valid_saturation_data():
    """Create valid saturation dataset."""
    return {
        "version": "1.0",
        "entries": [
            {"market": "web_development", "level": 0.7, "growth_forecast": 0.05},
            {"market": "ai_ml", "level": 0.4, "growth_forecast": 0.15},
        ]
    }


def create_risk_datasets(root: Path, dropout, cost, unemployment, saturation):
    """Helper to create all risk dataset files."""
    risk_dir = root / "backend" / "data" / "risk"
    risk_dir.mkdir(parents=True, exist_ok=True)
    
    datasets = {
        "dropout_rates.json": dropout,
        "cost_barriers.json": cost,
        "unemployment_rates.json": unemployment,
        "market_saturation.json": saturation,
    }
    
    for filename, data in datasets.items():
        if data is not None:
            with open(risk_dir / filename, 'w') as f:
                json.dump(data, f)


# =====================================================
# MISSING DATA TESTS
# =====================================================

class TestMissingRiskDataAbort:
    """Tests for missing risk data abortion."""
    
    def test_missing_dropout_dataset_aborts(self, temp_project_root):
        """Missing dropout dataset should abort."""
        # Don't create any files
        loader = RiskLoader(project_root=temp_project_root)
        
        with pytest.raises(RiskDatasetMissingError) as exc:
            loader.verify_dataset_exists("dropout")
        
        assert exc.value.code == "RISK_001"
        assert "dropout" in str(exc.value)
    
    def test_missing_cost_dataset_aborts(self, temp_project_root):
        """Missing cost dataset should abort."""
        loader = RiskLoader(project_root=temp_project_root)
        
        with pytest.raises(RiskDatasetMissingError):
            loader.verify_dataset_exists("cost")
    
    def test_unknown_dataset_name_aborts(self, temp_project_root):
        """Unknown dataset name should abort."""
        loader = RiskLoader(project_root=temp_project_root)
        
        with pytest.raises(RiskDatasetMissingError) as exc:
            loader.verify_dataset_exists("nonexistent_dataset")
        
        assert "Unknown dataset" in str(exc.value)
    
    def test_load_all_aborts_on_missing(self, temp_project_root, valid_cost_data):
        """load_all should abort if any dataset missing."""
        # Only create cost, not dropout
        risk_dir = temp_project_root / "backend" / "data" / "risk"
        risk_dir.mkdir(parents=True, exist_ok=True)
        
        with open(risk_dir / "cost_barriers.json", 'w') as f:
            json.dump(valid_cost_data, f)
        
        loader = RiskLoader(project_root=temp_project_root)
        
        with pytest.raises(RiskDatasetMissingError):
            loader.load_all()
    
    def test_healthcheck_fails_on_missing(self, temp_project_root):
        """Healthcheck should report FAIL when datasets missing."""
        loader = RiskLoader(project_root=temp_project_root)
        health = loader.healthcheck()
        
        assert health["status"] == HealthStatus.FAIL
        assert health["dataset"] == "missing"
        assert len(health.get("issues", [])) > 0


# =====================================================
# PARSE ERROR TESTS
# =====================================================

class TestRiskParseErrorAbort:
    """Tests for risk parse error abortion."""
    
    def test_invalid_json_aborts(self, temp_project_root):
        """Invalid JSON in dataset should abort."""
        risk_dir = temp_project_root / "backend" / "data" / "risk"
        risk_dir.mkdir(parents=True, exist_ok=True)
        
        # Write invalid JSON
        with open(risk_dir / "dropout_rates.json", 'w') as f:
            f.write("{invalid json syntax")
        
        # Create other valid files
        valid_data = {"version": "1.0", "entries": []}
        for fname in ["cost_barriers.json", "unemployment_rates.json", "market_saturation.json"]:
            with open(risk_dir / fname, 'w') as f:
                json.dump(valid_data, f)
        
        loader = RiskLoader(project_root=temp_project_root)
        
        with pytest.raises(RiskParseError) as exc:
            loader.load_all()
        
        assert exc.value.code == "RISK_002"
    
    def test_empty_file_aborts(self, temp_project_root):
        """Empty file should abort."""
        risk_dir = temp_project_root / "backend" / "data" / "risk"
        risk_dir.mkdir(parents=True, exist_ok=True)
        
        # Write empty file
        with open(risk_dir / "dropout_rates.json", 'w') as f:
            f.write("")
        
        loader = RiskLoader(project_root=temp_project_root)
        
        with pytest.raises(RiskParseError):
            loader.load_all()


# =====================================================
# COST COLUMN TESTS
# =====================================================

class TestCostColumnMissingAbort:
    """Tests for cost column missing abortion."""
    
    def test_missing_cost_usd_aborts(
        self, 
        temp_project_root, 
        valid_dropout_data, 
        valid_unemployment_data,
        valid_saturation_data
    ):
        """Missing cost_usd column should abort."""
        # Cost data without cost_usd but with valid schema fields
        # Schema validation runs first, so we need valid schema but missing cost_usd
        bad_cost_data = {
            "version": "1.0",
            "entries": [
                {"career": "physician", "education_years": 12},  # Missing cost_usd, barrier_level
            ]
        }
        
        # Test verify_cost_column directly since schema validation happens first
        loader = RiskLoader(project_root=temp_project_root)
        
        with pytest.raises(CostColumnMissingError) as exc:
            loader.verify_cost_column(bad_cost_data)
        
        assert exc.value.code == "RISK_003"
    
    def test_empty_cost_entries_aborts(self, temp_project_root, valid_dropout_data):
        """Empty cost entries should abort."""
        empty_cost = {"version": "1.0", "entries": []}
        
        risk_dir = temp_project_root / "backend" / "data" / "risk"
        risk_dir.mkdir(parents=True, exist_ok=True)
        
        with open(risk_dir / "dropout_rates.json", 'w') as f:
            json.dump(valid_dropout_data, f)
        with open(risk_dir / "cost_barriers.json", 'w') as f:
            json.dump(empty_cost, f)
        
        loader = RiskLoader(project_root=temp_project_root)
        
        with pytest.raises(CostColumnMissingError):
            loader.verify_cost_column(empty_cost)


# =====================================================
# DROPOUT RATE TESTS
# =====================================================

class TestDropoutRateMissingAbort:
    """Tests for dropout rate missing abortion."""
    
    def test_missing_rate_column_aborts(self, temp_project_root):
        """Missing rate column should abort."""
        bad_dropout = {
            "version": "1.0",
            "entries": [
                {"career": "physician", "confidence": 0.9, "last_updated": "2026-01-15"},  # Missing rate
            ]
        }
        
        loader = RiskLoader(project_root=temp_project_root)
        
        with pytest.raises(DropoutRateMissingError) as exc:
            loader.verify_dropout_rate(bad_dropout)
        
        assert exc.value.code == "RISK_004"
    
    def test_empty_dropout_entries_aborts(self, temp_project_root):
        """Empty dropout entries should abort."""
        empty_dropout = {"version": "1.0", "entries": []}
        
        loader = RiskLoader(project_root=temp_project_root)
        
        with pytest.raises(DropoutRateMissingError):
            loader.verify_dropout_rate(empty_dropout)


# =====================================================
# SCHEMA MISMATCH TESTS
# =====================================================

class TestSchemaMismatchBlocked:
    """Tests for schema mismatch blocking."""
    
    def test_missing_schema_field_aborts(self, temp_project_root):
        """Missing required schema field should abort."""
        # Dropout missing 'confidence' field
        bad_schema = {
            "version": "1.0",
            "entries": [
                {"career": "engineer", "rate": 0.3},  # Missing confidence, last_updated
            ]
        }
        
        loader = RiskLoader(project_root=temp_project_root)
        
        with pytest.raises(RiskSchemaMismatchError) as exc:
            loader.verify_schema("dropout", bad_schema)
        
        assert exc.value.code == "RISK_005"
        assert "missing" in str(exc.value).lower()
    
    def test_no_entries_key_aborts(self, temp_project_root):
        """Data without entries should abort."""
        empty_data = {"version": "1.0"}  # No 'entries' key
        
        loader = RiskLoader(project_root=temp_project_root)
        
        with pytest.raises(RiskSchemaMismatchError) as exc:
            loader.verify_schema("dropout", empty_data)
        
        assert "no entries" in str(exc.value).lower()


# =====================================================
# STALE DATA TESTS
# =====================================================

class TestStaleDataRejected:
    """Tests for stale data rejection."""
    
    def test_old_data_rejected(self, temp_project_root):
        """Data older than threshold should be rejected."""
        # Date older than MAX_DATA_AGE_DAYS
        old_date = (datetime.now() - timedelta(days=MAX_DATA_AGE_DAYS + 30)).isoformat()
        
        loader = RiskLoader(project_root=temp_project_root)
        
        with pytest.raises(StaleDataError) as exc:
            loader.verify_data_freshness(old_date)
        
        assert exc.value.code == "RISK_006"
        assert "days old" in str(exc.value)
    
    def test_recent_data_accepted(self, temp_project_root):
        """Recent data should be accepted."""
        recent_date = (datetime.now() - timedelta(days=30)).isoformat()
        
        loader = RiskLoader(project_root=temp_project_root)
        result = loader.verify_data_freshness(recent_date)
        
        assert result is True
    
    def test_invalid_date_format_aborts(self, temp_project_root):
        """Invalid date format should abort."""
        loader = RiskLoader(project_root=temp_project_root)
        
        with pytest.raises(RiskParseError) as exc:
            loader.verify_data_freshness("not-a-date")
        
        assert "Invalid date format" in str(exc.value)


# =====================================================
# HEALTHCHECK TESTS
# =====================================================

class TestHealthcheckFailAbort:
    """Tests for healthcheck failure abortion."""
    
    def test_verify_prerequisites_aborts_on_fail(self, temp_project_root):
        """verify_risk_prerequisites should abort when healthcheck fails."""
        # Mock the global loader to use temp root
        loader = RiskLoader(project_root=temp_project_root)
        
        with patch('backend.scoring.components.risk_loader.get_risk_loader', return_value=loader):
            with pytest.raises(HealthcheckFailError) as exc:
                verify_risk_prerequisites()
            
            assert exc.value.code == "HEALTH_001"
    
    def test_healthcheck_coverage_calculation(self, temp_project_root, valid_dropout_data):
        """Healthcheck coverage should reflect available datasets."""
        risk_dir = temp_project_root / "backend" / "data" / "risk"
        risk_dir.mkdir(parents=True, exist_ok=True)
        
        # Only create one dataset (25% coverage)
        with open(risk_dir / "dropout_rates.json", 'w') as f:
            json.dump(valid_dropout_data, f)
        
        loader = RiskLoader(project_root=temp_project_root)
        health = loader.healthcheck()
        
        assert health["coverage"] == 0.25  # 1/4 datasets
        assert health["status"] in [HealthStatus.FAIL, HealthStatus.DEGRADED]


# =====================================================
# CONTRACT VALIDATION TESTS
# =====================================================

class TestContractMissingFail:
    """Tests for contract validation."""
    
    def test_validate_none_input_aborts(self, temp_project_root):
        """Validating None input should abort."""
        loader = RiskLoader(project_root=temp_project_root)
        
        from backend.scoring.errors import ComponentContractError
        
        with pytest.raises(ComponentContractError):
            loader.validate(None)
    
    def test_validate_missing_career_name_aborts(self, temp_project_root):
        """Validating without career_name should abort."""
        loader = RiskLoader(project_root=temp_project_root)
        
        from backend.scoring.errors import ComponentContractError
        
        with pytest.raises(ComponentContractError) as exc:
            loader.validate({"sector": "technology"})  # Missing career_name
        
        assert "career_name" in str(exc.value)
    
    def test_validate_empty_career_name_aborts(self, temp_project_root):
        """Validating empty career_name should abort."""
        loader = RiskLoader(project_root=temp_project_root)
        
        from backend.scoring.errors import ComponentContractError
        
        with pytest.raises(ComponentContractError):
            loader.validate({"career_name": ""})
    
    def test_validate_valid_input_passes(self, temp_project_root):
        """Valid input should pass validation."""
        loader = RiskLoader(project_root=temp_project_root)
        
        result = loader.validate({"career_name": "software_engineer"})
        assert result is True


# =====================================================
# METADATA TESTS
# =====================================================

class TestMetadata:
    """Tests for metadata response."""
    
    def test_metadata_has_required_fields(self, temp_project_root):
        """Metadata should have all required fields."""
        loader = RiskLoader(project_root=temp_project_root)
        meta = loader.metadata()
        
        required = ["name", "version", "contract_version", "dependencies", "required_fields"]
        for field in required:
            assert field in meta
    
    def test_metadata_name_matches(self, temp_project_root):
        """Metadata name should match component name."""
        loader = RiskLoader(project_root=temp_project_root)
        meta = loader.metadata()
        
        assert meta["name"] == "risk"


# =====================================================
# INTEGRATION TESTS
# =====================================================

class TestFullValidation:
    """Integration tests for full validation pipeline."""
    
    def test_full_valid_datasets_pass(
        self,
        temp_project_root,
        valid_dropout_data,
        valid_cost_data,
        valid_unemployment_data,
        valid_saturation_data
    ):
        """Full valid datasets should pass all checks."""
        create_risk_datasets(
            temp_project_root,
            valid_dropout_data,
            valid_cost_data,
            valid_unemployment_data,
            valid_saturation_data
        )
        
        loader = RiskLoader(project_root=temp_project_root)
        
        # Should not raise
        datasets = loader.load_all(verify=True)
        
        assert "dropout" in datasets
        assert "cost" in datasets
        
        # Healthcheck should be OK
        health = loader.healthcheck()
        assert health["status"] == HealthStatus.OK
        assert health["coverage"] == 1.0


# =====================================================
# RUN IF MAIN
# =====================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

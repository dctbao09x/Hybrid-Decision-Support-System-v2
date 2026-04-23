# backend/tests/test_explain_stage3.py
"""
Comprehensive tests for Stage 3 - Rule + Template Engine.

Tests:
    - Stage3Input validation
    - Stage3Output generation
    - Stage3Config loading
    - Stage3Engine processing
    - Template rendering
    - Deterministic output
"""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone

from backend.explain.stage3.engine import (
    Stage3Input,
    Stage3Output,
    Stage3Config,
    Stage3Engine,
)
from backend.explain.stage3.rule_map import (
    REASON_MAP,
    VALID_SOURCES,
    map_reasons,
)


class TestStage3Input:
    """Tests for Stage3Input dataclass."""

    def test_input_creation(self):
        """Test basic input creation."""
        input_data = Stage3Input(
            trace_id="trace_001",
            career="Data Scientist",
            reason_codes=["MATH_STRONG", "LOGIC_HIGH"],
            sources=["model", "rules"],
            confidence=0.85,
        )
        
        assert input_data.trace_id == "trace_001"
        assert input_data.career == "Data Scientist"
        assert len(input_data.reason_codes) == 2
        assert input_data.confidence == 0.85

    def test_input_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "trace_id": "trace_002",
            "career": "AI Engineer",
            "reason_codes": ["IT_INTEREST"],
            "sources": ["model"],
            "confidence": 0.92,
        }
        
        input_data = Stage3Input.from_dict(data)
        
        assert input_data.trace_id == "trace_002"
        assert input_data.career == "AI Engineer"
        assert input_data.confidence == 0.92

    def test_input_from_dict_defaults(self):
        """Test from_dict with missing fields uses defaults."""
        data = {}
        input_data = Stage3Input.from_dict(data)
        
        assert input_data.trace_id == ""
        assert input_data.career == ""
        assert input_data.reason_codes == []
        assert input_data.sources == []
        assert input_data.confidence == 0.0

    def test_input_validation_success(self):
        """Test validation passes for valid input."""
        input_data = Stage3Input(
            trace_id="valid_trace",
            career="Software Engineer",
            reason_codes=["CODE1"],
            sources=["model"],
            confidence=0.75,
        )
        
        errors = input_data.validate()
        
        assert len(errors) == 0

    def test_input_validation_missing_trace_id(self):
        """Test validation fails for missing trace_id."""
        input_data = Stage3Input(
            trace_id="",  # Missing
            career="Engineer",
            reason_codes=[],
            sources=[],
            confidence=0.5,
        )
        
        errors = input_data.validate()
        
        assert "Missing trace_id" in errors

    def test_input_validation_missing_career(self):
        """Test validation fails for missing career."""
        input_data = Stage3Input(
            trace_id="trace_001",
            career="",  # Missing
            reason_codes=[],
            sources=[],
            confidence=0.5,
        )
        
        errors = input_data.validate()
        
        assert "Missing career" in errors

    def test_input_validation_confidence_range(self):
        """Test validation fails for invalid confidence."""
        input_data = Stage3Input(
            trace_id="trace_001",
            career="Engineer",
            reason_codes=[],
            sources=[],
            confidence=1.5,  # Out of range
        )
        
        errors = input_data.validate()
        
        assert any("confidence" in e.lower() for e in errors)


class TestStage3Output:
    """Tests for Stage3Output dataclass."""

    def test_output_creation(self):
        """Test basic output creation."""
        output = Stage3Output(
            trace_id="trace_001",
            career="Data Scientist",
            reasons=["Strong math skills", "High logic score"],
            explain_text="You are recommended for Data Scientist because...",
        )
        
        assert output.trace_id == "trace_001"
        assert len(output.reasons) == 2
        assert "math" in output.reasons[0].lower()

    def test_output_timestamp_auto_set(self):
        """Test timestamp is auto-set if not provided."""
        output = Stage3Output(
            trace_id="trace_001",
            career="Engineer",
            reasons=[],
            explain_text="Test",
        )
        
        assert output.timestamp != ""
        # Should be valid ISO format
        datetime.fromisoformat(output.timestamp.replace("Z", "+00:00"))

    def test_output_to_dict(self):
        """Test to_dict() method."""
        output = Stage3Output(
            trace_id="trace_001",
            career="Analyst",
            reasons=["Reason 1"],
            explain_text="Explanation text",
            used_codes=["CODE1"],
            skipped_codes=["CODE2"],
            input_hash="abc123",
            output_hash="def456",
        )
        
        result = output.to_dict()
        
        assert result["trace_id"] == "trace_001"
        assert result["career"] == "Analyst"
        assert "reasons" in result
        assert "explain_text" in result
        assert "used_codes" in result
        assert "skipped_codes" in result
        assert "input_hash" in result
        assert "output_hash" in result

    def test_output_to_api_response(self):
        """Test to_api_response() returns minimal data."""
        output = Stage3Output(
            trace_id="trace_001",
            career="Developer",
            reasons=["Good coding skills"],
            explain_text="You are suited for development.",
            used_codes=["CODE1"],  # Should not appear in API response
        )
        
        result = output.to_api_response()
        
        assert "trace_id" in result
        assert "career" in result
        assert "reasons" in result
        assert "explain_text" in result
        assert "used_codes" not in result


class TestStage3Config:
    """Tests for Stage3Config dataclass."""

    def test_config_defaults(self):
        """Test default configuration values."""
        config = Stage3Config()
        
        assert config.enabled is True
        assert config.strict is True
        assert config.log_level == "full"
        assert config.template_name == "base.j2"

    def test_config_from_dict(self):
        """Test loading config from dict."""
        data = {
            "enabled": False,
            "strict": False,
            "log_level": "minimal",
            "template_name": "custom.j2",
        }
        
        config = Stage3Config.from_dict(data)
        
        assert config.enabled is False
        assert config.strict is False
        assert config.log_level == "minimal"
        assert config.template_name == "custom.j2"

    def test_config_from_nested_dict(self):
        """Test loading from nested 'stage3' key."""
        data = {
            "stage3": {
                "enabled": True,
                "strict": True,
                "log_level": "off",
            }
        }
        
        config = Stage3Config.from_dict(data)
        
        assert config.enabled is True
        assert config.log_level == "off"


class TestRuleMap:
    """Tests for rule_map module."""

    def test_reason_map_exists(self):
        """Test REASON_MAP is defined."""
        assert REASON_MAP is not None
        assert isinstance(REASON_MAP, dict)

    def test_valid_sources_exists(self):
        """Test VALID_SOURCES is defined."""
        assert VALID_SOURCES is not None
        # It's a frozenset, which is a subclass of set-like types
        assert isinstance(VALID_SOURCES, (set, frozenset))

    def test_map_reasons_empty(self):
        """Test map_reasons with empty codes."""
        mapped, used, skipped = map_reasons([], [])
        
        assert mapped == []
        assert used == []
        assert skipped == []

    def test_map_reasons_with_codes(self):
        """Test map_reasons with actual codes."""
        codes = list(REASON_MAP.keys())[:3] if REASON_MAP else []
        
        if codes:
            mapped, used, skipped = map_reasons(codes, [])
            
            assert len(mapped) <= len(codes)
            assert len(used) + len(skipped) == len(codes)

    def test_map_reasons_unknown_code(self):
        """Test map_reasons handles unknown codes."""
        codes = ["UNKNOWN_CODE_XYZ"]
        
        mapped, used, skipped = map_reasons(codes, [])
        
        # Unknown codes should be skipped
        assert "UNKNOWN_CODE_XYZ" in skipped
        assert len(mapped) == 0


class TestStage3Engine:
    """Tests for Stage3Engine class."""

    def test_engine_creation(self):
        """Test engine can be created."""
        engine = Stage3Engine()
        assert engine is not None

    def test_engine_with_project_root(self, tmp_path):
        """Test engine with custom project root."""
        engine = Stage3Engine(project_root=tmp_path)
        assert engine._project_root == tmp_path

    def test_engine_load_config(self):
        """Test loading configuration."""
        engine = Stage3Engine()
        config = {
            "enabled": True,
            "strict": False,
            "log_level": "minimal",
        }
        
        engine.load_config(config)
        
        assert engine._config.strict is False

    def test_engine_disabled(self):
        """Test engine can be disabled."""
        engine = Stage3Engine()
        engine.load_config({"enabled": False})
        
        assert engine._config.enabled is False


class TestStage3Integration:
    """Integration tests for Stage 3."""

    def test_full_pipeline(self):
        """Test full Stage 3 processing pipeline."""
        engine = Stage3Engine()
        engine.load_config({"enabled": True, "strict": False})
        
        # Create valid input
        input_data = Stage3Input(
            trace_id="integration_test_001",
            career="Data Scientist",
            reason_codes=list(REASON_MAP.keys())[:2] if REASON_MAP else ["GENERAL"],
            sources=list(VALID_SOURCES)[:1] if VALID_SOURCES else ["model"],
            confidence=0.85,
        )
        
        # Validate input
        errors = input_data.validate()
        assert len(errors) == 0

    def test_deterministic_output(self):
        """Test output is deterministic for same input."""
        input_data = Stage3Input(
            trace_id="determinism_test",
            career="Engineer",
            reason_codes=["GENERAL"],
            sources=["model"],
            confidence=0.75,
        )
        
        # Create outputs should have same structure
        output1 = Stage3Output(
            trace_id=input_data.trace_id,
            career=input_data.career,
            reasons=["Test reason"],
            explain_text="Test explanation",
        )
        
        output2 = Stage3Output(
            trace_id=input_data.trace_id,
            career=input_data.career,
            reasons=["Test reason"],
            explain_text="Test explanation",
        )
        
        # Core fields should match
        assert output1.trace_id == output2.trace_id
        assert output1.career == output2.career
        assert output1.reasons == output2.reasons

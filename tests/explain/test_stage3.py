# tests/explain/test_stage3.py
"""
Test Suite for Stage 3 - Rule + Template Engine
================================================

Coverage targets:
  - valid input
  - missing code
  - unknown code
  - multi reason
  - empty list
  - config off

Target: ≥80% coverage
"""

import hashlib
import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from backend.explain.stage3.rule_map import (
    REASON_MAP,
    VALID_SOURCES,
    get_reason_text,
    bind_evidence,
    map_reasons,
    is_valid_source,
    list_all_codes,
)
from backend.explain.stage3.engine import (
    Stage3Engine,
    Stage3Input,
    Stage3Output,
    Stage3Config,
    run_stage3,
    get_stage3_engine,
)


# ==============================================================================
# Test Rule Map
# ==============================================================================

class TestRuleMap:
    """Test rule_map.py functionality."""
    
    def test_reason_map_not_empty(self):
        """REASON_MAP should have entries."""
        assert len(REASON_MAP) > 0
        assert "math_high" in REASON_MAP
        assert "logic_strong" in REASON_MAP
        assert "ai_interest" in REASON_MAP
    
    def test_valid_sources(self):
        """VALID_SOURCES should contain expected values."""
        assert "shap" in VALID_SOURCES
        assert "coef" in VALID_SOURCES
        assert "perm" in VALID_SOURCES
        assert "importance" in VALID_SOURCES
    
    def test_get_reason_text_known_code(self):
        """get_reason_text returns text for known codes."""
        text = get_reason_text("math_high")
        assert text is not None
        assert "Toán" in text or "Math" in text
    
    def test_get_reason_text_unknown_code(self):
        """get_reason_text returns None for unknown codes."""
        text = get_reason_text("unknown_code_xyz")
        assert text is None
    
    def test_bind_evidence_with_valid_source(self):
        """bind_evidence adds source annotation."""
        result = bind_evidence("Điểm Toán cao", "shap")
        assert result == "Điểm Toán cao (shap)"
    
    def test_bind_evidence_with_invalid_source(self):
        """bind_evidence returns text unchanged for invalid source."""
        result = bind_evidence("Điểm Toán cao", "invalid_source")
        assert result == "Điểm Toán cao"
    
    def test_bind_evidence_with_empty_source(self):
        """bind_evidence returns text unchanged for empty source."""
        result = bind_evidence("Điểm Toán cao", "")
        assert result == "Điểm Toán cao"
    
    def test_map_reasons_valid_codes(self):
        """map_reasons correctly maps known codes."""
        codes = ["math_high", "logic_strong"]
        sources = ["shap", "coef"]
        
        mapped, used, skipped = map_reasons(codes, sources)
        
        assert len(mapped) == 2
        assert len(used) == 2
        assert len(skipped) == 0
        assert "shap" in mapped[0]
        assert "coef" in mapped[1]
    
    def test_map_reasons_with_unknown_codes(self):
        """map_reasons skips unknown codes."""
        codes = ["math_high", "unknown_xyz", "logic_strong"]
        sources = ["shap"]
        
        mapped, used, skipped = map_reasons(codes, sources)
        
        assert len(mapped) == 2
        assert len(used) == 2
        assert len(skipped) == 1
        assert "unknown_xyz" in skipped
    
    def test_map_reasons_empty_list(self):
        """map_reasons handles empty list."""
        mapped, used, skipped = map_reasons([], [])
        
        assert len(mapped) == 0
        assert len(used) == 0
        assert len(skipped) == 0
    
    def test_map_reasons_single_source_broadcast(self):
        """Single source is applied to all codes."""
        codes = ["math_high", "logic_strong"]
        sources = ["shap"]  # Single source
        
        mapped, used, skipped = map_reasons(codes, sources)
        
        # Both should have shap annotation
        assert all("shap" in m for m in mapped)
    
    def test_is_valid_source(self):
        """is_valid_source validates correctly."""
        assert is_valid_source("shap") is True
        assert is_valid_source("coef") is True
        assert is_valid_source("invalid") is False
    
    def test_list_all_codes(self):
        """list_all_codes returns all codes."""
        codes = list_all_codes()
        assert len(codes) > 0
        assert "math_high" in codes


# ==============================================================================
# Test Stage3 Input/Output Models
# ==============================================================================

class TestStage3Models:
    """Test Stage3Input and Stage3Output models."""
    
    def test_stage3_input_from_dict(self):
        """Stage3Input parses from dict."""
        data = {
            "trace_id": "abc123",
            "career": "Data Scientist",
            "reason_codes": ["math_high", "logic_strong"],
            "sources": ["shap"],
            "confidence": 0.87,
        }
        
        input_obj = Stage3Input.from_dict(data)
        
        assert input_obj.trace_id == "abc123"
        assert input_obj.career == "Data Scientist"
        assert len(input_obj.reason_codes) == 2
        assert input_obj.confidence == 0.87
    
    def test_stage3_input_validation_valid(self):
        """Stage3Input validates correctly for valid input."""
        input_obj = Stage3Input(
            trace_id="abc123",
            career="Data Scientist",
            reason_codes=["math_high"],
            sources=["shap"],
            confidence=0.87,
        )
        
        errors = input_obj.validate()
        assert len(errors) == 0
    
    def test_stage3_input_validation_missing_trace_id(self):
        """Stage3Input catches missing trace_id."""
        input_obj = Stage3Input(
            trace_id="",
            career="Data Scientist",
            reason_codes=["math_high"],
            sources=["shap"],
            confidence=0.87,
        )
        
        errors = input_obj.validate()
        assert any("trace_id" in e for e in errors)
    
    def test_stage3_input_validation_invalid_confidence(self):
        """Stage3Input catches invalid confidence."""
        input_obj = Stage3Input(
            trace_id="abc123",
            career="Data Scientist",
            reason_codes=["math_high"],
            sources=["shap"],
            confidence=1.5,  # Invalid: > 1
        )
        
        errors = input_obj.validate()
        assert any("confidence" in e for e in errors)
    
    def test_stage3_output_to_dict(self):
        """Stage3Output converts to dict."""
        output = Stage3Output(
            trace_id="abc123",
            career="Data Scientist",
            reasons=["Điểm Toán cao (shap)"],
            explain_text="Bạn phù hợp...",
            used_codes=["math_high"],
            skipped_codes=[],
        )
        
        data = output.to_dict()
        
        assert data["trace_id"] == "abc123"
        assert data["career"] == "Data Scientist"
        assert len(data["reasons"]) == 1
        assert "explain_text" in data
    
    def test_stage3_output_to_api_response(self):
        """Stage3Output produces clean API response."""
        output = Stage3Output(
            trace_id="abc123",
            career="Data Scientist",
            reasons=["Điểm Toán cao (shap)"],
            explain_text="Bạn phù hợp...",
        )
        
        response = output.to_api_response()
        
        # API response should not include internal fields
        assert "trace_id" in response
        assert "career" in response
        assert "reasons" in response
        assert "explain_text" in response


# ==============================================================================
# Test Stage3 Config
# ==============================================================================

class TestStage3Config:
    """Test Stage3Config."""
    
    def test_config_defaults(self):
        """Config has sensible defaults."""
        config = Stage3Config()
        
        assert config.enabled is True
        assert config.strict is True
        assert config.log_level == "full"
    
    def test_config_from_dict(self):
        """Config loads from dict."""
        data = {
            "stage3": {
                "enabled": False,
                "strict": False,
                "log_level": "minimal",
            }
        }
        
        config = Stage3Config.from_dict(data)
        
        assert config.enabled is False
        assert config.strict is False
        assert config.log_level == "minimal"


# ==============================================================================
# Test Stage3 Engine
# ==============================================================================

class TestStage3Engine:
    """Test Stage3Engine."""
    
    def test_engine_initialization(self):
        """Engine initializes correctly."""
        engine = Stage3Engine()
        assert engine is not None
        assert engine.is_enabled() is True
    
    def test_engine_load_config(self):
        """Engine loads config correctly."""
        engine = Stage3Engine()
        engine.load_config({
            "stage3": {
                "enabled": True,
                "strict": False,
                "log_level": "minimal",
            }
        })
        
        assert engine._config.strict is False
        assert engine._config.log_level == "minimal"
    
    def test_engine_run_valid_input(self):
        """Engine processes valid input correctly."""
        engine = Stage3Engine()
        
        xai_output = {
            "trace_id": "test-001",
            "career": "Data Scientist",
            "reason_codes": ["math_high", "logic_strong", "ai_interest"],
            "sources": ["shap", "coef", "importance"],
            "confidence": 0.87,
        }
        
        result = engine.run(xai_output)
        
        assert isinstance(result, Stage3Output)
        assert result.trace_id == "test-001"
        assert result.career == "Data Scientist"
        assert len(result.reasons) >= 1
        assert "Bạn phù hợp" in result.explain_text
        assert "87" in result.explain_text  # Confidence percentage
    
    def test_engine_run_missing_code(self):
        """Engine handles input with missing reason codes."""
        engine = Stage3Engine()
        engine.load_config({"stage3": {"strict": False}})
        
        xai_output = {
            "trace_id": "test-002",
            "career": "Software Engineer",
            "reason_codes": [],  # Empty
            "sources": [],
            "confidence": 0.75,
        }
        
        result = engine.run(xai_output)
        
        assert result.trace_id == "test-002"
        assert len(result.reasons) == 0
    
    def test_engine_run_unknown_code(self):
        """Engine skips unknown codes."""
        engine = Stage3Engine()
        
        xai_output = {
            "trace_id": "test-003",
            "career": "Data Scientist",
            "reason_codes": ["math_high", "unknown_xyz", "unknown_abc"],
            "sources": ["shap"],
            "confidence": 0.80,
        }
        
        result = engine.run(xai_output)
        
        # Should have 1 valid reason
        assert len(result.reasons) == 1
        assert len(result.used_codes) == 1
        assert len(result.skipped_codes) == 2
        assert "unknown_xyz" in result.skipped_codes
    
    def test_engine_run_multi_reason(self):
        """Engine handles multiple reasons."""
        engine = Stage3Engine()
        
        xai_output = {
            "trace_id": "test-004",
            "career": "Data Scientist",
            "reason_codes": [
                "math_high", "logic_strong", "ai_interest",
                "physics_good", "data_skill"
            ],
            "sources": ["shap", "coef", "importance", "perm", "shap"],
            "confidence": 0.92,
        }
        
        result = engine.run(xai_output)
        
        assert len(result.reasons) == 5
        assert len(result.used_codes) == 5
    
    def test_engine_run_empty_list(self):
        """Engine handles empty reason list."""
        engine = Stage3Engine()
        engine.load_config({"stage3": {"strict": False}})
        
        xai_output = {
            "trace_id": "test-005",
            "career": "Data Scientist",
            "reason_codes": [],
            "sources": [],
            "confidence": 0.50,
        }
        
        result = engine.run(xai_output)
        
        assert len(result.reasons) == 0
        assert result.explain_text  # Should still render template
    
    def test_engine_disabled(self):
        """Engine returns passthrough when disabled."""
        engine = Stage3Engine()
        engine.load_config({"stage3": {"enabled": False}})
        
        assert engine.is_enabled() is False
        
        xai_output = {
            "trace_id": "test-006",
            "career": "Data Scientist",
            "reason_codes": ["math_high"],
            "sources": ["shap"],
            "confidence": 0.87,
        }
        
        result = engine.run(xai_output)
        
        # Should return passthrough (no processing)
        assert result.trace_id == "test-006"
        assert result.explain_text == ""  # No template rendered
    
    def test_engine_strict_mode_validation_error(self):
        """Engine raises error in strict mode on validation failure."""
        engine = Stage3Engine()
        engine.load_config({"stage3": {"strict": True}})
        
        xai_output = {
            "trace_id": "",  # Invalid: empty
            "career": "Data Scientist",
            "reason_codes": ["math_high"],
            "sources": ["shap"],
            "confidence": 0.87,
        }
        
        with pytest.raises(ValueError) as exc_info:
            engine.run(xai_output)
        
        assert "validation" in str(exc_info.value).lower()
    
    def test_engine_non_strict_mode_continues(self):
        """Engine continues in non-strict mode on validation warning."""
        engine = Stage3Engine()
        engine.load_config({"stage3": {"strict": False}})
        
        xai_output = {
            "trace_id": "",  # Invalid but non-strict
            "career": "Data Scientist",
            "reason_codes": ["math_high"],
            "sources": ["shap"],
            "confidence": 0.87,
        }
        
        # Should not raise
        result = engine.run(xai_output)
        assert result is not None


# ==============================================================================
# Test Template Rendering
# ==============================================================================

class TestTemplateRendering:
    """Test Jinja2 template rendering."""
    
    def test_base_template_renders(self):
        """Base template renders correctly."""
        engine = Stage3Engine()
        
        xai_output = {
            "trace_id": "template-001",
            "career": "Data Scientist",
            "reason_codes": ["math_high", "logic_strong"],
            "sources": ["shap", "coef"],
            "confidence": 0.87,
        }
        
        result = engine.run(xai_output)
        
        # Check template output
        assert "Bạn phù hợp với Data Scientist vì:" in result.explain_text
        assert "87" in result.explain_text  # Confidence
        assert "-" in result.explain_text  # Bullet points
    
    def test_template_fallback(self):
        """Template falls back on error."""
        engine = Stage3Engine()
        
        # Force invalid template
        engine._config.template_name = "nonexistent.j2"
        
        xai_output = {
            "trace_id": "template-002",
            "career": "Data Scientist",
            "reason_codes": ["math_high"],
            "sources": ["shap"],
            "confidence": 0.75,
        }
        
        result = engine.run(xai_output)
        
        # Should still produce output (fallback)
        assert result.explain_text != ""


# ==============================================================================
# Test Audit Logging
# ==============================================================================

class TestAuditLogging:
    """Test audit logging functionality."""
    
    def test_audit_log_written(self):
        """Audit log is written correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = Stage3Engine()
            engine._log_dir = Path(tmpdir)
            engine._log_file = Path(tmpdir) / "explain_stage3.log"
            engine.load_config({
                "stage3": {
                    "enabled": True,
                    "log_level": "full",
                }
            })
            
            xai_output = {
                "trace_id": "audit-001",
                "career": "Data Scientist",
                "reason_codes": ["math_high", "logic_strong"],
                "sources": ["shap", "coef"],
                "confidence": 0.87,
            }
            
            result = engine.run(xai_output)
            
            # Check log file
            assert engine._log_file.exists()
            
            with open(engine._log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            # Get the last line (most recent entry)
            log_entry = json.loads(lines[-1].strip())
            
            assert log_entry["trace_id"] == "audit-001"
            assert "input_hash" in log_entry
            assert "output_hash" in log_entry
            assert "used_codes" in log_entry
    
    def test_audit_log_off(self):
        """Audit log is not written when log_level=off."""
        with tempfile.TemporaryDirectory() as tmpdir:
            unique_log_file = Path(tmpdir) / "test_audit_off_unique.log"
            
            engine = Stage3Engine()
            engine._log_dir = Path(tmpdir)
            engine._log_file = unique_log_file
            engine.load_config({
                "stage3": {
                    "enabled": True,
                    "log_level": "off",
                }
            })
            
            # Ensure log file is pointing to temp dir after config load
            engine._log_file = unique_log_file
            
            xai_output = {
                "trace_id": "audit-002",
                "career": "Data Scientist",
                "reason_codes": ["math_high"],
                "sources": ["shap"],
                "confidence": 0.87,
            }
            
            engine.run(xai_output)
            
            # Log file should not exist for new temp file
            assert not unique_log_file.exists()


# ==============================================================================
# Test Determinism
# ==============================================================================

class TestDeterminism:
    """Test deterministic output (same input -> same output)."""
    
    def test_same_input_same_output(self):
        """Same input produces identical output."""
        engine = Stage3Engine()
        
        xai_output = {
            "trace_id": "determinism-001",
            "career": "Data Scientist",
            "reason_codes": ["math_high", "logic_strong", "ai_interest"],
            "sources": ["shap", "coef", "importance"],
            "confidence": 0.87,
        }
        
        result1 = engine.run(xai_output)
        result2 = engine.run(xai_output)
        
        # Core output should be identical
        assert result1.reasons == result2.reasons
        assert result1.explain_text == result2.explain_text
        assert result1.used_codes == result2.used_codes
        assert result1.skipped_codes == result2.skipped_codes
    
    def test_hash_reproducibility(self):
        """Hashes are reproducible."""
        engine = Stage3Engine()
        
        xai_output = {
            "trace_id": "hash-001",
            "career": "Data Scientist",
            "reason_codes": ["math_high"],
            "sources": ["shap"],
            "confidence": 0.87,
        }
        
        result1 = engine.run(xai_output)
        result2 = engine.run(xai_output)
        
        assert result1.input_hash == result2.input_hash
        assert result1.output_hash == result2.output_hash


# ==============================================================================
# Test run_stage3 Function
# ==============================================================================

class TestRunStage3Function:
    """Test run_stage3 convenience function."""
    
    def test_run_stage3_basic(self):
        """run_stage3 produces correct output."""
        xai_output = {
            "trace_id": "func-001",
            "career": "Data Scientist",
            "reason_codes": ["math_high", "logic_strong"],
            "sources": ["shap"],
            "confidence": 0.87,
        }
        
        result = run_stage3(xai_output)
        
        assert isinstance(result, dict)
        assert result["trace_id"] == "func-001"
        assert result["career"] == "Data Scientist"
        assert len(result["reasons"]) >= 1
        assert "explain_text" in result


# ==============================================================================
# Test Singleton
# ==============================================================================

class TestSingleton:
    """Test singleton pattern."""
    
    def test_get_stage3_engine_singleton(self):
        """get_stage3_engine returns singleton."""
        engine1 = get_stage3_engine()
        engine2 = get_stage3_engine()
        
        assert engine1 is engine2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=backend.explain.stage3", "--cov-report=term-missing"])

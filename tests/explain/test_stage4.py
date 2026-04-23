# tests/explain/test_stage4.py
"""
Test Suite for Stage 4 - Ollama LLM Formatting
==============================================

Coverage targets:
  - normal flow (mock Ollama success)
  - timeout/error handling
  - hallucination detection
  - empty response handling
  - fallback to Stage 3
  - config enabled/disabled

Target: ≥75% coverage
"""

import hashlib
import json
import pytest
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

from backend.explain.stage4.client import (
    OllamaClient,
    OllamaResponse,
    CircuitBreaker,
    CircuitState,
)
from backend.explain.stage4.ollama_adapter import (
    Stage4Engine,
    Stage4Output,
    Stage4Config,
    OutputValidator,
    ValidationResult,
    format_with_llm,
)


# ==============================================================================
# Test Fixtures
# ==============================================================================

@pytest.fixture
def sample_stage3_output():
    """Sample Stage 3 output for testing."""
    return {
        "trace_id": "test-trace-123",
        "career": "Data Scientist",
        "reasons": [
            "Điểm Toán vượt ngưỡng (shap)",
            "Tư duy logic mạnh (coef)",
        ],
        "confidence": 0.87,
        "explain_text": "Bạn phù hợp với ngành Data Scientist vì:\n- Điểm Toán vượt ngưỡng (shap)\n- Tư duy logic mạnh (coef)\nĐộ tin cậy: 87.0%",
        "used_codes": ["math_high", "logic_strong"],
        "skipped_codes": [],
        "meta": {"stage3_version": "1.0.0"},
    }


@pytest.fixture
def config_enabled():
    """Config with Stage 4 enabled."""
    return {
        "stage4": {
            "enabled": True,
            "model": "llama3",
            "timeout": 5.0,
            "retry": 2,
            "strict_validate": True,
            "max_output_length": 2000,
            "log_level": "off",
        }
    }


@pytest.fixture
def config_disabled():
    """Config with Stage 4 disabled."""
    return {
        "stage4": {
            "enabled": False,
            "model": "llama3",
            "timeout": 5.0,
            "retry": 2,
            "strict_validate": True,
            "log_level": "off",
        }
    }


@pytest.fixture
def mock_ollama_response_success():
    """Mock successful Ollama response."""
    return OllamaResponse(
        text="Bạn phù hợp với ngành Data Scientist. Điểm Toán của bạn vượt ngưỡng, tư duy logic mạnh. Độ tin cậy đạt 87%.",
        model="llama3",
        done=True,
        latency_ms=150.5,
        prompt_hash="abc123",
        error=None,
    )


# ==============================================================================
# Test CircuitBreaker
# ==============================================================================

class TestCircuitBreaker:
    """Test CircuitBreaker class."""
    
    def test_initial_state_closed(self):
        """CircuitBreaker starts in CLOSED state."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30)
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request()
    
    def test_failure_increments_count(self):
        """Recording failure increments failure count."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30)
        
        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.state == CircuitState.CLOSED
        
        cb.record_failure()
        assert cb.failure_count == 2
        assert cb.state == CircuitState.CLOSED
    
    def test_failure_threshold_opens_circuit(self):
        """Circuit opens after reaching failure threshold."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30)
        
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()  # Threshold reached
        
        assert cb.state == CircuitState.OPEN
        assert cb.is_open()
        assert not cb.allow_request()
    
    def test_success_resets_failure_count(self):
        """Recording success resets failure count."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30)
        
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2
        
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED
    
    def test_half_open_after_cooldown(self):
        """Circuit moves to HALF_OPEN after cooldown."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=0.1)
        
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open()
        
        # Wait for cooldown
        time.sleep(0.15)
        
        # Check state moves to HALF_OPEN
        assert cb.allow_request()
        assert cb.state == CircuitState.HALF_OPEN
    
    def test_half_open_success_closes_circuit(self):
        """Success in HALF_OPEN state closes circuit."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=0.1)
        
        # Open circuit
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        
        # Wait for cooldown
        time.sleep(0.15)
        cb.allow_request()  # Move to HALF_OPEN
        
        # Success closes circuit
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
    
    def test_half_open_failure_reopens_circuit(self):
        """Failure in HALF_OPEN state re-opens circuit."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=0.1)
        
        # Open circuit
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        
        # Wait for cooldown
        time.sleep(0.15)
        cb.allow_request()  # Move to HALF_OPEN
        
        # Failure re-opens circuit
        cb.record_failure()
        assert cb.is_open()
    
    def test_reset(self):
        """Reset returns circuit to initial state."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30)
        
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open()
        
        # Manual reset by recording success
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


# ==============================================================================
# Test OutputValidator
# ==============================================================================

class TestOutputValidator:
    """Test OutputValidator class."""
    
    def test_valid_output(self):
        """Valid output passes validation."""
        config = Stage4Config(strict_validate=True)
        validator = OutputValidator(config)
        
        result = validator.validate(
            llm_output="Bạn phù hợp với Data Scientist. Điểm Toán cao, logic mạnh.",
            original_text="Bạn phù hợp với Data Scientist vì: Điểm Toán cao, logic mạnh.",
            original_reasons=["Điểm Toán cao", "Logic mạnh"],
        )
        
        assert result.valid
        assert len(result.issues) == 0
    
    def test_empty_output_fails(self):
        """Empty output fails validation."""
        config = Stage4Config(strict_validate=True)
        validator = OutputValidator(config)
        
        result = validator.validate(
            llm_output="",
            original_text="Some text",
            original_reasons=["Reason 1"],
        )
        
        assert not result.valid
        assert "empty" in result.issues[0].lower()
    
    def test_whitespace_only_fails(self):
        """Whitespace-only output fails validation."""
        config = Stage4Config(strict_validate=True)
        validator = OutputValidator(config)
        
        result = validator.validate(
            llm_output="   \n\t  ",
            original_text="Some text",
            original_reasons=["Reason 1"],
        )
        
        assert not result.valid
    
    def test_too_long_output_fails_strict(self):
        """Output exceeding max length fails in strict mode."""
        config = Stage4Config(strict_validate=True, max_output_length=50)
        validator = OutputValidator(config)
        
        result = validator.validate(
            llm_output="A" * 100,
            original_text="A" * 30,
            original_reasons=[],
        )
        
        assert not result.valid
        assert "too long" in result.issues[0].lower()
    
    def test_too_long_output_passes_non_strict(self):
        """Output exceeding max length passes in non-strict mode."""
        config = Stage4Config(strict_validate=False, max_output_length=50)
        validator = OutputValidator(config)
        
        result = validator.validate(
            llm_output="A" * 100,
            original_text="A" * 30,
            original_reasons=[],
        )
        
        assert result.valid
        assert len(result.issues) > 0  # Issues logged but not blocking
    
    def test_hallucination_keyword_fails_strict(self):
        """Hallucination keyword fails in strict mode."""
        config = Stage4Config(strict_validate=True)
        validator = OutputValidator(config)
        
        result = validator.validate(
            llm_output="Tôi nghĩ bạn phù hợp với Data Scientist.",
            original_text="Bạn phù hợp với Data Scientist.",
            original_reasons=[],
        )
        
        assert not result.valid
        assert "hallucination" in result.issues[0].lower()
    
    def test_hallucination_keyword_passes_non_strict(self):
        """Hallucination keyword passes in non-strict mode."""
        config = Stage4Config(strict_validate=False)
        validator = OutputValidator(config)
        
        result = validator.validate(
            llm_output="Tôi nghĩ bạn phù hợp với Data Scientist.",
            original_text="Bạn phù hợp với Data Scientist.",
            original_reasons=[],
        )
        
        assert result.valid


# ==============================================================================
# Test Stage4Config
# ==============================================================================

class TestStage4Config:
    """Test Stage4Config class."""
    
    def test_default_values(self):
        """Default config values are set correctly."""
        config = Stage4Config()
        
        assert config.enabled is True
        assert config.model == "llama3"
        assert config.timeout == 5.0
        assert config.retry == 2
        assert config.strict_validate is True
    
    def test_from_dict(self):
        """Config loads from dict correctly."""
        data = {
            "stage4": {
                "enabled": False,
                "model": "mistral",
                "timeout": 10.0,
                "retry": 3,
            }
        }
        
        config = Stage4Config.from_dict(data)
        
        assert config.enabled is False
        assert config.model == "mistral"
        assert config.timeout == 10.0
        assert config.retry == 3
    
    def test_from_dict_with_missing_keys(self):
        """Config uses defaults for missing keys."""
        data = {"stage4": {"model": "codellama"}}
        
        config = Stage4Config.from_dict(data)
        
        assert config.model == "codellama"
        assert config.enabled is True  # Default
        assert config.timeout == 5.0   # Default


# ==============================================================================
# Test Stage4Output
# ==============================================================================

class TestStage4Output:
    """Test Stage4Output class."""
    
    def test_to_dict(self):
        """to_dict produces expected structure."""
        output = Stage4Output(
            trace_id="test-123",
            career="Data Scientist",
            reasons=["Reason 1"],
            confidence=0.9,
            raw_text="Raw text",
            llm_text="LLM text",
            used_llm=True,
            fallback=False,
            ollama_model="llama3",
            latency_ms=100.5,
        )
        
        d = output.to_dict()
        
        assert d["trace_id"] == "test-123"
        assert d["career"] == "Data Scientist"
        assert d["llm_text"] == "LLM text"
        assert d["used_llm"] is True
        assert d["meta"]["ollama_model"] == "llama3"
        assert d["meta"]["latency_ms"] == 100.5
    
    def test_to_api_response(self):
        """to_api_response produces clean API structure."""
        output = Stage4Output(
            trace_id="test-123",
            career="Data Scientist",
            reasons=["Reason 1"],
            confidence=0.9,
            raw_text="Raw text",
            llm_text="LLM text",
            used_llm=True,
        )
        
        resp = output.to_api_response()
        
        assert "trace_id" in resp
        assert "llm_text" in resp
        assert "meta" not in resp  # Excluded from API response


# ==============================================================================
# Test Stage4Engine
# ==============================================================================

class TestStage4Engine:
    """Test Stage4Engine class."""
    
    @patch("backend.explain.stage4.ollama_adapter.get_ollama_client")
    def test_format_disabled_config(
        self, mock_get_client, sample_stage3_output
    ):
        """Format returns fallback when disabled."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        engine = Stage4Engine()
        engine.load_config({"stage4": {"enabled": False, "log_level": "off"}})
        
        result = engine.format(sample_stage3_output)
        
        assert result.used_llm is False
        assert result.fallback is True
        assert result.llm_text == sample_stage3_output["explain_text"]
        mock_client.generate.assert_not_called()
    
    @patch("backend.explain.stage4.ollama_adapter.get_ollama_client")
    def test_format_empty_input(
        self, mock_get_client, sample_stage3_output
    ):
        """Format returns fallback for empty input text."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        engine = Stage4Engine()
        engine.load_config({"stage4": {"enabled": True, "log_level": "off"}})
        
        sample_stage3_output["explain_text"] = ""
        result = engine.format(sample_stage3_output)
        
        assert result.used_llm is False
        assert result.fallback is True
        mock_client.generate.assert_not_called()
    
    @patch("backend.explain.stage4.ollama_adapter.get_ollama_client")
    def test_format_success(
        self, mock_get_client, sample_stage3_output, mock_ollama_response_success
    ):
        """Format succeeds with valid Ollama response."""
        mock_client = MagicMock()
        mock_client.generate.return_value = mock_ollama_response_success
        mock_get_client.return_value = mock_client
        
        engine = Stage4Engine()
        engine.load_config({"stage4": {"enabled": True, "log_level": "off"}})
        
        result = engine.format(sample_stage3_output)
        
        assert result.used_llm is True
        assert result.fallback is False
        assert result.llm_text == mock_ollama_response_success.text
        mock_client.generate.assert_called_once()
    
    @patch("backend.explain.stage4.ollama_adapter.get_ollama_client")
    def test_format_ollama_error_fallback(
        self, mock_get_client, sample_stage3_output
    ):
        """Format falls back on Ollama error."""
        mock_client = MagicMock()
        mock_client.generate.return_value = OllamaResponse(
            text="",
            model="llama3",
            done=False,
            latency_ms=0,
            prompt_hash="abc123",
            error="Connection refused",
        )
        mock_get_client.return_value = mock_client
        
        engine = Stage4Engine()
        engine.load_config({"stage4": {"enabled": True, "log_level": "off"}})
        
        result = engine.format(sample_stage3_output)
        
        assert result.used_llm is False
        assert result.fallback is True
        assert result.llm_text == sample_stage3_output["explain_text"]
    
    @patch("backend.explain.stage4.ollama_adapter.get_ollama_client")
    def test_format_validation_failure_fallback(
        self, mock_get_client, sample_stage3_output
    ):
        """Format falls back on validation failure."""
        mock_client = MagicMock()
        mock_client.generate.return_value = OllamaResponse(
            text="",  # Empty response fails validation
            model="llama3",
            done=True,
            latency_ms=100,
            prompt_hash="abc123",
            error=None,
        )
        mock_get_client.return_value = mock_client
        
        engine = Stage4Engine()
        engine.load_config({
            "stage4": {"enabled": True, "strict_validate": True, "log_level": "off"}
        })
        
        result = engine.format(sample_stage3_output)
        
        assert result.used_llm is False
        assert result.fallback is True
    
    @patch("backend.explain.stage4.ollama_adapter.get_ollama_client")
    def test_format_hallucination_fallback(
        self, mock_get_client, sample_stage3_output
    ):
        """Format falls back on hallucination detection."""
        mock_client = MagicMock()
        mock_client.generate.return_value = OllamaResponse(
            text="Tôi nghĩ bạn rất phù hợp. Khuyên bạn nên chọn Data Scientist.",
            model="llama3",
            done=True,
            latency_ms=100,
            prompt_hash="abc123",
            error=None,
        )
        mock_get_client.return_value = mock_client
        
        engine = Stage4Engine()
        engine.load_config({
            "stage4": {"enabled": True, "strict_validate": True, "log_level": "off"}
        })
        
        result = engine.format(sample_stage3_output)
        
        assert result.used_llm is False
        assert result.fallback is True
        assert any("hallucination" in issue.lower() for issue in result.validation_issues)
    
    @patch("backend.explain.stage4.ollama_adapter.get_ollama_client")
    def test_format_exception_fallback(
        self, mock_get_client, sample_stage3_output
    ):
        """Format falls back on exception."""
        mock_client = MagicMock()
        mock_client.generate.side_effect = Exception("Network error")
        mock_get_client.return_value = mock_client
        
        engine = Stage4Engine()
        engine.load_config({"stage4": {"enabled": True, "log_level": "off"}})
        
        result = engine.format(sample_stage3_output)
        
        assert result.used_llm is False
        assert result.fallback is True
    
    @patch("backend.explain.stage4.ollama_adapter.get_ollama_client")
    def test_is_enabled(self, mock_get_client):
        """is_enabled reflects config setting."""
        mock_get_client.return_value = MagicMock()
        
        engine = Stage4Engine()
        
        engine.load_config({"stage4": {"enabled": True, "log_level": "off"}})
        assert engine.is_enabled() is True
        
        engine.load_config({"stage4": {"enabled": False, "log_level": "off"}})
        assert engine.is_enabled() is False
    
    @patch("backend.explain.stage4.ollama_adapter.get_ollama_client")
    def test_health_check_delegates_to_client(self, mock_get_client):
        """health_check delegates to OllamaClient."""
        mock_client = MagicMock()
        mock_client.health_check.return_value = True
        mock_get_client.return_value = mock_client
        
        engine = Stage4Engine()
        
        assert engine.health_check() is True
        mock_client.health_check.assert_called_once()


# ==============================================================================
# Test format_with_llm Helper Function
# ==============================================================================

class TestFormatWithLLM:
    """Test format_with_llm helper function."""
    
    @patch("backend.explain.stage4.ollama_adapter.get_stage4_engine")
    def test_format_with_llm_returns_dict(
        self, mock_get_engine, sample_stage3_output
    ):
        """format_with_llm returns dict from engine."""
        mock_engine = MagicMock()
        mock_engine.format.return_value = Stage4Output(
            trace_id="test-123",
            career="Data Scientist",
            reasons=["Reason 1"],
            confidence=0.9,
            raw_text="Raw text",
            llm_text="LLM text",
            used_llm=True,
        )
        mock_get_engine.return_value = mock_engine
        
        result = format_with_llm(sample_stage3_output)
        
        assert isinstance(result, dict)
        assert result["llm_text"] == "LLM text"
        assert result["used_llm"] is True
        mock_engine.format.assert_called_once_with(sample_stage3_output)


# ==============================================================================
# Test OllamaClient
# ==============================================================================

class TestOllamaClient:
    """Test OllamaClient class."""
    
    def test_init_localhost_only(self):
        """OllamaClient only allows localhost."""
        client = OllamaClient()
        assert "127.0.0.1" in client._base_url or "localhost" in client._base_url
    
    def test_configure_updates_settings(self):
        """configure updates client settings."""
        client = OllamaClient()
        client.configure(model="mistral", timeout=10.0, max_retries=5)
        
        assert client._model == "mistral"
        assert client._timeout == 10.0
        assert client._max_retries == 5
    
    @patch("requests.get")
    def test_health_check_success(self, mock_get):
        """health_check returns True on success."""
        mock_get.return_value = MagicMock(status_code=200)
        
        client = OllamaClient()
        result = client.health_check()
        
        assert result is True
    
    @patch("requests.get")
    def test_health_check_failure(self, mock_get):
        """health_check returns False on failure."""
        mock_get.side_effect = Exception("Connection refused")
        
        client = OllamaClient()
        result = client.health_check()
        
        assert result is False
    
    @patch("requests.post")
    def test_generate_circuit_open_fails(self, mock_post):
        """generate fails when circuit is open."""
        client = OllamaClient()
        
        # Open the circuit
        client._circuit.state = CircuitState.OPEN
        client._circuit.last_failure_time = time.time()
        
        response = client.generate("Test prompt")
        
        assert response.success is False
        assert "circuit" in response.error.lower()
        mock_post.assert_not_called()
    
    @patch("requests.post")
    def test_generate_success(self, mock_post):
        """generate returns success on valid response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "Generated text",
            "model": "llama3",
            "done": True,
        }
        mock_post.return_value = mock_response
        
        client = OllamaClient()
        response = client.generate("Test prompt")
        
        assert response.success is True
        assert response.text == "Generated text"
        assert response.model == "llama3"
    
    @patch("requests.post")
    def test_generate_http_error_records_failure(self, mock_post):
        """generate records failure on HTTP error."""
        mock_post.side_effect = Exception("Connection refused")
        
        client = OllamaClient()
        response = client.generate("Test prompt")
        
        assert response.success is False
        assert client._circuit.failure_count > 0


# ==============================================================================
# Test Integration (Mocked)
# ==============================================================================

class TestIntegration:
    """Integration tests with mocked Ollama."""
    
    @patch("backend.explain.stage4.ollama_adapter.get_ollama_client")
    def test_full_pipeline_success(
        self, mock_get_client, sample_stage3_output
    ):
        """Full pipeline from Stage 3 output to Stage 4 output."""
        mock_client = MagicMock()
        mock_client.generate.return_value = OllamaResponse(
            text="Bạn phù hợp với ngành Data Scientist. Điểm Toán vượt ngưỡng và tư duy logic mạnh giúp bạn xử lý dữ liệu hiệu quả. Độ tin cậy 87%.",
            model="llama3",
            done=True,
            latency_ms=120.0,
            prompt_hash="abc123",
            error=None,
        )
        mock_get_client.return_value = mock_client
        
        engine = Stage4Engine()
        engine.load_config({"stage4": {"enabled": True, "log_level": "off"}})
        
        result = engine.format(sample_stage3_output)
        
        # Verify successful processing
        assert result.used_llm is True
        assert result.fallback is False
        assert result.trace_id == sample_stage3_output["trace_id"]
        assert result.career == sample_stage3_output["career"]
        assert result.confidence == sample_stage3_output["confidence"]
        
        # Verify LLM text is different from raw
        assert result.llm_text != result.raw_text
    
    @patch("backend.explain.stage4.ollama_adapter.get_ollama_client")
    def test_graceful_degradation(
        self, mock_get_client, sample_stage3_output
    ):
        """Pipeline gracefully degrades to Stage 3 on any failure."""
        mock_client = MagicMock()
        mock_client.generate.side_effect = Exception("Ollama not running")
        mock_get_client.return_value = mock_client
        
        engine = Stage4Engine()
        engine.load_config({"stage4": {"enabled": True, "log_level": "off"}})
        
        result = engine.format(sample_stage3_output)
        
        # Verify fallback
        assert result.used_llm is False
        assert result.fallback is True
        assert result.llm_text == sample_stage3_output["explain_text"]
        
        # Core data preserved
        assert result.trace_id == sample_stage3_output["trace_id"]
        assert result.career == sample_stage3_output["career"]
        assert result.reasons == sample_stage3_output["reasons"]


# ==============================================================================
# Test Audit Logging
# ==============================================================================

class TestAuditLogging:
    """Test audit logging functionality."""
    
    @patch("backend.explain.stage4.ollama_adapter.get_ollama_client")
    def test_audit_log_full_mode(
        self, mock_get_client, sample_stage3_output
    ):
        """Audit log writes in full mode."""
        mock_client = MagicMock()
        mock_client.generate.return_value = OllamaResponse(
            text="Formatted text",
            model="llama3",
            done=True,
            latency_ms=100,
            prompt_hash="abc123",
            error=None,
        )
        mock_get_client.return_value = mock_client
        
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = Stage4Engine(project_root=Path(tmpdir))
            engine.load_config({
                "stage4": {
                    "enabled": True,
                    "log_level": "full",
                    "log_dir": "logs",
                }
            })
            
            engine.format(sample_stage3_output)
            
            log_file = Path(tmpdir) / "logs" / "explain_stage4.log"
            assert log_file.exists()
            
            content = log_file.read_text()
            log_entry = json.loads(content.strip().split("\n")[-1])
            
            assert "trace_id" in log_entry
            assert log_entry["trace_id"] == sample_stage3_output["trace_id"]
    
    @patch("backend.explain.stage4.ollama_adapter.get_ollama_client")
    def test_audit_log_off_mode(
        self, mock_get_client, sample_stage3_output
    ):
        """Audit log disabled in off mode."""
        mock_client = MagicMock()
        mock_client.generate.return_value = OllamaResponse(
            text="Formatted text",
            model="llama3",
            done=True,
            latency_ms=100,
            prompt_hash="abc123",
            error=None,
        )
        mock_get_client.return_value = mock_client
        
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = Stage4Engine(project_root=Path(tmpdir))
            engine.load_config({
                "stage4": {
                    "enabled": True,
                    "log_level": "off",
                    "log_dir": "logs",
                }
            })
            
            engine.format(sample_stage3_output)
            
            log_file = Path(tmpdir) / "logs" / "explain_stage4.log"
            assert not log_file.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

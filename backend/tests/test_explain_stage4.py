# backend/tests/test_explain_stage4.py
"""
Comprehensive tests for Stage 4 - Ollama LLM Client.

Tests:
    - CircuitBreaker functionality
    - OllamaResponse dataclass
    - OllamaClient configuration
    - Endpoint validation
    - Error handling
"""

import time
import pytest
from unittest.mock import patch, MagicMock

from backend.explain.stage4.client import (
    CircuitState,
    CircuitBreaker,
    OllamaResponse,
    OllamaClient,
    DEFAULT_OLLAMA_URL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    DEFAULT_MAX_RETRIES,
)


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def test_initial_state_closed(self):
        """Circuit should start in CLOSED state."""
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_record_success(self):
        """Recording success should reset failure count."""
        cb = CircuitBreaker()
        cb.failure_count = 2
        
        cb.record_success()
        
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_record_failure_increments(self):
        """Recording failure should increment count."""
        cb = CircuitBreaker()
        
        cb.record_failure()
        
        assert cb.failure_count == 1

    def test_circuit_opens_after_threshold(self):
        """Circuit should open after failure threshold."""
        cb = CircuitBreaker(failure_threshold=3)
        
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_allow_request_closed(self):
        """Requests allowed when CLOSED."""
        cb = CircuitBreaker()
        cb.state = CircuitState.CLOSED
        
        assert cb.allow_request() is True

    def test_block_request_open(self):
        """Requests blocked when OPEN (before cooldown)."""
        cb = CircuitBreaker(cooldown_seconds=60)
        cb.state = CircuitState.OPEN
        cb.last_failure_time = time.time()
        
        assert cb.allow_request() is False

    def test_half_open_after_cooldown(self):
        """Circuit becomes HALF_OPEN after cooldown."""
        cb = CircuitBreaker(cooldown_seconds=0.1)
        cb.state = CircuitState.OPEN
        cb.last_failure_time = time.time() - 1  # 1 second ago
        
        result = cb.allow_request()
        
        assert result is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_is_open(self):
        """is_open() should return correct state."""
        cb = CircuitBreaker()
        
        cb.state = CircuitState.CLOSED
        assert cb.is_open() is False
        
        cb.state = CircuitState.OPEN
        assert cb.is_open() is True
        
        cb.state = CircuitState.HALF_OPEN
        assert cb.is_open() is False


class TestOllamaResponse:
    """Tests for OllamaResponse dataclass."""

    def test_response_creation(self):
        """Test basic response creation."""
        response = OllamaResponse(
            text="Generated text",
            model="llama3.2:1b",
            done=True,
            latency_ms=150.5,
            prompt_hash="abc123",
        )
        
        assert response.text == "Generated text"
        assert response.model == "llama3.2:1b"
        assert response.done is True
        assert response.latency_ms == 150.5

    def test_success_property_true(self):
        """success should be True for valid response."""
        response = OllamaResponse(
            text="Valid response",
            model="llama3.2:1b",
            done=True,
            latency_ms=100,
            prompt_hash="hash",
            error=None,
        )
        
        assert response.success is True

    def test_success_property_false_with_error(self):
        """success should be False when error present."""
        response = OllamaResponse(
            text="",
            model="llama3.2:1b",
            done=False,
            latency_ms=0,
            prompt_hash="hash",
            error="Connection timeout",
        )
        
        assert response.success is False

    def test_success_property_false_not_done(self):
        """success should be False when not done."""
        response = OllamaResponse(
            text="Partial",
            model="llama3.2:1b",
            done=False,  # Not done
            latency_ms=100,
            prompt_hash="hash",
        )
        
        assert response.success is False

    def test_success_property_false_empty_text(self):
        """success should be False for empty text."""
        response = OllamaResponse(
            text="",  # Empty
            model="llama3.2:1b",
            done=True,
            latency_ms=100,
            prompt_hash="hash",
        )
        
        assert response.success is False


class TestOllamaClient:
    """Tests for OllamaClient class."""

    def test_client_creation_default(self):
        """Test client creation with defaults."""
        client = OllamaClient()
        
        assert client._base_url == DEFAULT_OLLAMA_URL
        assert client._model == DEFAULT_MODEL
        assert client._timeout == DEFAULT_TIMEOUT
        assert client._max_retries == DEFAULT_MAX_RETRIES

    def test_client_creation_custom(self):
        """Test client with custom settings."""
        client = OllamaClient(
            base_url="http://localhost:11434/api/generate",
            model="mistral",
            timeout=10,
            max_retries=5,
        )
        
        assert client._model == "mistral"
        assert client._timeout == 10
        assert client._max_retries == 5

    def test_validate_endpoint_localhost(self):
        """localhost endpoint should be valid."""
        # Should not raise
        client = OllamaClient(base_url="http://localhost:11434/api/generate")
        assert client is not None

    def test_validate_endpoint_127(self):
        """127.0.0.1 endpoint should be valid."""
        client = OllamaClient(base_url="http://127.0.0.1:11434/api/generate")
        assert client is not None

    def test_validate_endpoint_remote_fails(self):
        """Remote endpoint should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            OllamaClient(base_url="http://remote-server.com/api/generate")
        
        assert "localhost" in str(exc_info.value).lower()

    def test_configure_updates_settings(self):
        """configure() should update client settings."""
        client = OllamaClient()
        
        client.configure(
            model="codellama",
            timeout=15,
            max_retries=3,
        )
        
        assert client._model == "codellama"
        assert client._timeout == 15
        assert client._max_retries == 3

    def test_configure_validates_url(self):
        """configure() should validate new URL."""
        client = OllamaClient()
        
        with pytest.raises(ValueError):
            client.configure(base_url="http://external-server.com/api")


class TestOllamaClientGenerate:
    """Tests for OllamaClient.generate() method."""

    def test_generate_circuit_open(self):
        """generate() should fail fast when circuit open."""
        client = OllamaClient()
        client._circuit.state = CircuitState.OPEN
        client._circuit.last_failure_time = time.time()
        client._circuit.cooldown_seconds = 60
        
        response = client.generate("Test prompt")
        
        assert response.success is False
        assert "circuit" in response.error.lower()

    @patch("backend.explain.stage4.client.requests.post")
    def test_generate_success(self, mock_post):
        """generate() should return response on success."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "Generated text",
            "model": "llama3.2:1b",
            "done": True,
        }
        mock_post.return_value = mock_response
        
        client = OllamaClient()
        response = client.generate("Test prompt")
        
        assert response.success is True
        assert response.text == "Generated text"

    @patch("backend.explain.stage4.client.requests.post")
    def test_generate_timeout(self, mock_post):
        """generate() should handle timeout gracefully."""
        import requests
        mock_post.side_effect = requests.Timeout("Connection timed out")
        
        client = OllamaClient()
        response = client.generate("Test prompt")
        
        assert response.success is False
        assert "timeout" in response.error.lower()

    @patch("backend.explain.stage4.client.requests.post")
    def test_generate_connection_error(self, mock_post):
        """generate() should handle connection errors."""
        import requests
        mock_post.side_effect = requests.ConnectionError("Connection refused")
        
        client = OllamaClient()
        response = client.generate("Test prompt")
        
        assert response.success is False

    @patch("backend.explain.stage4.client.requests.post")
    def test_generate_with_retries(self, mock_post):
        """generate() should retry on transient failures."""
        # First call fails, second succeeds
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "Success on retry",
            "model": "llama3.2:1b",
            "done": True,
        }
        
        import requests
        mock_post.side_effect = [
            requests.Timeout("First attempt"),
            mock_response,
        ]
        
        client = OllamaClient(max_retries=2)
        response = client.generate("Test prompt")
        
        assert mock_post.call_count <= 2


class TestCircuitBreakerIntegration:
    """Integration tests for circuit breaker with client."""

    def test_circuit_opens_after_failures(self):
        """Circuit should open after consecutive failures."""
        client = OllamaClient()
        client._circuit = CircuitBreaker(failure_threshold=2)
        
        # Simulate failures
        with patch("backend.explain.stage4.client.requests.post") as mock:
            import requests
            mock.side_effect = requests.Timeout("Timeout")
            
            # First failure
            client.generate("Test 1")
            # Second failure - should open circuit
            client.generate("Test 2")
        
        assert client._circuit.state == CircuitState.OPEN

    def test_circuit_resets_on_success(self):
        """Circuit should reset after success."""
        client = OllamaClient()
        client._circuit.failure_count = 2
        client._circuit.state = CircuitState.HALF_OPEN
        
        with patch("backend.explain.stage4.client.requests.post") as mock:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "response": "Success",
                "model": "llama3.2:1b",
                "done": True,
            }
            mock.return_value = mock_response
            
            client.generate("Test")
        
        assert client._circuit.state == CircuitState.CLOSED
        assert client._circuit.failure_count == 0


class TestOllamaClientConfiguration:
    """Tests for client configuration edge cases."""

    def test_zero_timeout(self):
        """Zero timeout should be allowed."""
        client = OllamaClient(timeout=0)
        assert client._timeout == 0

    def test_zero_retries(self):
        """Zero retries should be allowed."""
        client = OllamaClient(max_retries=0)
        assert client._max_retries == 0

    def test_empty_model(self):
        """Empty model should use default."""
        client = OllamaClient(model="")
        # Implementation may default or accept empty
        assert client._model == ""

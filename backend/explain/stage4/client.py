# backend/explain/stage4/client.py
"""
Ollama Client for Stage 4
=========================

HTTP client for local Ollama LLM with:
  - Timeout < 5s
  - Retry ≤ 2
  - Circuit breaker
  - Local-only endpoint
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger("explain.stage4.client")


# ==============================================================================
# Configuration
# ==============================================================================

DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3.2:1b"
DEFAULT_TIMEOUT = 5  # seconds
DEFAULT_MAX_RETRIES = 2


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject calls
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreaker:
    """
    Circuit breaker to prevent cascading failures.
    
    - CLOSED: Normal operation
    - OPEN: After N failures, reject calls for cooldown period
    - HALF_OPEN: After cooldown, allow one test call
    """
    
    failure_threshold: int = 3
    cooldown_seconds: float = 30.0
    
    # State
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    
    def record_success(self) -> None:
        """Record successful call."""
        with self._lock:
            self.failure_count = 0
            self.state = CircuitState.CLOSED
    
    def record_failure(self) -> None:
        """Record failed call."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(
                    f"Circuit breaker OPEN after {self.failure_count} failures"
                )
    
    def allow_request(self) -> bool:
        """Check if request should be allowed."""
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            
            if self.state == CircuitState.OPEN:
                # Check if cooldown expired
                elapsed = time.time() - self.last_failure_time
                if elapsed >= self.cooldown_seconds:
                    self.state = CircuitState.HALF_OPEN
                    logger.info("Circuit breaker HALF_OPEN, testing recovery")
                    return True
                return False
            
            # HALF_OPEN: allow one test request
            return True
    
    def is_open(self) -> bool:
        """Check if circuit is open (rejecting calls)."""
        with self._lock:
            return self.state == CircuitState.OPEN


@dataclass
class OllamaResponse:
    """Response from Ollama API."""
    
    text: str
    model: str
    done: bool
    latency_ms: float
    prompt_hash: str
    raw_response: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    
    @property
    def success(self) -> bool:
        return self.error is None and self.done and len(self.text) > 0


class OllamaClient:
    """
    HTTP client for local Ollama LLM.
    
    Features:
      - Configurable timeout (default 5s)
      - Retry with exponential backoff (max 2)
      - Circuit breaker for failure protection
      - Local-only endpoint validation
    
    Usage::
    
        client = OllamaClient()
        response = client.generate("Rewrite this text...")
        
        if response.success:
            print(response.text)
        else:
            print(f"Error: {response.error}")
    """
    
    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self._base_url = base_url
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries
        
        # Circuit breaker
        self._circuit = CircuitBreaker()
        
        # Validate local-only endpoint
        self._validate_endpoint()
    
    def _validate_endpoint(self) -> None:
        """Ensure endpoint is localhost only."""
        url_lower = self._base_url.lower()
        if not any(local in url_lower for local in ["localhost", "127.0.0.1", "0.0.0.0"]):
            raise ValueError(
                f"Ollama endpoint must be localhost: {self._base_url}"
            )
    
    def configure(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> None:
        """Update client configuration."""
        if base_url:
            self._base_url = base_url
            self._validate_endpoint()
        if model:
            self._model = model
        if timeout is not None:
            self._timeout = timeout
        if max_retries is not None:
            self._max_retries = max_retries
    
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 500,
    ) -> OllamaResponse:
        """
        Generate text using Ollama.
        
        Args:
            prompt: User prompt
            system_prompt: System instruction
            temperature: Sampling temperature (0 = deterministic)
            max_tokens: Maximum tokens to generate
            
        Returns:
            OllamaResponse with generated text or error
        """
        # Check circuit breaker
        if not self._circuit.allow_request():
            return OllamaResponse(
                text="",
                model=self._model,
                done=False,
                latency_ms=0,
                prompt_hash=self._hash_prompt(prompt),
                error="Circuit breaker OPEN - Ollama unavailable",
            )
        
        # Build request payload
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        
        if system_prompt:
            payload["system"] = system_prompt
        
        prompt_hash = self._hash_prompt(prompt)
        start_time = time.time()
        
        # Retry loop
        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                response = requests.post(
                    self._base_url,
                    json=payload,
                    timeout=self._timeout,
                )
                
                latency_ms = (time.time() - start_time) * 1000
                
                if response.status_code == 200:
                    data = response.json()
                    
                    self._circuit.record_success()
                    
                    return OllamaResponse(
                        text=data.get("response", ""),
                        model=data.get("model", self._model),
                        done=data.get("done", False),
                        latency_ms=latency_ms,
                        prompt_hash=prompt_hash,
                        raw_response=data,
                    )
                else:
                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                    logger.warning(f"Ollama request failed: {last_error}")
                    
            except requests.Timeout:
                latency_ms = (time.time() - start_time) * 1000
                last_error = f"Timeout after {self._timeout}s"
                logger.warning(f"Ollama timeout (attempt {attempt + 1})")
                
            except requests.ConnectionError as e:
                latency_ms = (time.time() - start_time) * 1000
                last_error = f"Connection error: {str(e)[:100]}"
                logger.warning(f"Ollama connection error: {last_error}")
                
            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                last_error = f"Unexpected error: {str(e)[:100]}"
                logger.error(f"Ollama unexpected error: {e}")
            
            # Exponential backoff before retry
            if attempt < self._max_retries:
                backoff = 0.5 * (2 ** attempt)
                time.sleep(backoff)
        
        # All retries failed
        self._circuit.record_failure()
        
        return OllamaResponse(
            text="",
            model=self._model,
            done=False,
            latency_ms=latency_ms,
            prompt_hash=prompt_hash,
            error=last_error,
        )
    
    def _hash_prompt(self, prompt: str) -> str:
        """Compute hash of prompt for audit."""
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    
    def health_check(self) -> bool:
        """Check if Ollama is available."""
        try:
            # Use tags endpoint for health check
            url = self._base_url.replace("/api/generate", "/api/tags")
            response = requests.get(url, timeout=2)
            return response.status_code == 200
        except Exception:
            return False
    
    def get_model(self) -> str:
        """Get current model name."""
        return self._model
    
    def get_circuit_state(self) -> str:
        """Get circuit breaker state."""
        return self._circuit.state.value
    
    def reset_circuit(self) -> None:
        """Reset circuit breaker to closed state."""
        self._circuit.state = CircuitState.CLOSED
        self._circuit.failure_count = 0


# ==============================================================================
# Singleton
# ==============================================================================

_ollama_client: Optional[OllamaClient] = None


def get_ollama_client() -> OllamaClient:
    """Get or create singleton OllamaClient."""
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient()
    return _ollama_client

"""
LLM providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import json
import logging
import time
import requests

logger = logging.getLogger(__name__)


class LLMProviderError(RuntimeError):
    """Provider error."""


class BaseLLMProvider(ABC):
    @abstractmethod
    def analyze(self, user_text: str) -> Dict[str, Any]:
        raise NotImplementedError


class OllamaProvider(BaseLLMProvider):
    """
    Ollama provider using /api/generate for deterministic JSON output.
    
    Features:
    - Automatic retry with exponential backoff (configurable)
    - First request handling for cold start scenarios
    """

    # Retry configuration
    MAX_RETRIES = 3
    BACKOFF_BASE = 1.0  # seconds
    BACKOFF_MULTIPLIER = 2.0  # exponential backoff

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float = 10.0,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._request_count = 0

    def analyze(self, user_text: str) -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "prompt": user_text,
            "stream": False
        }

        self._request_count += 1
        is_first_request = self._request_count == 1
        
        # Use more retries for first request (cold start scenario)
        retries = self.max_retries if is_first_request else 1
        last_error = None

        for attempt in range(retries):
            try:
                # Increase timeout for first request (model loading)
                timeout = self.timeout_s * (2 if is_first_request and attempt == 0 else 1)
                
                response = requests.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=timeout
                )
                response.raise_for_status()
                
                # Success - parse response
                return self._parse_response(response)
                
            except requests.exceptions.Timeout as exc:
                last_error = exc
                logger.warning(
                    "Ollama request timeout (attempt %d/%d, timeout=%.1fs)",
                    attempt + 1,
                    retries,
                    timeout,
                )
            except requests.exceptions.RequestException as exc:
                last_error = exc
                logger.warning(
                    "Ollama request failed (attempt %d/%d): %s",
                    attempt + 1,
                    retries,
                    str(exc)[:100],
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Ollama error (attempt %d/%d): %s",
                    attempt + 1,
                    retries,
                    str(exc)[:100],
                )

            # Exponential backoff before retry
            if attempt < retries - 1:
                backoff = self.BACKOFF_BASE * (self.BACKOFF_MULTIPLIER ** attempt)
                time.sleep(backoff)

        raise LLMProviderError(f"Ollama request failed after {retries} retries: {last_error}") from last_error

    def _parse_response(self, response: requests.Response) -> Dict[str, Any]:
        """Parse Ollama response with fallback JSON extraction."""
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise LLMProviderError("Invalid JSON from Ollama") from exc

        # Ollama returns {"response": "..."} for /api/generate
        content = data.get("response", "")
        if not content:
            raise LLMProviderError("Empty Ollama response")

        # Best-effort JSON parse with fallback extraction
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON block from text
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(content[start:end + 1])
                except json.JSONDecodeError as exc:
                    raise LLMProviderError("Ollama response is not JSON") from exc
            raise LLMProviderError("Ollama response is not JSON")


class CloudFallbackProvider(BaseLLMProvider):
    """
    Optional cloud fallback stub.
    This preserves compatibility if you later plug in OpenAI or other APIs.
    """

    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def analyze(self, user_text: str) -> Dict[str, Any]:
        if not self.enabled:
            raise LLMProviderError("Cloud fallback disabled")
        raise LLMProviderError("Cloud fallback not configured")

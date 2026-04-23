"""
LLM client abstraction with provider selection and fallback.
"""

from __future__ import annotations

from typing import Dict, Any

from .config import load_llm_config
from .providers import (
    BaseLLMProvider,
    OllamaProvider,
    CloudFallbackProvider,
    LLMProviderError
)


class LLMClient:
    def __init__(self, provider: BaseLLMProvider, fallback: BaseLLMProvider | None = None):
        self.provider = provider
        self.fallback = fallback

    def analyze(self, user_text: str) -> Dict[str, Any]:
        try:
            return self.provider.analyze(user_text)
        except LLMProviderError:
            if self.fallback is None:
                raise
            return self.fallback.analyze(user_text)


def build_default_client() -> LLMClient:
    cfg = load_llm_config()

    if cfg.provider == "ollama":
        provider = OllamaProvider(cfg.ollama_url, cfg.ollama_model, cfg.timeout_s)
    else:
        # Unknown provider -> force fallback path
        provider = CloudFallbackProvider(enabled=False)

    fallback = CloudFallbackProvider(enabled=cfg.cloud_enabled)

    return LLMClient(provider=provider, fallback=fallback)

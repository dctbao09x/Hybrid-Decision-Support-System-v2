"""
LLM configuration via environment variables.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    ollama_url: str
    ollama_model: str
    timeout_s: float
    cloud_enabled: bool


def load_llm_config() -> LLMConfig:
    return LLMConfig(
        provider=os.getenv("LLM_PROVIDER", "ollama").strip().lower(),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434").strip(),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2:1b").strip(),
        timeout_s=float(os.getenv("LLM_TIMEOUT", "10")),
        cloud_enabled=os.getenv("LLM_CLOUD_FALLBACK", "0").strip() in ("1", "true", "yes")
    )

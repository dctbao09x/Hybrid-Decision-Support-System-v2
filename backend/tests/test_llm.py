# backend/tests/test_llm.py
"""Unit tests for backend.llm — config, providers, client."""

import os
from unittest.mock import patch, MagicMock

import pytest


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LLMConfig
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestLLMConfig:
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            from backend.llm.config import load_llm_config
            # Need to reload to pick up cleared env
            cfg = load_llm_config()
            assert cfg.provider == "ollama"
            assert "localhost" in cfg.ollama_url
            assert cfg.timeout_s == 10.0
            assert cfg.cloud_enabled is False

    def test_cloud_enabled_true(self):
        for truthy in ("1", "true", "yes"):
            with patch.dict(os.environ, {"LLM_CLOUD_FALLBACK": truthy}):
                from backend.llm.config import load_llm_config
                cfg = load_llm_config()
                assert cfg.cloud_enabled is True, f"'{truthy}' should be truthy"

    def test_cloud_enabled_false(self):
        for falsy in ("0", "false", "no", ""):
            with patch.dict(os.environ, {"LLM_CLOUD_FALLBACK": falsy}):
                from backend.llm.config import load_llm_config
                cfg = load_llm_config()
                assert cfg.cloud_enabled is False

    def test_frozen_dataclass(self):
        from backend.llm.config import load_llm_config
        cfg = load_llm_config()
        with pytest.raises(AttributeError):
            cfg.provider = "other"

    def test_custom_timeout(self):
        with patch.dict(os.environ, {"LLM_TIMEOUT": "30"}):
            from backend.llm.config import load_llm_config
            cfg = load_llm_config()
            assert cfg.timeout_s == 30.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Providers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestOllamaProvider:
    def test_strip_trailing_slash(self):
        from backend.llm.providers import OllamaProvider
        p = OllamaProvider("http://localhost:11434/", "llama3.2:1b")
        assert not p.base_url.endswith("/")

    def test_analyze_network_error(self):
        from backend.llm.providers import OllamaProvider, LLMProviderError
        p = OllamaProvider("http://localhost:99999", "bad-model", timeout_s=1.0)
        with pytest.raises(LLMProviderError):
            p.analyze("Hello")


class TestCloudFallbackProvider:
    def test_disabled_raises(self):
        from backend.llm.providers import CloudFallbackProvider, LLMProviderError
        p = CloudFallbackProvider(enabled=False)
        with pytest.raises(LLMProviderError):
            p.analyze("hello")

    def test_enabled_raises(self):
        from backend.llm.providers import CloudFallbackProvider, LLMProviderError
        p = CloudFallbackProvider(enabled=True)
        with pytest.raises(LLMProviderError):
            p.analyze("hello")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LLMClient
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TestLLMClient:
    def test_primary_success(self):
        from backend.llm.client import LLMClient
        primary = MagicMock()
        primary.analyze.return_value = {"result": "ok"}
        client = LLMClient(provider=primary)
        result = client.analyze("test")
        assert result == {"result": "ok"}
        primary.analyze.assert_called_once_with("test")

    def test_primary_fail_fallback_success(self):
        from backend.llm.client import LLMClient
        from backend.llm.providers import LLMProviderError
        primary = MagicMock()
        primary.analyze.side_effect = LLMProviderError("primary down")
        fallback = MagicMock()
        fallback.analyze.return_value = {"result": "fallback"}
        client = LLMClient(provider=primary, fallback=fallback)
        result = client.analyze("test")
        assert result == {"result": "fallback"}

    def test_primary_fail_no_fallback_raises(self):
        from backend.llm.client import LLMClient
        from backend.llm.providers import LLMProviderError
        primary = MagicMock()
        primary.analyze.side_effect = LLMProviderError("down")
        client = LLMClient(provider=primary, fallback=None)
        with pytest.raises(LLMProviderError):
            client.analyze("test")

    def test_primary_non_llm_error_propagates(self):
        from backend.llm.client import LLMClient
        primary = MagicMock()
        primary.analyze.side_effect = ValueError("not LLM error")
        fallback = MagicMock()
        client = LLMClient(provider=primary, fallback=fallback)
        with pytest.raises(ValueError):
            client.analyze("test")
        fallback.analyze.assert_not_called()

    def test_build_default_client_ollama(self):
        from backend.llm.client import build_default_client
        with patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}):
            client = build_default_client()
            assert client is not None

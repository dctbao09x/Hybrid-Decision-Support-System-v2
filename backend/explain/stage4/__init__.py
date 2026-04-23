# backend/explain/stage4/__init__.py
"""
Stage 4: Ollama LLM Formatting
==============================

Transforms Stage 3 explanation into natural Vietnamese using Ollama LLM.

This is a FORMATTER layer only:
  - Does NOT add new information
  - Does NOT change meaning  
  - Does NOT infer anything
  - Has mandatory fallback to Stage 3

Usage::

    from backend.explain.stage4 import format_with_llm
    
    result = format_with_llm(stage3_output)
    print(result["llm_text"])
"""

from backend.explain.stage4.client import (
    CircuitBreaker,
    CircuitState,
    OllamaClient,
    OllamaResponse,
    get_ollama_client,
)
from backend.explain.stage4.ollama_adapter import (
    OutputValidator,
    Stage4Config,
    Stage4Engine,
    Stage4Output,
    ValidationResult,
    format_with_llm,
    generate_analytical_summary,
    generate_structured_explanation,
    get_stage4_engine,
)

__all__ = [
    # Client
    "OllamaClient",
    "OllamaResponse",
    "CircuitBreaker",
    "CircuitState",
    "get_ollama_client",
    # Adapter
    "Stage4Engine",
    "Stage4Output",
    "Stage4Config",
    "OutputValidator",
    "ValidationResult",
    "format_with_llm",
    "generate_analytical_summary",
    "generate_structured_explanation",
    "get_stage4_engine",
]

__version__ = "1.0.0"

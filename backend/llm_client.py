"""
LLM client wrapper (compatibility layer).
"""

import json
from backend.llm.client import build_default_client
from backend.llm.providers import LLMProviderError


SYSTEM_PROMPT = """
You are an AI semantic analyzer for a career guidance system.

Task:
Analyze the user profile and extract structured features.

Return ONLY valid JSON with:
- intent (learning / career / switching / unclear)
- main_domains (list)
- skill_level (low / medium / high)
- motivation_score (0-1)
- ai_relevance_score (0-1)
- summary (string)

No explanation.
No markdown.
No extra text.
"""


def analyze_with_llm(user_text: str) -> dict:
    client = build_default_client()

    # Ollama /api/generate expects a full prompt, so embed system prompt.
    prompt = f"{SYSTEM_PROMPT}\n\nUSER:\n{user_text}\n"

    try:
        return client.analyze(prompt)
    except LLMProviderError as exc:
        raise RuntimeError(str(exc)) from exc

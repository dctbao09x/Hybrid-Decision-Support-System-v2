"""
LLM adapter: normalize LLM outputs via taxonomy facade.
"""

from typing import Dict, List, Any

from backend.llm_client import analyze_with_llm as _analyze_with_llm
from backend.taxonomy.facade import taxonomy


def analyze_with_llm(user_text: str) -> Dict[str, Any]:
    """
    Run LLM analyzer and normalize outputs via taxonomy.
    Deterministic post-processing only.
    """

    data = _analyze_with_llm(user_text) or {}

    # Normalize intent to taxonomy id
    intent_raw = data.get("intent", "")
    if intent_raw:
        data["intent"] = taxonomy.detect_intent(intent_raw, return_id=True)

    # Normalize main_domains into interest labels
    domains_raw = data.get("main_domains", [])
    if isinstance(domains_raw, list) and domains_raw:
        data["main_domains"] = taxonomy.resolve_interests(
            [str(x) for x in domains_raw],
            return_ids=False
        )

    return data

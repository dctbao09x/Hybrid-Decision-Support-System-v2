# backend/explain/stage3/rule_map.py
"""
Rule Mapping Layer for Stage 3
==============================

Maps reason codes from XAI (Stage 2) to human-readable Vietnamese text.

Rules:
  - All mappings are centralized in REASON_MAP
  - No hardcoded text outside the map
  - Unknown codes are logged and skipped
  - Source binding adds evidence trail (shap|coef|perm|importance)
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("explain.stage3.rule_map")


# ==============================================================================
# REASON CODE -> TEXT MAPPING
# ==============================================================================

REASON_MAP: Dict[str, str] = {
    # Academic scores - High
    "math_high": "Điểm Toán vượt ngưỡng yêu cầu",
    "math_excellent": "Điểm Toán xuất sắc",
    "math_good": "Điểm Toán ở mức khá",
    "physics_high": "Nền tảng Vật lý vững chắc",
    "physics_good": "Nền tảng Vật lý ổn định",
    "physics_excellent": "Điểm Vật lý xuất sắc",
    "chemistry_high": "Điểm Hóa học cao",
    "chemistry_good": "Nền tảng Hóa học tốt",
    "literature_high": "Năng lực Văn học tốt",
    "literature_good": "Khả năng diễn đạt văn học khá",
    "english_high": "Trình độ tiếng Anh tốt",
    "english_good": "Tiếng Anh ở mức khá",
    
    # Aptitude/Skill scores
    "logic_strong": "Năng lực tư duy logic tốt",
    "logic_high": "Tư duy logic mạnh",
    "logic_good": "Khả năng logic khá",
    "creativity_high": "Tư duy sáng tạo cao",
    "creativity_good": "Có khả năng sáng tạo",
    "communication_high": "Kỹ năng giao tiếp tốt",
    "communication_good": "Giao tiếp khá",
    "leadership_high": "Có năng lực lãnh đạo",
    "analytical_high": "Khả năng phân tích mạnh",
    "analytical_good": "Tư duy phân tích khá",
    "data_skill": "Kỹ năng xử lý dữ liệu tốt",
    "problem_solving": "Khả năng giải quyết vấn đề tốt",
    
    # Interest areas
    "ai_interest": "Mức độ quan tâm cao tới AI",
    "ai_interest_high": "Rất quan tâm đến AI/ML",
    "it_interest": "Quan tâm mạnh đến CNTT",
    "it_interest_high": "Đam mê công nghệ thông tin",
    "business_interest": "Quan tâm đến kinh doanh",
    "design_interest": "Yêu thích thiết kế sáng tạo",
    "science_interest": "Đam mê nghiên cứu khoa học",
    "healthcare_interest": "Quan tâm đến y tế sức khỏe",
    
    # Personality traits
    "personality_open": "Tính cách cởi mở, sẵn sàng học hỏi",
    "personality_analytical": "Tính cách hướng phân tích",
    "personality_creative": "Tính cách sáng tạo",
    "personality_social": "Tính cách hướng ngoại",
    
    # Combined/Derived
    "stem_strong": "Nền tảng STEM vững chắc",
    "technical_aptitude": "Năng khiếu kỹ thuật tốt",
    "quantitative_strong": "Khả năng định lượng cao",
    "verbal_strong": "Năng lực ngôn ngữ tốt",
    
    # Generic patterns (from XAI feature names)
    "math_score_high": "Điểm Toán vượt ngưỡng yêu cầu",
    "logic_score_high": "Năng lực tư duy logic tốt",
    "interest_it_high": "Quan tâm mạnh đến CNTT",
    "interest_ai_high": "Mức độ quan tâm cao tới AI",
}

# Valid evidence sources
VALID_SOURCES = frozenset({"shap", "coef", "perm", "importance"})


def get_reason_text(code: str) -> Optional[str]:
    """
    Get reason text for a code.
    
    Args:
        code: Reason code from XAI
        
    Returns:
        Vietnamese text or None if unknown
    """
    return REASON_MAP.get(code)


def bind_evidence(reason_text: str, source: str) -> str:
    """
    Bind evidence source to reason text.
    
    Args:
        reason_text: The translated reason text
        source: Evidence source (shap|coef|perm|importance)
        
    Returns:
        Text with source annotation, e.g., "Điểm Toán cao (shap)"
    """
    if source and source in VALID_SOURCES:
        return f"{reason_text} ({source})"
    return reason_text


def map_reasons(
    reason_codes: List[str],
    sources: Optional[List[str]] = None,
) -> Tuple[List[str], List[str], List[str]]:
    """
    Map reason codes to text with evidence binding.
    
    Args:
        reason_codes: List of reason codes from XAI
        sources: List of evidence sources (parallel to reason_codes or single)
        
    Returns:
        Tuple of (mapped_reasons, used_codes, skipped_codes)
    """
    mapped = []
    used = []
    skipped = []
    
    # Normalize sources
    if sources is None:
        sources = []
    
    # If single source provided, apply to all
    if len(sources) == 1 and len(reason_codes) > 1:
        sources = sources * len(reason_codes)
    
    for i, code in enumerate(reason_codes):
        text = get_reason_text(code)
        
        if text is None:
            logger.warning(f"Unknown reason code: {code}")
            skipped.append(code)
            continue
        
        # Get source for this reason
        source = sources[i] if i < len(sources) else ""
        
        # Bind evidence
        reason_with_source = bind_evidence(text, source)
        mapped.append(reason_with_source)
        used.append(code)
    
    return mapped, used, skipped


def is_valid_source(source: str) -> bool:
    """Check if source is valid."""
    return source in VALID_SOURCES


def list_all_codes() -> List[str]:
    """Get all available reason codes."""
    return list(REASON_MAP.keys())


def add_reason_mapping(code: str, text: str) -> None:
    """
    Add or update a reason mapping at runtime.
    
    Args:
        code: Reason code
        text: Vietnamese text
    """
    REASON_MAP[code] = text
    logger.info(f"Added reason mapping: {code} -> {text}")

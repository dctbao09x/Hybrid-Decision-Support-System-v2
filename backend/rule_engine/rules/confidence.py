# backend/rule_engine/rules/confidence.py
"""
Confidence Rules - Luật đánh giá độ tin cậy
"""
from typing import Dict, Any
from ..rule_base import Rule


class ConfidenceLevelRule(Rule):
    """Phân loại mức độ tin cậy"""
    
    def __init__(self):
        super().__init__(name="ConfidenceLevelRule", priority=60)
        self.high_threshold = 0.8
        self.low_threshold = 0.4
        self.high_bonus = 0.1
        self.low_penalty = -0.1
    
    def evaluate(self, profile: Dict, job: Dict) -> Dict[str, Any]:
        confidence = profile.get("confidence_score", 0.0)
        
        if confidence >= self.high_threshold:
            return {
                "passed": True,
                "score_delta": self.high_bonus,
                "flags": ["high_confidence"],
                "warnings": []
            }
        
        if confidence < self.low_threshold:
            return {
                "passed": True,
                "score_delta": self.low_penalty,
                "flags": ["low_confidence"],
                "warnings": ["Hồ sơ chưa đầy đủ, nên bổ sung thêm thông tin"]
            }
        
        return {
            "passed": True,
            "score_delta": 0.0,
            "flags": ["medium_confidence"],
            "warnings": []
        }


class DataCompletenessRule(Rule):
    """Kiểm tra tính đầy đủ của dữ liệu"""
    
    def __init__(self):
        super().__init__(name="DataCompletenessRule", priority=55)
        self.required_fields = [
            "age",
            "education_level",
            "interest_tags",
            "skill_tags",
            "goal_cleaned",
        ]
        self.low_threshold = 0.4
        self.high_threshold = 0.8
        self.low_penalty = -0.15
        self.high_bonus = 0.05
    
    def evaluate(self, profile: Dict, job: Dict) -> Dict[str, Any]:
        completeness_score = 0
        fields = self.required_fields if isinstance(self.required_fields, list) else []
        total_fields = len(fields) or 1

        for field_name in fields:
            value = profile.get(field_name)
            if field_name == "age":
                if value and int(value) > 0:
                    completeness_score += 1
                continue
            if field_name == "education_level":
                if value and value != "unknown":
                    completeness_score += 1
                continue
            if value:
                completeness_score += 1

        completeness_ratio = completeness_score / total_fields

        if completeness_ratio < self.low_threshold:
            return {
                "passed": True,
                "score_delta": self.low_penalty,
                "flags": ["incomplete_profile"],
                "warnings": ["Hồ sơ thiếu nhiều thông tin quan trọng"]
            }
        
        if completeness_ratio >= self.high_threshold:
            return {
                "passed": True,
                "score_delta": self.high_bonus,
                "flags": ["complete_profile"],
                "warnings": []
            }
        
        return {
            "passed": True,
            "score_delta": 0.0,
            "flags": [],
            "warnings": []
        }
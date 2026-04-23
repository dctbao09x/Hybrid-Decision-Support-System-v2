# backend/rule_engine/rules/skill_matching.py
"""
Skill Matching Rules - Luật khớp kỹ năng
"""
from typing import Dict, Any, List
from ..rule_base import Rule
from ..taxonomy_adapter import normalize_skill_list


class RequiredSkillRule(Rule):
    """Kiểm tra kỹ năng bắt buộc"""
    
    def __init__(self):
        super().__init__(name="RequiredSkillRule", priority=90)
        self.penalty_factor = 0.3
        self.success_bonus = 0.2
        self.max_missing_ratio = 1.0
    
    def evaluate(self, profile: Dict, job: Dict) -> Dict[str, Any]:
        user_skills = set(
            s.lower()
            for s in normalize_skill_list(profile.get("skill_tags", []))
        )
        required_skills = set(
            s.lower()
            for s in normalize_skill_list(job.get("required_skills", []))
        )
        
        if not required_skills:
            return {
                "passed": True,
                "score_delta": 0.0,
                "flags": [],
                "warnings": []
            }
        
        missing_skills = required_skills - user_skills
        
        if missing_skills:
            missing_count = len(missing_skills)
            total_required = len(required_skills)
            ratio = missing_count / total_required
            penalty = -self.penalty_factor * ratio
            
            return {
                "passed": ratio < self.max_missing_ratio,
                "score_delta": penalty,
                "flags": ["missing_required_skills"],
                "warnings": [f"Thiếu kỹ năng: {', '.join(missing_skills)}"]
            }
        
        return {
            "passed": True,
            "score_delta": self.success_bonus,
            "flags": ["all_required_skills"],
            "warnings": []
        }


class PreferredSkillRule(Rule):
    """Thưởng điểm cho kỹ năng ưu tiên"""
    
    def __init__(self):
        super().__init__(name="PreferredSkillRule", priority=70)
        self.bonus_factor = 0.1
        self.max_suggest = 3
    
    def evaluate(self, profile: Dict, job: Dict) -> Dict[str, Any]:
        user_skills = set(
            s.lower()
            for s in normalize_skill_list(profile.get("skill_tags", []))
        )
        preferred_skills = set(
            s.lower()
            for s in normalize_skill_list(job.get("preferred_skills", []))
        )
        
        if not preferred_skills:
            return {
                "passed": True,
                "score_delta": 0.0,
                "flags": [],
                "warnings": []
            }
        
        matched_preferred = user_skills & preferred_skills
        
        if matched_preferred:
            bonus = self.bonus_factor * (len(matched_preferred) / len(preferred_skills))
            return {
                "passed": True,
                "score_delta": bonus,
                "flags": ["has_preferred_skills"],
                "warnings": []
            }
        
        return {
            "passed": True,
            "score_delta": 0.0,
            "flags": [],
            "warnings": [
                f"Có thể học thêm: {', '.join(list(preferred_skills)[:self.max_suggest])}"
            ]
        }


class SkillCountRule(Rule):
    """Đánh giá dựa trên tổng số kỹ năng"""
    
    def __init__(self):
        super().__init__(name="SkillCountRule", priority=50)
        self.no_skill_penalty = -0.2
        self.bonus_threshold = 5
        self.bonus_value = 0.1
    
    def evaluate(self, profile: Dict, job: Dict) -> Dict[str, Any]:
        skill_count = len(profile.get("skill_tags", []))
        
        if skill_count == 0:
            return {
                "passed": True,
                "score_delta": self.no_skill_penalty,
                "flags": ["no_skills_listed"],
                "warnings": ["Chưa khai báo kỹ năng"]
            }
        
        if skill_count >= self.bonus_threshold:
            return {
                "passed": True,
                "score_delta": self.bonus_value,
                "flags": ["skill_rich"],
                "warnings": []
            }
        
        return {
            "passed": True,
            "score_delta": 0.0,
            "flags": [],
            "warnings": []
        }

# backend/rule_engine/rules/risk_detection.py
"""
Risk Detection Rules - Luật phát hiện rủi ro
"""
from typing import Dict, Any
from ..rule_base import Rule
from ..taxonomy_adapter import (
    normalize_skill_list,
    normalize_interest_list,
    normalize_education
)


class InterestSkillGapRule(Rule):
    """Phát hiện khoảng cách giữa sở thích và kỹ năng"""
    
    def __init__(self):
        super().__init__(name="InterestSkillGapRule", priority=65)
        self.gap_penalty = -0.1
        self.alignment_bonus = 0.15
    
    def evaluate(self, profile: Dict, job: Dict) -> Dict[str, Any]:
        from ..job_database import DOMAIN_INTEREST_MAP
        
        interests = set(
            i.lower()
            for i in normalize_interest_list(profile.get("interest_tags", []))
        )
        skills = set(
            s.lower()
            for s in normalize_skill_list(profile.get("skill_tags", []))
        )
        job_domain = job.get("domain", "Unknown")
        
        # Lấy sở thích liên quan đến domain
        relevant_interests = set(
            i.lower()
            for i in normalize_interest_list(DOMAIN_INTEREST_MAP.get(job_domain, []))
        )
        
        # Kiểm tra có sở thích khớp với ngành không
        has_relevant_interest = bool(interests & relevant_interests)
        
        # Kiểm tra có kỹ năng liên quan không
        job_skills = set(
            s.lower()
            for s in normalize_skill_list(job.get("required_skills", []))
        )
        has_relevant_skill = bool(skills & job_skills)
        
        # Trường hợp có hứng thú nhưng thiếu kỹ năng
        if has_relevant_interest and not has_relevant_skill:
            return {
                "passed": True,
                "score_delta": self.gap_penalty,
                "flags": ["interest_skill_gap"],
                "warnings": ["Có hứng thú nhưng cần học thêm kỹ năng"]
            }
        
        # Trường hợp có kỹ năng nhưng không có hứng thú
        if not has_relevant_interest and has_relevant_skill:
            return {
                "passed": True,
                "score_delta": 0.0,
                "flags": ["skill_without_interest"],
                "warnings": ["Cân nhắc thêm về sở thích nghề nghiệp"]
            }
        
        # Trường hợp lý tưởng: có cả hứng thú và kỹ năng
        if has_relevant_interest and has_relevant_skill:
            return {
                "passed": True,
                "score_delta": self.alignment_bonus,
                "flags": ["interest_skill_alignment"],
                "warnings": []
            }
        
        return {
            "passed": True,
            "score_delta": 0.0,
            "flags": [],
            "warnings": []
        }


class SimilarityMismatchRule(Rule):
    """Phát hiện mâu thuẫn giữa điểm tương đồng và kỹ năng"""
    
    def __init__(self):
        super().__init__(name="SimilarityMismatchRule", priority=60)
        self.high_similarity = 0.7
        self.low_similarity = 0.4
        self.mismatch_penalty = -0.15
        self.hidden_potential_bonus = 0.1
    
    def evaluate(self, profile: Dict, job: Dict) -> Dict[str, Any]:
        similarity_scores = profile.get("similarity_scores", {})
        
        # Lấy job name từ dict job
        job_name = job.get("name", "")
        if not job_name or job_name not in similarity_scores:
            return {
                "passed": True,
                "score_delta": 0.0,
                "flags": [],
                "warnings": []
            }
        
        similarity = similarity_scores.get(job_name, 0.0)
        user_skills = set(
            s.lower()
            for s in normalize_skill_list(profile.get("skill_tags", []))
        )
        required_skills = set(
            s.lower()
            for s in normalize_skill_list(job.get("required_skills", []))
        )
        
        # Điểm tương đồng cao nhưng thiếu kỹ năng cần thiết
        if similarity > self.high_similarity and required_skills and not (user_skills & required_skills):
            return {
                "passed": True,
                "score_delta": self.mismatch_penalty,
                "flags": ["potential_mismatch"],
                "warnings": ["Khớp về mục tiêu nhưng thiếu kỹ năng cốt lõi"]
            }
        
        # Điểm tương đồng thấp nhưng có đủ kỹ năng
        if similarity < self.low_similarity and required_skills and required_skills.issubset(user_skills):
            return {
                "passed": True,
                "score_delta": self.hidden_potential_bonus,
                "flags": ["hidden_potential"],
                "warnings": []
            }
        
        return {
            "passed": True,
            "score_delta": 0.0,
            "flags": [],
            "warnings": []
        }


class DifficultyMismatchRule(Rule):
    """Cảnh báo nếu độ khó không phù hợp với trình độ"""
    
    def __init__(self):
        super().__init__(name="DifficultyMismatchRule", priority=55)
        self.high_competition = 0.80
        self.low_competition = 0.60
        self.min_skill_count = 2
        self.high_competition_penalty = -0.2
    
    def evaluate(self, profile: Dict, job: Dict) -> Dict[str, Any]:
        user_edu = normalize_education(profile.get("education_level", "unknown"))
        user_edu_compact = user_edu.replace(" ", "").lower()
        competition = job.get("competition", 0.5)
        skill_count = len(profile.get("skill_tags", []))
        
        # Ngành cạnh tranh cao nhưng trình độ/kỹ năng thấp
        if competition >= self.high_competition and (
            user_edu_compact in ["highschool", "unknown"] or skill_count < self.min_skill_count
        ):
            return {
                "passed": True,
                "score_delta": self.high_competition_penalty,
                "flags": ["difficulty_too_high"],
                "warnings": ["Ngành này yêu cầu kỹ năng cao, cần chuẩn bị kỹ"]
            }
        
        # Ngành dễ nhưng trình độ cao (có thể underutilized)
        if competition <= self.low_competition and user_edu in ["Master", "PhD"]:
            return {
                "passed": True,
                "score_delta": 0.0,
                "flags": ["may_be_overqualified"],
                "warnings": ["Có thể phù hợp với vị trí cao hơn"]
            }
        
        return {
            "passed": True,
            "score_delta": 0.0,
            "flags": [],
            "warnings": []
        }

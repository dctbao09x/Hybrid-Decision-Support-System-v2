"""
Eligibility Rules
"""

from typing import Dict, Any
from ..rule_base import Rule


def _base_result() -> Dict[str, Any]:
    return {
        "passed": True,
        "score_delta": 0.0,
        "flags": [],
        "warnings": []
    }


def _clamp(score: float, min_v: float, max_v: float) -> float:
    return max(min(score, max_v), min_v)


# ========================
# Age Rule
# ========================

class AgeEligibilityRule(Rule):

    def __init__(self):
        super().__init__(
            name="AgeEligibilityRule",
            priority=100
        )
        self.clamp_min = -1.0
        self.clamp_max = 0.3
        self.min_age_fallback = 18
        self.age_penalty = -1.0

    def evaluate(self, profile: Dict, job: Dict) -> Dict[str, Any]:

        result = _base_result()

        try:
            age = int(profile.get("age", 0))
            min_age = int(job.get("min_age", self.min_age_fallback))
        except Exception:
            age = 0
            min_age = self.min_age_fallback

        if age < min_age:

            result["passed"] = False
            result["score_delta"] = self.age_penalty

            result["flags"].append("age_ineligible")

            result["warnings"].append(
                f"YÃªu cáº§u tá»‘i thiá»ƒu: {min_age} tuá»•i"
            )

        result["score_delta"] = _clamp(result["score_delta"], self.clamp_min, self.clamp_max)

        return result


# ========================
# Education Rule
# ========================

class EducationEligibilityRule(Rule):

    def __init__(self):
        super().__init__(
            name="EducationEligibilityRule",
            priority=95
        )
        self.clamp_min = -1.0
        self.clamp_max = 0.3
        self.below_penalty = -0.5
        self.above_bonus = 0.1

    def evaluate(self, profile: Dict, job: Dict) -> Dict[str, Any]:

        result = _base_result()

        try:
            from ..taxonomy_adapter import (
                normalize_education,
                education_rank
            )
        except Exception:
            result["warnings"].append("KhÃ´ng load Ä‘Æ°á»£c taxonomy adapter")
            return result

        user_edu = normalize_education(profile.get("education_level", "unknown"))
        min_edu = normalize_education(job.get("min_education", "high school"))

        user_lv = education_rank(user_edu)
        min_lv = education_rank(min_edu)

        if user_lv < min_lv:

            result["passed"] = False
            result["score_delta"] = self.below_penalty

            result["flags"].append("education_ineligible")

            result["warnings"].append(
                f"YÃªu cáº§u tá»‘i thiá»ƒu: {min_edu}"
            )

        elif user_lv > min_lv:

            result["score_delta"] = self.above_bonus
            result["flags"].append("education_advantage")

        result["score_delta"] = _clamp(result["score_delta"], self.clamp_min, self.clamp_max)

        return result

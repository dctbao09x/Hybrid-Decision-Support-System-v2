# backend/rule_engine/rules/__init__.py
"""
Import tất cả các rule
"""
from .eligibility import AgeEligibilityRule, EducationEligibilityRule
from .skill_matching import RequiredSkillRule, PreferredSkillRule, SkillCountRule
from .confidence import ConfidenceLevelRule, DataCompletenessRule
from .risk_detection import InterestSkillGapRule, SimilarityMismatchRule, DifficultyMismatchRule
from .priority import IntentAlignmentRule, InterestMatchRule, SimilarityBoostRule
from .market_rules import CompetitionRule, GrowthRateRule, AIRelevanceRule, DomainMatchRule

RULE_REGISTRY = {
    # Eligibility
    "AgeEligibilityRule": AgeEligibilityRule,
    "EducationEligibilityRule": EducationEligibilityRule,

    # Skill Matching
    "RequiredSkillRule": RequiredSkillRule,
    "PreferredSkillRule": PreferredSkillRule,
    "SkillCountRule": SkillCountRule,

    # Confidence
    "ConfidenceLevelRule": ConfidenceLevelRule,
    "DataCompletenessRule": DataCompletenessRule,

    # Risk Detection
    "InterestSkillGapRule": InterestSkillGapRule,
    "SimilarityMismatchRule": SimilarityMismatchRule,
    "DifficultyMismatchRule": DifficultyMismatchRule,

    # Priority
    "IntentAlignmentRule": IntentAlignmentRule,
    "InterestMatchRule": InterestMatchRule,
    "SimilarityBoostRule": SimilarityBoostRule,

    # Market Rules
    "CompetitionRule": CompetitionRule,
    "GrowthRateRule": GrowthRateRule,
    "AIRelevanceRule": AIRelevanceRule,
    "DomainMatchRule": DomainMatchRule,
}

__all__ = [
    # Eligibility
    "AgeEligibilityRule",
    "EducationEligibilityRule",
    
    # Skill Matching
    "RequiredSkillRule",
    "PreferredSkillRule",
    "SkillCountRule",
    
    # Confidence
    "ConfidenceLevelRule",
    "DataCompletenessRule",
    
    # Risk Detection
    "InterestSkillGapRule",
    "SimilarityMismatchRule",
    "DifficultyMismatchRule",
    
    # Priority
    "IntentAlignmentRule",
    "InterestMatchRule",
    "SimilarityBoostRule",
    
    # Market Rules
    "CompetitionRule",
    "GrowthRateRule",
    "AIRelevanceRule",
    "DomainMatchRule",
    "RULE_REGISTRY",
]
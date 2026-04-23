# backend/rule_engine/rule_engine.py
"""
Core Rule Engine - apply and manage rules.
"""
import os
from pathlib import Path
from typing import Dict, List, Any, Optional

from .config_loader import (
    DEFAULT_RULESET_PATH,
    RuleConfigError,
    RuleSetConfig,
    get_rule_catalog,
    load_ruleset_config,
    resolve_ruleset_path,
)
from .rule_base import Rule, RuleResult
from .job_database import get_job_requirements, get_all_jobs
from .rules import RULE_REGISTRY


CONFLICT_ACCUMULATE = "ACCUMULATE"
CONFLICT_FAIL_FAST = "FAIL_FAST"
CONFLICT_PRIORITY_WINS = "PRIORITY_WINS"


class RuleEngine:
    """Rule Engine with config-driven rule registry."""

    def __init__(self, config_path: Optional[Path] = None, strict_ruleset: Optional[bool] = None):
        """Initialize engine with default rules or config-driven ruleset."""
        self.rules: List[Rule] = []
        self.ruleset: Optional[RuleSetConfig] = None
        self.ruleset_version: Optional[str] = None
        self.conflict_strategy = CONFLICT_ACCUMULATE
        self.rule_groups: Dict[str, str] = {}
        self.conflict_groups: Dict[str, List[str]] = {}
        self.strict_ruleset = (
            strict_ruleset
            if strict_ruleset is not None
            else os.getenv("RULESET_STRICT", "0") == "1"
        )

        self._load_rules(config_path)

    def _load_rules(self, config_path: Optional[Path]) -> None:
        path = resolve_ruleset_path(config_path)

        if path.exists():
            self._load_rules_from_config(path)
            return

        if self.strict_ruleset:
            raise RuleConfigError(
                f"ruleset not found at {path}. strict ruleset enabled"
            )

        self._load_default_rules()
    
    def _load_default_rules(self):
        """Load tất cả rule mặc định"""
        # Eligibility rules
        self.add_rule(AgeEligibilityRule())
        self.add_rule(EducationEligibilityRule())
        
        # Skill matching rules
        self.add_rule(RequiredSkillRule())
        self.add_rule(PreferredSkillRule())
        self.add_rule(SkillCountRule())
        
        # Confidence rules
        self.add_rule(ConfidenceLevelRule())
        self.add_rule(DataCompletenessRule())
        
        # Risk detection rules
        self.add_rule(InterestSkillGapRule())
        self.add_rule(SimilarityMismatchRule())
        self.add_rule(DifficultyMismatchRule())
        
        # Priority rules
        self.add_rule(IntentAlignmentRule())
        self.add_rule(InterestMatchRule())
        self.add_rule(SimilarityBoostRule())
        
        # Market rules
        self.add_rule(CompetitionRule())
        self.add_rule(GrowthRateRule())
        self.add_rule(AIRelevanceRule())
        self.add_rule(DomainMatchRule())
        
        # Sắp xếp theo priority (cao -> thấp)
        self.rules.sort(key=lambda r: r.priority, reverse=True)

        # Default groups (legacy)
        self.rule_groups = {
            r.name: "legacy"
            for r in self.rules
        }

    def _load_rules_from_config(self, path: Path) -> None:
        ruleset = load_ruleset_config(path)
        self.ruleset = ruleset
        self.ruleset_version = ruleset.version
        self.conflict_strategy = ruleset.conflict_strategy or CONFLICT_ACCUMULATE
        self.conflict_groups = ruleset.conflict_groups or {}

        rule_map = self._build_rule_class_map()
        loaded_rules: List[Rule] = []
        groups: Dict[str, str] = {}

        for group in ruleset.groups.values():
            for rule_def in group.rules:
                if not rule_def.enabled:
                    continue

                rule_cls = rule_map.get(rule_def.class_name)
                if not rule_cls:
                    raise ValueError(f"Unknown rule class: {rule_def.class_name}")

                rule = rule_cls()
                rule.priority = rule_def.priority

                for key, value in rule_def.params.items():
                    setattr(rule, key, value)

                loaded_rules.append(rule)
                groups[rule.name] = group.name

        self.rules = sorted(loaded_rules, key=lambda r: r.priority, reverse=True)
        self.rule_groups = groups

    def _build_rule_class_map(self) -> Dict[str, Any]:
        return dict(RULE_REGISTRY)
    
    def add_rule(self, rule: Rule):
        """Thêm rule mới vào engine"""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)
    
    def remove_rule(self, rule_name: str):
        """Xóa rule theo tên"""
        self.rules = [r for r in self.rules if r.name != rule_name]

    def reload(self, config_path: Optional[Path] = None) -> None:
        """Reload rules from config or defaults."""
        self.rules = []
        self.ruleset = None
        self.ruleset_version = None
        self.conflict_strategy = CONFLICT_ACCUMULATE
        self.rule_groups = {}
        self.conflict_groups = {}
        self._load_rules(config_path)
    
    def evaluate_job(self, profile: Dict, job_name: str) -> Dict[str, Any]:
        """
        Đánh giá một ngành nghề cụ thể
        
        Args:
            profile: Hồ sơ người dùng đã xử lý
            job_name: Tên ngành nghề
            
        Returns:
            Kết quả đánh giá
        """
        job_requirements = get_job_requirements(job_name)
        if not job_requirements:
            return None
        
        # Thêm tên job vào requirements để rule sử dụng
        job_requirements["name"] = job_name
        
        # Kết quả tổng hợp
        result = RuleResult()
        
        # Áp dụng từng rule
        for rule in self.rules:
            rule_result = rule.evaluate(profile, job_requirements)

            result.merge(
                rule_result,
                rule_name=rule.name,
                rule_group=self.rule_groups.get(rule.name, "general"),
                rule_priority=rule.priority,
                ruleset_version=self.ruleset_version,
            )

            if self.conflict_strategy == CONFLICT_FAIL_FAST:
                if not rule_result.get("passed", True):
                    break

            if self.conflict_strategy == CONFLICT_PRIORITY_WINS:
                if self._is_effective(rule_result):
                    break
        
        conflict_warning = self._detect_conflicts(result)

        return {
            "job": job_name,
            "passed": result.passed,
            "score_delta": round(result.score_delta, 3),
            "confidence": profile.get("confidence_score"),
            "flags": result.flags,
            "warnings": result.warnings,
            "audit_trail": [a.__dict__ for a in result.audit_trail],
            "ruleset_version": self.ruleset_version,
            "conflict_strategy": self.conflict_strategy,
            "conflicts": conflict_warning,
        }
    
    def process_profile(self, profile: Dict) -> Dict[str, Any]:
        """
        Xử lý toàn bộ hồ sơ và trả về kết quả
        
        Args:
            profile: Hồ sơ từ Input Processing Layer
            
        Returns:
            {
                "filtered_jobs": [...],
                "ranked_jobs": [...],
                "flags": [...],
                "warnings": [...]
            }
        """
        all_jobs = get_all_jobs()
        job_evaluations = []
        
        # Đánh giá từng ngành
        for job_name in all_jobs:
            eval_result = self.evaluate_job(profile, job_name)
            if eval_result and eval_result["passed"]:
                job_evaluations.append(eval_result)
        
        # Tính điểm cuối cho mỗi ngành
        for job_eval in job_evaluations:
            # Điểm base từ similarity (nếu có)
            similarity_scores = profile.get("similarity_scores", {})
            base_score = similarity_scores.get(job_eval["job"], 0.5)
            
            # Điểm cuối = base + delta
            final_score = max(0.0, min(1.0, base_score + job_eval["score_delta"]))
            job_eval["score"] = round(final_score, 3)
        
        # Sắp xếp theo điểm giảm dần
        ranked_jobs = sorted(job_evaluations, key=lambda x: x["score"], reverse=True)
        
        # Lọc ngành (loại bỏ điểm quá thấp)
        filtered_jobs = [job for job in ranked_jobs if job["score"] >= 0.2]
        
        # Tổng hợp flags và warnings
        all_flags = set()
        all_warnings = set()
        
        for job in filtered_jobs:
            all_flags.update(job.get("flags", []))
            all_warnings.update(job.get("warnings", []))
        
        return {
            "filtered_jobs": [
                {
                    "job": job["job"],
                    "score": job["score"],
                    "tags": job.get("flags", [])
                }
                for job in filtered_jobs
            ],
            "ranked_jobs": [
                {
                    "job": job["job"],
                    "score": job["score"],
                    "tags": job.get("flags", [])
                }
                for job in ranked_jobs
            ],
            "flags": sorted(list(all_flags)),
            "warnings": sorted(list(all_warnings)),
            "total_jobs_evaluated": len(all_jobs),
            "jobs_passed": len(filtered_jobs)
        }

    @staticmethod
    def _is_effective(rule_result: Dict[str, Any]) -> bool:
        return (
            not rule_result.get("passed", True)
            or bool(rule_result.get("flags"))
            or bool(rule_result.get("warnings"))
            or float(rule_result.get("score_delta", 0.0)) != 0.0
        )

    def _detect_conflicts(self, result: RuleResult) -> Dict[str, List[str]]:
        if not self.conflict_groups:
            return {}

        conflicts: Dict[str, List[str]] = {}
        active_flags = set(result.flags)

        for group_name, flags in self.conflict_groups.items():
            hits = sorted(active_flags.intersection(set(flags)))
            if len(hits) > 1:
                conflicts[group_name] = hits
                result.add_conflict(group_name, hits)

        return conflicts
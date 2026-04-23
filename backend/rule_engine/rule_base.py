# backend/rule_engine/rule_base.py
"""
Base classes cho Rule Engine
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Any, Optional
from abc import ABC, abstractmethod


class Rule(ABC):
    """Base class cho tất cả các rule"""
    
    def __init__(self, name: str, priority: int = 0):
        """
        Args:
            name: Tên rule
            priority: Độ ưu tiên (số càng cao càng ưu tiên)
        """
        self.name = name
        self.priority = priority
    
    @abstractmethod
    def evaluate(self, profile: Dict, job: Dict) -> Dict[str, Any]:
        """
        Đánh giá rule
        
        Args:
            profile: Hồ sơ người dùng đã xử lý
            job: Thông tin ngành nghề
            
        Returns:
            {
                "passed": bool,
                "score_delta": float,  # Thay đổi điểm (-1.0 đến +1.0)
                "flags": List[str],
                "warnings": List[str]
            }
        """
        pass
    
    def __repr__(self):
        return f"<Rule: {self.name} (priority={self.priority})>"


@dataclass
class RuleAuditEntry:
    rule_name: str
    rule_group: str
    rule_priority: int
    passed: bool
    score_delta: float
    flags: List[str]
    warnings: List[str]
    ruleset_version: Optional[str] = None
    timestamp_utc: str = ""


class RuleResult:
    """Kết quả sau khi áp dụng các rule"""
    
    def __init__(self):
        self.passed = True
        self.score_delta = 0.0
        self.flags = []
        self.warnings = []
        self.audit_trail: List[RuleAuditEntry] = []
    
    def merge(
        self,
        result: Dict[str, Any],
        *,
        rule_name: Optional[str] = None,
        rule_group: Optional[str] = None,
        rule_priority: Optional[int] = None,
        ruleset_version: Optional[str] = None,
    ):
        """Merge kết quả từ một rule"""
        if not result.get("passed", True):
            self.passed = False
        
        self.score_delta += result.get("score_delta", 0.0)
        self.flags.extend(result.get("flags", []))
        self.warnings.extend(result.get("warnings", []))

        if rule_name:
            audit = RuleAuditEntry(
                rule_name=rule_name,
                rule_group=rule_group or "unknown",
                rule_priority=rule_priority or 0,
                passed=bool(result.get("passed", True)),
                score_delta=float(result.get("score_delta", 0.0)),
                flags=list(result.get("flags", [])),
                warnings=list(result.get("warnings", [])),
                ruleset_version=ruleset_version,
                timestamp_utc=datetime.utcnow().isoformat() + "Z",
            )
            self.audit_trail.append(audit)

    def add_conflict(self, group_name: str, flags: List[str]) -> None:
        message = f"rule_conflict:{group_name}"
        self.warnings.append(message)
        self.flags.append("rule_conflict")
        audit = RuleAuditEntry(
            rule_name="RULE_CONFLICT_DETECTOR",
            rule_group=group_name,
            rule_priority=0,
            passed=True,
            score_delta=0.0,
            flags=list(flags),
            warnings=[message],
            ruleset_version=None,
            timestamp_utc=datetime.utcnow().isoformat() + "Z",
        )
        self.audit_trail.append(audit)
    
    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "score_delta": self.score_delta,
            "flags": list(set(self.flags)),
            "warnings": list(set(self.warnings)),
            "audit_trail": [a.__dict__ for a in self.audit_trail],
        }
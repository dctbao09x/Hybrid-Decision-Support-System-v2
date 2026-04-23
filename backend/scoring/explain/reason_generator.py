# backend/scoring/explain/reason_generator.py
"""
Reason Generator
================

Converts feature importance and SHAP values into human-readable explanations.

Features:
  - Config-driven feature-to-reason mapping
  - Multi-language support (vi, en)
  - Value-aware reason generation
  - Deduplication and quality control
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger("xai.reason_generator")


# Default Vietnamese feature mappings
DEFAULT_FEATURE_MAPPINGS_VI = {
    # Academic scores
    "math_score": {
        "name": "Điểm Toán",
        "thresholds": [
            {"min": 9.0, "reason": "Toán xuất sắc ({value:.1f})"},
            {"min": 8.0, "reason": "Toán cao ({value:.1f})"},
            {"min": 7.0, "reason": "Toán khá ({value:.1f})"},
            {"min": 5.0, "reason": "Toán trung bình ({value:.1f})"},
            {"min": 0.0, "reason": "Toán yếu ({value:.1f})"},
        ],
    },
    "physics_score": {
        "name": "Điểm Lý",
        "thresholds": [
            {"min": 9.0, "reason": "Vật lý xuất sắc ({value:.1f})"},
            {"min": 8.0, "reason": "Vật lý cao ({value:.1f})"},
            {"min": 7.0, "reason": "Vật lý khá ({value:.1f})"},
            {"min": 5.0, "reason": "Vật lý trung bình ({value:.1f})"},
            {"min": 0.0, "reason": "Vật lý yếu ({value:.1f})"},
        ],
    },
    "chemistry_score": {
        "name": "Điểm Hóa",
        "thresholds": [
            {"min": 9.0, "reason": "Hóa học xuất sắc ({value:.1f})"},
            {"min": 8.0, "reason": "Hóa học cao ({value:.1f})"},
            {"min": 7.0, "reason": "Hóa học khá ({value:.1f})"},
            {"min": 5.0, "reason": "Hóa học trung bình ({value:.1f})"},
            {"min": 0.0, "reason": "Hóa học yếu ({value:.1f})"},
        ],
    },
    "literature_score": {
        "name": "Điểm Văn",
        "thresholds": [
            {"min": 8.0, "reason": "Văn tốt ({value:.1f})"},
            {"min": 6.5, "reason": "Văn khá ({value:.1f})"},
            {"min": 0.0, "reason": "Văn trung bình ({value:.1f})"},
        ],
    },
    "english_score": {
        "name": "Điểm Anh",
        "thresholds": [
            {"min": 8.0, "reason": "Tiếng Anh tốt ({value:.1f})"},
            {"min": 6.5, "reason": "Tiếng Anh khá ({value:.1f})"},
            {"min": 0.0, "reason": "Tiếng Anh cơ bản ({value:.1f})"},
        ],
    },
    
    # Aptitude/Skill scores
    "logic_score": {
        "name": "Tư duy logic",
        "thresholds": [
            {"min": 8.0, "reason": "Logic mạnh ({value:.1f})"},
            {"min": 7.0, "reason": "Logic khá ({value:.1f})"},
            {"min": 5.0, "reason": "Logic trung bình ({value:.1f})"},
            {"min": 0.0, "reason": "Logic cần cải thiện ({value:.1f})"},
        ],
    },
    "creativity_score": {
        "name": "Sáng tạo",
        "thresholds": [
            {"min": 8.0, "reason": "Rất sáng tạo ({value:.1f})"},
            {"min": 6.0, "reason": "Khá sáng tạo ({value:.1f})"},
            {"min": 0.0, "reason": "Sáng tạo cơ bản ({value:.1f})"},
        ],
    },
    "communication_score": {
        "name": "Giao tiếp",
        "thresholds": [
            {"min": 8.0, "reason": "Giao tiếp tốt ({value:.1f})"},
            {"min": 6.0, "reason": "Giao tiếp khá ({value:.1f})"},
            {"min": 0.0, "reason": "Giao tiếp cơ bản ({value:.1f})"},
        ],
    },
    "leadership_score": {
        "name": "Lãnh đạo",
        "thresholds": [
            {"min": 7.0, "reason": "Có năng lực lãnh đạo ({value:.1f})"},
            {"min": 5.0, "reason": "Lãnh đạo khá ({value:.1f})"},
            {"min": 0.0, "reason": "Lãnh đạo cơ bản ({value:.1f})"},
        ],
    },
    "analytical_score": {
        "name": "Phân tích",
        "thresholds": [
            {"min": 8.0, "reason": "Phân tích mạnh ({value:.1f})"},
            {"min": 6.0, "reason": "Phân tích khá ({value:.1f})"},
            {"min": 0.0, "reason": "Phân tích cơ bản ({value:.1f})"},
        ],
    },
    
    # Interest flags (0-1 scale)
    "interest_it": {
        "name": "Quan tâm IT",
        "thresholds": [
            {"min": 0.8, "reason": "Rất quan tâm IT/Công nghệ ({value:.2f})"},
            {"min": 0.5, "reason": "Quan tâm IT/Công nghệ ({value:.2f})"},
            {"min": 0.3, "reason": "Có hứng thú IT ({value:.2f})"},
            {"min": 0.0, "reason": "Ít quan tâm IT ({value:.2f})"},
        ],
    },
    "interest_ai": {
        "name": "Quan tâm AI",
        "thresholds": [
            {"min": 0.7, "reason": "Quan tâm AI/ML ({value:.2f})"},
            {"min": 0.4, "reason": "Có hứng thú AI ({value:.2f})"},
            {"min": 0.0, "reason": "Ít quan tâm AI ({value:.2f})"},
        ],
    },
    "interest_business": {
        "name": "Quan tâm kinh doanh",
        "thresholds": [
            {"min": 0.7, "reason": "Quan tâm kinh doanh ({value:.2f})"},
            {"min": 0.4, "reason": "Có hứng thú kinh doanh ({value:.2f})"},
            {"min": 0.0, "reason": "Ít quan tâm kinh doanh ({value:.2f})"},
        ],
    },
    "interest_design": {
        "name": "Quan tâm thiết kế",
        "thresholds": [
            {"min": 0.7, "reason": "Quan tâm thiết kế/sáng tạo ({value:.2f})"},
            {"min": 0.4, "reason": "Có hứng thú thiết kế ({value:.2f})"},
            {"min": 0.0, "reason": "Ít quan tâm thiết kế ({value:.2f})"},
        ],
    },
    "interest_science": {
        "name": "Quan tâm khoa học",
        "thresholds": [
            {"min": 0.7, "reason": "Yêu thích nghiên cứu khoa học ({value:.2f})"},
            {"min": 0.4, "reason": "Quan tâm khoa học ({value:.2f})"},
            {"min": 0.0, "reason": "Ít quan tâm khoa học ({value:.2f})"},
        ],
    },
    "interest_healthcare": {
        "name": "Quan tâm y tế",
        "thresholds": [
            {"min": 0.7, "reason": "Quan tâm y tế/sức khỏe ({value:.2f})"},
            {"min": 0.4, "reason": "Có hứng thú y tế ({value:.2f})"},
            {"min": 0.0, "reason": "Ít quan tâm y tế ({value:.2f})"},
        ],
    },
    
    # Generic fallback patterns
    "_default_high": {
        "name": "Đặc điểm",
        "thresholds": [
            {"min": 0.7, "reason": "{feature} cao ({value:.2f})"},
            {"min": 0.4, "reason": "{feature} khá ({value:.2f})"},
            {"min": 0.0, "reason": "{feature} thấp ({value:.2f})"},
        ],
    },
}

# English mappings
DEFAULT_FEATURE_MAPPINGS_EN = {
    "math_score": {
        "name": "Math Score",
        "thresholds": [
            {"min": 9.0, "reason": "Excellent math ({value:.1f})"},
            {"min": 8.0, "reason": "Strong math ({value:.1f})"},
            {"min": 7.0, "reason": "Good math ({value:.1f})"},
            {"min": 5.0, "reason": "Average math ({value:.1f})"},
            {"min": 0.0, "reason": "Weak math ({value:.1f})"},
        ],
    },
    "logic_score": {
        "name": "Logic",
        "thresholds": [
            {"min": 8.0, "reason": "Strong logic ({value:.1f})"},
            {"min": 7.0, "reason": "Good logic ({value:.1f})"},
            {"min": 0.0, "reason": "Average logic ({value:.1f})"},
        ],
    },
    "interest_it": {
        "name": "IT Interest",
        "thresholds": [
            {"min": 0.7, "reason": "High IT interest ({value:.2f})"},
            {"min": 0.4, "reason": "Moderate IT interest ({value:.2f})"},
            {"min": 0.0, "reason": "Low IT interest ({value:.2f})"},
        ],
    },
    "_default_high": {
        "name": "Feature",
        "thresholds": [
            {"min": 0.7, "reason": "High {feature} ({value:.2f})"},
            {"min": 0.4, "reason": "Moderate {feature} ({value:.2f})"},
            {"min": 0.0, "reason": "Low {feature} ({value:.2f})"},
        ],
    },
}


@dataclass
class ReasonResult:
    """Result of reason generation."""
    
    reasons: List[str]
    features_used: List[str]
    feature_values: List[float]
    importance_scores: List[float]
    language: str = "vi"
    timestamp: str = ""
    quality_passed: bool = True
    quality_issues: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "reasons": self.reasons,
            "features_used": self.features_used,
            "feature_values": [round(x, 4) for x in self.feature_values],
            "importance_scores": [round(x, 4) for x in self.importance_scores],
            "language": self.language,
            "quality_passed": self.quality_passed,
            "quality_issues": self.quality_issues,
            "timestamp": self.timestamp,
        }


class ReasonGenerator:
    """
    Generates human-readable explanations from feature importance and SHAP values.
    
    Usage::
    
        generator = ReasonGenerator(language="vi")
        generator.load_config(config)
        
        result = generator.generate(
            top_features=[("math_score", 0.25, 8.5), ("logic_score", 0.20, 7.8)],
            predicted_career="Data Scientist",
        )
        
        print(result.reasons)
        # ["Toán cao (8.5)", "Logic khá (7.8)"]
    """
    
    def __init__(
        self,
        language: str = "vi",
        config_path: Optional[str] = None,
    ):
        self._language = language
        self._mappings: Dict[str, Any] = {}
        self._min_importance = 0.05
        self._top_k = 3
        
        # Load default mappings
        self._load_default_mappings()
        
        # Load custom config if provided
        if config_path:
            self._load_config_file(config_path)
    
    def _load_default_mappings(self) -> None:
        """Load default feature mappings based on language."""
        if self._language == "vi":
            self._mappings = DEFAULT_FEATURE_MAPPINGS_VI.copy()
        elif self._language == "en":
            self._mappings = DEFAULT_FEATURE_MAPPINGS_EN.copy()
        else:
            # Fallback to Vietnamese
            self._mappings = DEFAULT_FEATURE_MAPPINGS_VI.copy()
    
    def _load_config_file(self, config_path: str) -> None:
        """Load custom mappings from config file."""
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"Config file not found: {config_path}")
            return
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            
            # Merge custom mappings
            custom_mappings = config.get("feature_mappings", {})
            self._mappings.update(custom_mappings)
            
            logger.info(f"Loaded {len(custom_mappings)} custom mappings")
            
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
    
    def load_config(self, config: Dict[str, Any]) -> None:
        """
        Load configuration from system.yaml xai section.
        
        Args:
            config: XAI configuration dict
        """
        self._language = config.get("language", self._language)
        self._min_importance = config.get("min_importance", 0.05)
        self._top_k = config.get("top_k", 3)
        
        # Load custom mappings if provided
        if "feature_mappings" in config:
            self._mappings.update(config["feature_mappings"])
        
        # Reload default mappings for new language
        self._load_default_mappings()
        
        logger.info(
            f"ReasonGenerator config: lang={self._language}, "
            f"min_importance={self._min_importance}, top_k={self._top_k}"
        )
    
    def generate(
        self,
        top_features: List[Tuple[str, float, float]],
        predicted_career: Optional[str] = None,
        min_importance: Optional[float] = None,
        max_reasons: Optional[int] = None,
    ) -> ReasonResult:
        """
        Generate reasons from top features.
        
        Args:
            top_features: List of (feature_name, importance/shap, value) tuples
            predicted_career: Predicted career name (for context)
            min_importance: Minimum importance to include (overrides config)
            max_reasons: Maximum number of reasons (overrides config)
            
        Returns:
            ReasonResult with generated reasons
        """
        min_imp = min_importance or self._min_importance
        max_k = max_reasons or self._top_k
        
        reasons = []
        features_used = []
        feature_values = []
        importance_scores = []
        quality_issues = []
        
        # Filter by importance
        filtered = [
            (name, imp, val)
            for name, imp, val in top_features
            if abs(imp) >= min_imp
        ]
        
        # Sort by absolute importance
        filtered.sort(key=lambda x: abs(x[1]), reverse=True)
        
        # Generate reasons for top k
        for name, importance, value in filtered[:max_k]:
            reason = self._generate_single_reason(name, value, importance)
            
            if reason:
                # Check for duplicates
                if reason not in reasons:
                    reasons.append(reason)
                    features_used.append(name)
                    feature_values.append(value)
                    importance_scores.append(importance)
                else:
                    quality_issues.append(f"Duplicate reason: {reason}")
        
        # Quality checks
        quality_passed = self._check_quality(
            reasons, quality_issues, predicted_career
        )
        
        return ReasonResult(
            reasons=reasons,
            features_used=features_used,
            feature_values=feature_values,
            importance_scores=importance_scores,
            language=self._language,
            quality_passed=quality_passed,
            quality_issues=quality_issues,
        )
    
    def _generate_single_reason(
        self,
        feature_name: str,
        value: float,
        importance: float,
    ) -> Optional[str]:
        """Generate reason for a single feature."""
        # Look up mapping
        mapping = self._mappings.get(feature_name)
        
        if mapping is None:
            # Try default mapping
            mapping = self._mappings.get("_default_high")
            if mapping is None:
                logger.warning(f"No mapping for feature: {feature_name}")
                return None
        
        # Find appropriate threshold
        thresholds = mapping.get("thresholds", [])
        
        for threshold in thresholds:
            min_val = threshold.get("min", 0.0)
            
            if value >= min_val:
                reason_template = threshold.get("reason", "")
                
                # Format the reason
                try:
                    reason = reason_template.format(
                        value=value,
                        feature=feature_name,
                        importance=importance,
                    )
                    return reason
                except Exception as e:
                    logger.warning(f"Reason format error: {e}")
                    return f"{feature_name}: {value:.2f}"
        
        # Fallback
        return f"{feature_name}: {value:.2f}"
    
    def _check_quality(
        self,
        reasons: List[str],
        quality_issues: List[str],
        predicted_career: Optional[str],
    ) -> bool:
        """
        Check quality of generated reasons.
        
        Returns True if quality is acceptable.
        """
        # Check 1: No empty reasons
        if not reasons:
            quality_issues.append("No reasons generated")
            return False
        
        # Check 2: No generic/vague reasons
        generic_patterns = ["unknown", "undefined", "N/A", "None"]
        for reason in reasons:
            if any(p.lower() in reason.lower() for p in generic_patterns):
                quality_issues.append(f"Generic reason: {reason}")
        
        # Check 3: All reasons have values
        for reason in reasons:
            if "({" in reason or "{value" in reason:
                quality_issues.append(f"Unformatted reason: {reason}")
                return False
        
        # Check 4: Minimum reason length
        for reason in reasons:
            if len(reason) < 5:
                quality_issues.append(f"Reason too short: {reason}")
        
        return len(quality_issues) == 0 or all(
            "Duplicate" in issue for issue in quality_issues
        )
    
    def add_mapping(
        self,
        feature_name: str,
        mapping: Dict[str, Any],
    ) -> None:
        """Add or update a feature mapping."""
        self._mappings[feature_name] = mapping
        logger.debug(f"Added mapping for {feature_name}")
    
    def get_mapping(self, feature_name: str) -> Optional[Dict[str, Any]]:
        """Get mapping for a feature."""
        return self._mappings.get(feature_name)
    
    def list_features(self) -> List[str]:
        """List all mapped features."""
        return [k for k in self._mappings.keys() if not k.startswith("_")]
    
    def export_mappings(self, output_path: str) -> None:
        """Export current mappings to YAML file."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(
                {"feature_mappings": self._mappings},
                f,
                allow_unicode=True,
                default_flow_style=False,
            )
        
        logger.info(f"Exported mappings to {output_path}")

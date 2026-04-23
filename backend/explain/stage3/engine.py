# backend/explain/stage3/engine.py
"""
Stage 3 - Rule + Template Engine
================================

Converts XAI output (Stage 2) into stable, deterministic explanation text.

Pipeline position:
    Inference → XAI (Stage 2) → Rule+Template (Stage 3) → LLM (Stage 4) → API

This stage is MANDATORY in the orchestrator - no bypass allowed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from jinja2 import Environment, FileSystemLoader, Template, select_autoescape

from backend.explain.stage3.rule_map import (
    REASON_MAP,
    VALID_SOURCES,
    map_reasons,
)

logger = logging.getLogger("explain.stage3.engine")


@dataclass
class Stage3Input:
    """Input schema from Stage 2 (XAI)."""
    
    trace_id: str
    career: str
    reason_codes: List[str]
    sources: List[str]
    confidence: float
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Stage3Input":
        """Parse input from dict."""
        return cls(
            trace_id=data.get("trace_id", ""),
            career=data.get("career", ""),
            reason_codes=data.get("reason_codes", []),
            sources=data.get("sources", []),
            confidence=float(data.get("confidence", 0.0)),
        )
    
    def validate(self) -> List[str]:
        """Validate input and return list of errors."""
        errors = []
        
        if not self.trace_id:
            errors.append("Missing trace_id")
        if not self.career:
            errors.append("Missing career")
        if not isinstance(self.reason_codes, list):
            errors.append("reason_codes must be a list")
        if not isinstance(self.sources, list):
            errors.append("sources must be a list")
        if not (0 <= self.confidence <= 1):
            errors.append("confidence must be between 0 and 1")
        
        return errors


@dataclass
class Stage3Output:
    """Output schema for Stage 4 / API."""
    
    trace_id: str
    career: str
    reasons: List[str]  # Mapped Vietnamese reasons with source
    explain_text: str  # Rendered template text
    
    # Audit metadata
    used_codes: List[str] = field(default_factory=list)
    skipped_codes: List[str] = field(default_factory=list)
    input_hash: str = ""
    output_hash: str = ""
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for API/logging."""
        return {
            "trace_id": self.trace_id,
            "career": self.career,
            "reasons": self.reasons,
            "explain_text": self.explain_text,
            "used_codes": self.used_codes,
            "skipped_codes": self.skipped_codes,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "timestamp": self.timestamp,
        }
    
    def to_api_response(self) -> Dict[str, Any]:
        """Convert to API response format."""
        return {
            "trace_id": self.trace_id,
            "career": self.career,
            "reasons": self.reasons,
            "explain_text": self.explain_text,
        }


@dataclass
class Stage3Config:
    """Configuration for Stage 3."""
    
    enabled: bool = True
    strict: bool = True  # Fail on validation errors if True
    log_level: str = "full"  # "full" | "minimal" | "off"
    template_name: str = "base.j2"
    fallback_template: str = "minimal.j2"
    log_dir: str = "logs"
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Stage3Config":
        """Load from config dict."""
        stage3 = data.get("stage3", data)
        return cls(
            enabled=stage3.get("enabled", True),
            strict=stage3.get("strict", True),
            log_level=stage3.get("log_level", "full"),
            template_name=stage3.get("template_name", "base.j2"),
            fallback_template=stage3.get("fallback_template", "minimal.j2"),
            log_dir=stage3.get("log_dir", "logs"),
        )


class Stage3Engine:
    """
    Stage 3 Engine - Rule + Template processing.
    
    Usage:
        engine = Stage3Engine()
        engine.load_config(config)
        
        result = engine.run(xai_output)
    """
    
    def __init__(self, project_root: Optional[Path] = None):
        self._project_root = project_root or Path(__file__).resolve().parents[3]
        
        # Configuration
        self._config = Stage3Config()
        
        # Template engine
        self._template_dir = Path(__file__).parent / "templates"
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(self._template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        
        # Logging
        self._log_dir = self._project_root / "logs"
        self._log_file: Optional[Path] = None
        self._setup_logging()
        
        self._lock = threading.RLock()
    
    def _setup_logging(self) -> None:
        """Setup Stage 3 specific logging."""
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_file = self._log_dir / "explain_stage3.log"
    
    def load_config(self, config: Dict[str, Any]) -> None:
        """
        Load configuration.
        
        Args:
            config: Configuration dict (or stage3 section)
        """
        self._config = Stage3Config.from_dict(config)
        
        # Update log directory
        if self._config.log_dir:
            self._log_dir = self._project_root / self._config.log_dir
            self._setup_logging()
        
        logger.info(
            f"Stage3 config: enabled={self._config.enabled}, "
            f"strict={self._config.strict}, log_level={self._config.log_level}"
        )
    
    def load_config_file(self, config_path: Optional[str] = None) -> None:
        """Load configuration from YAML file."""
        if config_path is None:
            config_path = str(self._project_root / "config" / "explain.yaml")
        
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"Config file not found: {config_path}")
            return
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            self.load_config(config)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
    
    def run(self, xai_output: Dict[str, Any]) -> Stage3Output:
        """
        Run Stage 3 processing.
        
        Args:
            xai_output: Output from Stage 2 (XAI)
            
        Returns:
            Stage3Output with mapped reasons and rendered text
            
        Raises:
            ValueError: If strict mode and validation fails
        """
        with self._lock:
            # Check if enabled
            if not self._config.enabled:
                logger.info("Stage3 disabled, returning passthrough")
                return self._create_passthrough(xai_output)
            
            # Parse and validate input
            input_data = Stage3Input.from_dict(xai_output)
            errors = input_data.validate()
            
            if errors:
                if self._config.strict:
                    raise ValueError(f"Stage3 validation failed: {errors}")
                else:
                    logger.warning(f"Stage3 validation warnings: {errors}")
            
            # Compute input hash for audit
            input_hash = self._compute_hash(xai_output)
            
            # Map reason codes to text
            reasons, used_codes, skipped_codes = map_reasons(
                input_data.reason_codes,
                input_data.sources,
            )
            
            # Render template
            explain_text = self._render_template(
                career=input_data.career,
                reasons=reasons,
                confidence=round(input_data.confidence * 100, 1),
            )
            
            # Create output
            output = Stage3Output(
                trace_id=input_data.trace_id,
                career=input_data.career,
                reasons=reasons,
                explain_text=explain_text,
                used_codes=used_codes,
                skipped_codes=skipped_codes,
                input_hash=input_hash,
            )
            
            # Compute output hash
            output.output_hash = self._compute_hash(output.to_api_response())
            
            # Audit log
            self._audit_log(output)
            
            return output
    
    def _create_passthrough(self, xai_output: Dict[str, Any]) -> Stage3Output:
        """Create passthrough output when Stage3 is disabled."""
        return Stage3Output(
            trace_id=xai_output.get("trace_id", ""),
            career=xai_output.get("career", ""),
            reasons=xai_output.get("reason_codes", []),
            explain_text="",
            used_codes=[],
            skipped_codes=[],
        )
    
    def _render_template(
        self,
        career: str,
        reasons: List[str],
        confidence: float,
        template_name: Optional[str] = None,
    ) -> str:
        """Render Jinja2 template."""
        if template_name is None:
            template_name = self._config.template_name
        
        try:
            template = self._jinja_env.get_template(template_name)
            return template.render(
                career=career,
                reasons=reasons,
                confidence=confidence,
            )
        except Exception as e:
            logger.error(f"Template render failed: {e}")
            
            # Try fallback template
            try:
                fallback = self._jinja_env.get_template(
                    self._config.fallback_template
                )
                return fallback.render(
                    career=career,
                    reasons=reasons,
                    confidence=confidence,
                )
            except Exception as e2:
                logger.error(f"Fallback template also failed: {e2}")
                # Last resort: plain text
                reasons_text = "\n".join(f"- {r}" for r in reasons)
                return f"{career}:\n{reasons_text}"
    
    def _compute_hash(self, data: Dict[str, Any]) -> str:
        """Compute deterministic hash for audit."""
        # Sort keys for deterministic output
        json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()[:16]
    
    def _audit_log(self, output: Stage3Output) -> None:
        """Write audit log entry."""
        if self._config.log_level == "off":
            return
        
        try:
            log_entry = {
                "timestamp": output.timestamp,
                "trace_id": output.trace_id,
                "input_hash": output.input_hash,
                "used_codes": output.used_codes,
                "skipped": output.skipped_codes,
                "output_hash": output.output_hash,
            }
            
            if self._config.log_level == "full":
                log_entry["career"] = output.career
                log_entry["reasons_count"] = len(output.reasons)
            
            # Write to log file
            if self._log_file:
                with open(self._log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            
            logger.debug(f"Stage3 audit: {output.trace_id}")
            
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")
    
    def is_enabled(self) -> bool:
        """Check if Stage 3 is enabled."""
        return self._config.enabled


# ==============================================================================
# SINGLETON & HELPER FUNCTIONS
# ==============================================================================

_stage3_engine: Optional[Stage3Engine] = None


def get_stage3_engine() -> Stage3Engine:
    """Get or create singleton Stage3Engine."""
    global _stage3_engine
    if _stage3_engine is None:
        _stage3_engine = Stage3Engine()
        _stage3_engine.load_config_file()
    return _stage3_engine


def run_stage3(xai_output: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run Stage 3 processing (main entry point).
    
    Args:
        xai_output: Output from Stage 2 (XAI)
        
    Returns:
        Stage3 output dict for Stage 4 / API
        
    Example:
        >>> xai_out = {
        ...     "trace_id": "abc123",
        ...     "career": "Data Scientist",
        ...     "reason_codes": ["math_high", "logic_strong", "ai_interest"],
        ...     "sources": ["shap", "coef", "importance"],
        ...     "confidence": 0.87
        ... }
        >>> result = run_stage3(xai_out)
        >>> print(result["explain_text"])
        Bạn phù hợp với Data Scientist vì:
        - Điểm Toán vượt ngưỡng yêu cầu (shap)
        - Năng lực tư duy logic tốt (coef)
        - Mức độ quan tâm cao tới AI (importance)
        
        Độ tin cậy mô hình: 87.0%
    """
    engine = get_stage3_engine()
    result = engine.run(xai_output)
    return result.to_dict()

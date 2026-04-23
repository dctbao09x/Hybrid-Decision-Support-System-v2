# backend/api/controllers/explain_controller.py
"""
Explain Controller
==================

Controller layer for Explanation API (Stage 5).

Responsibilities:
  - Validate input
  - Assign trace_id
  - Call main-control orchestrator
  - Handle errors
  - Build response

This controller MUST call main-control for all pipeline stages.
No bypass allowed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger("api.explain.controller")

# Error codes mapping
ERROR_CODES = {
    "validation": "E400",
    "timeout": "E504",
    "llm_fail": "E502",
    "internal": "E500",
}

# Version info
API_VERSION = "v1"
CONTROLLER_VERSION = "1.0.0"


# ==============================================================================
# Configuration
# ==============================================================================

@dataclass
class ExplainAPIConfig:
    """Configuration for Explain API."""
    
    timeout: float = 10.0  # Fast timeout with graceful fallback (no LLM stalling)
    max_payload_bytes: int = 65536  # 64KB
    enable_llm: bool = True
    audit: bool = True
    log_level: str = "full"
    log_dir: str = "logs"
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExplainAPIConfig":
        """Load from config dict."""
        api_config = data.get("api", {}).get("explain", data)
        return cls(
            timeout=api_config.get("timeout", 10.0),
            max_payload_bytes=api_config.get("max_payload", 65536),
            enable_llm=api_config.get("enable_llm", True),
            audit=api_config.get("audit", True),
            log_level=api_config.get("log_level", "full"),
            log_dir=api_config.get("log_dir", "logs"),
        )


# ==============================================================================
# Request Validation
# ==============================================================================

@dataclass
class ValidationError:
    """Validation error details."""
    
    field: str
    message: str
    code: str = "E400"


class RequestValidator:
    """
    Validates explain request against schema.
    
    Checks:
      - Required fields present
      - Type checking
      - Range checking
      - Missing field detection
    """
    
    # Required fields
    REQUIRED_FEATURES = ["math_score", "logic_score"]
    
    # Score range
    SCORE_MIN = 0
    SCORE_MAX = 10
    
    # Feature fields and their types
    FEATURE_FIELDS = {
        "math_score": (int, float),
        "physics_score": (int, float),
        "interest_it": (int, float),
        "logic_score": (int, float),
        "language_score": (int, float),
        "creativity_score": (int, float),
    }
    
    def validate(self, request: Dict[str, Any]) -> List[ValidationError]:
        """
        Validate request.
        
        Args:
            request: Raw request dict
            
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        # Check required top-level fields
        if "user_id" not in request:
            errors.append(ValidationError(
                field="user_id",
                message="Missing required field: user_id",
            ))
        elif not isinstance(request["user_id"], str) or len(request["user_id"]) == 0:
            errors.append(ValidationError(
                field="user_id",
                message="user_id must be a non-empty string",
            ))
        
        if "request_id" not in request:
            errors.append(ValidationError(
                field="request_id",
                message="Missing required field: request_id",
            ))
        
        if "features" not in request:
            errors.append(ValidationError(
                field="features",
                message="Missing required field: features",
            ))
            return errors  # Can't continue without features
        
        features = request["features"]
        if not isinstance(features, dict):
            errors.append(ValidationError(
                field="features",
                message="features must be an object",
            ))
            return errors
        
        # Check required features
        for req_field in self.REQUIRED_FEATURES:
            if req_field not in features:
                errors.append(ValidationError(
                    field=f"features.{req_field}",
                    message=f"Missing required feature: {req_field}",
                ))
        
        # Type and range check for features
        for field_name, allowed_types in self.FEATURE_FIELDS.items():
            if field_name in features:
                value = features[field_name]
                
                # Type check
                if not isinstance(value, allowed_types):
                    errors.append(ValidationError(
                        field=f"features.{field_name}",
                        message=f"{field_name} must be a number",
                    ))
                    continue
                
                # Range check
                if value < self.SCORE_MIN or value > self.SCORE_MAX:
                    errors.append(ValidationError(
                        field=f"features.{field_name}",
                        message=f"{field_name} must be between {self.SCORE_MIN} and {self.SCORE_MAX}",
                    ))
        
        return errors


# ==============================================================================
# Response Builder
# ==============================================================================

@dataclass
class ExplainResponse:
    """Standardized explain response."""
    
    api_version: str
    trace_id: str
    career: str
    confidence: float
    reasons: List[str]
    explain_text: str
    llm_text: str
    used_llm: bool
    meta: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to response dict."""
        return {
            "api_version": self.api_version,
            "trace_id": self.trace_id,
            "career": self.career,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "explain_text": self.explain_text,
            "llm_text": self.llm_text,
            "used_llm": self.used_llm,
            "meta": self.meta,
            "timestamp": self.timestamp,
        }


class ResponseBuilder:
    """Builds standardized API responses."""
    
    def __init__(
        self,
        model_version: str = "unknown",
        xai_version: str = "1.0.0",
        stage3_version: str = "1.0.0",
        stage4_version: str = "1.0.0",
    ):
        self._model_version = model_version
        self._xai_version = xai_version
        self._stage3_version = stage3_version
        self._stage4_version = stage4_version
    
    def build_success(
        self,
        trace_id: str,
        pipeline_result: Dict[str, Any],
    ) -> ExplainResponse:
        """Build success response from pipeline result."""
        return ExplainResponse(
            api_version=API_VERSION,
            trace_id=trace_id,
            career=pipeline_result.get("career", ""),
            confidence=float(pipeline_result.get("confidence", 0.0)),
            reasons=pipeline_result.get("reasons", []),
            explain_text=pipeline_result.get("explain_text", ""),
            llm_text=pipeline_result.get("llm_text", ""),
            used_llm=pipeline_result.get("used_llm", False),
            meta={
                "model_version": self._model_version,
                "xai_version": self._xai_version,
                "stage3_version": self._stage3_version,
                "stage4_version": self._stage4_version,
            },
        )
    
    def build_error(
        self,
        trace_id: str,
        error_code: str,
        message: str,
    ) -> Dict[str, Any]:
        """Build error response."""
        return {
            "api_version": API_VERSION,
            "trace_id": trace_id,
            "error": {
                "code": error_code,
                "message": message,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ==============================================================================
# Audit Logger
# ==============================================================================

class AuditLogger:
    """
    Audit logger for explain API requests.
    
    Logs:
      - trace_id
      - user_id (hashed)
      - latency
      - status
      - used_llm
      - error_code
    """
    
    def __init__(self, log_dir: Path, log_level: str = "full"):
        self._log_dir = log_dir
        self._log_level = log_level
        self._log_file = log_dir / "api_explain.log"
        
        # Ensure log dir exists
        self._log_dir.mkdir(parents=True, exist_ok=True)
    
    def log(
        self,
        trace_id: str,
        user_id: str,
        latency_ms: float,
        status: str,
        used_llm: bool = False,
        error_code: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write audit log entry."""
        if self._log_level == "off":
            return
        
        # Hash user_id for privacy
        user_hash = hashlib.sha256(user_id.encode()).hexdigest()[:16]
        
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace_id": trace_id,
            "user_id_hash": user_hash,
            "latency_ms": round(latency_ms, 2),
            "status": status,
            "used_llm": used_llm,
            "error_code": error_code,
        }
        
        if self._log_level == "full" and extra:
            entry["extra"] = extra
        
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")


# ==============================================================================
# Explain Controller
# ==============================================================================

class ExplainController:
    """
    Controller for Explanation API.
    
    Orchestrates:
      1. Input validation
      2. Trace ID assignment
      3. Main-control pipeline call
      4. Error handling
      5. Response building
      6. Audit logging
    
    Usage::
    
        controller = ExplainController()
        controller.load_config(config)
        
        # Handle request
        response = await controller.handle(request)
    """
    
    def __init__(self, project_root: Optional[Path] = None):
        self._project_root = project_root or Path(__file__).resolve().parents[3]
        
        # Components
        self._config = ExplainAPIConfig()
        self._validator = RequestValidator()
        self._response_builder = ResponseBuilder()
        self._audit_logger: Optional[AuditLogger] = None
        
        # Main control reference
        self._main_control = None
        
        # Persistence
        self._history_storage = None
    
    def load_config(self, config: Dict[str, Any]) -> None:
        """Load configuration."""
        self._config = ExplainAPIConfig.from_dict(config)
        
        # Initialize audit logger
        log_dir = self._project_root / self._config.log_dir
        self._audit_logger = AuditLogger(log_dir, self._config.log_level)
        
        logger.info(
            f"ExplainController config: timeout={self._config.timeout}s, "
            f"enable_llm={self._config.enable_llm}"
        )
    
    def load_config_file(self, config_path: Optional[str] = None) -> None:
        """Load configuration from file."""
        if config_path is None:
            config_path = str(self._project_root / "config" / "api.yaml")
        
        path = Path(config_path)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
                self.load_config(config)
            except Exception as e:
                logger.warning(f"Failed to load config: {e}")
    
    def set_main_control(self, main_control: Any) -> None:
        """Set main control reference for pipeline execution."""
        self._main_control = main_control
    
    def set_history_storage(self, storage: Any) -> None:
        """Set history storage for replay support."""
        self._history_storage = storage
    
    def set_versions(
        self,
        model_version: str = "unknown",
        xai_version: str = "1.0.0",
        stage3_version: str = "1.0.0",
        stage4_version: str = "1.0.0",
    ) -> None:
        """Set component versions for response metadata."""
        self._response_builder = ResponseBuilder(
            model_version=model_version,
            xai_version=xai_version,
            stage3_version=stage3_version,
            stage4_version=stage4_version,
        )
    
    async def handle(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle explain request.
        
        Args:
            request: Raw request dict
            
        Returns:
            Response dict
        """
        start_time = time.time()
        trace_id = request.get("request_id", str(uuid.uuid4()))
        user_id = request.get("user_id", "anonymous")
        
        try:
            # 1. Validate input
            errors = self._validator.validate(request)
            if errors:
                latency_ms = (time.time() - start_time) * 1000
                error_msg = "; ".join([f"{e.field}: {e.message}" for e in errors])
                
                self._log_audit(
                    trace_id=trace_id,
                    user_id=user_id,
                    latency_ms=latency_ms,
                    status="validation_error",
                    error_code=ERROR_CODES["validation"],
                )
                
                return self._response_builder.build_error(
                    trace_id=trace_id,
                    error_code=ERROR_CODES["validation"],
                    message=error_msg,
                )
            
            # 2. Check main control
            if self._main_control is None:
                raise RuntimeError("Main control not initialized")
            
            # 3. Extract features and options
            features = request["features"]
            options = request.get("options", {})
            use_llm = options.get("use_llm", self._config.enable_llm)
            
            # 4. Run pipeline through main control
            # This is the ONLY way to run the pipeline - no bypass
            pipeline_result = await self._run_pipeline(
                trace_id=trace_id,
                features=features,
                use_llm=use_llm,
            )
            
            latency_ms = (time.time() - start_time) * 1000
            
            # 5. Build response
            response = self._response_builder.build_success(
                trace_id=trace_id,
                pipeline_result=pipeline_result,
            )
            
            # 6. Store in history for replay
            if self._history_storage:
                await self._store_history(
                    trace_id=trace_id,
                    request=request,
                    response=response.to_dict(),
                )
            
            # 7. Audit log
            self._log_audit(
                trace_id=trace_id,
                user_id=user_id,
                latency_ms=latency_ms,
                status="success",
                used_llm=response.used_llm,
            )
            
            return response.to_dict()
            
        except TimeoutError as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error(f"Pipeline timeout: {e}")
            
            self._log_audit(
                trace_id=trace_id,
                user_id=user_id,
                latency_ms=latency_ms,
                status="timeout",
                error_code=ERROR_CODES["timeout"],
            )
            
            return self._response_builder.build_error(
                trace_id=trace_id,
                error_code=ERROR_CODES["timeout"],
                message="Request timed out",
            )
            
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            logger.error(f"Pipeline error: {e}")
            
            self._log_audit(
                trace_id=trace_id,
                user_id=user_id,
                latency_ms=latency_ms,
                status="error",
                error_code=ERROR_CODES["internal"],
            )
            
            return self._response_builder.build_error(
                trace_id=trace_id,
                error_code=ERROR_CODES["internal"],
                message="Internal server error",
            )
    
    async def _run_pipeline(
        self,
        trace_id: str,
        features: Dict[str, Any],
        use_llm: bool,
    ) -> Dict[str, Any]:
        """
        Run explain pipeline through main control.
        
        This method MUST go through main_control - no bypass allowed.
        """
        import asyncio
        
        # Prepare features for model
        feature_array = self._prepare_features(features)
        
        # Run full pipeline: Inference → XAI → Stage3 → Stage4
        def run_sync():
            # Get prediction from main control
            inference_result = self._main_control.run_inference(feature_array)
            
            # Get XAI explanation (Stage 2)
            xai_result = self._main_control.run_xai(
                features=feature_array,
                prediction=inference_result,
                trace_id=trace_id,
            )
            
            # Run Stage 3 + Stage 4 through explain pipeline
            explain_result = self._main_control.run_explain_pipeline(
                xai_output=xai_result,
                use_llm=use_llm,
            )
            
            # Merge results
            explain_result["career"] = inference_result.get("career", "")
            explain_result["confidence"] = inference_result.get("confidence", 0.0)
            
            return explain_result
        
        # Run with timeout
        result = await asyncio.wait_for(
            asyncio.to_thread(run_sync),
            timeout=self._config.timeout,
        )
        
        return result
    
    def _prepare_features(self, features: Dict[str, Any]) -> Dict[str, float]:
        """Prepare features dict with defaults."""
        return {
            "math_score": float(features.get("math_score", 0)),
            "physics_score": float(features.get("physics_score", 0)),
            "interest_it": float(features.get("interest_it", 0)),
            "logic_score": float(features.get("logic_score", 0)),
            "language_score": float(features.get("language_score", 0)),
            "creativity_score": float(features.get("creativity_score", 0)),
        }
    
    async def _store_history(
        self,
        trace_id: str,
        request: Dict[str, Any],
        response: Dict[str, Any],
    ) -> None:
        """Store request/response for replay support."""
        if self._history_storage:
            await self._history_storage.store(
                trace_id=trace_id,
                request=request,
                response=response,
            )
    
    def _log_audit(
        self,
        trace_id: str,
        user_id: str,
        latency_ms: float,
        status: str,
        used_llm: bool = False,
        error_code: Optional[str] = None,
    ) -> None:
        """Log audit entry."""
        if self._audit_logger and self._config.audit:
            self._audit_logger.log(
                trace_id=trace_id,
                user_id=user_id,
                latency_ms=latency_ms,
                status=status,
                used_llm=used_llm,
                error_code=error_code,
            )
    
    async def get_by_id(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """
        Get stored response by trace_id for replay.
        
        Args:
            trace_id: The trace ID to look up
            
        Returns:
            Stored response or None
        """
        if self._history_storage:
            return await self._history_storage.get(trace_id)
        return None


# ==============================================================================
# Helper Functions
# ==============================================================================

_explain_controller: Optional[ExplainController] = None


def get_explain_controller() -> ExplainController:
    """Get or create singleton ExplainController."""
    global _explain_controller
    if _explain_controller is None:
        _explain_controller = ExplainController()
        _explain_controller.load_config_file()
    return _explain_controller


async def explain_handler(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point for explain API.
    
    Args:
        request: Request dict with user_id, request_id, features
        
    Returns:
        Response dict with explanation
        
    Example:
        >>> request = {
        ...     "user_id": "user123",
        ...     "request_id": "abc-123-def",
        ...     "features": {
        ...         "math_score": 85,
        ...         "logic_score": 90
        ...     }
        ... }
        >>> response = await explain_handler(request)
    """
    controller = get_explain_controller()
    return await controller.handle(request)

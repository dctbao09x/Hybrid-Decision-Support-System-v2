# backend/quality/confidence_policy.py
"""
HARDENED: Confidence Threshold Policy + Pipeline Integration Control — Section D
================================================================================

PIPELINE ORDER (ENFORCED):
--------------------------
1. Feature Extraction → raw_features
2. Feature Freeze → frozen_features (IMMUTABLE COPY)
3. SIMGRScorer.score(frozen_features) → base_score
4. ConsistencyValidator.validate() → confidence_score
5. AdaptiveProbe (if triggered) → confidence_adjustment
6. ExplanationRenderer(base_score, confidence) → output

NON-INTERFERENCE GUARANTEE:
---------------------------
INVARIANT: base_score is computed BEFORE confidence exists
INVARIANT: frozen_features cannot be mutated after step 2
INVARIANT: confidence_score affects ONLY explanation/flagging

FEATURE FREEZE PROTOCOL:
-----------------------
frozen_features = deepcopy(raw_features)
del raw_features  # Prevent accidental use
# SIMGRScorer receives frozen_features only

Author: Quality Layer Hardening v2
Revision: HARDENED 2026 — Section D
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger("quality.confidence_policy")


class ConfidenceBand(Enum):
    """Confidence level bands."""
    HIGH = "high"           # [0.8, 1.0]
    MEDIUM = "medium"       # [0.6, 0.8)
    LOW = "low"             # [0.4, 0.6)
    CRITICAL = "critical"   # [0.0, 0.4)


class ExplanationMode(Enum):
    """Explanation detail levels."""
    FULL = "full"
    DEGRADED = "degraded"
    MINIMAL = "minimal"


class QualityFlag(Enum):
    """Quality warning flags."""
    WARNING_DATA_QUALITY = "WARNING_DATA_QUALITY"
    CRITICAL_DATA_QUALITY = "CRITICAL_DATA_QUALITY"


# ===========================================================================
# PIPELINE STAGE DEFINITIONS (IMMUTABLE)
# ===========================================================================
class PipelineStage(Enum):
    """Pipeline stages with execution order."""
    FEATURE_EXTRACT = (1, "feature_extraction")
    FEATURE_FREEZE = (2, "feature_freeze")
    BASE_SCORING = (3, "simgr_scorer")
    CONFIDENCE_COMPUTE = (4, "consistency_validator")
    ADAPTIVE_PROBE = (5, "adaptive_probe")
    EXPLANATION_RENDER = (6, "explanation_render")
    
    def __init__(self, order: int, name: str):
        self._order = order
        self._name = name
    
    @property
    def order(self) -> int:
        return self._order
    
    @property
    def stage_name(self) -> str:
        return self._name


@dataclass(frozen=True)
class FrozenFeatures:
    """
    IMMUTABLE feature container.
    
    Once created, features cannot be modified.
    This ensures SIMGRScorer receives exactly what was frozen.
    """
    data: Tuple[Tuple[str, Any], ...]
    timestamp: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Read-only dict view."""
        return dict(self.data)
    
    def __hash__(self):
        return hash(self.data)


def freeze_features(raw_features: Dict[str, Any]) -> FrozenFeatures:
    """
    Freeze features for SIMGRScorer.
    
    GUARANTEE: Returns immutable copy.
    
    Usage:
        frozen = freeze_features(raw_features)
        del raw_features  # Prevent accidental mutation
        base_score = scorer.score(frozen.to_dict())
    """
    import time
    
    # Deep copy to prevent mutation
    copied = copy.deepcopy(raw_features)
    
    # Convert to immutable tuple structure
    items = tuple(sorted((k, _make_hashable(v)) for k, v in copied.items()))
    
    return FrozenFeatures(data=items, timestamp=time.time())


def _make_hashable(value: Any) -> Any:
    """Convert value to hashable form."""
    if isinstance(value, dict):
        return tuple(sorted((k, _make_hashable(v)) for k, v in value.items()))
    elif isinstance(value, list):
        return tuple(_make_hashable(v) for v in value)
    elif isinstance(value, set):
        return frozenset(_make_hashable(v) for v in value)
    return value


@dataclass(frozen=True)
class ConfidenceThresholdPolicy:
    """
    IMMUTABLE threshold policy.
    
    CRITICAL: These thresholds NEVER affect base scoring.
    """
    
    EXPLANATION_FULL_THRESHOLD: float = 0.6
    EXPLANATION_MINIMAL_THRESHOLD: float = 0.3
    FLAG_WARNING_THRESHOLD: float = 0.7
    FLAG_CRITICAL_THRESHOLD: float = 0.4
    ADAPTIVE_TRIGGER_THRESHOLD: float = 0.6
    RESURVEY_OFFER_THRESHOLD: float = 0.3
    BAND_HIGH: float = 0.8
    BAND_MEDIUM: float = 0.6
    BAND_LOW: float = 0.4
    
    def get_confidence_band(self, confidence: float) -> ConfidenceBand:
        if confidence >= self.BAND_HIGH:
            return ConfidenceBand.HIGH
        elif confidence >= self.BAND_MEDIUM:
            return ConfidenceBand.MEDIUM
        elif confidence >= self.BAND_LOW:
            return ConfidenceBand.LOW
        return ConfidenceBand.CRITICAL
    
    def get_explanation_mode(self, confidence: float) -> ExplanationMode:
        if confidence >= self.EXPLANATION_FULL_THRESHOLD:
            return ExplanationMode.FULL
        elif confidence >= self.EXPLANATION_MINIMAL_THRESHOLD:
            return ExplanationMode.DEGRADED
        return ExplanationMode.MINIMAL
    
    def get_quality_flags(self, confidence: float) -> List[QualityFlag]:
        flags = []
        if confidence < self.FLAG_CRITICAL_THRESHOLD:
            flags.append(QualityFlag.CRITICAL_DATA_QUALITY)
        elif confidence < self.FLAG_WARNING_THRESHOLD:
            flags.append(QualityFlag.WARNING_DATA_QUALITY)
        return flags
    
    def should_trigger_adaptive(self, confidence: float) -> bool:
        return confidence < self.ADAPTIVE_TRIGGER_THRESHOLD
    
    def should_offer_resurvey(self, confidence: float) -> bool:
        return confidence < self.RESURVEY_OFFER_THRESHOLD
    
    def get_action_summary(self, confidence: float) -> dict:
        return {
            "confidence_score": confidence,
            "band": self.get_confidence_band(confidence).value,
            "explanation_mode": self.get_explanation_mode(confidence).value,
            "quality_flags": [f.value for f in self.get_quality_flags(confidence)],
            "trigger_adaptive": self.should_trigger_adaptive(confidence),
            "offer_resurvey": self.should_offer_resurvey(confidence),
        }


# ===========================================================================
# PIPELINE INTEGRATION CONTROLLER
# ===========================================================================
class QualityPipelineController:
    """
    HARDENED Pipeline Controller enforcing stage order.
    
    GUARANTEES:
        1. Features frozen before scoring
        2. Base score computed before confidence
        3. Confidence cannot backpropagate to scoring
    
    USAGE:
        controller = QualityPipelineController()
        
        # Stage 1-2: Freeze
        frozen = controller.freeze_features(raw_features)
        
        # Stage 3: Score (SIMGRScorer called externally)
        base_score = scorer.score(frozen.to_dict())
        controller.register_base_score(base_score)
        
        # Stage 4-5: Confidence (validated)
        confidence = controller.compute_confidence(validator, ...)
        
        # Stage 6: Explain
        result = controller.render_explanation(base_score, confidence)
    """
    
    def __init__(self, policy: Optional[ConfidenceThresholdPolicy] = None):
        self._policy = policy or ConfidenceThresholdPolicy()
        self._frozen_features: Optional[FrozenFeatures] = None
        self._base_score: Optional[float] = None
        self._confidence: Optional[float] = None
        self._current_stage = 0
        logger.info("QualityPipelineController (HARDENED) initialized")
    
    def freeze_features(self, raw_features: Dict[str, Any]) -> FrozenFeatures:
        """
        Stage 1-2: Extract and freeze features.
        
        GUARANTEE: After this, features are immutable.
        """
        assert self._current_stage < 2, "Cannot freeze: already past feature stage"
        
        self._frozen_features = freeze_features(raw_features)
        self._current_stage = 2
        
        logger.debug(f"Features frozen at stage 2 (timestamp={self._frozen_features.timestamp})")
        return self._frozen_features
    
    def register_base_score(self, base_score: float) -> None:
        """
        Stage 3: Register base score from SIMGRScorer.
        
        INVARIANT: Must be called AFTER freeze_features.
        """
        assert self._current_stage >= 2, "Cannot score: features not frozen"
        assert self._base_score is None, "Base score already registered (no re-scoring)"
        
        self._base_score = base_score
        self._current_stage = 3
        
        logger.debug(f"Base score registered at stage 3: {base_score:.4f}")
    
    def compute_confidence(
        self,
        validator,
        response_times_ms: Optional[List[int]] = None,
        likert_responses: Optional[List[int]] = None,
        trait_responses: Optional[Dict[str, int]] = None,
    ) -> float:
        """
        Stage 4: Compute confidence AFTER base scoring.
        
        INVARIANT: Base score is already frozen.
        """
        assert self._current_stage >= 3, "Cannot compute confidence: base score not set"
        
        result = validator.validate(response_times_ms, likert_responses, trait_responses)
        self._confidence = result.confidence_score
        self._current_stage = 4
        
        logger.debug(f"Confidence computed at stage 4: {self._confidence:.4f}")
        return self._confidence
    
    def get_policy_actions(self) -> Dict[str, Any]:
        """
        Stage 5-6: Get policy actions based on confidence.
        
        GUARANTEE: Returns actions based on ALREADY COMPUTED confidence.
        """
        assert self._confidence is not None, "Confidence not yet computed"
        return self._policy.get_action_summary(self._confidence)
    
    @property
    def base_score(self) -> Optional[float]:
        return self._base_score
    
    @property
    def confidence_score(self) -> Optional[float]:
        return self._confidence
    
    @property
    def features(self) -> Optional[FrozenFeatures]:
        return self._frozen_features


DEFAULT_POLICY = ConfidenceThresholdPolicy()

def get_default_policy() -> ConfidenceThresholdPolicy:
    return DEFAULT_POLICY

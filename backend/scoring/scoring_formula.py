# backend/scoring/scoring_formula.py
"""
CENTRAL FORMULA MODULE - SINGLE SOURCE OF TRUTH (GĐ4)

This file is the ONLY authority for:
- Scoring formula definition
- Component definitions
- Sign conventions
- Weight loading
- Score computation
- Output clamping

ALL OTHER MODULES MUST DELEGATE TO THIS MODULE.

NO HARDCODED FORMULAS ELSEWHERE.
NO DUPLICATE DEFINITIONS.
NO IMPLICIT MAPPINGS.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from backend.scoring.config import SIMGRWeights

logger = logging.getLogger(__name__)


# =====================================================
# FORMULA REGISTRY - DO NOT DUPLICATE
# =====================================================

class ComponentSign(Enum):
    """Sign convention for score aggregation.
    
    POSITIVE = contributes positively to total score
    NEGATIVE = subtracts from total score (penalty)
    """
    POSITIVE = +1
    NEGATIVE = -1


@dataclass(frozen=True)
class ComponentSpec:
    """Immutable specification for a SIMGR component."""
    name: str
    weight_key: str
    sign: ComponentSign
    default_fallback: float
    description: str


class ScoringFormula:
    """
    CENTRAL AUTHORITY for SIMGR scoring formula.
    
    This class is the SINGLE SOURCE OF TRUTH for:
    - Formula specification
    - Component definitions
    - Sign conventions
    - Score computation
    
    VERSION HISTORY:
    - v1.0: Initial formula with 5 components (SIMGR) — spec only, not fully activated
    - v1.3_3component: Production weights with market=0, risk=0 (3-component de-facto)
                       Training pipeline bug: positive=True without sign convention.
                       Historical records tagged with this version for backward compat.
    - v2.0_full_SIMGR: Full 5-component production model.
                       Training pipeline fixed: sign convention applied before fit.
                       All 5 components (S,I,M,G,R) have non-zero production weights.
    
    FORMULA:
        Score = wS*S + wI*I + wM*M + wG*G - wR*R
        Score = clamp(Score, 0.0, 1.0)
        
    Where:
        wS, wI, wM, wG, wR = weights (sum to 1.0, each >= 0.05)
        S = Study score
        I = Interest score
        M = Market score
        G = Growth score
        R = Risk score (SUBTRACTED)
    
    DO NOT MODIFY WITHOUT VERSION INCREMENT.
    """
    
    # ===========================================
    # CANONICAL DEFINITIONS - DO NOT DUPLICATE
    # ===========================================

    VERSION = "v2.0_full_SIMGR"

    # Legacy version tag for historical records produced before full 5-component activation
    LEGACY_VERSION = "v1.3_3component"

    # All known formula versions with description
    FORMULA_VERSIONS: Dict[str, str] = {
        "v1.0": "Initial 5-component spec (not fully activated in production)",
        "v1.3_3component": "Production 3-component de-facto (market=0, risk=0) — training pipeline bug",
        "v2.0_full_SIMGR": "Full 5-component production model — all S,I,M,G,R active",
    }

    SPEC = "Score = wS*S + wI*I + wM*M + wG*G - wR*R"

    # Minimum allowed weight per component in production
    MIN_COMPONENT_WEIGHT = 0.05
    
    COMPONENTS: List[str] = [
        "study",
        "interest",
        "market",
        "growth",
        "risk"
    ]
    
    SIGN: Dict[str, int] = {
        "study": +1,
        "interest": +1,
        "market": +1,
        "growth": +1,
        "risk": -1  # RISK IS SUBTRACTED
    }
    
    WEIGHT_KEYS: Dict[str, str] = {
        "study": "study_score",
        "interest": "interest_score",
        "market": "market_score",
        "growth": "growth_score",
        "risk": "risk_score"
    }
    
    DEFAULT_FALLBACKS: Dict[str, float] = {
        "study": 0.5,
        "interest": 0.5,
        "market": 0.5,
        "growth": 0.5,
        "risk": 0.0  # Risk defaults to 0 (no penalty) when missing
    }
    
    COMPONENT_SPECS: Dict[str, ComponentSpec] = {
        "study": ComponentSpec(
            name="study",
            weight_key="study_score",
            sign=ComponentSign.POSITIVE,
            default_fallback=0.5,
            description="Skill match score"
        ),
        "interest": ComponentSpec(
            name="interest",
            weight_key="interest_score",
            sign=ComponentSign.POSITIVE,
            default_fallback=0.5,
            description="Interest alignment score"
        ),
        "market": ComponentSpec(
            name="market",
            weight_key="market_score",
            sign=ComponentSign.POSITIVE,
            default_fallback=0.5,
            description="Market demand score"
        ),
        "growth": ComponentSpec(
            name="growth",
            weight_key="growth_score",
            sign=ComponentSign.POSITIVE,
            default_fallback=0.5,
            description="Growth potential score"
        ),
        "risk": ComponentSpec(
            name="risk",
            weight_key="risk_score",
            sign=ComponentSign.NEGATIVE,
            default_fallback=0.0,
            description="Risk penalty score (SUBTRACTED)"
        ),
    }
    
    # ===========================================
    # CLASS METHODS - FORMULA OPERATIONS
    # ===========================================
    
    @classmethod
    def get_formula(cls) -> str:
        """Get canonical formula specification.
        
        Returns:
            Formula spec string
        """
        return cls.SPEC
    
    @classmethod
    def get_version(cls) -> str:
        """Get formula version.
        
        Returns:
            Version string
        """
        return cls.VERSION
    
    @classmethod
    def get_components(cls) -> List[str]:
        """Get ordered list of components.
        
        Returns:
            List of component names in canonical order
        """
        return cls.COMPONENTS.copy()
    
    @classmethod
    def get_sign(cls, component: str) -> int:
        """Get sign for component.
        
        Args:
            component: Component name
            
        Returns:
            Sign (+1 or -1)
            
        Raises:
            KeyError: If component not found
        """
        if component not in cls.SIGN:
            raise KeyError(
                f"Unknown component: {component}. "
                f"Valid components: {cls.COMPONENTS}"
            )
        return cls.SIGN[component]
    
    @classmethod
    def get_weight_key(cls, component: str) -> str:
        """Get weight attribute key for component.
        
        Args:
            component: Component name
            
        Returns:
            Weight key string (e.g., "study_score")
            
        Raises:
            KeyError: If component not found
        """
        if component not in cls.WEIGHT_KEYS:
            raise KeyError(
                f"Unknown component: {component}. "
                f"Valid components: {cls.COMPONENTS}"
            )
        return cls.WEIGHT_KEYS[component]
    
    @classmethod
    def get_default_fallback(cls, component: str) -> float:
        """Get default fallback value for component.
        
        Args:
            component: Component name
            
        Returns:
            Default fallback value
            
        Raises:
            KeyError: If component not found
        """
        if component not in cls.DEFAULT_FALLBACKS:
            raise KeyError(
                f"Unknown component: {component}. "
                f"Valid components: {cls.COMPONENTS}"
            )
        return cls.DEFAULT_FALLBACKS[component]
    
    @classmethod
    def get_weights_from_config(cls, weights_obj: Any) -> Dict[str, float]:
        """Extract weights dict from SIMGRWeights object.
        
        Args:
            weights_obj: SIMGRWeights instance
            
        Returns:
            Dict mapping component to weight value
        """
        return {
            comp: getattr(weights_obj, cls.WEIGHT_KEYS[comp])
            for comp in cls.COMPONENTS
        }
    
    @classmethod
    def validate_scores(cls, scores: Dict[str, float]) -> None:
        """Validate score dict has all required components.
        
        Args:
            scores: Dict mapping component name to score value
            
        Raises:
            ValueError: If missing components or invalid values
        """
        # Check for missing components
        missing = set(cls.COMPONENTS) - set(scores.keys())
        if missing:
            raise ValueError(
                f"Missing required components: {missing}. "
                f"All SIMGR components required: {cls.COMPONENTS}"
            )
        
        # Validate each score is in [0, 1]
        for comp in cls.COMPONENTS:
            score = scores[comp]
            if not isinstance(score, (int, float)):
                raise ValueError(
                    f"Score for {comp} must be numeric, got {type(score)}"
                )
            if not (0.0 <= score <= 1.0):
                raise ValueError(
                    f"Score for {comp} must be in [0,1], got {score}"
                )
    
    @classmethod
    def validate_weights(cls, weights: Dict[str, float]) -> None:
        """Validate weight dict has all required components and sums to 1.
        
        Args:
            weights: Dict mapping component name to weight value
            
        Raises:
            ValueError: If missing components or invalid values
        """
        # Check for missing components
        missing = set(cls.COMPONENTS) - set(weights.keys())
        if missing:
            raise ValueError(
                f"Missing required weight components: {missing}. "
                f"All SIMGR weights required: {cls.COMPONENTS}"
            )
        
        # Validate sum
        total = sum(weights[comp] for comp in cls.COMPONENTS)
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"Weights must sum to 1.0, got {total:.4f}"
            )

    @classmethod
    def validate_no_zeros(cls, weights: Dict[str, float]) -> None:
        """Validate that no SIMGR component weight is zero or below minimum.

        A weight of 0 silently disables a component from affecting the final
        score, reducing the system to a sub-5-component model.  This is
        forbidden in v2.0_full_SIMGR production.

        Args:
            weights: Dict mapping component name to weight value

        Raises:
            ValueError: If any component has weight == 0 (hard block)
            UserWarning: Logged if any component has weight < MIN_COMPONENT_WEIGHT
        """
        import warnings

        zero_comps  = [c for c in cls.COMPONENTS if weights.get(c, 0.0) == 0.0]
        low_comps   = [
            (c, weights.get(c, 0.0))
            for c in cls.COMPONENTS
            if 0.0 < weights.get(c, 0.0) < cls.MIN_COMPONENT_WEIGHT
        ]

        if zero_comps:
            raise ValueError(
                f"5-Component SIMGR violation: components with weight=0: {zero_comps}. "
                f"All 5 components must contribute to the production model."
            )

        for comp, w in low_comps:
            warnings.warn(
                f"[ScoringFormula] Component '{comp}' weight={w:.4f} is below "
                f"recommended minimum {cls.MIN_COMPONENT_WEIGHT}.",
                UserWarning,
                stacklevel=2,
            )

    @classmethod
    def get_formula_versions(cls) -> Dict[str, str]:
        """Return all known formula versions with descriptions.

        Returns:
            Dict mapping version string to description
        """
        return cls.FORMULA_VERSIONS.copy()

    @classmethod
    def compute(
        cls,
        scores: Dict[str, float],
        weights: Dict[str, float],
        *,
        validate: bool = True,
        clamp_output: bool = True,
        method: Optional[str] = None
    ) -> float:
        """
        Compute total SIMGR score using canonical formula.
        
        THIS IS THE ONLY PLACE WHERE THE FORMULA IS COMPUTED.
        
        Formula: Score = wS*S + wI*I + wM*M + wG*G - wR*R
        
        GĐ Phase 1: Optional method validation for runtime integrity.
        
        Args:
            scores: Dict mapping component name to score [0,1]
            weights: Dict mapping component name to weight
            validate: If True, validate inputs before computing
            clamp_output: If True, clamp result to [0,1]
            method: Optional training method for integrity validation.
                    If provided and not 'linear_regression', raises RuntimeError.
            
        Returns:
            Total weighted score
            
        Raises:
            ValueError: If validation fails
            RuntimeError: If method validation fails (GĐ Phase 1)
        """
        # GĐ Phase 1: Runtime method validation (if provided)
        REQUIRED_METHOD = "linear_regression"
        if method is not None and method != "" and method != REQUIRED_METHOD:
            logger.critical(
                f"SCORING ABORTED: Weights are not ML-trained. "
                f"Expected method='{REQUIRED_METHOD}', got '{method}'."
            )
            raise RuntimeError(
                f"Scoring aborted: weights are not ML-trained. "
                f"Expected method='{REQUIRED_METHOD}', got '{method}'."
            )
        
        if validate:
            cls.validate_scores(scores)
            cls.validate_weights(weights)
        
        # CANONICAL FORMULA COMPUTATION
        # Score = Σ (sign[i] * weight[i] * score[i])
        total = 0.0
        for comp in cls.COMPONENTS:
            sign = cls.SIGN[comp]
            weight = weights[comp]
            score = scores[comp]
            total += sign * weight * score
        
        # Clamp to [0, 1]
        if clamp_output:
            total = cls.clamp(total)
        
        return total
    
    @classmethod
    def compute_from_weights_obj(
        cls,
        scores: Dict[str, float],
        weights_obj: Any,
        *,
        validate: bool = True,
        clamp_output: bool = True
    ) -> float:
        """
        Compute total score using SIMGRWeights object.
        
        Convenience method that extracts weights from object.
        
        GĐ Phase 1: RUNTIME GUARD - Validates weights are ML-trained.
        This prevents bypass even if weight loader is compromised.
        
        Args:
            scores: Dict mapping component name to score [0,1]
            weights_obj: SIMGRWeights instance
            validate: If True, validate inputs before computing
            clamp_output: If True, clamp result to [0,1]
            
        Returns:
            Total weighted score
            
        Raises:
            RuntimeError: If weights are not ML-trained (GĐ Phase 1)
        """
        # GĐ Phase 1: RUNTIME GUARD - Verify weights are ML-trained
        # This is a defense-in-depth check even if loader is compromised
        REQUIRED_METHOD = "linear_regression"
        
        weights_method = getattr(weights_obj, "_method", None)
        if weights_method is not None and weights_method != "" and weights_method != REQUIRED_METHOD:
            logger.critical(
                f"SCORING ABORTED: Weights are not ML-trained. "
                f"Expected method='{REQUIRED_METHOD}', got '{weights_method}'."
            )
            raise RuntimeError(
                f"Scoring aborted: weights are not ML-trained. "
                f"Expected method='{REQUIRED_METHOD}', got '{weights_method}'."
            )
        
        weights = cls.get_weights_from_config(weights_obj)
        return cls.compute(
            scores, 
            weights, 
            validate=validate, 
            clamp_output=clamp_output
        )
    
    @classmethod
    def clamp(cls, value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
        """Clamp value to range.
        
        Args:
            value: Value to clamp
            min_val: Minimum value (default 0.0)
            max_val: Maximum value (default 1.0)
            
        Returns:
            Clamped value
        """
        return max(min_val, min(max_val, value))
    
    @classmethod
    def get_breakdown(
        cls, 
        scores: Dict[str, float],
        weights: Dict[str, float]
    ) -> Dict[str, Any]:
        """Get detailed breakdown of score computation.
        
        Args:
            scores: Dict mapping component name to score [0,1]
            weights: Dict mapping component name to weight
            
        Returns:
            Breakdown dict with contributions and metadata
        """
        contributions = {}
        for comp in cls.COMPONENTS:
            sign = cls.SIGN[comp]
            weight = weights[comp]
            score = scores[comp]
            contribution = sign * weight * score
            contributions[comp] = {
                "score": round(score, 4),
                "weight": round(weight, 4),
                "sign": sign,
                "contribution": round(contribution, 4)
            }
        
        total_raw = sum(c["contribution"] for c in contributions.values())
        total_clamped = cls.clamp(total_raw)
        
        return {
            "formula": cls.SPEC,
            "version": cls.VERSION,
            "components": contributions,
            "total_raw": round(total_raw, 4),
            "total_clamped": round(total_clamped, 4),
            "was_clamped": total_raw != total_clamped
        }


# =====================================================
# PHASE 4: RUNTIME DRIFT GUARD (Task 5)
# =====================================================

class DriftMonitor:
    """Monitor for feature drift detection in production.
    
    Phase 4, Task 5: Runtime Drift Guard.
    
    Tracks average component scores over last N requests and compares
    to training dataset statistics. Logs warning if deviation exceeds threshold.
    
    Does NOT auto-disable model, only warns.
    
    Usage:
        drift_monitor = DriftMonitor()
        
        # On each scoring request:
        drift_monitor.track_scores(scores)
        drift_monitor.check_drift()
    """
    
    # Training dataset baseline statistics (from train.csv analysis)
    # These should be updated when retraining with new data
    TRAINING_STATS = {
        "study": {"mean": 0.65, "std": 0.18},
        "interest": {"mean": 0.55, "std": 0.22},
        "market": {"mean": 0.45, "std": 0.25},
        "growth": {"mean": 0.50, "std": 0.20},
        "risk": {"mean": 0.30, "std": 0.15},
    }
    
    # Configuration
    DEFAULT_WINDOW_SIZE = 100      # Track last N requests
    DEFAULT_DEVIATION_THRESHOLD = 0.20  # 20% deviation threshold
    
    def __init__(
        self,
        window_size: int = DEFAULT_WINDOW_SIZE,
        deviation_threshold: float = DEFAULT_DEVIATION_THRESHOLD
    ):
        """Initialize drift monitor.
        
        Args:
            window_size: Number of recent requests to track
            deviation_threshold: Threshold for drift warning (0.2 = 20%)
        """
        self.window_size = window_size
        self.deviation_threshold = deviation_threshold
        self._history: Dict[str, List[float]] = {comp: [] for comp in ScoringFormula.COMPONENTS}
        self._request_count = 0
        self._drift_warnings: List[Dict[str, Any]] = []
    
    def track_scores(self, scores: Dict[str, float]) -> None:
        """Track component scores for drift detection.
        
        Args:
            scores: Dict mapping component name to score value
        """
        self._request_count += 1
        
        for comp in ScoringFormula.COMPONENTS:
            if comp in scores:
                self._history[comp].append(scores[comp])
                # Keep only last N values
                if len(self._history[comp]) > self.window_size:
                    self._history[comp] = self._history[comp][-self.window_size:]
    
    def get_current_stats(self) -> Dict[str, Dict[str, float]]:
        """Get current average statistics from tracked history.
        
        Returns:
            Dict mapping component to {mean, std, count}
        """
        import numpy as np
        
        stats = {}
        for comp in ScoringFormula.COMPONENTS:
            values = self._history[comp]
            if len(values) >= 10:  # Need minimum samples
                stats[comp] = {
                    "mean": float(np.mean(values)),
                    "std": float(np.std(values)),
                    "count": len(values)
                }
        return stats
    
    def check_drift(self) -> List[Dict[str, Any]]:
        """Check for feature drift against training statistics.
        
        Phase 4, Task 5: Only logs warning, does NOT auto-disable.
        
        Returns:
            List of drift warnings (if any)
        """
        import numpy as np
        
        warnings = []
        current_stats = self.get_current_stats()
        
        for comp, current in current_stats.items():
            if comp not in self.TRAINING_STATS:
                continue
            
            training = self.TRAINING_STATS[comp]
            
            # Calculate relative deviation from training mean
            if training["mean"] > 0:
                deviation = abs(current["mean"] - training["mean"]) / training["mean"]
            else:
                deviation = abs(current["mean"] - training["mean"])
            
            if deviation > self.deviation_threshold:
                warning = {
                    "component": comp,
                    "training_mean": training["mean"],
                    "current_mean": current["mean"],
                    "deviation_pct": deviation * 100,
                    "threshold_pct": self.deviation_threshold * 100,
                    "samples": current["count"]
                }
                warnings.append(warning)
                
                logger.warning(
                    f"[DRIFT] Potential feature drift detected: {comp} "
                    f"(training={training['mean']:.3f}, current={current['mean']:.3f}, "
                    f"deviation={deviation*100:.1f}% > {self.deviation_threshold*100:.1f}%)"
                )
        
        if warnings:
            self._drift_warnings.extend(warnings)
        
        return warnings
    
    def get_drift_report(self) -> Dict[str, Any]:
        """Get full drift report.
        
        Returns:
            Dict with drift statistics and warnings
        """
        return {
            "request_count": self._request_count,
            "window_size": self.window_size,
            "threshold_pct": self.deviation_threshold * 100,
            "current_stats": self.get_current_stats(),
            "training_stats": self.TRAINING_STATS,
            "warnings": self._drift_warnings[-10:],  # Last 10 warnings
            "warning_count": len(self._drift_warnings)
        }
    
    def reset(self) -> None:
        """Reset drift monitor state."""
        self._history = {comp: [] for comp in ScoringFormula.COMPONENTS}
        self._request_count = 0
        self._drift_warnings = []


# Global drift monitor instance
_drift_monitor: Optional[DriftMonitor] = None


def get_drift_monitor() -> DriftMonitor:
    """Get global drift monitor instance (singleton)."""
    global _drift_monitor
    if _drift_monitor is None:
        _drift_monitor = DriftMonitor()
    return _drift_monitor


def track_scoring_request(scores: Dict[str, float]) -> None:
    """Track a scoring request for drift monitoring.
    
    Call this from scoring endpoints to enable drift detection.
    
    Args:
        scores: Component scores from the request
    """
    monitor = get_drift_monitor()
    monitor.track_scores(scores)
    
    # Check drift periodically (every 100 requests)
    if monitor._request_count % 100 == 0:
        monitor.check_drift()


# =====================================================
# FORMULA REGISTRY FOR EXTENSIBILITY
# =====================================================

class FormulaRegistry:
    """Registry for formula versions (for A/B testing and backward compat).

    Version map:
      v1.0             — initial spec (not fully activated)
      v1.3_3component  — legacy production 3-component de-facto
      v2.0_full_SIMGR  — current production 5-component model
    """

    _formulas: Dict[str, type] = {
        "v1.0":            ScoringFormula,
        "v1.3_3component": ScoringFormula,   # same formula class, different weight artifact
        "v2.0_full_SIMGR": ScoringFormula,
    }

    _active_version: str = "v2.0_full_SIMGR"
    
    @classmethod
    def get_formula(cls, version: Optional[str] = None) -> type:
        """Get formula class by version.
        
        Args:
            version: Version string (defaults to active)
            
        Returns:
            Formula class
            
        Raises:
            KeyError: If version not found
        """
        version = version or cls._active_version
        if version not in cls._formulas:
            raise KeyError(
                f"Unknown formula version: {version}. "
                f"Available: {list(cls._formulas.keys())}"
            )
        return cls._formulas[version]
    
    @classmethod
    def get_active_version(cls) -> str:
        """Get active formula version."""
        return cls._active_version
    
    @classmethod
    def set_active_version(cls, version: str) -> None:
        """Set active formula version (for testing).
        
        Args:
            version: Version to set as active
            
        Raises:
            KeyError: If version not found
        """
        if version not in cls._formulas:
            raise KeyError(
                f"Unknown formula version: {version}. "
                f"Available: {list(cls._formulas.keys())}"
            )
        cls._active_version = version
        logger.info(f"[FORMULA_REGISTRY] Active version set to: {version}")

    @classmethod
    def get_all_versions(cls) -> Dict[str, str]:
        """Return all known formula versions with descriptions."""
        return ScoringFormula.FORMULA_VERSIONS.copy()


# =====================================================
# MODULE-LEVEL HELPERS (FOR BACKWARDS COMPATIBILITY)
# =====================================================

def compute_simgr_score(
    scores: Dict[str, float],
    weights: Dict[str, float],
    *,
    validate: bool = True
) -> float:
    """Module-level helper for computing SIMGR score.
    
    Delegates to ScoringFormula.compute().
    
    Args:
        scores: Dict mapping component name to score [0,1]
        weights: Dict mapping component name to weight
        validate: If True, validate inputs before computing
        
    Returns:
        Total weighted score [0,1]
    """
    return ScoringFormula.compute(scores, weights, validate=validate)


def get_formula_spec() -> str:
    """Get canonical formula specification string."""
    return ScoringFormula.SPEC


def get_formula_version() -> str:
    """Get current formula version."""
    return ScoringFormula.VERSION


def get_component_names() -> List[str]:
    """Get ordered list of SIMGR component names."""
    return ScoringFormula.get_components()


def get_component_sign(component: str) -> int:
    """Get sign for component (+1 or -1)."""
    return ScoringFormula.get_sign(component)


# =====================================================
# SPEC SELF-VERIFICATION AT BOOT (GĐ4 Extended - PHẦN E)
# =====================================================

# Canonical formula spec that MUST match ScoringFormula.SPEC
# This ensures no one modifies the formula without updating this check
DOC_SPEC_FORMULA = "Score = wS*S + wI*I + wM*M + wG*G - wR*R"
DOC_SPEC_COMPONENTS = ["study", "interest", "market", "growth", "risk"]
DOC_SPEC_VERSION = "v2.0_full_SIMGR"

def _verify_spec_at_boot() -> None:
    """
    Verify formula spec at module import time.
    
    This ensures the runtime formula matches the documented spec.
    Any mismatch indicates formula drift and will raise AssertionError.
    
    Called automatically when module is imported.
    """
    # Verify formula string matches
    assert ScoringFormula.get_formula() == DOC_SPEC_FORMULA, (
        f"FORMULA DRIFT DETECTED!\n"
        f"  Expected: {DOC_SPEC_FORMULA}\n"
        f"  Actual  : {ScoringFormula.get_formula()}\n"
        f"If intentional change, update DOC_SPEC_FORMULA in scoring_formula.py"
    )
    
    # Verify components match
    assert ScoringFormula.get_components() == DOC_SPEC_COMPONENTS, (
        f"COMPONENT DRIFT DETECTED!\n"
        f"  Expected: {DOC_SPEC_COMPONENTS}\n"
        f"  Actual  : {ScoringFormula.get_components()}\n"
        f"If intentional change, update DOC_SPEC_COMPONENTS in scoring_formula.py"
    )
    
    # Verify version matches
    assert ScoringFormula.get_version() == DOC_SPEC_VERSION, (
        f"VERSION DRIFT DETECTED!\n"
        f"  Expected: {DOC_SPEC_VERSION}\n"
        f"  Actual  : {ScoringFormula.get_version()}\n"
        f"If intentional change, update DOC_SPEC_VERSION in scoring_formula.py"
    )
    
    # Verify sign convention for risk is NEGATIVE
    assert ScoringFormula.get_sign("risk") == -1, (
        f"RISK SIGN DRIFT! Risk MUST be subtracted (sign=-1)"
    )
    
    # Verify components have valid defaults
    for comp in ScoringFormula.COMPONENTS:
        fb = ScoringFormula.get_default_fallback(comp)
        assert 0.0 <= fb <= 1.0, f"Invalid fallback for {comp}: {fb}"

# Run verification at import time
_verify_spec_at_boot()


# =====================================================
# EXPORTS
# =====================================================

__all__ = [
    # Main class
    "ScoringFormula",
    # Supporting classes
    "ComponentSign",
    "ComponentSpec",
    "FormulaRegistry",
    # Spec verification
    "DOC_SPEC_FORMULA",
    "DOC_SPEC_COMPONENTS",
    "DOC_SPEC_VERSION",
    # Module-level helpers
    "compute_simgr_score",
    "get_formula_spec",
    "get_formula_version",
    "get_component_names",
    "get_component_sign",
    # Phase 4: Drift monitoring
    "DriftMonitor",
    "get_drift_monitor",
    "track_scoring_request",
]

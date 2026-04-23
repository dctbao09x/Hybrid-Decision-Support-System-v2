# backend/scoring/config.py
"""
Scoring configuration and weight management (SIMGR standard).

SIMGR = Study, Interest, Market, Growth, Risk scoring components.

Supports dynamic weight loading from trained models:
  - Load from models/weights/active/weights.json
  - Load from specific version: models/weights/v1/weights.json

GĐ5: Training ↔ Runtime Linkage
  - Runtime ONLY accepts weights from valid training pipeline
  - No manual weights, no shadow models, no bypass
  - Full metadata validation required
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Callable, Optional
import logging

logger = logging.getLogger(__name__)

# Default weights file path (file-relative so it works regardless of CWD)
DEFAULT_WEIGHTS_PATH = str(
    (Path(__file__).resolve().parent.parent.parent / "models" / "weights" / "active" / "weights.json")
)

# GĐ5: Runtime validation mode - controls weight governance enforcement
# HARDENED: Always STRICT in production. ENV override removed for determinism.
# Previous: os.environ.get("SIMGR_WEIGHT_VALIDATION_MODE", "WARN")
def _get_validation_mode() -> str:
    """Get validation mode from immutable manifest."""
    from backend.scoring.weight_manifest import load_validation_mode
    return load_validation_mode()

WEIGHT_VALIDATION_MODE = "STRICT"  # Default until manifest loads


# =====================================================
# Weight Classes (SIMGR Standard)
# =====================================================

@dataclass
class SIMGRWeights:
    """Main scoring weights - SIMGR standard.

    v2.0_full_SIMGR defaults: all 5 components non-zero.
    Previous defaults (study=0.25, interest=0.25, market=0.25, growth=0.15, risk=0.10)
    were correct in theory but production artifact had market=0, risk=0.
    New defaults reflect a balanced 5-component production weight set.
    """
    study_score: float = 0.30
    interest_score: float = 0.15
    market_score: float = 0.15
    growth_score: float = 0.30
    risk_score: float = 0.10

    # Metadata for tracking weight origin (GĐ Phase 1)
    _source: str = field(default="default", repr=False)
    _version: str = field(default="", repr=False)
    _method: str = field(default="", repr=False)  # ML training method (must be "linear_regression" for production)
    _formula_version: str = field(default="v2.0_full_SIMGR", repr=False)
    
    def __post_init__(self) -> None:
        """Validate weights sum to 1.0 and all components are non-zero."""
        total = (
            self.study_score
            + self.interest_score
            + self.market_score
            + self.growth_score
            + self.risk_score
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"SIMGR weights must sum to 1.0, got {total:.8f}"
            )
        # v2.0: Enforce 5-component model — no component may be exactly 0
        zero_comps = [
            k for k, v in self.to_dict().items() if v == 0.0
        ]
        if zero_comps:
            raise ValueError(
                f"5-Component SIMGR violation (v2.0_full_SIMGR): components "
                f"with weight=0: {zero_comps}.  All five weights must be > 0. "
                f"Re-run training pipeline with sign-corrected prepare_training_matrix."
            )
    
    @classmethod
    def from_file(cls, path: Optional[str] = None) -> SIMGRWeights:
        """Load weights from JSON file.
        
        Args:
            path: Path to weights JSON file. If None, uses active weights.
            
        Returns:
            SIMGRWeights instance with loaded values.
            
        Raises:
            FileNotFoundError: If weights file doesn't exist (NO FALLBACK).
            ValueError: If weights file is malformed or fails metadata validation.
            RuntimeError: If weights are incomplete (NO DEFAULTS) or integrity check fails.
            
        GĐ1: ALL FALLBACKS REMOVED - weights MUST exist.
        GĐ5: Runtime validation via WeightsRegistry - enforces training linkage.
        GĐ Phase 1: Scoring integrity validation - enforces ML-trained weights.
        """
        from backend.scoring.weights_registry import (
            WeightsRegistry,
            LoadMode, 
            get_registry,
            WeightValidationError,
            MissingMetadataError,
            ChecksumMismatchError,
            ManualWeightError,
            ScoringIntegrityError,
            ZeroWeightError,
            REQUIRED_METHOD,
        )
        
        path = path or DEFAULT_WEIGHTS_PATH
        
        # GĐ5: Determine validation mode from environment/config
        mode_str = WEIGHT_VALIDATION_MODE.upper()
        if mode_str == "STRICT":
            mode = LoadMode.STRICT
        elif mode_str == "BYPASS":
            mode = LoadMode.BYPASS
        else:
            mode = LoadMode.WARN
        
        # GĐ Phase 1: Use registry for integrity-enforced loading
        try:
            registry = WeightsRegistry(mode=mode)
            weights = registry.load_active_weights()
            
            # Get full weights data for metadata
            weights_path = Path(path)
            if weights_path.exists():
                with open(weights_path, "r", encoding="utf-8") as f:
                    weights_data = json.load(f)
                version = weights_data.get("version", "")
                method = weights_data.get("method") or weights_data.get("metrics", {}).get("method", "")
                trained_at = weights_data.get("trained_at", "")
            else:
                version = ""
                method = ""
                trained_at = ""
            
            instance = cls(
                study_score=weights.get("study_score", weights.get("study", 0)),
                interest_score=weights.get("interest_score", weights.get("interest", 0)),
                market_score=weights.get("market_score", weights.get("market", 0)),
                growth_score=weights.get("growth_score", weights.get("growth", 0)),
                risk_score=weights.get("risk_score", weights.get("risk", 0)),
            )
            instance._source = f"registry:active"
            instance._version = version
            instance._method = method
            
            logger.info(
                f"[WEIGHT_LOAD] Loaded weights version={version} "
                f"method={method} trained_at={trained_at}"
            )
            
            return instance
            
        except ScoringIntegrityError as e:
            # GĐ Phase 1: Scoring integrity violations are always fatal
            logger.critical(f"[WEIGHT_LOAD] SCORING INTEGRITY FAILURE - {e}")
            raise RuntimeError(f"Scoring integrity violation: {e}") from e

        except ZeroWeightError as e:
            # GĐ v2.0: Zero-weight components violate 5-component SIMGR spec
            logger.critical(
                f"[WEIGHT_LOAD] 5-COMPONENT SIMGR VIOLATION - {e}\n"
                "ACTION REQUIRED: Re-run training with fixed pipeline "
                "(GĐ v2.0 sign-corrected prepare_training_matrix)."
            )
            raise RuntimeError(f"5-component SIMGR violation: {e}") from e
            
        except (WeightValidationError, MissingMetadataError, 
                ChecksumMismatchError, ManualWeightError) as e:
            # GĐ5: Validation failures are fatal in STRICT mode
            logger.error(f"[WEIGHT_LOAD] GĐ5 VALIDATION FAILED - {e}")
            raise ValueError(f"GĐ5 validation failed: {e}") from e
            
        except FileNotFoundError:
            # GĐ1: NO FALLBACK - weight file MUST exist
            logger.critical(
                f"[WEIGHT_LOAD] FAILED - Weights file not found: {path}. "
                f"Trained weights REQUIRED - no default fallback."
            )
            raise RuntimeError(
                f"Active weights file missing. System integrity compromised. "
                f"Expected: {path}. Run training or provide valid weight artifact."
            )
            
        except Exception as e:
            logger.error(f"[WEIGHT_LOAD] FAILED - {e}")
            raise
    
    @classmethod
    def from_version(cls, version: str) -> SIMGRWeights:
        """Load weights from specific version directory.
        
        Args:
            version: Version identifier (e.g., "v1", "v2").
            
        Returns:
            SIMGRWeights instance from specified version.
            
        GĐ5: Uses WeightsRegistry for validated loading.
        """
        from backend.scoring.weights_registry import (
            LoadMode, 
            get_registry,
            WeightValidationError,
            MissingMetadataError,
            ChecksumMismatchError,
            ManualWeightError,
        )
        
        # GĐ5: Validation mode from immutable manifest (ENV override removed)
        # HARDENED: Always STRICT in production for deterministic scoring
        mode_str = _get_validation_mode().upper()
        if mode_str == "STRICT":
            mode = LoadMode.STRICT
        elif mode_str == "BYPASS":
            logger.warning("[WEIGHT_LOAD] BYPASS mode - only valid for testing")
            mode = LoadMode.BYPASS
        else:
            mode = LoadMode.STRICT  # Default to STRICT, not WARN
        
        # GĐ5: Use registry for validated loading
        try:
            registry = get_registry()
            payload, metadata = registry.load_version(version, mode=mode)
            
            weights = payload["weights"]
            ver = payload.get("version", version)
            
            instance = cls(
                study_score=weights.get("study_score", weights.get("study", 0)),
                interest_score=weights.get("interest_score", weights.get("interest", 0)),
                market_score=weights.get("market_score", weights.get("market", 0)),
                growth_score=weights.get("growth_score", weights.get("growth", 0)),
                risk_score=weights.get("risk_score", weights.get("risk", 0)),
            )
            instance._source = f"registry:{version}"
            instance._version = ver
            
            if metadata:
                logger.info(
                    f"[WEIGHT_LOAD] GĐ5 OK - Verified weights {version} "
                    f"(trained: {metadata.trained_at}, pipeline: {metadata.pipeline_version})"
                )
            else:
                logger.info(f"[WEIGHT_LOAD] OK - {version} (version: {ver})")
            
            return instance
            
        except (WeightValidationError, MissingMetadataError, 
                ChecksumMismatchError, ManualWeightError) as e:
            logger.error(f"[WEIGHT_LOAD] GĐ5 VALIDATION FAILED - {e}")
            raise ValueError(f"GĐ5 validation failed: {e}") from e
            
        except FileNotFoundError:
            logger.critical(f"[WEIGHT_LOAD] FAILED - Version {version} not found. System integrity compromised.")
            raise RuntimeError(f"Active weights file missing. System integrity compromised. Version: {version}")
            
        except Exception as e:
            logger.error(f"[WEIGHT_LOAD] FAILED - {e}")
            raise
    
    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary."""
        return {
            "study_score": self.study_score,
            "interest_score": self.interest_score,
            "market_score": self.market_score,
            "growth_score": self.growth_score,
            "risk_score": self.risk_score,
        }
    
    def normalize(self) -> None:
        """Normalize weights to sum to 1.0."""
        total = (
            self.study_score
            + self.interest_score
            + self.market_score
            + self.growth_score
            + self.risk_score
        )
        if total > 0:
            self.study_score /= total
            self.interest_score /= total
            self.market_score /= total
            self.growth_score /= total
            self.risk_score /= total


@dataclass
class ComponentWeights:
    """Sub-component weights for detailed scoring."""
    
    # Study component weights
    required_skill_match: float = 0.7
    preferred_skill_match: float = 0.3
    
    # Interest component weights
    # Uses Jaccard similarity by default
    
    # Market component weights
    ai_relevance: float = 0.4
    growth_rate: float = 0.4
    inverse_competition: float = 0.2
    
    # Growth component weights
    skill_growth_opportunity: float = 0.5
    salary_growth_potential: float = 0.5
    
    # Risk component weights
    market_saturation_risk: float = 0.4
    skill_obsolescence_risk: float = 0.3
    competition_risk: float = 0.3
    
    def __post_init__(self) -> None:
        """Validate sub-weights."""
        # Study weights
        study_total = (
            self.required_skill_match + self.preferred_skill_match
        )
        if abs(study_total - 1.0) > 0.001:
            raise ValueError(
                f"Study weights must sum to 1.0, got {study_total:.4f}"
            )
        
        # Market weights
        market_total = (
            self.ai_relevance
            + self.growth_rate
            + self.inverse_competition
        )
        if abs(market_total - 1.0) > 0.001:
            raise ValueError(
                f"Market weights must sum to 1.0, got {market_total:.4f}"
            )
        
        # Growth weights
        growth_total = (
            self.skill_growth_opportunity + self.salary_growth_potential
        )
        if abs(growth_total - 1.0) > 0.001:
            raise ValueError(
                f"Growth weights must sum to 1.0, got {growth_total:.4f}"
            )
        
        # Risk weights
        risk_total = (
            self.market_saturation_risk
            + self.skill_obsolescence_risk
            + self.competition_risk
        )
        if abs(risk_total - 1.0) > 0.001:
            raise ValueError(
                f"Risk weights must sum to 1.0, got {risk_total:.4f}"
            )


# =====================================================
# Scoring Configuration
# =====================================================

@dataclass
class ScoringConfig:
    """Complete scoring pipeline configuration.
    
    Properties:
        simgr_weights: Main SIMGR component weights
        component_weights: Sub-component weights
        min_score_threshold: Minimum score to include result
        debug_mode: Enable detailed logging and breakdown
        deterministic: Forbid non-deterministic operations
        component_map: Callable map for dynamic component loading
        personalization_enabled: Allow strategy-based weight personalization
    """
    
    simgr_weights: SIMGRWeights = field(default_factory=SIMGRWeights)
    component_weights: ComponentWeights = field(
        default_factory=ComponentWeights
    )
    
    min_score_threshold: float = 0.0
    debug_mode: bool = False
    deterministic: bool = True
    personalization_enabled: bool = True
    
    # Dynamic component loading (no hardcoded imports)
    component_map: Dict[str, Callable] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        """Initialize component map with default components."""
        if not self.component_map:
            self._init_default_components()
    
    def _init_default_components(self) -> None:
        """Lazy-load default components to avoid circular imports."""
        try:
            from backend.scoring.components import study
            from backend.scoring.components import interest
            from backend.scoring.components import market
            from backend.scoring.components import growth
            from backend.scoring.components import risk

            self.component_map = {
                "study": study.score,
                "interest": interest.score,
                "market": market.score,
                "growth": growth.score,
                "risk": risk.score,
            }
        except ImportError as e:
            logger.warning(f"Failed to load default components: {e}")
            self.component_map = {}
    
    def validate(self) -> None:
        """Full configuration validation."""
        if not (0.0 <= self.min_score_threshold <= 1.0):
            raise ValueError(
                f"min_score_threshold must be in [0, 1], "
                f"got {self.min_score_threshold}"
            )
        
        # Weights already validated in __post_init__
        # Component map validation happens at compute time
    
    @classmethod
    def create_custom(
        cls,
        study: float = None,
        interest: float = None,
        market: float = None,
        growth: float = None,
        risk: float = None,
        debug: bool = False,
        deterministic: bool = True,
    ) -> ScoringConfig:
        """Create config with custom SIMGR weights.
        
        If not all weights are specified, distributes remaining weight
        proportionally among unspecified components.
        """
        # Use defaults for unspecified weights
        weights_dict = {
            'study': study if study is not None else 0.25,
            'interest': interest if interest is not None else 0.25,
            'market': market if market is not None else 0.25,
            'growth': growth if growth is not None else 0.15,
            'risk': risk if risk is not None else 0.10,
        }
        
        # Normalize to ensure sum = 1.0
        total = sum(weights_dict.values())
        if total != 1.0 and total > 0:
            scale = 1.0 / total
            weights_dict = {k: v * scale for k, v in weights_dict.items()}
        
        return cls(
            simgr_weights=SIMGRWeights(
                study_score=weights_dict['study'],
                interest_score=weights_dict['interest'],
                market_score=weights_dict['market'],
                growth_score=weights_dict['growth'],
                risk_score=weights_dict['risk'],
            ),
            debug_mode=debug,
            deterministic=deterministic,
        )
    
    def copy_with_weights(
        self,
        study: Optional[float] = None,
        interest: Optional[float] = None,
        market: Optional[float] = None,
        growth: Optional[float] = None,
        risk: Optional[float] = None,
    ) -> ScoringConfig:
        """Create copy with modified SIMGR weights (for personalization).

        All five weights are applied simultaneously.  After modification the
        new weights object is reconstructed via ``SIMGRWeights.__post_init__``
        which validates sum == 1.0 (tolerance 1e-6).  Callers are responsible
        for supplying a complete, valid weight set when any argument is provided.
        """
        from copy import deepcopy

        cfg = deepcopy(self)

        new_study    = study    if study    is not None else cfg.simgr_weights.study_score
        new_interest = interest if interest is not None else cfg.simgr_weights.interest_score
        new_market   = market   if market   is not None else cfg.simgr_weights.market_score
        new_growth   = growth   if growth   is not None else cfg.simgr_weights.growth_score
        new_risk     = risk     if risk     is not None else cfg.simgr_weights.risk_score

        # Rebuild via constructor so __post_init__ re-validates sum == 1.0.
        cfg.simgr_weights = SIMGRWeights(
            study_score=new_study,
            interest_score=new_interest,
            market_score=new_market,
            growth_score=new_growth,
            risk_score=new_risk,
        )
        return cfg

    def reload(self) -> None:
        """Reload configuration from defaults.

        Resets component map and re-initializes defaults.
        Use for hot reload on startup or manual trigger.
        """
        self.component_map = {}
        self._init_default_components()
    
    @classmethod
    def from_trained_weights(
        cls,
        weights_path: Optional[str] = None,
        version: Optional[str] = None,
        debug: bool = False,
    ) -> ScoringConfig:
        """Create config with trained weights from file.
        
        Args:
            weights_path: Direct path to weights.json. Takes precedence.
            version: Load from models/weights/{version}/weights.json.
            debug: Enable debug mode.
            
        Returns:
            ScoringConfig with loaded weights.
            
        GĐ5: All loading paths now go through SIMGRWeights which uses
        registry validation. No bypass for path-based loading.
        """
        if weights_path:
            weights = SIMGRWeights.from_file(weights_path)
        elif version:
            weights = SIMGRWeights.from_version(version)
        else:
            # Load from active weights
            weights = SIMGRWeights.from_file(DEFAULT_WEIGHTS_PATH)
        
        return cls(
            simgr_weights=weights,
            debug_mode=debug,
        )


# =====================================================
# Default Configuration
# =====================================================

# GĐ1: NO FALLBACK - trained weights REQUIRED
def _load_default_config() -> ScoringConfig:
    """Load default config - REQUIRES trained weights.
    
    GĐ1: Silent fallback eliminated. If weights missing, FAIL.
    """
    if not os.path.exists(DEFAULT_WEIGHTS_PATH):
        raise RuntimeError(
            f"[CONFIG_LOAD] FAILED - Trained weights required at: {DEFAULT_WEIGHTS_PATH}\n"
            f"Run the training pipeline to generate weights before starting the service."
        )
    
    try:
        return ScoringConfig.from_trained_weights()
    except Exception as e:
        logger.error(f"[CONFIG_LOAD] FAILED - Cannot load trained weights: {e}")
        raise RuntimeError(
            f"[CONFIG_LOAD] FAILED - Trained weights invalid: {e}\n"
            f"Re-run training or fix weight artifact."
        ) from e


# GĐ1: Lazy load to defer error until actual use
_default_config: Optional[ScoringConfig] = None


def get_default_config() -> ScoringConfig:
    """Get default config - loads on first call."""
    global _default_config
    if _default_config is None:
        _default_config = _load_default_config()
    return _default_config


# Legacy support - will raise if weights missing
# GĐ1 TODO: Migrate consumers to get_default_config()
try:
    DEFAULT_CONFIG = _load_default_config()
except RuntimeError:
    # Allow module import even if weights missing
    # Error will raise when DEFAULT_CONFIG is accessed
    logger.warning(
        "[CONFIG] DEFAULT_CONFIG unavailable - weights not found. "
        "Call get_default_config() or load weights before use."
    )
    DEFAULT_CONFIG = None  # type: ignore
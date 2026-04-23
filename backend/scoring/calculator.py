# backend/scoring/calculator.py
"""
Scoring calculator: Orchestrates SIMGR component computation.

Architecture:
- Loads components dynamically from config.component_map
- Computes all SIMGR scores  
- Applies weights and produces breakdown
- No hardcoded component imports

GĐ4: DELEGATES TO scoring_formula.py FOR ALL FORMULA OPERATIONS.
"""

from __future__ import annotations

from typing import Tuple, Dict, Callable
import logging

from backend.scoring.models import UserProfile, CareerData, ScoreBreakdown
from backend.scoring.config import ScoringConfig
from backend.scoring.normalizer import DataNormalizer
from backend.scoring.scoring_formula import ScoringFormula

logger = logging.getLogger(__name__)


# =====================================================
# Main Calculator
# =====================================================

class SIMGRCalculator:
    """Orchestrates SIMGR scoring pipeline.
    
    Responsibilities:
    - Load components from config
    - Compute all SIMGR scores
    - Apply weights
    - Produce ScoreBreakdown
    """
    
    def __init__(self, config: ScoringConfig):
        """Initialize calculator.
        
        Args:
            config: Scoring configuration (must have component_map)
        """
        if not isinstance(config, ScoringConfig):
            raise TypeError("config must be ScoringConfig")
        
        self.config = config
        self.normalizer = DataNormalizer()
        self._validate_components()
    
    def _validate_components(self) -> None:
        """Validate component map is initialized."""
        if self.config.deterministic and not self.config.component_map:
            # Lazy initialize if not present
            self.config._init_default_components()
        
        # GĐ4: Use canonical component list from ScoringFormula
        required = set(ScoringFormula.COMPONENTS)
        available = set(self.config.component_map.keys())
        
        missing = required - available
        if missing:
            logger.warning(f"Missing components: {missing}")
    
    def calculate(
        self,
        user: UserProfile,
        career: CareerData
    ) -> Tuple[float, Dict]:
        """Calculate total score and breakdown.

        Args:
            user: User profile
            career: Career profile

        Returns:
            Tuple of (total_score, breakdown_dict)
        """
        # Initialize score dict
        simgr_scores: Dict[str, float] = {}
        details: Dict[str, Dict] = {}

        # GĐ4: Use canonical component iteration from ScoringFormula
        for component_name in ScoringFormula.COMPONENTS:
            try:
                result = self._compute_component(
                    component_name,
                    user,
                    career
                )
                simgr_scores[component_name] = result.value
                details[f"{component_name}_details"] = result.meta

            except Exception as e:
                logger.exception(
                    f"Component {component_name} failed for {career.name}: {e}"
                )

                if self.config.debug_mode:
                    raise

                # GĐ4: Use canonical fallback from ScoringFormula
                simgr_scores[component_name] = ScoringFormula.get_default_fallback(component_name)
                details[f"{component_name}_details"] = {
                    "error": str(e),
                    "fallback": True
                }

        # GĐ4: DELEGATE TO CENTRAL FORMULA MODULE
        # NO HARDCODED FORMULA HERE - ScoringFormula is SINGLE SOURCE OF TRUTH
        weights_dict = ScoringFormula.get_weights_from_config(self.config.simgr_weights)
        total_score = ScoringFormula.compute(
            simgr_scores, 
            weights_dict, 
            validate=False,  # Already validated by component computation
            clamp_output=True
        )

        # Build breakdown
        breakdown = {
            f"{comp}_score": round(simgr_scores.get(comp, 0.5), 4)
            for comp in ScoringFormula.COMPONENTS
        }

        if self.config.debug_mode:
            breakdown.update({
                f"{comp}_details": details.get(f"{comp}_details", {})
                for comp in ScoringFormula.COMPONENTS
            })

        return total_score, breakdown
    
    def _compute_component(
        self,
        component_name: str,
        user: UserProfile,
        career: CareerData
    ) -> ScoreResult:
        """Compute single component score.

        Args:
            component_name: Name of component (from SIMGR)
            user: User profile
            career: Career profile

        Returns:
            ScoreResult with value [0,1] and meta dict
        """
        from backend.scoring.models import ScoreResult

        component_fn: Callable = self.config.component_map.get(
            component_name
        )

        if not component_fn:
            logger.warning(f"Component {component_name} not found")
            return ScoreResult(value=0.5, meta={})

        # Call component function
        result = component_fn(career, user, self.config)

        # Validate output
        if not isinstance(result, ScoreResult):
            raise TypeError(
                f"Component {component_name} returned {type(result)}, "
                f"expected ScoreResult"
            )

        # Clamp score to [0, 1]
        result.value = self.normalizer.clamp(float(result.value))

        if not isinstance(result.meta, dict):
            raise TypeError(
                f"Component {component_name} returned non-dict meta: "
                f"{type(result.meta)}"
            )

        return result


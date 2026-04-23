# backend/scoring/scoring.py
"""
SIMGR Scorer: Unified public entry point for career scoring pipeline.

Single responsibility: Convert input dict → pipeline → output dict

Pipeline: SIMGRScorer → Engine → Strategy → Calculator → Components → Normalizer → Output

Attributes enforced:
- Deterministic behavior
- No circular imports
- Absolute imports (backend.scoring.*)
- Unified naming (study, interest, market, growth, risk)
- All scores ∈ [0,1]

GĐ4: DELEGATES TO scoring_formula.py FOR ALL FORMULA OPERATIONS.
"""

from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional

from backend.scoring.engine import RankingEngine, RankingContext
from backend.scoring.models import (
    UserProfile,
    CareerData,
    ScoredCareer,
    ScoreBreakdown,
)
from backend.scoring.config import ScoringConfig, SIMGRWeights, DEFAULT_CONFIG
from backend.scoring.scoring_formula import ScoringFormula
from backend.scoring.security.context import (
    require_execution_context,
    ExecutionContextRegistry,
    ContextRequiredError,
)


logger = logging.getLogger(__name__)


class SIMGRScorer:
    """
    Unified entry point for SIMGR (Study, Interest, Market, Growth, Risk) scoring.

    Responsibilities:
    - Accept input_dict with user and career data
    - Validate and normalize input
    - Orchestrate pipeline (Engine → Strategy → Calculator → Components → Normalizer)
    - Return scored results as output dict

    Pipeline Flow:
    1. SIMGRScorer.score(input_dict) receives raw input
    2. Validates and converts to UserProfile + CareerData models
    3. RankingEngine executes strategy selection and ranking
    4. Strategy delegates to Calculator for SIMGR scoring
    5. Calculator invokes 5 Components (study, interest, market, growth, risk)
    6. Normalizer ensures scores ∈ [0,1]
    7. Results converted to output dict and returned

    Guarantees:
    - Deterministic: same input → same output
    - Immutable: original config never mutated
    - Type-safe: Pydantic v2 validation
    - Explicit: all 5 SIMGR components computed
    """

    def __init__(
        self,
        config: Optional[ScoringConfig] = None,
        strategy: str = "weighted",
        debug: bool = False,
    ):
        """
        Initialize SIMGR Scorer.

        Args:
            config: Optional ScoringConfig (uses DEFAULT_CONFIG if None)
            strategy: Strategy name ("weighted" or "personalized", default="weighted")
            debug: Enable debug logging and raise exceptions (default=False)

        Raises:
            ValueError: If strategy name is invalid
        """
        self._config = config or DEFAULT_CONFIG
        self._strategy = strategy.lower()
        self._debug = debug
        self._engine = RankingEngine(
            default_config=self._config,
            default_strategy=self._strategy,
        )

        if debug:
            logging.basicConfig(level=logging.DEBUG)

    @require_execution_context(require_trace_id=True, log_access=True)
    def score(self, input_dict: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        Score careers for a user (main entry point).
        
        SECURITY: Requires valid ExecutionContext from DecisionController.
        Direct calls will fail with ContextRequiredError.

        Supports two input modes:

        Mode 1: User + Careers (full pipeline)
        {
            "user": {
                "skills": ["python", "java"],
                "interests": ["AI", "Data Science"],
                "education_level": "Master",  # optional
                "ability_score": 0.8,  # optional, [0,1]
                "confidence_score": 0.75,  # optional, [0,1]
            },
            "careers": [
                {
                    "name": "Data Scientist",
                    "required_skills": ["python"],
                    "preferred_skills": ["machine learning"],  # optional
                    "ai_relevance": 0.95,  # optional, [0,1]
                    "growth_rate": 0.85,  # optional, [0,1]
                    "competition": 0.6,  # optional, [0,1]
                    "domain": "AI",  # optional
                },
                ...
            ],
            "strategy": "weighted",  # optional, override default
            "config": {  # optional, override default weights
                "study_score": 0.3,
                "interest_score": 0.25,
                "market_score": 0.25,
                "growth_score": 0.1,
                "risk_score": 0.1,
            }
        }

        Mode 2: Direct component scores (computes weighted sum)
        {
            "study": 0.7,
            "interest": 0.6,
            "market": 0.8,
            "growth": 0.5,
            "risk": 0.2,
            "config": {  # optional, override default weights
                "study_score": 0.3,
                "interest_score": 0.25,
                "market_score": 0.25,
                "growth_score": 0.1,
                "risk_score": 0.1,
            }
        }

        Output dict format:
        {
            "success": true,
            "total_score": 0.6234,
            "breakdown": {
                "study_score": 0.7,
                "interest_score": 0.6,
                "market_score": 0.8,
                "growth_score": 0.5,
                "risk_score": 0.2,
            },
            "config_used": {
                "study_score": 0.25,
                "interest_score": 0.25,
                "market_score": 0.25,
                "growth_score": 0.15,
                "risk_score": 0.1,
            },
            "error": null
        }

        Args:
            input_dict: Input data (see formats above)

        Returns:
            Output dict with score and metadata

        Raises:
            ValueError: If input is invalid and debug=True
            KeyError: If required keys missing and debug=True
        """
        try:
            # Check if direct scores mode (study, interest, market, growth, risk present)
            if self._is_direct_scores_mode(input_dict):
                return self._score_direct_components(input_dict)
            
            # Otherwise use full pipeline mode
            return self._score_full_pipeline(input_dict)

        except (ValueError, KeyError, TypeError) as e:
            logger.exception(f"Error in scoring pipeline: {e}")
            if self._debug:
                raise
            return self._error_response_simple(str(e))

        except Exception as e:
            logger.exception(f"Unexpected error in scoring: {e}")
            if self._debug:
                raise
            return self._error_response_simple("Internal server error")

    def _is_direct_scores_mode(self, input_dict: Dict[str, Any]) -> bool:
        """Check if input contains direct component scores."""
        # GĐ4: Use canonical component list from ScoringFormula
        required_keys = set(ScoringFormula.COMPONENTS)
        input_keys = set(input_dict.keys())
        return required_keys.issubset(input_keys)

    def _score_direct_components(self, input_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Score using direct component scores (Mode 2).

        Args:
            input_dict: Direct scores dict

        Returns:
            Output dict with computed total score

        Raises:
            ValueError: If scores invalid
        """
        try:
            # GĐ4: Use canonical component list from ScoringFormula
            scores_dict = {}
            for comp in ScoringFormula.COMPONENTS:
                scores_dict[comp] = float(input_dict.get(comp, 0))

            # Validate scores are in [0,1]
            if not all(0.0 <= s <= 1.0 for s in scores_dict.values()):
                raise ValueError("All scores must be in [0,1]")

            # Build config override if provided
            config = self._config
            config_override_dict = input_dict.get("config")
            if config_override_dict:
                config = self._build_config(config_override_dict)

            # GĐ4: DELEGATE TO CENTRAL FORMULA MODULE
            # NO HARDCODED FORMULA HERE - ScoringFormula is SINGLE SOURCE OF TRUTH
            weights_dict = ScoringFormula.get_weights_from_config(config.simgr_weights)
            total_score = ScoringFormula.compute(
                scores_dict,
                weights_dict,
                validate=True,
                clamp_output=True
            )

            return {
                "success": True,
                "total_score": round(total_score, 4),
                "breakdown": {
                    f"{comp}_score": round(scores_dict[comp], 4)
                    for comp in ScoringFormula.COMPONENTS
                },
                "contributions": {
                    comp: {
                        "score": round(scores_dict[comp], 4),
                        "weight": round(weights_dict[comp], 4),
                        "sign": ScoringFormula.SIGN[comp],
                        "weighted_contribution": round(
                            ScoringFormula.SIGN[comp] * weights_dict[comp] * scores_dict[comp], 4
                        ),
                        "role": "penalty" if ScoringFormula.SIGN[comp] < 0 else "boost",
                    }
                    for comp in ScoringFormula.COMPONENTS
                },
                "config_used": {
                    ScoringFormula.WEIGHT_KEYS[comp]: getattr(config.simgr_weights, ScoringFormula.WEIGHT_KEYS[comp])
                    for comp in ScoringFormula.COMPONENTS
                },
                "formula_version": ScoringFormula.VERSION,
                "error": None,
            }

        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid direct scores: {e}") from e

    def _score_full_pipeline(self, input_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Score using full pipeline (user + careers) (Mode 1).

        Args:
            input_dict: Full pipeline input

        Returns:
            Output dict with ranked careers

        Raises:
            ValueError: If input invalid
        """
        # Extract and validate input
        user_dict = input_dict.get("user", {})
        careers_list = input_dict.get("careers", [])
        override_strategy = input_dict.get("strategy", self._strategy)
        config_override_dict = input_dict.get("config")

        # Build config override if provided
        config_override = None
        if config_override_dict:
            config_override = self._build_config(config_override_dict)

        # Convert user_dict to UserProfile
        user_profile = self._build_user_profile(user_dict)

        # Convert careers list to CareerData objects
        career_data_list = self._build_careers(careers_list)

        # Validate input
        if not career_data_list:
            logger.warning("No valid careers provided")
            return self._error_response("No valid careers provided", 0)

        # Execute ranking pipeline
        context = RankingContext()
        results = self._engine.rank(
            user=user_profile,
            careers=career_data_list,
            config_override=config_override,
            strategy_name=override_strategy,
            context=context,
        )

        # Convert results to output dict
        return self._build_output(
            results,
            len(career_data_list),
            config_override or self._config,
            context,
        )

    def _build_user_profile(self, user_dict: Dict[str, Any]) -> UserProfile:
        """
        Convert user_dict to UserProfile.

        Args:
            user_dict: Raw user data

        Returns:
            UserProfile instance

        Raises:
            ValueError: If required fields missing or invalid
        """
        try:
            skills = user_dict.get("skills", [])
            interests = user_dict.get("interests", [])
            education_level = user_dict.get("education_level", "Bachelor")
            ability_score = user_dict.get("ability_score", 0.5)
            confidence_score = user_dict.get("confidence_score", 0.5)

            return UserProfile(
                skills=skills,
                interests=interests,
                education_level=education_level,
                ability_score=float(ability_score),
                confidence_score=float(confidence_score),
            )
        except Exception as e:
            raise ValueError(f"Invalid user profile: {e}") from e

    def _build_careers(self, careers_list: List[Dict[str, Any]]) -> List[CareerData]:
        """
        Convert careers list to CareerData objects.

        Args:
            careers_list: List of career dicts

        Returns:
            List of CareerData instances

        Raises:
            ValueError: If any career is invalid
        """
        if not isinstance(careers_list, list):
            raise ValueError("careers must be a list")

        results = []
        for career_dict in careers_list:
            try:
                name = career_dict.get("name", "unknown")
                required_skills = career_dict.get("required_skills", [])
                preferred_skills = career_dict.get("preferred_skills", [])
                domain = career_dict.get("domain", "general")
                ai_relevance = career_dict.get("ai_relevance", 0.5)
                growth_rate = career_dict.get("growth_rate", 0.5)
                competition = career_dict.get("competition", 0.5)

                career = CareerData(
                    name=name,
                    required_skills=required_skills,
                    preferred_skills=preferred_skills,
                    domain=domain,
                    ai_relevance=float(ai_relevance),
                    growth_rate=float(growth_rate),
                    competition=float(competition),
                )
                results.append(career)
            except Exception as e:
                logger.warning(f"Skipping invalid career {career_dict.get('name')}: {e}")
                continue

        return results

    def _build_config(self, config_dict: Dict[str, Any]) -> ScoringConfig:
        """
        Convert config_dict to ScoringConfig.

        Args:
            config_dict: Raw config data

        Returns:
            ScoringConfig instance

        Raises:
            ValueError: If weights invalid
        """
        try:
            study = config_dict.get("study_score", 0.25)
            interest = config_dict.get("interest_score", 0.25)
            market = config_dict.get("market_score", 0.25)
            growth = config_dict.get("growth_score", 0.15)
            risk = config_dict.get("risk_score", 0.10)

            return ScoringConfig.create_custom(
                study=float(study),
                interest=float(interest),
                market=float(market),
                growth=float(growth),
                risk=float(risk),
                debug=self._debug,
            )
        except Exception as e:
            raise ValueError(f"Invalid config: {e}") from e

    def _build_output(
        self,
        results: List[ScoredCareer],
        total_evaluated: int,
        config: ScoringConfig,
        context: RankingContext,
    ) -> Dict[str, Any]:
        """
        Convert ranking results to output dict.

        Args:
            results: Ranked careers
            total_evaluated: Total career count
            config: Config used
            context: Execution context

        Returns:
            Output dict
        """
        weights_dict = ScoringFormula.get_weights_from_config(config.simgr_weights)
        ranked_careers = []
        for scored_career in results:
            bd = scored_career.breakdown
            scores_dict = {
                "study": bd.study_score,
                "interest": bd.interest_score,
                "market": bd.market_score,
                "growth": bd.growth_score,
                "risk": bd.risk_score,
            }
            ranked_careers.append({
                "rank": scored_career.rank,
                "name": scored_career.career_name,
                "total_score": round(scored_career.total_score, 4),
                "breakdown": {
                    "study_score": round(bd.study_score, 4),
                    "interest_score": round(bd.interest_score, 4),
                    "market_score": round(bd.market_score, 4),
                    "growth_score": round(bd.growth_score, 4),
                    "risk_score": round(bd.risk_score, 4),
                },
                "contributions": {
                    comp: {
                        "score": round(scores_dict[comp], 4),
                        "weight": round(weights_dict[comp], 4),
                        "sign": ScoringFormula.SIGN[comp],
                        "weighted_contribution": round(
                            ScoringFormula.SIGN[comp] * weights_dict[comp] * scores_dict[comp], 4
                        ),
                        "role": "penalty" if ScoringFormula.SIGN[comp] < 0 else "boost",
                    }
                    for comp in ScoringFormula.COMPONENTS
                },
            })

        return {
            "success": True,
            "total_evaluated": total_evaluated,
            "ranked_careers": ranked_careers,
            "config_used": {
                "study_score": config.simgr_weights.study_score,
                "interest_score": config.simgr_weights.interest_score,
                "market_score": config.simgr_weights.market_score,
                "growth_score": config.simgr_weights.growth_score,
                "risk_score": config.simgr_weights.risk_score,
            },
            "formula_version": ScoringFormula.VERSION,
            "error": None,
        }

    def _error_response(self, error_msg: str, total_evaluated: int) -> Dict[str, Any]:
        """
        Build error response dict for full pipeline.

        Args:
            error_msg: Error message
            total_evaluated: Total careers evaluated before error

        Returns:
            Error response dict
        """
        return {
            "success": False,
            "total_evaluated": total_evaluated,
            "ranked_careers": [],
            "config_used": self._config.simgr_weights.to_dict(),
            "error": error_msg,
        }

    def _error_response_simple(self, error_msg: str) -> Dict[str, Any]:
        """
        Build error response dict for direct scores mode.

        Args:
            error_msg: Error message

        Returns:
            Error response dict
        """
        return {
            "success": False,
            "total_score": 0.0,
            "breakdown": {
                "study_score": 0.0,
                "interest_score": 0.0,
                "market_score": 0.0,
                "growth_score": 0.0,
                "risk_score": 0.0,
            },
            "config_used": self._config.simgr_weights.to_dict(),
            "error": error_msg,
        }

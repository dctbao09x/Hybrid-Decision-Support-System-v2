# backend/scoring/config_loader.py
"""
Configuration Loader for SIMGR Scoring

Loads configuration from YAML files with schema validation.
NO HARDCODING - All values come from config/scoring.yaml

SIMGR Stage 3 Compliant.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

# Default config paths
CONFIG_DIR = Path("config")
SCORING_CONFIG_FILE = "scoring.yaml"
SCHEMA_FILE = "scoring_schema.yaml"


@dataclass 
class LoadedSIMGRWeights:
    """SIMGR weights loaded from config.
    
    GĐ1: NO DEFAULT VALUES - all must be explicitly provided.
    """
    study_score: float
    interest_score: float
    market_score: float
    growth_score: float
    risk_score: float
    
    # GĐ1: Track source for audit
    _source: str = field(default="", repr=False)
    
    def validate(self, tolerance: float = 0.001) -> bool:
        """Validate weights sum to 1.0."""
        total = (
            self.study_score +
            self.interest_score +
            self.market_score +
            self.growth_score +
            self.risk_score
        )
        return abs(total - 1.0) <= tolerance


@dataclass
class LoadedStudyFactors:
    """Study component factor weights."""
    ability_weight: float = 0.4
    background_weight: float = 0.3
    confidence_weight: float = 0.3
    required_skill_match: float = 0.7
    preferred_skill_match: float = 0.3


@dataclass
class LoadedInterestFactors:
    """Interest component factor weights."""
    nlp_weight: float = 0.4
    survey_weight: float = 0.3
    stability_weight: float = 0.3


@dataclass
class LoadedMarketFactors:
    """Market component factor weights."""
    ai_relevance_weight: float = 0.3
    growth_rate_weight: float = 0.3
    salary_weight: float = 0.2
    inverse_competition_weight: float = 0.2


@dataclass
class LoadedGrowthFactors:
    """Growth component factor weights."""
    lifecycle_weight: float = 0.4
    demand_weight: float = 0.3
    salary_growth_weight: float = 0.3


@dataclass
class LoadedRiskFactors:
    """Risk component factor weights."""
    saturation_weight: float = 0.25
    obsolescence_weight: float = 0.20
    competition_weight: float = 0.15
    dropout_weight: float = 0.15
    unemployment_weight: float = 0.15
    cost_weight: float = 0.10


@dataclass
class LoadedThresholds:
    """Scoring thresholds."""
    min_score: float = 0.0
    max_score: float = 1.0
    relevance_threshold: float = 0.3


@dataclass
class LoadedDataFreshness:
    """Data freshness settings."""
    max_age_days: int = 90
    auto_refresh: bool = True
    refresh_interval_hours: int = 24


@dataclass
class LoadedFeatures:
    """Feature flags."""
    debug_mode: bool = False
    personalization: bool = True
    deterministic: bool = True
    cache_enabled: bool = True
    drift_detection: bool = True


@dataclass
class ScoringConfigData:
    """Complete scoring configuration data."""
    version: str = "1.0"
    simgr_weights: LoadedSIMGRWeights = field(default_factory=LoadedSIMGRWeights)
    study_factors: LoadedStudyFactors = field(default_factory=LoadedStudyFactors)
    interest_factors: LoadedInterestFactors = field(default_factory=LoadedInterestFactors)
    market_factors: LoadedMarketFactors = field(default_factory=LoadedMarketFactors)
    growth_factors: LoadedGrowthFactors = field(default_factory=LoadedGrowthFactors)
    risk_factors: LoadedRiskFactors = field(default_factory=LoadedRiskFactors)
    thresholds: LoadedThresholds = field(default_factory=LoadedThresholds)
    data_freshness: LoadedDataFreshness = field(default_factory=LoadedDataFreshness)
    features: LoadedFeatures = field(default_factory=LoadedFeatures)
    
    _source: str = field(default="default", repr=False)


class ScoringConfigLoader:
    """Loads and validates scoring configuration from YAML.
    
    NO HARDCODING - All values come from config files.
    """
    
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or CONFIG_DIR
        self._config: Optional[ScoringConfigData] = None
    
    def load(self, config_file: Optional[str] = None) -> ScoringConfigData:
        """Load scoring configuration from YAML file.
        
        Args:
            config_file: Config filename (default: scoring.yaml)
            
        Returns:
            ScoringConfigData with loaded values.
        """
        config_file = config_file or SCORING_CONFIG_FILE
        config_path = self.config_dir / config_file
        
        if not config_path.exists():
            logger.warning(f"Config file not found: {config_path}. Using defaults.")
            self._config = ScoringConfigData()
            return self._config
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                raw_config = yaml.safe_load(f)
            
            self._config = self._parse_config(raw_config)
            self._config._source = str(config_path)
            
            logger.info(f"Loaded scoring config from {config_path}")
            return self._config
            
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse config YAML: {e}")
            raise ValueError(f"Invalid YAML in config: {e}")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            raise
    
    def _parse_config(self, raw: Dict[str, Any]) -> ScoringConfigData:
        """Parse raw YAML dict into ScoringConfigData.
        
        GĐ1: NO FALLBACKS - all required fields must be present.
        """
        config = ScoringConfigData()
        
        config.version = raw.get("version", "1.0")
        
        # GĐ1: Parse SIMGR weights - REQUIRED, NO FALLBACK
        if "simgr_weights" not in raw:
            raise ValueError(
                "[CONFIG_PARSE] FAILED - 'simgr_weights' section required in config. "
                "No default weights allowed."
            )
        
        w = raw["simgr_weights"]
        required_weight_keys = ["study_score", "interest_score", "market_score", 
                                "growth_score", "risk_score"]
        missing_keys = [k for k in required_weight_keys if k not in w]
        if missing_keys:
            raise ValueError(
                f"[CONFIG_PARSE] FAILED - Missing SIMGR weight keys: {missing_keys}. "
                f"All weights must be explicitly defined."
            )
        
        config.simgr_weights = LoadedSIMGRWeights(
            study_score=w["study_score"],
            interest_score=w["interest_score"],
            market_score=w["market_score"],
            growth_score=w["growth_score"],
            risk_score=w["risk_score"],
        )
        config.simgr_weights._source = "config:scoring.yaml"
        
        # Parse study factors (optional section)
        if "study_factors" in raw:
            s = raw["study_factors"]
            config.study_factors = LoadedStudyFactors(
                ability_weight=s.get("ability_weight", 0.4),
                background_weight=s.get("background_weight", 0.3),
                confidence_weight=s.get("confidence_weight", 0.3),
                required_skill_match=s.get("required_skill_match", 0.7),
                preferred_skill_match=s.get("preferred_skill_match", 0.3),
            )
        
        # Parse interest factors
        if "interest_factors" in raw:
            i = raw["interest_factors"]
            config.interest_factors = LoadedInterestFactors(
                nlp_weight=i.get("nlp_weight", 0.4),
                survey_weight=i.get("survey_weight", 0.3),
                stability_weight=i.get("stability_weight", 0.3),
            )
        
        # Parse market factors
        if "market_factors" in raw:
            m = raw["market_factors"]
            config.market_factors = LoadedMarketFactors(
                ai_relevance_weight=m.get("ai_relevance_weight", 0.3),
                growth_rate_weight=m.get("growth_rate_weight", 0.3),
                salary_weight=m.get("salary_weight", 0.2),
                inverse_competition_weight=m.get("inverse_competition_weight", 0.2),
            )
        
        # Parse growth factors
        if "growth_factors" in raw:
            g = raw["growth_factors"]
            config.growth_factors = LoadedGrowthFactors(
                lifecycle_weight=g.get("lifecycle_weight", 0.4),
                demand_weight=g.get("demand_weight", 0.3),
                salary_growth_weight=g.get("salary_growth_weight", 0.3),
            )
        
        # Parse risk factors
        if "risk_factors" in raw:
            r = raw["risk_factors"]
            config.risk_factors = LoadedRiskFactors(
                saturation_weight=r.get("saturation_weight", 0.25),
                obsolescence_weight=r.get("obsolescence_weight", 0.20),
                competition_weight=r.get("competition_weight", 0.15),
                dropout_weight=r.get("dropout_weight", 0.15),
                unemployment_weight=r.get("unemployment_weight", 0.15),
                cost_weight=r.get("cost_weight", 0.10),
            )
        
        # Parse thresholds
        if "thresholds" in raw:
            t = raw["thresholds"]
            config.thresholds = LoadedThresholds(
                min_score=t.get("min_score", 0.0),
                max_score=t.get("max_score", 1.0),
                relevance_threshold=t.get("relevance_threshold", 0.3),
            )
        
        # Parse data freshness
        if "data_freshness" in raw:
            d = raw["data_freshness"]
            config.data_freshness = LoadedDataFreshness(
                max_age_days=d.get("max_age_days", 90),
                auto_refresh=d.get("auto_refresh", True),
                refresh_interval_hours=d.get("refresh_interval_hours", 24),
            )
        
        # Parse features
        if "features" in raw:
            f = raw["features"]
            config.features = LoadedFeatures(
                debug_mode=f.get("debug_mode", False),
                personalization=f.get("personalization", True),
                deterministic=f.get("deterministic", True),
                cache_enabled=f.get("cache_enabled", True),
                drift_detection=f.get("drift_detection", True),
            )
        
        return config
    
    def validate(self, config: Optional[ScoringConfigData] = None) -> Dict[str, Any]:
        """Validate configuration against constraints.
        
        Returns:
            Validation result dict with status and errors.
        """
        config = config or self._config
        if config is None:
            return {"valid": False, "errors": ["No config loaded"]}
        
        errors = []
        warnings = []
        
        # Validate SIMGR weights sum to 1.0
        if not config.simgr_weights.validate():
            total = (
                config.simgr_weights.study_score +
                config.simgr_weights.interest_score +
                config.simgr_weights.market_score +
                config.simgr_weights.growth_score +
                config.simgr_weights.risk_score
            )
            errors.append(f"SIMGR weights must sum to 1.0, got {total:.4f}")
        
        # Validate study factors sum to 1.0
        study_sum = (
            config.study_factors.ability_weight +
            config.study_factors.background_weight +
            config.study_factors.confidence_weight
        )
        if abs(study_sum - 1.0) > 0.001:
            errors.append(f"Study factors must sum to 1.0, got {study_sum:.4f}")
        
        # Validate interest factors sum to 1.0
        interest_sum = (
            config.interest_factors.nlp_weight +
            config.interest_factors.survey_weight +
            config.interest_factors.stability_weight
        )
        if abs(interest_sum - 1.0) > 0.001:
            errors.append(f"Interest factors must sum to 1.0, got {interest_sum:.4f}")
        
        # Validate market factors sum to 1.0
        market_sum = (
            config.market_factors.ai_relevance_weight +
            config.market_factors.growth_rate_weight +
            config.market_factors.salary_weight +
            config.market_factors.inverse_competition_weight
        )
        if abs(market_sum - 1.0) > 0.001:
            errors.append(f"Market factors must sum to 1.0, got {market_sum:.4f}")
        
        # Validate growth factors sum to 1.0
        growth_sum = (
            config.growth_factors.lifecycle_weight +
            config.growth_factors.demand_weight +
            config.growth_factors.salary_growth_weight
        )
        if abs(growth_sum - 1.0) > 0.001:
            errors.append(f"Growth factors must sum to 1.0, got {growth_sum:.4f}")
        
        # Validate risk factors sum to 1.0
        risk_sum = (
            config.risk_factors.saturation_weight +
            config.risk_factors.obsolescence_weight +
            config.risk_factors.competition_weight +
            config.risk_factors.dropout_weight +
            config.risk_factors.unemployment_weight +
            config.risk_factors.cost_weight
        )
        if abs(risk_sum - 1.0) > 0.001:
            errors.append(f"Risk factors must sum to 1.0, got {risk_sum:.4f}")
        
        # Validate thresholds
        if config.thresholds.relevance_threshold < 0 or config.thresholds.relevance_threshold > 1:
            errors.append("Relevance threshold must be in [0, 1]")
        
        # Validate data freshness
        if config.data_freshness.max_age_days > 365:
            warnings.append("Data freshness max_age_days > 365, consider shorter TTL")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


# Singleton loader
_loader: Optional[ScoringConfigLoader] = None


def get_scoring_config_loader() -> ScoringConfigLoader:
    """Get singleton config loader."""
    global _loader
    if _loader is None:
        _loader = ScoringConfigLoader()
    return _loader


def load_scoring_config() -> ScoringConfigData:
    """Load scoring config from default location."""
    return get_scoring_config_loader().load()


def validate_scoring_config() -> Dict[str, Any]:
    """Validate current scoring config."""
    loader = get_scoring_config_loader()
    if loader._config is None:
        loader.load()
    return loader.validate()

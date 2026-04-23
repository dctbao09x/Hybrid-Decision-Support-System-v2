# backend/risk/registry.py
"""
Risk Registry - Dynamic Configuration Management

Loads and manages risk configuration from config.yaml.
Supports:
- Hot reload
- Versioning
- Validation
- Default fallbacks
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

# Default config path
DEFAULT_CONFIG_PATH = "backend/risk/config.yaml"


@dataclass
class RiskThresholds:
    """Risk threshold configuration."""
    dropout_high: float = 0.3
    dropout_medium: float = 0.15
    unemployment_high: float = 0.15
    unemployment_medium: float = 0.08
    cost_high: float = 50000.0
    cost_medium: float = 25000.0
    saturation_high: float = 0.7
    obsolescence_high: float = 0.6


@dataclass
class RiskWeights:
    """Risk component weights (must sum to 1.0)."""
    market_saturation: float = 0.25
    skill_obsolescence: float = 0.20
    competition: float = 0.15
    dropout: float = 0.15
    unemployment: float = 0.15
    cost: float = 0.10
    
    def __post_init__(self):
        """Validate weights sum to 1.0."""
        total = (
            self.market_saturation +
            self.skill_obsolescence +
            self.competition +
            self.dropout +
            self.unemployment +
            self.cost
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Risk weights must sum to 1.0, got {total:.4f}")
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "market_saturation": self.market_saturation,
            "skill_obsolescence": self.skill_obsolescence,
            "competition": self.competition,
            "dropout": self.dropout,
            "unemployment": self.unemployment,
            "cost": self.cost,
        }


@dataclass
class PenaltyConfig:
    """Penalty calculation configuration."""
    base_rate: float = 0.1
    scaling_factor: float = 1.5
    max_penalty: float = 0.95
    min_penalty: float = 0.0


@dataclass
class ModelConfig:
    """Risk model configuration."""
    dropout_education_weight: float = 0.3
    dropout_history_weight: float = 0.4
    dropout_engagement_weight: float = 0.3
    
    unemployment_sector_weight: float = 0.4
    unemployment_region_weight: float = 0.3
    unemployment_trend_weight: float = 0.3
    
    cost_education_weight: float = 0.5
    cost_time_weight: float = 0.3
    cost_opportunity_weight: float = 0.2


@dataclass
class RiskConfig:
    """Complete risk module configuration."""
    version: str = "1.0"
    thresholds: RiskThresholds = field(default_factory=RiskThresholds)
    weights: RiskWeights = field(default_factory=RiskWeights)
    penalty: PenaltyConfig = field(default_factory=PenaltyConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    loaded_at: Optional[datetime] = None
    source: str = "default"


class RiskRegistry:
    """Central registry for risk configuration.
    
    Features:
    - Load from YAML config
    - Hot reload support
    - Validation
    - Default fallbacks
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self._config: Optional[RiskConfig] = None
        self._raw_yaml: Dict[str, Any] = {}
        self._loaded = False
        self._last_modified: Optional[float] = None
    
    def load_config(self, force_reload: bool = False) -> RiskConfig:
        """Load configuration from YAML file.
        
        Args:
            force_reload: Force reload even if already loaded.
            
        Returns:
            RiskConfig instance.
        """
        if self._loaded and not force_reload:
            # Check for file changes (hot reload)
            if not self._check_modified():
                return self._config
        
        path = Path(self.config_path)
        
        if not path.exists():
            logger.warning(
                f"Risk config not found: {self.config_path}, using defaults"
            )
            self._config = RiskConfig(source="default")
            self._loaded = True
            return self._config
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                self._raw_yaml = yaml.safe_load(f)
            
            self._config = self._parse_config(self._raw_yaml)
            self._config.loaded_at = datetime.now()
            self._config.source = str(path)
            self._last_modified = path.stat().st_mtime
            self._loaded = True
            
            logger.info(f"Loaded risk config from {path}")
            return self._config
            
        except Exception as e:
            logger.error(f"Failed to load risk config: {e}")
            self._config = RiskConfig(source="default_fallback")
            self._loaded = True
            return self._config
    
    def _parse_config(self, data: Dict[str, Any]) -> RiskConfig:
        """Parse YAML data into RiskConfig."""
        # Parse thresholds
        thresh_data = data.get("thresholds", {})
        thresholds = RiskThresholds(
            dropout_high=thresh_data.get("dropout_high", 0.3),
            dropout_medium=thresh_data.get("dropout_medium", 0.15),
            unemployment_high=thresh_data.get("unemployment_high", 0.15),
            unemployment_medium=thresh_data.get("unemployment_medium", 0.08),
            cost_high=thresh_data.get("cost_high", 50000.0),
            cost_medium=thresh_data.get("cost_medium", 25000.0),
            saturation_high=thresh_data.get("saturation_high", 0.7),
            obsolescence_high=thresh_data.get("obsolescence_high", 0.6),
        )
        
        # Parse weights
        weight_data = data.get("weights", {})
        weights = RiskWeights(
            market_saturation=weight_data.get("market_saturation", 0.25),
            skill_obsolescence=weight_data.get("skill_obsolescence", 0.20),
            competition=weight_data.get("competition", 0.15),
            dropout=weight_data.get("dropout", 0.15),
            unemployment=weight_data.get("unemployment", 0.15),
            cost=weight_data.get("cost", 0.10),
        )
        
        # Parse penalty config
        penalty_data = data.get("penalty", {})
        penalty = PenaltyConfig(
            base_rate=penalty_data.get("base_rate", 0.1),
            scaling_factor=penalty_data.get("scaling_factor", 1.5),
            max_penalty=penalty_data.get("max_penalty", 0.95),
            min_penalty=penalty_data.get("min_penalty", 0.0),
        )
        
        # Parse model config
        model_data = data.get("model", {})
        dropout_cfg = model_data.get("dropout", {})
        unemp_cfg = model_data.get("unemployment", {})
        cost_cfg = model_data.get("cost", {})
        
        model = ModelConfig(
            dropout_education_weight=dropout_cfg.get("education_weight", 0.3),
            dropout_history_weight=dropout_cfg.get("history_weight", 0.4),
            dropout_engagement_weight=dropout_cfg.get("engagement_weight", 0.3),
            unemployment_sector_weight=unemp_cfg.get("sector_weight", 0.4),
            unemployment_region_weight=unemp_cfg.get("region_weight", 0.3),
            unemployment_trend_weight=unemp_cfg.get("trend_weight", 0.3),
            cost_education_weight=cost_cfg.get("education_weight", 0.5),
            cost_time_weight=cost_cfg.get("time_weight", 0.3),
            cost_opportunity_weight=cost_cfg.get("opportunity_weight", 0.2),
        )
        
        return RiskConfig(
            version=data.get("version", "1.0"),
            thresholds=thresholds,
            weights=weights,
            penalty=penalty,
            model=model,
        )
    
    def _check_modified(self) -> bool:
        """Check if config file was modified since last load."""
        if self._last_modified is None:
            return True
        
        path = Path(self.config_path)
        if not path.exists():
            return False
        
        current_mtime = path.stat().st_mtime
        if current_mtime > self._last_modified:
            logger.info("Config file modified, triggering reload")
            return True
        
        return False
    
    def get_weights(self) -> RiskWeights:
        """Get risk component weights."""
        if not self._loaded:
            self.load_config()
        return self._config.weights
    
    def get_thresholds(self) -> RiskThresholds:
        """Get risk thresholds."""
        if not self._loaded:
            self.load_config()
        return self._config.thresholds
    
    def get_penalty_config(self) -> PenaltyConfig:
        """Get penalty configuration."""
        if not self._loaded:
            self.load_config()
        return self._config.penalty
    
    def get_model_config(self) -> ModelConfig:
        """Get model configuration."""
        if not self._loaded:
            self.load_config()
        return self._config.model
    
    @property
    def config(self) -> RiskConfig:
        """Get full configuration."""
        if not self._loaded:
            self.load_config()
        return self._config
    
    def reload(self) -> RiskConfig:
        """Force reload configuration."""
        return self.load_config(force_reload=True)
    
    def validate(self) -> bool:
        """Validate current configuration."""
        if not self._loaded:
            self.load_config()
        
        try:
            # Validate weight sum
            weights = self._config.weights
            total = (
                weights.market_saturation +
                weights.skill_obsolescence +
                weights.competition +
                weights.dropout +
                weights.unemployment +
                weights.cost
            )
            if abs(total - 1.0) > 0.001:
                logger.error(f"Weight sum invalid: {total}")
                return False
            
            # Validate thresholds are in range
            thresholds = self._config.thresholds
            if not (0 < thresholds.dropout_high <= 1):
                logger.error("Invalid dropout_high threshold")
                return False
            
            # Validate penalty config
            penalty = self._config.penalty
            if penalty.max_penalty <= penalty.min_penalty:
                logger.error("Invalid penalty range")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            return False


# Singleton instance
_registry: Optional[RiskRegistry] = None


def get_registry() -> RiskRegistry:
    """Get singleton registry instance."""
    global _registry
    if _registry is None:
        _registry = RiskRegistry()
    return _registry

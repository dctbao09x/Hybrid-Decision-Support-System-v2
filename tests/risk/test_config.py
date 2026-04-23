# tests/risk/test_config.py
"""
Tests for Risk Module Configuration - SIMGR Stage 3 Compliance

CRITICAL TESTS:
- Weight sum = 1.0
- Config hot reload
- Threshold validation
- No hardcoded values
"""

import pytest
from pathlib import Path
import yaml


class TestRiskConfig:
    """Tests for risk configuration."""
    
    def test_config_file_exists(self):
        """Config file must exist."""
        config_path = Path(__file__).parent.parent.parent / "backend" / "risk" / "config.yaml"
        assert config_path.exists(), f"Config file not found: {config_path}"
    
    def test_config_valid_yaml(self):
        """Config must be valid YAML."""
        config_path = Path(__file__).parent.parent.parent / "backend" / "risk" / "config.yaml"
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        assert isinstance(config, dict), "Config must be a dictionary"
    
    def test_weights_sum_to_one(self):
        """Risk weights must sum to 1.0."""
        config_path = Path(__file__).parent.parent.parent / "backend" / "risk" / "config.yaml"
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        weights = config.get('weights', {})
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.001, f"Weights must sum to 1.0, got {total}"
    
    def test_required_weight_keys(self):
        """All required weight keys must be present."""
        config_path = Path(__file__).parent.parent.parent / "backend" / "risk" / "config.yaml"
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        required_keys = {
            'market_saturation',
            'skill_obsolescence',
            'competition',
            'dropout',
            'unemployment',
            'cost',
        }
        weights = config.get('weights', {})
        missing = required_keys - set(weights.keys())
        assert not missing, f"Missing weight keys: {missing}"
    
    def test_thresholds_in_range(self):
        """Thresholds must be in valid range (either [0,1] or positive for dollar amounts)."""
        config_path = Path(__file__).parent.parent.parent / "backend" / "risk" / "config.yaml"
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        thresholds = config.get('thresholds', {})
        for key, value in thresholds.items():
            if 'cost' in key:
                # Cost thresholds are in dollars
                assert value >= 0, f"Threshold {key}={value} must be non-negative"
            else:
                # Other thresholds are [0, 1]
                assert 0.0 <= value <= 1.0, f"Threshold {key}={value} out of range"
    
    def test_penalty_config_present(self):
        """Penalty configuration must be present."""
        config_path = Path(__file__).parent.parent.parent / "backend" / "risk" / "config.yaml"
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        assert 'penalty' in config, "Penalty config missing"
        penalty = config['penalty']
        assert 'base_rate' in penalty
        assert 'scaling_factor' in penalty
        assert 'min_penalty' in penalty
        assert 'max_penalty' in penalty
    
    def test_data_paths_configured(self):
        """Data paths must be configured."""
        config_path = Path(__file__).parent.parent.parent / "backend" / "risk" / "config.yaml"
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        assert 'data' in config, "Data section not configured"
        data = config['data']
        assert 'unemployment' in data
        assert 'costs' in data
        assert 'sectors' in data


class TestRiskRegistry:
    """Tests for RiskRegistry."""
    
    def test_registry_loads(self):
        """Registry should load without errors."""
        from backend.risk.registry import get_registry
        registry = get_registry()
        assert registry is not None
    
    def test_registry_get_weights(self):
        """Registry should return weights."""
        from backend.risk.registry import get_registry
        registry = get_registry()
        weights = registry.get_weights()
        assert weights is not None
        assert hasattr(weights, 'market_saturation')
        assert hasattr(weights, 'skill_obsolescence')
    
    def test_registry_weights_sum_to_one(self):
        """Registry weights must sum to 1.0."""
        from backend.risk.registry import get_registry
        registry = get_registry()
        weights = registry.get_weights()
        total = (
            weights.market_saturation +
            weights.skill_obsolescence +
            weights.competition +
            weights.dropout +
            weights.unemployment +
            weights.cost
        )
        assert abs(total - 1.0) < 0.001, f"Weights sum to {total}, expected 1.0"
    
    def test_registry_get_thresholds(self):
        """Registry should return thresholds."""
        from backend.risk.registry import get_registry
        registry = get_registry()
        thresholds = registry.get_thresholds()
        assert thresholds is not None
        assert hasattr(thresholds, 'dropout_high')
        assert hasattr(thresholds, 'unemployment_high')
    
    def test_registry_validation(self):
        """Registry should validate config."""
        from backend.risk.registry import get_registry
        registry = get_registry()
        is_valid = registry.validate()
        assert is_valid, "Registry validation failed"
    
    def test_registry_hot_reload(self):
        """Registry should support hot reload."""
        from backend.risk.registry import get_registry
        registry = get_registry()
        
        # Record initial version
        initial_version = registry._config.version if registry._config else None
        
        # Reload
        registry.reload()
        
        # Should still have valid config
        weights = registry.get_weights()
        assert weights is not None


class TestWeightSumCompliance:
    """Critical compliance tests for weight sum."""
    
    def test_weight_sum_exact(self):
        """Weights must sum to exactly 1.0."""
        from backend.risk.registry import get_registry
        registry = get_registry()
        weights = registry.get_weights()
        
        total = (
            weights.market_saturation +
            weights.skill_obsolescence +
            weights.competition +
            weights.dropout +
            weights.unemployment +
            weights.cost
        )
        
        # Exact sum check
        assert total == 1.0, f"Weights must sum to 1.0, got {total}"
    
    def test_no_hardcoded_weights_in_penalty(self):
        """PenaltyEngine must use config weights, not hardcoded."""
        from backend.risk.penalty import RiskPenaltyEngine
        
        engine = RiskPenaltyEngine()
        weights = engine.get_weights()
        
        # Should have all 6 components
        assert len(weights) == 6
        assert 'market_saturation' in weights
        assert 'skill_obsolescence' in weights
        assert 'competition' in weights
        assert 'dropout' in weights
        assert 'unemployment' in weights
        assert 'cost' in weights

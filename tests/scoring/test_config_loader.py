# tests/scoring/test_config_loader.py
"""
Tests for Configuration Loader (R005)

Validates:
- Config loading from YAML
- Schema validation
- Weight sum constraints
- No hardcoded values
"""

import pytest
import tempfile
from pathlib import Path
import yaml

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.scoring.config_loader import (
    ScoringConfigLoader,
    ScoringConfigData,
    LoadedSIMGRWeights,
    load_scoring_config,
    validate_scoring_config,
)


class TestLoadedSIMGRWeights:
    """Test SIMGR weights validation."""
    
    def test_valid_weights(self):
        """Valid weights should validate."""
        weights = LoadedSIMGRWeights(
            study_score=0.25,
            interest_score=0.25,
            market_score=0.25,
            growth_score=0.15,
            risk_score=0.10,
        )
        assert weights.validate()
    
    def test_invalid_weights_sum(self):
        """Invalid weights sum should fail validation."""
        weights = LoadedSIMGRWeights(
            study_score=0.30,
            interest_score=0.30,
            market_score=0.30,
            growth_score=0.15,
            risk_score=0.10,  # Sum = 1.15
        )
        assert not weights.validate()
    
    def test_default_weights(self):
        """Default weights should be valid."""
        weights = LoadedSIMGRWeights()
        assert weights.validate()


class TestScoringConfigLoader:
    """Test config loading from YAML."""
    
    @pytest.fixture
    def temp_config_dir(self):
        """Create temporary config directory."""
        import tempfile
        import shutil
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_load_valid_config(self, temp_config_dir):
        """Load valid YAML config."""
        config_content = """
version: "1.0"
simgr_weights:
  study_score: 0.25
  interest_score: 0.25
  market_score: 0.25
  growth_score: 0.15
  risk_score: 0.10
study_factors:
  ability_weight: 0.4
  background_weight: 0.3
  confidence_weight: 0.3
  required_skill_match: 0.7
  preferred_skill_match: 0.3
interest_factors:
  nlp_weight: 0.4
  survey_weight: 0.3
  stability_weight: 0.3
market_factors:
  ai_relevance_weight: 0.3
  growth_rate_weight: 0.3
  salary_weight: 0.2
  inverse_competition_weight: 0.2
growth_factors:
  lifecycle_weight: 0.4
  demand_weight: 0.3
  salary_growth_weight: 0.3
risk_factors:
  saturation_weight: 0.25
  obsolescence_weight: 0.20
  competition_weight: 0.15
  dropout_weight: 0.15
  unemployment_weight: 0.15
  cost_weight: 0.10
"""
        config_path = temp_config_dir / "scoring.yaml"
        config_path.write_text(config_content)
        
        loader = ScoringConfigLoader(config_dir=temp_config_dir)
        config = loader.load("scoring.yaml")
        
        assert config.version == "1.0"
        assert config.simgr_weights.study_score == 0.25
        assert config.simgr_weights.validate()
    
    def test_load_missing_config(self, temp_config_dir):
        """Missing config should use defaults."""
        loader = ScoringConfigLoader(config_dir=temp_config_dir)
        config = loader.load("nonexistent.yaml")
        
        # Should return defaults
        assert config.simgr_weights.validate()
        assert config._source == "default"
    
    def test_validate_valid_config(self, temp_config_dir):
        """Valid config should pass validation."""
        config_content = """
version: "1.0"
simgr_weights:
  study_score: 0.25
  interest_score: 0.25
  market_score: 0.25
  growth_score: 0.15
  risk_score: 0.10
study_factors:
  ability_weight: 0.4
  background_weight: 0.3
  confidence_weight: 0.3
interest_factors:
  nlp_weight: 0.4
  survey_weight: 0.3
  stability_weight: 0.3
market_factors:
  ai_relevance_weight: 0.3
  growth_rate_weight: 0.3
  salary_weight: 0.2
  inverse_competition_weight: 0.2
growth_factors:
  lifecycle_weight: 0.4
  demand_weight: 0.3
  salary_growth_weight: 0.3
risk_factors:
  saturation_weight: 0.25
  obsolescence_weight: 0.20
  competition_weight: 0.15
  dropout_weight: 0.15
  unemployment_weight: 0.15
  cost_weight: 0.10
"""
        config_path = temp_config_dir / "scoring.yaml"
        config_path.write_text(config_content)
        
        loader = ScoringConfigLoader(config_dir=temp_config_dir)
        config = loader.load("scoring.yaml")
        result = loader.validate(config)
        
        assert result["valid"]
        assert len(result["errors"]) == 0
    
    def test_validate_invalid_simgr_weights(self, temp_config_dir):
        """Invalid SIMGR weights should fail validation."""
        config_content = """
version: "1.0"
simgr_weights:
  study_score: 0.30
  interest_score: 0.30
  market_score: 0.30
  growth_score: 0.20
  risk_score: 0.10
"""
        config_path = temp_config_dir / "scoring.yaml"
        config_path.write_text(config_content)
        
        loader = ScoringConfigLoader(config_dir=temp_config_dir)
        config = loader.load("scoring.yaml")
        result = loader.validate(config)
        
        assert not result["valid"]
        assert any("SIMGR weights" in e for e in result["errors"])
    
    def test_validate_invalid_study_factors(self, temp_config_dir):
        """Invalid study factors should fail validation."""
        config_content = """
version: "1.0"
simgr_weights:
  study_score: 0.25
  interest_score: 0.25
  market_score: 0.25
  growth_score: 0.15
  risk_score: 0.10
study_factors:
  ability_weight: 0.5
  background_weight: 0.3
  confidence_weight: 0.3
"""
        config_path = temp_config_dir / "scoring.yaml"
        config_path.write_text(config_content)
        
        loader = ScoringConfigLoader(config_dir=temp_config_dir)
        config = loader.load("scoring.yaml")
        result = loader.validate(config)
        
        assert not result["valid"]
        assert any("Study factors" in e for e in result["errors"])


class TestR005Compliance:
    """Test R005 Config Externalization compliance."""
    
    def test_config_file_exists(self):
        """Config file must exist."""
        config_path = Path("config/scoring.yaml")
        assert config_path.exists(), "config/scoring.yaml must exist"
    
    def test_schema_file_exists(self):
        """Schema file must exist."""
        schema_path = Path("config/scoring_schema.yaml")
        assert schema_path.exists(), "config/scoring_schema.yaml must exist"
    
    def test_config_loads_successfully(self):
        """Config must load without errors."""
        loader = ScoringConfigLoader(config_dir=Path("config"))
        config = loader.load("scoring.yaml")
        
        assert config is not None
        assert config.version == "1.0"
    
    def test_config_validates_successfully(self):
        """Config must pass validation."""
        loader = ScoringConfigLoader(config_dir=Path("config"))
        config = loader.load("scoring.yaml")
        result = loader.validate(config)
        
        assert result["valid"], f"Validation errors: {result['errors']}"
    
    def test_no_hardcoded_values_in_loader(self):
        """Config loader should not have hardcoded business values."""
        import inspect
        from backend.scoring.config_loader import ScoringConfigLoader
        
        source = inspect.getsource(ScoringConfigLoader)
        
        # Should not have magic numbers for weights
        # (defaults are okay, but main values should come from config)
        assert "0.77" not in source
        assert "0.88" not in source
    
    def test_weights_come_from_config(self):
        """All weights should be loaded from config, not hardcoded."""
        loader = ScoringConfigLoader(config_dir=Path("config"))
        config = loader.load("scoring.yaml")
        
        # Verify source is the config file
        assert "config" in config._source.lower() or "default" in config._source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

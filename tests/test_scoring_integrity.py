# tests/test_scoring_integrity.py
"""
SCORING INTEGRITY TESTS - GĐ Phase 1

These tests ensure:
- Weights are ML-trained (method == "linear_regression")
- No default weights in production
- No silent fallback behavior
- Clear governance enforcement

CRITICAL: These tests are part of the governance gate.
If any test fails, scoring system MUST NOT start.
"""

from __future__ import annotations

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from typing import Dict, Any


class TestWeightsAreMLTrained:
    """Verify active weights are ML-trained, not defaults."""
    
    def test_weights_method_is_linear_regression(self):
        """Active weights MUST have method='linear_regression'."""
        # Load active weights directly
        weights_path = Path("models/weights/active/weights.json")
        
        # Skip if file doesn't exist (for CI without full setup)
        if not weights_path.exists():
            pytest.skip("Active weights file not present")
        
        with open(weights_path, "r", encoding="utf-8") as f:
            weights_data = json.load(f)
        
        # Method can be at root level or in metrics
        method = weights_data.get("method") or weights_data.get("metrics", {}).get("method")
        
        assert method == "linear_regression", (
            f"Scoring Integrity Violation: "
            f"Expected method='linear_regression', got '{method}'. "
            f"Weights MUST be ML-trained."
        )
    
    def test_weights_required_keys_present(self):
        """Active weights MUST contain all required components."""
        weights_path = Path("models/weights/active/weights.json")
        
        if not weights_path.exists():
            pytest.skip("Active weights file not present")
        
        with open(weights_path, "r", encoding="utf-8") as f:
            weights_data = json.load(f)
        
        weights = weights_data.get("weights", {})
        required_keys = {"study_score", "interest_score", "market_score", "growth_score", "risk_score"}
        
        assert set(weights.keys()) == required_keys, (
            f"Weights file missing required components. "
            f"Expected: {required_keys}, Got: {set(weights.keys())}"
        )
    
    def test_weights_are_not_default_pattern(self):
        """Active weights should NOT match default pattern exactly."""
        weights_path = Path("models/weights/active/weights.json")
        
        if not weights_path.exists():
            pytest.skip("Active weights file not present")
        
        with open(weights_path, "r", encoding="utf-8") as f:
            weights_data = json.load(f)
        
        weights = weights_data.get("weights", {})
        
        # Default pattern (baseline weights)
        default_pattern = {
            "study_score": 0.25,
            "interest_score": 0.25,
            "market_score": 0.25,
            "growth_score": 0.15,
            "risk_score": 0.10,
        }
        
        # If method is linear_regression, pattern match is OK
        method = weights_data.get("method") or weights_data.get("metrics", {}).get("method")
        if method == "linear_regression":
            return  # Skip pattern check for ML-trained weights
        
        # For non-ML weights, pattern match indicates default weights
        if weights == default_pattern:
            pytest.fail(
                "Governance Violation: Active weights match default pattern "
                "but method is not 'linear_regression'. "
                "ML-trained weights required."
            )


class TestWeightRegistryEnforcement:
    """Verify WeightsRegistry enforces integrity rules."""
    
    def test_registry_rejects_default_method_in_strict_mode(self):
        """Registry MUST reject weights with method='default' in STRICT mode."""
        from backend.scoring.weights_registry import (
            WeightsRegistry,
            LoadMode,
            ScoringIntegrityError,
            REQUIRED_METHOD,
        )
        
        # Create mock weights with default method
        mock_weights = {
            "version": "test",
            "method": "default",
            "weights": {
                "study_score": 0.25,
                "interest_score": 0.25,
                "market_score": 0.25,
                "growth_score": 0.15,
                "risk_score": 0.10,
            },
            "metrics": {"method": "default"},
        }
        
        with patch("builtins.open", MagicMock()), \
             patch("json.load", return_value=mock_weights), \
             patch("pathlib.Path.exists", return_value=True):
            
            registry = WeightsRegistry(mode=LoadMode.STRICT)
            
            with pytest.raises(ScoringIntegrityError) as exc_info:
                registry.load_active_weights()
            
            assert REQUIRED_METHOD in str(exc_info.value)
            assert "default" in str(exc_info.value)
    
    def test_registry_accepts_linear_regression_method(self):
        """Registry MUST accept weights with method='linear_regression'."""
        from backend.scoring.weights_registry import (
            WeightsRegistry,
            LoadMode,
        )
        
        # Create mock weights with ML-trained method
        mock_weights = {
            "version": "v3",
            "method": "linear_regression",
            "trained_at": "2026-02-16T12:00:00Z",
            "weights": {
                "study_score": 0.28,
                "interest_score": 0.23,
                "market_score": 0.22,
                "growth_score": 0.17,
                "risk_score": 0.10,
            },
            "metrics": {"method": "linear_regression"},
        }
        
        # Use WARN mode to test scoring integrity without requiring full GĐ5 metadata
        # Scoring integrity checks (method validation) run in both STRICT and WARN modes
        with patch("builtins.open", MagicMock()), \
             patch("json.load", return_value=mock_weights), \
             patch("pathlib.Path.exists", return_value=True):
            
            registry = WeightsRegistry(mode=LoadMode.WARN)
            
            # Should not raise - method is valid
            weights = registry.load_active_weights()
            
            assert weights["study_score"] == 0.28
    
    def test_registry_rejects_missing_weight_keys(self):
        """Registry MUST reject weights with missing required keys."""
        from backend.scoring.weights_registry import (
            WeightsRegistry,
            LoadMode,
            ScoringIntegrityError,
        )
        
        # Create mock weights with missing keys
        mock_weights = {
            "version": "test",
            "method": "linear_regression",
            "weights": {
                "study_score": 0.25,
                # Missing: interest_score, market_score, growth_score, risk_score
            },
        }
        
        with patch("builtins.open", MagicMock()), \
             patch("json.load", return_value=mock_weights), \
             patch("pathlib.Path.exists", return_value=True):
            
            registry = WeightsRegistry(mode=LoadMode.STRICT)
            
            with pytest.raises(ScoringIntegrityError) as exc_info:
                registry.load_active_weights()
            
            assert "missing required components" in str(exc_info.value).lower()


class TestNoFallbackBehavior:
    """Verify no silent fallback to default weights."""
    
    def test_missing_weights_file_raises_error(self):
        """Missing weights file MUST raise error, not fallback."""
        from backend.scoring.weights_registry import (
            WeightsRegistry,
            LoadMode,
            IncompleteArtifactError,
        )
        
        with patch("pathlib.Path.exists", return_value=False):
            registry = WeightsRegistry(mode=LoadMode.STRICT)
            
            with pytest.raises(IncompleteArtifactError):
                registry.load_active_weights()
    
    def test_config_from_file_raises_on_missing_weights(self):
        """SIMGRWeights.from_file propagates registry exceptions (no silent fallback).
        
        This tests that when the weights registry raises an exception,
        the config loader properly propagates it rather than silently
        falling back to default weights.
        """
        from backend.scoring.config import SIMGRWeights
        from backend.scoring.weights_registry import (
            IncompleteArtifactError,
            ScoringIntegrityError,
        )
        
        # Test 1: IncompleteArtifactError should be propagated as ValueError
        with patch("backend.scoring.weights_registry.WeightsRegistry") as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.load_active_weights.side_effect = IncompleteArtifactError(
                "weights.json not found in test"
            )
            MockRegistry.return_value = mock_instance
            
            with pytest.raises(ValueError) as exc_info:
                SIMGRWeights.from_file()
            
            # Verify the error mentions validation failure
            assert "validation failed" in str(exc_info.value).lower()
        
        # Test 2: ScoringIntegrityError should be propagated as RuntimeError
        with patch("backend.scoring.weights_registry.WeightsRegistry") as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.load_active_weights.side_effect = ScoringIntegrityError(
                "Scoring Integrity Violation: Expected method='linear_regression', got 'default'"
            )
            MockRegistry.return_value = mock_instance
            
            with pytest.raises(RuntimeError) as exc_info:
                SIMGRWeights.from_file()
            
            # Verify it's a scoring integrity error
            assert "scoring integrity" in str(exc_info.value).lower()


class TestDefaultWeightsProtection:
    """Verify default weights cannot be used in production."""
    
    def test_defaults_not_loaded_in_production(self):
        """load_default_weights_for_development MUST fail in production."""
        from backend.scoring.weights_registry import (
            load_default_weights_for_development,
        )
        
        with patch("backend.scoring.weights_registry.ENVIRONMENT", "production"):
            with pytest.raises(RuntimeError) as exc_info:
                load_default_weights_for_development()
            
            assert "cannot be used outside development" in str(exc_info.value)
    
    def test_defaults_allowed_in_development(self):
        """load_default_weights_for_development allowed in development."""
        from backend.scoring.weights_registry import (
            load_default_weights_for_development,
            DEFAULT_WEIGHTS_DIR,
        )
        
        mock_defaults = {
            "weights": {
                "study_score": 0.25,
                "interest_score": 0.25,
                "market_score": 0.25,
                "growth_score": 0.15,
                "risk_score": 0.10,
            }
        }
        
        with patch("backend.scoring.weights_registry.ENVIRONMENT", "development"), \
             patch("pathlib.Path.exists", return_value=True), \
             patch("builtins.open", MagicMock()), \
             patch("json.load", return_value=mock_defaults):
            
            # Should not raise
            weights = load_default_weights_for_development()
            
            assert weights["study_score"] == 0.25


class TestIntegrityConstants:
    """Verify integrity constants are properly defined."""
    
    def test_required_method_constant(self):
        """REQUIRED_METHOD constant must be 'linear_regression'."""
        from backend.scoring.weights_registry import REQUIRED_METHOD
        
        assert REQUIRED_METHOD == "linear_regression"
    
    def test_required_weight_keys_constant(self):
        """REQUIRED_WEIGHT_KEYS must include all SIMGR components."""
        from backend.scoring.weights_registry import REQUIRED_WEIGHT_KEYS
        
        expected = ["study", "interest", "market", "growth", "risk"]
        assert set(REQUIRED_WEIGHT_KEYS) == set(expected)

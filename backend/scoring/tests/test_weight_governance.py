# backend/scoring/tests/test_weight_governance.py
"""
Weight Governance Tests - GĐ1 PHẦN G

Tests enforcing weight governance rules:
1. test_no_fallback_on_missing_weights - MUST crash if weights missing
2. test_checksum_verification - MUST verify checksum before load
3. test_registry_lookup - MUST use registry for version resolution
4. test_reject_default_weights - MUST reject hardcoded defaults
"""

import json
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch


# Test 1: No Fallback on Missing Weights
class TestNoFallbackOnMissingWeights:
    """Test that weight loading crashes when file is missing."""
    
    def test_from_file_raises_on_missing(self):
        """SIMGRWeights.from_file must raise FileNotFoundError if file missing."""
        from backend.scoring.config import SIMGRWeights
        
        fake_path = "/nonexistent/path/weights.json"
        
        with pytest.raises(FileNotFoundError) as exc_info:
            SIMGRWeights.from_file(fake_path)
        
        assert "missing" in str(exc_info.value).lower() or "not found" in str(exc_info.value).lower()
    
    def test_weight_loader_raises_on_missing(self):
        """WeightLoader.load must raise WeightNotFoundError if file missing."""
        from backend.scoring.weight_loader import WeightLoader, WeightNotFoundError
        
        loader = WeightLoader()
        
        with pytest.raises(WeightNotFoundError):
            loader.load(path=Path("/nonexistent/path/weights.json"))
    
    def test_no_silent_fallback(self):
        """Must NOT silently return defaults when file missing."""
        from backend.scoring.config import SIMGRWeights
        
        # This should NOT work - weights file must exist
        with pytest.raises(FileNotFoundError):
            SIMGRWeights.from_file("/missing/weights.json")


# Test 2: Checksum Verification
class TestChecksumVerification:
    """Test that checksum is verified before weights are accepted."""
    
    def test_checksum_mismatch_raises(self):
        """Must raise error on checksum mismatch."""
        from backend.scoring.weight_loader import WeightLoader, WeightChecksumError
        
        # Create temp file with wrong checksum
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "version": "test",
                "trained_at": "2026-01-01T00:00:00Z",
                "dataset_hash": "test",
                "model_type": "test",
                "weights": {
                    "study_score": 0.25,
                    "interest_score": 0.25,
                    "market_score": 0.25,
                    "growth_score": 0.15,
                    "risk_score": 0.10
                },
                "metrics": {},
                "checksum": "wrong_checksum_value_that_will_fail"
            }, f)
            temp_path = f.name
        
        try:
            loader = WeightLoader()
            with pytest.raises(WeightChecksumError):
                loader.load(path=Path(temp_path))
        finally:
            os.unlink(temp_path)
    
    def test_checksum_valid_accepted(self):
        """Must accept weights with valid checksum."""
        from backend.scoring.weight_loader import WeightLoader, compute_checksum
        
        weights = {
            "study_score": 0.25,
            "interest_score": 0.25,
            "market_score": 0.25,
            "growth_score": 0.15,
            "risk_score": 0.10
        }
        valid_checksum = compute_checksum(weights)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "version": "test",
                "trained_at": "2026-01-01T00:00:00Z",
                "dataset_hash": "test",
                "model_type": "test",
                "weights": weights,
                "metrics": {},
                "checksum": valid_checksum
            }, f)
            temp_path = f.name
        
        try:
            loader = WeightLoader()
            artifact = loader.load(path=Path(temp_path))
            assert artifact._verified == True
            assert artifact.checksum == valid_checksum
        finally:
            os.unlink(temp_path)


# Test 3: Registry Lookup
class TestRegistryLookup:
    """Test that version resolution uses registry."""
    
    def test_registry_required(self):
        """Must fail if registry doesn't exist."""
        from backend.scoring.weight_loader import WeightLoader, WeightRegistryError
        
        loader = WeightLoader(registry_path=Path("/nonexistent/registry.json"))
        
        with pytest.raises(WeightRegistryError):
            loader._load_registry()
    
    def test_registry_active_lookup(self):
        """Must resolve active version from registry."""
        from backend.scoring.weight_loader import WeightLoader
        
        registry = {
            "active": "v1",
            "versions": {
                "v1": {"path": "models/weights/v1/weights.json"}
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(registry, f)
            temp_path = f.name
        
        try:
            loader = WeightLoader(registry_path=Path(temp_path))
            version = loader._resolve_version()
            assert version == "v1"
        finally:
            os.unlink(temp_path)


# Test 4: Reject Default Weights
class TestRejectDefaultWeights:
    """Test that default/hardcoded weights are rejected."""
    
    def test_require_trained_weights_rejects_defaults(self):
        """require_trained_weights must reject default pattern."""
        from backend.scoring.weight_loader import (
            WeightLoader, WeightArtifact, WeightLoadError
        )
        
        loader = WeightLoader()
        
        # Create artifact with default weights
        default_artifact = WeightArtifact(
            version="test",
            trained_at="2026-01-01T00:00:00Z",
            dataset_hash="test",
            model_type="test",
            weights={
                "study_score": 0.25,
                "interest_score": 0.25,
                "market_score": 0.25,
                "growth_score": 0.15,
                "risk_score": 0.10
            },
            metrics={},
            checksum="test"
        )
        
        # is_default should detect default pattern
        assert loader.is_default(default_artifact) == True
    
    def test_non_default_accepted(self):
        """Non-default weights should be accepted."""
        from backend.scoring.weight_loader import WeightLoader, WeightArtifact
        
        loader = WeightLoader()
        
        # Create artifact with trained (non-default) weights
        trained_artifact = WeightArtifact(
            version="test",
            trained_at="2026-01-01T00:00:00Z",
            dataset_hash="test",
            model_type="test",
            weights={
                "study_score": 0.30,  # Different from default 0.25
                "interest_score": 0.20,
                "market_score": 0.25,
                "growth_score": 0.15,
                "risk_score": 0.10
            },
            metrics={},
            checksum="test"
        )
        
        assert loader.is_default(trained_artifact) == False
    
    def test_config_requires_weights_file(self):
        """ScoringConfig must require weights file, not use defaults."""
        from backend.scoring.config import SIMGRWeights
        
        # Attempting to load from missing file must fail
        with pytest.raises(FileNotFoundError):
            SIMGRWeights.from_file("/missing/weights.json")


# Test 5: No .get() Fallbacks in Parsing
class TestNoGetFallbacks:
    """Test that weight parsing doesn't use .get() with defaults."""
    
    def test_missing_key_raises(self):
        """Must raise error if weight key is missing."""
        from backend.scoring.config import SIMGRWeights
        
        # Create temp file with missing key
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "version": "test",
                "weights": {
                    "study_score": 0.25,
                    "interest_score": 0.25,
                    # Missing: market_score, growth_score, risk_score
                }
            }, f)
            temp_path = f.name
        
        try:
            with pytest.raises(ValueError) as exc_info:
                SIMGRWeights.from_file(temp_path)
            
            assert "missing" in str(exc_info.value).lower()
        finally:
            os.unlink(temp_path)


# Test 6: Weight Sum Validation
class TestWeightSumValidation:
    """Test that weights must sum to 1.0."""
    
    def test_invalid_sum_raises(self):
        """Must raise error if weights don't sum to 1.0."""
        from backend.scoring.config import SIMGRWeights
        
        with pytest.raises(ValueError) as exc_info:
            SIMGRWeights(
                study_score=0.30,
                interest_score=0.30,
                market_score=0.30,
                growth_score=0.30,
                risk_score=0.30,  # Sum = 1.5
            )
        
        assert "sum" in str(exc_info.value).lower() or "1.0" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

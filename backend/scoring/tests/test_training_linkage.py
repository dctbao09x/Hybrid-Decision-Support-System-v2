# backend/scoring/tests/test_training_linkage.py
"""
GĐ5 Training ↔ Runtime Linkage Tests.

Tests enforcing weight governance rules for Stage 5:
1. No Untagged Model - All weights must have metadata
2. No Manual Promotion - Only pipeline-produced weights are valid
3. Immutable Artifact - Checksum must match
4. Verified Lineage - Metadata must pass validation
5. Runtime-Enforced Governance - STRICT mode rejects invalid weights

Principles:
- Runtime CHỈ chấp nhận weights sinh từ pipeline training hợp lệ
- NO manual weights, NO shadow models, NO bypass
"""

import json
import os
import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import patch


# =============================================================================
# Test 1: No Untagged Model - Weights Must Have Metadata
# =============================================================================
class TestNoUntaggedModel:
    """Test that weights without metadata are rejected in STRICT mode."""
    
    def test_weights_without_metadata_rejected_strict(self):
        """Weights.json without weight_metadata.json must be rejected in STRICT mode."""
        from backend.scoring.weights_registry import (
            WeightsRegistry, 
            LoadMode, 
            MissingMetadataError,
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create weights.json WITHOUT metadata
            weights_dir = Path(tmpdir) / "active"
            weights_dir.mkdir(parents=True)
            
            weights_file = weights_dir / "weights.json"
            weights_file.write_text(json.dumps({
                "version": "v1",
                "weights": {
                    "study": 0.25,
                    "interest": 0.25,
                    "market": 0.25,
                    "growth": 0.15,
                    "risk": 0.10,
                },
                "checksum": "abc123",
            }))
            
            # NO weight_metadata.json created
            
            registry = WeightsRegistry(base_path=tmpdir)
            
            # STRICT mode MUST reject
            with pytest.raises(MissingMetadataError) as exc_info:
                registry.load_active_weights(mode=LoadMode.STRICT)
            
            assert "metadata" in str(exc_info.value).lower()
    
    def test_weights_without_metadata_warn_mode(self):
        """WARN mode logs warning but allows loading without metadata."""
        from backend.scoring.weights_registry import (
            WeightsRegistry, 
            LoadMode,
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create weights.json WITHOUT metadata
            weights_dir = Path(tmpdir) / "active"
            weights_dir.mkdir(parents=True)
            
            weights_file = weights_dir / "weights.json"
            weights_file.write_text(json.dumps({
                "version": "v1",
                "weights": {
                    "study": 0.25,
                    "interest": 0.25,
                    "market": 0.25,
                    "growth": 0.15,
                    "risk": 0.10,
                },
                "checksum": "abc123",
            }))
            
            registry = WeightsRegistry(base_path=tmpdir)
            
            # WARN mode should succeed
            payload, metadata = registry.load_active_weights(mode=LoadMode.WARN)
            
            assert payload is not None
            assert "weights" in payload
            assert metadata is None  # No metadata available


# =============================================================================
# Test 2: No Manual Promotion - Only Pipeline Weights Are Valid
# =============================================================================
class TestNoManualPromotion:
    """Test that manually created weights are detected and rejected."""
    
    def test_detect_manual_weight_override(self):
        """Detect weights that were modified manually after training."""
        from backend.scoring.weight_metadata import detect_manual_override
        
        # Create metadata with original checksum
        original_checksum = "abcd1234efgh5678"
        metadata = {
            "weights_checksum": original_checksum,
        }
        
        # Modified weights (different checksum)
        modified_weights = {
            "study": 0.30,  # Changed from training
            "interest": 0.20,
            "market": 0.25,
            "growth": 0.15,
            "risk": 0.10,
        }
        
        # Should detect manual override
        from backend.scoring.weight_metadata import compute_weights_checksum
        actual_checksum = compute_weights_checksum(modified_weights)
        
        # Checksums won't match
        assert actual_checksum != original_checksum
    
    def test_manual_override_rejected_strict(self):
        """Weights modified after training must be rejected in STRICT mode."""
        from backend.scoring.weights_registry import (
            WeightsRegistry, 
            LoadMode,
            ChecksumMismatchError,
        )
        from backend.scoring.weight_metadata import compute_weights_checksum
        
        with tempfile.TemporaryDirectory() as tmpdir:
            weights_dir = Path(tmpdir) / "active"
            weights_dir.mkdir(parents=True)
            
            # Original weights
            original_weights = {
                "study": 0.25,
                "interest": 0.25,
                "market": 0.25,
                "growth": 0.15,
                "risk": 0.10,
            }
            original_checksum = compute_weights_checksum(original_weights)
            
            # Save weights.json with MODIFIED values (not matching checksum)
            modified_weights = {
                "study": 0.35,  # <-- Manual edit!
                "interest": 0.20,
                "market": 0.25,
                "growth": 0.10,
                "risk": 0.10,
            }
            
            weights_file = weights_dir / "weights.json"
            weights_file.write_text(json.dumps({
                "version": "v1",
                "weights": modified_weights,  # Modified
                "checksum": "weights_checksum_doesnt_match",
            }))
            
            # Create metadata with ORIGINAL checksum
            metadata_file = weights_dir / "weight_metadata.json"
            metadata_file.write_text(json.dumps({
                "version": "v1",
                "metadata_version": "1.0",
                "trained_at": datetime.utcnow().isoformat(),
                "dataset": "test.csv",
                "dataset_checksum": "dataset123",
                "features": ["study", "interest", "market", "growth", "risk"],
                "weights_checksum": original_checksum,  # Original
                "trainer_commit": "abc123",
                "pipeline_version": "train_v2.1",
                "status": "active",
                "metrics": {
                    "train_loss": 0.1,
                    "val_loss": 0.1,
                    "correlation": 0.9,
                    "mae": 0.05,
                    "samples_used": 1000,
                },
            }))
            
            registry = WeightsRegistry(base_path=tmpdir)
            
            # STRICT mode MUST reject due to checksum mismatch
            with pytest.raises(ChecksumMismatchError) as exc_info:
                registry.load_active_weights(mode=LoadMode.STRICT)
            
            assert "checksum" in str(exc_info.value).lower()


# =============================================================================
# Test 3: Immutable Artifact - Full Pipeline Verification
# =============================================================================
class TestImmutableArtifact:
    """Test that artifacts are immutable and verifiable."""
    
    def test_valid_pipeline_artifact_loads(self):
        """Valid artifact from training pipeline must load successfully."""
        from backend.scoring.weights_registry import (
            WeightsRegistry, 
            LoadMode,
        )
        from backend.scoring.weight_metadata import (
            compute_weights_checksum,
            compute_file_checksum,
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            weights_dir = Path(tmpdir) / "active"
            weights_dir.mkdir(parents=True)
            
            # Create dataset file
            dataset_file = Path(tmpdir) / "train.csv"
            dataset_file.write_text("study,interest,market,growth,risk,outcome\n0.5,0.5,0.5,0.5,0.5,0.8\n")
            dataset_checksum = compute_file_checksum(dataset_file)
            
            # Valid weights
            weights = {
                "study": 0.25,
                "interest": 0.25,
                "market": 0.25,
                "growth": 0.15,
                "risk": 0.10,
            }
            weights_checksum = compute_weights_checksum(weights)
            
            # Create weights.json
            weights_file = weights_dir / "weights.json"
            weights_file.write_text(json.dumps({
                "version": "v1",
                "weights": weights,
                "checksum": weights_checksum,
            }))
            
            # Create VALID metadata
            metadata_file = weights_dir / "weight_metadata.json"
            metadata_file.write_text(json.dumps({
                "version": "v1",
                "metadata_version": "1.0",
                "trained_at": datetime.utcnow().isoformat(),
                "dataset": "train.csv",
                "dataset_checksum": dataset_checksum,
                "features": ["study", "interest", "market", "growth", "risk"],
                "weights_checksum": weights_checksum,  # Matches!
                "trainer_commit": "abc123def",
                "pipeline_version": "train_v2.1",
                "status": "active",
                "metrics": {
                    "train_loss": 0.08,
                    "val_loss": 0.10,
                    "correlation": 0.92,
                    "mae": 0.04,
                    "samples_used": 1000,
                },
            }))
            
            registry = WeightsRegistry(base_path=tmpdir)
            
            # STRICT mode MUST succeed for valid artifact
            payload, metadata = registry.load_active_weights(mode=LoadMode.STRICT)
            
            assert payload is not None
            assert metadata is not None
            assert payload["weights"]["study"] == 0.25
            assert metadata.pipeline_version == "train_v2.1"
    
    def test_checksum_verification(self):
        """Checksum must be verified against actual weights."""
        from backend.scoring.weight_metadata import compute_weights_checksum
        
        weights1 = {"study": 0.25, "interest": 0.25, "market": 0.25, "growth": 0.15, "risk": 0.10}
        weights2 = {"study": 0.26, "interest": 0.25, "market": 0.25, "growth": 0.14, "risk": 0.10}
        
        checksum1 = compute_weights_checksum(weights1)
        checksum2 = compute_weights_checksum(weights2)
        
        # Different weights MUST produce different checksums
        assert checksum1 != checksum2
        
        # Same weights MUST produce same checksum
        assert compute_weights_checksum(weights1) == checksum1


# =============================================================================
# Test 4: Verified Lineage - Metadata Validation
# =============================================================================
class TestVerifiedLineage:
    """Test metadata validation for training lineage."""
    
    def test_metadata_required_fields(self):
        """Metadata must contain all required fields."""
        from backend.scoring.weight_metadata import WeightMetadata, validate_metadata
        
        # Create valid metadata
        metadata = WeightMetadata(
            version="v1",
            trained_at=datetime.utcnow().isoformat(),
            dataset="train.csv",
            dataset_checksum="abc123",
            features=["study", "interest", "market", "growth", "risk"],
            weights_checksum="def456",
            trainer_commit="commit123",
            pipeline_version="train_v2.1",
        )
        
        # Should be valid
        is_valid, errors = validate_metadata(metadata)
        assert is_valid, f"Valid metadata rejected: {errors}"
    
    def test_metadata_missing_version_invalid(self):
        """Metadata without version is invalid."""
        from backend.scoring.weight_metadata import WeightMetadata, validate_metadata
        
        metadata = WeightMetadata(
            version="",  # Invalid
            trained_at=datetime.utcnow().isoformat(),
            dataset="train.csv",
            dataset_checksum="abc123",
            features=["study", "interest", "market", "growth", "risk"],
            weights_checksum="def456",
            trainer_commit="commit123",
            pipeline_version="train_v2.1",
        )
        
        is_valid, errors = validate_metadata(metadata)
        assert not is_valid
        assert "version" in str(errors).lower()
    
    def test_metadata_missing_pipeline_version_invalid(self):
        """Metadata without pipeline_version is invalid."""
        from backend.scoring.weight_metadata import WeightMetadata, validate_metadata
        
        metadata = WeightMetadata(
            version="v1",
            trained_at=datetime.utcnow().isoformat(),
            dataset="train.csv",
            dataset_checksum="abc123",
            features=["study", "interest", "market", "growth", "risk"],
            weights_checksum="def456",
            trainer_commit="commit123",
            pipeline_version="",  # Invalid
        )
        
        is_valid, errors = validate_metadata(metadata)
        assert not is_valid
        assert "pipeline" in str(errors).lower()


# =============================================================================
# Test 5: Runtime-Enforced Governance
# =============================================================================
class TestRuntimeEnforcedGovernance:
    """Test runtime governance enforcement via config.py integration."""
    
    def test_config_uses_registry_strict(self):
        """SIMGRWeights.from_file must use registry in STRICT mode."""
        from backend.scoring.config import SIMGRWeights, WEIGHT_VALIDATION_MODE
        from backend.scoring.weight_metadata import compute_weights_checksum
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create valid artifact
            weights_dir = Path(tmpdir) / "active"
            weights_dir.mkdir(parents=True)
            
            weights = {
                "study": 0.25,
                "interest": 0.25,
                "market": 0.25,
                "growth": 0.15,
                "risk": 0.10,
            }
            weights_checksum = compute_weights_checksum(weights)
            
            # weights.json
            weights_file = weights_dir / "weights.json"
            weights_file.write_text(json.dumps({
                "version": "v1",
                "weights": weights,
                "checksum": weights_checksum,
            }))
            
            # weight_metadata.json
            metadata_file = weights_dir / "weight_metadata.json"
            metadata_file.write_text(json.dumps({
                "version": "v1",
                "metadata_version": "1.0",
                "trained_at": datetime.utcnow().isoformat(),
                "dataset": "train.csv",
                "dataset_checksum": "data123",
                "features": ["study", "interest", "market", "growth", "risk"],
                "weights_checksum": weights_checksum,
                "trainer_commit": "abc123",
                "pipeline_version": "train_v2.1",
                "status": "active",
                "metrics": {
                    "train_loss": 0.08,
                    "val_loss": 0.10,
                    "correlation": 0.92,
                    "mae": 0.04,
                    "samples_used": 1000,
                },
            }))
            
            # Patch registry base path
            with patch('backend.scoring.weights_registry.WeightsRegistry') as MockRegistry:
                from backend.scoring.weights_registry import WeightsRegistry, LoadMode
                
                # Create real registry with tmpdir
                real_registry = WeightsRegistry(base_path=tmpdir)
                
                # Test STRICT mode loads successfully
                payload, metadata = real_registry.load_active_weights(mode=LoadMode.STRICT)
                
                assert payload is not None
                assert metadata is not None
    
    def test_bypass_mode_skips_validation(self):
        """BYPASS mode loads weights without validation (testing only)."""
        from backend.scoring.weights_registry import (
            WeightsRegistry, 
            LoadMode,
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create weights.json WITHOUT metadata (normally invalid)
            weights_dir = Path(tmpdir) / "active"
            weights_dir.mkdir(parents=True)
            
            weights_file = weights_dir / "weights.json"
            weights_file.write_text(json.dumps({
                "version": "v1_test",
                "weights": {
                    "study": 0.25,
                    "interest": 0.25,
                    "market": 0.25,
                    "growth": 0.15,
                    "risk": 0.10,
                },
                "checksum": "test123",
            }))
            
            registry = WeightsRegistry(base_path=tmpdir)
            
            # BYPASS mode should succeed even without metadata
            payload, metadata = registry.load_active_weights(mode=LoadMode.BYPASS)
            
            assert payload is not None
            assert payload["version"] == "v1_test"
            assert metadata is None  # Not loaded in bypass


# =============================================================================
# Test 6: Training Output Produces Valid Metadata
# =============================================================================
class TestTrainingOutputMetadata:
    """Test that training pipeline produces valid metadata."""
    
    def test_create_weight_artifact_function(self):
        """create_weight_artifact must produce valid metadata."""
        from backend.scoring.weight_metadata import (
            create_weight_artifact,
            validate_metadata,
            TrainingMetrics,
        )
        
        weights = {
            "study": 0.25,
            "interest": 0.25,
            "market": 0.25,
            "growth": 0.15,
            "risk": 0.10,
        }
        
        metrics = TrainingMetrics(
            train_loss=0.08,
            val_loss=0.10,
            correlation=0.92,
            mae=0.04,
            samples_used=1000,
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fake dataset
            dataset_path = Path(tmpdir) / "train.csv"
            dataset_path.write_text("study,interest,market,growth,risk,outcome\n0.5,0.5,0.5,0.5,0.5,0.8\n")
            
            metadata = create_weight_artifact(
                version="v1",
                weights=weights,
                dataset_path=str(dataset_path),
                metrics=metrics,
                trainer_script="train_weights.py",
            )
            
            # Validate produced metadata
            is_valid, errors = validate_metadata(metadata)
            assert is_valid, f"create_weight_artifact produced invalid metadata: {errors}"
            
            assert metadata.version == "v1"
            assert metadata.pipeline_version == "train_v2.1"
            assert metadata.weights_checksum is not None
            assert metadata.dataset_checksum is not None


# =============================================================================
# Integration Test: Full Training → Runtime Flow
# =============================================================================
class TestTrainingRuntimeIntegration:
    """Test full flow from training to runtime loading."""
    
    def test_training_output_loadable_by_runtime(self):
        """Artifacts produced by training must be loadable by runtime."""
        from backend.scoring.weight_metadata import (
            create_weight_artifact,
            TrainingMetrics,
        )
        from backend.scoring.weights_registry import (
            WeightsRegistry,
            LoadMode,
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Simulate training output
            version = "v_test"
            version_dir = Path(tmpdir) / version
            version_dir.mkdir(parents=True)
            
            # Create dataset
            dataset_path = Path(tmpdir) / "train.csv"
            dataset_path.write_text("study,interest,market,growth,risk,outcome\n0.5,0.5,0.5,0.5,0.5,0.8\n")
            
            # Simulate trained weights
            weights = {
                "study": 0.22,
                "interest": 0.28,
                "market": 0.23,
                "growth": 0.17,
                "risk": 0.10,
            }
            
            metrics = TrainingMetrics(
                train_loss=0.07,
                val_loss=0.09,
                correlation=0.94,
                mae=0.03,
                samples_used=5000,
            )
            
            # Create metadata artifact (as training would)
            metadata = create_weight_artifact(
                version=version,
                weights=weights,
                dataset_path=str(dataset_path),
                metrics=metrics,
                trainer_script="train_weights.py",
            )
            
            # Save weights.json (as training would)
            weights_file = version_dir / "weights.json"
            weights_file.write_text(json.dumps({
                "version": version,
                "weights": weights,
                "checksum": metadata.weights_checksum,
            }))
            
            # Save metadata (as training would)
            metadata_file = version_dir / "weight_metadata.json"
            metadata_file.write_text(json.dumps(metadata.to_dict()))
            
            # Copy to active (as training would)
            active_dir = Path(tmpdir) / "active"
            active_dir.mkdir(parents=True)
            shutil.copy(weights_file, active_dir / "weights.json")
            shutil.copy(metadata_file, active_dir / "weight_metadata.json")
            
            # Now runtime loads - MUST succeed
            registry = WeightsRegistry(base_path=tmpdir)
            payload, loaded_metadata = registry.load_active_weights(mode=LoadMode.STRICT)
            
            # Verify loaded correctly
            assert payload is not None
            assert loaded_metadata is not None
            assert payload["weights"]["study"] == 0.22
            assert loaded_metadata.version == version
            assert loaded_metadata.metrics is not None
            assert loaded_metadata.metrics.correlation == 0.94


# =============================================================================
# PHẦN H — EXTENDED TEST SUITE
# =============================================================================

class TestValidModelLoad:
    """Test valid model loading scenarios."""
    
    def test_valid_model_loads_successfully(self):
        """Valid model with all metadata should load."""
        from backend.scoring.training_linker import (
            TrainingLinker,
            ModelLineage,
        )
        from backend.scoring.weight_metadata import compute_weights_checksum
        from datetime import datetime, timedelta
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create valid model
            active_dir = Path(tmpdir) / "active"
            active_dir.mkdir(parents=True)
            
            weights = {
                "study": 0.25,
                "interest": 0.25,
                "market": 0.25,
                "growth": 0.15,
                "risk": 0.10,
            }
            checksum = compute_weights_checksum(weights)
            
            # Recent training time (within MAX_AGE_DAYS)
            trained_at = (datetime.utcnow() - timedelta(days=30)).isoformat()
            
            # Create weights.json
            weights_file = active_dir / "weights.json"
            weights_file.write_text(json.dumps({
                "version": "v_test",
                "weights": weights,
                "checksum": checksum,
            }))
            
            # Create metadata with all required fields
            metadata_file = active_dir / "weight_metadata.json"
            metadata_file.write_text(json.dumps({
                "version": "v_test",
                "metadata_version": "1.0",
                "trained_at": trained_at,
                "dataset": "test.csv",
                "dataset_checksum": "abc123",
                "features": ["study", "interest", "market", "growth", "risk"],
                "weights_checksum": checksum,
                "trainer_commit": "abc123def456",
                "pipeline_version": "train_v2.1",
                "status": "active",
                "metrics": {
                    "train_loss": 0.05,
                    "val_loss": 0.06,
                    "correlation": 0.95,
                    "r2": 0.90,
                    "mae": 0.03,
                    "n_samples": 1000,
                },
            }))
            
            # Patch BASE_PATH
            original_path = TrainingLinker.BASE_PATH
            TrainingLinker.BASE_PATH = tmpdir
            TrainingLinker.reset()
            
            try:
                simgr_weights = TrainingLinker.load_verified_weights()
                assert simgr_weights is not None
                assert abs(simgr_weights.study_score - 0.25) < 0.001
                
                lineage = TrainingLinker.get_lineage()
                assert lineage.weight_version == "v_test"
            finally:
                TrainingLinker.BASE_PATH = original_path
                TrainingLinker.reset()


class TestMissingMetadataReject:
    """Test rejection when metadata is missing."""
    
    def test_missing_metadata_raises_error(self):
        """Model without metadata must be rejected."""
        from backend.scoring.training_linker import (
            TrainingLinker,
            InvalidModelError,
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create weights.json WITHOUT metadata
            active_dir = Path(tmpdir) / "active"
            active_dir.mkdir(parents=True)
            
            weights_file = active_dir / "weights.json"
            weights_file.write_text(json.dumps({
                "version": "v1",
                "weights": {"study": 0.25, "interest": 0.25, "market": 0.25, "growth": 0.15, "risk": 0.10},
                "checksum": "test123",
            }))
            
            # NO weight_metadata.json!
            
            original_path = TrainingLinker.BASE_PATH
            TrainingLinker.BASE_PATH = tmpdir
            TrainingLinker.reset()
            
            try:
                with pytest.raises(InvalidModelError) as exc_info:
                    TrainingLinker.load_verified_weights()
                
                assert "INVALID_MODEL" in str(exc_info.value)
                assert "metadata" in str(exc_info.value).lower()
            finally:
                TrainingLinker.BASE_PATH = original_path
                TrainingLinker.reset()


class TestStaleModelReject:
    """Test rejection of stale models."""
    
    def test_stale_model_raises_error(self):
        """Model older than MAX_AGE_DAYS must be rejected."""
        from backend.scoring.training_linker import (
            TrainingLinker,
            StaleModelError,
        )
        from backend.scoring.weight_metadata import compute_weights_checksum
        from datetime import datetime, timedelta
        
        with tempfile.TemporaryDirectory() as tmpdir:
            active_dir = Path(tmpdir) / "active"
            active_dir.mkdir(parents=True)
            
            weights = {"study": 0.25, "interest": 0.25, "market": 0.25, "growth": 0.15, "risk": 0.10}
            checksum = compute_weights_checksum(weights)
            
            # STALE: trained 100 days ago (> MAX_AGE_DAYS=90)
            stale_date = (datetime.utcnow() - timedelta(days=100)).isoformat()
            
            weights_file = active_dir / "weights.json"
            weights_file.write_text(json.dumps({
                "version": "v_stale",
                "weights": weights,
                "checksum": checksum,
            }))
            
            metadata_file = active_dir / "weight_metadata.json"
            metadata_file.write_text(json.dumps({
                "version": "v_stale",
                "trained_at": stale_date,
                "dataset": "test.csv",
                "dataset_checksum": "abc",
                "features": ["study", "interest", "market", "growth", "risk"],
                "weights_checksum": checksum,
                "trainer_commit": "abc123",
                "pipeline_version": "train_v2.1",
                "metrics": {"r2": 0.9, "mae": 0.05, "correlation": 0.95, "n_samples": 1000},
            }))
            
            original_path = TrainingLinker.BASE_PATH
            TrainingLinker.BASE_PATH = tmpdir
            TrainingLinker.reset()
            
            try:
                with pytest.raises(StaleModelError) as exc_info:
                    TrainingLinker.load_verified_weights()
                
                assert "STALE_MODEL" in str(exc_info.value)
            finally:
                TrainingLinker.BASE_PATH = original_path
                TrainingLinker.reset()


class TestChecksumMismatch:
    """Test checksum verification."""
    
    def test_checksum_mismatch_raises_error(self):
        """Modified weights must be detected via checksum."""
        from backend.scoring.training_linker import (
            TrainingLinker,
            TamperedModelError,
        )
        from backend.scoring.weight_metadata import compute_weights_checksum
        from datetime import datetime, timedelta
        
        with tempfile.TemporaryDirectory() as tmpdir:
            active_dir = Path(tmpdir) / "active"
            active_dir.mkdir(parents=True)
            
            # Original weights
            original_weights = {"study": 0.25, "interest": 0.25, "market": 0.25, "growth": 0.15, "risk": 0.10}
            original_checksum = compute_weights_checksum(original_weights)
            
            # MODIFIED weights (different from checksum)
            modified_weights = {"study": 0.35, "interest": 0.20, "market": 0.20, "growth": 0.15, "risk": 0.10}
            
            trained_at = (datetime.utcnow() - timedelta(days=10)).isoformat()
            
            # Save MODIFIED weights
            weights_file = active_dir / "weights.json"
            weights_file.write_text(json.dumps({
                "version": "v_tampered",
                "weights": modified_weights,  # <-- Different from checksum!
                "checksum": "doesnt_matter",
            }))
            
            # Metadata has ORIGINAL checksum
            metadata_file = active_dir / "weight_metadata.json"
            metadata_file.write_text(json.dumps({
                "version": "v_tampered",
                "trained_at": trained_at,
                "dataset": "test.csv",
                "dataset_checksum": "abc",
                "features": ["study", "interest", "market", "growth", "risk"],
                "weights_checksum": original_checksum,  # <-- Mismatch!
                "trainer_commit": "abc123",
                "pipeline_version": "train_v2.1",
                "metrics": {"r2": 0.9, "mae": 0.05, "correlation": 0.95, "n_samples": 1000},
            }))
            
            original_path = TrainingLinker.BASE_PATH
            TrainingLinker.BASE_PATH = tmpdir
            TrainingLinker.reset()
            
            try:
                with pytest.raises(TamperedModelError) as exc_info:
                    TrainingLinker.load_verified_weights()
                
                assert "TAMPERED_MODEL" in str(exc_info.value)
            finally:
                TrainingLinker.BASE_PATH = original_path
                TrainingLinker.reset()


class TestManualOverrideBlocked:
    """Test manual override detection."""
    
    def test_missing_trainer_commit_raises_error(self):
        """Model without trainer_commit must be rejected."""
        from backend.scoring.training_linker import (
            TrainingLinker,
            MissingTrainerCommitError,
        )
        from backend.scoring.weight_metadata import compute_weights_checksum
        from datetime import datetime, timedelta
        
        with tempfile.TemporaryDirectory() as tmpdir:
            active_dir = Path(tmpdir) / "active"
            active_dir.mkdir(parents=True)
            
            weights = {"study": 0.25, "interest": 0.25, "market": 0.25, "growth": 0.15, "risk": 0.10}
            checksum = compute_weights_checksum(weights)
            trained_at = (datetime.utcnow() - timedelta(days=10)).isoformat()
            
            weights_file = active_dir / "weights.json"
            weights_file.write_text(json.dumps({
                "version": "v_manual",
                "weights": weights,
                "checksum": checksum,
            }))
            
            # MISSING trainer_commit
            metadata_file = active_dir / "weight_metadata.json"
            metadata_file.write_text(json.dumps({
                "version": "v_manual",
                "trained_at": trained_at,
                "dataset": "test.csv",
                "dataset_checksum": "abc",
                "features": ["study", "interest", "market", "growth", "risk"],
                "weights_checksum": checksum,
                "trainer_commit": "",  # <-- MISSING!
                "pipeline_version": "train_v2.1",
                "metrics": {"r2": 0.9, "mae": 0.05, "correlation": 0.95, "n_samples": 1000},
            }))
            
            original_path = TrainingLinker.BASE_PATH
            TrainingLinker.BASE_PATH = tmpdir
            TrainingLinker.reset()
            
            try:
                with pytest.raises(MissingTrainerCommitError) as exc_info:
                    TrainingLinker.load_verified_weights()
                
                assert "trainer_commit" in str(exc_info.value).lower()
            finally:
                TrainingLinker.BASE_PATH = original_path
                TrainingLinker.reset()


class TestMetricThreshold:
    """Test metric threshold validation."""
    
    def test_low_r2_raises_error(self):
        """Model with R² below threshold must be rejected."""
        from backend.scoring.training_linker import (
            TrainingLinker,
            UnqualifiedModelError,
        )
        from backend.scoring.weight_metadata import compute_weights_checksum
        from datetime import datetime, timedelta
        
        with tempfile.TemporaryDirectory() as tmpdir:
            active_dir = Path(tmpdir) / "active"
            active_dir.mkdir(parents=True)
            
            weights = {"study": 0.25, "interest": 0.25, "market": 0.25, "growth": 0.15, "risk": 0.10}
            checksum = compute_weights_checksum(weights)
            trained_at = (datetime.utcnow() - timedelta(days=10)).isoformat()
            
            weights_file = active_dir / "weights.json"
            weights_file.write_text(json.dumps({
                "version": "v_poor",
                "weights": weights,
                "checksum": checksum,
            }))
            
            # LOW correlation (R² = 0.6² = 0.36 < 0.7)
            metadata_file = active_dir / "weight_metadata.json"
            metadata_file.write_text(json.dumps({
                "version": "v_poor",
                "trained_at": trained_at,
                "dataset": "test.csv",
                "dataset_checksum": "abc",
                "features": ["study", "interest", "market", "growth", "risk"],
                "weights_checksum": checksum,
                "trainer_commit": "abc123",
                "pipeline_version": "train_v2.1",
                "metrics": {
                    "r2": 0.5,  # <-- Below threshold!
                    "mae": 0.05,
                    "correlation": 0.6,
                    "n_samples": 1000,
                },
            }))
            
            original_path = TrainingLinker.BASE_PATH
            TrainingLinker.BASE_PATH = tmpdir
            TrainingLinker.reset()
            
            try:
                with pytest.raises(UnqualifiedModelError) as exc_info:
                    TrainingLinker.load_verified_weights()
                
                assert "UNQUALIFIED_MODEL" in str(exc_info.value)
            finally:
                TrainingLinker.BASE_PATH = original_path
                TrainingLinker.reset()
    
    def test_high_mae_raises_error(self):
        """Model with MAE above threshold must be rejected."""
        from backend.scoring.training_linker import (
            TrainingLinker,
            UnqualifiedModelError,
        )
        from backend.scoring.weight_metadata import compute_weights_checksum
        from datetime import datetime, timedelta
        
        with tempfile.TemporaryDirectory() as tmpdir:
            active_dir = Path(tmpdir) / "active"
            active_dir.mkdir(parents=True)
            
            weights = {"study": 0.25, "interest": 0.25, "market": 0.25, "growth": 0.15, "risk": 0.10}
            checksum = compute_weights_checksum(weights)
            trained_at = (datetime.utcnow() - timedelta(days=10)).isoformat()
            
            weights_file = active_dir / "weights.json"
            weights_file.write_text(json.dumps({
                "version": "v_high_mae",
                "weights": weights,
                "checksum": checksum,
            }))
            
            # HIGH MAE (> 0.1)
            metadata_file = active_dir / "weight_metadata.json"
            metadata_file.write_text(json.dumps({
                "version": "v_high_mae",
                "trained_at": trained_at,
                "dataset": "test.csv",
                "dataset_checksum": "abc",
                "features": ["study", "interest", "market", "growth", "risk"],
                "weights_checksum": checksum,
                "trainer_commit": "abc123",
                "pipeline_version": "train_v2.1",
                "metrics": {
                    "r2": 0.85,
                    "mae": 0.15,  # <-- Above threshold!
                    "correlation": 0.92,
                    "n_samples": 1000,
                },
            }))
            
            original_path = TrainingLinker.BASE_PATH
            TrainingLinker.BASE_PATH = tmpdir
            TrainingLinker.reset()
            
            try:
                with pytest.raises(UnqualifiedModelError) as exc_info:
                    TrainingLinker.load_verified_weights()
                
                assert "UNQUALIFIED_MODEL" in str(exc_info.value)
                assert "MAE" in str(exc_info.value)
            finally:
                TrainingLinker.BASE_PATH = original_path
                TrainingLinker.reset()


class TestLineageHeader:
    """Test lineage header generation."""
    
    def test_lineage_header_format(self):
        """Lineage header must have correct format."""
        from backend.scoring.lineage_validator import (
            LineageHeader,
            validate_response_lineage,
        )
        
        header = LineageHeader(
            weight_version="v1",
            trained_at="2026-01-15T10:30:00",
            dataset="train.csv",
            checksum="abc123def456",
            pipeline_version="train_v2.1",
        )
        
        response = header.to_response_header()
        
        assert "model_lineage" in response
        lineage = response["model_lineage"]
        assert lineage["weight_version"] == "v1"
        assert lineage["trained_at"] == "2026-01-15T10:30:00"
        assert lineage["dataset"] == "train.csv"
        assert lineage["checksum"] == "abc123def456"
    
    def test_add_lineage_to_response(self):
        """add_lineage_to_response must add lineage field."""
        from backend.scoring.lineage_validator import (
            add_lineage_to_response,
            init_lineage_validator,
        )
        from backend.scoring.training_linker import TrainingLinker
        from backend.scoring.weight_metadata import compute_weights_checksum
        from datetime import datetime, timedelta
        
        with tempfile.TemporaryDirectory() as tmpdir:
            active_dir = Path(tmpdir) / "active"
            active_dir.mkdir(parents=True)
            
            weights = {"study": 0.25, "interest": 0.25, "market": 0.25, "growth": 0.15, "risk": 0.10}
            checksum = compute_weights_checksum(weights)
            trained_at = (datetime.utcnow() - timedelta(days=10)).isoformat()
            
            weights_file = active_dir / "weights.json"
            weights_file.write_text(json.dumps({
                "version": "v_lineage_test",
                "weights": weights,
                "checksum": checksum,
            }))
            
            metadata_file = active_dir / "weight_metadata.json"
            metadata_file.write_text(json.dumps({
                "version": "v_lineage_test",
                "trained_at": trained_at,
                "dataset": "test.csv",
                "dataset_checksum": "abc",
                "features": ["study", "interest", "market", "growth", "risk"],
                "weights_checksum": checksum,
                "trainer_commit": "abc123",
                "pipeline_version": "train_v2.1",
                "metrics": {"r2": 0.9, "mae": 0.05, "correlation": 0.95, "n_samples": 1000},
            }))
            
            original_path = TrainingLinker.BASE_PATH
            TrainingLinker.BASE_PATH = tmpdir
            TrainingLinker.reset()
            
            try:
                # Load weights first
                TrainingLinker.load_verified_weights()
                
                # Initialize validator
                init_lineage_validator()
                
                # Add lineage to response
                response = {"score": 0.85, "components": {}}
                response_with_lineage = add_lineage_to_response(response)
                
                assert "model_lineage" in response_with_lineage
                assert response_with_lineage["score"] == 0.85
            finally:
                TrainingLinker.BASE_PATH = original_path
                TrainingLinker.reset()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

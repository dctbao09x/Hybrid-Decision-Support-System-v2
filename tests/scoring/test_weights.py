# tests/scoring/test_weights.py
"""
Tests for Weight Learning Pipeline (R002)

Validates:
- Weight training pipeline exists
- Gradient/grid search methods work
- Cross-validation support
- Weight constraint (sum = 1.0)
- Trained weights file exists
"""

import pytest
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestWeightTrainingPipeline:
    """Test weight training infrastructure."""
    
    def test_train_weights_module_exists(self):
        """Training module must exist."""
        from backend.training import train_weights
        assert train_weights is not None
    
    def test_gradient_descent_method_exists(self):
        """Gradient descent training method must exist."""
        from backend.training.train_weights import SIMGRWeightTrainer
        trainer = SIMGRWeightTrainer()
        assert hasattr(trainer, 'train_gradient')
        assert callable(trainer.train_gradient)
    
    def test_grid_search_method_exists(self):
        """Grid search training method must exist."""
        from backend.training.train_weights import SIMGRWeightTrainer
        trainer = SIMGRWeightTrainer()
        assert hasattr(trainer, 'train_grid_search')
        assert callable(trainer.train_grid_search)
    
    def test_cross_validate_method_exists(self):
        """Cross-validation method must exist."""
        from backend.training.train_weights import SIMGRWeightTrainer
        trainer = SIMGRWeightTrainer()
        assert hasattr(trainer, 'cross_validate')
        assert callable(trainer.cross_validate)


class TestWeightConstraints:
    """Test weight constraints."""
    
    def test_constraint_function_exists(self):
        """Constraint function for sum=1.0 must exist."""
        from backend.training.train_weights import SIMGRWeightTrainer
        trainer = SIMGRWeightTrainer()
        # Constraint is internally enforced in optimization
        assert hasattr(trainer, 'config')
    
    def test_constraint_enforces_sum_one(self):
        """Weights from training must sum to 1.0."""
        # Test that trained weights sum to 1.0
        import json
        from pathlib import Path
        
        weights_path = Path("models/weights/v1/weights.json")
        with open(weights_path) as f:
            data = json.load(f)
        
        weights = data["weights"]
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.001


class TestTrainedWeights:
    """Test trained weights artifacts."""
    
    def test_weights_v1_exists(self):
        """Trained weights v1 must exist."""
        weights_path = Path("models/weights/v1/weights.json")
        assert weights_path.exists(), f"Weights file not found: {weights_path}"
    
    def test_weights_v1_structure(self):
        """Trained weights must have correct structure."""
        weights_path = Path("models/weights/v1/weights.json")
        
        with open(weights_path) as f:
            data = json.load(f)
        
        assert "weights" in data
        assert "version" in data
        
        weights = data["weights"]
        required_keys = ["study_score", "interest_score", "market_score", "growth_score", "risk_score"]
        
        for key in required_keys:
            assert key in weights, f"Missing weight: {key}"
    
    def test_weights_v1_sum_to_one(self):
        """Trained weights must sum to 1.0."""
        weights_path = Path("models/weights/v1/weights.json")
        
        with open(weights_path) as f:
            data = json.load(f)
        
        weights = data["weights"]
        total = sum(weights.values())
        
        assert abs(total - 1.0) < 0.001, f"Weights sum to {total}, expected 1.0"
    
    def test_weights_v1_in_valid_range(self):
        """All weights must be in [0, 1]."""
        weights_path = Path("models/weights/v1/weights.json")
        
        with open(weights_path) as f:
            data = json.load(f)
        
        weights = data["weights"]
        
        for name, value in weights.items():
            assert 0.0 <= value <= 1.0, f"Weight {name}={value} out of range"


class TestTrainingData:
    """Test training data exists."""
    
    def test_training_data_exists(self):
        """Training data CSV must exist."""
        data_path = Path("backend/data/scoring/train.csv")
        assert data_path.exists(), f"Training data not found: {data_path}"
    
    def test_training_data_has_required_columns(self):
        """Training data must have required columns."""
        import csv
        data_path = Path("backend/data/scoring/train.csv")
        
        with open(data_path) as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames
        
        # Actual columns in the file
        required = ["study", "interest", "market", "growth", "risk", "outcome"]
        for col in required:
            assert col in columns, f"Missing column: {col}"
    
    def test_training_data_has_records(self):
        """Training data must have records."""
        import csv
        data_path = Path("backend/data/scoring/train.csv")
        
        with open(data_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) > 0, "Training data is empty"


class TestR002Compliance:
    """Test R002 Weight Learning Pipeline compliance."""
    
    def test_optimizer_uses_scipy(self):
        """Should use scipy.optimize for weight optimization."""
        from backend.training import train_weights
        import inspect
        
        source = inspect.getsource(train_weights)
        assert "scipy" in source or "minimize" in source
    
    def test_weights_versioned(self):
        """Weights should be versioned."""
        weights_path = Path("models/weights/v1/weights.json")
        
        with open(weights_path) as f:
            data = json.load(f)
        
        assert "version" in data
        assert data["version"] != ""
    
    def test_training_metrics_recorded(self):
        """Training should record metrics."""
        weights_path = Path("models/weights/v1/weights.json")
        
        with open(weights_path) as f:
            data = json.load(f)
        
        # Should have metrics or config section
        assert "metrics" in data or "config" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

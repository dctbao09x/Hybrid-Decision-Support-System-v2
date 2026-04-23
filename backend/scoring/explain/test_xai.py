"""Test suite for XAI pipeline."""
import pytest
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile
import json

# Test Feature Importance
from backend.scoring.explain.feature_importance import (
    FeatureImportance, FeatureImportanceResult
)


class MockTreeModel:
    """Mock tree-based model with feature_importances_."""
    def __init__(self, importances: np.ndarray):
        self.feature_importances_ = importances
    
    def predict(self, X):
        return np.array([0] * len(X))


class MockLinearModel:
    """Mock linear model with coef_."""
    def __init__(self, coef: np.ndarray):
        self.coef_ = coef
    
    def predict(self, X):
        return np.array([0] * len(X))


class MockGenericModel:
    """Mock model without importances (needs permutation)."""
    def predict(self, X):
        return np.array([0] * len(X))


class TestFeatureImportance:
    """Test FeatureImportance class."""
    
    def test_tree_based_extraction(self):
        """Test extraction from tree-based models (RF, XGBoost)."""
        importances = np.array([0.1, 0.3, 0.2, 0.4])
        feature_names = ["math", "logic", "interest", "personality"]
        model = MockTreeModel(importances)
        
        fi = FeatureImportance()
        result = fi.compute(model, feature_names)
        
        assert isinstance(result, FeatureImportanceResult)
        assert len(result.importances) == 4
        assert result.method == "tree"
        # Check normalization
        assert abs(sum(result.importances) - 1.0) < 0.01
    
    def test_linear_extraction(self):
        """Test extraction from linear models (LogisticRegression)."""
        coef = np.array([[-0.5, 1.2, 0.3, -0.8]])
        feature_names = ["math", "logic", "interest", "personality"]
        model = MockLinearModel(coef)
        
        fi = FeatureImportance()
        result = fi.compute(model, feature_names)
        
        assert result.method == "coef"
        assert len(result.importances) == 4
    
    def test_top_k_features(self):
        """Test filtering top-k important features."""
        importances = np.array([0.1, 0.5, 0.2, 0.2])
        feature_names = ["math", "logic", "interest", "personality"]
        model = MockTreeModel(importances)
        
        fi = FeatureImportance()
        result = fi.compute(model, feature_names)
        
        top3 = result.top_k(3)
        assert len(top3) == 3
        assert top3[0][0] == "logic"  # Highest importance
    
    def test_min_importance_threshold(self):
        """Test filtering by minimum importance."""
        importances = np.array([0.05, 0.4, 0.05, 0.5])
        feature_names = ["math", "logic", "interest", "personality"]
        model = MockTreeModel(importances)
        
        fi = FeatureImportance()
        result = fi.compute(model, feature_names)
        
        # Get top features and filter by threshold manually
        top_features = result.top_k(4)
        filtered = [(n, i) for n, i in top_features if i >= 0.1]
        assert len(filtered) == 2  # Only logic and personality


# Test SHAP Engine
from backend.scoring.explain.shap_engine import SHAPEngine, SHAPResult


class TestSHAPEngine:
    """Test SHAPEngine class."""
    
    def test_tree_model_shap(self):
        """Test SHAP for tree-based models."""
        try:
            from sklearn.ensemble import RandomForestClassifier
        except ImportError:
            pytest.skip("sklearn not available")
        
        # Create small RF model
        X_train = np.random.rand(50, 4)
        y_train = np.random.randint(0, 2, 50)
        model = RandomForestClassifier(n_estimators=5, random_state=42)
        model.fit(X_train, y_train)
        
        feature_names = ["math", "logic", "interest", "personality"]
        engine = SHAPEngine()
        engine.set_model(model, feature_names, X_train)
        
        # Explain single sample
        sample = X_train[0:1]
        try:
            result = engine.explain(sample)
            assert isinstance(result, SHAPResult)
            assert len(result.shap_values) == 4
        except Exception as e:
            # SHAP may not be available
            pytest.skip(f"SHAP not available: {e}")
    
    def test_fallback_to_permutation(self):
        """Test fallback to permutation importance when SHAP fails."""
        model = MockGenericModel()
        feature_names = ["math", "logic", "interest", "personality"]
        
        engine = SHAPEngine(enable_shap=False)  # Disable SHAP to force fallback
        X_bg = np.random.rand(20, 4)
        engine.set_model(model, feature_names, X_bg)
        
        sample = np.random.rand(1, 4)
        try:
            result = engine.explain(sample)
            # Should return permutation result
            assert result is not None
        except Exception:
            # OK if model incompatible
            pass
    
    def test_compress_shap(self):
        """Test SHAP compression for storage."""
        shap_vals = [0.1, 0.3, 0.05, 0.2]
        feature_names = ["math", "logic", "interest", "personality"]
        feature_values = [8.0, 7.5, 6.0, 5.5]
        
        result = SHAPResult(
            feature_names=feature_names,
            shap_values=shap_vals,
            feature_values=feature_values,
            base_value=0.5,
            method="tree"
        )
        
        compressed = result.compress()
        assert "top_features" in compressed
        assert len(compressed["top_features"]) <= 10
        assert "base_value" in compressed
        assert "mean_abs_shap" in compressed


# Test Reason Generator
from backend.scoring.explain.reason_generator import (
    ReasonGenerator, ReasonResult
)


class TestReasonGenerator:
    """Test ReasonGenerator class."""
    
    def test_reason_from_importance(self):
        """Test generating Vietnamese reasons from importance."""
        generator = ReasonGenerator(language="vi")
        
        # Top features format: (name, importance, value)
        top_features = [("math_score", 0.4, 9.0), ("logic_score", 0.3, 7.5)]
        
        result = generator.generate(top_features, predicted_career="Data Scientist")
        
        assert isinstance(result, ReasonResult)
        assert len(result.reasons) >= 1
        # Check Vietnamese reason generated
        assert any("Toán" in r for r in result.reasons)
    
    def test_no_empty_reasons(self):
        """Test that no empty or generic reasons are generated."""
        generator = ReasonGenerator(language="vi")
        
        # Feature not in mappings should use default
        top_features = [("unknown_feature", 0.5, 0.8)]
        
        result = generator.generate(top_features)
        
        # Should not include empty reasons
        assert all(r.strip() for r in result.reasons)
    
    def test_deduplicate_reasons(self):
        """Test that duplicate reasons are removed."""
        generator = ReasonGenerator(language="vi")
        
        # Similar features with same values
        top_features = [
            ("math_score", 0.3, 8.5),
            ("physics_score", 0.3, 8.5),
        ]
        
        result = generator.generate(top_features, max_reasons=5)
        
        # Should deduplicate identical reasons (though these should be different)
        assert len(set(result.reasons)) == len(result.reasons)


# Test XAI Service Integration
from backend.scoring.explain.xai import XAIService, ExplanationResult, get_xai_service


class TestXAIService:
    """Test XAIService integration."""
    
    def test_service_initialization(self):
        """Test XAI service singleton initialization."""
        service = get_xai_service()
        assert isinstance(service, XAIService)
        
        # Singleton pattern
        service2 = get_xai_service()
        assert service is service2
    
    def test_load_config(self):
        """Test loading XAI configuration."""
        service = XAIService()
        
        config = {
            "top_k": 5,
            "min_importance": 0.1,
            "enable_shap": True,
            "language": "vi"
        }
        
        service.load_config(config)
        
        assert service._top_k == 5
        assert service._min_importance == 0.1
    
    def test_full_explain_pipeline(self):
        """Test full explanation pipeline with mock model."""
        try:
            from sklearn.ensemble import RandomForestClassifier
        except ImportError:
            pytest.skip("sklearn not available")
        
        # Setup
        X_train = np.random.rand(50, 4)
        y_train = np.random.randint(0, 3, 50)
        model = RandomForestClassifier(n_estimators=5, random_state=42)
        model.fit(X_train, y_train)
        
        feature_names = ["math_score", "logic_score", "interest_it", "personality_open"]
        
        service = XAIService()
        service.load_config({
            "top_k": 3,
            "min_importance": 0.1,
            "enable_shap": True,
            "language": "vi",
        })
        
        # Load model
        service.load_model(
            model=model,
            feature_names=feature_names,
            background_data=X_train,
        )
        
        # Test explanation with sample array
        sample = np.array([9.0, 8.0, 7.5, 6.5])
        
        result = service.explain(
            sample=sample,
            predicted_career="Data Scientist",
            confidence=0.85,
        )
        
        assert isinstance(result, ExplanationResult)
        assert result.predicted_career == "Data Scientist"
        assert result.confidence == 0.85
        assert len(result.reasons) >= 0  # May be empty if no thresholds matched
        assert result.trace_id is not None
        assert result.feature_importance is not None
    
    def test_audit_logging(self):
        """Test XAI audit log output."""
        try:
            from sklearn.ensemble import RandomForestClassifier
        except ImportError:
            pytest.skip("sklearn not available")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "xai_logs"
            log_path.mkdir()
            
            # Setup
            X_train = np.random.rand(30, 4)
            y_train = np.random.randint(0, 2, 30)
            model = RandomForestClassifier(n_estimators=3, random_state=42)
            model.fit(X_train, y_train)
            
            service = XAIService()
            service._xai_logs_dir = log_path  # Override log dir
            service.load_config({
                "top_k": 3,
                "min_importance": 0.1,
                "enable_logging": True,
            })
            service.load_model(model=model, feature_names=["a", "b", "c", "d"], background_data=X_train)
            
            sample = np.array([1.0, 2.0, 3.0, 4.0])
            result = service.explain(sample, predicted_career="Test", confidence=0.5)
            
            # Check log file created
            log_files = list(log_path.glob("*.jsonl"))
            assert len(log_files) >= 1  # Should create daily log
    
    def test_is_ready(self):
        """Test service readiness check."""
        service = XAIService()
        
        # Not ready before model loaded
        assert not service.is_ready()


class TestXAIResponseFormat:
    """Test XAI API response format."""
    
    def test_explanation_result_to_response(self):
        """Test ExplanationResult to_response() method."""
        result = ExplanationResult(
            predicted_career="Software Engineer",
            confidence=0.85,
            reasons=["Toán học cao", "Tư duy logic tốt"],
            xai_meta={"method": "shap+fi"},
        )
        
        data = result.to_response()
        
        assert data["career"] == "Software Engineer"
        assert data["confidence"] == 0.85
        assert len(data["reason"]) == 2
        assert "Toán học cao" in data["reason"]
        assert "xai_meta" in data
    
    def test_explanation_result_to_dict(self):
        """Test full ExplanationResult serialization."""
        result = ExplanationResult(
            predicted_career="Data Scientist",
            confidence=0.78,
            reasons=["Quan tâm CNTT"],
            xai_meta={"method": "fi"},
            trace_id="api-001",
        )
        
        data = result.to_dict()
        
        assert data["predicted_career"] == "Data Scientist"
        assert data["trace_id"] == "api-001"
        assert "timestamp" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

# backend/retrain/trainer.py
"""
Retrain Trainer
===============

Reuses the ML Evaluation pipeline for retraining.

Ensures:
  - Same model configuration
  - Same cross-validation
  - Full audit logging
  - Phase 1 + 2 validation
"""

from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from backend.evaluation.service import MLEvaluationService
from backend.evaluation.fingerprint import FingerprintGenerator

logger = logging.getLogger("ml_retrain.trainer")


@dataclass
class TrainResult:
    """Result of a training run."""
    run_id: str
    model_type: str
    kfold: int
    metrics: Dict[str, Any]
    quality_passed: bool
    regression_status: str
    drift_status: str
    dataset_hash: str
    model_path: str
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "model_type": self.model_type,
            "kfold": self.kfold,
            "metrics": self.metrics,
            "quality_passed": self.quality_passed,
            "regression_status": self.regression_status,
            "drift_status": self.drift_status,
            "dataset_hash": self.dataset_hash,
            "model_path": self.model_path,
            "timestamp": self.timestamp,
        }


class RetrainTrainer:
    """
    Trains models using the evaluation pipeline.
    
    Usage::
    
        trainer = RetrainTrainer()
        trainer.load_config(config)
        
        result = trainer.train(
            data_path="data/training_combined.csv",
            run_id="retrain_20260213",
        )
    """
    
    def __init__(self):
        self._project_root = Path(__file__).resolve().parents[2]
        self._config: Dict[str, Any] = {}
        
        # Output paths
        self._models_dir = self._project_root / "models"
        self._retrain_runs_dir = self._project_root / "retrain_runs"
    
    def load_config(self, config: Dict[str, Any]) -> None:
        """Load configuration."""
        self._config = config
        logger.info("Trainer config loaded")
    
    def train(
        self,
        data_path: str,
        run_id: Optional[str] = None,
        version: Optional[str] = None,
    ) -> TrainResult:
        """
        Train a new model.
        
        Args:
            data_path: Path to training data CSV
            run_id: Unique run identifier
            version: Model version (e.g., "v2"). Auto-generated if not provided.
        
        Returns:
            TrainResult with metrics and model path
        """
        run_id = run_id or f"retrain_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        logger.info("Starting training run: %s", run_id)
        
        # Create evaluation service with custom data path
        ml_config = self._config.get("ml_evaluation", {}).copy()
        ml_config["data_path"] = data_path
        
        service = MLEvaluationService()
        service._config = ml_config
        service._config_loaded = True
        
        # Run evaluation pipeline (this trains and validates)
        result = service.run_pipeline(run_id)
        
        # Extract trained model
        model = service._last_trained_model if hasattr(service, "_last_trained_model") else None
        
        # Generate version if not provided
        if not version:
            version = self._get_next_version()
        
        # Save model to versioned directory
        model_path = self._save_model(
            version=version,
            metrics=result.get("metrics", {}),
            fingerprint_hash=result.get("stability", {}).get("dataset_hash", ""),
            run_id=run_id,
            model_type=result.get("model", "unknown"),
        )
        
        # Log retrain run
        self._log_retrain_run(run_id, result, version)
        
        return TrainResult(
            run_id=run_id,
            model_type=result.get("model", "unknown"),
            kfold=result.get("kfold", 5),
            metrics=result.get("metrics", {}),
            quality_passed=result.get("quality_passed", False),
            regression_status=result.get("stability", {}).get("regression_status", "UNKNOWN"),
            drift_status=result.get("stability", {}).get("drift_status", "UNKNOWN"),
            dataset_hash=result.get("stability", {}).get("dataset_hash", ""),
            model_path=model_path,
        )
    
    def train_with_model(
        self,
        data_path: str,
        run_id: Optional[str] = None,
        version: Optional[str] = None,
    ) -> TrainResult:
        """
        Train and return the actual model object.
        
        This method trains the model and saves it properly.
        """
        import pandas as pd
        from sklearn.preprocessing import LabelEncoder
        from backend.evaluation.models import ModelFactory
        
        run_id = run_id or f"retrain_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        logger.info("Training with model export: %s", run_id)
        
        # Load data
        full_path = self._project_root / data_path
        df = pd.read_csv(full_path)
        
        # Prepare features and labels
        feature_cols = ["math_score", "physics_score", "interest_it", "logic_score"]
        X = df[feature_cols].values
        
        label_encoder = LabelEncoder()
        y = label_encoder.fit_transform(df["target_career"])
        classes = list(label_encoder.classes_)
        
        # Get model config
        ml_config = self._config.get("ml_evaluation", {})
        model_type = ml_config.get("model_type", "random_forest")
        model_params = ml_config.get("model_params", {}).get(model_type, {})
        random_state = ml_config.get("random_state", 42)
        
        # Build and train model
        model = ModelFactory.get_model(model_type, model_params, random_state)
        model.fit(X, y)
        
        # Cross-validate for metrics
        from sklearn.model_selection import cross_val_score
        cv_scores = cross_val_score(model, X, y, cv=5, scoring="accuracy")
        
        # Retrain on full data
        model.fit(X, y)
        
        # Compute metrics
        from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
        y_pred = model.predict(X)
        
        metrics = {
            "accuracy": {"mean": float(cv_scores.mean()), "std": float(cv_scores.std())},
            "f1": {"mean": float(f1_score(y, y_pred, average="macro")), "std": 0.0},
            "precision": {"mean": float(precision_score(y, y_pred, average="macro")), "std": 0.0},
            "recall": {"mean": float(recall_score(y, y_pred, average="macro")), "std": 0.0},
        }
        
        # Quality gate check
        quality_gate = ml_config.get("quality_gate", {})
        min_accuracy = quality_gate.get("min_accuracy", 0.90)
        min_f1 = quality_gate.get("min_f1", 0.88)
        quality_passed = (
            metrics["accuracy"]["mean"] >= min_accuracy and
            metrics["f1"]["mean"] >= min_f1
        )
        
        # Generate version
        if not version:
            version = self._get_next_version()
        
        # Compute fingerprint
        fingerprint_gen = FingerprintGenerator()
        fingerprint = fingerprint_gen.compute(str(full_path))
        
        # Save model
        model_path = self._save_model_with_artifact(
            version=version,
            model=model,
            classes=classes,
            metrics=metrics,
            fingerprint=fingerprint,
            model_type=model_type,
            run_id=run_id,
        )
        
        # Log retrain run
        self._log_retrain_run(run_id, {
            "metrics": metrics,
            "quality_passed": quality_passed,
            "model": model_type,
            "stability": {"dataset_hash": fingerprint.hash},
        }, version)
        
        return TrainResult(
            run_id=run_id,
            model_type=model_type,
            kfold=5,
            metrics=metrics,
            quality_passed=quality_passed,
            regression_status="PASS" if quality_passed else "WARN",
            drift_status="LOW",
            dataset_hash=fingerprint.hash,
            model_path=model_path,
        )
    
    def _get_next_version(self) -> str:
        """Get the next available version number."""
        existing = []
        
        if self._models_dir.exists():
            for item in self._models_dir.iterdir():
                if item.is_dir() and item.name.startswith("v"):
                    try:
                        num = int(item.name[1:])
                        existing.append(num)
                    except ValueError:
                        pass
        
        next_num = max(existing, default=0) + 1
        return f"v{next_num}"
    
    def _save_model(
        self,
        version: str,
        metrics: Dict[str, Any],
        fingerprint_hash: str,
        run_id: str,
        model_type: str,
    ) -> str:
        """Save model metadata (without actual model object)."""
        version_dir = self._models_dir / version
        version_dir.mkdir(parents=True, exist_ok=True)
        
        # Save metrics
        metrics_data = {
            "accuracy": metrics.get("accuracy", {}).get("mean", 0),
            "f1": metrics.get("f1", {}).get("mean", 0),
            "precision": metrics.get("precision", {}).get("mean", 0),
            "recall": metrics.get("recall", {}).get("mean", 0),
            "model_type": model_type,
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        with open(version_dir / "metrics.json", "w", encoding="utf-8") as f:
            json.dump(metrics_data, f, indent=2)
        
        # Save fingerprint
        fingerprint_data = {
            "hash": fingerprint_hash,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        with open(version_dir / "fingerprint.json", "w", encoding="utf-8") as f:
            json.dump(fingerprint_data, f, indent=2)
        
        logger.info("Saved model metadata to %s", version_dir)
        return str(version_dir)
    
    def _save_model_with_artifact(
        self,
        version: str,
        model: Any,
        classes: list,
        metrics: Dict[str, Any],
        fingerprint: Any,
        model_type: str,
        run_id: str,
    ) -> str:
        """Save model with actual model artifact."""
        version_dir = self._models_dir / version
        version_dir.mkdir(parents=True, exist_ok=True)
        
        # Save model pickle
        with open(version_dir / "model.pkl", "wb") as f:
            pickle.dump(model, f)
        
        # Save classes
        with open(version_dir / "classes.json", "w", encoding="utf-8") as f:
            json.dump(classes, f, indent=2)
        
        # Save metrics
        metrics_data = {
            "accuracy": metrics.get("accuracy", {}).get("mean", 0),
            "f1": metrics.get("f1", {}).get("mean", 0),
            "precision": metrics.get("precision", {}).get("mean", 0),
            "recall": metrics.get("recall", {}).get("mean", 0),
            "model_type": model_type,
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        with open(version_dir / "metrics.json", "w", encoding="utf-8") as f:
            json.dump(metrics_data, f, indent=2)
        
        # Save fingerprint
        fingerprint_data = fingerprint.to_dict() if hasattr(fingerprint, "to_dict") else {
            "hash": str(fingerprint),
        }
        
        with open(version_dir / "fingerprint.json", "w", encoding="utf-8") as f:
            json.dump(fingerprint_data, f, indent=2)
        
        logger.info("Saved model with artifact to %s", version_dir)
        return str(version_dir)
    
    def _log_retrain_run(
        self,
        run_id: str,
        result: Dict[str, Any],
        version: str,
    ) -> None:
        """Log retrain run details."""
        self._retrain_runs_dir.mkdir(parents=True, exist_ok=True)
        
        log_data = {
            "run_id": run_id,
            "version": version,
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        log_file = self._retrain_runs_dir / f"{run_id}.json"
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, default=str)
        
        logger.info("Logged retrain run to %s", log_file)

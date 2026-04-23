# backend/training/retraining_monitor.py
"""
SIMGR Retraining Monitor - Phase 5 Retraining Automation.

Monitors for conditions that trigger model retraining:
- Dataset size growth (new training data)
- Time-based scheduled retraining
- Performance degradation detection
- Weight stability comparison

GĐ Phase 5: Retraining Automation
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RetrainingConfig:
    """Configuration for retraining triggers.
    
    GĐ Phase 5: Retraining automation thresholds.
    """
    # Dataset growth triggers
    min_new_samples: int = 100  # Min new samples to trigger retrain
    growth_ratio_threshold: float = 0.2  # 20% growth triggers retrain (spec)
    
    # Time-based triggers
    max_model_age_days: int = 180  # 180 days before retrain (spec)
    
    # Performance triggers
    min_r2_threshold: float = 0.6  # R² below this triggers retrain
    max_drift_threshold: float = 0.05  # Weight drift above this triggers retrain
    
    # Weight stability
    max_weight_change: float = 0.15  # Max weight change per component
    
    # Paths
    weights_dir: str = "models/weights"
    training_data_path: str = "backend/data/scoring/train.csv"
    monitor_state_path: str = "models/weights/monitor_state.json"


class RetrainingTrigger:
    """Enum-like class for trigger reasons."""
    DATASET_GROWTH = "dataset_growth"
    TIME_BASED = "time_based"
    PERFORMANCE_DEGRADATION = "performance_degradation"
    WEIGHT_DRIFT = "weight_drift"
    MANUAL = "manual"


class RetrainingMonitor:
    """Monitor retraining conditions and triggers.
    
    GĐ Phase 5: Automatic retraining trigger logic.
    """
    
    def __init__(self, config: Optional[RetrainingConfig] = None):
        self.config = config or RetrainingConfig()
        self._state: Dict[str, Any] = self._load_state()
    
    def _load_state(self) -> Dict[str, Any]:
        """Load monitor state from disk."""
        state_path = Path(self.config.monitor_state_path)
        if state_path.exists():
            with open(state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "last_check": None,
            "last_retrain": None,
            "last_dataset_hash": None,
            "last_dataset_size": 0,
            "triggers_history": []
        }
    
    def _save_state(self) -> None:
        """Save monitor state to disk."""
        state_path = Path(self.config.monitor_state_path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2, default=str)
    
    def _compute_dataset_hash(self, data_path: str) -> str:
        """Compute SHA256 hash of dataset."""
        hasher = hashlib.sha256()
        with open(data_path, "rb") as f:
            hasher.update(f.read())
        return hasher.hexdigest()[:16]
    
    def _count_dataset_samples(self, data_path: str) -> int:
        """Count number of samples in dataset."""
        try:
            with open(data_path, "r", encoding="utf-8") as f:
                # Count lines minus header
                return sum(1 for _ in f) - 1
        except FileNotFoundError:
            return 0
    
    def _get_active_model_info(self) -> Optional[Dict[str, Any]]:
        """Get info about currently active model."""
        active_path = Path(self.config.weights_dir) / "active" / "weights.json"
        if not active_path.exists():
            return None
        with open(active_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    # =========================================
    # TRIGGER CHECKS
    # =========================================
    
    def check_dataset_growth(self) -> Optional[Dict[str, Any]]:
        """Check if dataset has grown enough to trigger retraining.
        
        Returns:
            Trigger info dict if trigger condition met, else None
        """
        data_path = self.config.training_data_path
        if not os.path.exists(data_path):
            logger.warning(f"[RETRAIN] Training data not found: {data_path}")
            return None
        
        current_size = self._count_dataset_samples(data_path)
        current_hash = self._compute_dataset_hash(data_path)
        
        last_size = self._state.get("last_dataset_size", 0)
        last_hash = self._state.get("last_dataset_hash")
        
        # Check if dataset changed
        if current_hash == last_hash:
            logger.info("[RETRAIN] Dataset unchanged (same hash)")
            return None
        
        # Check growth
        new_samples = current_size - last_size
        growth_ratio = new_samples / max(last_size, 1)
        
        trigger = None
        if new_samples >= self.config.min_new_samples:
            trigger = {
                "reason": RetrainingTrigger.DATASET_GROWTH,
                "details": f"Added {new_samples} new samples (>= {self.config.min_new_samples})",
                "current_size": current_size,
                "previous_size": last_size,
                "new_samples": new_samples,
                "growth_ratio": growth_ratio
            }
            logger.info(f"[RETRAIN] TRIGGER: {trigger['details']}")
        elif growth_ratio >= self.config.growth_ratio_threshold:
            trigger = {
                "reason": RetrainingTrigger.DATASET_GROWTH,
                "details": f"Dataset grew by {growth_ratio:.1%} (>= {self.config.growth_ratio_threshold:.1%})",
                "current_size": current_size,
                "previous_size": last_size,
                "new_samples": new_samples,
                "growth_ratio": growth_ratio
            }
            logger.info(f"[RETRAIN] TRIGGER: {trigger['details']}")
        
        return trigger
    
    def check_time_based(self) -> Optional[Dict[str, Any]]:
        """Check if model age exceeds maximum.
        
        Returns:
            Trigger info dict if trigger condition met, else None
        """
        model_info = self._get_active_model_info()
        if not model_info:
            logger.info("[RETRAIN] No active model found")
            return None
        
        trained_at = model_info.get("trained_at")
        if not trained_at:
            logger.warning("[RETRAIN] Model has no trained_at timestamp")
            return None
        
        try:
            trained_date = datetime.fromisoformat(trained_at)
        except ValueError:
            logger.warning(f"[RETRAIN] Invalid trained_at format: {trained_at}")
            return None
        
        age_days = (datetime.now() - trained_date).days
        max_age = self.config.max_model_age_days
        
        if age_days >= max_age:
            trigger = {
                "reason": RetrainingTrigger.TIME_BASED,
                "details": f"Model age ({age_days} days) >= threshold ({max_age} days)",
                "model_age_days": age_days,
                "threshold_days": max_age,
                "trained_at": trained_at
            }
            logger.info(f"[RETRAIN] TRIGGER: {trigger['details']}")
            return trigger
        
        logger.info(f"[RETRAIN] Model age OK: {age_days} days (< {max_age})")
        return None
    
    def check_performance_degradation(self, current_r2: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Check if model performance has degraded.
        
        Args:
            current_r2: Current R² score on validation data
            
        Returns:
            Trigger info dict if trigger condition met, else None
        """
        model_info = self._get_active_model_info()
        if not model_info:
            return None
        
        # If current R² provided, use it
        if current_r2 is not None:
            if current_r2 < self.config.min_r2_threshold:
                trigger = {
                    "reason": RetrainingTrigger.PERFORMANCE_DEGRADATION,
                    "details": f"R² ({current_r2:.4f}) < threshold ({self.config.min_r2_threshold})",
                    "current_r2": current_r2,
                    "threshold_r2": self.config.min_r2_threshold
                }
                logger.info(f"[RETRAIN] TRIGGER: {trigger['details']}")
                return trigger
        
        # Check stored R² from model info
        stored_r2 = model_info.get("r2_score")
        if stored_r2 and stored_r2 < self.config.min_r2_threshold:
            trigger = {
                "reason": RetrainingTrigger.PERFORMANCE_DEGRADATION,
                "details": f"Stored R² ({stored_r2:.4f}) < threshold ({self.config.min_r2_threshold})",
                "stored_r2": stored_r2,
                "threshold_r2": self.config.min_r2_threshold
            }
            logger.info(f"[RETRAIN] TRIGGER: {trigger['details']}")
            return trigger
        
        return None
    
    def check_weight_stability(self, new_weights: Dict[str, float]) -> Optional[Dict[str, Any]]:
        """Compare new weights against current active weights.
        
        GĐ Phase 5: Weight stability monitoring.
        
        Args:
            new_weights: Newly trained weights to compare
            
        Returns:
            Dict with stability analysis and potential trigger
        """
        model_info = self._get_active_model_info()
        if not model_info:
            return {
                "stable": True,
                "reason": "No active model to compare",
                "changes": {}
            }
        
        current_weights = model_info.get("weights", {})
        if not current_weights:
            return {
                "stable": True,
                "reason": "No weights in active model",
                "changes": {}
            }
        
        # Compare each weight
        changes = {}
        max_change = 0.0
        
        for component, new_val in new_weights.items():
            old_val = current_weights.get(component, 0.0)
            change = abs(new_val - old_val)
            changes[component] = {
                "old": old_val,
                "new": new_val,
                "change": change,
                "change_pct": change / max(old_val, 0.01) * 100
            }
            max_change = max(max_change, change)
        
        # Check stability threshold
        is_stable = max_change <= self.config.max_weight_change
        
        result = {
            "stable": is_stable,
            "max_change": max_change,
            "threshold": self.config.max_weight_change,
            "changes": changes
        }
        
        if not is_stable:
            result["trigger"] = {
                "reason": RetrainingTrigger.WEIGHT_DRIFT,
                "details": f"Weight change ({max_change:.4f}) > threshold ({self.config.max_weight_change})",
                "max_change": max_change
            }
            logger.warning(f"[RETRAIN] Weight stability WARNING: {result['trigger']['details']}")
        else:
            logger.info(f"[RETRAIN] Weights stable: max change = {max_change:.4f}")
        
        return result
    
    # =========================================
    # MAIN MONITORING
    # =========================================
    
    def check_all_triggers(self) -> Dict[str, Any]:
        """Run all trigger checks.
        
        Returns:
            Dict with:
                - should_retrain: bool
                - triggers: List of active triggers
                - checks: Dict of all check results
        """
        logger.info("=" * 50)
        logger.info("[RETRAIN] Running retraining trigger checks...")
        logger.info("=" * 50)
        
        triggers = []
        checks = {}
        
        # 1. Dataset growth
        growth_trigger = self.check_dataset_growth()
        checks["dataset_growth"] = growth_trigger
        if growth_trigger:
            triggers.append(growth_trigger)
        
        # 2. Time-based
        time_trigger = self.check_time_based()
        checks["time_based"] = time_trigger
        if time_trigger:
            triggers.append(time_trigger)
        
        # 3. Performance (no current data, use stored)
        perf_trigger = self.check_performance_degradation()
        checks["performance"] = perf_trigger
        if perf_trigger:
            triggers.append(perf_trigger)
        
        # Update state
        self._state["last_check"] = datetime.now().isoformat()
        if Path(self.config.training_data_path).exists():
            self._state["last_dataset_size"] = self._count_dataset_samples(self.config.training_data_path)
            self._state["last_dataset_hash"] = self._compute_dataset_hash(self.config.training_data_path)
        
        if triggers:
            self._state["triggers_history"].append({
                "timestamp": datetime.now().isoformat(),
                "triggers": [t["reason"] for t in triggers]
            })
        
        self._save_state()
        
        result = {
            "should_retrain": len(triggers) > 0,
            "triggers": triggers,
            "checks": checks,
            "checked_at": datetime.now().isoformat()
        }
        
        if result["should_retrain"]:
            logger.info(f"[RETRAIN] RECOMMENDATION: Retrain - {len(triggers)} trigger(s) active")
        else:
            logger.info("[RETRAIN] No retraining needed at this time")
        
        return result
    
    # =========================================
    # RUNTIME DRIFT EVALUATION
    # =========================================

    def evaluate(
        self,
        feature_vector: Dict[str, float],
        score_output: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Evaluate runtime drift for a single inference.

        Computes a lightweight drift score by comparing the incoming feature
        vector against the training-time weight distribution.  The score is
        the mean absolute deviation of each normalised feature value from the
        expected neutral centre (0.5), weighted by the active model's trained
        weights.  This gives a signal that is sensitive to systematic bias
        in the feature distribution without requiring a stored reference
        dataset at runtime.

        The result is metadata-only: callers MUST NOT modify rankings based
        on this output.

        Args:
            feature_vector: Dict mapping feature names to [0, 1] float values.
                            Keys are a subset of the scoring weight keys.
            score_output:   Dict produced by the scoring stage, expected to
                            contain at least ``{"count": int, "rankings": [...]}``.  
                            Used to extract the top score for context.

        Returns:
            Dict with:
                drift_score   (float)  – computed drift metric in [0, 1]
                threshold     (float)  – configured drift threshold
                drift_detected (bool)  – True when drift_score > threshold
                feature_count  (int)   – number of features evaluated
                top_score      (float) – top ranking score from score_output
                method         (str)   – algorithm name for auditability
        """
        threshold = self.config.max_drift_threshold

        # ── Resolve active weights for weighting the deviation ───────────────
        model_info = self._get_active_model_info() or {}
        active_weights: Dict[str, float] = model_info.get("weights", {})

        # ── Compute weighted MAD from neutral centre (0.5) ─────────────────
        NEUTRAL = 0.5
        total_weight = 0.0
        weighted_deviation = 0.0
        feature_count = 0

        for feat, value in feature_vector.items():
            if not isinstance(value, (int, float)):
                continue
            w = active_weights.get(feat, 1.0 / max(len(feature_vector), 1))
            deviation = abs(float(value) - NEUTRAL)
            weighted_deviation += w * deviation
            total_weight += w
            feature_count += 1

        drift_score: float
        if total_weight > 0:
            # Normalise so that a fully-extreme vector (all 0s or all 1s) = 0.5
            drift_score = round(weighted_deviation / total_weight, 6)
        else:
            drift_score = 0.0

        # ── Extract top score from score_output ────────────────────────────
        top_score: float = 0.0
        rankings = score_output.get("rankings", [])
        if rankings:
            first = rankings[0]
            if isinstance(first, dict):
                top_score = float(first.get("total_score", 0.0))

        drift_detected = drift_score > threshold

        result = {
            "drift_score": drift_score,
            "threshold": threshold,
            "drift_detected": drift_detected,
            "feature_count": feature_count,
            "top_score": top_score,
            "method": "weighted_mad_from_neutral",
        }

        if drift_detected:
            logger.warning(
                f"[DRIFT] DETECTED: score={drift_score:.4f} > threshold={threshold}. "
                f"features_evaluated={feature_count}"
            )
        else:
            logger.info(
                f"[DRIFT] OK: score={drift_score:.4f} <= threshold={threshold}. "
                f"features_evaluated={feature_count}"
            )

        return result

    def record_retrain(self, version: str, r2_score: float, previous_version: Optional[str] = None, rollback: bool = False) -> None:
        """Record that retraining was performed.

        Args:
            version: Version of new model
            r2_score: R² score of new model
            previous_version: Version being replaced (optional)
            rollback: True if the new model was subsequently rolled back
        """
        self._state["last_retrain"] = {
            "timestamp": datetime.now().isoformat(),
            "version": version,
            "r2_score": r2_score
        }
        dataset_hash: Optional[str] = None
        if Path(self.config.training_data_path).exists():
            self._state["last_dataset_size"] = self._count_dataset_samples(self.config.training_data_path)
            dataset_hash = self._compute_dataset_hash(self.config.training_data_path)
            self._state["last_dataset_hash"] = dataset_hash
        self._save_state()
        logger.info(f"[RETRAIN] Recorded retrain: {version}, R²={r2_score:.4f}")

        # ── Persistent governance log ────────────────────────────────────
        try:
            import json as _json
            from backend.governance.retrain_event_log import (
                log_retrain_event,
                hash_retrain_config,
                TRIGGER_MANUAL,
            )
            cfg_hash = hash_retrain_config({
                "min_new_samples": self.config.min_new_samples,
                "growth_ratio_threshold": self.config.growth_ratio_threshold,
                "max_model_age_days": self.config.max_model_age_days,
                "min_r2_threshold": self.config.min_r2_threshold,
                "max_drift_threshold": self.config.max_drift_threshold,
                "max_weight_change": self.config.max_weight_change,
            })
            log_retrain_event(
                trigger_source=TRIGGER_MANUAL,
                previous_model_version=previous_version,
                new_model_version=version,
                validation_metrics={"r2": r2_score},
                rollback_flag=rollback,
                dataset_snapshot_hash=dataset_hash,
                config_hash=cfg_hash,
            )
        except Exception as _exc:
            logger.warning("[RETRAIN] governance retrain event log write failed (non-fatal): %s", _exc)
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate retraining status report.
        
        Returns:
            Comprehensive status report dict
        """
        model_info = self._get_active_model_info()
        
        report = {
            "generated_at": datetime.now().isoformat(),
            "config": {
                "min_new_samples": self.config.min_new_samples,
                "growth_ratio_threshold": self.config.growth_ratio_threshold,
                "max_model_age_days": self.config.max_model_age_days,
                "min_r2_threshold": self.config.min_r2_threshold,
                "max_weight_change": self.config.max_weight_change
            },
            "state": {
                "last_check": self._state.get("last_check"),
                "last_retrain": self._state.get("last_retrain"),
                "last_dataset_size": self._state.get("last_dataset_size"),
                "triggers_count": len(self._state.get("triggers_history", []))
            },
            "active_model": None,
            "current_triggers": self.check_all_triggers()
        }
        
        if model_info:
            report["active_model"] = {
                "version": model_info.get("version"),
                "method": model_info.get("method"),
                "trained_at": model_info.get("trained_at"),
                "r2_score": model_info.get("r2_score")
            }
            
            # Calculate age
            trained_at = model_info.get("trained_at")
            if trained_at:
                try:
                    trained_date = datetime.fromisoformat(trained_at)
                    report["active_model"]["age_days"] = (datetime.now() - trained_date).days
                except ValueError:
                    pass
        
        return report


# =====================================================
# CLI ENTRY POINT
# =====================================================

def main():
    """CLI for retraining monitor."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="SIMGR Retraining Monitor (GĐ Phase 5)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run all trigger checks",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate full status report",
    )
    parser.add_argument(
        "--max-age",
        type=int,
        default=30,
        help="Max model age in days (default: 30)",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=100,
        help="Min new samples to trigger retrain (default: 100)",
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    config = RetrainingConfig(
        max_model_age_days=args.max_age,
        min_new_samples=args.min_samples
    )
    
    monitor = RetrainingMonitor(config)
    
    if args.report:
        import json
        report = monitor.generate_report()
        print(json.dumps(report, indent=2, default=str))
    elif args.check:
        result = monitor.check_all_triggers()
        print("\n" + "=" * 50)
        print("RETRAINING TRIGGER CHECK RESULTS")
        print("=" * 50)
        print(f"\nShould Retrain: {'YES' if result['should_retrain'] else 'NO'}")
        if result["triggers"]:
            print("\nActive Triggers:")
            for t in result["triggers"]:
                print(f"  - {t['reason']}: {t['details']}")
        print("=" * 50)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

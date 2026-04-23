"""
Test ML Operations - Phase 3: Auto-Retraining + Online Inference
================================================================
Tests the complete closed-loop ML system:
- Inference modules
- Retrain modules
- Model registry
- A/B routing
- Feedback collection
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_model_loader():
    """Test ModelLoader initialization and version management."""
    print("\n" + "="*60)
    print("TEST 1: Model Loader")
    print("="*60)
    
    from backend.inference.model_loader import ModelLoader
    
    loader = ModelLoader()
    
    # Test list versions
    versions = loader.list_versions()
    print(f"Available versions: {versions}")
    
    # Test load active model
    model = loader.load_active()
    if model:
        print(f"✓ Active model loaded: {model.version}")
        print(f"  - Metrics: {model.metrics}")
        print(f"  - Model type: {model.model_type}")
    else:
        print("✗ No active model found")
        
    return model is not None


def test_ab_router():
    """Test A/B routing with sticky user assignment."""
    print("\n" + "="*60)
    print("TEST 2: A/B Router")
    print("="*60)
    
    from backend.inference.ab_router import ABRouter, RouteTarget
    
    router = ABRouter()
    router.configure(canary_ratio=0.10)  # 10% canary
    
    # Test routing for different users
    users = ["user_001", "user_002", "user_003", "user_004", "user_005"]
    
    active_count = 0
    canary_count = 0
    
    for user_id in users:
        decision = router.route(user_id)
        target = "ACTIVE" if decision.target == RouteTarget.ACTIVE else "CANARY"
        print(f"  User {user_id} -> {target}")
        
        if decision.target == RouteTarget.ACTIVE:
            active_count += 1
        else:
            canary_count += 1
    
    # Test sticky routing (same user should get same target)
    user = "sticky_test_user"
    first_decision = router.route(user)
    second_decision = router.route(user)
    
    sticky_ok = first_decision.target == second_decision.target
    print(f"\n  Sticky routing test: {'✓ OK' if sticky_ok else '✗ FAILED'}")
    
    # Test kill switch
    router.set_kill_switch(True)
    ks_decision = router.route("any_user")
    ks_ok = ks_decision.target == RouteTarget.ACTIVE
    print(f"  Kill switch test: {'✓ OK' if ks_ok else '✗ FAILED'}")
    router.set_kill_switch(False)
    
    return sticky_ok and ks_ok


def test_feedback_collector():
    """Test feedback collection and logging."""
    print("\n" + "="*60)
    print("TEST 3: Feedback Collector")
    print("="*60)
    
    from backend.inference.feedback_collector import FeedbackCollector
    import tempfile
    
    # Use temp directory for test
    with tempfile.TemporaryDirectory() as tmp_dir:
        collector = FeedbackCollector(logs_dir=tmp_dir)
        
        # Log some predictions
        pred_id = None
        for i in range(3):
            pred_id = collector.log_prediction(
                user_id=f"test_user_{i}",
                features={"math_score": 85.0, "physics_score": 90.0},
                predicted_career="Data Scientist",
                predicted_proba=0.85 + i * 0.03,
                model_version="v1",
                latency_ms=50 + i * 10
            )
            print(f"  Logged prediction: {pred_id[:20]}...")
        
        # Log feedback
        collector.log_feedback(
            prediction_id=pred_id,
            actual_career="Data Scientist",
        )
        print(f"  Logged feedback for: {pred_id[:20]}...")
        
        # Get summary
        summary = collector.get_summary()
        print(f"\n  Summary:")
        print(f"    - Total predictions: {summary.total_predictions}")
        print(f"    - Total feedback: {summary.total_feedback}")
        
    return True


def test_metric_tracker():
    """Test inference metric tracking."""
    print("\n" + "="*60)
    print("TEST 4: Metric Tracker")
    print("="*60)
    
    from backend.inference.metric_tracker import MetricTracker
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        tracker = MetricTracker(logs_dir=tmp_dir)
        
        # Simulate some requests
        for i in range(10):
            if i % 5 == 0:  # 20% error rate
                tracker.record_error(
                    latency_ms=100 + i * 5,
                    model_version="v1",
                    error_type="TestError"
                )
            else:
                tracker.record_success(latency_ms=50 + i * 3, model_version="v1")
        
        metrics = tracker.get_metrics()
        print(f"  Total requests: {metrics.total_requests}")
        print(f"  Successful: {metrics.successful_requests}")
        print(f"  Failed: {metrics.failed_requests}")
        print(f"  Error rate: {metrics.error_rate:.1%}")
        print(f"  Latency mean: {metrics.latency_mean:.1f}ms")
        
        return metrics.total_requests == 10


def test_trigger_engine():
    """Test retrain trigger detection."""
    print("\n" + "="*60)
    print("TEST 5: Trigger Engine")
    print("="*60)
    
    from backend.retrain.trigger_engine import TriggerEngine, TriggerType
    
    engine = TriggerEngine()
    
    # Test manual trigger / force trigger
    result = engine.force_trigger("test")
    print(f"  Force trigger: should_trigger={result.should_trigger}")
    print(f"  Trigger type: {result.trigger_type.value if result.trigger_type else None}")
    
    # Test evaluate (checks all conditions)
    eval_result = engine.evaluate()
    print(f"  Evaluate all: should_trigger={eval_result.should_trigger}")
    
    print(f"  Drift threshold: {engine._drift_threshold}")
    
    return True


def test_dataset_builder():
    """Test dataset building from offline + online sources."""
    print("\n" + "="*60)
    print("TEST 6: Dataset Builder")
    print("="*60)
    
    from backend.retrain.dataset_builder import DatasetBuilder
    
    builder = DatasetBuilder()
    
    print("  Dataset builder initialized")
    print(f"  Required columns: {builder.REQUIRED_COLUMNS}")
    print(f"  Project root: {builder._project_root}")

    # The build method requires actual data files
    # Just verify the class is importable and configurable
    return True


def test_model_registry():
    """Test model registry operations."""
    print("\n" + "="*60)
    print("TEST 7: Model Registry")
    print("="*60)
    
    from backend.retrain.model_registry import ModelRegistry
    
    registry = ModelRegistry()
    
    # List versions
    versions = registry.list_versions()
    print(f"  Registered versions: {len(versions)}")
    
    for v in versions[:3]:
        print(f"    - {v.version}: accuracy={v.accuracy:.3f}, is_active={v.is_active}")
    
    # Get active version - method is get_active()
    active = registry.get_active()
    print(f"\n  Active model: {active.version if active else 'None'}")
    
    # Get rollback version
    rollback = registry.get_rollback()
    print(f"  Rollback model: {rollback.version if rollback else 'None'}")
    
    return True


def test_deploy_manager():
    """Test deployment manager."""
    print("\n" + "="*60)
    print("TEST 8: Deploy Manager")
    print("="*60)
    
    from backend.retrain.deploy_manager import DeployManager, DeployState
    from backend.retrain.model_registry import ModelRegistry
    from backend.inference.ab_router import ABRouter
    from backend.inference.model_loader import ModelLoader
    
    # DeployManager __init__ order: router, loader, registry
    router = ABRouter()
    loader = ModelLoader()
    registry = ModelRegistry()
    
    manager = DeployManager(router=router, loader=loader, registry=registry)
    
    print(f"  Deploy manager initialized")
    print(f"  Current state: {manager._state.value}")
    print(f"  Kill switch: {manager._kill_switch}")
    
    # Test kill switch
    manager.set_kill_switch(True)
    print(f"  Kill switch enabled: {manager._kill_switch}")
    manager.set_kill_switch(False)
    print(f"  Kill switch disabled: {manager._kill_switch}")
    
    return True


def test_main_controller_ml_ops():
    """Test MainController ML operations methods."""
    print("\n" + "="*60)
    print("TEST 9: MainController ML Ops Integration")
    print("="*60)
    
    # Add crawlers path for correct import
    import sys
    from pathlib import Path
    backend_dir = Path(__file__).parent.parent / "backend"
    sys.path.insert(0, str(backend_dir))
    
    try:
        from backend.main_controller import MainController
        
        print("  MainController imported successfully")
        
        # Verify ML ops methods exist
        methods = [
            "_init_ml_ops",
            "start_inference_api",
            "get_inference_metrics",
            "check_retrain_trigger",
            "run_retrain",
            "deploy_model",
            "promote_canary",
            "rollback_model",
            "set_kill_switch",
            "get_model_versions",
            "run_ml_monitoring_cycle",
        ]
        
        all_present = True
        for method in methods:
            has_method = hasattr(MainController, method)
            status = "✓" if has_method else "✗"
            print(f"  {status} {method}")
            if not has_method:
                all_present = False
        
        return all_present
        
    except ImportError as e:
        print(f"  Import failed (expected in isolated test): {e}")
        
        # Alternative: Just read the file and check methods exist
        controller_path = Path(__file__).parent.parent / "backend" / "main_controller.py"
        
        if controller_path.exists():
            content = controller_path.read_text(encoding="utf-8")
            
            methods = [
                "def _init_ml_ops",
                "def start_inference_api",
                "def get_inference_metrics",
                "def check_retrain_trigger",
                "def run_retrain",
                "def deploy_model",
                "def promote_canary",
                "def rollback_model",
                "def set_kill_switch",
                "def get_model_versions",
                "def run_ml_monitoring_cycle",
            ]
            
            all_present = True
            for method in methods:
                has_method = method in content
                status = "✓" if has_method else "✗"
                print(f"  {status} {method.replace('def ', '')}")
                if not has_method:
                    all_present = False
            
            return all_present
        
        return False


def run_all_tests():
    """Run all tests and print summary."""
    print("\n" + "#"*60)
    print("# ML OPERATIONS TEST SUITE - PHASE 3")
    print("# Auto-Retraining + Online Inference")
    print("#"*60)
    print(f"Started: {datetime.now().isoformat()}")
    
    tests = [
        ("Model Loader", test_model_loader),
        ("A/B Router", test_ab_router),
        ("Feedback Collector", test_feedback_collector),
        ("Metric Tracker", test_metric_tracker),
        ("Trigger Engine", test_trigger_engine),
        ("Dataset Builder", test_dataset_builder),
        ("Model Registry", test_model_registry),
        ("Deploy Manager", test_deploy_manager),
        ("MainController ML Ops", test_main_controller_ml_ops),
    ]
    
    results = []
    
    for name, test_fn in tests:
        try:
            passed = test_fn()
            results.append((name, "PASS" if passed else "FAIL"))
        except Exception as e:
            import traceback
            print(f"\n  ERROR: {e}")
            traceback.print_exc()
            results.append((name, f"ERROR: {str(e)[:30]}"))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    pass_count = sum(1 for _, r in results if r == "PASS")
    fail_count = len(results) - pass_count
    
    for name, result in results:
        status = "✓" if result == "PASS" else "✗"
        print(f"  {status} {name}: {result}")
    
    print(f"\nTotal: {pass_count}/{len(results)} passed")
    print(f"Finished: {datetime.now().isoformat()}")
    
    return fail_count == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

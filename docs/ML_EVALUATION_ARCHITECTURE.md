# ML Evaluation Service — Architecture Documentation

## Phase 1: ML Evaluation Core

### 1. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           HDSS Pipeline Architecture                        │
│                                                                             │
│  ┌──────┐    ┌─────────┐    ┌────────────┐    ┌─────────┐                   │
│  │  UI  │───▶│  Input  │───▶│  Feature   │───▶│  Rule   │                 │
│  │      │    │  Layer  │    │ Extraction │    │ Engine  │                   │
│  └──────┘    └─────────┘    └────────────┘    └────┬────┘                   │
│                                                     │                       │
│                                                     ▼                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         SCORING ENGINE                                │  │
│  └───────────────────────────────┬──────────────────────────────────────┘   │
│                                  │                                          │
│                                  ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  ╔═══════════════════════════════════════════════════════════════╗   │   │
│  │  ║               ML EVALUATION SERVICE (Phase 1)                  ║   │  │
│  │  ║                                                                ║   │  │
│  │  ║   ┌──────────────┐   ┌─────────────┐   ┌──────────────────┐   ║   │   │
│  │  ║   │ DatasetLoader│──▶│ ModelFactory│──▶│ CrossValidator   │   ║   │  │
│  │  ║   │              │   │             │   │ (K-Fold CV)      │   ║   │   │
│  │  ║   │ • validate   │   │ • RF        │   │                  │   ║   │   │
│  │  ║   │ • load       │   │ • LogReg    │   │ • train/predict  │   ║   │   │
│  │  ║   │ • encode     │   │ • factory   │   │ • per-fold log   │   ║   │   │
│  │  ║   └──────────────┘   └─────────────┘   └────────┬─────────┘   ║   │   │
│  │  ║                                                  │             ║   │  │
│  │  ║                                                  ▼             ║   │  │
│  │  ║                                        ┌──────────────────┐   ║   │   │
│  │  ║                                        │ MetricsEngine    │   ║   │   │
│  │  ║                                        │                  │   ║   │   │
│  │  ║                                        │ • accuracy       │   ║   │   │
│  │  ║                                        │ • precision      │   ║   │   │
│  │  ║                                        │ • recall         │   ║   │   │
│  │  ║                                        │ • F1 (macro)     │   ║   │   │
│  │  ║                                        │ • mean ± std     │   ║   │   │
│  │  ║                                        └────────┬─────────┘   ║   │   │
│  │  ║                                                  │             ║   │  │
│  │  ║                                                  ▼             ║   │  │
│  │  ║                                        ┌──────────────────┐   ║   │   │
│  │  ║                                        │ MLEvaluationSvc  │   ║   │   │
│  │  ║                                        │                  │   ║   │   │
│  │  ║                                        │ • run_pipeline() │   ║   │   │
│  │  ║                                        │ • publish()      │   ║   │   │
│  │  ║                                        │ • audit_log()    │   ║   │   │
│  │  ║                                        └────────┬─────────┘   ║   │   │
│  │  ╚════════════════════════════════════════════════╪══════════════╝   │   │
│  │                              ┌─────────────────────┤                 │   │
│  └──────────────────────────────┼─────────────────────┼─────────────────┘   │
│                                 │                     │                     │
│                                 ▼                     ▼                     │
│  ┌───────────────────────┐  ┌─────────────┐  ┌────────────────────┐         │
│  │   EXPLANATION LAYER  │◀─│  EVENT BUS  │─▶│   LOGGING/AUDIT    │         │
│  │                       │  │             │  │                    │         │
│  │ • Feature importance  │  │ • Scoring   │  │ • cv_results.json  │         │
│  │ • SHAP values         │  │ • Explain   │  │ • Audit trail      │         │
│  │ • Decision paths      │  │ • Logging   │  │ • Metrics export   │         │
│  └───────────────────────┘  └─────────────┘  └────────────────────┘         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2. Data Flow

```
┌────────────────┐     ┌──────────────────┐     ┌───────────────────┐
│ config/        │     │ data/            │     │ outputs/          │
│ system.yaml    │────▶│ training.csv    │────▶│ cv_results.jso n  │
│                │     │                  │     │                   │
│ • data_path    │     │ 215 rows         │     │ • run_id          │
│ • model_type   │     │ 5 columns        │     │ • timestamp       │
│ • kfold        │     │ 7 career classes │     │ • metrics         │
│ • random_state │     └──────────────────┘     │ • quality_passed  │
│ • output_path  │                              └───────────────────┘
│ • enable_pub   │
└────────────────┘
```

### 3. Module Structure

```
backend/
├── evaluation/
│   ├── __init__.py
│   ├── dataset_loader.py   # DatasetLoader: validate, load, encode
│   ├── models.py           # ModelFactory: RF, LogReg
│   ├── train_eval.py       # CrossValidator: K-Fold CV
│   ├── metrics.py          # MetricsEngine: acc, prec, rec, F1
│   ├── event_bus.py        # EventBus: publish to downstream
│   └── service.py          # MLEvaluationService: orchestrator
│
├── controller/
│   └── main_controller.py  # Integration point (calls service)
│
└── main.py                 # FastAPI endpoints
```

### 4. Integration Points

#### MainController Integration

```python
# backend/main_controller.py

# Stage constant
STAGE_ML_EVAL = "ml_eval"
ALL_STAGES = [STAGE_CRAWL, STAGE_VALIDATE, STAGE_SCORE, STAGE_ML_EVAL, STAGE_EXPLAIN]

# Stage execution
async def _stage_ml_eval(self, run_id: str, scored_careers: List[Any]):
    from backend.evaluation.service import MLEvaluationService
    service = MLEvaluationService()
    service.load_config()
    result = await asyncio.to_thread(service.run_pipeline, run_id)
    return result

# Standalone invocation
async def run_ml_evaluation(self, run_id: Optional[str] = None):
    # Available for on-demand runs
    ...
```

#### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/ml/evaluation` | POST | Run ML evaluation on-demand |
| `/api/v1/ml/evaluation/results` | GET | Retrieve latest cv_results.json |
| `/api/v1/pipeline/run` | POST | Full pipeline (includes ML eval) |

### 5. Configuration (config/system.yaml)

```yaml
ml_evaluation:
  data_path: "data/training.csv"
  model_type: "random_forest"
  kfold: 5
  random_state: 42
  output_path: "outputs/cv_results.json"
  enable_publish: true

  model_params:
    random_forest:
      n_estimators: 200
      max_depth: 12
      min_samples_split: 4
      min_samples_leaf: 2
      class_weight: "balanced"

    logistic_regression:
      C: 1.0
      max_iter: 1000
      solver: "lbfgs"
      multi_class: "multinomial"
      class_weight: "balanced"

  quality_gate:
    min_accuracy: 0.90
    min_f1: 0.88

  log_level: "INFO"
```

### 6. Dataset Schema (data/training.csv)

| Column | Type | Description |
|--------|------|-------------|
| math_score | float | Math aptitude (0-100) |
| physics_score | float | Physics aptitude (0-100) |
| interest_it | float | IT interest level (0-100) |
| logic_score | float | Logical reasoning (0-100) |
| target_career | string | Career label (7 classes) |

Career Classes:
- Software Engineer
- Data Analyst
- Mechanical Engineer
- Accountant
- Civil Engineer
- Business Administration
- Cybersecurity Analyst

### 7. Output Format (outputs/cv_results.json)

```json
{
  "run_id": "eval_e51f11e8bab1",
  "timestamp": "2026-02-13T10:37:16.396061+00:00",
  "model": "random_forest",
  "kfold": 5,
  "metrics": {
    "accuracy": { "mean": 0.953488, "std": 0.014708 },
    "precision": { "mean": 0.945771, "std": 0.023789 },
    "recall": { "mean": 0.950124, "std": 0.019134 },
    "f1": { "mean": 0.939514, "std": 0.020869 }
  },
  "quality_passed": true,
  "meta": {
    "cv_time_s": 2.0357,
    "num_samples": 215,
    "num_classes": 7
  }
}
```

### 8. Event/Publish Layer

The EventBus publishes evaluation results to:

1. **ScoringEngine** — Updates model selection/weights
2. **ExplanationLayer** — Feature importance data
3. **LoggingSystem** — Central audit trail

```python
# Usage
bus = create_default_event_bus()  # Pre-wired with all publishers
bus.publish(EvaluationEvent(
    run_id="...",
    model_type="random_forest",
    kfold=5,
    metrics={...},
    output_path="outputs/cv_results.json",
    timestamp="...",
    quality_passed=True,
))
```

### 9. Logging & Audit

Every pipeline step is logged:

```
[AUDIT] {"run_id": "eval_...", "step": "pipeline_start", ...}
[AUDIT] {"run_id": "eval_...", "step": "load_data", ...}
[AUDIT] {"run_id": "eval_...", "step": "build_model", ...}
[AUDIT] {"run_id": "eval_...", "step": "train_start", ...}
[AUDIT] {"run_id": "eval_...", "step": "train_complete", ...}
[AUDIT] {"run_id": "eval_...", "step": "eval_complete", ...}
[AUDIT] {"run_id": "eval_...", "step": "persist_output", ...}
[AUDIT] {"run_id": "eval_...", "step": "publish_complete", ...}
[AUDIT] {"run_id": "eval_...", "step": "pipeline_end", ...}
```

### 10. Usage Examples

#### From MainController (Pipeline)

```python
# Full data pipeline (ML eval as stage 4)
await main_controller.run_data_pipeline()

# On-demand ML evaluation only
await main_controller.run_ml_evaluation()
```

#### Direct Service Usage

```python
from backend.evaluation.service import MLEvaluationService

service = MLEvaluationService()
service.load_config()
result = service.run_pipeline()

print(f"Accuracy: {result['metrics']['accuracy']['mean']:.4f}")
print(f"F1: {result['metrics']['f1']['mean']:.4f}")
print(f"Quality Gate: {'PASSED' if result['quality_passed'] else 'FAILED'}")
```

#### Via API

```bash
# Run ML evaluation
curl -X POST http://localhost:8000/api/v1/ml/evaluation

# Get latest results
curl http://localhost:8000/api/v1/ml/evaluation/results
```

### 11. Quality Gate

Evaluation automatically checks metrics against thresholds:

| Metric | Threshold | Current |
|--------|-----------|---------|
| Accuracy | ≥ 0.90 | **0.9535** ✓ |
| F1 | ≥ 0.88 | **0.9395** ✓ |

### 12. Validation Checklist

✅ Runs from main.py (not standalone)  
✅ Config binding (no hardcoding)  
✅ Service layer architecture  
✅ Publish interface (EventBus)  
✅ Audit logging  
✅ Metrics ≥ 0.90  
✅ Real K-Fold CV (not fake)  
✅ 215 unique training samples  
✅ Trace ID per run  
✅ JSON output with timestamps  

---

## Phase 2: Stability Layer

### 1. Stability Architecture

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                     ML EVALUATION — STABILITY LAYER (Phase 2)                  │
│                                                                                │
│  ┌─────────────────────────────────────────────────────────────────────────┐  │
│  │                         MLEvaluationService.run_pipeline()               │  │
│  └──────────────────────────────────┬──────────────────────────────────────┘  │
│                                     │                                          │
│                                     ▼                                          │
│  ╔═══════════════════════════════════════════════════════════════════════════╗│
│  ║                           STABILITY SERVICE                                ║│
│  ║  ┌────────────────┐  ┌────────────────┐  ┌──────────────────────┐         ║│
│  ║  │ Fingerprint    │  │ Regression     │  │ Drift Monitor        │         ║│
│  ║  │ Generator      │  │ Guard          │  │                      │         ║│
│  ║  │                │  │                │  │ • PSI calculation    │         ║│
│  ║  │ • SHA256 hash  │  │ • Baseline vs  │  │ • Feature drift      │         ║│
│  ║  │ • Schema       │  │   current      │  │ • Label drift        │         ║│
│  ║  │ • Stats        │  │ • PASS/WARN/   │  │ • Schema change      │         ║│
│  ║  │ • Distribution │  │   FAIL         │  │                      │         ║│
│  ║  └───────┬────────┘  └───────┬────────┘  └──────────┬───────────┘         ║│
│  ║          │                    │                      │                     ║│
│  ║          ▼                    ▼                      ▼                     ║│
│  ║  ┌─────────────────────────────────────────────────────────────────────┐  ║│
│  ║  │                        StabilityReport                               │  ║│
│  ║  │                                                                      │  ║│
│  ║  │  • regression_status: PASS | WARN | FAIL                            │  ║│
│  ║  │  • drift_status: LOW | MEDIUM | HIGH | CRITICAL                     │  ║│
│  ║  │  • should_publish: true | false                                      │  ║│
│  ║  │  • delta_metrics: {accuracy, f1, precision, recall}                 │  ║│
│  ║  │  • recommendations: [...]                                            │  ║│
│  ║  └─────────────────────────────────────────────────────────────────────┘  ║│
│  ╚═══════════════════════════════════════════════════════════════════════════╝│
│                                     │                                          │
│                                     ▼                                          │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────────────────────┐│
│  │ baseline/       │  │ runs/           │  │ outputs/                          ││
│  │                 │  │                 │  │                                   ││
│  │ • baseline_     │  │ • run_YYYYMMDD  │  │ • cv_results.json                 ││
│  │   metrics.json  │  │   _HHMMSS.json  │  │ • stability_report.json           ││
│  │ • dataset_      │  │ • env_snapshot  │  │ • drift_report.json               ││
│  │   fingerprint   │  │   .json         │  │                                   ││
│  │   .json         │  │                 │  │                                   ││
│  └─────────────────┘  └─────────────────┘  └──────────────────────────────────┘│
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```

### 2. Stability Pipeline Flow

```
run_pipeline()
    │
    ├─► fingerprint_dataset()      ── SHA256 + stats
    │
    ├─► load_baselines()           ── baseline_metrics.json + dataset_fingerprint.json
    │
    ├─► [Cross-Validation]         ── K-Fold CV (Phase 1)
    │
    ├─► validate_regression()      ── Compare vs baseline metrics
    │       │
    │       └─► PASS   → metrics improved or within threshold
    │           WARN   → minor regression (within 3%)
    │           FAIL   → significant regression (> 3%)
    │
    ├─► detect_drift()             ── Compare fingerprints
    │       │
    │       └─► LOW      → PSI < 0.1
    │           MEDIUM   → 0.1 ≤ PSI < 0.25
    │           HIGH     → 0.25 ≤ PSI < 0.5
    │           CRITICAL → PSI ≥ 0.5
    │
    ├─► save_run()                 ── runs/run_YYYYMMDD_HHMMSS.json
    │
    ├─► update_baseline()          ── (if improved)
    │       │
    │       └─► Updates baseline_metrics.json
    │           Updates dataset_fingerprint.json
    │
    └─► publish()                  ── (if should_publish == true)
```

### 3. Module Structure (Phase 2)

```
backend/
├── evaluation/
│   ├── __init__.py              # Updated exports
│   ├── fingerprint.py           # DatasetFingerprint, FingerprintGenerator
│   ├── regression_guard.py      # RegressionGuard, RegressionCheckResult
│   ├── drift_monitor.py         # DriftMonitor, DriftReport, DriftSeverity
│   ├── stability_service.py     # StabilityService, StabilityReport
│   └── service.py               # Updated with stability integration
│
baseline/
├── baseline_metrics.json        # Reference metrics (acc, f1, etc.)
└── dataset_fingerprint.json     # Reference fingerprint (hash, stats)

runs/
├── run_20260213_180909.json     # Run registry entry
└── env_snapshot.json            # Environment snapshot

outputs/
├── cv_results.json              # Evaluation results (updated)
├── stability_report.json        # Stability validation report
└── drift_report.json            # Drift analysis report
```

### 4. Configuration (config/system.yaml)

```yaml
stability:
  enabled: true

  # Regression guard
  regression_threshold: 0.03       # 3% regression tolerance
  block_on_regression: true        # Block publish on FAIL

  # Drift monitoring
  block_on_critical_drift: true    # Block publish on CRITICAL drift
  drift_thresholds:
    low: 0.1
    medium: 0.25
    high: 0.5

  # Baseline management
  baseline_update_policy: "on_improvement"  # auto | manual | on_improvement

  # Paths
  paths:
    baseline_dir: "baseline"
    runs_dir: "runs"
    output_dir: "outputs"
```

### 5. Output Formats

#### stability_report.json

```json
{
  "run_id": "test_stability_run",
  "dataset_hash": "d14776e0a98036119ed58fd626431497...",
  "baseline_hash": "",
  "regression_status": "WARN",
  "drift_status": "LOW",
  "delta_metrics": {
    "accuracy_delta": -0.00001,
    "f1_delta": 0.00001,
    "precision_delta": -0.0024,
    "recall_delta": 0.0171
  },
  "recommendations": [
    "First run — this will become the baseline"
  ],
  "should_publish": true,
  "timestamp": "2026-02-13T11:09:09.114566+00:00"
}
```

#### drift_report.json

```json
{
  "run_id": "test_stability_run",
  "baseline_hash": "",
  "current_hash": "d14776e0a98036119ed58fd626431497...",
  "overall_severity": "LOW",
  "overall_psi": 0.0,
  "feature_drifts": [],
  "label_drift": null,
  "schema_changed": false,
  "row_count_change": 0,
  "recommendations": [
    "First run — this will become the baseline"
  ]
}
```

#### run_YYYYMMDD_HHMMSS.json

```json
{
  "run_id": "test_stability_run",
  "timestamp": "2026-02-13T11:09:06.946473+00:00",
  "dataset_hash": "d14776e0a98036119...",
  "model_type": "random_forest",
  "model_config": {
    "n_estimators": 200,
    "max_depth": 12,
    ...
  },
  "kfold": 5,
  "random_state": 42,
  "metrics": { ... },
  "quality_passed": true,
  "regression_status": "WARN",
  "drift_status": "LOW",
  "environment": {
    "python_version": "3.13.7...",
    "platform": "Windows",
    "libraries": { "scikit-learn": "1.8.0", ... },
    "git_commit": "156b70ee...",
    "git_branch": "master"
  },
  "system_version": "1.0.0"
}
```

### 6. Regression Guard Logic

```
IF accuracy_new < accuracy_baseline - threshold
   OR f1_new < f1_baseline - threshold:
    status = FAIL
    should_block = true

ELIF accuracy_new < accuracy_baseline
     OR f1_new < f1_baseline:
    status = WARN
    should_block = false

ELSE:
    status = PASS
    should_block = false
```

### 7. PSI (Population Stability Index) Calculation

```
PSI = Σ (P_new_i - P_base_i) × ln(P_new_i / P_base_i)

Where:
  P_new_i  = proportion in bin i for new data
  P_base_i = proportion in bin i for baseline data

Interpretation:
  PSI < 0.1      → LOW (no significant drift)
  0.1 ≤ PSI < 0.25 → MEDIUM (moderate drift, monitor)
  0.25 ≤ PSI < 0.5 → HIGH (significant drift, investigate)
  PSI ≥ 0.5      → CRITICAL (severe drift, block publish)
```

### 8. Blocking Rules

| Condition | Action |
|-----------|--------|
| `regression_status == FAIL && block_on_regression` | Block publish |
| `drift_status == CRITICAL && block_on_critical_drift` | Block publish |
| Otherwise | Allow publish |

### 9. MainController Integration

```python
# backend/main_controller.py

async def _stage_ml_eval(self, run_id: str, scored_careers: List[Any]):
    from backend.evaluation.service import MLEvaluationService
    from backend.evaluation.stability_service import StabilityService

    service = MLEvaluationService()
    service.load_config()
    result = await asyncio.to_thread(service.run_pipeline, run_id)

    # Extract stability info
    stability_info = result.get("stability", {})
    regression_status = stability_info.get("regression_status", "PASS")
    drift_status = stability_info.get("drift_status", "LOW")

    # Log warnings
    if regression_status == "FAIL":
        self.logger.warning(f"[{run_id}] Regression detected!")
    if drift_status in ("HIGH", "CRITICAL"):
        self.logger.warning(f"[{run_id}] High drift detected!")

    return result
```

### 10. Phase 2 Validation Checklist

✅ Dataset fingerprinting (SHA256 + stats)  
✅ Regression guard (baseline comparison)  
✅ Drift monitoring (PSI calculation)  
✅ Run registry (persistent history)  
✅ Environment snapshot (reproducibility)  
✅ Baseline auto-update (on improvement)  
✅ Blocking rules (regression + critical drift)  
✅ stability_report.json output  
✅ drift_report.json output  
✅ runs/run_*.json output  
✅ main_controller integration  
✅ No hardcoded paths (config-driven)  

---

## Quick Start (Phase 2)

```bash
# 1. Run ML evaluation with stability checks
python -c "
from backend.evaluation.service import MLEvaluationService
import json

service = MLEvaluationService()
service.load_config()
result = service.run_pipeline('stability_test')

print('Quality Gate:', 'PASSED' if result['quality_passed'] else 'FAILED')
print('Regression:', result['stability']['regression_status'])
print('Drift:', result['stability']['drift_status'])
print('Can Publish:', result['stability']['should_publish'])
"

# 2. Check outputs
cat outputs/cv_results.json
cat outputs/stability_report.json
cat outputs/drift_report.json
ls runs/
```

# MAINTENANCE HANDBOOK
## Pipeline MLOps / DataOps — Crawl → Validate → Score → Explain

> **Version**: 2.0  
> **Last Updated**: 2025-06  
> **Scope**: Full lifecycle operations for the Hybrid Decision Support System  

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [OpsHub — Central Integration Layer](#2-opshub--central-integration-layer)
3. [Auto-Restart Supervisor](#3-auto-restart-supervisor)
4. [Automation Scripts Reference](#4-automation-scripts-reference)
5. [API Endpoints Reference](#5-api-endpoints-reference)
6. [CLI Reference](#6-cli-reference)
7. [Test Suite Documentation](#7-test-suite-documentation)
8. [Monitoring Architecture](#8-monitoring-architecture)
9. [Explanation Monitoring](#9-explanation-monitoring)
10. [Rollback & Recovery Plan](#10-rollback--recovery-plan)
11. [Security & Secrets Management](#11-security--secrets-management)
12. [Maintenance Procedures](#12-maintenance-procedures)
13. [Runbooks](#13-runbooks)
14. [Appendix](#14-appendix)

---

## 1. System Architecture Overview

### 1.1 Pipeline Stages

```
Crawl (Playwright) → Validate (Pydantic) → Score (SIMGR) → Explain (LLM/Tracer)
```

| Stage | Module | Input | Output |
|-------|--------|-------|--------|
| Crawl | `crawlers/topcv_playwright.py`, `vietnamworks_playwright.py` | Site URLs | `RawJobRecord[]` |
| Validate | `data_pipeline/validator.py` | `RawJobRecord[]` | `CleanJobRecord[]` |
| Score | `scoring/engine.py` → `scoring/calculator.py` | `CleanJobRecord[]` + `UserProfile` | `ScoredCareer[]` |
| Explain | `scoring/tracer.py` + `llm/client.py` | `ScoringTrace` | Human-readable explanations |

### 1.2 Production Integration

The ops infrastructure is wired into the production pipeline through three integration points:

| Integration Point | Module | What It Does |
|---|---|---|
| **OpsHub** | `backend/ops/integration.py` | Central lazy-init hub — single entry point for all 28 ops services |
| **MainController** | `backend/main_controller.py` | Pipeline orchestrator instrumented with access log, audit, SLA, bottleneck tracing, source reliability, completeness, anomaly detection |
| **FastAPI** | `backend/run_api.py` | Unified production API entrypoint exposing health, ops, liveops, and resilience endpoints |

### 1.3 Ops Module Structure

```
backend/ops/
├── __init__.py            # Exports OpsHub
├── integration.py         # OpsHub — central lazy-init access to all services
│
├── orchestration/         # A. Orchestration & Reliability
│   ├── scheduler.py       # Pipeline stage scheduling & dependency resolution
│   ├── checkpoint.py      # Stage checkpoint persistence & resume
│   ├── rollback.py        # Multi-stage rollback with auto-trigger
│   ├── retry.py           # Retry policies + circuit breaker
│   └── supervisor.py      # Auto-restart supervisor with backoff (NEW)
│
├── resource/              # B. Resource & Performance
│   ├── browser_monitor.py # Per-browser RSS/CPU monitoring
│   ├── leak_detector.py   # Memory/handle leak detection
│   ├── concurrency.py     # Browser pool + rate limiting
│   └── bottleneck.py      # Span-based performance tracing
│
├── quality/               # C. Data Quality Control
│   ├── schema_validator.py    # Boundary schema validation
│   ├── completeness.py        # Field fill rate analysis
│   ├── outlier.py             # IQR + z-score anomaly detection
│   ├── drift.py               # PSI-based data drift monitoring
│   └── source_reliability.py  # Per-source quality scoring
│
├── versioning/            # D. Versioning & Reproducibility
│   ├── dataset.py         # Content-addressable dataset storage
│   ├── config_version.py  # Git-like config versioning
│   ├── snapshot.py        # Full pipeline state snapshots
│   └── reproducible.py    # Deterministic run reproduction
│
├── tests/                 # E. Testing System (88 tests across 6 files)
│   ├── conftest.py        # Shared fixtures
│   ├── test_unit.py       # 28 unit tests
│   ├── test_ops_modules.py# 35 tests — resource, monitoring, security, maintenance (NEW)
│   ├── test_supervisor.py # 6 async tests — supervisor lifecycle (NEW)
│   ├── test_integration.py# 6 stage-to-stage integration tests
│   ├── test_e2e.py        # 4 full pipeline end-to-end tests
│   └── test_regression.py # 9 determinism & performance regression tests
│
├── monitoring/            # F. Monitoring & Health
│   ├── health.py          # Component health checks + probes
│   ├── sla.py             # SLA definition & compliance tracking
│   ├── alerts.py          # Multi-channel alerting (log, file, webhook)
│   ├── anomaly.py         # Z-score + pct-change anomaly detection
│   └── explanation.py     # Explanation quality & drift monitoring (NEW)
│
├── security/              # G. Security & Backup
│   ├── secrets.py         # Fernet-encrypted secret management (UPGRADED)
│   ├── access_log.py      # Structured access logging
│   ├── backup.py          # Full/config backup & restore
│   └── disaster_recovery.py # DR plan with RPO/RTO
│
├── maintenance/           # H. Maintenance & Governance
│   ├── update_policy.py   # Component update schedules
│   ├── dependency_manager.py # Package version tracking
│   ├── retention.py       # Data lifecycle & cleanup
│   └── audit_trail.py     # Immutable governance audit log
│
└── scripts/               # I. CLI Entry Point (NEW)
    └── __main__.py        # 9 operational CLI commands
```

---

## 2. OpsHub — Central Integration Layer

`OpsHub` is the central bridge between the ops infrastructure and production code. It provides **lazy-initialized** access to all 28 services through a single instance.

### 2.1 Initialization

```python
from backend.ops import OpsHub

ops = OpsHub()
await ops.startup()   # registers health checks, alert hooks, supervisor hooks
# ... application lifetime ...
await ops.shutdown()  # graceful shutdown of supervisor + browser monitor
```

In FastAPI (`backend/run_api.py`), OpsHub is initialized at module level and wired into startup/shutdown hooks:

```python
ops = OpsHub()

@app.on_event("startup")
async def startup():
    await ops.startup()

@app.on_event("shutdown")
async def shutdown():
    await ops.shutdown()
```

### 2.2 Available Services

All properties are **lazy** — services are only instantiated on first access.

| Property | Service Class | Category |
|---|---|---|
| `ops.scheduler` | `PipelineScheduler` | Orchestration |
| `ops.checkpoint` | `CheckpointManager` | Orchestration |
| `ops.rollback` | `RollbackManager` | Orchestration |
| `ops.retry` | `RetryExecutor` | Orchestration |
| `ops.supervisor` | `PipelineSupervisor` | Orchestration |
| `ops.browser_monitor` | `BrowserResourceMonitor` | Resource |
| `ops.concurrency` | `ConcurrencyController` | Resource |
| `ops.bottleneck` | `BottleneckTracer` | Resource |
| `ops.leak_detector` | `LeakDetector` | Resource |
| `ops.completeness` | `CompletenessChecker` | Quality |
| `ops.outlier` | `OutlierDetector` | Quality |
| `ops.drift` | `DriftMonitor` | Quality |
| `ops.source_reliability` | `SourceReliabilityScorer` | Quality |
| `ops.dataset_version` | `DatasetVersionManager` | Versioning |
| `ops.config_version` | `ConfigVersionManager` | Versioning |
| `ops.snapshot` | `PipelineSnapshotManager` | Versioning |
| `ops.health` | `HealthCheckService` | Monitoring |
| `ops.sla` | `SLAMonitor` | Monitoring |
| `ops.alerts` | `AlertManager` | Monitoring |
| `ops.anomaly` | `AnomalyDetector` | Monitoring |
| `ops.explanation_monitor` | `ExplanationMonitor` | Monitoring |
| `ops.secrets` | `SecretManager` | Security |
| `ops.access_log` | `AccessLogger` | Security |
| `ops.backup` | `BackupManager` | Security |
| `ops.retention` | `RetentionManager` | Maintenance |
| `ops.audit` | `AuditTrail` | Maintenance |
| `ops.update_policy` | `UpdatePolicy` | Maintenance |

### 2.3 MainController Integration

The `MainController` accepts `ops: OpsHub` and instruments the pipeline with observability:

```python
from backend.ops import OpsHub

ops = OpsHub()
controller = MainController(ops=ops)

# In _refresh_job_data:
#   - access_log.log_pipeline_start(session_id)
#   - audit.record("pipeline_start", ...)
#   - bottleneck.async_span("crawl") — performance tracing
#   - source_reliability.record_crawl(source, success, count)
#   - sla.record("pipeline_duration", elapsed)
#   - anomaly.record("crawl_records_count", count)
#   - access_log.log_pipeline_complete(session_id, ...)

# In _run_validation_and_scoring:
#   - bottleneck.async_span("validate") / bottleneck.async_span("score")
#   - completeness.check_batch(records)
#   - sla.record("validation_rate", rate)
#   - anomaly.record("validation_pass_rate", rate)
```

### 2.4 Startup Behavior

`ops.startup()` performs:

1. **Health check registration**: `disk_space`, `memory`, `data_dir`, `scoring_engine`
2. **Webhook alerts**: Adds Slack webhook channel if `SLACK_WEBHOOK_URL` is set
3. **Supervisor hooks**: Wires crash → `CRITICAL` alert, max-restart → `FATAL` alert with `force=True`

---

## 3. Auto-Restart Supervisor

The `PipelineSupervisor` monitors registered async processes and automatically restarts them on failure with configurable backoff.

### 3.1 RestartPolicy Configuration

| Parameter | Default | Description |
|---|---|---|
| `max_restarts` | `5` | Max restarts within the window before entering FAILED state |
| `restart_window_seconds` | `300.0` | Window for counting restarts (5 min) |
| `base_backoff_seconds` | `2.0` | Initial backoff delay before restart |
| `max_backoff_seconds` | `60.0` | Maximum backoff delay cap |
| `backoff_factor` | `2.0` | Multiplier for exponential backoff |
| `cooldown_after_max` | `120.0` | Cooldown period after max restarts exhausted |

### 3.2 Process States

```
STOPPED → STARTING → RUNNING → (crash) → RESTARTING → RUNNING
                                   ↓ (max restarts)
                                 FAILED
                                   ↓ (manual restart)
                                 STARTING → RUNNING

SHUTDOWN (terminal — from any state via shutdown())
```

### 3.3 Usage

```python
from backend.ops.orchestration import PipelineSupervisor, RestartPolicy

supervisor = PipelineSupervisor()

# Register a process with custom policy
policy = RestartPolicy(max_restarts=3, base_backoff_seconds=5.0)
supervisor.register("crawler_service", crawl_main_loop, policy=policy)
supervisor.register("health_poller", health_poll_loop)  # default policy

# Set event hooks
supervisor.set_hooks(
    on_start=lambda name: print(f"{name} started"),
    on_crash=lambda name, err: print(f"{name} crashed: {err}"),
    on_restart=lambda name, count: print(f"{name} restart #{count}"),
    on_max_restart=lambda name: print(f"{name} exceeded max restarts!"),
)

# Start all registered processes
await supervisor.start_all()

# Inspect status
status = supervisor.get_status()
# {"processes": {"crawler_service": {"state": "running", ...}, ...}}

detail = supervisor.get_process_detail("crawler_service")
# {"name": "...", "state": "...", "restart_count": 0, "uptime": 123.4, "events": [...]}

# Manual restart (resets restart counter)
await supervisor.restart("crawler_service")

# Graceful shutdown
await supervisor.shutdown()
```

### 3.4 OpsHub Integration

When using via OpsHub, crash/max-restart hooks automatically fire alerts:

- **Process crash** → `CRITICAL` alert: `"Supervised process '{name}' crashed: {error}"`
- **Max restarts exceeded** → `FATAL` alert (force=True): `"Supervised process '{name}' exceeded max restarts"`

---

## 4. Automation Scripts Reference

### 4.1 Pipeline Orchestration

```python
from backend.ops.orchestration import PipelineScheduler, CheckpointManager

# Initialize scheduler with all 4 stages
scheduler = PipelineScheduler()
scheduler.register_stage("crawl", crawl_func, order=1, critical=True)
scheduler.register_stage("validate", validate_func, order=2, critical=True, depends_on=["crawl"])
scheduler.register_stage("score", score_func, order=3, critical=True, depends_on=["validate"])
scheduler.register_stage("explain", explain_func, order=4, critical=False, depends_on=["score"])

# Run full pipeline
result = await scheduler.run_pipeline(input_data)

# Resume from checkpoint
checkpoint_mgr = CheckpointManager()
resume_point = checkpoint_mgr.get_resume_point(run_id)
result = await scheduler.run_pipeline(input_data, resume_from=resume_point)
```

### 4.2 Retry with Circuit Breaker

```python
from backend.ops.orchestration import RetryPolicy, RetryExecutor

policy = RetryPolicy(max_retries=3, strategy="exponential", base_delay=2.0)
executor = RetryExecutor(policy)

# Auto-retry with backoff
result = await executor.execute(unreliable_function, arg1, arg2)
```

### 4.3 Resource Monitoring

```python
from backend.ops.resource import BrowserResourceMonitor, ConcurrencyController

# Start browser monitoring
monitor = BrowserResourceMonitor(check_interval=10)
await monitor.start()

# Concurrency management
controller = ConcurrencyController(max_browsers=3)
async with controller.acquire_browser() as browser_slot:
    # Browser work here
    pass
```

### 4.4 Data Quality Gate

```python
from backend.ops.quality import PipelineSchemaValidator, CompletenessChecker, DriftMonitor

validator = PipelineSchemaValidator()
completeness = CompletenessChecker()
drift = DriftMonitor()

# Validate at stage boundary
issues = validator.validate_stage_output("crawl", records)

# Check completeness
report = completeness.check(records)
assert report["overall_fill_rate"] >= 0.8

# Monitor drift
drift_report = drift.check_drift("jobs", current_records)
assert not drift_report["drift_detected"]
```

### 4.5 Backup Operations

```python
from backend.ops.security import BackupManager

backup_mgr = BackupManager()

# Full backup before risky operation
metadata = backup_mgr.create_full_backup(label="pre-migration")

# Config-only backup
backup_mgr.create_config_backup()

# Restore
backup_mgr.restore("full_pre-migration_20250120_143000", dry_run=True)  # preview
backup_mgr.restore("full_pre-migration_20250120_143000")                # execute
```

---

## 5. API Endpoints Reference

All ops endpoints are exposed via FastAPI at `backend/run_api.py` and tagged `["Ops"]`.

| Endpoint | Method | Query Params | Response |
|---|---|---|---|
| `/health` | `GET` | — | Full component health check (`status`, `components`) |
| `/ops/sla` | `GET` | — | SLA compliance dashboard (totals, violations, compliance rate) |
| `/ops/alerts` | `GET` | `hours: float = 24.0` | Recent alerts within time window |
| `/ops/status` | `GET` | — | Combined: supervisor status + SLA + alerts + source reliability + bottleneck analysis |
| `/ops/explanation` | `GET` | — | Explanation quality check (completeness, coverage, latency, issues) |
| `/ops/backup` | `POST` | `label: str = ""` | Creates full backup, returns metadata |
| `/ops/retention` | `POST` | `dry_run: bool = True` | Enforces data retention policies |

### 5.1 Health Check Response

```json
{
  "status": "healthy",
  "components": {
    "disk_space": {"status": "healthy", "message": "2.1 GB free"},
    "memory": {"status": "healthy", "message": "62% used"},
    "data_dir": {"status": "healthy", "message": "Directory exists"},
    "scoring_engine": {"status": "healthy", "message": "Scoring engine OK"}
  }
}
```

### 5.2 Combined Status Response

```json
{
  "supervisor": {"processes": {"crawler": {"state": "running", "restarts": 0}}},
  "sla": {"total_slas": 5, "violations": 0, "compliance_rate": 1.0},
  "alerts": {"total": 0, "by_severity": {}},
  "source_reliability": {"topcv": 0.95, "vietnamworks": 0.88},
  "bottleneck": {"stages": {"crawl": {"mean_ms": 1200}, "validate": {"mean_ms": 300}}}
}
```

---

## 6. CLI Reference

Entry point: `python -m backend.ops.scripts <command> [options]`

| Command | Options | Description |
|---|---|---|
| `health` | — | Run all health checks (exit 0=healthy, 1=unhealthy) |
| `sla` | — | Print SLA compliance dashboard as JSON |
| `backup` | `[create\|list\|config]`, `--label` | Manage backups (default: list) |
| `restore` | `--name`, `--latest`, `--dry-run` | Restore from backup |
| `retention` | `--dry-run`, `--status` | Enforce or preview data retention |
| `deps` | `[check\|outdated\|vulnerabilities\|lock]` | Dependency management (default: check) |
| `updates` | — | Show component update dashboard |
| `status` | — | Combined health + SLA + alerts + source reliability |
| `verify` | `--dataset` (default: `"jobs"`) | Verify dataset integrity (exit 0/1) |

### 6.1 Usage Examples

```bash
# Quick system health check
python -m backend.ops.scripts health

# Full status dashboard
python -m backend.ops.scripts status

# Create labeled backup before deploy
python -m backend.ops.scripts backup create --label pre-deploy-v2

# Preview retention cleanup
python -m backend.ops.scripts retention --dry-run

# Check for outdated dependencies
python -m backend.ops.scripts deps outdated

# Verify data integrity
python -m backend.ops.scripts verify --dataset jobs

# Restore latest backup (dry run first)
python -m backend.ops.scripts restore --latest --dry-run
python -m backend.ops.scripts restore --latest
```

---

## 7. Test Suite Documentation

### 7.1 Test Structure

| Suite | File | Classes | Tests | Purpose |
|-------|------|---------|-------|---------|
| Unit | `test_unit.py` | 9 | 28 | Individual component validation |
| Ops Modules | `test_ops_modules.py` | 15 | 35 | Resource, monitoring, security, maintenance, integration |
| Supervisor | `test_supervisor.py` | 1 | 6 | Async supervisor lifecycle & restart behavior |
| Integration | `test_integration.py` | 4 | 6 | Stage-to-stage data flow |
| E2E | `test_e2e.py` | 1 | 4 | Full pipeline execution |
| Regression | `test_regression.py` | 4 | 9 | Determinism & performance |
| **Total** | **6 files** | **~34** | **~88** | |

### 7.2 Running Tests

```bash
# All ops tests
pytest backend/ops/tests/ -v

# By category
pytest backend/ops/tests/test_unit.py -v
pytest backend/ops/tests/test_integration.py -v
pytest backend/ops/tests/test_e2e.py -v
pytest backend/ops/tests/test_regression.py -v

# With coverage
pytest backend/ops/tests/ --cov=backend --cov-report=html

# Specific test class
pytest backend/ops/tests/test_unit.py::TestDataValidator -v
```

### 7.3 Key Test Categories

**Unit Tests** — validate isolated component behavior:
- `TestDataValidator`: field validation, deduplication, logic checks
- `TestDataProcessor`: salary normalization, location, skills extraction
- `TestScoringEngine`: SIMGR calculation, weight application, edge cases
- `TestScoringTracer`: trace generation, component detail capture
- `TestScheduler`: stage ordering, failure isolation
- `TestRetry`: backoff strategies, circuit breaker states
- `TestCheckpoint`: save/load/resume
- `TestCompletenessChecker`: fill rate analysis
- `TestOutlierDetector`: IQR & z-score detection
- `TestDriftMonitor`: PSI-based drift detection

**Integration Tests** — validate data flows between stages:
- Crawl → Validate: raw records pass through validation
- Validate → Process: clean records processed correctly
- Scoring integration: validate → score → explain chain
- Orchestrator integration: full scheduler traversal

**E2E Tests** — simulate real pipeline runs:
- Full pipeline with mock crawl data
- Score determinism across runs
- Explanation generation consistency

**Regression Tests** — prevent quality degradation:
- Score determinism: same input → same output
- Validation contracts: schema changes caught
- Performance regression: latency within bounds
- Explanation consistency: same scores → same explanations

**Ops Module Tests** (`test_ops_modules.py`) — cover all ops subsystems:
- `TestBottleneckTracer`: span timing, analysis accuracy
- `TestConcurrencyController`: slot acquisition, limit enforcement
- `TestLeakDetector`: leak trend detection
- `TestAlertManager`: fire, fire_if, deduplication, severity filtering
- `TestSLAMonitor`: recording, violation detection
- `TestAnomalyDetector`: z-score and percentage change detection
- `TestHealthCheckService`: built-in checks, custom check registration
- `TestExplanationMonitor`: recording, completeness, coverage, drift
- `TestSecretManager`: set/get, validation, masking, required keys
- `TestAccessLogger`: pipeline start/complete logging
- `TestBackupManager`: create and list operations
- `TestRetentionManager`: dry-run enforcement
- `TestAuditTrail`: record, query, immutability
- `TestUpdatePolicy`: schedule tracking, overdue detection
- `TestOpsHub`: lazy initialization, startup, property access

**Supervisor Tests** (`test_supervisor.py`) — async lifecycle:
- Clean exit behavior (process exits without restart)
- Auto-restart on crash (verify restart count increments)
- Manual restart resets restart counter
- Graceful shutdown terminates all processes
- Event hooks called correctly on crash/restart
- `get_process_detail` returns correct state

---

## 8. Monitoring Architecture

### 8.1 Health Checks

```python
from backend.ops.monitoring import HealthCheckService

health = HealthCheckService()

# Built-in checks: disk_space, memory, data_dir, scoring_engine
status = await health.check_all()
# Returns: {"status": "healthy|degraded|unhealthy", "components": {...}}

# Register custom check
async def check_crawler():
    return ComponentHealth("crawler", HealthStatus.HEALTHY, "All browsers running")
health.register_check("crawler", check_crawler)
```

### 8.2 SLA Monitoring

**Default SLAs:**

| SLA | Metric | Threshold | Type |
|-----|--------|-----------|------|
| Pipeline Duration | End-to-end time | ≤ 7200s (2h) | max |
| Data Freshness | Hours since last crawl | ≤ 24h | max |
| Validation Rate | Records passing validation | ≥ 95% | min |
| Crawl Success | Successful crawl rate | ≥ 90% | min |
| Stage Timeout | Any single stage | ≤ 3600s (1h) | max |

```python
from backend.ops.monitoring import SLAMonitor

sla = SLAMonitor()
sla.record("pipeline_duration", 3500)  # seconds
dashboard = sla.get_dashboard()
# {"total_slas": 5, "violations": 0, "compliance_rate": 1.0, ...}
```

### 8.3 Alert Channels

```python
from backend.ops.monitoring import AlertManager

alerts = AlertManager()

# Channels configured automatically:
# - LogAlertChannel (always active)
# - FileAlertChannel (backend/data/logs/alerts.jsonl)
# - WebhookAlertChannel (if SLACK_WEBHOOK_URL env var set)

# Manual alert
await alerts.fire("High memory usage on crawler", severity="warning", source="browser_monitor")

# Automatic deduplication (5-min cooldown for identical alerts)
# Use fire_if for conditional alerting
await alerts.fire_if(memory_pct > 90, "Memory critical", severity="critical")
```

### 8.4 Anomaly Detection

```python
from backend.ops.monitoring import AnomalyDetector

detector = AnomalyDetector()

# Feed time-series data
detector.record("crawl_records_count", 150)
detector.record("crawl_records_count", 145)
detector.record("crawl_records_count", 5)  # anomaly!

anomalies = detector.check("crawl_records_count")
# [{"metric": "crawl_records_count", "value": 5, "method": "z_score", ...}]
```

---

## 9. Explanation Monitoring

The `ExplanationMonitor` tracks quality and consistency of SIMGR scoring explanations across the pipeline.

### 9.1 Recording Explanations

```python
from backend.ops.monitoring import ExplanationMonitor

monitor = ExplanationMonitor(max_history=2000)

# Track that a career was scored (for coverage calculation)
monitor.record_scored_career("Software Engineer")

# Record an explanation with its trace dict
metrics = monitor.record_explanation(
    career_name="Software Engineer",
    trace_dict={
        "total_score": 78.5,
        "components": {
            "study": {"score": 85, "weight": 0.25, "detail": "..."},
            "interest": {"score": 70, "weight": 0.20, "detail": "..."},
            "market": {"score": 80, "weight": 0.25, "detail": "..."},
            "growth": {"score": 75, "weight": 0.15, "detail": "..."},
            "risk": {"score": 65, "weight": 0.15, "detail": "..."},
        },
        "readable": "Software Engineer scores 78.5 overall..."
    },
    latency_ms=120.0,
)
# Returns ExplanationMetrics with has_all_components=True, component_count=5, etc.
```

### 9.2 Quality Checks

```python
quality = monitor.check_quality()
# {
#   "passed": True,
#   "issues": [],
#   "metrics": {
#     "completeness_rate": 0.98,
#     "coverage_rate": 0.95,
#     "mean_latency_ms": 150.0,
#     "components_seen": ["study", "interest", "market", "growth", "risk"]
#   }
# }
```

**Quality Thresholds:**

| Check | Threshold | Severity |
|---|---|---|
| Completeness rate (all 5 components present) | ≥ 95% | `warning` |
| Coverage rate (scored careers with explanations) | ≥ 90% | `warning` |
| Mean latency | ≤ 500ms | `warning` |
| Required components (S, I, M, G, R all seen) | All 5 present | `critical` |

### 9.3 Drift Detection

```python
drift = monitor.detect_drift(window=50)
# {
#   "drift_detected": False,
#   "signals": {
#     "score_drift": {"recent_mean": 75.2, "older_mean": 74.8, "change_pct": 0.5},
#     "completeness_drift": {"recent": 0.97, "older": 0.96, "change_pp": 1.0},
#     "latency_drift": {"recent_mean_ms": 140, "older_mean_ms": 135, "change_pct": 3.7}
#   }
# }
```

**Drift Thresholds:**

| Signal | Threshold | Method |
|---|---|---|
| Score drift | > 15% change | Mean comparison between windows |
| Completeness drift | > 5 percentage points drop | Recent vs older window |
| Latency drift | > 30% increase | Mean comparison between windows |

Requires `window × 2` history records minimum (default window = 50, needs 100+ records).

### 9.4 Dashboard

```python
dashboard = monitor.get_dashboard()
# {
#   "total_explanations": 150,
#   "completeness_rate": 0.97,
#   "coverage": {"scored": 160, "explained": 150, "rate": 0.9375},
#   "latency": {"mean_ms": 145.0, "p50_ms": 130.0, "p95_ms": 280.0, "max_ms": 450.0},
#   "component_frequency": {"study": 147, "interest": 146, ...}
# }
```

---

## 10. Rollback & Recovery Plan

### 10.1 Automatic Rollback

The `RollbackManager` triggers automatically when a **critical stage** fails:

```python
from backend.ops.orchestration import RollbackManager

rollback = RollbackManager()

# Create rollback plan before risky operation
plan = rollback.create_plan(
    run_id="run_123",
    stages=["crawl", "validate", "score"],
    checkpoints=checkpoint_data,
)

# Auto-rollback on failure
if stage_failed and stage.critical:
    result = await rollback.execute(plan, target_stage="validate")
```

### 10.2 Manual Rollback Procedures

**Scenario: Bad Scoring Config Deployed**

1. Stop pipeline: `scheduler.cancel(run_id)`
2. Rollback config: `config_version.rollback("scoring", steps=1)`
3. Verify config: `config_version.get_current("scoring")`
4. Re-run from checkpoint: `scheduler.run_pipeline(data, resume_from="validate")`

**Scenario: Corrupted Crawl Data**

1. Identify corruption: check validation rate drop in SLA monitor
2. Restore data: `backup_mgr.restore("full_<latest>", dry_run=True)`
3. Execute restore: `backup_mgr.restore("full_<latest>")`
4. Re-crawl: `scheduler.run_pipeline(data, stages=["crawl", "validate"])`

### 10.3 Disaster Recovery

| Scenario | RPO | RTO | Procedure |
|----------|-----|-----|-----------|
| Data Corruption | 6 hours | 2 hours | `disaster_recovery.get_scenario("data_corruption")` |
| Crawler Failure | 0 (stateless) | 30 min | `disaster_recovery.get_scenario("crawler_failure")` |
| Scoring Failure | 0 | 1 hour | `disaster_recovery.get_scenario("scoring_failure")` |
| Full System | 6 hours | 2 hours | `disaster_recovery.get_scenario("full_recovery")` |

### 10.4 Recovery Verification

After any recovery, run:

```python
# 1. Health check
status = await health.check_all()
assert status["status"] != "unhealthy"

# 2. Data integrity
integrity = dataset_version.verify_integrity("jobs")
assert integrity["valid"]

# 3. Smoke test pipeline
result = await scheduler.run_pipeline(sample_data)
assert result.status == PipelineStatus.COMPLETED

# 4. SLA compliance
dashboard = sla.get_dashboard()
assert dashboard["compliance_rate"] >= 0.9
```

---

## 11. Security & Secrets Management

### 11.1 Encryption Architecture

Secrets are encrypted at rest using **Fernet (AES-128-CBC)** with PBKDF2-derived keys:

```
ENCRYPTION_KEY (env var)
    ↓ PBKDF2-HMAC-SHA256 (100,000 iterations, salt="ops-secrets-salt")
    ↓ base64url encode (32 bytes → 44 chars)
    → Fernet key
    → AES-128-CBC encryption of secrets JSON
    → Written to backend/data/.secrets.enc
```

If the `cryptography` package is not installed, falls back to legacy XOR (with console warning).

### 11.2 Secret Management

```python
from backend.ops.security import SecretManager

secrets = SecretManager()
secrets.load()  # loads from .env then .secrets.enc

# Get secrets (priority: env var > cached > default)
api_key = secrets.get("LLM_API_KEY")
db_url = secrets.get_required("DATABASE_URL")  # raises on missing

# Set in-memory (not persisted until save)
secrets.set("NEW_KEY", "value")

# Save encrypted
secrets.save_encrypted({"LLM_API_KEY": "sk-...", "DATABASE_URL": "postgres://..."})

# Validation report
report = secrets.validate()
# {"valid": True, "missing_required": [], "missing_optional": ["SLACK_WEBHOOK_URL"]}

# Masked display
secrets.mask("LLM_API_KEY")  # "sk-x****xxxx"
```

### 11.3 Required & Optional Secrets

| Secret | Required | Purpose |
|---|---|---|
| `LLM_API_KEY` | ✅ | LLM provider API key |
| `DATABASE_URL` | ✅ | Database connection string |
| `SLACK_WEBHOOK_URL` | ❌ | Slack alert webhook |
| `ALERT_EMAIL` | ❌ | Email alert destination |
| `ENCRYPTION_KEY` | ❌ | Secrets file encryption key (default: `"default-dev-key"`) |
| `CRAWLER_PROXY_URL` | ❌ | Proxy for crawlers |
| `BACKUP_S3_KEY` | ❌ | S3 backup access key |
| `BACKUP_S3_SECRET` | ❌ | S3 backup secret key |

### 11.4 Access Logging

All pipeline operations are logged with structured access events:

```python
from backend.ops.security import AccessLogger

logger = AccessLogger()
logger.log_pipeline_start(session_id="sess_123")
# ... pipeline runs ...
logger.log_pipeline_complete(session_id="sess_123", records=150, duration=3600)
```

### 11.5 Audit Trail

Immutable governance audit log:

```python
from backend.ops.maintenance import AuditTrail

audit = AuditTrail()
audit.record("pipeline_start", details={"session": "sess_123", "trigger": "scheduled"})
audit.record("config_change", details={"key": "scoring.weights", "old": "...", "new": "..."})

# Query audit history
events = audit.query(event_type="config_change", limit=10)
```

---

## 12. Maintenance Procedures

### 12.1 Daily Operations

| Task | Frequency | Automation |
|------|-----------|------------|
| Health check | Every 5 min | `HealthCheckService` auto-runs |
| SLA monitoring | Continuous | `SLAMonitor` records every run |
| Log review | Daily | Check `backend/data/logs/` |
| Alert triage | As triggered | `AlertManager` sends notifications |

### 12.2 Weekly Operations

| Task | Procedure |
|------|-----------|
| Data quality review | `CompletenessChecker.check()` + `DriftMonitor.check_drift()` |
| Backup verification | `BackupManager.list_backups()` — verify recent |
| Resource trends | `LeakDetector.analyze()` — check for slow leaks |
| Crawler selector check | `UpdatePolicy.check_updates_due()` |
| Test suite run | `pytest backend/ops/tests/ -v` |

### 12.3 Monthly Operations

| Task | Procedure |
|------|-----------|
| Dependency update | `DependencyManager.check_outdated()` |
| Vulnerability scan | `DependencyManager.check_vulnerabilities()` |
| Retention enforcement | `RetentionManager.enforce_all()` |
| DR plan review | `DisasterRecoveryPlan.get_plan_summary()` |
| Performance baseline | `BottleneckTracer` review of stage durations |

### 12.4 Data Retention Policies

| Data Type | Retention | Min Kept |
|-----------|-----------|----------|
| Crawl logs | 30 days | — |
| Data logs | 14 days | — |
| Session data | 7 days | — |
| Checkpoints | 14 days | — |
| Backups | 90 days | 3 |
| Market data | 60 days | — |
| Output CSVs | 30 days | 5 |
| Temp files | 1 day | — |

```python
from backend.ops.maintenance import RetentionManager

retention = RetentionManager(dry_run=True)  # preview first
status = retention.enforce_all()

retention = RetentionManager(dry_run=False)  # then enforce
retention.enforce_all()
```

### 12.5 Update Policy

| Component | Check Interval | Max Age | Criticality |
|-----------|---------------|---------|-------------|
| Crawler selectors | 7 days | 30 days | High |
| Dependencies | 30 days | 90 days | Medium |
| Scoring weights | 90 days | 365 days | High |
| Taxonomy data | 30 days | 180 days | Medium |
| LLM prompts | 14 days | 60 days | Medium |

---

## 13. Runbooks

### 13.1 Runbook: Pipeline Not Completing

**Symptoms**: Pipeline runs exceed SLA timeout, stages hang.

1. Check health: `await health.check_all()` — identify failing component
2. Check resources: `BrowserResourceMonitor.get_stats()` — memory/CPU
3. Check bottlenecks: `BottleneckTracer.get_analysis()` — find slow stage
4. Kill zombies: terminate stuck browser processes
5. Clear checkpoints: `CheckpointManager.cleanup(run_id)`
6. Restart: `scheduler.run_pipeline(data)` with fresh state

### 13.2 Runbook: Validation Rate Drop

**Symptoms**: Validation pass rate falls below 95% SLA.

1. Check score reliability: `SourceReliabilityScorer.get_scores()`
2. Identify source: which crawler is producing bad data?
3. Check for site changes: manual inspection of target site
4. Check drift: `DriftMonitor.check_drift("jobs", records)`
5. Update selectors if needed in crawler config
6. Re-crawl affected source only

### 13.3 Runbook: Memory Leak Detected

**Symptoms**: `LeakDetector` reports increasing memory trend.

1. Identify process: `BrowserResourceMonitor.get_stats()` per browser
2. Auto-kill if above threshold (configured at 512 MB)
3. Check for browser page accumulation
4. Review `ConcurrencyController` settings
5. Force garbage collection cycle
6. If persistent: restart crawler service

### 13.4 Runbook: Score Drift Detected

**Symptoms**: Score distributions shift significantly.

1. Verify with `DriftMonitor.check_drift("scores", new_scores)`
2. Check if input data changed: `DriftMonitor.check_drift("jobs", new_jobs)`
3. If input data drifted: expected — update baselines
4. If input data stable but scores drifted: check config changes
5. Rollback scoring config if unintended: `config_version.rollback("scoring")`
6. Re-run scoring: `scheduler.run_pipeline(data, stages=["score", "explain"])`

### 13.5 Runbook: New Crawler Deployment

1. Create config backup: `BackupManager.create_config_backup()`
2. Snapshot current state: `PipelineSnapshotManager.capture()`
3. Deploy new crawler code
4. Run integration tests: `pytest backend/ops/tests/test_integration.py -v`
5. Crawl small sample: test with limited page count
6. Validate output: `PipelineSchemaValidator.validate_stage_output("crawl", data)`
7. Check completeness: `CompletenessChecker.check(data)`
8. If OK: deploy to production schedule
9. If FAIL: rollback code, restore from snapshot

### 13.6 Runbook: Explanation Quality Degradation

**Symptoms**: `/ops/explanation` shows `passed: false` or completeness < 95%.

1. Check quality: `monitor.check_quality()` — identify which threshold failed
2. Check components: are all 5 SIMGR components present in traces?
3. If missing component: check `scoring/calculator.py` for changes
4. Check latency: if > 500ms, investigate LLM provider performance
5. Check drift: `monitor.detect_drift()` — compare recent vs historical
6. If score drift > 15%: check for config changes in scoring weights
7. If coverage < 90%: check if `record_scored_career()` is being called
8. Reset baselines if drift is intentional

### 13.7 Runbook: Supervised Process Max Restarts

**Symptoms**: `FATAL` alert "Supervised process exceeded max restarts".

1. Check supervisor status: `GET /ops/status` → `supervisor.processes`
2. Identify failed process and its error history
3. Check `get_process_detail(name)` for crash details and event log
4. Fix root cause (network, resource, config issue)
5. Manual restart: `await supervisor.restart(name)` — resets restart counter
6. Monitor: verify process stays in `RUNNING` state
7. If recurring: increase `RestartPolicy.max_restarts` or `cooldown_after_max`

---

## 14. Appendix

### 14.1 Module Dependencies

```
ops/integration      → all ops modules (lazy import)
ops/orchestration    → (standalone; supervisor uses asyncio)
ops/resource         → psutil
ops/quality          → pydantic, numpy (for z-score)
ops/versioning       → hashlib, json (stdlib)
ops/tests            → pytest, pytest-asyncio
ops/monitoring       → aiohttp (for webhooks, optional)
ops/security         → cryptography (for Fernet, optional — XOR fallback)
ops/maintenance      → subprocess (for pip commands)
ops/scripts          → all ops modules (CLI entry point)
```

### 14.2 Configuration Files

| File | Purpose |
|------|---------|
| `config/crawler_config.yaml` | Crawler targets and schedules |
| `config/data_pipeline.yaml` | Validation thresholds and processing rules |
| `backend/crawlers/crawler.yaml` | Crawler-specific settings |
| `backend/.env` | Secrets (not committed) |

### 14.3 Key Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `LLM_API_KEY` | Yes | LLM provider API key |
| `DATABASE_URL` | Yes | Database connection string |
| `SLACK_WEBHOOK_URL` | No | Slack alert destination |
| `ALERT_EMAIL` | No | Email alert destination |
| `ENCRYPTION_KEY` | No | Secrets file encryption key |
| `CRAWLER_PROXY_URL` | No | Proxy for crawlers |

### 14.4 Contact & Escalation

| Level | Trigger | Action |
|-------|---------|--------|
| L1 | SLA warning | Check dashboards, run health check |
| L2 | SLA violation | Run relevant runbook, check logs |
| L3 | Multiple failures | Execute DR plan, notify stakeholders |
| L4 | Full system down | Execute full recovery scenario |

---

*End of Maintenance Handbook*

# Retrain Governance Framework

## Governance Rules

1. Manual retrain requests require prior approval when `MLOPS_MANUAL_RETRAIN_APPROVAL_REQUIRED=true`.
2. Cooldown is enforced for governed triggers (`manual`, `admin`, `admin_ui`, `auto`, `scheduled`, `drift`, `alarm`).
3. Cooldown bypass is blocked unless an approved token exists when `MLOPS_COOLDOWN_BYPASS_REQUIRES_APPROVAL=true`.
4. Static CSV fallback is prohibited in production retrain path. If no eligible candidates exist, retrain fails.
5. Dataset quality gate must pass before training:
   - `rows >= MLOPS_RETRAIN_MIN_DATASET_ROWS`
   - `avg_quality_score >= MLOPS_RETRAIN_MIN_AVG_QUALITY`
   - `label_classes >= MLOPS_RETRAIN_MIN_LABEL_CLASSES`
6. Candidate ingestion gate enforces `min_quality >= MLOPS_RETRAIN_MIN_CANDIDATE_QUALITY`.
7. Deployment gate requires:
   - `validation.passed=true`
   - model status in `staging|candidate`
   - `accuracy >= MLOPS_DEPLOY_MIN_ACCURACY`
   - `f1 >= MLOPS_DEPLOY_MIN_F1`
8. Rollback policy requires:
   - reason in `MLOPS_ROLLBACK_ALLOWED_REASONS`
   - successful rollbacks in last 24h < `MLOPS_ROLLBACK_MAX_PER_24H`
   - rollback target must pass validation and be archived/prod
9. Every approval/retrain/deploy/rollback action writes append-only audit records.
10. Scheduler validates provider wiring and payload schema before trigger evaluation.

## Retrain Workflow

1. Operator submits manual approval request via `POST /api/v1/mlops/train/approval/request`.
2. Admin approves request via `POST /api/v1/mlops/train/approval/{approval_id}/approve`.
3. Operator starts retrain via `POST /api/v1/mlops/train` with `approval_id` (and `bypass_cooldown` if needed).
4. System enforces approval gate, then cooldown gate.
5. System builds immutable dataset from training candidates only.
6. Dataset quality gate evaluates rows, average quality, and class diversity.
7. If gate passes, training runs and model is registered as staging.
8. Governance metrics and audit logs are updated for success/failure/blocked outcomes.

## Scheduler Flow

1. Scheduler startup validates providers (`metric_provider`, `feedback_provider`, `train_callback`).
2. Poll loop executes `check_and_trigger` at configured interval.
3. Cooldown and anti-storm protections are evaluated first.
4. Scheduler validates metrics/feedback payload shape.
5. Trigger conditions evaluate drift, accuracy drop, error rate, and negative feedback rate.
6. If conditions match, scheduler invokes train callback with trigger=`auto`.
7. Scheduler records check outcome and updates `scheduler_failure_rate`.
8. If consecutive scheduler failures exceed threshold (`MLOPS_SCHEDULER_MAX_CONSECUTIVE_FAILURES`), scheduler self-stops.

## Approval Matrix

| Action | Requester Role | Approver Role | Approval Required | Cooldown Bypass Allowed |
|---|---|---|---|---|
| Auto retrain (scheduler) | system | n/a | No | No |
| Manual retrain | operator/admin | admin | Yes (configurable) | Only with approval flag |
| Manual retrain during cooldown | operator/admin | admin | Yes | Yes, if approved token includes bypass right |
| Deploy staging model | operator/admin | admin (route guard) | Route-protected | n/a |
| Rollback model | admin | n/a | No separate token | Policy-gated by reason/rate/validation |

## Rollout Plan

1. Stage 0 (dry run):
   - Enable audit and metrics only.
   - Keep manual approval required, but monitor blocked reasons before hard SLA.
2. Stage 1 (staging enforce):
   - Enforce approval and dataset quality gates in staging.
   - Verify dashboards for:
     - `retrain_trigger_count`
     - `retrain_success_rate`
     - `bypass_attempt_rate`
     - `scheduler_failure_rate`
     - `rollback_rate`
3. Stage 2 (production enforce):
   - Enable full gating in production.
   - Confirm rollback policy limits and allowed reasons are tuned.
4. Stage 3 (operational hardening):
   - Add periodic review of blocked retrain events.
   - Tune thresholds from observed data quality distributions.
   - Add alerting on scheduler failure rate and bypass attempt spikes.

## Implementation Pointers

- Governance module: `backend/mlops/governance.py`
- Lifecycle enforcement: `backend/mlops/lifecycle.py`
- Scheduler validation/failure handling: `backend/mlops/scheduler/retrain_scheduler.py`
- Scheduler state counters: `backend/mlops/scheduler/state_store.py`
- API approval workflow: `backend/api/routers/mlops_router.py`
- Startup metrics wiring: `backend/main.py`
- Governance regression tests: `backend/tests/test_retrain_governance.py`

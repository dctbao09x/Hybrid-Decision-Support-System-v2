# Migration Plan

## Goal

Move operational state ownership from process-local memory and node-local files to distributed storage semantics.

## Executed Steps

1. Added shared substrate `backend/state/operational.py`.
2. Added distributed locking and required reliability gauges.
3. Migrated scheduler state store to distributed backend default.
4. Migrated retry subsystem state (circuits, budgets, telemetry).
5. Migrated deployment runtime state to distributed ownership.
6. Migrated kill-switch control maps (states/rules/approvals/cooldowns).
7. Replaced in-process kill-switch API router state with controller-backed state.
8. Replaced in-process rate-limit metric ratio counters with distributed counters.
9. Wired state metrics collector in startup paths.

## Runtime Cutover Strategy

1. Enable Redis connectivity and keep fail-open enabled for first cutover:
   - `OPS_STATE_REDIS_ENABLED=true`
   - `OPS_STATE_FAIL_OPEN=true`
2. Start one instance and verify substrate health.
3. Scale to multi-instance and verify lock contention and sync failure gauges.
4. After stabilization, optionally tighten to fail-closed mode for critical paths:
   - `OPS_STATE_FAIL_OPEN=false`

## Validation Checklist

- Kill-switch activation on one instance is visible on all instances.
- Scheduler cooldown and retrain history persist across restarts.
- Retry budget/circuit state survives worker restarts.
- Deployment canary state survives API process restart.
- Rate-limit hit/abuse ratio gauges remain continuous across instances.
- SLO gauges are emitted: stale, contention, sync-failure rates.

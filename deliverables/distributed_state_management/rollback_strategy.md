# Rollback Strategy

## Triggers for Rollback

- `state_sync_failure_rate` sustained above SLO threshold.
- Unacceptable `lock_contention_rate` causing control-plane latency.
- Redis instability with repeated lock acquisition failures.
- Functional regression in kill-switch, scheduler, retry, or deployment control paths.

## Rollback Modes

### Mode A: Soft Rollback (preferred)

Keep distributed code paths but disable Redis primary temporarily:

- `OPS_STATE_REDIS_ENABLED=false`

Result: control paths continue using persistent SQLite mirror via the same APIs.

### Mode B: Scheduler legacy fallback

For scheduler-only emergency fallback to JSON state:

- `MLOPS_SCHEDULER_STATE_BACKEND=json`

### Mode C: Full emergency rollback (code-level)

Revert deployment to pre-migration commit if functional impact persists.

## Data Safety

- Durable mirror is maintained in `storage/ops/operational_state.db`.
- Kill-switch and deployment events are mirrored in SQLite event streams.
- Deployment JSONL logs remain intact as secondary audit trail.

## Recovery After Rollback

1. Stabilize backend dependencies (Redis, network, latency).
2. Re-enable Redis primary:
   - `OPS_STATE_REDIS_ENABLED=true`
3. Verify hydration from persistent mirror to Redis.
4. Confirm SLO gauges return to normal ranges before full traffic restore.

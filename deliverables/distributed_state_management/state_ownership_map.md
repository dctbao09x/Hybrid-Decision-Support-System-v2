# Distributed Operational State Ownership Map

## Scope

This map defines authoritative ownership for operational state after migration to distributed storage.

| Domain | State Objects | Previous Owner | New Authoritative Owner | Storage Backend | TTL Policy | Persistence Policy |
|---|---|---|---|---|---|---|
| Kill-switch | scope state, safe mode level, approval requests, auto-trigger rules, rule cooldown timestamps | process-local dictionaries + SQLite | `KillSwitchController` via `backend.state.operational` (`namespace=killswitch`) | Redis primary + SQLite fallback | No TTL for control-plane state | Persistent (write-through)
| Scheduler | `last_retrain_at`, run history, cooldown/storm counters | JSON file + in-process cache | `StateStore` (`namespace=mlops_scheduler`, key=`scheduler_state`) | Redis primary + SQLite fallback | No TTL | Persistent
| Retry subsystem | per-stage circuit breakers, retry budgets, telemetry | in-process maps/lists | `StageRetryExecutor` (`namespace=stage_retry`) | Redis primary + SQLite fallback | No TTL | Persistent
| Rate limit counters | request/hit/abuse counters for ratio gauges | in-process dict (`_rate_metric_state`) | `rate_limit.py` distributed counters (`namespace=rate_limit`, key=`counters`) | Redis primary + SQLite fallback | No TTL | Persistent
| Cooldown windows / ban / strike | sliding/burst/cooldown/ban/strike counters | Redis Lua state | unchanged (already distributed) | Redis | policy-driven key TTL | Ephemeral by TTL
| Deployment state | lifecycle state, canary version, canary start, kill-switch flag | in-process fields in `DeployManager` | `DeployManager` (`namespace=deploy_manager`, key=`runtime`) | Redis primary + SQLite fallback | No TTL | Persistent
| Deployment event trail | deploy actions and state snapshots | JSONL local files | `DeployManager` event stream + JSONL mirror | Redis list + SQLite events table + JSONL | bounded Redis list | Persistent in SQLite + JSONL

## Lock Ownership

- Kill-switch transitions: `killswitch:*` distributed lock
- Scheduler state writes: `mlops_scheduler_state` lock
- Retry stage state updates: `stage_retry:<stage>` lock
- Retry telemetry append: `stage_retry:telemetry` lock
- Rate-limit metric counters: `rate_limit_metrics` lock
- Deployment transitions: `deploy_manager:*` locks

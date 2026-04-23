# Distributed Operational State Storage Design

## Architecture

The platform now uses a shared operational state substrate (`backend/state/operational.py`) with:

1. Redis as the distributed primary store for low-latency, multi-instance consistency.
2. SQLite persistent mirror as fallback and recovery source (`storage/ops/operational_state.db`).
3. Distributed lock primitive backed by Redis `SET NX PX`, with local lock fallback when Redis is unavailable.
4. Health and fail-open behavior controlled by environment flags.

## State API

- `get_json(namespace, state_key, default, policy)`
- `set_json(namespace, state_key, value, policy)`
- `delete(namespace, state_key)`
- `lock(name, ttl_seconds, wait_timeout_seconds, retry_interval_seconds)`
- `append_event(namespace, event_type, payload, state_key)`
- `list_events(namespace, limit)`
- `health()`

## State Policies

`StatePolicy` fields:

- `ttl_seconds`: optional TTL for ephemeral state.
- `persistent`: whether to write-through to durable mirror.
- `stale_after_seconds`: threshold for `stale_state_rate` calculation.

## Failover and Recovery Behavior

- Read path:
  - Prefer Redis.
  - On Redis miss/failure, read SQLite mirror.
  - On successful SQLite read, hydrate Redis for subsequent distributed reads.
- Write path:
  - Attempt Redis write (if available).
  - Persist to SQLite when policy is persistent or Redis is unavailable.
  - Track synchronization attempts/failures for SLO gauge.
- Lock path:
  - Prefer Redis distributed lock.
  - Fallback to local process lock if Redis is unavailable.

## Metrics

The substrate computes and publishes:

- `stale_state_rate`: stale reads / total reads
- `lock_contention_rate`: contended lock acquisitions / total lock acquisitions
- `state_sync_failure_rate`: failed backend sync attempts / total backend sync attempts

Metrics are exported via `set_operational_state_metrics_collector(...)` and wired in startup flows.

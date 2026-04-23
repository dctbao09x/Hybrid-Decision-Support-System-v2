# Redis / Postgres Schema Specification

## Redis Key Schema

### Shared substrate

- `hdss:ops:state:v1:data:{namespace}:{state_key}`
  - JSON envelope: `{ value, updated_at, expires_at }`
- `hdss:ops:state:v1:lock:{lock_name}`
  - lock token value with PX TTL
- `hdss:ops:state:v1:events:{namespace}`
  - LPUSH/LTRIM bounded event stream

### Namespaces in use

- `killswitch`
  - keys: `states`, `safe_mode_levels`, `rules`, `approvals`, `last_trigger`
- `mlops_scheduler`
  - key: `scheduler_state`
- `stage_retry`
  - keys: `circuit:{stage}`, `budget:{stage}`, `telemetry`
- `rate_limit`
  - key: `counters`
- `deploy_manager`
  - key: `runtime`

## Relational Schema (SQLite now, Postgres-compatible design)

The substrate writes durable mirror data to `operational_state` and `operational_events`.

### Table: `operational_state`

```sql
CREATE TABLE operational_state (
    namespace TEXT NOT NULL,
    state_key TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    PRIMARY KEY(namespace, state_key)
);
CREATE INDEX idx_operational_state_updated ON operational_state(updated_at);
```

### Table: `operational_events`

```sql
CREATE TABLE operational_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL,
    state_key TEXT,
    event_type TEXT NOT NULL,
    payload TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_operational_events_namespace
ON operational_events(namespace, created_at DESC);
```

## Postgres DDL Equivalent

For a Postgres deployment, use:

```sql
CREATE TABLE operational_state (
    namespace VARCHAR(128) NOT NULL,
    state_key VARCHAR(256) NOT NULL,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NULL,
    PRIMARY KEY(namespace, state_key)
);
CREATE INDEX idx_operational_state_updated
ON operational_state(updated_at DESC);

CREATE TABLE operational_events (
    id BIGSERIAL PRIMARY KEY,
    namespace VARCHAR(128) NOT NULL,
    state_key VARCHAR(256),
    event_type VARCHAR(128) NOT NULL,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_operational_events_namespace
ON operational_events(namespace, created_at DESC);
```

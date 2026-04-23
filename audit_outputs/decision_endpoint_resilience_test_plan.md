# Decision Endpoint Resilience Test Plan

## Scope
Mandatory resilience validation for:

- `POST /api/v1/one-button/run`
- `POST /api/v1/decision/run`

Coverage includes concurrent load, soak stability, and deterministic failure injection.

## Scenario Matrix

| ID | Scenario | Validation Focus | Expected Behavior |
|---|---|---|---|
| RES-LOAD-001 | Concurrent load on canonical and legacy endpoints | Throughput, p95 latency, error-rate | Both endpoints serve 200 responses within threshold |
| RES-SOAK-001 | Sustained soak windows | Stability drift and long-run errors | No instability drift beyond threshold, low error-rate |
| RES-FI-001 | Redis unavailable (fail-closed) | Error visibility | 503 with `RATE_LIMIT_BACKEND_UNAVAILABLE` |
| RES-FI-002 | Redis unavailable (fail-open) | Fallback validation | Request succeeds with fail-open behavior |
| RES-FI-003 | Auth provider failure | Error visibility | 500 with auth taxonomy code `CONFIG_ERROR` |
| RES-FI-004 | Market timeout | Error visibility + fallback taxonomy probe | Endpoint error is retryable and market fallback taxonomy is recorded |
| RES-FI-005 | LLM timeout | Fallback visibility | Response remains contract-compliant and exposes fallback reason |
| RES-FI-006 | Scheduler delay | Delay injection behavior | Delay is observable; scheduler health metrics remain available |
| RES-RET-001 | Retry probe (transient timeout) | Retry behavior | Retries are performed before success |

## Required Metrics

The suite emits `audit_outputs/decision_endpoint_resilience_metrics.json` with:

- `p95_latency_under_load`
- `error_rate_under_load`
- `retry_rate`
- `fallback_rate`
- `dead_letter_rate`

## Pass/Fail Thresholds

- `p95_latency_under_load <= 400 ms`
- `error_rate_under_load <= 0.05`
- `retry_rate >= 0.20`
- `fallback_rate >= 0.40`
- `dead_letter_rate <= 0.05`

The pytest suite fails immediately when any threshold is violated.

## Tooling Recommendation

- Test runner: `pytest` + `pytest-asyncio`
- In-process load driver: `httpx.AsyncClient` with `ASGITransport`
- Deterministic fault injection: `pytest` `monkeypatch` and explicit stub controllers
- Output artifacts:
  - `audit_outputs/decision_endpoint_resilience_metrics.json`
  - `audit_outputs/decision_endpoint_resilience_report.md`

## CI/CD Integration

CI gate command:

```bash
python -m pytest backend/tests/test_decision_endpoint_resilience.py -v --tb=short
```

Integrated in `.github/workflows/ci.yml` test matrix job via mandatory `backend/tests` execution.

Artifacts uploaded per matrix version:

- `decision-resilience-metrics-py${{ matrix.python-version }}`

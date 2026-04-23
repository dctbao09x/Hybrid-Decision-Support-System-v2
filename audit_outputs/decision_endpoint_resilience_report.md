# Decision Endpoint Resilience Report

## Required Metrics

- p95_latency_under_load: 7.67 ms (threshold <= 400.00 ms)
- error_rate_under_load: 0.0000 (threshold <= 0.0500)
- retry_rate: 0.6667 (threshold >= 0.2000)
- fallback_rate: 0.5000 (threshold >= 0.4000)
- dead_letter_rate: 0.0000 (threshold <= 0.0500)

## Scenario Outcomes

- [PASS] concurrent_load_on_one_button_and_decision_alias: requests=120 p95=6.37ms error_rate=0.0000
- [PASS] soak_stability_for_decision_endpoints: windows=6 overall_p95=7.67ms drift_ratio=0.974
- [PASS] failure_injection_redis_unavailable_fail_closed: status=503 code=RATE_LIMIT_BACKEND_UNAVAILABLE
- [PASS] failure_injection_redis_unavailable_fail_open_fallback: status=200 with fail_open fallback
- [PASS] failure_injection_auth_provider_failure: status=500 code=CONFIG_ERROR
- [PASS] failure_injection_market_timeout_error_visibility: status=500 retryable=true code=ONE_BUTTON_PIPELINE_ERROR
- [PASS] failure_injection_llm_timeout_fallback_visibility: status=200 with fallback_reason=provider_timeout
- [PASS] failure_injection_scheduler_delay: delay_injected=0.080s observed=0.082s
- [PASS] market_timeout_fallback_taxonomy_probe: fallback_delta=1 missing_signal_delta=1

## Tooling Recommendation

- Test runner: pytest plus pytest-asyncio
- Load generation: httpx.AsyncClient with ASGITransport for deterministic in-process concurrency
- Fault injection: pytest monkeypatch and deterministic controller stubs
- Artifact format: JSON metrics and Markdown report under audit_outputs

## CI/CD Integration

- Mandatory gate command: python -m pytest backend/tests/test_decision_endpoint_resilience.py -v --tb=short
- Workflow integration: .github/workflows/ci.yml test job
- Uploaded artifacts: audit_outputs/decision_endpoint_resilience_metrics.json and audit_outputs/decision_endpoint_resilience_report.md

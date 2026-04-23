# Cost Observability and Unit Economics

## Scope

This document defines the production implementation for cost observability across decision pipeline layers.

Coverage includes:

- Per-request attribution
- Endpoint-level attribution
- Tenant-level attribution
- Model and prompt/version attribution
- Budget enforcement and burn-rate alerts
- Cost anomaly detection


## Telemetry Schema

### Required Dimensions

- endpoint
- endpoint_version
- tenant_id
- request_id
- trace_id
- model_id
- model_version
- prompt_version
- explanation_status

### Required Cost Fields

- cost_usd
- cost_breakdown.token_cost_usd
- cost_breakdown.redis_cost_usd
- cost_breakdown.queue_cost_usd
- cost_breakdown.storage_cost_usd
- cost_breakdown.market_crawl_cost_usd
- cost_breakdown.total_cost_usd

### Required Unit Economics Fields

- unit_cost_per_decision_usd
- unit_cost_per_successful_explanation_usd


## Cost Model

Total request cost is calculated as:

```
total_cost_usd = token_cost_usd
               + redis_cost_usd
               + queue_cost_usd
               + storage_cost_usd
               + market_crawl_cost_usd
```

Component formulas:

```
token_cost_usd = (prompt_tokens / 1000) * token_input_cost_per_1k_usd
               + (completion_tokens / 1000) * token_output_cost_per_1k_usd

redis_cost_usd = redis_ops * redis_op_cost_usd

queue_cost_usd = queue_ops * queue_op_cost_usd

storage_cost_usd = (storage_bytes / 1024) * storage_kb_write_cost_usd

market_crawl_cost_usd = market_crawl_jobs * market_crawl_job_cost_usd
```

Default coefficients are configurable with environment variables:

- COST_TOKEN_INPUT_PER_1K_USD
- COST_TOKEN_OUTPUT_PER_1K_USD
- COST_REDIS_OP_USD
- COST_QUEUE_OP_USD
- COST_STORAGE_KB_WRITE_USD
- COST_MARKET_CRAWL_JOB_USD


## Dashboard Metrics

Primary metrics:

- cost_per_decision
- cost_per_successful_explanation
- cost_by_model_usd
- cost_by_tenant_usd
- cost_vs_conversion

Supporting metrics:

- cost_conversion_per_usd
- cost_burn_rate_1h
- cost_burn_rate_6h
- cost_budget_daily_utilization
- cost_budget_monthly_utilization


## Alert Rules

Production alerts:

- COST_SPIKE: cost_per_decision > 2x_baseline for 10m
- COST_BURN_RATE_1H: cost_burn_rate_1h > 1.25 for 15m
- COST_BUDGET_DAILY_EXHAUSTED: cost_budget_daily_utilization >= 1.0 for 5m
- COST_BUDGET_MONTHLY_EXHAUSTED: cost_budget_monthly_utilization >= 1.0 for 10m
- COST_ANOMALY_SPIKE: cost_per_request_usd z_score > 3.0 for 10m

Actions include throttle, budget guard enforcement, release freeze, and incident escalation.


## Budget Enforcement

Budget policy is evaluated on every request.

Hard guard behavior:

- If COST_HARD_BUDGET_ENFORCEMENT=true and daily or monthly budget is exhausted,
  one-button requests are blocked with HTTP 429.

Budget controls:

- COST_DAILY_BUDGET_USD
- COST_MONTHLY_BUDGET_USD


## Rollout Plan

1. Shadow phase
- Enable tracking only, no hard budget enforcement.
- Verify dashboard stability and attribution completeness.

2. Alerting phase
- Enable burn-rate and anomaly alerts.
- Tune thresholds from observed baseline.

3. Guarded enforcement phase
- Enable hard budget enforcement for selected tenants/endpoints.
- Validate that fallback and replay behavior remain stable.

4. Full enforcement
- Enforce across production endpoints that use one-button orchestration.
- Keep monthly review of model-level and tenant-level unit economics.

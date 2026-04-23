# Cross-Layer Contract Test Matrix and CI Plan

## Scope
This plan implements cross-layer contract tests covering frontend consumer, backend provider, router registry alignment, and startup parity checks.

## Test Matrix

| ID | Scenario | Layer(s) | Validation | Test File | Marker(s) |
|---|---|---|---|---|---|
| CL-001 | Frontend-like payload reaches canonical one-button endpoint | Backend API + one-button orchestration | HTTP 200, strict response schema model, required fields | `backend/tests/test_cross_layer_contracts.py::test_frontend_payload_e2e_backend_response_schema` | `contract`, `schema_regression`, `regression` |
| CL-002 | Contract version mismatch semantics | Backend API contract | Status code + error code + retryability | `backend/tests/test_cross_layer_contracts.py::test_error_semantics_contract_version_mismatch` | `contract` |
| CL-003 | Taxonomy validation failure semantics | Backend API + taxonomy gate | Status code + error code + retryability | `backend/tests/test_cross_layer_contracts.py::test_error_semantics_taxonomy_validation_failure` | `contract` |
| CL-004 | Fallback behavior still emits full manifest | Backend pipeline + fallback handling | Required stage manifest and stage statuses | `backend/tests/test_cross_layer_contracts.py::test_stage_manifest_and_fallback_behavior` | `contract`, `schema_regression`, `regression` |
| CL-005 | Router registry alignment for one-button route | Router registry + one-button constants | Router registration + auth level + stage manifest parity | `backend/tests/test_cross_layer_contracts.py::test_router_registry_alignment_with_one_button_contract` | `contract` |
| CL-006 | Consumer-driven FE/BE constant compatibility | Frontend service + backend contract constants | Endpoint, contract version, schema version parity | `backend/tests/test_cross_layer_contracts.py::test_consumer_driven_frontend_backend_constant_compatibility` | `contract`, `schema_regression`, `regression` |
| SP-001 | Required startup parity routes exist in both entrypoints | backend.main declaration + backend.run_api runtime | Required route presence | `backend/tests/test_startup_parity_main_vs_run_api.py::test_required_startup_routes_exist_in_main_and_run_api` | `contract`, `startup_parity` |
| SP-002 | Method parity for startup-required routes | backend.main declaration + backend.run_api runtime | HTTP method parity | `backend/tests/test_startup_parity_main_vs_run_api.py::test_required_startup_route_methods_are_parity_aligned` | `contract`, `startup_parity` |
| SP-003 | Startup contract endpoint is canonical in run_api | backend.run_api | Canonical entrypoint + strict validation metadata | `backend/tests/test_startup_parity_main_vs_run_api.py::test_run_api_startup_contract_endpoint_reports_canonical_metadata` | `contract`, `startup_parity` |
| SP-004 | Startup probe shape remains backward-compatible | backend.run_api | Startup probe required shape | `backend/tests/test_startup_parity_main_vs_run_api.py::test_startup_probe_contract_shape_is_backward_compatible` | `contract`, `startup_parity` |
| FE-001 | Consumer sends canonical contract envelope | Frontend decision API client | Outbound endpoint/body + inbound required fields | `ui-vite/src/services/decisionApi.contract.test.ts` | Vitest suite |
| FE-002 | Consumer maps 400 to non-retryable validation error | Frontend decision API client | Error code + retryability mapping | `ui-vite/src/services/decisionApi.contract.test.ts` | Vitest suite |
| FE-003 | Consumer maps 500 to retryable server error | Frontend decision API client | Error code + retryability mapping | `ui-vite/src/services/decisionApi.contract.test.ts` | Vitest suite |
| FE-004 | Consumer health endpoint path is canonical | Frontend decision API client | Health endpoint call path and method | `ui-vite/src/services/decisionApi.contract.test.ts` | Vitest suite |

## Files Added

- `contracts/one_button_consumer_contract_v1.json`
- `backend/tests/contract_metrics.py`
- `backend/tests/test_cross_layer_contracts.py`
- `backend/tests/test_startup_parity_main_vs_run_api.py`
- `ui-vite/src/services/decisionApi.contract.test.ts`
- `audit_outputs/cross_layer_contract_test_plan.md`

## Files Updated

- `backend/tests/conftest.py`

## Required Fixtures

1. Shared contract fixture: `contracts/one_button_consumer_contract_v1.json`
2. Frontend sample request payload embedded in fixture under `frontend_request_sample`
3. Required stage manifest in fixture under `required_stage_manifest`
4. Startup parity route subset in fixture under `startup_parity_required_routes`
5. Error semantics map in fixture under `error_semantics`

## Metric Outputs

Pytest emits `audit_outputs/contract_test_metrics.json` with:

- `contract_test_pass_rate`
- `startup_parity_pass_rate`
- `schema_regression_rate`

## CI Integration Plan

### Phase 1 (immediate)
Add a contract gate job in CI that executes:

```bash
python -m pytest backend/tests/test_cross_layer_contracts.py backend/tests/test_startup_parity_main_vs_run_api.py -q
npm --prefix ui-vite run test -- --run src/services/decisionApi.contract.test.ts
```

Archive:

- `audit_outputs/contract_test_metrics.json`
- `audit_outputs/cross_layer_contract_test_plan.md`

### Phase 2 (quality gates)
Set threshold checks:

1. `contract_test_pass_rate == 1.0`
2. `startup_parity_pass_rate == 1.0`
3. `schema_regression_rate == 0.0`

Fail CI when any threshold is violated.

### Phase 3 (nightly extension)
Run full one-button regression suite nightly in addition to targeted contract suites:

```bash
python -m pytest backend/tests/test_one_button_run.py -q
```

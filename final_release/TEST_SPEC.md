# Test Specification
## Hybrid Decision Support System - Complete Test Suite

**Version:** 1.2.0  
**Generated:** 2026-01-15  
**Status:** Production

---

## Overview

This document defines the complete test specification for the Hybrid Decision Support System, covering unit tests, integration tests, enforcement tests, and audit validations.

---

## Test Categories

### 1. Controller Enforcement Tests

**File:** `tests/test_controller_enforcement.py`

| Test | Description | Severity |
|------|-------------|----------|
| `test_no_forbidden_imports_in_routers` | Verify no router imports service modules directly | CRITICAL |
| `test_no_direct_instantiation_in_routers` | Verify no router instantiates services | CRITICAL |
| `test_scoring_router_uses_dispatch` | Verify scoring_router uses controller.dispatch() | HIGH |
| `test_router_registry_completeness` | Verify all routers registered | HIGH |

**Run:**
```bash
pytest tests/test_controller_enforcement.py -v
python tests/test_controller_enforcement.py  # JSON report
```

**Expected Output:**
```json
{
  "status": "PASS",
  "files_checked": 16,
  "violations": [],
  "summary": {}
}
```

---

### 2. Router Registry Tests

**File:** `tests/test_router_registry.py`

| Test | Description |
|------|-------------|
| `test_all_routers_registered` | Verify all routers in registry |
| `test_router_info_schema` | Verify RouterInfo schema |
| `test_killswitch_registered` | Verify kill-switch router |
| `test_no_duplicate_prefixes` | Verify unique prefixes |
| `test_minimum_route_count` | Verify 190+ routes |

---

### 3. MainController Tests

**File:** `tests/test_main_controller.py`

| Test | Description |
|------|-------------|
| `test_dispatch_valid_service` | Valid service dispatch |
| `test_dispatch_invalid_service` | Invalid service rejection |
| `test_dispatch_invalid_action` | Invalid action rejection |
| `test_dispatch_8_step_pipeline` | Full pipeline execution |
| `test_dispatch_auth_required` | Auth enforcement |
| `test_dispatch_context_enrichment` | Context propagation |
| `test_dispatch_xai_integration` | XAI layer for scoring |
| `test_dispatch_logging` | Audit log generation |

**Test Fixture:**
```python
@pytest.fixture
def controller():
    return MainController(
        scoring_service=MockScoringService(),
        market_service=MockMarketService(),
        feedback_service=MockFeedbackService()
    )

async def test_dispatch_scoring_rank(controller):
    result = await controller.dispatch(
        service="scoring",
        action="rank",
        payload={"skills": ["python"], "interests": ["ai"]},
        context={"user_id": "test-user"}
    )
    assert "careers" in result
    assert "_meta" in result
```

---

### 4. Scoring Router Tests

**File:** `tests/test_scoring_router.py`

| Test | Description |
|------|-------------|
| `test_rank_endpoint` | POST /api/v1/scoring/rank |
| `test_score_endpoint` | POST /api/v1/scoring/score |
| `test_weights_get` | GET /api/v1/scoring/weights |
| `test_weights_put` | PUT /api/v1/scoring/weights |
| `test_reset_endpoint` | POST /api/v1/scoring/reset |
| `test_config_endpoint` | GET /api/v1/scoring/config |
| `test_no_bypass` | Verify controller.dispatch used |

**Integration Test:**
```python
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_scoring_rank_integration():
    response = client.post(
        "/api/v1/scoring/rank",
        json={
            "user_id": "test-user",
            "skills": ["python", "machine-learning"],
            "interests": ["ai-research"]
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "careers" in data
    assert "_meta" in data
    assert data["_meta"]["service"] == "scoring"
    assert data["_meta"]["action"] == "rank"
```

---

### 5. Kill-Switch Tests

**File:** `tests/test_killswitch.py`

| Test | Description | Auth |
|------|-------------|------|
| `test_status_endpoint` | GET /api/v1/kill-switch/status | ADMIN |
| `test_activate` | POST /api/v1/kill-switch/activate | ADMIN |
| `test_deactivate` | POST /api/v1/kill-switch/deactivate | ADMIN |
| `test_unauthorized_access` | 401 without admin token | - |

---

### 6. Market Intelligence Tests

**File:** `tests/test_market.py`

| Test | Description |
|------|-------------|
| `test_signal_generation` | POST /api/v1/market/signal |
| `test_trends_analysis` | GET /api/v1/market/trends |
| `test_forecast` | POST /api/v1/market/forecast |
| `test_gap_analysis` | POST /api/v1/market/gap |

---

### 7. Health & Ops Tests

**File:** `tests/test_health.py`

| Test | Description | Expected |
|------|-------------|----------|
| `test_health_check` | GET /api/v1/health | 200 |
| `test_readiness` | GET /api/v1/health/ready | 200 |
| `test_liveness` | GET /api/v1/health/live | 200 |
| `test_metrics` | GET /api/v1/ops/metrics | 200 |

---

## Test Execution

### Full Test Suite
```bash
pytest tests/ -v --tb=short
```

### With Coverage
```bash
pytest tests/ --cov=backend --cov-report=html
```

### Specific Categories
```bash
# Enforcement only
pytest tests/test_controller_enforcement.py -v

# Integration only
pytest tests/integration/ -v

# Smoke tests
pytest tests/smoke/ -v
```

### Parallel Execution
```bash
pytest tests/ -n auto  # Requires pytest-xdist
```

---

## Test Coverage Requirements

| Module | Required Coverage |
|--------|-------------------|
| `main_controller.py` | ≥ 90% |
| `router_registry.py` | ≥ 85% |
| `scoring_router.py` | ≥ 80% |
| `All routers` | ≥ 75% |
| `Services` | ≥ 70% |

---

## Audit Test Matrix

| Audit Layer | Test File | Pass Criteria |
|-------------|-----------|---------------|
| L1: Routing | `test_router_registry.py` | All routers registered |
| L2: Registry | `test_router_registry.py` | 190+ routes |
| L3: Controller | `test_controller_enforcement.py` | 0 bypass violations |
| L4: Service | `test_main_controller.py` | All handlers work |
| L5: Decision | `test_scoring_router.py` | dispatch() used |
| L6: Frontend | `test_api_integration.py` | Endpoints accessible |
| L7: Ops | `test_health.py` | Health checks pass |

---

## CI/CD Integration

### GitHub Actions
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pytest tests/ -v --tb=short
```

### Pre-Commit Hook
```bash
#!/bin/bash
# .git/hooks/pre-commit
python tests/test_controller_enforcement.py
if [ $? -ne 0 ]; then
    echo "Controller enforcement check failed!"
    exit 1
fi
```

---

## Failure Response Matrix

| Test Failure | Severity | Response |
|--------------|----------|----------|
| Controller bypass detected | CRITICAL | Block merge |
| Router not registered | HIGH | Block deploy |
| Coverage < threshold | MEDIUM | Warning |
| Health check fails | CRITICAL | Rollback |

---

## Report Generation

### JSON Report
```bash
pytest tests/ --json-report --json-report-file=test_report.json
```

### HTML Report
```bash
pytest tests/ --html=test_report.html --self-contained-html
```

### JUnit XML (CI)
```bash
pytest tests/ --junitxml=junit.xml
```

---

*Test specification maintained by QA Team - Last Updated: 2026-01-15*

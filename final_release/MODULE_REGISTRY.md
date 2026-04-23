# Module Registry
## Hybrid Decision Support System - Complete Module Inventory

**Version:** 1.2.0  
**Generated:** 2026-01-15  
**Status:** Production

---

## Overview

This document provides the complete registry of all modules in the system, their responsibilities, dependencies, and compliance status.

---

## Core Modules

### 1. Main Controller (`backend/main_controller.py`)

| Property | Value |
|----------|-------|
| **Type** | Controller |
| **Responsibility** | Central dispatch orchestrator |
| **Dependencies** | All service modules |
| **Auth Level** | N/A (handles auth) |
| **Status** | ✅ Active |

**Key Methods:**
- `dispatch()` - 8-step pipeline entry point
- `_dispatch_validate()` - Service/action validation
- `_dispatch_to_service()` - Handler routing

---

### 2. Router Registry (`backend/api/router_registry.py`)

| Property | Value |
|----------|-------|
| **Type** | Registry |
| **Responsibility** | Deterministic router registration |
| **Dependencies** | All router modules |
| **Auth Level** | N/A |
| **Status** | ✅ Active |

**Key Functions:**
- `get_all_routers()` - Returns all registered routers
- `RouterInfo` - Router configuration dataclass
- `AuthLevel` - Authentication level enum

---

### 3. Scoring Service (`backend/scoring/`)

| Module | Responsibility | Status |
|--------|----------------|--------|
| `engine.py` | RankingEngine core logic | ✅ Active |
| `service.py` | ScoringService wrapper | ✅ Active |
| `cache.py` | ScoringCache implementation | ✅ Active |
| `weight_optimizer.py` | Weight tuning | ✅ Active |
| `domain.py` | Domain models | ✅ Active |

**Access Pattern:**
- ❌ Direct import forbidden
- ✅ Via `controller.dispatch(service="scoring", action="...")`

---

### 4. Market Intelligence (`backend/market/`)

| Module | Responsibility | Status |
|--------|----------------|--------|
| `analyzer.py` | Market trend analysis | ✅ Active |
| `signal_processor.py` | Signal generation | ✅ Active |
| `router.py` | API router | ✅ Active |
| `cache.py` | Market data caching | ✅ Active |

**Access Pattern:**
- ❌ Direct import forbidden in routers
- ✅ Via `controller.dispatch(service="market", action="...")`

---

### 5. Feedback System (`backend/feedback/`)

| Module | Responsibility | Status |
|--------|----------------|--------|
| `router.py` | Feedback API router | ✅ Active |
| `service.py` | FeedbackService | ✅ Active |
| `models.py` | Feedback domain models | ✅ Active |
| `storage.py` | Persistence layer | ✅ Active |

---

### 6. Inference Engine (`backend/inference/`)

| Module | Responsibility | Status |
|--------|----------------|--------|
| `engine.py` | Main inference logic | ✅ Active |
| `service.py` | InferenceService wrapper | ✅ Active |
| `models.py` | ML model management | ✅ Active |

---

### 7. Ops Hub (`backend/ops/`)

| Module | Responsibility | Status |
|--------|----------------|--------|
| `integration.py` | OpsHub central integration | ✅ Active |
| `health.py` | Health check logic | ✅ Active |
| `metrics.py` | Metrics collection | ✅ Active |
| `killswitch/api.py` | Kill-switch API | ✅ Active |
| `killswitch/service.py` | Kill-switch service | ✅ Active |

---

### 8. Explain/XAI (`backend/api/controllers/`)

| Module | Responsibility | Status |
|--------|----------------|--------|
| `explain_controller.py` | ExplainController | ✅ Active |
| `xai_service.py` | XAI generation | ✅ Active |

---

### 9. LiveOps (`backend/liveops/`)

| Module | Responsibility | Status |
|--------|----------------|--------|
| `command_engine.py` | Live operations commands | ✅ Active |
| `router.py` | LiveOps API router | ✅ Active |

---

## API Routers

| Router | File | Prefix | Status |
|--------|------|--------|--------|
| Health | `routers/health_router.py` | `/api/v1/health` | ✅ Registered |
| Ops | `routers/ops_router.py` | `/api/v1/ops` | ✅ Registered |
| ML | `routers/ml_router.py` | `/api/v1/ml` | ✅ Registered |
| MLOps | `routers/mlops_router.py` | `/api/v1/mlops` | ✅ Registered |
| Inference | `routers/infer_router.py` | `/api/v1/infer` | ✅ Registered |
| Pipeline | `routers/pipeline_router.py` | `/api/v1/pipeline` | ✅ Registered |
| Crawler | `routers/crawler_router.py` | `/api/v1/crawlers` | ✅ Registered |
| Chat | `routers/chat_router.py` | `/api/v1/chat` | ✅ Registered |
| Feedback | `feedback/router.py` | - | ✅ Registered |
| Eval | `routers/eval_router.py` | `/api/v1/eval` | ✅ Registered |
| Rules | `routers/rules_router.py` | `/api/v1/rules` | ✅ Registered |
| Taxonomy | `routers/taxonomy_router.py` | `/api/v1/taxonomy` | ✅ Registered |
| Scoring | `routers/scoring_router.py` | `/api/v1/scoring` | ✅ Registered |
| Market | `market/router.py` | `/api/v1/market` | ✅ Registered |
| Kill-Switch | `ops/killswitch/api.py` | `/api/v1/kill-switch` | ✅ Registered |
| Explain | `routers/explain_router.py` | - | ✅ Registered |
| LiveOps | `routers/liveops_router.py` | `/api/v1/live` | ✅ Registered |
| Admin Auth | `modules/admin_auth/routes.py` | - | ✅ Registered |
| Admin Gateway | `modules/admin_gateway/routes.py` | - | ✅ Registered |
| Governance | `routers/governance_router.py` | `/api/v1/governance` | ✅ Registered |

---

## Module Dependencies Graph

```
                    ┌─────────────────┐
                    │  MainController │
                    └────────┬────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
    ┌───────────┐     ┌───────────┐     ┌───────────┐
    │  Scoring  │     │  Market   │     │  Feedback │
    │  Service  │     │  Service  │     │  Service  │
    └─────┬─────┘     └─────┬─────┘     └─────┬─────┘
          │                 │                 │
          ▼                 ▼                 ▼
    ┌───────────┐     ┌───────────┐     ┌───────────┐
    │  Ranking  │     │  Signal   │     │  Storage  │
    │  Engine   │     │ Processor │     │  Layer    │
    └───────────┘     └───────────┘     └───────────┘
```

---

## Compliance Status

### Controller Bypass Check

| Module | Bypass Violations | Status |
|--------|-------------------|--------|
| scoring_router.py | 0 | ✅ COMPLIANT |
| market_router.py | 0 | ✅ COMPLIANT |
| feedback_router.py | 0 | ✅ COMPLIANT |
| all others | 0 | ✅ COMPLIANT |

### Registry Check

| Router | Registered | Status |
|--------|------------|--------|
| Kill-Switch | ✅ Yes | ✅ COMPLIANT |
| All Core | ✅ Yes | ✅ COMPLIANT |

---

## Test Coverage

| Module | Unit Tests | Integration Tests |
|--------|------------|-------------------|
| MainController | ✅ | ✅ |
| ScoringService | ✅ | ✅ |
| MarketService | ✅ | ✅ |
| RouterRegistry | ✅ | ✅ |
| FeedbackService | ✅ | ✅ |

---

## Configuration Files

| File | Purpose |
|------|---------|
| `config/settings.yaml` | Main configuration |
| `config/auth_config.yaml` | Authentication settings |
| `config/services.yaml` | Service configuration |
| `.env` | Environment variables |

---

*Document auto-generated from codebase analysis - Last Updated: 2026-01-15*

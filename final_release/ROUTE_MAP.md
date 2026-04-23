# Route Map
## Hybrid Decision Support System - Complete API Routing Table

**Version:** 1.2.0  
**Generated:** 2026-01-15  
**Status:** Production

---

## Overview

This document provides the complete mapping of all API routes to their controllers, services, and authentication requirements.

## Architecture Flow

```
Client Request
     ↓
 APIRouter
     ↓
router_registry.py (validates registration)
     ↓
MainController.dispatch() (8-step pipeline)
     ↓
Service Layer
     ↓
Response + Metadata
```

---

## Core API Routes

### Health & Operations
| Route | Method | Controller | Service | Auth | Version |
|-------|--------|------------|---------|------|---------|
| `/api/v1/health` | GET/POST | OpsHub | HealthService | PUBLIC | v1 |
| `/api/v1/health/ready` | GET | OpsHub | HealthService | PUBLIC | v1 |
| `/api/v1/health/live` | GET | OpsHub | HealthService | PUBLIC | v1 |
| `/api/v1/ops/metrics` | GET | OpsHub | OpsService | ADMIN | v1 |
| `/api/v1/ops/config` | GET/PUT | OpsHub | OpsService | ADMIN | v1 |

### Kill-Switch (Operations)
| Route | Method | Controller | Service | Auth | Version |
|-------|--------|------------|---------|------|---------|
| `/api/v1/kill-switch/status` | GET | KillSwitchController | KillSwitchService | ADMIN | v1 |
| `/api/v1/kill-switch/activate` | POST | KillSwitchController | KillSwitchService | ADMIN | v1 |
| `/api/v1/kill-switch/deactivate` | POST | KillSwitchController | KillSwitchService | ADMIN | v1 |
| `/api/v1/kill-switch/rules` | GET/POST | KillSwitchController | KillSwitchService | ADMIN | v1 |
| `/api/v1/kill-switch/audit` | GET | KillSwitchController | KillSwitchService | ADMIN | v1 |

### Scoring Engine
| Route | Method | Controller | Service | Auth | Version |
|-------|--------|------------|---------|------|---------|
| `/api/v1/scoring/rank` | POST | MainController | ScoringService | USER | v1 |
| `/api/v1/scoring/score` | POST | MainController | ScoringService | USER | v1 |
| `/api/v1/scoring/weights` | GET/PUT | MainController | ScoringService | USER | v1 |
| `/api/v1/scoring/reset` | POST | MainController | ScoringService | ADMIN | v1 |
| `/api/v1/scoring/config` | GET | MainController | ScoringService | USER | v1 |

### Market Intelligence
| Route | Method | Controller | Service | Auth | Version |
|-------|--------|------------|---------|------|---------|
| `/api/v1/market/signal` | POST | MainController | MarketService | USER | v1 |
| `/api/v1/market/trends` | GET | MainController | MarketService | USER | v1 |
| `/api/v1/market/forecast` | POST | MainController | MarketService | USER | v1 |
| `/api/v1/market/gap` | POST | MainController | MarketService | USER | v1 |

### Machine Learning & Inference
| Route | Method | Controller | Service | Auth | Version |
|-------|--------|------------|---------|------|---------|
| `/api/v1/ml/train` | POST | MainController | MLService | USER | v1 |
| `/api/v1/ml/models` | GET | MainController | MLService | USER | v1 |
| `/api/v1/mlops/train` | POST | MainController | MLOpsService | ADMIN | v1 |
| `/api/v1/mlops/deploy` | POST | MainController | MLOpsService | ADMIN | v1 |
| `/api/v1/mlops/rollback` | POST | MainController | MLOpsService | ADMIN | v1 |
| `/api/v1/infer/predict` | POST | MainController | InferenceService | USER | v1 |
| `/api/v1/infer/batch` | POST | MainController | InferenceService | USER | v1 |

### Chat & Feedback
| Route | Method | Controller | Service | Auth | Version |
|-------|--------|------------|---------|------|---------|
| `/api/v1/chat/message` | POST | MainController | ChatService | USER | v1 |
| `/api/v1/chat/history` | GET | MainController | ChatService | USER | v1 |
| `/api/v1/chat/feedback` | POST | MainController | FeedbackService | USER | v1 |
| `/api/v1/feedback/submit` | POST | MainController | FeedbackService | USER | v1 |
| `/api/v1/feedback/list` | GET | MainController | FeedbackService | ADMIN | v1 |

### Pipeline & Data
| Route | Method | Controller | Service | Auth | Version |
|-------|--------|------------|---------|------|---------|
| `/api/v1/pipeline/run` | POST | MainController | PipelineService | ADMIN | v1 |
| `/api/v1/pipeline/status` | GET | MainController | PipelineService | ADMIN | v1 |
| `/api/v1/crawlers/start` | POST | MainController | CrawlerService | ADMIN | v1 |
| `/api/v1/crawlers/stop` | POST | MainController | CrawlerService | ADMIN | v1 |
| `/api/v1/crawlers/status` | GET | MainController | CrawlerService | ADMIN | v1 |

### Governance & Rules
| Route | Method | Controller | Service | Auth | Version |
|-------|--------|------------|---------|------|---------|
| `/api/v1/governance/approve` | POST | MainController | GovernanceService | ADMIN | v1 |
| `/api/v1/governance/reject` | POST | MainController | GovernanceService | ADMIN | v1 |
| `/api/v1/governance/status` | GET | MainController | GovernanceService | ADMIN | v1 |
| `/api/v1/rules/evaluate` | POST | MainController | RuleEngineService | USER | v1 |
| `/api/v1/rules/get` | GET | MainController | RuleEngineService | USER | v1 |
| `/api/v1/rules/reload` | POST | MainController | RuleEngineService | ADMIN | v1 |

### Taxonomy & Knowledge Base
| Route | Method | Controller | Service | Auth | Version |
|-------|--------|------------|---------|------|---------|
| `/api/v1/taxonomy/resolve` | POST | MainController | TaxonomyService | USER | v1 |
| `/api/v1/taxonomy/get` | GET | MainController | TaxonomyService | USER | v1 |
| `/api/v1/taxonomy/detect` | POST | MainController | TaxonomyService | USER | v1 |
| `/api/v1/kb/get` | GET | MainController | KBService | USER | v1 |
| `/api/v1/kb/list` | GET | MainController | KBService | USER | v1 |
| `/api/v1/kb/search` | POST | MainController | KBService | USER | v1 |

### Evaluation
| Route | Method | Controller | Service | Auth | Version |
|-------|--------|------------|---------|------|---------|
| `/api/v1/eval/run` | POST | MainController | EvalService | ADMIN | v1 |
| `/api/v1/eval/get` | GET | MainController | EvalService | ADMIN | v1 |
| `/api/v1/eval/baselines` | GET | MainController | EvalService | ADMIN | v1 |

---

## Explain API Routes

| Route | Method | Controller | Service | Auth | Version |
|-------|--------|------------|---------|------|---------|
| `/api/v1/explain/run` | POST | ExplainController | XAIService | USER | v1 |
| `/api/v1/explain/get/{id}` | GET | ExplainController | XAIService | USER | v1 |
| `/api/v1/explain/history` | GET | ExplainController | XAIService | USER | v1 |
| `/api/v2/explain/run` | POST | ExplainController | XAIService | USER | v2 |
| `/api/v2/explain/batch` | POST | ExplainController | XAIService | USER | v2 |

---

## Admin API Routes

| Route | Method | Controller | Service | Auth | Version |
|-------|--------|------------|---------|------|---------|
| `/api/v1/admin/auth/login` | POST | AdminController | AdminAuthService | PUBLIC | v1 |
| `/api/v1/admin/auth/refresh` | POST | AdminController | AdminAuthService | USER | v1 |
| `/api/v1/admin/gateway/routes` | GET | AdminController | AdminGatewayService | ADMIN | v1 |
| `/api/v1/admin/gateway/config` | GET/PUT | AdminController | AdminGatewayService | ADMIN | v1 |
| `/api/v1/feedback/public/submit` | POST | FeedbackController | FeedbackService | PUBLIC | v1 |

---

## LiveOps API Routes

| Route | Method | Controller | Service | Auth | Version |
|-------|--------|------------|---------|------|---------|
| `/api/v1/live/command` | POST | LiveOpsController | CommandEngine | ADMIN | v1 |
| `/api/v1/live/status` | GET | LiveOpsController | CommandEngine | ADMIN | v1 |
| `/api/v1/live/config` | GET/PUT | LiveOpsController | CommandEngine | ADMIN | v1 |
| `/api/v1/live/models` | GET | LiveOpsController | CommandEngine | ADMIN | v1 |
| `/api/v1/live/warmup` | POST | LiveOpsController | CommandEngine | ADMIN | v1 |

---

## Route Registration

All routes MUST be registered in `backend/api/router_registry.py`:

```python
from backend.api.router_registry import get_all_routers

for router_info in get_all_routers():
    app.include_router(
        router_info.router, 
        prefix=router_info.prefix,
        tags=router_info.tags
    )
```

---

## Route Validation Rules

1. **All routes MUST go through `MainController.dispatch()`**
2. **No direct service imports in routers**
3. **Authentication level must match route sensitivity**
4. **All routes must be registered in `router_registry.py`**
5. **Correlation ID must be propagated**

---

## Total Route Count

- **Core Routes:** 45+
- **Admin Routes:** 5+
- **Explain Routes:** 5+
- **LiveOps Routes:** 5+
- **Kill-Switch Routes:** 15+
- **Total Registered:** 190+ endpoints

---

*Document maintained by Architecture Team*

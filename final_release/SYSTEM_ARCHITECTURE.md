# System Architecture - Final Release

## Version: 1.0.0 (Academic Defense Ready)
## Date: 2026-02-13
## Status: FROZEN

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    HYBRID DECISION SUPPORT SYSTEM (HDSS)                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │  Frontend   │───▶│   Backend   │───▶│     ML      │───▶│   Output    │  │
│  │   (GĐ6)     │    │   (GĐ5)     │    │ Pipeline    │    │  Response   │  │
│  └─────────────┘    └──────┬──────┘    └─────────────┘    └─────────────┘  │
│                            │                                                │
│                            ▼                                                │
│         ┌─────────────────────────────────────────────┐                    │
│         │              MAIN CONTROLLER                 │                    │
│         │         (Central Orchestrator)               │                    │
│         └──────────────────┬──────────────────────────┘                    │
│                            │                                                │
│    ┌───────────┬───────────┼───────────┬───────────┬───────────┐          │
│    ▼           ▼           ▼           ▼           ▼           ▼          │
│ ┌──────┐  ┌──────┐  ┌───────────┐  ┌──────┐  ┌──────┐  ┌───────────┐     │
│ │ GĐ1  │  │ GĐ2  │  │    GĐ3    │  │ GĐ4  │  │ GĐ5  │  │    GĐ6    │     │
│ │ ML   │  │ XAI  │  │Rule+Tmpl  │  │Ollama│  │ API  │  │ Frontend  │     │
│ │ Eval │  │ SHAP │  │  Engine   │  │ LLM  │  │Router│  │   React   │     │
│ └──────┘  └──────┘  └───────────┘  └──────┘  └──────┘  └───────────┘     │
│                                                                             │
│                    ┌─────────────────────────────────┐                     │
│                    │           OPS HUB               │                     │
│                    │  (31 Services - Zero Orphans)   │                     │
│                    └─────────────────────────────────┘                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Inventory

| Component | Location | LOC | Status |
|-----------|----------|-----|--------|
| MainController | `backend/main_controller.py` | 2393 | ✅ Frozen |
| ML Evaluation | `backend/evaluation/` | ~2000 | ✅ Frozen |
| XAI Service | `backend/scoring/explain/xai.py` | ~500 | ✅ Frozen |
| Stage 3 Engine | `backend/explain/stage3/` | ~400 | ✅ Frozen |
| Stage 4 Adapter | `backend/explain/stage4/` | ~300 | ✅ Frozen |
| API Router | `backend/api/routers/` | ~600 | ✅ Frozen |
| Frontend | `ui-vite/src/` | ~4000 | ✅ Frozen |
| Ops Hub | `backend/ops/` | ~5000 | ✅ Frozen |

**Total Python Files:** 232
**Total Backend LOC:** ~15,000+

---

## 3. Data Flow Diagram

```
                              USER INPUT
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          FRONTEND (GĐ6)                                  │
│  ExplainPage.tsx ─► ExplainForm ─► Submit ─► explainApi.ts              │
└──────────────────────────────────────┬───────────────────────────────────┘
                                       │ POST /api/v1/explain
                                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          BACKEND (GĐ5)                                   │
│  main.py ─► explain_router ─► ExplainController ─► MainController       │
└──────────────────────────────────────┬───────────────────────────────────┘
                                       │
                             ┌─────────┴─────────┐
                             ▼                   ▼
                    ┌────────────────┐  ┌────────────────┐
                    │   ML Model     │  │   Rule Engine  │
                    │  (GĐ1: Eval)   │  │   (Matching)   │
                    └───────┬────────┘  └───────┬────────┘
                            │                   │
                            └─────────┬─────────┘
                                      ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          XAI SERVICE (GĐ2)                               │
│  SHAP TreeExplainer ─► Feature Importance ─► Reasons List               │
└──────────────────────────────────────┬───────────────────────────────────┘
                                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       STAGE 3 ENGINE (GĐ3)                               │
│  Rule Map ─► Template Matching ─► explain_text                          │
└──────────────────────────────────────┬───────────────────────────────────┘
                                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       STAGE 4 ADAPTER (GĐ4)                              │
│  Ollama Client ─► llama3.2:1b ─► llm_text (Enhanced Explanation)        │
└──────────────────────────────────────┬───────────────────────────────────┘
                                       ▼
                               RESPONSE JSON
                    {career, confidence, reasons, llm_text, trace_id}
```

---

## 4. Control Flow

```
Main Entry Points:
├── POST /api/v1/explain      ──► ExplainController ──► Full Pipeline
├── POST /api/v1/profile/process ──► ProfileProcessor ──► Validation
├── POST /api/v1/recommendations ──► MainController.recommend()
├── GET /health/full          ──► OpsHub.health.check_all()
└── GET /metrics              ──► OpsHub.metrics.export_prometheus()

Pipeline Stages (Sequential):
  GĐ1 (ML Eval) ──► GĐ2 (XAI) ──► GĐ3 (Rule) ──► GĐ4 (Ollama) ──► GĐ5 (API) ──► GĐ6 (UI)
```

---

## 5. Dependency Graph

### No Circular Dependencies ✅

```
backend/run_api.py
    └── backend/main_controller.py
         ├── backend/processor.py
         ├── backend/rule_engine/
         ├── backend/embedding_engine.py
         ├── backend/crawler_manager.py
         ├── backend/ops/integration.py
         │    └── 31 ops services (zero orphans)
         └── backend/evaluation/
              ├── service.py
              ├── stability_service.py
              └── drift_monitor.py
```

### Verification:
- All imports are unidirectional (parent → child)
- No cross-module circular references
- MainController is the single orchestrator
- No bypass patterns detected

---

## 6. Hidden API Audit

| Endpoint | Visibility | Status |
|----------|------------|--------|
| `/api/v1/explain` | PUBLIC | ✅ Documented |
| `/api/v1/profile/process` | PUBLIC | ✅ Documented |
| `/api/v1/recommendations` | PUBLIC | ✅ Documented |
| `/health/*` | PUBLIC | ✅ Documented |
| `/metrics/*` | PUBLIC | ✅ Documented |
| `/ops/*` | INTERNAL | ✅ Documented |

**No Hidden APIs Detected** ✅

---

## 7. Technology Stack

| Layer | Technology | Version |
|-------|------------|---------|
| Backend | FastAPI | 0.100+ |
| ML | scikit-learn | 1.3+ |
| XAI | SHAP | 0.42+ |
| LLM | Ollama (llama3.2:1b) | Local |
| Frontend | React + Vite | 18.x |
| Database | SQLite | 3.x |
| Metrics | Custom + Prometheus | - |

---

## 8. Architecture Certification

| Check | Status | Evidence |
|-------|--------|----------|
| No circular dependency | ✅ PASS | Import graph analysis |
| No bypass main-controller | ✅ PASS | All routes go through controller |
| No hidden API | ✅ PASS | Endpoint audit complete |
| Single orchestrator | ✅ PASS | MainController is central |
| Ops services wired | ✅ PASS | 31 services, zero orphans |

**Architecture Status: FROZEN & CERTIFIED**

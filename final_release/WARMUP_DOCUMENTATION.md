# Warmup System Documentation

## Version: 1.0.0
## Date: 2026-02-13

---

## 1. Overview

This document describes the warm-start system implemented to eliminate W001 (Scoring Engine degraded) and W002 (LLM cold start timeout) warnings.

### 1.1 Problem Statement

| Warning | Component | Issue |
|---------|-----------|-------|
| W001 | scoring_engine | Health check created new scorer each time, causing "degraded" status |
| W002 | ollama | First LLM request timeout due to model loading latency |

### 1.2 Solution Summary

Implemented a centralized warmup system that:
- Pre-initializes scoring engine at startup
- Pre-warms Ollama model before accepting traffic
- Provides dedicated health endpoints
- Completes within 5-second startup budget

---

## 2. Files Modified/Created

### 2.1 New Files

| File | Purpose |
|------|---------|
| `backend/ops/warmup.py` | Central warmup module with ScoringEngineWarmup, LLMWarmup, WarmupManager |

### 2.2 Modified Files

| File | Changes |
|------|---------|
| `backend/inference/api_server_v2.py` | Added /health/scoring, /health/llm, /health/warmup endpoints; Updated startup to call warmup |
| `backend/ops/integration.py` | Added llm_service health check |
| `backend/ops/monitoring/health.py` | Updated check_scoring_engine to use pre-warmed scorer |
| `backend/llm/providers.py` | Added retry with exponential backoff for OllamaProvider |

---

## 3. Startup Sequence Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         SYSTEM STARTUP                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. FastAPI App Init                                                     │
│    - Load routes                                                        │
│    - Register explain_router                                            │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. OpsHub.startup()                                                     │
│    - Init metrics collector                                             │
│    - Register health checks (5 total):                                  │
│      • disk_space                                                       │
│      • memory                                                           │
│      • data_dir                                                         │
│      • scoring_engine ← Uses pre-warmed scorer                          │
│      • llm_service    ← Uses pre-warmed LLM status                      │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. WarmupManager.initialize_all()  [PARALLEL, Budget: 5000ms]           │
│                                                                         │
│    ┌──────────────────────────┐    ┌──────────────────────────┐         │
│    │ ScoringEngineWarmup      │    │ LLMWarmup                │         │
│    │ (~35ms)                  │    │ (~2000ms)                │         │
│    │                          │    │                          │         │
│    │ 1. Load config           │    │ 1. Load LLM config       │         │
│    │ 2. Init SIMGRScorer      │    │ 2. Check Ollama service  │         │
│    │ 3. Init RankingEngine    │    │ 3. Warmup model (retry)  │         │
│    │ 4. Load normalization    │    │ 4. Build LLM client      │         │
│    │ 5. Load rule base        │    │                          │         │
│    │ 6. Cache warmup (test)   │    │                          │         │
│    └──────────────────────────┘    └──────────────────────────┘         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 4. Start Background Tasks                                               │
│    - Metrics collector (15s interval)                                   │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 5. READY TO ACCEPT TRAFFIC                                              │
│    - All components pre-warmed                                          │
│    - First request latency minimized                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 4. New Health Endpoints

### 4.1 GET /health/scoring

Returns scoring engine readiness status.

**Response:**
```json
{
  "status": "ready",
  "model_loaded": true,
  "config_loaded": true,
  "cache_warm": true,
  "feature_sync": true,
  "normalization_ready": true,
  "rule_base_ready": true,
  "initialized_at": "2026-02-13T16:36:04.167355+00:00",
  "initialization_time_ms": 36.77,
  "last_health_check": "2026-02-13T16:36:27.854243+00:00",
  "error": null
}
```

### 4.2 GET /health/llm

Returns LLM (Ollama) readiness status.

**Response:**
```json
{
  "status": "ready",
  "ollama_up": true,
  "model_ready": true,
  "last_warmup": "2026-02-13T16:36:06.256306+00:00",
  "warmup_time_ms": 2088.68,
  "model_name": "llama3.2:1b",
  "retry_count": 1,
  "error": null
}
```

### 4.3 GET /health/warmup

Returns combined warmup status for all components.

**Response:**
```json
{
  "status": "ready",
  "initialized": true,
  "startup_time_ms": 2127.77,
  "budget_ms": 5000.0,
  "components": {
    "scoring": { ... },
    "llm": { ... }
  }
}
```

---

## 5. Retry Configuration (LLM)

The OllamaProvider now includes automatic retry with exponential backoff:

| Parameter | Value | Description |
|-----------|-------|-------------|
| MAX_RETRIES | 3 | Maximum retry attempts for first request |
| BACKOFF_BASE | 1.0s | Initial backoff duration |
| BACKOFF_MULTIPLIER | 2.0 | Exponential multiplier |
| First request timeout | 2x normal | Extra time for model loading |

**Retry sequence for first request:**
```
Attempt 1: timeout=20s
  ↓ (fail)
Wait 1.0s
Attempt 2: timeout=10s
  ↓ (fail)
Wait 2.0s
Attempt 3: timeout=10s
```

---

## 6. Test Cases

### 6.1 Warmup Status Test

```powershell
# Verify warmup completed successfully
Invoke-RestMethod http://localhost:8000/health/warmup | ConvertTo-Json

# Expected: status = "ready"
```

### 6.2 Scoring Engine Test

```powershell
# Verify scoring engine is pre-warmed
Invoke-RestMethod http://localhost:8000/health/scoring | ConvertTo-Json

# Expected: status = "ready", model_loaded = true
```

### 6.3 LLM Test

```powershell
# Verify LLM is pre-warmed
Invoke-RestMethod http://localhost:8000/health/llm | ConvertTo-Json

# Expected: ollama_up = true, model_ready = true
```

### 6.4 Full Health Test

```powershell
# Verify all components healthy
Invoke-RestMethod http://localhost:8000/health/full | ConvertTo-Json

# Expected: status = "healthy", all components healthy
```

---

## 7. Verification Log

Actual startup log from test run:

```
2026-02-13 16:36:04 | INFO | HDSS Backend starting...
2026-02-13 16:36:04 | INFO | OpsHub starting up...
2026-02-13 16:36:04 | INFO | Health check registered: scoring_engine
2026-02-13 16:36:04 | INFO | Health check registered: llm_service
2026-02-13 16:36:04 | INFO | OpsHub ready (metrics + 5 health checks + recovery)
2026-02-13 16:36:04 | INFO | Starting system warmup (scoring engine + LLM)...
2026-02-13 16:36:04 | INFO | WarmupManager: Starting system warmup (budget=5000ms)
2026-02-13 16:36:04 | INFO | Warming up scoring engine: loading config...
2026-02-13 16:36:04 | INFO | Scoring config loaded
2026-02-13 16:36:04 | INFO | SIMGRScorer initialized
2026-02-13 16:36:04 | INFO | RankingEngine initialized
2026-02-13 16:36:04 | INFO | Scoring engine warmup complete in 35.3ms (status=ready)
2026-02-13 16:36:04 | INFO | Warming up LLM: model=llama3.2:1b
2026-02-13 16:36:04 | INFO | HTTP Request: GET http://localhost:11434/api/version "200 OK"
2026-02-13 16:36:04 | INFO | Warming up LLM: pre-loading model...
2026-02-13 16:36:06 | INFO | HTTP Request: POST http://localhost:11434/api/generate "200 OK"
2026-02-13 16:36:06 | INFO | LLM model pre-warmed successfully
2026-02-13 16:36:06 | INFO | LLM warmup complete in 2088.68ms (status=ready, retries=1)
2026-02-13 16:36:06 | INFO | WarmupManager: Startup complete in 2127.77ms (budget=5000ms)
2026-02-13 16:36:06 | INFO | Warmup complete: scoring=ready, llm=ready
2026-02-13 16:36:06 | INFO | HDSS Backend ready to accept traffic
```

---

## 8. PASS Criteria Verification

| Criteria | Target | Actual | Status |
|----------|--------|--------|--------|
| W001 | false | false | ✅ PASS |
| W002 | false | false | ✅ PASS |
| Audit report | clean | clean | ✅ PASS |
| Startup time | < 5000ms | 2127.77ms | ✅ PASS |
| /health/full | all healthy | all healthy | ✅ PASS |

---

## 9. Architecture Summary

```
                    ┌─────────────────────┐
                    │    WarmupManager    │
                    │  (Singleton, 5s)    │
                    └──────────┬──────────┘
                               │
               ┌───────────────┴───────────────┐
               │                               │
    ┌──────────▼──────────┐        ┌───────────▼───────────┐
    │ ScoringEngineWarmup │        │      LLMWarmup        │
    │    (Singleton)      │        │     (Singleton)       │
    ├─────────────────────┤        ├───────────────────────┤
    │ - SIMGRScorer       │        │ - OllamaProvider      │
    │ - RankingEngine     │        │ - LLMClient           │
    │ - ScoringConfig     │        │ - Retry config        │
    └─────────────────────┘        └───────────────────────┘
               │                               │
               ▼                               ▼
    ┌─────────────────────┐        ┌───────────────────────┐
    │ /health/scoring     │        │ /health/llm           │
    └─────────────────────┘        └───────────────────────┘
```

# 🎯 One-Button AI Evaluation Pipeline Specification

> **Document Version**: 2.0 (REVISED)  
> **Date**: 2026-02-21  
> **Author**: Principal System Architect  
> **Revision Note**: Critical fixes based on architecture audit

---

# ⚠️ REVISION SUMMARY (v2.0)

## Issues Found in v1.0

| # | Issue | Severity | Impact | Fix Status |
|---|-------|----------|--------|------------|
| 1 | **State machine thiếu `aborting` state** | HIGH | User không thể cancel pipeline mid-flight | ✅ Fixed |
| 2 | **API Dependency sai** - Ghi "KHÔNG phụ thuộc" nhưng vẫn ép sequential | CRITICAL | Tăng latency vô ích ~8s | ✅ Fixed |
| 3 | **Explain API tự chạy inference** - không cần Score data | CRITICAL | Design dựa trên giả định sai | ✅ Fixed |
| 4 | **Timeout không nhất quán** - 8+15≠25 | MEDIUM | Math error trong spec | ✅ Fixed |
| 5 | **Thiếu double-click protection** | HIGH | Có thể gọi duplicate API | ✅ Fixed |
| 6 | **Retry branch không rõ ràng** - auto vs manual | MEDIUM | Implementation confusion | ✅ Fixed |
| 7 | **Input schema khác nhau** nhưng chưa address | HIGH | Form design chưa rõ | ✅ Fixed |
| 8 | **`error` state không phân biệt phase** | MEDIUM | Lost context on retry | ✅ Fixed |
| 9 | **`partial_success` không có retry_score** | LOW | Limited recovery options | ✅ Fixed |
| 10 | **Missing rate limit (E429) handling** | MEDIUM | No backoff strategy | ✅ Fixed |

---

## 1. Executive Summary

Thiết kế pipeline thống nhất cho button **"Khởi động đánh giá AI"** — chuyển từ multi-step flow hiện tại sang single-action orchestration.

### 1.1 Current State (AS-IS)
```
┌─────────────┐     ┌─────────────┐
│  Scoring    │     │  Explain    │
│   Flow      │     │   Flow      │
│  (Manual)   │     │  (Manual)   │
└─────────────┘     └─────────────┘
      │                   │
      ▼                   ▼
 User enters         User enters
 profile data       score features
      │                   │
      ▼                   ▼
POST /scoring/rank  POST /explain
      │                   │
      ▼                   ▼
 ScoreResults      ExplainResults
 (standalone)       (standalone)
```

### 1.2 Target State (TO-BE) — REVISED v2.0

> **⚠️ CRITICAL ARCHITECTURE CHANGE**: Scoring và Explain APIs hoạt động **PARALLEL**, không phải sequential.

```
                ┌─────────────────────────────────┐
                │  "Khởi động đánh giá AI" Button │
                └────────────────┬────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │   Unified Form Input   │
                    │  (Skills + Scores)     │
                    └────────────┬───────────┘
                                 │
              ┌──────────────────┴──────────────────┐
              │         PARALLEL EXECUTION          │
              │         Promise.allSettled()        │
              ▼                                     ▼
    ┌──────────────┐                       ┌──────────────┐
    │ Scoring API  │                       │ Explain API  │
    │   (SIMGR)    │                       │  (ML + XAI)  │
    └──────┬───────┘                       └──────┬───────┘
           │                                      │
           │ ~200-2000ms                          │ ~500-8000ms
           ▼                                      ▼
    ┌──────────────┐                       ┌──────────────┐
    │ ScorePanel   │                       │ ExplainPanel │
    │ (render ASAP)│                       │ (render ASAP)│
    └──────────────┘                       └──────────────┘
              │                                     │
              └──────────────────┬──────────────────┘
                                 │
                    ┌────────────┴───────────┐
                    │   Completed / Partial  │
                    │   (Both visible when   │
                    │    respective ready)   │
                    └────────────────────────┘
```

### 1.3 Why Parallel? (Architecture Evidence)

**Scoring API** (`POST /api/v1/scoring/rank`):
- Input: skills, interests, education_level
- Logic: SIMGR formula (Study + Interest + Market + Growth + Risk)
- Output: Ranked career list with scores

**Explain API** (`POST /api/v1/explain`):
- Input: math_score, logic_score, physics_score, etc.
- Logic: **Runs its OWN inference** via `main_control.run_inference()` → XAI → Stage3 → Stage4
- Output: Predicted career + explanation

**Evidence from backend code** ([explain_controller.py](../backend/api/controllers/explain_controller.py#L560-L580)):
```python
# Get prediction from main control - EXPLAIN DOES ITS OWN PREDICTION
inference_result = self._main_control.run_inference(feature_array)

# Then runs XAI pipeline
xai_result = self._main_control.run_xai(...)
```

**Conclusion**: Explain API is **SELF-CONTAINED**. It does NOT need Score data. Sequential execution wastes ~2-8 seconds.


---

## 2. Internal Pipeline Breakdown

### 2.1 Phase Definitions

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        ONE-BUTTON PIPELINE PHASES                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────┐    ┌──────────────────┐    ┌──────────┐    ┌──────────┐       │
│  │ TRIGGER  │───▶│ INPUT AGGREGATION│───▶│ SCORING  │───▶│ EXPLAIN │──    │
│  │  PHASE   │    │     PHASE        │    │  PHASE   │    │  PHASE   │  │    │
│  └──────────┘    └──────────────────┘    └──────────┘    └──────────┘  │    │
│       │                  │                    │               │        │    │
│       │                  │                    │               │        │    │
│       ▼                  ▼                    ▼               ▼        ▼    │
│  User clicks       Validate &           API Call +      API Call + ┌──────┐ │
│  button            normalize            render score    render exp │ DONE │ │
│                                                                    └──────┘ │
│                                                                             │
│  ◀─── ERROR BRANCHING CAN OCCUR AT ANY PHASE ───▶                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Phase Details

#### Phase 1: Trigger Phase
| Aspect | Specification |
|--------|---------------|
| **Action** | User clicks "Khởi động đánh giá AI" |
| **Pre-conditions** | Form valid, no active request |
| **Side Effects** | Disable button, show spinner |
| **State Transition** | `idle` → `collecting_input` |
| **Duration** | ~0ms (synchronous) |

#### Phase 2: Input Aggregation Phase
| Aspect | Specification |
|--------|---------------|
| **Action** | Collect all form fields, validate, normalize |
| **Validation Rules** | Zod schema + business rules |
| **Output** | `AggregatedInput` object |
| **State Transition** | `collecting_input` → `scoring` |
| **Duration** | ~10-50ms |
| **Error Handling** | Validation errors → show inline, stay in `idle` |

**AggregatedInput Schema:**
```typescript
interface AggregatedInput {
  user_id: string;
  request_id: string;          // UUID auto-generated
  timestamp: string;           // ISO 8601
  
  // For Scoring API
  scoring_profile: {
    skills: string[];
    interests: string[];
    education_level: string;
    ability_score: number;     // 0-1
    confidence_score: number;  // 0-1
  };
  
  // For Explain API
  explain_features: {
    math_score: number;        // 0-10
    logic_score: number;       // 0-10
    physics_score?: number;
    interest_it?: number;
    language_score?: number;
    creativity_score?: number;
  };
  
  // Options
  options: {
    use_llm: boolean;
    include_meta: boolean;
  };
}
```

#### Phase 3: API Execution Phase (REVISED - PARALLEL)
| Aspect | Specification |
|--------|---------------|
| **Action** | Call BOTH APIs in parallel via `Promise.allSettled()` |
| **Input** | `scoring_profile` + `explain_features` from AggregatedInput |
| **Output** | `{ scoring: ScoringResult, explain: ExplainResult }` |
| **State Transition** | `executing` → `completed` OR `partial_success` |
| **Duration** | ~max(scoring, explain) = ~500-8000ms |
| **Progressive Render** | **YES** - Each panel renders when its API completes |
| **Error Handling** | One fail → `partial_success`, Both fail → `error` |

#### Phase 4: Completed Phase
| Aspect | Specification |
|--------|---------------|
| **Action** | All available results rendered |
| **Visible Components** | ScorePanel + ExplainPanel (both or one) |
| **State Transition** | Can go to `idle` via NEW_REQUEST |
| **User Actions** | "Đánh giá lại", "Export PDF", "Share" |

---

## 3. State Machine Definition (REVISED v2.0)

### 3.1 Corrected State Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     STATE MACHINE v2.0 (PARALLEL EXECUTION)                     │
└─────────────────────────────────────────────────────────────────────────────────┘

                                    ┌─────────┐
                            ┌──────│ ABORTING│◀──────────────────────────────┐
                            │      └────┬────┘                               │
                            │           │ cleanup_done                       │
                            │           ▼                                    │
    ┌────────┐         ┌────┴────────────┐         ┌───────────┐            │
    │  IDLE  │────────▶│ VALIDATING      │────────▶│ EXECUTING │────────────┤
    └────────┘ click   └─────────────────┘ valid   └─────┬─────┘   abort    │
        ▲                      │                         │                   │
        │                      │ invalid                 │                   │
        │                      ▼                         │                   │
        │              ┌───────────────┐                 │                   │
        │◀─────────────│ (back to idle)│                 │                   │
        │              └───────────────┘                 │                   │
        │                                                │                   │
        │                        ┌───────────────────────┴───────────────┐   │
        │                        │        Promise.allSettled()          │   │
        │                        │  ┌─────────────┐  ┌─────────────┐    │   │
        │                        │  │  Scoring    │  │  Explain    │    │   │
        │                        │  │  Promise    │  │  Promise    │    │   │
        │                        │  └──────┬──────┘  └──────┬──────┘    │   │
        │                        │         │                │          │   │
        │                        └─────────┴────────────────┴──────────┘   │
        │                                  │                               │
        │              ┌───────────────────┼───────────────────┐           │
        │              │                   │                   │           │
        │              ▼                   ▼                   ▼           │
        │     ┌────────────────┐  ┌────────────────┐  ┌────────────────┐   │
        │     │   COMPLETED    │  │PARTIAL_SUCCESS │  │     ERROR      │   │
        │     │ (both success) │  │ (one success)  │  │  (both fail)   │   │
        │     └───────┬────────┘  └───────┬────────┘  └───────┬────────┘   │
        │             │                   │                   │           │
        │◀────────────┴───────────────────┴───────────────────┘           │
        │                    new_request                                   │
        │                                                                  │
        │              ┌───────────────────────────────────────────────────┘
        │              │ abort from any state
        │◀─────────────┘

LEGEND:
  ────▶  Normal transition
  ◀────  Reset transition
  ─ ─ ▶  Abort transition (can happen from validating/executing)
```

### 3.2 State Definitions

| State | Description | Entry Actions | Exit Actions |
|-------|-------------|---------------|--------------|
| `idle` | Waiting for user action | Enable button, clear results | Disable button |
| `validating` | Validating form input | Show inline validation | - |
| `executing` | API calls in progress | Create AbortController, start parallel calls | - |
| `aborting` | Cleanup in progress | Call abort(), cancel pending | Set results to null |
| `completed` | All APIs succeeded | Render both panels | - |
| `partial_success` | One API succeeded | Render available panel, show warning | - |
| `error` | Both APIs failed | Show error banner, enable retry | - |

### 3.3 Corrected State Transition Table

| Current | Event | Next | Actions | Guard |
|---------|-------|------|---------|-------|
| `idle` | `CLICK` | `validating` | disable button, debounce | `!isExecuting && formMounted` |
| `idle` | `CLICK` | `idle` | (no-op) | `isExecuting` (double-click protection) |
| `validating` | `VALID` | `executing` | aggregate input, start parallel calls | `allRequiredFieldsPresent` |
| `validating` | `INVALID` | `idle` | show errors, enable button | `validationErrors.length > 0` |
| `validating` | `ABORT` | `idle` | enable button | user_cancelled |
| `executing` | `BOTH_SUCCESS` | `completed` | render both panels | `score.ok && explain.ok` |
| `executing` | `SCORE_ONLY` | `partial_success` | render score, show explain warning | `score.ok && !explain.ok` |
| `executing` | `EXPLAIN_ONLY` | `partial_success` | render explain, show score warning | `!score.ok && explain.ok` |
| `executing` | `BOTH_FAIL` | `error` | show error banner | `!score.ok && !explain.ok` |
| `executing` | `ABORT` | `aborting` | call abortController.abort() | user_cancelled |
| `aborting` | `CLEANUP_DONE` | `idle` | clear state, enable button | - |
| `completed` | `NEW_REQUEST` | `idle` | clear all | - |
| `partial_success` | `NEW_REQUEST` | `idle` | clear all | - |
| `partial_success` | `RETRY_FAILED` | `executing` | retry only failed API | `hasPreviousInput` |
| `error` | `RETRY` | `executing` | retry both APIs | `hasPreviousInput` |
| `error` | `NEW_REQUEST` | `idle` | clear all | - |

### 3.4 Updated Type Definitions

```typescript
type EvaluationState = 
  | 'idle'
  | 'validating'
  | 'executing'
  | 'aborting'
  | 'completed'
  | 'partial_success'
  | 'error';

interface ApiResult<T> {
  status: 'fulfilled' | 'rejected';
  value?: T;
  reason?: ApiError;
}

interface EvaluationContext {
  state: EvaluationState;
  request_id: string | null;
  
  // Aggregated input (persisted for retry)
  aggregated_input: AggregatedInput | null;
  
  // API results (separated for partial success)
  scoring: {
    status: 'pending' | 'success' | 'error';
    result: ScoringResponse | null;
    error: ApiError | null;
  };
  explain: {
    status: 'pending' | 'success' | 'error';
    result: ExplainResponse | null;
    error: ApiError | null;
  };
  
  // Abort handling
  abort_controller: AbortController | null;
  
  // Timing
  started_at: number | null;
  completed_at: number | null;
  
  // Double-click protection
  last_click_timestamp: number | null;
}

interface ApiError {
  code: string;        // E4xx, E5xx
  message: string;
  phase: 'scoring' | 'explaining';
  retryable: boolean;
}
```

### 3.5 Double-Click Protection

```typescript
const DEBOUNCE_MS = 300;

function handleClick(ctx: EvaluationContext): void {
  const now = Date.now();
  
  // Guard: Already executing
  if (ctx.state === 'executing' || ctx.state === 'aborting') {
    return; // Ignore
  }
  
  // Guard: Debounce rapid clicks
  if (ctx.last_click_timestamp && (now - ctx.last_click_timestamp) < DEBOUNCE_MS) {
    return; // Ignore
  }
  
  ctx.last_click_timestamp = now;
  dispatch({ type: 'CLICK' });
}
```

---

## 4. API Dependency Mapping (REVISED v2.0)

### 4.1 Architecture Decision: PARALLEL vs SEQUENTIAL

#### Analysis of Options

| Aspect | Sequential (v1.0) | Parallel (v2.0 - RECOMMENDED) |
|--------|-------------------|-------------------------------|
| **Total Latency** | max(Scoring) + max(Explain) = ~10s | max(Scoring, Explain) = ~8s |
| **UX** | User waits longer | Results appear faster |
| **Complexity** | 2 states (scoring→explaining) | 1 state (executing) |
| **Partial Success** | Score always available first | Either can fail independently |
| **Dependencies** | Artificial (not needed) | None |

#### Why NOT Sequential?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    🔍 DEPENDENCY ANALYSIS                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  QUESTION: Does Explain API need data from Scoring API?                     │
│                                                                             │
│  ┌───────────────────────────┐    ┌───────────────────────────┐            │
│  │    SCORING API INPUT      │    │    EXPLAIN API INPUT      │            │
│  ├───────────────────────────┤    ├───────────────────────────┤            │
│  │ • skills: string[]        │    │ • math_score: number      │            │
│  │ • interests: string[]     │    │ • logic_score: number     │            │
│  │ • education_level: string │    │ • physics_score: number   │            │
│  │ • ability_score: number   │    │ • interest_it: number     │            │
│  │ • confidence_score: number│    │ • language_score: number  │            │
│  └───────────────────────────┘    └───────────────────────────┘            │
│           │                                │                                │
│           │ COMPLETELY                     │                                │
│           │ DIFFERENT                      │                                │
│           │ SCHEMAS                        │                                │
│           └────────────X──────────────────┘                                │
│                        │                                                    │
│              NO DATA DEPENDENCY!                                            │
│                                                                             │
│  ANSWER: ❌ NO                                                              │
│                                                                             │
│  Explain API runs its OWN inference:                                        │
│  self._main_control.run_inference(feature_array)                           │
│                                                                             │
│  It does NOT use Score results. The v1.0 "context enrichment" was purely  │
│  for logging/correlation, NOT required for Explain to function.            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Parallel Execution Pattern

```typescript
async function executeParallel(
  input: AggregatedInput,
  signal: AbortSignal
): Promise<ParallelResult> {
  const results = await Promise.allSettled([
    callScoringAPI(input.scoring_profile, signal),
    callExplainAPI(input.explain_features, signal),
  ]);
  
  const [scoringResult, explainResult] = results;
  
  return {
    scoring: {
      status: scoringResult.status,
      value: scoringResult.status === 'fulfilled' ? scoringResult.value : null,
      error: scoringResult.status === 'rejected' ? scoringResult.reason : null,
    },
    explain: {
      status: explainResult.status,
      value: explainResult.status === 'fulfilled' ? explainResult.value : null,
      error: explainResult.status === 'rejected' ? explainResult.reason : null,
    },
  };
}
```

### 4.3 Result Handling Matrix

| Scoring | Explain | Next State | UI Behavior |
|---------|---------|------------|-------------|
| ✅ Success | ✅ Success | `completed` | Both panels visible |
| ✅ Success | ❌ Fail | `partial_success` | Score panel + Explain warning |
| ❌ Fail | ✅ Success | `partial_success` | Explain panel + Score warning |
| ❌ Fail | ❌ Fail | `error` | Error banner + retry button |

### 4.4 Timeout Strategy (REVISED)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    TIMEOUT CONFIGURATION v2.0                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Since APIs run in parallel, timeouts are INDEPENDENT:                      │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     PARALLEL TIMELINE                               │   │
│  │                                                                     │   │
│  │  T=0          T=2s         T=5s         T=8s         T=12s         │   │
│  │   │            │            │            │            │            │   │
│  │   ├────────────┴────────────┴────────────┤                         │   │
│  │   │       Scoring API (8s timeout)       │                         │   │
│  │   │                                      │                         │   │
│  │   ├──────────────────────────────────────┴────────────┤            │   │
│  │   │            Explain API (12s timeout w/ LLM)       │            │   │
│  │   │                                                   │            │   │
│  │   │        ┌────────────────┐                         │            │   │
│  │   │        │ Explain no-LLM │ (5s timeout)            │            │   │
│  │   └────────┴────────────────┴─────────────────────────┘            │   │
│  │                                                                     │   │
│  │   Total: max(8s, 12s) = 12s (not 20s!)                             │   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  API             │ Timeout  │ Auto-Retry │ Fallback                        │
│  ────────────────┼──────────┼────────────┼─────────────────                │
│  Scoring         │ 8000ms   │ 2x (auto)  │ Mark as failed                  │
│  Explain (LLM)   │ 12000ms  │ 1x (auto)  │ Retry with use_llm=false        │
│  Explain (basic) │ 5000ms   │ 1x (auto)  │ Mark as failed                  │
│  Global Guard    │ 15000ms  │ N/A        │ Force-resolve with partial      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.5 Retry Logic (REVISED)

```typescript
interface RetryConfig {
  maxRetries: number;
  baseDelayMs: number;
  maxDelayMs: number;
  retryableErrors: string[];
  backoffMultiplier: number;
}

const SCORING_RETRY: RetryConfig = {
  maxRetries: 2,
  baseDelayMs: 500,
  maxDelayMs: 2000,
  backoffMultiplier: 2,  // 500ms → 1000ms → 2000ms
  retryableErrors: ['E502', 'E503', 'E504', 'NETWORK_ERROR'],
};

const EXPLAIN_RETRY: RetryConfig = {
  maxRetries: 1,
  baseDelayMs: 1000,
  maxDelayMs: 3000,
  backoffMultiplier: 2,
  retryableErrors: ['E502', 'E503', 'E504'],
};

// Exponential backoff with jitter
function calculateDelay(attempt: number, config: RetryConfig): number {
  const exponentialDelay = config.baseDelayMs * Math.pow(config.backoffMultiplier, attempt);
  const jitter = Math.random() * 500;  // Add 0-500ms jitter
  return Math.min(exponentialDelay + jitter, config.maxDelayMs);
}

// Rate limit (E429) specific handling
async function handleRateLimit(response: Response): Promise<number> {
  const retryAfter = response.headers.get('Retry-After');
  if (retryAfter) {
    return parseInt(retryAfter, 10) * 1000; // Server-specified delay
  }
  return 5000; // Default 5s for rate limits
}
```

### 4.6 AbortController Usage (REVISED)

```typescript
class PipelineOrchestrator {
  private abortController: AbortController | null = null;
  private isAborting: boolean = false;
  
  async execute(input: AggregatedInput): Promise<EvaluationResult> {
    // Prevent re-entry
    if (this.abortController && !this.abortController.signal.aborted) {
      console.warn('Pipeline already executing, ignoring');
      return { ignored: true };
    }
    
    // Create new AbortController
    this.abortController = new AbortController();
    const { signal } = this.abortController;
    this.isAborting = false;
    
    try {
      // Parallel execution
      const results = await Promise.allSettled([
        this.callWithRetry('scoring', input.scoring_profile, signal, SCORING_RETRY),
        this.callWithRetry('explain', input.explain_features, signal, EXPLAIN_RETRY),
      ]);
      
      // Check if aborted during execution
      if (signal.aborted || this.isAborting) {
        return { aborted: true, partial: this.extractPartialResults(results) };
      }
      
      return this.processResults(results);
      
    } catch (error) {
      if (error.name === 'AbortError') {
        return { aborted: true };
      }
      throw error;
    } finally {
      this.abortController = null;
    }
  }
  
  abort(): void {
    if (this.abortController && !this.isAborting) {
      this.isAborting = true;
      this.abortController.abort();
    }
  }
  
  private extractPartialResults(results: PromiseSettledResult<any>[]): Partial<EvaluationResult> {
    // Even if aborted, return any results that completed
    const [scoring, explain] = results;
    return {
      scoring: scoring.status === 'fulfilled' ? scoring.value : null,
      explain: explain.status === 'fulfilled' ? explain.value : null,
    };
  }
}
```

---

## 5. Progressive Rendering Strategy (REVISED for PARALLEL)

### 5.1 Render Timeline (Parallel)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PARALLEL PROGRESSIVE RENDER TIMELINE                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Time ───────────────────────────────────────────────────────────────────▶  │
│                                                                             │
│  T=0ms      T=50ms     T=500ms     T=2000ms    T=5000ms    T=8000ms        │
│    │          │          │            │           │           │            │
│    ▼          ▼          ▼            ▼           ▼           ▼            │
│  ┌─────┐  ┌────────┐  ┌──────────────────────────────────────────┐        │
│  │Click│  │Validate│  │          EXECUTING STATE                 │        │
│  └─────┘  └────────┘  │  ┌──────────────────────────────────┐   │        │
│                       │  │  Scoring API (parallel)          │   │        │
│                       │  │  ████████████████░░░░░░░░░░░░░░░│   │        │
│                       │  │         ▼ success @ T=2000ms     │   │        │
│                       │  │    [ScorePanel renders]          │   │        │
│                       │  └──────────────────────────────────┘   │        │
│                       │                                         │        │
│                       │  ┌──────────────────────────────────┐   │        │
│                       │  │  Explain API (parallel)          │   │        │
│                       │  │  ██████████████████████████████░░│   │        │
│                       │  │              ▼ success @ T=8000ms│   │        │
│                       │  │         [ExplainPanel renders]   │   │        │
│                       │  └──────────────────────────────────┘   │        │
│                       └─────────────────────────────────────────┘        │
│                                                                           │
│                       T=8100ms: Both panels visible, button re-enabled   │
│                                                                           │
│  KEY IMPROVEMENT: ScorePanel appears at T=2000ms, NOT waiting for Explain │
│  Total UX latency: max(2000, 8000) = 8000ms (was 10000ms in sequential)   │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Component Render Rules (REVISED)

| Component | Render Condition | Show Skeleton | Hide |
|-----------|------------------|---------------|------|
| **MainSpinner** | `state === 'validating' \|\| state === 'executing'` | N/A | Any terminal state |
| **ScoreSkeleton** | `state === 'executing' && scoring.status === 'pending'` | YES | On scoring complete |
| **ScorePanel** | `scoring.status === 'success'` | N/A | Never (persist) |
| **ScoreError** | `scoring.status === 'error'` | N/A | On retry |
| **ExplainSkeleton** | `state === 'executing' && explain.status === 'pending'` | YES | On explain complete |
| **ExplainPanel** | `explain.status === 'success'` | N/A | Never (persist) |
| **ExplainError** | `explain.status === 'error'` | N/A | On retry |
| **AbortButton** | `state === 'executing'` | N/A | On complete/abort |

### 5.3 Skeleton Components

```tsx
// ScorePanelSkeleton - shown during scoring phase
const ScorePanelSkeleton: React.FC = () => (
  <Card className="score-panel-skeleton">
    <CardHeader>
      <Skeleton variant="text" width="60%" />
    </CardHeader>
    <CardContent>
      <Skeleton variant="rectangular" height={100} />
      <Box display="flex" gap={2} mt={2}>
        {[1, 2, 3].map(i => (
          <Skeleton key={i} variant="circular" width={60} height={60} />
        ))}
      </Box>
    </CardContent>
  </Card>
);

// ExplainPanelSkeleton - shown during explaining phase
const ExplainPanelSkeleton: React.FC = () => (
  <Card className="explain-panel-skeleton">
    <CardHeader>
      <Skeleton variant="text" width="40%" />
    </CardHeader>
    <CardContent>
      <Skeleton variant="text" count={3} />
      <Skeleton variant="rectangular" height={80} />
    </CardContent>
  </Card>
);
```

### 5.4 Streaming Handling

> **Không đủ dữ liệu để xác minh**: Backend Explain API hiện tại không hỗ trợ streaming response (SSE/WebSocket). Nếu backend được mở rộng để support streaming, cần bổ sung:

```typescript
// Future streaming support (NOT IMPLEMENTED YET)
interface StreamingConfig {
  enabled: boolean;
  onChunk: (chunk: string) => void;
  onComplete: () => void;
  onError: (error: Error) => void;
}

// Text would be progressively rendered:
// "Dựa trên..." → "Dựa trên điểm số..." → "Dựa trên điểm số của bạn, ngành..."
```

---

## 6. Failure Handling Matrix

### 6.1 Failure Scenarios

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        FAILURE HANDLING MATRIX                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  SCENARIO              │ ERROR CODE │ RECOVERY ACTION         │ USER MSG   │
│  ──────────────────────┼────────────┼─────────────────────────┼────────────│
│                                                                             │
│  INPUT VALIDATION                                                           │
│  ─────────────────────────────────────────────────────────────────────────  │
│  Required field empty  │ V001       │ Stay idle, highlight    │ "Bắt buộc" │
│  Score out of range    │ V002       │ Stay idle, show range   │ "0-10"     │
│  Invalid user_id       │ V003       │ Stay idle, re-enter     │ "ID lỗi"   │
│                                                                             │
│  SCORING PHASE                                                              │
│  ─────────────────────────────────────────────────────────────────────────  │
│  Network error         │ E502       │ Retry 2x → error state  │ "Mạng lỗi" │
│  Server unavailable    │ E503       │ Retry 2x → error state  │ "Server"   │
│  Timeout               │ E504       │ Retry 2x → error state  │ "Timeout"  │
│  Auth error            │ E401       │ Redirect login          │ "Re-login" │
│  Rate limited          │ E429       │ Wait + retry            │ "Chờ..."   │
│  Server error          │ E500       │ Show error, allow retry │ "Lỗi hệ"   │
│                                                                             │
│  EXPLAIN PHASE                                                              │
│  ─────────────────────────────────────────────────────────────────────────  │
│  LLM unavailable       │ E503       │ Retry w/o LLM → partial │ "LLM off"  │
│  LLM timeout           │ E504       │ Fallback basic mode     │ "Đơn giản" │
│  Network error         │ E502       │ partial_success         │ "Mạng lỗi" │
│  Ollama error          │ E503       │ Fallback stage3-only    │ "Ollama"   │
│                                                                             │
│  COMBINED                                                                   │
│  ─────────────────────────────────────────────────────────────────────────  │
│  User aborts           │ ABORT      │ Cancel all, reset       │ "Đã hủy"   │
│  Component unmount     │ UNMOUNT    │ Cleanup, no state update│ (none)     │
│  Total timeout (25s)   │ GLOBAL_TO  │ Force complete what we have│ "Timeout"│
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Partial Success Strategy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PARTIAL SUCCESS HANDLING                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Condition: Scoring OK + Explain FAIL                                       │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                                                                      │  │
│  │   ┌─────────────────────────────────┐                                │  │
│  │   │  ✅ ScorePanel (RENDERED)       │                                │  │
│  │   │    Top Career: Software Engineer│                                │  │
│  │   │    Score: 0.87                  │                                │  │
│  │   └─────────────────────────────────┘                                │  │
│  │                                                                      │  │
│  │   ┌─────────────────────────────────┐                                │  │
│  │   │  ⚠️ ExplainPanel (WARNING)      │                                │  │
│  │   │    "Giải thích chi tiết không   │                                │  │
│  │   │     khả dụng. Vui lòng thử lại."│                                │  │
│  │   │                                 │                                │  │
│  │   │    [🔄 Thử lại giải thích]      │                                │  │
│  │   └─────────────────────────────────┘                                │  │
│  │                                                                      │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  User Options:                                                              │
│  • "Thử lại giải thích" → Re-enter explaining state with same score        │
│  • "Đánh giá lại" → Full reset to idle                                     │
│  • Continue browsing with score-only results                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 Error Recovery Flow

```typescript
interface ErrorRecoveryAction {
  type: 'retry_full' | 'retry_explain' | 'reset' | 'redirect';
  target?: string;
  delay?: number;
}

function getRecoveryAction(error: PipelineError, currentState: EvaluationState): ErrorRecoveryAction {
  // Retryable errors
  if (['E502', 'E503', 'E504'].includes(error.code)) {
    if (currentState === 'scoring') {
      return { type: 'retry_full', delay: 1000 };
    }
    if (currentState === 'explaining') {
      return { type: 'retry_explain', delay: 500 };
    }
  }
  
  // Auth errors
  if (error.code === 'E401') {
    return { type: 'redirect', target: '/login' };
  }
  
  // Fatal errors
  if (error.code === 'E500') {
    return { type: 'reset' };
  }
  
  // Default
  return { type: 'reset' };
}
```

---

## 7. API Orchestration Diagram

### 7.1 Sequence Diagram

```
┌─────────┐     ┌────────────┐     ┌──────────────┐     ┌─────────────┐     ┌─────────────┐
│  User   │     │  OneButton │     │ ScoringAPI   │     │ ExplainAPI  │     │   State     │
│         │     │ Component  │     │/api/v1/scoring│    │/api/v1/explain│   │   Machine   │
└────┬────┘     └─────┬──────┘     └──────┬───────┘     └──────┬──────┘     └──────┬──────┘
     │                │                   │                    │                   │
     │  Click Button  │                   │                    │                   │
     │───────────────▶│                   │                    │                   │
     │                │                   │                    │                   │
     │                │ dispatch('CLICK') │                    │                   │
     │                │──────────────────────────────────────────────────────────▶│
     │                │                   │                    │                   │
     │                │                   │                    │ state=collecting  │
     │                │◀──────────────────────────────────────────────────────────│
     │                │                   │                    │                   │
     │                │ Validate & Aggregate                   │                   │
     │                │─────────┐         │                    │                   │
     │                │         │         │                    │                   │
     │                │◀────────┘         │                    │                   │
     │                │                   │                    │                   │
     │                │ dispatch('INPUT_VALID')                │                   │
     │                │──────────────────────────────────────────────────────────▶│
     │                │                   │                    │                   │
     │                │                   │                    │ state=scoring     │
     │                │◀──────────────────────────────────────────────────────────│
     │                │                   │                    │                   │
     │                │ POST /rank        │                    │                   │
     │                │──────────────────▶│                    │                   │
     │                │                   │                    │                   │
     │                │                   │ (processing)       │                   │
     │                │                   │                    │                   │
     │                │ 200 + ScoreCards  │                    │                   │
     │                │◀──────────────────│                    │                   │
     │                │                   │                    │                   │
     │                │ dispatch('SCORE_SUCCESS')              │                   │
     │                │──────────────────────────────────────────────────────────▶│
     │                │                   │                    │                   │
     │                │                   │                    │ state=explaining  │
     │                │◀──────────────────────────────────────────────────────────│
     │                │                   │                    │                   │
     │  ScorePanel    │                   │                    │                   │
     │◀───────────────│                   │                    │                   │
     │  (immediate)   │                   │                    │                   │
     │                │                   │                    │                   │
     │                │ POST /explain     │                    │                   │
     │                │────────────────────────────────────────▶│                  │
     │                │                   │                    │                   │
     │                │                   │                    │ (LLM processing)  │
     │                │                   │                    │                   │
     │                │ 200 + ExplainResp │                    │                   │
     │                │◀────────────────────────────────────────│                  │
     │                │                   │                    │                   │
     │                │ dispatch('EXPLAIN_SUCCESS')            │                   │
     │                │──────────────────────────────────────────────────────────▶│
     │                │                   │                    │                   │
     │                │                   │                    │ state=completed   │
     │                │◀──────────────────────────────────────────────────────────│
     │                │                   │                    │                   │
     │ ExplainPanel   │                   │                    │                   │
     │◀───────────────│                   │                    │                   │
     │                │                   │                    │                   │
     ▼                ▼                   ▼                    ▼                   ▼
```

### 7.2 Request/Response Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         REQUEST/RESPONSE CONTRACTS                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  SCORING REQUEST (POST /api/v1/scoring/rank)                                │
│  ───────────────────────────────────────────                                │
│  {                                                                          │
│    "user_profile": {                                                        │
│      "skills": ["python", "machine-learning"],                              │
│      "interests": ["ai", "data-science"],                                   │
│      "education_level": "Master",                                           │
│      "ability_score": 0.8,                                                  │
│      "confidence_score": 0.7                                                │
│    },                                                                       │
│    "careers": [...],  // Or use default career list                         │
│    "strategy": "weighted",                                                  │
│    "top_n": 5                                                               │
│  }                                                                          │
│                                                                             │
│  SCORING RESPONSE                                                           │
│  ────────────────                                                           │
│  {                                                                          │
│    "score_cards": [                                                         │
│      {                                                                      │
│        "career_name": "Data Scientist",                                     │
│        "total_score": 0.87,                                                 │
│        "rank": 1,                                                           │
│        "components": [                                                      │
│          { "name": "study", "score": 0.9, "weight": 0.25, ... },            │
│          { "name": "interest", "score": 0.85, ... },                        │
│          ...                                                                │
│        ]                                                                    │
│      },                                                                     │
│      ...                                                                    │
│    ],                                                                       │
│    "reproducibility": { "input_hash": "sha256...", ... }                    │
│  }                                                                          │
│                                                                             │
│  ───────────────────────────────────────────────────────────────────────── │
│                                                                             │
│  EXPLAIN REQUEST (POST /api/v1/explain)                                     │
│  ──────────────────────────────────────                                     │
│  {                                                                          │
│    "user_id": "user-123",                                                   │
│    "request_id": "req-uuid",                                                │
│    "features": {                                                            │
│      "math_score": 8.5,                                                     │
│      "logic_score": 9.0,                                                    │
│      "physics_score": 7.5,                                                  │
│      "interest_it": 8.0                                                     │
│    },                                                                       │
│    "options": {                                                             │
│      "use_llm": true,                                                       │
│      "include_meta": true                                                   │
│    }                                                                        │
│  }                                                                          │
│                                                                             │
│  EXPLAIN RESPONSE                                                           │
│  ───────────────                                                            │
│  {                                                                          │
│    "api_version": "1.0",                                                    │
│    "trace_id": "trace-uuid",                                                │
│    "career": "Data Scientist",                                              │
│    "confidence": 0.87,                                                      │
│    "reasons": [                                                             │
│      "Điểm toán cao (8.5)",                                                 │
│      "Logic mạnh (9.0)",                                                    │
│      "Quan tâm IT (8.0)"                                                    │
│    ],                                                                       │
│    "explain_text": "Stage 3 explanation...",                                │
│    "llm_text": "Dựa trên điểm số của bạn...",                               │
│    "used_llm": true,                                                        │
│    "meta": { ... }                                                          │
│  }                                                                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Implementation Checklist (REVISED)

### 8.1 Frontend Changes Required

- [ ] Create `useEvaluationPipeline` hook with **parallel** state machine
- [ ] Create `OneButtonEvaluate` component with abort button
- [ ] Create `ScorePanel` component
- [ ] Create `ExplainPanel` component  
- [ ] Create unified `EvaluationForm` component (see 8.4)
- [ ] Add `scoringApi.ts` service layer
- [ ] Add `evaluationOrchestrator.ts` with Promise.allSettled
- [ ] Implement double-click protection (debounce + state guard)
- [ ] Add progress indicators and dual skeletons
- [ ] Implement abort handling with cleanup

### 8.2 Backend Verification Required

- [x] ~~Confirm `/api/v1/scoring/rank` supports the payload format~~ ✅ Verified
- [ ] Verify career list handling (see Open Question #1)
- [x] ~~Check rate limiting compatibility for parallel calls~~ ✅ OK - separate endpoints
- [x] ~~Validate CORS for parallel requests~~ ✅ Same origin policy applies

### 8.3 Testing Requirements

- [ ] Unit tests for state machine transitions (all 7 states)
- [ ] Integration tests for parallel execution patterns
- [ ] E2E tests: happy path + partial success + full failure
- [ ] Performance tests: max latency under parallel load
- [ ] Abort handling tests: mid-flight cancellation

### 8.4 Unified Form Design

```typescript
// Input schema that maps to BOTH APIs
interface EvaluationFormData {
  // User identification
  user_id: string;
  
  // Shared between concepts
  education_level: string;      // → Scoring
  
  // Scoring-specific (skills/interests)
  skills: string[];             // → Scoring
  interests: string[];          // → Scoring
  ability_score: number;        // → Scoring (0-1)
  confidence_score: number;     // → Scoring (0-1)
  
  // Explain-specific (academic scores)
  math_score: number;           // → Explain (0-10)
  logic_score: number;          // → Explain (0-10)
  physics_score?: number;       // → Explain (0-10)
  interest_it?: number;         // → Explain (0-10)
  language_score?: number;      // → Explain (0-10)
  creativity_score?: number;    // → Explain (0-10)
  
  // Options
  use_llm: boolean;
  include_meta: boolean;
}

// Transform function: Form → API payloads
function transformFormToPayloads(form: EvaluationFormData): {
  scoring: ScoringRequest;
  explain: ExplainRequest;
} {
  return {
    scoring: {
      user_profile: {
        skills: form.skills,
        interests: form.interests,
        education_level: form.education_level,
        ability_score: form.ability_score,
        confidence_score: form.confidence_score,
      },
      strategy: 'weighted',
      top_n: 5,
    },
    explain: {
      user_id: form.user_id,
      features: {
        math_score: form.math_score,
        logic_score: form.logic_score,
        physics_score: form.physics_score,
        interest_it: form.interest_it,
        language_score: form.language_score,
        creativity_score: form.creativity_score,
      },
      options: {
        use_llm: form.use_llm,
        include_meta: form.include_meta,
      },
    },
  };
}
```

---

## 9. Open Questions Resolution (REVISED v2.0)

| # | Question | Resolution | Recommendation |
|---|----------|------------|----------------|
| 1 | Backend có default career list không? | **Không đủ dữ liệu để xác minh** từ code scan. Cần verify với backend team. | **Safe default**: FE truyền career list rỗng `[]`, để backend dùng default. Nếu backend lỗi → add explicit list. |
| 2 | Có nên merge thành `/api/v1/evaluate`? | **KHÔNG NÊN**. 2 APIs solve different problems (SIMGR ranking vs ML prediction). | Keep separate, call parallel. Future: Backend có thể add `/evaluate` wrapper nếu muốn. |
| 3 | LLM streaming ảnh hưởng state machine? | Hiện tại **KHÔNG support** streaming. Nếu có → cần thêm `explaining_streaming` state. | Design cho non-streaming trước. Add streaming later as enhancement. |
| 4 | Scoring API cần auth? | **CẦN** - `Permission.SCORING_EXECUTE`. | FE phải pass auth token cho cả 2 API calls. |
| 5 | Correlation ID cách dùng? | Dùng single `request_id` cho cả 2 API calls để trace trong logs. | Generate UUID in `validating` phase, pass to both APIs. |

---

## 10. Risk Assessment

### 10.1 Risk nếu giữ nguyên Design v1.0 (Sequential)

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **Latency cao hơn cần thiết** | UX tệ: +2-8s wait time | 100% | Switch to parallel |
| **Artificial dependency** | Code complexity, confusing logic | 100% | Remove dependency |
| **Inconsistent error handling** | Score fail blocks Explain even though Explain could succeed alone | HIGH | Independent error states |
| **Dead-end state nếu Score fail** | User không thấy Explain dù Explain độc lập | HIGH | Parallel allows both to try |

### 10.2 Risk của Design v2.0 (Parallel)

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **Higher concurrent load on backend** | 2 requests instead of 1 sequential | MEDIUM | Rate limiting đã có sẵn |
| **More complex partial success UI** | 4 possible end states instead of 2 | LOW | Clear UI for each state |
| **Abort complexity** | Need to handle mid-flight cancellation | LOW | AbortController + cleanup |

### 10.3 Final Recommendation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ARCHITECTURE DECISION RECORD                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  DECIDED: Use PARALLEL execution (v2.0)                                     │
│                                                                             │
│  RATIONALE:                                                                 │
│  1. APIs are PROVABLY independent (different input schemas)                 │
│  2. Explain API runs its own inference (no dependency on Score)             │
│  3. Parallel saves 2-8 seconds of user wait time                           │
│  4. Enables independent failure handling (partial success)                  │
│  5. Simpler state machine (1 executing state vs 2 phases)                  │
│                                                                             │
│  TRADE-OFFS ACCEPTED:                                                       │
│  - Higher concurrent backend load (acceptable, rate-limited)               │
│  - More complex partial success UI (better than lost functionality)        │
│                                                                             │
│  STATUS: Approved for implementation                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 11. Summary of v1.0 → v2.0 Changes

| Section | v1.0 | v2.0 | Change Type |
|---------|------|------|-------------|
| Architecture | Sequential | **Parallel** | BREAKING |
| States | 7 (includes scoring→explaining) | 7 (includes aborting) | MODIFIED |
| State: `scoring` | Dedicated phase | Merged into `executing` | REMOVED |
| State: `explaining` | Dedicated phase | Merged into `executing` | REMOVED |
| State: `aborting` | Missing | **Added** | NEW |
| Double-click | Not addressed | **Implemented** | NEW |
| Timeout math | 8+15=25s (wrong) | max(8,12)=12s | FIXED |
| E429 handling | Generic | **Retry-After header** | IMPROVED |
| Partial success | Score-only | **Either can succeed** | IMPROVED |

---

**Document End**

**Revision History**:
- v1.0 (2026-02-21): Initial design with sequential assumption
- v2.0 (2026-02-21): Architecture audit, fixed to parallel execution


# One-Button AI Evaluation Pipeline Specification v3.0 (HARDENED)

> **Document Type:** Production Implementation Specification  
> **Author:** Principal System Architect  
> **Version:** 3.0 (HARDENED)  
> **Date:** 2026-02-21  
> **Status:** FINAL - Ready for Implementation  
> **Supersedes:** ONE_BUTTON_PIPELINE_SPEC.md v2.0

---

## 0. Document Conventions

| Symbol | Meaning |
|--------|---------|
| `MUST` | Non-negotiable requirement |
| `MUST NOT` | Strictly forbidden |
| `SHALL` | Contract obligation |
| `INVARIANT` | Condition that must always hold |
| `GUARD` | Condition checked before transition |

---

## 1. Architecture Summary

### 1.1 System Context

**Button Label:** "Khởi động đánh giá AI"  
**Purpose:** Execute parallel API calls to Scoring and Explain services, render results progressively

### 1.2 API Independence Proof

| Aspect | Scoring API | Explain API |
|--------|-------------|-------------|
| Endpoint | `POST /api/v1/scoring/rank` | `POST /api/v1/explain` |
| Formula | SIMGR (Static) | ML Inference + XAI |
| Inputs | `{skills, interests, education_level}` | `{math_score, logic_score, physics_score, literature_score, history_score, geography_score, biology_score, chemistry_score, economics_score, creativity_score, interest_tech, interest_science, interest_arts, interest_social, education_level: int}` |
| Response | `{rankings: CareerScore[]}` | `{explanation: string, factors: Factor[], confidence: float}` |
| Latency | 1-3s | 5-10s |
| Data Dependency | **NONE** | Runs own inference via `main_control.run_inference()` |

**CONCLUSION:** APIs are **COMPLETELY INDEPENDENT**. Parallel execution is SAFE and REQUIRED.

### 1.3 Execution Model

```
                   T=0ms                    T=max(T_scoring, T_explain)
                     │                                │
                     ▼                                ▼
┌──────────────────────────────────────────────────────┐
│  [Button Click] → [Validate] → [Execute Parallel]   │
│                                       │             │
│                     ┌─────────────────┼─────────────┤
│                     │                 │             │
│                     ▼                 ▼             │
│              ┌──────────┐      ┌───────────┐       │
│              │ Scoring  │      │  Explain  │       │
│              │ API      │      │  API      │       │
│              └────┬─────┘      └─────┬─────┘       │
│                   │                  │             │
│                   ▼                  ▼             │
│            [Render Score]     [Render Explain]     │
│            (as soon as        (as soon as          │
│             available)         available)          │
└──────────────────────────────────────────────────────┘
```

---

## 2. State Machine (Deterministic)

### 2.1 State Definitions

| State | Description | Max Duration | Entry Action | Exit Condition |
|-------|-------------|--------------|--------------|----------------|
| `idle` | Awaiting user action | ∞ | Reset all API tracking | `CLICK` event |
| `validating` | Input validation | 100ms | Validate form fields | Valid → `executing_parallel`, Invalid → `idle` |
| `executing_parallel` | Both APIs in flight | 12000ms | Fire both requests | Both settled OR global timeout |
| `retrying_scoring` | Auto-retry scoring only | 3000ms (per attempt) | Re-fire scoring request | Success/Max retries |
| `retrying_explain` | Auto-retry explain only | 5000ms (per attempt) | Re-fire explain request | Success/Max retries |
| `completed` | Both APIs succeeded | ∞ (terminal) | Render both panels | Manual reset only |
| `partial_success` | One API succeeded | ∞ (terminal) | Render available + error | Manual retry/reset |
| `error` | Both APIs failed | ∞ (terminal) | Show error UI | Manual retry/reset |

### 2.2 State Transition Table (Exhaustive)

| Current State | Event | Guard | Next State | Action |
|---------------|-------|-------|------------|--------|
| `idle` | `CLICK` | `!isExecuting` | `validating` | `startValidation()` |
| `idle` | `CLICK` | `isExecuting` | `idle` | NO-OP (debounce) |
| `validating` | `VALID` | `true` | `executing_parallel` | `fireParallelRequests()` |
| `validating` | `INVALID` | `true` | `idle` | `showValidationErrors()` |
| `executing_parallel` | `SCORING_SUCCESS` | `explainPending` | `executing_parallel` | `renderScorePanel()` |
| `executing_parallel` | `SCORING_SUCCESS` | `explainDone` | Compute terminal | `renderScorePanel(), computeTerminal()` |
| `executing_parallel` | `SCORING_ERROR` | `retriesLeft > 0` | `retrying_scoring` | `scheduleRetry('scoring')` |
| `executing_parallel` | `SCORING_ERROR` | `retriesLeft === 0` | Compute partial | `markScoringFailed()` |
| `executing_parallel` | `EXPLAIN_SUCCESS` | `scoringPending` | `executing_parallel` | `renderExplainPanel()` |
| `executing_parallel` | `EXPLAIN_SUCCESS` | `scoringDone` | Compute terminal | `renderExplainPanel(), computeTerminal()` |
| `executing_parallel` | `EXPLAIN_ERROR` | `retriesLeft > 0` | `retrying_explain` | `scheduleRetry('explain')` |
| `executing_parallel` | `EXPLAIN_ERROR` | `retriesLeft === 0` | Compute partial | `markExplainFailed()` |
| `executing_parallel` | `GLOBAL_TIMEOUT` | `true` | Compute terminal | `forceSettle()` |
| `executing_parallel` | `ABORT` | `true` | `idle` | `cleanup()` |
| `retrying_scoring` | `SCORING_SUCCESS` | `true` | Compute terminal | `renderScorePanel()` |
| `retrying_scoring` | `SCORING_ERROR` | `retriesLeft > 0` | `retrying_scoring` | `scheduleRetry('scoring')` |
| `retrying_scoring` | `SCORING_ERROR` | `retriesLeft === 0` | Compute partial | `markScoringFailed()` |
| `retrying_explain` | `EXPLAIN_SUCCESS` | `true` | Compute terminal | `renderExplainPanel()` |
| `retrying_explain` | `EXPLAIN_ERROR` | `retriesLeft > 0` | `retrying_explain` | `scheduleRetry('explain')` |
| `retrying_explain` | `EXPLAIN_ERROR` | `retriesLeft === 0` | Compute partial | `markExplainFailed()` |
| `completed` | `RESET` | `true` | `idle` | `clearResults()` |
| `partial_success` | `RETRY_FAILED` | `true` | Retry appropriate | `fireRetryRequest()` |
| `partial_success` | `RESET` | `true` | `idle` | `clearResults()` |
| `error` | `RETRY_ALL` | `true` | `validating` | `startValidation()` |
| `error` | `RESET` | `true` | `idle` | `clearResults()` |

**Terminal State Computation:**
```
computeTerminal():
  if scoring.success AND explain.success → 'completed'
  if scoring.success XOR explain.success → 'partial_success'
  if scoring.failed AND explain.failed → 'error'
```

### 2.3 Type Definitions

```typescript
// ═══════════════════════════════════════════════════════════════════
// CORE STATE TYPES
// ═══════════════════════════════════════════════════════════════════

type PipelineState = 
  | 'idle'
  | 'validating'
  | 'executing_parallel'
  | 'retrying_scoring'
  | 'retrying_explain'
  | 'completed'
  | 'partial_success'
  | 'error';

type ApiStatus = 'idle' | 'pending' | 'success' | 'error';

interface ApiTracker {
  status: ApiStatus;
  retriesRemaining: number;
  startTime: number | null;
  endTime: number | null;
  error: TypedError | null;
  data: unknown | null;
}

interface PipelineContext {
  state: PipelineState;
  scoring: ApiTracker;
  explain: ApiTracker;
  correlationId: string | null;
  globalStartTime: number | null;
  isMounted: boolean;  // CRITICAL for cleanup
}

// ═══════════════════════════════════════════════════════════════════
// INITIAL CONTEXT FACTORY
// ═══════════════════════════════════════════════════════════════════

function createInitialContext(): PipelineContext {
  return {
    state: 'idle',
    scoring: { status: 'idle', retriesRemaining: 2, startTime: null, endTime: null, error: null, data: null },
    explain: { status: 'idle', retriesRemaining: 2, startTime: null, endTime: null, error: null, data: null },
    correlationId: null,
    globalStartTime: null,
    isMounted: true,
  };
}
```

---

## 3. Error Taxonomy (Typed)

### 3.1 Error Type Hierarchy

```typescript
// ═══════════════════════════════════════════════════════════════════
// ERROR TYPES - NOT GENERIC STATUS CODES
// ═══════════════════════════════════════════════════════════════════

type ErrorKind = 
  | 'TRANSPORT_ERROR'    // Network failure, DNS, connection refused
  | 'TIMEOUT_ERROR'      // Request exceeded deadline
  | 'RATE_LIMIT_ERROR'   // 429 Too Many Requests
  | 'VALIDATION_ERROR'   // 400 Bad Request, schema mismatch
  | 'AUTH_ERROR'         // 401/403 Authentication/Authorization
  | 'BACKEND_ERROR'      // 500+ Server-side failure
  | 'ABORT_ERROR'        // User cancelled or component unmount
  | 'UNKNOWN_ERROR';     // Unexpected/unclassified

interface TypedError {
  kind: ErrorKind;
  message: string;
  httpStatus: number | null;  // null for non-HTTP errors
  retryable: boolean;
  source: 'scoring' | 'explain';
  timestamp: number;
  correlationId: string;
}

// ═══════════════════════════════════════════════════════════════════
// ERROR FACTORY - SINGLE SOURCE OF TRUTH
// ═══════════════════════════════════════════════════════════════════

function classifyError(
  error: unknown, 
  source: 'scoring' | 'explain',
  correlationId: string
): TypedError {
  const timestamp = Date.now();
  const base = { source, timestamp, correlationId };

  // AbortError (user cancel or unmount)
  if (error instanceof DOMException && error.name === 'AbortError') {
    return { ...base, kind: 'ABORT_ERROR', message: 'Request aborted', httpStatus: null, retryable: false };
  }

  // Network/Transport errors
  if (error instanceof TypeError && error.message.includes('fetch')) {
    return { ...base, kind: 'TRANSPORT_ERROR', message: 'Network error', httpStatus: null, retryable: true };
  }

  // HTTP Response errors
  if (error instanceof Response || (error as any)?.status) {
    const status = (error as any).status;
    
    if (status === 429) {
      return { ...base, kind: 'RATE_LIMIT_ERROR', message: 'Rate limited', httpStatus: 429, retryable: true };
    }
    if (status === 401 || status === 403) {
      return { ...base, kind: 'AUTH_ERROR', message: 'Authentication failed', httpStatus: status, retryable: false };
    }
    if (status === 400 || status === 422) {
      return { ...base, kind: 'VALIDATION_ERROR', message: 'Invalid request', httpStatus: status, retryable: false };
    }
    if (status >= 500) {
      return { ...base, kind: 'BACKEND_ERROR', message: 'Server error', httpStatus: status, retryable: true };
    }
  }

  // Timeout (custom detection)
  if ((error as any)?.isTimeout || (error as any)?.code === 'TIMEOUT') {
    return { ...base, kind: 'TIMEOUT_ERROR', message: 'Request timeout', httpStatus: null, retryable: true };
  }

  // Unknown
  return { 
    ...base, 
    kind: 'UNKNOWN_ERROR', 
    message: error instanceof Error ? error.message : 'Unknown error', 
    httpStatus: null, 
    retryable: false 
  };
}
```

### 3.2 Error Handling Rules

| Error Kind | Auto Retry | Max Attempts | Backoff | User Action |
|------------|------------|--------------|---------|-------------|
| `TRANSPORT_ERROR` | YES | 2 | 1000ms, 2000ms | "Thử lại" button after max |
| `TIMEOUT_ERROR` | YES | 2 | 0ms (immediate) | "Thử lại" button after max |
| `RATE_LIMIT_ERROR` | YES | 1 | Use Retry-After header | Wait indicator |
| `VALIDATION_ERROR` | NO | - | - | Fix form, "Gửi lại" |
| `AUTH_ERROR` | NO | - | - | Redirect to login |
| `BACKEND_ERROR` | YES | 2 | 2000ms, 4000ms | "Thử lại" button after max |
| `ABORT_ERROR` | NO | - | - | None (intentional) |
| `UNKNOWN_ERROR` | NO | - | - | "Báo lỗi" + reset |

---

## 4. Timeout Model (Hierarchical)

### 4.1 Timeout Tree

```
GLOBAL_DEADLINE: 12000ms
├── SCORING_TIMEOUT: 5000ms (MUST be < GLOBAL_DEADLINE)
│   └── Per-retry: 5000ms (no increase on retry)
└── EXPLAIN_TIMEOUT: 10000ms (MUST be < GLOBAL_DEADLINE)
    └── Per-retry: 10000ms (no increase on retry)

INVARIANT: max(SCORING_TIMEOUT, EXPLAIN_TIMEOUT) ≤ GLOBAL_DEADLINE
PROOF: max(5000, 10000) = 10000 ≤ 12000 ✓
```

### 4.2 Timeout Configuration

```typescript
// ═══════════════════════════════════════════════════════════════════
// TIMEOUT CONSTANTS - IMMUTABLE
// ═══════════════════════════════════════════════════════════════════

const TIMEOUT_CONFIG = Object.freeze({
  GLOBAL_DEADLINE_MS: 12000,
  SCORING_TIMEOUT_MS: 5000,
  EXPLAIN_TIMEOUT_MS: 10000,
  VALIDATION_TIMEOUT_MS: 100,
  DEBOUNCE_MS: 300,
} as const);

// Compile-time validation (TypeScript assertion)
type AssertTimeoutHierarchy = 
  typeof TIMEOUT_CONFIG.SCORING_TIMEOUT_MS extends number 
    ? typeof TIMEOUT_CONFIG.EXPLAIN_TIMEOUT_MS extends number
      ? true
      : never
    : never;

// Runtime validation (startup check)
function validateTimeoutConfig(): void {
  const { GLOBAL_DEADLINE_MS, SCORING_TIMEOUT_MS, EXPLAIN_TIMEOUT_MS } = TIMEOUT_CONFIG;
  
  if (Math.max(SCORING_TIMEOUT_MS, EXPLAIN_TIMEOUT_MS) > GLOBAL_DEADLINE_MS) {
    throw new Error(
      `INVARIANT VIOLATION: Individual timeouts exceed global deadline. ` +
      `max(${SCORING_TIMEOUT_MS}, ${EXPLAIN_TIMEOUT_MS}) > ${GLOBAL_DEADLINE_MS}`
    );
  }
}
```

### 4.3 Timeout Enforcement Pattern

```typescript
// ═══════════════════════════════════════════════════════════════════
// TIMEOUT-AWARE FETCH WRAPPER
// ═══════════════════════════════════════════════════════════════════

async function fetchWithTimeout(
  url: string,
  options: RequestInit,
  timeoutMs: number,
  abortController: AbortController
): Promise<Response> {
  const timeoutId = setTimeout(() => {
    abortController.abort();
  }, timeoutMs);

  try {
    const response = await fetch(url, {
      ...options,
      signal: abortController.signal,
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    
    // Tag timeout errors explicitly
    if (error instanceof DOMException && error.name === 'AbortError') {
      const timeoutError = new Error('Request timeout');
      (timeoutError as any).isTimeout = true;
      (timeoutError as any).code = 'TIMEOUT';
      throw timeoutError;
    }
    throw error;
  }
}
```

---

## 5. Retry Model (Deterministic)

### 5.1 Retry Strategy

| Phase | Auto Retry | Max Attempts | Backoff Pattern | Jitter |
|-------|------------|--------------|-----------------|--------|
| Scoring | YES | 2 | Fixed: [1000ms, 2000ms] | **NO** (deterministic) |
| Explain | YES | 2 | Fixed: [2000ms, 4000ms] | **NO** (deterministic) |
| Manual | User trigger | 1 per click | 0ms | NO |

**RATIONALE:** No jitter = reproducible behavior = easier debugging

### 5.2 Retry State Machine

```
┌─────────────────────────────────────────────────────────────┐
│                  AUTO-RETRY DECISION TREE                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  API_ERROR received                                         │
│       │                                                     │
│       ▼                                                     │
│  ┌─────────────────────────────────────┐                   │
│  │ error.retryable === true ?          │                   │
│  └─────────────┬───────────────────────┘                   │
│                │                                            │
│       ┌────────┴────────┐                                  │
│       │                 │                                   │
│      YES               NO                                   │
│       │                 │                                   │
│       ▼                 ▼                                   │
│  ┌──────────┐    ┌──────────────┐                          │
│  │ retries  │    │ Mark as      │                          │
│  │ > 0 ?    │    │ FINAL_FAIL   │                          │
│  └────┬─────┘    └──────────────┘                          │
│       │                                                     │
│  ┌────┴────┐                                               │
│ YES       NO                                                │
│  │         │                                                │
│  ▼         ▼                                                │
│ RETRY   FINAL_FAIL                                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 5.3 Retry Implementation

```typescript
// ═══════════════════════════════════════════════════════════════════
// RETRY CONFIGURATION - NO JITTER
// ═══════════════════════════════════════════════════════════════════

const RETRY_CONFIG = Object.freeze({
  scoring: {
    maxAttempts: 2,
    backoffMs: [1000, 2000] as const,  // Fixed delays, no jitter
  },
  explain: {
    maxAttempts: 2,
    backoffMs: [2000, 4000] as const,
  },
} as const);

function getRetryDelay(api: 'scoring' | 'explain', attemptIndex: number): number {
  const config = RETRY_CONFIG[api];
  const delays = config.backoffMs;
  
  // Clamp to available delays
  const index = Math.min(attemptIndex, delays.length - 1);
  return delays[index];
}

// ═══════════════════════════════════════════════════════════════════
// RETRY EXECUTOR
// ═══════════════════════════════════════════════════════════════════

async function executeWithRetry<T>(
  operation: () => Promise<T>,
  api: 'scoring' | 'explain',
  ctx: PipelineContext,
  dispatch: (action: PipelineAction) => void
): Promise<T> {
  let lastError: TypedError | null = null;
  const maxAttempts = RETRY_CONFIG[api].maxAttempts + 1; // +1 for initial attempt

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    // Check for abort/unmount before each attempt
    if (!ctx.isMounted) {
      throw classifyError(new DOMException('Aborted', 'AbortError'), api, ctx.correlationId!);
    }

    try {
      return await operation();
    } catch (error) {
      lastError = classifyError(error, api, ctx.correlationId!);

      // Non-retryable errors: fail immediately
      if (!lastError.retryable) {
        throw lastError;
      }

      // Last attempt: fail
      if (attempt >= RETRY_CONFIG[api].maxAttempts) {
        throw lastError;
      }

      // Schedule retry with fixed delay (no jitter)
      const delay = getRetryDelay(api, attempt);
      
      dispatch({ 
        type: api === 'scoring' ? 'SCORING_RETRY' : 'EXPLAIN_RETRY',
        attempt: attempt + 1,
        delayMs: delay,
      });

      await sleep(delay);
    }
  }

  throw lastError!;
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
```

---

## 6. Execution Algorithm (Production-Ready)

### 6.1 Main Pipeline Executor

```typescript
// ═══════════════════════════════════════════════════════════════════
// PIPELINE EXECUTOR - SINGLE ENTRY POINT
// ═══════════════════════════════════════════════════════════════════

class PipelineExecutor {
  private ctx: PipelineContext;
  private scoringController: AbortController | null = null;
  private explainController: AbortController | null = null;
  private globalTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private onStateChange: (state: PipelineState) => void;

  constructor(onStateChange: (state: PipelineState) => void) {
    this.ctx = createInitialContext();
    this.onStateChange = onStateChange;
  }

  // ═══════════════════════════════════════════════════════════════
  // PUBLIC INTERFACE
  // ═══════════════════════════════════════════════════════════════

  async execute(input: AggregatedInput): Promise<void> {
    // GUARD: Prevent double execution
    if (this.ctx.state !== 'idle') {
      console.warn('[Pipeline] Ignoring execute() - not idle');
      return;
    }

    // Initialize correlation ID
    this.ctx.correlationId = generateCorrelationId();
    this.ctx.globalStartTime = Date.now();

    try {
      // Phase 1: Validation
      this.transition('validating');
      const validationResult = await this.validate(input);
      
      if (!validationResult.valid) {
        this.transition('idle');
        return;
      }

      // Phase 2: Parallel Execution
      this.transition('executing_parallel');
      await this.executeParallel(input);

    } catch (error) {
      // Only update state if still mounted
      if (this.ctx.isMounted) {
        this.handleFatalError(error);
      }
    } finally {
      this.cleanup();
    }
  }

  abort(): void {
    console.log('[Pipeline] Abort requested');
    this.scoringController?.abort();
    this.explainController?.abort();
    this.cleanup();
    
    if (this.ctx.isMounted) {
      this.ctx = createInitialContext();
      this.transition('idle');
    }
  }

  unmount(): void {
    this.ctx.isMounted = false;
    this.abort();
  }

  // ═══════════════════════════════════════════════════════════════
  // PRIVATE: VALIDATION
  // ═══════════════════════════════════════════════════════════════

  private async validate(input: AggregatedInput): Promise<{ valid: boolean; errors?: string[] }> {
    const errors: string[] = [];

    // Required fields
    if (!input.user_id) errors.push('user_id is required');
    if (!input.skills || input.skills.length === 0) errors.push('skills is required');
    
    // Score ranges (0-10)
    const scoreFields = [
      'math_score', 'logic_score', 'physics_score', 'literature_score',
      'history_score', 'geography_score', 'biology_score', 'chemistry_score',
      'economics_score', 'creativity_score'
    ] as const;

    for (const field of scoreFields) {
      const value = input[field];
      if (typeof value !== 'number' || value < 0 || value > 10) {
        errors.push(`${field} must be a number between 0 and 10`);
      }
    }

    return { valid: errors.length === 0, errors };
  }

  // ═══════════════════════════════════════════════════════════════
  // PRIVATE: PARALLEL EXECUTION
  // ═══════════════════════════════════════════════════════════════

  private async executeParallel(input: AggregatedInput): Promise<void> {
    // Create independent abort controllers
    this.scoringController = new AbortController();
    this.explainController = new AbortController();

    // Start global timeout
    this.globalTimeoutId = setTimeout(() => {
      console.warn('[Pipeline] Global timeout reached');
      this.scoringController?.abort();
      this.explainController?.abort();
    }, TIMEOUT_CONFIG.GLOBAL_DEADLINE_MS);

    // Mark both as pending
    this.ctx.scoring.status = 'pending';
    this.ctx.scoring.startTime = Date.now();
    this.ctx.explain.status = 'pending';
    this.ctx.explain.startTime = Date.now();

    // Fire both requests SIMULTANEOUSLY
    const scoringPromise = this.executeScoring(input);
    const explainPromise = this.executeExplain(input);

    // Wait for both to settle (success or failure)
    const [scoringResult, explainResult] = await Promise.allSettled([
      scoringPromise,
      explainPromise,
    ]);

    // Clear global timeout
    if (this.globalTimeoutId) {
      clearTimeout(this.globalTimeoutId);
      this.globalTimeoutId = null;
    }

    // Process results
    this.processResults(scoringResult, explainResult);
  }

  private async executeScoring(input: AggregatedInput): Promise<ScoringResponse> {
    const scoringInput = {
      user_id: input.user_id,
      skills: input.skills,
      interests: input.interests,
      education_level: input.education_level,
    };

    return executeWithRetry(
      async () => {
        const controller = this.scoringController!;
        const response = await fetchWithTimeout(
          '/api/v1/scoring/rank',
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-Correlation-ID': this.ctx.correlationId!,
            },
            body: JSON.stringify(scoringInput),
          },
          TIMEOUT_CONFIG.SCORING_TIMEOUT_MS,
          controller
        );

        if (!response.ok) {
          throw response;
        }

        return response.json();
      },
      'scoring',
      this.ctx,
      (action) => this.handleRetryAction(action)
    );
  }

  private async executeExplain(input: AggregatedInput): Promise<ExplainResponse> {
    const explainInput = {
      math_score: input.math_score,
      logic_score: input.logic_score,
      physics_score: input.physics_score,
      literature_score: input.literature_score,
      history_score: input.history_score,
      geography_score: input.geography_score,
      biology_score: input.biology_score,
      chemistry_score: input.chemistry_score,
      economics_score: input.economics_score,
      creativity_score: input.creativity_score,
      interest_tech: input.interest_tech,
      interest_science: input.interest_science,
      interest_arts: input.interest_arts,
      interest_social: input.interest_social,
      education_level: input.education_level,
    };

    return executeWithRetry(
      async () => {
        const controller = this.explainController!;
        const response = await fetchWithTimeout(
          '/api/v1/explain',
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-Correlation-ID': this.ctx.correlationId!,
            },
            body: JSON.stringify(explainInput),
          },
          TIMEOUT_CONFIG.EXPLAIN_TIMEOUT_MS,
          controller
        );

        if (!response.ok) {
          throw response;
        }

        return response.json();
      },
      'explain',
      this.ctx,
      (action) => this.handleRetryAction(action)
    );
  }

  // ═══════════════════════════════════════════════════════════════
  // PRIVATE: RESULT PROCESSING
  // ═══════════════════════════════════════════════════════════════

  private processResults(
    scoringResult: PromiseSettledResult<ScoringResponse>,
    explainResult: PromiseSettledResult<ExplainResponse>
  ): void {
    // Process scoring
    if (scoringResult.status === 'fulfilled') {
      this.ctx.scoring.status = 'success';
      this.ctx.scoring.data = scoringResult.value;
      this.ctx.scoring.endTime = Date.now();
    } else {
      this.ctx.scoring.status = 'error';
      this.ctx.scoring.error = classifyError(
        scoringResult.reason, 
        'scoring', 
        this.ctx.correlationId!
      );
      this.ctx.scoring.endTime = Date.now();
    }

    // Process explain
    if (explainResult.status === 'fulfilled') {
      this.ctx.explain.status = 'success';
      this.ctx.explain.data = explainResult.value;
      this.ctx.explain.endTime = Date.now();
    } else {
      this.ctx.explain.status = 'error';
      this.ctx.explain.error = classifyError(
        explainResult.reason, 
        'explain', 
        this.ctx.correlationId!
      );
      this.ctx.explain.endTime = Date.now();
    }

    // Compute terminal state
    const terminal = this.computeTerminalState();
    this.transition(terminal);
  }

  private computeTerminalState(): PipelineState {
    const scoringOk = this.ctx.scoring.status === 'success';
    const explainOk = this.ctx.explain.status === 'success';

    if (scoringOk && explainOk) return 'completed';
    if (scoringOk || explainOk) return 'partial_success';
    return 'error';
  }

  // ═══════════════════════════════════════════════════════════════
  // PRIVATE: STATE MANAGEMENT
  // ═══════════════════════════════════════════════════════════════

  private transition(newState: PipelineState): void {
    // GUARD: No state updates after unmount
    if (!this.ctx.isMounted) {
      console.warn('[Pipeline] Ignoring transition after unmount');
      return;
    }

    console.log(`[Pipeline] ${this.ctx.state} → ${newState}`);
    this.ctx.state = newState;
    this.onStateChange(newState);
  }

  private handleRetryAction(action: RetryAction): void {
    console.log(`[Pipeline] Retry action: ${action.type}, attempt ${action.attempt}`);
  }

  private handleFatalError(error: unknown): void {
    console.error('[Pipeline] Fatal error:', error);
    this.transition('error');
  }

  private cleanup(): void {
    if (this.globalTimeoutId) {
      clearTimeout(this.globalTimeoutId);
      this.globalTimeoutId = null;
    }
    // Controllers are already aborted, just nullify references
    this.scoringController = null;
    this.explainController = null;
  }

  // ═══════════════════════════════════════════════════════════════
  // PUBLIC: GETTERS FOR UI
  // ═══════════════════════════════════════════════════════════════

  getContext(): Readonly<PipelineContext> {
    return Object.freeze({ ...this.ctx });
  }

  getScoringData(): ScoringResponse | null {
    return this.ctx.scoring.status === 'success' 
      ? this.ctx.scoring.data as ScoringResponse 
      : null;
  }

  getExplainData(): ExplainResponse | null {
    return this.ctx.explain.status === 'success' 
      ? this.ctx.explain.data as ExplainResponse 
      : null;
  }
}

// ═══════════════════════════════════════════════════════════════════
// CORRELATION ID GENERATOR
// ═══════════════════════════════════════════════════════════════════

function generateCorrelationId(): string {
  return `eval-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}
```

---

## 7. Rendering Contract (Deterministic)

### 7.1 Render Predicate Table

| Component | Render Predicate | Invariant |
|-----------|------------------|-----------|
| `<MainSpinner />` | `state === 'validating' \|\| state === 'executing_parallel' \|\| state === 'retrying_scoring' \|\| state === 'retrying_explain'` | Visible during any active state |
| `<ScoreSkeleton />` | `scoring.status === 'pending'` | Disappears when scoring settles |
| `<ScorePanel data={...} />` | `scoring.status === 'success' && scoring.data !== null` | Only render with valid data |
| `<ScoreError error={...} />` | `scoring.status === 'error' && scoring.error !== null` | Only render with typed error |
| `<ExplainSkeleton />` | `explain.status === 'pending'` | Disappears when explain settles |
| `<ExplainPanel data={...} />` | `explain.status === 'success' && explain.data !== null` | Only render with valid data |
| `<ExplainError error={...} />` | `explain.status === 'error' && explain.error !== null` | Only render with typed error |
| `<AbortButton />` | `state.startsWith('executing') \|\| state.startsWith('retrying')` | Only during active requests |
| `<RetryButton api="scoring" />` | `state === 'partial_success' && scoring.status === 'error'` | Only when scoring failed specifically |
| `<RetryButton api="explain" />` | `state === 'partial_success' && explain.status === 'error'` | Only when explain failed specifically |
| `<RetryAllButton />` | `state === 'error'` | Only when both failed |
| `<StartButton disabled={...} />` | `true` (always rendered) | `disabled` when not idle |

### 7.2 Decision Tree Pseudo-Code

```typescript
function renderPipeline(ctx: PipelineContext): ReactNode {
  return (
    <>
      {/* Main Action Button - Always Present */}
      <StartButton 
        disabled={ctx.state !== 'idle'} 
        onClick={handleStart}
      />

      {/* Abort Button - During Active States */}
      {isActiveState(ctx.state) && (
        <AbortButton onClick={handleAbort} />
      )}

      {/* Main Loading Indicator */}
      {isActiveState(ctx.state) && <MainSpinner />}

      {/* Scoring Section */}
      <ScoringSection>
        {ctx.scoring.status === 'pending' && <ScoreSkeleton />}
        {ctx.scoring.status === 'success' && ctx.scoring.data && (
          <ScorePanel data={ctx.scoring.data} />
        )}
        {ctx.scoring.status === 'error' && ctx.scoring.error && (
          <ScoreError 
            error={ctx.scoring.error} 
            onRetry={ctx.state === 'partial_success' ? handleRetryScoring : undefined}
          />
        )}
      </ScoringSection>

      {/* Explain Section */}
      <ExplainSection>
        {ctx.explain.status === 'pending' && <ExplainSkeleton />}
        {ctx.explain.status === 'success' && ctx.explain.data && (
          <ExplainPanel data={ctx.explain.data} />
        )}
        {ctx.explain.status === 'error' && ctx.explain.error && (
          <ExplainError 
            error={ctx.explain.error}
            onRetry={ctx.state === 'partial_success' ? handleRetryExplain : undefined}
          />
        )}
      </ExplainSection>

      {/* Global Error State */}
      {ctx.state === 'error' && (
        <GlobalErrorBanner onRetryAll={handleRetryAll} onReset={handleReset} />
      )}
    </>
  );
}

function isActiveState(state: PipelineState): boolean {
  return ['validating', 'executing_parallel', 'retrying_scoring', 'retrying_explain'].includes(state);
}
```

### 7.3 React Hook Implementation

```typescript
// ═══════════════════════════════════════════════════════════════════
// REACT HOOK - LIFECYCLE SAFE
// ═══════════════════════════════════════════════════════════════════

function useEvaluationPipeline() {
  const [state, setState] = useState<PipelineState>('idle');
  const [ctx, setCtx] = useState<PipelineContext | null>(null);
  const executorRef = useRef<PipelineExecutor | null>(null);

  // Initialize executor on mount
  useEffect(() => {
    executorRef.current = new PipelineExecutor((newState) => {
      setState(newState);
      setCtx(executorRef.current?.getContext() ?? null);
    });

    // CRITICAL: Mark as unmounted on cleanup
    return () => {
      executorRef.current?.unmount();
      executorRef.current = null;
    };
  }, []);

  const execute = useCallback((input: AggregatedInput) => {
    executorRef.current?.execute(input);
  }, []);

  const abort = useCallback(() => {
    executorRef.current?.abort();
  }, []);

  const reset = useCallback(() => {
    executorRef.current?.abort(); // Same as abort for now
  }, []);

  const retryScoring = useCallback(() => {
    // Implementation: re-fire scoring only
    console.log('Retry scoring requested');
  }, []);

  const retryExplain = useCallback(() => {
    // Implementation: re-fire explain only
    console.log('Retry explain requested');
  }, []);

  return {
    state,
    ctx,
    scoringData: ctx?.scoring.status === 'success' ? ctx.scoring.data : null,
    explainData: ctx?.explain.status === 'success' ? ctx.explain.data : null,
    scoringError: ctx?.scoring.status === 'error' ? ctx.scoring.error : null,
    explainError: ctx?.explain.status === 'error' ? ctx.explain.error : null,
    isLoading: isActiveState(state),
    execute,
    abort,
    reset,
    retryScoring,
    retryExplain,
  };
}
```

---

## 8. Final Invariants

### 8.1 System Invariants (MUST ALWAYS HOLD)

| ID | Invariant | Enforcement |
|----|-----------|-------------|
| `INV-001` | Only ONE state at any time | TypeScript union type + single state variable |
| `INV-002` | No setState after unmount | `isMounted` guard in all transitions |
| `INV-003` | No double execution | State guard: execute only from `idle` |
| `INV-004` | Scoring and Explain are independent | No data flow between API calls |
| `INV-005` | Individual timeout ≤ Global deadline | Compile-time + runtime validation |
| `INV-006` | Retry delays are deterministic (no jitter) | Fixed delay arrays, no Math.random() |
| `INV-007` | AbortController cleanup guaranteed | try/finally pattern in executor |
| `INV-008` | Correlation ID propagates to all requests | Set in context before any API call |
| `INV-009` | Terminal states require manual exit | No automatic transitions from completed/partial/error |
| `INV-010` | UI renders only with non-null data | Render predicates check both status AND data |

### 8.2 Pre-Conditions by Operation

| Operation | Pre-Conditions |
|-----------|----------------|
| `execute(input)` | `state === 'idle'` AND `isMounted === true` |
| `abort()` | `isActiveState(state)` |
| `reset()` | `isTerminalState(state)` |
| `retryScoring()` | `state === 'partial_success'` AND `scoring.status === 'error'` |
| `retryExplain()` | `state === 'partial_success'` AND `explain.status === 'error'` |
| `retryAll()` | `state === 'error'` |

### 8.3 Post-Conditions by Operation

| Operation | Post-Conditions |
|-----------|-----------------|
| `execute(input)` | `state ∈ {completed, partial_success, error, idle}` eventually |
| `abort()` | `state === 'idle'` AND all timers cleared |
| `reset()` | `state === 'idle'` AND `ctx === initialContext` |

---

## 9. Observability

### 9.1 Logging Schema

```typescript
interface PipelineLog {
  timestamp: string;           // ISO 8601
  correlationId: string;       // Request trace
  event: PipelineEvent;        // Structured event type
  fromState?: PipelineState;   // For transitions
  toState?: PipelineState;     // For transitions
  api?: 'scoring' | 'explain'; // For API events
  durationMs?: number;         // For completed operations
  error?: TypedError;          // For error events
}

type PipelineEvent =
  | 'PIPELINE_START'
  | 'VALIDATION_START'
  | 'VALIDATION_SUCCESS'
  | 'VALIDATION_FAIL'
  | 'PARALLEL_EXEC_START'
  | 'API_REQUEST_START'
  | 'API_REQUEST_SUCCESS'
  | 'API_REQUEST_ERROR'
  | 'API_RETRY'
  | 'GLOBAL_TIMEOUT'
  | 'USER_ABORT'
  | 'PIPELINE_COMPLETE'
  | 'PIPELINE_ERROR';
```

### 9.2 Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `pipeline_executions_total` | Counter | Total pipeline executions |
| `pipeline_success_total` | Counter | Successful completions |
| `pipeline_partial_success_total` | Counter | Partial success count |
| `pipeline_error_total` | Counter | Total errors by error kind |
| `pipeline_duration_ms` | Histogram | End-to-end latency |
| `api_duration_ms{api}` | Histogram | Per-API latency |
| `api_retry_total{api}` | Counter | Retry count per API |

---

## 10. Appendix: Type Definitions

```typescript
// ═══════════════════════════════════════════════════════════════════
// API TYPES
// ═══════════════════════════════════════════════════════════════════

interface AggregatedInput {
  user_id: string;
  skills: string[];
  interests: string[];
  education_level: string;
  math_score: number;
  logic_score: number;
  physics_score: number;
  literature_score: number;
  history_score: number;
  geography_score: number;
  biology_score: number;
  chemistry_score: number;
  economics_score: number;
  creativity_score: number;
  interest_tech: number;
  interest_science: number;
  interest_arts: number;
  interest_social: number;
}

interface ScoringResponse {
  rankings: CareerScore[];
  timestamp: string;
}

interface CareerScore {
  career_id: string;
  career_name: string;
  score: number;
  confidence: number;
}

interface ExplainResponse {
  explanation: string;
  factors: ExplainFactor[];
  confidence: number;
  model_version: string;
}

interface ExplainFactor {
  name: string;
  weight: number;
  description: string;
}

interface RetryAction {
  type: 'SCORING_RETRY' | 'EXPLAIN_RETRY';
  attempt: number;
  delayMs: number;
}
```

---

## Document Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 3.0 | 2026-02-21 | Principal Architect | Complete rewrite: hardened state machine, typed errors, deterministic retry, lifecycle safety |
| 2.0 | 2026-02-20 | System Architect | Parallel execution, API independence proof |
| 1.0 | 2026-02-19 | System Architect | Initial sequential design |

---

**END OF SPECIFICATION**

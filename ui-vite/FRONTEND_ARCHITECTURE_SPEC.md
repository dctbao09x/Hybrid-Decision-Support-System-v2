# Frontend Architecture Specification: 1-Button Evaluation Flow

> **Document Type:** Frontend Implementation Specification  
> **Author:** Principal Frontend Architect  
> **Version:** 1.0  
> **Date:** 2026-02-21  
> **Status:** FINAL - Ready for Implementation  
> **Depends On:** ONE_BUTTON_PIPELINE_SPEC_v3.md

---

## PHẦN 1 — COMPONENT ARCHITECTURE

### 1.1 Component Hierarchy

```
src/
├── features/
│   └── evaluation/
│       ├── index.ts                          # Public exports
│       ├── EvaluationOrchestrator.tsx        # Container component
│       ├── hooks/
│       │   └── useEvaluationFlow.ts          # State machine hook
│       ├── services/
│       │   └── evaluationService.ts          # API layer
│       ├── components/
│       │   ├── ScorePanel.tsx                # Presentation: scoring results
│       │   ├── ExplainPanel.tsx              # Presentation: explanation
│       │   ├── LoadingStageIndicator.tsx     # Presentation: progress
│       │   ├── ErrorBanner.tsx               # Presentation: errors
│       │   └── EvaluationButton.tsx          # Presentation: trigger button
│       ├── types/
│       │   └── evaluation.types.ts           # All TypeScript types
│       └── constants/
│           └── evaluation.constants.ts       # Config values
```

### 1.2 Component Responsibilities

| Component | Type | Responsibility | State Access |
|-----------|------|----------------|--------------|
| `EvaluationOrchestrator` | Container | Wire hook to presenters, handle layout | Full context |
| `useEvaluationFlow` | Hook | State machine, lifecycle, API orchestration | Owner |
| `evaluationService` | Service | HTTP calls, timeout, retry, abort | None (stateless) |
| `ScorePanel` | Presenter | Render scoring results | Props only |
| `ExplainPanel` | Presenter | Render explanation | Props only |
| `LoadingStageIndicator` | Presenter | Show progress stages | Props only |
| `ErrorBanner` | Presenter | Display errors with retry | Props + callbacks |
| `EvaluationButton` | Presenter | Trigger button with disabled state | Props + callbacks |

### 1.3 Container vs Presentation Rules

```
CONTAINER (EvaluationOrchestrator):
  ✓ Calls useEvaluationFlow()
  ✓ Passes data to presenters via props
  ✓ Handles layout/grid structure
  ✓ Conditionally renders presenters based on state
  ✗ MUST NOT contain API calls
  ✗ MUST NOT contain business logic
  ✗ MUST NOT contain complex conditionals in JSX

PRESENTER (ScorePanel, ExplainPanel, etc.):
  ✓ Receives typed props
  ✓ Pure render function
  ✓ Handles own visual state (hover, focus)
  ✗ MUST NOT call hooks except styling hooks
  ✗ MUST NOT dispatch actions
  ✗ MUST NOT access external state
```

---

## PHẦN 2 — DATA CONTRACT

### 2.1 Input Types

```typescript
// ═══════════════════════════════════════════════════════════════════
// FORM INPUT (from UI forms)
// ═══════════════════════════════════════════════════════════════════

/**
 * Raw form data collected from user input components.
 * All fields are required for evaluation to proceed.
 */
interface EvaluationFormInput {
  // Identity
  user_id: string;                    // REQUIRED - Authenticated user ID

  // Scoring API inputs
  skills: string[];                   // REQUIRED - Min 1 item
  interests: string[];                // REQUIRED - Min 1 item
  education_level: string;            // REQUIRED - Enum: 'high_school' | 'bachelor' | 'master' | 'phd'

  // Explain API inputs (scores 0-10)
  math_score: number;                 // REQUIRED - Range [0, 10]
  logic_score: number;                // REQUIRED - Range [0, 10]
  physics_score: number;              // REQUIRED - Range [0, 10]
  literature_score: number;           // REQUIRED - Range [0, 10]
  history_score: number;              // REQUIRED - Range [0, 10]
  geography_score: number;            // REQUIRED - Range [0, 10]
  biology_score: number;              // REQUIRED - Range [0, 10]
  chemistry_score: number;            // REQUIRED - Range [0, 10]
  economics_score: number;            // REQUIRED - Range [0, 10]
  creativity_score: number;           // REQUIRED - Range [0, 10]

  // Interest weights (0-1)
  interest_tech: number;              // REQUIRED - Range [0, 1]
  interest_science: number;           // REQUIRED - Range [0, 1]
  interest_arts: number;              // REQUIRED - Range [0, 1]
  interest_social: number;            // REQUIRED - Range [0, 1]
}
```

### 2.2 API Payloads

```typescript
// ═══════════════════════════════════════════════════════════════════
// SCORING API CONTRACT
// ═══════════════════════════════════════════════════════════════════

/**
 * POST /api/v1/scoring/rank
 * Uses SIMGR formula - static computation
 */
interface ScoringPayload {
  user_id: string;
  skills: string[];
  interests: string[];
  education_level: string;
}

interface ScoringResponse {
  rankings: CareerScore[];
  timestamp: string;                  // ISO 8601
  request_id: string;                 // Backend correlation
}

interface CareerScore {
  career_id: string;
  career_name: string;
  score: number;                      // Range [0, 1]
  confidence: number;                 // Range [0, 1]
  rank: number;                       // 1-based rank
}

// ═══════════════════════════════════════════════════════════════════
// EXPLAIN API CONTRACT
// ═══════════════════════════════════════════════════════════════════

/**
 * POST /api/v1/explain
 * Runs own inference via main_control.run_inference()
 * DOES NOT depend on ScoringResponse
 */
interface ExplainPayload {
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
  education_level: number;            // NOTE: int, not string
}

interface ExplainResponse {
  explanation: string;                // Natural language explanation
  factors: ExplainFactor[];
  confidence: number;                 // Range [0, 1]
  model_version: string;
  request_id: string;
}

interface ExplainFactor {
  name: string;
  weight: number;                     // Importance weight
  contribution: number;               // Contribution to result
  description: string;
}
```

### 2.3 Field Dependencies

```
┌─────────────────────────────────────────────────────────────────────┐
│                     FIELD DEPENDENCY MATRIX                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  EvaluationFormInput                                                │
│        │                                                            │
│        ├──────────────────┐                                         │
│        │                  │                                         │
│        ▼                  ▼                                         │
│  ScoringPayload      ExplainPayload                                 │
│  ├─ user_id          ├─ math_score                                  │
│  ├─ skills           ├─ logic_score                                 │
│  ├─ interests        ├─ ... (all scores)                            │
│  └─ education_level  ├─ interest_*                                  │
│        (string)      └─ education_level (int) ← TRANSFORM REQUIRED  │
│                                                                     │
│  CRITICAL: ScoringPayload and ExplainPayload share NO fields        │
│  except education_level which requires string→int transformation    │
│                                                                     │
│  ExplainPayload DOES NOT use any field from ScoringResponse         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.4 Education Level Transformation

```typescript
// ═══════════════════════════════════════════════════════════════════
// TRANSFORMATION FUNCTIONS
// ═══════════════════════════════════════════════════════════════════

const EDUCATION_LEVEL_MAP: Record<string, number> = {
  'high_school': 0,
  'bachelor': 1,
  'master': 2,
  'phd': 3,
} as const;

function transformToScoringPayload(input: EvaluationFormInput): ScoringPayload {
  return {
    user_id: input.user_id,
    skills: input.skills,
    interests: input.interests,
    education_level: input.education_level,
  };
}

function transformToExplainPayload(input: EvaluationFormInput): ExplainPayload {
  return {
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
    education_level: EDUCATION_LEVEL_MAP[input.education_level] ?? 0,
  };
}
```

---

## PHẦN 3 — CODE SKELETON

### 3.1 Type Definitions (evaluation.types.ts)

```typescript
// ═══════════════════════════════════════════════════════════════════
// FILE: src/features/evaluation/types/evaluation.types.ts
// ═══════════════════════════════════════════════════════════════════

// --- State Machine Types ---

export type PipelineState =
  | 'idle'
  | 'validating'
  | 'executing_parallel'
  | 'retrying_scoring'
  | 'retrying_explain'
  | 'completed'
  | 'partial_success'
  | 'error';

export type ApiStatus = 'idle' | 'pending' | 'success' | 'error';

// --- Error Types ---

export type ErrorKind =
  | 'TRANSPORT_ERROR'
  | 'TIMEOUT_ERROR'
  | 'RATE_LIMIT_ERROR'
  | 'VALIDATION_ERROR'
  | 'AUTH_ERROR'
  | 'BACKEND_ERROR'
  | 'ABORT_ERROR'
  | 'UNKNOWN_ERROR';

export interface TypedError {
  kind: ErrorKind;
  message: string;
  httpStatus: number | null;
  retryable: boolean;
  source: 'scoring' | 'explain';
  timestamp: number;
  correlationId: string;
}

// --- API Tracker ---

export interface ApiTracker<T = unknown> {
  status: ApiStatus;
  retriesRemaining: number;
  startTime: number | null;
  endTime: number | null;
  error: TypedError | null;
  data: T | null;
}

// --- Pipeline Context ---

export interface PipelineContext {
  state: PipelineState;
  scoring: ApiTracker<ScoringResponse>;
  explain: ApiTracker<ExplainResponse>;
  correlationId: string | null;
  globalStartTime: number | null;
  isMounted: boolean;
}

// --- Actions ---

export type PipelineAction =
  | { type: 'START'; payload: EvaluationFormInput }
  | { type: 'VALIDATION_SUCCESS' }
  | { type: 'VALIDATION_FAILURE'; errors: string[] }
  | { type: 'SCORING_SUCCESS'; data: ScoringResponse }
  | { type: 'SCORING_ERROR'; error: TypedError }
  | { type: 'SCORING_RETRY'; attempt: number }
  | { type: 'EXPLAIN_SUCCESS'; data: ExplainResponse }
  | { type: 'EXPLAIN_ERROR'; error: TypedError }
  | { type: 'EXPLAIN_RETRY'; attempt: number }
  | { type: 'GLOBAL_TIMEOUT' }
  | { type: 'ABORT' }
  | { type: 'RETRY_FAILED_ONLY' }
  | { type: 'RETRY_ALL' }
  | { type: 'RESET' };

// --- Hook Return Type ---

export interface UseEvaluationFlowReturn {
  // State
  state: PipelineState;
  scoringData: ScoringResponse | null;
  explainData: ExplainResponse | null;
  scoringError: TypedError | null;
  explainError: TypedError | null;
  
  // Computed
  isLoading: boolean;
  isIdle: boolean;
  isCompleted: boolean;
  hasPartialSuccess: boolean;
  hasError: boolean;
  
  // Progress
  scoringProgress: 'idle' | 'loading' | 'success' | 'error';
  explainProgress: 'idle' | 'loading' | 'success' | 'error';
  
  // Actions
  execute: (input: EvaluationFormInput) => void;
  abort: () => void;
  retryFailed: () => void;
  retryAll: () => void;
  reset: () => void;
}
```

### 3.2 Constants (evaluation.constants.ts)

```typescript
// ═══════════════════════════════════════════════════════════════════
// FILE: src/features/evaluation/constants/evaluation.constants.ts
// ═══════════════════════════════════════════════════════════════════

export const TIMEOUT_CONFIG = Object.freeze({
  GLOBAL_DEADLINE_MS: 12000,
  SCORING_TIMEOUT_MS: 5000,
  EXPLAIN_TIMEOUT_MS: 10000,
  VALIDATION_TIMEOUT_MS: 100,
  DEBOUNCE_MS: 300,
} as const);

export const RETRY_CONFIG = Object.freeze({
  scoring: {
    maxAttempts: 2,
    backoffMs: [1000, 2000] as const,
  },
  explain: {
    maxAttempts: 2,
    backoffMs: [2000, 4000] as const,
  },
} as const);

export const API_ENDPOINTS = Object.freeze({
  SCORING: '/api/v1/scoring/rank',
  EXPLAIN: '/api/v1/explain',
} as const);

export const EDUCATION_LEVEL_MAP: Readonly<Record<string, number>> = Object.freeze({
  'high_school': 0,
  'bachelor': 1,
  'master': 2,
  'phd': 3,
});
```

### 3.3 Evaluation Service (evaluationService.ts)

```typescript
// ═══════════════════════════════════════════════════════════════════
// FILE: src/features/evaluation/services/evaluationService.ts
// ═══════════════════════════════════════════════════════════════════

import { 
  ScoringPayload, 
  ScoringResponse, 
  ExplainPayload, 
  ExplainResponse,
  TypedError,
  ErrorKind,
} from '../types/evaluation.types';
import { TIMEOUT_CONFIG, RETRY_CONFIG, API_ENDPOINTS } from '../constants/evaluation.constants';

// --- Error Classification ---

function classifyError(
  error: unknown,
  source: 'scoring' | 'explain',
  correlationId: string
): TypedError {
  const timestamp = Date.now();
  const base = { source, timestamp, correlationId };

  if (error instanceof DOMException && error.name === 'AbortError') {
    return { ...base, kind: 'ABORT_ERROR', message: 'Request aborted', httpStatus: null, retryable: false };
  }

  if (error instanceof TypeError && error.message.includes('fetch')) {
    return { ...base, kind: 'TRANSPORT_ERROR', message: 'Network error', httpStatus: null, retryable: true };
  }

  if ((error as any)?.isTimeout) {
    return { ...base, kind: 'TIMEOUT_ERROR', message: 'Request timeout', httpStatus: null, retryable: true };
  }

  if ((error as any)?.status) {
    const status = (error as any).status;
    if (status === 429) return { ...base, kind: 'RATE_LIMIT_ERROR', message: 'Rate limited', httpStatus: 429, retryable: true };
    if (status === 401 || status === 403) return { ...base, kind: 'AUTH_ERROR', message: 'Auth failed', httpStatus: status, retryable: false };
    if (status === 400 || status === 422) return { ...base, kind: 'VALIDATION_ERROR', message: 'Invalid request', httpStatus: status, retryable: false };
    if (status >= 500) return { ...base, kind: 'BACKEND_ERROR', message: 'Server error', httpStatus: status, retryable: true };
  }

  return { ...base, kind: 'UNKNOWN_ERROR', message: String(error), httpStatus: null, retryable: false };
}

// --- Timeout-aware Fetch ---

async function fetchWithTimeout(
  url: string,
  options: RequestInit,
  timeoutMs: number,
  controller: AbortController
): Promise<Response> {
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error instanceof DOMException && error.name === 'AbortError') {
      const timeoutError = new Error('Timeout');
      (timeoutError as any).isTimeout = true;
      throw timeoutError;
    }
    throw error;
  }
}

// --- Retry Logic ---

async function executeWithRetry<T>(
  operation: () => Promise<T>,
  api: 'scoring' | 'explain',
  isMountedRef: { current: boolean },
  onRetry?: (attempt: number) => void
): Promise<T> {
  const config = RETRY_CONFIG[api];
  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= config.maxAttempts; attempt++) {
    if (!isMountedRef.current) {
      throw new DOMException('Aborted', 'AbortError');
    }

    try {
      return await operation();
    } catch (error) {
      lastError = error as Error;
      
      // Non-retryable: throw immediately
      if ((error as any)?.kind && !(error as TypedError).retryable) {
        throw error;
      }

      // Max attempts reached
      if (attempt >= config.maxAttempts) {
        throw error;
      }

      // Schedule retry
      const delay = config.backoffMs[Math.min(attempt, config.backoffMs.length - 1)];
      onRetry?.(attempt + 1);
      await sleep(delay);
    }
  }

  throw lastError!;
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// --- Public API ---

export interface EvaluationServiceConfig {
  correlationId: string;
  isMountedRef: { current: boolean };
  onScoringRetry?: (attempt: number) => void;
  onExplainRetry?: (attempt: number) => void;
}

export async function score(
  payload: ScoringPayload,
  controller: AbortController,
  config: EvaluationServiceConfig
): Promise<ScoringResponse> {
  const { correlationId, isMountedRef, onScoringRetry } = config;

  return executeWithRetry(
    async () => {
      const response = await fetchWithTimeout(
        API_ENDPOINTS.SCORING,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Correlation-ID': correlationId,
          },
          body: JSON.stringify(payload),
        },
        TIMEOUT_CONFIG.SCORING_TIMEOUT_MS,
        controller
      );

      if (!response.ok) {
        const error = { status: response.status };
        throw classifyError(error, 'scoring', correlationId);
      }

      return response.json();
    },
    'scoring',
    isMountedRef,
    onScoringRetry
  );
}

export async function explain(
  payload: ExplainPayload,
  controller: AbortController,
  config: EvaluationServiceConfig
): Promise<ExplainResponse> {
  const { correlationId, isMountedRef, onExplainRetry } = config;

  return executeWithRetry(
    async () => {
      const response = await fetchWithTimeout(
        API_ENDPOINTS.EXPLAIN,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Correlation-ID': correlationId,
          },
          body: JSON.stringify(payload),
        },
        TIMEOUT_CONFIG.EXPLAIN_TIMEOUT_MS,
        controller
      );

      if (!response.ok) {
        const error = { status: response.status };
        throw classifyError(error, 'explain', correlationId);
      }

      return response.json();
    },
    'explain',
    isMountedRef,
    onExplainRetry
  );
}

export { classifyError };
```

### 3.4 State Machine Hook (useEvaluationFlow.ts)

```typescript
// ═══════════════════════════════════════════════════════════════════
// FILE: src/features/evaluation/hooks/useEvaluationFlow.ts
// ═══════════════════════════════════════════════════════════════════

import { useReducer, useCallback, useRef, useEffect } from 'react';
import {
  PipelineState,
  PipelineContext,
  PipelineAction,
  ApiTracker,
  TypedError,
  ScoringResponse,
  ExplainResponse,
  EvaluationFormInput,
  UseEvaluationFlowReturn,
} from '../types/evaluation.types';
import { TIMEOUT_CONFIG, EDUCATION_LEVEL_MAP } from '../constants/evaluation.constants';
import * as evaluationService from '../services/evaluationService';

// --- Initial State Factory ---

function createInitialApiTracker<T>(): ApiTracker<T> {
  return {
    status: 'idle',
    retriesRemaining: 2,
    startTime: null,
    endTime: null,
    error: null,
    data: null,
  };
}

function createInitialContext(): PipelineContext {
  return {
    state: 'idle',
    scoring: createInitialApiTracker<ScoringResponse>(),
    explain: createInitialApiTracker<ExplainResponse>(),
    correlationId: null,
    globalStartTime: null,
    isMounted: true,
  };
}

// --- Reducer ---

function reducer(ctx: PipelineContext, action: PipelineAction): PipelineContext {
  // GUARD: No updates after unmount
  if (!ctx.isMounted && action.type !== 'RESET') {
    return ctx;
  }

  switch (action.type) {
    case 'START':
      return {
        ...createInitialContext(),
        state: 'validating',
        correlationId: generateCorrelationId(),
        globalStartTime: Date.now(),
        isMounted: true,
      };

    case 'VALIDATION_SUCCESS':
      return {
        ...ctx,
        state: 'executing_parallel',
        scoring: { ...ctx.scoring, status: 'pending', startTime: Date.now() },
        explain: { ...ctx.explain, status: 'pending', startTime: Date.now() },
      };

    case 'VALIDATION_FAILURE':
      return {
        ...ctx,
        state: 'idle',
      };

    case 'SCORING_SUCCESS':
      return updateApiSuccess(ctx, 'scoring', action.data);

    case 'SCORING_ERROR':
      return updateApiError(ctx, 'scoring', action.error);

    case 'EXPLAIN_SUCCESS':
      return updateApiSuccess(ctx, 'explain', action.data);

    case 'EXPLAIN_ERROR':
      return updateApiError(ctx, 'explain', action.error);

    case 'GLOBAL_TIMEOUT':
      return computeTerminalState(ctx);

    case 'ABORT':
    case 'RESET':
      return createInitialContext();

    default:
      return ctx;
  }
}

function updateApiSuccess(
  ctx: PipelineContext,
  api: 'scoring' | 'explain',
  data: ScoringResponse | ExplainResponse
): PipelineContext {
  const updated = {
    ...ctx,
    [api]: {
      ...ctx[api],
      status: 'success' as const,
      data,
      endTime: Date.now(),
      error: null,
    },
  };
  return maybeTransitionToTerminal(updated);
}

function updateApiError(
  ctx: PipelineContext,
  api: 'scoring' | 'explain',
  error: TypedError
): PipelineContext {
  const tracker = ctx[api];
  const updated = {
    ...ctx,
    [api]: {
      ...tracker,
      status: 'error' as const,
      error,
      endTime: Date.now(),
      retriesRemaining: tracker.retriesRemaining - 1,
    },
  };
  return maybeTransitionToTerminal(updated);
}

function maybeTransitionToTerminal(ctx: PipelineContext): PipelineContext {
  const scoringDone = ctx.scoring.status === 'success' || ctx.scoring.status === 'error';
  const explainDone = ctx.explain.status === 'success' || ctx.explain.status === 'error';

  if (!scoringDone || !explainDone) {
    return { ...ctx, state: 'executing_parallel' };
  }

  return computeTerminalState(ctx);
}

function computeTerminalState(ctx: PipelineContext): PipelineContext {
  const scoringOk = ctx.scoring.status === 'success';
  const explainOk = ctx.explain.status === 'success';

  let state: PipelineState;
  if (scoringOk && explainOk) state = 'completed';
  else if (scoringOk || explainOk) state = 'partial_success';
  else state = 'error';

  return { ...ctx, state };
}

function generateCorrelationId(): string {
  return `eval-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}

// --- Hook ---

export function useEvaluationFlow(): UseEvaluationFlowReturn {
  const [ctx, dispatch] = useReducer(reducer, undefined, createInitialContext);
  
  const isMountedRef = useRef(true);
  const scoringControllerRef = useRef<AbortController | null>(null);
  const explainControllerRef = useRef<AbortController | null>(null);
  const globalTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<EvaluationFormInput | null>(null);

  // --- Lifecycle ---

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      cleanup();
    };
  }, []);

  // --- Cleanup ---

  const cleanup = useCallback(() => {
    scoringControllerRef.current?.abort();
    explainControllerRef.current?.abort();
    if (globalTimeoutRef.current) {
      clearTimeout(globalTimeoutRef.current);
      globalTimeoutRef.current = null;
    }
    scoringControllerRef.current = null;
    explainControllerRef.current = null;
  }, []);

  // --- Validation ---

  const validate = useCallback((input: EvaluationFormInput): string[] => {
    const errors: string[] = [];
    
    if (!input.user_id) errors.push('user_id is required');
    if (!input.skills?.length) errors.push('skills is required');
    if (!input.interests?.length) errors.push('interests is required');

    const scoreFields = [
      'math_score', 'logic_score', 'physics_score', 'literature_score',
      'history_score', 'geography_score', 'biology_score', 'chemistry_score',
      'economics_score', 'creativity_score'
    ] as const;

    for (const field of scoreFields) {
      const value = input[field];
      if (typeof value !== 'number' || value < 0 || value > 10) {
        errors.push(`${field} must be 0-10`);
      }
    }

    return errors;
  }, []);

  // --- Execute ---

  const execute = useCallback(async (input: EvaluationFormInput) => {
    // GUARD: Only execute from idle
    if (ctx.state !== 'idle') {
      console.warn('[useEvaluationFlow] Ignoring execute - not idle');
      return;
    }

    inputRef.current = input;
    dispatch({ type: 'START', payload: input });

    // Validation
    const errors = validate(input);
    if (errors.length > 0) {
      dispatch({ type: 'VALIDATION_FAILURE', errors });
      return;
    }
    dispatch({ type: 'VALIDATION_SUCCESS' });

    // Setup
    scoringControllerRef.current = new AbortController();
    explainControllerRef.current = new AbortController();
    const correlationId = ctx.correlationId || generateCorrelationId();

    // Global timeout
    globalTimeoutRef.current = setTimeout(() => {
      if (isMountedRef.current) {
        dispatch({ type: 'GLOBAL_TIMEOUT' });
        cleanup();
      }
    }, TIMEOUT_CONFIG.GLOBAL_DEADLINE_MS);

    // Transform payloads
    const scoringPayload = {
      user_id: input.user_id,
      skills: input.skills,
      interests: input.interests,
      education_level: input.education_level,
    };

    const explainPayload = {
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
      education_level: EDUCATION_LEVEL_MAP[input.education_level] ?? 0,
    };

    const serviceConfig: evaluationService.EvaluationServiceConfig = {
      correlationId,
      isMountedRef,
      onScoringRetry: (attempt) => dispatch({ type: 'SCORING_RETRY', attempt }),
      onExplainRetry: (attempt) => dispatch({ type: 'EXPLAIN_RETRY', attempt }),
    };

    // Fire parallel requests
    const scoringPromise = evaluationService.score(
      scoringPayload,
      scoringControllerRef.current,
      serviceConfig
    ).then(
      (data) => {
        if (isMountedRef.current) dispatch({ type: 'SCORING_SUCCESS', data });
      },
      (error) => {
        if (isMountedRef.current) {
          const typedError = error.kind ? error : evaluationService.classifyError(error, 'scoring', correlationId);
          dispatch({ type: 'SCORING_ERROR', error: typedError });
        }
      }
    );

    const explainPromise = evaluationService.explain(
      explainPayload,
      explainControllerRef.current,
      serviceConfig
    ).then(
      (data) => {
        if (isMountedRef.current) dispatch({ type: 'EXPLAIN_SUCCESS', data });
      },
      (error) => {
        if (isMountedRef.current) {
          const typedError = error.kind ? error : evaluationService.classifyError(error, 'explain', correlationId);
          dispatch({ type: 'EXPLAIN_ERROR', error: typedError });
        }
      }
    );

    // Wait for both to settle
    await Promise.allSettled([scoringPromise, explainPromise]);

    // Cleanup global timeout if still running
    if (globalTimeoutRef.current) {
      clearTimeout(globalTimeoutRef.current);
      globalTimeoutRef.current = null;
    }
  }, [ctx.state, ctx.correlationId, validate, cleanup]);

  // --- Abort ---

  const abort = useCallback(() => {
    cleanup();
    dispatch({ type: 'ABORT' });
  }, [cleanup]);

  // --- Retry Failed Only ---

  const retryFailed = useCallback(() => {
    if (ctx.state !== 'partial_success' || !inputRef.current) return;

    const input = inputRef.current;
    const correlationId = generateCorrelationId();

    if (ctx.scoring.status === 'error') {
      scoringControllerRef.current = new AbortController();
      const payload = {
        user_id: input.user_id,
        skills: input.skills,
        interests: input.interests,
        education_level: input.education_level,
      };
      evaluationService.score(payload, scoringControllerRef.current, {
        correlationId,
        isMountedRef,
      }).then(
        (data) => { if (isMountedRef.current) dispatch({ type: 'SCORING_SUCCESS', data }); },
        (error) => { if (isMountedRef.current) dispatch({ type: 'SCORING_ERROR', error }); }
      );
    }

    if (ctx.explain.status === 'error') {
      explainControllerRef.current = new AbortController();
      const payload = {
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
        education_level: EDUCATION_LEVEL_MAP[input.education_level] ?? 0,
      };
      evaluationService.explain(payload, explainControllerRef.current, {
        correlationId,
        isMountedRef,
      }).then(
        (data) => { if (isMountedRef.current) dispatch({ type: 'EXPLAIN_SUCCESS', data }); },
        (error) => { if (isMountedRef.current) dispatch({ type: 'EXPLAIN_ERROR', error }); }
      );
    }
  }, [ctx.state, ctx.scoring.status, ctx.explain.status]);

  // --- Retry All ---

  const retryAll = useCallback(() => {
    if (ctx.state !== 'error' || !inputRef.current) return;
    cleanup();
    execute(inputRef.current);
  }, [ctx.state, cleanup, execute]);

  // --- Reset ---

  const reset = useCallback(() => {
    cleanup();
    dispatch({ type: 'RESET' });
  }, [cleanup]);

  // --- Computed Values ---

  const isActiveState = (s: PipelineState) =>
    ['validating', 'executing_parallel', 'retrying_scoring', 'retrying_explain'].includes(s);

  const mapStatus = (s: string) => {
    if (s === 'pending') return 'loading';
    return s as 'idle' | 'success' | 'error';
  };

  return {
    state: ctx.state,
    scoringData: ctx.scoring.data,
    explainData: ctx.explain.data,
    scoringError: ctx.scoring.error,
    explainError: ctx.explain.error,
    
    isLoading: isActiveState(ctx.state),
    isIdle: ctx.state === 'idle',
    isCompleted: ctx.state === 'completed',
    hasPartialSuccess: ctx.state === 'partial_success',
    hasError: ctx.state === 'error',
    
    scoringProgress: mapStatus(ctx.scoring.status),
    explainProgress: mapStatus(ctx.explain.status),
    
    execute,
    abort,
    retryFailed,
    retryAll,
    reset,
  };
}
```

### 3.5 Components

#### EvaluationOrchestrator.tsx (Container)

```typescript
// ═══════════════════════════════════════════════════════════════════
// FILE: src/features/evaluation/EvaluationOrchestrator.tsx
// ═══════════════════════════════════════════════════════════════════

import React from 'react';
import { Box, Grid } from '@mui/material';
import { useEvaluationFlow } from './hooks/useEvaluationFlow';
import { EvaluationButton } from './components/EvaluationButton';
import { LoadingStageIndicator } from './components/LoadingStageIndicator';
import { ScorePanel } from './components/ScorePanel';
import { ExplainPanel } from './components/ExplainPanel';
import { ErrorBanner } from './components/ErrorBanner';
import type { EvaluationFormInput } from './types/evaluation.types';

interface EvaluationOrchestratorProps {
  formData: EvaluationFormInput;
}

export const EvaluationOrchestrator: React.FC<EvaluationOrchestratorProps> = ({ formData }) => {
  const {
    state,
    scoringData,
    explainData,
    scoringError,
    explainError,
    isLoading,
    isIdle,
    isCompleted,
    hasPartialSuccess,
    hasError,
    scoringProgress,
    explainProgress,
    execute,
    abort,
    retryFailed,
    retryAll,
    reset,
  } = useEvaluationFlow();

  const handleStart = () => execute(formData);

  return (
    <Box sx={{ width: '100%', mt: 3 }}>
      {/* Action Button */}
      <EvaluationButton
        isIdle={isIdle}
        isLoading={isLoading}
        isCompleted={isCompleted || hasPartialSuccess}
        onStart={handleStart}
        onAbort={abort}
        onReset={reset}
      />

      {/* Loading Indicator */}
      {isLoading && (
        <LoadingStageIndicator
          scoringProgress={scoringProgress}
          explainProgress={explainProgress}
        />
      )}

      {/* Results Grid */}
      <Grid container spacing={3} sx={{ mt: 2 }}>
        {/* Score Panel */}
        <Grid item xs={12} md={6}>
          {scoringProgress === 'loading' && <ScorePanel.Skeleton />}
          {scoringData && <ScorePanel data={scoringData} />}
          {scoringError && (
            <ErrorBanner
              error={scoringError}
              onRetry={hasPartialSuccess ? retryFailed : undefined}
            />
          )}
        </Grid>

        {/* Explain Panel */}
        <Grid item xs={12} md={6}>
          {explainProgress === 'loading' && <ExplainPanel.Skeleton />}
          {explainData && <ExplainPanel data={explainData} />}
          {explainError && (
            <ErrorBanner
              error={explainError}
              onRetry={hasPartialSuccess ? retryFailed : undefined}
            />
          )}
        </Grid>
      </Grid>

      {/* Global Error */}
      {hasError && (
        <Box sx={{ mt: 3 }}>
          <ErrorBanner
            error={{ kind: 'UNKNOWN_ERROR', message: 'Both APIs failed' } as any}
            onRetry={retryAll}
            isGlobal
          />
        </Box>
      )}
    </Box>
  );
};
```

#### ScorePanel.tsx (Presenter)

```typescript
// ═══════════════════════════════════════════════════════════════════
// FILE: src/features/evaluation/components/ScorePanel.tsx
// ═══════════════════════════════════════════════════════════════════

import React from 'react';
import { Card, CardHeader, CardContent, Typography, Box, Chip, Skeleton } from '@mui/material';
import type { ScoringResponse, CareerScore } from '../types/evaluation.types';

interface ScorePanelProps {
  data: ScoringResponse;
}

export const ScorePanel: React.FC<ScorePanelProps> & { Skeleton: React.FC } = ({ data }) => {
  const topCareer = data.rankings[0];

  return (
    <Card elevation={2}>
      <CardHeader
        title="Kết quả đánh giá"
        subheader={`${data.rankings.length} ngành nghề phù hợp`}
      />
      <CardContent>
        {/* Top Career Highlight */}
        <Box sx={{ mb: 2, p: 2, bgcolor: 'primary.light', borderRadius: 1 }}>
          <Typography variant="h6" color="primary.contrastText">
            {topCareer.career_name}
          </Typography>
          <Typography variant="body2" color="primary.contrastText">
            Độ phù hợp: {(topCareer.score * 100).toFixed(0)}%
          </Typography>
        </Box>

        {/* Other Rankings */}
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
          {data.rankings.slice(1, 5).map((career) => (
            <CareerChip key={career.career_id} career={career} />
          ))}
        </Box>
      </CardContent>
    </Card>
  );
};

const CareerChip: React.FC<{ career: CareerScore }> = ({ career }) => (
  <Chip
    label={`${career.career_name} (${(career.score * 100).toFixed(0)}%)`}
    variant="outlined"
    size="small"
  />
);

ScorePanel.Skeleton = () => (
  <Card elevation={2}>
    <CardHeader
      title={<Skeleton variant="text" width="60%" />}
      subheader={<Skeleton variant="text" width="40%" />}
    />
    <CardContent>
      <Skeleton variant="rectangular" height={80} sx={{ borderRadius: 1, mb: 2 }} />
      <Box sx={{ display: 'flex', gap: 1 }}>
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} variant="rounded" width={120} height={32} />
        ))}
      </Box>
    </CardContent>
  </Card>
);
```

#### ExplainPanel.tsx (Presenter)

```typescript
// ═══════════════════════════════════════════════════════════════════
// FILE: src/features/evaluation/components/ExplainPanel.tsx
// ═══════════════════════════════════════════════════════════════════

import React from 'react';
import { Card, CardHeader, CardContent, Typography, Box, LinearProgress, Skeleton } from '@mui/material';
import type { ExplainResponse, ExplainFactor } from '../types/evaluation.types';

interface ExplainPanelProps {
  data: ExplainResponse;
}

export const ExplainPanel: React.FC<ExplainPanelProps> & { Skeleton: React.FC } = ({ data }) => {
  return (
    <Card elevation={2}>
      <CardHeader
        title="Giải thích chi tiết"
        subheader={`Model: ${data.model_version} | Confidence: ${(data.confidence * 100).toFixed(0)}%`}
      />
      <CardContent>
        {/* Explanation Text */}
        <Typography variant="body1" sx={{ mb: 3 }}>
          {data.explanation}
        </Typography>

        {/* Factor Breakdown */}
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          Các yếu tố ảnh hưởng:
        </Typography>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          {data.factors.slice(0, 5).map((factor) => (
            <FactorBar key={factor.name} factor={factor} />
          ))}
        </Box>
      </CardContent>
    </Card>
  );
};

const FactorBar: React.FC<{ factor: ExplainFactor }> = ({ factor }) => (
  <Box>
    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
      <Typography variant="caption">{factor.name}</Typography>
      <Typography variant="caption">{(factor.weight * 100).toFixed(0)}%</Typography>
    </Box>
    <LinearProgress
      variant="determinate"
      value={factor.weight * 100}
      sx={{ height: 6, borderRadius: 3 }}
    />
  </Box>
);

ExplainPanel.Skeleton = () => (
  <Card elevation={2}>
    <CardHeader
      title={<Skeleton variant="text" width="50%" />}
      subheader={<Skeleton variant="text" width="70%" />}
    />
    <CardContent>
      <Skeleton variant="text" />
      <Skeleton variant="text" />
      <Skeleton variant="text" width="80%" sx={{ mb: 3 }} />
      <Skeleton variant="text" width="40%" sx={{ mb: 1 }} />
      {[1, 2, 3].map((i) => (
        <Box key={i} sx={{ mb: 1.5 }}>
          <Skeleton variant="text" width="30%" />
          <Skeleton variant="rectangular" height={6} sx={{ borderRadius: 3 }} />
        </Box>
      ))}
    </CardContent>
  </Card>
);
```

#### LoadingStageIndicator.tsx (Presenter)

```typescript
// ═══════════════════════════════════════════════════════════════════
// FILE: src/features/evaluation/components/LoadingStageIndicator.tsx
// ═══════════════════════════════════════════════════════════════════

import React from 'react';
import { Box, Typography, CircularProgress, Chip } from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';

interface LoadingStageIndicatorProps {
  scoringProgress: 'idle' | 'loading' | 'success' | 'error';
  explainProgress: 'idle' | 'loading' | 'success' | 'error';
}

export const LoadingStageIndicator: React.FC<LoadingStageIndicatorProps> = ({
  scoringProgress,
  explainProgress,
}) => {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 3,
        mt: 3,
        p: 2,
        bgcolor: 'background.paper',
        borderRadius: 1,
        boxShadow: 1,
      }}
    >
      <StageChip label="Đánh giá" status={scoringProgress} />
      <StageChip label="Giải thích" status={explainProgress} />
    </Box>
  );
};

const StageChip: React.FC<{ label: string; status: string }> = ({ label, status }) => {
  const getIcon = () => {
    switch (status) {
      case 'loading':
        return <CircularProgress size={16} />;
      case 'success':
        return <CheckCircleIcon color="success" fontSize="small" />;
      case 'error':
        return <ErrorIcon color="error" fontSize="small" />;
      default:
        return null;
    }
  };

  const getColor = (): 'default' | 'primary' | 'success' | 'error' => {
    switch (status) {
      case 'loading':
        return 'primary';
      case 'success':
        return 'success';
      case 'error':
        return 'error';
      default:
        return 'default';
    }
  };

  return (
    <Chip
      icon={getIcon() || undefined}
      label={label}
      color={getColor()}
      variant={status === 'idle' ? 'outlined' : 'filled'}
    />
  );
};
```

#### ErrorBanner.tsx (Presenter)

```typescript
// ═══════════════════════════════════════════════════════════════════
// FILE: src/features/evaluation/components/ErrorBanner.tsx
// ═══════════════════════════════════════════════════════════════════

import React from 'react';
import { Alert, AlertTitle, Button, Box } from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import type { TypedError } from '../types/evaluation.types';

interface ErrorBannerProps {
  error: TypedError;
  onRetry?: () => void;
  isGlobal?: boolean;
}

const ERROR_MESSAGES: Record<string, string> = {
  TRANSPORT_ERROR: 'Không thể kết nối đến server. Vui lòng kiểm tra mạng.',
  TIMEOUT_ERROR: 'Yêu cầu đã hết thời gian chờ. Vui lòng thử lại.',
  RATE_LIMIT_ERROR: 'Quá nhiều yêu cầu. Vui lòng đợi một chút.',
  VALIDATION_ERROR: 'Dữ liệu không hợp lệ. Vui lòng kiểm tra lại.',
  AUTH_ERROR: 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.',
  BACKEND_ERROR: 'Lỗi server. Vui lòng thử lại sau.',
  ABORT_ERROR: 'Yêu cầu đã bị hủy.',
  UNKNOWN_ERROR: 'Đã xảy ra lỗi không xác định.',
};

export const ErrorBanner: React.FC<ErrorBannerProps> = ({ error, onRetry, isGlobal }) => {
  const message = ERROR_MESSAGES[error.kind] || error.message;
  const showRetry = error.retryable && onRetry;

  return (
    <Alert
      severity="error"
      sx={{ mt: isGlobal ? 0 : 2 }}
      action={
        showRetry && (
          <Button
            color="inherit"
            size="small"
            startIcon={<RefreshIcon />}
            onClick={onRetry}
          >
            Thử lại
          </Button>
        )
      }
    >
      <AlertTitle>
        {isGlobal ? 'Lỗi hệ thống' : `Lỗi ${error.source === 'scoring' ? 'đánh giá' : 'giải thích'}`}
      </AlertTitle>
      {message}
    </Alert>
  );
};
```

#### EvaluationButton.tsx (Presenter)

```typescript
// ═══════════════════════════════════════════════════════════════════
// FILE: src/features/evaluation/components/EvaluationButton.tsx
// ═══════════════════════════════════════════════════════════════════

import React from 'react';
import { Button, CircularProgress, Box } from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import RefreshIcon from '@mui/icons-material/Refresh';

interface EvaluationButtonProps {
  isIdle: boolean;
  isLoading: boolean;
  isCompleted: boolean;
  onStart: () => void;
  onAbort: () => void;
  onReset: () => void;
}

export const EvaluationButton: React.FC<EvaluationButtonProps> = ({
  isIdle,
  isLoading,
  isCompleted,
  onStart,
  onAbort,
  onReset,
}) => {
  if (isLoading) {
    return (
      <Button
        variant="outlined"
        color="error"
        size="large"
        startIcon={<StopIcon />}
        onClick={onAbort}
        fullWidth
      >
        Hủy đánh giá
      </Button>
    );
  }

  if (isCompleted) {
    return (
      <Button
        variant="outlined"
        color="secondary"
        size="large"
        startIcon={<RefreshIcon />}
        onClick={onReset}
        fullWidth
      >
        Đánh giá lại
      </Button>
    );
  }

  return (
    <Button
      variant="contained"
      color="primary"
      size="large"
      startIcon={<PlayArrowIcon />}
      onClick={onStart}
      disabled={!isIdle}
      fullWidth
    >
      Khởi động đánh giá AI
    </Button>
  );
};
```

### 3.6 Module Exports (index.ts)

```typescript
// ═══════════════════════════════════════════════════════════════════
// FILE: src/features/evaluation/index.ts
// ═══════════════════════════════════════════════════════════════════

// Container
export { EvaluationOrchestrator } from './EvaluationOrchestrator';

// Hook
export { useEvaluationFlow } from './hooks/useEvaluationFlow';

// Types
export type {
  PipelineState,
  ApiStatus,
  TypedError,
  ScoringResponse,
  ExplainResponse,
  EvaluationFormInput,
  UseEvaluationFlowReturn,
} from './types/evaluation.types';
```

---

## PHẦN 4 — UX RENDER STRATEGY

### 4.1 Progressive Rendering Rules

| Event | UI Update | Latency |
|-------|-----------|---------|
| Button click | Show LoadingStageIndicator | 0ms |
| Scoring starts | Show ScorePanel.Skeleton | 0ms |
| Explain starts | Show ExplainPanel.Skeleton | 0ms |
| Scoring success | Replace skeleton with ScorePanel | Immediate |
| Explain success | Replace skeleton with ExplainPanel | Immediate |
| Scoring error | Replace skeleton with ErrorBanner | Immediate |
| Explain error | Replace skeleton with ErrorBanner | Immediate |

### 4.2 Layout Stability Rules

```
INVARIANT: No layout shift after initial render

RULES:
1. Skeleton components MUST have same dimensions as final components
2. Grid layout MUST be established before any API call
3. Error banners MUST NOT add height (use fixed container)
4. Success panels MUST use same Card height as skeletons
```

### 4.3 Skeleton Dimensions Contract

| Component | Min Height | Max Height |
|-----------|------------|------------|
| ScorePanel / ScorePanel.Skeleton | 200px | 280px |
| ExplainPanel / ExplainPanel.Skeleton | 240px | 320px |
| LoadingStageIndicator | 56px | 56px |
| ErrorBanner | 80px | 120px |

### 4.4 Animation Guidelines

```
ALLOWED:
- Fade transition on panel swap (150ms ease-out)
- Progress indicator rotation
- Chip color transition

FORBIDDEN:
- Height animations (causes layout shift)
- Slide animations (causes layout shift)
- Staggered children animations (causes flash)
```

### 4.5 Error Banner Strategy

| Error Kind | Display Location | Auto Dismiss | Retry Available |
|------------|------------------|--------------|-----------------|
| `TRANSPORT_ERROR` | Per-panel | No | Yes |
| `TIMEOUT_ERROR` | Per-panel | No | Yes |
| `RATE_LIMIT_ERROR` | Per-panel | After Retry-After | Yes |
| `VALIDATION_ERROR` | Toast notification | 5s | No |
| `AUTH_ERROR` | Full-page redirect | N/A | No |
| `BACKEND_ERROR` | Per-panel | No | Yes |
| `ABORT_ERROR` | None (silent) | N/A | No |
| Both APIs failed | Global banner | No | Yes (retry all) |

---

## ASSUMPTIONS & LIMITATIONS

### Backend Schema Verification Status

| Item | Status |
|------|--------|
| ScoringPayload schema | Verified from `_frontend_backend_contract_audit_report.json` |
| ExplainPayload schema | Verified from `api/routers/explain_router.py` |
| ScoringResponse shape | Assumed based on typical ranking API |
| ExplainResponse shape | Assumed based on XAI output patterns |
| Error response format | NOT VERIFIED - assumes HTTP status only |

### Missing Backend Information

1. `ScoringResponse.timestamp` format: **Assumed ISO 8601**
2. `ExplainResponse.model_version` existence: **Assumed present**
3. Backend rate limit headers: **Assumed standard Retry-After**
4. Request ID in response: **Assumed present as `request_id`**

---

## IMPLEMENTATION CHECKLIST

```
[ ] Create folder structure: src/features/evaluation/
[ ] Create evaluation.types.ts
[ ] Create evaluation.constants.ts
[ ] Create evaluationService.ts
[ ] Create useEvaluationFlow.ts
[ ] Create ScorePanel.tsx + Skeleton
[ ] Create ExplainPanel.tsx + Skeleton
[ ] Create LoadingStageIndicator.tsx
[ ] Create ErrorBanner.tsx
[ ] Create EvaluationButton.tsx
[ ] Create EvaluationOrchestrator.tsx
[ ] Create index.ts
[ ] Write unit tests for useEvaluationFlow
[ ] Write integration tests for EvaluationOrchestrator
[ ] Verify skeleton dimensions match final components
```

---

**END OF SPECIFICATION**

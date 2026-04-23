// src/services/decisionApi.ts
/**
 * One-Button Decision API Client
 * ==============================
 *
 * SINGLE canonical entry-point for the entire decision pipeline.
 *
 * Architecture:
 *   POST /api/v1/one-button/run → Atomic execution → Full response
 *
 * Mandatory stages executed server-side (none may be skipped):
 *   1. taxonomy_normalize  — canonicalise skills / interests / education
 *   2. taxonomy_validate   — block unresolvable inputs (HTTP 400)
 *   3. rule_engine         — audit business rules (frozen pass-through)
 *   4. ml_predict          — LLM feature extraction
 *   5. scoring             — deterministic SIMGR ranking (AUTHORITY)
 *   6. explain             — XAI explanation generation
 *   7. diagnostics         — per-stage latency & error summary
 *   8. stage_trace         — full ordered execution log
 *
 * NO client-side orchestration. NO partial states. NO split calls.
 */

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');
/** Canonical decision entrypoint */
const DECISION_ENDPOINT = `${API_BASE_URL}/api/v1/one-button/run`;
const CONTRACT_VERSION = '2026-04-02.v1';
const REQUEST_SCHEMA_VERSION = 'one_button.request.v1';
const DEFAULT_TIMEOUT_MS = 20000; // 20 seconds for full pipeline (explanation now skips gracefully if slow)

// ═══════════════════════════════════════════════════════════════════
// TYPE DEFINITIONS
// ═══════════════════════════════════════════════════════════════════

export interface DecisionInput {
  user_id?: string;
  profile: {
    skills: string[];
    interests: string[];
    education_level: string;
    /** Maps to education.field_of_study in ScoringInput */
    education_field_of_study?: string;
    ability_score?: number;
    confidence_score?: number;
  };
  /** Maps to ScoringInput.experience */
  experience?: {
    years: number;
    domains: string[];
  };
  /** Maps to ScoringInput.goals */
  goals?: {
    career_aspirations: string[];
    timeline_years: number;
  };
  /** Maps to ScoringInput.preferences */
  preferences?: {
    preferred_domains: string[];
    work_style: string;
  };
  features?: {
    math_score?: number;
    logic_score?: number;
    physics_score?: number;
    literature_score?: number;
    history_score?: number;
    geography_score?: number;
    biology_score?: number;
    chemistry_score?: number;
    economics_score?: number;
    creativity_score?: number;
    interest_tech?: number;
    interest_science?: number;
    interest_arts?: number;
    interest_social?: number;
  };
}

export interface CareerResult {
  name: string;
  domain: string;
  total_score: number;
  skill_score: number;
  interest_score: number;
  market_score: number;
  growth_potential: number;
  ai_relevance: number;
}

export interface StructuredExplanation {
  summary: string;
  main_reasons: string[];
  strengths: string[];
  risks_or_gaps: string[];
  market_context: string[];
  next_actions: string[];
  confidence_explanation: string;
}

export interface ExplanationResult {
  summary: string;
  factors: Array<{
    name: string;
    contribution: number;
    description: string;
  }>;
  confidence: number;
  reasoning_chain: string[];
  structured_explanation?: StructuredExplanation | null;
}

export interface MarketInsight {
  career_name: string;
  demand_level: 'HIGH' | 'MEDIUM' | 'LOW';
  salary_range: { min: number; max: number; currency: string };
  growth_rate: number;
  competition_level: 'HIGH' | 'MEDIUM' | 'LOW';
}

export interface ScoringBreakdown {
  // P6 core fields — always present on SUCCESS
  ml_score: number;
  rule_score: number;
  penalty: number;
  final_score: number;
  result_hash: string;
  formula?: string;
  // Sub-score decomposition (from sub_scorer)
  skill_score?: number;
  experience_score?: number;
  education_score?: number;
  goal_alignment_score?: number;
  preference_score?: number;
  [key: string]: unknown;
}

export interface DecisionResponse {
  contract_version: string;
  response_schema_version: string;
  request_endpoint: string;
  canonical_endpoint: string;
  stage_manifest: string[];
  idempotency: {
    key?: string | null;
    status: 'not_provided' | 'stored' | 'replayed';
    replayed: boolean;
    request_hash?: string | null;
  };

  trace_id: string;
  timestamp: string;
  status: 'SUCCESS' | 'PARTIAL' | 'ERROR';
  
  // Core results
  rankings: CareerResult[];
  top_career: CareerResult | null;
  
  // Explanation
  explanation: ExplanationResult | null;
  
  // Market data
  market_insights: MarketInsight[];

  // Extended scoring breakdown (P6) — present on SUCCESS
  scoring_breakdown: ScoringBreakdown | null;

  // P7: Decision traceability
  rule_applied: Array<{
    rule: string;
    category: string;
    priority: number;
    outcome: string;
    frozen: boolean;
  }>;
  reasoning_path: string[];
  stage_log: Array<{
    stage: string;
    status: string;
    duration_ms: number;
    input?: Record<string, unknown>;
    output?: Record<string, unknown>;
    error?: string;
    [key: string]: unknown;
  }>;
  // P10: Diagnostics block
  diagnostics: {
    total_latency_ms: number;
    stage_count: number;
    stage_passed: number;
    stage_skipped: number;
    stage_failed: number;
    slowest_stage: string;
    errors: Array<{ stage: string; error: string | null }>;
    llm_used: boolean;
    rules_audited: number;
  } | null;

  // P11: One-button 8-stage manifest (present when endpoint = /one-button/run)
  stages?: Record<string, {
    stage: string;
    status: string;
    duration_ms: number;
    input?: Record<string, unknown>;
    output?: Record<string, unknown>;
    error?: string | null;
  }>;
  stage_trace?: Array<{
    stage: string;
    status: string;
    duration_ms: number;
    input?: Record<string, unknown>;
    output?: Record<string, unknown>;
    error?: string | null;
  }>;
  pipeline_duration_ms?: number;
  entrypoint?: string;
  entrypoint_enforced?: boolean;

  // Metadata
  meta: {
    correlation_id: string;
    pipeline_duration_ms: number;
    model_version: string;
    weights_version: string;
    llm_used: boolean;
    stages_completed: string[];
    /** P14: version trace — every response must contain these fields */
    rule_version: string;
    taxonomy_version: string;
    schema_version: string;
    schema_hash: string;
  };
  /** P14: artifact chain hash root — top-level for backward compat */
  artifact_hash_chain_root?: string;
}

export interface DecisionError {
  code: string;
  message: string;
  trace_id?: string;
  retryable: boolean;
}

// ═══════════════════════════════════════════════════════════════════
// ERROR CLASSIFICATION
// ═══════════════════════════════════════════════════════════════════

function classifyError(error: unknown): DecisionError {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return {
      code: 'TIMEOUT',
      message: 'Yêu cầu đã hết thời gian chờ. Vui lòng thử lại.',
      retryable: true,
    };
  }

  if (error instanceof TypeError && error.message.includes('fetch')) {
    return {
      code: 'NETWORK_ERROR',
      message: 'Không thể kết nối đến máy chủ. Vui lòng kiểm tra kết nối mạng.',
      retryable: true,
    };
  }

  if (error instanceof Error) {
    const anyError = error as unknown as Record<string, unknown>;
    const status = anyError.status || anyError.httpStatus;
    
    if (status === 429) {
      return {
        code: 'RATE_LIMIT',
        message: 'Quá nhiều yêu cầu. Vui lòng đợi một chút.',
        retryable: true,
      };
    }
    
    if (status === 503) {
      return {
        code: 'SERVICE_UNAVAILABLE',
        message: 'Hệ thống đang bảo trì. Vui lòng thử lại sau.',
        retryable: true,
      };
    }
    
    if (typeof status === 'number' && status >= 500) {
      return {
        code: 'SERVER_ERROR',
        message: 'Lỗi máy chủ. Vui lòng thử lại.',
        retryable: true,
      };
    }
    
    if (status === 400 || status === 422) {
      return {
        code: 'VALIDATION_ERROR',
        message: 'Dữ liệu không hợp lệ. Vui lòng kiểm tra lại.',
        retryable: false,
      };
    }

    if (status === 404) {
      return {
        code: 'NOT_FOUND',
        message: 'Endpoint không tồn tại. Vui lòng liên hệ hỗ trợ.',
        retryable: false,
      };
    }
  }

  return {
    code: 'UNKNOWN_ERROR',
    message: 'Đã xảy ra lỗi không xác định.',
    retryable: false,
  };
}

function hasValidLegacyExplanation(explanation: ExplanationResult | null | undefined): boolean {
  return Boolean(
    explanation &&
    typeof explanation.summary === 'string' &&
    explanation.summary.trim().length >= 10
  );
}

function hasValidStructuredExplanation(explanation: ExplanationResult | null | undefined): boolean {
  const structured = explanation?.structured_explanation;
  if (!structured || typeof structured !== 'object') {
    return false;
  }

  const hasSummary =
    typeof structured.summary === 'string' && structured.summary.trim().length >= 10;
  const hasConfidenceNarrative =
    typeof structured.confidence_explanation === 'string' &&
    structured.confidence_explanation.trim().length >= 8;

  const hasAnySection =
    Array.isArray(structured.main_reasons) ||
    Array.isArray(structured.strengths) ||
    Array.isArray(structured.risks_or_gaps) ||
    Array.isArray(structured.market_context) ||
    Array.isArray(structured.next_actions);

  return hasSummary && hasConfidenceNarrative && hasAnySection;
}

function normalizeExplanationPayload(explanation: ExplanationResult): ExplanationResult {
  const normalized: ExplanationResult = {
    ...explanation,
    summary: typeof explanation.summary === 'string' ? explanation.summary : '',
    factors: Array.isArray(explanation.factors) ? explanation.factors : [],
    confidence: Number.isFinite(explanation.confidence) ? explanation.confidence : 0,
    reasoning_chain: Array.isArray(explanation.reasoning_chain) ? explanation.reasoning_chain : [],
    structured_explanation: explanation.structured_explanation ?? null,
  };

  if (
    normalized.summary.trim().length < 10 &&
    normalized.structured_explanation &&
    typeof normalized.structured_explanation.summary === 'string' &&
    normalized.structured_explanation.summary.trim().length >= 10
  ) {
    normalized.summary = normalized.structured_explanation.summary.trim();
  }

  return normalized;
}

function linkAbortSignals(signal: AbortSignal | undefined, timeoutMs: number): {
  controller: AbortController;
  isTimedOut: () => boolean;
  cleanup: () => void;
} {
  const controller = new AbortController();
  let timedOut = false;

  const timeoutId = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const onAbort = () => controller.abort();
  signal?.addEventListener('abort', onAbort);

  return {
    controller,
    isTimedOut: () => timedOut,
    cleanup: () => {
      globalThis.clearTimeout(timeoutId);
      signal?.removeEventListener('abort', onAbort);
    },
  };
}

// ═══════════════════════════════════════════════════════════════════
// MAIN API FUNCTION - SINGLE ENTRY POINT
// ═══════════════════════════════════════════════════════════════════

/**
 * Execute the full decision pipeline.
 * 
 * This is the ONLY function that should be called from the frontend.
 * One button → One call → Full result.
 * 
 * @param input - User profile and features
 * @param options - Request options
 * @returns Full decision response with rankings, explanation, and market data
 */
export async function runDecisionPipeline(
  input: DecisionInput,
  options?: {
    signal?: AbortSignal;
    timeoutMs?: number;
  }
): Promise<DecisionResponse> {
  const { signal, timeoutMs = DEFAULT_TIMEOUT_MS } = options || {};
  const { controller, isTimedOut, cleanup } = linkAbortSignals(signal, timeoutMs);
  
  try {
    // Map DecisionInput → ScoringInput (strict backend Pydantic schema)
    const p = input.profile;

    // ── preferred_domains: explicit → top skills → fallback 'general' ────────
    const preferredDomains: string[] =
      (input.preferences?.preferred_domains ?? []).filter(Boolean).length > 0
        ? input.preferences!.preferred_domains.filter(Boolean)
        : p.skills.slice(0, 3).filter(Boolean).length > 0
        ? p.skills.slice(0, 3).filter(Boolean)
        : ['general'];

    // ── experience.domains: same derivation ───────────────────────────────────
    const experienceDomains: string[] =
      (input.experience?.domains ?? []).filter(Boolean).length > 0
        ? input.experience!.domains.filter(Boolean)
        : preferredDomains;

    // ── career_aspirations: explicit → derived from domains ───────────────────
    const careerAspirations: string[] =
      (input.goals?.career_aspirations ?? []).filter(Boolean).length > 0
        ? input.goals!.career_aspirations.filter(Boolean)
        : preferredDomains.map((d) => `${d} professional`).slice(0, 2);

    // ── interests: at least one entry ─────────────────────────────────────────
    const interests: string[] =
      p.interests.filter(Boolean).length > 0
        ? p.interests.filter(Boolean)
        : preferredDomains;

    // ── Runtime assertions — mirror backend min_length constraints ─────────────
    if (careerAspirations.length === 0) {
      throw Object.assign(
        new Error('ASSERTION: goals.career_aspirations must have length >= 1'),
        { status: 400 }
      );
    }
    if (preferredDomains.length === 0) {
      throw Object.assign(
        new Error('ASSERTION: preferences.preferred_domains must have length >= 1'),
        { status: 400 }
      );
    }

    const scoringInput = {
      personal_profile: {
        ability_score:    p.ability_score    ?? 0.5,
        confidence_score: p.confidence_score ?? 0.5,
        interests,
      },
      experience: {
        years:   input.experience?.years ?? 0,
        domains: experienceDomains,
      },
      goals: {
        career_aspirations: careerAspirations,
        timeline_years:     input.goals?.timeline_years ?? 3,
      },
      skills: p.skills.filter(Boolean).length > 0 ? p.skills.filter(Boolean) : ['general'],
      education: {
        level:          p.education_level                          || 'Bachelor',
        field_of_study: (p.education_field_of_study ?? '').trim() || 'general',
      },
      preferences: {
        preferred_domains: preferredDomains,
        work_style:        (input.preferences?.work_style ?? '').trim() || 'mixed',
      },
    };

    const response = await fetch(DECISION_ENDPOINT, {
      method: 'POST',
      cache: 'no-store',
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'X-Request-ID': crypto.randomUUID(),
        'Idempotency-Key': crypto.randomUUID(),
      },
      body: JSON.stringify({
        contract_version: CONTRACT_VERSION,
        request_schema_version: REQUEST_SCHEMA_VERSION,
        user_id: input.user_id || `anon_${crypto.randomUUID().slice(0, 8)}`,
        scoring_input: scoringInput,
        features: input.features || undefined,
      }),
      signal: controller.signal,
    });
    
    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}));
      const error = new Error(errorBody.detail || `HTTP ${response.status}`) as unknown as Record<string, unknown>;
      error.status = response.status;
      error.body = errorBody;
      throw error;
    }
    
    const data: DecisionResponse = await response.json();

    // Hard assertion: explanation must be present and non-trivial.
    // An empty object {}, null, or a summary shorter than 10 chars indicates
    // a backend fallback or serialization failure — surface it immediately
    // rather than rendering silently stale content.
    if (data.explanation) {
      data.explanation = normalizeExplanationPayload(data.explanation);
    }

    if (
      !data.explanation ||
      (!hasValidLegacyExplanation(data.explanation) && !hasValidStructuredExplanation(data.explanation))
    ) {
      const err = Object.assign(
        new Error(
          'Invalid explanation payload — backend returned neither a valid legacy summary nor a valid structured explanation'
        ),
        { status: 502, body: data }
      ) as unknown as Record<string, unknown>;
      throw err;
    }

    return data;

  } catch (error) {
    if (controller.signal.aborted && isTimedOut()) {
      throw classifyError(new DOMException('The operation was aborted.', 'AbortError'));
    }
    throw classifyError(error);
  } finally {
    cleanup();
  }
}

// ═══════════════════════════════════════════════════════════════════
// HEALTH CHECK - For connection validation
// ═══════════════════════════════════════════════════════════════════

export async function checkDecisionServiceHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/one-button/health`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
    });
    return response.ok;
  } catch {
    return false;
  }
}

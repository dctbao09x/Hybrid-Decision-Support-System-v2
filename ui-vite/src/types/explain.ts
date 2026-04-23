// src/types/explain.ts
/**
 * Type definitions for Explain API (Stage 6)
 * 
 * These types match the API response contract from Stage 5.
 */

/**
 * Response metadata containing version information.
 */
export interface ExplainMeta {
  model_version: string;
  xai_version: string;
  stage3_version: string;
  stage4_version: string;
}

/**
 * Single reason/evidence item.
 */
export interface ReasonItem {
  text: string;
  source?: 'shap' | 'coef' | 'perm' | 'importance' | 'rule' | string;
  weight?: number;
}

/**
 * Parsed reason from reasons array.
 */
export interface ParsedReason {
  text: string;
  source: string;
  tooltip: string;
}

/**
 * Full explanation response from /api/v1/explain.
 */
export interface ExplainResponse {
  api_version: string;
  trace_id: string;
  explanation_id?: string;
  model_id?: string;
  kb_version?: string;
  
  career: string;
  confidence: number;
  
  reasons: string[];
  explain_text: string;
  llm_text: string;
  
  used_llm: boolean;
  
  meta?: ExplainMeta;
  timestamp?: string;
  
  // Additional fields for extended responses
  score?: number;
  fallback_used?: boolean;
  processing_time_ms?: number;
  rule_path?: Array<{
    rule_id: string;
    condition: string;
    matched_features: Record<string, number>;
    weight: number;
  }>;
  weights?: Record<string, number>;
  evidence?: Array<{
    source: string;
    key: string;
    value: unknown;
    weight?: number;
  }>;
}

export interface ExplainHistoryResponse {
  items: ExplainResponse[];
  count: number;
  from?: string;
  to?: string;
}

export interface ExplainStatsResponse {
  total_records: number;
  unique_traces: number;
  range: {
    from?: string;
    to?: string;
  };
  tamper_ok: boolean;
  retention_days_min: number;
}

export interface ExplainTraceGraphResponse {
  trace_id: string;
  nodes: Array<{ id: string }>;
  edges: Array<{
    source: string;
    target: string;
    edge_type: string;
    metadata?: Record<string, unknown>;
  }>;
  adjacency: Record<string, string[]>;
}

/**
 * Error response from API.
 */
export interface ExplainError {
  api_version: string;
  trace_id: string;
  error: {
    code: string;
    message: string;
    details?: string;
  };
  timestamp: string;
}

/**
 * Request payload for /api/v1/explain.
 */
export interface ExplainRequest {
  user_id: string;
  request_id?: string;
  features: {
    math_score: number;
    logic_score: number;
    physics_score?: number;
    interest_it?: number;
    language_score?: number;
    creativity_score?: number;
    [key: string]: number | undefined;
  };
  options?: {
    use_llm?: boolean;
    include_meta?: boolean;
    timeout_ms?: number;
  };
}

/**
 * State stored for replay support.
 */
export interface ExplainState {
  trace_id: string | null;
  last_result: ExplainResponse | null;
  last_timestamp: string | null;
  used_llm: boolean;
  loading: boolean;
  error: string | null;
}

/**
 * Retry configuration for API calls.
 */
export interface RetryConfig {
  maxRetries: number;
  baseDelayMs: number;
  maxDelayMs: number;
  retryOn: string[];
}

/**
 * Polling options for async requests.
 */
export interface PollOptions {
  intervalMs?: number;
  maxAttempts?: number;
  onProgress?: (attempt: number, maxAttempts: number) => void;
}

/**
 * Configuration for Explain UI.
 */
export interface ExplainConfig {
  showMeta: boolean;
  enableDetail: boolean;
  apiVersion: string;
  apiBaseUrl: string;
  timeoutMs: number;
  enableCache: boolean;
  maxCacheAge: number;
  promptVersion: string;
  engineVersion: string;
}

/**
 * Audit mode parameters from URL.
 */
export interface AuditParams {
  mode: 'audit' | 'normal';
  trace_id?: string;
}

/**
 * Type guard for ExplainError.
 */
export function isExplainError(obj: unknown): obj is ExplainError {
  return (
    typeof obj === 'object' &&
    obj !== null &&
    'error' in obj &&
    typeof (obj as ExplainError).error === 'object'
  );
}

/**
 * Type guard for ExplainResponse.
 */
export function isExplainResponse(obj: unknown): obj is ExplainResponse {
  return (
    typeof obj === 'object' &&
    obj !== null &&
    'career' in obj &&
    'trace_id' in obj &&
    !('error' in obj)
  );
}

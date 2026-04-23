// src/services/feedbackApi.ts
/**
 * Feedback API layer
 * - Production-safe timeout + retry
 * - AbortController aware (supports request cancel)
 * - Endpoint fallback for mixed deployments
 */

import { getAdminSession } from '../utils/adminSession';
import type {
  FeedbackDetailResponse,
  FeedbackListResponse,
  FeedbackSource,
  FeedbackStatsResponse,
  FeedbackSubmitRequest,
  FeedbackSubmitResponse,
  TraceMeta,
} from '../types/feedback';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');
const DEFAULT_TIMEOUT_MS = Number(import.meta.env.VITE_FEEDBACK_TIMEOUT_MS) || 10000;
const DEFAULT_RETRY = 2;

const FEEDBACK_COLLECTION_CANDIDATES = ['/api/admin/feedback', '/api/feedback', '/api/v1/feedback'] as const;

type HttpMethod = 'GET' | 'POST';

type FeedbackStatus =
  | ''
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'flagged'
  | 'new'
  | 'reviewed'
  | 'closed'
  | 'used_in_training';

export interface FeedbackQueryParams {
  limit?: number;
  offset?: number;
  status?: FeedbackStatus;
  source?: FeedbackSource | '';
  from?: string;
  to?: string;
  signal?: AbortSignal;
  // === RETRAIN-GRADE FILTERS (2026-02-20) ===
  career_id?: string;
  model_version?: string;
  explicit_accept?: boolean;
  min_confidence?: number;
  max_confidence?: number;
}

export interface FeedbackAdminItem {
  feedback_id: string;
  user_id: string;
  content: string;
  status: string;
  source: string;
  created_at: string;
}

export interface FeedbackAdminListResponse {
  items: FeedbackAdminItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface FeedbackAdminStats {
  total_feedback: number;
  feedback_rate: number;
  processing_count: number;
  approved_count: number;
  used_for_training_count: number;
}

class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function toNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function toString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function buildHeaders(method: HttpMethod): Record<string, string> {
  const session = getAdminSession();
  const headers: Record<string, string> = {
    Accept: 'application/json',
  };

  if (session.accessToken) {
    headers.Authorization = `Bearer ${session.accessToken}`;
  }

  if (method !== 'GET') {
    headers['Content-Type'] = 'application/json';
    if (session.csrfToken) {
      headers['X-CSRF-Token'] = session.csrfToken;
    }
  }

  return headers;
}

function linkAbortSignals(signal: AbortSignal | undefined, timeoutMs: number): {
  controller: AbortController;
  isTimedOut: () => boolean;
  cleanup: () => void;
} {
  const controller = new AbortController();
  let timedOut = false;
  const timeoutId = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const onAbort = () => controller.abort();
  signal?.addEventListener('abort', onAbort);

  return {
    controller,
    isTimedOut: () => timedOut,
    cleanup: () => {
      window.clearTimeout(timeoutId);
      signal?.removeEventListener('abort', onAbort);
    },
  };
}

async function parseResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get('content-type') || '';
  const isJson = contentType.includes('application/json');
  const payload: unknown = isJson ? await response.json().catch(() => ({})) : await response.text();

  if (!response.ok) {
    const message = isRecord(payload)
      ? toString(payload.detail, toString(payload.message, `HTTP ${response.status}`))
      : `HTTP ${response.status}`;
    throw new ApiError(message, response.status);
  }

  return payload as T;
}

async function requestWithRetry<T>(
  path: string,
  method: HttpMethod,
  options: {
    body?: unknown;
    retries?: number;
    timeoutMs?: number;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  const retries = options.retries ?? DEFAULT_RETRY;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const { controller, isTimedOut, cleanup } = linkAbortSignals(options.signal, timeoutMs);

    try {
      const response = await fetch(`${API_BASE_URL}${path}`, {
        method,
        headers: buildHeaders(method),
        body: method === 'GET' ? undefined : JSON.stringify(options.body ?? {}),
        signal: controller.signal,
      });

      const parsed = await parseResponse<T>(response);
      cleanup();
      return parsed;
    } catch (error) {
      cleanup();

      if (controller.signal.aborted) {
        if (options.signal?.aborted) {
          throw new ApiError('Request was cancelled', 499);
        }

        if (isTimedOut()) {
          const timeoutError = new ApiError(`Request timed out after ${timeoutMs}ms`, 504);
          if (attempt >= retries) {
            throw timeoutError;
          }
          lastError = timeoutError;
          await sleep(300 * (attempt + 1));
          continue;
        }

        throw new ApiError('Request was cancelled', 499);
      }

      const normalized = error instanceof Error ? error : new Error('Request failed');
      lastError = normalized;

      const status = normalized instanceof ApiError ? normalized.status : 0;
      const retriable = status === 0 || status >= 500 || status === 429;

      if (!retriable || attempt >= retries) {
        throw normalized;
      }

      await sleep(300 * (attempt + 1));
    }
  }

  throw lastError ?? new Error('Unknown request failure');
}

function buildListQuery(params: FeedbackQueryParams): string {
  const query = new URLSearchParams();
  const limit = params.limit ?? 50;
  const offset = params.offset ?? 0;

  query.set('limit', String(limit));
  query.set('offset', String(offset));

  if (params.status) {
    query.set('status', params.status);
  }

  if (params.source) {
    query.set('source', params.source);
  }

  if (params.from) {
    query.set('from', params.from);
    query.set('from_date', params.from);
  }

  if (params.to) {
    query.set('to', params.to);
    query.set('to_date', params.to);
  }

  // === RETRAIN-GRADE FILTERS (2026-02-20) ===
  if (params.career_id) {
    query.set('career_id', params.career_id);
  }

  if (params.model_version) {
    query.set('model_version', params.model_version);
  }

  if (params.explicit_accept !== undefined) {
    query.set('explicit_accept', String(params.explicit_accept));
  }

  if (params.min_confidence !== undefined) {
    query.set('min_confidence', String(params.min_confidence));
  }

  if (params.max_confidence !== undefined) {
    query.set('max_confidence', String(params.max_confidence));
  }

  return query.toString();
}

async function requestFromCandidates<T>(
  suffix: string,
  method: HttpMethod,
  options: {
    body?: unknown;
    retries?: number;
    timeoutMs?: number;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  let lastError: Error | null = null;

  for (const base of FEEDBACK_COLLECTION_CANDIDATES) {
    try {
      return await requestWithRetry<T>(`${base}${suffix}`, method, options);
    } catch (error) {
      const normalized = error instanceof Error ? error : new Error('Request failed');
      lastError = normalized;
      if (normalized instanceof ApiError && normalized.status === 404) {
        continue;
      }
      throw normalized;
    }
  }

  throw lastError ?? new Error('No feedback endpoint available');
}

function normalizeListResponse(payload: unknown, fallbackLimit: number, fallbackOffset: number): FeedbackAdminListResponse {
  if (!isRecord(payload)) {
    return { items: [], total: 0, limit: fallbackLimit, offset: fallbackOffset };
  }

  const rawItems = Array.isArray(payload.items) ? payload.items : [];
  const items: FeedbackAdminItem[] = rawItems
    .map((entry): FeedbackAdminItem | null => {
      if (!isRecord(entry)) {
        return null;
      }

      const correction = isRecord(entry.correction) ? entry.correction : null;
      const correctionCareer = correction ? toString(correction.correct_career) : '';
      const reason = toString(entry.reason);
      // Backend FeedbackRecord stores the free-text body in `message`; the
      // inference-feedback model uses `correction.correct_career` / `reason`.
      const content = correctionCareer || reason || toString(entry.message);

      return {
        feedback_id: toString(entry.feedback_id, toString(entry.id)),
        user_id: toString(entry.user_id, toString(entry.reviewer_id, '-')),
        content,
        status: toString(entry.status, 'unknown'),
        source: toString(entry.source, toString(entry.category, '-')),
        created_at: toString(entry.created_at, ''),
      };
    })
    .filter((row): row is FeedbackAdminItem => row !== null && row.feedback_id.length > 0);

  return {
    items,
    total: toNumber(payload.total, items.length),
    limit: toNumber(payload.limit, fallbackLimit),
    offset: toNumber(payload.offset, fallbackOffset),
  };
}

function normalizeStats(payload: unknown): FeedbackAdminStats {
  if (!isRecord(payload)) {
    return {
      total_feedback: 0,
      feedback_rate: 0,
      processing_count: 0,
      approved_count: 0,
      used_for_training_count: 0,
    };
  }

  const statusCounts = isRecord(payload.status_counts) ? payload.status_counts : null;

  return {
    total_feedback: toNumber(payload.total_feedback),
    feedback_rate: toNumber(payload.feedback_rate),
    processing_count: statusCounts ? toNumber(statusCounts.pending, toNumber(payload.pending_count)) : toNumber(payload.pending_count),
    approved_count: statusCounts ? toNumber(statusCounts.approved, toNumber(payload.approved_count)) : toNumber(payload.approved_count),
    used_for_training_count: statusCounts
      ? toNumber(statusCounts.used_in_training, toNumber(payload.training_samples_used))
      : toNumber(payload.training_samples_used),
  };
}

export async function getFeedback(params: FeedbackQueryParams = {}): Promise<FeedbackAdminListResponse> {
  const limit = params.limit ?? 50;
  const offset = params.offset ?? 0;
  const query = buildListQuery(params);
  const payload = await requestFromCandidates<unknown>(`?${query}`, 'GET', { signal: params.signal });
  return normalizeListResponse(payload, limit, offset);
}

export async function getStats(signal?: AbortSignal): Promise<FeedbackAdminStats> {
  const payload = await requestFromCandidates<unknown>('/stats', 'GET', { signal });
  return normalizeStats(payload);
}

export async function exportCSV(params: Omit<FeedbackQueryParams, 'limit' | 'offset' | 'signal'> = {}): Promise<string> {
  const query = buildListQuery({ ...params, limit: 50, offset: 0 });
  const suffix = `/export/csv?${query}`;

  for (const base of FEEDBACK_COLLECTION_CANDIDATES) {
    const path = `${base}${suffix}`;
    const { controller, cleanup } = linkAbortSignals(undefined, DEFAULT_TIMEOUT_MS);
    try {
      const response = await fetch(`${API_BASE_URL}${path}`, {
        method: 'GET',
        headers: buildHeaders('GET'),
        signal: controller.signal,
      });
      if (response.status === 404) {
        cleanup();
        continue;
      }
      if (!response.ok) {
        throw new ApiError(`Export failed: HTTP ${response.status}`, response.status);
      }
      const text = await response.text();
      cleanup();
      return text;
    } catch (error) {
      cleanup();
      if (error instanceof ApiError && error.status === 404) {
        continue;
      }
      throw error instanceof Error ? error : new Error('Export failed');
    }
  }

  throw new Error('CSV export endpoint not available');
}

// -----------------------------------------------------------------------------
// Backward-compatible exports used by existing feedback panel.
// -----------------------------------------------------------------------------

let lastSubmitTime = 0;
const MIN_SUBMIT_INTERVAL_MS = 2000;
const sessionTraces = new Map<string, TraceMeta>();

export function injectTrace(meta: TraceMeta): void {
  if (!meta?.trace_id) {
    return;
  }
  sessionTraces.set(meta.trace_id, meta);
}

export function getTrace(traceId: string): TraceMeta | undefined {
  return sessionTraces.get(traceId);
}

export function hasTrace(traceId: string): boolean {
  return sessionTraces.has(traceId);
}

export function getSessionTrace(): TraceMeta | undefined {
  const traces = Array.from(sessionTraces.values());
  return traces.length > 0 ? traces[traces.length - 1] : undefined;
}

export function clearSessionTraces(): void {
  sessionTraces.clear();
}

export function validateFeedback(data: Partial<FeedbackSubmitRequest>): { valid: boolean; errors: Record<string, string> } {
  const errors: Record<string, string> = {};

  // === EXISTING VALIDATION ===
  if (!data.trace_id || !data.trace_id.trim()) {
    errors.trace_id = 'trace_id is required';
  }

  if (!data.rating || data.rating < 1 || data.rating > 5) {
    errors.rating = 'Rating must be between 1 and 5';
  }

  const correctionText = typeof data.correction === 'string'
    ? data.correction
    : data.correction?.correct_career || '';
  if (!correctionText || correctionText.length < 20) {
    errors.correction = 'Correction must be at least 20 characters';
  }

  if (!data.reason || data.reason.length < 10) {
    errors.reason = 'Reason must be at least 10 characters';
  }

  // === RETRAIN-GRADE VALIDATION (2026-02-20) ===
  if (!data.career_id || !data.career_id.trim()) {
    errors.career_id = 'career_id is required for retrain-grade feedback';
  }

  if (!data.rank_position || data.rank_position < 1) {
    errors.rank_position = 'rank_position must be >= 1';
  }

  if (!data.score_snapshot || typeof data.score_snapshot !== 'object') {
    errors.score_snapshot = 'score_snapshot is required';
  } else if (data.score_snapshot.matchScore === undefined) {
    errors.score_snapshot = 'score_snapshot must contain matchScore';
  }

  if (!data.profile_snapshot || typeof data.profile_snapshot !== 'object' || Object.keys(data.profile_snapshot).length === 0) {
    errors.profile_snapshot = 'profile_snapshot is required and cannot be empty';
  }

  if (!data.model_version || !data.model_version.trim()) {
    errors.model_version = 'model_version is required for retrain-grade feedback';
  }

  if (data.explicit_accept === undefined) {
    errors.explicit_accept = 'explicit_accept is required (true for rating >= 4, false for rating <= 2)';
  }

  return {
    valid: Object.keys(errors).length === 0,
    errors,
  };
}

export async function submitFeedback(data: FeedbackSubmitRequest): Promise<FeedbackSubmitResponse> {
  const now = Date.now();
  if (now - lastSubmitTime < MIN_SUBMIT_INTERVAL_MS) {
    throw new Error('Please wait before submitting another feedback');
  }

  const validation = validateFeedback(data);
  if (!validation.valid) {
    throw new Error(Object.values(validation.errors).join('; '));
  }

  // Keep submit endpoint fallback for environments exposing /api/feedback/submit or /api/v1/feedback/submit.
  const submitCandidates = ['/api/feedback/submit', '/api/v1/feedback/submit'] as const;
  let lastError: Error | null = null;

  for (const path of submitCandidates) {
    try {
      const response = await requestWithRetry<FeedbackSubmitResponse>(path, 'POST', {
        body: data,
      });
      lastSubmitTime = now;
      return response;
    } catch (error) {
      const normalized = error instanceof Error ? error : new Error('Submit failed');
      lastError = normalized;
      if (normalized instanceof ApiError && normalized.status === 404) {
        continue;
      }
      throw normalized;
    }
  }

  throw lastError ?? new Error('Submit endpoint not available');
}

export async function getFeedbackStats(
  _fromDate?: string,
  _toDate?: string,
): Promise<FeedbackStatsResponse> {
  const stats = await getStats();
  return {
    total_feedback: stats.total_feedback,
    pending_count: stats.processing_count,
    approved_count: stats.approved_count,
    rejected_count: 0,
    flagged_count: 0,
    feedback_rate: stats.feedback_rate,
    approval_rate: 0,
    correction_rate: 0,
    avg_rating: 0,
    avg_quality_score: 0,
    training_samples_generated: 0,
    training_samples_used: stats.used_for_training_count,
    retrain_impact: 0,
    drift_signal: 0,
    career_distribution: {},
    linked_to_trace: 0,
    pending_for_training: stats.processing_count,
    status_counts: {
      pending: stats.processing_count,
      approved: stats.approved_count,
      rejected: 0,
      used_in_training: stats.used_for_training_count,
    },
  };
}

export async function getFeedbackList(
  options: {
    status?: string;
    source?: FeedbackSource;
    from_date?: string;
    to_date?: string;
    limit?: number;
    offset?: number;
  } = {},
): Promise<FeedbackListResponse> {
  const list = await getFeedback({
    limit: options.limit,
    offset: options.offset,
    status: (options.status ?? '') as FeedbackStatus,
    source: options.source ?? '',
    from: options.from_date,
    to: options.to_date,
  });

  const items: FeedbackDetailResponse[] = list.items.map((item) => ({
    feedback_id: item.feedback_id,
    trace_id: '',
    rating: 0,
    correction: { correct_career: item.content },
    reason: item.content,
    source: item.source as FeedbackSource,
    status: item.status as FeedbackDetailResponse['status'],
    created_at: item.created_at,
    quality_score: 0,
  }));

  return {
    items,
    total: list.total,
    limit: list.limit,
    offset: list.offset,
  };
}

export async function exportFeedback(
  options: {
    format?: 'json' | 'csv';
    status?: string;
    source?: FeedbackSource;
    from_date?: string;
    to_date?: string;
  } = {},
): Promise<string | Record<string, unknown>> {
  const format = options.format ?? 'json';
  if (format === 'csv') {
    return exportCSV({
      status: (options.status ?? '') as FeedbackStatus,
      source: options.source ?? '',
      from: options.from_date,
      to: options.to_date,
    });
  }

  const list = await getFeedback({
    status: (options.status ?? '') as FeedbackStatus,
    source: options.source ?? '',
    from: options.from_date,
    to: options.to_date,
  });
  return { items: list.items, total: list.total };
}

export function interceptResponse<T extends { meta?: TraceMeta; trace_id?: string }>(response: T): T {
  if (response.meta?.trace_id) {
    injectTrace(response.meta);
    return response;
  }
  if (response.trace_id) {
    injectTrace({
      trace_id: response.trace_id,
      model_version: 'unknown',
      kb_version: 'unknown',
      confidence: 0,
    });
  }
  return response;
}

// src/services/explainApi.ts
/**
 * Explain API Client Layer (Stage 6)
 * 
 * Handles communication with /api/v1/explain endpoint.
 * Only source for explain data - no direct backend calls elsewhere.
 * 
 * Features:
 *   - Timeout handling (configurable)
 *   - Retry with exponential backoff
 *   - Response caching
 *   - Structured error handling
 *   - Telemetry hooks
 */

import type {
  ExplainRequest,
  ExplainResponse,
  ExplainError,
  PollOptions,
  RetryConfig,
  ExplainHistoryResponse,
  ExplainStatsResponse,
  ExplainTraceGraphResponse,
} from '../types/explain';
import { isExplainError } from '../types/explain';
import { EXPLAIN, ENDPOINTS, ERROR_DISPLAY } from '../config/explain';
import { logInfo, logWarn, logError, trackApiCall } from '../utils/logger';

// Cache for responses
const responseCache = new Map<string, { data: ExplainResponse; timestamp: number }>();

// Default retry configuration
const DEFAULT_RETRY_CONFIG: RetryConfig = {
  maxRetries: 2,  // Reduced from 3 for faster fail
  baseDelayMs: 800,
  maxDelayMs: 4000,
  retryOn: ['E502', 'E503', 'E504'],
};

/**
 * Sleep for a specified duration.
 */
function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Calculate delay with exponential backoff and jitter.
 */
function getRetryDelay(attempt: number, config: RetryConfig): number {
  const baseDelay = config.baseDelayMs * Math.pow(2, attempt);
  const jitter = Math.random() * 500;
  return Math.min(baseDelay + jitter, config.maxDelayMs);
}

/**
 * Clear expired cache entries.
 */
function cleanCache(): void {
  const now = Date.now();
  for (const [key, entry] of responseCache.entries()) {
    if (now - entry.timestamp > EXPLAIN.maxCacheAge) {
      responseCache.delete(key);
    }
  }
}

/**
 * FNV-1a 32-bit hash of an ordered sequence of numeric score values.
 * Deterministic: same scores always produce the same hex string.
 * Used as a component of the cache key to distinguish score vectors
 * independently of JSON key ordering.
 */
function hashScores(features: ExplainRequest['features']): string {
  // Extract numeric values in deterministic key-sort order.
  const values = Object.keys(features)
    .sort()
    .map((k) => (features as Record<string, unknown>)[k])
    .filter((v): v is number => typeof v === 'number');

  let hash = 0x811c9dc5; // FNV offset basis (32-bit)
  for (const value of values) {
    // Represent each float as a fixed string to avoid IEEE 754 rounding
    // differences between environments.
    const bytes = String(value.toFixed(6));
    for (let i = 0; i < bytes.length; i++) {
      hash ^= bytes.charCodeAt(i);
      // FNV prime 32-bit: 0x01000193
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
  }
  return hash.toString(16).padStart(8, '0');
}

/**
 * Generate a versioned, content-addressable cache key.
 *
 * Key components:
 *   features      — raw score input (canonicalized via JSON.stringify)
 *   options       — request options affecting output format
 *   promptVersion — VITE_PROMPT_VERSION baked at build time
 *   engineVersion — VITE_ENGINE_VERSION baked at build time
 *   scoringHash   — FNV-1a fingerprint of numeric score vector
 *
 * Any change to prompt template, engine, or scores produces a different key.
 * Old entries become unreachable without explicit deletion.
 */
function getCacheKey(request: ExplainRequest): string {
  const { features, options } = request;
  return JSON.stringify({
    features,
    options,
    promptVersion: EXPLAIN.promptVersion,
    engineVersion: EXPLAIN.engineVersion,
    scoringHash: hashScores(features),
  });
}

/**
 * Get cached response if valid.
 * Emits explain_cache_hit_total{reason="memory"} on hit.
 */
function getCachedResponse(request: ExplainRequest): ExplainResponse | null {
  if (!EXPLAIN.enableCache) return null;

  const key = getCacheKey(request);
  const cached = responseCache.get(key);

  if (cached && Date.now() - cached.timestamp < EXPLAIN.maxCacheAge) {
    _emitCacheHit('memory');
    return cached.data;
  }

  return null;
}

/**
 * Internal telemetry counter for cache hits.
 * Increments explain_cache_hit_total with a reason label.
 * Piggybacks on the existing trackApiCall hook for transport.
 */
function _emitCacheHit(reason: 'memory'): void {
  try {
    trackApiCall('explain_cache_hit', 0, true, reason);
  } catch {
    // Telemetry must never throw
  }
}

/**
 * Store response in cache.
 *
 * Skips caching when:
 *   - Cache is disabled
 *   - X-Fallback-Used header is "true" (response is degraded)
 *   - HTTP status is not 200 (non-canonical response)
 */
function cacheResponse(
  request: ExplainRequest,
  response: ExplainResponse,
  rawResponse?: Response,
): void {
  if (!EXPLAIN.enableCache) return;

  if (rawResponse !== undefined) {
    // Never cache a fallback response — it may be inferior quality and
    // should not survive the next successful LLM call.
    if (rawResponse.headers.get('x-fallback-used') === 'true') {
      logWarn('[explainApi] Skipping cache: X-Fallback-Used=true', {});
      return;
    }
    if (rawResponse.status !== 200) {
      logWarn('[explainApi] Skipping cache: HTTP status', { status: rawResponse.status });
      return;
    }
  }

  cleanCache();

  const key = getCacheKey(request);
  responseCache.set(key, {
    data: response,
    timestamp: Date.now(),
  });
}

/**
 * Parse error response.
 */
function parseError(error: unknown): { code: string; message: string } {
  if (isExplainError(error)) {
    return error.error;
  }
  
  if (error instanceof Error) {
    if (error.message.includes('timeout') || error.message.includes('abort')) {
      return { code: 'E504', message: 'Request timed out' };
    }
    if (error.message.includes('network') || error.message.includes('fetch')) {
      return { code: 'E502', message: 'Network error' };
    }
    return { code: 'E500', message: error.message };
  }
  
  return { code: 'E500', message: 'Unknown error' };
}

async function parseResponseBody(response: Response): Promise<Record<string, unknown>> {
  const raw = await response.text();
  if (!raw) {
    return {};
  }

  try {
    return JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return { message: raw, detail: raw };
  }
}

/**
 * Get user-friendly error info.
 */
export function getErrorDisplay(code: string): typeof ERROR_DISPLAY[keyof typeof ERROR_DISPLAY] {
  return ERROR_DISPLAY[code as keyof typeof ERROR_DISPLAY] || ERROR_DISPLAY.E500;
}

/**
 * Main API function: Get explanation from API.
 * 
 * @param payload - ExplainRequest with user features
 * @param retryConfig - Optional retry configuration
 * @returns Promise<ExplainResponse>
 * @throws Error with code and message
 * 
 * @example
 * ```ts
 * const response = await getExplanation({
 *   user_id: "user123",
 *   features: {
 *     math_score: 85,
 *     logic_score: 90
 *   }
 * });
 * ```
 */
export async function getExplanation(
  payload: ExplainRequest,
  retryConfig: Partial<RetryConfig> = {}
): Promise<ExplainResponse> {
  const config = { ...DEFAULT_RETRY_CONFIG, ...retryConfig };
  const startTime = performance.now();
  
  // Check cache first
  const cached = getCachedResponse(payload);
  if (cached) {
    logInfo('[explainApi] Cache hit for request', { user_id: payload.user_id });
    trackApiCall('getExplanation', performance.now() - startTime, true, 'cache_hit');
    return cached;
  }
  
  const url = `${EXPLAIN.apiBaseUrl}${ENDPOINTS.explain}`;
  let lastError: ExplainError | null = null;
  
  for (let attempt = 0; attempt <= config.maxRetries; attempt++) {
    if (attempt > 0) {
      const delay = getRetryDelay(attempt - 1, config);
      logWarn('[explainApi] Retrying request', { attempt, delay, user_id: payload.user_id });
      await sleep(delay);
    }
    
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), EXPLAIN.timeoutMs);
    
    try {
      logInfo('[explainApi] Sending POST request', { 
        url, 
        attempt, 
        user_id: payload.user_id,
        features: payload.features 
      });
      
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      
      const data = await parseResponseBody(response);
      
      // Check for error response
      if (isExplainError(data)) {
        lastError = data;
        if (config.retryOn.includes(data.error.code) && attempt < config.maxRetries) {
          logWarn('[explainApi] Retryable error received', { code: data.error.code });
          continue;
        }
        throw data;
      }
      
      if (!response.ok) {
        const detail = data.detail;
        const message =
          (typeof detail === 'string' && detail) ||
          (typeof data.message === 'string' && data.message) ||
          (typeof (detail as Record<string, unknown>)?.message === 'string' &&
            ((detail as Record<string, unknown>).message as string)) ||
          (typeof (detail as Record<string, unknown>)?.error === 'object' &&
            typeof (((detail as Record<string, unknown>).error as Record<string, unknown>).message) === 'string' &&
            ((((detail as Record<string, unknown>).error as Record<string, unknown>).message) as string)) ||
          'Request failed';

        const error: ExplainError = {
          api_version: EXPLAIN.apiVersion,
          trace_id: (typeof data.trace_id === 'string' && data.trace_id) || 'unknown',
          error: {
            code: `E${response.status}`.slice(0, 4),
            message,
          },
          timestamp: new Date().toISOString(),
        };
        lastError = error;
        
        if (config.retryOn.includes(error.error.code) && attempt < config.maxRetries) {
          continue;
        }
        throw error;
      }
      
      // Cache successful response — pass raw Response so cacheResponse
      // can inspect X-Fallback-Used and HTTP status before persisting.
      cacheResponse(payload, (data as unknown) as ExplainResponse, response);
      
      const duration = performance.now() - startTime;
      logInfo('[explainApi] Request successful', { 
        trace_id: data.trace_id, 
        duration: `${duration.toFixed(0)}ms`,
        attempts: attempt + 1
      });
      trackApiCall('getExplanation', duration, true);
      
      return (data as unknown) as ExplainResponse;
      
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        const timeoutError: ExplainError = {
          api_version: EXPLAIN.apiVersion,
          trace_id: 'timeout',
          error: { code: 'E504', message: 'Request timed out' },
          timestamp: new Date().toISOString(),
        };
        lastError = timeoutError;
        
        if (config.retryOn.includes('E504') && attempt < config.maxRetries) {
          logWarn('[explainApi] Request timeout, will retry', { attempt });
          continue;
        }
        throw timeoutError;
      }
      
      // Re-throw if already ExplainError
      if (isExplainError(error)) {
        throw error;
      }
      
      // Wrap other errors
      const parsed = parseError(error);
      const wrappedError: ExplainError = {
        api_version: EXPLAIN.apiVersion,
        trace_id: 'error',
        error: parsed,
        timestamp: new Date().toISOString(),
      };
      lastError = wrappedError;
      
      if (config.retryOn.includes(parsed.code) && attempt < config.maxRetries) {
        continue;
      }
      throw wrappedError;
      
    } finally {
      clearTimeout(timeoutId);
    }
  }
  
  // All retries exhausted
  const duration = performance.now() - startTime;
  logError('[explainApi] All retries exhausted', { 
    lastError: lastError?.error,
    duration: `${duration.toFixed(0)}ms`
  });
  trackApiCall('getExplanation', duration, false, lastError?.error.code);
  throw lastError!;
}

/**
 * Get stored explanation by trace_id (replay/audit mode).
 * 
 * @param traceId - The trace ID to fetch
 * @param retryConfig - Optional retry configuration
 * @returns Promise<ExplainResponse>
 */
export async function getExplanationByTraceId(
  traceId: string,
  retryConfig: Partial<RetryConfig> = {}
): Promise<ExplainResponse> {
  const config = { ...DEFAULT_RETRY_CONFIG, ...retryConfig };
  const startTime = performance.now();
  const url = `${EXPLAIN.apiBaseUrl}${ENDPOINTS.explain}/${traceId}`;
  let lastError: ExplainError | null = null;
  
  for (let attempt = 0; attempt <= config.maxRetries; attempt++) {
    if (attempt > 0) {
      const delay = getRetryDelay(attempt - 1, config);
      logWarn('[explainApi] Retrying GET request', { traceId, attempt, delay });
      await sleep(delay);
    }
    
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), EXPLAIN.timeoutMs);
    
    try {
      logInfo('[explainApi] Fetching by trace_id', { traceId, attempt });
      
      const response = await fetch(url, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
        signal: controller.signal,
      });
      
      const data = await parseResponseBody(response);
      
      if (isExplainError(data)) {
        lastError = data;
        if (config.retryOn.includes(data.error.code) && attempt < config.maxRetries) {
          continue;
        }
        throw data;
      }
      
      if (!response.ok) {
        const detail = data.detail;
        const message =
          (typeof detail === 'string' && detail) ||
          (typeof data.message === 'string' && data.message) ||
          (typeof (detail as Record<string, unknown>)?.message === 'string' &&
            ((detail as Record<string, unknown>).message as string)) ||
          'Not found';

        const error: ExplainError = {
          api_version: EXPLAIN.apiVersion,
          trace_id: traceId,
          error: {
            code: response.status === 404 ? 'E404' : 'E500',
            message,
          },
          timestamp: new Date().toISOString(),
        };
        // Don't retry 404
        if (response.status === 404) {
          throw error;
        }
        lastError = error;
        if (config.retryOn.includes(error.error.code) && attempt < config.maxRetries) {
          continue;
        }
        throw error;
      }
      
      const duration = performance.now() - startTime;
      logInfo('[explainApi] GET by trace_id successful', { 
        traceId, 
        duration: `${duration.toFixed(0)}ms` 
      });
      trackApiCall('getExplanationByTraceId', duration, true);
      
      return (data as unknown) as ExplainResponse;
      
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        const timeoutError: ExplainError = {
          api_version: EXPLAIN.apiVersion,
          trace_id: traceId,
          error: { code: 'E504', message: 'Request timed out' },
          timestamp: new Date().toISOString(),
        };
        lastError = timeoutError;
        if (config.retryOn.includes('E504') && attempt < config.maxRetries) {
          continue;
        }
        throw timeoutError;
      }
      
      if (isExplainError(error)) {
        throw error;
      }
      
      const parsed = parseError(error);
      lastError = {
        api_version: EXPLAIN.apiVersion,
        trace_id: traceId,
        error: parsed,
        timestamp: new Date().toISOString(),
      };
      throw lastError;
    } finally {
      clearTimeout(timeoutId);
    }
  }
  
  const duration = performance.now() - startTime;
  logError('[explainApi] GET by trace_id failed after retries', { traceId, duration });
  trackApiCall('getExplanationByTraceId', duration, false, lastError?.error.code);
  throw lastError!;
}

/**
 * Poll for explanation result by trace_id.
 * Used when backend is processing asynchronously.
 * 
 * @param traceId - The trace ID to poll for
 * @param options - Polling options
 * @returns Promise<ExplainResponse>
 */
export async function pollExplanationByTraceId(
  traceId: string,
  options: PollOptions = {}
): Promise<ExplainResponse> {
  const {
    intervalMs = 2000,
    maxAttempts = 15,
    onProgress,
  } = options;
  
  logInfo('[explainApi] Starting poll for trace_id', { traceId, maxAttempts });
  
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      onProgress?.(attempt, maxAttempts);
      
      const response = await getExplanationByTraceId(traceId, { maxRetries: 0 });
      
      // Check if result is ready (has career and not pending)
      if (response.career && response.trace_id) {
        logInfo('[explainApi] Poll completed', { traceId, attempt });
        return response;
      }
      
    } catch (error) {
      // 404 means still processing, continue polling
      if (isExplainError(error) && error.error.code === 'E404') {
        logInfo('[explainApi] Result not ready, continuing poll', { traceId, attempt });
      } else {
        // Other errors, stop polling
        throw error;
      }
    }
    
    if (attempt < maxAttempts) {
      await sleep(intervalMs);
    }
  }
  
  // Max attempts reached
  const error: ExplainError = {
    api_version: EXPLAIN.apiVersion,
    trace_id: traceId,
    error: {
      code: 'E504',
      message: 'Polling timeout - result not ready',
    },
    timestamp: new Date().toISOString(),
  };
  logError('[explainApi] Poll timeout', { traceId, maxAttempts });
  throw error;
}

/**
 * Check API health status with timeout.
 */
export async function checkHealth(timeoutMs = 3000): Promise<{
  status: string;
  api_version: string;
  components: Record<string, string>;
} | null> {
  const url = `${EXPLAIN.apiBaseUrl}${ENDPOINTS.health}`;
  
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  
  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
    });
    
    clearTimeout(timeoutId);
    
    if (!response.ok) {
      console.warn('[checkHealth] Non-OK response:', response.status);
      return null;
    }
    
    return response.json();
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof Error && err.name === 'AbortError') {
      console.warn('[checkHealth] Request timeout');
    } else {
      console.warn('[checkHealth] Request failed:', err);
    }
    return null;
  }
}

/**
 * Clear response cache.
 */
export function clearCache(): void {
  responseCache.clear();
}

/**
 * Get cache statistics.
 */
export function getCacheStats(): { size: number; enabled: boolean } {
  return {
    size: responseCache.size,
    enabled: EXPLAIN.enableCache,
  };
}

export async function getExplanationHistory(
  fromDate?: string,
  toDate?: string
): Promise<ExplainHistoryResponse> {
  const baseUrl = `${EXPLAIN.apiBaseUrl}${ENDPOINTS.explain}/history`;
  const params = new URLSearchParams();
  if (fromDate) params.set('from', fromDate);
  if (toDate) params.set('to', toDate);
  const url = params.toString() ? `${baseUrl}?${params.toString()}` : baseUrl;

  const response = await fetch(url, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch explanation history: ${response.status}`);
  }
  return response.json();
}

export async function getExplanationStats(): Promise<ExplainStatsResponse> {
  const url = `${EXPLAIN.apiBaseUrl}${ENDPOINTS.explain}/stats`;
  const response = await fetch(url, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch explanation stats: ${response.status}`);
  }
  return response.json();
}

export async function getExplanationTraceGraph(traceId: string): Promise<ExplainTraceGraphResponse> {
  const url = `${EXPLAIN.apiBaseUrl}${ENDPOINTS.explain}/graph/${traceId}`;
  const response = await fetch(url, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch trace graph: ${response.status}`);
  }
  return response.json();
}

/**
 * Export explanation to PDF (downloads from backend).
 * Falls back to window.print() if backend export fails.
 */
export async function exportExplainToPdf(traceId?: string): Promise<void> {
  if (!traceId) {
    // Fallback to window.print() if no trace ID provided
    window.print();
    return;
  }

  try {
    const url = `${EXPLAIN.apiBaseUrl}${ENDPOINTS.explain}/${traceId}/pdf`;
    const response = await fetch(url, {
      method: 'GET',
      headers: { 'Accept': 'application/pdf' },
    });

    if (!response.ok) {
      throw new Error(`PDF export failed: ${response.status}`);
    }

    // Get the PDF blob
    const blob = await response.blob();

    // Create download link
    const downloadUrl = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = downloadUrl;
    link.download = `explanation_${traceId}.pdf`;

    // Trigger download
    document.body.appendChild(link);
    link.click();

    // Cleanup
    document.body.removeChild(link);
    window.URL.revokeObjectURL(downloadUrl);

    logInfo('PDF exported successfully', { traceId });
  } catch (error) {
    logWarn('PDF export failed, falling back to print', { error });
    window.print();
  }
}

/**
 * Get calibration report with Brier Score and ECE.
 */
export interface CalibrationReport {
  brier_score: number;
  expected_calibration_error: number;
  max_calibration_error: number;
  overall_accuracy: number;
  total_samples: number;
  correct_predictions: number;
  is_well_calibrated: boolean;
  bins: Array<{
    bin_start: number;
    bin_end: number;
    count: number;
    mean_confidence: number;
    accuracy: number;
    gap: number;
  }>;
  timestamp: string;
}

export async function getCalibrationReport(
  nBins: number = 10,
  fromDate?: string,
  toDate?: string
): Promise<CalibrationReport> {
  let url = `${EXPLAIN.apiBaseUrl}${ENDPOINTS.explain}/calibration/report?n_bins=${nBins}`;
  if (fromDate) url += `&from=${encodeURIComponent(fromDate)}`;
  if (toDate) url += `&to=${encodeURIComponent(toDate)}`;

  const response = await fetch(url, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch calibration report: ${response.status}`);
  }

  return response.json();
}

/**
 * Legal hold management interfaces and functions.
 */
export interface LegalHoldStatus {
  trace_id: string;
  legal_hold: boolean;
  created_at: string;
}

export async function setLegalHold(traceId: string): Promise<LegalHoldStatus> {
  const url = `${EXPLAIN.apiBaseUrl}${ENDPOINTS.explain}/legal-hold/${traceId}`;
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Role': 'admin',
    },
    credentials: 'include',  // Include cookies for cross-origin requests
  });

  if (!response.ok) {
    throw new Error(`Failed to set legal hold: ${response.status}`);
  }

  return response.json();
}

export async function clearLegalHold(traceId: string): Promise<LegalHoldStatus> {
  const url = `${EXPLAIN.apiBaseUrl}${ENDPOINTS.explain}/legal-hold/${traceId}`;
  const response = await fetch(url, {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json',
      'X-Role': 'admin',
    },
    credentials: 'include',  // Include cookies for cross-origin requests
  });

  if (!response.ok) {
    throw new Error(`Failed to clear legal hold: ${response.status}`);
  }

  return response.json();
}

export async function getLegalHoldStatus(traceId: string): Promise<LegalHoldStatus> {
  const url = `${EXPLAIN.apiBaseUrl}${ENDPOINTS.explain}/legal-hold/${traceId}`;
  const response = await fetch(url, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',  // Include cookies for cross-origin requests
  });

  if (!response.ok) {
    throw new Error(`Failed to get legal hold status: ${response.status}`);
  }

  return response.json();
}

export default {
  getExplanation,
  getExplanationByTraceId,
  pollExplanationByTraceId,
  checkHealth,
  clearCache,
  getCacheStats,
  getErrorDisplay,
  getExplanationHistory,
  getExplanationStats,
  getExplanationTraceGraph,
  exportExplainToPdf,
  getCalibrationReport,
  setLegalHold,
  clearLegalHold,
  getLegalHoldStatus,
};

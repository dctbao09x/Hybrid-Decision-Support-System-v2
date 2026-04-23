import { getAdminSession, clearAdminSession, saveAdminSession } from '../../utils/adminSession';
import type { AdminSessionPayload } from '../../utils/adminSession';
import { endpoints } from './endpoints';

function resolveApiBaseUrl() {
  const raw = import.meta.env.VITE_API_BASE_URL;
  if (!raw) {
    // In dev, use same-origin so requests route via the Vite proxy (/api → http://127.0.0.1:8000)
    return '';
  }
  try {
    const parsed = new URL(raw);
    if (parsed.hostname === 'localhost') {
      parsed.hostname = '127.0.0.1';
    }
    return parsed.toString().replace(/\/$/, '');
  } catch {
    return '';
  }
}

const API_BASE_URL = resolveApiBaseUrl();
const RETRY_COUNT = 2;
const RETRY_BASE_DELAY_MS = 200;  // Increased from 150
const RETRY_MAX_DELAY_MS = 2000;  // Cap retry delay
const REQUEST_TIMEOUT_MS = Number(import.meta.env.VITE_ADMIN_REQUEST_TIMEOUT_MS) || 10000; // Reduced from 12000
const BREAKER_FAILURE_THRESHOLD = 10;  // Raised: don't trip on backend warmup blips
const BREAKER_RESET_TIMEOUT_MS = 15000; // Give backend more time to recover
const BREAKER_HALF_OPEN_MAX_PROBES = 2; // Allow 2 probes instead of 1
const SLOW_REQUEST_LOG_MS = 2000; // Reduced from 3000
const PENDING_ALERT_THRESHOLD = 15; // Reduced from 20

/**
 * Add jitter to retry delay for better load distribution.
 * Uses decorrelated jitter algorithm for optimal retry spread.
 */
function getRetryDelay(attempt: number, baseDelay: number = RETRY_BASE_DELAY_MS): number {
  // Exponential backoff with full jitter
  const exponentialDelay = baseDelay * Math.pow(2, attempt);
  const cappedDelay = Math.min(exponentialDelay, RETRY_MAX_DELAY_MS);
  // Full jitter: random between 0 and capped delay
  const jitter = Math.random() * cappedDelay;
  return Math.max(baseDelay, jitter);
}

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

interface RequestOptions {
  method?: HttpMethod;
  body?: unknown;
  headers?: Record<string, string>;
  skipAuth?: boolean;
  timeoutMs?: number;
}

interface ApiError {
  status: number;
  code: string;
  message: string;
  retriable: boolean;
}

interface PendingRequest {
  abortController: AbortController;
  startedAt: number;
}

const breakerState = {
  failures: 0,
  openedAt: 0,
  halfOpenProbeCount: 0,
  state: 'closed' as 'closed' | 'open' | 'half-open',
};

const pendingRequests = new Map<string, PendingRequest>();

function normalizeError(status: number, message: string): ApiError {
  return {
    status,
    code: status >= 500 ? 'SERVER_ERROR' : status === 401 ? 'UNAUTHORIZED' : 'REQUEST_ERROR',
    message,
    retriable: (status >= 500 && status !== 504) || status === 429,
  };
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getRequestKey(method: HttpMethod, path: string, body: unknown) {
  const bodyKey = body === undefined ? '' : JSON.stringify(body);
  return `${method}:${path}:${bodyKey}`;
}

function shouldOpenCircuit() {
  return breakerState.failures >= BREAKER_FAILURE_THRESHOLD;
}

function isCircuitOpen() {
  if (breakerState.state !== 'open') return false;
  if (breakerState.openedAt === 0) return false;

  if (Date.now() - breakerState.openedAt > BREAKER_RESET_TIMEOUT_MS) {
    breakerState.state = 'half-open';
    breakerState.halfOpenProbeCount = 0;
    return false;
  }

  return true;
}

function recordFailure() {
  if (breakerState.state === 'half-open') {
    breakerState.state = 'open';
    breakerState.openedAt = Date.now();
    breakerState.halfOpenProbeCount = 0;
    return;
  }

  breakerState.failures += 1;
  if (shouldOpenCircuit()) {
    breakerState.state = 'open';
    breakerState.openedAt = Date.now();
  }
}

function recordSuccess() {
  breakerState.state = 'closed';
  breakerState.failures = 0;
  breakerState.openedAt = 0;
  breakerState.halfOpenProbeCount = 0;
}

function canExecuteInHalfOpen() {
  if (breakerState.state !== 'half-open') return true;
  if (breakerState.halfOpenProbeCount >= BREAKER_HALF_OPEN_MAX_PROBES) {
    return false;
  }
  breakerState.halfOpenProbeCount += 1;
  return true;
}

function withTimeout<T>(
  promise: Promise<T>,
  timeoutMs: number,
  onTimeout: () => void,
  errorFactory: () => ApiError,
): Promise<T> {
  let timer = 0;
  const timeoutPromise = new Promise<T>((_, reject) => {
    timer = window.setTimeout(() => {
      onTimeout();
      reject(errorFactory());
    }, timeoutMs);
  });

  return Promise.race([promise, timeoutPromise]).finally(() => {
    if (timer) {
      window.clearTimeout(timer);
    }
  });
}

async function parseResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await response.json().catch(() => ({})) : await response.text();

  if (!response.ok) {
    const message = typeof payload === 'string'
      ? payload
      : payload?.detail || payload?.message || `HTTP ${response.status}`;
    throw normalizeError(response.status, message);
  }

  return payload as T;
}

async function refreshToken() {
  const session = getAdminSession();
  if (!session.refreshToken) {
    clearAdminSession();
    throw normalizeError(401, 'Session expired');
  }

  const response = await fetch(`${API_BASE_URL}${endpoints.auth.refresh}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refreshToken: session.refreshToken }),
  });

  const data = await parseResponse<Record<string, unknown>>(response);
  saveAdminSession(data as unknown as AdminSessionPayload);
  return data;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  if (isCircuitOpen()) {
    throw normalizeError(503, 'Service temporarily unavailable (circuit open)');
  }

  const method = options.method || 'GET';
  if (!canExecuteInHalfOpen()) {
    throw normalizeError(503, 'Service temporarily unavailable (half-open probe in progress)');
  }

  let attempt = 0;
  let refreshed = false;

  while (attempt <= RETRY_COUNT) {
    const requestKey = getRequestKey(method, path, options.body);
    const existingPending = pendingRequests.get(requestKey);
    if (existingPending) {
      existingPending.abortController.abort();
      pendingRequests.delete(requestKey);
    }

    const abortController = new AbortController();
    let timedOut = false;
    const startedAt = Date.now();
    const timeoutMs = options.timeoutMs ?? REQUEST_TIMEOUT_MS;
    pendingRequests.set(requestKey, { abortController, startedAt });

    if (pendingRequests.size > PENDING_ALERT_THRESHOLD) {
      console.warn('[apiClient] Pending request count exceeded threshold', { pendingCount: pendingRequests.size });
    }

    try {
      const session = getAdminSession();
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      };

      if (!options.skipAuth && session.accessToken) {
        headers.Authorization = `Bearer ${session.accessToken}`;
      }
      if (!options.skipAuth && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
        headers['X-CSRF-Token'] = session.csrfToken;
      }

      const response = await withTimeout(
        fetch(`${API_BASE_URL}${path}`, {
          method,
          headers,
          body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
          signal: abortController.signal,
        }),
        timeoutMs,
        () => {
          timedOut = true;
          abortController.abort();
        },
        () => normalizeError(504, `Request timed out after ${timeoutMs}ms`),
      );

      if (response.status === 401 && !options.skipAuth && !refreshed && path !== endpoints.auth.refresh) {
        refreshed = true;
        await refreshToken();
        pendingRequests.delete(requestKey);
        continue;
      }

      const parsed = await parseResponse<T>(response);
      const latencyMs = Date.now() - startedAt;
      if (latencyMs > SLOW_REQUEST_LOG_MS) {
        console.warn('[apiClient] Slow request detected', { method, path, latencyMs });
      }

      pendingRequests.delete(requestKey);
      recordSuccess();
      return parsed;
    } catch (error) {
      pendingRequests.delete(requestKey);

      if ((error as Error)?.name === 'AbortError') {
        if (!timedOut) {
          throw normalizeError(499, 'Request superseded by a newer action');
        }

        const timeoutMsg = timedOut
          ? `Request timed out after ${timeoutMs}ms`
          : 'Request aborted due to deduplication';
        const timeoutError = normalizeError(504, timeoutMsg);
        recordFailure();
        throw timeoutError;
      }

      const apiError = error as ApiError;
      recordFailure();

      if (!apiError.retriable || attempt >= RETRY_COUNT) {
        throw apiError;
      }

      // Use jittered exponential backoff
      const delay = getRetryDelay(attempt);
      if (import.meta.env.DEV) {
        console.log(`[apiClient] Retrying in ${delay.toFixed(0)}ms (attempt ${attempt + 1}/${RETRY_COUNT})`);
      }
      await sleep(delay);
      attempt += 1;
    }
  }

  throw normalizeError(500, 'Unknown request failure');
}

export function getApiClientHealth() {
  return {
    breaker: {
      state: breakerState.state,
      failures: breakerState.failures,
      openedAt: breakerState.openedAt,
    },
    pendingCount: pendingRequests.size,
  };
}

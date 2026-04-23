import { getAdminSession } from '../utils/adminSession';
import { refreshAdminToken } from './adminAuthApi';

function resolveApiBaseUrl() {
  const raw = import.meta.env.VITE_API_BASE_URL;
  if (!raw) return ''; // In dev use Vite proxy — avoids CORS
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
const REQUEST_TIMEOUT_MS = 5000;
const MAX_RETRY = 2;
const pendingRequests = new Map();

function requestKey(method, path, body) {
  return `${method}:${path}:${body || ''}`;
}

function withTimeout(promise, timeoutMs, onTimeout) {
  let timer = 0;
  const timeoutPromise = new Promise((_, reject) => {
    timer = window.setTimeout(() => {
      onTimeout?.();
      reject(new Error(`Request timeout after ${timeoutMs}ms`));
    }, timeoutMs);
  });
  return Promise.race([promise, timeoutPromise]).finally(() => {
    if (timer) window.clearTimeout(timer);
  });
}

function buildQuery(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      query.append(key, String(value));
    }
  });
  return query.toString();
}

async function authedFetch(path, options = {}, retried = false, attempt = 0) {
  const session = getAdminSession();
  const method = (options.method || 'GET').toUpperCase();
  const key = requestKey(method, path, options.body);

  const existing = pendingRequests.get(key);
  if (existing) {
    existing.abort();
    pendingRequests.delete(key);
  }

  const controller = new AbortController();
  pendingRequests.set(key, controller);

  const headers = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${session.accessToken}`,
    ...(options.headers || {}),
  };

  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    headers['X-CSRF-Token'] = session.csrfToken;
  }

  let response;
  try {
    response = await withTimeout(
      fetch(`${API_BASE_URL}${path}`, { 
        ...options, 
        headers, 
        credentials: 'include',  // Include cookies for cross-origin requests
        signal: controller.signal 
      }),
      REQUEST_TIMEOUT_MS,
      () => controller.abort(),
    );
  } catch (error) {
    pendingRequests.delete(key);
    if (attempt < MAX_RETRY) {
      return authedFetch(path, options, retried, attempt + 1);
    }
    throw error;
  }

  pendingRequests.delete(key);

  if (response.status === 401 && !retried) {
    await refreshAdminToken();
    return authedFetch(path, options, true, attempt);
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (attempt < MAX_RETRY && response.status >= 500) {
      return authedFetch(path, options, retried, attempt + 1);
    }
    throw new Error(body.detail || body.message || `HTTP ${response.status}`);
  }

  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return response.json();
  }
  return response.text();
}

export function fetchFeedback(params) {
  const query = buildQuery(params);
  const suffix = query ? `?${query}` : '';
  return authedFetch(`/api/admin/feedback${suffix}`);
}

export function updateFeedbackStatus(feedbackId, payload) {
  return authedFetch(`/api/admin/feedback/${feedbackId}/status`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function assignFeedbackReviewer(feedbackId, reviewer) {
  return authedFetch(`/api/admin/feedback/${feedbackId}/reviewer`, {
    method: 'PATCH',
    body: JSON.stringify({ reviewer }),
  });
}

export function archiveFeedback(feedbackId) {
  return authedFetch(`/api/admin/feedback/${feedbackId}/archive`, {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

export function deleteFeedback(feedbackId) {
  return authedFetch(`/api/admin/feedback/${feedbackId}`, {
    method: 'DELETE',
  });
}

export async function exportFeedbackCsv(params) {
  const query = buildQuery(params);
  const suffix = query ? `?${query}` : '';
  return authedFetch(`/api/admin/feedback/export/csv${suffix}`);
}

export async function submitUserFeedback(payload) {
  const submitCandidates = ['/api/feedback/submit', '/api/v1/feedback/submit'];
  let lastError = null;

  for (const path of submitCandidates) {
    const controller = new AbortController();
    try {
      const response = await withTimeout(
        fetch(`${API_BASE_URL}${path}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(payload),
          signal: controller.signal,
        }),
        REQUEST_TIMEOUT_MS,
        () => controller.abort(),
      );

      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(data.detail || data.message || `HTTP ${response.status}`);
        // Try alternative endpoint aliases for 404/405 compatibility drift.
        if (response.status === 404 || response.status === 405) {
          lastError = error;
          continue;
        }
        throw error;
      }

      return data;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error('Feedback submit failed');
    }
  }

  throw lastError || new Error('Feedback submit endpoint not available');
}

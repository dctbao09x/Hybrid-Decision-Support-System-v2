// src/services/crawlerApi.js
/**
 * Crawler API (Admin Only)
 * Used by Admin Crawlers panel
 */

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const CRAWLER_BASE = `${API_BASE_URL}/api/v1/crawlers`;

// ═══════════════════════════════════════════════════════════════════
// HELPER FUNCTIONS
// ═══════════════════════════════════════════════════════════════════

async function request(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    credentials: 'include',  // Include cookies for cross-origin requests
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  
  return response.json();
}

// ═══════════════════════════════════════════════════════════════════
// CRAWLER API EXPORT
// ═══════════════════════════════════════════════════════════════════

export const crawlerApi = {
  // List all crawlers
  list: () => request(CRAWLER_BASE),
  
  // Get crawler status
  getStatus: (crawlerId) => request(`${CRAWLER_BASE}/${crawlerId}/status`),
  
  // Start crawl
  start: (crawlerId, config = {}) => request(`${CRAWLER_BASE}/${crawlerId}/start`, {
    method: 'POST',
    body: JSON.stringify(config),
  }),
  
  // Stop crawl
  stop: (crawlerId) => request(`${CRAWLER_BASE}/${crawlerId}/stop`, {
    method: 'POST',
  }),
  
  // Get crawl history
  getHistory: (crawlerId, params = {}) => {
    const queryParams = new URLSearchParams(params).toString();
    return request(`${CRAWLER_BASE}/${crawlerId}/history${queryParams ? `?${queryParams}` : ''}`);
  },
  
  // Get crawl logs
  getLogs: (crawlerId, runId) => request(`${CRAWLER_BASE}/${crawlerId}/runs/${runId}/logs`),
  
  // Get crawler metrics
  getMetrics: () => request(`${CRAWLER_BASE}/metrics`),
  
  // Update crawler config
  updateConfig: (crawlerId, config) => request(`${CRAWLER_BASE}/${crawlerId}/config`, {
    method: 'PUT',
    body: JSON.stringify(config),
  }),
};

export default crawlerApi;

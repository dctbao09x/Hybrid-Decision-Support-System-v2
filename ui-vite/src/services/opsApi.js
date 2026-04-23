// src/services/opsApi.js
/**
 * Operations API (Admin Only)
 * Used by Admin Ops panel
 */

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const OPS_BASE = `${API_BASE_URL}/api/v1/ops`;

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
// OPS API EXPORT
// ═══════════════════════════════════════════════════════════════════

export const opsApi = {
  // Health & Status
  getHealth: () => request(`${OPS_BASE}/health`),
  getStatus: () => request(`${OPS_BASE}/status`),
  getMetrics: () => request(`${OPS_BASE}/metrics`),
  
  // Services
  listServices: () => request(`${OPS_BASE}/services`),
  getServiceStatus: (serviceName) => request(`${OPS_BASE}/services/${serviceName}/status`),
  restartService: (serviceName) => request(`${OPS_BASE}/services/${serviceName}/restart`, {
    method: 'POST',
  }),
  
  // Logs
  getLogs: (params = {}) => {
    const queryParams = new URLSearchParams(params).toString();
    return request(`${OPS_BASE}/logs${queryParams ? `?${queryParams}` : ''}`);
  },
  
  // Cache
  getCacheStats: () => request(`${OPS_BASE}/cache/stats`),
  clearCache: (cacheType) => request(`${OPS_BASE}/cache/${cacheType}/clear`, {
    method: 'POST',
  }),
  
  // Feature Flags
  getFeatureFlags: () => request(`${OPS_BASE}/features`),
  updateFeatureFlag: (flagName, enabled) => request(`${OPS_BASE}/features/${flagName}`, {
    method: 'PUT',
    body: JSON.stringify({ enabled }),
  }),
  
  // System Info
  getSystemInfo: () => request(`${OPS_BASE}/system/info`),
  getResourceUsage: () => request(`${OPS_BASE}/system/resources`),
  
  // Kill Switch
  getKillSwitchStatus: () => request(`${API_BASE_URL}/api/v1/kill-switch/status`),
  activateKillSwitch: (reason) => request(`${API_BASE_URL}/api/v1/kill-switch/activate`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  }),
  deactivateKillSwitch: () => request(`${API_BASE_URL}/api/v1/kill-switch/deactivate`, {
    method: 'POST',
  }),
};

export default opsApi;

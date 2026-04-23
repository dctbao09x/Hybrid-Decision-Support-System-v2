// src/services/governanceApi.js
/**
 * Governance API (Admin Only)
 * Used by Admin Governance panel
 */

function resolveApiBaseUrl() {
  const raw = import.meta.env.VITE_API_BASE_URL;
  if (!raw) return ''; // In dev use Vite proxy — avoids CORS
  try {
    const parsed = new URL(raw);
    if (parsed.hostname === 'localhost') parsed.hostname = '127.0.0.1';
    return parsed.toString().replace(/\/$/, '');
  } catch {
    return '';
  }
}

const API_BASE_URL = resolveApiBaseUrl();
const GOVERNANCE_BASE = `${API_BASE_URL}/api/v1/governance`;

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
// GOVERNANCE API EXPORT
// ═══════════════════════════════════════════════════════════════════

export const governanceApi = {
  // Legacy compatibility alias used by current Governance page
  getDashboard: () => request(`${GOVERNANCE_BASE}/dashboard`),

  // SLA Management
  getSLAStatus: () => request(`${GOVERNANCE_BASE}/sla/status`),
  getSLAHistory: (params = {}) => {
    const queryParams = new URLSearchParams(params).toString();
    return request(`${GOVERNANCE_BASE}/sla/history${queryParams ? `?${queryParams}` : ''}`);
  },
  updateSLAThresholds: (thresholds) => request(`${GOVERNANCE_BASE}/sla/thresholds`, {
    method: 'PUT',
    body: JSON.stringify(thresholds),
  }),
  
  // Drift Detection
  // getDrift(): returns the full drift dashboard (used by DriftTab)
  getDrift: () => request(`${GOVERNANCE_BASE}/drift`),
  getDriftStatus: () => request(`${GOVERNANCE_BASE}/drift/status`),
  getDriftHistory: (params = {}) => {
    const queryParams = new URLSearchParams(params).toString();
    return request(`${GOVERNANCE_BASE}/drift/history${queryParams ? `?${queryParams}` : ''}`);
  },
  triggerDriftCheck: () => request(`${GOVERNANCE_BASE}/drift/check`, { method: 'POST' }),

  // Audit Logs
  // getAuditLog(): returns { audit_entries: [...] } (used by AuditTab and AlertsTab)
  getAuditLog: (params = {}) => {
    const queryParams = new URLSearchParams(params).toString();
    return request(`${GOVERNANCE_BASE}/audit${queryParams ? `?${queryParams}` : ''}`);
  },
  getAuditLogs: (params = {}) => {
    const queryParams = new URLSearchParams(params).toString();
    return request(`${GOVERNANCE_BASE}/audit/logs${queryParams ? `?${queryParams}` : ''}`);
  },
  getAuditStats: () => request(`${GOVERNANCE_BASE}/audit/stats`),

  // SLA (extended)
  getSLAViolations: (params = {}) => {
    const queryParams = new URLSearchParams(params).toString();
    return request(`${GOVERNANCE_BASE}/sla/violations${queryParams ? `?${queryParams}` : ''}`);
  },
  getSLACompliance: () => request(`${GOVERNANCE_BASE}/sla/compliance`),
  getSLAContracts: () => request(`${GOVERNANCE_BASE}/sla/contracts`),

  // Reports
  generateReport: (payload) => request(`${GOVERNANCE_BASE}/reports/generate`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  getReports: () => request(`${GOVERNANCE_BASE}/reports`),
  getWeeklyReport: () => request(`${GOVERNANCE_BASE}/reports/weekly`),
  getMonthlyReport: () => request(`${GOVERNANCE_BASE}/reports/monthly`),

  // Alerts
  getAlerts: (params = {}) => {
    const queryParams = new URLSearchParams(params).toString();
    return request(`${GOVERNANCE_BASE}/alerts${queryParams ? `?${queryParams}` : ''}`);
  },
  acknowledgeAlert: (alertId) => request(`${GOVERNANCE_BASE}/alerts/${alertId}/ack`, {
    method: 'POST',
  }),
  resolveAlert: (alertId, resolution) => request(`${GOVERNANCE_BASE}/alerts/${alertId}/resolve`, {
    method: 'POST',
    body: JSON.stringify({ resolution }),
  }),

  // Weight Governance
  getWeightHistory: () => request(`${GOVERNANCE_BASE}/weights/history`),
  getCurrentWeights: () => request(`${GOVERNANCE_BASE}/weights/current`),
  proposeWeightChange: (proposal) => request(`${GOVERNANCE_BASE}/weights/propose`, {
    method: 'POST',
    body: JSON.stringify(proposal),
  }),
  approveWeightChange: (proposalId) => request(`${GOVERNANCE_BASE}/weights/${proposalId}/approve`, {
    method: 'POST',
  }),
  rejectWeightChange: (proposalId, reason) => request(`${GOVERNANCE_BASE}/weights/${proposalId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  }),

  // Model Governance
  getModelVersions: () => request(`${GOVERNANCE_BASE}/models`),
  getModelStatus: (version) => request(`${GOVERNANCE_BASE}/models/${version}/status`),
};

export default governanceApi;

// src/services/kbApi.js
/**
 * Knowledge Base API (Admin Only)
 * Used by Admin KnowledgeBase panels
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
const KB_BASE = `${API_BASE_URL}/api/v1`;

// ═══════════════════════════════════════════════════════════════════
// HELPER FUNCTIONS
// ═══════════════════════════════════════════════════════════════════

/**
 * Build a URLSearchParams string, skipping null/undefined/empty-string values.
 * Prevents issues like `domain_id=undefined` reaching the backend and causing 422.
 */
function buildQuery(params = {}) {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    q.append(key, String(value));
  }
  return q.toString();
}

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
// CAREER API
// ═══════════════════════════════════════════════════════════════════

export async function listCareers(params = {}) {
  const queryParams = buildQuery(params);
  return request(`${KB_BASE}/kb/careers${queryParams ? `?${queryParams}` : ''}`);
}

export async function getCareer(id) {
  return request(`${KB_BASE}/kb/careers/${id}`);
}

export async function createCareer(data) {
  return request(`${KB_BASE}/kb/careers`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateCareer(id, data) {
  return request(`${KB_BASE}/kb/careers/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteCareer(id) {
  return request(`${KB_BASE}/kb/careers/${id}`, {
    method: 'DELETE',
  });
}

// ═══════════════════════════════════════════════════════════════════
// SKILL API
// ═══════════════════════════════════════════════════════════════════

export async function listSkills(params = {}) {
  const queryParams = buildQuery(params);
  return request(`${KB_BASE}/kb/skills${queryParams ? `?${queryParams}` : ''}`);
}

export async function getSkill(id) {
  return request(`${KB_BASE}/kb/skills/${id}`);
}

export async function createSkill(data) {
  return request(`${KB_BASE}/kb/skills`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateSkill(id, data) {
  return request(`${KB_BASE}/kb/skills/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteSkill(id) {
  return request(`${KB_BASE}/kb/skills/${id}`, {
    method: 'DELETE',
  });
}

// ═══════════════════════════════════════════════════════════════════
// TEMPLATE API
// ═══════════════════════════════════════════════════════════════════

export async function listTemplates(params = {}) {
  const queryParams = buildQuery(params);
  return request(`${KB_BASE}/kb/templates${queryParams ? `?${queryParams}` : ''}`);
}

export async function getTemplate(id) {
  return request(`${KB_BASE}/kb/templates/${id}`);
}

export async function createTemplate(data) {
  return request(`${KB_BASE}/kb/templates`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateTemplate(id, data) {
  return request(`${KB_BASE}/kb/templates/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteTemplate(id) {
  return request(`${KB_BASE}/kb/templates/${id}`, {
    method: 'DELETE',
  });
}

// ═══════════════════════════════════════════════════════════════════
// ONTOLOGY API
// ═══════════════════════════════════════════════════════════════════

export async function getOntologyTree() {
  return request(`${KB_BASE}/kb/ontology/tree`);
}

export async function createOntologyNode(data) {
  return request(`${KB_BASE}/kb/ontology/nodes`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateOntologyNode(id, data) {
  return request(`${KB_BASE}/kb/ontology/nodes/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteOntologyNode(id) {
  return request(`${KB_BASE}/kb/ontology/nodes/${id}`, {
    method: 'DELETE',
  });
}

// ═══════════════════════════════════════════════════════════════════
// BULK IMPORT API
// ═══════════════════════════════════════════════════════════════════

export async function bulkImport(entityType, data, options = {}) {
  return request(`${KB_BASE}/kb/import`, {
    method: 'POST',
    body: JSON.stringify({
      entity_type: entityType,
      data,
      dry_run: options.dryRun ?? false,
      skip_duplicates: options.skipDuplicates ?? true,
    }),
  });
}

export async function bulkExport(entityType, params = {}) {
  const queryParams = buildQuery({ entity_type: entityType, ...params });
  return request(`${KB_BASE}/kb/export?${queryParams}`);
}

// ═══════════════════════════════════════════════════════════════════
// STATS API
// ═══════════════════════════════════════════════════════════════════

export async function getKBStats() {
  return request(`${KB_BASE}/kb/stats`);
}

// ═══════════════════════════════════════════════════════════════════
// LEGACY COMPATIBILITY HELPERS (used by current Admin pages)
// ═══════════════════════════════════════════════════════════════════

export async function listDomains(params = {}) {
  const queryParams = buildQuery(params);
  return request(`${KB_BASE}/kb/domains${queryParams ? `?${queryParams}` : ''}`);
}

export async function getEntityHistory(entityType, entityId) {
  return request(`${KB_BASE}/kb/history/${entityType}/${entityId}`);
}

export async function rollbackEntity(entityType, entityId, targetVersion) {
  const queryParams = new URLSearchParams({ target_version: String(targetVersion) }).toString();
  return request(`${KB_BASE}/kb/rollback/${entityType}/${entityId}?${queryParams}`, {
    method: 'POST',
  });
}

export async function getOntologyRoots() {
  return request(`${KB_BASE}/kb/ontology/roots`);
}

export async function listOntologyNodes(params = {}) {
  const queryParams = buildQuery(params);
  return request(`${KB_BASE}/kb/ontology${queryParams ? `?${queryParams}` : ''}`);
}

export async function getOntologyChildren(nodeId) {
  return request(`${KB_BASE}/kb/ontology/${nodeId}/children`);
}

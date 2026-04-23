import { clearAdminSession, getAdminSession, saveAdminSession } from '../utils/adminSession';

function resolveApiBaseUrl() {
  const raw = import.meta.env.VITE_API_BASE_URL;
  if (!raw) {
    // In dev, use same-origin via Vite proxy (/api → http://127.0.0.1:8000)
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

async function parseJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || data.message || `HTTP ${response.status}`);
  }
  return data;
}

export async function adminLogin(username, password) {
  const response = await fetch(`${API_BASE_URL}/api/admin/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',  // Include cookies for cross-origin requests
    body: JSON.stringify({ username, password }),
  });
  const data = await parseJson(response);
  saveAdminSession(data);
  return data;
}

export async function refreshAdminToken() {
  const { refreshToken } = getAdminSession();
  if (!refreshToken) throw new Error('Missing refresh token');
  const response = await fetch(`${API_BASE_URL}/api/admin/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',  // Include cookies for cross-origin requests
    body: JSON.stringify({ refreshToken }),
  });
  const data = await parseJson(response);
  saveAdminSession(data);
  return data;
}

export async function adminLogout() {
  const { refreshToken } = getAdminSession();
  if (refreshToken) {
    await fetch(`${API_BASE_URL}/api/admin/logout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',  // Include cookies for cross-origin requests
      body: JSON.stringify({ refreshToken }),
    }).catch(() => undefined);
  }
  clearAdminSession();
}

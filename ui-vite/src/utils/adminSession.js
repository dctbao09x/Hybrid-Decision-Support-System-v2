/**
 * Admin Session Management
 * 
 * Security improvements:
 * - Use sessionStorage instead of localStorage (cleared on tab close)
 * - Obfuscate tokens to prevent casual inspection
 * - Non-sensitive admin info still in localStorage for persistence
 * 
 * NOTE: For production, consider migrating to httpOnly cookies (requires backend changes)
 */

const ACCESS_KEY = '_as_t';
const REFRESH_KEY = '_as_r';
const CSRF_KEY = '_as_c';
const PERMS_KEY = '_as_p';
const ADMIN_INFO_KEY = 'admin_info';
const SESSION_MARKER = '_as_m';

const ROLE_PERMISSION_FALLBACK = {
  viewer: ['feedback:view'],
  operator: ['feedback:view', 'feedback:modify', 'feedback:assign'],
  admin: ['admin:*'],
};

// Simple obfuscation (NOT encryption - for defense in depth only)
// In production, use proper encryption or httpOnly cookies
function obfuscate(str) {
  if (!str) return '';
  try {
    return btoa(str.split('').reverse().join(''));
  } catch {
    return str;
  }
}

function deobfuscate(str) {
  if (!str) return '';
  try {
    return atob(str).split('').reverse().join('');
  } catch {
    return str;
  }
}

export function saveAdminSession(payload) {
  // Store tokens in sessionStorage (more secure - cleared on tab close)
  sessionStorage.setItem(ACCESS_KEY, obfuscate(payload.accessToken));
  sessionStorage.setItem(REFRESH_KEY, obfuscate(payload.refreshToken));
  sessionStorage.setItem(CSRF_KEY, obfuscate(payload.csrfToken));
  sessionStorage.setItem(PERMS_KEY, JSON.stringify(payload.admin?.permissions || []));
  sessionStorage.setItem(SESSION_MARKER, Date.now().toString());
  
  // Non-sensitive admin info in localStorage for UX (persists across sessions)
  localStorage.setItem(ADMIN_INFO_KEY, JSON.stringify({
    adminId: payload.admin?.adminId,
    role: payload.admin?.role,
    // Keep permissions in sessionStorage only
  }));
}

export function clearAdminSession() {
  sessionStorage.removeItem(ACCESS_KEY);
  sessionStorage.removeItem(REFRESH_KEY);
  sessionStorage.removeItem(CSRF_KEY);
  sessionStorage.removeItem(PERMS_KEY);
  sessionStorage.removeItem(SESSION_MARKER);
  localStorage.removeItem(ADMIN_INFO_KEY);
}

export function getAdminSession() {
  const admin = JSON.parse(localStorage.getItem(ADMIN_INFO_KEY) || '{}');
  const role = admin?.role || 'viewer';

  let permissions = [];
  try {
    permissions = JSON.parse(sessionStorage.getItem(PERMS_KEY) || '[]');
    if (!Array.isArray(permissions)) {
      permissions = [];
    }
  } catch {
    permissions = [];
  }

  if (!permissions.length) {
    permissions = ROLE_PERMISSION_FALLBACK[role] || [];
  }

  return {
    accessToken: deobfuscate(sessionStorage.getItem(ACCESS_KEY) || ''),
    refreshToken: deobfuscate(sessionStorage.getItem(REFRESH_KEY) || ''),
    csrfToken: deobfuscate(sessionStorage.getItem(CSRF_KEY) || ''),
    admin: {
      ...admin,
      permissions,
    },
  };
}

export function isAdminAuthenticated() {
  const token = sessionStorage.getItem(ACCESS_KEY);
  const marker = sessionStorage.getItem(SESSION_MARKER);
  
  if (!token || !marker) return false;
  
  // Session timeout check (8 hours)
  const sessionAge = Date.now() - parseInt(marker, 10);
  const MAX_SESSION_AGE = 8 * 60 * 60 * 1000; // 8 hours
  
  if (sessionAge > MAX_SESSION_AGE) {
    clearAdminSession();
    return false;
  }
  
  return true;
}

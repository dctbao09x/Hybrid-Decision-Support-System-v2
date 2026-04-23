import { useState, useEffect, useCallback } from 'react';
import { ModuleWorkspace } from '../../shared/ModuleWorkspace';
import { useAdminStore } from '../../store/AdminStoreProvider';
import { getAdminSession, clearAdminSession } from '../../../utils/adminSession';

// ─── Types ────────────────────────────────────────────────────────────────────
interface UiPrefs {
  compactMode: boolean;
  stickyToasts: boolean;
  themeIntensity: 'dim' | 'normal' | 'bright';
  autoRefreshInterval: number; // seconds, 0 = disable
}

const PREFS_KEY = 'admin_ui_prefs';
const DEFAULT_PREFS: UiPrefs = {
  compactMode: false,
  stickyToasts: false,
  themeIntensity: 'normal',
  autoRefreshInterval: 30,
};

function loadPrefs(): UiPrefs {
  try {
    return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREFS_KEY) || '{}') };
  } catch {
    return DEFAULT_PREFS;
  }
}
function savePrefs(p: UiPrefs) {
  localStorage.setItem(PREFS_KEY, JSON.stringify(p));
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function sessionAge(markerMs: number | null): string {
  if (!markerMs) return '—';
  const ms = Date.now() - markerMs;
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function maskToken(tok: string): string {
  if (!tok) return '—';
  return tok.slice(0, 8) + '…' + tok.slice(-6);
}

// ─── Sub-sections ─────────────────────────────────────────────────────────────

function ProfileSection() {
  const { authState } = useAdminStore();
  const session = getAdminSession();
  const admin = authState.admin;

  return (
    <div className="settings-section">
      <div className="settings-row">
        <span className="settings-label">Admin ID</span>
        <span className="settings-value">{admin?.adminId ?? '—'}</span>
      </div>
      <div className="settings-row">
        <span className="settings-label">Role</span>
        <span className="settings-value">
          <span className={`settings-role-badge settings-role-${admin?.role ?? 'viewer'}`}>
            {admin?.role ?? 'viewer'}
          </span>
        </span>
      </div>
      <div className="settings-row settings-row--top">
        <span className="settings-label">Permissions</span>
        <div className="settings-perm-list">
          {(admin?.permissions ?? session.admin?.permissions ?? []).length === 0
            ? <span className="settings-dim">No permissions</span>
            : (admin?.permissions ?? session.admin?.permissions ?? []).map((perm) => (
                <span key={perm} className="settings-perm-chip">{perm}</span>
              ))}
        </div>
      </div>
    </div>
  );
}

function SecuritySection() {
  const { pushNotification } = useAdminStore();
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const markerRaw = sessionStorage.getItem('_as_m');
  const markerMs = markerRaw ? parseInt(markerRaw, 10) : null;
  const session = getAdminSession();
  const expiryMs = markerMs ? markerMs + 8 * 3_600_000 : null;

  const handleRefreshToken = useCallback(async () => {
    const rf = session.refreshToken;
    if (!rf) {
      pushNotification({ level: 'error', message: 'No refresh token found — please log in again.' });
      return;
    }
    setBusy(true);
    try {
      const res = await fetch('/api/admin/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refreshToken: rf }),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      pushNotification({ level: 'success', message: 'Access token refreshed successfully.' });
    } catch (e) {
      pushNotification({ level: 'error', message: `Token refresh failed: ${(e as Error).message}` });
    } finally {
      setBusy(false);
    }
  }, [session.refreshToken, pushNotification]);

  const handleLogout = useCallback(async () => {
    const rf = session.refreshToken;
    setBusy(true);
    try {
      if (rf) {
        await fetch('/api/admin/logout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refreshToken: rf }),
        });
      }
    } finally {
      clearAdminSession();
      window.location.href = '/admin/login';
    }
  }, [session.refreshToken]);

  const handleCopyToken = useCallback(async () => {
    const tok = session.accessToken;
    if (!tok) return;
    await navigator.clipboard.writeText(tok).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [session.accessToken]);

  return (
    <div className="settings-section">
      <div className="settings-row">
        <span className="settings-label">Session age</span>
        <span className="settings-value">{sessionAge(markerMs)}</span>
      </div>
      <div className="settings-row">
        <span className="settings-label">Session expires</span>
        <span className="settings-value">
          {expiryMs ? new Date(expiryMs).toLocaleTimeString() : '—'}
        </span>
      </div>
      <div className="settings-row">
        <span className="settings-label">Access token</span>
        <span className="settings-value settings-mono">
          {maskToken(session.accessToken)}
          {session.accessToken && (
            <button className="settings-inline-btn" onClick={handleCopyToken}>
              {copied ? 'Copied!' : 'Copy'}
            </button>
          )}
        </span>
      </div>
      <div className="settings-row">
        <span className="settings-label">Refresh token</span>
        <span className="settings-value settings-mono">{maskToken(session.refreshToken)}</span>
      </div>
      <div className="settings-row settings-row--top">
        <span className="settings-label">Actions</span>
        <div className="settings-actions">
          <button className="ops-action-btn" disabled={busy} onClick={handleRefreshToken}>
            {busy ? 'Refreshing…' : 'Refresh token'}
          </button>
          <button className="ops-action-btn ops-btn-danger" disabled={busy} onClick={handleLogout}>
            Logout &amp; revoke session
          </button>
        </div>
      </div>
    </div>
  );
}

function PreferencesSection() {
  const { pushNotification } = useAdminStore();
  const [prefs, setPrefs] = useState<UiPrefs>(loadPrefs);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    // Apply compact mode to body class
    document.body.classList.toggle('admin-compact', prefs.compactMode);
  }, [prefs.compactMode]);

  const update = useCallback(<K extends keyof UiPrefs>(key: K, val: UiPrefs[K]) => {
    setPrefs((prev) => ({ ...prev, [key]: val }));
    setSaved(false);
  }, []);

  const handleSave = () => {
    savePrefs(prefs);
    setSaved(true);
    document.body.classList.toggle('admin-compact', prefs.compactMode);
    pushNotification({ level: 'success', message: 'UI preferences saved.' });
    setTimeout(() => setSaved(false), 2000);
  };

  const handleReset = () => {
    setPrefs(DEFAULT_PREFS);
    savePrefs(DEFAULT_PREFS);
    document.body.classList.remove('admin-compact');
    pushNotification({ level: 'info', message: 'Preferences reset to defaults.' });
  };

  return (
    <div className="settings-section">
      <div className="settings-row settings-row--field">
        <label className="settings-label settings-label--for">
          <input
            type="checkbox"
            className="settings-checkbox"
            checked={prefs.compactMode}
            onChange={(e) => update('compactMode', e.target.checked)}
          />
          Compact mode
        </label>
        <span className="settings-dim">Reduce padding and font sizes across the admin UI</span>
      </div>

      <div className="settings-row settings-row--field">
        <label className="settings-label settings-label--for">
          <input
            type="checkbox"
            className="settings-checkbox"
            checked={prefs.stickyToasts}
            onChange={(e) => update('stickyToasts', e.target.checked)}
          />
          Sticky notifications
        </label>
        <span className="settings-dim">Keep toast messages visible until manually dismissed</span>
      </div>

      <div className="settings-row settings-row--field">
        <span className="settings-label">Theme intensity</span>
        <div className="settings-radio-group">
          {(['dim', 'normal', 'bright'] as const).map((v) => (
            <label key={v} className="settings-radio-label">
              <input
                type="radio"
                className="settings-radio"
                name="themeIntensity"
                value={v}
                checked={prefs.themeIntensity === v}
                onChange={() => update('themeIntensity', v)}
              />
              {v.charAt(0).toUpperCase() + v.slice(1)}
            </label>
          ))}
        </div>
      </div>

      <div className="settings-row settings-row--field">
        <span className="settings-label">Auto-refresh interval</span>
        <div className="settings-select-wrap">
          <select
            className="settings-select"
            value={prefs.autoRefreshInterval}
            onChange={(e) => update('autoRefreshInterval', Number(e.target.value))}
          >
            <option value={0}>Disabled</option>
            <option value={15}>15 seconds</option>
            <option value={30}>30 seconds</option>
            <option value={60}>1 minute</option>
            <option value={300}>5 minutes</option>
          </select>
        </div>
      </div>

      <div className="settings-row">
        <span className="settings-label" />
        <div className="settings-actions">
          <button className="ops-action-btn" onClick={handleSave}>
            {saved ? 'Saved ✓' : 'Save preferences'}
          </button>
          <button className="ops-action-btn" onClick={handleReset}>
            Reset to defaults
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────────

const TABS = [
  { key: 'profile', label: 'Profile' },
  { key: 'security', label: 'Security & Session' },
  { key: 'preferences', label: 'UI Preferences' },
] as const;
type TabKey = typeof TABS[number]['key'];

export function SettingsWorkspace() {
  const [activeTab, setActiveTab] = useState<TabKey>('profile');

  return (
    <ModuleWorkspace title="Admin Settings" subtitle="Security, profile, and workspace preferences">
      <div className="settings-workspace">
        <nav className="settings-tabs">
          {TABS.map((t) => (
            <button
              key={t.key}
              className={`settings-tab-btn${activeTab === t.key ? ' settings-tab-btn--active' : ''}`}
              onClick={() => setActiveTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className="settings-panel">
          {activeTab === 'profile' && <ProfileSection />}
          {activeTab === 'security' && <SecuritySection />}
          {activeTab === 'preferences' && <PreferencesSection />}
        </div>
      </div>
    </ModuleWorkspace>
  );
}

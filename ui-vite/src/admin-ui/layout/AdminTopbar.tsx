import type { SystemHealth } from '../types';

interface AdminTopbarProps {
  health: SystemHealth;
  alertCount: number;
  adminName: string;
  darkMode: boolean;
  onToggleDarkMode: () => void;
  onOpenSearch: () => void;
}

export function AdminTopbar({
  health,
  alertCount,
  adminName,
  darkMode,
  onToggleDarkMode,
  onOpenSearch,
}: AdminTopbarProps) {
  return (
    <header className="admin-topbar">
      <div className="admin-topbar-left">
        <button type="button" onClick={onOpenSearch}>⌘K Search</button>
        <span className={`status-badge status-${health.status}`}>System: {health.status}</span>
      </div>
      <div className="admin-topbar-right">
        <span className="alert-badge">Alerts {alertCount}</span>
        <button type="button" onClick={onToggleDarkMode}>{darkMode ? 'Light' : 'Dark'}</button>
        <div className="admin-profile">{adminName}</div>
      </div>
    </header>
  );
}

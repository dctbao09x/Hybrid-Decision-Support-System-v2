import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { adminLogout } from '../../services/adminAuthApi';
import { getAdminSession } from '../../utils/adminSession';
import { useIdleLogout } from '../auth/useIdleLogout';
import { moduleRoutes } from '../router/moduleConfig';
import { ModuleRouter } from '../router/ModuleRouter';
import { getSystemHealth } from '../services/adminModulesApi';
import { useAdminStore } from '../store/AdminStoreProvider';
import { AdminBreadcrumb } from './AdminBreadcrumb';
import { AdminSidebar } from './AdminSidebar';
import { AdminTopbar } from './AdminTopbar';
import { GlobalSearch } from '../shared/GlobalSearch';
import { ToastCenter } from '../shared/ToastCenter';

export function AdminShell() {
  const navigate = useNavigate();
  const { authState, systemHealth, setSystemHealth, notificationQueue, pushNotification } = useAdminStore();

  const [collapsed, setCollapsed] = useState(false);
  const [darkMode, setDarkMode] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  useIdleLogout(authState.isAuthenticated);

  const adminName = useMemo(() => {
    const session = getAdminSession();
    return session.admin?.adminId || 'admin';
  }, []);

  useEffect(() => {
    const load = async () => {
      const next = await getSystemHealth();
      setSystemHealth(next);
      if (next.status === 'critical') {
        pushNotification({ level: 'error', message: 'Critical system health detected' });
      }
    };

    load();
    const interval = window.setInterval(load, 15000);
    return () => window.clearInterval(interval);
  }, [pushNotification, setSystemHealth]);

  useEffect(() => {
    const onShortcut = (event: KeyboardEvent) => {
      const isSearchKey = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k';
      if (isSearchKey) {
        event.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener('keydown', onShortcut);
    return () => window.removeEventListener('keydown', onShortcut);
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute('data-admin-theme', darkMode ? 'dark' : 'light');
  }, [darkMode]);

  const onLogout = async () => {
    await adminLogout();
    navigate('/admin/login', { replace: true });
  };

  return (
    <div className="admin-shell">
      <div className="admin-watermark">ADMIN {adminName}</div>
      <AdminSidebar collapsed={collapsed} onToggle={() => setCollapsed((prev) => !prev)} onLogout={onLogout} />
      <div className="admin-shell-main">
        <AdminTopbar
          health={systemHealth}
          alertCount={notificationQueue.length}
          adminName={adminName}
          darkMode={darkMode}
          onToggleDarkMode={() => setDarkMode((prev) => !prev)}
          onOpenSearch={() => setSearchOpen(true)}
        />
        <AdminBreadcrumb />
        <main className="admin-main-panel">
          <ModuleRouter />
        </main>
      </div>

      <GlobalSearch open={searchOpen} onClose={() => setSearchOpen(false)} routes={moduleRoutes} />
      <ToastCenter />
    </div>
  );
}

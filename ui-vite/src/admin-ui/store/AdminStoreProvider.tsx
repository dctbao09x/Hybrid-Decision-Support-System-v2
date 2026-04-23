import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { getAdminSession } from '../../utils/adminSession';
import type { AdminIdentity, AdminNotification, SystemHealth } from '../types';

interface AdminStoreContextType {
  authState: {
    isAuthenticated: boolean;
    admin: AdminIdentity | null;
  };
  permissionState: {
    permissions: string[];
  };
  systemHealth: SystemHealth;
  notificationQueue: AdminNotification[];
  setSystemHealth: (next: SystemHealth) => void;
  pushNotification: (payload: Omit<AdminNotification, 'id' | 'timestamp'>) => void;
  dismissNotification: (id: string) => void;
}

const AdminStoreContext = createContext<AdminStoreContextType | null>(null);

const defaultHealth: SystemHealth = {
  status: 'unknown',
  updatedAt: new Date().toISOString(),
  services: [],
};

export function AdminStoreProvider({ children }: { children: React.ReactNode }) {
  const session = getAdminSession();
  const admin = session?.admin?.adminId
    ? {
      adminId: session.admin.adminId,
      role: session.admin.role || 'viewer',
      permissions: session.admin.permissions || [],
    }
    : null;

  const [systemHealth, setSystemHealth] = useState<SystemHealth>(defaultHealth);
  const [notificationQueue, setNotificationQueue] = useState<AdminNotification[]>([]);

  const pushNotification = useCallback((payload: Omit<AdminNotification, 'id' | 'timestamp'>) => {
    setNotificationQueue((prev) => [
      ...prev,
      {
        ...payload,
        id: `ntf_${Math.random().toString(36).slice(2, 10)}`,
        timestamp: Date.now(),
      },
    ]);
  }, []);

  const dismissNotification = useCallback((id: string) => {
    setNotificationQueue((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const value = useMemo<AdminStoreContextType>(() => ({
    authState: {
      isAuthenticated: Boolean(session.accessToken && admin),
      admin,
    },
    permissionState: {
      permissions: admin?.permissions || [],
    },
    systemHealth,
    notificationQueue,
    setSystemHealth,
    pushNotification,
    dismissNotification,
  }), [admin, dismissNotification, notificationQueue, pushNotification, session.accessToken, systemHealth]);

  return <AdminStoreContext.Provider value={value}>{children}</AdminStoreContext.Provider>;
}

export function useAdminStore() {
  const context = useContext(AdminStoreContext);
  if (!context) {
    throw new Error('useAdminStore must be used inside AdminStoreProvider');
  }
  return context;
}

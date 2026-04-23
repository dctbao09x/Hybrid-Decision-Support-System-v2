export type ModuleKey =
  | 'dashboard'
  | 'crawlers'
  | 'feedback'
  | 'governance'
  | 'knowledgebase'
  | 'liveops'
  | 'mlops'
  | 'ops'
  | 'settings';

export interface AdminIdentity {
  adminId: string;
  role: string;
  permissions: string[];
}

export interface SystemHealth {
  status: 'healthy' | 'degraded' | 'critical' | 'unknown';
  updatedAt: string;
  services: Array<{ name: string; status: 'up' | 'down' | 'degraded' }>;
}

export interface AdminNotification {
  id: string;
  level: 'info' | 'warning' | 'error' | 'success';
  message: string;
  timestamp: number;
}

export interface ModuleRouteDef {
  key: ModuleKey;
  label: string;
  path: string;
  requiredPermissions?: string[];
}

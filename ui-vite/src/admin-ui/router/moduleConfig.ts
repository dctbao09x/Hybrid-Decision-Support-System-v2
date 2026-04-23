import type { ModuleRouteDef } from '../types';

export const moduleRoutes: ModuleRouteDef[] = [
  { key: 'dashboard', label: 'Dashboard', path: '/admin/dashboard' },
  { key: 'crawlers', label: 'Crawlers', path: '/admin/crawlers', requiredPermissions: ['crawlers:view|feedback:view'] },
  { key: 'feedback', label: 'Feedback', path: '/admin/feedback', requiredPermissions: ['feedback:view'] },
  { key: 'governance', label: 'Governance', path: '/admin/governance', requiredPermissions: ['governance:view|feedback:modify'] },
  { key: 'knowledgebase', label: 'Knowledge Base', path: '/admin/kb', requiredPermissions: ['kb:view|feedback:view'] },
  { key: 'liveops', label: 'Live Operations', path: '/admin/liveops', requiredPermissions: ['ops:view|feedback:view'] },
  { key: 'mlops', label: 'MLOps', path: '/admin/mlops', requiredPermissions: ['mlops:view|feedback:modify'] },
  { key: 'ops', label: 'Ops', path: '/admin/ops', requiredPermissions: ['ops:view|feedback:view'] },
  { key: 'settings', label: 'Settings', path: '/admin/settings' },
];

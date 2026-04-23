/**
 * Live Operations Types
 * =====================
 */

export type WidgetStatus = 'healthy' | 'warning' | 'critical' | 'unknown' | 'loading';

export interface WidgetConfig {
  id: string;
  title: string;
  refreshInterval?: number;  // ms
  alertThreshold?: number;
  drillDownPath?: string;
}

export interface BaseWidgetData {
  lastUpdate: string;
  status: WidgetStatus;
}

// System Health Widget
export interface SystemHealthData extends BaseWidgetData {
  overallStatus: WidgetStatus;
  services: Array<{
    name: string;
    status: 'up' | 'down' | 'degraded';
    latency?: number;
  }>;
  uptime: number;  // seconds
  cpuUsage?: number;
  memoryUsage?: number;
}

// Job Queue Widget
export interface JobQueueData extends BaseWidgetData {
  pending: number;
  running: number;
  completed: number;
  failed: number;
  avgWaitTime: number;  // seconds
  jobs: Array<{
    id: string;
    type: string;
    status: string;
    progress?: number;
    startedAt?: string;
  }>;
}

// Drift Monitoring Widget
export interface DriftData extends BaseWidgetData {
  currentDrift: number;  // percentage
  threshold: number;
  trend: 'increasing' | 'decreasing' | 'stable';
  history: Array<{
    timestamp: string;
    value: number;
  }>;
  alertActive: boolean;
}

// Cost Widget
export interface CostData extends BaseWidgetData {
  currentMonth: number;
  budget: number;
  forecast: number;
  breakdown: Array<{
    category: string;
    amount: number;
    percentage: number;
  }>;
  trend: 'increasing' | 'decreasing' | 'stable';
}

// SLA Widget
export interface SLAData extends BaseWidgetData {
  compliance: number;  // percentage
  target: number;
  metrics: Array<{
    name: string;
    current: number;
    target: number;
    status: 'met' | 'at_risk' | 'breached';
  }>;
  incidents: number;
}

// Error Rate Widget
export interface ErrorRateData extends BaseWidgetData {
  currentRate: number;  // percentage
  threshold: number;
  errors24h: number;
  errorsByType: Array<{
    type: string;
    count: number;
  }>;
  trend: 'increasing' | 'decreasing' | 'stable';
}

// Command Types
export interface CommandRequest {
  target: string;
  params?: Record<string, unknown>;
  idempotencyKey?: string;
  dryRun?: boolean;
  priority?: 'low' | 'normal' | 'high' | 'critical';
  timeoutSeconds?: number;
}

export interface CommandResponse {
  status: 'ok' | 'error';
  data: {
    commandId: string;
    state: string;
  };
  meta?: Record<string, unknown>;
}

// Audit Types
export interface AuditEntry {
  id: string;
  timestamp: string;
  userId: string;
  role: string;
  action: string;
  target: string;
  result: 'success' | 'failure' | 'pending';
  error?: string;
  traceId: string;
}

// Approval Types
export interface ApprovalRequest {
  id: string;
  commandId: string;
  commandType: string;
  target: string;
  requesterId: string;
  requesterRole: string;
  status: 'pending' | 'approved' | 'rejected' | 'expired';
  reason?: string;
  createdAt: string;
  expiresAt: string;
  decisions: Array<{
    approverId: string;
    decision: 'approve' | 'reject';
    comment?: string;
    timestamp: string;
  }>;
}

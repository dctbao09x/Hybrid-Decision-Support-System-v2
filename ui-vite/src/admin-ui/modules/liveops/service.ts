import { apiRequest } from '../../services/apiClient';
import type {
  CommandRequest,
  CommandResponse,
  CostData,
  DriftData,
  ErrorRateData,
  JobQueueData,
  SLAData,
  SystemHealthData,
} from './types';

const LIVEOPS_SIGNING_SECRET = (import.meta.env.VITE_LIVEOPS_SIGNING_SECRET || 'liveops-dev-secret').trim();

interface SignedFields {
  nonce: string;
  timestamp: number;
  signature: string;
}

function getSession() {
  const adminRaw = localStorage.getItem('admin_info') || '{}';
  let admin: Record<string, unknown> = {};
  try {
    admin = JSON.parse(adminRaw);
  } catch {
    admin = {};
  }
  return {
    accessToken: localStorage.getItem('admin_access_token') || '',
    csrfToken: localStorage.getItem('admin_csrf_token') || '',
    admin,
  };
}

function nowTs(): number {
  return Math.floor(Date.now() / 1000);
}

function nonce(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 14)}`;
}

async function hmacSha256Hex(message: string, secret: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw',
    enc.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const sig = await crypto.subtle.sign('HMAC', key, enc.encode(message));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function signRequest(commandType: string, target: string): Promise<SignedFields> {
  const session = getSession();
  const userId = String(session?.admin?.adminId || 'admin');
  const ts = nowTs();
  const n = nonce();
  const payload = `${userId}:${commandType}:${target}:${ts}:${n}`;
  const signature = await hmacSha256Hex(payload, LIVEOPS_SIGNING_SECRET);
  return { nonce: n, timestamp: ts, signature };
}

function mapCommandResponse(raw: any): CommandResponse {
  return {
    status: raw?.status === 'ok' ? 'ok' : 'error',
    data: {
      commandId: String(raw?.data?.command_id || raw?.data?.commandId || ''),
      state: String(raw?.data?.state || 'unknown'),
    },
    meta: raw?.meta || {},
  };
}

async function submitSignedCommand(path: string, commandType: string, body: Record<string, unknown>): Promise<CommandResponse> {
  const target = String(body.target || 'system');
  const signed = await signRequest(commandType, target);
  const payload = {
    ...body,
    ...signed,
  };
  const result = await apiRequest<any>(`/api/v1/live${path}`, { method: 'POST', body: payload });
  return mapCommandResponse(result);
}

export async function killCrawler(siteName: string, options: Partial<CommandRequest> = {}): Promise<CommandResponse> {
  return submitSignedCommand('/crawler/kill', 'crawler_kill', {
    target: options.target || siteName,
    site_name: siteName,
    force: Boolean(options.params && (options.params as any).force),
    params: options.params || {},
    idempotency_key: options.idempotencyKey,
    dry_run: Boolean(options.dryRun),
    priority: options.priority || 'normal',
    timeout_seconds: options.timeoutSeconds || 300,
  });
}

export async function pauseJob(jobId: string, options: Partial<CommandRequest> = {}): Promise<CommandResponse> {
  return submitSignedCommand('/job/pause', 'job_pause', {
    target: options.target || jobId,
    job_id: jobId,
    params: options.params || {},
    idempotency_key: options.idempotencyKey,
    dry_run: Boolean(options.dryRun),
    priority: options.priority || 'normal',
    timeout_seconds: options.timeoutSeconds || 300,
  });
}

export async function resumeJob(jobId: string, options: Partial<CommandRequest> = {}): Promise<CommandResponse> {
  return submitSignedCommand('/job/resume', 'job_resume', {
    target: options.target || jobId,
    job_id: jobId,
    params: options.params || {},
    idempotency_key: options.idempotencyKey,
    dry_run: Boolean(options.dryRun),
    priority: options.priority || 'normal',
    timeout_seconds: options.timeoutSeconds || 300,
  });
}

export async function rollbackKB(version: string, target: string, options: Partial<CommandRequest> = {}): Promise<CommandResponse> {
  return submitSignedCommand('/kb/rollback', 'kb_rollback', {
    target,
    version,
    backup_current: true,
    params: options.params || {},
    idempotency_key: options.idempotencyKey,
    dry_run: Boolean(options.dryRun),
    priority: options.priority || 'high',
    timeout_seconds: options.timeoutSeconds || 600,
  });
}

export async function freezeModel(modelId: string, reason?: string, options: Partial<CommandRequest> = {}): Promise<CommandResponse> {
  return submitSignedCommand('/mlops/freeze', 'mlops_freeze', {
    target: options.target || modelId,
    model_id: modelId,
    reason,
    params: options.params || {},
    idempotency_key: options.idempotencyKey,
    dry_run: Boolean(options.dryRun),
    priority: options.priority || 'high',
    timeout_seconds: options.timeoutSeconds || 300,
  });
}

export async function retrainModel(modelId: string, options: Partial<CommandRequest> = {}): Promise<CommandResponse> {
  return submitSignedCommand('/mlops/retrain', 'mlops_retrain', {
    target: options.target || modelId,
    model_id: modelId,
    config_override: {},
    params: options.params || {},
    idempotency_key: options.idempotencyKey,
    dry_run: Boolean(options.dryRun),
    priority: options.priority || 'normal',
    timeout_seconds: options.timeoutSeconds || 900,
  });
}

export async function getCommand(commandId: string): Promise<CommandResponse> {
  const raw = await apiRequest<any>(`/api/v1/live/commands/${commandId}`);
  return {
    status: 'ok',
    data: {
      commandId: raw.command_id || commandId,
      state: raw.state || 'unknown',
    },
    meta: raw,
  };
}

export async function listCommands(limit = 50): Promise<CommandResponse[]> {
  const rows = await apiRequest<any[]>(`/api/v1/live/commands?limit=${limit}`);
  return rows.map((row) => ({
    status: 'ok',
    data: {
      commandId: String(row.command_id || ''),
      state: String(row.state || 'unknown'),
    },
    meta: row,
  }));
}

export async function approveCommand(commandId: string, approverComment?: string): Promise<CommandResponse> {
  const raw = await apiRequest<any>(`/api/v1/live/commands/${commandId}/approve`, {
    method: 'POST',
    body: { approver_comment: approverComment || '' },
  });
  return mapCommandResponse(raw);
}

export async function getSystemHealth(): Promise<SystemHealthData> {
  return apiRequest<SystemHealthData>('/api/v1/live/widget/health');
}

export async function getJobQueue(): Promise<JobQueueData> {
  return apiRequest<JobQueueData>('/api/v1/live/widget/queue');
}

export async function getDriftMetrics(): Promise<DriftData> {
  return apiRequest<DriftData>('/api/v1/live/widget/drift');
}

export async function getCostMetrics(): Promise<CostData> {
  return apiRequest<CostData>('/api/v1/live/widget/cost');
}

export async function getSLAMetrics(): Promise<SLAData> {
  return apiRequest<SLAData>('/api/v1/live/widget/sla');
}

export async function getErrorRateMetrics(): Promise<ErrorRateData> {
  return apiRequest<ErrorRateData>('/api/v1/live/widget/errors');
}

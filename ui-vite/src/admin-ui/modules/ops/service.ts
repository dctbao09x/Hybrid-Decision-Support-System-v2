import { apiRequest } from '../../services/apiClient';

// ─── Domain types ────────────────────────────────────────────────────────────

export interface ServiceEntry {
  name: string;
  status: 'running' | 'idle' | 'error' | string;
  uptime_s: number;
}

export interface CacheEntry {
  size: number;
  hits: number;
  misses: number;
}

export interface SystemResources {
  cpu_pct: number | null;
  memory: { total_mb: number; used_mb: number; pct: number } | null;
}

export interface SystemInfo {
  python: string;
  platform: string;
  architecture: string;
  processor: string;
}

export interface OpsSnapshot {
  // core
  status: Record<string, unknown>;
  sla: Record<string, unknown>;
  alerts: unknown[];
  metrics: Record<string, unknown>;
  // extended
  health: { status: string; component: string } | null;
  systemInfo: SystemInfo | null;
  systemResources: SystemResources | null;
  services: ServiceEntry[];
  cacheStats: Record<string, CacheEntry>;
  features: Record<string, boolean>;
  recoveryStatus: Record<string, unknown>;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────
// Uses plain fetch (not apiRequest) so transient backend 503s on ops polling
// do NOT register failures in the shared admin circuit breaker.
async function opt<T>(path: string, fallback: T, timeoutMs = 4000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(path, { signal: controller.signal });
    if (!res.ok) return fallback;
    return await res.json() as T;
  } catch {
    return fallback;
  } finally {
    window.clearTimeout(timer);
  }
}

// ─── Loaders ─────────────────────────────────────────────────────────────────

export async function loadOpsSnapshot(): Promise<OpsSnapshot> {
  const [
    status, sla, alerts, metrics,
    health, systemInfo, systemResources,
    servicesResp, cacheResp, featuresResp, recoveryStatus,
  ] = await Promise.all([
    opt<Record<string, unknown>>('/api/v1/ops/status', {}),
    opt<Record<string, unknown>>('/api/v1/ops/sla', {}),
    opt<unknown[]>('/api/v1/ops/alerts', []),
    opt<Record<string, unknown>>('/api/v1/ops/metrics', {}),
    opt<{ status: string; component: string }>('/api/v1/ops/health', { status: 'unknown', component: 'ops' }),
    opt<SystemInfo | null>('/api/v1/ops/system/info', null),
    opt<SystemResources | null>('/api/v1/ops/system/resources', null),
    opt<{ services: ServiceEntry[] }>('/api/v1/ops/services', { services: [] }),
    opt<{ caches: Record<string, CacheEntry> }>('/api/v1/ops/cache/stats', { caches: {} }),
    opt<{ flags: Record<string, boolean> }>('/api/v1/ops/features', { flags: {} }),
    opt<Record<string, unknown>>('/api/v1/ops/recovery/status', {}),
  ]);

  return {
    status,
    sla,
    alerts: Array.isArray(alerts) ? alerts : [],
    metrics,
    health,
    systemInfo,
    systemResources,
    services: servicesResp.services ?? [],
    cacheStats: cacheResp.caches ?? {},
    features: featuresResp.flags ?? {},
    recoveryStatus,
  };
}

// ─── Actions ─────────────────────────────────────────────────────────────────

export async function triggerOpsBackup(label?: string): Promise<{ message?: string; error?: string }> {
  const qs = label ? `?label=${encodeURIComponent(label)}` : '';
  return apiRequest(`/api/v1/ops/backup${qs}`, { method: 'POST' });
}

export async function triggerRetention(dryRun = true): Promise<Record<string, unknown>> {
  return apiRequest(`/api/v1/ops/retention?dry_run=${dryRun}`, { method: 'POST' });
}

export async function clearOpsCache(cacheType: string): Promise<{ cleared: boolean; entries_removed: number }> {
  return apiRequest(`/api/v1/ops/cache/${cacheType}/clear`, { method: 'POST' });
}

export async function restartService(name: string): Promise<{ service: string; action: string; queued: boolean }> {
  return apiRequest(`/api/v1/ops/services/${name}/restart`, { method: 'POST' });
}

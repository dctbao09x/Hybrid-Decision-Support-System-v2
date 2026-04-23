import { useState } from 'react';
import { ModuleWorkspace } from '../../shared/ModuleWorkspace';
import type { CacheEntry, OpsSnapshot, ServiceEntry } from './service';

interface OpsViewProps {
  snapshot: OpsSnapshot;
  isLoading: boolean;
  error: string;
  actionBusy: string;
  onRefresh: () => void;
  onBackup: (label?: string) => void;
  onRetention: (dryRun: boolean) => void;
  onClearCache: (cacheType: string) => void;
  onRestartService: (name: string) => void;
}

// ─── Tiny helpers ─────────────────────────────────────────────────────────────

function healthClass(status: string) {
  if (status === 'ok' || status === 'healthy') return 'status-badge status-healthy';
  if (status === 'error' || status === 'critical') return 'status-badge status-critical';
  return 'status-badge';
}

function serviceClass(status: string) {
  if (status === 'running') return 'ops-svc-badge ops-svc-running';
  if (status === 'idle') return 'ops-svc-badge ops-svc-idle';
  return 'ops-svc-badge ops-svc-error';
}

function formatUptime(s: number) {
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

function hitRate(c: CacheEntry) {
  const total = c.hits + c.misses;
  if (!total) return '—';
  return `${Math.round((c.hits / total) * 100)}%`;
}

// ─── Sub-sections ──────────────────────────────────────────────────────────────

function ResourceBar({ label, pct, value }: { label: string; pct: number; value: string }) {
  const fill = pct > 85 ? '#ef4444' : pct > 65 ? '#f59e0b' : '#6ee7b7';
  return (
    <div className="ops-resource">
      <div className="ops-resource-header">
        <span className="admin-governance-metric-label">{label}</span>
        <span className="ops-resource-value">{value}</span>
      </div>
      <div className="ops-resource-track">
        <div className="ops-resource-fill" style={{ width: `${Math.min(pct, 100)}%`, background: fill }} />
      </div>
    </div>
  );
}

function ServicesSection({
  services,
  actionBusy,
  onRestart,
}: {
  services: ServiceEntry[];
  actionBusy: string;
  onRestart: (name: string) => void;
}) {
  if (!services.length) return <p className="ops-empty">No service data</p>;
  return (
    <div className="ops-services-grid">
      {services.map((svc) => (
        <div key={svc.name} className="ops-service-row">
          <span className={serviceClass(svc.status)}>{svc.status}</span>
          <span className="ops-service-name">{svc.name}</span>
          <span className="ops-service-uptime">{formatUptime(svc.uptime_s)}</span>
          <button
            type="button"
            className="ops-action-btn"
            disabled={actionBusy === `restart-${svc.name}`}
            onClick={() => onRestart(svc.name)}
          >
            {actionBusy === `restart-${svc.name}` ? '…' : 'Restart'}
          </button>
        </div>
      ))}
    </div>
  );
}

function FeaturesSection({ features }: { features: Record<string, boolean> }) {
  const entries = Object.entries(features);
  if (!entries.length) return <p className="ops-empty">No feature flags</p>;
  return (
    <div className="ops-flags-list">
      {entries.map(([flag, enabled]) => (
        <div key={flag} className="ops-flag-row">
          <span className={`ops-flag-dot ${enabled ? 'ops-flag-on' : 'ops-flag-off'}`} />
          <span className="ops-flag-name">{flag}</span>
          <span className={`ops-flag-label ${enabled ? 'ops-flag-on' : 'ops-flag-off'}`}>
            {enabled ? 'ON' : 'OFF'}
          </span>
        </div>
      ))}
    </div>
  );
}

function CacheSection({
  cacheStats,
  actionBusy,
  onClear,
}: {
  cacheStats: Record<string, CacheEntry>;
  actionBusy: string;
  onClear: (t: string) => void;
}) {
  const entries = Object.entries(cacheStats);
  if (!entries.length) return <p className="ops-empty">No cache data</p>;
  return (
    <div className="ops-cache-table">
      <div className="ops-cache-header">
        <span>Cache</span><span>Size</span><span>Hit%</span><span></span>
      </div>
      {entries.map(([name, c]) => (
        <div key={name} className="ops-cache-row">
          <span className="ops-cache-name">{name}</span>
          <span>{c.size}</span>
          <span>{hitRate(c)}</span>
          <button
            type="button"
            className="ops-action-btn"
            disabled={actionBusy === `cache-${name}`}
            onClick={() => onClear(name)}
          >
            {actionBusy === `cache-${name}` ? '…' : 'Clear'}
          </button>
        </div>
      ))}
    </div>
  );
}

function AlertsSection({ alerts }: { alerts: unknown[] }) {
  if (!alerts.length) return <p className="ops-empty">No active alerts</p>;
  return (
    <div className="admin-alert-list">
      {alerts.slice(0, 10).map((a, i) => (
        <div key={i} className="admin-alert-item">
          {typeof a === 'string' ? a : JSON.stringify(a)}
        </div>
      ))}
    </div>
  );
}

function SlaSection({ sla }: { sla: Record<string, unknown> }) {
  const entries = Object.entries(sla);
  if (!entries.length) return <p className="ops-empty">No SLA data</p>;
  // render key metrics as badges, rest as compact JSON
  return (
    <div className="admin-governance-metrics">
      {entries.slice(0, 8).map(([k, v]) => (
        <div key={k} className="admin-governance-metric">
          <span className="admin-governance-metric-label">{k}</span>
          <span className="admin-governance-metric-value">
            {typeof v === 'object' ? JSON.stringify(v) : String(v)}
          </span>
        </div>
      ))}
    </div>
  );
}

// ─── Main view ────────────────────────────────────────────────────────────────

export function OpsView({
  snapshot,
  isLoading,
  error,
  actionBusy,
  onRefresh,
  onBackup,
  onRetention,
  onClearCache,
  onRestartService,
}: OpsViewProps) {
  const [backupLabel, setBackupLabel] = useState('');

  const health = snapshot.health;
  const res = snapshot.systemResources;
  const info = snapshot.systemInfo;

  return (
    <ModuleWorkspace title="Ops Panel" subtitle="Infrastructure status, services, cache, SLA, alerts and maintenance actions">

      {/* ── Top toolbar ─────────────────────────────────────────── */}
      <div className="ops-toolbar">
        {health && (
          <span className={healthClass(health.status)}>
            {health.status === 'ok' ? '● healthy' : `● ${health.status}`}
          </span>
        )}
        {isLoading && <span className="ops-spinner" aria-label="Loading" />}
        <button type="button" className="admin-nav-link" onClick={onRefresh} disabled={isLoading}>
          Refresh
        </button>
        {info && (
          <span className="ops-sys-label">
            {info.platform.split(' ')[0]} · Python {info.python.split(' ')[0]}
          </span>
        )}
      </div>

      <div className="admin-grid-cards admin-grid-cards--ops">

        {/* ── System Resources ──────────────────────────────────── */}
        {res && (
          <article className="admin-card" data-testid="ops-resources-card">
            <h3>System Resources</h3>
            {res.cpu_pct != null && (
              <ResourceBar label="CPU" pct={res.cpu_pct} value={`${res.cpu_pct.toFixed(1)}%`} />
            )}
            {res.memory && (
              <ResourceBar
                label="Memory"
                pct={res.memory.pct}
                value={`${res.memory.used_mb.toFixed(0)} / ${res.memory.total_mb.toFixed(0)} MB`}
              />
            )}
          </article>
        )}

        {/* ── Services ──────────────────────────────────────────── */}
        <article className="admin-card" data-testid="ops-services-card">
          <h3>Services</h3>
          <ServicesSection
            services={snapshot.services}
            actionBusy={actionBusy}
            onRestart={onRestartService}
          />
        </article>

        {/* ── Feature Flags ─────────────────────────────────────── */}
        <article className="admin-card" data-testid="ops-features-card">
          <h3>Feature Flags</h3>
          <FeaturesSection features={snapshot.features} />
        </article>

        {/* ── SLA ───────────────────────────────────────────────── */}
        <article className="admin-card" data-testid="ops-sla-card">
          <h3>SLA Dashboard</h3>
          <SlaSection sla={snapshot.sla} />
        </article>

        {/* ── Alerts ────────────────────────────────────────────── */}
        <article className="admin-card" data-testid="ops-alerts-card">
          <h3>Incident Alerts</h3>
          <AlertsSection alerts={snapshot.alerts} />
        </article>

        {/* ── Cache ─────────────────────────────────────────────── */}
        <article className="admin-card" data-testid="ops-cache-card">
          <h3>Cache Status</h3>
          <CacheSection
            cacheStats={snapshot.cacheStats}
            actionBusy={actionBusy}
            onClear={onClearCache}
          />
        </article>

        {/* ── Actions ───────────────────────────────────────────── */}
        <article className="admin-card" data-testid="ops-actions-card">
          <h3>Maintenance Actions</h3>
          <div className="ops-actions">
            <div className="ops-action-row">
              <input
                className="ops-label-input"
                type="text"
                placeholder="Backup label (optional)"
                value={backupLabel}
                onChange={(e) => setBackupLabel(e.target.value)}
              />
              <button
                type="button"
                className="admin-nav-link"
                disabled={actionBusy === 'backup'}
                onClick={() => { onBackup(backupLabel || undefined); setBackupLabel(''); }}
              >
                {actionBusy === 'backup' ? 'Backing up…' : 'Create Backup'}
              </button>
            </div>
            <div className="ops-action-row">
              <button
                type="button"
                className="admin-nav-link"
                disabled={actionBusy === 'retention'}
                onClick={() => onRetention(true)}
              >
                {actionBusy === 'retention' ? 'Running…' : 'Retention Preview (dry-run)'}
              </button>
              <button
                type="button"
                className="admin-nav-link ops-btn-danger"
                disabled={actionBusy === 'retention'}
                onClick={() => onRetention(false)}
              >
                Enforce Retention
              </button>
            </div>
          </div>
        </article>

        {/* ── Recovery ──────────────────────────────────────────── */}
        {Object.keys(snapshot.recoveryStatus).length > 0 && (
          <article className="admin-card" data-testid="ops-recovery-card">
            <h3>Recovery Status</h3>
            <pre className="admin-json admin-json--compact">
              {JSON.stringify(snapshot.recoveryStatus, null, 2)}
            </pre>
          </article>
        )}

      </div>

      {error && (
        <div className="admin-context-help" role="alert" style={{ borderLeftColor: '#ef4444' }}>
          {error}
        </div>
      )}

    </ModuleWorkspace>
  );
}

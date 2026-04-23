/**
 * ModelRegistryPanel.tsx
 *
 * Governance-grade ML registry panel (Prompt-12).
 * Displays all registered model versions, live evaluation metrics,
 * and lets admins trigger a controlled retrain.
 *
 * Endpoints used (from /api/v1/ml/*):
 *   GET  /models        — model version list
 *   GET  /eval          — latest eval metrics snapshot
 *   GET  /retrain/jobs  — recent retrain jobs
 *   POST /retrain       — start a new retrain job (with concurrency guard)
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  mlRegistryApi,
  type EvalMetricsResponse,
  type ModelRegistryRecord,
  type RetrainJobRecord,
} from '../../../services/mlopsApi';

// ─── helpers ─────────────────────────────────────────────────────────────────

const pct = (v: number | null): string =>
  v == null ? '—' : `${(v * 100).toFixed(1)} %`;

const fmtDate = (iso: string | null): string => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('vi-VN');
  } catch {
    return iso;
  }
};

const STATUS_COLOR: Record<string, string> = {
  production: '#22c55e',
  staged:     '#3b82f6',
  training:   '#f59e0b',
  pending:    '#94a3b8',
  archived:   '#6b7280',
};

const JOB_COLOR: Record<string, string> = {
  running:   '#f59e0b',
  completed: '#22c55e',
  failed:    '#ef4444',
  pending:   '#94a3b8',
};

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span
      style={{
        background: color + '22',
        color,
        border: `1px solid ${color}44`,
        borderRadius: 4,
        padding: '1px 8px',
        fontSize: '0.78rem',
        fontWeight: 600,
        letterSpacing: '0.03em',
        textTransform: 'uppercase',
      }}
    >
      {label}
    </span>
  );
}

// ─── mini metric bar chart (no external deps) ────────────────────────────────

function MetricBar({
  label,
  value,
  color = '#3b82f6',
}: {
  label: string;
  value: number | null;
  color?: string;
}) {
  const pctVal = value == null ? 0 : Math.min(1, Math.max(0, value)) * 100;
  return (
    <div style={{ marginBottom: 8 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          marginBottom: 3,
          fontSize: '0.82rem',
          color: '#e2e8f0',
        }}
      >
        <span>{label}</span>
        <span style={{ fontWeight: 600 }}>{pct(value)}</span>
      </div>
      <div
        style={{
          background: '#334155',
          borderRadius: 4,
          height: 8,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            background: color,
            width: `${pctVal}%`,
            height: '100%',
            borderRadius: 4,
            transition: 'width 0.6s ease',
          }}
        />
      </div>
    </div>
  );
}

// ─── main component ───────────────────────────────────────────────────────────

export default function ModelRegistryPanel() {
  const [models, setModels]     = useState<ModelRegistryRecord[]>([]);
  const [eval_, setEval]        = useState<EvalMetricsResponse | null>(null);
  const [jobs, setJobs]         = useState<RetrainJobRecord[]>([]);
  const [loading, setLoading]   = useState(false);
  const [retraining, setRetraining] = useState(false);
  const [statusMsg, setStatusMsg]   = useState('');
  const [errorMsg, setErrorMsg]     = useState('');
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── fetch all data ──────────────────────────────────────────────────
  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    setErrorMsg('');
    try {
      const [reg, ev, jobsResp] = await Promise.all([
        mlRegistryApi.listModels(),
        mlRegistryApi.getEval(),
        mlRegistryApi.listJobs(10),
      ]);
      setModels(reg.models ?? []);
      setEval(ev);
      setJobs(jobsResp.jobs ?? []);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Failed to load data');
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    intervalRef.current = setInterval(() => refresh(true), 10_000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [refresh]);

  // ── trigger retrain ─────────────────────────────────────────────────
  const handleRetrain = async () => {
    setRetraining(true);
    setStatusMsg('');
    setErrorMsg('');
    try {
      const res = await mlRegistryApi.triggerRetrain({ triggered_by: 'admin_ui' });
      setStatusMsg(`Job ${res.job_id} started — ${res.message}`);
      setTimeout(() => refresh(true), 1500);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Retrain failed';
      if (msg.includes('409') || msg.toLowerCase().includes('conflict')) {
        setErrorMsg(`Conflict: a retrain job is already running. ${msg}`);
      } else {
        setErrorMsg(msg);
      }
    } finally {
      setRetraining(false);
    }
  };

  const activeJob = jobs.find((j) => j.status === 'running' || j.status === 'pending');
  const canRetrain = !retraining && !activeJob;

  // ── render ──────────────────────────────────────────────────────────
  return (
    <div
      style={{
        fontFamily: 'inherit',
        color: '#e2e8f0',
        display: 'flex',
        flexDirection: 'column',
        gap: 20,
      }}
    >
      {/* ─── Header ─────────────────────────────────────── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: '1.2rem' }}>ML Model Registry</h2>
          <p style={{ margin: '2px 0 0', fontSize: '0.82rem', color: '#94a3b8' }}>
            Every model version tracked · every retrain logged · one job at a time
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <button
            onClick={() => refresh()}
            disabled={loading}
            style={btnStyle('secondary')}
          >
            {loading ? 'Loading…' : 'Refresh'}
          </button>
          <button
            onClick={handleRetrain}
            disabled={!canRetrain}
            title={
              activeJob
                ? `Job ${activeJob.job_id} is already running`
                : 'Trigger a new controlled retraining job'
            }
            style={btnStyle(canRetrain ? 'primary' : 'disabled')}
          >
            {retraining ? 'Starting…' : activeJob ? 'Retraining…' : 'Trigger Retrain'}
          </button>
        </div>
      </div>

      {/* status / error banners */}
      {statusMsg && (
        <div style={bannerStyle('success')}>{statusMsg}</div>
      )}
      {errorMsg && (
        <div style={bannerStyle('error')}>{errorMsg}</div>
      )}

      {/* ─── Eval metrics chart ─────────────────────────── */}
      <div style={panelStyle}>
        <h3 style={panelHeading}>
          Evaluation Metrics
          {eval_ && (
            <span style={{ marginLeft: 10, fontSize: '0.78rem', color: '#94a3b8', fontWeight: 400 }}>
              model {eval_.model_version} · {eval_.sample_size} samples ·{' '}
              <Badge
                label={eval_.source}
                color={eval_.source === 'live' ? '#22c55e' : eval_.source === 'log' ? '#3b82f6' : '#94a3b8'}
              />
            </span>
          )}
        </h3>
        {eval_ ? (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 32px' }}>
            <MetricBar label="Accuracy"  value={eval_.rolling_accuracy}  color="#22c55e" />
            <MetricBar label="Precision" value={eval_.rolling_precision} color="#3b82f6" />
            <MetricBar label="Recall"    value={eval_.rolling_recall}    color="#a855f7" />
            <MetricBar label="F1 Score"  value={eval_.rolling_f1}        color="#f59e0b" />
            {eval_.calibration_error != null && (
              <MetricBar label="Calibration Error (lower=better)" value={eval_.calibration_error} color="#ef4444" />
            )}
            {eval_.ece != null && (
              <MetricBar label="ECE (lower=better)" value={eval_.ece} color="#f97316" />
            )}
          </div>
        ) : (
          <p style={{ color: '#94a3b8', margin: 0 }}>No evaluation data available yet.</p>
        )}
      </div>

      {/* ─── Model versions table ───────────────────────── */}
      <div style={panelStyle}>
        <h3 style={panelHeading}>Model Versions ({models.length})</h3>
        {models.length === 0 ? (
          <p style={{ color: '#94a3b8', margin: 0 }}>
            No registered models yet. Trigger a retrain to create the first record.
          </p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  {['Version', 'Status', 'Accuracy', 'Precision', 'Recall', 'F1', 'Trigger', 'Created'].map(
                    (h) => (
                      <th key={h} style={thStyle}>{h}</th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {models.map((m) => (
                  <tr key={m.version} style={{ borderBottom: '1px solid #1e293b' }}>
                    <td style={tdStyle}>
                      <code style={{ fontSize: '0.82rem' }}>{m.version}</code>
                    </td>
                    <td style={tdStyle}>
                      <Badge
                        label={m.status}
                        color={STATUS_COLOR[m.status] ?? '#94a3b8'}
                      />
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{pct(m.accuracy)}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{pct(m.precision)}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{pct(m.recall)}</td>
                    <td style={{ ...tdStyle, textAlign: 'right' }}>{pct(m.f1)}</td>
                    <td style={{ ...tdStyle, color: '#94a3b8' }}>{m.retrain_trigger ?? '—'}</td>
                    <td style={{ ...tdStyle, color: '#94a3b8', whiteSpace: 'nowrap' }}>
                      {fmtDate(m.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ─── Retrain job history ─────────────────────────── */}
      <div style={panelStyle}>
        <h3 style={panelHeading}>
          Recent Retrain Jobs
          {activeJob && (
            <span style={{ marginLeft: 10 }}>
              <Badge label="running" color="#f59e0b" />
            </span>
          )}
        </h3>
        {jobs.length === 0 ? (
          <p style={{ color: '#94a3b8', margin: 0 }}>No retrain jobs recorded yet.</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  {['Job ID', 'Status', 'Triggered By', 'Started', 'Completed', 'Error'].map(
                    (h) => <th key={h} style={thStyle}>{h}</th>,
                  )}
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.job_id} style={{ borderBottom: '1px solid #1e293b' }}>
                    <td style={tdStyle}>
                      <code style={{ fontSize: '0.78rem' }}>{j.job_id.slice(0, 12)}…</code>
                    </td>
                    <td style={tdStyle}>
                      <Badge label={j.status} color={JOB_COLOR[j.status] ?? '#94a3b8'} />
                    </td>
                    <td style={tdStyle}>{j.triggered_by}</td>
                    <td style={{ ...tdStyle, whiteSpace: 'nowrap', color: '#94a3b8' }}>
                      {fmtDate(j.started_at)}
                    </td>
                    <td style={{ ...tdStyle, whiteSpace: 'nowrap', color: '#94a3b8' }}>
                      {fmtDate(j.completed_at)}
                    </td>
                    <td style={{ ...tdStyle, color: '#ef4444', fontSize: '0.78rem' }}>
                      {j.error ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── style helpers ────────────────────────────────────────────────────────────

const panelStyle: React.CSSProperties = {
  background: '#0f172a',
  border: '1px solid #1e293b',
  borderRadius: 8,
  padding: '16px 20px',
};

const panelHeading: React.CSSProperties = {
  margin: '0 0 16px',
  fontSize: '0.95rem',
  fontWeight: 600,
  color: '#cbd5e1',
  display: 'flex',
  alignItems: 'center',
};

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: '0.85rem',
};

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '6px 10px',
  fontSize: '0.78rem',
  color: '#64748b',
  borderBottom: '1px solid #1e293b',
  whiteSpace: 'nowrap',
};

const tdStyle: React.CSSProperties = {
  padding: '8px 10px',
  verticalAlign: 'middle',
};

function btnStyle(variant: 'primary' | 'secondary' | 'disabled'): React.CSSProperties {
  const base: React.CSSProperties = {
    padding: '7px 16px',
    borderRadius: 6,
    border: 'none',
    cursor: variant === 'disabled' ? 'not-allowed' : 'pointer',
    fontSize: '0.85rem',
    fontWeight: 600,
    transition: 'opacity 0.15s',
    opacity: variant === 'disabled' ? 0.5 : 1,
  };
  if (variant === 'primary') {
    return { ...base, background: '#3b82f6', color: '#fff' };
  }
  if (variant === 'secondary') {
    return { ...base, background: '#1e293b', color: '#cbd5e1' };
  }
  return { ...base, background: '#334155', color: '#94a3b8' };
}

function bannerStyle(kind: 'success' | 'error'): React.CSSProperties {
  return {
    padding: '10px 16px',
    borderRadius: 6,
    fontSize: '0.85rem',
    background: kind === 'success' ? '#14532d33' : '#7f1d1d33',
    border: `1px solid ${kind === 'success' ? '#22c55e44' : '#ef444444'}`,
    color: kind === 'success' ? '#4ade80' : '#fca5a5',
  };
}

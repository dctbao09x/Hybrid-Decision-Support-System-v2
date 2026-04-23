// src/components/PipelineTimeline/PipelineTimeline.tsx
/**
 * PipelineTimeline — P10
 * ======================
 *
 * Visualizes every stage of the decision pipeline as a vertical timeline.
 * Shows: stage name, status badge, duration bar, input/output snapshot.
 *
 * Props:
 *   stageLog    — array from DecisionResponse.stage_log
 *   diagnostics — object from DecisionResponse.diagnostics
 */

import styles from './PipelineTimeline.module.css';

export interface StageEntry {
  stage: string;
  status: string;
  duration_ms: number;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  error?: string;
}

export interface DiagnosticsBlock {
  total_latency_ms: number;
  stage_count: number;
  stage_passed: number;
  stage_skipped: number;
  stage_failed: number;
  slowest_stage: string;
  errors: Array<{ stage: string; error: string | null }>;
  llm_used: boolean;
  rules_audited: number;
}

interface PipelineTimelineProps {
  stageLog: StageEntry[];
  diagnostics?: DiagnosticsBlock | null;
}

const STAGE_LABELS: Record<string, string> = {
  input_normalize: '1 · Input Normalize',
  feature_extraction: '2 · Feature Extraction',
  kb_alignment: '3 · KB Alignment',
  merge: '4 · Merge',
  simgr_scoring: '5 · SIMGR Scoring',
  drift_check: '6 · Drift Check',
  rule_engine: '7 · Rule Engine',
  market_data: '8 · Market Data',
  explanation: '9 · Explanation',
};

const STATUS_COLOR: Record<string, string> = {
  ok: '#4caf7d',
  degraded: '#d6a54f',
  frozen_pass_through: '#c8a55a',
  skipped: '#6b6b7a',
  error: '#e05252',
};

const MAX_INLINE_ITEMS = 4;
const MAX_TEXT_LENGTH = 180;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function truncateText(text: string, maxLength = MAX_TEXT_LENGTH): string {
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength - 1)}…`;
}

function summarizeObject(value: Record<string, unknown>): string {
  const preferredKeys = ['taxonomy', 'stage', 'status', 'reason', 'career_name', 'demand_level'];
  const selectedPairs: Array<[string, unknown]> = [];

  preferredKeys.forEach((key) => {
    if (key in value) {
      selectedPairs.push([key, value[key]]);
    }
  });

  if (selectedPairs.length === 0) {
    selectedPairs.push(...Object.entries(value).slice(0, 3));
  }

  const body = selectedPairs
    .map(([k, v]) => `${k}: ${formatValue(v, 1)}`)
    .join(', ');

  return `{ ${truncateText(body, 140)} }`;
}

function formatArray(values: unknown[]): string {
  if (values.length === 0) return '[]';

  const shown = values.slice(0, MAX_INLINE_ITEMS).map((item) => formatValue(item, 1));
  const suffix = values.length > MAX_INLINE_ITEMS ? ` … +${values.length - MAX_INLINE_ITEMS}` : '';
  return `[${shown.join(' | ')}${suffix}]`;
}

function formatValue(value: unknown, depth = 0): string {
  if (value === null) return 'null';
  if (value === undefined) return 'undefined';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return Number.isFinite(value) ? `${value}` : 'NaN';
  if (typeof value === 'string') return truncateText(value);

  if (Array.isArray(value)) {
    return formatArray(value);
  }

  if (isPlainObject(value)) {
    if (depth > 1) {
      const compact = JSON.stringify(value);
      return truncateText(compact ?? '{…}', 120);
    }
    return summarizeObject(value);
  }

  return truncateText(String(value));
}

function StatusBadge({ status }: { status: string }) {
  const color = STATUS_COLOR[status] ?? '#888';
  const label =
    status === 'ok' ? 'OK' :
    status === 'degraded' ? 'DEGRADED' :
    status === 'frozen_pass_through' ? 'FROZEN' :
    status === 'skipped' ? 'SKIP' :
    status === 'error' ? 'ERR' : status.toUpperCase();
  return (
    <span className={styles.badge} style={{ background: color + '22', border: `1px solid ${color}`, color }}>
      {label}
    </span>
  );
}

function DurationBar({ durationMs, maxMs }: { durationMs: number; maxMs: number }) {
  const pct = maxMs > 0 ? Math.min((durationMs / maxMs) * 100, 100) : 0;
  return (
    <div className={styles.barTrack}>
      <div className={styles.barFill} style={{ width: `${pct}%` }} />
      <span className={styles.barLabel}>{durationMs.toFixed(1)}ms</span>
    </div>
  );
}

function IOSnapshot({ label, data }: { label: string; data: Record<string, unknown> | undefined }) {
  if (!data || Object.keys(data).length === 0) return null;
  return (
    <div className={styles.ioBlock}>
      <span className={styles.ioLabel}>{label}</span>
      <div className={styles.ioRows}>
        {Object.entries(data).map(([k, v]) => (
          <div key={k} className={styles.ioRow}>
            <span className={styles.ioKey}>{k}</span>
            <span className={styles.ioVal} title={formatValue(v)}>
              {formatValue(v)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function PipelineTimeline({ stageLog, diagnostics }: PipelineTimelineProps) {
  if (!stageLog || stageLog.length === 0) return null;

  const maxMs = Math.max(...stageLog.map(s => s.duration_ms ?? 0), 1);

  return (
    <div className={styles.wrap}>
      <h3 className={styles.title}>Pipeline Lifecycle</h3>

      {/* ─ Diagnostics summary bar ──────────────────────────────────── */}
      {diagnostics && (
        <div className={styles.diagBar}>
          <div className={styles.diagStat}>
            <span className={styles.diagVal}>{diagnostics.total_latency_ms.toFixed(0)}ms</span>
            <span className={styles.diagKey}>latency</span>
          </div>
          <div className={styles.diagStat}>
            <span className={styles.diagVal} style={{ color: '#4caf7d' }}>{diagnostics.stage_passed}</span>
            <span className={styles.diagKey}>passed</span>
          </div>
          <div className={styles.diagStat}>
            <span className={styles.diagVal} style={{ color: '#6b6b7a' }}>{diagnostics.stage_skipped}</span>
            <span className={styles.diagKey}>skipped</span>
          </div>
          <div className={styles.diagStat}>
            <span className={styles.diagVal} style={{ color: '#e05252' }}>{diagnostics.stage_failed}</span>
            <span className={styles.diagKey}>failed</span>
          </div>
          <div className={styles.diagStat}>
            <span className={styles.diagVal}>{diagnostics.rules_audited}</span>
            <span className={styles.diagKey}>rules</span>
          </div>
          <div className={styles.diagStat}>
            <span className={styles.diagVal}>{diagnostics.slowest_stage?.replace('_', ' ')}</span>
            <span className={styles.diagKey}>slowest</span>
          </div>
        </div>
      )}

      {/* ─ Stage rows ───────────────────────────────────────────────── */}
      <div className={styles.timeline}>
        {stageLog.map((stage, idx) => (
          <div key={stage.stage} className={styles.stageRow}>
            {/* Connector line */}
            <div className={styles.connector}>
              <div className={styles.dot} style={{ background: STATUS_COLOR[stage.status] ?? '#888' }} />
              {idx < stageLog.length - 1 && <div className={styles.line} />}
            </div>

            {/* Content */}
            <div className={styles.stageContent}>
              <div className={styles.stageHeader}>
                <span className={styles.stageName}>
                  {STAGE_LABELS[stage.stage] ?? stage.stage}
                </span>
                <StatusBadge status={stage.status} />
              </div>

              <DurationBar durationMs={stage.duration_ms ?? 0} maxMs={maxMs} />

              {/* Expandable I/O */}
              <details className={styles.ioDetails}>
                <summary className={styles.ioSummary}>I/O snapshot</summary>
                <div className={styles.ioGrid}>
                  <IOSnapshot label="INPUT" data={stage.input} />
                  <IOSnapshot label="OUTPUT" data={stage.output} />
                </div>
                {stage.error && (
                  <p className={styles.stageError}>{stage.error}</p>
                )}
              </details>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * LLM Health Widget
 * =================
 * 
 * Dedicated LLM health monitoring widget.
 * Phase 1 - Critical Visibility Component
 * 
 * Features:
 * - LLM service status (healthy/degraded/down)
 * - Error rate percentage
 * - Timeout rate percentage  
 * - Average latency
 * - Anomaly rate with threshold alerting
 * - Auto-refresh with exponential backoff on errors
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { apiRequest } from '../../services/apiClient';
import type { WidgetStatus, WidgetConfig } from '../liveops/types';

// ==============================================================================
// Types
// ==============================================================================

interface LLMHealthData {
  ollama_up: boolean;
  model_ready: boolean;
  last_warmup: string | null;
}

interface LLMAnomalyData {
  anomaly_rate: number;
  error_rate: number;
  timeout_rate: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  total_requests: number;
  failed_requests: number;
  threshold: number;
  is_anomaly: boolean;
  timestamp: string;
}

interface LLMHealthWidgetData {
  status: WidgetStatus;
  health: LLMHealthData | null;
  anomaly: LLMAnomalyData | null;
  lastUpdate: string;
}

type LoadingState = 'idle' | 'loading' | 'success' | 'error';

interface LLMHealthWidgetProps {
  config?: Partial<WidgetConfig>;
  onDrillDown?: () => void;
}

// ==============================================================================
// Helper Components
// ==============================================================================

interface StatusIndicatorProps {
  status: WidgetStatus;
  size?: 'sm' | 'md' | 'lg';
}

function StatusIndicator({ status, size = 'md' }: StatusIndicatorProps) {
  const colors: Record<WidgetStatus, string> = {
    healthy: '#6ee7b7',
    warning: '#fbbf24',
    critical: '#f87171',
    unknown: '#6a6a7e',
    loading: '#60a5fa',
  };
  const sizes = { sm: '8px', md: '10px', lg: '14px' };
  return (
    <span
      style={{ display: 'inline-block', borderRadius: '50%', background: colors[status], width: sizes[size], height: sizes[size], flexShrink: 0 }}
      title={status}
    />
  );
}

// ==============================================================================
// Component
// ==============================================================================

export function LLMHealthWidget({ config, onDrillDown }: LLMHealthWidgetProps) {
  const [data, setData] = useState<LLMHealthWidgetData | null>(null);
  const [loadingState, setLoadingState] = useState<LoadingState>('idle');
  const [error, setError] = useState<string | null>(null);

  // Use refs to avoid re-render loops — retryCount must NOT be in state
  const retryCountRef = useRef(0);
  const retryTimerRef = useRef<number | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const intervalRef = useRef<number | null>(null);

  const refreshInterval = config?.refreshInterval || 30000; // 30s default
  const alertThreshold = config?.alertThreshold || 0.05; // 5% default

  // Stable fetchData — no state vars in deps to prevent re-render loops
  const fetchData = useCallback(async (isRetry = false) => {
    // Abort any pending request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    abortControllerRef.current = new AbortController();

    if (!isRetry) {
      setLoadingState('loading');
      setError(null);
    }

    try {
      // Fetch both endpoints in parallel; swallow individual 404s gracefully
      const [healthResult, anomalyResult] = await Promise.all([
        apiRequest<LLMHealthData>('/api/v1/health/llm').catch(() => null),
        apiRequest<LLMAnomalyData>('/api/v1/health/llm/anomaly-rate').catch(() => null),
      ]);

      // Determine overall status
      let status: WidgetStatus = 'unknown';

      if (healthResult) {
        if (healthResult.ollama_up && healthResult.model_ready) {
          status = 'healthy';
        } else if (healthResult.ollama_up) {
          status = 'warning';
        } else {
          status = 'critical';
        }
      }

      // Override status if anomaly detected
      if (anomalyResult?.is_anomaly) {
        status = anomalyResult.anomaly_rate > alertThreshold * 2 ? 'critical' : 'warning';
      }

      setData({
        status,
        health: healthResult,
        anomaly: anomalyResult,
        lastUpdate: new Date().toISOString(),
      });

      setLoadingState('success');
      retryCountRef.current = 0; // reset without re-render
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        return;
      }

      const errorMessage = err instanceof Error ? err.message : 'Failed to load LLM health';
      setError(errorMessage);
      setLoadingState('error');

      // Exponential backoff retry (max 3 retries) — use ref, not state
      if (retryCountRef.current < 3) {
        const delay = Math.min(1000 * Math.pow(2, retryCountRef.current), 8000);
        retryCountRef.current += 1;
        retryTimerRef.current = window.setTimeout(() => {
          fetchData(true);
        }, delay);
      }
    }
  }, [alertThreshold]); // stable — alertThreshold is derived from props only

  // Initial fetch and interval setup
  useEffect(() => {
    fetchData();

    intervalRef.current = window.setInterval(() => {
      fetchData();
    }, refreshInterval);

    return () => {
      if (retryTimerRef.current) window.clearTimeout(retryTimerRef.current);
      if (abortControllerRef.current) abortControllerRef.current.abort();
      if (intervalRef.current) window.clearInterval(intervalRef.current);
    };
  }, [fetchData, refreshInterval]);

  // Format time
  const formatTime = (iso: string): string => {
    try {
      return new Date(iso).toLocaleTimeString();
    } catch {
      return '-';
    }
  };

  // Render loading skeleton
  if (loadingState === 'loading' && !data) {
    return (
      <div className="admin-card" style={{ minHeight: '140px' }}>
        <div style={{ height: '80px', background: 'rgba(255,255,255,0.04)', borderRadius: '6px' }} />
      </div>
    );
  }

  // Render error state
  if (loadingState === 'error' && !data) {
    return (
      <div className="admin-card" style={{ minHeight: '140px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <StatusIndicator status="critical" />
            <h3 style={{ margin: 0, fontSize: '0.8rem', fontWeight: 600, color: '#c8a55a', letterSpacing: '0.08em', textTransform: 'uppercase' }}>LLM Health</h3>
          </div>
          <button onClick={() => fetchData()} style={{ background: 'none', border: '1px solid rgba(200,165,90,0.2)', borderRadius: '6px', color: '#c8a55a', padding: '3px 8px', cursor: 'pointer', fontSize: '12px' }}>
            Retry
          </button>
        </div>
        <div style={{ background: 'rgba(248,113,113,0.07)', border: '1px solid rgba(248,113,113,0.2)', borderRadius: '6px', padding: '10px' }}>
          <p style={{ color: '#f87171', fontSize: '13px', margin: 0 }}>{error}</p>
          {retryCountRef.current > 0 && <p style={{ color: '#f87171', fontSize: '11px', margin: '4px 0 0' }}>Retrying... ({retryCountRef.current}/3)</p>}
        </div>
      </div>
    );
  }

  const status = data?.status || 'unknown';
  const health = data?.health;
  const anomaly = data?.anomaly;

  // Get status label
  const getStatusLabel = (): string => {
    if (!health) return 'Unknown';
    if (health.ollama_up && health.model_ready) return 'Healthy';
    if (health.ollama_up) return 'Degraded';
    return 'Down';
  };

  const statusColor = status === 'healthy' ? '#6ee7b7' : status === 'warning' ? '#fbbf24' : status === 'critical' ? '#f87171' : '#6a6a7e';

  return (
    <div className="admin-card" style={{ display: 'flex', flexDirection: 'column', minHeight: '140px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <StatusIndicator status={status} />
          <h3 style={{ margin: 0, fontSize: '0.8rem', fontWeight: 600, color: '#c8a55a', letterSpacing: '0.08em', textTransform: 'uppercase' }}>LLM Health</h3>
          {anomaly?.is_anomaly && (
            <span style={{ background: 'rgba(248,113,113,0.12)', color: '#f87171', fontSize: '10px', padding: '2px 6px', borderRadius: '999px', border: '1px solid rgba(248,113,113,0.2)' }}>Anomaly</span>
          )}
        </div>
        <div style={{ display: 'flex', gap: '4px' }}>
          <button onClick={() => fetchData()} disabled={loadingState === 'loading'} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6a6a7e', padding: '4px', borderRadius: '6px' }} title="Refresh">
            <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
          {onDrillDown && (
            <button onClick={onDrillDown} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6a6a7e', padding: '4px', borderRadius: '6px' }} title="View Details">
              <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {/* Status Badge */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '12px', color: '#6a6a7e' }}>Status</span>
          <span style={{ background: `${statusColor}14`, color: statusColor, fontSize: '12px', fontWeight: 600, padding: '2px 10px', borderRadius: '999px', border: `1px solid ${statusColor}30` }}>
            {getStatusLabel()}
          </span>
        </div>

        {/* Anomaly Alert */}
        {anomaly?.is_anomaly && (
          <div style={{ background: 'rgba(248,113,113,0.07)', border: '1px solid rgba(248,113,113,0.2)', borderRadius: '6px', padding: '8px', fontSize: '12px', color: '#f87171' }}>
            ⚠ Anomaly Rate: {(anomaly.anomaly_rate * 100).toFixed(2)}% (threshold: {(anomaly.threshold * 100).toFixed(0)}%)
          </div>
        )}

        {/* Metrics Grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
          <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: '6px', padding: '8px' }}>
            <div style={{ fontSize: '10px', color: '#6a6a7e', marginBottom: '2px' }}>Error Rate</div>
            <div style={{ fontSize: '1rem', fontWeight: 700, color: (anomaly?.error_rate || 0) > alertThreshold ? '#f87171' : '#ede8df' }}>
              {anomaly ? `${(anomaly.error_rate * 100).toFixed(2)}%` : '-'}
            </div>
          </div>
          <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: '6px', padding: '8px' }}>
            <div style={{ fontSize: '10px', color: '#6a6a7e', marginBottom: '2px' }}>Timeout Rate</div>
            <div style={{ fontSize: '1rem', fontWeight: 700, color: (anomaly?.timeout_rate || 0) > alertThreshold ? '#f87171' : '#ede8df' }}>
              {anomaly ? `${(anomaly.timeout_rate * 100).toFixed(2)}%` : '-'}
            </div>
          </div>
          <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: '6px', padding: '8px' }}>
            <div style={{ fontSize: '10px', color: '#6a6a7e', marginBottom: '2px' }}>Avg Latency</div>
            <div style={{ fontSize: '1rem', fontWeight: 700, color: '#ede8df' }}>{anomaly ? `${anomaly.avg_latency_ms.toFixed(0)}ms` : '-'}</div>
          </div>
          <div style={{ background: 'rgba(255,255,255,0.03)', borderRadius: '6px', padding: '8px' }}>
            <div style={{ fontSize: '10px', color: '#6a6a7e', marginBottom: '2px' }}>P95 Latency</div>
            <div style={{ fontSize: '1rem', fontWeight: 700, color: '#ede8df' }}>{anomaly ? `${anomaly.p95_latency_ms.toFixed(0)}ms` : '-'}</div>
          </div>
        </div>

        {/* Request Stats */}
        {anomaly && (
          <div style={{ fontSize: '11px', color: '#6a6a7e' }}>
            {anomaly.total_requests.toLocaleString()} requests
            {anomaly.failed_requests > 0 && <span style={{ color: '#f87171', marginLeft: '4px' }}>({anomaly.failed_requests.toLocaleString()} failed)</span>}
          </div>
        )}

        {/* Warmup Status */}
        {health?.last_warmup && (
          <div style={{ fontSize: '11px', color: '#6a6a7e' }}>Last warmup: {formatTime(health.last_warmup)}</div>
        )}
      </div>

      {/* Footer */}
      <div style={{ fontSize: '11px', color: '#6a6a7e', marginTop: '10px', paddingTop: '8px', borderTop: '1px solid rgba(200,165,90,0.1)' }}>
        Last updated: {data ? formatTime(data.lastUpdate) : '-'}
      </div>
    </div>
  );
}

export default LLMHealthWidget;

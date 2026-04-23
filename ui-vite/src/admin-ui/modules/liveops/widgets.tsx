/**
 * Live Dashboard Widgets
 * ======================
 * 
 * Real-time monitoring widgets for the Admin Control Panel.
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useLiveChannel } from './useLiveChannel';
import type {
  WidgetStatus,
  WidgetConfig,
  SystemHealthData,
  JobQueueData,
  DriftData,
  CostData,
  SLAData,
  ErrorRateData,
} from './types';
import type { LiveEvent } from '../../interface/liveChannel';
import { isAdminAuthenticated } from '../../../utils/adminSession';
import * as service from './service';

// ==============================================================================
// Shared Components
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
      style={{
        display: 'inline-block',
        borderRadius: '50%',
        background: colors[status],
        width: sizes[size],
        height: sizes[size],
        flexShrink: 0,
      }}
      title={status}
    />
  );
}

interface WidgetCardProps {
  title: string;
  status: WidgetStatus;
  lastUpdate: string;
  onRefresh?: () => void;
  onDrillDown?: () => void;
  children: React.ReactNode;
}

function WidgetCard({ 
  title, 
  status, 
  lastUpdate, 
  onRefresh, 
  onDrillDown,
  children 
}: WidgetCardProps) {
  const formatTime = (iso: string) => {
    try {
      return new Date(iso).toLocaleTimeString();
    } catch {
      return '-';
    }
  };
  
  return (
    <div className="admin-card" style={{ display: 'flex', flexDirection: 'column', minHeight: '140px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <StatusIndicator status={status} />
          <h3 style={{ margin: 0, fontSize: '0.8rem', fontWeight: 600, color: '#c8a55a', letterSpacing: '0.08em', textTransform: 'uppercase' }}>{title}</h3>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          {onRefresh && (
            <button
              onClick={onRefresh}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6a6a7e', padding: '4px', borderRadius: '6px' }}
              title="Refresh"
            >
              <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </button>
          )}
          {onDrillDown && (
            <button
              onClick={onDrillDown}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6a6a7e', padding: '4px', borderRadius: '6px' }}
              title="View Details"
            >
              <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          )}
        </div>
      </div>
      
      <div style={{ flex: 1 }}>
        {children}
      </div>
      
      <div style={{ fontSize: '11px', color: '#6a6a7e', marginTop: '10px', paddingTop: '8px', borderTop: '1px solid rgba(200,165,90,0.1)' }}>
        Last updated: {formatTime(lastUpdate)}
      </div>
    </div>
  );
}

// ==============================================================================
// System Health Widget
// ==============================================================================

interface SystemHealthWidgetProps {
  config?: Partial<WidgetConfig>;
  onDrillDown?: () => void;
  lastEvent?: LiveEvent | null;
}

export function SystemHealthWidget({ config, onDrillDown, lastEvent }: SystemHealthWidgetProps) {
  const [data, setData] = useState<SystemHealthData | null>(null);
  const intervalRef = useRef<number | null>(null);

  const fetchData = useCallback(async () => {
    if (!isAdminAuthenticated()) return;
    const result = await service.getSystemHealth().catch(() => null);
    if (result) setData(result);
  }, []);

  useEffect(() => {
    fetchData();
    intervalRef.current = window.setInterval(fetchData, config?.refreshInterval || 30000);
    return () => { if (intervalRef.current) window.clearInterval(intervalRef.current); };
  }, [fetchData, config?.refreshInterval]);

  // Update from live events passed down from LiveDashboard
  useEffect(() => {
    if (lastEvent?.type === 'status' && lastEvent.module === 'system') {
      setData(prev => prev ? { ...prev, ...lastEvent.payload as Partial<SystemHealthData> } : prev);
    }
  }, [lastEvent]);
  
  if (!data) {
    return (
      <WidgetCard title="System Health" status="loading" lastUpdate="">
        <div style={{ height: '80px', background: 'rgba(255,255,255,0.04)', borderRadius: '6px', animation: 'pulse 2s infinite' }} />
      </WidgetCard>
    );
  }
  
  return (
    <WidgetCard
      title="System Health"
      status={data.status}
      lastUpdate={data.lastUpdate}
      onRefresh={fetchData}
      onDrillDown={onDrillDown}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ fontSize: '1.3rem', fontWeight: 700, textTransform: 'capitalize', color: '#ede8df' }}>
          {data.overallStatus}
        </div>
        
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', fontSize: '13px' }}>
          {data.services.slice(0, 4).map((svc) => (
            <div key={svc.name} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <StatusIndicator 
                status={svc.status === 'up' ? 'healthy' : svc.status === 'degraded' ? 'warning' : 'critical'} 
                size="sm" 
              />
              <span style={{ color: '#a0a0b4', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{svc.name}</span>
            </div>
          ))}
        </div>
        
        {data.uptime > 0 && (
          <div style={{ fontSize: '11px', color: '#6a6a7e' }}>
            Uptime: {Math.floor(data.uptime / 3600)}h {Math.floor((data.uptime % 3600) / 60)}m
          </div>
        )}
      </div>
    </WidgetCard>
  );
}

// ==============================================================================
// Job Queue Widget
// ==============================================================================

interface JobQueueWidgetProps {
  config?: Partial<WidgetConfig>;
  onDrillDown?: () => void;
  lastEvent?: LiveEvent | null;
}

export function JobQueueWidget({ config, onDrillDown, lastEvent }: JobQueueWidgetProps) {
  const [data, setData] = useState<JobQueueData | null>(null);
  const intervalRef = useRef<number | null>(null);

  const fetchData = useCallback(async () => {
    if (!isAdminAuthenticated()) return;
    const result = await service.getJobQueue().catch(() => null);
    if (result) setData(result);
  }, []);

  useEffect(() => {
    fetchData();
    intervalRef.current = window.setInterval(fetchData, config?.refreshInterval || 15000);
    return () => { if (intervalRef.current) window.clearInterval(intervalRef.current); };
  }, [fetchData, config?.refreshInterval]);

  useEffect(() => {
    if (lastEvent?.type === 'status' && lastEvent.module === 'ops') fetchData();
  }, [lastEvent, fetchData]);
  
  if (!data) {
    return (
      <WidgetCard title="Job Queue" status="loading" lastUpdate="">
        <div style={{ height: '80px', background: 'rgba(255,255,255,0.04)', borderRadius: '6px' }} />
      </WidgetCard>
    );
  }
  
  const total = data.pending + data.running + data.completed + data.failed;
  const failRate = total > 0 ? (data.failed / total) * 100 : 0;
  
  return (
    <WidgetCard
      title="Job Queue"
      status={failRate > 10 ? 'critical' : failRate > 5 ? 'warning' : data.status}
      lastUpdate={data.lastUpdate}
      onRefresh={fetchData}
      onDrillDown={onDrillDown}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
          <div style={{ background: 'rgba(200,165,90,0.06)', borderRadius: '6px', padding: '8px' }}>
            <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#c8a55a' }}>{data.pending}</div>
            <div style={{ fontSize: '11px', color: '#6a6a7e' }}>Pending</div>
          </div>
          <div style={{ background: 'rgba(96,165,250,0.08)', borderRadius: '6px', padding: '8px' }}>
            <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#60a5fa' }}>{data.running}</div>
            <div style={{ fontSize: '11px', color: '#6a6a7e' }}>Running</div>
          </div>
          <div style={{ background: 'rgba(110,231,183,0.07)', borderRadius: '6px', padding: '8px' }}>
            <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#6ee7b7' }}>{data.completed}</div>
            <div style={{ fontSize: '11px', color: '#6a6a7e' }}>Completed</div>
          </div>
          <div style={{ background: 'rgba(248,113,113,0.08)', borderRadius: '6px', padding: '8px' }}>
            <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#f87171' }}>{data.failed}</div>
            <div style={{ fontSize: '11px', color: '#6a6a7e' }}>Failed</div>
          </div>
        </div>
        <div style={{ fontSize: '11px', color: '#6a6a7e' }}>Avg wait: {data.avgWaitTime.toFixed(1)}s</div>
      </div>
    </WidgetCard>
  );
}

// ==============================================================================
// Drift Widget
// ==============================================================================

interface DriftWidgetProps {
  config?: Partial<WidgetConfig>;
  onDrillDown?: () => void;
  lastEvent?: LiveEvent | null;
}

export function DriftWidget({ config, onDrillDown, lastEvent }: DriftWidgetProps) {
  const [data, setData] = useState<DriftData | null>(null);
  const intervalRef = useRef<number | null>(null);

  const fetchData = useCallback(async () => {
    if (!isAdminAuthenticated()) return;
    const result = await service.getDriftMetrics().catch(() => null);
    if (result) setData(result);
  }, []);

  useEffect(() => {
    fetchData();
    intervalRef.current = window.setInterval(fetchData, config?.refreshInterval || 60000);
    return () => { if (intervalRef.current) window.clearInterval(intervalRef.current); };
  }, [fetchData, config?.refreshInterval]);

  useEffect(() => {
    if (lastEvent?.module === 'mlops') fetchData();
  }, [lastEvent, fetchData]);
  
  if (!data) {
    return (
      <WidgetCard title="Model Drift" status="loading" lastUpdate="">
        <div style={{ height: '80px', background: 'rgba(255,255,255,0.04)', borderRadius: '6px' }} />
      </WidgetCard>
    );
  }
  
  const driftPercent = (data.currentDrift * 100).toFixed(2);
  const thresholdPercent = (data.threshold * 100).toFixed(1);
  
  return (
    <WidgetCard
      title="Model Drift"
      status={data.status}
      lastUpdate={data.lastUpdate}
      onRefresh={fetchData}
      onDrillDown={onDrillDown}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
          <span style={{ fontSize: '1.6rem', fontWeight: 700, color: data.alertActive ? '#f87171' : '#ede8df' }}>
            {driftPercent}%
          </span>
          <span style={{ fontSize: '12px', color: '#6a6a7e' }}>/ {thresholdPercent}% threshold</span>
        </div>
        
        <div style={{ width: '100%', background: 'rgba(255,255,255,0.08)', borderRadius: '999px', height: '6px' }}>
          <div
            style={{
              height: '6px',
              borderRadius: '999px',
              background: data.alertActive ? '#f87171' : '#6ee7b7',
              width: `${Math.min(100, (data.currentDrift / data.threshold) * 100)}%`,
              transition: 'width 0.3s'
            }}
          />
        </div>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px' }}>
          <span style={{ color: '#6a6a7e' }}>Trend:</span>
          <span style={{ color: data.trend === 'increasing' ? '#f87171' : data.trend === 'decreasing' ? '#6ee7b7' : '#6a6a7e' }}>
            {data.trend === 'increasing' ? '↑' : data.trend === 'decreasing' ? '↓' : '→'} {data.trend}
          </span>
        </div>
        
        {data.alertActive && (
          <div style={{ fontSize: '11px', color: '#f87171', fontWeight: 600 }}>⚠ Drift threshold exceeded</div>
        )}
      </div>
    </WidgetCard>
  );
}

// ==============================================================================
// Cost Widget
// ==============================================================================

interface CostWidgetProps {
  config?: Partial<WidgetConfig>;
  onDrillDown?: () => void;
}

export function CostWidget({ config, onDrillDown }: CostWidgetProps) {
  const [data, setData] = useState<CostData | null>(null);
  const intervalRef = useRef<number | null>(null);

  const fetchData = useCallback(async () => {
    if (!isAdminAuthenticated()) return;
    const result = await service.getCostMetrics().catch(() => null);
    if (result) setData(result);
  }, []);

  useEffect(() => {
    fetchData();
    intervalRef.current = window.setInterval(fetchData, config?.refreshInterval || 300000); // 5 min
    return () => { if (intervalRef.current) window.clearInterval(intervalRef.current); };
  }, [fetchData, config?.refreshInterval]);
  
  if (!data) {
    return (
      <WidgetCard title="Cost" status="loading" lastUpdate="">
        <div style={{ height: '80px', background: 'rgba(255,255,255,0.04)', borderRadius: '6px' }} />
      </WidgetCard>
    );
  }
  
  const usagePercent = (data.currentMonth / data.budget) * 100;
  
  return (
    <WidgetCard
      title="Cost"
      status={data.status}
      lastUpdate={data.lastUpdate}
      onRefresh={fetchData}
      onDrillDown={onDrillDown}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#ede8df' }}>${data.currentMonth.toLocaleString()}</div>
          <div style={{ fontSize: '12px', color: '#6a6a7e' }}>of ${data.budget.toLocaleString()} budget</div>
        </div>
        
        <div style={{ width: '100%', background: 'rgba(255,255,255,0.08)', borderRadius: '999px', height: '6px' }}>
          <div
            style={{
              height: '6px', borderRadius: '999px', transition: 'width 0.3s',
              background: usagePercent > 100 ? '#f87171' : usagePercent > 90 ? '#fbbf24' : '#6ee7b7',
              width: `${Math.min(100, usagePercent)}%`
            }}
          />
        </div>
        
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: '#6a6a7e' }}>
          <span>Forecast: ${data.forecast.toLocaleString()}</span>
          <span style={{ color: data.trend === 'increasing' ? '#f87171' : data.trend === 'decreasing' ? '#6ee7b7' : '#6a6a7e' }}>
            {data.trend === 'increasing' ? '↑' : data.trend === 'decreasing' ? '↓' : '→'}
          </span>
        </div>
      </div>
    </WidgetCard>
  );
}

// ==============================================================================
// SLA Widget
// ==============================================================================

interface SLAWidgetProps {
  config?: Partial<WidgetConfig>;
  onDrillDown?: () => void;
}

export function SLAWidget({ config, onDrillDown }: SLAWidgetProps) {
  const [data, setData] = useState<SLAData | null>(null);
  const intervalRef = useRef<number | null>(null);

  const fetchData = useCallback(async () => {
    if (!isAdminAuthenticated()) return;
    const result = await service.getSLAMetrics().catch(() => null);
    if (result) setData(result);
  }, []);

  useEffect(() => {
    fetchData();
    intervalRef.current = window.setInterval(fetchData, config?.refreshInterval || 60000);
    return () => { if (intervalRef.current) window.clearInterval(intervalRef.current); };
  }, [fetchData, config?.refreshInterval]);
  
  if (!data) {
    return (
      <WidgetCard title="SLA" status="loading" lastUpdate="">
        <div style={{ height: '80px', background: 'rgba(255,255,255,0.04)', borderRadius: '6px' }} />
      </WidgetCard>
    );
  }
  
  return (
    <WidgetCard
      title="SLA Compliance"
      status={data.status}
      lastUpdate={data.lastUpdate}
      onRefresh={fetchData}
      onDrillDown={onDrillDown}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
          <span style={{ fontSize: '1.6rem', fontWeight: 700, color: data.compliance >= data.target ? '#6ee7b7' : '#f87171' }}>
            {data.compliance.toFixed(2)}%
          </span>
          <span style={{ fontSize: '12px', color: '#6a6a7e' }}>/ {data.target}% target</span>
        </div>
        
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {data.metrics.slice(0, 3).map((metric) => (
            <div key={metric.name} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
              <span style={{ color: '#a0a0b4', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{metric.name}</span>
              <span style={{ color: metric.status === 'met' ? '#6ee7b7' : metric.status === 'at_risk' ? '#fbbf24' : '#f87171' }}>
                {metric.current.toFixed(1)}%
              </span>
            </div>
          ))}
        </div>
        
        {data.incidents > 0 && (
          <div style={{ fontSize: '11px', color: '#f87171' }}>
            {data.incidents} incident{data.incidents > 1 ? 's' : ''} this period
          </div>
        )}
      </div>
    </WidgetCard>
  );
}

// ==============================================================================
// Error Rate Widget
// ==============================================================================

interface ErrorRateWidgetProps {
  config?: Partial<WidgetConfig>;
  onDrillDown?: () => void;
  lastEvent?: LiveEvent | null;
}

export function ErrorRateWidget({ config, onDrillDown, lastEvent }: ErrorRateWidgetProps) {
  const [data, setData] = useState<ErrorRateData | null>(null);
  const intervalRef = useRef<number | null>(null);

  const fetchData = useCallback(async () => {
    if (!isAdminAuthenticated()) return;
    const result = await service.getErrorRateMetrics().catch(() => null);
    if (result) setData(result);
  }, []);

  useEffect(() => {
    fetchData();
    intervalRef.current = window.setInterval(fetchData, config?.refreshInterval || 30000);
    return () => { if (intervalRef.current) window.clearInterval(intervalRef.current); };
  }, [fetchData, config?.refreshInterval]);

  useEffect(() => {
    if (lastEvent?.type === 'alert') fetchData();
  }, [lastEvent, fetchData]);
  
  if (!data) {
    return (
      <WidgetCard title="Error Rate" status="loading" lastUpdate="">
        <div style={{ height: '80px', background: 'rgba(255,255,255,0.04)', borderRadius: '6px' }} />
      </WidgetCard>
    );
  }
  
  return (
    <WidgetCard
      title="Error Rate"
      status={data.status}
      lastUpdate={data.lastUpdate}
      onRefresh={fetchData}
      onDrillDown={onDrillDown}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
          <span style={{ fontSize: '1.6rem', fontWeight: 700, color: data.currentRate > data.threshold ? '#f87171' : '#6ee7b7' }}>
            {data.currentRate.toFixed(2)}%
          </span>
          <span style={{ color: data.trend === 'increasing' ? '#f87171' : data.trend === 'decreasing' ? '#6ee7b7' : '#6a6a7e', fontSize: '14px' }}>
            {data.trend === 'increasing' ? '↑' : data.trend === 'decreasing' ? '↓' : '→'}
          </span>
        </div>
        
        <div style={{ fontSize: '12px', color: '#6a6a7e' }}>{data.errors24h} errors in last 24h</div>
        
        {data.errorsByType.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {data.errorsByType.slice(0, 3).map((err) => (
              <div key={err.type} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
                <span style={{ color: '#a0a0b4', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{err.type}</span>
                <span style={{ color: '#6a6a7e' }}>{err.count}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </WidgetCard>
  );
}

// ==============================================================================
// Live Dashboard Grid
// ==============================================================================

interface LiveDashboardProps {
  onNavigate?: (path: string) => void;
}

export function LiveDashboard({ onNavigate }: LiveDashboardProps) {
  // Single LiveChannel connection shared across all widgets
  const { isConnected, connectionState, lastEvent } = useLiveChannel({
    modules: ['system', 'ops', 'mlops', 'pipeline'],
  });

  // Dynamically import LLMHealthWidget to avoid circular dependency
  const [LLMHealthWidget, setLLMHealthWidget] = React.useState<React.ComponentType<{
    config?: { refreshInterval?: number };
    onDrillDown?: () => void;
  }> | null>(null);

  React.useEffect(() => {
    import('./LLMHealthWidget').then(mod => setLLMHealthWidget(() => mod.LLMHealthWidget));
  }, []);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
        <h2 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 700, color: '#c8a55a', letterSpacing: '0.04em' }}>
          Live Operations
        </h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px' }}>
          <StatusIndicator status={isConnected ? 'healthy' : 'warning'} size="sm" />
          <span style={{ color: '#6a6a7e', textTransform: 'capitalize' }}>{connectionState}</span>
        </div>
      </div>

      <div className="admin-grid-cards admin-grid-cards--ops">
        <SystemHealthWidget lastEvent={lastEvent} onDrillDown={() => onNavigate?.('/admin/ops/health')} />
        <JobQueueWidget lastEvent={lastEvent} onDrillDown={() => onNavigate?.('/admin/ops/jobs')} />
        <DriftWidget lastEvent={lastEvent} onDrillDown={() => onNavigate?.('/admin/mlops/drift')} />
        {LLMHealthWidget && (
          <LLMHealthWidget config={{ refreshInterval: 30000 }} onDrillDown={() => onNavigate?.('/admin/ops/llm')} />
        )}
        <CostWidget onDrillDown={() => onNavigate?.('/admin/ops/cost')} />
        <SLAWidget onDrillDown={() => onNavigate?.('/admin/ops/sla')} />
        <ErrorRateWidget lastEvent={lastEvent} onDrillDown={() => onNavigate?.('/admin/ops/errors')} />
      </div>
    </div>
  );
}

export default LiveDashboard;

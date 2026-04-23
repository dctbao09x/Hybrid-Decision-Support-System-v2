/**
 * KL Divergence Indicator
 * =======================
 * 
 * Compact indicator showing KL divergence with sparkline trend.
 * Phase 3 - RankingGovernance Telemetry Component
 * 
 * Features:
 * - Real-time KL divergence value
 * - Trend sparkline (last 24 data points)
 * - Threshold-based color coding
 * - Auto-refresh every 60 seconds
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';

// ==============================================================================
// Types
// ==============================================================================

interface KLDataPoint {
  timestamp: string;
  kl_divergence: number;
}

interface KLDivergenceResponse {
  current: number;
  trend: KLDataPoint[];
  threshold: number;
  is_alert: boolean;
  avg_24h: number;
  max_24h: number;
  timestamp: string;
}

type LoadingState = 'idle' | 'loading' | 'success' | 'error';

interface KLDivergenceIndicatorProps {
  refreshInterval?: number;
  compactMode?: boolean;
}

// ==============================================================================
// API functions
// ==============================================================================

function resolveApiBaseUrl(): string {
  const raw = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
  try {
    const parsed = new URL(raw);
    if (parsed.hostname === 'localhost') {
      parsed.hostname = '127.0.0.1';
    }
    return parsed.toString().replace(/\/$/, '');
  } catch {
    return 'http://127.0.0.1:8000';
  }
}

const API_BASE_URL = resolveApiBaseUrl();

async function fetchWithTimeout<T>(url: string, options: RequestInit = {}, timeoutMs = 10000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        'X-Role': 'admin',
        ...options.headers,
      },
    });
    
    if (!response.ok) {
      const errorText = await response.text().catch(() => '');
      throw new Error(errorText || `HTTP ${response.status}`);
    }
    
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

// ==============================================================================
// Component
// ==============================================================================

export function KLDivergenceIndicator({ 
  refreshInterval = 60000,
  compactMode = false
}: KLDivergenceIndicatorProps) {
  const [data, setData] = useState<KLDivergenceResponse | null>(null);
  const [loadingState, setLoadingState] = useState<LoadingState>('idle');
  const [error, setError] = useState<string | null>(null);
  
  const abortControllerRef = useRef<AbortController | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Fetch data
  const fetchData = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();
    
    setLoadingState('loading');
    setError(null);
    
    try {
      const result = await fetchWithTimeout<KLDivergenceResponse>(
        `${API_BASE_URL}/api/v1/governance/kl-divergence`
      );
      
      setData(result);
      setLoadingState('success');
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        return;
      }
      
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch KL divergence';
      setError(errorMessage);
      setLoadingState('error');
    }
  }, []);

  // Generate sparkline path
  const sparklinePath = useMemo(() => {
    if (!data || data.trend.length < 2) return '';
    
    const width = 80;
    const height = 24;
    const padding = 2;
    
    const values = data.trend.map(p => p.kl_divergence);
    const minVal = Math.min(...values, 0);
    const maxVal = Math.max(...values, data.threshold);
    const range = maxVal - minVal || 1;
    
    const points = values.map((val, i) => {
      const x = padding + (i / (values.length - 1)) * (width - 2 * padding);
      const y = height - padding - ((val - minVal) / range) * (height - 2 * padding);
      return { x, y };
    });
    
    return points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
  }, [data]);

  // Threshold line Y position
  const thresholdY = useMemo(() => {
    if (!data || data.trend.length < 2) return 12;
    
    const height = 24;
    const padding = 2;
    
    const values = data.trend.map(p => p.kl_divergence);
    const minVal = Math.min(...values, 0);
    const maxVal = Math.max(...values, data.threshold);
    const range = maxVal - minVal || 1;
    
    return height - padding - ((data.threshold - minVal) / range) * (height - 2 * padding);
  }, [data]);

  // Get status color
  const getStatusColor = () => {
    if (!data) return { bg: 'bg-gray-100 dark:bg-gray-700', text: 'text-gray-600 dark:text-gray-400', line: '#9ca3af' };
    if (data.is_alert) return { bg: 'bg-red-100 dark:bg-red-900/30', text: 'text-red-600 dark:text-red-400', line: '#ef4444' };
    if (data.current > data.threshold * 0.8) return { bg: 'bg-yellow-100 dark:bg-yellow-900/30', text: 'text-yellow-600 dark:text-yellow-400', line: '#f59e0b' };
    return { bg: 'bg-green-100 dark:bg-green-900/30', text: 'text-green-600 dark:text-green-400', line: '#22c55e' };
  };

  // Get trend direction
  const getTrend = () => {
    if (!data || data.trend.length < 2) return 'stable';
    const recent = data.trend.slice(-3).map(p => p.kl_divergence);
    const diff = recent[recent.length - 1] - recent[0];
    if (Math.abs(diff) < 0.01) return 'stable';
    return diff > 0 ? 'up' : 'down';
  };

  const colors = getStatusColor();
  const trend = getTrend();

  // Initial load
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Auto-refresh
  useEffect(() => {
    if (refreshInterval > 0) {
      intervalRef.current = setInterval(fetchData, refreshInterval);
      return () => {
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
        }
      };
    }
  }, [fetchData, refreshInterval]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, []);

  // Compact mode render
  if (compactMode) {
    return (
      <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full ${colors.bg}`}>
        <span className={`text-xs font-medium ${colors.text}`}>KL</span>
        {loadingState === 'loading' && !data ? (
          <span className="text-xs text-gray-500">--</span>
        ) : error ? (
          <span className="text-xs text-red-500">Error</span>
        ) : data ? (
          <>
            <span className={`text-sm font-bold ${colors.text}`}>{data.current.toFixed(3)}</span>
            {trend === 'up' && <span className="text-red-500 text-xs">↑</span>}
            {trend === 'down' && <span className="text-green-500 text-xs">↓</span>}
          </>
        ) : null}
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-semibold text-gray-900 dark:text-white text-sm">KL Divergence</h3>
        <button
          onClick={fetchData}
          disabled={loadingState === 'loading'}
          className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded disabled:opacity-50"
          title="Refresh"
        >
          {loadingState === 'loading' ? (
            <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
          ) : (
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          )}
        </button>
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 rounded p-2 mb-2">
          <p className="text-red-600 dark:text-red-400 text-xs">{error}</p>
        </div>
      )}

      {/* Loading State */}
      {loadingState === 'loading' && !data && (
        <div className="animate-pulse">
          <div className="h-16 bg-gray-200 dark:bg-gray-700 rounded" />
        </div>
      )}

      {/* Content */}
      {data && (
        <div className="space-y-3">
          {/* Main Value */}
          <div className="flex items-center justify-between">
            <div>
              <div className={`text-2xl font-bold ${colors.text}`}>
                {data.current.toFixed(4)}
                {trend === 'up' && <span className="text-red-500 text-lg ml-1">↑</span>}
                {trend === 'down' && <span className="text-green-500 text-lg ml-1">↓</span>}
              </div>
              <div className="text-xs text-gray-500">
                Threshold: {data.threshold.toFixed(3)}
              </div>
            </div>
            
            {/* Sparkline */}
            {sparklinePath && (
              <svg width="80" height="24" className="opacity-80">
                <line
                  x1="0"
                  y1={thresholdY}
                  x2="80"
                  y2={thresholdY}
                  stroke="#ef4444"
                  strokeWidth="1"
                  strokeDasharray="2 2"
                  strokeOpacity="0.5"
                />
                <path
                  d={sparklinePath}
                  fill="none"
                  stroke={colors.line}
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            )}
          </div>

          {/* Status Badge */}
          {data.is_alert && (
            <div className="bg-red-100 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded px-2 py-1">
              <span className="text-xs text-red-600 dark:text-red-400 font-medium">
                ⚠ Distribution drift detected
              </span>
            </div>
          )}

          {/* Stats */}
          <div className="grid grid-cols-2 gap-2 text-center">
            <div className="bg-gray-50 dark:bg-gray-700/50 rounded p-1.5">
              <div className="text-sm font-medium text-gray-900 dark:text-white">{data.avg_24h.toFixed(4)}</div>
              <div className="text-xs text-gray-500">24h Avg</div>
            </div>
            <div className="bg-gray-50 dark:bg-gray-700/50 rounded p-1.5">
              <div className="text-sm font-medium text-gray-900 dark:text-white">{data.max_24h.toFixed(4)}</div>
              <div className="text-xs text-gray-500">24h Max</div>
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="text-xs text-gray-400 mt-2 pt-2 border-t border-gray-100 dark:border-gray-700">
        {data && new Date(data.timestamp).toLocaleTimeString()}
      </div>
    </div>
  );
}

export default KLDivergenceIndicator;

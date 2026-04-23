/**
 * Ranking Volatility Chart
 * ========================
 * 
 * Time-series line chart showing score ranking volatility.
 * Phase 3 - RankingGovernance Telemetry Component
 * 
 * Features:
 * - Volatility index trend line
 * - Threshold indicator
 * - Alert zones highlighting
 * - Auto-refresh every 60 seconds
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';

// ==============================================================================
// Types
// ==============================================================================

interface VolatilityDataPoint {
  timestamp: string;
  volatility_index: number;
  threshold: number;
  is_alert: boolean;
  sample_size: number;
}

interface RankingVolatilityResponse {
  data: VolatilityDataPoint[];
  current_volatility: number;
  avg_volatility_24h: number;
  max_volatility_24h: number;
  alert_count: number;
  threshold: number;
}

type LoadingState = 'idle' | 'loading' | 'success' | 'error';

interface RankingVolatilityChartProps {
  refreshInterval?: number;
  height?: number;
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

export function RankingVolatilityChart({ 
  refreshInterval = 60000,
  height = 280 
}: RankingVolatilityChartProps) {
  const [data, setData] = useState<RankingVolatilityResponse | null>(null);
  const [loadingState, setLoadingState] = useState<LoadingState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  
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
      const result = await fetchWithTimeout<RankingVolatilityResponse>(
        `${API_BASE_URL}/api/v1/governance/ranking-volatility?window_hours=24`
      );
      
      setData(result);
      setLoadingState('success');
      setLastUpdate(new Date());
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        return;
      }
      
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch volatility data';
      setError(errorMessage);
      setLoadingState('error');
    }
  }, []);

  // Calculate chart dimensions
  const chartMetrics = useMemo(() => {
    if (!data || data.data.length === 0) return null;
    
    const padding = { top: 20, right: 20, bottom: 40, left: 60 };
    const width = 600;
    const innerWidth = width - padding.left - padding.right;
    const innerHeight = height - padding.top - padding.bottom;
    
    // Calculate scale based on max volatility
    const maxValue = Math.max(data.max_volatility_24h * 1.2, data.threshold * 1.5, 0.3);
    
    const xScale = (i: number) => padding.left + (i / Math.max(data.data.length - 1, 1)) * innerWidth;
    const yScale = (v: number) => padding.top + innerHeight - (v / maxValue) * innerHeight;
    
    return { padding, width, height, innerWidth, innerHeight, maxValue, xScale, yScale };
  }, [data, height]);

  // Generate line path
  const linePath = useMemo(() => {
    if (!chartMetrics || !data || data.data.length === 0) return '';
    
    return data.data.map((point, i) => {
      const x = chartMetrics.xScale(i);
      const y = chartMetrics.yScale(point.volatility_index);
      return `${i === 0 ? 'M' : 'L'} ${x} ${y}`;
    }).join(' ');
  }, [data, chartMetrics]);

  // Generate area path for alerts
  const alertAreaPath = useMemo(() => {
    if (!chartMetrics || !data || data.data.length === 0) return '';
    
    const alertPoints = data.data
      .map((point, i) => ({ ...point, index: i }))
      .filter(p => p.is_alert);
    
    if (alertPoints.length === 0) return '';
    
    // Find contiguous alert regions
    const regions: number[][] = [];
    let currentRegion: number[] = [];
    
    alertPoints.forEach((p, i) => {
      if (i === 0 || p.index !== alertPoints[i - 1].index + 1) {
        if (currentRegion.length > 0) {
          regions.push(currentRegion);
        }
        currentRegion = [p.index];
      } else {
        currentRegion.push(p.index);
      }
    });
    if (currentRegion.length > 0) {
      regions.push(currentRegion);
    }
    
    // Build rect paths for each region
    return regions.map(region => {
      const startX = chartMetrics.xScale(region[0]) - 2;
      const endX = chartMetrics.xScale(region[region.length - 1]) + 2;
      return `M ${startX} ${chartMetrics.padding.top} L ${endX} ${chartMetrics.padding.top} L ${endX} ${chartMetrics.height - chartMetrics.padding.bottom} L ${startX} ${chartMetrics.height - chartMetrics.padding.bottom} Z`;
    }).join(' ');
  }, [data, chartMetrics]);

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

  // Format time for X axis
  const formatTime = (ts: string) => {
    const date = new Date(ts);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  // Get status color
  const getStatusColor = () => {
    if (!data) return 'text-gray-500';
    if (data.current_volatility > data.threshold) return 'text-red-500';
    if (data.current_volatility > data.threshold * 0.8) return 'text-yellow-500';
    return 'text-green-500';
  };

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h3 className="font-semibold text-gray-900 dark:text-white">Ranking Volatility</h3>
          {data && (
            <span className={`text-sm font-mono ${getStatusColor()}`}>
              {(data.current_volatility * 100).toFixed(1)}%
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {lastUpdate && (
            <span className="text-xs text-gray-500">
              Updated {lastUpdate.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={fetchData}
            disabled={loadingState === 'loading'}
            className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded disabled:opacity-50"
            title="Refresh"
          >
            {loadingState === 'loading' ? (
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Stats Row */}
      {data && (
        <div className="grid grid-cols-4 gap-2 mb-3">
          <div className="text-center p-2 bg-gray-50 dark:bg-gray-700/50 rounded">
            <div className="text-lg font-bold text-gray-900 dark:text-white">
              {(data.current_volatility * 100).toFixed(1)}%
            </div>
            <div className="text-xs text-gray-500">Current</div>
          </div>
          <div className="text-center p-2 bg-gray-50 dark:bg-gray-700/50 rounded">
            <div className="text-lg font-bold text-gray-900 dark:text-white">
              {(data.avg_volatility_24h * 100).toFixed(1)}%
            </div>
            <div className="text-xs text-gray-500">24h Avg</div>
          </div>
          <div className="text-center p-2 bg-gray-50 dark:bg-gray-700/50 rounded">
            <div className="text-lg font-bold text-gray-900 dark:text-white">
              {(data.max_volatility_24h * 100).toFixed(1)}%
            </div>
            <div className="text-xs text-gray-500">24h Max</div>
          </div>
          <div className="text-center p-2 bg-gray-50 dark:bg-gray-700/50 rounded">
            <div className={`text-lg font-bold ${data.alert_count > 0 ? 'text-red-500' : 'text-green-500'}`}>
              {data.alert_count}
            </div>
            <div className="text-xs text-gray-500">Alerts</div>
          </div>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-3 mb-3">
          <p className="text-red-600 dark:text-red-400 text-sm">{error}</p>
        </div>
      )}

      {/* Loading State */}
      {loadingState === 'loading' && !data && (
        <div className="animate-pulse">
          <div className="h-48 bg-gray-200 dark:bg-gray-700 rounded" />
        </div>
      )}

      {/* Empty State */}
      {loadingState === 'success' && (!data || data.data.length === 0) && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          <svg className="w-12 h-12 mx-auto mb-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
          </svg>
          <p>No volatility data available</p>
        </div>
      )}

      {/* Chart */}
      {chartMetrics && data && data.data.length > 0 && (
        <svg 
          viewBox={`0 0 ${chartMetrics.width} ${chartMetrics.height}`}
          className="w-full"
          style={{ height: `${height}px` }}
        >
          {/* Alert zones */}
          {alertAreaPath && (
            <path
              d={alertAreaPath}
              fill="#ef4444"
              fillOpacity={0.1}
            />
          )}

          {/* Grid lines */}
          {[0, 0.25, 0.5, 0.75, 1].map(ratio => (
            <line
              key={ratio}
              x1={chartMetrics.padding.left}
              y1={chartMetrics.padding.top + chartMetrics.innerHeight * (1 - ratio)}
              x2={chartMetrics.width - chartMetrics.padding.right}
              y2={chartMetrics.padding.top + chartMetrics.innerHeight * (1 - ratio)}
              stroke="currentColor"
              strokeOpacity={0.1}
              strokeDasharray={ratio === 0 ? 'none' : '4 4'}
            />
          ))}

          {/* Threshold line */}
          <line
            x1={chartMetrics.padding.left}
            y1={chartMetrics.yScale(data.threshold)}
            x2={chartMetrics.width - chartMetrics.padding.right}
            y2={chartMetrics.yScale(data.threshold)}
            stroke="#ef4444"
            strokeWidth={2}
            strokeDasharray="6 4"
          />
          <text
            x={chartMetrics.width - chartMetrics.padding.right + 5}
            y={chartMetrics.yScale(data.threshold) + 4}
            className="text-xs fill-red-500"
          >
            Threshold
          </text>

          {/* Y axis labels */}
          {[0, 0.5, 1].map(ratio => (
            <text
              key={ratio}
              x={chartMetrics.padding.left - 8}
              y={chartMetrics.padding.top + chartMetrics.innerHeight * (1 - ratio) + 4}
              textAnchor="end"
              className="text-xs fill-gray-500"
            >
              {(chartMetrics.maxValue * ratio * 100).toFixed(0)}%
            </text>
          ))}

          {/* Line path */}
          <path
            d={linePath}
            fill="none"
            stroke="#3b82f6"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Data points */}
          {data.data.map((point, i) => (
            <circle
              key={i}
              cx={chartMetrics.xScale(i)}
              cy={chartMetrics.yScale(point.volatility_index)}
              r={point.is_alert ? 4 : 2}
              fill={point.is_alert ? '#ef4444' : '#3b82f6'}
            />
          ))}

          {/* X axis labels */}
          {data.data.filter((_, i) => i % Math.ceil(data.data.length / 6) === 0).map((point, idx) => {
            const i = data.data.indexOf(point);
            return (
              <text
                key={idx}
                x={chartMetrics.xScale(i)}
                y={chartMetrics.height - 10}
                textAnchor="middle"
                className="text-xs fill-gray-500"
              >
                {formatTime(point.timestamp)}
              </text>
            );
          })}
        </svg>
      )}

      {/* Footer */}
      <div className="text-xs text-gray-500 dark:text-gray-400 mt-2 pt-2 border-t border-gray-100 dark:border-gray-700 flex justify-between">
        <span>24-hour window • Threshold: {data ? (data.threshold * 100).toFixed(0) : '--'}%</span>
        <span>Auto-refresh every {refreshInterval / 1000}s</span>
      </div>
    </div>
  );
}

export default RankingVolatilityChart;

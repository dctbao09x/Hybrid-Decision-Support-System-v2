/**
 * Ranking Frequency Chart
 * =======================
 * 
 * Bar chart showing score value distribution frequency.
 * Phase 3 - RankingGovernance Telemetry Component
 * 
 * Features:
 * - Frequency buckets 0-100
 * - Mean line indicator
 * - Top N value highlighting
 * - Auto-refresh every 60 seconds
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';

// ==============================================================================
// Types
// ==============================================================================

interface FrequencyBucket {
  range_start: number;
  range_end: number;
  count: number;
  percentage: number;
}

interface RankingFrequencyResponse {
  buckets: FrequencyBucket[];
  total_samples: number;
  mean_value: number;
  median_value: number;
  std_deviation: number;
  min_value: number;
  max_value: number;
  timestamp: string;
}

type LoadingState = 'idle' | 'loading' | 'success' | 'error';

interface RankingFrequencyChartProps {
  refreshInterval?: number;
  height?: number;
  highlightTopN?: number;
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

export function RankingFrequencyChart({ 
  refreshInterval = 60000,
  height = 280,
  highlightTopN = 3
}: RankingFrequencyChartProps) {
  const [data, setData] = useState<RankingFrequencyResponse | null>(null);
  const [loadingState, setLoadingState] = useState<LoadingState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [hoveredBucket, setHoveredBucket] = useState<number | null>(null);
  
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
      const result = await fetchWithTimeout<RankingFrequencyResponse>(
        `${API_BASE_URL}/api/v1/governance/ranking-frequency`
      );
      
      setData(result);
      setLoadingState('success');
      setLastUpdate(new Date());
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        return;
      }
      
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch frequency data';
      setError(errorMessage);
      setLoadingState('error');
    }
  }, []);

  // Calculate chart metrics
  const chartMetrics = useMemo(() => {
    if (!data || data.buckets.length === 0) return null;
    
    const padding = { top: 20, right: 20, bottom: 50, left: 50 };
    const width = 600;
    const innerWidth = width - padding.left - padding.right;
    const innerHeight = height - padding.top - padding.bottom;
    
    const maxCount = Math.max(...data.buckets.map(b => b.count));
    const barWidth = innerWidth / data.buckets.length - 2;
    
    const xScale = (i: number) => padding.left + (i / data.buckets.length) * innerWidth + 1;
    const yScale = (v: number) => padding.top + innerHeight - (v / Math.max(maxCount, 1)) * innerHeight;
    const meanX = padding.left + (data.mean_value / 100) * innerWidth;
    
    return { padding, width, height, innerWidth, innerHeight, maxCount, barWidth, xScale, yScale, meanX };
  }, [data, height]);

  // Identify top N buckets
  const topBuckets = useMemo(() => {
    if (!data) return new Set<number>();
    
    const sorted = data.buckets
      .map((b, i) => ({ count: b.count, index: i }))
      .sort((a, b) => b.count - a.count)
      .slice(0, highlightTopN);
    
    return new Set(sorted.map(b => b.index));
  }, [data, highlightTopN]);

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

  // Get bar color
  const getBarColor = (index: number, isHovered: boolean) => {
    if (topBuckets.has(index)) {
      return isHovered ? '#16a34a' : '#22c55e'; // Green for top buckets
    }
    return isHovered ? '#2563eb' : '#3b82f6'; // Blue for normal
  };

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-900 dark:text-white">Ranking Value Distribution</h3>
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
        <div className="grid grid-cols-5 gap-2 mb-3">
          <div className="text-center p-2 bg-gray-50 dark:bg-gray-700/50 rounded">
            <div className="text-sm font-bold text-gray-900 dark:text-white">
              {data.mean_value.toFixed(1)}
            </div>
            <div className="text-xs text-gray-500">Mean</div>
          </div>
          <div className="text-center p-2 bg-gray-50 dark:bg-gray-700/50 rounded">
            <div className="text-sm font-bold text-gray-900 dark:text-white">
              {data.median_value.toFixed(1)}
            </div>
            <div className="text-xs text-gray-500">Median</div>
          </div>
          <div className="text-center p-2 bg-gray-50 dark:bg-gray-700/50 rounded">
            <div className="text-sm font-bold text-gray-900 dark:text-white">
              {data.std_deviation.toFixed(2)}
            </div>
            <div className="text-xs text-gray-500">Std Dev</div>
          </div>
          <div className="text-center p-2 bg-gray-50 dark:bg-gray-700/50 rounded">
            <div className="text-sm font-bold text-gray-900 dark:text-white">
              {data.min_value.toFixed(0)}-{data.max_value.toFixed(0)}
            </div>
            <div className="text-xs text-gray-500">Range</div>
          </div>
          <div className="text-center p-2 bg-gray-50 dark:bg-gray-700/50 rounded">
            <div className="text-sm font-bold text-gray-900 dark:text-white">
              {data.total_samples.toLocaleString()}
            </div>
            <div className="text-xs text-gray-500">Samples</div>
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
      {loadingState === 'success' && (!data || data.buckets.length === 0) && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          <svg className="w-12 h-12 mx-auto mb-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M16 8v8m-4-5v5m-4-2v2m-2 4h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          <p>No distribution data available</p>
        </div>
      )}

      {/* Chart */}
      {chartMetrics && data && data.buckets.length > 0 && (
        <div className="relative">
          <svg 
            viewBox={`0 0 ${chartMetrics.width} ${chartMetrics.height}`}
            className="w-full"
            style={{ height: `${height}px` }}
          >
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

            {/* Y axis labels */}
            {[0, 0.5, 1].map(ratio => (
              <text
                key={ratio}
                x={chartMetrics.padding.left - 8}
                y={chartMetrics.padding.top + chartMetrics.innerHeight * (1 - ratio) + 4}
                textAnchor="end"
                className="text-xs fill-gray-500"
              >
                {Math.round(chartMetrics.maxCount * ratio)}
              </text>
            ))}

            {/* Bars */}
            {data.buckets.map((bucket, i) => {
              const barHeight = (bucket.count / chartMetrics.maxCount) * chartMetrics.innerHeight;
              const isHovered = hoveredBucket === i;
              
              return (
                <g key={i}>
                  <rect
                    x={chartMetrics.xScale(i)}
                    y={chartMetrics.padding.top + chartMetrics.innerHeight - barHeight}
                    width={chartMetrics.barWidth}
                    height={barHeight}
                    fill={getBarColor(i, isHovered)}
                    fillOpacity={isHovered ? 1 : 0.8}
                    rx={1}
                    onMouseEnter={() => setHoveredBucket(i)}
                    onMouseLeave={() => setHoveredBucket(null)}
                    className="cursor-pointer transition-opacity"
                  />
                  {/* Tooltip on hover */}
                  {isHovered && (
                    <g>
                      <rect
                        x={chartMetrics.xScale(i) - 20}
                        y={chartMetrics.padding.top + chartMetrics.innerHeight - barHeight - 35}
                        width={chartMetrics.barWidth + 40}
                        height={30}
                        fill="rgba(0,0,0,0.8)"
                        rx={4}
                      />
                      <text
                        x={chartMetrics.xScale(i) + chartMetrics.barWidth / 2}
                        y={chartMetrics.padding.top + chartMetrics.innerHeight - barHeight - 18}
                        textAnchor="middle"
                        className="text-xs fill-white font-medium"
                      >
                        {bucket.range_start.toFixed(0)}-{bucket.range_end.toFixed(0)}: {bucket.count}
                      </text>
                    </g>
                  )}
                </g>
              );
            })}

            {/* Mean line */}
            <line
              x1={chartMetrics.meanX}
              y1={chartMetrics.padding.top}
              x2={chartMetrics.meanX}
              y2={chartMetrics.height - chartMetrics.padding.bottom}
              stroke="#ef4444"
              strokeWidth={2}
              strokeDasharray="4 4"
            />
            <text
              x={chartMetrics.meanX}
              y={chartMetrics.padding.top - 5}
              textAnchor="middle"
              className="text-xs fill-red-500 font-medium"
            >
              μ={data.mean_value.toFixed(1)}
            </text>

            {/* X axis labels */}
            {[0, 25, 50, 75, 100].map(value => (
              <text
                key={value}
                x={chartMetrics.padding.left + (value / 100) * chartMetrics.innerWidth}
                y={chartMetrics.height - 10}
                textAnchor="middle"
                className="text-xs fill-gray-500"
              >
                {value}
              </text>
            ))}
          </svg>

          {/* Legend */}
          <div className="flex gap-4 justify-center mt-2">
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-sm bg-blue-500" />
              <span className="text-xs text-gray-600 dark:text-gray-400">Normal</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-3 rounded-sm bg-green-500" />
              <span className="text-xs text-gray-600 dark:text-gray-400">Top {highlightTopN}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-3 h-0.5 bg-red-500" />
              <span className="text-xs text-gray-600 dark:text-gray-400">Mean</span>
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="text-xs text-gray-500 dark:text-gray-400 mt-2 pt-2 border-t border-gray-100 dark:border-gray-700">
        {data && `${data.buckets.length} buckets • `}Auto-refresh every {refreshInterval / 1000}s
      </div>
    </div>
  );
}

export default RankingFrequencyChart;

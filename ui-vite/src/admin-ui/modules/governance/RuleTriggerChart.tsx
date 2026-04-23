/**
 * Rule Trigger Chart
 * ==================
 * 
 * Time-series chart showing governance rule trigger frequency.
 * Phase 3 - RankingGovernance Telemetry Component
 * 
 * Features:
 * - 24h sliding window
 * - Stacked area chart by rule type
 * - Auto-refresh every 60 seconds
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';

// ==============================================================================
// Types
// ==============================================================================

interface RuleTriggerEntry {
  timestamp: string;
  rule_name: string;
  trigger_count: number;
  severity: 'info' | 'warning' | 'critical';
}

interface ProcessedDataPoint {
  timestamp: string;
  [ruleName: string]: string | number;
}

type LoadingState = 'idle' | 'loading' | 'success' | 'error';

interface RuleTriggerChartProps {
  refreshInterval?: number;
  height?: number;
}

// ==============================================================================
// Constants
// ==============================================================================

const RULE_COLORS = [
  '#3b82f6', // blue
  '#10b981', // emerald
  '#f59e0b', // amber
  '#ef4444', // red
  '#8b5cf6', // violet
  '#06b6d4', // cyan
  '#ec4899', // pink
  '#6b7280', // gray
];

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

export function RuleTriggerChart({ 
  refreshInterval = 60000,
  height = 300 
}: RuleTriggerChartProps) {
  const [data, setData] = useState<RuleTriggerEntry[]>([]);
  const [loadingState, setLoadingState] = useState<LoadingState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  
  const abortControllerRef = useRef<AbortController | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  // Fetch data
  const fetchData = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();
    
    setLoadingState('loading');
    setError(null);
    
    try {
      const result = await fetchWithTimeout<RuleTriggerEntry[]>(
        `${API_BASE_URL}/api/v1/governance/rule-triggers?window_hours=24`
      );
      
      setData(result);
      setLoadingState('success');
      setLastUpdate(new Date());
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        return;
      }
      
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch rule triggers';
      setError(errorMessage);
      setLoadingState('error');
    }
  }, []);

  // Process data for chart
  const chartData = useMemo(() => {
    if (data.length === 0) return { points: [] as ProcessedDataPoint[], rules: [] as string[] };
    
    // Get unique rules and timestamps
    const rules = [...new Set(data.map(d => d.rule_name))];
    const timestamps = [...new Set(data.map(d => d.timestamp))].sort();
    
    // Build data points
    const points: ProcessedDataPoint[] = timestamps.map(ts => {
      const point: ProcessedDataPoint = { timestamp: ts };
      rules.forEach(rule => {
        const entry = data.find(d => d.timestamp === ts && d.rule_name === rule);
        point[rule] = entry?.trigger_count || 0;
      });
      return point;
    });
    
    return { points, rules };
  }, [data]);

  // Calculate chart dimensions
  const chartMetrics = useMemo(() => {
    const { points, rules } = chartData;
    if (points.length === 0) return null;
    
    const padding = { top: 20, right: 20, bottom: 40, left: 50 };
    const width = 600;
    const innerWidth = width - padding.left - padding.right;
    const innerHeight = height - padding.top - padding.bottom;
    
    // Calculate max stacked value
    let maxValue = 0;
    points.forEach(point => {
      let sum = 0;
      rules.forEach(rule => {
        sum += (point[rule] as number) || 0;
      });
      maxValue = Math.max(maxValue, sum);
    });
    
    const xScale = (i: number) => padding.left + (i / Math.max(points.length - 1, 1)) * innerWidth;
    const yScale = (v: number) => padding.top + innerHeight - (v / Math.max(maxValue, 1)) * innerHeight;
    
    return { padding, width, height, innerWidth, innerHeight, maxValue, xScale, yScale };
  }, [chartData, height]);

  // Generate stacked area paths
  const areaPaths = useMemo(() => {
    const { points, rules } = chartData;
    if (!chartMetrics || points.length === 0) return [];
    
    const { xScale, yScale } = chartMetrics;
    
    return rules.map((rule, ruleIndex) => {
      // Calculate stacked values
      const stackedPoints = points.map((point, i) => {
        let y0 = 0;
        for (let j = 0; j < ruleIndex; j++) {
          y0 += (point[rules[j]] as number) || 0;
        }
        const y1 = y0 + ((point[rule] as number) || 0);
        return { x: xScale(i), y0, y1 };
      });
      
      // Build path
      const upperPath = stackedPoints.map((p, i) => 
        `${i === 0 ? 'M' : 'L'} ${p.x} ${yScale(p.y1)}`
      ).join(' ');
      
      const lowerPath = stackedPoints.slice().reverse().map((p) => 
        `L ${p.x} ${yScale(p.y0)}`
      ).join(' ');
      
      return {
        rule,
        path: `${upperPath} ${lowerPath} Z`,
        color: RULE_COLORS[ruleIndex % RULE_COLORS.length],
      };
    });
  }, [chartData, chartMetrics]);

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

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-900 dark:text-white">Rule Trigger Frequency</h3>
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

      {/* Error State */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-3 mb-3">
          <p className="text-red-600 dark:text-red-400 text-sm">{error}</p>
        </div>
      )}

      {/* Loading State */}
      {loadingState === 'loading' && data.length === 0 && (
        <div className="animate-pulse">
          <div className="h-64 bg-gray-200 dark:bg-gray-700 rounded" />
        </div>
      )}

      {/* Empty State */}
      {loadingState === 'success' && data.length === 0 && (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          <svg className="w-12 h-12 mx-auto mb-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
          <p>No rule triggers in the last 24 hours</p>
        </div>
      )}

      {/* Chart */}
      {chartMetrics && areaPaths.length > 0 && (
        <div className="relative">
          <svg 
            ref={svgRef}
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
                {Math.round(chartMetrics.maxValue * ratio)}
              </text>
            ))}

            {/* Area paths */}
            {areaPaths.map(({ rule, path, color }) => (
              <path
                key={rule}
                d={path}
                fill={color}
                fillOpacity={0.6}
                stroke={color}
                strokeWidth={1}
              />
            ))}

            {/* X axis labels */}
            {chartData.points.filter((_, i) => i % Math.ceil(chartData.points.length / 6) === 0).map((point, i) => {
              const index = chartData.points.indexOf(point);
              return (
                <text
                  key={i}
                  x={chartMetrics.xScale(index)}
                  y={chartMetrics.height - 10}
                  textAnchor="middle"
                  className="text-xs fill-gray-500"
                >
                  {formatTime(point.timestamp)}
                </text>
              );
            })}
          </svg>

          {/* Legend */}
          <div className="flex flex-wrap gap-3 mt-3 justify-center">
            {chartData.rules.map((rule, i) => (
              <div key={rule} className="flex items-center gap-1.5">
                <div 
                  className="w-3 h-3 rounded-sm"
                  style={{ backgroundColor: RULE_COLORS[i % RULE_COLORS.length] }}
                />
                <span className="text-xs text-gray-600 dark:text-gray-400">{rule}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="text-xs text-gray-500 dark:text-gray-400 mt-3 pt-2 border-t border-gray-100 dark:border-gray-700">
        24-hour sliding window • Auto-refresh every {refreshInterval / 1000}s
      </div>
    </div>
  );
}

export default RuleTriggerChart;

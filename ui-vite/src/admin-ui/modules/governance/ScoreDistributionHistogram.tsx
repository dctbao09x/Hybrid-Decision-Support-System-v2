/**
 * Score Distribution Histogram
 * ============================
 * 
 * Displays score distribution histogram with drift indicators.
 * Phase 1 - Critical Visibility Component
 * 
 * Features:
 * - Histogram buckets 0-100
 * - Drift threshold highlighting
 * - Auto-refresh with configurable interval
 * - Manual refresh button
 * - Statistics display (mean, std, total samples)
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { apiRequest } from '../../services/apiClient';

// ==============================================================================
// Types
// ==============================================================================

interface ScoreDistributionBucket {
  range_start: number;
  range_end: number;
  count: number;
  percentage: number;
  is_drift: boolean;
}

interface ScoreDistributionData {
  component: string;
  buckets: ScoreDistributionBucket[];
  total_samples: number;
  mean: number;
  std_deviation: number;
  psi: number;
  kl_divergence: number;
  drift_threshold: number;
  is_drift_active: boolean;
  last_update: string;
}

type LoadingState = 'idle' | 'loading' | 'success' | 'error';

interface ScoreDistributionHistogramProps {
  component?: string;
  refreshInterval?: number;  // ms, default 60000
  onDrillDown?: () => void;
  showStats?: boolean;
}

// ==============================================================================
// Component
// ==============================================================================

export function ScoreDistributionHistogram({
  component = 'final',
  refreshInterval = 60000,
  onDrillDown,
  showStats = true,
}: ScoreDistributionHistogramProps) {
  const [data, setData] = useState<ScoreDistributionData | null>(null);
  const [loadingState, setLoadingState] = useState<LoadingState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  
  const abortControllerRef = useRef<AbortController | null>(null);
  const intervalRef = useRef<number | null>(null);

  // Fetch data with retry logic
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
      const params = component ? `?component=${component}` : '';
      const result = await apiRequest<ScoreDistributionData[]>(
        `/api/v1/governance/score-distribution${params}`
      );
      
      // Find the matching component or use first result
      const componentData = result.find(d => d.component === component) || result[0];
      
      if (componentData) {
        setData(componentData);
        setLoadingState('success');
        setRetryCount(0);
      } else {
        throw new Error('No distribution data available');
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        return; // Ignore abort errors
      }
      
      const errorMessage = err instanceof Error ? err.message : 'Failed to load distribution data';
      setError(errorMessage);
      setLoadingState('error');
      
      // Exponential backoff retry (max 3 retries)
      if (retryCount < 3) {
        const delay = Math.min(1000 * Math.pow(2, retryCount), 8000);
        setTimeout(() => {
          setRetryCount(prev => prev + 1);
          fetchData(true);
        }, delay);
      }
    }
  }, [component, retryCount]);

  // Initial fetch and interval setup
  useEffect(() => {
    fetchData();
    
    intervalRef.current = window.setInterval(() => {
      fetchData();
    }, refreshInterval);
    
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      if (intervalRef.current) {
        window.clearInterval(intervalRef.current);
      }
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

  // Get max count for scaling
  const maxCount = data?.buckets.reduce((max, b) => Math.max(max, b.count), 0) || 1;

  // Render loading skeleton
  if (loadingState === 'loading' && !data) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-4">
        <div className="animate-pulse">
          <div className="h-6 bg-gray-200 dark:bg-gray-700 rounded w-1/3 mb-4" />
          <div className="h-40 bg-gray-200 dark:bg-gray-700 rounded mb-4" />
          <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-2/3" />
        </div>
      </div>
    );
  }

  // Render error state
  if (loadingState === 'error' && !data) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-900 dark:text-white">Score Distribution</h3>
          <button
            onClick={() => fetchData()}
            className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded text-sm text-blue-600"
          >
            Retry
          </button>
        </div>
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
          <p className="text-red-600 dark:text-red-400 text-sm">{error}</p>
          {retryCount > 0 && (
            <p className="text-red-500 text-xs mt-1">
              Retrying... ({retryCount}/3)
            </p>
          )}
        </div>
      </div>
    );
  }

  // Render empty state
  if (!data || data.total_samples === 0) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-900 dark:text-white">Score Distribution</h3>
          <button
            onClick={() => fetchData()}
            className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
            title="Refresh"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
        </div>
        <div className="text-center py-8 text-gray-500 dark:text-gray-400">
          <svg className="w-12 h-12 mx-auto mb-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
          <p>No distribution data available</p>
          <p className="text-xs mt-1">Scores will appear as they are recorded</p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span 
            className={`inline-block w-3 h-3 rounded-full ${
              data.is_drift_active ? 'bg-red-500 animate-pulse' : 'bg-green-500'
            }`}
            title={data.is_drift_active ? 'Drift detected' : 'Stable'}
          />
          <h3 className="font-semibold text-gray-900 dark:text-white">
            Score Distribution
            <span className="text-sm font-normal text-gray-500 ml-2">({data.component})</span>
          </h3>
        </div>
        <div className="flex items-center gap-2">
          {loadingState === 'loading' && (
            <svg className="w-4 h-4 animate-spin text-gray-400" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
          )}
          <button
            onClick={() => fetchData()}
            className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
            title="Refresh"
            disabled={loadingState === 'loading'}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
          {onDrillDown && (
            <button
              onClick={onDrillDown}
              className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
              title="View Details"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Drift Alert */}
      {data.is_drift_active && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-3 mb-4">
          <div className="flex items-center gap-2">
            <svg className="w-5 h-5 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span className="text-red-600 dark:text-red-400 text-sm font-medium">
              Drift Alert: PSI = {(data.psi * 100).toFixed(2)}% (threshold: {(data.drift_threshold * 100).toFixed(0)}%)
            </span>
          </div>
        </div>
      )}

      {/* Histogram */}
      <div className="relative h-40 flex items-end gap-1" role="img" aria-label="Score distribution histogram">
        {data.buckets.map((bucket, idx) => {
          const height = maxCount > 0 ? (bucket.count / maxCount) * 100 : 0;
          const rangeLabel = `${Math.round(bucket.range_start * 100)}-${Math.round(bucket.range_end * 100)}`;
          
          return (
            <div
              key={idx}
              className="flex-1 flex flex-col items-center group"
            >
              <div className="relative w-full flex-1 flex items-end">
                <div
                  className={`w-full transition-all duration-300 rounded-t ${
                    bucket.is_drift
                      ? 'bg-red-500 dark:bg-red-600'
                      : 'bg-blue-500 dark:bg-blue-600 hover:bg-blue-600 dark:hover:bg-blue-500'
                  }`}
                  style={{ height: `${height}%`, minHeight: bucket.count > 0 ? '4px' : '0' }}
                  title={`${rangeLabel}: ${bucket.count} samples (${bucket.percentage.toFixed(1)}%)`}
                />
                
                {/* Tooltip */}
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 bg-gray-900 dark:bg-gray-700 text-white text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-10">
                  <div>{rangeLabel}%</div>
                  <div>{bucket.count} ({bucket.percentage.toFixed(1)}%)</div>
                  {bucket.is_drift && <div className="text-red-300">Drift ⚠️</div>}
                </div>
              </div>
              
              {/* X-axis label */}
              <span className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                {idx % 2 === 0 ? rangeLabel : ''}
              </span>
            </div>
          );
        })}
      </div>

      {/* Statistics */}
      {showStats && (
        <div className="mt-4 pt-3 border-t border-gray-100 dark:border-gray-700">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div>
              <span className="text-gray-500 dark:text-gray-400">Total Samples</span>
              <div className="font-semibold text-gray-900 dark:text-white">
                {data.total_samples.toLocaleString()}
              </div>
            </div>
            <div>
              <span className="text-gray-500 dark:text-gray-400">Mean</span>
              <div className="font-semibold text-gray-900 dark:text-white">
                {(data.mean * 100).toFixed(2)}%
              </div>
            </div>
            <div>
              <span className="text-gray-500 dark:text-gray-400">Std Dev</span>
              <div className="font-semibold text-gray-900 dark:text-white">
                {(data.std_deviation * 100).toFixed(2)}%
              </div>
            </div>
            <div>
              <span className="text-gray-500 dark:text-gray-400">PSI / KL</span>
              <div className={`font-semibold ${
                data.psi > data.drift_threshold ? 'text-red-600' : 'text-gray-900 dark:text-white'
              }`}>
                {data.psi.toFixed(4)} / {data.kl_divergence.toFixed(4)}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="text-xs text-gray-500 dark:text-gray-400 mt-3 pt-2 border-t border-gray-100 dark:border-gray-700">
        Last updated: {formatTime(data.last_update)}
      </div>
    </div>
  );
}

export default ScoreDistributionHistogram;

/**
 * Model Comparison Panel
 * ======================
 * 
 * Side-by-side comparison of two model versions.
 * Phase 2 - Canary & Governance Control Component
 * 
 * Features:
 * - Dropdown selectors for model A and B
 * - Side-by-side metrics comparison
 * - Delta highlighting with configurable threshold
 * - Recommendation display
 */

import { useState, useEffect, useCallback, useRef } from 'react';

// ==============================================================================
// Types
// ==============================================================================

interface ModelMetrics {
  model_id: string;
  version: string;
  accuracy: number;
  precision: number;
  recall: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
  drift_score: number;
  error_rate: number;
  samples: number;
}

interface ModelComparisonData {
  model_a: ModelMetrics;
  model_b: ModelMetrics;
  delta: Record<string, number>;
  recommendation: 'PROMOTE_B' | 'KEEP_A' | 'CONTINUE_TESTING';
  timestamp: string;
}

interface ModelInfo {
  model_id: string;
  version: string;
  status: string;
}

type LoadingState = 'idle' | 'loading' | 'success' | 'error';

interface ModelComparisonPanelProps {
  deltaThreshold?: number;  // Threshold for highlighting significant deltas
  onPromote?: (modelId: string) => void;
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

export function ModelComparisonPanel({ 
  deltaThreshold = 0.02,
  onPromote 
}: ModelComparisonPanelProps) {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelA, setModelA] = useState<string>('');
  const [modelB, setModelB] = useState<string>('');
  const [comparison, setComparison] = useState<ModelComparisonData | null>(null);
  const [loadingState, setLoadingState] = useState<LoadingState>('idle');
  const [error, setError] = useState<string | null>(null);
  
  const abortControllerRef = useRef<AbortController | null>(null);

  // Fetch available models
  const fetchModels = useCallback(async () => {
    try {
      const response = await fetchWithTimeout<{ items: ModelInfo[] }>(
        `${API_BASE_URL}/api/v1/mlops/models`
      );
      const modelList = response.items || [];
      setModels(modelList);
      
      // Auto-select first two models if available
      if (modelList.length >= 2 && !modelA && !modelB) {
        const prodModel = modelList.find(m => m.status === 'prod');
        const candidateModel = modelList.find(m => m.status !== 'prod') || modelList[1];
        
        if (prodModel) {
          setModelA(prodModel.model_id);
        } else {
          setModelA(modelList[0].model_id);
        }
        
        if (candidateModel && candidateModel.model_id !== (prodModel?.model_id || modelList[0].model_id)) {
          setModelB(candidateModel.model_id);
        }
      }
    } catch (err) {
      console.error('Failed to fetch models:', err);
    }
  }, [modelA, modelB]);

  // Fetch comparison data
  const fetchComparison = useCallback(async () => {
    if (!modelA || !modelB) {
      setComparison(null);
      return;
    }
    
    if (modelA === modelB) {
      setError('Please select different models for comparison');
      return;
    }
    
    // Abort any pending request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();
    
    setLoadingState('loading');
    setError(null);
    
    try {
      const result = await fetchWithTimeout<ModelComparisonData>(
        `${API_BASE_URL}/api/v1/mlops/compare?model_a=${encodeURIComponent(modelA)}&model_b=${encodeURIComponent(modelB)}`
      );
      
      setComparison(result);
      setLoadingState('success');
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        return;
      }
      
      const errorMessage = err instanceof Error ? err.message : 'Failed to compare models';
      setError(errorMessage);
      setLoadingState('error');
    }
  }, [modelA, modelB]);

  // Initial load
  useEffect(() => {
    fetchModels();
  }, [fetchModels]);

  // Fetch comparison when models change
  useEffect(() => {
    if (modelA && modelB && modelA !== modelB) {
      fetchComparison();
    }
  }, [modelA, modelB, fetchComparison]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  // Get delta color class
  const getDeltaClass = (metric: string, delta: number): string => {
    const isPositiveBetter = ['accuracy', 'precision', 'recall'].includes(metric);
    const isNegativeBetter = ['latency_p50_ms', 'latency_p95_ms', 'drift_score', 'error_rate'].includes(metric);
    
    const absChange = Math.abs(delta);
    if (absChange < 0.001) return 'text-gray-500';
    
    if (isPositiveBetter) {
      return delta > deltaThreshold ? 'text-green-600 font-bold' : 
             delta < -deltaThreshold ? 'text-red-600 font-bold' : 'text-gray-900 dark:text-white';
    }
    
    if (isNegativeBetter) {
      return delta < -deltaThreshold ? 'text-green-600 font-bold' : 
             delta > deltaThreshold ? 'text-red-600 font-bold' : 'text-gray-900 dark:text-white';
    }
    
    return 'text-gray-900 dark:text-white';
  };

  // Format metric value
  const formatMetric = (metric: string, value: number): string => {
    if (['accuracy', 'precision', 'recall', 'drift_score', 'error_rate'].includes(metric)) {
      return `${(value * 100).toFixed(2)}%`;
    }
    if (metric.includes('latency')) {
      return `${value.toFixed(1)}ms`;
    }
    return value.toFixed(4);
  };

  // Format delta value
  const formatDelta = (metric: string, delta: number): string => {
    const sign = delta > 0 ? '+' : '';
    if (['accuracy', 'precision', 'recall', 'drift_score', 'error_rate'].includes(metric)) {
      return `${sign}${(delta * 100).toFixed(2)}%`;
    }
    if (metric.includes('latency')) {
      return `${sign}${delta.toFixed(1)}ms`;
    }
    return `${sign}${delta.toFixed(4)}`;
  };

  // Get recommendation badge
  const getRecommendationBadge = (rec: string) => {
    switch (rec) {
      case 'PROMOTE_B':
        return (
          <span className="bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400 px-3 py-1 rounded-full text-sm font-medium">
            ✓ Recommend: Promote Model B
          </span>
        );
      case 'KEEP_A':
        return (
          <span className="bg-yellow-100 dark:bg-yellow-900/30 text-yellow-600 dark:text-yellow-400 px-3 py-1 rounded-full text-sm font-medium">
            → Keep Model A
          </span>
        );
      case 'CONTINUE_TESTING':
        return (
          <span className="bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 px-3 py-1 rounded-full text-sm font-medium">
            ⟳ Continue Testing
          </span>
        );
      default:
        return null;
    }
  };

  const metricLabels: Record<string, string> = {
    accuracy: 'Accuracy',
    precision: 'Precision',
    recall: 'Recall',
    latency_p50_ms: 'Latency P50',
    latency_p95_ms: 'Latency P95',
    drift_score: 'Drift Score',
    error_rate: 'Error Rate',
  };

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-gray-900 dark:text-white">Model Comparison</h3>
        <button
          onClick={fetchComparison}
          disabled={loadingState === 'loading' || !modelA || !modelB}
          className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded disabled:opacity-50"
          title="Refresh Comparison"
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

      {/* Model Selectors */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Model A (Current/Prod)
          </label>
          <select
            value={modelA}
            onChange={(e) => setModelA(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Select model...</option>
            {models.map((m) => (
              <option key={m.model_id} value={m.model_id}>
                {m.version} ({m.status})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Model B (Candidate/Canary)
          </label>
          <select
            value={modelB}
            onChange={(e) => setModelB(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Select model...</option>
            {models.map((m) => (
              <option key={m.model_id} value={m.model_id}>
                {m.version} ({m.status})
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-3 mb-4">
          <p className="text-red-600 dark:text-red-400 text-sm">{error}</p>
        </div>
      )}

      {/* Loading State */}
      {loadingState === 'loading' && !comparison && (
        <div className="animate-pulse space-y-3">
          <div className="h-8 bg-gray-200 dark:bg-gray-700 rounded w-1/2 mx-auto" />
          <div className="h-48 bg-gray-200 dark:bg-gray-700 rounded" />
        </div>
      )}

      {/* Empty State */}
      {!comparison && loadingState !== 'loading' && !error && (
        <div className="text-center py-8 text-gray-500 dark:text-gray-400">
          <svg className="w-12 h-12 mx-auto mb-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
          <p>Select two models to compare</p>
        </div>
      )}

      {/* Comparison Table */}
      {comparison && (
        <>
          {/* Recommendation */}
          <div className="flex justify-center mb-4">
            {getRecommendationBadge(comparison.recommendation)}
          </div>

          {/* Metrics Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-700">
                  <th className="text-left py-2 px-3 font-medium text-gray-500 dark:text-gray-400">Metric</th>
                  <th className="text-center py-2 px-3 font-medium text-gray-500 dark:text-gray-400">
                    Model A<br />
                    <span className="text-xs font-normal">{comparison.model_a.version}</span>
                  </th>
                  <th className="text-center py-2 px-3 font-medium text-gray-500 dark:text-gray-400">
                    Model B<br />
                    <span className="text-xs font-normal">{comparison.model_b.version}</span>
                  </th>
                  <th className="text-center py-2 px-3 font-medium text-gray-500 dark:text-gray-400">Delta</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(metricLabels).map(([key, label]) => {
                  const valueA = comparison.model_a[key as keyof ModelMetrics] as number;
                  const valueB = comparison.model_b[key as keyof ModelMetrics] as number;
                  const delta = comparison.delta[key] || 0;
                  
                  return (
                    <tr key={key} className="border-b border-gray-100 dark:border-gray-700/50 hover:bg-gray-50 dark:hover:bg-gray-700/50">
                      <td className="py-2 px-3 text-gray-700 dark:text-gray-300">{label}</td>
                      <td className="py-2 px-3 text-center text-gray-900 dark:text-white">
                        {formatMetric(key, valueA)}
                      </td>
                      <td className="py-2 px-3 text-center text-gray-900 dark:text-white">
                        {formatMetric(key, valueB)}
                      </td>
                      <td className={`py-2 px-3 text-center ${getDeltaClass(key, delta)}`}>
                        {formatDelta(key, delta)}
                      </td>
                    </tr>
                  );
                })}
                <tr className="border-b border-gray-100 dark:border-gray-700/50">
                  <td className="py-2 px-3 text-gray-700 dark:text-gray-300">Samples</td>
                  <td className="py-2 px-3 text-center text-gray-900 dark:text-white">
                    {comparison.model_a.samples.toLocaleString()}
                  </td>
                  <td className="py-2 px-3 text-center text-gray-900 dark:text-white">
                    {comparison.model_b.samples.toLocaleString()}
                  </td>
                  <td className="py-2 px-3 text-center text-gray-500">-</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Action Buttons */}
          {comparison.recommendation === 'PROMOTE_B' && onPromote && (
            <div className="mt-4 flex justify-end">
              <button
                onClick={() => onPromote(comparison.model_b.model_id)}
                className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-medium transition-colors"
              >
                Promote Model B to Production
              </button>
            </div>
          )}

          {/* Timestamp */}
          <div className="text-xs text-gray-500 dark:text-gray-400 mt-3 pt-2 border-t border-gray-100 dark:border-gray-700">
            Compared at: {new Date(comparison.timestamp).toLocaleString()}
          </div>
        </>
      )}
    </div>
  );
}

export default ModelComparisonPanel;

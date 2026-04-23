/**
 * Alert Threshold Configuration Panel
 * ====================================
 * 
 * Configuration form for monitoring alert thresholds.
 * Phase 2 - Canary & Governance Control Component
 * 
 * Features:
 * - Threshold sliders for drift PSI, LLM anomaly, error rate, volatility
 * - Optimistic UI update with rollback on failure
 * - Real-time validation
 */

import { useState, useEffect, useCallback, useRef } from 'react';

// ==============================================================================
// Types
// ==============================================================================

interface Thresholds {
  drift_psi: number;
  llm_anomaly_rate: number;
  error_rate: number;
  volatility_index: number;
  updated_at?: string;
}

type LoadingState = 'idle' | 'loading' | 'saving' | 'success' | 'error';

interface AlertThresholdConfigProps {
  onSave?: (thresholds: Thresholds) => void;
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
// Validation helpers
// ==============================================================================

interface ThresholdMeta {
  label: string;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  description: string;
}

const thresholdMeta: Record<keyof Omit<Thresholds, 'updated_at'>, ThresholdMeta> = {
  drift_psi: {
    label: 'Drift PSI Threshold',
    min: 0.01,
    max: 0.5,
    step: 0.01,
    format: (v) => v.toFixed(2),
    description: 'Population Stability Index threshold. Values above this trigger drift alerts.',
  },
  llm_anomaly_rate: {
    label: 'LLM Anomaly Rate',
    min: 0.01,
    max: 0.2,
    step: 0.01,
    format: (v) => `${(v * 100).toFixed(0)}%`,
    description: 'Maximum acceptable anomaly rate for LLM responses.',
  },
  error_rate: {
    label: 'Error Rate Threshold',
    min: 0.001,
    max: 0.1,
    step: 0.001,
    format: (v) => `${(v * 100).toFixed(1)}%`,
    description: 'Maximum system error rate before alerting.',
  },
  volatility_index: {
    label: 'Volatility Index',
    min: 0.01,
    max: 0.3,
    step: 0.01,
    format: (v) => v.toFixed(2),
    description: 'Maximum ranking volatility before triggering stability alerts.',
  },
};

const defaultThresholds: Thresholds = {
  drift_psi: 0.25,
  llm_anomaly_rate: 0.05,
  error_rate: 0.01,
  volatility_index: 0.15,
};

// ==============================================================================
// Component
// ==============================================================================

export function AlertThresholdConfig({ onSave }: AlertThresholdConfigProps) {
  const [thresholds, setThresholds] = useState<Thresholds>(defaultThresholds);
  const [previousThresholds, setPreviousThresholds] = useState<Thresholds | null>(null);
  const [loadingState, setLoadingState] = useState<LoadingState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [isDirty, setIsDirty] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  
  const abortControllerRef = useRef<AbortController | null>(null);

  // Fetch current thresholds
  const fetchThresholds = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();
    
    setLoadingState('loading');
    setError(null);
    
    try {
      const result = await fetchWithTimeout<Thresholds>(
        `${API_BASE_URL}/api/v1/governance/thresholds`
      );
      
      setThresholds(result);
      setLoadingState('success');
      setIsDirty(false);
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        return;
      }
      
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch thresholds';
      setError(errorMessage);
      setLoadingState('error');
      // Keep default thresholds on error
    }
  }, []);

  // Save thresholds with optimistic update
  const saveThresholds = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();
    
    // Store previous state for rollback
    setPreviousThresholds(thresholds);
    setLoadingState('saving');
    setError(null);
    setSuccessMessage(null);
    
    try {
      const result = await fetchWithTimeout<Thresholds>(
        `${API_BASE_URL}/api/v1/governance/thresholds`,
        {
          method: 'PUT',
          body: JSON.stringify({
            drift_psi: thresholds.drift_psi,
            llm_anomaly_rate: thresholds.llm_anomaly_rate,
            error_rate: thresholds.error_rate,
            volatility_index: thresholds.volatility_index,
          }),
        }
      );
      
      setThresholds(result);
      setLoadingState('success');
      setIsDirty(false);
      setPreviousThresholds(null);
      setSuccessMessage('Thresholds saved successfully');
      
      if (onSave) {
        onSave(result);
      }
      
      // Clear success message after 3s
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        return;
      }
      
      const errorMessage = err instanceof Error ? err.message : 'Failed to save thresholds';
      setError(errorMessage);
      setLoadingState('error');
      
      // Rollback to previous state
      if (previousThresholds) {
        setThresholds(previousThresholds);
        setPreviousThresholds(null);
      }
    }
  }, [thresholds, previousThresholds, onSave]);

  // Reset to defaults
  const resetToDefaults = useCallback(() => {
    setThresholds(defaultThresholds);
    setIsDirty(true);
  }, []);

  // Handle threshold change
  const handleChange = useCallback((key: keyof Omit<Thresholds, 'updated_at'>, value: number) => {
    setThresholds(prev => ({
      ...prev,
      [key]: value,
    }));
    setIsDirty(true);
    setError(null);
    setSuccessMessage(null);
  }, []);

  // Initial load
  useEffect(() => {
    fetchThresholds();
  }, [fetchThresholds]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-gray-900 dark:text-white">Alert Thresholds</h3>
        <button
          onClick={resetToDefaults}
          disabled={loadingState === 'saving'}
          className="text-sm text-blue-600 hover:text-blue-700 dark:text-blue-400 disabled:opacity-50"
        >
          Reset to Defaults
        </button>
      </div>

      {/* Loading State */}
      {loadingState === 'loading' && (
        <div className="animate-pulse space-y-4">
          {[1, 2, 3, 4].map(i => (
            <div key={i}>
              <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-1/3 mb-2" />
              <div className="h-8 bg-gray-200 dark:bg-gray-700 rounded" />
            </div>
          ))}
        </div>
      )}

      {/* Form */}
      {loadingState !== 'loading' && (
        <div className="space-y-5">
          {(Object.keys(thresholdMeta) as Array<keyof Omit<Thresholds, 'updated_at'>>).map(key => {
            const meta = thresholdMeta[key];
            const value = thresholds[key];
            
            return (
              <div key={key}>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
                    {meta.label}
                  </label>
                  <span className="text-sm font-mono text-gray-900 dark:text-white bg-gray-100 dark:bg-gray-700 px-2 py-0.5 rounded">
                    {meta.format(value)}
                  </span>
                </div>
                <input
                  type="range"
                  min={meta.min}
                  max={meta.max}
                  step={meta.step}
                  value={value}
                  onChange={(e) => handleChange(key, parseFloat(e.target.value))}
                  disabled={loadingState === 'saving'}
                  className="w-full h-2 bg-gray-200 dark:bg-gray-700 rounded-lg appearance-none cursor-pointer slider-thumb disabled:opacity-50"
                />
                <div className="flex justify-between text-xs text-gray-400 mt-1">
                  <span>{meta.format(meta.min)}</span>
                  <span className="text-gray-500">{meta.description}</span>
                  <span>{meta.format(meta.max)}</span>
                </div>
              </div>
            );
          })}

          {/* Error Message */}
          {error && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-3">
              <div className="flex items-center">
                <svg className="w-4 h-4 text-red-500 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span className="text-red-600 dark:text-red-400 text-sm">{error}</span>
              </div>
            </div>
          )}

          {/* Success Message */}
          {successMessage && (
            <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-3">
              <div className="flex items-center">
                <svg className="w-4 h-4 text-green-500 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span className="text-green-600 dark:text-green-400 text-sm">{successMessage}</span>
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div className="flex justify-end gap-3 pt-2 border-t border-gray-100 dark:border-gray-700">
            <button
              onClick={fetchThresholds}
              disabled={loadingState === 'saving'}
              className="px-4 py-2 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={saveThresholds}
              disabled={!isDirty || loadingState === 'saving'}
              className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {loadingState === 'saving' && (
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
              )}
              {loadingState === 'saving' ? 'Saving...' : 'Save Thresholds'}
            </button>
          </div>

          {/* Last Updated */}
          {thresholds.updated_at && (
            <div className="text-xs text-gray-500 dark:text-gray-400 text-right">
              Last updated: {new Date(thresholds.updated_at).toLocaleString()}
            </div>
          )}
        </div>
      )}

      {/* Custom Slider Styles */}
      <style>{`
        .slider-thumb::-webkit-slider-thumb {
          -webkit-appearance: none;
          appearance: none;
          width: 16px;
          height: 16px;
          border-radius: 50%;
          background: #3b82f6;
          cursor: pointer;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
        }
        .slider-thumb::-moz-range-thumb {
          width: 16px;
          height: 16px;
          border-radius: 50%;
          background: #3b82f6;
          cursor: pointer;
          border: none;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
        }
      `}</style>
    </div>
  );
}

export default AlertThresholdConfig;

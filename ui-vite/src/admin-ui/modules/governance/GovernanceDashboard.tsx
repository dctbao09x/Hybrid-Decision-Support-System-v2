/**
 * Governance Monitoring Dashboard
 * ================================
 * 
 * Phase 4 - Dashboard Layout Refactor
 * 
 * Responsive grid layout integrating all governance monitoring components:
 * - Score Distribution Histogram
 * - KL Divergence Indicator
 * - Alert Threshold Configuration
 * - Rule Trigger Chart
 * - Ranking Volatility Chart
 * - Ranking Frequency Chart
 * 
 * Layout: 3-column responsive grid with 2-column fallback on medium screens
 */

import React, { useState, Suspense } from 'react';

// ==============================================================================
// Lazy load components for better performance
// ==============================================================================

const ScoreDistributionHistogram = React.lazy(() => 
  import('./ScoreDistributionHistogram').then(m => ({ default: m.ScoreDistributionHistogram }))
);
const AlertThresholdConfig = React.lazy(() => 
  import('./AlertThresholdConfig').then(m => ({ default: m.AlertThresholdConfig }))
);
const RuleTriggerChart = React.lazy(() => 
  import('./RuleTriggerChart').then(m => ({ default: m.RuleTriggerChart }))
);
const RankingVolatilityChart = React.lazy(() => 
  import('./RankingVolatilityChart').then(m => ({ default: m.RankingVolatilityChart }))
);
const RankingFrequencyChart = React.lazy(() => 
  import('./RankingFrequencyChart').then(m => ({ default: m.RankingFrequencyChart }))
);
const KLDivergenceIndicator = React.lazy(() => 
  import('./KLDivergenceIndicator').then(m => ({ default: m.KLDivergenceIndicator }))
);

// ==============================================================================
// Types
// ==============================================================================

interface GovernanceDashboardProps {
  refreshInterval?: number;
  showConfig?: boolean;
}

// ==============================================================================
// Loading Fallback
// ==============================================================================

function WidgetSkeleton({ height = 300 }: { height?: number }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-4 animate-pulse">
      <div className="h-5 bg-gray-200 dark:bg-gray-700 rounded w-1/3 mb-4" />
      <div className="rounded bg-gray-200 dark:bg-gray-700" style={{ height: `${height - 60}px` }} />
    </div>
  );
}

// ==============================================================================
// Alert Banner Component
// ==============================================================================

interface AlertBannerProps {
  alerts: Array<{ type: string; message: string; severity: 'info' | 'warning' | 'critical' }>;
  onDismiss?: (index: number) => void;
}

function AlertBanner({ alerts, onDismiss }: AlertBannerProps) {
  if (alerts.length === 0) return null;
  
  const severityClasses = {
    info: 'bg-blue-100 dark:bg-blue-900/30 border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-400',
    warning: 'bg-yellow-100 dark:bg-yellow-900/30 border-yellow-200 dark:border-yellow-800 text-yellow-700 dark:text-yellow-400',
    critical: 'bg-red-100 dark:bg-red-900/30 border-red-200 dark:border-red-800 text-red-700 dark:text-red-400',
  };
  
  return (
    <div className="space-y-2 mb-4">
      {alerts.map((alert, idx) => (
        <div 
          key={idx}
          className={`flex items-center justify-between border rounded-lg px-4 py-2 ${severityClasses[alert.severity]}`}
        >
          <div className="flex items-center gap-2">
            {alert.severity === 'critical' && (
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            )}
            {alert.severity === 'warning' && (
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            )}
            <span className="text-sm font-medium">{alert.message}</span>
          </div>
          {onDismiss && (
            <button
              onClick={() => onDismiss(idx)}
              className="p-1 hover:bg-black/10 rounded"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

// ==============================================================================
// Main Dashboard Component
// ==============================================================================

export function GovernanceDashboard({ 
  refreshInterval = 60000,
  showConfig = true 
}: GovernanceDashboardProps) {
  const [alerts, setAlerts] = useState<Array<{ type: string; message: string; severity: 'info' | 'warning' | 'critical' }>>([]);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  
  const handleDismissAlert = (index: number) => {
    setAlerts(prev => prev.filter((_, i) => i !== index));
  };
  
  const handleRefreshAll = () => {
    setLastRefresh(new Date());
    // Components will auto-refresh based on their intervals
  };
  
  return (
    <div className="p-4 bg-gray-50 dark:bg-gray-900 min-h-screen">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Governance Dashboard</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Real-time monitoring of scoring governance and distribution drift
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500">
            Last refresh: {lastRefresh.toLocaleTimeString()}
          </span>
          <button
            onClick={handleRefreshAll}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg flex items-center gap-1.5 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Refresh All
          </button>
        </div>
      </div>
      
      {/* Alert Banner */}
      <AlertBanner alerts={alerts} onDismiss={handleDismissAlert} />
      
      {/* Status Summary Bar */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-3 mb-4">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-4">
            <Suspense fallback={<span className="text-xs text-gray-500">Loading...</span>}>
              <KLDivergenceIndicator compactMode refreshInterval={refreshInterval} />
            </Suspense>
          </div>
          <div className="flex items-center gap-3 text-xs text-gray-500">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 bg-green-500 rounded-full" />
              Healthy
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 bg-yellow-500 rounded-full" />
              Warning
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 bg-red-500 rounded-full" />
              Alert
            </span>
          </div>
        </div>
      </div>
      
      {/* Main Grid - Responsive 3-column layout */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        
        {/* Score Distribution - Full width on large screens */}
        <div className="xl:col-span-2">
          <Suspense fallback={<WidgetSkeleton height={400} />}>
            <ScoreDistributionHistogram refreshInterval={refreshInterval} />
          </Suspense>
        </div>
        
        {/* KL Divergence - Side panel */}
        <div>
          <Suspense fallback={<WidgetSkeleton height={220} />}>
            <KLDivergenceIndicator refreshInterval={refreshInterval} />
          </Suspense>
          
          {/* Alert Thresholds Config under KL Indicator */}
          {showConfig && (
            <div className="mt-4">
              <Suspense fallback={<WidgetSkeleton height={320} />}>
                <AlertThresholdConfig />
              </Suspense>
            </div>
          )}
        </div>
        
        {/* Rule Trigger Chart */}
        <div className="md:col-span-2 xl:col-span-2">
          <Suspense fallback={<WidgetSkeleton height={300} />}>
            <RuleTriggerChart refreshInterval={refreshInterval} height={300} />
          </Suspense>
        </div>
        
        {/* Ranking Volatility */}
        <div>
          <Suspense fallback={<WidgetSkeleton height={280} />}>
            <RankingVolatilityChart refreshInterval={refreshInterval} height={280} />
          </Suspense>
        </div>
        
        {/* Ranking Frequency - Full width at bottom */}
        <div className="md:col-span-2 xl:col-span-3">
          <Suspense fallback={<WidgetSkeleton height={280} />}>
            <RankingFrequencyChart refreshInterval={refreshInterval} height={280} highlightTopN={5} />
          </Suspense>
        </div>
        
      </div>
      
      {/* Footer */}
      <div className="mt-4 pt-3 border-t border-gray-200 dark:border-gray-700 text-xs text-gray-500 dark:text-gray-400 text-center">
        Governance Monitoring Dashboard • Auto-refresh: {refreshInterval / 1000}s • 
        Components: 6/6 Active
      </div>
    </div>
  );
}

export default GovernanceDashboard;

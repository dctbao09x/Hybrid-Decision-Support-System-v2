/**
 * useFeedback.ts
 * React hook for managing feedback admin panel state
 * 
 * Features:
 * - Real-time data fetching with AbortController
 * - Debounced filter updates (400ms)
 * - Automatic polling (15s silent refresh)
 * - Pagination (limit 50, offset)
 * - CSV export
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import { getFeedback, getStats, exportCSV } from '../../../services/feedbackApi';
import type { FeedbackAdminItem, FeedbackAdminStats, FeedbackQueryParams } from '../../../services/feedbackApi';

const DEBOUNCE_DELAY_MS = 400;
const POLL_INTERVAL_MS = 15000; // 15 seconds

export function useFeedback() {
  // Data state
  const [rows, setRows] = useState<FeedbackAdminItem[]>([]);
  const [stats, setStats] = useState<FeedbackAdminStats | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);

  // UI state
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters state
  const [filters, setFilters] = useState<FeedbackQueryParams>({
    status: '',
    source: '',
    from: '',
    to: '',
  });

  // Refs for cleanup
  const abortController = useRef<AbortController | null>(null);
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const didFirstLoad = useRef(false);

  /**
   * Core data loading function.
   */
  const reload = useCallback(async (silent = false) => {
    if (!silent) {
      setLoading(true);
      setError(null);
    }

    // Cancel previous request
    abortController.current?.abort();
    abortController.current = new AbortController();

    try {
      const limit = 50;
      const offset = page * limit;

      // Fetch feedback list
      const listResponse = await getFeedback({
        ...filters,
        limit,
        offset,
        signal: abortController.current.signal,
      });

      setRows(listResponse.items);
      setTotal(listResponse.total);

      // Fetch stats
      const statsResponse = await getStats(abortController.current.signal);
      setStats(statsResponse);

      if (!silent) {
        setLoading(false);
      }
    } catch (err) {
      if (err instanceof Error && (err.message.includes('aborted') || err.message.includes('cancelled'))) {
        // Request was cancelled, ignore
        return;
      }

      const message = err instanceof Error ? err.message : 'Failed to load feedback';
      setError(message);

      if (!silent) {
        setLoading(false);
      }
    }
  }, [filters, page]);

  /**
   * Export feedback as CSV.
   */
  const exportCsv = useCallback(async () => {
    try {
      const csv = await exportCSV({
        status: filters.status,
        source: filters.source,
        from: filters.from,
        to: filters.to,
      });

      // Create blob and download
      const blob = new Blob([csv], { type: 'text/csv' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `feedback-export-${Date.now()}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      // Toast notification would go here in production
      // console.log('✓ Exported feedback');
    } catch (err) {
      console.error('Export failed:', err);
    }
  }, [filters]);

  // Debounced filter/page changes, includes first load once
  useEffect(() => {
    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current);
    }

    const delay = didFirstLoad.current ? DEBOUNCE_DELAY_MS : 0;

    debounceTimer.current = setTimeout(() => {
      didFirstLoad.current = true;
      reload(false); // Not silent - show loading state
    }, delay);

    return () => {
      if (debounceTimer.current) {
        clearTimeout(debounceTimer.current);
      }
    };
  }, [filters, page, reload]);

  // Auto-refresh polling (silent)
  useEffect(() => {
    const startPolling = () => {
      if (pollTimer.current) {
        clearInterval(pollTimer.current);
      }

      pollTimer.current = setInterval(() => {
        reload(true); // Silent reload
      }, POLL_INTERVAL_MS);
    };

    startPolling();

    return () => {
      if (pollTimer.current) {
        clearInterval(pollTimer.current);
      }
    };
  }, [reload]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortController.current?.abort();
      if (debounceTimer.current) {
        clearTimeout(debounceTimer.current);
      }
      if (pollTimer.current) {
        clearInterval(pollTimer.current);
      }
    };
  }, []);

  return {
    // Data
    rows,
    stats,
    total,
    page,

    // UI
    loading,
    error,
    filters,

    // Methods
    reload,
    setPage,
    setFilters,
    exportCsv,
  };
}

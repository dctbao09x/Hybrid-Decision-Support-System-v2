import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';
import { markFeatureAvailability } from '../../services/featureFlags';
import { crawlersReducer, initialCrawlersState } from './store';
import { loadCrawlerJobs, loadCrawlerLogs, runCrawler, stopCrawler } from './service';

const JOB_POLL_MS = 15000;
const LOG_POLL_MS = 5000;
const LOADING_GUARD_MS = 8000;

export function useCrawlersModule() {
  const [state, dispatch] = useReducer(crawlersReducer, initialCrawlersState);
  const jobRequestInFlightRef = useRef(false);
  const logRequestInFlightRef = useRef(false);
  const loadingTimeoutRef = useRef<number | null>(null);

  const armLoadingGuard = useCallback(() => {
    if (loadingTimeoutRef.current) {
      window.clearTimeout(loadingTimeoutRef.current);
    }
    loadingTimeoutRef.current = window.setTimeout(() => {
      dispatch({ type: 'set-loading', payload: false });
      dispatch({ type: 'set-error', payload: `Loading timed out after ${LOADING_GUARD_MS}ms` });
    }, LOADING_GUARD_MS);
  }, []);

  const clearLoadingGuard = useCallback(() => {
    if (loadingTimeoutRef.current) {
      window.clearTimeout(loadingTimeoutRef.current);
      loadingTimeoutRef.current = null;
    }
  }, []);

  const refreshJobs = useCallback(async () => {
    if (jobRequestInFlightRef.current) return;
    jobRequestInFlightRef.current = true;
    dispatch({ type: 'set-loading', payload: true });
    armLoadingGuard();
    try {
      const jobs = await loadCrawlerJobs();
      dispatch({ type: 'set-jobs', payload: jobs });
      dispatch({ type: 'set-error', payload: '' });
      markFeatureAvailability('crawlers', true);
    } catch (error) {
      // Keep module visible but surface the error inside the view.
      // Only mark unavailable on explicit 404 (route does not exist).
      const msg = error instanceof Error ? error.message : 'Failed to load crawler jobs';
      dispatch({ type: 'set-error', payload: msg });
      const is404 = msg.includes('404') || msg.includes('Not Found');
      if (is404) markFeatureAvailability('crawlers', false);
    } finally {
      clearLoadingGuard();
      jobRequestInFlightRef.current = false;
      dispatch({ type: 'set-loading', payload: false });
    }
  }, [armLoadingGuard, clearLoadingGuard]);

  const refreshLogs = useCallback(async (site: string) => {
    if (!site) return;
    if (logRequestInFlightRef.current) return;
    logRequestInFlightRef.current = true;
    try {
      const logs = await loadCrawlerLogs(site);
      dispatch({ type: 'set-site-logs', payload: { site, logs } });
    } catch (error) {
      dispatch({ type: 'set-error', payload: error instanceof Error ? error.message : 'Unable to load crawler logs' });
    } finally {
      logRequestInFlightRef.current = false;
    }
  }, []);

  useEffect(() => {
    void refreshJobs();
    const timer = window.setInterval(() => void refreshJobs(), JOB_POLL_MS);
    return () => {
      window.clearInterval(timer);
      clearLoadingGuard();
    };
  }, [refreshJobs]);

  useEffect(() => {
    if (!state.selectedSite) return;
    void refreshLogs(state.selectedSite);
    const timer = window.setInterval(() => void refreshLogs(state.selectedSite), LOG_POLL_MS);
    return () => window.clearInterval(timer);
  }, [refreshLogs, state.selectedSite]);

  const runSelectedCrawler = useCallback(async () => {
    if (!state.selectedSite) return;
    try {
      await runCrawler(state.selectedSite);
      await refreshJobs();
      await refreshLogs(state.selectedSite);
      dispatch({ type: 'set-error', payload: '' });
    } catch (error) {
      const msg = error instanceof Error ? error.message
        : (typeof (error as { message?: string })?.message === 'string'
          ? (error as { message: string }).message
          : 'Unable to run crawler');
      dispatch({ type: 'set-error', payload: msg });
    }
  }, [refreshJobs, refreshLogs, state.selectedSite]);

  const stopSelectedCrawler = useCallback(async () => {
    if (!state.selectedSite) return;
    try {
      await stopCrawler(state.selectedSite);
      await refreshJobs();
      dispatch({ type: 'set-error', payload: '' });
    } catch (error) {
      const msg = error instanceof Error ? error.message
        : (typeof (error as { message?: string })?.message === 'string'
          ? (error as { message: string }).message
          : 'Unable to stop crawler');
      dispatch({ type: 'set-error', payload: msg });
    }
  }, [refreshJobs, state.selectedSite]);

  const selectedLogs = useMemo(() => state.logs[state.selectedSite] || [], [state.logs, state.selectedSite]);

  return {
    state,
    selectedLogs,
    refreshJobs,
    refreshLogs,
    runSelectedCrawler,
    stopSelectedCrawler,
    setSelectedSite: (site: string) => dispatch({ type: 'set-selected-site', payload: site }),
    setScheduleOpen: (open: boolean) => dispatch({ type: 'set-schedule-open', payload: open }),
    dismissError: () => dispatch({ type: 'set-error', payload: '' }),
  };
}

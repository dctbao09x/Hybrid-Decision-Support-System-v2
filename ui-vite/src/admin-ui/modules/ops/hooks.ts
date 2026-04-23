import { useCallback, useEffect, useReducer, useRef } from 'react';
import { markFeatureAvailability } from '../../services/featureFlags';
import { useAdminStore } from '../../store/AdminStoreProvider';
import {
  clearOpsCache,
  loadOpsSnapshot,
  restartService,
  triggerOpsBackup,
  triggerRetention,
} from './service';
import { initialOpsState, opsReducer } from './store';

const POLL_MS = 20000;
const LOADING_GUARD_MS = 10000;

export function useOpsModule() {
  const [state, dispatch] = useReducer(opsReducer, initialOpsState);
  const { pushNotification } = useAdminStore();
  const requestInFlightRef = useRef(false);
  const loadingTimeoutRef = useRef<number | null>(null);

  const armLoadingGuard = useCallback(() => {
    if (loadingTimeoutRef.current) window.clearTimeout(loadingTimeoutRef.current);
    loadingTimeoutRef.current = window.setTimeout(() => {
      dispatch({ type: 'set-loading', payload: false });
      dispatch({ type: 'set-error', payload: `Loading timed out after ${LOADING_GUARD_MS / 1000}s` });
    }, LOADING_GUARD_MS);
  }, []);

  const clearLoadingGuard = useCallback(() => {
    if (loadingTimeoutRef.current) {
      window.clearTimeout(loadingTimeoutRef.current);
      loadingTimeoutRef.current = null;
    }
  }, []);

  const refresh = useCallback(async () => {
    if (requestInFlightRef.current) return;
    requestInFlightRef.current = true;
    dispatch({ type: 'set-loading', payload: true });
    armLoadingGuard();
    try {
      const snapshot = await loadOpsSnapshot();
      dispatch({ type: 'set-snapshot', payload: snapshot });
      dispatch({ type: 'set-error', payload: '' });
      markFeatureAvailability('ops', true);
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Failed to load ops snapshot';
      dispatch({ type: 'set-error', payload: msg });
      markFeatureAvailability('ops', false);
    } finally {
      clearLoadingGuard();
      requestInFlightRef.current = false;
      dispatch({ type: 'set-loading', payload: false });
    }
  }, [armLoadingGuard, clearLoadingGuard]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => {
      window.clearInterval(timer);
      clearLoadingGuard();
    };
  }, [refresh, clearLoadingGuard]);

  // ── Actions ────────────────────────────────────────────────────────────────

  const createBackup = useCallback(async (label?: string) => {
    dispatch({ type: 'set-action-busy', payload: 'backup' });
    try {
      const result = await triggerOpsBackup(label);
      const msg = result?.message ?? result?.error ?? 'Backup complete';
      pushNotification({ level: result?.error ? 'warning' : 'info', message: `Backup: ${msg}` });
      dispatch({ type: 'set-action-result', payload: msg });
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Backup failed';
      pushNotification({ level: 'warning', message: msg });
      dispatch({ type: 'set-error', payload: msg });
    } finally {
      dispatch({ type: 'set-action-busy', payload: '' });
    }
  }, [pushNotification]);

  const runRetention = useCallback(async (dryRun = true) => {
    dispatch({ type: 'set-action-busy', payload: 'retention' });
    try {
      const result = await triggerRetention(dryRun);
      const msg = dryRun ? 'Retention preview OK' : 'Retention enforced';
      pushNotification({ level: 'info', message: `${msg}: ${JSON.stringify(result).slice(0, 80)}` });
      dispatch({ type: 'set-action-result', payload: JSON.stringify(result, null, 2) });
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Retention failed';
      pushNotification({ level: 'warning', message: msg });
    } finally {
      dispatch({ type: 'set-action-busy', payload: '' });
    }
  }, [pushNotification]);

  const clearCache = useCallback(async (cacheType: string) => {
    dispatch({ type: 'set-action-busy', payload: `cache-${cacheType}` });
    try {
      const result = await clearOpsCache(cacheType);
      pushNotification({ level: 'info', message: `Cache '${cacheType}' cleared — ${result.entries_removed} entries removed` });
      void refresh();
    } catch (err) {
      const msg = err instanceof Error ? err.message : `Failed to clear cache '${cacheType}'`;
      pushNotification({ level: 'warning', message: msg });
    } finally {
      dispatch({ type: 'set-action-busy', payload: '' });
    }
  }, [pushNotification, refresh]);

  const triggerRestart = useCallback(async (name: string) => {
    dispatch({ type: 'set-action-busy', payload: `restart-${name}` });
    try {
      await restartService(name);
      pushNotification({ level: 'info', message: `Service '${name}' restart queued` });
    } catch (err) {
      const msg = err instanceof Error ? err.message : `Failed to restart '${name}'`;
      pushNotification({ level: 'warning', message: msg });
    } finally {
      dispatch({ type: 'set-action-busy', payload: '' });
    }
  }, [pushNotification]);

  return { state, refresh, createBackup, runRetention, clearCache, triggerRestart };
}

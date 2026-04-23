import { useCallback, useEffect, useReducer, useRef } from 'react';
import { markFeatureAvailability } from '../../services/featureFlags';
import { loadGovernanceDashboard } from './service';
import { governanceReducer, initialGovernanceState } from './store';

const POLL_MS = 30000;
const LOADING_GUARD_MS = 8000;

export function useGovernanceModule() {
  const [state, dispatch] = useReducer(governanceReducer, initialGovernanceState);
  const requestInFlightRef = useRef(false);
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

  const refresh = useCallback(async () => {
    if (requestInFlightRef.current) return;
    requestInFlightRef.current = true;
    dispatch({ type: 'set-loading', payload: true });
    armLoadingGuard();
    try {
      const dashboard = await loadGovernanceDashboard();
      dispatch({ type: 'set-dashboard', payload: dashboard });
      dispatch({ type: 'set-error', payload: '' });
      markFeatureAvailability('governance', true);
    } catch (error) {
      dispatch({ type: 'set-error', payload: error instanceof Error ? error.message : 'Failed to load governance dashboard' });
      markFeatureAvailability('governance', false);
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
  }, [refresh]);

  return { state, refresh };
}

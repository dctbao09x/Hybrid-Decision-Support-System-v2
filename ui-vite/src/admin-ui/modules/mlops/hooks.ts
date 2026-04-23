import { useCallback, useEffect, useReducer } from 'react';
import { markFeatureAvailability } from '../../services/featureFlags';
import { loadMLOpsHealth } from './service';
import { initialMLOpsState, mlopsReducer } from './store';

export function useMLOpsModule() {
  const [state, dispatch] = useReducer(mlopsReducer, initialMLOpsState);

  const refresh = useCallback(async () => {
    dispatch({ type: 'set-loading', payload: true });
    try {
      const health = await loadMLOpsHealth();
      dispatch({ type: 'set-health', payload: health });
      dispatch({ type: 'set-error', payload: '' });
      markFeatureAvailability('mlops', true);
    } catch (error) {
      dispatch({ type: 'set-error', payload: error instanceof Error ? error.message : 'Failed to load MLOps health' });
      markFeatureAvailability('mlops', false);
    } finally {
      dispatch({ type: 'set-loading', payload: false });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { state, refresh };
}

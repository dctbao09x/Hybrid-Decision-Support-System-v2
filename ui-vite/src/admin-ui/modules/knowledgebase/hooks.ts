import { useCallback, useEffect, useReducer } from 'react';
import { markFeatureAvailability } from '../../services/featureFlags';
import { loadKBHealth } from './service';
import { initialKBState, kbReducer } from './store';

export function useKnowledgeBaseModule() {
  const [state, dispatch] = useReducer(kbReducer, initialKBState);

  const refresh = useCallback(async () => {
    dispatch({ type: 'set-loading', payload: true });
    try {
      const health = await loadKBHealth();
      dispatch({ type: 'set-health', payload: health });
      dispatch({ type: 'set-error', payload: '' });
      markFeatureAvailability('knowledgebase', true);
    } catch (error) {
      dispatch({ type: 'set-error', payload: error instanceof Error ? error.message : 'Failed to load KB health' });
      markFeatureAvailability('knowledgebase', false);
    } finally {
      dispatch({ type: 'set-loading', payload: false });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { state, refresh };
}

import { isFeatureEnabled } from '../../services/featureFlags';
import { useOpsModule } from './hooks';
import { OpsView } from './View';

export function OpsContainer() {
  const enabled = isFeatureEnabled('ops');
  const { state, refresh, createBackup, runRetention, clearCache, triggerRestart } = useOpsModule();

  if (!enabled) {
    return (
      <section className="admin-card">
        <h3>Ops module disabled</h3>
        <p>Feature flag disabled or backend health check failed.</p>
      </section>
    );
  }

  return (
    <OpsView
      snapshot={state.snapshot}
      isLoading={state.isLoading}
      error={state.error}
      actionBusy={state.actionBusy}
      onRefresh={() => void refresh()}
      onBackup={(label) => void createBackup(label)}
      onRetention={(dry) => void runRetention(dry)}
      onClearCache={(t) => void clearCache(t)}
      onRestartService={(n) => void triggerRestart(n)}
    />
  );
}

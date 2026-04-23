import { isFeatureEnabled } from '../../services/featureFlags';
import { useMLOpsModule } from './hooks';
import { MLOpsView } from './View';

export function MLOpsContainer() {
  const enabled = isFeatureEnabled('mlops');
  const { state, refresh } = useMLOpsModule();

  if (!enabled) {
    return (
      <section className="admin-card">
        <h3>MLOps module disabled</h3>
        <p>Feature flag disabled or backend health check failed.</p>
      </section>
    );
  }

  return (
    <MLOpsView
      health={state.health}
      isLoading={state.isLoading}
      error={state.error}
      onRefresh={() => void refresh()}
    />
  );
}

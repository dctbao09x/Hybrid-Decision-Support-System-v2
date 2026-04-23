import { isFeatureEnabled } from '../../services/featureFlags';
import { useGovernanceModule } from './hooks';
import { GovernanceView } from './View';

export function GovernanceContainer() {
  const enabled = isFeatureEnabled('governance');
  const { state, refresh } = useGovernanceModule();

  if (!enabled) {
    return (
      <section className="admin-card">
        <h3>Governance module disabled</h3>
        <p>Feature flag disabled or backend health check failed.</p>
      </section>
    );
  }

  return (
    <GovernanceView
      dashboard={state.dashboard}
      isLoading={state.isLoading}
      error={state.error}
      onRefresh={() => void refresh()}
    />
  );
}

import { isFeatureEnabled } from '../../services/featureFlags';
import { useKnowledgeBaseModule } from './hooks';
import { KnowledgeBaseView } from './View';

export function KnowledgeBaseContainer() {
  const enabled = isFeatureEnabled('knowledgebase');
  const { state, refresh } = useKnowledgeBaseModule();

  if (!enabled) {
    return (
      <section className="admin-card">
        <h3>Knowledge Base module disabled</h3>
        <p>Feature flag disabled or backend health check failed.</p>
      </section>
    );
  }

  return (
    <KnowledgeBaseView
      health={state.health}
      isLoading={state.isLoading}
      error={state.error}
      onRefresh={() => void refresh()}
    />
  );
}

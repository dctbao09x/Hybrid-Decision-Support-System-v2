import { ModuleWorkspace } from '../../shared/ModuleWorkspace';
import KBAdmin from '../../../pages/Admin/KnowledgeBase/KBAdmin.jsx';
import type { KBHealth } from './service';

interface KnowledgeBaseViewProps {
  health: KBHealth | null;
  isLoading: boolean;
  error: string;
  onRefresh: () => void;
}

export function KnowledgeBaseView({ health, isLoading, error, onRefresh }: KnowledgeBaseViewProps) {
  return (
    <ModuleWorkspace title="Knowledge Base" subtitle="Recovered dynamic KB admin workflows">
      <div className="admin-card" data-testid="kb-health-card">
        <h3>Knowledge Base Health</h3>
        <button type="button" className="admin-nav-link" onClick={onRefresh} disabled={isLoading}>Refresh</button>
        <p>Status: {health?.status || 'unknown'}</p>
        <p>Timestamp: {health?.timestamp || '-'}</p>
      </div>
      {error && <div className="admin-context-help" role="alert">{error}</div>}
      <KBAdmin />
    </ModuleWorkspace>
  );
}

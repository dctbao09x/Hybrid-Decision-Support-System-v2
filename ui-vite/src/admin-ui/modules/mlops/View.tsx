import { ModuleWorkspace } from '../../shared/ModuleWorkspace';
import MLOpsAdmin from '../../../pages/Admin/MLOps/MLOpsAdmin.jsx';
import type { MLOpsHealth } from './service';

interface MLOpsViewProps {
  health: MLOpsHealth | null;
  isLoading: boolean;
  error: string;
  onRefresh: () => void;
}

export function MLOpsView({ health, isLoading, error, onRefresh }: MLOpsViewProps) {
  return (
    <ModuleWorkspace title="MLOps Panel" subtitle="Recovered dynamic lifecycle console">
      <div className="admin-card" data-testid="mlops-health-card">
        <h3>Service Health</h3>
        <button type="button" className="admin-nav-link" onClick={onRefresh} disabled={isLoading}>Refresh</button>
        <p>Status: {health?.status || 'unknown'}</p>
        <p>Timestamp: {health?.timestamp || '-'}</p>
      </div>
      {error && <div className="admin-context-help" role="alert">{error}</div>}
      <MLOpsAdmin />
    </ModuleWorkspace>
  );
}

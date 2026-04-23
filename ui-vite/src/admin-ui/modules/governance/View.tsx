import { ModuleWorkspace } from '../../shared/ModuleWorkspace';
import GovernancePanel from '../../../pages/Admin/Governance/index.jsx';

interface GovernanceViewProps {
  dashboard: Record<string, unknown> | null;
  isLoading: boolean;
  error: string;
  onRefresh: () => void;
}

export function GovernanceView({ dashboard, isLoading, error, onRefresh }: GovernanceViewProps) {
  const dashboardObj = (dashboard ?? {}) as {
    status?: string;
    timestamp?: string;
    aggregator?: {
      realtime?: {
        counts?: {
          total?: number;
          success?: number;
          error?: number;
          timeout?: number;
        };
      };
    };
  };

  const counts = dashboardObj.aggregator?.realtime?.counts;

  return (
    <ModuleWorkspace title="Governance Panel" subtitle="Recovered dynamic governance workflows">
      <div className="admin-card" data-testid="governance-health-card">
        <h3>Dashboard Health</h3>
        <div className="admin-card-toolbar">
          <button type="button" className="admin-nav-link" onClick={onRefresh} disabled={isLoading}>Refresh</button>
        </div>
        <div className="admin-governance-health">
          <div className="admin-governance-metrics">
            <div className="admin-governance-metric">
              <span className="admin-governance-metric-label">Status</span>
              <strong className="admin-governance-metric-value">{dashboardObj.status || 'unknown'}</strong>
            </div>
            <div className="admin-governance-metric">
              <span className="admin-governance-metric-label">Total</span>
              <strong className="admin-governance-metric-value">{counts?.total ?? 0}</strong>
            </div>
            <div className="admin-governance-metric">
              <span className="admin-governance-metric-label">Success</span>
              <strong className="admin-governance-metric-value">{counts?.success ?? 0}</strong>
            </div>
            <div className="admin-governance-metric">
              <span className="admin-governance-metric-label">Errors</span>
              <strong className="admin-governance-metric-value">{counts?.error ?? 0}</strong>
            </div>
            <div className="admin-governance-metric">
              <span className="admin-governance-metric-label">Timeout</span>
              <strong className="admin-governance-metric-value">{counts?.timeout ?? 0}</strong>
            </div>
            <div className="admin-governance-metric">
              <span className="admin-governance-metric-label">Updated</span>
              <strong className="admin-governance-metric-value">{dashboardObj.timestamp || 'N/A'}</strong>
            </div>
          </div>

          <details className="admin-governance-json">
            <summary>Raw dashboard payload</summary>
            <pre className="admin-json admin-json--compact">{JSON.stringify(dashboard || {}, null, 2)}</pre>
          </details>
        </div>
      </div>
      {error && <div className="admin-context-help" role="alert">{error}</div>}
      <GovernancePanel />
    </ModuleWorkspace>
  );
}

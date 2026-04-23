import { useNavigate } from 'react-router-dom';
import { ModuleWorkspace } from '../shared/ModuleWorkspace';
import { LiveDashboard, CommandControlPanel } from '../modules/liveops';

export function DashboardWorkspace() {
  const navigate = useNavigate();

  return (
    <ModuleWorkspace title="Admin Dashboard" subtitle="Central control panel for AI Career Platform">
      {/* Live Operations Widgets */}
      <section className="mb-8">
        <LiveDashboard onNavigate={(path) => navigate(path)} />
      </section>

      {/* Command Control Panel */}
      <section className="mb-8">
        <div style={{ marginBottom: '12px' }}>
          <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 700, color: '#c8a55a', letterSpacing: '0.04em' }}>Command Control Panel</h2>
        </div>
        <CommandControlPanel />
      </section>

      {/* Quick Info Cards */}
      <div className="admin-grid-cards">
        <article className="admin-card">
          <h3>Recent Alerts</h3>
          <p>Critical actions requiring attention.</p>
        </article>
        <article className="admin-card">
          <h3>Pending Approvals</h3>
          <p>Governance and release tasks.</p>
        </article>
      </div>
    </ModuleWorkspace>
  );
}
